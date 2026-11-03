"""Binance read-only client; trading stays locked until paired execution is implemented."""
import asyncio
import hashlib
import hmac
import math
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
import requests
from backend.models import ArbitrageOpportunity, BinanceCredentials

FUTURES_URL = "https://fapi.binance.com"
TESTNET_FUTURES_URL = "https://demo-fapi.binance.com"
SPOT_URL = "https://api.binance.com"
TESTNET_SPOT_URL = "https://testnet.binance.vision"
TRADING_DISABLED = "交易功能已锁定：双腿成交与异常恢复尚未通过验证，请在币安端管理已有仓位。"


class BinanceAPIError(RuntimeError):
    pass


def get_binance_signature(params, secret_key):
    return hmac.new(secret_key.encode(), urlencode(params).encode(), hashlib.sha256).hexdigest()


class BinanceFuturesClient:
    def __init__(self, api_key="", secret_key="", testnet=True):
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = TESTNET_FUTURES_URL if testnet else FUTURES_URL
        self._local = threading.local()

    @property
    def session(self):
        if not hasattr(self._local, "session"):
            self._local.session = requests.Session()
            self._local.session.headers.update({"X-MBX-APIKEY": self.api_key})
        return self._local.session

    def _request(self, method, endpoint, params=None, signed=False):
        if method != "GET":
            raise BinanceAPIError(TRADING_DISABLED)
        params = dict(params or {})
        if signed:
            if not self.api_key or not self.secret_key:
                raise BinanceAPIError("请配置只读合约 API 凭证")
            params.update(timestamp=int(time.time() * 1000), recvWindow=5000)
            params["signature"] = get_binance_signature(params, self.secret_key)
        try:
            response = self.session.get(self.base_url + endpoint, params=params, timeout=(5, 15))
            if response.status_code != 200:
                raise BinanceAPIError(f"币安请求失败 (HTTP {response.status_code})")
            return response.json()
        except (requests.RequestException, ValueError):
            # Do not expose signed URLs, API keys or response bodies to logs/UI.
            raise BinanceAPIError("币安请求超时、连接失败或响应无效") from None

    def get_mark_price(self, symbol):
        return float(self._request("GET", "/fapi/v1/premiumIndex", {"symbol": symbol})["markPrice"])

    def get_balance(self):
        data = self._request("GET", "/fapi/v3/balance", signed=True)
        return next((float(a["availableBalance"]) for a in data if a["asset"] == "USDT"), 0.0)

    def get_positions(self):
        return [p for p in self._request("GET", "/fapi/v3/positionRisk", signed=True)
                if float(p["positionAmt"]) != 0]

    def place_order(self, *args, **kwargs):
        raise BinanceAPIError(TRADING_DISABLED)

    def set_leverage(self, *args, **kwargs):
        raise BinanceAPIError(TRADING_DISABLED)


class BinanceClient:
    def __init__(self, credentials: BinanceCredentials, enabled_pairs=None):
        self.credentials = credentials
        self.futures_client = BinanceFuturesClient(credentials.futures_api_key,
                                                  credentials.futures_secret_key, credentials.testnet)
        self.spot_url = TESTNET_SPOT_URL if credentials.testnet else SPOT_URL
        self.enabled_pairs = set(enabled_pairs or [])
        self._metadata = None
        self._metadata_time = 0.0
        self._scan_lock = threading.Lock()

    def _spot(self, path):
        try:
            # Separate session: never send the futures API key to the spot service.
            response = requests.get(self.spot_url + path, timeout=(5, 15))
            if response.status_code != 200:
                raise BinanceAPIError(f"现货行情请求失败 (HTTP {response.status_code})")
            return response.json()
        except (requests.RequestException, ValueError):
            raise BinanceAPIError("现货行情连接失败或响应无效") from None

    def _symbols(self):
        if self._metadata is not None and time.monotonic() - self._metadata_time < 300:
            return self._metadata
        futures = self.futures_client._request("GET", "/fapi/v1/exchangeInfo")["symbols"]
        spots = {s["symbol"]: s for s in self._spot("/api/v3/exchangeInfo")["symbols"]
                 if s["status"] == "TRADING" and s.get("isSpotTradingAllowed", False)}
        # Equal symbols alone are insufficient for multiplier contracts.
        self._metadata = {s["symbol"] for s in futures
                          if s["contractType"] == "PERPETUAL" and s["status"] == "TRADING"
                          and s["quoteAsset"] == "USDT" and s["symbol"] in spots
                          and s["baseAsset"] == spots[s["symbol"]]["baseAsset"]}
        self._metadata_time = time.monotonic()
        return self._metadata

    def scan_opportunities_sync(self, min_funding_rate=0.01, max_results=20):
        with self._scan_lock:
            symbols = self._symbols()
            marks = self.futures_client._request("GET", "/fapi/v1/premiumIndex")
            intervals = {s["symbol"]: int(s["fundingIntervalHours"]) for s in
                         self.futures_client._request("GET", "/fapi/v1/fundingInfo")}
            spots = {s["symbol"]: float(s["price"]) for s in self._spot("/api/v3/ticker/price")}
            result = []
            now = datetime.now(timezone.utc)
            for mark in marks:
                symbol = mark["symbol"]
                if symbol not in symbols or (self.enabled_pairs and symbol not in self.enabled_pairs):
                    continue
                spot = spots.get(symbol, 0)
                future = float(mark["markPrice"])
                rate = float(mark["lastFundingRate"]) * 100
                hours = intervals.get(symbol, 8)
                if not all(math.isfinite(n) for n in (spot, future, rate)) or min(spot, future, hours) <= 0:
                    continue
                if rate < min_funding_rate:
                    continue
                result.append(ArbitrageOpportunity(
                    symbol=symbol, spot_price=spot, futures_price=future, funding_rate=rate,
                    annualized_rate=rate * (24 / hours) * 365,
                    premium=(future / spot - 1) * 100, spread=future - spot,
                    timestamp=now, funding_interval_hours=hours,
                    next_funding_time=datetime.fromtimestamp(int(mark["nextFundingTime"]) / 1000, timezone.utc)))
            return sorted(result, key=lambda o: o.annualized_rate, reverse=True)[:max_results]

    async def scan_opportunities_async(self, min_funding_rate=0.01, max_results=20):
        return await asyncio.to_thread(self.scan_opportunities_sync, min_funding_rate, max_results)

    async def get_futures_balance(self):
        return await asyncio.to_thread(self.futures_client.get_balance)

    def get_positions(self):
        result = []
        for p in self.futures_client.get_positions():
            result.append({"symbol": p["symbol"], "side": "LONG" if float(p["positionAmt"]) > 0 else "SHORT",
                           "quantity": abs(float(p["positionAmt"])), "entry_futures_price": float(p["entryPrice"]),
                           "current_futures_price": float(p["markPrice"]), "unrealized_pnl": float(p["unRealizedProfit"]),
                           "position_side": p.get("positionSide", "BOTH")})
        return result

    def place_futures_order(self, symbol, side, quantity, leverage=1, reduce_only=False):
        # Validate direction even though this release cannot send orders.
        if side not in {"BUY", "SELL"}:
            raise ValueError("订单方向必须是 BUY 或 SELL")
        raise BinanceAPIError(TRADING_DISABLED)


# Keep the import name compatible, using one implementation for both modes.
AsyncBinanceClient = BinanceClient
