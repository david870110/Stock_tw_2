"""Models for raw historical fetch orchestration scaffolding."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Mapping, Sequence

from src.tw_quant.core.types import DateLike, Symbol


@dataclass(slots=True, frozen=True)
class RawFetchRequest:
    """Provider-agnostic request shape for raw historical fetch workflows."""

    provider: str
    dataset: str
    symbols: tuple[Symbol, ...]
    start: DateLike
    end: DateLike
    request_id: str
    requested_at: datetime
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class RetryBackoffPolicy:
    """Retry and backoff placeholders used by orchestration control flow."""

    max_attempts: int = 1
    backoff_schedule_seconds: tuple[float, ...] = ()


@dataclass(slots=True, frozen=True)
class RawArtifactRecord:
    """Raw payload artifact metadata, explicitly isolated from downstream processing."""

    namespace: str
    key: str
    payload: Mapping[str, Any]
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class RawFetchResultRecord:
    """Result record shape for successful or failed raw fetch attempts."""

    request_id: str
    outcome: Literal["success", "failure"]
    attempts: int
    raw_artifact: RawArtifactRecord | None
    error_type: str | None = None
    error_message: str | None = None
    planned_backoff_seconds: Sequence[float] = field(default_factory=tuple)
