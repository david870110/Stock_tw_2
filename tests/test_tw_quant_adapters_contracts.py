"""Contract tests for yfinance OHLCV adapter and TWSE/TPEX universe mappers."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src.tw_quant.adapters.twse_universe import map_tpex_row, map_twse_row
from src.tw_quant.adapters.yfinance_ohlcv import yfinance_fetcher
from src.tw_quant.config.models import AppConfig, DataConfig
from src.tw_quant.wiring.container import build_app_context


def test_yfinance_fetcher_returns_correct_shape():
    import pandas as pd

    fake_df = pd.DataFrame(
        {
            "Open": [100.0, 101.0],
            "High": [105.0, 106.0],
            "Low": [99.0, 100.0],
            "Close": [103.0, 104.0],
            "Volume": [50000.0, 60000.0],
        },
        index=pd.to_datetime(["2024-01-02", "2024-01-03"]),
    )
    fake_df.index.name = "Date"

    mock_ticker = MagicMock()
    mock_ticker.history.return_value = fake_df

    with patch("yfinance.Ticker", return_value=mock_ticker):
        rows = yfinance_fetcher("2330.TW", "2024-01-01", "2024-01-31", timeout=10.0)

    assert len(rows) == 2
    first = rows[0]
    assert first["date"] == date(2024, 1, 2)
    assert first["open"] == pytest.approx(100.0)
    assert first["high"] == pytest.approx(105.0)
    assert first["low"] == pytest.approx(99.0)
    assert first["close"] == pytest.approx(103.0)
    assert first["volume"] == pytest.approx(50000.0)


def test_yfinance_fetcher_returns_empty_on_no_data():
    import pandas as pd

    mock_ticker = MagicMock()
    mock_ticker.history.return_value = pd.DataFrame()

    with patch("yfinance.Ticker", return_value=mock_ticker):
        rows = yfinance_fetcher("9999.TW", "2024-01-01", "2024-01-31", timeout=10.0)

    assert rows == []


def test_yfinance_fetcher_falls_back_from_tw_to_two():
    import pandas as pd

    fake_df = pd.DataFrame(
        {
            "Open": [50.0],
            "High": [52.0],
            "Low": [49.5],
            "Close": [51.0],
            "Volume": [12000.0],
        },
        index=pd.to_datetime(["2024-01-05"]),
    )
    fake_df.index.name = "Date"

    tw_ticker = MagicMock()
    tw_ticker.history.return_value = pd.DataFrame()
    two_ticker = MagicMock()
    two_ticker.history.return_value = fake_df

    def _ticker_side_effect(symbol: str):
        if symbol == "6488.TW":
            return tw_ticker
        if symbol == "6488.TWO":
            return two_ticker
        raise AssertionError(f"unexpected symbol: {symbol}")

    with patch("yfinance.Ticker", side_effect=_ticker_side_effect):
        rows = yfinance_fetcher("6488.TW", "2024-01-01", "2024-01-31", timeout=10.0)

    assert len(rows) == 1
    assert rows[0]["date"] == date(2024, 1, 5)
    assert rows[0]["close"] == pytest.approx(51.0)


def test_map_twse_row_maps_current_chinese_fields():
    row = {"公司代號": "2330", "公司名稱": "台灣積體電路製造股份有限公司", "公司簡稱": "台積電"}
    result = map_twse_row(row)

    assert result["symbol"] == "2330"
    assert result["name"] == "台積電"
    assert result["exchange"] == "TWSE"
    assert result["market"] == "stock"
    assert result["listing_status"] == "listed"


def test_map_twse_row_marks_etf_market():
    row = {"公司代號": "0050", "公司簡稱": "元大台灣50 ETF"}
    result = map_twse_row(row)
    assert result["market"] == "etf"


def test_map_tpex_row_maps_current_fields():
    row = {"SecuritiesCompanyCode": "1569", "CompanyName": "濱川"}
    result = map_tpex_row(row)

    assert result["symbol"] == "1569"
    assert result["name"] == "濱川"
    assert result["exchange"] == "TPEX"
    assert result["market"] == "stock"
    assert result["listing_status"] == "listed"


def test_map_tpex_row_prefers_securities_code():
    row = {"SecuritiesCompanyCode": "1260", "SecuritiesCode": "6488", "CompanyName": "環球晶"}
    result = map_tpex_row(row)
    assert result["symbol"] == "6488"
    assert result["name"] == "環球晶"


def test_build_app_context_yfinance_ohlcv_wires_non_none_market_provider():
    config = AppConfig(
        data=DataConfig(
            wiring_mode="active",
            market_provider="yfinance_ohlcv",
            universe_provider="stub_universe",
        )
    )
    ctx = build_app_context(config)
    assert ctx.market_data_provider is not None


def test_build_app_context_remote_universe_wires_non_none_universe_provider():
    config = AppConfig(
        data=DataConfig(
            wiring_mode="active",
            market_provider="stub_market",
            universe_provider="remote_universe",
            universe_twse_url="https://example.com/twse",
            universe_tpex_url="https://example.com/tpex",
        )
    )
    ctx = build_app_context(config)
    assert ctx.universe_provider is not None
