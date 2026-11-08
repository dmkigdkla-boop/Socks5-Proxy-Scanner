"""
集成增强主扫描器
整合所有新功能: 数据持久化、增强评分、源健康检查等
"""

import asyncio
import argparse
import logging
import sys
import os
import re
from datetime import datetime

from config import Config
from proxy_sources_fixed import ProxySourceManager
from validators import ProxyValidator
from exporters import ResultExporter
from proxy_database import ProxyDatabase
from enhanced_validator import EnhancedValidator, ProxyScorer
from source_health_checker import SourceHealthChecker
from timezone_utils import get_display_time


PROXY_ADDRESS = re.compile(r'^(?:\d{1,3}\.){3}\d{1,3}:\d{1,5}$')


def load_staged_candidates(file_path: str) -> set:
    """Load de-duplicated IP:PORT candidates discovered by VPS workers."""
    if not file_path or not os.path.isfile(file_path):
        return set()

    candidates = set()
    with open(file_path, 'r', encoding='utf-8') as candidate_file:
        for line in candidate_file:
            address = line.strip()
            if PROXY_ADDRESS.fullmatch(address):
                candidates.add(address)
    return candidates


async def main():
    """主函数"""
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='SOCKS5代理扫描器 (增强版)')
    parser.add_argument('--timeout', type=int, default=10, help='超时时间(秒)')
    parser.add_argument('--max-concurrency', type=int, default=300, help='最大并发数')
    parser.add_argument('--output', type=str, default='subscribe/proxies.json', help='输出文件')
    parser.add_argument('--log-level', type=str, default='INFO',
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                       help='日志级别')
    parser.add_argument('--db-path', type=str, default='proxies.db', help='数据库路径')
    parser.add_argument('--cleanup-days', type=int, default=30, help='清理天数')
    parser.add_argument('--enable-enhanced', action='store_true', 
                       help='启用增强验证(DNS泄露、带宽测试等)')
    parser.add_argument('--check-sources', action='store_true',
                       help='检查代理源健康状况')
    parser.add_argument('--enable-telegram', action='store_true',
                       help='启用Telegram Bot')
    parser.add_argument('--enable-web', action='store_true',
                       help='启动Web Dashboard')
    parser.add_argument('--enable-blacklist', action='store_true',
                       help='启用代理黑名单过滤')
    parser.add_argument('--auto-blacklist', action='store_true',
                       help='自动将持续失败的代理加入黑名单')
    parser.add_argument('--blacklist-threshold', type=int, default=5,
                       help='自动加入黑名单的失败次数阈值')
    parser.add_argument('--candidate-file', type=str, default=None,
                       help='VPS 发现器生成的 IP:PORT 候选文件')
    
    args = parser.parse_args()
    
    # 配置日志
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('scanner.log', encoding='utf-8')
        ]
    )
    logger = logging.getLogger(__name__)
    
    logger.info("=" * 70)
    logger.info("SOCKS5代理扫描器 (增强版) 启动")
    logger.info("=" * 70)
    
    # 加载配置
    config = Config(
        timeout=args.timeout,
        max_concurrency=args.max_concurrency,
        output_file=args.output
    )
    
    
    # 初始化数据库
    db = ProxyDatabase(args.db_path)
    logger.info(f"数据库初始化完成: {args.db_path}")
    
    # 检查代理源健康状况(可选)
    if args.check_sources:
        logger.info("\n开始检查代理源健康状况...")
        source_checker = SourceHealthChecker(timeout=args.timeout)
        source_results = await source_checker.check_all_sources(config.sources)
        report = source_checker.generate_report(source_results)
        print("\n" + report)
        
        # 保存源状态到数据库
        for result in source_results:
            db.update_source_stats(
                result['url'],
                result['is_available'],
                result.get('valid_proxies', 0)
            )
    
    # 获取代理列表
    logger.info("\n开始从代理源获取代理列表...")
    source_manager = ProxySourceManager(config)
    all_proxies = await source_manager.fetch_all_sources()

    staged_candidates = load_staged_candidates(args.candidate_file)
    if staged_candidates:
        all_proxies.update(staged_candidates)
        logger.info(f"✅ 已合并 {len(staged_candidates)} 个 VPS 发现候选")
    
    if not all_proxies:
        logger.error("❌ 未获取到任何代理")
        return
    
    logger.info(f"✅ 成功获取 {len(all_proxies)} 个代理")
    
    # 黑名单过滤
    if args.enable_blacklist:
        logger.info("\n应用黑名单过滤...")
        blacklist = db.get_blacklisted_proxies()
        logger.info(f"   当前黑名单: {len(blacklist)} 个代理")
        
        original_count = len(all_proxies)
        all_proxies = {p for p in all_proxies if p not in blacklist}
        filtered_count = original_count - len(all_proxies)
        
        logger.info(f"   ✅ 过滤掉 {filtered_count} 个黑名单代理")
        logger.info(f"   剩余 {len(all_proxies)} 个代理待验证")
    
    # 验证代理
    logger.info("\n开始验证代理...")
    
    if args.enable_enhanced:
        # 使用增强验证器
        logger.info("使用增强验证模式 (包含DNS泄露、带宽测试)")
        validator = EnhancedValidator(timeout=args.timeout)
        valid_results = await validator.validate_batch(
            list(all_proxies),
            max_concurrency=args.max_concurrency
        )
    else:
        # 使用标准验证器
        validator = ProxyValidator(config)
        valid_results = await validator.validate_proxies(list(all_proxies))
    
    # 过滤有效代理
    valid_proxies = [r for r in valid_results if r.get('is_valid')]
    logger.info(f"✅ 验证完成: {len(valid_proxies)}/{len(all_proxies)} 个代理有效")
    
    # 评分和保存到数据库
    logger.info("\n计算评分并保存到数据库...")
    scorer = ProxyScorer(db)
    
    for proxy_data in valid_proxies:
        try:
            # 保存代理信息
            proxy_id = db.save_proxy(proxy_data)
            
            # 获取历史统计
            historical_stats = db.get_proxy_stats(proxy_data['proxy'])
            
            # 计算综合评分
            score = scorer.calculate_score(proxy_data, historical_stats)
            proxy_data['score'] = score
            
            # 保存验证结果
            db.save_validation_result(proxy_data['proxy'], {
                'is_valid': True,
                'response_time': proxy_data.get('response_time'),
                'test_url': proxy_data.get('test_url'),
                'score': score
            })
            
        except Exception as e:
            logger.error(f"处理代理 {proxy_data.get('proxy')} 时出错: {e}")
    
    # 保存失败代理的验证记录（用于黑名单系统）
    logger.info("\n保存失败代理的验证记录...")
    failed_count = 0
    for result in valid_results:
        if not result.get('is_valid'):
            try:
                proxy_address = result.get('proxy')
                if proxy_address:
                    # 尝试保存代理信息（如果有基本信息）
                    try:
                        db.save_proxy({
                            'proxy': proxy_address,
                            'country': 'Unknown',
                            'country_code': 'UN',
                            'city': 'Unknown'
                        })
                    except:
                        pass  # 代理可能已存在
                    
                    # 保存失败的验证记录
                    db.save_validation_result(proxy_address, {
                        'is_valid': False,
                        'response_time': None,
                        'test_url': config.test_urls[0] if config.test_urls else None,
                        'error': result.get('error', 'Validation failed'),
                        'score': 0
                    })
                    failed_count += 1
            except Exception as e:
                logger.debug(f"保存失败记录时出错 {proxy_address}: {e}")
    
    logger.info(f"   ✅ 已保存 {failed_count} 个失败代理的验证记录")
    
    # 导出结果
    logger.info(f"\n导出结果到 {args.output}...")
    exporter = ResultExporter(config)
    await exporter.export_results(valid_proxies)
    
    # 获取最佳代理并额外导出
    logger.info("\n生成最佳代理列表...")
    best_proxies = db.get_best_proxies(limit=50, min_checks=2, min_success_rate=0.6)
    if best_proxies:
        best_proxies_file = 'subscribe/best_proxies.txt'
        with open(best_proxies_file, 'w', encoding='utf-8') as f:
            for proxy in best_proxies:
                f.write(f"{proxy['proxy_address']}\n")
        logger.info(f"✅ 最佳代理列表已保存到 {best_proxies_file} ({len(best_proxies)}个)")
    
    # 数据库统计
    logger.info("\n数据库统计:")
    stats = db.get_database_stats()
    logger.info(f"  总代理数: {stats['total_proxies']}")
    logger.info(f"  24小时活跃: {stats['active_proxies_24h']}")
    logger.info(f"  24小时成功率: {stats['success_rate_24h']*100:.1f}%")
    logger.info(f"  总验证次数: {stats['total_validations']}")
    
    # 清理旧数据
    logger.info(f"\n清理 {args.cleanup_days} 天前的旧数据...")
    deleted_validations, deleted_proxies = db.cleanup_old_records(days=args.cleanup_days)
    logger.info(f"✅ 清理完成: 删除 {deleted_validations} 条验证记录, {deleted_proxies} 个代理")
    
    # 自动加入黑名单
    if args.auto_blacklist:
        logger.info(f"\n执行自动黑名单检查 (阈值: {args.blacklist_threshold}次失败)...")
        blacklisted_count = db.auto_blacklist_failing_proxies(
            fail_threshold=args.blacklist_threshold,
            days=7
        )
        if blacklisted_count > 0:
            logger.info(f"   ✅ 新增 {blacklisted_count} 个代理到黑名单")
            
            # 显示黑名单统计
            bl_stats = db.get_blacklist_stats()
            logger.info(f"   黑名单总数: {bl_stats['total_blacklisted']}")
            logger.info(f"   自动添加: {bl_stats['auto_added']}")
            logger.info(f"   手动添加: {bl_stats['manual_added']}")
        else:
            logger.info(f"   ℹ️ 没有发现需要加入黑名单的代理")

    # 导出黑名单文件
    if args.enable_blacklist:
        try:
            blacklist_file = 'subscribe/blacklist.txt'
            all_blacklisted = db.get_blacklisted_proxies()
            if all_blacklisted:
                logger.info(f"\n导出黑名单到 {blacklist_file}...")
                with open(blacklist_file, 'w', encoding='utf-8') as f:
                    f.write("# Proxy Blacklist\n")
                    f.write(f"# Total: {len(all_blacklisted)}\n")
                    f.write(f"# Updated: {get_display_time()} (北京时间)\n\n")
                    for proxy in sorted(all_blacklisted):
                        f.write(f"{proxy}\n")
                logger.info(f"✅ 黑名单已保存 ({len(all_blacklisted)}个)")
        except Exception as e:
            logger.error(f"导出黑名单失败: {e}")
    
    # 启动可选功能
    # 启动可选功能
    if args.enable_telegram:
        logger.info("\n启动Telegram Bot...")
        try:
            from telegram_bot import TelegramBot
            # 注意：此处不再使用 ConfigManager，而是提示用户单独运行
            # 如果需要集成，应从环境变量或args读取 token
            token = os.getenv("TELEGRAM_BOT_TOKEN")
            if token:
                bot = TelegramBot(token, args.db_path)
                logger.info("⚠️  Telegram Bot需要单独运行: python telegram_bot.py")
            else:
                logger.warning("⚠️  未设置TELEGRAM_BOT_TOKEN, 跳过Telegram功能")
        except ImportError:
            logger.warning("⚠️  pyTelegramBotAPI未安装, 跳过Telegram功能")
    
    if args.enable_web:
        logger.info("\nWeb Dashboard可单独启动: python web_dashboard.py")
    
    logger.info("\n" + "=" * 70)
    logger.info("✅ 扫描完成!")
    logger.info("=" * 70)
    
    # 显示运行建议
    print("\n💡 提示:")
    print("  - 查看最佳代理: cat best_proxies.txt")
    print("  - 启动Web Dashboard: python web_dashboard.py")
    print("  - 启动Telegram Bot: python telegram_bot.py")
    print("  - 查看数据库统计: python -c 'from proxy_database import *; db=ProxyDatabase(); print(db.get_database_stats())'")


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断")
        sys.exit(0)
    except Exception as e:
        logging.error(f"❌ 程序异常: {e}", exc_info=True)
        sys.exit(1)
