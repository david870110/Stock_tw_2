"""Typed configuration dataclasses for application wiring."""

from dataclasses import dataclass, field


@dataclass(slots=True)
class BacktestExitConfig:
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    max_holding_days: int | None = None


@dataclass(slots=True)
class BacktestStrategyDefaults:
    exits: BacktestExitConfig = field(default_factory=BacktestExitConfig)


@dataclass(slots=True)
class DataConfig:
    wiring_mode: str = "placeholder"
    market_provider: str = "stub_market"
    fundamental_provider: str = "stub_fundamental"
    corporate_action_provider: str = "stub_corporate_action"
    universe_provider: str = "stub_universe"
    universe: list[str] = field(default_factory=list)
    universe_csv_path: str = ""
    market_ohlcv_url_template: str = ""
    universe_twse_url: str = ""
    universe_tpex_url: str = ""
    timeout_seconds: float = 10.0
    max_retries: int = 2
    retry_backoff_seconds: float = 0.25
    min_interval_seconds: float = 0.0
    batch_size: int = 50
    timezone: str = "Asia/Taipei"


@dataclass(slots=True)
class StorageConfig:
    raw_store: str = "memory"
    canonical_store: str = "memory"
    artifact_store: str = "local"
    base_path: str = "./artifacts"


@dataclass(slots=True)
class BacktestConfig:
    initial_cash: float = 1_000_000.0
    commission_bps: float = 0.0
    slippage_bps: float = 0.0
    benchmark: str = "TAIEX"
    timezone: str = "Asia/Taipei"
    strategy_defaults: dict[str, BacktestStrategyDefaults] = field(default_factory=dict)


@dataclass(slots=True)
class ReportingConfig:
    output_dir: str = "./reports"
    formats: list[str] = field(default_factory=lambda: ["json"])
    timezone: str = "Asia/Taipei"


@dataclass(slots=True)
class AppConfig:
    data: DataConfig = field(default_factory=DataConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    reporting: ReportingConfig = field(default_factory=ReportingConfig)
    timezone: str = "Asia/Taipei"
