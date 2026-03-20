"""Contract tests for chip-flow strategy adapter."""

from src.tw_quant.schema.models import FeatureFrameRef, SignalRecord
from src.tw_quant.strategy.chip.indicators import (
    chip_concentration,
    chip_distribution,
    cost_basis_ratio,
)
from src.tw_quant.strategy.chip.chip_flow_strategy import ChipFlowStrategy
from src.tw_quant.strategy.interfaces import StrategyContext


def _holdings_source_stub(feature_ref: FeatureFrameRef) -> dict[str, list[float]]:
    all_data = {
        "CONC.TW": [200.0, 10.0, 10.0],  # Highly concentrated (95% in one holder)
        "DIST.TW": [30.0, 30.0, 30.0],  # Distributed (uniform)
        "MIX.TW": [60.0, 30.0, 10.0],  # Mixed
    }
    # Filter to only requested symbols
    return {k: v for k, v in all_data.items() if k in feature_ref.symbols}


def _build_context(feature_ref: FeatureFrameRef | None = None) -> StrategyContext:
    return StrategyContext(
        strategy_name="chip_flow_ref",
        as_of="2026-03-11",
        feature_ref=feature_ref,
    )


class TestChipFlowIndicators:
    def test_chip_distribution_with_uniform_holdings(self) -> None:
        holdings = [25.0, 25.0, 25.0, 25.0]
        distribution = chip_distribution(holdings, window=2)
        
        assert distribution is not None
        # Uniform distribution should have low values
        for value in distribution[1:]:
            assert value is not None
            assert 0 <= value <= 1

    def test_chip_distribution_with_concentrated_holdings(self) -> None:
        holdings = [100.0, 5.0, 5.0, 5.0]
        distribution = chip_distribution(holdings, window=2)
        
        assert distribution is not None
        # Concentrated distribution should have higher values
        for value in distribution[1:]:
            assert value is not None
            assert 0 <= value <= 1

    def test_chip_concentration_returns_value_between_0_and_1(self) -> None:
        uniform = [25.0, 25.0, 25.0, 25.0]
        concentrated = [100.0, 5.0, 5.0, 5.0]
        
        conc_uniform = chip_concentration(uniform)
        conc_concentrated = chip_concentration(concentrated)
        
        assert 0 <= conc_uniform <= 1
        assert 0 <= conc_concentrated <= 1
        assert conc_concentrated > conc_uniform

    def test_cost_basis_ratio_deterministic(self) -> None:
        prices = [100.0, 110.0, 90.0]
        holdings = [1.0, 1.0, 1.0]
        
        ratio1 = cost_basis_ratio(prices, holdings)
        ratio2 = cost_basis_ratio(prices, holdings)
        
        assert ratio1 == ratio2


class TestChipFlowStrategy:
    def test_generate_signals_returns_empty_when_feature_ref_missing(self) -> None:
        strategy = ChipFlowStrategy(holdings_source=_holdings_source_stub)
        
        assert strategy.generate_signals(_build_context(feature_ref=None)) == []

    def test_generate_signals_emits_buy_below_concentration_threshold(self) -> None:
        strategy = ChipFlowStrategy(holdings_source=_holdings_source_stub)
        context = _build_context(
            feature_ref=FeatureFrameRef(
                frame_id="f1",
                as_of="2026-03-11",
                symbols=["DIST.TW"],
                columns=["holdings"],
            )
        )
        
        signals = strategy.generate_signals(context)
        
        assert len(signals) == 1
        assert signals[0].symbol == "DIST.TW"
        assert signals[0].signal == "buy"
        assert signals[0].score == 1.0

    def test_generate_signals_emits_sell_above_concentration_threshold(self) -> None:
        strategy = ChipFlowStrategy(holdings_source=_holdings_source_stub)
        context = _build_context(
            feature_ref=FeatureFrameRef(
                frame_id="f1",
                as_of="2026-03-11",
                symbols=["CONC.TW"],
                columns=["holdings"],
            )
        )
        
        signals = strategy.generate_signals(context)
        
        assert len(signals) == 1
        assert signals[0].symbol == "CONC.TW"
        assert signals[0].signal == "sell"
        assert signals[0].score == -1.0

    def test_generate_signals_includes_deterministic_metadata(self) -> None:
        strategy = ChipFlowStrategy(holdings_source=_holdings_source_stub)
        context = _build_context(
            feature_ref=FeatureFrameRef(
                frame_id="f1",
                as_of="2026-03-11",
                symbols=["MIX.TW"],
                columns=["holdings"],
            )
        )
        
        signals = strategy.generate_signals(context)
        
        assert len(signals) == 1
        signal = signals[0]
        assert signal.timestamp == "2026-03-11"
        assert signal.metadata["strategy"] == "chip_flow_ref"
        assert signal.metadata["metric"] == "concentration"
        assert signal.metadata["threshold"] == 0.3
        assert "concentration" in signal.metadata
        assert signal.metadata["concentration"] is not None

    def test_build_orders_converts_buy_sell_ignores_hold(self) -> None:
        strategy = ChipFlowStrategy(holdings_source=_holdings_source_stub)
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
