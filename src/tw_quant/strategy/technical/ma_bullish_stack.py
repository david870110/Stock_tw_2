"""Simple moving-average bullish-stack (多頭排列) strategy adapter."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.tw_quant.schema.models import FeatureFrameRef, OrderIntent, SignalRecord
from src.tw_quant.strategy.interfaces import StrategyContext
from src.tw_quant.strategy.technical.features import simple_moving_average

FeatureSource = Callable[[FeatureFrameRef], dict[str, list[float]]]


class MovingAverageBullishStackStrategy:
    def __init__(
        self,
        feature_source: FeatureSource,
        *,
        short_window: int = 5,
        mid_window: int = 20,
        long_window: int = 60,
    ) -> None:
        self._feature_source = feature_source

        if not _is_strict_int(short_window) or not _is_strict_int(mid_window) or not _is_strict_int(long_window):
            raise ValueError("MA windows must be integers")
        if short_window < 1:
            raise ValueError("short_window must be >= 1")
        if not (short_window < mid_window < long_window):
            raise ValueError("Expected 1 <= short_window < mid_window < long_window")

        self._short_window = short_window
        self._mid_window = mid_window
        self._long_window = long_window

    def generate_signals(self, context: StrategyContext) -> list[SignalRecord]:
        if context.feature_ref is None:
            return []

        by_symbol = self._feature_source(context.feature_ref)
        signals: list[SignalRecord] = []

        for symbol, close_values in by_symbol.items():
            passed, metadata, signal, score = self._evaluate_symbol(close_values, context.strategy_name)
            signals.append(
                SignalRecord(
                    symbol=symbol,
                    timestamp=context.as_of,
                    signal=signal,
                    score=score,
                    metadata=metadata,
                )
            )

        return signals

    def build_orders(self, context: StrategyContext, selections: list[SignalRecord]) -> list[OrderIntent]:
        return [
            OrderIntent(
                symbol=signal.symbol,
                timestamp=context.as_of,
                side="buy",
                quantity=1.0,
                order_type="market",
            )
            for signal in selections
            if signal.signal == "buy"
        ]

    def _evaluate_symbol(
        self,
        close_values: list[float],
        strategy_name: str,
    ) -> tuple[bool, dict[str, Any], str, float]:
        provided_bars = len(close_values)
        index = provided_bars - 1

        ma_short = simple_moving_average(close_values, self._short_window) if close_values else []
        ma_mid = simple_moving_average(close_values, self._mid_window) if close_values else []
        ma_long = simple_moving_average(close_values, self._long_window) if close_values else []

        ma_short_current = ma_short[index] if index >= 0 and ma_short else None
        ma_mid_current = ma_mid[index] if index >= 0 and ma_mid else None
        ma_long_current = ma_long[index] if index >= 0 and ma_long else None

        metadata: dict[str, Any] = {
            "strategy": strategy_name,
            "indicator": "ma_bullish_stack",
            "short_window": self._short_window,
            "mid_window": self._mid_window,
            "long_window": self._long_window,
            "stack": False,
            "ma_short": ma_short_current,
            "ma_mid": ma_mid_current,
            "ma_long": ma_long_current,
        }

        if (
            not close_values
            or ma_short_current is None
            or ma_mid_current is None
            or ma_long_current is None
        ):
            metadata.update(
                {
                    "reason": "insufficient_history",
                    "required_bars": self._long_window,
                    "provided_bars": provided_bars,
                }
            )
            return False, metadata, "hold", 0.0

        stacked = ma_short_current > ma_mid_current > ma_long_current
        metadata["stack"] = stacked
        if stacked:
            return True, metadata, "buy", 1.0
        return False, metadata, "hold", 0.0


def _is_strict_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
