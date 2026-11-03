"""Authenticated, read-only monitoring API."""
import atexit
import hmac
import json
import logging
import os
import secrets
from datetime import datetime, timezone
from threading import RLock
from flask import Flask, jsonify, render_template, request
from pydantic import ValidationError
from backend.config import load_config
from backend.models import BinanceCredentials, StrategyConfig
from backend.binance_client import BinanceClient, BinanceAPIError, TRADING_DISABLED
from backend.arbitrage_engine import ArbitrageEngine, StrategyParams
from backend.database import Database


def create_app(config_path=None, *, access_token=None):
    app = Flask(__name__, template_folder='../frontend/templates', static_folder='../frontend/static')
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024
    config = load_config(config_path)
    db = Database(config.database.db_path)
    token = access_token or os.getenv('DASHBOARD_TOKEN') or secrets.token_urlsafe(32)
    # Display the generated token once at startup, never return it in a public HTTP response.
    if access_token is None and not os.getenv('DASHBOARD_TOKEN'):
        print(f'面板访问口令（请勿分享）: {token}', flush=True)
    credentials = BinanceCredentials(**config.binance.model_dump())
    initial = StrategyConfig(min_funding_rate=config.trading.min_funding_rate,
                             max_position_size=config.trading.max_trade_amount,
                             leverage=config.trading.leverage)
    stored = db.get_config('strategy_v2')
    if stored:
        initial = StrategyConfig.model_validate_json(stored)
    strategy = StrategyParams(**initial.model_dump())
    engine = ArbitrageEngine(credentials, strategy, db, config.monitoring.refresh_interval,
                             config.trading.enabled_pairs)
    state_lock = RLock()
    app.extensions.update(engine=engine, database=db, bot_config=config)
    atexit.register(engine.stop)

    @app.before_request
    def authenticate():
        if request.path.startswith('/api/') and request.path != '/api/health':
            auth = request.headers.get('Authorization', '')
            if not hmac.compare_digest(auth.encode(), ('Bearer ' + token).encode()):
                return jsonify(success=False, error='需要面板访问口令'), 401
            # Reject cross-origin API calls, even when a token is supplied.
            origin = request.headers.get('Origin')
            if origin and origin.rstrip('/') != request.host_url.rstrip('/'):
                return jsonify(success=False, error='不允许跨站请求'), 403

    @app.after_request
    def secure_response(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
        return response

    @app.errorhandler(ValidationError)
    def invalid_model(exc):
        # Pydantic errors may contain submitted secrets; omit input values.
        fields = ', '.join('.'.join(map(str, e['loc'])) for e in exc.errors())
        return jsonify(success=False, error='参数无效: ' + fields), 400

    @app.errorhandler(ValueError)
    def invalid_value(exc):
        return jsonify(success=False, error='参数格式或范围无效'), 400

    @app.errorhandler(BinanceAPIError)
    def upstream_failed(exc):
        return jsonify(success=False, error=str(exc)), 502

    @app.errorhandler(400)
    def invalid_json(exc):
        return jsonify(success=False, error='请求必须是有效 JSON 对象'), 400

    def body():
        value = request.get_json()
        if not isinstance(value, dict):
            raise ValueError('JSON object required')
        return value

    def integer_arg(key, default, lower, upper):
        value = int(request.args.get(key, default))
        if not lower <= value <= upper:
            raise ValueError('out of bounds')
        return value

    @app.get('/')
    def index():
        return render_template('index.html')

    @app.get('/api/health')
    def health():
        return jsonify(status='healthy', mode='monitor_only', timestamp=datetime.now(timezone.utc).isoformat())

    @app.get('/api/status')
    def status():
        return jsonify(success=True, data={
            'engine_running': engine.is_running, 'api_configured': bool(engine.credentials.futures_api_key),
            'mode': 'monitor_only', 'trading_enabled': False,
            'testnet': engine.credentials.testnet,
            'positions_count': None,
            'last_scan': engine._last_scan_time.isoformat() if engine._last_scan_time else None,
            'last_error': engine.last_error})

    @app.get('/api/credentials')
    def credential_status():
        c = engine.credentials
        return jsonify(success=True, data=dict(spot_configured=bool(c.spot_api_key),
            futures_configured=bool(c.futures_api_key), testnet=c.testnet, persistence='process_only'))

    @app.post('/api/credentials')
    def credentials_update():
        with state_lock:
            if engine.is_running:
                return jsonify(success=False, error='请先停止监控，再更换凭证或测试网'), 409
            data = body()
            if set(data) - set(BinanceCredentials.model_fields):
                raise ValueError('unknown field')
            c = BinanceCredentials(**data)
            if bool(c.futures_api_key) != bool(c.futures_secret_key) or bool(c.spot_api_key) != bool(c.spot_secret_key):
                raise ValueError('incomplete credentials')
            engine.credentials = c
            engine.client = BinanceClient(c, config.trading.enabled_pairs)
            # Never persist submitted API secrets in SQLite. Use environment/config for restart persistence.
            engine._last_scan_time = None
            engine.last_error = None
            engine.latest_opportunities = []
            return jsonify(success=True, message='凭证仅保存于本次运行；扫描行情不需要密钥')

    @app.get('/api/opportunities')
    def opportunities():
        rate = float(request.args.get('min_rate', engine.strategy.min_funding_rate))
        StrategyConfig(min_funding_rate=rate)
        limit = integer_arg('limit', 20, 1, 500)
        with state_lock:
            data = engine.scan(rate, limit)
        return jsonify(success=True, data=[o.model_dump(mode='json') for o in data], count=len(data))

    @app.get('/api/opportunities/history')
    def opportunity_history():
        hours = integer_arg('hours', 24, 1, 168)
        limit = integer_arg('limit', 100, 1, 1000)
        return jsonify(success=True, data=db.get_recent_opportunities(hours, limit))

    @app.get('/api/trades')
    def trades():
        return jsonify(success=True, data=db.get_all_trades(), source='legacy_unreconciled')

    @app.get('/api/trades/stats')
    def stats():
        return jsonify(success=True, data=db.get_trade_stats(), source='legacy_unreconciled')

    @app.get('/api/positions')
    def positions():
        if not engine.credentials.futures_api_key:
            return jsonify(success=False, error='未配置只读凭证，无法查询真实持仓'), 400
        with state_lock:
            data = engine.get_positions()
        return jsonify(success=True, data=data, source='exchange')

    @app.post('/api/engine/start')
    def start():
        with state_lock:
            started = engine.start()
        return jsonify(success=started, message='监控已启动' if started else '监控已在运行'), 200 if started else 409

    @app.post('/api/engine/stop')
    def stop():
        with state_lock:
            stopped = engine.stop()
        return jsonify(success=stopped, message='监控已停止' if stopped else '正在等待当前行情请求结束'), 200 if stopped else 202

    @app.get('/api/strategy')
    def strategy_get():
        with engine._lock:
            data = {k: getattr(engine.strategy, k) for k in StrategyConfig.model_fields}
        return jsonify(success=True, data=data)

    @app.post('/api/strategy')
    def strategy_update():
        with state_lock, engine._lock:
            data = body()
            current = {k: getattr(engine.strategy, k) for k in StrategyConfig.model_fields}
            validated = StrategyConfig(**(current | data))
            db.save_configs({'strategy_v2': validated.model_dump_json()})
            engine.update_strategy(validated.model_dump())
        return jsonify(success=True, message='监控配置已保存；本版本不执行止盈止损或交易')

    @app.post('/api/execute')
    @app.post('/api/close/<symbol>')
    @app.post('/api/close-all')
    def blocked_trade(symbol=None):
        return jsonify(success=False, error=TRADING_DISABLED), 409

    @app.get('/api/account')
    def account():
        if not engine.credentials.futures_api_key:
            return jsonify(success=False, error='查询余额需要只读合约凭证'), 400
        with state_lock:
            balance = engine.client.futures_client.get_balance()
        # Old DB values omit fees, real fills and funding settlements; do not claim real profit.
        return jsonify(success=True, data=dict(futures_balance=balance, total_pnl=None,
                       total_funding=None, win_rate=None), source='exchange')

    return app
