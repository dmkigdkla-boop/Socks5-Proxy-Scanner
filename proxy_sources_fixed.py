"""
代理源管理器模块
"""

import asyncio
import aiohttp
import re
import logging
from typing import List, Set
import time


class ProxySourceManager:
    """代理源管理器"""
    
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.session = None
        
    async def fetch_all_sources(self) -> Set[str]:
        """从所有配置的源获取代理"""
        # 创建session
        self.session = aiohttp.ClientSession(
            headers={"User-Agent": "SOCKS5-Scanner/1.0"},
            timeout=aiohttp.ClientTimeout(total=self.config.timeout)
        )
        
        try:
            tasks = []
            for source in self.config.sources:
                if source.startswith('http'):
                    tasks.append(self._fetch_http_source(source))
            
            if not tasks:
                self.logger.warning("没有配置有效的代理源")
                return set()
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            all_proxies = set()
            for i, result in enumerate(results):
                source = self.config.sources[i]
                if isinstance(result, Exception):
                    self.logger.error(f"源 {source} 获取失败: {result}")
                else:
                    self.logger.info(f"源 {source} 获取到 {len(result)} 个代理")
                    all_proxies.update(result)
            
            self.logger.info(f"总计从 {len(tasks)} 个源获取到 {len(all_proxies)} 个代理")
            return all_proxies
            
        finally:
            # 确保关闭session
            if self.session:
                await self.session.close()
    
    async def _fetch_http_source(self, url: str) -> Set[str]:
        """获取HTTP源"""
        proxies = set()
        
        try:
            async with self.session.get(url) as response:
                if response.status != 200:
                    self.logger.warning(f"源 {url} 返回状态码 {response.status}")
                    return proxies
                
                content = await response.text()
                
                # 提取IP:端口格式的代理
                ip_port_pattern = r'\b(?:\d{1,3}\.){3}\d{1,3}:\d{2,5}\b'
                matches = re.findall(ip_port_pattern, content)
                
                for match in matches:
                    ip, port = match.split(':')
                    if self._is_valid_ip(ip) and self._is_valid_port(port):
                        proxies.add(match)
                
                self.logger.debug(f"从 {url} 提取到 {len(proxies)} 个有效代理")
                
        except Exception as e:
            self.logger.error(f"获取源 {url} 失败: {e}")
        
        return proxies
    
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
            
            # 排除私有IP和保留IP
            first = int(parts[0])
            if first == 10:  # 10.0.0.0/8
                return False
            if first == 172 and 16 <= int(parts[1]) <= 31:  # 172.16.0.0/12
                return False
            if first == 192 and parts[1] == '168':  # 192.168.0.0/16
                return False
            if first == 127:  # 127.0.0.0/8
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
