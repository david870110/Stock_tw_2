"""Signal generation and filtering contracts."""

from typing import Protocol, Sequence

from src.tw_quant.schema.models import FeatureFrameRef, SignalRecord


class SignalGenerator(Protocol):
    def generate(self, features: FeatureFrameRef) -> list[SignalRecord]:
        """Generate raw signals from canonical feature references."""


class SignalFilter(Protocol):
    def filter(self, signals: Sequence[SignalRecord]) -> list[SignalRecord]:
        """Filter or transform signals before ranking and selection."""
