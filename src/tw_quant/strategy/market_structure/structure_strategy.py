"""Market-structure strategy adapter for support/resistance analysis."""

from __future__ import annotations

from collections.abc import Callable

from src.tw_quant.schema.models import FeatureFrameRef, OrderIntent, SignalRecord
from src.tw_quant.strategy.interfaces import StrategyContext
from src.tw_quant.strategy.market_structure.levels import (
    mean_reversion_signal,
    support_resistance,
)

PriceSource = Callable[[FeatureFrameRef], dict[str, list[float]]]


class MarketStructureStrategy:
    """Strategy adapter for market structure analysis using support/resistance."""

    def __init__(
        self,
        price_source: PriceSource,
        level_window: int = 10,
        signal_threshold: float = 0.3,
    ) -> None:
        """Initialize market-structure strategy.
        
        Args:
            price_source: Callable that retrieves price data by symbol
                from a FeatureFrameRef.
            level_window: Window size for support/resistance identification.
            signal_threshold: Distance from support/resistance for signal generation.
        """
        self._price_source = price_source
        self._level_window = level_window
        self._signal_threshold = signal_threshold

    def generate_signals(self, context: StrategyContext) -> list[SignalRecord]:
        """Generate market-structure signals based on support/resistance levels.
        
        Returns empty list if context.feature_ref is None.
        
        For each symbol:
        - Buy if price near support
        - Sell if price near resistance
        - Hold otherwise
        
        Args:
            context: Strategy context with feature reference and timestamp.
            
        Returns:
            List of signal records, one per symbol.
        """
        if context.feature_ref is None:
            return []

        by_symbol = self._price_source(context.feature_ref)
        signals: list[SignalRecord] = []

        for symbol, prices in by_symbol.items():
            if not prices:
                signals.append(
                    SignalRecord(
                        symbol=symbol,
                        timestamp=context.as_of,
                        signal="hold",
                        score=0.0,
                        metadata={
                            "strategy": context.strategy_name,
                            "metric": "level_distance",
                            "support": None,
                            "resistance": None,
                        },
                    )
                )
                continue

            supports, resistances = support_resistance(prices, window=self._level_window)
            
            if not supports or not resistances:
                signals.append(
                    SignalRecord(
                        symbol=symbol,
                        timestamp=context.as_of,
                        signal="hold",
                        score=0.0,
                        metadata={
                            "strategy": context.strategy_name,
                            "metric": "level_distance",
                            "support": None,
                            "resistance": None,
                        },
                    )
                )
                continue

            current_price = prices[-1]
            current_support = supports[-1]
            current_resistance = resistances[-1]

            mr_signal = mean_reversion_signal(
                current_price, current_support, current_resistance
            )

            if mr_signal > self._signal_threshold:
                signal, score = "buy", 1.0
            elif mr_signal < -self._signal_threshold:
                signal, score = "sell", -1.0
            else:
                signal, score = "hold", 0.0

            signals.append(
                SignalRecord(
                    symbol=symbol,
                    timestamp=context.as_of,
                    signal=signal,
                    score=score,
                    metadata={
                        "strategy": context.strategy_name,
                        "metric": "level_distance",
                        "support": current_support,
                        "resistance": current_resistance,
                        "signal_value": mr_signal,
                    },
                )
            )

        return signals

    def build_orders(
        self, context: StrategyContext, selections: list[SignalRecord]
    ) -> list[OrderIntent]:
        """Convert selected signals into market orders.
        
        Filters out hold signals and converts buy/sell to market orders.
        
        Args:
            context: Strategy context with timestamp.
            selections: Selected signals to convert.
            
        Returns:
            List of order intents.
        """
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
