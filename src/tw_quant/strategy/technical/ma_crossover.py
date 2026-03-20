"""Reference moving-average crossover strategy adapter."""

from __future__ import annotations

from collections.abc import Callable

from src.tw_quant.schema.models import FeatureFrameRef, OrderIntent, SignalRecord
from src.tw_quant.strategy.interfaces import StrategyContext
from src.tw_quant.strategy.technical.features import crossover_direction, simple_moving_average

FeatureSource = Callable[[FeatureFrameRef], dict[str, list[float]]]


class MovingAverageCrossoverStrategy:
    def __init__(
        self,
        feature_source: FeatureSource,
        short_window: int = 5,
        long_window: int = 20,
        signal_on_no_cross: str = "hold",
    ) -> None:
        self._feature_source = feature_source
        self._short_window = short_window
        self._long_window = long_window
        self._signal_on_no_cross = signal_on_no_cross

    def generate_signals(self, context: StrategyContext) -> list[SignalRecord]:
        if context.feature_ref is None:
            return []

        by_symbol = self._feature_source(context.feature_ref)
        signals: list[SignalRecord] = []

        for symbol, close_values in by_symbol.items():
            short_ma = simple_moving_average(close_values, self._short_window)
            long_ma = simple_moving_average(close_values, self._long_window)
            direction = crossover_direction(short_ma, long_ma)[-1] if close_values else "no_cross"

            signal, score = self._map_direction(direction)
            signals.append(
                SignalRecord(
                    symbol=symbol,
                    timestamp=context.as_of,
                    signal=signal,
                    score=score,
                    metadata={
                        "strategy": context.strategy_name,
                        "indicator": "ma_crossover",
                        "short_window": self._short_window,
                        "long_window": self._long_window,
                    },
                )
            )

        return signals

    def build_orders(
        self, context: StrategyContext, selections: list[SignalRecord]
    ) -> list[OrderIntent]:
        orders: list[OrderIntent] = []
        for signal in selections:
            if signal.signal == "buy":
                orders.append(
                    OrderIntent(
                        symbol=signal.symbol,
                        timestamp=context.as_of,
                        side="buy",
                        quantity=1.0,
                        order_type="market",
                    )
                )
            elif signal.signal == "sell":
                orders.append(
                    OrderIntent(
                        symbol=signal.symbol,
                        timestamp=context.as_of,
                        side="sell",
                        quantity=1.0,
                        order_type="market",
                    )
                )
        return orders

    def _map_direction(self, direction: str) -> tuple[str, float]:
        if direction == "bullish_cross":
            return "buy", 1.0
        if direction == "bearish_cross":
            return "sell", -1.0

        if self._signal_on_no_cross == "buy":
            return "buy", 1.0
        if self._signal_on_no_cross == "sell":
            return "sell", -1.0
        return "hold", 0.0
