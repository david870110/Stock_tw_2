"""Incremental update planning and orchestration scaffolding."""

from src.tw_quant.incremental.interfaces import (
    IncrementalAttemptRunner,
    IncrementalUpdateOrchestrator,
    MissingWindowComputer,
    SymbolWindowPlanner,
    WindowDataFetcher,
)
from src.tw_quant.incremental.models import (
    DateWindow,
    IncrementalUpdateRequest,
    IncrementalUpdateResult,
    SymbolWindowPlan,
    WindowAttemptOutcome,
)
from src.tw_quant.incremental.stubs import (
    DeterministicMissingWindowComputer,
    InMemoryIncrementalAttemptRunner,
    InMemoryIncrementalUpdateOrchestrator,
    InMemorySymbolWindowPlanner,
    InMemoryWindowDataFetcher,
)

__all__ = [
    "DateWindow",
    "IncrementalUpdateRequest",
    "SymbolWindowPlan",
    "WindowAttemptOutcome",
    "IncrementalUpdateResult",
    "MissingWindowComputer",
    "SymbolWindowPlanner",
    "WindowDataFetcher",
    "IncrementalAttemptRunner",
    "IncrementalUpdateOrchestrator",
    "DeterministicMissingWindowComputer",
    "InMemorySymbolWindowPlanner",
    "InMemoryWindowDataFetcher",
    "InMemoryIncrementalAttemptRunner",
    "InMemoryIncrementalUpdateOrchestrator",
]
