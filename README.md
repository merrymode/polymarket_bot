# Polymarket 自动交易系统

一个模块化、可扩展的 Polymarket 预测市场自动交易框架。

## 系统特性

- **模拟交易优先**: 默认 `DRY_RUN=true`，不花真钱验证策略逻辑
- **模块化架构**: 策略、风控、执行引擎分离，易于扩展
- **内置风控**: 日亏损上限、持仓上限、单笔限额、断路器、Kill Switch
- **模拟账本**: 完整的 Paper Trading 系统，跟踪虚拟盈亏
- **单市场套利策略**: 自动扫描 YES+NO<$1 的套利机会
- **策略可插拔**: 继承 `BaseStrategy` 即可添加新策略

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填入你的钱包地址（模拟模式可不填）
```

### 3. 调整策略配置

编辑 `config.yaml`：

```yaml
trading:
  dry_run: true          # true=模拟，false=实盘（谨慎！）
  scan_interval: 10      # 扫描间隔（秒）
  max_open_positions: 5  # 最大持仓数

risk:
  max_trade_size: 50     # 单笔最大金额（USDC）
  max_daily_loss: 200    # 日亏损上限
  max_daily_trades: 20   # 日交易上限

strategy:
  active: simple_arbitrage
  simple_arbitrage:
    threshold: 0.02      # 套利触发阈值（总和<0.98）
    min_apy_pct: 20      # 最小年化收益率
    min_volume: 1000     # 最小市场交易量
    max_days_to_resolution: 30  # 最大等待结算天数
```

### 4. 快速测试（只扫描，不交易）

```bash
python main.py --test
```

输出示例：
```
Polymarket 套利扫描测试
获取 47 个活跃二元市场

套利空间最大的市场（前10个）：
利润: 3.2% | 总和: $0.9680
  YES=$0.4820 NO=$0.4860 | 量=$125000
  Will BTC hit $100K by end of 2025?

策略发现 3 个交易信号
```

### 5. 启动模拟交易

```bash
python main.py
```

系统会：
1. 每 10 秒扫描一次市场
2. 发现套利机会时模拟买入
3. 记录虚拟盈亏到 `logs/paper_trading_state.json`
4. 达到风控限制时自动停止

## 系统架构

```
main.py
  ├── PolymarketClient (API层)
  │     ├── GammaAPIClient   (市场数据)
  │     └── ClobAPIClient    (订单簿+交易)
  ├── RiskManager (风控层)
  │     ├── 日亏损断路器
  │     ├── 持仓上限
  │     ├── 单笔限额
  │     └── Kill Switch
  ├── ExecutionEngine (执行层)
  │     ├── 模拟交易账本 (PaperTradingLedger)
  │     └── 实盘下单接口 (预留)
  └── Strategy (策略层)
        └── SimpleArbitrageStrategy
              ├── 扫描: YES+NO < threshold
              └── 执行: 同时买入两边
```

## 核心代码说明

### 添加新策略

```python
from strategies.base import BaseStrategy

class MyStrategy(BaseStrategy):
    name = "my_strategy"
    description = "我的自定义策略"
    
    def scan(self, markets):
        signals = []
        for m in markets:
            # 你的逻辑...
            if condition_met:
                signals.append({
                    "market_id": m["id"],
                    "action": "BUY_YES",
                    "confidence": 0.8,
                    "reason": "原因说明",
                    "market_data": m
                })
        return signals
    
    def execute(self, signal, engine):
        if signal["action"] == "BUY_YES":
            return engine.execute_directional(
                signal["market_data"], "YES", signal["confidence"]
            )
        return False, "未执行"
```

然后在 `main.py` 中注册：

```python
if active_strategy_name == "my_strategy":
    self.strategy = MyStrategy(strategy_config.get("my_strategy", {}))
```

### 风控 API

```python
from core.risk_manager import RiskManager

risk = RiskManager(config)

# 检查是否可以交易
can_trade, reason = risk.can_trade()

# 验证单笔交易
ok, reason = risk.validate_trade(market_id, side, size, price)

# 紧急停止
risk.trigger_kill_switch()

# 查看状态
print(risk.get_status())
```

### 模拟交易 API

```python
from core.paper_trading import PaperTradingLedger

ledger = PaperTradingLedger(initial_balance=1000)

# 模拟买入
ok, msg, trade_id = ledger.buy(
    market_id="...", market_question="...",
    side="BUY_YES", token_id="...",
    price=0.45, size_usdc=50
)

# 模拟卖出（按当前价平仓）
ok, msg, pnl = ledger.sell(market_id="...", current_price=0.55)

# 模拟结算
ok, msg, pnl = ledger.settle(market_id="...", outcome="YES")

# 查看账户
print(ledger.get_portfolio())
```

## 文件结构

```
.
├── .env.example              # 环境变量模板
├── config.yaml               # 主配置
├── requirements.txt          # Python依赖
├── main.py                   # 主程序入口
├── README.md                 # 本文件
│
├── core/                     # 核心模块
│   ├── polymarket_client.py  # API客户端
│   ├── risk_manager.py       # 风控管理
│   ├── paper_trading.py      # 模拟账本
│   └── execution_engine.py   # 执行引擎
│
├── strategies/               # 策略模块
│   ├── base.py               # 策略基类
│   └── simple_arbitrage.py   # 简单套利策略
│
└── utils/                    # 工具模块
    └── logger.py             # 日志配置
```

## 实盘交易注意事项

1. **API 认证**: 实盘需要 Polymarket API Key。通过 `py-clob-client` 生成：
   ```python
   from py_clob_client_v2 import ClobClient
   client = ClobClient(host, key=private_key, chain_id=137)
   creds = client.create_or_derive_api_key()
   ```

2. **Polygon 网络**: 需要 USDC.e（Bridged USDC）作为抵押品

3. **Gas 费**: Polygon 上 gas 费很低（通常 <$0.01），但仍需预留少量 MATIC

4. **手续费**: Taker 费 0-1.8%（动态），Maker 费 0% + Rebate

5. **建议**: 先在模拟模式运行至少 1 周，确认策略逻辑和风控行为符合预期

## 免责声明

本项目仅供学习和研究用途。**预测市场交易具有高风险，可能导致本金全部损失。** 使用本系统进行实盘交易前，请确保你充分理解相关风险。开发者不对任何交易损失负责。

## License

MIT
