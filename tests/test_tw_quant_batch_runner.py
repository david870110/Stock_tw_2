"""Unit tests for deterministic batch backtest orchestration."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.tw_quant.batch.runner import (
    DeterministicBatchRunner,
    build_artifact_path,
    build_batch_id,
    build_run_id,
)
from src.tw_quant.schema.models import BacktestResult


def _ok_executor(symbol, strategy_name, start, end, parameters, run_id, artifact_path):
    return BacktestResult(
        run_id=run_id,
        strategy_name=strategy_name,
        start=start,
        end=end,
        metrics={"final_nav": 1.0, "num_trades": 0.0},
    )


def test_run_grid_accepts_parameter_grid_symbol_subset_and_windows() -> None:
    calls: list[dict] = []

    def executor(symbol, strategy_name, start, end, parameters, run_id, artifact_path):
        calls.append(
            {
                "symbol": symbol,
                "strategy_name": strategy_name,
                "start": start,
                "end": end,
                "parameters": parameters,
                "run_id": run_id,
                "artifact_path": artifact_path,
            }
        )
        return _ok_executor(symbol, strategy_name, start, end, parameters, run_id, artifact_path)

    runner = DeterministicBatchRunner(execute_run=executor, storage_base="/store")
    parameter_sets = [
        {"strategy_name": "ma_cross", "parameters": {"short": 5, "long": 20}},
        {"strategy_name": "ma_cross", "parameters": {"short": 10, "long": 60}},
    ]
    symbols = ["2330.TW", "2317.TW"]
    windows = [(date(2024, 1, 1), date(2024, 1, 31))]

    result = runner.run_grid(parameter_sets=parameter_sets, symbols=symbols, windows=windows)

    assert result.run_count == 4
    assert result.success_count == 4
    assert result.failed_count == 0
    assert len(result.results) == 4
    assert len(result.run_records) == 4
    assert len(calls) == 4
    assert all(record.status == "SUCCESS" for record in result.run_records)


def test_run_id_is_deterministic_for_same_payload() -> None:
    run_id_1 = build_run_id(
        symbol="2330.TW",
        strategy_name="ma_cross",
        start="2024-01-01",
        end="2024-01-31",
        parameters={"long": 20, "short": 5},
    )
    run_id_2 = build_run_id(
        symbol="2330.TW",
        strategy_name="ma_cross",
        start="2024-01-01",
        end="2024-01-31",
        parameters={"short": 5, "long": 20},
    )

    assert run_id_1 == run_id_2
    assert run_id_1.startswith("run_")
    assert len(run_id_1) == 20


def test_batch_id_is_deterministic_across_input_ordering() -> None:
    parameter_sets_a = [
        {"strategy_name": "alpha", "parameters": {"x": 1}},
        {"strategy_name": "beta", "parameters": {"y": 2}},
    ]
    parameter_sets_b = [
        {"strategy_name": "beta", "parameters": {"y": 2}},
        {"strategy_name": "alpha", "parameters": {"x": 1}},
    ]

    symbols_a = ["2330.TW", "2317.TW"]
    symbols_b = ["2317.TW", "2330.TW"]

    windows_a = [("2024-01-01", "2024-01-31"), ("2024-02-01", "2024-02-28")]
    windows_b = [("2024-02-01", "2024-02-28"), ("2024-01-01", "2024-01-31")]

    batch_a = build_batch_id(parameter_sets_a, symbols_a, windows_a, batch_label="l1")
    batch_b = build_batch_id(parameter_sets_b, symbols_b, windows_b, batch_label="l1")

    assert batch_a == batch_b
    assert batch_a.startswith("batch_")
    assert len(batch_a) == 22


def test_artifact_path_uses_deterministic_template() -> None:
    artifact_path = build_artifact_path(
        storage_base="/storage",
        batch_id="batch_1234567890abcdef",
        symbol="2330.TW",
        strategy_name="ma_cross",
        start="2024-01-01",
        end="2024-01-31",
        run_id="run_abcdef1234567890",
    )

    assert (
        artifact_path
        == "/storage/tw_quant/batch/batch_1234567890abcdef/2330.TW/"
        "ma_cross/2024-01-01_2024-01-31/run_abcdef1234567890.json"
    )


def test_failure_isolation_keeps_partial_successful_results() -> None:
    def executor(symbol, strategy_name, start, end, parameters, run_id, artifact_path):
        if symbol == "2317.TW":
            raise RuntimeError("simulated failure")
        return _ok_executor(symbol, strategy_name, start, end, parameters, run_id, artifact_path)

    runner = DeterministicBatchRunner(execute_run=executor, storage_base="/store")

    result = runner.run_grid(
        parameter_sets=[{"strategy_name": "ma_cross", "parameters": {"short": 5, "long": 20}}],
        symbols=["2330.TW", "2317.TW"],
        windows=[("2024-01-01", "2024-01-31")],
    )

    assert result.run_count == 2
    assert result.success_count == 1
    assert result.failed_count == 1
    assert len(result.results) == 1
    assert len(result.run_records) == 2

    statuses = {record.symbol: record.status for record in result.run_records}
    assert statuses["2330.TW"] == "SUCCESS"
    assert statuses["2317.TW"] == "FAILED"

    failed_record = next(record for record in result.run_records if record.status == "FAILED")
    assert failed_record.error_message == "simulated failure"


def test_checkpoint_hooks_receive_batch_and_run_events() -> None:
    events: list[tuple[str, str]] = []

    class Hook:
        def on_batch_start(self, batch_id, metadata):
            events.append(("start", batch_id))

        def on_run_complete(self, batch_id, record, result):
            events.append(("ok", record.run_id))

        def on_run_error(self, batch_id, record, error):
            events.append(("err", record.run_id))

        def on_batch_end(self, batch_id, result):
            events.append(("end", batch_id))

    runner = DeterministicBatchRunner(execute_run=_ok_executor, storage_base="/store")
    result = runner.run_grid(
        parameter_sets=[{"strategy_name": "ma_cross", "parameters": {"short": 5, "long": 20}}],
        symbols=["2330.TW"],
        windows=[("2024-01-01", "2024-01-31")],
        checkpoint_hook=Hook(),
    )

    assert result.success_count == 1
    assert [item[0] for item in events] == ["start", "ok", "end"]


def test_run_grid_accepts_two_suffix_symbols() -> None:
    runner = DeterministicBatchRunner(execute_run=_ok_executor)

    result = runner.run_grid(
        parameter_sets=[{"strategy_name": "ma_cross", "parameters": {"short": 5, "long": 20}}],
        symbols=["6488.TWO"],
        windows=[("2024-01-01", "2024-01-31")],
    )

    assert result.success_count == 1
    assert result.failed_count == 0
    assert result.run_records[0].symbol == "6488.TWO"


def test_run_grid_writes_user_backtest_csv_triplet(tmp_path: Path) -> None:
    runner = DeterministicBatchRunner(execute_run=_ok_executor, storage_base=str(tmp_path))

    result = runner.run_grid(
        parameter_sets=[{"strategy_name": "ma_cross", "parameters": {"short": 5, "long": 20}}],
        symbols=["2330.TW"],
        windows=[("2024-01-01", "2024-01-31")],
    )

    batch_dir = tmp_path / "tw_quant" / "batch" / result.batch_id
    trades_path = batch_dir / "backtest_trades.csv"
    summary_path = batch_dir / "backtest_summary.csv"
    equity_path = batch_dir / "backtest_equity.csv"

    assert trades_path.exists()
    assert summary_path.exists()
    assert equity_path.exists()

    trades_header = trades_path.read_text(encoding="utf-8").splitlines()[0]
    assert trades_header == (
        "stock_id,stock_name,signal_date,entry_date,entry_price,exit_date,"
        "exit_price,holding_days,exit_reason,return_pct,exit_fraction,exit_shares,is_partial_exit"
    )

    summary_header = summary_path.read_text(encoding="utf-8").splitlines()[0]
    assert summary_header == (
        "start_date,end_date,entry_conditions,exit_rules,total_return,bench_return,end_equity,"
        "stocks_used,universe_size,max_pos,cooldown_days,ckpt_enable,ckpt_resume,ckpt_dir,"
        "require_full_signals,error_top_n"
    )

    equity_header = equity_path.read_text(encoding="utf-8").splitlines()[0]
    assert equity_header == "date,equity,pos_count,bench_equity"


def test_run_grid_populates_buy_and_hold_benchmark_fields(tmp_path: Path) -> None:
    def executor(symbol, strategy_name, start, end, parameters, run_id, artifact_path):
        return BacktestResult(
            run_id=run_id,
            strategy_name=strategy_name,
            start=start,
            end=end,
            metrics={"final_nav": 1.0, "num_trades": 0.0},
            equity_curve=[
                {"date": "2024-01-01", "equity": 1.0, "pos_count": 0},
                {"date": "2024-01-02", "equity": 1.0, "pos_count": 0},
                {"date": "2024-01-03", "equity": 1.0, "pos_count": 0},
            ],
        )

    def benchmark_fetcher(symbol, start, end):
        assert symbol == "2330.TW"
        return {
            "2024-01-02": 100.0,
            "2024-01-03": 110.0,
        }

    runner = DeterministicBatchRunner(
        execute_run=executor,
        storage_base=str(tmp_path),
        benchmark_symbol="2330.TW",
        benchmark_close_fetcher=benchmark_fetcher,
    )

    result = runner.run_grid(
        parameter_sets=[{"strategy_name": "ma_cross", "parameters": {"short": 5, "long": 20}}],
        symbols=["2330.TW"],
        windows=[("2024-01-01", "2024-01-03")],
    )

    batch_dir = tmp_path / "tw_quant" / "batch" / result.batch_id
    summary_path = batch_dir / "backtest_summary.csv"
    equity_path = batch_dir / "backtest_equity.csv"

    summary_lines = summary_path.read_text(encoding="utf-8").splitlines()
    summary_values = summary_lines[1].split(",")
    assert float(summary_values[5]) == pytest.approx(0.1)

    equity_lines = equity_path.read_text(encoding="utf-8").splitlines()
    assert equity_lines[1].endswith(",")
    assert equity_lines[2].endswith(",1.0")
    assert equity_lines[3].endswith(",1.1")


def test_run_grid_uses_sequential_strategy_batch_folder_name_when_label_provided(tmp_path: Path) -> None:
    runner = DeterministicBatchRunner(execute_run=_ok_executor, storage_base=str(tmp_path))

    first = runner.run_grid(
        parameter_sets=[{"strategy_name": "pullback_trend_compression", "parameters": {}}],
        symbols=["2330.TW"],
        windows=[("2024-01-01", "2024-01-31")],
        batch_label="pullback_trend_compression",
    )
    second = runner.run_grid(
        parameter_sets=[{"strategy_name": "pullback_trend_compression", "parameters": {}}],
        symbols=["2317.TW"],
        windows=[("2024-02-01", "2024-02-29")],
        batch_label="pullback_trend_compression",
    )

    assert first.batch_id == "batch_pullback_trend_compression_00"
    assert second.batch_id == "batch_pullback_trend_compression_01"


def test_run_grid_sanitizes_label_for_batch_folder_name(tmp_path: Path) -> None:
    runner = DeterministicBatchRunner(execute_run=_ok_executor, storage_base=str(tmp_path))

    result = runner.run_grid(
        parameter_sets=[{"strategy_name": "demo", "parameters": {}}],
        symbols=["2330.TW"],
        windows=[("2024-01-01", "2024-01-31")],
        batch_label="Pullback Trend/Compression",
    )

    assert result.batch_id == "batch_pullback_trend_compression_00"


def test_run_grid_persists_all_batches_summary_csv(tmp_path: Path) -> None:
    runner = DeterministicBatchRunner(execute_run=_ok_executor, storage_base=str(tmp_path))

    first = runner.run_grid(
        parameter_sets=[{"strategy_name": "pullback_trend_compression", "parameters": {}}],
        symbols=["2330.TW"],
        windows=[("2024-01-01", "2024-01-31")],
        batch_label="pullback_trend_compression",
    )
    second = runner.run_grid(
        parameter_sets=[{"strategy_name": "pullback_trend_compression", "parameters": {}}],
        symbols=["2317.TW"],
        windows=[("2024-02-01", "2024-02-29")],
        batch_label="pullback_trend_compression",
    )

    all_summary_path = tmp_path / "tw_quant" / "batch" / "all_batches_summary.csv"
    assert all_summary_path.exists()

    lines = all_summary_path.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("batch_id,strategy_name,start_date,end_date,total_return")
    assert any(first.batch_id in line for line in lines)
    assert any(second.batch_id in line for line in lines)
    assert any("ALL_BATCHES_SUMMARY" in line for line in lines)


@pytest.mark.parametrize(
    "parameter_sets,symbols,windows",
    [
        ([{"parameters": {"a": 1}}], ["2330.TW"], [("2024-01-01", "2024-01-31")]),
        ([{"strategy_name": "demo", "parameters": []}], ["2330.TW"], [("2024-01-01", "2024-01-31")]),
        ([{"strategy_name": "demo", "parameters": {"a": 1}}], ["AAPL"], [("2024-01-01", "2024-01-31")]),
        ([{"strategy_name": "demo", "parameters": {"a": 1}}], ["2330.TW"], [("2024-02-01", "2024-01-31")]),
        ([{"strategy_name": "demo", "parameters": {"a": 1}}], ["2330.TW"], ["2024-01-01"]),
    ],
)
def test_run_grid_static_pre_validation_rejects_malformed_inputs(
    parameter_sets, symbols, windows
) -> None:
    runner = DeterministicBatchRunner(execute_run=_ok_executor)

    with pytest.raises(ValueError):
        runner.run_grid(parameter_sets=parameter_sets, symbols=symbols, windows=windows)
