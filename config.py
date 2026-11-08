"""
配置文件模块
"""

from dataclasses import dataclass
from typing import List, Dict


@dataclass
class Config:
    """配置类"""
    
    # 基础配置
    timeout: int = 10
    max_concurrency: int = 300  # GitHub Actions 上的高吞吐默认值
    output_file: str = "subscribe/proxies.json"  # 输出到 subscribe 目录
    
    # 代理源配置
    sources: List[str] = None
    
    # 验证配置
    test_urls: List[str] = None
    max_retries: int = 2
    
    # 过滤配置
    min_score: float = 0.0
    target_countries: List[str] = None  # 国家白名单；空列表表示保留所有国家
    priority_countries: List[str] = None  # 仅影响导出顺序，不过滤结果
    
    def __post_init__(self):
        if self.sources is None:
            self.sources = [
                # === 顶级代理源 (质量最高) ===
                "https://raw.githubusercontent.com/zevtyardt/proxy-list/main/socks5.txt",  # ⭐ 43,963 个
                "https://raw.githubusercontent.com/officialputuid/KangProxy/KangProxy/socks5/socks5.txt",  # ⭐ 3,001 个
                "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks5.txt",  # ⭐ 1,682 个
                "https://raw.githubusercontent.com/sunny9577/proxy-scraper/master/proxies.txt",  # ⭐ 1,388 个
                "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt",  # ⭐ 870 个
                
                # === 优质 GitHub 源 ===
                "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/socks5/data.txt",  # 748 个
                "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-socks5.txt",  # 405 个
                "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",  # 400 个
                "https://raw.githubusercontent.com/mmpx12/proxy-list/master/socks5.txt",  # 279 个
                "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/socks5.txt",  # 279 个
                "https://raw.githubusercontent.com/rdavydov/proxy-list/main/proxies/socks5.txt",  # 247 个
                
                # === 小型但活跃的源 ===
                "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",  # 17 个
                "https://raw.githubusercontent.com/roosterkid/openproxylist/main/SOCKS5_RAW.txt",  # 13 个
                "https://raw.githubusercontent.com/prxchk/proxy-list/main/socks5.txt",  # 10 个
                
                # === 已移除失效源 ===
                # ❌ mertguvencli/http-proxy-list (404)
                # ❌ zloi-user/hideip.me (404)
                # ❌ proxyscrape.com API (返回0个)
                # ❌ proxy-list.download API (失败)
                # ❌ geonode.com API (返回0个)
            ]
        
        if self.test_urls is None:
            self.test_urls = [
                "http://httpbin.org/ip",
                "http://icanhazip.com",
                "http://ip-api.com/json",
            ]
        
        if self.target_countries is None:
            # 不过滤国家；扫描完成后按 priority_countries 排序导出。
            self.target_countries = []

        if self.priority_countries is None:
            self.priority_countries = [
                # 首选
                "Taiwan",
                "Hong Kong",
                # 东南亚
                "Singapore", "Malaysia", "Thailand", "Vietnam", "Indonesia",
                "Philippines", "Brunei", "Cambodia", "Laos", "Myanmar", "Timor-Leste",
                # 东亚（台湾、香港已在首选中）
                "Japan", "South Korea", "China", "Mongolia",
            ]
        
        # 国家名称映射（用于处理不同的国家名称格式）
        self.country_aliases = {
            "US": "United States",
            "USA": "United States", 
            "UK": "United Kingdom",
            "TW": "Taiwan",
            "KR": "South Korea",
            "HK": "Hong Kong",
            "JP": "Japan",
            "SG": "Singapore",
            "CA": "Canada",
            "AU": "Australia",
            "NL": "Netherlands",
            "CH": "Switzerland",
            "SE": "Sweden",
            "DE": "Germany",
            "FR": "France",
            "GB": "United Kingdom",
        }
