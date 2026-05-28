"""
执行引擎模块
负责：策略信号 -> 风控检查 -> 下单执行 -> 结果记录
支持模拟交易和实盘交易两种模式
"""
import os
import uuid
from datetime import datetime
from typing import Dict, Optional, Tuple

from core.polymarket_client import PolymarketClient
from core.risk_manager import RiskManager, TradeRecord
from core.paper_trading import PaperTradingLedger
from utils.logger import setup_logger


class ExecutionEngine:
    """
    交易执行引擎
    
    执行流程：
    1. 接收策略信号（市场ID、方向、预期价格、金额）
    2. 风控验证
    3. 价格确认（检查当前订单簿）
    4. 下单（模拟或实盘）
    5. 记录交易
    6. 滑点检查
    """
    
    def __init__(self, client: PolymarketClient, 
                 risk_manager: RiskManager,
                 config: Dict,
                 dry_run: bool = True):
        self.client = client
        self.risk = risk_manager
        self.dry_run = dry_run
        self.logger = setup_logger("Execution", "logs/execution.log")
        
        # 模拟交易账本
        self.paper_ledger = PaperTradingLedger(
            initial_balance=config.get("paper_trading_balance", 1000.0)
        )
        
        # 手续费估算（简化：使用固定比例）
        self.estimated_fee_rate = 0.005  # 0.5% 保守估计
        
        # 实盘客户端（延迟初始化，避免启动时就加载私钥）
        self._live_client = None
        self._live_config = {
            "host": config.get("clob_host", "https://clob.polymarket.com"),
            "chain_id": 137,  # Polygon mainnet
            "private_key": os.getenv("POLYMARKET_PRIVATE_KEY", ""),
            "funder_address": os.getenv("POLYMARKET_FUNDER_ADDRESS", ""),
            "signature_type": int(os.getenv("POLYMARKET_SIGNATURE_TYPE", "0"))
        }
        
        if not dry_run:
            self._warn_live_mode()
    
    def _warn_live_mode(self):
        """实盘模式警告"""
        self.logger.warning("=" * 60)
        self.logger.warning("🚨 实盘交易模式已激活")
        self.logger.warning("   将使用真实资金在 Polymarket 上交易")
        self.logger.warning("   请确保：")
        self.logger.warning("   1. 已存入 pUSD（V2 抵押品）")
        self.logger.warning("   2. 已完成 token approvals")
        self.logger.warning("   3. 私钥和地址已正确配置在 .env")
        self.logger.warning("=" * 60)
        
        # 检查必要配置
        if not self._live_config["private_key"]:
            self.logger.error("❌ 错误: POLYMARKET_PRIVATE_KEY 未设置")
            raise ValueError("实盘模式需要 POLYMARKET_PRIVATE_KEY，请检查 .env")
        if not self._live_config["funder_address"]:
            self.logger.error("❌ 错误: POLYMARKET_FUNDER_ADDRESS 未设置")
            raise ValueError("实盘模式需要 POLYMARKET_FUNDER_ADDRESS，请检查 .env")
    
    def _get_live_client(self):
        """懒加载实盘客户端"""
        if self._live_client is None and not self.dry_run:
            from core.live_trading import LiveTradingClient
            self._live_client = LiveTradingClient(
                host=self._live_config["host"],
                chain_id=self._live_config["chain_id"],
                private_key=self._live_config["private_key"],
                funder_address=self._live_config["funder_address"],
                signature_type=self._live_config["signature_type"]
            )
            # 打印余额
            balance = self._live_client.get_balance()
            if balance is not None:
                self.logger.info(f"[实盘] 当前 pUSD 余额: ${balance:.2f}")
        return self._live_client
    
    # ==================== 套利执行 ====================
    
    def execute_arbitrage(self, market: Dict) -> Tuple[bool, str]:
        """
        执行单市场内套利：同时买入 YES 和 NO
        
        注意：实盘套利存在原子性问题（两单无法同时成交），
        当前实现为风险提示，建议小资金用户优先使用方向性策略。
        """
        market_id = market["id"]
        question = market["question"]
        yes_price = market["yes_price"]
        no_price = market["no_price"]
        sum_price = market["sum_price"]
        
        profit_per_set = 1.0 - sum_price
        
        if profit_per_set <= 0:
            return False, "无套利空间"
        
        max_size = self.risk.max_trade_size
        size_per_side = min(max_size / 2, self.risk.max_trade_size / 2)
        
        ok, reason = self.risk.validate_trade(
            market_id=market_id,
            side="ARBITRAGE",
            size=size_per_side * 2,
            expected_price=sum_price
        )
        if not ok:
            return False, f"风控拒绝: {reason}"
        
        self.logger.info(
            f"[套利机会] {question[:60]} | "
            f"YES=${yes_price:.4f} NO=${no_price:.4f} | "
            f"总和=${sum_price:.4f} | 每套利润=${profit_per_set:.4f}"
        )
        
        if self.dry_run:
            return self._paper_execute_arbitrage(market, size_per_side)
        else:
            return self._live_execute_arbitrage(market, size_per_side)
    
    def _paper_execute_arbitrage(self, market: Dict, size_per_side: float) -> Tuple[bool, str]:
        """模拟执行套利"""
        market_id = market["id"]
        question = market["question"]
        yes_price = market["yes_price"]
        no_price = market["no_price"]
        
        fees = size_per_side * 2 * self.estimated_fee_rate
        
        ok1, msg1, tid1 = self.paper_ledger.buy(
            market_id=market_id,
            market_question=question,
            side="BUY_YES",
            token_id=market["yes_token_id"],
            price=yes_price,
            size_usdc=size_per_side,
            fees=fees / 2
        )
        if not ok1:
            return False, f"模拟买入YES失败: {msg1}"
        
        ok2, msg2, tid2 = self.paper_ledger.buy(
            market_id=market_id + "_NO",
            market_question=question,
            side="BUY_NO",
            token_id=market["no_token_id"],
            price=no_price,
            size_usdc=size_per_side,
            fees=fees / 2
        )
        if not ok2:
            return False, f"模拟买入NO失败: {msg2}"
        
        total_cost = size_per_side * 2 + fees
        profit = (1.0 - yes_price - no_price) * (size_per_side / max(yes_price, no_price))
        
        trade = TradeRecord(
            trade_id=tid1,
            timestamp=datetime.now(),
            market_id=market_id,
            side="ARBITRAGE",
            size=total_cost,
            price=yes_price + no_price,
            expected_profit=profit,
            strategy="simple_arbitrage"
        )
        self.risk.record_trade(trade)
        
        self.logger.info(
            f"[模拟套利成交] {question[:50]} | 总成本 ${total_cost:.2f} | "
            f"预期利润 ${profit:.2f} | 余额 ${self.paper_ledger.balance:.2f}"
        )
        
        return True, f"模拟套利成功: {msg1}; {msg2}"
    
    def _live_execute_arbitrage(self, market: Dict, size_per_side: float) -> Tuple[bool, str]:
        """实盘执行套利（风险提示：非原子性）"""
        self.logger.warning(
            "[实盘套利警告] 套利需要同时成交两单，Polymarket 不支持原子多腿交易。\n"
            "  如果第一单成交后第二单失败，你将承担单边暴露风险。\n"
            "  建议小资金用户使用方向性策略（clueless_tailwind）。"
        )
        return False, "实盘套利暂未启用（建议使用方向性策略）"
    
    # ==================== 方向性交易执行 ====================
    
    def execute_directional(self, market: Dict, side: str, 
                            confidence: float) -> Tuple[bool, str]:
        """
        执行方向性交易（买 YES 或买 NO）
        
        side: "YES" or "NO"
        confidence: 置信度 0-1，影响仓位大小
        """
        market_id = market["id"]
        question = market["question"]
        
        token_id = market["yes_token_id"] if side == "YES" else market["no_token_id"]
        price = market["yes_price"] if side == "YES" else market["no_price"]
        
        # 根据置信度调整仓位
        size = self.risk.max_trade_size * confidence
        size = max(size, self.risk.min_trade_size)
        size = min(size, self.risk.max_trade_size)
        
        ok, reason = self.risk.validate_trade(
            market_id=market_id,
            side=f"BUY_{side}",
            size=size,
            expected_price=price
        )
        if not ok:
            return False, f"风控拒绝: {reason}"
        
        if self.dry_run:
            return self._paper_execute_directional(market, side, size, price, token_id)
        else:
            return self._live_execute_directional(market, side, size, price, token_id)
    
    def _paper_execute_directional(self, market: Dict, side: str,
                                    size: float, price: float, token_id: str) -> Tuple[bool, str]:
        """模拟执行方向性交易"""
        fees = size * self.estimated_fee_rate
        
        ok, msg, tid = self.paper_ledger.buy(
            market_id=market["id"],
            market_question=market["question"],
            side=f"BUY_{side}",
            token_id=token_id,
            price=price,
            size_usdc=size,
            fees=fees
        )
        if not ok:
            return False, msg
        
        trade = TradeRecord(
            trade_id=tid,
            timestamp=datetime.now(),
            market_id=market["id"],
            side=f"BUY_{side}",
            size=size + fees,
            price=price,
            expected_profit=0,
            strategy="directional"
        )
        self.risk.record_trade(trade)
        
        self.logger.info(f"[模拟方向性成交] {side} {market['question'][:50]} | ${size:.2f} @ ${price:.4f}")
        return True, msg
    
    def _live_execute_directional(self, market: Dict, side: str,
                                   size: float, price: float, token_id: str) -> Tuple[bool, str]:
        """实盘执行方向性交易"""
        try:
            live = self._get_live_client()
            
            self.logger.info(
                f"[实盘下单准备] {side} {market['question'][:50]} | "
                f"金额 ${size:.2f} | 预期价格 ${price:.4f}"
            )
            
            # 使用市价单(FOK)确保快速成交
            # amount_usdc = size，FOK = 要么全成要么取消
            success, msg, resp = live.place_market_order(
                token_id=token_id,
                amount_usdc=size,
                side="BUY"
            )
            
            if success:
                # 记录到风控
                trade = TradeRecord(
                    trade_id=resp.get("orderID", str(uuid.uuid4())) if resp else str(uuid.uuid4()),
                    timestamp=datetime.now(),
                    market_id=market["id"],
                    side=f"BUY_{side}",
                    size=size,
                    price=price,
                    expected_profit=0,
                    strategy="directional_live"
                )
                self.risk.record_trade(trade)
                
                self.logger.info(f"[实盘成交] {msg}")
                return True, f"实盘成交: {msg}"
            else:
                self.logger.warning(f"[实盘未成交] {msg}")
                return False, f"实盘未成交: {msg}"
                
        except Exception as e:
            self.logger.error(f"[实盘下单异常] {e}")
            return False, f"实盘下单异常: {e}"
    
    # ==================== 状态查询 ====================
    
    def get_portfolio_summary(self) -> str:
        """获取账户摘要（文本格式）"""
        if self.dry_run:
            p = self.paper_ledger.get_portfolio()
            lines = [
                "=" * 50,
                " 模拟交易账户状态",
                "=" * 50,
                f" 初始资金: ${p['initial_balance']:.2f}",
                f" 当前余额: ${p['current_balance']:.2f}",
                f" 总盈亏:   ${p['total_pnl']:.2f} ({p['roi_pct']:.1f}%)",
                f" 持仓数:   {p['open_positions']}",
                f" 总交易:   {p['total_trades']}",
                "-" * 50,
            ]
            
            if p['positions']:
                lines.append(" 当前持仓:")
                for pos in p['positions']:
                    lines.append(f"   - {pos['side']} | ${pos['entry_price']:.3f} | {pos['shares']:.2f}股")
            
            lines.append("=" * 50)
            return "\n".join(lines)
        else:
            try:
                live = self._get_live_client()
                balance = live.get_balance()
                open_orders = live.get_open_orders()
                return (
                    f"实盘账户:\n"
                    f"  pUSD 余额: ${balance:.2f}\n"
                    f"  未成交订单: {len(open_orders)}"
                )
            except Exception as e:
                return f"实盘账户查询失败: {e}"
    
    def print_trade_history(self, limit: int = 10):
        """打印最近交易记录"""
        if not self.dry_run:
            print("实盘交易记录请通过 Polymarket 前端或 API 查询")
            return
        
        history = self.paper_ledger.get_trade_history(limit)
        if not history:
            print("暂无交易记录")
            return
        
        print("\n最近交易记录:")
        print("-" * 80)
        for t in history:
            pnl_str = f"${t['pnl']:.2f}" if t['pnl'] is not None else "持仓中"
            print(f"[{t['status']}] {t['time']} | {t['side']} | ${t['price']:.3f} | {pnl_str}")
            print(f"  -> {t['market']}")
        print("-" * 80)
