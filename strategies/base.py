"""
策略基类
所有策略必须继承此类并实现 scan() 和 execute() 方法
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Tuple, Any


class BaseStrategy(ABC):
    """
    策略基类
    
    子类需要实现：
    - name: 策略名称
    - description: 策略描述
    - scan(markets) -> List[Dict]: 扫描市场，返回交易信号列表
    - execute(signal, engine) -> Tuple[bool, str]: 执行单个信号
    """
    
    name = "base"
    description = "策略基类"
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.enabled = True
    
    @abstractmethod
    def scan(self, markets: List[Dict]) -> List[Dict]:
        """
        扫描市场，发现交易机会
        
        Args:
            markets: 市场列表（由 PolymarketClient 格式化后的数据）
        
        Returns:
            交易信号列表，每个信号是一个字典，至少包含：
            - market_id: 市场ID
            - strategy: 策略名称
            - action: 操作类型（如 ARBITRAGE, BUY_YES, BUY_NO）
            - confidence: 置信度 0-1
            - reason: 触发原因说明
        """
        pass
    
    @abstractmethod
    def execute(self, signal: Dict, engine) -> Tuple[bool, str]:
        """
        执行交易信号
        
        Args:
            signal: scan() 返回的信号字典
            engine: ExecutionEngine 实例
        
        Returns:
            (是否成功, 结果描述)
        """
        pass
    
    def on_market_update(self, market: Dict):
        """
        市场数据更新时的回调（可选）
        用于需要实时跟踪持仓的策略
        """
        pass
    
    def get_status(self) -> Dict:
        """返回策略当前状态"""
        return {
            "name": self.name,
            "enabled": self.enabled,
            "config": self.config
        }
