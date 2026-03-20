"""Strategy contracts for transforming features into orders/signals."""

from dataclasses import dataclass, field
from typing import Any, Protocol

from src.tw_quant.core.types import DateLike
from src.tw_quant.schema.models import FeatureFrameRef, OrderIntent, SignalRecord


@dataclass(slots=True)
class StrategyContext:
    strategy_name: str
    as_of: DateLike
    parameters: dict[str, Any] = field(default_factory=dict)
    feature_ref: FeatureFrameRef | None = None


class Strategy(Protocol):
    def generate_signals(self, context: StrategyContext) -> list[SignalRecord]:
        """Generate signal records for downstream selection."""

    def build_orders(
        self, context: StrategyContext, selections: list[SignalRecord]
    ) -> list[OrderIntent]:
        """Convert selected signals into executable order intents."""
