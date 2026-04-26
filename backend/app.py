"""
Flask API 服务
提供 Web 前端接口
"""
import os
import sys
import asyncio
import logging
from datetime import datetime
from functools import wraps
from typing import Optional

from flask import Flask, render_template, request, jsonify, Response
from flask_cors import CORS
from pydantic import ValidationError

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backend.config import load_config, AppConfig
from backend.models import BinanceCredentials, StrategyConfig, ArbitrageOpportunity
from backend.binance_client import BinanceClient, AsyncBinanceClient
from backend.arbitrage_engine import ArbitrageEngine, StrategyParams
from backend.database import Database

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 创建 Flask 应用
app = Flask(__name__,
            template_folder='../frontend/templates',
            static_folder='../frontend/static')
CORS(app)

# 全局状态
config: Optional[AppConfig] = None
engine: Optional[ArbitrageEngine] = None
db: Optional[Database] = None
binance_client: Optional[AsyncBinanceClient] = None


def init_app():
    """初始化应用"""
    global config, engine, db, binance_client

    config = load_config()

    # 初始化数据库
    db = Database(config.database.db_path)

    # 从数据库加载 API 凭证
    credentials = load_credentials()

    if credentials.futures_api_key:
        # 初始化套利引擎
        strategy = StrategyParams(
            min_funding_rate=config.trading.min_funding_rate,
            max_position_size=config.trading.max_trade_amount,
            leverage=config.trading.leverage,
            auto_execute=config.trading.auto_execute
        )
        engine = ArbitrageEngine(credentials, strategy, db)

        # 初始化客户端（用于查询）
        binance_client = AsyncBinanceClient(credentials)

    logger.info("应用初始化完成")


def load_credentials() -> BinanceCredentials:
    """从数据库加载凭证"""
    spot_api = db.get_config("spot_api_key") or ""
    spot_secret = db.get_config("spot_secret_key") or ""
    futures_api = db.get_config("futures_api_key") or ""
    futures_secret = db.get_config("futures_secret_key") or ""
    testnet = db.get_config("testnet") == "true"

    return BinanceCredentials(
        spot_api_key=spot_api,
        spot_secret_key=spot_secret,
        futures_api_key=futures_api,
        futures_secret_key=futures_secret,
        testnet=testnet
    )


def async_route(f):
    """异步路由装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(f(*args, **kwargs))
        finally:
            loop.close()
    return decorated_function


# ============ 页面路由 ============

@app.route('/')
def index():
    """主页"""
    return render_template('index.html')


# ============ API 路由 ============

@app.route('/api/status')
def get_status():
    """获取系统状态"""
    return jsonify({
        "success": True,
        "data": {
            "engine_running": engine.is_running if engine else False,
            "api_configured": bool(binance_client),
            "positions_count": len(engine.get_positions()) if engine else 0,
            "last_scan": engine._last_scan_time.isoformat() if engine and engine._last_scan_time else None
        }
    })


@app.route('/api/credentials', methods=['GET'])
def get_credentials():
    """获取 API 配置状态（不返回密钥）"""
    spot_configured = bool(db.get_config("spot_api_key"))
    futures_configured = bool(db.get_config("futures_api_key"))

    return jsonify({
        "success": True,
        "data": {
            "spot_configured": spot_configured,
            "futures_configured": futures_configured,
            "testnet": db.get_config("testnet") == "true"
        }
    })


@app.route('/api/credentials', methods=['POST'])
def set_credentials():
    """设置 API 凭证"""
    global engine, binance_client, config

    data = request.get_json()

    try:
        # 验证凭证
        credentials = BinanceCredentials(
            spot_api_key=data.get('spot_api_key', ''),
            spot_secret_key=data.get('spot_secret_key', ''),
            futures_api_key=data.get('futures_api_key', ''),
            futures_secret_key=data.get('futures_secret_key', ''),
            testnet=data.get('testnet', False)
        )

        # 保存到数据库
        db.save_config("spot_api_key", credentials.spot_api_key)
        db.save_config("spot_secret_key", credentials.spot_secret_key)
        db.save_config("futures_api_key", credentials.futures_api_key)
        db.save_config("futures_secret_key", credentials.futures_secret_key)
        db.save_config("testnet", "true" if credentials.testnet else "false")

        # 重新初始化客户端
        config = load_config()
        if credentials.futures_api_key:
            strategy = StrategyParams(
                min_funding_rate=config.trading.min_funding_rate,
                max_position_size=config.trading.max_trade_amount,
                leverage=config.trading.leverage,
                auto_execute=config.trading.auto_execute
            )
            engine = ArbitrageEngine(credentials, strategy, db)
            binance_client = AsyncBinanceClient(credentials)

        return jsonify({
            "success": True,
            "message": "API 凭证保存成功"
        })

    except ValidationError as e:
        return jsonify({
            "success": False,
            "error": f"参数验证失败: {e}"
        }), 400


@app.route('/api/opportunities')
@async_route
async def get_opportunities():
    """扫描套利机会"""
    if not binance_client:
        return jsonify({
            "success": False,
            "error": "请先配置 API 凭证"
        }), 400

    min_rate = request.args.get('min_rate', type=float, default=0.01)
    max_results = request.args.get('limit', type=int, default=20)

    try:
        opportunities = await binance_client.scan_opportunities_async(
            min_funding_rate=min_rate,
            max_results=max_results
        )

        return jsonify({
            "success": True,
            "data": [o.model_dump() for o in opportunities],
            "count": len(opportunities)
        })

    except Exception as e:
        logger.error(f"扫描机会失败: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/opportunities/history')
def get_opportunities_history():
    """获取历史套利机会"""
    hours = request.args.get('hours', type=int, default=24)
    limit = request.args.get('limit', type=int, default=100)

    opportunities = db.get_recent_opportunities(hours=hours, limit=limit)

    return jsonify({
        "success": True,
        "data": opportunities,
        "count": len(opportunities)
    })


@app.route('/api/trades')
def get_trades():
    """获取交易记录"""
    trades = db.get_all_trades(limit=50)

    return jsonify({
        "success": True,
        "data": trades
    })


@app.route('/api/trades/stats')
def get_trade_stats():
    """获取交易统计"""
    stats = db.get_trade_stats()

    return jsonify({
        "success": True,
        "data": stats
    })


@app.route('/api/positions')
def get_positions():
    """获取当前持仓"""
    if not engine:
        return jsonify({
            "success": True,
            "data": []
        })

    positions = engine.get_positions()

    return jsonify({
        "success": True,
        "data": [p.model_dump() for p in positions]
    })


@app.route('/api/engine/start', methods=['POST'])
@async_route
async def start_engine():
    """启动套利引擎"""
    if not engine:
        return jsonify({
            "success": False,
            "error": "请先配置 API 凭证"
        }), 400

    if engine.is_running:
        return jsonify({
            "success": False,
            "error": "引擎已在运行中"
        }), 400

    await engine.start()

    return jsonify({
        "success": True,
        "message": "套利引擎已启动"
    })


@app.route('/api/engine/stop', methods=['POST'])
@async_route
async def stop_engine():
    """停止套利引擎"""
    if not engine:
        return jsonify({
            "success": False,
            "error": "请先配置 API 凭证"
        }), 400

    if not engine.is_running:
        return jsonify({
            "success": False,
            "error": "引擎未运行"
        }), 400

    await engine.stop()

    return jsonify({
        "success": True,
        "message": "套利引擎已停止"
    })


@app.route('/api/strategy', methods=['GET'])
def get_strategy():
    """获取策略配置"""
    if not engine:
        return jsonify({
            "success": True,
            "data": {
                "min_funding_rate": config.trading.min_funding_rate,
                "max_position_size": config.trading.max_trade_amount,
                "leverage": config.trading.leverage,
                "auto_execute": config.trading.auto_execute
            }
        })

    return jsonify({
        "success": True,
        "data": {
            "min_funding_rate": engine.strategy.min_funding_rate,
            "max_position_size": engine.strategy.max_position_size,
            "leverage": engine.strategy.leverage,
            "auto_execute": engine.strategy.auto_execute,
            "max_positions": engine.strategy.max_positions,
            "stop_loss_pct": engine.strategy.stop_loss_pct,
            "take_profit_pct": engine.strategy.take_profit_pct
        }
    })


@app.route('/api/strategy', methods=['POST'])
def update_strategy():
    """更新策略配置"""
    global engine

    data = request.get_json()

    if engine:
        # 更新运行时策略
        if 'min_funding_rate' in data:
            engine.strategy.min_funding_rate = float(data['min_funding_rate'])
        if 'max_position_size' in data:
            engine.strategy.max_position_size = float(data['max_position_size'])
        if 'leverage' in data:
            engine.strategy.leverage = int(data['leverage'])
        if 'auto_execute' in data:
            engine.strategy.auto_execute = bool(data['auto_execute'])
        if 'max_positions' in data:
            engine.strategy.max_positions = int(data['max_positions'])
        if 'stop_loss_pct' in data:
            engine.strategy.stop_loss_pct = float(data['stop_loss_pct'])
        if 'take_profit_pct' in data:
            engine.strategy.take_profit_pct = float(data['take_profit_pct'])

    # 保存到配置文件
    if 'min_funding_rate' in data:
        db.save_config("min_funding_rate", str(data['min_funding_rate']))
    if 'max_trade_amount' in data:
        db.save_config("max_trade_amount", str(data['max_trade_amount']))
    if 'leverage' in data:
        db.save_config("leverage", str(data['leverage']))
    if 'auto_execute' in data:
        db.save_config("auto_execute", str(data['auto_execute']))

    return jsonify({
        "success": True,
        "message": "策略配置已更新"
    })


@app.route('/api/execute', methods=['POST'])
@async_route
async def execute_trade():
    """手动执行套利"""
    if not engine:
        return jsonify({
            "success": False,
            "error": "请先配置 API 凭证"
        }), 400

    data = request.get_json()
    symbol = data.get('symbol')

    if not symbol:
        return jsonify({
            "success": False,
            "error": "请提供交易对"
        }), 400

    try:
        opportunities = await binance_client.scan_opportunities_async(
            min_funding_rate=0,
            max_results=100
        )

        opportunity = next((o for o in opportunities if o.symbol == symbol), None)

        if not opportunity:
            return jsonify({
                "success": False,
                "error": "未找到该交易对的套利机会"
            }), 404

        result = await engine._execute_arbitrage(opportunity)

        return jsonify({
            "success": result.success,
            "message": result.message,
            "trade_id": result.trade_id
        })

    except Exception as e:
        logger.error(f"执行交易失败: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/close/<symbol>', methods=['POST'])
@async_route
async def close_position(symbol):
    """平仓"""
    if not engine:
        return jsonify({
            "success": False,
            "error": "请先配置 API 凭证"
        }), 400

    reason = request.json.get('reason', 'manual') if request.json else 'manual'

    result = await engine._close_position(symbol, reason)

    return jsonify({
        "success": result.success,
        "message": result.message
    })


@app.route('/api/close-all', methods=['POST'])
@async_route
async def close_all_positions():
    """平所有仓位"""
    if not engine:
        return jsonify({
            "success": False,
            "error": "请先配置 API 凭证"
        }), 400

    results = await engine.close_all_positions()

    return jsonify({
        "success": True,
        "message": f"已平 {len(results)} 个仓位",
        "details": [{"symbol": r.message, "success": r.success} for r in results]
    })


@app.route('/api/account')
@async_route
async def get_account():
    """获取账户信息"""
    if not binance_client:
        return jsonify({
            "success": False,
            "error": "请先配置 API 凭证"
        }), 400

    try:
        balance = await binance_client.get_futures_balance()
        stats = db.get_trade_stats()

        return jsonify({
            "success": True,
            "data": {
                "futures_balance": balance,
                "total_trades": stats.get("total_trades", 0),
                "total_pnl": stats.get("total_pnl", 0),
                "total_funding": stats.get("total_funding", 0),
                "win_rate": stats.get("win_rate", 0)
            }
        })

    except Exception as e:
        logger.error(f"获取账户信息失败: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============ 健康检查 ============

@app.route('/api/health')
def health_check():
    """健康检查"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat()
    })


# ============ 初始化 ============

init_app()


if __name__ == '__main__':
    app.run(
        host=config.server.host,
        port=config.server.port,
        debug=config.server.debug
    )
