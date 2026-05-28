"""
实盘交易客户端（Polymarket V2 CLOB）

使用 py-clob-client-v2 进行：
1. L1 钱包签名 → 派生 API Key
2. L2 HMAC 认证 → 下单/撤单/查余额

重要安全提示：
- 本模块只会在 DRY_RUN=false 时被调用
- 所有下单前会再次经过风控验证
- 支持限价单(GTC)和市价单(FOK)
- V2 抵押品为 pUSD（非 USDC.e）
"""
import os
from typing import Dict, Optional, Tuple
from datetime import datetime

from utils.logger import setup_logger

logger = setup_logger("LiveTrading", "logs/live_trading.log")


class LiveTradingClient:
    """
    Polymarket 实盘交易客户端
    
    初始化流程：
    1. 用私钥做 L1 EIP-712 签名，派生 API Key
    2. 用 API Key 初始化 L2 HMAC 认证客户端
    3. 后续所有交易通过 L2 客户端完成
    """
    
    def __init__(self, host: str, chain_id: int, private_key: str,
                 funder_address: str, signature_type: int = 0):
        """
        Args:
            host: CLOB API host, e.g. "https://clob.polymarket.com"
            chain_id: Polygon mainnet = 137
            private_key: 以太坊私钥（0x开头）
            funder_address: 资金地址（EOA 或 Proxy）
            signature_type: 0=EOA(MetaMask), 1=Email/Magic, 2=Browser Proxy
        """
        self.host = host
        self.chain_id = chain_id
        self.private_key = private_key
        self.funder_address = funder_address
        self.signature_type = signature_type
        
        self._client = None
        self._init_client()
    
    def _init_client(self):
        """初始化认证客户端"""
        try:
            from py_clob_client_v2 import ClobClient
            
            # Step 1: L1 auth - 派生 API credentials
            logger.info("正在派生 API Key...")
            temp_client = ClobClient(
                host=self.host,
                chain_id=self.chain_id,
                key=self.private_key
            )
            creds = temp_client.create_or_derive_api_key()
            logger.info(f"API Key 派生成功")
            
            # Step 2: L2 auth - 完整认证客户端
            self._client = ClobClient(
                host=self.host,
                chain_id=self.chain_id,
                key=self.private_key,
                creds=creds,
                signature_type=self.signature_type,
                funder=self.funder_address
            )
            logger.info("实盘客户端初始化完成")
            
        except ImportError:
            logger.error("未安装 py-clob-client-v2，请运行: pip install py-clob-client-v2")
            raise
        except Exception as e:
            logger.error(f"实盘客户端初始化失败: {e}")
            raise
    
    # ==================== 账户查询 ====================
    
    def get_balance(self) -> Optional[float]:
        """获取 pUSD 余额"""
        try:
            # py-clob-client-v2 的余额查询
            balance = self._client.get_balance()
            return float(balance) if balance else 0.0
        except Exception as e:
            logger.error(f"查询余额失败: {e}")
            return None
    
    def get_allowances(self) -> Dict:
        """获取 token allowances（检查是否已授权）"""
        try:
            return self._client.get_balance_allowance()
        except Exception as e:
            logger.error(f"查询授权失败: {e}")
            return {}
    
    # ==================== 下单 ====================
    
    def place_limit_order(self, token_id: str, price: float, 
                          size: float, side: str = "BUY") -> Tuple[bool, str, Optional[Dict]]:
        """
        下限价单（GTC - Good Till Cancelled）
        
        Args:
            token_id: 结果代币ID
            price: 限价（0.00 - 1.00）
            size: 购买股数
            side: BUY 或 SELL
        
        Returns:
            (是否成功, 消息, 订单详情)
        """
        try:
            from py_clob_client_v2 import OrderArgs, OrderType, Side, PartialCreateOrderOptions
            
            side_enum = Side.BUY if side.upper() == "BUY" else Side.SELL
            
            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=side_enum
            )
            
            logger.info(f"[实盘限价单] {side} {size}股 @ ${price:.4f} | token={token_id[:20]}...")
            
            resp = self._client.create_and_post_order(
                order_args=order_args,
                options=PartialCreateOrderOptions(tick_size="0.01"),
                order_type=OrderType.GTC
            )
            
            order_id = resp.get("orderID") if isinstance(resp, dict) else None
            logger.info(f"[实盘成交] 订单ID: {order_id}")
            
            return True, f"限价单已提交 | ID: {order_id}", resp
            
        except Exception as e:
            logger.error(f"限价单失败: {e}")
            return False, f"下单失败: {e}", None
    
    def place_market_order(self, token_id: str, amount_usdc: float,
                           side: str = "BUY") -> Tuple[bool, str, Optional[Dict]]:
        """
        下市价单（FOK - Fill or Kill）
        
        FOK = 要么全部成交，要么全部取消（防止部分成交后的库存风险）
        
        Args:
            token_id: 结果代币ID
            amount_usdc: 投入金额（USDC）
            side: BUY 或 SELL
        
        Returns:
            (是否成功, 消息, 订单详情)
        """
        try:
            from py_clob_client_v2 import MarketOrderArgs, OrderType, Side, PartialCreateOrderOptions
            
            side_enum = Side.BUY if side.upper() == "BUY" else Side.SELL
            
            order_args = MarketOrderArgs(
                token_id=token_id,
                amount=amount_usdc,
                side=side_enum,
                order_type=OrderType.FOK
            )
            
            logger.info(f"[实盘市价单] {side} ${amount_usdc:.2f} | token={token_id[:20]}...")
            
            resp = self._client.create_and_post_market_order(
                order_args=order_args,
                options=PartialCreateOrderOptions(tick_size="0.01"),
                order_type=OrderType.FOK
            )
            
            order_id = resp.get("orderID") if isinstance(resp, dict) else None
            status = resp.get("status", "UNKNOWN") if isinstance(resp, dict) else "UNKNOWN"
            
            if status == "MATCHED":
                logger.info(f"[实盘成交] 市价单全部成交 | ID: {order_id}")
                return True, f"市价单成交 | ID: {order_id}", resp
            elif status == "CANCELLED":
                logger.warning(f"[实盘取消] 市价单未完全成交已取消 | ID: {order_id}")
                return False, "市价单未完全成交（流动性不足）", resp
            else:
                logger.info(f"[实盘状态] {status} | ID: {order_id}")
                return True, f"订单状态: {status} | ID: {order_id}", resp
                
        except Exception as e:
            logger.error(f"市价单失败: {e}")
            return False, f"下单失败: {e}", None
    
    # ==================== 撤单 ====================
    
    def cancel_order(self, order_id: str) -> Tuple[bool, str]:
        """撤单"""
        try:
            self._client.cancel(order_id)
            logger.info(f"[实盘撤单] {order_id}")
            return True, f"已撤单: {order_id}"
        except Exception as e:
            logger.error(f"撤单失败: {e}")
            return False, f"撤单失败: {e}"
    
    def cancel_all_orders(self) -> Tuple[bool, str]:
        """撤销所有未成交订单"""
        try:
            self._client.cancel_all()
            logger.info("[实盘撤单] 全部未成交订单已撤销")
            return True, "全部撤单成功"
        except Exception as e:
            logger.error(f"全部撤单失败: {e}")
            return False, f"全部撤单失败: {e}"
    
    # ==================== 查询订单 ====================
    
    def get_open_orders(self) -> list:
        """获取未成交订单"""
        try:
            from py_clob_client_v2 import OpenOrderParams
            return self._client.get_orders(OpenOrderParams())
        except Exception as e:
            logger.error(f"查询订单失败: {e}")
            return []
    
    def get_order_status(self, order_id: str) -> Optional[Dict]:
        """查询订单状态"""
        try:
            # py-clob-client-v2 可能没有直接的 get_order 方法
            # 通过 get_orders 过滤
            orders = self.get_open_orders()
            for o in orders:
                if o.get("id") == order_id:
                    return o
            return None
        except Exception as e:
            logger.error(f"查询订单状态失败: {e}")
            return None
