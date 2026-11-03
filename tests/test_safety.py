"""Offline regressions: no exchange traffic and no real credentials."""
import asyncio
import hashlib
import hmac
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlencode
from backend.app import create_app
from backend.binance_client import BinanceClient, BinanceFuturesClient, BinanceAPIError, get_binance_signature
from backend.config import load_config
from backend.models import BinanceCredentials


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'config.ini'
        self.path.write_text('[binance]\ntestnet = true\n[monitoring]\nrefresh_interval = 5\n')
        self.app = create_app(self.path, access_token='test-token')
        self.client = self.app.test_client()
        self.headers = {'Authorization': 'Bearer test-token'}
        self.engine = self.app.extensions['engine']

    def tearDown(self):
        self.engine.stop()
        self.app.extensions['database'].engine.dispose()
        self.temp.cleanup()

    def post(self, path, data=None):
        return self.client.post(path, json=data, headers=self.headers)

    def test_auth_and_cors(self):
        self.assertEqual(self.client.get('/api/status').status_code, 401)
        self.assertEqual(self.client.get('/api/health').status_code, 200)
        self.assertEqual(self.client.get('/api/status', headers=self.headers).status_code, 200)
        self.assertEqual(self.client.get('/api/status', headers=self.headers | {'Origin':'https://evil.example'}).status_code, 403)
        self.assertNotIn('Access-Control-Allow-Origin', self.client.get('/api/health').headers)

    def test_all_trade_routes_blocked_even_with_auth(self):
        for route in ['/api/execute', '/api/close/BTCUSDT', '/api/close-all']:
            self.assertEqual(self.post(route, {'symbol':'BTCUSDT'}).status_code, 409)
        result = asyncio.run(self.engine._execute_arbitrage(None))
        self.assertFalse(result.success)
        self.assertFalse(asyncio.run(self.engine._close_position('BTCUSDT')).success)

    def test_no_automatic_execution(self):
        self.assertEqual(self.post('/api/strategy', {'auto_execute':True}).status_code, 400)
        self.assertEqual(self.post('/api/strategy', {'auto_execute':'false'}).status_code, 400)
        self.assertFalse(self.engine.strategy.auto_execute)

    def test_invalid_strategy_atomic(self):
        before = self.engine.strategy.min_funding_rate
        for bad in [{'leverage':-1}, {'min_funding_rate':float('nan')}, {'max_positions':0},
                    {'stop_loss_pct':0}, {'max_position_size':1}, {'unknown':1}]:
            self.assertEqual(self.post('/api/strategy', {'min_funding_rate':2} | bad).status_code, 400)
            self.assertEqual(self.engine.strategy.min_funding_rate, before)

    def test_all_strategy_keys_persist(self):
        values = dict(min_funding_rate=0, max_position_size=333, leverage=2,
                      max_positions=7, stop_loss_pct=3, take_profit_pct=8, auto_execute=False)
        self.assertEqual(self.post('/api/strategy', values).status_code, 200)
        second = create_app(self.path, access_token='test-token')
        try:
            response = second.test_client().get('/api/strategy', headers=self.headers).json
            self.assertEqual(response['data'], values)
        finally:
            second.extensions['database'].engine.dispose()

    def test_credentials_memory_only_and_no_leak(self):
        secret='synthetic-secret-not-a-real-key'
        data={'futures_api_key':'test-key', 'futures_secret_key':secret, 'testnet':True}
        self.assertEqual(self.post('/api/credentials', data).status_code, 200)
        self.assertNotIn(secret, self.client.get('/api/credentials', headers=self.headers).text)
        db=self.app.extensions['database']
        self.assertIsNone(db.get_config('futures_secret_key'))
        self.assertNotIn(secret.encode(), Path(db.engine.url.database).read_bytes())
        second = create_app(self.path, access_token='test-token')
        try:
            self.assertEqual(second.extensions['engine'].credentials.futures_secret_key, '')
        finally:
            second.extensions['database'].engine.dispose()

    def test_invalid_credentials_do_not_echo_secret(self):
        response = self.post('/api/credentials', {'futures_api_key':{'secret':'never-echo'}})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn('never-echo', response.text)

    def test_worker_survives_start_http_request_and_stops(self):
        scanned=threading.Event()
        def scan(**kwargs):
            scanned.set()
            return []
        with patch.object(self.engine, 'scan', side_effect=scan):
            self.assertEqual(self.post('/api/engine/start').status_code, 200)
            self.assertTrue(scanned.wait(1))
            self.assertTrue(self.engine.is_running)
            self.assertEqual(self.post('/api/engine/start').status_code, 409)
            self.assertEqual(self.post('/api/credentials', {'testnet':False}).status_code, 409)
            self.assertEqual(self.post('/api/engine/stop').status_code, 200)
            self.assertFalse(self.engine.is_running)

    def test_worker_failure_visible_and_stoppable(self):
        scanned=threading.Event()
        def failed(**kwargs):
            scanned.set()
            raise BinanceAPIError('fake failure')
        with patch.object(self.engine, 'scan', side_effect=failed):
            self.engine.start()
            self.assertTrue(scanned.wait(1))
            for _ in range(100):
                if self.engine.last_error:
                    break
                time.sleep(.001)
            self.assertIsNotNone(self.engine.last_error)
            self.assertTrue(self.engine.is_running)
            self.assertTrue(self.engine.stop())

    def test_positions_use_exchange_not_empty_memory(self):
        self.post('/api/credentials', {'futures_api_key':'test', 'futures_secret_key':'test', 'testnet':True})
        expected=[{'symbol':'BTCUSDT', 'side':'SHORT'}]
        with patch.object(self.engine.client, 'get_positions', return_value=expected):
            self.assertEqual(self.client.get('/api/positions', headers=self.headers).json['data'], expected)

    def test_account_failure_not_fake_zero(self):
        self.post('/api/credentials', {'futures_api_key':'test', 'futures_secret_key':'test'})
        with patch.object(self.engine.client.futures_client, 'get_balance', side_effect=BinanceAPIError('unavailable')):
            self.assertEqual(self.client.get('/api/account', headers=self.headers).status_code, 502)

    def test_query_validation(self):
        for query in ['limit=0', 'limit=501', 'min_rate=nan', 'min_rate=-1']:
            self.assertEqual(self.client.get('/api/opportunities?' + query, headers=self.headers).status_code, 400)

    def test_no_credentials_is_unknown_positions(self):
        self.assertEqual(self.client.get('/api/positions', headers=self.headers).status_code, 400)


class ClientTests(unittest.TestCase):
    def test_hmac_signature(self):
        params={'symbol':'BTCUSDT', 'clientOrderId':'a&b', 'timestamp':123}
        expected=hmac.new(b'fake-secret', urlencode(params).encode(), hashlib.sha256).hexdigest()
        self.assertEqual(get_binance_signature(params, 'fake-secret'), expected)

    def test_testnet_url_and_timeout(self):
        client=BinanceFuturesClient(testnet=True)
        response=Mock(status_code=200)
        response.json.return_value={'markPrice':'100'}
        with patch.object(client.session, 'get', return_value=response) as get:
            self.assertEqual(client.get_mark_price('BTCUSDT'), 100)
            self.assertEqual(get.call_args.args[0], 'https://demo-fapi.binance.com/fapi/v1/premiumIndex')
            self.assertEqual(get.call_args.kwargs['timeout'], (5, 15))

    def test_errors_do_not_fake_connection_or_leak_urls(self):
        client=BinanceFuturesClient('fake', 'fake')
        with patch.object(client.session, 'get', return_value=Mock(status_code=401, text='secret')):
            with self.assertRaises(BinanceAPIError) as ctx:
                client.get_balance()
            self.assertNotIn('secret', str(ctx.exception))

    def test_low_level_all_writes_blocked(self):
        client=BinanceFuturesClient('fake','fake')
        with patch.object(client.session, 'post') as post:
            for method in ['POST','PUT','DELETE']:
                with self.assertRaises(BinanceAPIError):
                    client._request(method, '/fapi/v1/order')
            with self.assertRaises(BinanceAPIError):
                client.place_order('BTCUSDT','BUY','MARKET',1)
            post.assert_not_called()

    def test_scan_all_pairs_real_spot_and_variable_intervals(self):
        client=BinanceClient(BinanceCredentials(testnet=True))
        symbols=[f'COIN{i}USDT' for i in range(65)]
        marks=[dict(symbol=s,markPrice='101',lastFundingRate='0.001',nextFundingTime=2000000000000) for s in symbols]
        def futures(method, path):
            if path.endswith('premiumIndex'):
                return marks
            if path.endswith('fundingInfo'):
                return [{'symbol':symbols[-1], 'fundingIntervalHours':4}]
            if path.endswith('exchangeInfo'):
                return {'symbols':[dict(symbol=s, baseAsset=s[:-4], quoteAsset='USDT', status='TRADING', contractType='PERPETUAL') for s in symbols]}
            raise AssertionError(path)
        def spot(path):
            if path.endswith('exchangeInfo'):
                return {'symbols':[dict(symbol=s,baseAsset=s[:-4],status='TRADING',isSpotTradingAllowed=True) for s in symbols]}
            return [dict(symbol=s, price='100') for s in symbols]
        with patch.object(client.futures_client, '_request', side_effect=futures), patch.object(client, '_spot', side_effect=spot):
            result=client.scan_opportunities_sync(0,100)
            self.assertEqual(len(result),65)
            self.assertEqual(result[0].symbol, symbols[-1])
            self.assertAlmostEqual(result[0].annualized_rate,219)
            self.assertAlmostEqual(result[1].annualized_rate,109.5)
            self.assertEqual(result[0].spread,1)
            client.enabled_pairs={symbols[-1]}
            self.assertEqual(len(client.scan_opportunities_sync(0,100)),1)

    def test_order_directions_cannot_be_converted_to_sell(self):
        client=BinanceClient(BinanceCredentials())
        for side in ['BUY','SELL']:
            with self.assertRaises(BinanceAPIError):
                client.place_futures_order('BTCUSDT',side,1)
        with self.assertRaises(ValueError):
            client.place_futures_order('BTCUSDT','LONG',1)


class ConfigTests(unittest.TestCase):
    def test_selected_config_quotes_lists_comments_and_env_override(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'chosen.ini'
            path.write_text('[binance]\nfutures_api_key = "fake"\ntestnet = true # safe\n[trading]\nenabled_pairs = []\n[server]\ndebug = false\n')
            with patch.dict(os.environ, {'CONFIG_PATH':str(path), 'BINANCE_FUTURES_API_KEY':'env-fake'}):
                config=load_config()
                self.assertEqual(config.binance.futures_api_key,'env-fake')
                self.assertTrue(config.binance.testnet)
                self.assertEqual(config.trading.enabled_pairs,[])
                self.assertFalse(config.server.debug)
                self.assertEqual(config.server.host,'127.0.0.1')
                self.assertEqual(Path(config.database.db_path).parent,Path(folder).resolve()/'data')


if __name__ == '__main__':
    unittest.main()
