"""
Polymarket API 客户端封装
支持 Gamma API（公开市场数据）和 CLOB API（交易）
"""
import time
import requests
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone


class GammaAPIClient:
    """Gamma API 客户端 - 用于获取市场元数据和价格（无需认证）"""
    
    def __init__(self, host: str = "https://gamma-api.polymarket.com", timeout: int = 15):
        self.host = host.rstrip('/')
        self.timeout = timeout
        self.session = requests.Session()
        self._last_request_time = 0
        self._min_interval = 0.2  # 请求间隔秒数，避免限流
    
    def _rate_limited_get(self, endpoint: str, params: Optional[Dict] = None) -> Any:
        """带速率限制的 GET 请求"""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        
        url = f"{self.host}{endpoint}"
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            self._last_request_time = time.time()
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Gamma API 请求失败: {url} - {e}")
    
    def get_markets(self, active: bool = True, closed: bool = False, 
                    limit: int = 50, offset: int = 0,
                    category: Optional[str] = None) -> List[Dict]:
        """获取市场列表"""
        params = {
            "active": str(active).lower(),
            "closed": str(closed).lower(),
            "limit": limit,
            "offset": offset
        }
        if category:
            params["tag"] = category
        
        data = self._rate_limited_get("/markets", params)
        return data if isinstance(data, list) else data.get("markets", [])
    
    def get_market_by_id(self, market_id: str) -> Optional[Dict]:
        """获取单个市场详情"""
        try:
            return self._rate_limited_get(f"/markets/{market_id}")
        except ConnectionError:
            return None


class ClobAPIClient:
    """CLOB API 客户端 - 用于订单簿和交易（需要认证）"""
    
    def __init__(self, host: str = "https://clob.polymarket.com", 
                 timeout: int = 15, api_key: Optional[str] = None):
        self.host = host.rstrip('/')
        self.timeout = timeout
        self.api_key = api_key
        self.session = requests.Session()
        self._last_request_time = 0
        self._min_interval = 0.5
    
    def _headers(self) -> Dict[str, str]:
        """构建请求头"""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["POLY_API_KEY"] = self.api_key
        return headers
    
    def _rate_limited_request(self, method: str, endpoint: str, 
                               params: Optional[Dict] = None,
                               json_data: Optional[Dict] = None) -> Any:
        """带速率限制的通用请求"""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        
        url = f"{self.host}{endpoint}"
        try:
            resp = self.session.request(
                method, url, params=params, json=json_data,
                headers=self._headers(), timeout=self.timeout
            )
            self._last_request_time = time.time()
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"CLOB API 请求失败: {url} - {e}")
    
    def get_orderbook(self, token_id: str) -> Dict:
        """获取订单簿"""
        return self._rate_limited_request("GET", f"/book/{token_id}")
    
    def get_price(self, token_id: str, side: str = "BUY") -> Optional[float]:
        """获取最优报价"""
        try:
            data = self._rate_limited_request(
                "GET", f"/price", {"token_id": token_id, "side": side}
            )
            return float(data) if data else None
        except Exception:
            return None
    
    def get_midpoint(self, token_id: str) -> Optional[float]:
        """获取中间价"""
        try:
            data = self._rate_limited_request("GET", f"/midpoint", {"token_id": token_id})
            return float(data) if data else None
        except Exception:
            return None
    
    def get_spread(self, token_id: str) -> Optional[Dict]:
        """获取买卖价差"""
        try:
            return self._rate_limited_request("GET", f"/spread", {"token_id": token_id})
        except Exception:
            return None
    
    def get_market_info(self, condition_id: str) -> Dict:
        """获取市场微观结构信息（tick size, fees等）"""
        return self._rate_limited_request("GET", f"/markets/{condition_id}")


class PolymarketClient:
    """统一客户端：整合 Gamma + CLOB API"""
    
    def __init__(self, config: Dict[str, Any]):
        self.gamma = GammaAPIClient(
            host=config.get("gamma_host", "https://gamma-api.polymarket.com"),
            timeout=config.get("timeout", 15)
        )
        self.clob = ClobAPIClient(
            host=config.get("clob_host", "https://clob.polymarket.com"),
            timeout=config.get("timeout", 15),
            api_key=config.get("api_key")
        )
        self.logger = None
    
    def get_active_binary_markets(self, limit: int = 50, 
                                   min_volume: float = 0,
                                   max_days: int = 365,
                                   categories: Optional[List[str]] = None) -> List[Dict]:
        """
        获取活跃的二元市场（YES/NO），带过滤条件
        """
        markets_raw = self.gamma.get_markets(active=True, closed=False, limit=limit)
        
        # 调试日志
        if self.logger:
            self.logger.info(f"[DEBUG] Gamma API 返回 {len(markets_raw)} 个原始市场")
            if markets_raw:
                sample = markets_raw[0]
                self.logger.info(f"[DEBUG] 第一个市场的 keys: {list(sample.keys())[:15]}")
                self.logger.info(f"[DEBUG] 第一个市场 active={sample.get('active')} closed={sample.get('closed')} archived={sample.get('archived')}")
                self.logger.info(f"[DEBUG] 第一个市场 outcomes={sample.get('outcomes')} clobTokenIds={sample.get('clobTokenIds')}")
        
        results = []
        now = datetime.now(timezone.utc)
        
        for m in markets_raw:
            # 放宽 active/closed 检查，有些市场可能没有这些字段
            if m.get("archived") is True:
                continue
            
            outcomes = m.get("outcomes", [])
            if len(outcomes) != 2:
                continue
            
            if categories:
                tags = [t.lower() for t in m.get("tags", [])]
                if not any(c.lower() in tags for c in categories):
                    continue
            
            volume = float(m.get("volume", 0) or 0)
            if volume < min_volume:
                continue
            
            end_date_raw = m.get("endDate") or m.get("resolutionDate")
            days_to_res = None
            if end_date_raw:
                try:
                    end_date = datetime.fromisoformat(end_date_raw.replace('Z', '+00:00'))
                    days_to_res = (end_date - now).days
                    if days_to_res > max_days or days_to_res < 0:
                        continue
                except Exception:
                    pass
            
            clob_tokens = m.get("clobTokenIds", [])
            if len(clob_tokens) < 2:
                continue
            
            yes_token = clob_tokens[0]
            no_token = clob_tokens[1]
            
            yes_price = self.clob.get_midpoint(yes_token)
            no_price = self.clob.get_midpoint(no_token)
            
            if yes_price is None or no_price is None:
                continue
            
            results.append({
                "id": m.get("id"),
                "condition_id": m.get("conditionId"),
                "question": m.get("question"),
                "slug": m.get("slug"),
                "yes_token_id": yes_token,
                "no_token_id": no_token,
                "yes_price": yes_price,
                "no_price": no_price,
                "sum_price": round(yes_price + no_price, 4),
                "volume": volume,
                "category": m.get("category", ""),
                "tags": m.get("tags", []),
                "end_date": end_date_raw,
                "days_to_resolution": days_to_res,
                "liquidity": float(m.get("liquidity", 0) or 0),
                "spread": abs(yes_price + no_price - 1.0)
            })
        
        return results
