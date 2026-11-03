"""Validated configuration. Environment variables override the selected INI file."""
import configparser
import json
import os
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field
from dotenv import load_dotenv


class Settings(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra="forbid", allow_inf_nan=False)


class BinanceConfig(Settings):
    spot_api_key: str = ""
    spot_secret_key: str = ""
    futures_api_key: str = ""
    futures_secret_key: str = ""
    testnet: bool = True


class TradingConfig(Settings):
    enabled_pairs: list[str] = Field(default_factory=list)
    min_funding_rate: float = Field(default=0.01, ge=0, le=100)
    max_trade_amount: float = Field(default=1000, ge=50)
    leverage: int = Field(default=3, ge=1, le=125)
    auto_execute: bool = False


class MonitoringConfig(Settings):
    refresh_interval: int = Field(default=30, ge=5, le=3600)


class DatabaseConfig(Settings):
    db_path: str = "./data/arbitrage.db"


class ServerConfig(Settings):
    host: str = "127.0.0.1"
    port: int = Field(default=5000, ge=1, le=65535)
    debug: bool = False


class AppConfig(Settings):
    binance: BinanceConfig = Field(default_factory=BinanceConfig)
    trading: TradingConfig = Field(default_factory=TradingConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)


def load_config(config_path=None):
    path = Path(config_path or os.getenv("CONFIG_PATH", "config.ini")).expanduser().resolve()
    load_dotenv(path.parent / ".env", override=False)
    parser = configparser.ConfigParser(inline_comment_prefixes=("#", ";"), interpolation=None)
    parser.read(path)
    sections = {}
    models = {"binance": BinanceConfig, "trading": TradingConfig,
              "monitoring": MonitoringConfig, "database": DatabaseConfig, "server": ServerConfig}
    for section, model in models.items():
        values = {}
        for key in model.model_fields:
            env = ("BINANCE_" + key.upper()) if section == "binance" else key.upper()
            # Preserve the existing HOST/PORT/DEBUG/DB_PATH environment names.
            raw = os.getenv(env, parser.get(section, key, fallback=None))
            if raw is None:
                continue
            raw = raw.strip().strip('"').strip("'")
            if key == "enabled_pairs":
                raw = json.loads(raw) if raw.startswith("[") else [s.strip().upper() for s in raw.split(",") if s.strip()]
            values[key] = raw
        sections[section] = model(**values)
    cfg = AppConfig(**sections)
    db_path = Path(cfg.database.db_path)
    if not db_path.is_absolute():
        cfg.database.db_path = str(path.parent / db_path)
    return cfg
