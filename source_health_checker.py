"""
代理源健康检查模块
监控代理源质量并生成报告
"""

import asyncio
import aiohttp
import logging
from typing import List, Dict
from datetime import datetime
import re


class SourceHealthChecker:
    """代理源健康检查器"""
    
    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.logger = logging.getLogger(__name__)
    
    async def check_source(self, source_url: str) -> Dict:
        """
        检查单个代理源的健康状况
        
        Returns:
            {
                'url': 源URL,
                'is_available': 是否可用,
                'response_time': 响应时间,
                'proxies_found': 找到的代理数量,
                'valid_proxies': 有效格式的代理数量,
                'error': 错误信息
            }
        """
        result = {
            'url': source_url,
            'is_available': False,
            'response_time': None,
            'proxies_found': 0,
            'valid_proxies': 0,
            'error': None,
            'check_time': datetime.now().isoformat()
        }
        
        try:
            import time
            start_time = time.time()
            
            async with aiohttp.ClientSession(
                headers={"User-Agent": "SOCKS5-Scanner/2.0"},
                timeout=aiohttp.ClientTimeout(total=self.timeout, sock_connect=5.0)
            ) as session:
                async with session.get(source_url) as response:
                    response_time = time.time() - start_time
                    result['response_time'] = round(response_time, 2)
                    
                    if response.status != 200:
                        result['error'] = f"HTTP {response.status}"
                        return result
                    
                    content = await response.text()
                    
                    # 提取所有IP:端口格式
                    ip_port_pattern = r'\b(?:\d{1,3}\.){3}\d{1,3}:\d{2,5}\b'
                    matches = re.findall(ip_port_pattern, content)
                    
                    result['proxies_found'] = len(matches)
                    
                    # 验证IP格式
                    valid_count = 0
                    for match in matches:
                        ip, port = match.split(':')
                        if self._is_valid_ip(ip) and self._is_valid_port(port):
                            valid_count += 1
                    
                    result['valid_proxies'] = valid_count
                    result['is_available'] = True
                    
                    self.logger.info(
                        f"源 {source_url} 检查完成: "
                        f"{valid_count}/{len(matches)} 有效代理, "
                        f"响应时间 {response_time:.2f}s"
                    )
                    
        except asyncio.TimeoutError:
            result['error'] = "连接超时"
            self.logger.warning(f"源 {source_url} 超时")
        except Exception as e:
            result['error'] = str(e)
            self.logger.error(f"源 {source_url} 检查失败: {e}")
        
        return result
    
    async def check_all_sources(self, sources: List[str]) -> List[Dict]:
        """检查所有代理源"""
        tasks = [self.check_source(source) for source in sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 过滤异常
        valid_results = []
        for i, result in enumerate(results):
            if isinstance(result, dict):
                valid_results.append(result)
            else:
                self.logger.error(f"源 {sources[i]} 检查异常: {result}")
                valid_results.append({
                    'url': sources[i],
                    'is_available': False,
                    'error': str(result),
                    'check_time': datetime.now().isoformat()
                })
        
        return valid_results
    
    def _is_valid_ip(self, ip: str) -> bool:
        """验证IP地址格式"""
        try:
            parts = ip.split('.')
            if len(parts) != 4:
                return False
            
            for part in parts:
                num = int(part)
                if not 0 <= num <= 255:
                    return False
            
            # 排除私有IP
            first = int(parts[0])
            if first in [10, 127]:
                return False
            if first == 172 and 16 <= int(parts[1]) <= 31:
                return False
            if first == 192 and parts[1] == '168':
                return False
            
            return True
        except (ValueError, IndexError):
            return False
    
    def _is_valid_port(self, port: str) -> bool:
        """验证端口格式"""
        try:
            port_num = int(port)
            return 1 <= port_num <= 65535
        except ValueError:
            return False
    
    def generate_report(self, results: List[Dict]) -> str:
        """生成健康检查报告"""
        total = len(results)
        available = sum(1 for r in results if r['is_available'])
        total_proxies = sum(r.get('valid_proxies', 0) for r in results)
        
        report = [
            "=" * 70,
            "代理源健康检查报告",
            "=" * 70,
            f"检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"总源数量: {total}",
            f"可用源数: {available} ({available/total*100:.1f}%)",
            f"总代理数: {total_proxies}",
            "",
            "详细信息:",
            "-" * 70
        ]
        
        # 按可用性和代理数量排序
        sorted_results = sorted(
            results, 
            key=lambda x: (x['is_available'], x.get('valid_proxies', 0)), 
            reverse=True
        )
        
        for r in sorted_results:
            status = "✓" if r['is_available'] else "✗"
            proxies = r.get('valid_proxies', 0)
            time_str = f"{r['response_time']:.2f}s" if r.get('response_time') else "N/A"
            error_str = f" - {r.get('error', '')}" if r.get('error') else ""
            
            # 缩短URL显示
            url = r['url']
            if len(url) > 60:
                url = url[:57] + "..."
            
            report.append(
                f"{status} {url}\n"
                f"   代理: {proxies}, 响应: {time_str}{error_str}"
            )
        
        report.append("=" * 70)
        
        return "\n".join(report)
    
    async def auto_disable_bad_sources(self, results: List[Dict], 
                                       db=None, 
                                       min_proxies: int = 5,
                                       max_fails: int = 3) -> List[str]:
        """
        自动禁用质量差的源
        
        Args:
            results: 健康检查结果
            db: 数据库实例
            min_proxies: 最小代理数量阈值
            max_fails: 最大失败次数
            
        Returns:
            被禁用的源列表
        """
        disabled_sources = []
        
        for result in results:
            source_url = result['url']
            
            # 条件1: 当前不可用
            if not result['is_available']:
                if db:
                    # 检查历史失败次数
                    source_stats = await self._get_source_stats(db, source_url)
                    if source_stats and source_stats['fail_count'] >= max_fails:
                        disabled_sources.append(source_url)
                        self.logger.warning(f"禁用源 {source_url}: 连续失败{max_fails}次")
            
            # 条件2: 代理数量太少
            elif result.get('valid_proxies', 0) < min_proxies:
                disabled_sources.append(source_url)
                self.logger.warning(f"禁用源 {source_url}: 代理数量不足({result['valid_proxies']})")
        
        return disabled_sources
    
    async def _get_source_stats(self, db, source_url: str) -> Dict:
        """从数据库获取源统计信息"""
        try:
            sources = db.get_source_health()
            for source in sources:
                if source['source_url'] == source_url:
                    return source
        except:
            pass
        return None
