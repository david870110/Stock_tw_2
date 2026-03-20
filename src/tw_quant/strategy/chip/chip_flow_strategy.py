"""Chip-flow strategy adapter for holder concentration analysis."""

from __future__ import annotations

from collections.abc import Callable

from src.tw_quant.schema.models import FeatureFrameRef, OrderIntent, SignalRecord
from src.tw_quant.strategy.chip.indicators import (
    chip_concentration,
    chip_distribution,
)
from src.tw_quant.strategy.interfaces import StrategyContext

HoldingsSource = Callable[[FeatureFrameRef], dict[str, list[float]]]


class ChipFlowStrategy:
    """Strategy adapter for chip-flow analysis based on holder concentration."""

    def __init__(self, holdings_source: HoldingsSource) -> None:
        """Initialize chip-flow strategy.
        
        Args:
            holdings_source: Callable that retrieves holder distribution data
                by symbol from a FeatureFrameRef.
        """
        self._holdings_source = holdings_source

    def generate_signals(self, context: StrategyContext) -> list[SignalRecord]:
        """Generate chip-flow signals based on concentration thresholds.
        
        Returns empty list if context.feature_ref is None.
        
        For each symbol:
        - Buy if concentration < 0.3 (widely distributed)
        - Sell if concentration > 0.7 (highly concentrated)
        - Hold otherwise
        
        Args:
            context: Strategy context with feature reference and timestamp.
            
        Returns:
            List of signal records, one per symbol.
        """
        if context.feature_ref is None:
            return []

        by_symbol = self._holdings_source(context.feature_ref)
        signals: list[SignalRecord] = []

        for symbol, holdings in by_symbol.items():
            if not holdings:
                signals.append(
                    SignalRecord(
                        symbol=symbol,
                        timestamp=context.as_of,
                        signal="hold",
                        score=0.0,
                        metadata={
                            "strategy": context.strategy_name,
                            "metric": "concentration",
                            "threshold": 0.3,
                            "concentration": None,
                        },
                    )
                )
                continue

            concentration = chip_concentration(holdings)
            distribution = chip_distribution(holdings, window=5)
            last_distribution = distribution[-1] if distribution else None

            if concentration < 0.3:
                signal, score = "buy", 1.0
            elif concentration > 0.7:
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
                        "metric": "concentration",
                        "threshold": 0.3,
                        "concentration": concentration,
                        "distribution": last_distribution,
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
