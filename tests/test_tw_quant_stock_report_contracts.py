from __future__ import annotations

import csv
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from src.tw_quant.data import InMemoryMarketDataProvider
from src.tw_quant.runner import _write_stock_report_csv
from src.tw_quant.schema.models import OHLCVBar
from src.tw_quant.universe.models import ListingStatus, UniverseEntry
from src.tw_quant.universe.stub import InMemoryUniverseProvider
from src.tw_quant.workflows import build_stock_report


def _build_sample_bars(symbol: str, start: date, days: int) -> list[OHLCVBar]:
    bars: list[OHLCVBar] = []
    for offset in range(days):
        current = start + timedelta(days=offset)
        close = 100.0 + float(offset)
        bars.append(
            OHLCVBar(
                symbol=symbol,
                date=current.isoformat(),
                open=close - 1.0,
                high=close + 1.0,
                low=close - 2.0,
                close=close,
                volume=1000.0 + float(offset * 10),
                turnover=(100000.0 + float(offset * 1000)),
            )
        )
    return bars


def test_build_stock_report_returns_requested_window_and_metadata() -> None:
    provider = InMemoryMarketDataProvider(_build_sample_bars("2330.TW", date(2025, 8, 1), 70))
    universe = InMemoryUniverseProvider([
        UniverseEntry(
            symbol="2330.TW",
            name="TSMC",
            exchange="TWSE",
            market="stock",
            listing_status=ListingStatus.LISTED,
            updated_at=datetime(2025, 9, 5),
        )
    ])

    report = build_stock_report(
        symbol="2330.TW",
        start="2025-09-01",
        end="2025-09-05",
        market_data_provider=provider,
        universe_provider=universe,
    )

    assert report["mode"] == "stock_report"
    assert report["symbol"] == "2330.TW"
    assert report["stock_name"] == "TSMC"
    assert report["row_count"] == 5
    assert report["requested_window_days"] == 5
    assert "latest_close" in report
    assert "period_return_pct" in report
    assert "latest_qizhang_signal" in report
    assert [row["date"] for row in report["rows"]] == [
        "2025-09-01",
        "2025-09-02",
        "2025-09-03",
        "2025-09-04",
        "2025-09-05",
    ]
    last_row = report["rows"][-1]
    assert "ma_20" in last_row
    assert "macd_histogram" in last_row
    assert "rsi_14" in last_row
    assert "flow_ratio_5" in last_row
    assert "chip_concentration_proxy" in last_row
    assert "close_vs_ma_20" in last_row
    assert "return_20d" in last_row
    assert "atr_14" in last_row
    assert "candle_body" in last_row
    assert "volume_change_pct" in last_row
    assert "qizhang_signal" in last_row
    assert "qizhang_selected_setup" in last_row
    assert "qizhang_check_sig_anchor_close_vs_ma60" in last_row


def test_build_stock_report_rejects_empty_history_in_requested_range() -> None:
    provider = InMemoryMarketDataProvider(_build_sample_bars("2330.TW", date(2025, 7, 1), 10))

    with pytest.raises(ValueError, match="inside requested date range"):
        build_stock_report(
            symbol="2330.TW",
            start="2025-09-01",
            end="2025-09-05",
            market_data_provider=provider,
        )


def test_write_stock_report_csv_writes_expected_headers_and_rows(tmp_path: Path) -> None:
    rows = [
        {
            "date": "2025-09-01",
            "symbol": "2330.TW",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1200.0,
            "turnover": 500000.0,
            "price_change": 1.0,
            "price_change_pct": 0.01,
            "volume_ratio_5": 1.2,
            "volume_ratio_20": 1.1,
            "ma_5": 99.0,
            "ma_10": 98.0,
            "ma_20": 97.0,
            "ma_60": 95.0,
            "rolling_high_20": 102.0,
            "rolling_low_20": 90.0,
            "macd_histogram": 0.3,
            "rsi_14": 62.0,
            "estimated_inflow": 1200.0,
            "estimated_outflow": 0.0,
            "flow_ratio_5": 1.1,
            "flow_momentum_5": 40.0,
            "chip_concentration_proxy": 0.2,
            "chip_distribution_5_proxy": 0.1,
            "cost_basis_ratio_proxy": 0.98,
            "close_vs_ma_5": 0.015,
            "close_vs_ma_10": 0.025,
            "close_vs_ma_20": 0.035,
            "close_vs_ma_60": 0.055,
            "close_position_20d": 0.8,
            "distance_to_rolling_high_20_pct": -0.01,
            "distance_to_rolling_low_20_pct": 0.12,
            "return_5d": 0.08,
            "return_20d": 0.15,
            "true_range": 2.0,
            "atr_14": 1.7,
            "volume_change_pct": 0.1,
            "candle_body": 0.5,
            "candle_body_pct": 0.25,
            "upper_shadow": 0.5,
            "lower_shadow": 1.0,
            "intraday_range": 2.0,
            "intraday_range_pct": 0.02,
            "qizhang_signal": "buy",
            "qizhang_score": 1.0,
            "qizhang_selected_setup": "sig_explosive",
            "qizhang_sig_anchor": False,
            "qizhang_sig_explosive": True,
            "qizhang_close_pos": 0.8,
            "qizhang_close_vs_ma60": 0.055,
            "qizhang_net_flow": 1,
            "qizhang_check_sig_explosive_price_change_pct": True,
            "qizhang_check_sig_explosive_volume_ratio_5": True,
            "qizhang_check_sig_explosive_volume_ratio_20": True,
            "qizhang_check_sig_explosive_close_pos": True,
            "qizhang_check_sig_explosive_close_gt_ma_20": True,
            "qizhang_check_sig_explosive_net_flow": True,
            "qizhang_check_sig_anchor_volume_ratio_5": False,
            "qizhang_check_sig_anchor_volume_ratio_20": False,
            "qizhang_check_sig_anchor_close_pos": True,
            "qizhang_check_sig_anchor_close_gt_ma_20": True,
            "qizhang_check_sig_anchor_net_flow": True,
            "qizhang_check_sig_anchor_rsi_14": True,
            "qizhang_check_sig_anchor_macd_histogram": True,
            "qizhang_check_sig_anchor_close_vs_ma60": True,
        }
    ]

    csv_path = _write_stock_report_csv(
        output_path=str(tmp_path / "reports" / "stock_report.csv"),
        rows=rows,
    )
    png_path = Path(csv_path).with_suffix(".png")

    with Path(csv_path).open("r", encoding="utf-8") as handle:
        parsed = list(csv.DictReader(handle))

    assert len(parsed) == 1
    assert parsed[0]["symbol"] == "2330.TW"
    assert parsed[0]["macd_histogram"] == "0.3"
    assert parsed[0]["atr_14"] == "1.7"
    assert parsed[0]["qizhang_signal"] == "buy"
    assert png_path.exists()
    assert png_path.stat().st_size > 0
