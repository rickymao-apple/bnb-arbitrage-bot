"""
套利引擎核心模块
实现资金费率套利逻辑
"""
import asyncio
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field

from backend.binance_client import BinanceClient, AsyncBinanceClient
from backend.models import (
    ArbitrageOpportunity,
    Trade,
    Position,
    StrategyConfig,
    BinanceCredentials
)
from backend.database import Database

logger = logging.getLogger(__name__)


@dataclass
class StrategyParams:
    """策略参数"""
    min_funding_rate: float = 0.01  # 最小资金费率(%)
    max_positions: int = 5  # 最大持仓数
    min_position_size: float = 50.0  # 最小持仓金额(USDT)
    max_position_size: float = 1000.0  # 最大持仓金额(USDT)
    leverage: int = 3  # 杠杆倍数
    stop_loss_pct: float = 2.0  # 止损比例(%)
    take_profit_pct: float = 5.0  # 止盈比例(%)
    auto_execute: bool = False  # 是否自动执行
    hold_duration_hours: int = 8  # 持仓时长(小时)，建议到下次资金结算


@dataclass
class TradeResult:
    """交易结果"""
    success: bool
    message: str
    trade_id: Optional[int] = None
    order_details: Optional[Dict] = None


class ArbitrageEngine:
    """
    套利引擎

    资金费率套利原理:
    1. 当永续合约资金费率为正时，多头持仓者每8小时获得补贴
    2. 策略：做多现货 + 做空永续合约
    3. 收益 = 资金费率收益 + 价差收益
    4. 风险：现货价格下跌导致亏损
    """

    def __init__(
        self,
        credentials: BinanceCredentials,
        strategy: StrategyParams,
        db: Database
    ):
        """
        初始化套利引擎

        Args:
            credentials: API 凭证
            strategy: 策略参数
            db: 数据库实例
        """
        self.credentials = credentials
        self.strategy = strategy
        self.db = db

        # 初始化客户端
        if strategy.auto_execute:
            self.client = BinanceClient(credentials)
        else:
            self.client = AsyncBinanceClient(credentials)

        # 运行时状态
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._positions: Dict[str, Trade] = {}
        self._last_scan_time: Optional[datetime] = None

        logger.info("套利引擎初始化完成")

    @property
    def is_running(self) -> bool:
        """检查引擎是否运行"""
        return self._running

    async def start(self):
        """启动套利引擎"""
        if self._running:
            logger.warning("引擎已在运行中")
            return

        self._running = True
        logger.info("套利引擎已启动")

        # 启动监控任务
        self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def stop(self):
        """停止套利引擎"""
        if not self._running:
            return

        self._running = False

        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        logger.info("套利引擎已停止")

    async def _monitor_loop(self):
        """监控循环"""
        while self._running:
            try:
                # 扫描套利机会
                opportunities = await self.client.scan_opportunities_async(
                    min_funding_rate=self.strategy.min_funding_rate,
                    max_results=20
                )

                # 保存机会记录
                if opportunities:
                    opp_data = [{
                        "symbol": o.symbol,
                        "spot_price": o.spot_price,
                        "futures_price": o.futures_price,
                        "funding_rate": o.funding_rate,
                        "annualized_rate": o.annualized_rate,
                        "premium": o.premium,
                        "spread": o.spread,
                        "confidence": o.confidence,
                        "timestamp": o.timestamp
                    } for o in opportunities]

                    self.db.save_opportunities_batch(opp_data)

                # 检查现有持仓
                await self._check_positions()

                # 自动执行（如果启用）
                if self.strategy.auto_execute and len(self._positions) < self.strategy.max_positions:
                    for opp in opportunities:
                        if opp.symbol not in self._positions:
                            await self._execute_arbitrage(opp)

                self._last_scan_time = datetime.now()

            except Exception as e:
                logger.error(f"监控循环错误: {e}")

            # 等待下次扫描
            await asyncio.sleep(self.strategy.hold_duration_hours * 3600 // 4)  # 每2小时扫描一次

    async def _check_positions(self):
        """检查持仓状态"""
        # 获取当前持仓
        current_positions = self.client.get_positions()

        # 更新内部状态
        closed_positions = []

        for symbol, trade in self._positions.items():
            # 检查是否需要止损/止盈
            if symbol in [p.symbol for p in current_positions]:
                position = next(p for p in current_positions if p.symbol == symbol)
                pnl_pct = position.unrealized_pnl / (position.quantity * position.entry_futures_price) * 100

                if pnl_pct <= -self.strategy.stop_loss_pct:
                    closed_positions.append((symbol, "stop_loss"))
                elif pnl_pct >= self.strategy.take_profit_pct:
                    closed_positions.append((symbol, "take_profit"))

        # 平仓
        for symbol, reason in closed_positions:
            await self._close_position(symbol, reason)

    async def _execute_arbitrage(self, opportunity: ArbitrageOpportunity) -> TradeResult:
        """
        执行套利

        Args:
            opportunity: 套利机会

        Returns:
            交易结果
        """
        if len(self._positions) >= self.strategy.max_positions:
            return TradeResult(False, "已达到最大持仓数")

        # 计算仓位大小
        position_size = min(
            self.strategy.max_position_size,
            self.strategy.max_position_size
        )

        if position_size < self.strategy.min_position_size:
            return TradeResult(False, "仓位太小")

        # 计算数量
        quantity = position_size / opportunity.spot_price

        try:
            # 永续合约做空
            order = self.client.place_futures_order(
                symbol=opportunity.symbol,
                side="SELL",
                quantity=quantity,
                leverage=self.strategy.leverage
            )

            if not order:
                return TradeResult(False, "下单失败")

            # 记录交易
            trade = Trade(
                symbol=opportunity.symbol,
                side="SHORT",
                entry_spot_price=opportunity.spot_price,
                entry_futures_price=opportunity.futures_price,
                quantity=quantity,
                leverage=self.strategy.leverage,
                entry_time=datetime.now(),
                status="open"
            )

            trade_id = self.db.save_trade({
                "symbol": trade.symbol,
                "side": trade.side,
                "entry_spot_price": trade.entry_spot_price,
                "entry_futures_price": trade.entry_futures_price,
                "quantity": trade.quantity,
                "leverage": trade.leverage,
                "entry_time": trade.entry_time,
                "status": "open"
            })

            trade.id = trade_id
            self._positions[opportunity.symbol] = trade

            logger.info(f"开仓成功: {opportunity.symbol}, 数量: {quantity}")

            return TradeResult(
                True,
                "开仓成功",
                trade_id=trade_id,
                order_details=order
            )

        except Exception as e:
            logger.error(f"执行套利失败: {e}")
            return TradeResult(False, str(e))

    async def _close_position(self, symbol: str, reason: str = "manual") -> TradeResult:
        """
        平仓

        Args:
            symbol: 交易对
            reason: 平仓原因
        """
        if symbol not in self._positions:
            return TradeResult(False, "无持仓")

        trade = self._positions[symbol]

        try:
            # 平掉合约仓位
            order = self.client.place_futures_order(
                symbol=symbol,
                side="BUY",  # 平空
                quantity=trade.quantity,
                leverage=trade.leverage
            )

            if not order:
                return TradeResult(False, "平仓下单失败")

            # 计算收益
            exit_price = self.client.get_futures_price(symbol)
            pnl = (trade.entry_futures_price - exit_price) * trade.quantity * (1 if trade.side == "SHORT" else -1)

            # 更新交易记录
            self.db.update_trade(trade.id, {
                "status": "closed",
                "exit_time": datetime.now(),
                "exit_futures_price": exit_price,
                "pnl": pnl,
                "notes": f"平仓原因: {reason}"
            })

            del self._positions[symbol]

            logger.info(f"平仓成功: {symbol}, 原因: {reason}, PnL: {pnl}")

            return TradeResult(True, f"平仓成功: {reason}", trade_id=trade.id)

        except Exception as e:
            logger.error(f"平仓失败: {e}")
            return TradeResult(False, str(e))

    async def scan_opportunities(
        self,
        min_funding_rate: Optional[float] = None,
        max_results: int = 20
    ) -> List[ArbitrageOpportunity]:
        """
        扫描套利机会（手动触发）

        Args:
            min_funding_rate: 最小资金费率
            max_results: 最大结果数

        Returns:
            套利机会列表
        """
        rate = min_funding_rate or self.strategy.min_funding_rate
        return await self.client.scan_opportunities_async(
            min_funding_rate=rate,
            max_results=max_results
        )

    def get_positions(self) -> List[Trade]:
        """获取当前持仓"""
        return list(self._positions.values())

    def get_trade_history(self, days: int = 30) -> List[dict]:
        """获取交易历史"""
        return self.db.get_all_trades(limit=100)

    def get_performance_stats(self) -> dict:
        """获取绩效统计"""
        return self.db.get_trade_stats()

    async def close_all_positions(self) -> List[TradeResult]:
        """平所有仓位"""
        results = []
        for symbol in list(self._positions.keys()):
            result = await self._close_position(symbol, "手动全部平仓")
            results.append(result)
        return results


# ============ 套利策略说明 ============

"""
资金费率套利策略详解:

【策略原理】
永续合约每8小时进行一次资金费率结算。当资金费率为正时：
- 多头持仓者获得空头持仓者支付的利息
- 做空者支付利息

【套利操作】
1. 做多现货 (spot): 买入标的资产
2. 做空永续合约 (perpetual): 卖出等值的合约
3. 持有仓位直到资金结算获得资金费率收益

【收益来源】
1. 资金费率收益: 持有期间获得的资金费用
2. 理论上价差中性: 现货和合约价格趋于一致

【风险因素】
1. 现货价格下跌 → 现货多头亏损
2. 合约价格波动 → 短期浮动盈亏
3. 杠杆风险 → 放大亏损
4. 流动性风险 → 无法及时成交

【最优时机】
- 资金费率为正且较高时
- 现货与合约价差稳定
- 市场波动较小时

【建议参数】
- 杠杆: 2-3倍（保守）
- 持仓: 到下次资金结算前1-2小时
- 止损: 1-2% 现货价格波动
"""
