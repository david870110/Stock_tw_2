"""Batch orchestration contracts for parameterized runs."""

from typing import Any, Protocol

from src.tw_quant.core.types import DateLike, Symbol
from src.tw_quant.schema.models import BacktestResult, BatchRunRecord, BatchRunResult


class ParameterGridProvider(Protocol):
    def iter_parameter_sets(self) -> list[dict[str, Any]]:
        """Provide parameter combinations for batch execution."""


class BatchCheckpointHook(Protocol):
    def on_batch_start(self, batch_id: str, metadata: dict[str, Any]) -> None:
        """Called once when a batch run begins."""

    def on_run_complete(
        self,
        batch_id: str,
        record: BatchRunRecord,
        result: BacktestResult,
    ) -> None:
        """Called for each successful atomic run."""

    def on_run_error(self, batch_id: str, record: BatchRunRecord, error: Exception) -> None:
        """Called for each failed atomic run."""

    def on_batch_end(self, batch_id: str, result: BatchRunResult) -> None:
        """Called once when a batch run completes."""


class BatchRunner(Protocol):
    def run_grid(
        self,
        parameter_sets: list[dict[str, Any]],
        symbols: list[Symbol],
        windows: list[tuple[DateLike, DateLike]],
        checkpoint_hook: BatchCheckpointHook | None = None,
        batch_label: str | None = None,
    ) -> BatchRunResult:
        """Execute batch run for the provided parameter sets."""
