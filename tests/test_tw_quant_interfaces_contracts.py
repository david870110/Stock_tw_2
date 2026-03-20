import inspect

from src.tw_quant.batch.interfaces import BatchRunner, ParameterGridProvider
from src.tw_quant.backtest.exits import ExitRule, PositionClosePolicy
from src.tw_quant.backtest.interfaces import BacktestEngine, ExecutionModel, PortfolioBook
from src.tw_quant.data.interfaces import (
    CorporateActionProvider,
    FundamentalDataProvider,
    MarketDataProvider,
)
from src.tw_quant.reporting.interfaces import MetricsCalculator, ReportBuilder
from src.tw_quant.selection.interfaces import RankingModel, Selector
from src.tw_quant.signal.interfaces import SignalFilter, SignalGenerator
from src.tw_quant.storage.interfaces import ArtifactStore, CanonicalDataStore, RawDataStore
from src.tw_quant.strategy.interfaces import Strategy, StrategyContext
from src.tw_quant.wiring.container import AppContext, build_app_context
from src.tw_quant.config.models import AppConfig


def _assert_has_method(cls: type, method_name: str) -> None:
    assert hasattr(cls, method_name)
    method = getattr(cls, method_name)
    assert callable(method)
    signature = inspect.signature(method)
    assert "self" in signature.parameters


def test_protocol_names_and_core_methods_present():
    _assert_has_method(MarketDataProvider, "fetch_ohlcv")
    _assert_has_method(FundamentalDataProvider, "fetch_fundamentals")
    _assert_has_method(CorporateActionProvider, "fetch_actions")

    _assert_has_method(RawDataStore, "save_raw")
    _assert_has_method(CanonicalDataStore, "load_ohlcv")
    _assert_has_method(ArtifactStore, "save_artifact")

    _assert_has_method(Strategy, "generate_signals")
    _assert_has_method(SignalGenerator, "generate")
    _assert_has_method(SignalFilter, "filter")

    _assert_has_method(Selector, "select")
    _assert_has_method(RankingModel, "score")

    _assert_has_method(ExecutionModel, "execute")
    _assert_has_method(PortfolioBook, "snapshot")
    _assert_has_method(BacktestEngine, "run")
    _assert_has_method(ExitRule, "evaluate")
    _assert_has_method(PositionClosePolicy, "select_trigger")

    _assert_has_method(ParameterGridProvider, "iter_parameter_sets")
    _assert_has_method(BatchRunner, "run_grid")

    _assert_has_method(MetricsCalculator, "calculate")
    _assert_has_method(ReportBuilder, "build")


def test_strategy_context_and_wiring_stub_types():
    context = StrategyContext(strategy_name="demo", as_of="2026-01-01")
    assert context.strategy_name == "demo"

    app_context = build_app_context(AppConfig())
    assert isinstance(app_context, AppContext)
