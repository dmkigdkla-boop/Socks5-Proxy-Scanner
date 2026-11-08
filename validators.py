"""
代理验证器模块
"""

import asyncio
import aiohttp
import time
import logging
import sys
from typing import List, Dict
from aiohttp_socks import ProxyConnector
from tqdm.asyncio import tqdm # 引入tqdm


class ProxyValidator:
    """代理验证器"""
    
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.semaphore = asyncio.Semaphore(config.max_concurrency)
        # IP-API 速率限制保护 (45次/分钟 → 40次/分钟安全值)
        self.geo_semaphore = asyncio.Semaphore(40)
        
    async def validate_proxies(self, proxies: List[str]) -> List[Dict]:
        """验证代理列表"""
        if not proxies:
            return []
        
        self.logger.info(f"开始验证 {len(proxies)} 个代理")
        
        tasks = [self._validate_single_proxy(proxy) for proxy in proxies]
        all_results = []  # 改为保存所有结果

        # 使用 asyncio.as_completed 和 tqdm 手动处理进度
        use_tqdm = sys.stdout.isatty()
        iterable = asyncio.as_completed(tasks)
        
        # 进度跟踪
        processed = 0
        total = len(proxies)
        
        if use_tqdm:
            pbar = tqdm(total=total, desc="验证代理", unit="个")
            
        for future in iterable:
            try:
                result = await future
                # 保存所有结果（成功和失败的）
                all_results.append(result)
                processed += 1
                
                # 在非终端环境（如GitHub Actions）中，每1000个打印一次进度
                if not use_tqdm and processed % 1000 == 0:
                    valid_count = len([r for r in all_results if r and r.get('is_valid')])
                    self.logger.info(f"🔄 进度: {processed}/{total} 已验证 ({processed*100//total}%), 有效: {valid_count}")
                    
            except Exception as e:
                # 代理验证过程中可能会抛出各种异常 (e.g., connection errors)
                # 我们在这里捕获它们，记录日志，然后继续处理下一个
                self.logger.debug(f"代理验证失败: {e}")
                processed += 1
            finally:
                if use_tqdm:
                    pbar.update(1)
        
        if use_tqdm:
            pbar.close()
        
        # 统计有效代理
        valid_proxies = [r for r in all_results if r and r.get('is_valid')]
        self.logger.info(f"验证完成，{len(valid_proxies)}/{len(proxies)} 个代理有效")
        
        # 应用国家白名单过滤
        if self.config.target_countries:
            filtered_proxies = self._filter_by_country(valid_proxies)
            self.logger.info(f"国家白名单过滤后，{len(filtered_proxies)}/{len(valid_proxies)} 个代理保留")
            # 返回所有结果：过滤后的成功 + 所有失败
            failed_results = [r for r in all_results if r and not r.get('is_valid')]
            return filtered_proxies + failed_results
        
        return all_results  # 返回所有结果（包括None的会被过滤）
    
    def _filter_by_country(self, proxies: List[Dict]) -> List[Dict]:
        """根据国家白名单过滤代理"""
        filtered = []
        target_countries = [country.lower() for country in self.config.target_countries]
        
        for proxy in proxies:
            country = proxy.get('country', 'Unknown').lower()
            city = proxy.get('city', 'Unknown')
            
            # 检查国家是否在白名单中
            if country in target_countries:
                filtered.append(proxy)
            else:
                # 检查国家别名
                country_found = False
                for alias, full_name in getattr(self.config, 'country_aliases', {}).items():
                    if country == full_name.lower() and full_name.lower() in target_countries:
                        filtered.append(proxy)
                        country_found = True
                        break
                
                if not country_found:
                    self.logger.debug(f"代理 {proxy['proxy']} 被过滤（国家: {country}, 城市: {city}）")
        
        return filtered
    
    async def _validate_single_proxy(self, proxy: str) -> Dict:
        """验证单个未标注协议的代理，并记录实际可用协议。"""
        async with self.semaphore:
            try:
                ip, port = proxy.split(':')
                port = int(port)
            except ValueError:
                return None

            errors = []
            # 公开源通常不标注协议。短探测避免把每个失效地址的等待时间扩大三倍。
            for protocol in ('socks5', 'http', 'https'):
                try:
                    result = await self._validate_with_protocol(proxy, ip, port, protocol)
                    if result:
                        return result
                except Exception as e:
                    errors.append(f'{protocol}: {e}')

            return {
                'proxy': proxy,
                'ip': ip,
                'port': port,
                'is_valid': False,
                'error': '; '.join(errors) or 'No supported proxy protocol'
            }

    async def _validate_with_protocol(self, proxy: str, ip: str, port: int, protocol: str) -> Dict:
        """使用一个确定的协议探测代理。"""
        # 对无响应地址快速失败；仍允许后续协议继续探测。
        probe_timeout = min(float(self.config.timeout), 3.0)
        timeout = aiohttp.ClientTimeout(total=probe_timeout, sock_connect=min(2.5, probe_timeout))
        proxy_url = f'{protocol}://{proxy}'
        session_kwargs = {'timeout': timeout}
        request_kwargs = {}

        if protocol == 'socks5':
            session_kwargs['connector'] = ProxyConnector.from_url(proxy_url)
        else:
            request_kwargs['proxy'] = proxy_url

        start_time = time.time()
        async with aiohttp.ClientSession(**session_kwargs) as session:
            test_url = self.config.test_urls[0]
            async with session.get(test_url, **request_kwargs) as response:
                if response.status != 200:
                    raise RuntimeError(f'HTTP {response.status}')

            response_time = time.time() - start_time
            try:
                geo_info = await self._get_geo_info(session, request_kwargs.get('proxy'))
            except Exception as e:
                self.logger.debug(f"获取地理位置失败 (非致命): {e}")
                geo_info = {}

            return {
                'proxy': proxy,
                'ip': ip,
                'port': port,
                'protocol': protocol,
                'is_valid': True,
                'response_time': response_time,
                'test_url': test_url,
                'country': geo_info.get('country', 'Unknown'),
                'country_code': self._get_country_code(geo_info.get('country', 'Unknown')),
                'city': geo_info.get('city', 'Unknown'),
                'isp': geo_info.get('isp', 'Unknown'),
                'is_mobile': geo_info.get('mobile', False),
                'is_proxy': geo_info.get('proxy', False),
                'anonymity_level': geo_info.get('anonymity', 'Unknown'),
                'speed_tier': self._classify_speed(response_time),
                'score': self._calculate_score(response_time, geo_info)
            }
    
    async def _get_geo_info(self, session: aiohttp.ClientSession, proxy_url: str = None) -> Dict:
        """获取地理位置信息（带速率限制保护）"""
        async with self.geo_semaphore:  # 控制并发调用
            try:
                request_kwargs = {'proxy': proxy_url} if proxy_url else {}
                async with session.get("http://ip-api.com/json/", **request_kwargs) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            'country': data.get('country', 'Unknown'),
                            'city': data.get('city', 'Unknown'),
                            'isp': data.get('isp', 'Unknown'),
                            'mobile': data.get('mobile', False),
                            'proxy': data.get('proxy', False),
                            'anonymity': self._determine_anonymity(data)
                        }
            except Exception as e:
                self.logger.warning(f"获取地理位置失败: {e}")
                raise  # 重新抛出异常，让上层捕获
    
    def _calculate_score(self, response_time: float, geo_info: Dict) -> float:
        """计算代理评分"""
        score = 10.0
        
        if response_time < 1.0:
            score += 5.0
        elif response_time < 3.0:
            score += 3.0
        elif response_time < 5.0:
            score += 1.0
        else:
            score -= 2.0
        
        if geo_info.get('mobile'):
            score += 2.0
        
        if geo_info.get('proxy'):
            score -= 3.0
        
        return max(0.0, score)
    
    def _get_country_code(self, country: str) -> str:
        """根据国家名获取国家代码"""
        country_codes = {
            'United States': 'US',
            'Japan': 'JP',
            'Germany': 'DE',
            'Singapore': 'SG',
            'Netherlands': 'NL',
            'United Kingdom': 'GB',
            'Canada': 'CA',
            'France': 'FR',
            'South Korea': 'KR',
            'Hong Kong': 'HK',
            'Taiwan': 'TW',
            'Switzerland': 'CH',
            'Sweden': 'SE',
            'Australia': 'AU',
            'Unknown': 'UN'
        }
        return country_codes.get(country, country[:2].upper() if len(country) >= 2 else 'UN')
    
    def _determine_anonymity(self, geo_data: Dict) -> str:
        """确定匿名级别"""
        is_proxy = geo_data.get('proxy', False)
        is_mobile = geo_data.get('mobile', False)
        
        if is_proxy:
            return 'Transparent'  # 被识别为代理
        elif is_mobile:
            return 'Anonymous'     # 移动IP，较难追踪
        else:
            return 'Elite'         # 未被识别，精英匿名
    
    def _classify_speed(self, response_time: float) -> str:
        """响应时间分级"""
        if response_time < 1.0:
            return 'Fast'
        elif response_time < 3.0:
            return 'Medium'
        else:
            return 'Slow'
