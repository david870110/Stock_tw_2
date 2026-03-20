"""Contract tests for market-structure strategy adapter."""

from src.tw_quant.schema.models import FeatureFrameRef, SignalRecord
from src.tw_quant.strategy.market_structure.levels import (
    mean_reversion_signal,
    structure_trend,
    support_resistance,
)
from src.tw_quant.strategy.market_structure.structure_strategy import (
    MarketStructureStrategy,
)
from src.tw_quant.strategy.interfaces import StrategyContext


def _price_source_stub(feature_ref: FeatureFrameRef) -> dict[str, list[float]]:
    all_data = {
        "NEAR_SUPPORT.TW": [100.0, 95.0, 100.0, 95.0, 95.0],  # Price near support
        "NEAR_RESIST.TW": [100.0, 110.0, 105.0, 110.0, 110.0],  # Price near resistance
        "MID_RANGE.TW": [100.0, 102.0, 99.0, 101.0, 100.0],  # Price in middle
    }
    # Filter to only requested symbols
    return {k: v for k, v in all_data.items() if k in feature_ref.symbols}


def _build_context(feature_ref: FeatureFrameRef | None = None) -> StrategyContext:
    return StrategyContext(
        strategy_name="market_structure_ref",
        as_of="2026-03-11",
        feature_ref=feature_ref,
    )


class TestStructureLevels:
    def test_support_resistance_identifies_local_extrema(self) -> None:
        prices = [100.0, 95.0, 105.0, 90.0, 110.0]
        
        supports, resistances = support_resistance(prices, window=2)
        
        assert len(supports) == len(prices)
        assert len(resistances) == len(prices)
        
        # Each support should be <= corresponding price
        # Each resistance should be >= corresponding price
        for i, price in enumerate(prices):
            assert supports[i] <= price or i < 1
            assert resistances[i] >= price or i < 1

    def test_structure_trend_determines_bias(self) -> None:
        uptrend_levels = [95.0, 96.0, 97.0, 98.0, 99.0, 100.0]
        downtrend_levels = [100.0, 99.0, 98.0, 97.0, 96.0, 95.0]
        sideways_levels = [100.0, 100.0, 100.0, 100.0, 100.0, 100.0]
        
        assert structure_trend(uptrend_levels) == "uptrend"
        assert structure_trend(downtrend_levels) == "downtrend"
        assert structure_trend(sideways_levels) == "sideways"

    def test_mean_reversion_signal_deterministic(self) -> None:
        signal1 = mean_reversion_signal(100.0, 90.0, 110.0)
        signal2 = mean_reversion_signal(100.0, 90.0, 110.0)
        
        assert signal1 == signal2
        assert -1 <= signal1 <= 1


class TestMarketStructureStrategy:
    def test_generate_signals_returns_empty_when_feature_ref_missing(self) -> None:
        strategy = MarketStructureStrategy(price_source=_price_source_stub)
        
        assert strategy.generate_signals(_build_context(feature_ref=None)) == []

    def test_generate_signals_emits_buy_near_support(self) -> None:
        strategy = MarketStructureStrategy(
            price_source=_price_source_stub,
            level_window=3,
            signal_threshold=0.4,
        )
        context = _build_context(
            feature_ref=FeatureFrameRef(
                frame_id="f1",
                as_of="2026-03-11",
                symbols=["NEAR_SUPPORT.TW"],
                columns=["close"],
            )
        )
        
        signals = strategy.generate_signals(context)
        
        assert len(signals) == 1
        assert signals[0].symbol == "NEAR_SUPPORT.TW"
        assert signals[0].signal == "buy"
        assert signals[0].score == 1.0

    def test_generate_signals_emits_sell_near_resistance(self) -> None:
        strategy = MarketStructureStrategy(
            price_source=_price_source_stub,
            level_window=3,
            signal_threshold=0.4,
        )
        context = _build_context(
            feature_ref=FeatureFrameRef(
                frame_id="f1",
                as_of="2026-03-11",
                symbols=["NEAR_RESIST.TW"],
                columns=["close"],
            )
        )
        
        signals = strategy.generate_signals(context)
        
        assert len(signals) == 1
        assert signals[0].symbol == "NEAR_RESIST.TW"
        assert signals[0].signal == "sell"
        assert signals[0].score == -1.0

    def test_generate_signals_includes_level_metadata(self) -> None:
        strategy = MarketStructureStrategy(
            price_source=_price_source_stub,
            level_window=3,
        )
        context = _build_context(
            feature_ref=FeatureFrameRef(
                frame_id="f1",
                as_of="2026-03-11",
                symbols=["MID_RANGE.TW"],
                columns=["close"],
            )
        )
        
        signals = strategy.generate_signals(context)
        
        assert len(signals) == 1
        signal = signals[0]
        assert signal.timestamp == "2026-03-11"
        assert signal.metadata["strategy"] == "market_structure_ref"
        assert signal.metadata["metric"] == "level_distance"
        assert "support" in signal.metadata
        assert "resistance" in signal.metadata

    def test_build_orders_converts_signals_to_orders(self) -> None:
        strategy = MarketStructureStrategy(price_source=_price_source_stub)
        context = _build_context()
        selections = [
            SignalRecord(symbol="BUY.TW", timestamp="2026-03-11", signal="buy", score=1.0),
            SignalRecord(symbol="HOLD.TW", timestamp="2026-03-11", signal="hold", score=0.0),
            SignalRecord(symbol="SELL.TW", timestamp="2026-03-11", signal="sell", score=-1.0),
        ]
        
        orders = strategy.build_orders(context, selections)
        
        assert len(orders) == 2
        
        buy_order = orders[0]
        sell_order = orders[1]
        
        assert buy_order.symbol == "BUY.TW"
        assert buy_order.side == "buy"
        assert buy_order.quantity == 1.0
        assert buy_order.order_type == "market"
        
        assert sell_order.symbol == "SELL.TW"
        assert sell_order.side == "sell"
        assert sell_order.quantity == 1.0
        assert sell_order.order_type == "market"
