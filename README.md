# ₿ BNB Arbitrage Bot

> Binance perpetual futures funding-rate arbitrage monitor & execution engine with a modern web dashboard.

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-2.x-000000?style=flat-square&logo=flask)](https://flask.palletsprojects.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)
[![Binance Futures](https://img.shields.io/badge/Binance-Futures%20API-F0B90B?style=flat-square&logo=binance)](https://www.binance.com/)
[![Helped by AI](https://img.shields.io/badge/Helped%20by-AI-blueviolet?style=flat-square)](https://github.com/rickymao-apple)

---

## ✨ Overview

Perpetual futures contracts are repriced every **8 hours** via a funding rate mechanism — when the rate is positive, short-position holders receive payments from longs. This bot identifies high-yield opportunities, optionally executes delta-neutral positions (long spot / short perp), and tracks everything through a sleek dashboard.

```
┌─────────────────────────────────────────────────────────────┐
│                  BNB Arbitrage Bot                          │
│                                                             │
│  Scanner ──► Arbitrage Engine ──► Position Manager         │
│     │               │                    │                  │
│  Binance         Strategy             SQLite DB             │
│  REST API        Params               (trades, history)     │
│     │               │                    │                  │
│  ───────────── Flask API ─────────────── │                  │
│                     │                                       │
│              Web Dashboard                                  │
│          (Bootstrap 5 + ECharts)                            │
└─────────────────────────────────────────────────────────────┘
```

---

## 🚀 Features

| Feature | Description |
|---------|-------------|
| 🔍 **Real-time Scanner** | Concurrently scans all USDT-margined perps, ranks by annualized funding yield |
| 📊 **Live Dashboard** | Dark-themed single-page UI with ECharts P&L curves and position tables |
| ⚙️ **Configurable Strategy** | Min funding rate, max position size, leverage (1-10×), stop-loss, take-profit |
| 🤖 **Auto-Execute** | Optional automated open/close triggered by the monitoring loop |
| 🔐 **Secure Storage** | API keys stored locally in SQLite; never leaves your machine |
| 📈 **Performance Stats** | Win rate, total P&L, funding income, historical trades |
| 🧪 **Testnet Support** | Full integration with Binance Futures Testnet for strategy validation |

---

## 📦 Installation

### 1. Clone

```bash
git clone https://github.com/rickymao-apple/bnb-arbitrage-bot.git
cd bnb-arbitrage-bot
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure (optional)

```bash
cp config.ini.example config.ini
# Edit config.ini with your Binance API keys
# Or configure directly in the web UI
```

### 4. Run

```bash
python run.py
# Or with custom port / debug mode
python run.py --port 8080 --debug
```

Open your browser at **http://localhost:5000**

---

## 🔑 API Keys Setup

1. Log in to [Binance](https://www.binance.com)
2. Go to **API Management**
3. Create a new API key — enable **Futures Trading** permission
4. Enter the key in the web dashboard **Settings** modal or `config.ini`

> ⚠️ Never commit your real API keys. `config.ini` is in `.gitignore`.

---

## 🏗 Project Structure

```
bnb-arbitrage-bot/
├── backend/
│   ├── app.py                # Flask API (17 endpoints)
│   ├── arbitrage_engine.py   # Core trading logic, monitoring loop
│   ├── binance_client.py     # Binance REST API client (sync + async)
│   ├── config.py             # Pydantic config management
│   ├── database.py           # SQLAlchemy / SQLite layer
│   └── models.py             # Pydantic + ORM models
├── frontend/
│   └── templates/
│       └── index.html        # Single-page dashboard (Bootstrap 5 + ECharts)
├── data/                     # Auto-created; holds arbitrage.db
├── logs/                     # Auto-created; holds arbitrage.log
├── config.ini.example        # Config template
├── requirements.txt
└── run.py                    # Entry point
```

---

## 📡 API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/status` | Engine & API connection status |
| GET/POST | `/api/credentials` | Manage Binance API keys |
| GET | `/api/opportunities` | Scan live arbitrage opportunities |
| GET | `/api/opportunities/history` | Historical opportunities |
| POST | `/api/execute` | Manually execute a trade |
| GET | `/api/positions` | Active positions |
| POST | `/api/close/<symbol>` | Close a position |
| POST | `/api/close-all` | Close all positions |
| GET/POST | `/api/strategy` | Read / update strategy config |
| POST | `/api/engine/start` | Start automated monitoring |
| POST | `/api/engine/stop` | Stop automated monitoring |
| GET | `/api/account` | Account balance & stats |
| GET | `/api/health` | Health check |

---

## ⚙️ Strategy Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `min_funding_rate` | 0.01% | Minimum 8h funding rate to display/trade |
| `max_position_size` | 1000 USDT | Max notional per position |
| `leverage` | 3× | Futures contract leverage |
| `stop_loss_pct` | 2% | Auto stop-loss threshold |
| `take_profit_pct` | 5% | Auto take-profit threshold |
| `auto_execute` | false | Enable automated execution |

---

## 🛠 Tech Stack

- **Backend**: Python 3.10+, Flask, SQLAlchemy, Pydantic v2
- **Frontend**: HTML5, Bootstrap 5.3, ECharts 5.4
- **Database**: SQLite
- **Exchange**: Binance Futures REST API (direct HMAC-SHA256 signed requests)
- **Async**: asyncio + `run_in_executor` for concurrent symbol scanning

---

## ⚠️ Risk Disclaimer

This software is for **educational purposes**. Crypto trading carries significant financial risk.

- High leverage amplifies losses
- Funding rates can reverse unexpectedly
- Always test on Testnet before using real funds
- Never risk more than you can afford to lose

---

## 📄 License

MIT © [rickymao-apple](https://github.com/rickymao-apple)

---

*Helped by AI — built with ❤️ and a lot of caffeine*
