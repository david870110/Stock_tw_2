from __future__ import annotations

import csv
import json
from argparse import Namespace
from datetime import date, datetime
from pathlib import Path

from src.tw_quant import runner as runner_module
from src.tw_quant.schema.models import OHLCVBar
from src.tw_quant.universe.models import ListingStatus, UniverseEntry


def _parse_last_json_from_stdout(text: str) -> dict[str, object]:
    start = text.rfind("\n{")
    if start >= 0:
        start += 1
    else:
        start = text.find("{")
    return json.loads(text[start:])


class _DummyMarketDataProvider:
    def __init__(self, bars: list[OHLCVBar]) -> None:
        self._bars = list(bars)

    def fetch_ohlcv(self, symbols, start, end):  # noqa: ANN001
        symbol_set = {str(symbol) for symbol in symbols}
        return [bar for bar in self._bars if str(bar.symbol) in symbol_set]


class _DummyUniverseProvider:
    def get_universe(self, as_of=None):  # noqa: ANN001
        return [
            UniverseEntry(
                symbol="2330.TW",
                name="TSMC",
                exchange="TWSE",
                market="stock",
                listing_status=ListingStatus.LISTED,
                updated_at=datetime(2025, 1, 31),
            )
        ]

    def get_symbol(self, symbol, as_of=None):  # noqa: ANN001
        if str(symbol) != "2330.TW":
            return None
        return UniverseEntry(
            symbol="2330.TW",
            name="TSMC",
            exchange="TWSE",
            market="stock",
            listing_status=ListingStatus.LISTED,
            updated_at=datetime(2025, 1, 31),
        )


class _DummyContext:
    def __init__(self, bars: list[OHLCVBar]) -> None:
        self.market_data_provider = _DummyMarketDataProvider(bars)
        self.universe_provider = _DummyUniverseProvider()


class _DummyDailySelectionRunner:
    def __init__(self, *, output_base: str, **kwargs) -> None:  # noqa: ANN003
        self._output_base = Path(output_base)
        self.last_run_summary: dict[str, object] = {}

    def run(self, *, as_of, strategy_name, **kwargs):  # noqa: ANN003
        selection_date = as_of if isinstance(as_of, date) else date.fromisoformat(str(as_of))
        output_dir = self._output_base / "tw_quant" / "daily_selection" / selection_date.isoformat()
        output_dir.mkdir(parents=True, exist_ok=True)

        csv_path = output_dir / f"{strategy_name}.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["symbol", "stock_name", "timestamp", "rank", "weight", "reason", "signal", "score", "selected"],
            )
            writer.writeheader()
            writer.writerow({
                "symbol": "2330.TW",
                "stock_name": "TSMC",
                "timestamp": selection_date.isoformat(),
                "rank": 1,
                "weight": 1.0,
                "reason": "buy",
                "signal": "buy",
                "score": 1.0,
                "selected": True,
            })

        self.last_run_summary = {
            "as_of": selection_date.isoformat(),
            "universe_size": 10,
            "missing_history_count": 0,
            "csv_rows": [
                {
                    "symbol": "2330.TW",
                    "stock_name": "TSMC",
                    "timestamp": selection_date.isoformat(),
                    "rank": 1,
                    "weight": 1.0,
                    "reason": "buy",
                    "signal": "buy",
                    "score": 1.0,
                    "selected": True,
                }
            ],
        }
        return []


def test_run_strategy_improve_report_writes_bucketed_stock_report_artifacts(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    bars = [
        OHLCVBar(symbol="2330.TW", date="2025-01-31", open=100, high=101, low=99, close=100, volume=1000),
        OHLCVBar(symbol="2330.TW", date="2025-02-28", open=124, high=126, low=123, close=125, volume=1200),
    ]

    monkeypatch.setattr(
        runner_module,
        "_prepare_daily_selection_environment",
        lambda args: (object(), _DummyContext(bars), _DummyUniverseProvider()),
    )
    monkeypatch.setattr(runner_module, "DailySelectionRunner", _DummyDailySelectionRunner)
    monkeypatch.setattr(
        runner_module,
        "_build_strategy_improve_sample_plan",
        lambda **kwargs: [  # noqa: ARG005
            {
                "sample_year": 2025,
                "sample_month": 1,
                "selection_date": "2025-01-31",
            }
        ],
    )

    args = Namespace(
        strategy="qizhang_selection_strategy",
        years=1,
        months_per_year=1,
        sample_end_year=2025,
        sample_seed=42,
        workers=20,
        show_progress=False,
        missing_history_threshold=0.2,
        top_n=30,
        max_symbols=None,
        symbols=None,
        output_root=str(tmp_path / "artifacts" / "Stratage_improve"),
    )

    runner_module._run_strategy_improve_report(args)
    output = _parse_last_json_from_stdout(capsys.readouterr().out)

    artifact_root = Path(output["artifact_root"])
    assert output["mode"] == "strategy_improve_report"
    assert output["selection_run_count"] == 1
    assert output["selected_symbol_count"] == 1
    assert output["evaluated_row_count"] == 1
    assert output["bucket_counts"]["gte_0_2"] == 1
    assert output["forward_fetch_diagnostics"]["failed_row_count"] == 0
    assert output["forward_fetch_diagnostics"]["missing_symbols"] == []

    assert (artifact_root / "manifest" / "sample_plan.csv").exists()
    assert (artifact_root / "manifest" / "run_manifest.json").exists()
    assert (artifact_root / "forward_returns" / "forward_returns.csv").exists()
    assert (artifact_root / "buckets" / "bucket_summary.csv").exists()
    assert (artifact_root / "selection_cache" / "tw_quant" / "daily_selection" / "2025-01-31" / "qizhang_selection_strategy.csv").exists()

    gte_csv = artifact_root / "stock_reports" / "2025-01-31" / "gte_0_2.csv"
    empty_csv = artifact_root / "stock_reports" / "2025-01-31" / "lt_neg_0_2.csv"
    assert gte_csv.exists()
    assert empty_csv.exists()

    with gte_csv.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    assert rows[0]["bucket"] == "gte_0_2"
    assert rows[0]["selection_date"] == "2025-01-31"
    assert rows[0]["return_pct"] == "0.25"
    assert rows[0]["symbol"] == "2330.TW"

    with empty_csv.open("r", encoding="utf-8", newline="") as handle:
        empty_rows = list(csv.DictReader(handle))
    assert empty_rows == []


def test_run_strategy_improve_report_accepts_qizhang_improve_strategy_name(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    bars = [
        OHLCVBar(symbol="2330.TW", date="2025-01-31", open=100, high=101, low=99, close=100, volume=1000),
        OHLCVBar(symbol="2330.TW", date="2025-02-28", open=124, high=126, low=123, close=125, volume=1200),
    ]

    monkeypatch.setattr(
        runner_module,
        "_prepare_daily_selection_environment",
        lambda args: (object(), _DummyContext(bars), _DummyUniverseProvider()),
    )
    monkeypatch.setattr(runner_module, "DailySelectionRunner", _DummyDailySelectionRunner)
    monkeypatch.setattr(
        runner_module,
        "_build_strategy_improve_sample_plan",
        lambda **kwargs: [  # noqa: ARG005
            {
                "sample_year": 2025,
                "sample_month": 1,
                "selection_date": "2025-01-31",
            }
        ],
    )

    args = Namespace(
        strategy="qizhang_improve_strategy",
        years=1,
        months_per_year=1,
        sample_end_year=2025,
        sample_seed=42,
        workers=20,
        show_progress=False,
        missing_history_threshold=0.2,
        top_n=30,
        max_symbols=None,
        symbols=None,
        output_root=str(tmp_path / "artifacts" / "Stratage_improve"),
    )

    runner_module._run_strategy_improve_report(args)
    output = _parse_last_json_from_stdout(capsys.readouterr().out)

    artifact_root = Path(output["artifact_root"])
    assert output["mode"] == "strategy_improve_report"
    assert output["selection_run_count"] == 1
    assert (artifact_root / "selection_cache" / "tw_quant" / "daily_selection" / "2025-01-31" / "qizhang_improve_strategy.csv").exists()


def test_run_strategy_improve_report_accepts_qizhang_improve_strategy_v15_name(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    bars = [
        OHLCVBar(symbol="2330.TW", date="2025-01-31", open=100, high=101, low=99, close=100, volume=1000),
        OHLCVBar(symbol="2330.TW", date="2025-02-28", open=124, high=126, low=123, close=125, volume=1200),
    ]

    monkeypatch.setattr(
        runner_module,
        "_prepare_daily_selection_environment",
        lambda args: (object(), _DummyContext(bars), _DummyUniverseProvider()),
    )
    monkeypatch.setattr(runner_module, "DailySelectionRunner", _DummyDailySelectionRunner)
    monkeypatch.setattr(
        runner_module,
        "_build_strategy_improve_sample_plan",
        lambda **kwargs: [  # noqa: ARG005
            {
                "sample_year": 2025,
                "sample_month": 1,
                "selection_date": "2025-01-31",
            }
        ],
    )

    args = Namespace(
        strategy="qizhang_improve_strategy_v15",
        years=1,
        months_per_year=1,
        sample_end_year=2025,
        sample_seed=42,
        workers=20,
        show_progress=False,
        missing_history_threshold=0.2,
        top_n=30,
        max_symbols=None,
        symbols=None,
        output_root=str(tmp_path / "artifacts" / "Stratage_improve"),
    )

    runner_module._run_strategy_improve_report(args)
    output = _parse_last_json_from_stdout(capsys.readouterr().out)

    artifact_root = Path(output["artifact_root"])
    assert output["mode"] == "strategy_improve_report"
    assert output["selection_run_count"] == 1
    assert (artifact_root / "selection_cache" / "tw_quant" / "daily_selection" / "2025-01-31" / "qizhang_improve_strategy_v15.csv").exists()


def test_run_strategy_improve_report_supports_show_progress_path(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    bars = [
        OHLCVBar(symbol="2330.TW", date="2025-01-31", open=100, high=101, low=99, close=100, volume=1000),
        OHLCVBar(symbol="2330.TW", date="2025-02-28", open=124, high=126, low=123, close=125, volume=1200),
    ]

    monkeypatch.setattr(
        runner_module,
        "_prepare_daily_selection_environment",
        lambda args: (object(), _DummyContext(bars), _DummyUniverseProvider()),
    )
    monkeypatch.setattr(runner_module, "DailySelectionRunner", _DummyDailySelectionRunner)
    monkeypatch.setattr(
        runner_module,
        "_build_strategy_improve_sample_plan",
        lambda **kwargs: [  # noqa: ARG005
            {
                "sample_year": 2025,
                "sample_month": 1,
                "selection_date": "2025-01-31",
            }
        ],
    )
    monkeypatch.setattr(
        runner_module,
        "_create_progress_iterable",
        lambda *, iterable, desc, unit: iterable,  # noqa: ARG005
    )

    args = Namespace(
        strategy="qizhang_selection_strategy",
        years=1,
        months_per_year=1,
        sample_end_year=2025,
        sample_seed=42,
        workers=20,
        show_progress=True,
        missing_history_threshold=0.2,
        top_n=30,
        max_symbols=None,
        symbols=None,
        output_root=str(tmp_path / "artifacts" / "Stratage_improve"),
    )

    runner_module._run_strategy_improve_report(args)
    output = _parse_last_json_from_stdout(capsys.readouterr().out)

    assert output["mode"] == "strategy_improve_report"
    assert output["selected_symbol_count"] == 1


def test_run_strategy_improve_report_warns_and_skips_dates_over_threshold(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    bars = [
        OHLCVBar(symbol="2330.TW", date="2025-02-28", open=100, high=101, low=99, close=100, volume=1000),
        OHLCVBar(symbol="2330.TW", date="2025-03-31", open=124, high=126, low=123, close=125, volume=1200),
    ]

    class _ThresholdAwareDummyRunner(_DummyDailySelectionRunner):
        def run(self, *, as_of, strategy_name, **kwargs):  # noqa: ANN003
            selection_date = as_of if isinstance(as_of, date) else date.fromisoformat(str(as_of))
            if selection_date.isoformat() == "2025-01-31":
                self.last_run_summary = {
                    "as_of": selection_date.isoformat(),
                    "universe_size": 10,
                    "missing_history_count": 7,
                    "csv_rows": [],
                }
                return []
            return super().run(as_of=as_of, strategy_name=strategy_name, **kwargs)

    monkeypatch.setattr(
        runner_module,
        "_prepare_daily_selection_environment",
        lambda args: (object(), _DummyContext(bars), _DummyUniverseProvider()),
    )
    monkeypatch.setattr(runner_module, "DailySelectionRunner", _ThresholdAwareDummyRunner)
    monkeypatch.setattr(
        runner_module,
        "_build_strategy_improve_sample_plan",
        lambda **kwargs: [  # noqa: ARG005
            {"sample_year": 2025, "sample_month": 1, "selection_date": "2025-01-31"},
            {"sample_year": 2025, "sample_month": 2, "selection_date": "2025-02-28"},
        ],
    )

    args = Namespace(
        strategy="qizhang_selection_strategy",
        years=1,
        months_per_year=2,
        sample_end_year=2025,
        sample_seed=42,
        workers=20,
        show_progress=False,
        missing_history_threshold=0.2,
        top_n=30,
        max_symbols=None,
        symbols=None,
        output_root=str(tmp_path / "artifacts" / "Stratage_improve"),
    )

    runner_module._run_strategy_improve_report(args)
    captured = capsys.readouterr().out
    output = _parse_last_json_from_stdout(captured)

    assert "Warning: Daily selection aborted because missing-history ratio exceeded threshold" in captured
    assert output["selection_run_count"] == 2
    assert output["selected_symbol_count"] == 1
    assert output["skipped_date_count"] == 1
    assert output["skipped_dates"][0]["selection_date"] == "2025-01-31"
    assert output["sampled_dates"] == ["2025-01-31", "2025-02-28"]


def test_run_strategy_improve_report_uses_all_buy_signals_not_only_selected(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    bars = [
        OHLCVBar(symbol="2330.TW", date="2025-01-31", open=100, high=101, low=99, close=100, volume=1000),
        OHLCVBar(symbol="2330.TW", date="2025-02-28", open=109, high=110, low=108, close=110, volume=1200),
        OHLCVBar(symbol="2317.TW", date="2025-01-31", open=50, high=51, low=49, close=50, volume=800),
        OHLCVBar(symbol="2317.TW", date="2025-02-28", open=59, high=60, low=58, close=60, volume=900),
    ]

    class _AllSignalUniverseProvider:
        def get_universe(self, as_of=None):  # noqa: ANN001
            return [
                UniverseEntry(
                    symbol="2330.TW",
                    name="TSMC",
                    exchange="TWSE",
                    market="stock",
                    listing_status=ListingStatus.LISTED,
                    updated_at=datetime(2025, 1, 31),
                ),
                UniverseEntry(
                    symbol="2317.TW",
                    name="HonHai",
                    exchange="TWSE",
                    market="stock",
                    listing_status=ListingStatus.LISTED,
                    updated_at=datetime(2025, 1, 31),
                ),
            ]

        def get_symbol(self, symbol, as_of=None):  # noqa: ANN001
            entries = {item.symbol: item for item in self.get_universe(as_of=as_of)}
            return entries.get(str(symbol))

    class _AllSignalContext:
        def __init__(self, bars: list[OHLCVBar]) -> None:
            self.market_data_provider = _DummyMarketDataProvider(bars)
            self.universe_provider = _AllSignalUniverseProvider()

    class _AllSignalDummyRunner(_DummyDailySelectionRunner):
        def run(self, *, as_of, strategy_name, **kwargs):  # noqa: ANN003
            selection_date = as_of if isinstance(as_of, date) else date.fromisoformat(str(as_of))
            output_dir = self._output_base / "tw_quant" / "daily_selection" / selection_date.isoformat()
            output_dir.mkdir(parents=True, exist_ok=True)
            rows = [
                {
                    "symbol": "2330.TW",
                    "stock_name": "TSMC",
                    "timestamp": selection_date.isoformat(),
                    "rank": 1,
                    "weight": 1.0,
                    "reason": "buy",
                    "signal": "buy",
                    "score": 1.0,
                    "selected": True,
                },
                {
                    "symbol": "2317.TW",
                    "stock_name": "HonHai",
                    "timestamp": selection_date.isoformat(),
                    "rank": "",
                    "weight": "",
                    "reason": "buy",
                    "signal": "buy",
                    "score": 0.8,
                    "selected": False,
                },
            ]
            csv_path = output_dir / f"{strategy_name}.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["symbol", "stock_name", "timestamp", "rank", "weight", "reason", "signal", "score", "selected"],
                )
                writer.writeheader()
                for row in rows:
                    writer.writerow(row)
            self.last_run_summary = {
                "as_of": selection_date.isoformat(),
                "universe_size": 10,
                "missing_history_count": 0,
                "csv_rows": rows,
            }
            return []

    monkeypatch.setattr(
        runner_module,
        "_prepare_daily_selection_environment",
        lambda args: (object(), _AllSignalContext(bars), _AllSignalUniverseProvider()),
    )
    monkeypatch.setattr(runner_module, "DailySelectionRunner", _AllSignalDummyRunner)
    monkeypatch.setattr(
        runner_module,
        "_build_strategy_improve_sample_plan",
        lambda **kwargs: [  # noqa: ARG005
            {
                "sample_year": 2025,
                "sample_month": 1,
                "selection_date": "2025-01-31",
            }
        ],
    )

    args = Namespace(
        strategy="qizhang_selection_strategy",
        years=1,
        months_per_year=1,
        sample_end_year=2025,
        sample_seed=42,
        workers=20,
        show_progress=False,
        missing_history_threshold=0.2,
        top_n=1,
        max_symbols=None,
        symbols=None,
        output_root=str(tmp_path / "artifacts" / "Stratage_improve"),
    )

    runner_module._run_strategy_improve_report(args)
    output = _parse_last_json_from_stdout(capsys.readouterr().out)
    forward_csv = Path(output["output_paths"]["forward_returns_csv"])

    assert output["selected_symbol_count"] == 2
    assert output["evaluated_row_count"] == 2

    with forward_csv.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert {row["symbol"] for row in rows} == {"2330.TW", "2317.TW"}
    by_symbol = {row["symbol"]: row for row in rows}
    assert by_symbol["2330.TW"]["selected"] in {"True", "true", "1"}
    assert by_symbol["2317.TW"]["selected"] in {"False", "false", "0", ""}
    assert by_symbol["2317.TW"]["status"] == "ok"


def test_run_strategy_improve_report_refreshes_provider_before_forward_stage(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    class _FakeConfig:
        class data:  # noqa: N801
            wiring_mode = "active"

    stale_bars: list[OHLCVBar] = []
    fresh_bars = [
        OHLCVBar(symbol="2330.TW", date="2025-01-31", open=100, high=101, low=99, close=100, volume=1000),
        OHLCVBar(symbol="2330.TW", date="2025-02-28", open=124, high=126, low=123, close=125, volume=1200),
    ]

    monkeypatch.setattr(
        runner_module,
        "_prepare_daily_selection_environment",
        lambda args: (_FakeConfig(), _DummyContext(stale_bars), _DummyUniverseProvider()),
    )
    monkeypatch.setattr(
        runner_module,
        "build_app_context",
        lambda config: _DummyContext(fresh_bars),  # noqa: ARG005
    )
    monkeypatch.setattr(runner_module, "DailySelectionRunner", _DummyDailySelectionRunner)
    monkeypatch.setattr(
        runner_module,
        "_build_strategy_improve_sample_plan",
        lambda **kwargs: [  # noqa: ARG005
            {
                "sample_year": 2025,
                "sample_month": 1,
                "selection_date": "2025-01-31",
            }
        ],
    )

    args = Namespace(
        strategy="qizhang_selection_strategy",
        years=1,
        months_per_year=1,
        sample_end_year=2025,
        sample_seed=42,
        workers=20,
        show_progress=False,
        missing_history_threshold=0.2,
        top_n=30,
        max_symbols=None,
        symbols=None,
        output_root=str(tmp_path / "artifacts" / "Stratage_improve"),
    )

    runner_module._run_strategy_improve_report(args)
    output = _parse_last_json_from_stdout(capsys.readouterr().out)

    assert output["evaluated_row_count"] == 1
    assert output["missing_row_count"] == 0
    assert output["forward_fetch_diagnostics"]["failed_row_count"] == 0
    assert output["forward_fetch_diagnostics"]["status_counts"] == {}


def test_run_strategy_improve_report_records_forward_fetch_diagnostics_in_manifest(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        runner_module,
        "_prepare_daily_selection_environment",
        lambda args: (object(), _DummyContext([]), _DummyUniverseProvider()),
    )
    monkeypatch.setattr(runner_module, "DailySelectionRunner", _DummyDailySelectionRunner)
    monkeypatch.setattr(
        runner_module,
        "_build_strategy_improve_sample_plan",
        lambda **kwargs: [  # noqa: ARG005
            {
                "sample_year": 2025,
                "sample_month": 1,
                "selection_date": "2025-01-31",
            }
        ],
    )

    args = Namespace(
        strategy="qizhang_selection_strategy",
        years=1,
        months_per_year=1,
        sample_end_year=2025,
        sample_seed=42,
        workers=20,
        show_progress=False,
        missing_history_threshold=0.2,
        top_n=30,
        max_symbols=None,
        symbols=None,
        output_root=str(tmp_path / "artifacts" / "Stratage_improve"),
    )

    runner_module._run_strategy_improve_report(args)
    output = _parse_last_json_from_stdout(capsys.readouterr().out)

    assert output["selected_symbol_count"] == 1
    assert output["evaluated_row_count"] == 0
    assert output["missing_row_count"] == 1
    assert output["forward_fetch_diagnostics"]["ok_row_count"] == 0
    assert output["forward_fetch_diagnostics"]["failed_row_count"] == 1
    assert output["forward_fetch_diagnostics"]["failed_symbol_count"] == 1
    assert output["forward_fetch_diagnostics"]["missing_symbols"] == ["2330.TW"]
    assert output["forward_fetch_diagnostics"]["status_counts"] == {
        "missing_entry_price|missing_evaluation_price": 1,
    }
    assert output["forward_fetch_diagnostics"]["failed_rows"] == [
        {
            "selection_date": "2025-01-31",
            "target_date": "2025-02-28",
            "symbol": "2330.TW",
            "stock_name": "TSMC",
            "status": "missing_entry_price|missing_evaluation_price",
        }
    ]
