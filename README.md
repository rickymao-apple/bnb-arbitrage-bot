# BNB Arbitrage Bot

**币安永续合约资金费率监控与研究工具**

一个运行在本机的 Web 面板，用来筛选资金费率较高、同时具备现货与永续合约的交易对，查看参考年化、价格溢价和扫描历史。配置只读凭证后，还可以查询合约账户余额与真实持仓。

> **当前版本仅监控，不执行交易。** 开仓、平仓、修改杠杆、自动执行和自动止盈止损均不可用，测试网也不会下单。已有仓位请直接在币安端管理。

[查看自动检查](https://github.com/rickymao-apple/bnb-arbitrage-bot/actions/workflows/tests.yml) · [查看修复记录](https://github.com/rickymao-apple/bnb-arbitrage-bot/pull/1)

## 这个项目能做什么

| 功能 | 当前行为 |
| --- | --- |
| 扫描机会 | 批量读取合约与真实现货行情，不再只扫描前 50 个合约 |
| 匹配交易对 | 保留双方均可交易、交易代码和标的相符的 USDT 交易对 |
| 费率比较 | 根据各合约的结算间隔计算简单参考年化，接口返回下次结算时间 |
| 价格比较 | 显示现货价格、合约标记价格及二者溢价 |
| 持续监控 | 后台独立运行，定期扫描并记录结果 |
| 历史记录 | 保存最近的扫描机会，定期清理超过 7 天的记录 |
| 账户查询 | 使用只读合约凭证查询可用 USDT 余额与实际合约持仓 |
| 参数设置 | 校验并保存监控阈值；交易相关设置仅保留兼容，不触发交易 |

公开行情扫描不需要币安 API 密钥，也不需要付费数据接口。

## 快速开始

推荐 Python 3.12；自动检查覆盖 Python 3.11、3.12 和 3.13。

### 1. 下载项目并安装依赖

```sh
git clone https://github.com/rickymao-apple/bnb-arbitrage-bot.git
cd bnb-arbitrage-bot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Windows 激活环境时使用 `.venv\Scripts\activate`。

### 2. 创建配置并启动

```sh
cp config.ini.example config.ini
python run.py
```

Windows 可直接复制 `config.ini.example` 并重命名为 `config.ini`。

启动终端会显示面板地址和本次运行的访问口令。打开 `http://127.0.0.1:5000`，输入口令，点击“连接面板”。口令不会放在网页源码或 URL 中，刷新页面后需要重新输入。

### 3. 开始扫描

点击“扫描套利机会”查看结果，或点击“启动监控”持续扫描。默认连接**测试网**，用于检查工具能否工作；测试网的交易对和行情可能与主网不同。

要查看主网公开行情，可以在 `config.ini` 中设置：

```ini
[binance]
testnet = false
```

然后重启服务。也可以先停止监控，再在网页 API 设置中切换测试网选项。切换主网不会解锁交易功能。

## 查询账户与持仓

账户查询是可选功能。在网页 API 设置中填入对应环境的合约 API Key 和 Secret，仅需要**读取权限**，不要为此开启交易或提现权限。

- 网页提交的凭证只保存在本次进程内存中，服务重启后失效，不写入 SQLite。
- 如需重启后继续查询，可以通过环境变量或本地 `config.ini` 提供凭证。
- 更换凭证或网络环境前，先停止监控；如果仍有行情请求进行中，等待它结束后再更换。
- 没有凭证、请求失败和“账户确实没有持仓”是不同状态。查询失败不会显示成零余额或空仓。

面板显示的是合约账户持仓，并不表示已核对现货与合约组成的完整对冲组合。

## 如何理解扫描结果

以同一标的为例：

```text
溢价率 (%) = (合约标记价格 / 现货价格 - 1) × 100
参考年化 (%) = 当前资金费率 (%) × (24 / 结算间隔小时数) × 365
```

例如，资金费率为 `0.01% / 8 小时` 时，简单外推年化为 `10.95%`。程序会查询合约的结算间隔，未调整的合约按 8 小时处理。

**参考年化只是当前费率的外推，不是预期收益或账户资金回报率。** 它未扣除手续费、滑点、保证金占用及其他成本，也没有预测后续资金费率。溢价同样只是价格比较，不能直接视为可实现利润。

现货与合约双腿交易、成交精度、部分成交补偿、超时对账、重启恢复和幂等控制仍未完成，因此当前版本保持只读。

## 常用配置

```ini
[binance]
testnet = true
futures_api_key =
futures_secret_key =

[trading]
enabled_pairs = []
min_funding_rate = 0.01

[monitoring]
refresh_interval = 30

[database]
db_path = ./data/arbitrage.db

[server]
host = 127.0.0.1
port = 5000
debug = false
```

| 参数 | 说明 |
| --- | --- |
| `testnet` | `true` 使用测试网，`false` 使用主网 |
| `enabled_pairs` | `[]` 扫描全部匹配交易对；也可填 `BTCUSDT,ETHUSDT` |
| `min_funding_rate` | 最低资金费率，单位为百分比；`0.01` 表示 `0.01%` |
| `refresh_interval` | 后台扫描间隔，单位为秒，范围为 5–3600 |
| `db_path` | 数据库位置；相对路径以选定配置文件所在目录为基准 |
| `host` / `port` | 监听地址和端口，默认仅本机访问 |

环境变量优先于配置文件。常用变量为 `BINANCE_TESTNET`、`BINANCE_FUTURES_API_KEY`、`BINANCE_FUTURES_SECRET_KEY`、`MIN_FUNDING_RATE`、`ENABLED_PAIRS`、`REFRESH_INTERVAL`、`DB_PATH`、`HOST` 和 `PORT`。

设置 `DASHBOARD_TOKEN` 可以固定面板口令；未设置时，每次启动自动生成随机口令。包含凭证的文件不要提交到 Git。旧的现货密钥字段仅保留配置兼容，公开现货报价不会使用它们。

### 启动选项

```sh
python run.py --port 5001
python run.py --config /path/to/config.ini
```

`--host` 可覆盖监听地址。服务默认关闭调试和自动重载。若需要远程访问，请配置 HTTPS 反向代理并限制网络访问；面板访问口令不替代网络隔离。

## 从旧版升级

1. 保留或备份原数据库，再更新源码与依赖。
2. 旧版 SQLite `config` 表中的密钥不再自动加载。请改用环境变量、本地配置文件，或重新填写网页表单。
3. 旧库中的明文密钥不会被自动删除。迁移后请自行清理相应条目，并按需在币安更新旧密钥。
4. 旧版交易记录缺少完整成交、手续费和资金费核对。记录会保留，但不会继续展示成实际总收益。
5. 策略统一保存到 `strategy_v2`。旧配置中的 `auto_execute=true` 不会恢复交易，接口与底层客户端都会拒绝交易写操作。

## 常见问题

**打不开面板？** 检查启动终端中的地址。如果 5000 端口已被占用，使用 `python run.py --port 5001`。

**扫描没有结果？** 检查最低费率阈值、交易对过滤和当前测试网选项。只有具备匹配现货和永续合约的交易对才会出现；真正的网络错误会返回失败提示。

**配置了 API，余额仍无法读取？** 确认密钥属于所选主网或测试网，具有读取权限，且满足你在币安设置的访问限制。本版不会把请求失败伪装成零余额。

**为什么不能平仓或开启自动执行？** 原执行链路缺少现货对冲，平仓方向也存在错误。当前版本已移除这条不完整的执行路径，已有持仓必须在币安端管理。

## 开发与验证

```sh
python -m unittest discover -s tests -v
python -m pip check
```

20 项离线回归测试覆盖交易写入锁定、签名、测试网地址、错误处理、全市场扫描、费率间隔、监控线程、配置持久化、凭证不落库和面板访问验证。Python 3.11–3.13 的云端检查已通过。测试不使用真实密钥，不发送交易；真实账户与订单联调尚未进行。

```text
backend/app.py                面板接口与访问验证
backend/binance_client.py     只读行情、余额与持仓查询
backend/arbitrage_engine.py   后台扫描与历史记录
backend/config.py            配置加载与参数校验
backend/database.py          SQLite 存取
backend/models.py            数据模型
frontend/templates/index.html
run.py
tests/test_safety.py
```

接口行为以 [币安开发者文档](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/general-info) 为参考。项目用于监控与研究，不保证行情准确性、服务持续可用性或投资收益。

## License

沿用项目原有 MIT 声明。
