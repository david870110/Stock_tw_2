"""Deterministic batch orchestration for TW symbol backtests."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Protocol

from src.tw_quant.batch.interfaces import BatchCheckpointHook
from src.tw_quant.core.types import DateLike, Symbol
from src.tw_quant.schema.models import BacktestResult, BatchRunRecord, BatchRunResult


_TW_SYMBOL_PATTERN = re.compile(r"^\d{4,6}\.(TW|TWO)$", re.IGNORECASE)


class AtomicRunExecutor(Protocol):
    def __call__(
        self,
        symbol: Symbol,
        strategy_name: str,
        start: DateLike,
        end: DateLike,
        parameters: dict[str, Any],
        run_id: str,
        artifact_path: str,
    ) -> BacktestResult:
        """Execute one atomic run and return a BacktestResult."""


class BenchmarkCloseFetcher(Protocol):
    def __call__(self, symbol: Symbol, start: DateLike, end: DateLike) -> dict[str, float]:
        """Fetch benchmark close prices keyed by date string."""


@dataclass(slots=True)
class PlannedRun:
    symbol: Symbol
    strategy_name: str
    start: DateLike
    end: DateLike
    parameters: dict[str, Any]


def build_run_id(
    symbol: Symbol,
    strategy_name: str,
    start: DateLike,
    end: DateLike,
    parameters: dict[str, Any],
) -> str:
    payload = {
        "symbol": symbol,
        "strategy_name": strategy_name,
        "start": _normalize_date_like(start),
        "end": _normalize_date_like(end),
        "parameters": parameters,
    }
    digest = _canonical_hash(payload)
    return f"run_{digest[:16]}"


def build_batch_id(
    parameter_sets: list[dict[str, Any]],
    symbols: list[Symbol],
    windows: list[tuple[DateLike, DateLike]],
    batch_label: str | None = None,
) -> str:
    canonical_parameter_sets = [
        {
            "strategy_name": parameter_set["strategy_name"],
            "parameters": parameter_set["parameters"],
        }
        for parameter_set in parameter_sets
    ]

    canonical_parameter_sets_sorted = sorted(
        canonical_parameter_sets,
        key=_canonical_json,
    )
    windows_sorted = sorted(
        [(_normalize_date_like(start), _normalize_date_like(end)) for start, end in windows],
        key=lambda item: (item[0], item[1]),
    )

    payload: dict[str, Any] = {
        "parameter_sets": canonical_parameter_sets_sorted,
        "symbols": sorted(symbols),
        "windows": windows_sorted,
    }
    if batch_label is not None:
        payload["batch_label"] = batch_label

    digest = _canonical_hash(payload)
    return f"batch_{digest[:16]}"


def build_artifact_path(
    storage_base: str,
    batch_id: str,
    symbol: Symbol,
    strategy_name: str,
    start: DateLike,
    end: DateLike,
    run_id: str,
) -> str:
    normalized_base = storage_base.rstrip("/\\").replace("\\", "/")
    start_norm = _normalize_date_like(start)
    end_norm = _normalize_date_like(end)
    return (
        f"{normalized_base}/tw_quant/batch/{batch_id}/{symbol}/"
        f"{strategy_name}/{start_norm}_{end_norm}/{run_id}.json"
    )


class DeterministicBatchRunner:
    """Execute parameter/symbol/window grids with deterministic IDs and paths."""

    def __init__(
        self,
        execute_run: AtomicRunExecutor,
        storage_base: str = "artifacts",
        benchmark_symbol: Symbol | None = None,
        benchmark_close_fetcher: BenchmarkCloseFetcher | None = None,
    ) -> None:
        self._execute_run = execute_run
        self._storage_base = storage_base
        self._benchmark_symbol = benchmark_symbol
        self._benchmark_close_fetcher = benchmark_close_fetcher

    def run_grid(
        self,
        parameter_sets: list[dict[str, Any]],
        symbols: list[Symbol],
        windows: list[tuple[DateLike, DateLike]],
        checkpoint_hook: BatchCheckpointHook | None = None,
        batch_label: str | None = None,
    ) -> BatchRunResult:
        _validate_parameter_sets(parameter_sets)
        _validate_symbols(symbols)
        _validate_windows(windows)

        planned_runs = _build_planned_runs(parameter_sets, symbols, windows)
        batch_id = self._resolve_batch_id(
            parameter_sets=parameter_sets,
            symbols=symbols,
            windows=windows,
            batch_label=batch_label,
        )

        metadata: dict[str, Any] = {
            "batch_label": batch_label,
            "storage_base": self._storage_base,
            "planned_runs": len(planned_runs),
        }

        if checkpoint_hook is not None:
            checkpoint_hook.on_batch_start(batch_id, dict(metadata))

        successful_results: list[BacktestResult] = []
        run_records: list[BatchRunRecord] = []

        for planned in planned_runs:
            run_id = build_run_id(
                symbol=planned.symbol,
                strategy_name=planned.strategy_name,
                start=planned.start,
                end=planned.end,
                parameters=planned.parameters,
            )
            artifact_path = build_artifact_path(
                storage_base=self._storage_base,
                batch_id=batch_id,
                symbol=planned.symbol,
                strategy_name=planned.strategy_name,
                start=planned.start,
                end=planned.end,
                run_id=run_id,
            )

            try:
                result = self._execute_run(
                    symbol=planned.symbol,
                    strategy_name=planned.strategy_name,
                    start=planned.start,
                    end=planned.end,
                    parameters=planned.parameters,
                    run_id=run_id,
                    artifact_path=artifact_path,
                )
                successful_results.append(result)
                record = BatchRunRecord(
                    run_id=run_id,
                    symbol=planned.symbol,
                    strategy_name=planned.strategy_name,
                    start=planned.start,
                    end=planned.end,
                    status="SUCCESS",
                    artifact_path=artifact_path,
                    metadata={"parameters": dict(planned.parameters)},
                )
                run_records.append(record)
                if checkpoint_hook is not None:
                    checkpoint_hook.on_run_complete(batch_id, record, result)
            except Exception as exc:  # pragma: no cover - exercised by tests
                record = BatchRunRecord(
                    run_id=run_id,
                    symbol=planned.symbol,
                    strategy_name=planned.strategy_name,
                    start=planned.start,
                    end=planned.end,
                    status="FAILED",
                    artifact_path=artifact_path,
                    error_message=str(exc),
                    metadata={"parameters": dict(planned.parameters)},
                )
                run_records.append(record)
                if checkpoint_hook is not None:
                    checkpoint_hook.on_run_error(batch_id, record, exc)

        success_count = sum(1 for record in run_records if record.status == "SUCCESS")
        failed_count = sum(1 for record in run_records if record.status == "FAILED")

        result = BatchRunResult(
            batch_id=batch_id,
            run_count=len(planned_runs),
            results=successful_results,
            best_run_id=None,
            metadata=metadata,
            run_records=run_records,
            failed_count=failed_count,
            success_count=success_count,
        )
        _persist_batch_summary_csv(
            storage_base=self._storage_base,
            batch_id=batch_id,
            run_records=run_records,
            successful_results=successful_results,
        )
        _persist_user_backtest_csv_triplet(
            storage_base=self._storage_base,
            batch_id=batch_id,
            run_records=run_records,
            successful_results=successful_results,
            benchmark_symbol=self._benchmark_symbol,
            benchmark_close_fetcher=self._benchmark_close_fetcher,
        )
        _persist_all_batches_summary_csv(storage_base=self._storage_base)

        if checkpoint_hook is not None:
            checkpoint_hook.on_batch_end(batch_id, result)

        return result

    def _resolve_batch_id(
        self,
        *,
        parameter_sets: list[dict[str, Any]],
        symbols: list[Symbol],
        windows: list[tuple[DateLike, DateLike]],
        batch_label: str | None,
    ) -> str:
        if batch_label is None:
            return build_batch_id(parameter_sets, symbols, windows, batch_label=None)

        readable = _sanitize_batch_label(batch_label)
        batch_root = Path(self._storage_base) / "tw_quant" / "batch"
        prefix = f"batch_{readable}_"
        pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")

        max_index = -1
        if batch_root.exists():
            for child in batch_root.iterdir():
                if not child.is_dir():
                    continue
                matched = pattern.match(child.name)
                if matched is None:
                    continue
                max_index = max(max_index, int(matched.group(1)))

        next_index = max_index + 1
        return f"{prefix}{next_index:02d}"


def _sanitize_batch_label(label: str) -> str:
    lowered = label.strip().lower().replace(" ", "_")
    compact = re.sub(r"[^a-z0-9_]+", "_", lowered)
    compact = re.sub(r"_+", "_", compact).strip("_")
    return compact or "strategy"


def _persist_batch_summary_csv(
    *,
    storage_base: str,
    batch_id: str,
    run_records: list[BatchRunRecord],
    successful_results: list[BacktestResult],
) -> None:
    metrics_by_run_id = {item.run_id: dict(item.metrics) for item in successful_results}
    metric_names: list[str] = sorted({name for item in successful_results for name in item.metrics.keys()})

    summary_path = Path(storage_base) / "tw_quant" / "batch" / batch_id / "batch_summary.csv"
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    fields = [
        "run_id",
        "symbol",
        "strategy_name",
        "start",
        "end",
        "status",
        "error_message",
        "total_return_pct",
        "artifact_path",
        *metric_names,
    ]
    rows: list[dict[str, Any]] = []
    for record in run_records:
        metrics = metrics_by_run_id.get(record.run_id, {})
        raw_return = metrics.get("total_return")
        total_return_pct = f"{raw_return * 100:.2f}" if isinstance(raw_return, (int, float)) else ""
        rows.append(
            {
                "run_id": record.run_id,
                "symbol": record.symbol,
                "strategy_name": record.strategy_name,
                "start": _normalize_date_like(record.start),
                "end": _normalize_date_like(record.end),
                "status": record.status,
                "error_message": record.error_message or "",
                "total_return_pct": total_return_pct,
                "artifact_path": record.artifact_path,
                **metrics,
            }
        )

    returns = _collect_summary_returns(successful_results)
    trade_return_sum = _collect_trade_return_pct_sum(successful_results)
    success_count = len(returns)
    win_count = sum(1 for r in returns if r > 0)
    loss_count = sum(1 for r in returns if r < 0)
    avg_return = (sum(returns) / success_count) if success_count > 0 else None
    best_return = max(returns) if returns else None
    worst_return = min(returns) if returns else None

    def _fmt_pct(v: float | None) -> str:
        return f"{v * 100:.2f}" if isinstance(v, (int, float)) else ""

    summary_row: dict[str, Any] = {
        "run_id": "BATCH_SUMMARY",
        "symbol": f"total={len(run_records)} success={success_count} win={win_count} loss={loss_count}",
        "strategy_name": "",
        "start": "",
        "end": "",
        "status": "SUMMARY",
        "error_message": "",
        "total_return_pct": _fmt_pct(trade_return_sum),
        "artifact_path": str(summary_path),
        **{name: "" for name in metric_names},
        "total_return": trade_return_sum,
    }
    for name in metric_names:
        if name == "total_return":
            summary_row[name] = trade_return_sum
    summary_row["error_message"] = (
        f"trade_sum={_fmt_pct(trade_return_sum)}% avg={_fmt_pct(avg_return)}% best={_fmt_pct(best_return)}% worst={_fmt_pct(worst_return)}%"
        f" win_rate={f'{win_count / success_count * 100:.1f}' if success_count > 0 else 'N/A'}%"
    )

    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        writer.writerow(summary_row)


def _persist_user_backtest_csv_triplet(
    *,
    storage_base: str,
    batch_id: str,
    run_records: list[BatchRunRecord],
    successful_results: list[BacktestResult],
    benchmark_symbol: Symbol | None = None,
    benchmark_close_fetcher: BenchmarkCloseFetcher | None = None,
) -> None:
    batch_dir = Path(storage_base) / "tw_quant" / "batch" / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)

    trades_path = batch_dir / "backtest_trades.csv"
    equity_path = batch_dir / "backtest_equity.csv"
    summary_path = batch_dir / "backtest_summary.csv"

    trade_fields = [
        "stock_id",
        "stock_name",
        "signal_date",
        "entry_date",
        "entry_price",
        "exit_date",
        "exit_price",
        "holding_days",
        "exit_reason",
        "return_pct",
        "exit_fraction",
        "exit_shares",
        "is_partial_exit",
    ]
    trade_rows: list[dict[str, Any]] = []
    for result in successful_results:
        for raw in result.trades:
            row = {field: raw.get(field, "") for field in trade_fields}
            trade_rows.append(row)

    with trades_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=trade_fields)
        writer.writeheader()
        writer.writerows(trade_rows)

    equity_fields = ["date", "equity", "pos_count", "bench_equity"]
    equity_aggregate: dict[str, dict[str, float]] = {}
    for result in successful_results:
        for point in result.equity_curve:
            date_key = str(point.get("date", ""))
            if not date_key:
                continue
            slot = equity_aggregate.setdefault(
                date_key,
                {"equity_sum": 0.0, "equity_count": 0.0, "pos_sum": 0.0},
            )
            equity_value = point.get("equity")
            if isinstance(equity_value, (int, float)):
                slot["equity_sum"] += float(equity_value)
                slot["equity_count"] += 1.0
            pos_count = point.get("pos_count")
            if isinstance(pos_count, (int, float)):
                slot["pos_sum"] += float(pos_count)

    equity_rows: list[dict[str, Any]] = []
    sorted_equity_dates = sorted(equity_aggregate.keys())
    for date_key in sorted_equity_dates:
        values = equity_aggregate[date_key]
        denominator = values["equity_count"] if values["equity_count"] > 0.0 else 1.0
        equity_rows.append(
            {
                "date": date_key,
                "equity": values["equity_sum"] / denominator,
                "pos_count": int(round(values["pos_sum"])),
                "bench_equity": "",
            }
        )

    benchmark_return: float | str = ""
    benchmark_equity_by_date: dict[str, float] = {}
    if benchmark_symbol and benchmark_close_fetcher and run_records:
        starts = [_normalize_date_like(record.start) for record in run_records]
        ends = [_normalize_date_like(record.end) for record in run_records]
        benchmark_start = min(starts) if starts else ""
        benchmark_end = max(ends) if ends else ""
        if benchmark_start and benchmark_end:
            try:
                benchmark_closes = benchmark_close_fetcher(benchmark_symbol, benchmark_start, benchmark_end)
            except Exception:
                benchmark_closes = {}

            benchmark_equity_by_date, benchmark_return = _build_buy_and_hold_benchmark(
                equity_dates=sorted_equity_dates,
                benchmark_closes=benchmark_closes,
            )

    for row in equity_rows:
        date_key = str(row.get("date", ""))
        if date_key in benchmark_equity_by_date:
            row["bench_equity"] = benchmark_equity_by_date[date_key]

    with equity_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=equity_fields)
        writer.writeheader()
        writer.writerows(equity_rows)

    successful_records = [record for record in run_records if record.status == "SUCCESS"]
    successful_symbols = sorted({record.symbol for record in successful_records})
    all_symbols = sorted({record.symbol for record in run_records})
    total_return = _collect_trade_return_pct_sum(successful_results)

    starts = [_normalize_date_like(record.start) for record in run_records]
    ends = [_normalize_date_like(record.end) for record in run_records]
    start_date = min(starts) if starts else ""
    end_date = max(ends) if ends else ""

    exit_rule_description = ""
    for record in successful_records:
        exits = record.metadata.get("parameters", {}).get("exits")
        if isinstance(exits, dict) and exits:
            exit_rule_description = json.dumps(exits, ensure_ascii=False, separators=(",", ":"))
            break

    summary_row = {
        "start_date": start_date,
        "end_date": end_date,
        "entry_conditions": "",
        "exit_rules": exit_rule_description,
        "total_return": total_return,
        "bench_return": benchmark_return,
        "end_equity": 1.0 + total_return,
        "stocks_used": len(successful_symbols),
        "universe_size": len(all_symbols),
        "max_pos": "",
        "cooldown_days": "",
        "ckpt_enable": "",
        "ckpt_resume": "",
        "ckpt_dir": "",
        "require_full_signals": "",
        "error_top_n": "",
    }

    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary_row.keys()))
        writer.writeheader()
        writer.writerow(summary_row)


def _collect_summary_returns(successful_results: list[BacktestResult]) -> list[float]:
    traded_returns: list[float] = []
    all_returns: list[float] = []

    for result in successful_results:
        raw_return = result.metrics.get("total_return")
        if not isinstance(raw_return, (int, float)):
            continue

        normalized_return = float(raw_return)
        all_returns.append(normalized_return)

        raw_num_trades = result.metrics.get("num_trades")
        num_trades = float(raw_num_trades) if isinstance(raw_num_trades, (int, float)) else 0.0
        if num_trades > 0.0:
            traded_returns.append(normalized_return)

    return traded_returns if traded_returns else all_returns


def _collect_trade_return_pct_sum(successful_results: list[BacktestResult]) -> float:
    total_return_pct = 0.0

    for result in successful_results:
        for raw_trade in result.trades:
            raw_value = raw_trade.get("return_pct") if isinstance(raw_trade, dict) else None
            if isinstance(raw_value, (int, float)):
                total_return_pct += float(raw_value)
                continue
            if isinstance(raw_value, str):
                text = raw_value.strip()
                if not text:
                    continue
                try:
                    total_return_pct += float(text)
                except ValueError:
                    continue

    return total_return_pct


def _persist_all_batches_summary_csv(*, storage_base: str) -> None:
    batch_root = Path(storage_base) / "tw_quant" / "batch"
    batch_root.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "batch_id",
        "strategy_name",
        "start_date",
        "end_date",
        "total_return",
        "end_equity",
        "stocks_used",
        "universe_size",
        "success_count",
        "failed_count",
        "backtest_summary_path",
        "batch_summary_path",
    ]

    rows: list[dict[str, Any]] = []
    for child in sorted(batch_root.iterdir(), key=lambda item: item.name):
        if not child.is_dir():
            continue

        backtest_summary_path = child / "backtest_summary.csv"
        batch_summary_path = child / "batch_summary.csv"
        if not backtest_summary_path.exists():
            continue

        with backtest_summary_path.open("r", encoding="utf-8", newline="") as handle:
            backtest_rows = list(csv.DictReader(handle))
        if not backtest_rows:
            continue
        backtest_row = backtest_rows[0]

        success_count = 0
        failed_count = 0
        strategy_name = ""
        if batch_summary_path.exists():
            with batch_summary_path.open("r", encoding="utf-8", newline="") as handle:
                per_run_rows = list(csv.DictReader(handle))
            for row in per_run_rows:
                if row.get("status") == "SUCCESS":
                    success_count += 1
                    if not strategy_name:
                        strategy_name = row.get("strategy_name", "")
                elif row.get("status") == "FAILED":
                    failed_count += 1

        row = {
            "batch_id": child.name,
            "strategy_name": strategy_name,
            "start_date": backtest_row.get("start_date", ""),
            "end_date": backtest_row.get("end_date", ""),
            "total_return": backtest_row.get("total_return", ""),
            "end_equity": backtest_row.get("end_equity", ""),
            "stocks_used": backtest_row.get("stocks_used", ""),
            "universe_size": backtest_row.get("universe_size", ""),
            "success_count": success_count,
            "failed_count": failed_count,
            "backtest_summary_path": str(backtest_summary_path),
            "batch_summary_path": str(batch_summary_path) if batch_summary_path.exists() else "",
        }
        rows.append(row)

    summary_path = batch_root / "all_batches_summary.csv"

    total_batches = len(rows)
    total_success = 0
    total_failed = 0
    sum_total_return = 0.0
    sum_end_equity = 0.0
    sum_stocks_used = 0.0
    sum_universe_size = 0.0
    for row in rows:
        total_success += int(row["success_count"])
        total_failed += int(row["failed_count"])
        try:
            sum_total_return += float(row["total_return"])
        except (TypeError, ValueError):
            pass
        try:
            sum_end_equity += float(row["end_equity"])
        except (TypeError, ValueError):
            pass
        try:
            sum_stocks_used += float(row["stocks_used"])
        except (TypeError, ValueError):
            pass
        try:
            sum_universe_size += float(row["universe_size"])
        except (TypeError, ValueError):
            pass

    total_row = {
        "batch_id": "ALL_BATCHES_SUMMARY",
        "strategy_name": "",
        "start_date": "",
        "end_date": "",
        "total_return": sum_total_return,
        "end_equity": sum_end_equity,
        "stocks_used": int(sum_stocks_used),
        "universe_size": int(sum_universe_size),
        "success_count": total_success,
        "failed_count": total_failed,
        "backtest_summary_path": f"batch_count={total_batches}",
        "batch_summary_path": "",
    }

    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        writer.writerow(total_row)


def _build_planned_runs(
    parameter_sets: list[dict[str, Any]],
    symbols: list[Symbol],
    windows: list[tuple[DateLike, DateLike]],
) -> list[PlannedRun]:
    planned: list[PlannedRun] = []
    for parameter_set in parameter_sets:
        strategy_name = parameter_set["strategy_name"]
        parameters = parameter_set["parameters"]
        for symbol in symbols:
            for start, end in windows:
                planned.append(
                    PlannedRun(
                        symbol=symbol,
                        strategy_name=strategy_name,
                        start=start,
                        end=end,
                        parameters=parameters,
                    )
                )
    return planned


def _validate_parameter_sets(parameter_sets: list[dict[str, Any]]) -> None:
    if not parameter_sets:
        raise ValueError("parameter_sets must be a non-empty list")

    for index, parameter_set in enumerate(parameter_sets):
        if not isinstance(parameter_set, dict):
            raise ValueError(f"parameter_set[{index}] must be a dict")
        strategy_name = parameter_set.get("strategy_name")
        parameters = parameter_set.get("parameters")
        if not isinstance(strategy_name, str) or not strategy_name.strip():
            raise ValueError(f"parameter_set[{index}].strategy_name must be a non-empty string")
        if not isinstance(parameters, dict):
            raise ValueError(f"parameter_set[{index}].parameters must be a dict")


def _validate_symbols(symbols: list[Symbol]) -> None:
    if not symbols:
        raise ValueError("symbols must be a non-empty list")

    for index, symbol in enumerate(symbols):
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError(f"symbols[{index}] must be a non-empty string")
        if _TW_SYMBOL_PATTERN.match(symbol) is None:
            raise ValueError(
                (
                    f"symbols[{index}] must be a Taiwan stock symbol in "
                    "####.TW, ######.TW, ####.TWO, or ######.TWO format"
                )
            )


def _validate_windows(windows: list[tuple[DateLike, DateLike]]) -> None:
    if not windows:
        raise ValueError("windows must be a non-empty list")

    for index, window in enumerate(windows):
        if not isinstance(window, (tuple, list)) or len(window) != 2:
            raise ValueError(f"windows[{index}] must be a two-item (start, end) tuple")
        start, end = window
        if _normalize_for_ordering(start) > _normalize_for_ordering(end):
            raise ValueError(f"windows[{index}] start must be <= end")


def _normalize_date_like(value: DateLike) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _normalize_for_ordering(value: DateLike) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    if not isinstance(value, str):
        raise ValueError(f"DateLike value must be date, datetime, or ISO string: {value!r}")

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        try:
            return datetime.combine(date.fromisoformat(value), time.min)
        except ValueError as exc:
            raise ValueError(f"DateLike string must be ISO date/datetime: {value!r}") from exc


def _build_buy_and_hold_benchmark(
    *,
    equity_dates: list[str],
    benchmark_closes: dict[str, float],
) -> tuple[dict[str, float], float | str]:
    if not equity_dates or not benchmark_closes:
        return {}, ""

    normalized_close_by_date: dict[str, float] = {}
    for raw_date, raw_close in benchmark_closes.items():
        if not isinstance(raw_close, (int, float)):
            continue
        normalized_date = _coerce_iso_date(raw_date)
        normalized_close_by_date[normalized_date] = float(raw_close)

    if not normalized_close_by_date:
        return {}, ""

    benchmark_equity_by_date: dict[str, float] = {}
    base_close: float | None = None
    last_close: float | None = None

    for date_key in equity_dates:
        normalized_date = _coerce_iso_date(date_key)
        close = normalized_close_by_date.get(normalized_date)
        if close is not None:
            if base_close is None:
                base_close = close
            last_close = close

        if base_close is None or last_close is None:
            continue
        if base_close == 0.0:
            continue
        benchmark_equity_by_date[date_key] = last_close / base_close

    if not benchmark_equity_by_date:
        return {}, ""

    final_equity = next(reversed(benchmark_equity_by_date.values()))
    return benchmark_equity_by_date, final_equity - 1.0


def _coerce_iso_date(value: DateLike) -> str:
    if isinstance(value, str):
        raw = value.strip()
    else:
        raw = str(value)
    if not raw:
        return ""
    try:
        return _normalize_for_ordering(raw).date().isoformat()
    except ValueError:
        return raw


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _canonical_hash(value: Any) -> str:
    canonical = _canonical_json(value)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
