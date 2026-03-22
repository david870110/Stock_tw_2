"""CLI entrypoints for tw_quant backtest batch and daily selection."""

from __future__ import annotations

import argparse
import calendar
import csv
import json
import pathlib
from datetime import date, datetime, timedelta
from typing import Any

import yaml

from src.tw_quant.batch import DeterministicBatchRunner
from src.tw_quant.batch.interfaces import BatchCheckpointHook
from src.tw_quant.config.models import (
    AppConfig,
    BacktestConfig,
    BacktestExitConfig,
    BacktestStrategyDefaults,
    DataConfig,
    ReportingConfig,
    StorageConfig,
)
from src.tw_quant.reporting.csv_image import write_csv_preview_image
from src.tw_quant.schema.models import BacktestResult, BatchRunRecord, BatchRunResult
from src.tw_quant.selection.pipeline import SelectionConfig
from src.tw_quant.universe.interfaces import UniverseProvider
from src.tw_quant.universe.models import ListingStatus, UniverseEntry
from src.tw_quant.universe.providers import normalize_tw_symbol
from src.tw_quant.wiring.container import build_app_context
from src.tw_quant.workflows import AtomicBacktestExecutor, DailySelectionRunner, build_stock_report

_CONFIG_PATH = pathlib.Path(__file__).parent.parent.parent / "configs" / "quant" / "default.yaml"
_YFINANCE_UNSUPPORTED_SYMBOLS_PATH = _CONFIG_PATH.parent / "yfinance_unsupported_symbols.txt"


def _load_config(path: pathlib.Path = _CONFIG_PATH) -> AppConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    d = raw.get("data", {})
    s = raw.get("storage", {})
    b = raw.get("backtest", {})
    r = raw.get("reporting", {})
    a = raw.get("app", {})
    strategy_examples = raw.get("strategy_examples", {})
    return AppConfig(
        data=DataConfig(
            wiring_mode=d.get("wiring_mode", "placeholder"),
            market_provider=d.get("market_provider", "stub_market"),
            universe_provider=d.get("universe_provider", "stub_universe"),
            universe_csv_path=d.get("universe_csv_path", ""),
            market_ohlcv_url_template=d.get("market_ohlcv_url_template", ""),
            universe_twse_url=d.get("universe_twse_url", ""),
            universe_tpex_url=d.get("universe_tpex_url", ""),
            timeout_seconds=float(d.get("timeout_seconds", 10.0)),
            max_retries=int(d.get("max_retries", 2)),
            retry_backoff_seconds=float(d.get("retry_backoff_seconds", 0.25)),
            min_interval_seconds=float(d.get("min_interval_seconds", 0.3)),
            batch_size=int(d.get("batch_size", 20)),
        ),
        storage=StorageConfig(
            raw_store=s.get("raw_store", "memory"),
            canonical_store=s.get("canonical_store", "memory"),
            artifact_store=s.get("artifact_store", "local"),
            base_path=s.get("base_path", "./artifacts"),
        ),
        backtest=BacktestConfig(
            initial_cash=float(b.get("initial_cash", 1_000_000.0)),
            commission_bps=float(b.get("commission_bps", 0.0)),
            slippage_bps=float(b.get("slippage_bps", 0.0)),
            benchmark=b.get("benchmark", "TAIEX"),
            timezone=b.get("timezone", "Asia/Taipei"),
            strategy_defaults=_load_backtest_strategy_defaults(strategy_examples),
        ),
        reporting=ReportingConfig(
            output_dir=r.get("output_dir", "./reports"),
            formats=r.get("formats", ["json"]),
        ),
        timezone=a.get("timezone", "Asia/Taipei"),
    )


def _load_backtest_strategy_defaults(raw_examples: object) -> dict[str, BacktestStrategyDefaults]:
    if not isinstance(raw_examples, dict):
        return {}

    strategy_defaults: dict[str, BacktestStrategyDefaults] = {}
    for strategy_name, raw_strategy in raw_examples.items():
        if not isinstance(strategy_name, str) or not isinstance(raw_strategy, dict):
            continue

        exits = raw_strategy.get("exits", {})
        if not isinstance(exits, dict):
            exits = {}

        strategy_defaults[strategy_name.strip().lower()] = BacktestStrategyDefaults(
            exits=BacktestExitConfig(
                stop_loss_pct=_optional_float(exits.get("stop_loss_pct")),
                take_profit_pct=_optional_float(exits.get("take_profit_pct")),
                max_holding_days=_optional_int(exits.get("max_holding_days")),
            )
        )

    return strategy_defaults


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="tw_quant workflow runner")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backtest = subparsers.add_parser("backtest-batch", help="Run deterministic batch backtest")
    symbol_source = backtest.add_mutually_exclusive_group(required=True)
    symbol_source.add_argument("--symbols", nargs="+")
    symbol_source.add_argument("--symbols-file", help="Path to newline-delimited symbols file")
    backtest.add_argument("--start", required=True)
    backtest.add_argument("--end", required=True)
    backtest.add_argument("--strategy", default="pullback_trend_compression")
    backtest.add_argument("--batch-label", default="", help="Optional unique batch folder label")
    backtest.add_argument("--params", default="{}", help="JSON string for strategy parameters")
    backtest.add_argument("--show-progress", action="store_true", help="Show backtest progress")
    backtest.add_argument("--progress-step", type=int, default=0, help="Progress update step by run count; 0 uses auto")

    daily = subparsers.add_parser("daily-selection", help="Run daily selection")
    daily_mode = daily.add_mutually_exclusive_group(required=True)
    daily_mode.add_argument("--as-of", help="Single-day selection date (YYYY-MM-DD)")
    daily_mode.add_argument("--start", help="Range start date (YYYY-MM-DD)")
    daily.add_argument("--end", default=None, help="Range end date (YYYY-MM-DD), required when --start is set")
    daily.add_argument("--strategy", default="pullback_trend_compression")
    daily.add_argument("--output-csv", default=None, help="Optional output path for date-range aggregated CSV")
    daily.add_argument("--workers", type=int, default=1, help="Parallel worker count for per-day symbol evaluation")
    daily.add_argument("--show-progress", action="store_true", help="Show progress for daily selection runs")
    daily.add_argument(
        "--missing-history-threshold",
        type=float,
        default=0.2,
        help="Fail when missing_history_count / universe_size exceeds this ratio; use a negative value to disable",
    )
    daily.add_argument("--top-n", type=int, default=30)
    daily.add_argument(
        "--max-symbols",
        type=int,
        default=None,
        help="Optional max symbols to evaluate (e.g. 100) when universe is large",
    )
    daily.add_argument(
        "--symbols",
        nargs="+",
        default=None,
        help="Optional symbol subset (e.g. 2330.TW 2317.TW) to avoid full-market fetch",
    )
    stock_report = subparsers.add_parser("stock-report", help="Export a single-stock report over a date range")
    stock_report.add_argument("--symbol", required=True, help="Target stock symbol (e.g. 2330 or 2330.TW)")
    stock_report.add_argument("--start", required=True, help="Range start date (YYYY-MM-DD)")
    stock_report.add_argument("--end", required=True, help="Range end date (YYYY-MM-DD)")
    stock_report.add_argument("--output-csv", default=None, help="Optional output path for row-level CSV export")

    forward_report = subparsers.add_parser(
        "selection-forward-report",
        help="Project selected daily-selection symbols forward and report later close/return",
    )
    forward_report.add_argument(
        "--selection-csv",
        required=True,
        help="Path to a repository daily-selection CSV artifact",
    )
    forward_window = forward_report.add_mutually_exclusive_group(required=True)
    forward_window.add_argument("--forward-months", type=int, default=None, help="Calendar months to project forward")
    forward_window.add_argument("--forward-days", type=int, default=None, help="Calendar days to project forward")
    forward_report.add_argument("--output-csv", default=None, help="Optional output path for row-level CSV export")

    args = parser.parse_args()

    if args.command == "backtest-batch":
        _run_backtest_batch(args)
        return
    if args.command == "stock-report":
        _run_stock_report(args)
        return
    if args.command == "selection-forward-report":
        _run_selection_forward_report(args)
        return
    _run_daily_selection(args)


def _run_backtest_batch(args: argparse.Namespace) -> None:
    params = _parse_backtest_params(args.params)
    symbols = _resolve_backtest_symbols(args)
    config = _load_config()
    ctx = build_app_context(config)
    executor = AtomicBacktestExecutor(
        market_data_provider=ctx.market_data_provider,
        backtest_config=config.backtest,
    )

    def _fetch_benchmark_closes(symbol: str, start: str, end: str) -> dict[str, float]:
        bars = ctx.market_data_provider.fetch_ohlcv([symbol], start, end)
        closes: dict[str, float] = {}
        for bar in bars:
            if str(bar.symbol).upper() != symbol.upper():
                continue
            date_text = str(bar.date)
            closes[date_text] = float(bar.close)
        return closes

    runner = DeterministicBatchRunner(
        execute_run=executor,
        benchmark_symbol="2330.TW",
        benchmark_close_fetcher=_fetch_benchmark_closes,
    )
    checkpoint_hook: BatchCheckpointHook | None = None
    if bool(args.show_progress):
        checkpoint_hook = _CliBatchProgressHook(step=max(0, int(args.progress_step)))

    result = runner.run_grid(
        parameter_sets=[{"strategy_name": args.strategy, "parameters": params}],
        symbols=symbols,
        windows=[(args.start, args.end)],
        checkpoint_hook=checkpoint_hook,
        batch_label=(str(args.batch_label).strip() or args.strategy),
    )
    print(json.dumps({
        "batch_id": result.batch_id,
        "run_count": result.run_count,
        "success_count": result.success_count,
        "failed_count": result.failed_count,
    }, indent=2, ensure_ascii=False))


def _resolve_backtest_symbols(args: argparse.Namespace) -> list[str]:
    if getattr(args, "symbols", None) is not None:
        symbols = [str(symbol).strip() for symbol in args.symbols if str(symbol).strip()]
    else:
        raw_path = getattr(args, "symbols_file", None)
        if not raw_path:
            raise SystemExit("Either --symbols or --symbols-file is required.")
        path = pathlib.Path(str(raw_path)).expanduser()
        if not path.exists():
            raise SystemExit(f"Symbols file not found: {path}")
        symbols = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    if not symbols:
        raise SystemExit("No symbols provided.")
    return symbols


class _CliBatchProgressHook:
    def __init__(self, step: int = 0) -> None:
        self._requested_step = max(0, step)
        self._total = 0
        self._done = 0
        self._step = 1
        self._next_mark = 1
        self._bar: Any = None

    def on_batch_start(self, batch_id: str, metadata: dict[str, Any]) -> None:
        self._total = int(metadata.get("planned_runs", 0) or 0)
        auto_step = max(1, self._total // 50) if self._total > 0 else 1
        self._step = self._requested_step if self._requested_step > 0 else auto_step
        self._next_mark = self._step
        try:
            from tqdm import tqdm

            self._bar = tqdm(total=self._total, desc="Backtest", unit="run", miniters=self._step)
        except Exception:
            self._bar = None
            print(f"Progress: 0% (0/{self._total} runs)")

    def on_run_complete(self, batch_id: str, record: BatchRunRecord, result: BacktestResult) -> None:
        self._advance()

    def on_run_error(self, batch_id: str, record: BatchRunRecord, error: Exception) -> None:
        self._advance()

    def on_batch_end(self, batch_id: str, result: BatchRunResult) -> None:
        if self._bar is not None:
            remaining = self._total - self._done
            if remaining > 0:
                self._bar.update(remaining)
                self._done = self._total
            self._bar.close()
            return

        if self._total > 0 and self._done < self._total:
            print(f"Progress: 100% ({self._total}/{self._total} runs)")

    def _advance(self) -> None:
        self._done += 1
        if self._bar is not None:
            self._bar.update(1)
            return

        while self._done >= self._next_mark and self._next_mark <= self._total:
            percent = min(100, int((self._next_mark / self._total) * 100)) if self._total > 0 else 100
            print(f"Progress: {percent}% ({self._next_mark}/{self._total} runs)")
            self._next_mark += self._step


def _parse_backtest_params(raw_params: str) -> dict[str, object]:
    raw = raw_params.strip()
    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    else:
        if not isinstance(parsed, dict):
            raise SystemExit("Invalid --params: expected a JSON object.")
        return _normalize_backtest_params(parsed)

    try:
        yaml_parsed = yaml.safe_load(raw)
    except yaml.YAMLError:
        yaml_parsed = None
    else:
        if isinstance(yaml_parsed, dict) and _is_valid_params_mapping(yaml_parsed):
            return _normalize_backtest_params(yaml_parsed)

    loose = _parse_loose_mapping(raw)
    if loose is not None:
        return _normalize_backtest_params(loose)

    raise SystemExit(
        "Invalid --params. Use JSON like '{\"short\":60,\"mid\":120,\"long\":200}' "
        "or loose mapping like '{short:60,mid:120,long:200}'."
    )


def _is_valid_params_mapping(value: dict[object, object]) -> bool:
    return all(
        isinstance(key, str)
        and not (mapped_value is None and ":" in key)
        for key, mapped_value in value.items()
    )


def _parse_loose_mapping(raw: str) -> dict[str, object] | None:
    if not (raw.startswith("{") and raw.endswith("}")):
        return None

    body = raw[1:-1].strip()
    if not body:
        return {}

    pairs = [segment.strip() for segment in body.split(",") if segment.strip()]
    result: dict[str, object] = {}
    for pair in pairs:
        if ":" not in pair:
            return None
        key_raw, value_raw = pair.split(":", 1)
        key = key_raw.strip().strip("\"'")
        if not key:
            return None
        value_text = value_raw.strip()
        try:
            value = yaml.safe_load(value_text)
        except yaml.YAMLError:
            value = value_text.strip("\"'")
        result[key] = value

    return result


def _normalize_backtest_params(params: dict[str, object]) -> dict[str, object]:
    normalized = dict(params)
    exits = normalized.get("exits")
    if not isinstance(exits, dict):
        return normalized

    repaired_exits: dict[str, object] = {}
    for key, value in exits.items():
        if not isinstance(key, str):
            repaired_exits[key] = value
            continue

        if value is None and ":" in key:
            name, candidate = key.split(":", 1)
            normalized_name = name.strip()
            parsed_candidate = _parse_scalar_text(candidate.strip())
            if normalized_name:
                repaired_exits[normalized_name] = parsed_candidate
                continue

        repaired_exits[key] = value

    normalized["exits"] = repaired_exits
    return normalized


def _parse_scalar_text(raw: str) -> object:
    if raw == "":
        return ""
    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError:
        return raw
    return parsed


def _run_daily_selection(args: argparse.Namespace) -> None:
    execution_dates = _resolve_daily_selection_dates(args)
    config = _load_config()
    ctx = build_app_context(config)
    universe_provider = ctx.universe_provider
    yfinance_unsupported_symbols = _load_excluded_symbols(
        _YFINANCE_UNSUPPORTED_SYMBOLS_PATH if _uses_yfinance_provider(config) else None
    )
    if yfinance_unsupported_symbols:
        universe_provider = _ExcludedUniverseProvider(
            base_provider=universe_provider,
            excluded_symbols=yfinance_unsupported_symbols,
        )
    if args.symbols:
        selected = list(args.symbols)
        if args.max_symbols is not None:
            selected = selected[: max(args.max_symbols, 1)]
        universe_provider = _StaticUniverseProvider(symbols=selected)
    elif args.max_symbols is not None:
        universe_provider = _LimitedUniverseProvider(
            base_provider=universe_provider,
            max_symbols=max(args.max_symbols, 1),
        )
    runner = DailySelectionRunner(
        universe_provider=universe_provider,
        market_data_provider=ctx.market_data_provider,
        app_config=config,
    )
    selection_config = SelectionConfig(top_n=max(args.top_n, 1), signal_type_whitelist=["buy"], min_score=0.0)
    symbol_name_map = _resolve_symbol_names(universe_provider=universe_provider, as_of=execution_dates[-1])

    if len(execution_dates) == 1 and getattr(args, "as_of", None):
        selections = runner.run(
            as_of=execution_dates[0],
            strategy_name=args.strategy,
            selection_config=selection_config,
            max_workers=max(1, int(getattr(args, "workers", 1))),
            show_progress=bool(getattr(args, "show_progress", False)),
            progress_label=f"Daily Selection {execution_dates[0].isoformat()}",
        )
        _raise_if_missing_history_ratio_exceeded(
            run_summary=dict(getattr(runner, "last_run_summary", {}) or {}),
            threshold=_resolve_missing_history_threshold(args),
        )
        selection_rows = _attach_stock_names_to_selection_rows(
            rows=_resolve_runner_selection_rows(runner=runner, selections=selections),
            symbol_name_map=symbol_name_map,
        )
        print(json.dumps(selection_rows, indent=2, ensure_ascii=False))
        return

    symbol_stats: dict[str, dict[str, Any]] = {}
    for current_date in execution_dates:
        selections = runner.run(
            as_of=current_date,
            strategy_name=args.strategy,
            selection_config=selection_config,
            max_workers=max(1, int(getattr(args, "workers", 1))),
            show_progress=bool(getattr(args, "show_progress", False)),
            progress_label=f"Daily Selection {current_date.isoformat()}",
        )
        _raise_if_missing_history_ratio_exceeded(
            run_summary=dict(getattr(runner, "last_run_summary", {}) or {}),
            threshold=_resolve_missing_history_threshold(args),
        )
        selection_rows = _attach_stock_names_to_selection_rows(
            rows=_resolve_runner_selection_rows(runner=runner, selections=selections),
            symbol_name_map=symbol_name_map,
        )
        for row in selection_rows:
            symbol = str(row.get("symbol", "")).strip()
            if not symbol:
                continue
            stat = symbol_stats.get(symbol)
            if stat is None:
                symbol_stats[symbol] = {
                    "symbol": symbol,
                    "stock_name": str(row.get("stock_name", "")),
                    "first_matched_date": current_date.isoformat(),
                    "last_matched_date": current_date.isoformat(),
                    "matched_days": 1,
                    "latest_signal": row.get("signal", ""),
                    "latest_score": row.get("score", ""),
                    "latest_criteria": dict(row.get("criteria", {}) or {}),
                    "criteria_history": [{
                        "date": current_date.isoformat(),
                        "signal": row.get("signal", ""),
                        "score": row.get("score", ""),
                        "criteria": dict(row.get("criteria", {}) or {}),
                    }],
                }
                continue
            stat["last_matched_date"] = current_date.isoformat()
            stat["matched_days"] = int(stat["matched_days"]) + 1
            stat["latest_signal"] = row.get("signal", "")
            stat["latest_score"] = row.get("score", "")
            stat["latest_criteria"] = dict(row.get("criteria", {}) or {})
            stat.setdefault("criteria_history", []).append({
                "date": current_date.isoformat(),
                "signal": row.get("signal", ""),
                "score": row.get("score", ""),
                "criteria": dict(row.get("criteria", {}) or {}),
            })

    aggregated = sorted(
        symbol_stats.values(),
        key=lambda item: (-int(item["matched_days"]), str(item["symbol"])),
    )
    output_csv_path = None
    if getattr(args, "output_csv", None):
        output_csv_path = _write_daily_selection_range_csv(
            output_path=str(args.output_csv),
            rows=aggregated,
        )

    print(json.dumps({
        "mode": "date_range",
        "strategy": args.strategy,
        "start": execution_dates[0].isoformat(),
        "end": execution_dates[-1].isoformat(),
        "day_count": len(execution_dates),
        "selected_symbol_count": len(aggregated),
        "output_csv": output_csv_path,
        "selections": aggregated,
    }, indent=2, ensure_ascii=False))


def _run_stock_report(args: argparse.Namespace) -> None:
    start_date, end_date = _resolve_stock_report_dates(args)
    resolved_symbol = _resolve_stock_report_symbol(str(getattr(args, "symbol", "")))
    config = _load_config()
    ctx = build_app_context(config)
    if ctx.market_data_provider is None:
        raise SystemExit("Market data provider is not configured for stock-report.")

    try:
        report = build_stock_report(
            symbol=resolved_symbol,
            start=start_date,
            end=end_date,
            market_data_provider=ctx.market_data_provider,
            universe_provider=ctx.universe_provider,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    report["requested_symbol"] = str(getattr(args, "symbol", "")).strip()
    report["resolved_symbol"] = resolved_symbol

    output_csv_path = None
    if getattr(args, "output_csv", None):
        output_csv_path = _write_stock_report_csv(
            output_path=str(args.output_csv),
            rows=list(report.get("rows", []) or []),
        )
    report["output_csv"] = output_csv_path
    print(json.dumps(report, indent=2, ensure_ascii=False))


def _run_selection_forward_report(args: argparse.Namespace) -> None:
    selection_csv_path = pathlib.Path(str(getattr(args, "selection_csv", ""))).expanduser()
    if not selection_csv_path.exists():
        raise SystemExit(f"Selection CSV not found: {selection_csv_path}")

    forward_window = _resolve_selection_forward_window(args)
    selection_rows = _read_selection_csv(selection_csv_path)
    candidate_rows = _filter_selection_forward_candidates(selection_rows)
    if not candidate_rows:
        raise SystemExit("No eligible rows found in selection CSV.")

    config = _load_config()
    ctx = build_app_context(config)
    if ctx.market_data_provider is None:
        raise SystemExit("Market data provider is not configured for selection-forward-report.")

    report_rows = _build_selection_forward_report_rows(
        selection_rows=candidate_rows,
        market_data_provider=ctx.market_data_provider,
        forward_window=forward_window,
    )

    output_csv_path = _resolve_selection_forward_output_path(
        selection_csv_path=selection_csv_path,
        forward_window=forward_window,
        explicit_output_path=getattr(args, "output_csv", None),
    )
    summary = _build_selection_forward_summary(report_rows)
    written_csv_path = _write_selection_forward_report_csv(
        output_path=str(output_csv_path),
        rows=report_rows,
    )
    written_summary_csv_path = _write_selection_forward_summary_csv(
        output_path=str(pathlib.Path(written_csv_path).with_name(f"{pathlib.Path(written_csv_path).stem}_summary.csv")),
        summary=summary,
        holding_period_label=str(forward_window["label"]),
        selection_csv=str(selection_csv_path),
    )

    print(json.dumps({
        "mode": "selection_forward_report",
        "selection_csv": str(selection_csv_path),
        "forward_window": {
            "kind": forward_window["kind"],
            "value": forward_window["value"],
            "label": forward_window["label"],
        },
        "row_count": len(report_rows),
        "summary": summary,
        "output_csv": written_csv_path,
        "output_png": str(pathlib.Path(written_csv_path).with_suffix(".png")),
        "output_summary_csv": written_summary_csv_path,
        "output_summary_png": str(pathlib.Path(written_summary_csv_path).with_suffix(".png")),
        "rows": report_rows,
    }, indent=2, ensure_ascii=False))


def _resolve_daily_selection_dates(args: argparse.Namespace) -> list[date]:
    raw_as_of = getattr(args, "as_of", None)
    raw_start = getattr(args, "start", None)
    raw_end = getattr(args, "end", None)

    if raw_as_of:
        if raw_end:
            raise SystemExit("--end cannot be used together with --as-of.")
        return [date.fromisoformat(str(raw_as_of))]

    if not raw_start:
        raise SystemExit("Either --as-of or --start/--end is required.")
    if not raw_end:
        raise SystemExit("--end is required when --start is provided.")

    start_date = date.fromisoformat(str(raw_start))
    end_date = date.fromisoformat(str(raw_end))
    if end_date < start_date:
        raise SystemExit("--end must be greater than or equal to --start.")

    dates: list[date] = []
    current = start_date
    while current <= end_date:
        dates.append(current)
        current += timedelta(days=1)
    return dates


def _resolve_stock_report_dates(args: argparse.Namespace) -> tuple[date, date]:
    start_date = date.fromisoformat(str(getattr(args, "start", "")))
    end_date = date.fromisoformat(str(getattr(args, "end", "")))
    if end_date < start_date:
        raise SystemExit("--end must be greater than or equal to --start.")
    return start_date, end_date


def _resolve_stock_report_symbol(raw_symbol: str) -> str:
    normalized = normalize_tw_symbol(raw_symbol)
    candidate = normalized or raw_symbol.strip().upper()
    if not candidate:
        raise SystemExit("--symbol is required.")
    return candidate


def _resolve_selection_forward_window(args: argparse.Namespace) -> dict[str, Any]:
    raw_months = getattr(args, "forward_months", None)
    raw_days = getattr(args, "forward_days", None)
    if raw_months is not None:
        months = int(raw_months)
        if months <= 0:
            raise SystemExit("--forward-months must be greater than 0.")
        return {"kind": "months", "value": months, "label": f"{months}m"}
    if raw_days is not None:
        days = int(raw_days)
        if days <= 0:
            raise SystemExit("--forward-days must be greater than 0.")
        return {"kind": "days", "value": days, "label": f"{days}d"}
    raise SystemExit("Either --forward-months or --forward-days is required.")


def _read_selection_csv(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _filter_selection_forward_candidates(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    filtered: list[dict[str, str]] = []
    for row in rows:
        symbol = str(row.get("symbol", "")).strip()
        timestamp = str(row.get("timestamp", "")).strip()
        if not symbol or not timestamp:
            continue
        filtered.append(dict(row))
    return filtered


def _is_truthy(value: object) -> bool:
    normalized = str(value).strip().lower()
    return normalized in {"1", "true", "yes", "y"}


def _build_selection_forward_report_rows(
    *,
    selection_rows: list[dict[str, str]],
    market_data_provider,
    forward_window: dict[str, Any],
) -> list[dict[str, Any]]:
    selection_dates = [date.fromisoformat(str(row["timestamp"])) for row in selection_rows]
    target_dates = [_apply_forward_window(item, forward_window) for item in selection_dates]
    fetch_start = min(selection_dates)
    fetch_end = max(target_dates) + timedelta(days=15)
    symbols = sorted({str(row.get("symbol", "")).strip() for row in selection_rows if str(row.get("symbol", "")).strip()})
    bars = market_data_provider.fetch_ohlcv(symbols, fetch_start, fetch_end)
    history_by_symbol: dict[str, list[Any]] = {}
    for bar in bars:
        symbol = str(getattr(bar, "symbol", "")).strip()
        if not symbol:
            continue
        history_by_symbol.setdefault(symbol, []).append(bar)
    for symbol in history_by_symbol:
        history_by_symbol[symbol].sort(key=lambda item: date.fromisoformat(str(item.date)))

    report_rows: list[dict[str, Any]] = []
    for row in selection_rows:
        symbol = str(row.get("symbol", "")).strip()
        selection_date = date.fromisoformat(str(row.get("timestamp", "")).strip())
        target_date = _apply_forward_window(selection_date, forward_window)
        history = history_by_symbol.get(symbol, [])
        entry_bar = _find_first_bar_on_or_after(history, selection_date)
        evaluation_bar = _find_first_bar_on_or_after(history, target_date)
        status = "ok"
        entry_date = None
        entry_close = None
        evaluation_date = None
        evaluation_close = None
        return_pct = None

        if entry_bar is None:
            status = "missing_entry_price"
        else:
            entry_date = date.fromisoformat(str(entry_bar.date))
            entry_close = float(entry_bar.close)

        if evaluation_bar is None:
            status = "missing_evaluation_price" if status == "ok" else f"{status}|missing_evaluation_price"
        else:
            evaluation_date = date.fromisoformat(str(evaluation_bar.date))
            evaluation_close = float(evaluation_bar.close)

        if entry_close not in (None, 0.0) and evaluation_close is not None:
            return_pct = round((evaluation_close / entry_close) - 1.0, 6)

        report_rows.append({
            "symbol": symbol,
            "stock_name": str(row.get("stock_name", "") or ""),
            "selection_date": selection_date.isoformat(),
            "entry_date": (entry_date.isoformat() if entry_date is not None else ""),
            "entry_close": entry_close,
            "target_date": target_date.isoformat(),
            "evaluation_date": (evaluation_date.isoformat() if evaluation_date is not None else ""),
            "evaluation_close": evaluation_close,
            "return_pct": return_pct,
            "holding_period_label": str(forward_window["label"]),
            "selected": _is_truthy(row.get("selected", "")) if "selected" in row else True,
            "rank": row.get("rank", ""),
            "weight": row.get("weight", ""),
            "status": status,
        })
    return report_rows


def _build_selection_forward_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid_returns = [
        float(row["return_pct"])
        for row in rows
        if row.get("return_pct") is not None
    ]
    evaluated_count = len(valid_returns)
    missing_count = len(rows) - evaluated_count
    if not valid_returns:
        return {
            "evaluated_count": 0,
            "missing_count": missing_count,
            "average_return_pct": None,
            "win_rate": None,
            "max_return_pct": None,
            "min_return_pct": None,
        }
    win_count = sum(1 for item in valid_returns if item > 0)
    return {
        "evaluated_count": evaluated_count,
        "missing_count": missing_count,
        "average_return_pct": round(sum(valid_returns) / evaluated_count, 6),
        "win_rate": round(win_count / evaluated_count, 6),
        "max_return_pct": round(max(valid_returns), 6),
        "min_return_pct": round(min(valid_returns), 6),
    }


def _find_first_bar_on_or_after(history: list[Any], target_date: date):
    for bar in history:
        bar_date = date.fromisoformat(str(bar.date))
        if bar_date >= target_date:
            return bar
    return None


def _apply_forward_window(base_date: date, forward_window: dict[str, Any]) -> date:
    if str(forward_window["kind"]) == "days":
        return base_date + timedelta(days=int(forward_window["value"]))
    return _add_calendar_months(base_date, int(forward_window["value"]))


def _add_calendar_months(base_date: date, months: int) -> date:
    month_index = (base_date.month - 1) + months
    year = base_date.year + (month_index // 12)
    month = (month_index % 12) + 1
    day = min(base_date.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _resolve_selection_forward_output_path(
    *,
    selection_csv_path: pathlib.Path,
    forward_window: dict[str, Any],
    explicit_output_path: str | None,
) -> pathlib.Path:
    if explicit_output_path:
        return pathlib.Path(str(explicit_output_path)).expanduser()
    return selection_csv_path.with_name(f"{selection_csv_path.stem}_forward_{forward_window['label']}.csv")


def _resolve_missing_history_threshold(args: argparse.Namespace) -> float | None:
    raw_threshold = float(getattr(args, "missing_history_threshold", 0.2))
    if raw_threshold < 0:
        return None
    return raw_threshold


def _raise_if_missing_history_ratio_exceeded(*, run_summary: dict[str, Any], threshold: float | None) -> None:
    if threshold is None:
        return
    universe_size = int(run_summary.get("universe_size", 0) or 0)
    if universe_size <= 0:
        return
    missing_history_count = int(run_summary.get("missing_history_count", 0) or 0)
    missing_ratio = missing_history_count / universe_size
    if missing_ratio <= threshold:
        return
    raise SystemExit(
        "Daily selection aborted because missing-history ratio exceeded threshold: "
        f"as_of={run_summary.get('as_of', '')} "
        f"missing_history_count={missing_history_count} "
        f"universe_size={universe_size} "
        f"missing_ratio={missing_ratio:.4f} "
        f"threshold={threshold:.4f}"
    )


def _uses_yfinance_provider(config: AppConfig) -> bool:
    data_config = getattr(config, "data", None)
    return str(getattr(data_config, "market_provider", "") or "").strip().lower() == "yfinance_ohlcv"


def _load_excluded_symbols(path: pathlib.Path | None) -> set[str]:
    if path is None or not path.exists():
        return set()
    symbols: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        normalized = str(line).split("#", 1)[0].strip().upper()
        if normalized:
            symbols.add(normalized)
    return symbols


def _write_daily_selection_range_csv(*, output_path: str, rows: list[dict[str, Any]]) -> str:
    path = pathlib.Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "symbol",
        "stock_name",
        "first_matched_date",
        "last_matched_date",
        "matched_days",
        "latest_signal",
        "latest_score",
        "latest_criteria_json",
        "criteria_history_json",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            criteria_history = list(row.get("criteria_history", []) or [])
            latest_criteria = dict(row.get("latest_criteria", {}) or {})
            writer.writerow({
                "symbol": row.get("symbol", ""),
                "stock_name": row.get("stock_name", ""),
                "first_matched_date": row.get("first_matched_date", ""),
                "last_matched_date": row.get("last_matched_date", ""),
                "matched_days": row.get("matched_days", ""),
                "latest_signal": row.get("latest_signal", ""),
                "latest_score": row.get("latest_score", ""),
                "latest_criteria_json": json.dumps(latest_criteria, ensure_ascii=False, sort_keys=True),
                "criteria_history_json": json.dumps(criteria_history, ensure_ascii=False, sort_keys=True),
            })
    render_rows = [
        {
            "symbol": row.get("symbol", ""),
            "stock_name": row.get("stock_name", ""),
            "first_matched_date": row.get("first_matched_date", ""),
            "last_matched_date": row.get("last_matched_date", ""),
            "matched_days": row.get("matched_days", ""),
            "latest_signal": row.get("latest_signal", ""),
            "latest_score": row.get("latest_score", ""),
            "latest_criteria_json": json.dumps(dict(row.get("latest_criteria", {}) or {}), ensure_ascii=False, sort_keys=True),
            "criteria_history_json": json.dumps(list(row.get("criteria_history", []) or []), ensure_ascii=False, sort_keys=True),
        }
        for row in rows
    ]
    write_csv_preview_image(csv_path=path, fieldnames=fieldnames, rows=render_rows)
    return str(path)


def _write_selection_forward_report_csv(
    *,
    output_path: str,
    rows: list[dict[str, Any]],
) -> str:
    path = pathlib.Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "symbol",
        "stock_name",
        "selection_date",
        "entry_date",
        "entry_close",
        "target_date",
        "evaluation_date",
        "evaluation_close",
        "return_pct",
        "holding_period_label",
        "selected",
        "rank",
        "weight",
        "status",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    render_rows = [{field: row.get(field, "") for field in fieldnames} for row in rows]
    write_csv_preview_image(csv_path=path, fieldnames=fieldnames, rows=render_rows)
    return str(path)


def _write_selection_forward_summary_csv(
    *,
    output_path: str,
    summary: dict[str, Any],
    holding_period_label: str,
    selection_csv: str,
) -> str:
    path = pathlib.Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "selection_csv",
        "holding_period_label",
        "evaluated_count",
        "missing_count",
        "average_return_pct",
        "win_rate",
        "max_return_pct",
        "min_return_pct",
    ]
    row = {
        "selection_csv": selection_csv,
        "holding_period_label": holding_period_label,
        "evaluated_count": summary.get("evaluated_count", ""),
        "missing_count": summary.get("missing_count", ""),
        "average_return_pct": summary.get("average_return_pct", ""),
        "win_rate": summary.get("win_rate", ""),
        "max_return_pct": summary.get("max_return_pct", ""),
        "min_return_pct": summary.get("min_return_pct", ""),
    }
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(row)
    write_csv_preview_image(csv_path=path, fieldnames=fieldnames, rows=[row])
    return str(path)


def _write_stock_report_csv(*, output_path: str, rows: list[dict[str, Any]]) -> str:
    path = pathlib.Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "date",
        "symbol",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "turnover",
        "price_change",
        "price_change_pct",
        "volume_ratio_5",
        "volume_ratio_20",
        "ma_5",
        "ma_10",
        "ma_20",
        "ma_60",
        "rolling_high_20",
        "rolling_low_20",
        "macd_histogram",
        "rsi_14",
        "estimated_inflow",
        "estimated_outflow",
        "flow_ratio_5",
        "flow_momentum_5",
        "chip_concentration_proxy",
        "chip_distribution_5_proxy",
        "cost_basis_ratio_proxy",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    render_rows = [{field: row.get(field, "") for field in fieldnames} for row in rows]
    write_csv_preview_image(csv_path=path, fieldnames=fieldnames, rows=render_rows)
    return str(path)


def _resolve_symbol_names(*, universe_provider: UniverseProvider, as_of: date) -> dict[str, str]:
    names: dict[str, str] = {}
    for entry in universe_provider.get_universe(as_of=as_of):
        symbol = str(entry.symbol).strip()
        if not symbol or symbol in names:
            continue
        names[symbol] = str(getattr(entry, "name", "") or "").strip()
    return names


def _resolve_runner_selection_rows(*, runner: Any, selections: list[Any]) -> list[dict[str, Any]]:
    summary = dict(getattr(runner, "last_run_summary", {}) or {})
    rows = list(summary.get("selections", []) or [])
    if rows:
        return [dict(row) for row in rows]
    return [{
        "symbol": item.symbol,
        "timestamp": str(item.timestamp),
        "rank": item.rank,
        "weight": item.weight,
        "reason": item.reason,
        "signal": "",
        "score": "",
        "criteria": {},
        "criteria_json": "{}",
    } for item in selections]


def _attach_stock_names_to_selection_rows(*, rows: list[dict[str, Any]], symbol_name_map: dict[str, str]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for row in rows:
        copied = dict(row)
        symbol = str(copied.get("symbol", "")).strip()
        copied["stock_name"] = symbol_name_map.get(symbol, "")
        enriched.append(copied)
    return enriched


class _StaticUniverseProvider(UniverseProvider):
    def __init__(self, symbols: list[str]) -> None:
        self._entries = [
            UniverseEntry(
                symbol=symbol,
                name="",
                exchange="CUSTOM",
                market="stock",
                listing_status=ListingStatus.LISTED,
                updated_at=datetime.now(),
            )
            for symbol in symbols
        ]

    def get_universe(self, as_of=None) -> list[UniverseEntry]:
        return list(self._entries)

    def get_symbol(self, symbol, as_of=None) -> UniverseEntry | None:
        for entry in self._entries:
            if entry.symbol == symbol:
                return entry
        return None


class _LimitedUniverseProvider(UniverseProvider):
    def __init__(self, *, base_provider: UniverseProvider, max_symbols: int) -> None:
        self._base_provider = base_provider
        self._max_symbols = max(max_symbols, 1)

    def get_universe(self, as_of=None) -> list[UniverseEntry]:
        entries = self._base_provider.get_universe(as_of=as_of)
        deduped: list[UniverseEntry] = []
        seen_symbols: set[str] = set()
        for entry in sorted(entries, key=lambda item: item.updated_at, reverse=True):
            if entry.listing_status != ListingStatus.LISTED:
                continue
            if entry.symbol in seen_symbols:
                continue
            deduped.append(entry)
            seen_symbols.add(entry.symbol)
            if len(deduped) >= self._max_symbols:
                break
        return deduped

    def get_symbol(self, symbol, as_of=None) -> UniverseEntry | None:
        return self._base_provider.get_symbol(symbol, as_of=as_of)


class _ExcludedUniverseProvider(UniverseProvider):
    def __init__(self, *, base_provider: UniverseProvider, excluded_symbols: set[str]) -> None:
        self._base_provider = base_provider
        self._excluded_symbols = {str(symbol).strip().upper() for symbol in excluded_symbols if str(symbol).strip()}

    def get_universe(self, as_of=None) -> list[UniverseEntry]:
        return [
            entry for entry in self._base_provider.get_universe(as_of=as_of)
            if str(entry.symbol).strip().upper() not in self._excluded_symbols
        ]

    def get_symbol(self, symbol, as_of=None) -> UniverseEntry | None:
        normalized = str(symbol).strip().upper()
        if normalized in self._excluded_symbols:
            return None
        return self._base_provider.get_symbol(symbol, as_of=as_of)


if __name__ == "__main__":
    main()
