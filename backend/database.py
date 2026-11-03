"""
数据库管理模块
"""
import os
import sys
import logging
from typing import Optional, List
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager

from sqlalchemy import create_engine, and_
from sqlalchemy.orm import sessionmaker, Session


# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.models import Base, DBTrade, DBOpportunity, DBConfig

logger = logging.getLogger(__name__)


class Database:
    """数据库管理类"""

    def __init__(self, db_path: str = "./data/arbitrage.db"):
        """
        初始化数据库

        Args:
            db_path: 数据库文件路径
        """
        # 确保目录存在
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)

        # 创建数据库引擎
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False, "timeout": 15},
            pool_pre_ping=True,
            echo=False
        )

        # 创建表
        Base.metadata.create_all(self.engine)

        # 创建会话工厂
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine
        )

        logger.info(f"数据库初始化完成: {db_path}")

    @contextmanager
    def get_session(self) -> Session:
        """获取数据库会话"""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"数据库会话错误: {e}")
            raise
        finally:
            session.close()

    # ============ 交易记录操作 ============

    def save_trade(self, trade_data: dict) -> int:
        """保存交易记录"""
        with self.get_session() as session:
            trade = DBTrade(**trade_data)
            session.add(trade)
            session.flush()
            return trade.id

    def update_trade(self, trade_id: int, update_data: dict):
        """更新交易记录"""
        with self.get_session() as session:
            trade = session.query(DBTrade).filter(DBTrade.id == trade_id).first()
            if trade:
                for key, value in update_data.items():
                    setattr(trade, key, value)

    def get_trade(self, trade_id: int) -> Optional[dict]:
        """获取交易记录"""
        with self.get_session() as session:
            trade = session.query(DBTrade).filter(DBTrade.id == trade_id).first()
            if trade:
                return {
                    "id": trade.id,
                    "symbol": trade.symbol,
                    "side": trade.side,
                    "entry_spot_price": trade.entry_spot_price,
                    "entry_futures_price": trade.entry_futures_price,
                    "quantity": trade.quantity,
                    "leverage": trade.leverage,
                    "entry_time": trade.entry_time,
                    "exit_time": trade.exit_time,
                    "pnl": trade.pnl,
                    "funding_earned": trade.funding_earned,
                    "status": trade.status,
                    "notes": trade.notes
                }
            return None

    def get_open_trades(self) -> List[dict]:
        """获取所有未平仓交易"""
        with self.get_session() as session:
            trades = session.query(DBTrade).filter(DBTrade.status == "open").all()
            return [self._trade_to_dict(t) for t in trades]

    def get_closed_trades(self, days: int = 30) -> List[dict]:
        """获取已平仓交易"""
        with self.get_session() as session:
            cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
            trades = session.query(DBTrade).filter(
                and_(
                    DBTrade.status == "closed",
                    DBTrade.exit_time >= cutoff
                )
            ).order_by(DBTrade.exit_time.desc()).all()
            return [self._trade_to_dict(t) for t in trades]

    def get_all_trades(self, limit: int = 100) -> List[dict]:
        """获取所有交易"""
        with self.get_session() as session:
            trades = session.query(DBTrade).order_by(
                DBTrade.entry_time.desc()
            ).limit(limit).all()
            return [self._trade_to_dict(t) for t in trades]

    def get_trade_stats(self) -> dict:
        """获取交易统计"""
        with self.get_session() as session:
            total = session.query(DBTrade).count()
            closed = session.query(DBTrade).filter(DBTrade.status == "closed").count()
            open_pos = session.query(DBTrade).filter(DBTrade.status == "open").count()

            # 计算盈亏
            closed_trades = session.query(DBTrade).filter(DBTrade.status == "closed").all()
            total_pnl = sum(t.pnl for t in closed_trades)
            total_funding = sum(t.funding_earned for t in closed_trades)

            # 计算胜率
            winning_trades = [t for t in closed_trades if t.pnl > 0]
            win_rate = len(winning_trades) / closed if closed > 0 else 0

            return {
                "total_trades": total,
                "closed_trades": closed,
                "open_positions": open_pos,
                "total_pnl": total_pnl,
                "total_funding": total_funding,
                "win_rate": win_rate
            }

    @staticmethod
    def _trade_to_dict(trade: DBTrade) -> dict:
        """交易对象转字典"""
        return {
            "id": trade.id,
            "symbol": trade.symbol,
            "side": trade.side,
            "entry_spot_price": trade.entry_spot_price,
            "entry_futures_price": trade.entry_futures_price,
            "quantity": trade.quantity,
            "leverage": trade.leverage,
            "entry_time": trade.entry_time.isoformat() if trade.entry_time else None,
            "exit_time": trade.exit_time.isoformat() if trade.exit_time else None,
            "exit_spot_price": trade.exit_spot_price,
            "exit_futures_price": trade.exit_futures_price,
            "pnl": trade.pnl,
            "funding_earned": trade.funding_earned,
            "status": trade.status,
            "notes": trade.notes
        }

    # ============ 套利机会记录操作 ============

    def save_opportunity(self, opp_data: dict) -> int:
        """保存套利机会"""
        with self.get_session() as session:
            opportunity = DBOpportunity(**opp_data)
            session.add(opportunity)
            session.flush()
            return opportunity.id

    def save_opportunities_batch(self, opportunities: List[dict]):
        """批量保存套利机会"""
        with self.get_session() as session:
            for opp in opportunities:
                session.add(DBOpportunity(**opp))
            session.commit()

    def get_recent_opportunities(self, hours: int = 24, limit: int = 100) -> List[dict]:
        """获取最近的套利机会"""
        with self.get_session() as session:
            cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)
            opportunities = session.query(DBOpportunity).filter(
                DBOpportunity.timestamp >= cutoff
            ).order_by(DBOpportunity.timestamp.desc()).limit(limit).all()

            return [{
                "id": o.id,
                "symbol": o.symbol,
                "spot_price": o.spot_price,
                "futures_price": o.futures_price,
                "funding_rate": o.funding_rate,
                "annualized_rate": o.annualized_rate,
                "premium": o.premium,
                "spread": o.spread,
                "confidence": o.confidence,
                "timestamp": o.timestamp.isoformat()
            } for o in opportunities]

    # ============ 配置存储操作 ============

    def save_config(self, key: str, value: str):
        """保存配置"""
        with self.get_session() as session:
            config = session.query(DBConfig).filter(DBConfig.key == key).first()
            if config:
                config.value = value
            else:
                config = DBConfig(key=key, value=value)
                session.add(config)

    def get_config(self, key: str) -> Optional[str]:
        """获取配置"""
        with self.get_session() as session:
            config = session.query(DBConfig).filter(DBConfig.key == key).first()
            return config.value if config else None

    def get_all_configs(self) -> dict:
        """获取所有配置"""
        with self.get_session() as session:
            configs = session.query(DBConfig).all()
            return {c.key: c.value for c in configs}

    # ============ 清理和维护 ============

    def cleanup_old_opportunities(self, days: int = 7):
        """清理旧的套利机会记录"""
        with self.get_session() as session:
            cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
            session.query(DBOpportunity).filter(
                DBOpportunity.timestamp < cutoff
            ).delete()


    def save_configs(self, values: dict):
        """Atomically persist one complete strategy document."""
        with self.get_session() as session:
            for key, value in values.items():
                record = session.query(DBConfig).filter(DBConfig.key == key).first()
                if record:
                    record.value = value
                else:
                    session.add(DBConfig(key=key, value=value))
