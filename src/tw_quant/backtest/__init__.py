"""Backtest execution interfaces."""

from src.tw_quant.backtest.exits import (
    AtrInitialStopRule,
    ExitEvaluationContext,
    ExitRule,
    ExitTrigger,
    MaxHoldingPeriodRule,
    OpenPositionState,
    PositionClosePolicy,
    PriorityClosePolicy,
    ProfitProtectionExitRule,
    SignalExitRule,
    StopLossRule,
    TakeProfitRule,
    TrendBreakExitRule,
)
from src.tw_quant.backtest.interfaces import BacktestEngine, ExecutionModel, PortfolioBook
from src.tw_quant.backtest.engine import (
    InMemoryPortfolioBook,
    SimpleExecutionModel,
    SymbolBacktestEngine,
)

__all__ = [
    "ExecutionModel",
    "PortfolioBook",
    "BacktestEngine",
    "SimpleExecutionModel",
    "InMemoryPortfolioBook",
    "SymbolBacktestEngine",
    "ExitRule",
    "PositionClosePolicy",
    "OpenPositionState",
    "ExitEvaluationContext",
    "ExitTrigger",
    "SignalExitRule",
    "StopLossRule",
    "TakeProfitRule",
    "MaxHoldingPeriodRule",
    "AtrInitialStopRule",
    "TrendBreakExitRule",
    "ProfitProtectionExitRule",
    "PriorityClosePolicy",
]
