"""CLI entrypoints for tw_quant backtest batch and daily selection."""

from __future__ import annotations

import argparse
import json
import pathlib
from datetime import date, datetime
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
from src.tw_quant.schema.models import BacktestResult, BatchRunRecord, BatchRunResult
from src.tw_quant.selection.pipeline import SelectionConfig
from src.tw_quant.universe.interfaces import UniverseProvider
from src.tw_quant.universe.models import ListingStatus, UniverseEntry
from src.tw_quant.wiring.container import build_app_context
from src.tw_quant.workflows import AtomicBacktestExecutor, DailySelectionRunner

_CONFIG_PATH = pathlib.Path(__file__).parent.parent.parent / "configs" / "quant" / "default.yaml"


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
    daily.add_argument("--as-of", required=True)
    daily.add_argument("--strategy", default="pullback_trend_compression")
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

    args = parser.parse_args()

    if args.command == "backtest-batch":
        _run_backtest_batch(args)
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
    as_of = date.fromisoformat(args.as_of)
    config = _load_config()
    ctx = build_app_context(config)
    universe_provider = ctx.universe_provider
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
    )
    selections = runner.run(
        as_of=as_of,
        strategy_name=args.strategy,
        selection_config=SelectionConfig(top_n=max(args.top_n, 1), signal_type_whitelist=["buy"], min_score=0.0),
    )
    print(json.dumps([{
        "symbol": item.symbol,
        "timestamp": str(item.timestamp),
        "rank": item.rank,
        "weight": item.weight,
        "reason": item.reason,
    } for item in selections], indent=2, ensure_ascii=False))


class _StaticUniverseProvider(UniverseProvider):
    def __init__(self, symbols: list[str]) -> None:
        self._entries = [
            UniverseEntry(
                symbol=symbol,
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


if __name__ == "__main__":
    main()
