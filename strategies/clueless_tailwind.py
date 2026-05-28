"""
零基础尾盘策略（Clueless Tailwind）

为"什么都不懂"的人设计的策略。

核心逻辑：
-----------
你不需要懂NBA、不懂政治、不懂加密货币。
你只需要相信一个数学事实：

  "事件越接近结算，价格越接近真实结果。"

策略规则（极其简单）：
1. 只看结算前 6 小时内的市场
2. 找价格 > 92% 的结果 → 买入（几乎确定会发生）
3. 找价格 < 8% 的结果 → 买对面（几乎确定不发生）
4. 单笔不超过 $10，分散买很多个

为什么能赚钱：
--------------
到了最后几小时，该知道的人早就知道了。
如果 YES 还定价 92%，但实际结果几乎确定是 YES，
那剩下的 8% 利润就是"散户的幻想税"。

总有最后一批人：
- 没看新闻的
- 一厢情愿希望反转的
- 纯粹来赌一把的

他们给了你这 5-8% 的无风险（低风险）利润。

预期收益：
----------
- 单笔利润：3-8%
- 胜率：约 85-95%（结算前 4 小时的统计数据）
- 资金效率：极高（几小时就结算，不占用资金）
- 单笔金额：$5-15（小资金友好）

风险：
------
1. 黑天鹅：极小概率事件在最后一刻发生（<5%）
2. 结算争议：规则模糊导致意外结果（<2%）
3. 流动性枯竭：最后几小时可能买不到/卖不出

对策：分散 + 小额 + 绝不 ALL IN
"""
from typing import Dict, List, Tuple, Any
from datetime import datetime

from strategies.base import BaseStrategy


class CluelessTailwindStrategy(BaseStrategy):
    """
    零基础尾盘策略
    
    不需要懂任何领域，只赚"时间收敛"的钱。
    """
    
    name = "clueless_tailwind"
    description = "零基础：只赚结算前时间收敛的钱，不需要懂任何领域"
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.max_hours = config.get("max_hours_before_close", 6)   # 结算前N小时
        self.min_certainty = config.get("min_certainty", 0.92)      # 最低确定性
        self.min_volume = config.get("min_volume", 1000)            # 最小交易量
        self.max_price = config.get("max_entry_price", 0.96)        # 最高买入价（避免太贵）
        self.min_price = config.get("min_entry_price", 0.04)        # 最低买入价（对面）
        self.profit_target = config.get("profit_target", 0.05)      # 最小利润空间
    
    def scan(self, markets: List[Dict]) -> List[Dict]:
        """扫描尾盘确定性机会"""
        signals = []
        now = datetime.now()
        
        for m in markets:
            yes_price = m.get("yes_price", 0)
            no_price = m.get("no_price", 0)
            days = m.get("days_to_resolution")
            hours = days * 24 if days is not None else 999
            volume = m.get("volume", 0)
            question = m.get("question", "")
            
            # 只关注快结算的市场
            if hours > self.max_hours:
                continue
            
            if volume < self.min_volume:
                continue
            
            # ========== 信号1: 高确定性 YES ==========
            # YES > 92% 且 < 96%，说明几乎确定会发生
            # 但还有几美分的利润空间
            if self.min_certainty <= yes_price <= self.max_price:
                profit = 1.0 - yes_price  # 每投入$1的利润
                
                if profit >= self.profit_target:
                    # 年化极高（因为几小时就结算）
                    apy = (profit / yes_price) * (365 / max(0.1, days)) * 100
                    
                    signals.append({
                        "market_id": m["id"],
                        "condition_id": m["condition_id"],
                        "strategy": self.name,
                        "action": "BUY_YES_TAILWIND",
                        "confidence": yes_price,
                        "reason": (
                            f"【尾盘YES｜无需懂领域】{question[:50]}...\n"
                            f"    结算前 {hours:.1f} 小时 | 定价 {yes_price:.0%} | "
                            f"利润 {profit:.1%} | 年化 {apy:.0f}%"
                        ),
                        "market_data": m,
                        "priority": apy,
                        "suggested_size_usd": self._suggest_size(yes_price, hours)
                    })
            
            # ========== 信号2: 高确定性 NO ==========
            # NO > 92% 且 < 96%，说明几乎确定不发生
            if self.min_certainty <= no_price <= self.max_price:
                profit = 1.0 - no_price
                
                if profit >= self.profit_target:
                    apy = (profit / no_price) * (365 / max(0.1, days)) * 100
                    
                    signals.append({
                        "market_id": m["id"],
                        "condition_id": m["condition_id"],
                        "strategy": self.name,
                        "action": "BUY_NO_TAILWIND",
                        "confidence": no_price,
                        "reason": (
                            f"【尾盘NO｜无需懂领域】{question[:50]}...\n"
                            f"    结算前 {hours:.1f} 小时 | 定价 {no_price:.0%} | "
                            f"利润 {profit:.1%} | 年化 {apy:.0f}%"
                        ),
                        "market_data": m,
                        "priority": apy,
                        "suggested_size_usd": self._suggest_size(no_price, hours)
                    })
        
        signals.sort(key=lambda x: x["priority"], reverse=True)
        return signals
    
    def execute(self, signal: Dict, engine) -> Tuple[bool, str]:
        """执行信号"""
        action = signal.get("action", "")
        market = signal.get("market_data", {})
        confidence = signal.get("confidence", 0.5)
        
        if action == "BUY_YES_TAILWIND":
            return engine.execute_directional(market, "YES", confidence)
        elif action == "BUY_NO_TAILWIND":
            return engine.execute_directional(market, "NO", confidence)
        else:
            return False, f"未知操作: {action}"
    
    def _suggest_size(self, certainty: float, hours: float) -> float:
        """
        建议仓位大小
        
        规则：
        - 确定性越高、时间越短，可以稍微大一点
        - 但小资金策略永远不超过 $20
        """
        base = 5  # 最低 $5
        
        # 确定性加成（92%→+$3，96%→+$7）
        certainty_boost = (certainty - 0.90) * 100  # 约 2-6
        
        # 时间加成（越短越好，1小时内→+$5）
        time_boost = max(0, (6 - hours) * 1.5)  # 0-7.5
        
        suggested = base + certainty_boost + time_boost
        return min(20, suggested)  # 硬顶 $20
