"""
简单套利策略

核心逻辑：
1. 扫描所有活跃二元市场
2. 计算 YES + NO 价格总和
3. 若总和 < (1 - threshold)，则存在无风险套利空间
4. 同时买入两边，持有到结算稳赚差价

同时包含方向性交易的逻辑：
- 当发现某个结果被明显低估时（用户有信息优势时），可单独买入
"""
from typing import Dict, List, Tuple, Any
from datetime import datetime

from strategies.base import BaseStrategy


class SimpleArbitrageStrategy(BaseStrategy):
    """
    简单套利策略
    
    配置项（来自 config.yaml strategy.simple_arbitrage）：
    - threshold: 套利触发阈值（如 0.02 表示总和<0.98时触发）
    - min_apy_pct: 最小年化收益率要求
    - categories: 类别白名单
    - min_volume: 最小交易量过滤
    - max_days_to_resolution: 最大结算等待天数
    """
    
    name = "simple_arbitrage"
    description = "单市场内套利：YES+NO<$1时同时买入两边"
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.threshold = config.get("threshold", 0.02)
        self.min_apy_pct = config.get("min_apy_pct", 20)
        self.categories = config.get("categories", [])
        self.min_volume = config.get("min_volume", 1000)
        self.max_days = config.get("max_days_to_resolution", 30)
    
    def scan(self, markets: List[Dict]) -> List[Dict]:
        """
        扫描套利机会
        
        返回信号列表，按预期利润率排序
        """
        signals = []
        
        for m in markets:
            # 基础过滤已在 PolymarketClient 中完成
            # 这里只判断套利条件
            
            yes_price = m.get("yes_price", 0)
            no_price = m.get("no_price", 0)
            sum_price = m.get("sum_price", 1.0)
            days = m.get("days_to_resolution")
            volume = m.get("volume", 0)
            
            # 1. 套利检测：YES + NO < 1 - threshold
            profit_margin = 1.0 - sum_price
            
            if profit_margin >= self.threshold:
                # 计算年化收益率
                apy = self._calculate_apy(profit_margin, days)
                
                if apy >= self.min_apy_pct:
                    signals.append({
                        "market_id": m["id"],
                        "condition_id": m["condition_id"],
                        "strategy": self.name,
                        "action": "ARBITRAGE",
                        "confidence": min(profit_margin * 10, 0.95),  # 利润越大越确定
                        "reason": (
                            f"套利空间: YES(${yes_price:.4f}) + NO(${no_price:.4f}) = "
                            f"${sum_price:.4f} < 1.0 | 利润 ${profit_margin:.4f}/套 | "
                            f"年化 {apy:.0f}% | 交易量 ${volume:.0f}"
                        ),
                        "market_data": m,
                        "profit_margin": profit_margin,
                        "apy": apy,
                        "priority": apy  # 按年化排序
                    })
            
            # 2. 极端价格检测：某一侧<0.05的捡漏机会
            # 这类机会很少，但一旦发生可能有利可图
            if yes_price < 0.03 or no_price < 0.03:
                cheap_side = "YES" if yes_price < no_price else "NO"
                cheap_price = min(yes_price, no_price)
                
                signals.append({
                    "market_id": m["id"],
                    "condition_id": m["condition_id"],
                    "strategy": self.name,
                    "action": f"EXTREME_{cheap_side}",
                    "confidence": 0.3,  # 低置信度，仅提示
                    "reason": (
                        f"极端低价: {cheap_side}=${cheap_price:.4f} | "
                        f"{m['question'][:60]}..."
                    ),
                    "market_data": m,
                    "profit_margin": 0,
                    "apy": 0,
                    "priority": 0  # 低优先级
                })
        
        # 按年化收益率降序排列
        signals.sort(key=lambda x: x["priority"], reverse=True)
        return signals
    
    def execute(self, signal: Dict, engine) -> Tuple[bool, str]:
        """
        执行套利信号
        """
        action = signal.get("action", "")
        market = signal.get("market_data", {})
        
        if action == "ARBITRAGE":
            return engine.execute_arbitrage(market)
        
        elif action.startswith("EXTREME_"):
            # 极端价格只记录日志，不自动交易（风险太高）
            side = action.replace("EXTREME_", "")
            engine.logger.info(f"[极端价格提示] {side}=${market.get(side.lower()+'_price', 0):.4f} | {market.get('question', '')}")
            return False, "极端价格信号仅提示，不自动执行"
        
        return False, f"未知操作类型: {action}"
    
    def _calculate_apy(self, profit_margin: float, days: int) -> float:
        """
        计算年化收益率
        
        公式: APY = (profit_margin / sum_price) * (365 / days) * 100
        
        如果 days 未知，使用保守估计 30 天
        """
        if not days or days <= 0:
            days = 30  # 保守假设
        
        if days < 1:
            days = 1
        
        # 利润 / 投入成本 / 天数 * 365
        # 投入成本 = sum_price（同时买两边的总成本）
        holding_return = profit_margin  # 每投入$1的回报
        
        apy = (holding_return / max(0.5, 1.0 - profit_margin)) * (365.0 / days) * 100
        
        return max(0, apy)
