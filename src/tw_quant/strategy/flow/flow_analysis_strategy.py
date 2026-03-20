"""Flow-analysis strategy adapter for volume and momentum analysis."""

from __future__ import annotations

from collections.abc import Callable

from src.tw_quant.schema.models import FeatureFrameRef, OrderIntent, SignalRecord
from src.tw_quant.strategy.flow.metrics import flow_momentum, flow_ratio, inflow_outflow
from src.tw_quant.strategy.interfaces import StrategyContext

VolumeSource = Callable[[FeatureFrameRef], dict[str, list[float]]]


class FlowAnalysisStrategy:
    """Strategy adapter for flow analysis based on volume momentum."""

    def __init__(
        self,
        volume_source: VolumeSource,
        momentum_window: int = 5,
        momentum_threshold: float = 0.5,
    ) -> None:
        """Initialize flow-analysis strategy.
        
        Args:
            volume_source: Callable that retrieves volume data by symbol
                from a FeatureFrameRef.
            momentum_window: Rolling window for momentum calculation.
            momentum_threshold: Threshold for buy/sell signal generation.
        """
        self._volume_source = volume_source
        self._momentum_window = momentum_window
        self._momentum_threshold = momentum_threshold

    def generate_signals(self, context: StrategyContext) -> list[SignalRecord]:
        """Generate flow-analysis signals based on momentum thresholds.
        
        Returns empty list if context.feature_ref is None.
        
        For each symbol:
        - Buy if momentum > threshold
        - Sell if momentum < -threshold
        - Hold otherwise
        
        Args:
            context: Strategy context with feature reference and timestamp.
            
        Returns:
            List of signal records, one per symbol.
        """
        if context.feature_ref is None:
            return []

        by_symbol = self._volume_source(context.feature_ref)
        signals: list[SignalRecord] = []

        for symbol, volumes in by_symbol.items():
            if not volumes:
                signals.append(
                    SignalRecord(
                        symbol=symbol,
                        timestamp=context.as_of,
                        signal="hold",
                        score=0.0,
                        metadata={
                            "strategy": context.strategy_name,
                            "metric": "momentum",
                            "threshold": self._momentum_threshold,
                            "momentum": None,
                        },
                    )
                )
                continue

            # Approximate momentum: net inflow over window
            momentum_values = flow_momentum(volumes, window=self._momentum_window)
            last_momentum = momentum_values[-1] if momentum_values else None

            if last_momentum is None:
                signal, score = "hold", 0.0
            elif last_momentum > self._momentum_threshold:
                signal, score = "buy", 1.0
            elif last_momentum < -self._momentum_threshold:
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
                        "metric": "momentum",
                        "threshold": self._momentum_threshold,
                        "momentum": last_momentum,
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
