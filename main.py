#!/usr/bin/env python3
"""
Polymarket 自动交易系统 - 主程序

使用方法:
1. 复制 .env.example 为 .env，填入你的钱包地址和私钥
2. 修改 config.yaml 调整策略参数（默认 DRY_RUN=true 为模拟模式）
3. 安装依赖: pip install -r requirements.txt
4. 运行: python main.py

安全提示:
- 默认开启模拟交易（DRY_RUN=true），不会使用真实资金
- 确认策略逻辑无误后，再修改 config.yaml 中的 dry_run: false
- 首次运行建议观察 1-2 天模拟结果
"""

import os
import sys
import time
import yaml
import signal
from datetime import datetime
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

from core.polymarket_client import PolymarketClient
from core.risk_manager import RiskManager
from core.execution_engine import ExecutionEngine
from strategies.simple_arbitrage import SimpleArbitrageStrategy
from strategies.no_value_hunter import NoValueHunterStrategy
from strategies.clueless_tailwind import CluelessTailwindStrategy
from strategies.multi_market_rotator import MultiMarketRotator
from utils.logger import setup_logger


class TradingBot:
    """交易机器人主类"""
    
    def __init__(self, config_path: str = "config.yaml"):
        # 加载配置
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)
        
        # 初始化日志
        log_level = self.config.get("logging", {}).get("level", "INFO")
        log_file = self.config.get("logging", {}).get("file", "logs/trading.log")
        self.logger = setup_logger("TradingBot", log_file, log_level)
        
        self.logger.info("=" * 60)
        self.logger.info(" Polymarket 自动交易系统启动")
        self.logger.info("=" * 60)
        
        # 交易模式
        self.dry_run = self.config.get("trading", {}).get("dry_run", True)
        if self.dry_run:
            self.logger.warning("⚠️  当前为模拟交易模式（DRY_RUN），不使用真实资金")
        else:
            self.logger.warning("🚨 当前为实盘交易模式，将使用真实资金！")
            self.logger.warning("   按 Ctrl+C 立即终止，或确认继续...")
            time.sleep(3)
        
        # 初始化组件
        self._init_components()
        
        # 运行状态
        self.running = True
        self.scan_count = 0
        self.signals_found = 0
        self.trades_executed = 0
        
        # 信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _init_components(self):
        """初始化各组件"""
        # API 客户端
        api_config = self.config.get("api", {})
        self.client = PolymarketClient(api_config)
        self.client.logger = self.logger
        
        # 风控
        risk_config = self.config.get("risk", {})
        self.risk = RiskManager(risk_config)
        
        # 执行引擎
        trading_config = self.config.get("trading", {})
        self.engine = ExecutionEngine(
            client=self.client,
            risk_manager=self.risk,
            config=trading_config,
            dry_run=self.dry_run
        )
        
        # 策略
        strategy_config = self.config.get("strategy", {})
        self.active_strategy_name = strategy_config.get("active", "simple_arbitrage")
        
        if self.active_strategy_name == "simple_arbitrage":
            self.strategy = SimpleArbitrageStrategy(
                strategy_config.get("simple_arbitrage", {})
            )
        elif self.active_strategy_name == "no_value_hunter":
            self.strategy = NoValueHunterStrategy(
                strategy_config.get("no_value_hunter", {})
            )
        elif self.active_strategy_name == "clueless_tailwind":
            self.strategy = CluelessTailwindStrategy(
                strategy_config.get("clueless_tailwind", {})
            )
        elif self.active_strategy_name == "multi_market_rotator":
            self.strategy = MultiMarketRotator(
                strategy_config.get("multi_market_rotator", {})
            )
        else:
            self.logger.error(f"未知策略: {self.active_strategy_name}")
            sys.exit(1)
        
        self.logger.info(f"策略加载: {self.strategy.name} - {self.strategy.description}")
    
    def _signal_handler(self, signum, frame):
        """处理终止信号"""
        self.logger.info("\n收到终止信号，正在安全退出...")
        self.running = False
    
    def run(self):
        """主循环"""
        scan_interval = self.config.get("trading", {}).get("scan_interval", 10)
        max_markets = self.config.get("trading", {}).get("max_markets_per_scan", 50)
        
        strategy_cfg = self.config.get("strategy", {}).get(self.active_strategy_name, {})
        min_volume = strategy_cfg.get("min_volume", 1000)
        max_days = strategy_cfg.get("max_days_to_resolution", 90)
        categories = strategy_cfg.get("categories", [])
        
        self.logger.info(f"扫描间隔: {scan_interval}秒 | 每次最多 {max_markets} 个市场")
        self.logger.info(f"最小交易量: ${min_volume} | 最大结算等待: {max_days}天")
        self.logger.info("按 Ctrl+C 停止\n")
        
        while self.running:
            try:
                loop_start = time.time()
                self.scan_count += 1
                
                # 风控检查
                can_trade, reason = self.risk.can_trade()
                if not can_trade:
                    self.logger.warning(f"[风控] 暂停交易: {reason}")
                    time.sleep(scan_interval)
                    continue
                
                # 扫描市场
                self.logger.info(f"\n--- 第 {self.scan_count} 轮扫描 ---")
                
                markets = self.client.get_active_binary_markets(
                    limit=max_markets,
                    min_volume=min_volume,
                    max_days=max_days,
                    categories=categories if categories else None
                )
                
                self.logger.info(f"获取 {len(markets)} 个活跃二元市场")
                
                if not markets:
                    self.logger.info("无有效市场，跳过")
                    time.sleep(scan_interval)
                    continue
                
                # 打印前几个市场的价格
                self._print_market_snapshots(markets[:5])
                
                # 策略扫描
                signals = self.strategy.scan(markets)
                self.signals_found += len(signals)
                
                if signals:
                    self.logger.info(f"发现 {len(signals)} 个交易信号")
                    
                    # 执行信号（只执行优先级最高的几个）
                    executed = 0
                    for sig in signals[:3]:  # 每轮最多执行3个
                        self.logger.info(f"[信号] {sig['reason']}")
                        
                        success, msg = self.strategy.execute(sig, self.engine)
                        if success:
                            executed += 1
                            self.trades_executed += 1
                            self.logger.info(f"[执行成功] {msg}")
                        else:
                            self.logger.info(f"[执行跳过] {msg}")
                        
                        time.sleep(1)  # 执行间隔
                    
                    if executed > 0:
                        self.logger.info(self.engine.get_portfolio_summary())
                else:
                    self.logger.info("未发现套利机会")
                
                # 风控状态
                risk_status = self.risk.get_status()
                self.logger.info(
                    f"[风控状态] 日盈亏: ${risk_status['daily_pnl']} | "
                    f"日交易: {risk_status['daily_trades']}/{risk_status['max_trade_size']} | "
                    f"持仓: {risk_status['open_positions']}"
                )
                
                # 等待下一轮
                elapsed = time.time() - loop_start
                sleep_time = max(0, scan_interval - elapsed)
                if sleep_time > 0 and self.running:
                    time.sleep(sleep_time)
                
            except Exception as e:
                self.logger.error(f"主循环异常: {e}", exc_info=True)
                time.sleep(scan_interval)
        
        # 退出前打印汇总
        self._print_summary()
    
    def _print_market_snapshots(self, markets: list):
        """打印市场快照"""
        self.logger.info("市场快照（前5个）:")
        for m in markets:
            spread = m.get("spread", 0)
            indicator = "🎯" if spread > 0.02 else "  "
            self.logger.info(
                f"  {indicator} {m['question'][:50]}... | "
                f"YES=${m['yes_price']:.3f} NO=${m['no_price']:.3f} | "
                f"总和=${m['sum_price']:.3f} | 量=${m['volume']:.0f}"
            )
    
    def _print_summary(self):
        """打印运行汇总"""
        self.logger.info("\n" + "=" * 60)
        self.logger.info(" 运行汇总")
        self.logger.info("=" * 60)
        self.logger.info(f" 总扫描轮数: {self.scan_count}")
        self.logger.info(f" 发现信号数: {self.signals_found}")
        self.logger.info(f" 执行交易数: {self.trades_executed}")
        
        if self.dry_run:
            self.logger.info(self.engine.get_portfolio_summary())
            self.engine.print_trade_history(10)
        
        self.logger.info("=" * 60)


def quick_test():
    """
    快速测试模式：只扫描一次市场，打印结果，不执行交易
    """
    print("=" * 60)
    print(" Polymarket 套利扫描测试")
    print("=" * 60)
    
    with open("config.yaml", 'r') as f:
        config = yaml.safe_load(f)
    
    client = PolymarketClient(config.get("api", {}))
    strategy = SimpleArbitrageStrategy(config.get("strategy", {}).get("simple_arbitrage", {}))
    
    print("\n正在扫描市场...")
    markets = client.get_active_binary_markets(
        limit=100,
        min_volume=500,
        max_days=60
    )
    
    print(f"获取 {len(markets)} 个活跃二元市场\n")
    
    # 按套利空间排序
    markets_sorted = sorted(markets, key=lambda x: x.get("spread", 0), reverse=True)
    
    print("套利空间最大的市场（前10个）：")
    print("-" * 80)
    for m in markets_sorted[:10]:
        spread = m.get("spread", 0)
        profit = spread * 100
        print(f"利润: {profit:.1f}% | 总和: ${m['sum_price']:.4f}")
        print(f"  YES=${m['yes_price']:.4f} NO=${m['no_price']:.4f} | 量=${m['volume']:.0f}")
        print(f"  {m['question'][:70]}")
        print()
    
    # 策略扫描
    signals = strategy.scan(markets)
    print(f"\n策略发现 {len(signals)} 个交易信号：")
    print("-" * 80)
    for sig in signals[:5]:
        print(f"[{sig['action']}] 置信度: {sig['confidence']:.2f}")
        print(f"  {sig['reason']}")
        print()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Polymarket 自动交易系统")
    parser.add_argument("--test", action="store_true", help="快速测试模式（只扫描不交易）")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    args = parser.parse_args()
    
    if args.test:
        quick_test()
    else:
        bot = TradingBot(config_path=args.config)
        bot.run()
