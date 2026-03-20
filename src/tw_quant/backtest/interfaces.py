"""Backtest contracts for execution, bookkeeping, and orchestration."""

from typing import Protocol, Sequence

from src.tw_quant.core.types import DateLike
from src.tw_quant.schema.models import (
    BacktestResult,
    FillRecord,
    OrderIntent,
    PortfolioSnapshot,
)


class ExecutionModel(Protocol):
    def execute(
        self, intents: Sequence[OrderIntent], timestamp: DateLike
    ) -> list[FillRecord]:
        """Translate order intents to simulated fills."""


class PortfolioBook(Protocol):
    def apply_fills(self, fills: Sequence[FillRecord]) -> None:
        """Apply fills to internal portfolio state."""

    def snapshot(self, timestamp: DateLike) -> PortfolioSnapshot:
        """Read current portfolio state at a specific time."""


class BacktestEngine(Protocol):
    def run(self, start: DateLike, end: DateLike) -> BacktestResult:
        """Run backtest between two dates and return summarized result."""
