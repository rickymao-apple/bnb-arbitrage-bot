"""
币安 API 客户端模块
支持现货和永续合约 API
"""
import asyncio
import logging
import time
import hashlib
import requests
from typing import Optional, List, Dict, Any
from datetime import datetime

try:
    from binance.client import Client
except ImportError:
    Client = None

from backend.models import (
    ArbitrageOpportunity,
    BinanceCredentials,
    AccountInfo,
    Position
)

logger = logging.getLogger(__name__)

# API URLs
FUTURES_URL = "https://fapi.binance.com"
TESTNET_FUTURES_URL = "https://testnet.binancefuture.com/fapi"


def get_binance_signature(params: dict, secret_key: str) -> str:
    """生成签名"""
    param_str = "&".join([f"{k}={v}" for k, v in params.items()])
    signature = hashlib.sha256((param_str + secret_key).encode()).hexdigest()
    return signature


class BinanceFuturesClient:
    """币安合约客户端（兼容 python-binance 1.0.x）"""

    def __init__(self, api_key: str, secret_key: str, testnet: bool = False):
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = TESTNET_FUTURES_URL if testnet else FUTURES_URL
        self.session = requests.Session()
        self.session.headers.update({"X-MBX-APIKEY": api_key})

    def _request(self, method: str, endpoint: str, params: dict = None, signed: bool = False) -> dict:
        """发送请求"""
        url = f"{self.base_url}{endpoint}"
        params = params or {}

        if signed:
            params["timestamp"] = int(time.time() * 1000)
            params["signature"] = get_binance_signature(params, self.secret_key)

        if method == "GET":
            response = self.session.get(url, params=params)
        else:
            response = self.session.post(url, data=params)

        if response.status_code != 200:
            logger.error(f"API 请求失败: {response.text}")
            return {}

        return response.json()

    def get_mark_price(self, symbol: str) -> Optional[float]:
        """获取标记价格"""
        data = self._request("GET", "/fapi/v1/premiumIndex", {"symbol": symbol})
        if data and "markPrice" in data:
            return float(data["markPrice"])
        return None

    def get_funding_rate(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取资金费率"""
        data = self._request("GET", "/fapi/v1/fundingRate", {
            "symbol": symbol,
            "limit": 1
        })
        if data and len(data) > 0:
            return {
                "funding_rate": float(data[0]["fundingRate"]) * 100,
                "funding_time": datetime.fromtimestamp(data[0]["fundingTime"] / 1000)
            }
        return None

    def get_exchange_info(self) -> List[str]:
        """获取交易对列表"""
        data = self._request("GET", "/fapi/v1/exchangeInfo")
        if data and "symbols" in data:
            return [
                s["symbol"] for s in data["symbols"]
                if s["contractType"] == "PERPETUAL"
                and s["status"] == "TRADING"
                and s["quoteAsset"] == "USDT"
            ]
        return []

    def get_account(self) -> dict:
        """获取账户信息"""
        return self._request("GET", "/fapi/v1/account", signed=True)

    def get_balance(self) -> float:
        """获取 USDT 余额"""
        data = self._request("GET", "/fapi/v2/balance", signed=True)
        if data:
            for asset in data:
                if asset["asset"] == "USDT":
                    return float(asset["availableBalance"])
        return 0.0

    def get_positions(self) -> List[dict]:
        """获取持仓"""
        data = self._request("GET", "/fapi/v2/positionRisk", signed=True)
        return [
            p for p in data
            if float(p["positionAmt"]) != 0
        ]

    def place_order(self, symbol: str, side: str, order_type: str, quantity: float) -> dict:
        """下单"""
        params = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "quantity": quantity
        }
        return self._request("POST", "/fapi/v1/order", params, signed=True)

    def set_leverage(self, symbol: str, leverage: int) -> dict:
        """设置杠杆"""
        params = {
            "symbol": symbol,
            "leverage": leverage
        }
        return self._request("POST", "/fapi/v1/leverage", params, signed=True)


class BinanceClient:
    """币安客户端封装"""

    def __init__(self, credentials: BinanceCredentials):
        self.credentials = credentials
        self.spot_client: Optional[Client] = None
        self.futures_client: Optional[BinanceFuturesClient] = None
        self._testnet = credentials.testnet

        self._initialize_clients()

    def _initialize_clients(self):
        """初始化客户端"""
        try:
            # 初始化现货客户端
            if self.credentials.spot_api_key and self.credentials.spot_secret_key:
                self.spot_client = Client(
                    self.credentials.spot_api_key,
                    self.credentials.spot_secret_key
                )

            # 初始化合约客户端
            if self.credentials.futures_api_key and self.credentials.futures_secret_key:
                self.futures_client = BinanceFuturesClient(
                    self.credentials.futures_api_key,
                    self.credentials.futures_secret_key,
                    testnet=self._testnet
                )

            logger.info("币安客户端初始化完成")

        except Exception as e:
            logger.error(f"初始化币安客户端失败: {e}")
            raise

    def is_connected(self) -> bool:
        """检查连接状态"""
        try:
            if self.futures_client:
                self.futures_client.get_balance()
                return True
            return False
        except:
            return False

    def get_spot_price(self, symbol: str) -> Optional[float]:
        """获取现货价格"""
        try:
            if self.spot_client:
                ticker = self.spot_client.get_symbol_ticker(symbol=symbol)
                return float(ticker["price"])
            elif self.futures_client:
                return self.futures_client.get_mark_price(symbol)
            return None
        except Exception as e:
            logger.warning(f"获取现货价格失败 {symbol}: {e}")
            return None

    def get_futures_price(self, symbol: str) -> Optional[float]:
        """获取合约价格"""
        try:
            if self.futures_client:
                return self.futures_client.get_mark_price(symbol)
            return None
        except Exception as e:
            logger.warning(f"获取合约价格失败 {symbol}: {e}")
            return None

    def get_funding_rate(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取资金费率"""
        try:
            if self.futures_client:
                return self.futures_client.get_funding_rate(symbol)
            return None
        except Exception as e:
            logger.warning(f"获取资金费率失败 {symbol}: {e}")
            return None

    def get_premium_index(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取溢价指数"""
        try:
            if self.futures_client:
                return self.futures_client.get_funding_rate(symbol)
            return None
        except Exception as e:
            logger.warning(f"获取溢价指数失败 {symbol}: {e}")
            return None

    async def get_all_perpetual_symbols(self) -> List[str]:
        """获取所有永续合约"""
        try:
            if self.futures_client:
                return self.futures_client.get_exchange_info()
            return []
        except Exception as e:
            logger.error(f"获取永续合约列表失败: {e}")
            return []

    async def get_futures_balance(self) -> float:
        """获取合约余额"""
        try:
            if self.futures_client:
                return self.futures_client.get_balance()
            return 0.0
        except Exception as e:
            logger.error(f"获取合约余额失败: {e}")
            return 0.0

    def get_account_info(self) -> Optional[AccountInfo]:
        """获取账户信息"""
        try:
            if not self.futures_client:
                return None

            account = self.futures_client.get_account()
            balance = self.futures_client.get_balance()

            positions = self.futures_client.get_positions()
            open_positions = len(positions)

            return AccountInfo(
                total_balance=balance,
                available_balance=balance,
                total_pnl=0.0,
                daily_pnl=0.0,
                open_positions=open_positions,
                total_trades=0,
                win_rate=0.0
            )
        except Exception as e:
            logger.error(f"获取账户信息失败: {e}")
            return None

    def get_positions(self) -> List[Position]:
        """获取当前持仓"""
        try:
            if not self.futures_client:
                return []

            positions = self.futures_client.get_positions()
            result = []

            for pos in positions:
                symbol = pos["symbol"]
                spot_price = self.get_spot_price(symbol)
                futures_price = self.get_futures_price(symbol)

                result.append(Position(
                    symbol=symbol,
                    side="LONG" if float(pos["positionAmt"]) > 0 else "SHORT",
                    quantity=abs(float(pos["positionAmt"])),
                    entry_spot_price=float(pos["entryPrice"]),
                    entry_futures_price=float(pos["entryPrice"]),
                    current_spot_price=spot_price or float(pos["entryPrice"]),
                    current_futures_price=futures_price or float(pos["entryPrice"]),
                    unrealized_pnl=float(pos["unRealizedProfit"]),
                    funding_accrued=0.0,
                    leverage=int(pos["leverage"]),
                    opened_at=datetime.now()
                ))

            return result
        except Exception as e:
            logger.error(f"获取持仓失败: {e}")
            return []

    async def scan_opportunities(
        self,
        min_funding_rate: float = 0.01,
        max_results: int = 20
    ) -> List[ArbitrageOpportunity]:
        """扫描套利机会"""
        opportunities = []
        symbols = await self.get_all_perpetual_symbols()

        for symbol in symbols[:50]:
            try:
                spot_price = self.get_spot_price(symbol)
                futures_price = self.get_futures_price(symbol)
                funding_info = self.get_funding_rate(symbol)

                if not all([spot_price, futures_price, funding_info]):
                    continue

                premium = ((futures_price - spot_price) / spot_price) * 100
                annualized_rate = funding_info["funding_rate"] * 1095 / 100

                if funding_info["funding_rate"] >= min_funding_rate:
                    opportunities.append(ArbitrageOpportunity(
                        symbol=symbol,
                        spot_price=spot_price,
                        futures_price=futures_price,
                        funding_rate=funding_info["funding_rate"],
                        annualized_rate=annualized_rate,
                        premium=premium,
                        spread=futures_price - spot_price,
                        timestamp=datetime.now()
                    ))

            except Exception as e:
                logger.debug(f"扫描 {symbol} 失败: {e}")
                continue

        opportunities.sort(key=lambda x: x.annualized_rate, reverse=True)
        return opportunities[:max_results]

    def place_futures_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        leverage: int = 1
    ) -> Optional[Dict[str, Any]]:
        """合约下单"""
        try:
            if not self.futures_client:
                return None

            self.futures_client.set_leverage(symbol, leverage)

            order_side = "BUY" if side == "LONG" else "SELL"
            order = self.futures_client.place_order(symbol, order_side, "MARKET", quantity)

            return order
        except Exception as e:
            logger.error(f"下单失败 {symbol}: {e}")
            return None


# ============ 异步版本客户端 ============

class AsyncBinanceClient:
    """异步币安客户端"""

    def __init__(self, credentials: BinanceCredentials):
        self.credentials = credentials
        self.spot_client: Optional[Client] = None
        self.futures_client: Optional[BinanceFuturesClient] = None
        self._testnet = credentials.testnet
        self._initialize_clients()

    def _initialize_clients(self):
        """初始化客户端"""
        try:
            if self.credentials.spot_api_key and self.credentials.spot_secret_key:
                self.spot_client = Client(
                    self.credentials.spot_api_key,
                    self.credentials.spot_secret_key
                )

            if self.credentials.futures_api_key and self.credentials.futures_secret_key:
                self.futures_client = BinanceFuturesClient(
                    self.credentials.futures_api_key,
                    self.credentials.futures_secret_key,
                    testnet=self._testnet
                )

            logger.info("异步币安客户端初始化完成")
        except Exception as e:
            logger.error(f"初始化异步客户端失败: {e}")
            raise

    def get_spot_price(self, symbol: str) -> Optional[float]:
        """获取现货价格"""
        try:
            if self.spot_client:
                ticker = self.spot_client.get_symbol_ticker(symbol=symbol)
                return float(ticker["price"])
            elif self.futures_client:
                return self.futures_client.get_mark_price(symbol)
            return None
        except Exception as e:
            logger.warning(f"获取现货价格失败 {symbol}: {e}")
            return None

    def get_futures_price(self, symbol: str) -> Optional[float]:
        """获取合约价格"""
        try:
            if self.futures_client:
                return self.futures_client.get_mark_price(symbol)
            return None
        except Exception as e:
            logger.warning(f"获取合约价格失败 {symbol}: {e}")
            return None

    def get_funding_rate(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取资金费率"""
        try:
            if self.futures_client:
                return self.futures_client.get_funding_rate(symbol)
            return None
        except Exception as e:
            logger.warning(f"获取资金费率失败 {symbol}: {e}")
            return None

    async def get_spot_price_async(self, symbol: str) -> Optional[float]:
        """异步获取现货价格"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.get_spot_price, symbol)

    async def get_futures_price_async(self, symbol: str) -> Optional[float]:
        """异步获取合约价格"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.get_futures_price, symbol)

    async def get_funding_rate_async(self, symbol: str) -> Optional[Dict[str, Any]]:
        """异步获取资金费率"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.get_funding_rate, symbol)

    async def get_all_perpetual_symbols_async(self) -> List[str]:
        """异步获取所有永续合约"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_all_perpetual_symbols_sync)

    def _get_all_perpetual_symbols_sync(self) -> List[str]:
        """同步获取所有永续合约"""
        try:
            if self.futures_client:
                return self.futures_client.get_exchange_info()
            return []
        except Exception as e:
            logger.error(f"获取永续合约列表失败: {e}")
            return []

    async def scan_opportunities_async(
        self,
        min_funding_rate: float = 0.01,
        max_results: int = 20
    ) -> List[ArbitrageOpportunity]:
        """异步扫描套利机会"""
        loop = asyncio.get_event_loop()

        symbols = await self.get_all_perpetual_symbols_async()
        opportunities = []

        batch_size = 10
        for i in range(0, min(len(symbols), 50), batch_size):
            batch = symbols[i:i + batch_size]
            tasks = []

            for symbol in batch:
                tasks.append(self._scan_single_symbol(symbol, min_funding_rate))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, ArbitrageOpportunity):
                    opportunities.append(result)

        opportunities.sort(key=lambda x: x.annualized_rate, reverse=True)
        return opportunities[:max_results]

    async def _scan_single_symbol(
        self,
        symbol: str,
        min_funding_rate: float
    ) -> Optional[ArbitrageOpportunity]:
        """扫描单个交易对"""
        try:
            spot_price, futures_price, funding_info = await asyncio.gather(
                self.get_spot_price_async(symbol),
                self.get_futures_price_async(symbol),
                self.get_funding_rate_async(symbol)
            )

            if not all([spot_price, futures_price, funding_info]):
                return None

            premium = ((futures_price - spot_price) / spot_price) * 100
            annualized_rate = funding_info["funding_rate"] * 1095 / 100

            if funding_info["funding_rate"] >= min_funding_rate:
                return ArbitrageOpportunity(
                    symbol=symbol,
                    spot_price=spot_price,
                    futures_price=futures_price,
                    funding_rate=funding_info["funding_rate"],
                    annualized_rate=annualized_rate,
                    premium=premium,
                    spread=futures_price - spot_price,
                    timestamp=datetime.now()
                )

            return None
        except Exception as e:
            logger.debug(f"扫描 {symbol} 失败: {e}")
            return None
