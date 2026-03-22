from __future__ import annotations

import csv
import json
from argparse import Namespace
from datetime import datetime
from pathlib import Path

from src.tw_quant import runner as runner_module
from src.tw_quant.schema.models import OHLCVBar
from src.tw_quant.universe.models import ListingStatus, UniverseEntry


class _DummyContext:
    def __init__(self, bars: list[OHLCVBar]) -> None:
        self.market_data_provider = _DummyMarketDataProvider(bars)
        self.universe_provider = _DummyUniverseProvider()


class _DummyMarketDataProvider:
    def __init__(self, bars: list[OHLCVBar]) -> None:
        self._bars = list(bars)

    def fetch_ohlcv(self, symbols, start, end):  # noqa: ANN001
        symbol_set = {str(symbol) for symbol in symbols}
        return [
            bar
            for bar in self._bars
            if str(bar.symbol) in symbol_set
        ]


class _DummyUniverseProvider:
    def get_universe(self, as_of=None):  # noqa: ANN001
        return [
            UniverseEntry(
                symbol="2330.TW",
                name="TSMC",
                exchange="TWSE",
                market="stock",
                listing_status=ListingStatus.LISTED,
                updated_at=datetime(2026, 2, 11),
            )
        ]


def test_run_selection_forward_report_uses_all_signal_rows_and_writes_artifacts(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    selection_csv = tmp_path / "artifacts" / "tw_quant" / "daily_selection" / "2026-02-11" / "qizhang_selection_strategy.csv"
    selection_csv.parent.mkdir(parents=True, exist_ok=True)
    with selection_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["symbol", "stock_name", "timestamp", "selected", "rank", "weight"],
        )
        writer.writeheader()
        writer.writerow({
            "symbol": "2330.TW",
            "stock_name": "TSMC",
            "timestamp": "2026-02-11",
            "selected": "True",
            "rank": 1,
            "weight": 1.0,
        })
        writer.writerow({
            "symbol": "2317.TW",
            "stock_name": "HonHai",
            "timestamp": "2026-02-11",
            "selected": "False",
            "rank": 2,
            "weight": 0.5,
        })

    bars = [
        OHLCVBar(symbol="2330.TW", date="2026-02-11", open=100, high=101, low=99, close=100, volume=1000),
        OHLCVBar(symbol="2330.TW", date="2026-03-11", open=109, high=111, low=108, close=110, volume=1000),
        OHLCVBar(symbol="2317.TW", date="2026-02-11", open=50, high=51, low=49, close=50, volume=1000),
        OHLCVBar(symbol="2317.TW", date="2026-03-11", open=52, high=53, low=51, close=52, volume=1000),
    ]

    monkeypatch.setattr(runner_module, "_load_config", lambda: object())
    monkeypatch.setattr(runner_module, "build_app_context", lambda config: _DummyContext(bars))

    args = Namespace(
        selection_csv=str(selection_csv),
        forward_months=1,
        forward_days=None,
        output_csv=None,
    )
    runner_module._run_selection_forward_report(args)
    output = json.loads(capsys.readouterr().out)

    assert output["mode"] == "selection_forward_report"
    assert output["forward_window"]["label"] == "1m"
    assert output["row_count"] == 2
    assert output["summary"] == {
        "evaluated_count": 2,
        "missing_count": 0,
        "average_return_pct": 0.07,
        "win_rate": 1.0,
        "max_return_pct": 0.1,
        "min_return_pct": 0.04,
    }
    assert output["rows"][0]["symbol"] == "2330.TW"
    assert output["rows"][0]["entry_close"] == 100.0
    assert output["rows"][0]["evaluation_close"] == 110.0
    assert output["rows"][0]["return_pct"] == 0.1
    assert output["rows"][1]["symbol"] == "2317.TW"
    assert output["rows"][1]["selected"] is False
    assert output["rows"][1]["return_pct"] == 0.04

    output_csv = selection_csv.with_name("qizhang_selection_strategy_forward_1m.csv")
    output_summary_csv = selection_csv.with_name("qizhang_selection_strategy_forward_1m_summary.csv")
    assert output["output_csv"] == str(output_csv)
    assert output["output_summary_csv"] == str(output_summary_csv)
    assert output_csv.exists()
    assert output_csv.with_suffix(".png").exists()
    assert output_summary_csv.exists()
    assert output_summary_csv.with_suffix(".png").exists()

    with output_csv.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert rows[0]["symbol"] == "2330.TW"
    assert rows[0]["evaluation_close"] == "110.0"
    assert rows[1]["symbol"] == "2317.TW"
    assert rows[1]["selected"] in {"False", "false", "0", ""}
    with output_summary_csv.open("r", encoding="utf-8", newline="") as handle:
        summary_rows = list(csv.DictReader(handle))
    assert len(summary_rows) == 1
    assert summary_rows[0]["average_return_pct"] == "0.07"
    assert summary_rows[0]["win_rate"] == "1.0"


def test_run_selection_forward_report_marks_missing_evaluation_price(monkeypatch, capsys, tmp_path: Path) -> None:
    selection_csv = tmp_path / "selection.csv"
    with selection_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["symbol", "stock_name", "timestamp"])
        writer.writeheader()
        writer.writerow({
            "symbol": "2330.TW",
            "stock_name": "TSMC",
            "timestamp": "2026-02-11",
        })

    bars = [
        OHLCVBar(symbol="2330.TW", date="2026-02-11", open=100, high=101, low=99, close=100, volume=1000),
    ]

    monkeypatch.setattr(runner_module, "_load_config", lambda: object())
    monkeypatch.setattr(runner_module, "build_app_context", lambda config: _DummyContext(bars))

    args = Namespace(
        selection_csv=str(selection_csv),
        forward_months=None,
        forward_days=30,
        output_csv=str(tmp_path / "forward.csv"),
    )
    runner_module._run_selection_forward_report(args)
    output = json.loads(capsys.readouterr().out)

    assert output["row_count"] == 1
    assert output["summary"] == {
        "evaluated_count": 0,
        "missing_count": 1,
        "average_return_pct": None,
        "win_rate": None,
        "max_return_pct": None,
        "min_return_pct": None,
    }
    assert output["rows"][0]["status"] == "missing_evaluation_price"
    assert output["rows"][0]["evaluation_close"] is None
    assert Path(output["output_csv"]).exists()
    assert Path(output["output_png"]).exists()
    assert Path(output["output_summary_csv"]).exists()
    assert Path(output["output_summary_png"]).exists()
    with Path(output["output_csv"]).open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["symbol"] == "2330.TW"
    with Path(output["output_summary_csv"]).open("r", encoding="utf-8", newline="") as handle:
        summary_rows = list(csv.DictReader(handle))
    assert summary_rows[0]["missing_count"] == "1"
