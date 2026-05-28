"""
模拟交易（Paper Trading）模块
用于在不使用真实资金的情况下测试策略逻辑
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime
import json
import os


@dataclass
class PaperPosition:
    """模拟持仓"""
    market_id: str
    market_question: str
    side: str  # BUY_YES or BUY_NO
    token_id: str
    entry_price: float
    size_usdc: float
    shares: float
    entry_time: datetime
    
    @property
    def unrealized_pnl(self, current_price: float = 0) -> float:
        if self.side == "BUY_YES":
            return self.shares * (current_price - self.entry_price)
        else:  # BUY_NO
            return self.shares * (current_price - self.entry_price)


@dataclass
class PaperTrade:
    """模拟成交记录"""
    trade_id: str
    timestamp: datetime
    market_id: str
    market_question: str
    side: str
    token_id: str
    price: float
    size_usdc: float
    shares: float
    fees: float
    pnl: Optional[float] = None
    status: str = "OPEN"  # OPEN / CLOSED


class PaperTradingLedger:
    """
    模拟交易账本
    
    模拟 Polymarket 的交易行为：
    - 买入时扣除 USDC
    - 持仓到结算时按 $1/股 结算正确结果
    - 记录所有交易和盈亏
    """
    
    def __init__(self, initial_balance: float = 1000.0):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.positions: Dict[str, PaperPosition] = {}  # market_id -> position
        self.trades: List[PaperTrade] = []
        self.total_pnl = 0.0
        self.trade_counter = 0
        
        self._load_state()
    
    def _state_file(self) -> str:
        return "logs/paper_trading_state.json"
    
    def _load_state(self):
        if os.path.exists(self._state_file()):
            try:
                with open(self._state_file(), 'r') as f:
                    data = json.load(f)
                self.balance = data.get("balance", self.initial_balance)
                self.total_pnl = data.get("total_pnl", 0.0)
                # 简化：不恢复持仓状态，每次重启重新扫描
            except Exception:
                pass
    
    def _save_state(self):
        os.makedirs("logs", exist_ok=True)
        data = {
            "balance": round(self.balance, 2),
            "total_pnl": round(self.total_pnl, 2),
            "open_positions": len(self.positions),
            "total_trades": len(self.trades)
        }
        with open(self._state_file(), 'w') as f:
            json.dump(data, f, indent=2)
    
    def _next_trade_id(self) -> str:
        self.trade_counter += 1
        return f"PAPER_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{self.trade_counter}"
    
    def buy(self, market_id: str, market_question: str, 
            side: str, token_id: str, price: float, 
            size_usdc: float, fees: float = 0) -> tuple[bool, str, Optional[str]]:
        """
        模拟买入
        
        Returns: (是否成功, 原因, trade_id)
        """
        total_cost = size_usdc + fees
        
        if total_cost > self.balance:
            return False, f"余额不足: 需要 {total_cost:.2f}, 剩余 {self.balance:.2f}", None
        
        shares = size_usdc / price if price > 0 else 0
        
        trade_id = self._next_trade_id()
        trade = PaperTrade(
            trade_id=trade_id,
            timestamp=datetime.now(),
            market_id=market_id,
            market_question=market_question,
            side=side,
            token_id=token_id,
            price=price,
            size_usdc=size_usdc,
            shares=shares,
            fees=fees
        )
        
        position = PaperPosition(
            market_id=market_id,
            market_question=market_question,
            side=side,
            token_id=token_id,
            entry_price=price,
            size_usdc=size_usdc,
            shares=shares,
            entry_time=datetime.now()
        )
        
        self.balance -= total_cost
        self.positions[market_id] = position
        self.trades.append(trade)
        self._save_state()
        
        return True, f"模拟买入成功: {side} {shares:.2f}股 @ ${price:.4f}, 成本 ${total_cost:.2f}", trade_id
    
    def sell(self, market_id: str, current_price: float) -> tuple[bool, str, float]:
        """
        模拟卖出/平仓
        
        Returns: (是否成功, 原因, 实现盈亏)
        """
        if market_id not in self.positions:
            return False, f"市场 {market_id} 无持仓", 0.0
        
        pos = self.positions[market_id]
        
        # 计算盈亏
        if pos.side == "BUY_YES":
            realized_pnl = pos.shares * (current_price - pos.entry_price)
        else:  # BUY_NO
            realized_pnl = pos.shares * (current_price - pos.entry_price)
        
        proceeds = pos.shares * current_price
        self.balance += proceeds
        self.total_pnl += realized_pnl
        
        # 更新交易记录
        for t in self.trades:
            if t.market_id == market_id and t.status == "OPEN":
                t.pnl = realized_pnl
                t.status = "CLOSED"
                break
        
        del self.positions[market_id]
        self._save_state()
        
        return True, f"模拟平仓成功: 盈亏 ${realized_pnl:.2f}, 余额 ${self.balance:.2f}", realized_pnl
    
    def settle(self, market_id: str, outcome: str) -> tuple[bool, str, float]:
        """
        模拟结算（事件结果揭晓）
        
        outcome: "YES" or "NO"
        
        Returns: (是否成功, 原因, 实现盈亏)
        """
        if market_id not in self.positions:
            return False, f"市场 {market_id} 无持仓", 0.0
        
        pos = self.positions[market_id]
        
        # 结算价：正确结果=$1，错误结果=$0
        if pos.side == "BUY_YES":
            settlement_price = 1.0 if outcome == "YES" else 0.0
        else:  # BUY_NO
            settlement_price = 1.0 if outcome == "NO" else 0.0
        
        realized_pnl = pos.shares * (settlement_price - pos.entry_price)
        proceeds = pos.shares * settlement_price
        
        self.balance += proceeds
        self.total_pnl += realized_pnl
        
        for t in self.trades:
            if t.market_id == market_id and t.status == "OPEN":
                t.pnl = realized_pnl
                t.status = "SETTLED"
                break
        
        del self.positions[market_id]
        self._save_state()
        
        result = "盈利" if realized_pnl > 0 else "亏损" if realized_pnl < 0 else "持平"
        return True, f"模拟结算成功 [{result}]: 盈亏 ${realized_pnl:.2f}, 余额 ${self.balance:.2f}", realized_pnl
    
    def get_portfolio(self) -> Dict:
        """获取当前模拟账户状态"""
        return {
            "initial_balance": self.initial_balance,
            "current_balance": round(self.balance, 2),
            "total_pnl": round(self.total_pnl, 2),
            "roi_pct": round((self.total_pnl / self.initial_balance) * 100, 2) if self.initial_balance else 0,
            "open_positions": len(self.positions),
            "total_trades": len(self.trades),
            "positions": [
                {
                    "market": p.market_question,
                    "side": p.side,
                    "entry_price": p.entry_price,
                    "shares": round(p.shares, 4),
                    "cost": p.size_usdc
                }
                for p in self.positions.values()
            ]
        }
    
    def get_trade_history(self, limit: int = 20) -> List[Dict]:
        """获取最近的交易记录"""
        recent = self.trades[-limit:]
        return [
            {
                "id": t.trade_id,
                "time": t.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "market": t.market_question[:50] + "..." if len(t.market_question) > 50 else t.market_question,
                "side": t.side,
                "price": t.price,
                "shares": round(t.shares, 4),
                "cost": t.size_usdc,
                "pnl": round(t.pnl, 2) if t.pnl is not None else None,
                "status": t.status
            }
            for t in reversed(recent)
        ]
