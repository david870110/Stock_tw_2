"""Serializable canonical dataclasses for research and backtesting objects."""

from dataclasses import dataclass, field
from typing import Any

from src.tw_quant.core.types import DateLike, Symbol


@dataclass(slots=True)
class OHLCVBar:
    symbol: Symbol
    date: DateLike
    open: float
    high: float
    low: float
    close: float
    volume: float
    turnover: float | None = None


@dataclass(slots=True)
class CorporateAction:
    symbol: Symbol
    ex_date: DateLike
    action_type: str
    value: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FundamentalPoint:
    symbol: Symbol
    date: DateLike
    metric: str
    value: float
    source: str = ""


@dataclass(slots=True)
class FeatureFrameRef:
    frame_id: str
    as_of: DateLike
    symbols: list[Symbol] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    storage_uri: str = ""


@dataclass(slots=True)
class SignalRecord:
    symbol: Symbol
    timestamp: DateLike
    signal: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SelectionRecord:
    symbol: Symbol
    timestamp: DateLike
    rank: int
    weight: float
    reason: str = ""


@dataclass(slots=True)
class OrderIntent:
    symbol: Symbol
    timestamp: DateLike
    side: str
    quantity: float
    order_type: str = "market"
    limit_price: float | None = None


@dataclass(slots=True)
class FillRecord:
    symbol: Symbol
    timestamp: DateLike
    side: str
    quantity: float
    price: float
    fee: float = 0.0


@dataclass(slots=True)
class PortfolioSnapshot:
    timestamp: DateLike
    cash: float
    holdings: dict[Symbol, float] = field(default_factory=dict)
    nav: float = 0.0


@dataclass(slots=True)
class BacktestResult:
    run_id: str
    strategy_name: str
    start: DateLike
    end: DateLike
    metrics: dict[str, float] = field(default_factory=dict)
    equity_curve_ref: FeatureFrameRef | None = None
    trades: list[dict[str, Any]] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class BatchRunRecord:
    run_id: str
    symbol: Symbol
    strategy_name: str
    start: DateLike
    end: DateLike
    status: str
    artifact_path: str
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BatchRunResult:
    batch_id: str
    run_count: int
    results: list[BacktestResult] = field(default_factory=list)
    best_run_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    run_records: list[BatchRunRecord] = field(default_factory=list)
    failed_count: int = 0
    success_count: int = 0


@dataclass(slots=True)
class ReportArtifact:
    artifact_id: str
    report_type: str
    path: str
    created_at: DateLike
    metadata: dict[str, Any] = field(default_factory=dict)
