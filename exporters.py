"""
结果导出器模块
"""

import json
import csv
import logging
from pathlib import Path
from typing import List, Dict
from datetime import datetime, timezone


class ResultExporter:
    """结果导出器"""
    
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
    
    async def export_results(self, proxies: List[Dict]):
        """导出代理结果"""
        if not proxies:
            self.logger.warning("没有有效的代理可以导出；将发布空结果以避免保留过期代理")
        
        # 按评分排序（优先使用rating中的overall_score，如果没有则使用旧的score）
        proxies.sort(key=lambda x: x.get('rating', {}).get('overall_score', x.get('score', 0)), reverse=True)
        
        # 导出JSON格式
        await self._export_json(proxies)
        
        # 导出TXT格式（纯代理列表）
        await self._export_txt(proxies)
        
        # 导出CSV格式（详细信息）
        await self._export_csv(proxies)
        
        self.logger.info(f"✅ 结果已导出到: {self.config.output_file} (及相关的 .txt, .csv 文件)")
    
    async def _export_json(self, proxies: List[Dict]):
        """导出JSON格式"""
        output_file = Path(self.config.output_file)
        # 确保输出目录存在
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Cloudflare Pages API and the static dashboard consume this schema.  Keep
        # the legacy top-level fields below so existing subscription tooling stays
        # compatible with previously generated files.
        generated_at = datetime.now(timezone.utc).isoformat()
        public_proxies = []
        for proxy in proxies:
            item = dict(proxy)
            item.setdefault('protocol', 'socks5')
            item.setdefault('latency', item.get('response_time'))
            item.setdefault('anonymity', item.get('anonymity_level', 'unknown'))
            item.setdefault('last_check', generated_at)
            public_proxies.append(item)

        # 计算评分统计
        premium_count = sum(1 for p in proxies if p.get('rating', {}).get('quality_tier') == 'premium')
        standard_count = sum(1 for p in proxies if p.get('rating', {}).get('quality_tier') == 'standard')
        basic_count = sum(1 for p in proxies if p.get('rating', {}).get('quality_tier') == 'basic')
        poor_count = sum(1 for p in proxies if p.get('rating', {}).get('quality_tier') == 'poor')
        
        data = {
            'metadata': {
                'total': len(public_proxies),
                'updated_at': generated_at,
                'update_time_utc': generated_at,
                'description': 'SOCKS5 代理列表'
            },
            'timestamp': generated_at,
            'total_proxies': len(public_proxies),
            'avg_response_time': (
                sum(p.get('response_time', 0) for p in proxies) / len(proxies)
                if proxies else 0
            ),
            'countries': list(set(p.get('country', 'Unknown') for p in proxies)),
            'quality_distribution': {
                'premium': premium_count,
                'standard': standard_count,
                'basic': basic_count,
                'poor': poor_count
            },
            'proxies': public_proxies
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    async def _export_txt(self, proxies: List[Dict]):
        """导出TXT格式（带质量等级的代理列表）"""
        output_file = Path(self.config.output_file).with_suffix('.txt')
        
        with open(output_file, 'w', encoding='utf-8') as f:
            # 按质量等级分组
            premium_proxies = [p for p in proxies if p.get('rating', {}).get('quality_tier') == 'premium']
            standard_proxies = [p for p in proxies if p.get('rating', {}).get('quality_tier') == 'standard']
            basic_proxies = [p for p in proxies if p.get('rating', {}).get('quality_tier') == 'basic']
            poor_proxies = [p for p in proxies if p.get('rating', {}).get('quality_tier') == 'poor']
            
            # 写入Premium等级代理
            if premium_proxies:
                f.write("# Premium Quality Proxies\n")
                for proxy in premium_proxies:
                    rating = proxy.get('rating', {})
                    f.write(f"{proxy['proxy']} # Score: {rating.get('overall_score', 0):.1f} Tier: {rating.get('quality_tier', 'unknown')}\n")
                f.write("\n")
            
            # 写入Standard等级代理
            if standard_proxies:
                f.write("# Standard Quality Proxies\n")
                for proxy in standard_proxies:
                    rating = proxy.get('rating', {})
                    f.write(f"{proxy['proxy']} # Score: {rating.get('overall_score', 0):.1f} Tier: {rating.get('quality_tier', 'unknown')}\n")
                f.write("\n")
            
            # 写入Basic等级代理
            if basic_proxies:
                f.write("# Basic Quality Proxies\n")
                for proxy in basic_proxies:
                    rating = proxy.get('rating', {})
                    f.write(f"{proxy['proxy']} # Score: {rating.get('overall_score', 0):.1f} Tier: {rating.get('quality_tier', 'unknown')}\n")
                f.write("\n")
            
            # 写入Poor等级代理
            if poor_proxies:
                f.write("# Poor Quality Proxies\n")
                for proxy in poor_proxies:
                    rating = proxy.get('rating', {})
                    f.write(f"{proxy['proxy']} # Score: {rating.get('overall_score', 0):.1f} Tier: {rating.get('quality_tier', 'unknown')}\n")
                f.write("\n")
            
            # 写入纯代理列表（兼容旧格式）
            f.write("# Pure Proxy List (for compatibility)\n")
            for proxy in proxies:
                f.write(f"{proxy['proxy']}\n")
    
    async def _export_csv(self, proxies: List[Dict]):
        """导出CSV格式"""
        output_file = Path(self.config.output_file).with_suffix('.csv')
        
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['proxy', 'ip', 'port', 'country', 'city', 'response_time', 'score', 'quality_tier', 'overall_score', 'reliability_rating']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            
            writer.writeheader()
            for proxy in proxies:
                row = {field: proxy.get(field, '') for field in fieldnames}
                # 添加评分数据
                rating = proxy.get('rating', {})
                row['quality_tier'] = rating.get('quality_tier', '')
                row['overall_score'] = f"{rating.get('overall_score', 0):.1f}"
                row['reliability_rating'] = f"{rating.get('reliability_rating', 0):.1f}"
                writer.writerow(row)
