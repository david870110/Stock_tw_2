import pytest
from datetime import date
from src.tw_quant.selection_contracts.qizhang_selection_strategy import QizhangSelectionStrategy

@pytest.fixture
def sample_stock_list():
    return ["2330.TW", "2317.TW", "2454.TW", "2412.TW"]

@pytest.fixture
def as_of():
    return date(2026, 3, 20)


def test_qizhang_strategy_returns_candidates(sample_stock_list, as_of):
    strategy = QizhangSelectionStrategy()
    candidates = strategy.get_candidates(sample_stock_list, as_of)
    assert isinstance(candidates, list)
    for c in candidates:
        assert "stock" in c
        assert "date" in c
        assert "reason" in c
        assert "indicators" in c
        assert isinstance(c["indicators"], dict)


def test_qizhang_strategy_conditions(sample_stock_list, as_of):
    strategy = QizhangSelectionStrategy()
    candidates = strategy.get_candidates(sample_stock_list, as_of)
    for c in candidates:
        reason = c["reason"]
        assert reason["ma_break"]
        assert reason["volume_ok"]
        assert reason["macd_cross"]
        assert reason["rsi_strong"]
        assert reason["no_negative"]


def test_qizhang_strategy_indicators(sample_stock_list, as_of):
    strategy = QizhangSelectionStrategy()
    candidates = strategy.get_candidates(sample_stock_list, as_of)
    for c in candidates:
        indicators = c["indicators"]
        assert indicators["ma_short"] is not None
        assert indicators["ma_long"] is not None
        assert indicators["macd"] is not None
        assert indicators["signal"] is not None
        assert indicators["rsi"] is not None
        assert indicators["volume"] is not None
