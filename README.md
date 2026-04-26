# 🤖 BNB Arbitrage Bot — 币安永续合约资金费率套利机器人

> 利用币安永续合约资金费率与现货价差进行低风险套利，附带实时 Web 监控面板。

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.x-000000?style=flat-square&logo=flask&logoColor=white)](https://flask.palletsprojects.com)
[![Binance](https://img.shields.io/badge/Binance-API-F0B90B?style=flat-square&logo=binance&logoColor=white)](https://binance-docs.github.io/apidocs)
[![SQLite](https://img.shields.io/badge/SQLite-Database-003B57?style=flat-square&logo=sqlite&logoColor=white)](https://sqlite.org)
[![Helped by AI](https://img.shields.io/badge/Helped%20by-AI-blueviolet?style=flat-square)](#)

---

## 为什么做这个

学期货的时候，我注意到币安永续合约的**资金费率**有时候非常高（年化 30%+），而且是稳定的被动收入——只要持仓方向对，每 8 小时就会收到资金费。

这不是投机，是**套利**：
- 做多现货 → 价格涨跌两边都对冲了
- 做空永续合约 → 收取资金费
- 净收益 = 资金费率收益，几乎不受方向影响

手动盯盘效率太低，所以写了这个机器人，自动扫描机会、提醒开仓、记录收益。

---

## 套利原理

```
永续合约资金费率套利（Delta Neutral 策略）

┌─────────────────────────────────────────────────────┐
│  资金费率 > 0（多头付费给空头）                       │
│                                                     │
│  做多现货 ←──────────── 对冲价格风险 ──────────────┐ │
│  做空永续合约 ←──────── 每 8h 收取资金费 ──────────┘ │
│                                                     │
│  净收益 ≈ 资金费率 × 持仓金额（与价格涨跌无关）        │
└─────────────────────────────────────────────────────┘

例：BTC 资金费率 0.1% / 8h
  = 0.3% / 天
  = 约 109% 年化

风险点：
  1. 现货与期货价差扩大（基差风险）
  2. 资金费率突然转负（方向反转）
  3. 交易所流动性不足
```

---

## 功能特性

- **实时扫描** — 自动扫描全市场永续合约，筛选资金费率超过阈值的机会
- **风险计算** — 综合资金费率、基差、流动性评估每笔机会的风险收益比
- **开仓建议** — 给出仓位大小建议（1x 杠杆做多现货 + 对冲空头）
- **自动执行** — 支持配置后自动下单（需谨慎开启）
- **Web 面板** — 实时查看持仓、历史收益、资金费率走势图
- **止损保护** — 可配置止损和止盈比例，防止极端行情
- **交易日志** — 所有操作记录到 SQLite，可复盘分析

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API

复制配置文件模板：

```bash
cp config.ini.example config.ini
```

编辑 `config.ini`，填入你的币安 API Key：

```ini
[binance]
api_key    = 你的 API Key
api_secret = 你的 Secret Key
testnet    = true   # 先用测试网！

[strategy]
min_funding_rate  = 0.01   # 最低触发资金费率(%)
max_positions     = 5      # 最大同时持仓数
min_position_size = 50     # 最小单笔金额(USDT)
max_position_size = 1000   # 最大单笔金额(USDT)
leverage          = 3      # 杠杆倍数（建议 ≤3）
stop_loss_pct     = 2.0    # 止损比例(%)
auto_execute      = false  # 是否自动下单
```

### 3. 启动

```bash
python run.py
```

打开浏览器访问：[http://localhost:5000](http://localhost:5000)

---

## Web 面板功能

| 页面 | 功能 |
|------|------|
| 仪表盘 | 实时资金费率排行、当前持仓、今日收益 |
| 机会扫描 | 全市场扫描结果，按年化收益率排序 |
| 持仓管理 | 当前所有套利仓位，支持一键平仓 |
| 历史记录 | 历史交易和收益统计图表 |
| 策略配置 | 在线修改策略参数，无需重启 |

---

## 项目结构

```
bnb-arbitrage-bot/
├── run.py                      # 启动入口
├── config.ini.example          # 配置文件模板
├── requirements.txt
├── backend/
│   ├── app.py                  # Flask 路由 & API
│   ├── arbitrage_engine.py     # 套利核心逻辑
│   ├── binance_client.py       # 币安 API 封装
│   ├── models.py               # 数据模型
│   ├── database.py             # SQLite 数据库操作
│   └── config.py               # 配置读取
├── frontend/
│   ├── templates/              # HTML 模板
│   └── static/                 # JS / CSS
├── data/                       # 运行时数据（已 gitignore）
└── logs/                       # 日志（已 gitignore）
```

---

## 策略参数说明

| 参数 | 说明 | 建议值 |
|------|------|--------|
| `min_funding_rate` | 触发套利的最低资金费率 | 0.01%（年化 ≈ 11%）|
| `max_positions` | 同时最多持有几个套利仓位 | 3~5 |
| `leverage` | 永续合约杠杆倍数 | ≤3（低风险） |
| `hold_duration_hours` | 建议持仓时长 | 8（一个结算周期）|
| `auto_execute` | 是否自动下单 | 先用 `false` 观察 |

---

## ⚠️ 风险提示

> 本项目仅供学习和研究目的。加密货币市场风险极高，**请勿投入超过你能承受损失的资金**。
>
> - 资金费率可能突然转负，导致亏损
> - 极端行情下基差可能大幅扩大
> - 交易所 API 限频或宕机会影响平仓
> - 建议先在**测试网**充分验证后再接入真实资金

---

## License

MIT — 随意 fork，有用的话点个 ⭐
