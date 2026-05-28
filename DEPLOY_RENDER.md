# Render 部署指南

Render 是一个免费的云平台，可以 24 小时持续运行你的 Bot。

## 为什么选 Render？

| 特性 | GitHub Actions | Render |
|------|---------------|--------|
| 运行方式 | 每 5 分钟触发一次 | **24 小时持续运行** |
| 延迟 | 等 cron 触发 | **实时监控** |
| 状态保存 | 每次重启丢失 | 进程内存中保留（重启才丢失）|
| 费用 | 免费 | **免费套餐够用** |
| 日志 | 看 Actions 日志 | Dashboard 实时查看 |

## 部署步骤（5分钟搞定）

### 第1步：注册 Render

1. 打开 [render.com](https://render.com)
2. 点击 "Get Started for Free"
3. 用 **GitHub 账号** 直接登录（最方便）

### 第2步：把代码推送到 GitHub

```bash
git init
git add .
git commit -m "ready for render"
git remote add origin https://github.com/你的用户名/你的仓库名.git
git push -u origin main
```

> **必须设为公开仓库**，否则 Render 免费套餐无法读取。

### 第3步：在 Render 创建服务

**方法 A：Blueprint 一键部署（推荐）**

1. Render Dashboard → "New +" → "Blueprint"
2. 选择你的 GitHub 仓库
3. Render 自动读取 `render.yaml` 创建服务
4. 等待 2-3 分钟构建完成

**方法 B：手动创建（如果 Blueprint 不行）**

1. Render Dashboard → "New +" → "Background Worker"
2. 选择你的 GitHub 仓库
3. 填写：
   - **Name**: `polymarket-bot`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python main.py`
   - **Plan**: `Free`
4. 点击 "Create Background Worker"

### 第4步：配置环境变量

进入服务页面 → "Environment" 标签：

| Key | Value | 说明 |
|-----|-------|------|
| `DRY_RUN` | `true` | 先跑模拟，确认无误后改 `false` |
| `POLYMARKET_PRIVATE_KEY` | `0x...` | 你的私钥（实盘才填）|
| `POLYMARKET_FUNDER_ADDRESS` | `0x...` | 你的钱包地址 |
| `POLYMARKET_SIGNATURE_TYPE` | `0` | 0=MetaMask, 1=邮箱 |

> ⚠️ **永远不要把这些写到代码里！** Render 的环境变量是加密存储的。

### 第5步：查看日志

1. 进入服务页面 → "Logs" 标签
2. 你会看到：
   ```
   [INFO]  Polymarket 自动交易系统启动
   [WARNING] ⚠️  当前为模拟交易模式（DRY_RUN）
   [INFO]  策略加载: clueless_tailwind
   [INFO]  扫描间隔: 10秒 | 每次最多 50 个市场
   ```

### 第6步：切换到实盘（确认无误后）

1. 把 `DRY_RUN` 环境变量改成 `false`
2. Render 会自动重新部署
3. 日志会显示：
   ```
   [WARNING] 🚨 实盘交易模式已激活
   [INFO]    当前 pUSD 余额: $xxx.xx
   ```

---

## 免费套餐限制

| 限制 | 说明 |
|------|------|
| RAM | 512MB |
| CPU | 共享 |
| 运行时间 | 每月 750 小时（足够 24/7）|
| 磁盘 | 临时，重启后文件丢失 |
| 网络 | 无限制 |

**关于磁盘**：风控状态文件（`logs/risk_state.json`）重启后会丢失。如果你需要跨重启持久化，有两种方案：

### 方案 1：挂载 Render Disk（$0.25/GB/月）

在 `render.yaml` 中添加：
```yaml
disk:
  name: bot-data
  mountPath: /opt/render/project/logs
  sizeGB: 1
```

### 方案 2：用外部数据库（免费）

把风控状态存到免费的 Supabase PostgreSQL 或 Firebase。需要额外开发，当前版本暂不支持。

**当前建议**：免费 Worker 很稳定，很少自动重启。先用着，有问题再说。

---

## 常见问题

### Q: 为什么日志里显示 "No module named py_clob_client_v2"？

A: Render 的构建过程中可能缓存了旧依赖。手动点击 "Manual Deploy" → "Clear Build Cache & Deploy"。

### Q: Bot 运行一段时间自己停了？

A: 检查日志：
- 如果是风控触发断路器 → 正常，等次日自动恢复
- 如果是代码异常 → 修复后重新部署
- 如果是 Render 重启 → 免费 Worker 偶尔会重启，属于正常

### Q: 怎么更新 Bot？

A: 本地修改代码 → `git push` → Render 自动拉取最新代码重新部署。

### Q: 可以同时跑模拟和实盘两个实例吗？

A: 可以。创建两个 Background Worker：
- `polymarket-bot-paper`: `DRY_RUN=true`
- `polymarket-bot-live`: `DRY_RUN=false`

### Q: 不想用了怎么停止？

A: Render Dashboard → 服务 → Settings → "Suspend" 暂停，或删除服务。
