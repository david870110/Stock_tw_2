"""Contracts for incremental update planning and execution scaffolding."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Protocol

from src.tw_quant.incremental.models import (
    DateWindow,
    IncrementalUpdateRequest,
    IncrementalUpdateResult,
    SymbolWindowPlan,
    WindowAttemptOutcome,
)


class MissingWindowComputer(Protocol):
    """Deterministic boundary computer for missing date windows."""

    def compute(self, start: date, end: date, covered: tuple[DateWindow, ...]) -> tuple[DateWindow, ...]:
        """Return uncovered inclusive windows inside [start, end]."""


class SymbolWindowPlanner(Protocol):
    """Plan missing windows for each symbol using cache metadata boundaries."""

    def plan(self, request: IncrementalUpdateRequest) -> tuple[SymbolWindowPlan, ...]:
        """Build deterministic symbol plans for the requested range."""


class WindowDataFetcher(Protocol):
    """Fetches data for a symbol/window attempt without external side effects here."""

    def fetch(self, symbol: str, window: DateWindow, request: IncrementalUpdateRequest) -> Mapping[str, Any]:
        """Return payload for one symbol-window request."""


class IncrementalAttemptRunner(Protocol):
    """Runs retry attempts for planned windows and reports outcomes."""

    def run_attempts(
        self,
        plans: tuple[SymbolWindowPlan, ...],
        request: IncrementalUpdateRequest,
    ) -> tuple[WindowAttemptOutcome, ...]:
        """Execute all planned windows and collect attempt outcomes."""


class IncrementalUpdateOrchestrator(Protocol):
    """Coordinates incremental update flow: plan, attempt, collect outcomes."""

    def run(self, request: IncrementalUpdateRequest) -> IncrementalUpdateResult:
        """Execute full incremental update orchestration."""
