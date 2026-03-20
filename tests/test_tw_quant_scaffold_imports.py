import importlib


MODULES = [
    "src.tw_quant",
    "src.tw_quant.config",
    "src.tw_quant.config.models",
    "src.tw_quant.config.defaults",
    "src.tw_quant.core",
    "src.tw_quant.core.types",
    "src.tw_quant.core.exceptions",
    "src.tw_quant.schema",
    "src.tw_quant.schema.models",
    "src.tw_quant.normalization",
    "src.tw_quant.normalization.models",
    "src.tw_quant.normalization.mappers",
    "src.tw_quant.data",
    "src.tw_quant.data.interfaces",
    "src.tw_quant.fetch",
    "src.tw_quant.fetch.models",
    "src.tw_quant.fetch.interfaces",
    "src.tw_quant.fetch.stubs",
    "src.tw_quant.incremental",
    "src.tw_quant.incremental.models",
    "src.tw_quant.incremental.interfaces",
    "src.tw_quant.incremental.stubs",
    "src.tw_quant.storage",
    "src.tw_quant.storage.interfaces",
    "src.tw_quant.storage.cache",
    "src.tw_quant.storage.cache.models",
    "src.tw_quant.storage.cache.interfaces",
    "src.tw_quant.storage.cache.stubs",
    "src.tw_quant.strategy",
    "src.tw_quant.strategy.interfaces",
    "src.tw_quant.strategy.technical",
    "src.tw_quant.strategy.technical.features",
    "src.tw_quant.strategy.technical.ma_crossover",
    "src.tw_quant.strategy.technical.pullback_trend_compression",
    "src.tw_quant.strategy.chip",
    "src.tw_quant.strategy.chip.indicators",
    "src.tw_quant.strategy.chip.chip_flow_strategy",
    "src.tw_quant.strategy.flow",
    "src.tw_quant.strategy.flow.metrics",
    "src.tw_quant.strategy.flow.flow_analysis_strategy",
    "src.tw_quant.strategy.market_structure",
    "src.tw_quant.strategy.market_structure.levels",
    "src.tw_quant.strategy.market_structure.structure_strategy",
    "src.tw_quant.signal",
    "src.tw_quant.signal.interfaces",
    "src.tw_quant.selection",
    "src.tw_quant.selection.interfaces",
    "src.tw_quant.selection.pipeline",
    "src.tw_quant.backtest",
    "src.tw_quant.backtest.interfaces",
    "src.tw_quant.backtest.engine",
    "src.tw_quant.backtest.exits",
    "src.tw_quant.batch",
    "src.tw_quant.batch.interfaces",
    "src.tw_quant.reporting",
    "src.tw_quant.reporting.interfaces",
    "src.tw_quant.wiring",
    "src.tw_quant.wiring.container",
]


def test_tw_quant_modules_importable_without_circular_errors():
    for module_name in MODULES:
        module = importlib.import_module(module_name)
        assert module is not None


def test_tw_quant_t10_exports_verify_all_symbols() -> None:
    """Verify T10 modules export expected symbols with __all__ defined."""
    
    # Chip module exports
    from src.tw_quant.strategy import chip
    assert hasattr(chip, '__all__')
    assert "ChipFlowStrategy" in chip.__all__
    assert "chip_distribution" in chip.__all__
    assert "chip_concentration" in chip.__all__
    
    from src.tw_quant.strategy.chip import ChipFlowStrategy, chip_distribution, chip_concentration
    assert callable(ChipFlowStrategy)
    assert callable(chip_distribution)
    assert callable(chip_concentration)
    
    # Flow module exports
    from src.tw_quant.strategy import flow
    assert hasattr(flow, '__all__')
    assert "FlowAnalysisStrategy" in flow.__all__
    assert "inflow_outflow" in flow.__all__
    assert "flow_momentum" in flow.__all__
    
    from src.tw_quant.strategy.flow import FlowAnalysisStrategy, inflow_outflow, flow_momentum
    assert callable(FlowAnalysisStrategy)
    assert callable(inflow_outflow)
    assert callable(flow_momentum)
    
    # Market structure module exports
    from src.tw_quant.strategy import market_structure
    assert hasattr(market_structure, '__all__')
    assert "MarketStructureStrategy" in market_structure.__all__
    assert "support_resistance" in market_structure.__all__
    assert "structure_trend" in market_structure.__all__
    
    from src.tw_quant.strategy.market_structure import MarketStructureStrategy, support_resistance, structure_trend
    assert callable(MarketStructureStrategy)
    assert callable(support_resistance)
    assert callable(structure_trend)

    # Technical module exports
    from src.tw_quant.strategy import technical
    assert hasattr(technical, '__all__')
    assert "PullbackTrendCompressionStrategy" in technical.__all__
    assert "macd_histogram" in technical.__all__
    assert "rolling_max" in technical.__all__
    assert "rolling_min" in technical.__all__
    assert "exponential_moving_average" in technical.__all__
    assert "is_negative_histogram_above_prior_negative_min" in technical.__all__

    from src.tw_quant.strategy.technical import (
        PullbackTrendCompressionStrategy,
        exponential_moving_average,
        is_negative_histogram_above_prior_negative_min,
        macd_histogram,
        rolling_max,
        rolling_min,
    )
    assert callable(PullbackTrendCompressionStrategy)
    assert callable(exponential_moving_average)
    assert callable(rolling_max)
    assert callable(rolling_min)
    assert callable(macd_histogram)
    assert callable(is_negative_histogram_above_prior_negative_min)


def test_tw_quant_t12_exports_verify_all_symbols() -> None:
    """Verify T12 selection pipeline exports expected symbols."""

    from src.tw_quant import selection
    assert "SelectionPipeline" in selection.__all__
    assert "SelectionConfig" in selection.__all__

    from src.tw_quant.selection import SelectionConfig, SelectionPipeline
    assert callable(SelectionPipeline)
    assert callable(SelectionConfig)

    from src.tw_quant.selection.pipeline import (
        ConfiguredSelector,
        WeightedRankingModel,
        filter_signals,
        rank_signals,
        select_top,
    )
    assert callable(filter_signals)
    assert callable(rank_signals)
    assert callable(select_top)
    assert callable(WeightedRankingModel)
    assert callable(ConfiguredSelector)


def test_tw_quant_t13_exports_verify_all_symbols() -> None:
    """Verify T13 backtest engine exports expected symbols with __all__ defined."""

    from src.tw_quant import backtest
    assert hasattr(backtest, '__all__')
    assert "SimpleExecutionModel" in backtest.__all__
    assert "InMemoryPortfolioBook" in backtest.__all__
    assert "SymbolBacktestEngine" in backtest.__all__

    from src.tw_quant.backtest import (
        InMemoryPortfolioBook,
        SimpleExecutionModel,
        SymbolBacktestEngine,
    )
    assert callable(SimpleExecutionModel)
    assert callable(InMemoryPortfolioBook)
    assert callable(SymbolBacktestEngine)

    from src.tw_quant.backtest.engine import _to_date, _iter_dates
    assert callable(_to_date)
    assert callable(_iter_dates)


def test_tw_quant_t14_exports_verify_all_symbols() -> None:
    """Verify T14 exit-rule exports remain selectively available."""

    from src.tw_quant import backtest
    assert "ExitRule" in backtest.__all__
    assert "PositionClosePolicy" in backtest.__all__
    assert "SignalExitRule" in backtest.__all__
    assert "StopLossRule" in backtest.__all__
    assert "TakeProfitRule" in backtest.__all__
    assert "MaxHoldingPeriodRule" in backtest.__all__
    assert "PriorityClosePolicy" in backtest.__all__

    from src.tw_quant.backtest import (
        ExitEvaluationContext,
        ExitRule,
        ExitTrigger,
        MaxHoldingPeriodRule,
        OpenPositionState,
        PositionClosePolicy,
        PriorityClosePolicy,
        SignalExitRule,
        StopLossRule,
        TakeProfitRule,
    )

    assert callable(ExitRule)
    assert callable(PositionClosePolicy)
    assert callable(OpenPositionState)
    assert callable(ExitEvaluationContext)
    assert callable(ExitTrigger)
    assert callable(SignalExitRule)
    assert callable(StopLossRule)
    assert callable(TakeProfitRule)
    assert callable(MaxHoldingPeriodRule)
    assert callable(PriorityClosePolicy)
