from __future__ import annotations

import csv
import json
from argparse import Namespace
from datetime import date, datetime

from src.tw_quant import runner as runner_module
from src.tw_quant.schema.models import SelectionRecord
from src.tw_quant.universe.models import ListingStatus, UniverseEntry


class _DummyContext:
    def __init__(self) -> None:
        self.universe_provider = _DummyUniverseProvider()
        self.market_data_provider = object()


class _DummyUniverseProvider:
    def get_universe(self, as_of=None):  # noqa: ANN001
        return [
            UniverseEntry(
                symbol="2330.TW",
                exchange="TWSE",
                market="stock",
                listing_status=ListingStatus.LISTED,
                updated_at=datetime(2026, 3, 15),
                name="TSMC",
            ),
            UniverseEntry(
                symbol="2317.TW",
                exchange="TWSE",
                market="stock",
                listing_status=ListingStatus.LISTED,
                updated_at=datetime(2026, 3, 15),
                name="HonHai",
            ),
            UniverseEntry(
                symbol="2454.TW",
                exchange="TWSE",
                market="stock",
                listing_status=ListingStatus.LISTED,
                updated_at=datetime(2026, 3, 15),
                name="MediaTek",
            ),
        ]

    def get_symbol(self, symbol, as_of=None):  # noqa: ANN001
        for entry in self.get_universe(as_of=as_of):
            if entry.symbol == symbol:
                return entry
        return None


def test_run_daily_selection_range_outputs_deduplicated_stats(monkeypatch, capsys) -> None:
    schedule: dict[str, list[SelectionRecord]] = {
        "2026-03-09": [
            SelectionRecord(symbol="2330.TW", timestamp=date(2026, 3, 9), rank=1, weight=0.5, reason="hit"),
            SelectionRecord(symbol="2317.TW", timestamp=date(2026, 3, 9), rank=2, weight=0.5, reason="hit"),
        ],
        "2026-03-10": [
            SelectionRecord(symbol="2317.TW", timestamp=date(2026, 3, 10), rank=1, weight=1.0, reason="hit"),
        ],
        "2026-03-15": [
            SelectionRecord(symbol="2330.TW", timestamp=date(2026, 3, 15), rank=1, weight=0.6, reason="hit"),
            SelectionRecord(symbol="2454.TW", timestamp=date(2026, 3, 15), rank=2, weight=0.4, reason="hit"),
        ],
    }

    class DummyDailySelectionRunner:
        def __init__(self, *, universe_provider, market_data_provider, app_config=None) -> None:
            self._universe_provider = universe_provider
            self._market_data_provider = market_data_provider
            self.last_run_summary = {}

        def run(
            self,
            *,
            as_of,
            strategy_name,
            selection_config,
            max_workers=1,
            show_progress=None,
            progress_label=None,
        ):  # noqa: ANN001
            self.last_run_summary = {
                "selections": [
                    {
                        "symbol": item.symbol,
                        "timestamp": str(item.timestamp),
                        "rank": item.rank,
                        "weight": item.weight,
                        "reason": item.reason,
                        "signal": "buy",
                        "score": 1.0,
                        "criteria": {"strategy": strategy_name, "window": 20},
                        "criteria_json": '{"strategy": "qizhang_selection_strategy", "window": 20}',
                    }
                    for item in schedule.get(str(as_of), [])
                ]
            }
            return list(schedule.get(str(as_of), []))

    monkeypatch.setattr(runner_module, "_load_config", lambda: object())
    monkeypatch.setattr(runner_module, "build_app_context", lambda config: _DummyContext())
    monkeypatch.setattr(runner_module, "DailySelectionRunner", DummyDailySelectionRunner)

    args = Namespace(
        as_of=None,
        start="2026-03-09",
        end="2026-03-15",
        strategy="qizhang_selection_strategy",
        output_csv=None,
        workers=1,
        show_progress=False,
        missing_history_threshold=0.2,
        top_n=30,
        max_symbols=None,
        symbols=None,
    )

    runner_module._run_daily_selection(args)
    output = json.loads(capsys.readouterr().out)

    assert output["mode"] == "date_range"
    assert output["start"] == "2026-03-09"
    assert output["end"] == "2026-03-15"
    assert output["day_count"] == 7
    assert output["selected_symbol_count"] == 3

    by_symbol = {item["symbol"]: item for item in output["selections"]}
    assert by_symbol["2330.TW"]["stock_name"] == "TSMC"
    assert by_symbol["2330.TW"]["first_matched_date"] == "2026-03-09"
    assert by_symbol["2330.TW"]["last_matched_date"] == "2026-03-15"
    assert by_symbol["2330.TW"]["matched_days"] == 2
    assert by_symbol["2317.TW"]["matched_days"] == 2
    assert by_symbol["2454.TW"]["matched_days"] == 1


def test_run_daily_selection_as_of_keeps_legacy_output_shape(monkeypatch, capsys) -> None:
    class DummyDailySelectionRunner:
        def __init__(self, *, universe_provider, market_data_provider, app_config=None) -> None:
            self._universe_provider = universe_provider
            self._market_data_provider = market_data_provider
            self.last_run_summary = {}

        def run(
            self,
            *,
            as_of,
            strategy_name,
            selection_config,
            max_workers=1,
            show_progress=None,
            progress_label=None,
        ):  # noqa: ANN001
            self.last_run_summary = {
                "selections": [
                    {
                        "symbol": "2330.TW",
                        "timestamp": "2026-03-09",
                        "rank": 1,
                        "weight": 1.0,
                        "reason": "legacy-shape",
                        "signal": "buy",
                        "score": 1.0,
                        "criteria": {"strategy": strategy_name, "short_window": 5, "long_window": 20},
                        "criteria_json": '{"long_window": 20, "short_window": 5, "strategy": "qizhang_selection_strategy"}',
                    }
                ]
            }
            return [
                SelectionRecord(
                    symbol="2330.TW",
                    timestamp=date(2026, 3, 9),
                    rank=1,
                    weight=1.0,
                    reason="legacy-shape",
                )
            ]

    monkeypatch.setattr(runner_module, "_load_config", lambda: object())
    monkeypatch.setattr(runner_module, "build_app_context", lambda config: _DummyContext())
    monkeypatch.setattr(runner_module, "DailySelectionRunner", DummyDailySelectionRunner)

    args = Namespace(
        as_of="2026-03-09",
        start=None,
        end=None,
        strategy="qizhang_selection_strategy",
        output_csv=None,
        workers=1,
        show_progress=False,
        missing_history_threshold=0.2,
        top_n=30,
        max_symbols=None,
        symbols=None,
    )

    runner_module._run_daily_selection(args)
    output = json.loads(capsys.readouterr().out)

    assert isinstance(output, list)
    assert output[0]["symbol"] == "2330.TW"
    assert output[0]["stock_name"] == "TSMC"
    assert output[0]["timestamp"] == "2026-03-09"
    assert output[0]["criteria"]["short_window"] == 5
    assert output[0]["signal"] == "buy"
    assert "matched_days" not in output[0]


def test_run_daily_selection_range_writes_aggregated_csv(monkeypatch, capsys, tmp_path) -> None:
    schedule: dict[str, list[SelectionRecord]] = {
        "2026-03-09": [
            SelectionRecord(symbol="2317.TW", timestamp=date(2026, 3, 9), rank=1, weight=1.0, reason="hit"),
        ],
        "2026-03-10": [
            SelectionRecord(symbol="2317.TW", timestamp=date(2026, 3, 10), rank=1, weight=0.7, reason="hit"),
            SelectionRecord(symbol="2330.TW", timestamp=date(2026, 3, 10), rank=2, weight=0.3, reason="hit"),
        ],
    }

    class DummyDailySelectionRunner:
        def __init__(self, *, universe_provider, market_data_provider, app_config=None) -> None:
            self._universe_provider = universe_provider
            self._market_data_provider = market_data_provider
            self.last_run_summary = {}

        def run(
            self,
            *,
            as_of,
            strategy_name,
            selection_config,
            max_workers=1,
            show_progress=None,
            progress_label=None,
        ):  # noqa: ANN001
            self.last_run_summary = {
                "selections": [
                    {
                        "symbol": item.symbol,
                        "timestamp": str(item.timestamp),
                        "rank": item.rank,
                        "weight": item.weight,
                        "reason": item.reason,
                        "signal": "buy",
                        "score": 1.0,
                        "criteria": {"strategy": strategy_name, "window": 20, "as_of": str(as_of)},
                        "criteria_json": "",
                    }
                    for item in schedule.get(str(as_of), [])
                ]
            }
            return list(schedule.get(str(as_of), []))

    monkeypatch.setattr(runner_module, "_load_config", lambda: object())
    monkeypatch.setattr(runner_module, "build_app_context", lambda config: _DummyContext())
    monkeypatch.setattr(runner_module, "DailySelectionRunner", DummyDailySelectionRunner)

    output_path = tmp_path / "reports" / "range_summary.csv"
    args = Namespace(
        as_of=None,
        start="2026-03-09",
        end="2026-03-10",
        strategy="qizhang_selection_strategy",
        output_csv=str(output_path),
        workers=1,
        show_progress=False,
        missing_history_threshold=0.2,
        top_n=30,
        max_symbols=None,
        symbols=None,
    )

    runner_module._run_daily_selection(args)
    output = json.loads(capsys.readouterr().out)

    assert output["output_csv"] == str(output_path)
    assert output_path.exists()
    assert output_path.with_suffix(".png").exists()
    assert output_path.with_suffix(".png").stat().st_size > 0

    with output_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert rows == [
        {
            "symbol": "2317.TW",
            "stock_name": "HonHai",
            "first_matched_date": "2026-03-09",
            "last_matched_date": "2026-03-10",
            "matched_days": "2",
            "latest_signal": "buy",
            "latest_score": "1.0",
            "latest_criteria_json": '{"as_of": "2026-03-10", "strategy": "qizhang_selection_strategy", "window": 20}',
            "criteria_history_json": '[{"criteria": {"as_of": "2026-03-09", "strategy": "qizhang_selection_strategy", "window": 20}, "date": "2026-03-09", "score": 1.0, "signal": "buy"}, {"criteria": {"as_of": "2026-03-10", "strategy": "qizhang_selection_strategy", "window": 20}, "date": "2026-03-10", "score": 1.0, "signal": "buy"}]',
        },
        {
            "symbol": "2330.TW",
            "stock_name": "TSMC",
            "first_matched_date": "2026-03-10",
            "last_matched_date": "2026-03-10",
            "matched_days": "1",
            "latest_signal": "buy",
            "latest_score": "1.0",
            "latest_criteria_json": '{"as_of": "2026-03-10", "strategy": "qizhang_selection_strategy", "window": 20}',
            "criteria_history_json": '[{"criteria": {"as_of": "2026-03-10", "strategy": "qizhang_selection_strategy", "window": 20}, "date": "2026-03-10", "score": 1.0, "signal": "buy"}]',
        },
    ]


def test_run_daily_selection_forwards_workers_to_runner(monkeypatch, capsys) -> None:
    observed: dict[str, int] = {}

    class DummyDailySelectionRunner:
        def __init__(self, *, universe_provider, market_data_provider, app_config=None) -> None:
            self._universe_provider = universe_provider
            self._market_data_provider = market_data_provider
            self.last_run_summary = {"selections": []}

        def run(
            self,
            *,
            as_of,
            strategy_name,
            selection_config,
            max_workers=1,
            show_progress=None,
            progress_label=None,
        ):  # noqa: ANN001
            observed["max_workers"] = max_workers
            return []

    monkeypatch.setattr(runner_module, "_load_config", lambda: object())
    monkeypatch.setattr(runner_module, "build_app_context", lambda config: _DummyContext())
    monkeypatch.setattr(runner_module, "DailySelectionRunner", DummyDailySelectionRunner)

    args = Namespace(
        as_of="2026-03-09",
        start=None,
        end=None,
        strategy="qizhang_selection_strategy",
        output_csv=None,
        workers=8,
        show_progress=False,
        missing_history_threshold=0.2,
        top_n=30,
        max_symbols=None,
        symbols=None,
    )

    runner_module._run_daily_selection(args)
    capsys.readouterr()
    assert observed["max_workers"] == 8


def test_run_daily_selection_blocks_when_missing_history_exceeds_threshold(monkeypatch) -> None:
    class DummyDailySelectionRunner:
        def __init__(self, *, universe_provider, market_data_provider, app_config=None) -> None:
            self._universe_provider = universe_provider
            self._market_data_provider = market_data_provider
            self.last_run_summary = {
                "as_of": "2026-03-09",
                "universe_size": 100,
                "missing_history_count": 30,
            }

        def run(
            self,
            *,
            as_of,
            strategy_name,
            selection_config,
            max_workers=1,
            show_progress=None,
            progress_label=None,
        ):  # noqa: ANN001
            return []

    monkeypatch.setattr(runner_module, "_load_config", lambda: object())
    monkeypatch.setattr(runner_module, "build_app_context", lambda config: _DummyContext())
    monkeypatch.setattr(runner_module, "DailySelectionRunner", DummyDailySelectionRunner)

    args = Namespace(
        as_of="2026-03-09",
        start=None,
        end=None,
        strategy="qizhang_selection_strategy",
        output_csv=None,
        workers=1,
        show_progress=False,
        missing_history_threshold=0.2,
        top_n=30,
        max_symbols=None,
        symbols=None,
    )

    import pytest

    with pytest.raises(SystemExit, match="missing-history ratio exceeded threshold"):
        runner_module._run_daily_selection(args)
