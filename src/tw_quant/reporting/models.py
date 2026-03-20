"""Reporting-side supplemental input models and resolver helpers."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.tw_quant.core.types import DateLike
from src.tw_quant.schema.models import FillRecord, PortfolioSnapshot


SCHEMA_VERSION = 0.1


@dataclass(slots=True)
class SupplementalReportingInputs:
    """Supplemental inputs registered by run_id for reporting-only concerns."""

    fills: list[FillRecord] = field(default_factory=list)
    snapshots: list[PortfolioSnapshot] = field(default_factory=list)
    base_location: str | None = None
    path_stem: str | None = None
    created_at: DateLike | None = None


class InMemoryReportingInputResolver:
    """Thread-unsafe in-memory resolver keyed by backtest run_id."""

    def __init__(self) -> None:
        self._entries: dict[str, SupplementalReportingInputs] = {}

    def register(self, run_id: str, inputs: SupplementalReportingInputs) -> None:
        self._entries[run_id] = inputs

    def resolve(self, run_id: str) -> SupplementalReportingInputs | None:
        return self._entries.get(run_id)
