from __future__ import annotations

from datetime import date, timedelta

from src.tw_quant.schema.models import OHLCVBar
from src.tw_quant.workflows import _generate_strategy_signals


def _build_history(
    closes: list[float],
    *,
    base_volume: float = 1000.0,
    last_volume: float | None = None,
    last_close_pos: float | None = None,
) -> list[OHLCVBar]:
    start = date(2025, 1, 1)
    history: list[OHLCVBar] = []
    for index, close_price in enumerate(closes):
        previous_close = closes[index - 1] if index > 0 else close_price - 0.5
        if index == len(closes) - 1:
            open_price = previous_close * 1.01
            if last_close_pos is None:
                low_price = previous_close * 1.005
                high_price = close_price * 1.001
            else:
                low_price = min(open_price, close_price) - 1.0
                high_price = low_price + ((close_price - low_price) / last_close_pos)
            volume = last_volume if last_volume is not None else base_volume
        else:
            open_price = close_price - 0.3
            low_price = open_price - 0.2
            high_price = close_price + 0.2
            volume = base_volume
        history.append(
            OHLCVBar(
                symbol="8299.TW",
                date=(start + timedelta(days=index)).isoformat(),
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=volume,
            )
        )
    return history


def _build_v15_closes(last_close: float) -> list[float]:
    base: list[float] = []
    for index in range(79):
        base.append(
            60.0
            + (0.25 * index)
            + (0.8 if index % 4 == 0 else -0.6 if index % 4 == 1 else 0.25 if index % 4 == 2 else -0.15)
        )
    return base + [last_close]


def test_qizhang_improve_strategy_selects_sig_explosive() -> None:
    closes = [60.0 + (0.5 * index) for index in range(79)] + [106.0]
    history = _build_history(closes, last_volume=2400.0)

    signals = _generate_strategy_signals(
        strategy_name="qizhang_improve_strategy",
        parameters={},
        as_of="2025-03-20",
        by_symbol_history={"8299.TW": history},
    )

    assert len(signals) == 1
    signal = signals[0]

    assert signal.signal == "buy"
    assert signal.score == 1.0
    assert signal.metadata["indicator"] == "qizhang_improve_signal"
    assert signal.metadata["selected_setup"] == "sig_explosive"
    assert signal.metadata["close_pos"] >= 0.70
    assert signal.metadata["check_sig_explosive_close_pos"] is True
    assert signal.metadata["check_sig_explosive_close_gt_ma_60"] is True
    assert signal.metadata["check_sig_explosive_rsi_14"] is True
    assert signal.metadata["check_sig_explosive_macd_histogram"] is True


def test_qizhang_improve_strategy_selects_sig_anchor_without_explosive_price_change() -> None:
    closes = [60.0 + (0.5 * index) for index in range(79)] + [100.98]
    history = _build_history(closes, last_volume=3200.0)

    signals = _generate_strategy_signals(
        strategy_name="qizhang_improve_strategy",
        parameters={},
        as_of="2025-03-20",
        by_symbol_history={"8299.TW": history},
    )

    assert len(signals) == 1
    signal = signals[0]

    assert signal.signal == "buy"
    assert signal.score == 0.9
    assert signal.metadata["selected_setup"] == "sig_anchor"
    assert signal.metadata["check_sig_explosive_price_change_pct"] is False
    assert signal.metadata["check_sig_anchor_close_pos"] is True
    assert signal.metadata["check_sig_anchor_close_gt_ma_60"] is True
    assert signal.metadata["check_sig_anchor_rsi_14"] is True
    assert signal.metadata["check_sig_anchor_macd_histogram"] is True


def test_qizhang_improve_strategy_is_stricter_than_legacy_qizhang() -> None:
    closes = [60.0 + (0.5 * index) for index in range(79)] + [106.0]
    history = _build_history(closes, last_volume=2400.0, last_close_pos=0.65)

    legacy_signals = _generate_strategy_signals(
        strategy_name="qizhang_selection_strategy",
        parameters={},
        as_of="2025-03-20",
        by_symbol_history={"8299.TW": history},
    )
    improved_signals = _generate_strategy_signals(
        strategy_name="qizhang_improve_strategy",
        parameters={},
        as_of="2025-03-20",
        by_symbol_history={"8299.TW": history},
    )

    assert len(legacy_signals) == 1
    assert len(improved_signals) == 1
    assert legacy_signals[0].signal == "buy"
    assert legacy_signals[0].metadata["selected_setup"] == "sig_explosive"
    assert legacy_signals[0].metadata["check_sig_explosive_close_pos"] is True

    assert improved_signals[0].signal == "hold"
    assert improved_signals[0].metadata["close_pos"] < 0.70
    assert improved_signals[0].metadata["check_sig_explosive_close_pos"] is False


def test_qizhang_improve_strategy_v15_selects_sig_explosive() -> None:
    closes = _build_v15_closes(84.0)
    history = _build_history(closes, last_volume=2400.0)

    signals = _generate_strategy_signals(
        strategy_name="qizhang_improve_strategy_v15",
        parameters={},
        as_of="2025-03-20",
        by_symbol_history={"8299.TW": history},
    )

    assert len(signals) == 1
    signal = signals[0]

    assert signal.signal == "buy"
    assert signal.score == 1.0
    assert signal.metadata["indicator"] == "qizhang_improve_signal_v15"
    assert signal.metadata["selected_setup"] == "sig_explosive"
    assert signal.metadata["check_sig_explosive_close_position_20d"] is True
    assert signal.metadata["check_sig_explosive_close_vs_ma20_max"] is True
    assert signal.metadata["check_sig_explosive_close_vs_ma60_min"] is True
    assert signal.metadata["check_sig_explosive_close_vs_ma60_max"] is True
    assert signal.metadata["check_sig_explosive_rsi_14_max"] is True
    assert signal.metadata["check_sig_explosive_macd_histogram"] is True


def test_qizhang_improve_strategy_v15_selects_sig_anchor_without_explosive_price_change() -> None:
    closes = _build_v15_closes(83.0)
    history = _build_history(closes, last_volume=3200.0)

    signals = _generate_strategy_signals(
        strategy_name="qizhang_improve_strategy_v15",
        parameters={},
        as_of="2025-03-20",
        by_symbol_history={"8299.TW": history},
    )

    assert len(signals) == 1
    signal = signals[0]

    assert signal.signal == "buy"
    assert signal.score == 0.9
    assert signal.metadata["selected_setup"] == "sig_anchor"
    assert signal.metadata["check_sig_explosive_price_change_pct"] is False
    assert signal.metadata["check_sig_anchor_branch_rsi_14"] is True
    assert signal.metadata["check_sig_anchor_branch_macd_histogram"] is True
    assert signal.metadata["check_sig_anchor_close_position_20d"] is True
    assert signal.metadata["check_sig_anchor_close_vs_ma20_max"] is True
    assert signal.metadata["check_sig_anchor_rsi_14_max"] is True


def test_qizhang_improve_strategy_v15_rejects_overextended_setup_that_old_improve_accepts() -> None:
    closes = _build_v15_closes(94.0)
    history = _build_history(closes, last_volume=3200.0)

    improve_signals = _generate_strategy_signals(
        strategy_name="qizhang_improve_strategy",
        parameters={},
        as_of="2025-03-20",
        by_symbol_history={"8299.TW": history},
    )
    v15_signals = _generate_strategy_signals(
        strategy_name="qizhang_improve_strategy_v15",
        parameters={},
        as_of="2025-03-20",
        by_symbol_history={"8299.TW": history},
    )

    assert len(improve_signals) == 1
    assert len(v15_signals) == 1
    assert improve_signals[0].signal == "buy"
    assert v15_signals[0].signal == "hold"
    assert v15_signals[0].metadata["check_sig_explosive_rsi_14_max"] is False
