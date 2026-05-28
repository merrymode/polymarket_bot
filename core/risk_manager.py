"""
风险管理模块
核心职责：控制单笔风险、日亏损上限、持仓上限、滑点保护
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime, date
import json
import os


@dataclass
class TradeRecord:
    """单笔交易记录"""
    trade_id: str
    timestamp: datetime
    market_id: str
    side: str
    size: float
    price: float
    expected_profit: float
    strategy: str


@dataclass  
class DailyStats:
    """每日统计"""
    date: date
    trades_count: int = 0
    total_pnl: float = 0.0
    winning_trades: int = 0
    losing_trades: int = 0
    max_drawdown: float = 0.0


class RiskManager:
    """
    风控管理器
    """
    
    def __init__(self, config: Dict):
        self.max_trade_size = config.get("max_trade_size", 50)
        self.min_trade_size = config.get("min_trade_size", 5)
        self.max_daily_loss = config.get("max_daily_loss", 200)
        self.max_daily_trades = config.get("max_daily_trades", 20)
        self.max_open_positions = config.get("max_open_positions", 5)
        self.slippage_tolerance = config.get("slippage_tolerance", 0.02)
        self.stop_loss_pct = config.get("stop_loss_pct", 0.10)
        
        self.today = date.today()
        self.daily_stats = DailyStats(date=self.today)
        self.open_positions: Dict[str, Dict] = {}
        self.trade_history: List[TradeRecord] = []
        self.circuit_breaker_triggered = False
        self.kill_switch = False
        
        self._load_state()
    
    def _state_file(self) -> str:
        return "logs/risk_state.json"
    
    def _load_state(self):
        path = self._state_file()
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                saved_date = date.fromisoformat(data.get("date", str(self.today)))
                if saved_date == self.today:
                    self.daily_stats.trades_count = data.get("trades_count", 0)
                    self.daily_stats.total_pnl = data.get("total_pnl", 0.0)
            except Exception:
                pass
    
    def _save_state(self):
        os.makedirs("logs", exist_ok=True)
        data = {
            "date": str(self.today),
            "trades_count": self.daily_stats.trades_count,
            "total_pnl": self.daily_stats.total_pnl,
            "open_positions_count": len(self.open_positions),
            "circuit_breaker": self.circuit_breaker_triggered
        }
        with open(self._state_file(), 'w') as f:
            json.dump(data, f, indent=2)
    
    def can_trade(self) -> tuple[bool, str]:
        if date.today() != self.today:
            self.today = date.today()
            self.daily_stats = DailyStats(date=self.today)
            self.circuit_breaker_triggered = False
        
        if self.kill_switch:
            return False, "KILL_SWITCH: 手动停止"
        
        if self.circuit_breaker_triggered:
            return False, f"CIRCUIT_BREAKER: 日亏损已达 {self.max_daily_loss} USDC"
        
        if self.daily_stats.trades_count >= self.max_daily_trades:
            return False, f"日交易次数已达上限: {self.max_daily_trades}"
        
        if len(self.open_positions) >= self.max_open_positions:
            return False, f"持仓数已达上限: {self.max_open_positions}"
        
        if self.daily_stats.total_pnl <= -self.max_daily_loss:
            self.circuit_breaker_triggered = True
            self._save_state()
            return False, f"日亏损触发断路器: {self.daily_stats.total_pnl:.2f} USDC"
        
        return True, "OK"
    
    def validate_trade(self, market_id: str, side: str, 
                       size: float, expected_price: float) -> tuple[bool, str]:
        can_trade, reason = self.can_trade()
        if not can_trade:
            return False, reason
        
        if size < self.min_trade_size:
            return False, f"交易金额 {size} 低于最小限制 {self.min_trade_size}"
        
        if size > self.max_trade_size:
            return False, f"交易金额 {size} 超过最大限制 {self.max_trade_size}"
        
        if market_id in self.open_positions:
            return False, f"市场 {market_id} 已有持仓"
        
        if expected_price <= 0 or expected_price >= 1:
            return False, f"价格 {expected_price} 不合理"
        
        return True, "OK"
    
    def check_slippage(self, expected_price: float, 
                       execution_price: float) -> tuple[bool, float]:
        if expected_price <= 0:
            return False, 0
        
        slippage = abs(execution_price - expected_price) / expected_price
        acceptable = slippage <= self.slippage_tolerance
        return acceptable, slippage
    
    def record_trade(self, trade: TradeRecord):
        self.trade_history.append(trade)
        self.daily_stats.trades_count += 1
        
        if trade.side in ["BUY_YES", "BUY_NO"]:
            self.open_positions[trade.market_id] = {
                "entry_time": trade.timestamp,
                "side": trade.side,
                "size": trade.size,
                "entry_price": trade.price
            }
        
        self._save_state()
    
    def record_pnl(self, market_id: str, realized_pnl: float):
        self.daily_stats.total_pnl += realized_pnl
        
        if market_id in self.open_positions:
            del self.open_positions[market_id]
        
        if realized_pnl > 0:
            self.daily_stats.winning_trades += 1
        else:
            self.daily_stats.losing_trades += 1
        
        self._save_state()
    
    def trigger_kill_switch(self):
        self.kill_switch = True
        self._save_state()
    
    def reset_kill_switch(self):
        self.kill_switch = False
        self._save_state()
    
    def get_status(self) -> Dict:
        return {
            "date": str(self.today),
            "can_trade": self.can_trade()[0],
            "daily_pnl": round(self.daily_stats.total_pnl, 2),
            "daily_trades": self.daily_stats.trades_count,
            "open_positions": len(self.open_positions),
            "circuit_breaker": self.circuit_breaker_triggered,
            "kill_switch": self.kill_switch,
            "max_daily_loss": self.max_daily_loss,
            "max_trade_size": self.max_trade_size
        }
