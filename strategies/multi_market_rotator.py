"""
多市场尾盘轮换策略（方案 B）

专为小资金、高资金利用率设计。

核心逻辑：
-----------
1. 不限类别：扫遍 crypto、sports、politics、economics、culture、tech... 所有市场
2. 只看快结算的：48 小时内出结果
3. 按确定性分级：
   - 4小时内：确定性 > 95%
   - 4-24小时：确定性 > 90%
   - 24-48小时：确定性 > 85%
4. 资金轮换：优先投入最快结算的市场，释放后再找下一个

资金利用率优化：
-----------------
- 不把钱锁在长期市场
- 哪里快结算就往哪里投
- 一笔资金一天可能转 2-3 轮

配置项（config.yaml strategy.multi_market_rotator）：
- max_hours: 最大结算等待时间（48小时）
- certainty_tiers: 按时间分级的确定性门槛
- min_volume: 最小交易量
- max_positions: 同时持仓上限（防止资金全锁住）
"""
from typing import Dict, List, Tuple, Any
from datetime import datetime

from strategies.base import BaseStrategy


class MultiMarketRotator(BaseStrategy):
    """
    多市场尾盘轮换策略
    
    不看类别，只看结算时间 + 确定性。
    """
    
    name = "multi_market_rotator"
    description = "多市场尾盘轮换：扫遍所有类别，只追快结算的高确定性机会"
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.max_hours = config.get("max_hours", 48)
        self.min_volume = config.get("min_volume", 500)
        
        # 按时间分级的确定性门槛（越短确定性要求越高）
        self.certainty_tiers = [
            (4, 0.95),      # 4小时内：>95%
            (24, 0.90),     # 24小时内：>90%
            (48, 0.85),     # 48小时内：>85%
        ]
        
        # 利润门槛（按年化思维）
        # 4小时赚3% = 年化 6570%，值得
        # 48小时赚3% = 年化 547%，也值得
        self.profit_target = config.get("profit_target", 0.03)
    
    def scan(self, markets: List[Dict]) -> List[Dict]:
        """扫描所有快结算市场"""
        signals = []
        now = datetime.now()
        
        for m in markets:
            yes_price = m.get("yes_price", 0)
            no_price = m.get("no_price", 0)
            days = m.get("days_to_resolution")
            hours = days * 24 if days is not None else 999
            volume = m.get("volume", 0)
            question = m.get("question", "")
            category = m.get("category", "")
            tags = m.get("tags", [])
            
            # 1. 基础过滤
            if hours > self.max_hours:
                continue
            if volume < self.min_volume:
                continue
            
            # 2. 确定适用的确定性门槛
            min_certainty = 0.95  # 默认最严格
            for max_h, threshold in self.certainty_tiers:
                if hours <= max_h:
                    min_certainty = threshold
                    break
            
            # 3. 找高确定性机会
            
            # 场景A: YES 高度确定
            if yes_price >= min_certainty and yes_price <= 0.99:
                profit = 1.0 - yes_price
                if profit >= self.profit_target:
                    signals.append(self._build_signal(
                        m, "BUY_YES", yes_price, hours, profit,
                        f"YES确定性 {yes_price:.0%} | 结算前 {hours:.1f}h | 利润 {profit:.1%}",
                        category
                    ))
            
            # 场景B: NO 高度确定
            if no_price >= min_certainty and no_price <= 0.99:
                profit = 1.0 - no_price
                if profit >= self.profit_target:
                    signals.append(self._build_signal(
                        m, "BUY_NO", no_price, hours, profit,
                        f"NO确定性 {no_price:.0%} | 结算前 {hours:.1f}h | 利润 {profit:.1%}",
                        category
                    ))
        
        # 排序：按结算时间升序（最快结算的优先）
        signals.sort(key=lambda x: x.get("hours_to_res", 999))
        return signals
    
    def _build_signal(self, market: Dict, action: str, price: float,
                      hours: float, profit: float, reason: str,
                      category: str) -> Dict:
        """构建交易信号"""
        # 估算年化
        holding_days = max(0.1, hours / 24)
        apy = (profit / price) * (365 / holding_days) * 100
        
        # 建议仓位（确定性越高、时间越短，仓位越大）
        confidence = price
        suggested_size = self._suggest_size(confidence, hours)
        
        return {
            "market_id": market["id"],
            "condition_id": market["condition_id"],
            "strategy": self.name,
            "action": action,
            "confidence": confidence,
            "reason": f"【{category}】{market['question'][:50]}... | {reason}",
            "market_data": market,
            "hours_to_res": hours,
            "profit_margin": profit,
            "apy": apy,
            "priority": -hours,  # 负数：时间越短优先级越高
            "suggested_size_usd": suggested_size
        }
    
    def execute(self, signal: Dict, engine) -> Tuple[bool, str]:
        """执行信号"""
        action = signal.get("action", "")
        market = signal.get("market_data", {})
        confidence = signal.get("confidence", 0.5)
        
        if action == "BUY_YES":
            return engine.execute_directional(market, "YES", confidence)
        elif action == "BUY_NO":
            return engine.execute_directional(market, "NO", confidence)
        else:
            return False, f"未知操作: {action}"
    
    def _suggest_size(self, confidence: float, hours: float) -> float:
        """
        建议仓位大小
        
        规则：
        - 基础 $10
        - 确定性加成（90%→+$5, 95%→+$10）
        - 时间加成（越短越大）
        """
        base = 10
        confidence_boost = (confidence - 0.80) * 50  # 90%=+$5, 95%=+$7.5
        time_boost = max(0, (self.max_hours - hours) * 0.3)  # 48h=0, 1h=+$14
        
        suggested = base + confidence_boost + time_boost
        return min(50, max(5, suggested))  # 硬顶 $50，硬底 $5
