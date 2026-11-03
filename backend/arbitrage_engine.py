"""Persistent background monitoring worker. This release never sends orders."""
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Dict
from backend.binance_client import BinanceClient, TRADING_DISABLED
from backend.models import StrategyConfig

logger = logging.getLogger(__name__)


@dataclass
class StrategyParams:
    min_funding_rate: float = 0.01
    max_positions: int = 5
    min_position_size: float = 50.0
    max_position_size: float = 1000.0
    leverage: int = 3
    stop_loss_pct: float = 2.0
    take_profit_pct: float = 5.0
    auto_execute: bool = False
    hold_duration_hours: int = 8


@dataclass
class TradeResult:
    success: bool
    message: str
    trade_id: Optional[int] = None
    order_details: Optional[Dict] = None


class ArbitrageEngine:
    def __init__(self, credentials, strategy, db, refresh_interval=30, enabled_pairs=None):
        self.credentials = credentials
        self.strategy = strategy
        self.db = db
        self.client = BinanceClient(credentials, enabled_pairs)
        self.refresh_interval = refresh_interval
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.RLock()
        self._scan_lock = threading.Lock()
        self._last_scan_time = None
        self._last_cleanup = None
        self.last_error = None
        self.latest_opportunities = []

    @property
    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        with self._lock:
            if self.is_running:
                return False
            self._stop.clear()
            self._thread = threading.Thread(target=self._monitor_loop, name="funding-monitor", daemon=True)
            self._thread.start()
            return True

    def stop(self):
        with self._lock:
            thread = self._thread
            self._stop.set()
        if thread:
            thread.join(timeout=2)
        # A request in progress is bounded by the HTTP timeouts. Do not start a second worker.
        return not self.is_running

    def update_strategy(self, values):
        with self._lock:
            current = {k: getattr(self.strategy, k) for k in StrategyConfig.model_fields}
            validated = StrategyConfig(**(current | values))
            for key, value in validated.model_dump().items():
                setattr(self.strategy, key, value)
            return validated

    def scan(self, min_funding_rate=None, max_results=20):
        with self._scan_lock:
            with self._lock:
                rate = self.strategy.min_funding_rate if min_funding_rate is None else min_funding_rate
            opportunities = self.client.scan_opportunities_sync(rate, max_results)
            self.db.save_opportunities_batch([
                o.model_dump(exclude={"funding_interval_hours", "next_funding_time"}) for o in opportunities])
            self._last_scan_time = datetime.now(timezone.utc)
            self.latest_opportunities = opportunities
            self.last_error = None
            if self._last_cleanup is None or (self._last_scan_time - self._last_cleanup).total_seconds() > 3600:
                self.db.cleanup_old_opportunities(days=7)
                self._last_cleanup = self._last_scan_time
            return opportunities

    def _monitor_loop(self):
        while not self._stop.is_set():
            try:
                self.scan(max_results=100)
            except Exception:
                self.last_error = "行情扫描失败，请检查连接后重试"
                logger.warning(self.last_error)
            self._stop.wait(self.refresh_interval)

    def get_positions(self):
        return self.client.get_positions()

    async def _execute_arbitrage(self, opportunity):
        return TradeResult(False, TRADING_DISABLED)

    async def _close_position(self, symbol, reason="manual"):
        return TradeResult(False, TRADING_DISABLED)

    async def close_all_positions(self):
        return [TradeResult(False, TRADING_DISABLED)]
