from datetime import date, timedelta

from src.tw_quant.selection_contracts.qizhang_selection_strategy import QizhangSelectionStrategy


def _build_history(*, length=80, base_open=100.0, base_step=0.1, volume=100.0):
    start = date(2025, 1, 1)
    history = []
    for i in range(length):
        open_price = base_open + i * base_step
        close_price = open_price + 0.3
        history.append(
            {
                "date": start + timedelta(days=i),
                "open": open_price,
                "high": close_price + 0.2,
                "low": open_price - 0.2,
                "close": close_price,
                "volume": volume,
            }
        )
    return history


def test_qizhang_strategy_selects_setup_a(monkeypatch):
    history = _build_history()
    previous_close = history[-2]["close"]
    history[-1] = {
        "date": history[-1]["date"],
        "open": previous_close * 1.01,
        "high": previous_close * 1.099,
        "low": previous_close * 1.005,
        "close": previous_close * 1.0986,
        "volume": 320.0,
    }

    def fake_get_daily_data(stock, as_of_date, lookback=80):  # noqa: ANN001
        return history

    monkeypatch.setattr(
        "src.tw_quant.selection_contracts.qizhang_selection_strategy.get_daily_data",
        fake_get_daily_data,
    )

    strategy = QizhangSelectionStrategy()
    candidates = strategy.get_candidates(["8299.TW"], date(2026, 3, 20))

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["stock"] == "8299.TW"
    assert candidate["reason"]["setup_a"] is True
    assert candidate["reason"]["setup_b"] is False
    assert candidate["reason"]["selected_setup"] == "A"
    assert candidate["reason"]["setup_a_checks"]["price_change_pct_ge_0_05"] is True
    assert candidate["reason"]["setup_a_checks"]["volume_ratio_5_ge_1_45"] is True
    assert candidate["indicators"]["price_change_pct"] >= 0.05
    assert candidate["indicators"]["close_pos"] >= 0.60
    assert candidate["indicators"]["volume_ratio_5"] >= 1.45
    assert candidate["indicators"]["volume_ratio_20"] >= 1.70


def test_qizhang_strategy_selects_setup_b_with_confirmation(monkeypatch):
    history = _build_history(base_open=90.0, base_step=0.2)
    prior_high = max(row["high"] for row in history[-21:-1])
    previous_close = history[-2]["close"]
    history[-1] = {
        "date": history[-1]["date"],
        "open": previous_close * 0.995,
        "high": prior_high + 0.6,
        "low": previous_close * 0.99,
        "close": prior_high + 0.3,
        "volume": 360.0,
    }

    def fake_get_daily_data(stock, as_of_date, lookback=80):  # noqa: ANN001
        return history

    monkeypatch.setattr(
        "src.tw_quant.selection_contracts.qizhang_selection_strategy.get_daily_data",
        fake_get_daily_data,
    )

    strategy = QizhangSelectionStrategy()
    candidates = strategy.get_candidates(["3081.TW"], date(2026, 3, 20))

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["reason"]["setup_a"] is False
    assert candidate["reason"]["setup_b"] is True
    assert candidate["reason"]["selected_setup"] == "B"
    assert candidate["reason"]["setup_b_checks"]["volume_ratio_5_ge_3_0"] is True
    assert candidate["reason"]["setup_b_checks"]["volume_ratio_20_ge_1_70"] is True
    assert candidate["reason"]["setup_b_checks"]["rsi_14_ge_45"] is True
    assert candidate["reason"]["setup_b_checks"]["macd_histogram_gt_0"] is True
    assert candidate["reason"]["setup_b_checks"]["close_vs_ma60_ge_neg_0_03"] is True
    assert candidate["indicators"]["price_change_pct"] < 0.08
    assert candidate["indicators"]["rsi_14"] >= 45
    assert candidate["indicators"]["macd_histogram"] > 0


def test_qizhang_strategy_rejects_unconfirmed_or_weak_breakout(monkeypatch):
    history = _build_history(base_open=120.0, base_step=0.05)
    previous_close = history[-2]["close"]
    history[-1] = {
        "date": history[-1]["date"],
        "open": previous_close * 1.02,
        "high": previous_close * 1.03,
        "low": previous_close * 0.96,
        "close": previous_close * 1.01,
        "volume": 350.0,
    }

    def fake_get_daily_data(stock, as_of_date, lookback=80):  # noqa: ANN001
        return history

    monkeypatch.setattr(
        "src.tw_quant.selection_contracts.qizhang_selection_strategy.get_daily_data",
        fake_get_daily_data,
    )

    strategy = QizhangSelectionStrategy()
    candidates = strategy.get_candidates(["2454.TW"], date(2026, 3, 20))

    assert candidates == []


def test_qizhang_strategy_indicators_keep_contract_shape(monkeypatch):
    history = _build_history()
    previous_close = history[-2]["close"]
    history[-1] = {
        "date": history[-1]["date"],
        "open": previous_close * 1.01,
        "high": previous_close * 1.1,
        "low": previous_close * 1.005,
        "close": previous_close * 1.099,
        "volume": 300.0,
    }

    def fake_get_daily_data(stock, as_of_date, lookback=80):  # noqa: ANN001
        return history

    monkeypatch.setattr(
        "src.tw_quant.selection_contracts.qizhang_selection_strategy.get_daily_data",
        fake_get_daily_data,
    )

    strategy = QizhangSelectionStrategy()
    candidates = strategy.get_candidates(["2330.TW"], date(2026, 3, 20))

    assert len(candidates) == 1
    candidate = candidates[0]
    assert set(candidate.keys()) == {"stock", "date", "reason", "indicators"}
    for key in [
        "price_change_pct",
        "close_pos",
        "volume_ratio_5",
        "volume_ratio_20",
        "net_flow",
        "ma_20",
        "ma_60",
        "close_vs_ma60",
        "rsi_14",
        "macd_histogram",
        "prior_20d_high",
    ]:
        assert key in candidate["indicators"]
