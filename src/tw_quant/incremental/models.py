"""Models for incremental update planning and execution scaffolding."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal, Mapping

from src.tw_quant.core.types import Symbol


@dataclass(slots=True, frozen=True)
class DateWindow:
    """Inclusive date window boundary used by incremental updates."""

    start: date
    end: date


@dataclass(slots=True, frozen=True)
class IncrementalUpdateRequest:
    """Input shape for incremental update orchestration."""

    dataset: str
    symbols: tuple[Symbol, ...]
    start: date
    end: date
    request_id: str
    max_attempts: int = 1
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class SymbolWindowPlan:
    """Per-symbol missing-window plan computed from cache boundaries."""

    symbol: Symbol
    cache_key: str
    missing_windows: tuple[DateWindow, ...]


@dataclass(slots=True, frozen=True)
class WindowAttemptOutcome:
    """Outcome record for a single missing-window attempt."""

    symbol: Symbol
    window: DateWindow
    outcome: Literal["success", "failure"]
    attempts: int
    payload: Mapping[str, Any] | None = None
    error_type: str | None = None
    error_message: str | None = None


@dataclass(slots=True, frozen=True)
class IncrementalUpdateResult:
    """Collected plan and execution outcomes for an incremental request."""

    request_id: str
    plans: tuple[SymbolWindowPlan, ...]
    outcomes: tuple[WindowAttemptOutcome, ...]
