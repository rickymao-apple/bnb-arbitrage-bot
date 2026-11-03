"""
数据模型定义
"""
from datetime import datetime
from typing import Optional, List, Literal
from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, JSON
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()


class ArbitrageOpportunity(BaseModel):
    """套利机会模型"""
    symbol: str  # 交易对，如 BTCUSDT
    spot_price: float  # 现货价格
    futures_price: float  # 合约价格
    funding_rate: float  # 当前资金费率
    annualized_rate: float  # 年化资金费率
    premium: float  # 溢价率 (%)
    spread: float  # 价差
    timestamp: datetime = Field(default_factory=datetime.now)
    confidence: float = 1.0  # 置信度
    funding_interval_hours: int = 8
    next_funding_time: Optional[datetime] = None


class Trade(BaseModel):
    """交易记录模型"""
    id: Optional[int] = None
    symbol: str
    side: str  # LONG or SHORT
    entry_spot_price: float
    entry_futures_price: float
    quantity: float
    leverage: int
    entry_time: datetime
    exit_time: Optional[datetime] = None
    exit_spot_price: Optional[float] = None
    exit_futures_price: Optional[float] = None
    pnl: float = 0.0
    funding_earned: float = 0.0
    status: str = "open"  # open, closed
    notes: str = ""


class Position(BaseModel):
    """持仓模型"""
    symbol: str
    side: str  # LONG or SHORT
    quantity: float
    entry_spot_price: float
    entry_futures_price: float
    current_spot_price: float
    current_futures_price: float
    unrealized_pnl: float
    funding_accrued: float
    leverage: int
    opened_at: datetime


class AccountInfo(BaseModel):
    """账户信息模型"""
    total_balance: float
    available_balance: float
    total_pnl: float
    daily_pnl: float
    open_positions: int
    total_trades: int
    win_rate: float


class BinanceCredentials(BaseModel):
    """币安 API 凭证"""
    spot_api_key: str = ""
    spot_secret_key: str = ""
    futures_api_key: str = ""
    futures_secret_key: str = ""
    testnet: bool = True  # 是否使用测试网


class StrategyConfig(BaseModel):
    """All persisted strategy keys use the same names as the UI."""
    model_config = {"extra": "forbid", "allow_inf_nan": False}
    min_funding_rate: float = Field(default=0.01, ge=0, le=100)
    max_positions: int = Field(default=5, ge=1, le=100)
    max_position_size: float = Field(default=1000, ge=50)
    leverage: int = Field(default=3, ge=1, le=125)
    stop_loss_pct: float = Field(default=2, gt=0, le=100)
    take_profit_pct: float = Field(default=5, gt=0, le=100)
    auto_execute: Literal[False] = False


# ============ 数据库表模型 ============

class DBTrade(Base):
    """数据库交易记录表"""
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    side = Column(String(10), nullable=False)
    entry_spot_price = Column(Float, nullable=False)
    entry_futures_price = Column(Float, nullable=False)
    quantity = Column(Float, nullable=False)
    leverage = Column(Integer, default=1)
    entry_time = Column(DateTime, default=func.now())
    exit_time = Column(DateTime, nullable=True)
    exit_spot_price = Column(Float, nullable=True)
    exit_futures_price = Column(Float, nullable=True)
    pnl = Column(Float, default=0.0)
    funding_earned = Column(Float, default=0.0)
    status = Column(String(10), default="open")
    notes = Column(Text, default="")


class DBOpportunity(Base):
    """数据库套利机会记录表"""
    __tablename__ = "opportunities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    spot_price = Column(Float, nullable=False)
    futures_price = Column(Float, nullable=False)
    funding_rate = Column(Float, nullable=False)
    annualized_rate = Column(Float, nullable=False)
    premium = Column(Float, nullable=False)
    spread = Column(Float, nullable=False)
    confidence = Column(Float, default=1.0)
    timestamp = Column(DateTime, default=func.now())


class DBConfig(Base):
    """数据库配置存储表"""
    __tablename__ = "config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(50), unique=True, nullable=False)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
