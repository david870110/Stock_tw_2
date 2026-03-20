"""Selection contracts for ranking and portfolio candidate construction."""

from typing import Protocol, Sequence

from src.tw_quant.core.types import DateLike
from src.tw_quant.schema.models import SelectionRecord, SignalRecord


class RankingModel(Protocol):
    def score(self, signal: SignalRecord) -> float:
        """Return comparable score for a signal."""


class Selector(Protocol):
    def select(
        self, signals: Sequence[SignalRecord], as_of: DateLike
    ) -> list[SelectionRecord]:
        """Select ranked candidates from the filtered signal set."""
