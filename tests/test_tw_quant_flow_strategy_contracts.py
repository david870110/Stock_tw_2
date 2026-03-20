"""Contract tests for flow-analysis strategy adapter."""

from src.tw_quant.schema.models import FeatureFrameRef, SignalRecord
from src.tw_quant.strategy.flow.metrics import (
    flow_momentum,
    flow_ratio,
    inflow_outflow,
)
from src.tw_quant.strategy.flow.flow_analysis_strategy import FlowAnalysisStrategy
from src.tw_quant.strategy.interfaces import StrategyContext


def _volume_source_stub(feature_ref: FeatureFrameRef) -> dict[str, list[float]]:
    all_data = {
        "BULL.TW": [100.0, 110.0, 120.0, 130.0],  # Positive flows
        "BEAR.TW": [100.0, 90.0, 80.0, 70.0],  # Negative flows
        "HOLD.TW": [100.0, 100.0, 100.0, 100.0],  # Flat
    }
    # Filter to only requested symbols
    return {k: v for k, v in all_data.items() if k in feature_ref.symbols}


def _build_context(feature_ref: FeatureFrameRef | None = None) -> StrategyContext:
    return StrategyContext(
        strategy_name="flow_analysis_ref",
        as_of="2026-03-11",
        feature_ref=feature_ref,
    )


class TestFlowMetrics:
    def test_inflow_outflow_separates_buy_sell_pressure(self) -> None:
        volumes = [100.0, 110.0, 90.0]
        prices = [100.0, 105.0, 100.0]
        
        inflows, outflows = inflow_outflow(volumes, prices)
        
        assert len(inflows) == 3
        assert len(outflows) == 3
        # First bar has no direction
        assert inflows[0] == 0.0
        assert outflows[0] == 0.0
        # Second bar has positive price change
        assert inflows[1] > 0
        assert outflows[1] == 0.0
        # Third bar has negative price change
        assert inflows[2] == 0.0
        assert outflows[2] > 0

    def test_flow_momentum_deterministic(self) -> None:
        volumes = [100.0, 110.0, 120.0, 130.0]
        
        momentum1 = flow_momentum(volumes, window=2)
        momentum2 = flow_momentum(volumes, window=2)
        
        assert momentum1 == momentum2

    def test_flow_ratio_with_zero_volumes(self) -> None:
        volumes = [100.0, 0.0, 50.0, 100.0]
        
        ratio = flow_ratio(volumes, window=2)
        
        assert ratio is not None
        assert len(ratio) == 4


class TestFlowAnalysisStrategy:
    def test_generate_signals_returns_empty_when_feature_ref_missing(self) -> None:
        strategy = FlowAnalysisStrategy(volume_source=_volume_source_stub)
        
        assert strategy.generate_signals(_build_context(feature_ref=None)) == []

    def test_generate_signals_emits_buy_on_positive_momentum(self) -> None:
        strategy = FlowAnalysisStrategy(
            volume_source=_volume_source_stub,
            momentum_window=2,
            momentum_threshold=0.0,
        )
        context = _build_context(
            feature_ref=FeatureFrameRef(
                frame_id="f1",
                as_of="2026-03-11",
                symbols=["BULL.TW"],
                columns=["volume"],
            )
        )
        
        signals = strategy.generate_signals(context)
        
        assert len(signals) == 1
        assert signals[0].symbol == "BULL.TW"
        assert signals[0].signal == "buy"
        assert signals[0].score == 1.0

    def test_generate_signals_emits_sell_on_negative_momentum(self) -> None:
        strategy = FlowAnalysisStrategy(
            volume_source=_volume_source_stub,
            momentum_window=2,
            momentum_threshold=0.0,
        )
        context = _build_context(
            feature_ref=FeatureFrameRef(
                frame_id="f1",
                as_of="2026-03-11",
                symbols=["BEAR.TW"],
                columns=["volume"],
            )
        )
        
        signals = strategy.generate_signals(context)
        
        assert len(signals) == 1
        assert signals[0].symbol == "BEAR.TW"
        assert signals[0].signal == "sell"
        assert signals[0].score == -1.0

    def test_generate_signals_includes_deterministic_metadata(self) -> None:
        strategy = FlowAnalysisStrategy(
            volume_source=_volume_source_stub,
            momentum_window=2,
        )
        context = _build_context(
            feature_ref=FeatureFrameRef(
                frame_id="f1",
                as_of="2026-03-11",
                symbols=["HOLD.TW"],
                columns=["volume"],
            )
        )
        
        signals = strategy.generate_signals(context)
        
        assert len(signals) == 1
        signal = signals[0]
        assert signal.timestamp == "2026-03-11"
        assert signal.metadata["strategy"] == "flow_analysis_ref"
        assert signal.metadata["metric"] == "momentum"
        assert "threshold" in signal.metadata
        assert "momentum" in signal.metadata

    def test_build_orders_converts_signals_to_orders(self) -> None:
        strategy = FlowAnalysisStrategy(volume_source=_volume_source_stub)
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
