"""
NO 价值猎人策略 + 尾盘确定性捡漏

专为资金有限（<$1000）设计的策略。

核心逻辑：
-----------
1. 【NO 捡漏】散户偏爱买 YES（"万一中了赚10倍"），导致 NO 经常被低估。
   当 NO 的价格 < (1 - 真实概率) 时，买 NO 的期望值为正。
   简单说：市场认为"不发生"的概率比实际低，我们就买 NO。

2. 【尾盘确定性】事件快结算前（4-24小时），信息最充分。
   此时若价格与确定性结果仍有偏差（如99%会发生但定价只92¢），
   买入确定性一边，胜率极高。

3. 【小额分散】不押注单一市场，每次只投$5-20，买10-20个高胜率机会。
   靠大数定律盈利，不靠一次暴利。

为什么适合小资金：
------------------
- 不需要提供流动性（不用做市）
- 不需要低延迟VPS（不是毫秒级竞争）
- 单笔金额小，风控压力低
- 持仓周期短（尾盘策略几小时到几天）

配置项（config.yaml strategy.no_value_hunter）：
- no_max_price: NO 最高买入价（如 0.15 = 15美分）
- no_min_edge: 最小安全边际（如 0.10 = 要求真实概率比定价高10%）
- tailwind_hours: 尾盘窗口（如 24 = 只关注24小时内结算的市场）
- min_confidence: 最低置信度（0-1）
- categories: 你擅长的领域（只玩你懂的！）
"""
from typing import Dict, List, Tuple, Any
from datetime import datetime

from strategies.base import BaseStrategy


class NoValueHunterStrategy(BaseStrategy):
    """
    NO 价值猎人 + 尾盘确定性策略
    """
    
    name = "no_value_hunter"
    description = "小资金专精：买低估NO + 尾盘确定性捡漏"
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.no_max_price = config.get("no_max_price", 0.20)       # NO 最高买价
        self.no_min_edge = config.get("no_min_edge", 0.08)         # 最小安全边际
        self.tailwind_hours = config.get("tailwind_hours", 48)     # 尾盘时间窗口
        self.min_confidence = config.get("min_confidence", 0.75)   # 最低置信度
        self.categories = config.get("categories", [])
        self.min_volume = config.get("min_volume", 500)
    
    def scan(self, markets: List[Dict]) -> List[Dict]:
        """扫描高价值机会"""
        signals = []
        now = datetime.now()
        
        for m in markets:
            yes_price = m.get("yes_price", 0)
            no_price = m.get("no_price", 0)
            days = m.get("days_to_resolution")
            volume = m.get("volume", 0)
            question = m.get("question", "")
            
            if volume < self.min_volume:
                continue
            
            # ========== 信号1: 极端低价 NO 捡漏 ==========
            # 逻辑: NO < no_max_price，且 YES 被过度乐观推高
            # 典型场景: 大众热衷的事件（大选、名人八卦），YES被炒高
            if no_price <= self.no_max_price and yes_price >= 0.80:
                # 市场认为"不发生"的概率很低，但实际可能没那么确定
                # 这里我们给一个保守的"真实概率"估计
                # 如果 YES=85¢，意味着市场认为85%会发生
                # 但大众事件往往被高估，真实概率可能只有70%
                # 那么 NO 的公允价应该是 30¢，但市场只卖 15¢ → 低估50%
                
                estimated_true_yes = self._estimate_true_probability(question, yes_price)
                fair_no_price = 1.0 - estimated_true_yes
                edge = fair_no_price - no_price  # 安全边际
                
                if edge >= self.no_min_edge:
                    confidence = min(0.95, 0.5 + edge * 2)  # 安全边际越大越确定
                    
                    signals.append({
                        "market_id": m["id"],
                        "condition_id": m["condition_id"],
                        "strategy": self.name,
                        "action": "BUY_NO",
                        "confidence": confidence,
                        "reason": (
                            f"【NO捡漏】{question[:55]}... | "
                            f"YES被炒到{yes_price:.0%}，但估计真实只有{estimated_true_yes:.0%} | "
                            f"NO定价{no_price:.0%}，公允应{fair_no_price:.0%} | "
                            f"安全边际{edge:.1%}"
                        ),
                        "market_data": m,
                        "priority": edge * 100,
                        "suggested_size_usd": self._suggest_size(confidence, edge)
                    })
            
            # ========== 信号2: 尾盘确定性 ==========
            # 逻辑: 结算前X小时，价格应该很接近结果了
            # 但如果仍有 >5% 的偏差，就是捡漏机会
            if days is not None and days <= (self.tailwind_hours / 24):
                # 接近结算，找高确定性但定价未完全反映的机会
                
                # 场景A: 几乎确定会发生（YES > 90%），但定价 < 85%
                if yes_price >= 0.85 and yes_price < 0.95:
                    confidence = yes_price
                    signals.append({
                        "market_id": m["id"],
                        "condition_id": m["condition_id"],
                        "strategy": self.name,
                        "action": "BUY_YES_TAILWIND",
                        "confidence": confidence,
                        "reason": (
                            f"【尾盘YES】{question[:55]}... | "
                            f"结算前{days:.1f}天 | 定价{yes_price:.0%}，确定性高"
                        ),
                        "market_data": m,
                        "priority": confidence * 50,
                        "suggested_size_usd": self._suggest_size(confidence, 0.05)
                    })
                
                # 场景B: 几乎确定不发生（NO > 90%），但定价 < 85%
                if no_price >= 0.85 and no_price < 0.95:
                    confidence = no_price
                    signals.append({
                        "market_id": m["id"],
                        "condition_id": m["condition_id"],
                        "strategy": self.name,
                        "action": "BUY_NO_TAILWIND",
                        "confidence": confidence,
                        "reason": (
                            f"【尾盘NO】{question[:55]}... | "
                            f"结算前{days:.1f}天 | 定价{no_price:.0%}，确定性高"
                        ),
                        "market_data": m,
                        "priority": confidence * 50,
                        "suggested_size_usd": self._suggest_size(confidence, 0.05)
                    })
        
        # 按优先级排序
        signals.sort(key=lambda x: x["priority"], reverse=True)
        return signals
    
    def execute(self, signal: Dict, engine) -> Tuple[bool, str]:
        """执行信号"""
        action = signal.get("action", "")
        market = signal.get("market_data", {})
        confidence = signal.get("confidence", 0.5)
        suggested_size = signal.get("suggested_size_usd", 10)
        
        # 根据 confidence 调整金额
        if action.startswith("BUY_NO"):
            side = "NO"
        elif action.startswith("BUY_YES"):
            side = "YES"
        else:
            return False, f"未知操作: {action}"
        
        return engine.execute_directional(market, side, confidence)
    
    def _estimate_true_probability(self, question: str, market_yes_price: float) -> float:
        """
        估计真实概率（对抗市场泡沫）
        
        核心假设：大众热门事件中，YES 被系统性高估。
        我们用一个简单的"去泡沫"公式：
        - 如果 market_yes > 0.80，真实概率 = market_yes * 0.85（打折15%）
        - 如果 market_yes > 0.90，真实概率 = market_yes * 0.80（打折20%）
        
        这很粗糙，但比直接相信市场定价更安全。
        更好的做法：用户在自己的领域建立真实模型。
        """
        if market_yes_price > 0.90:
            return min(0.95, market_yes_price * 0.82)
        elif market_yes_price > 0.80:
            return min(0.90, market_yes_price * 0.88)
        else:
            return market_yes_price
    
    def _suggest_size(self, confidence: float, edge: float) -> float:
        """
        根据置信度和安全边际建议仓位
        
        小资金策略：绝不重注，永远分散
        """
        base = 10  # 基础金额 $10
        
        # 置信度加成
        confidence_boost = confidence * 10  # 最多+$10
        
        # 安全边际加成
        edge_boost = edge * 50  # edge=10% → +$5
        
        suggested = base + confidence_boost + edge_boost
        
        # 上限封顶
        return min(30, suggested)  # 单笔最多$30
