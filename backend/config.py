"""
配置管理模块
"""
import os
import configparser
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()


class BinanceConfig(BaseModel):
    """币安 API 配置"""
    spot_api_key: str = ""
    spot_secret_key: str = ""
    futures_api_key: str = ""
    futures_secret_key: str = ""


class TradingConfig(BaseModel):
    """交易配置"""
    enabled_pairs: list[str] = []
    min_funding_rate: float = 0.01
    max_trade_amount: float = 1000.0
    leverage: int = 3
    auto_execute: bool = False


class MonitoringConfig(BaseModel):
    """监控配置"""
    refresh_interval: int = 5


class DatabaseConfig(BaseModel):
    """数据库配置"""
    db_path: str = "./data/arbitrage.db"


class ServerConfig(BaseModel):
    """服务器配置"""
    host: str = "0.0.0.0"
    port: int = 5000
    debug: bool = True


class LoggingConfig(BaseModel):
    """日志配置"""
    log_level: str = "INFO"
    log_file: str = "./logs/arbitrage.log"


class AppConfig(BaseModel):
    """全局配置"""
    binance: BinanceConfig = Field(default_factory=BinanceConfig)
    trading: TradingConfig = Field(default_factory=TradingConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


def load_config(config_path: str = "config.ini") -> AppConfig:
    """从配置文件加载配置"""
    config_parser = configparser.ConfigParser()

    if not os.path.exists(config_path):
        return AppConfig(
            binance=BinanceConfig(
                spot_api_key=os.getenv("BINANCE_SPOT_API_KEY", ""),
                spot_secret_key=os.getenv("BINANCE_SPOT_SECRET_KEY", ""),
                futures_api_key=os.getenv("BINANCE_FUTURES_API_KEY", ""),
                futures_secret_key=os.getenv("BINANCE_FUTURES_SECRET_KEY", ""),
            ),
            trading=TradingConfig(
                enabled_pairs=os.getenv("ENABLED_PAIRS", "").split(",") if os.getenv("ENABLED_PAIRS") else [],
                min_funding_rate=float(os.getenv("MIN_FUNDING_RATE", "0.01")),
                max_trade_amount=float(os.getenv("MAX_TRADE_AMOUNT", "1000")),
                leverage=int(os.getenv("LEVERAGE", "3")),
                auto_execute=os.getenv("AUTO_EXECUTE", "false").lower() == "true",
            ),
            monitoring=MonitoringConfig(
                refresh_interval=int(os.getenv("REFRESH_INTERVAL", "5")),
            ),
            database=DatabaseConfig(
                db_path=os.getenv("DB_PATH", "./data/arbitrage.db"),
            ),
            server=ServerConfig(
                host=os.getenv("HOST", "0.0.0.0"),
                port=int(os.getenv("PORT", "5000")),
                debug=os.getenv("DEBUG", "true").lower() == "true",
            ),
            logging=LoggingConfig(
                log_level=os.getenv("LOG_LEVEL", "INFO"),
                log_file=os.getenv("LOG_FILE", "./logs/arbitrage.log"),
            ),
        )

    config_parser.read(config_path)

    return AppConfig(
        binance=BinanceConfig(
            spot_api_key=config_parser.get("binance", "spot_api_key", fallback=""),
            spot_secret_key=config_parser.get("binance", "spot_secret_key", fallback=""),
            futures_api_key=config_parser.get("binance", "futures_api_key", fallback=""),
            futures_secret_key=config_parser.get("binance", "futures_secret_key", fallback=""),
        ),
        trading=TradingConfig(
            enabled_pairs=config_parser.get("trading", "enabled_pairs", fallback="").split(",") if config_parser.get("trading", "enabled_pairs", fallback="") else [],
            min_funding_rate=float(config_parser.get("trading", "min_funding_rate", fallback="0.01")),
            max_trade_amount=float(config_parser.get("trading", "max_trade_amount", fallback="1000")),
            leverage=int(config_parser.get("trading", "leverage", fallback="3")),
            auto_execute=config_parser.get("trading", "auto_execute", fallback="false").lower() == "true",
        ),
        monitoring=MonitoringConfig(
            refresh_interval=int(config_parser.get("monitoring", "refresh_interval", fallback="5")),
        ),
        database=DatabaseConfig(
            db_path=config_parser.get("database", "db_path", fallback="./data/arbitrage.db"),
        ),
        server=ServerConfig(
            host=config_parser.get("server", "host", fallback="0.0.0.0"),
            port=int(config_parser.get("server", "port", fallback="5000")),
            debug=config_parser.get("server", "debug", fallback="true").lower() == "true",
        ),
        logging=LoggingConfig(
            log_level=config_parser.get("logging", "log_level", fallback="INFO"),
            log_file=config_parser.get("logging", "log_file", fallback="./logs/arbitrage.log"),
        ),
    )


config = load_config()
