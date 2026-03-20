"""Contract tests for MA crossover strategy adapter."""

import pytest

from src.tw_quant.schema.models import FeatureFrameRef, OHLCVBar, SignalRecord
from src.tw_quant.strategy.interfaces import StrategyContext
from src.tw_quant.strategy.technical.ma_bullish_stack import (
    MovingAverageBullishStackStrategy,
)
from src.tw_quant.strategy.technical.ma_crossover import MovingAverageCrossoverStrategy
from src.tw_quant.strategy.technical.pullback_trend_compression import (
    PullbackTrend120dOptimizedStrategy,
    PullbackTrendCompressionStrategy,
)
from src.tw_quant.workflows import _build_strategy


def _feature_source_stub(_: FeatureFrameRef) -> dict[str, list[float]]:
    return {
        "BULL.TW": [5.0, 1.0, 2.0, 10.0],
        "BEAR.TW": [1.0, 5.0, 4.0, 0.0],
        "HOLD.TW": [2.0, 2.0, 2.0, 2.0],
    }


def _build_context(feature_ref: FeatureFrameRef | None = None) -> StrategyContext:
    return StrategyContext(
        strategy_name="ma_cross_ref",
        as_of="2026-03-11",
        feature_ref=feature_ref,
    )


def test_generate_signals_returns_empty_when_feature_ref_missing() -> None:
    strategy = MovingAverageCrossoverStrategy(
        feature_source=_feature_source_stub,
        short_window=2,
        long_window=3,
    )

    assert strategy.generate_signals(_build_context(feature_ref=None)) == []


def test_generate_signals_emits_one_deterministic_signal_per_symbol() -> None:
    strategy = MovingAverageCrossoverStrategy(
        feature_source=_feature_source_stub,
        short_window=2,
        long_window=3,
    )
    context = _build_context(
        feature_ref=FeatureFrameRef(
            frame_id="f1",
            as_of="2026-03-11",
            symbols=["BULL.TW", "BEAR.TW", "HOLD.TW"],
            columns=["close"],
        )
    )

    signals = strategy.generate_signals(context)

    assert len(signals) == 3
    by_symbol = {signal.symbol: signal for signal in signals}

    assert by_symbol["BULL.TW"].signal == "buy"
    assert by_symbol["BULL.TW"].score == 1.0

    assert by_symbol["BEAR.TW"].signal == "sell"
    assert by_symbol["BEAR.TW"].score == -1.0

    assert by_symbol["HOLD.TW"].signal == "hold"
    assert by_symbol["HOLD.TW"].score == 0.0

    for signal in signals:
        assert signal.timestamp == "2026-03-11"
        assert signal.metadata["strategy"] == "ma_cross_ref"
        assert signal.metadata["indicator"] == "ma_crossover"
        assert signal.metadata["short_window"] == 2
        assert signal.metadata["long_window"] == 3


def test_build_orders_converts_buy_sell_and_ignores_hold() -> None:
    strategy = MovingAverageCrossoverStrategy(
        feature_source=_feature_source_stub,
        short_window=2,
        long_window=3,
    )
    context = _build_context()
    selections = [
        SignalRecord(symbol="BULL.TW", timestamp="2026-03-11", signal="buy", score=1.0),
        SignalRecord(symbol="HOLD.TW", timestamp="2026-03-11", signal="hold", score=0.0),
        SignalRecord(symbol="BEAR.TW", timestamp="2026-03-11", signal="sell", score=-1.0),
    ]

    orders = strategy.build_orders(context, selections)
    assert len(orders) == 2

    buy_order = orders[0]
    sell_order = orders[1]

    assert buy_order.symbol == "BULL.TW"
    assert buy_order.side == "buy"
    assert buy_order.quantity == 1.0
    assert buy_order.timestamp == "2026-03-11"
    assert buy_order.order_type == "market"

    assert sell_order.symbol == "BEAR.TW"
    assert sell_order.side == "sell"
    assert sell_order.quantity == 1.0
    assert sell_order.timestamp == "2026-03-11"
    assert sell_order.order_type == "market"


def _build_pullback_payload(size: int = 220) -> dict[str, list[float] | str]:
    close = [100.0 + index * 0.6 for index in range(160)]
    close += [196.0 + index * 0.12 for index in range(40)]
    close += [201.0 + index * 0.2 for index in range(20)]

    open_values = [value + 0.4 for value in close]
    high_values = [value + 25.0 for value in close]
    low_values = [value - 2.0 for value in close]
    volume_values = [1000.0 for _ in close]

    open_values[-1] = close[-1] + 1.0
    low_values[-1] = min(low_values[-10:-1])
    volume_values[-1] = 800.0

    payload = {
        "interval": "1d",
        "open": open_values,
        "high": high_values,
        "low": low_values,
        "close": close,
        "volume": volume_values,
    }
    if size < len(close):
        return {
            key: value[:size] if isinstance(value, list) else value
            for key, value in payload.items()
        }
    return payload


def _pullback_feature_source(_: FeatureFrameRef) -> dict[str, dict[str, list[float] | str]]:
    return {"PULLBACK.TW": _build_pullback_payload()}


def test_pullback_generate_signals_returns_empty_when_feature_ref_missing() -> None:
    strategy = PullbackTrendCompressionStrategy(feature_source=_pullback_feature_source)

    assert strategy.generate_signals(_build_context(feature_ref=None)) == []


def test_pullback_generate_signals_emits_buy_when_all_conditions_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strategy = PullbackTrendCompressionStrategy(feature_source=_pullback_feature_source)
    monkeypatch.setattr(strategy, "_passes_macd_condition", lambda *_args, **_kwargs: True)

    context = _build_context(
        feature_ref=FeatureFrameRef(
            frame_id="f_pullback",
            as_of="2026-03-11",
            symbols=["PULLBACK.TW"],
            columns=["open", "high", "low", "close", "volume"],
        )
    )

    signals = strategy.generate_signals(context)

    assert len(signals) == 1
    signal = signals[0]
    assert signal.symbol == "PULLBACK.TW"
    assert signal.signal == "buy"
    assert signal.score == 1.0
    assert signal.metadata["strategy"] == "ma_cross_ref"
    assert signal.metadata["indicator"] == "pullback_trend_compression"
    assert all(signal.metadata["conditions"].values())


@pytest.mark.parametrize(
    ("condition_name", "mutator"),
    [
        (
            "trend_stack",
            lambda payload: [
                payload["close"].__setitem__(-(index + 1), payload["close"][-(index + 1)] - 150.0)
                for index in range(65)
            ],
        ),
        (
            "ma60_proximity",
            lambda payload: payload["close"].__setitem__(-1, payload["close"][-1] + 80.0),
        ),
        (
            "ma60_slope",
            lambda payload: [
                payload["close"].__setitem__(-(index + 1), payload["close"][-(index + 1)] - 35.0)
                for index in range(6)
            ],
        ),
        (
            "ma120_slope",
            lambda payload: [
                payload["close"].__setitem__(-(index + 1), payload["close"][-(index + 1)] - 55.0)
                for index in range(120)
            ],
        ),
        (
            "compression",
            lambda payload: [
                payload["high"].__setitem__(-(index + 1), payload["close"][-(index + 1)] - 5.0)
                for index in range(60)
            ],
        ),
        (
            "volume",
            lambda payload: payload["volume"].__setitem__(-1, payload["volume"][-2] + 50.0),
        ),
        (
            "bearish_candle",
            lambda payload: payload["open"].__setitem__(-1, payload["close"][-1] - 1.0),
        ),
        (
            "rolling_low10",
            lambda payload: payload["low"].__setitem__(-1, payload["low"][-2] + 5.0),
        ),
    ],
)
def test_pullback_generate_signals_returns_hold_when_each_condition_fails(
    condition_name: str,
    mutator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _build_pullback_payload()
    mutator(payload)

    strategy = PullbackTrendCompressionStrategy(
        feature_source=lambda _feature_ref: {"PULLBACK.TW": payload}
    )
    monkeypatch.setattr(strategy, "_passes_macd_condition", lambda *_args, **_kwargs: True)

    signals = strategy.generate_signals(
        _build_context(
            feature_ref=FeatureFrameRef(
                frame_id="f_pullback_fail",
                as_of="2026-03-11",
                symbols=["PULLBACK.TW"],
                columns=["open", "high", "low", "close", "volume"],
            )
        )
    )

    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal == "hold"
    assert signal.score == 0.0
    assert signal.metadata["conditions"][condition_name] is False


def test_pullback_generate_signals_macd_failure_returns_hold() -> None:
    strategy = PullbackTrendCompressionStrategy(feature_source=_pullback_feature_source)

    signals = strategy.generate_signals(
        _build_context(
            feature_ref=FeatureFrameRef(
                frame_id="f_pullback_macd",
                as_of="2026-03-11",
                symbols=["PULLBACK.TW"],
                columns=["open", "high", "low", "close", "volume"],
            )
        )
    )

    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal == "hold"
    assert signal.metadata["conditions"]["macd"] is False


def test_pullback_generate_signals_insufficient_history_returns_hold() -> None:
    short_payload = _build_pullback_payload(size=120)
    strategy = PullbackTrendCompressionStrategy(
        feature_source=lambda _feature_ref: {"PULLBACK.TW": short_payload}
    )

    signals = strategy.generate_signals(
        _build_context(
            feature_ref=FeatureFrameRef(
                frame_id="f_pullback_short",
                as_of="2026-03-11",
                symbols=["PULLBACK.TW"],
                columns=["open", "high", "low", "close", "volume"],
            )
        )
    )

    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal == "hold"
    assert signal.metadata["reason"] == "insufficient_history"


def test_pullback_generate_signals_non_daily_interval_returns_hold() -> None:
    payload = _build_pullback_payload()
    payload["interval"] = "1h"
    strategy = PullbackTrendCompressionStrategy(
        feature_source=lambda _feature_ref: {"PULLBACK.TW": payload}
    )

    signals = strategy.generate_signals(
        _build_context(
            feature_ref=FeatureFrameRef(
                frame_id="f_pullback_intraday",
                as_of="2026-03-11",
                symbols=["PULLBACK.TW"],
                columns=["open", "high", "low", "close", "volume"],
            )
        )
    )

    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal == "hold"
    assert signal.metadata["reason"] == "non_daily_interval"


def test_pullback_build_orders_only_places_buy_orders() -> None:
    strategy = PullbackTrendCompressionStrategy(feature_source=_pullback_feature_source)
    context = _build_context()
    selections = [
        SignalRecord(symbol="BUY.TW", timestamp="2026-03-11", signal="buy", score=1.0),
        SignalRecord(symbol="HOLD.TW", timestamp="2026-03-11", signal="hold", score=0.0),
    ]

    orders = strategy.build_orders(context, selections)

    assert len(orders) == 1
    order = orders[0]
    assert order.symbol == "BUY.TW"
    assert order.side == "buy"
    assert order.quantity == 1.0
    assert order.timestamp == "2026-03-11"
    assert order.order_type == "market"


def _build_pullback_optimized_payload() -> dict[str, list[float] | str]:
    close = [80.0 + index * 1.2 for index in range(220)]
    high = [value + 6.0 for value in close]
    low = [value - 3.0 for value in close]
    open_values = [value - 0.3 for value in close]
    volume = [300_000.0 for _ in close]

    # Keep close near MA20 while preserving required pullback via a higher recent high.
    pullback_close = close[-2] * 0.969
    close[-1] = pullback_close
    high[-1] = close[-1] + 3.0
    low[-1] = close[-1] - 3.0
    open_values[-1] = close[-1] - 1.0

    # Create a local weak point at t-6 so 5-day momentum can recover by entry day.
    close[-6] = close[-6] - 25.0
    high[-6] = close[-6] + 3.0
    low[-6] = close[-6] - 3.0
    open_values[-6] = close[-6] - 1.0
    # Force 20-day range to be wider and 5-day range tighter (ratio contraction pass).
    for offset in range(20):
        idx = -(offset + 1)
        high[idx] = close[idx] + 12.0
        low[idx] = close[idx] - 12.0
    for offset in range(5):
        idx = -(offset + 1)
        high[idx] = close[idx] + 3.0
        low[idx] = close[idx] - 3.0
    high[-10] = close[-10] + 60.0

    # Declining volume so VolMA10 < VolMA20
    volume[-5:] = [290_000.0, 280_000.0, 270_000.0, 260_000.0, 250_000.0]

    return {
        "interval": "1d",
        "open": open_values,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def test_pullback_optimized_generate_signals_emits_buy_without_legacy_conditions() -> None:
    payload = _build_pullback_optimized_payload()
    strategy = PullbackTrend120dOptimizedStrategy(
        feature_source=lambda _feature_ref: {"OPT.TW": payload}
    )

    signals = strategy.generate_signals(
        _build_context(
            feature_ref=FeatureFrameRef(
                frame_id="f_pullback_opt",
                as_of="2026-03-11",
                symbols=["OPT.TW"],
                columns=["open", "high", "low", "close", "volume"],
            )
        )
    )

    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal == "buy"
    assert signal.score == 1.0
    assert signal.metadata["indicator"] == "pullback_trend_120d_optimized"
    assert signal.metadata["close_above_ma20_pass"] is True
    assert signal.metadata["ma20_slope_pass"] is True
    assert signal.metadata["price_contraction_pass"] is True
    assert signal.metadata["close_strength_pass"] is True
    assert signal.metadata["short_momentum_pass"] is True
    assert signal.metadata["final_selected"] is True
    assert signal.metadata["is_selected"] is True
    assert signal.metadata["module_debug"]["ma"]["passed"] is True
    assert signal.metadata["module_debug"]["ma"]["metrics"]["close_above_ma20_pass"] is True
    assert signal.metadata["module_debug"]["ma"]["metrics"]["ma20_slope_pass"] is True
    assert signal.metadata["module_debug"]["ma"]["metrics"]["ma200_slope_ok"] is True
    assert signal.metadata["module_debug"]["ma"]["metrics"]["close_above_ma120"] is True
    assert signal.metadata["module_debug"]["pullback"]["passed"] is True
    assert signal.metadata["module_debug"]["price_contraction"]["passed"] is True
    assert signal.metadata["module_debug"]["price_contraction"]["metrics"]["price_contraction_pass"] is True
    assert signal.metadata["module_debug"]["close_strength"]["passed"] is True
    assert signal.metadata["module_debug"]["short_momentum"]["passed"] is True
    assert signal.metadata["module_debug"]["volume"]["metrics"]["volume_contract_enabled"] is True
    assert signal.metadata["module_debug"]["chip"]["enabled"] is False
    assert signal.metadata["module_debug"]["margin"]["enabled"] is False
    assert signal.metadata["module_debug"]["borrow"]["enabled"] is False
    assert signal.metadata["failure_reason"] is None
    assert signal.metadata["entry_semantics_mode"] == "legacy"
    assert signal.metadata["setup_index"] == signal.metadata["trigger_index"]
    assert signal.metadata["setup_pass"] is True
    assert signal.metadata["trigger_pass"] is True
    assert signal.metadata["setup_volume_pass"] is True
    assert signal.metadata["trigger_volume_pass"] is True


def test_pullback_optimized_trigger_volume_warn_is_soft_gate_by_default() -> None:
    payload = _build_pullback_optimized_payload()
    payload["volume"][-1] = payload["volume"][-1] * 10.0

    strategy = PullbackTrend120dOptimizedStrategy(
        feature_source=lambda _feature_ref: {"OPT.TW": payload},
        config={
            "entry": {"entry_semantics_mode": "setup_trigger", "setup_offset_bars": 1},
            "volume": {
                "setup_volume_contract_enabled": False,
                "trigger_volume_check_enabled": True,
                "trigger_volume_ratio_warn_max": 1.2,
                "trigger_volume_hard_block": False,
            },
        },
    )

    signals = strategy.generate_signals(
        _build_context(
            feature_ref=FeatureFrameRef(
                frame_id="f_pullback_opt_trigger_soft",
                as_of="2026-03-11",
                symbols=["OPT.TW"],
                columns=["open", "high", "low", "close", "volume"],
            )
        )
    )

    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal == "buy"
    assert signal.metadata["trigger_volume_pass"] is False
    assert signal.metadata["trigger_volume_reason"] == "trigger_volume_warn_exceeded"


def test_pullback_optimized_trigger_volume_can_hard_block_when_enabled() -> None:
    payload = _build_pullback_optimized_payload()
    payload["volume"][-1] = payload["volume"][-1] * 10.0

    strategy = PullbackTrend120dOptimizedStrategy(
        feature_source=lambda _feature_ref: {"OPT.TW": payload},
        config={
            "entry": {"entry_semantics_mode": "setup_trigger", "setup_offset_bars": 1},
            "volume": {
                "setup_volume_contract_enabled": False,
                "trigger_volume_check_enabled": True,
                "trigger_volume_ratio_warn_max": 1.2,
                "trigger_volume_hard_block": True,
            },
        },
    )

    signals = strategy.generate_signals(
        _build_context(
            feature_ref=FeatureFrameRef(
                frame_id="f_pullback_opt_trigger_hard",
                as_of="2026-03-11",
                symbols=["OPT.TW"],
                columns=["open", "high", "low", "close", "volume"],
            )
        )
    )

    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal == "hold"
    assert signal.metadata["trigger_volume_pass"] is False
    assert signal.metadata["trigger_volume_reason"] == "trigger_volume_warn_exceeded"


def test_pullback_optimized_requires_close_above_ma20() -> None:
    payload = _build_pullback_optimized_payload()
    close_values = list(payload["close"])
    high_values = list(payload["high"])
    low_values = list(payload["low"])
    open_values = list(payload["open"])

    close_values[-1] = close_values[-1] * 0.75
    high_values[-1] = close_values[-1] + 6.0
    low_values[-1] = close_values[-1] - 1.0
    open_values[-1] = close_values[-1] - 0.5

    payload["close"] = close_values
    payload["high"] = high_values
    payload["low"] = low_values
    payload["open"] = open_values

    strategy = PullbackTrend120dOptimizedStrategy(
        feature_source=lambda _: {"SYM.TW": payload}
    )
    signals = strategy.generate_signals(
        _build_context(
            feature_ref=FeatureFrameRef(
                frame_id="f_close_below_ma20",
                as_of="2026-03-11",
                symbols=["SYM.TW"],
                columns=["open", "high", "low", "close", "volume"],
            )
        )
    )

    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal == "hold"
    assert signal.metadata["close_above_ma20_pass"] is False


def test_pullback_optimized_requires_non_negative_ma20_slope() -> None:
    payload = _build_pullback_optimized_payload()
    close_values = list(payload["close"])
    high_values = list(payload["high"])
    low_values = list(payload["low"])
    open_values = list(payload["open"])

    for offset in range(6):
        idx = -(offset + 1)
        close_values[idx] = close_values[idx] - (offset + 1) * 12.0
        high_values[idx] = close_values[idx] + 6.0
        low_values[idx] = close_values[idx] - 1.0
        open_values[idx] = close_values[idx] - 0.5

    payload["close"] = close_values
    payload["high"] = high_values
    payload["low"] = low_values
    payload["open"] = open_values

    strategy = PullbackTrend120dOptimizedStrategy(
        feature_source=lambda _: {"SYM.TW": payload}
    )
    signals = strategy.generate_signals(
        _build_context(
            feature_ref=FeatureFrameRef(
                frame_id="f_ma20_slope_down",
                as_of="2026-03-11",
                symbols=["SYM.TW"],
                columns=["open", "high", "low", "close", "volume"],
            )
        )
    )

    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal == "hold"
    assert signal.metadata["ma20_slope_pass"] is False


def test_pullback_optimized_requires_close_strength_by_default() -> None:
    payload = _build_pullback_optimized_payload()
    close_values = list(payload["close"])
    high_values = list(payload["high"])
    low_values = list(payload["low"])
    open_values = list(payload["open"])

    close_values[-1] = close_values[-2] * 0.90
    high_values[-1] = close_values[-1] + 3.0
    low_values[-1] = close_values[-1] - 3.0
    open_values[-1] = close_values[-1] - 0.5

    payload["close"] = close_values
    payload["high"] = high_values
    payload["low"] = low_values
    payload["open"] = open_values

    strategy = PullbackTrend120dOptimizedStrategy(
        feature_source=lambda _: {"SYM.TW": payload}
    )
    signals = strategy.generate_signals(
        _build_context(
            feature_ref=FeatureFrameRef(
                frame_id="f_close_strength_fail",
                as_of="2026-03-11",
                symbols=["SYM.TW"],
                columns=["open", "high", "low", "close", "volume"],
            )
        )
    )

    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal == "hold"
    assert signal.metadata["close_strength_pass"] is False


def test_pullback_optimized_requires_short_momentum_by_default() -> None:
    payload = _build_pullback_optimized_payload()
    close_values = list(payload["close"])
    high_values = list(payload["high"])
    low_values = list(payload["low"])
    open_values = list(payload["open"])

    close_values[-1] = close_values[-6] * 0.99
    high_values[-1] = close_values[-1] + 3.0
    low_values[-1] = close_values[-1] - 3.0
    open_values[-1] = close_values[-1] - 0.5

    payload["close"] = close_values
    payload["high"] = high_values
    payload["low"] = low_values
    payload["open"] = open_values

    strategy = PullbackTrend120dOptimizedStrategy(
        feature_source=lambda _: {"SYM.TW": payload}
    )
    signals = strategy.generate_signals(
        _build_context(
            feature_ref=FeatureFrameRef(
                frame_id="f_short_momentum_fail",
                as_of="2026-03-11",
                symbols=["SYM.TW"],
                columns=["open", "high", "low", "close", "volume"],
            )
        )
    )

    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal == "hold"
    assert signal.metadata["short_momentum_pass"] is False


def test_pullback_optimized_mandatory_price_contraction_ratio_gate_cannot_be_disabled() -> None:
    payload = _build_pullback_optimized_payload()
    high_values = list(payload["high"])
    low_values = list(payload["low"])

    high_values[-5] = high_values[-5] + 80.0
    low_values[-1] = low_values[-1] - 80.0

    payload["high"] = high_values
    payload["low"] = low_values

    strategy = PullbackTrend120dOptimizedStrategy(
        feature_source=lambda _: {"SYM.TW": payload},
        config={"price_contraction": {"price_contract_enabled": False, "range_contract_ratio_max": 0.7}},
    )
    signals = strategy.generate_signals(
        _build_context(
            feature_ref=FeatureFrameRef(
                frame_id="f_price_contract_required",
                as_of="2026-03-11",
                symbols=["SYM.TW"],
                columns=["open", "high", "low", "close", "volume"],
            )
        )
    )

    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal == "hold"
    assert signal.metadata["price_contraction_pass"] is False
    assert signal.metadata["module_debug"]["price_contraction"]["metrics"]["ratio_gate_required"] is True


def test_pullback_optimized_ma_requires_close_above_ma120() -> None:
    payload = _build_pullback_optimized_payload()
    close_values = list(payload["close"])
    high_values = list(payload["high"])
    low_values = list(payload["low"])
    open_values = list(payload["open"])

    close_values[-1] = close_values[-80]
    high_values[-1] = close_values[-1] + 6.0
    low_values[-1] = close_values[-1] - 1.0
    open_values[-1] = close_values[-1] - 1.0

    payload["close"] = close_values
    payload["high"] = high_values
    payload["low"] = low_values
    payload["open"] = open_values

    strategy = PullbackTrend120dOptimizedStrategy(
        feature_source=lambda _feature_ref: {"OPT.TW": payload}
    )

    signals = strategy.generate_signals(
        _build_context(
            feature_ref=FeatureFrameRef(
                frame_id="f_pullback_opt_ma120",
                as_of="2026-03-11",
                symbols=["OPT.TW"],
                columns=["open", "high", "low", "close", "volume"],
            )
        )
    )

    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal == "hold"
    assert signal.metadata["module_debug"]["ma"]["passed"] is False
    assert signal.metadata["module_debug"]["ma"]["metrics"]["close_above_ma120"] is False
    assert signal.metadata["failure_reason"] == "ma:ma_trend_not_met"


def test_pullback_optimized_ma_requires_non_negative_ma200_slope() -> None:
    payload = _build_pullback_optimized_payload()
    close_values = list(payload["close"])
    high_values = list(payload["high"])
    low_values = list(payload["low"])
    open_values = list(payload["open"])

    for offset in range(20):
        index = -(offset + 1)
        close_values[index] -= 300.0
        high_values[index] = close_values[index] + 6.0
        low_values[index] = close_values[index] - 1.0
        open_values[index] = close_values[index] - 1.0

    payload["close"] = close_values
    payload["high"] = high_values
    payload["low"] = low_values
    payload["open"] = open_values

    strategy = PullbackTrend120dOptimizedStrategy(
        feature_source=lambda _feature_ref: {"OPT.TW": payload}
    )

    signals = strategy.generate_signals(
        _build_context(
            feature_ref=FeatureFrameRef(
                frame_id="f_pullback_opt_ma200",
                as_of="2026-03-11",
                symbols=["OPT.TW"],
                columns=["open", "high", "low", "close", "volume"],
            )
        )
    )

    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal == "hold"
    assert signal.metadata["module_debug"]["ma"]["passed"] is False
    assert signal.metadata["module_debug"]["ma"]["metrics"]["ma200_slope_ok"] is False


def test_pullback_optimized_chip_filter_passes_when_trust_flow_is_positive() -> None:
    payload = _build_pullback_optimized_payload()
    payload["foreign_net_buy"] = [-1.0 for _ in payload["close"]]
    payload["investment_trust_net_buy"] = [2.0 for _ in payload["close"]]

    strategy = PullbackTrend120dOptimizedStrategy(
        feature_source=lambda _feature_ref: {"OPT.TW": payload},
        config={
            "chip": {
                "enable_chip_filter": True,
                "enable_foreign_buy_filter": True,
                "enable_investment_trust_filter": True,
                "chip_lookback": 20,
            }
        },
    )

    signals = strategy.generate_signals(
        _build_context(
            feature_ref=FeatureFrameRef(
                frame_id="f_pullback_opt_chip",
                as_of="2026-03-11",
                symbols=["OPT.TW"],
                columns=["open", "high", "low", "close", "volume"],
            )
        )
    )

    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal == "buy"
    assert signal.metadata["module_debug"]["chip"]["enabled"] is True
    assert signal.metadata["module_debug"]["chip"]["passed"] is True
    assert signal.metadata["module_debug"]["chip"]["metrics"]["foreign_cumulative_net_buy"] == -20.0
    assert signal.metadata["module_debug"]["chip"]["metrics"]["investment_trust_cumulative_net_buy"] == 40.0


def test_pullback_optimized_margin_filter_fails_on_divergence() -> None:
    payload = _build_pullback_optimized_payload()
    payload["margin_balance"] = [100.0 + index * 0.2 for index in range(len(payload["close"]))]

    strategy = PullbackTrend120dOptimizedStrategy(
        feature_source=lambda _feature_ref: {"OPT.TW": payload},
        config={
            "margin": {
                "enable_margin_filter": True,
                "margin_lookback": 20,
                "margin_growth_limit": 0.15,
            }
        },
    )

    signals = strategy.generate_signals(
        _build_context(
            feature_ref=FeatureFrameRef(
                frame_id="f_pullback_opt_margin",
                as_of="2026-03-11",
                symbols=["OPT.TW"],
                columns=["open", "high", "low", "close", "volume"],
            )
        )
    )

    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal == "hold"
    assert signal.metadata["module_debug"]["margin"]["enabled"] is True
    assert signal.metadata["module_debug"]["margin"]["passed"] is False
    assert signal.metadata["module_debug"]["margin"]["metrics"]["close_at_lookback_high"] is False
    assert signal.metadata["module_debug"]["margin"]["metrics"]["margin_at_lookback_high"] is True
    assert signal.metadata["module_debug"]["margin"]["reason"] == "margin_divergence_exclusion"
    assert signal.metadata["failure_reason"] == "margin:margin_divergence_exclusion"


def test_pullback_optimized_borrow_filter_fails_on_growth_with_price_divergence() -> None:
    payload = _build_pullback_optimized_payload()
    borrow_balance = [100.0 for _ in payload["close"]]
    for offset in range(20):
        borrow_balance[-(offset + 1)] = 130.0
    payload["borrow_balance"] = borrow_balance

    strategy = PullbackTrend120dOptimizedStrategy(
        feature_source=lambda _feature_ref: {"OPT.TW": payload},
        config={
            "borrow": {
                "enable_borrow_filter": True,
                "borrow_lookback": 20,
                "borrow_balance_growth_limit": 0.15,
            }
        },
    )

    signals = strategy.generate_signals(
        _build_context(
            feature_ref=FeatureFrameRef(
                frame_id="f_pullback_opt_borrow",
                as_of="2026-03-11",
                symbols=["OPT.TW"],
                columns=["open", "high", "low", "close", "volume"],
            )
        )
    )

    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal == "hold"
    assert signal.metadata["module_debug"]["borrow"]["enabled"] is True
    assert signal.metadata["module_debug"]["borrow"]["passed"] is False
    assert signal.metadata["module_debug"]["borrow"]["metrics"]["borrow_growth"] == 0.3
    assert signal.metadata["module_debug"]["borrow"]["metrics"]["close_below_rolling_max"] is True
    assert signal.metadata["module_debug"]["borrow"]["reason"] == "borrow_growth_with_price_divergence"
    assert signal.metadata["failure_reason"] == "borrow:borrow_growth_with_price_divergence"


def test_pullback_optimized_generate_signals_reports_module_failure_reason() -> None:
    payload = _build_pullback_optimized_payload()
    payload["volume"][-1] = 500_000.0
    strategy = PullbackTrend120dOptimizedStrategy(
        feature_source=lambda _feature_ref: {"OPT.TW": payload}
    )

    signals = strategy.generate_signals(
        _build_context(
            feature_ref=FeatureFrameRef(
                frame_id="f_pullback_opt_fail",
                as_of="2026-03-11",
                symbols=["OPT.TW"],
                columns=["open", "high", "low", "close", "volume"],
            )
        )
    )

    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal == "hold"
    assert signal.metadata["module_debug"]["volume"]["passed"] is False
    assert signal.metadata["failure_reason"] == "volume:volume_not_contracted"


def test_build_strategy_supports_pullback_optimized_alias() -> None:
    strategy = _build_strategy(
        "pullback_120d_optimized",
        {},
        by_symbol_history={
            "OPT.TW": [
                OHLCVBar(symbol="OPT.TW", date="2026-03-10", open=100.0, high=102.0, low=99.0, close=101.0, volume=1000.0)
            ]
        },
    )

    assert isinstance(strategy, PullbackTrend120dOptimizedStrategy)


def _bullish_stack_feature_source_stub(_: FeatureFrameRef) -> dict[str, list[float]]:
    return {
        "STACK.TW": [1.0, 2.0, 3.0, 4.0],
        "NO_STACK.TW": [4.0, 3.0, 2.0, 1.0],
        "WARMUP.TW": [1.0, 2.0, 3.0],
    }


def test_bullish_stack_generate_signals_returns_empty_when_feature_ref_missing() -> None:
    strategy = MovingAverageBullishStackStrategy(
        feature_source=_bullish_stack_feature_source_stub,
        short_window=2,
        mid_window=3,
        long_window=4,
    )

    assert strategy.generate_signals(_build_context(feature_ref=None)) == []


def test_bullish_stack_generate_signals_emits_buy_hold_and_warmup_hold() -> None:
    strategy = MovingAverageBullishStackStrategy(
        feature_source=_bullish_stack_feature_source_stub,
        short_window=2,
        mid_window=3,
        long_window=4,
    )
    context = _build_context(
        feature_ref=FeatureFrameRef(
            frame_id="f_ma_stack",
            as_of="2026-03-11",
            symbols=["STACK.TW", "NO_STACK.TW", "WARMUP.TW"],
            columns=["close"],
        )
    )

    signals = strategy.generate_signals(context)

    assert len(signals) == 3
    by_symbol = {signal.symbol: signal for signal in signals}

    stack_signal = by_symbol["STACK.TW"]
    assert stack_signal.signal == "buy"
    assert stack_signal.score == 1.0
    assert stack_signal.metadata["stack"] is True

    hold_signal = by_symbol["NO_STACK.TW"]
    assert hold_signal.signal == "hold"
    assert hold_signal.score == 0.0
    assert hold_signal.metadata["stack"] is False

    warmup_signal = by_symbol["WARMUP.TW"]
    assert warmup_signal.signal == "hold"
    assert warmup_signal.score == 0.0
    assert warmup_signal.metadata["stack"] is False
    assert warmup_signal.metadata["reason"] == "insufficient_history"
    assert warmup_signal.metadata["required_bars"] == 4
    assert warmup_signal.metadata["provided_bars"] == 3

    for signal in signals:
        assert signal.timestamp == "2026-03-11"
        assert signal.metadata["strategy"] == "ma_cross_ref"
        assert signal.metadata["indicator"] == "ma_bullish_stack"
        assert signal.metadata["short_window"] == 2
        assert signal.metadata["mid_window"] == 3
        assert signal.metadata["long_window"] == 4
        assert "ma_short" in signal.metadata
        assert "ma_mid" in signal.metadata
        assert "ma_long" in signal.metadata


def test_bullish_stack_build_orders_only_places_buy_orders() -> None:
    strategy = MovingAverageBullishStackStrategy(
        feature_source=_bullish_stack_feature_source_stub,
        short_window=2,
        mid_window=3,
        long_window=4,
    )
    context = _build_context()
    selections = [
        SignalRecord(symbol="STACK.TW", timestamp="2026-03-11", signal="buy", score=1.0),
        SignalRecord(symbol="NO_STACK.TW", timestamp="2026-03-11", signal="hold", score=0.0),
    ]

    orders = strategy.build_orders(context, selections)

    assert len(orders) == 1
    order = orders[0]
    assert order.symbol == "STACK.TW"
    assert order.side == "buy"
    assert order.quantity == 1.0
    assert order.timestamp == "2026-03-11"
    assert order.order_type == "market"


def test_workflows_build_strategy_dispatch_includes_bullish_stack_and_preserves_existing() -> None:
    history = [
        OHLCVBar(
            symbol="STACK.TW",
            date=f"2026-03-0{index + 1}",
            open=float(index + 1),
            high=float(index + 1),
            low=float(index + 1),
            close=float(index + 1),
            volume=1000.0,
        )
        for index in range(4)
    ]
    by_symbol_history = {"STACK.TW": history}

    for name in ["ma_bullish_stack", "bullish_stack", "ma_stack", "bull_stack"]:
        strategy = _build_strategy(
            name,
            {"short": 2, "mid": 3, "long": 4},
            by_symbol_history=by_symbol_history,
        )
        assert isinstance(strategy, MovingAverageBullishStackStrategy)

        context = StrategyContext(
            strategy_name=name,
            as_of="2026-03-11",
            feature_ref=FeatureFrameRef(
                frame_id="f_dispatch",
                as_of="2026-03-11",
                symbols=["STACK.TW"],
                columns=["close"],
            ),
        )
        signals = strategy.generate_signals(context)
        assert len(signals) == 1
        assert signals[0].metadata["short_window"] == 2
        assert signals[0].metadata["mid_window"] == 3
        assert signals[0].metadata["long_window"] == 4

    pullback = _build_strategy("pullback", {}, by_symbol_history=by_symbol_history)
    assert isinstance(pullback, PullbackTrendCompressionStrategy)

    fallback = _build_strategy("unknown_strategy", {}, by_symbol_history=by_symbol_history)
    assert isinstance(fallback, MovingAverageCrossoverStrategy)


def test_workflows_build_strategy_for_pullback_optimized_forwards_all_module_sections() -> None:
    history = [
        OHLCVBar(
            symbol="OPT.TW",
            date=f"2026-03-{index + 1:02d}",
            open=100.0 + index,
            high=101.0 + index,
            low=99.0 + index,
            close=100.0 + index,
            volume=1000.0,
        )
        for index in range(220)
    ]
    strategy = _build_strategy(
        "pullback_trend_120d_optimized",
        {
            "ma": {"ma_short": 21},
            "atr_pullback": {"use_atr_normalized_pullback": True},
            "price_contraction": {"range_contract_ratio_max": 0.65},
            "close_strength": {"close_vs_5d_high_min": 0.96},
            "short_momentum": {"short_momentum_lookback": 7},
            "chip_scoring": {"enable_chip_scoring": True},
        },
        by_symbol_history={"OPT.TW": history},
    )

    assert isinstance(strategy, PullbackTrend120dOptimizedStrategy)
    assert strategy._config["ma"]["ma_short"] == 21
    assert strategy._config["atr_pullback"]["use_atr_normalized_pullback"] is True
    assert strategy._config["price_contraction"]["range_contract_ratio_max"] == 0.65
    assert strategy._config["close_strength"]["close_vs_5d_high_min"] == 0.96
    assert strategy._config["short_momentum"]["short_momentum_lookback"] == 7
    assert strategy._config["chip_scoring"]["enable_chip_scoring"] is True


def test_pullback_optimized_min_bars_default_is_200_returns_hold_for_199_bars() -> None:
    """Verify default min_bars=200: 199 bars → insufficient_history."""
    payload = _build_pullback_optimized_payload()
    short_payload = {
        key: value[:199] if isinstance(value, list) else value
        for key, value in payload.items()
    }
    strategy = PullbackTrend120dOptimizedStrategy(
        feature_source=lambda _: {"SYM.TW": short_payload}
    )
    signals = strategy.generate_signals(
        _build_context(
            feature_ref=FeatureFrameRef(
                frame_id="f_min_bars",
                as_of="2026-03-11",
                symbols=["SYM.TW"],
                columns=["open", "high", "low", "close", "volume"],
            )
        )
    )
    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal == "hold"
    assert signal.metadata["module_debug"]["basic"]["reason"] == "insufficient_history"


def test_pullback_optimized_drawdown_below_min_fails_pullback_module() -> None:
    """Verify drawdown_min=0.08: drawdown < 8% causes pullback failure."""
    payload = _build_pullback_optimized_payload()
    # Reduce pullback close to recent high to force drawdown below configured minimum.
    close_vals = list(payload["close"])
    close_vals[-1] = close_vals[-2] * 1.03
    payload["close"] = close_vals
    strategy = PullbackTrend120dOptimizedStrategy(
        feature_source=lambda _: {"SYM.TW": payload}
    )
    signals = strategy.generate_signals(
        _build_context(
            feature_ref=FeatureFrameRef(
                frame_id="f_drawdown_low",
                as_of="2026-03-11",
                symbols=["SYM.TW"],
                columns=["open", "high", "low", "close", "volume"],
            )
        )
    )
    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal == "hold"
    assert signal.metadata["module_debug"]["pullback"]["passed"] is False
    assert signal.metadata["module_debug"]["pullback"]["reason"] == "pullback_range_not_met"


def test_pullback_optimized_signed_dist_above_max_fails_pullback_module() -> None:
    """Verify ma60_dist_max=0.08: signed dist > 0.08 causes pullback failure."""
    payload = _build_pullback_optimized_payload()
    # Push close way above MA60 (large positive signed dist)
    close_vals = list(payload["close"])
    close_vals[-1] = close_vals[-2] * 1.30
    payload["close"] = close_vals
    strategy = PullbackTrend120dOptimizedStrategy(
        feature_source=lambda _: {"SYM.TW": payload}
    )
    signals = strategy.generate_signals(
        _build_context(
            feature_ref=FeatureFrameRef(
                frame_id="f_dist_above",
                as_of="2026-03-11",
                symbols=["SYM.TW"],
                columns=["open", "high", "low", "close", "volume"],
            )
        )
    )
    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal == "hold"
    assert signal.metadata["module_debug"]["pullback"]["passed"] is False


def test_pullback_optimized_vol_ma_short_above_vol_ma_long_fails_volume_module() -> None:
    """Verify VolMA10 >= VolMA20 causes volume failure."""
    payload = _build_pullback_optimized_payload()
    # Set last 10 volumes much higher than prior so VolMA10 > VolMA20
    vol = list(payload["volume"])
    for i in range(10):
        vol[-(i + 1)] = 600_000.0
    payload["volume"] = vol
    strategy = PullbackTrend120dOptimizedStrategy(
        feature_source=lambda _: {"SYM.TW": payload}
    )
    signals = strategy.generate_signals(
        _build_context(
            feature_ref=FeatureFrameRef(
                frame_id="f_vol_expand",
                as_of="2026-03-11",
                symbols=["SYM.TW"],
                columns=["open", "high", "low", "close", "volume"],
            )
        )
    )
    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal == "hold"
    assert signal.metadata["module_debug"]["volume"]["passed"] is False
    assert signal.metadata["failure_reason"] == "volume:volume_not_contracted"
