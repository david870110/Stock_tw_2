"""Execution workflows for batch backtests and daily market selection."""

from __future__ import annotations

import csv
import json
import sys
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Sequence

from src.tw_quant.backtest import InMemoryPortfolioBook, SimpleExecutionModel, SymbolBacktestEngine
from src.tw_quant.backtest.exit_builder import build_close_policy, build_exit_rules, canonicalize_strategy_name
from src.tw_quant.config.models import AppConfig
from src.tw_quant.config.models import BacktestConfig
from src.tw_quant.core.types import DateLike, Symbol
from src.tw_quant.data.interfaces import MarketDataProvider
from src.tw_quant.schema.models import (
    BacktestResult,
    FeatureFrameRef,
    OHLCVBar,
    OrderIntent,
    SelectionRecord,
    SignalRecord,
)
from src.tw_quant.selection import SelectionConfig, SelectionPipeline
from src.tw_quant.reporting.csv_image import write_csv_preview_image
from src.tw_quant.strategy.chip.indicators import (
    chip_concentration,
    chip_distribution,
    cost_basis_ratio,
)
from src.tw_quant.strategy.flow.metrics import flow_momentum, flow_ratio, inflow_outflow
from src.tw_quant.strategy.interfaces import StrategyContext
from src.tw_quant.strategy.technical.features import (
    macd_histogram,
    rolling_max,
    rolling_min,
    simple_moving_average,
)
from src.tw_quant.strategy.technical.ma_bullish_stack import (
    MovingAverageBullishStackStrategy,
)
from src.tw_quant.strategy.technical.ma_crossover import MovingAverageCrossoverStrategy
from src.tw_quant.strategy.technical.pullback_trend_compression import (
    PullbackTrend120dOptimizedStrategy,
    PullbackTrendCompressionStrategy,
)
from src.tw_quant.strategy.technical.qizhang_signal import QizhangSignalStrategy
from src.tw_quant.utils.indicators import calculate_rsi
from src.tw_quant.universe.interfaces import UniverseProvider
from src.tw_quant.universe.models import ListingStatus
from src.tw_quant.wiring.container import build_app_context

try:
    from tqdm import tqdm
except Exception:  # pragma: no cover - environment-dependent
    tqdm = None


class AtomicBacktestExecutor:
    """Atomic executor compatible with DeterministicBatchRunner."""

    def __init__(
        self,
        *,
        market_data_provider: MarketDataProvider,
        backtest_config: BacktestConfig | None = None,
    ) -> None:
        self._market_data_provider = market_data_provider
        self._backtest_config = backtest_config or BacktestConfig()

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
        result = execute_atomic_backtest_run(
            market_data_provider=self._market_data_provider,
            symbol=symbol,
            strategy_name=strategy_name,
            start=start,
            end=end,
            parameters=parameters,
            run_id=run_id,
            initial_cash=self._backtest_config.initial_cash,
            backtest_config=self._backtest_config,
        )
        persist_backtest_result(
            result=result,
            artifact_path=artifact_path,
            metadata={"parameters": parameters},
            write_summary_csv=False,
        )
        return result


def execute_atomic_backtest_run(
    *,
    market_data_provider: MarketDataProvider,
    symbol: Symbol,
    strategy_name: str,
    start: DateLike,
    end: DateLike,
    parameters: dict[str, Any],
    run_id: str,
    initial_cash: float,
    backtest_config: BacktestConfig | None = None,
) -> BacktestResult:
    bars = market_data_provider.fetch_ohlcv([symbol], start, end)
    symbol_bars = [bar for bar in bars if bar.symbol == symbol]
    bars_by_date = {_to_date(bar.date): bar for bar in symbol_bars}
    sorted_dates = sorted(bars_by_date.keys())

    def data_provider(sym: Symbol, dt: DateLike) -> OHLCVBar | None:
        if sym != symbol:
            return None
        return bars_by_date.get(_to_date(dt))

    def signal_source(sym: Symbol, dt: DateLike):
        if sym != symbol:
            return []
        current_date = _to_date(dt)
        history = [bars_by_date[item] for item in sorted_dates if item <= current_date]
        if not history:
            return []

        signals = _generate_strategy_signals(
            strategy_name=strategy_name,
            parameters=parameters,
            as_of=current_date,
            by_symbol_history={symbol: history},
        )
        if not signals:
            return []

        strategy = _build_strategy(strategy_name, parameters, by_symbol_history={symbol: history})
        context = StrategyContext(strategy_name=strategy_name, as_of=current_date)
        orders = strategy.build_orders(context, signals)
        current_bar = bars_by_date.get(current_date)
        return _apply_position_cash_sizing(
            orders=orders,
            current_bar=current_bar,
            position_cash=_resolve_position_cash(strategy_name, parameters),
            risk_budget_cash=_resolve_risk_budget_cash(strategy_name, parameters),
            stop_distance=_resolve_stop_distance(
                strategy_name=strategy_name,
                parameters=parameters,
                history=history,
            ),
        )

    engine = SymbolBacktestEngine(
        symbol=symbol,
        data_provider=data_provider,
        execution_model=SimpleExecutionModel(data_provider),
        portfolio_book=InMemoryPortfolioBook(initial_cash=initial_cash),
        signal_source=signal_source,
        run_id=run_id,
        strategy_name=strategy_name,
        exit_rules=build_exit_rules(
            strategy_name=strategy_name,
            parameters=parameters,
            backtest_config=backtest_config,
        ),
        close_policy=build_close_policy(strategy_name=strategy_name),
        reentry_cooldown_days=_resolve_reentry_cooldown_days(strategy_name, parameters),
        cooldown_apply_on=_resolve_cooldown_apply_on(strategy_name, parameters),
    )

    return engine.run(start, end)


class DailySelectionRunner:
    """Generate same-day selections from full market universe and strategy signals."""

    def __init__(
        self,
        *,
        universe_provider: UniverseProvider,
        market_data_provider: MarketDataProvider,
        output_base: str = "artifacts",
        app_config: AppConfig | None = None,
    ) -> None:
        self._universe_provider = universe_provider
        self._market_data_provider = market_data_provider
        self._output_base = output_base
        self._app_config = app_config
        self._last_run_summary: dict[str, Any] = {}

    @property
    def last_run_summary(self) -> dict[str, Any]:
        return dict(self._last_run_summary)

    def run(
        self,
        *,
        as_of: DateLike,
        strategy_name: str,
        strategy_parameters: dict[str, Any] | None = None,
        lookback_bars: int = 220,
        selection_config: SelectionConfig | None = None,
        max_workers: int = 1,
        show_progress: bool | None = None,
        progress_label: str | None = None,
    ) -> list[SelectionRecord]:
        as_of_date = _to_date(as_of)
        symbols = self._resolve_active_symbols(as_of_date)
        if not symbols:
            self._persist_daily_selection(
                as_of=as_of_date,
                strategy_name=strategy_name,
                signals=[],
                selections=[],
            )
            return []

        signals: list[SignalRecord] = []
        parameters = dict(strategy_parameters or {})
        use_progress = bool(show_progress) if show_progress is not None else (tqdm is not None and len(symbols) > 1)
        requested_workers = max(1, int(max_workers))
        parallel_mode, worker_count = _resolve_daily_selection_parallel_mode(
            app_config=self._app_config,
            requested_workers=requested_workers,
            symbol_count=len(symbols),
        )
        chunk_size = _resolve_parallel_chunk_size(symbol_count=len(symbols), worker_count=worker_count)

        if use_progress:
            print(
                f"{progress_label or 'Daily Selection'} mode={parallel_mode} requested_workers={requested_workers} effective_workers={worker_count} chunk_size={chunk_size} symbols={len(symbols)}",
                file=sys.stdout,
                flush=True,
            )

        if parallel_mode == "process-chunk" and worker_count > 1 and len(symbols) > 1 and self._app_config is not None:
            symbols_with_history: set[Symbol] = set()
            progress_bar = _create_progress_bar(
                total=len(symbols),
                desc=progress_label or "Daily Selection",
                unit="symbol",
            ) if use_progress else None
            try:
                with ProcessPoolExecutor(max_workers=worker_count) as executor:
                    chunks = _chunk_symbols(symbols, chunk_size=chunk_size)
                    future_map = {
                        executor.submit(
                            _process_daily_selection_chunk_task,
                            app_config=self._app_config,
                            symbols_chunk=chunk,
                            as_of=as_of_date,
                            strategy_name=strategy_name,
                            parameters=parameters,
                            lookback_bars=lookback_bars,
                        ): len(chunk)
                        for chunk in chunks
                    }
                    for future in as_completed(future_map):
                        result = future.result()
                        signals.extend(result["signals"])
                        symbols_with_history.update(result["symbols_with_history"])
                        if progress_bar is not None:
                            progress_bar.update(int(future_map[future]))
            finally:
                if progress_bar is not None:
                    progress_bar.close()
            config = selection_config or SelectionConfig(signal_type_whitelist=["buy"], min_score=0.0, top_n=30)
            selections = SelectionPipeline(config).run(signals, as_of_date)
            self._persist_daily_selection(
                as_of=as_of_date,
                strategy_name=strategy_name,
                signals=signals,
                selections=selections,
                universe_size=len(symbols),
                symbols_with_history=symbols_with_history,
                missing_symbols=[symbol for symbol in symbols if symbol not in symbols_with_history],
            )
            return selections

        if parallel_mode == "thread-chunk-yfinance" and worker_count > 1 and len(symbols) > 1:
            symbols_with_history: set[Symbol] = set()
            progress_bar = _create_progress_bar(
                total=len(symbols),
                desc=progress_label or "Daily Selection",
                unit="symbol",
            ) if use_progress else None
            start = as_of_date - timedelta(days=max(lookback_bars * 3, lookback_bars + 30))
            fetch_end = as_of_date + timedelta(days=1)
            try:
                with ThreadPoolExecutor(max_workers=worker_count) as executor:
                    chunks = _chunk_symbols(symbols, chunk_size=chunk_size)
                    future_map = {
                        executor.submit(
                            _process_daily_selection_chunk_with_provider_task,
                            market_data_provider=self._market_data_provider,
                            symbols_chunk=chunk,
                            as_of=as_of_date,
                            strategy_name=strategy_name,
                            parameters=parameters,
                            start=start,
                            fetch_end=fetch_end,
                        ): len(chunk)
                        for chunk in chunks
                    }
                    for future in as_completed(future_map):
                        result = future.result()
                        signals.extend(result["signals"])
                        symbols_with_history.update(result["symbols_with_history"])
                        if progress_bar is not None:
                            progress_bar.update(int(future_map[future]))
            finally:
                if progress_bar is not None:
                    progress_bar.close()

            missing_symbols = [symbol for symbol in symbols if symbol not in symbols_with_history]
            if missing_symbols:
                recovered = _recover_missing_daily_selection_symbols(
                    market_data_provider=self._market_data_provider,
                    missing_symbols=missing_symbols,
                    as_of=as_of_date,
                    strategy_name=strategy_name,
                    parameters=parameters,
                    start=start,
                    fetch_end=fetch_end,
                )
                signals.extend(recovered["signals"])
                symbols_with_history.update(recovered["symbols_with_history"])
                missing_symbols = [symbol for symbol in symbols if symbol not in symbols_with_history]

            config = selection_config or SelectionConfig(signal_type_whitelist=["buy"], min_score=0.0, top_n=30)
            selections = SelectionPipeline(config).run(signals, as_of_date)
            self._persist_daily_selection(
                as_of=as_of_date,
                strategy_name=strategy_name,
                signals=signals,
                selections=selections,
                universe_size=len(symbols),
                symbols_with_history=symbols_with_history,
                missing_symbols=missing_symbols,
            )
            return selections

        start = as_of_date - timedelta(days=max(lookback_bars * 3, lookback_bars + 30))
        fetch_end = as_of_date + timedelta(days=1)
        bars = self._market_data_provider.fetch_ohlcv(symbols, start, fetch_end)
        grouped = _group_bars_by_symbol(bars, as_of=as_of_date)

        def _generate_for_symbol(symbol: Symbol) -> list[SignalRecord]:
            history = grouped.get(symbol, [])
            if not history:
                return []
            return _generate_strategy_signals(
                strategy_name=strategy_name,
                parameters=parameters,
                as_of=as_of_date,
                by_symbol_history={symbol: history},
            )

        if worker_count > 1 and len(symbols) > 1:
            progress_bar = _create_progress_bar(
                total=len(symbols),
                desc=progress_label or "Daily Selection",
                unit="symbol",
            ) if use_progress else None
            try:
                with ProcessPoolExecutor(max_workers=worker_count) as executor:
                    chunks = _chunk_symbols(symbols, chunk_size=chunk_size)
                    future_map = {
                        executor.submit(
                            _generate_signals_for_symbol_chunk_task,
                            chunk_histories={
                                symbol: grouped.get(symbol, [])
                                for symbol in chunk
                            },
                            strategy_name=strategy_name,
                            parameters=parameters,
                            as_of=as_of_date,
                        ): len(chunk)
                        for chunk in chunks
                    }
                    for future in as_completed(future_map):
                        signals.extend(future.result())
                        if progress_bar is not None:
                            progress_bar.update(int(future_map[future]))
            finally:
                if progress_bar is not None:
                    progress_bar.close()
        else:
            iterator = _create_progress_iterable(
                iterable=symbols,
                desc=progress_label or "Daily Selection",
                unit="symbol",
            ) if use_progress else symbols
            try:
                for symbol in iterator:
                    signals.extend(_generate_for_symbol(symbol))
            finally:
                if use_progress and hasattr(iterator, "close"):
                    iterator.close()

        config = selection_config or SelectionConfig(signal_type_whitelist=["buy"], min_score=0.0, top_n=30)
        selections = SelectionPipeline(config).run(signals, as_of_date)
        symbols_with_history = {symbol for symbol in symbols if grouped.get(symbol)}
        self._persist_daily_selection(
            as_of=as_of_date,
            strategy_name=strategy_name,
            signals=signals,
            selections=selections,
            universe_size=len(symbols),
            symbols_with_history=symbols_with_history,
            missing_symbols=[symbol for symbol in symbols if symbol not in symbols_with_history],
        )
        return selections

    def _resolve_active_symbols(self, as_of: date) -> list[Symbol]:
        entries = self._universe_provider.get_universe(as_of=as_of)
        symbols: list[Symbol] = []
        seen: set[Symbol] = set()
        for entry in sorted(entries, key=lambda item: item.updated_at, reverse=True):
            if entry.symbol in seen:
                continue
            if entry.listing_status != ListingStatus.LISTED:
                seen.add(entry.symbol)
                continue
            symbols.append(entry.symbol)
            seen.add(entry.symbol)
        symbols.sort()
        return symbols

    def _persist_daily_selection(
        self,
        *,
        as_of: date,
        strategy_name: str,
        signals: Sequence[SignalRecord],
        selections: Sequence[SelectionRecord],
        universe_size: int | None = None,
        symbols_with_history: Sequence[Symbol] | None = None,
        missing_symbols: Sequence[Symbol] | None = None,
    ) -> None:
        output_dir = Path(self._output_base) / "tw_quant" / "daily_selection" / as_of.isoformat()
        output_dir.mkdir(parents=True, exist_ok=True)
        stock_name_by_symbol = self._resolve_stock_names(as_of)
        symbols_with_history_list = sorted({str(symbol).strip() for symbol in (symbols_with_history or []) if str(symbol).strip()})
        missing_symbols_list = sorted({str(symbol).strip() for symbol in (missing_symbols or []) if str(symbol).strip()})
        buy_signal_count = sum(1 for signal in signals if str(signal.signal).strip().lower() == "buy")
        selection_rows = _build_daily_selection_rows(signals=signals, selections=selections)
        csv_rows = _build_daily_signal_rows(
            signals=signals,
            selections=selections,
            stock_name_by_symbol=stock_name_by_symbol,
        )

        payload = {
            "as_of": as_of.isoformat(),
            "strategy_name": strategy_name,
            "universe_size": int(universe_size or 0),
            "symbols_with_history_count": len(symbols_with_history_list),
            "missing_history_count": len(missing_symbols_list),
            "missing_history_sample": missing_symbols_list[:50],
            "signal_count": len(signals),
            "buy_signal_count": buy_signal_count,
            "selection_count": len(selections),
            "signals": [
                {
                    "symbol": signal.symbol,
                    "timestamp": _serialize_date_like(signal.timestamp),
                    "signal": signal.signal,
                    "score": signal.score,
                    "metadata": dict(signal.metadata),
                }
                for signal in signals
            ],
            "selections": selection_rows,
        }
        self._last_run_summary = {
            "as_of": payload["as_of"],
            "strategy_name": strategy_name,
            "universe_size": payload["universe_size"],
            "symbols_with_history_count": payload["symbols_with_history_count"],
            "missing_history_count": payload["missing_history_count"],
            "missing_history_sample": list(payload["missing_history_sample"]),
            "signal_count": payload["signal_count"],
            "buy_signal_count": payload["buy_signal_count"],
            "selection_count": payload["selection_count"],
            "selections": [dict(row) for row in selection_rows],
            "csv_rows": [dict(row) for row in csv_rows],
        }

        json_path = output_dir / f"{strategy_name}.json"
        json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

        csv_path = output_dir / f"{strategy_name}.csv"
        selection_fieldnames = _resolve_selection_csv_fieldnames(csv_rows)
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=selection_fieldnames)
            writer.writeheader()
            for row in csv_rows:
                writer.writerow({field: row.get(field, "") for field in selection_fieldnames})
        write_csv_preview_image(
            csv_path=csv_path,
            fieldnames=selection_fieldnames,
            rows=csv_rows,
        )

    def _resolve_stock_names(self, as_of: date) -> dict[str, str]:
        entries = self._universe_provider.get_universe(as_of=as_of)
        stock_name_by_symbol: dict[str, str] = {}
        for entry in entries:
            symbol = str(getattr(entry, "symbol", "")).strip()
            if not symbol or symbol in stock_name_by_symbol:
                continue
            stock_name_by_symbol[symbol] = str(getattr(entry, "name", "") or "")
        return stock_name_by_symbol


def build_stock_report(
    *,
    symbol: Symbol,
    start: DateLike,
    end: DateLike,
    market_data_provider: MarketDataProvider,
    universe_provider: UniverseProvider | None = None,
    warmup_days: int = 180,
) -> dict[str, Any]:
    start_date = _to_date(start)
    end_date = _to_date(end)
    if end_date < start_date:
        raise ValueError("end must be greater than or equal to start")

    warmup = max(1, int(warmup_days))
    fetch_start = start_date - timedelta(days=warmup)
    fetch_end = end_date + timedelta(days=1)
    bars = market_data_provider.fetch_ohlcv([symbol], fetch_start, fetch_end)
    history = sorted(
        [bar for bar in bars if str(bar.symbol).strip().upper() == str(symbol).strip().upper()],
        key=lambda item: _to_date(item.date),
    )
    if not history:
        raise ValueError(f"No price history found for symbol: {symbol}")

    closes = [float(bar.close) for bar in history]
    volumes = [float(bar.volume) for bar in history]
    ma_5 = simple_moving_average(closes, 5)
    ma_10 = simple_moving_average(closes, 10)
    ma_20 = simple_moving_average(closes, 20)
    ma_60 = simple_moving_average(closes, 60)
    volume_ma_5 = simple_moving_average(volumes, 5)
    volume_ma_20 = simple_moving_average(volumes, 20)
    high_20 = rolling_max(closes, 20)
    low_20 = rolling_min(closes, 20)
    macd_hist = macd_histogram(closes)
    rsi_14 = calculate_rsi([{"close": close} for close in closes], period=14)
    inflows, outflows = inflow_outflow(volumes, closes)
    flow_ratio_5 = flow_ratio(volumes, 5)
    flow_momentum_5 = flow_momentum(inflows, 5)
    true_ranges = _compute_true_ranges(history)
    atr_14 = simple_moving_average(true_ranges, 14)

    rows: list[dict[str, Any]] = []
    for index, bar in enumerate(history):
        bar_date = _to_date(bar.date)
        if bar_date < start_date or bar_date > end_date:
            continue

        previous_close = closes[index - 1] if index > 0 else None
        holdings_window = volumes[max(0, index - 19): index + 1]
        prices_window = closes[max(0, index - 19): index + 1]
        chip_distribution_window = (
            chip_distribution(holdings_window, window=min(5, len(holdings_window)))
            if holdings_window else []
        )
        cost_ratio_window = (
            cost_basis_ratio(prices_window, holdings_window)
            if holdings_window and prices_window else []
        )
        intraday_range = float(bar.high) - float(bar.low)
        close_position_20d = _resolve_close_position(
            close=float(bar.close),
            rolling_low=low_20[index],
            rolling_high=high_20[index],
        )
        qizhang_snapshot = _evaluate_qizhang_snapshot(history[: index + 1])

        rows.append({
            "date": bar_date.isoformat(),
            "symbol": str(bar.symbol),
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "volume": float(bar.volume),
            "turnover": (float(bar.turnover) if bar.turnover is not None else None),
            "price_change": (float(bar.close) - previous_close) if previous_close is not None else None,
            "price_change_pct": (
                ((float(bar.close) - previous_close) / previous_close)
                if previous_close not in (None, 0.0) else None
            ),
            "volume_ratio_5": _safe_divide(float(bar.volume), volume_ma_5[index]),
            "volume_ratio_20": _safe_divide(float(bar.volume), volume_ma_20[index]),
            "ma_5": ma_5[index],
            "ma_10": ma_10[index],
            "ma_20": ma_20[index],
            "ma_60": ma_60[index],
            "rolling_high_20": high_20[index],
            "rolling_low_20": low_20[index],
            "macd_histogram": macd_hist[index],
            "rsi_14": rsi_14[index],
            "close_vs_ma_5": _safe_pct_from_base(float(bar.close), ma_5[index]),
            "close_vs_ma_10": _safe_pct_from_base(float(bar.close), ma_10[index]),
            "close_vs_ma_20": _safe_pct_from_base(float(bar.close), ma_20[index]),
            "close_vs_ma_60": _safe_pct_from_base(float(bar.close), ma_60[index]),
            "close_position_20d": close_position_20d,
            "distance_to_rolling_high_20_pct": _safe_pct_from_base(float(bar.close), high_20[index]),
            "distance_to_rolling_low_20_pct": _safe_pct_from_base(float(bar.close), low_20[index]),
            "return_5d": _resolve_period_return(closes, index=index, lookback=5),
            "return_20d": _resolve_period_return(closes, index=index, lookback=20),
            "true_range": true_ranges[index],
            "atr_14": atr_14[index],
            "estimated_inflow": inflows[index],
            "estimated_outflow": outflows[index],
            "flow_ratio_5": flow_ratio_5[index],
            "flow_momentum_5": flow_momentum_5[index],
            "chip_concentration_proxy": chip_concentration(holdings_window) if holdings_window else None,
            "chip_distribution_5_proxy": chip_distribution_window[-1] if chip_distribution_window else None,
            "cost_basis_ratio_proxy": cost_ratio_window[-1] if cost_ratio_window else None,
            "volume_change_pct": _safe_pct_from_base(float(bar.volume), volumes[index - 1] if index > 0 else None),
            "candle_body": float(bar.close) - float(bar.open),
            "candle_body_pct": (_safe_divide(float(bar.close) - float(bar.open), intraday_range) if intraday_range != 0 else 0.0),
            "upper_shadow": float(bar.high) - max(float(bar.open), float(bar.close)),
            "lower_shadow": min(float(bar.open), float(bar.close)) - float(bar.low),
            "intraday_range": intraday_range,
            "intraday_range_pct": _safe_divide(intraday_range, float(bar.open)),
            "qizhang_signal": qizhang_snapshot["signal"],
            "qizhang_score": qizhang_snapshot["score"],
            "qizhang_selected_setup": qizhang_snapshot["selected_setup"],
            "qizhang_sig_anchor": qizhang_snapshot["sig_anchor"],
            "qizhang_sig_explosive": qizhang_snapshot["sig_explosive"],
            "qizhang_close_pos": qizhang_snapshot["close_pos"],
            "qizhang_close_vs_ma60": qizhang_snapshot["close_vs_ma60"],
            "qizhang_net_flow": qizhang_snapshot["net_flow"],
            "qizhang_check_sig_explosive_price_change_pct": qizhang_snapshot["check_sig_explosive_price_change_pct"],
            "qizhang_check_sig_explosive_volume_ratio_5": qizhang_snapshot["check_sig_explosive_volume_ratio_5"],
            "qizhang_check_sig_explosive_volume_ratio_20": qizhang_snapshot["check_sig_explosive_volume_ratio_20"],
            "qizhang_check_sig_explosive_close_pos": qizhang_snapshot["check_sig_explosive_close_pos"],
            "qizhang_check_sig_explosive_close_gt_ma_20": qizhang_snapshot["check_sig_explosive_close_gt_ma_20"],
            "qizhang_check_sig_explosive_net_flow": qizhang_snapshot["check_sig_explosive_net_flow"],
            "qizhang_check_sig_anchor_volume_ratio_5": qizhang_snapshot["check_sig_anchor_volume_ratio_5"],
            "qizhang_check_sig_anchor_volume_ratio_20": qizhang_snapshot["check_sig_anchor_volume_ratio_20"],
            "qizhang_check_sig_anchor_close_pos": qizhang_snapshot["check_sig_anchor_close_pos"],
            "qizhang_check_sig_anchor_close_gt_ma_20": qizhang_snapshot["check_sig_anchor_close_gt_ma_20"],
            "qizhang_check_sig_anchor_net_flow": qizhang_snapshot["check_sig_anchor_net_flow"],
            "qizhang_check_sig_anchor_rsi_14": qizhang_snapshot["check_sig_anchor_rsi_14"],
            "qizhang_check_sig_anchor_macd_histogram": qizhang_snapshot["check_sig_anchor_macd_histogram"],
            "qizhang_check_sig_anchor_close_vs_ma60": qizhang_snapshot["check_sig_anchor_close_vs_ma60"],
        })

    if not rows:
        raise ValueError(
            f"No price history found inside requested date range: symbol={symbol} start={start_date.isoformat()} end={end_date.isoformat()}"
        )

    universe_entry = universe_provider.get_symbol(str(symbol), as_of=end_date) if universe_provider is not None else None
    latest_row = rows[-1]
    first_close = float(rows[0]["close"])
    latest_close = float(latest_row["close"])
    return {
        "mode": "stock_report",
        "symbol": str(symbol),
        "stock_name": str(getattr(universe_entry, "name", "") or ""),
        "exchange": str(getattr(universe_entry, "exchange", "") or ""),
        "market": str(getattr(universe_entry, "market", "") or ""),
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
        "row_count": len(rows),
        "requested_window_days": (end_date - start_date).days + 1,
        "warmup_days": warmup,
        "chip_metrics_are_proxies": True,
        "latest_close": latest_close,
        "latest_volume": float(latest_row["volume"]),
        "period_return_pct": ((latest_close / first_close) - 1.0) if first_close != 0.0 else None,
        "latest_qizhang_signal": latest_row["qizhang_signal"],
        "latest_qizhang_selected_setup": latest_row["qizhang_selected_setup"],
        "rows": rows,
    }


def persist_backtest_result(
    *,
    result: BacktestResult,
    artifact_path: str,
    metadata: dict[str, Any] | None = None,
    write_summary_csv: bool = True,
) -> None:
    path = Path(artifact_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": result.run_id,
        "strategy_name": result.strategy_name,
        "start": _serialize_date_like(result.start),
        "end": _serialize_date_like(result.end),
        "metrics": dict(result.metrics),
        "equity_curve_ref": asdict(result.equity_curve_ref) if result.equity_curve_ref is not None else None,
        "trades": list(result.trades),
        "equity_curve": list(result.equity_curve),
        "metadata": dict(metadata or {}),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    if not write_summary_csv:
        return

    summary_path = path.with_name(f"{path.stem}_summary.csv")
    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["run_id", "strategy_name", "start", "end", *sorted(result.metrics.keys())],
        )
        writer.writeheader()
        writer.writerow(
            {
                "run_id": result.run_id,
                "strategy_name": result.strategy_name,
                "start": _serialize_date_like(result.start),
                "end": _serialize_date_like(result.end),
                **result.metrics,
            }
        )


def _generate_strategy_signals(
    *,
    strategy_name: str,
    parameters: dict[str, Any],
    as_of: DateLike,
    by_symbol_history: dict[Symbol, list[OHLCVBar]],
) -> list[SignalRecord]:
    strategy = _build_strategy(strategy_name, parameters, by_symbol_history=by_symbol_history)
    context = StrategyContext(
        strategy_name=strategy_name,
        as_of=as_of,
        parameters=dict(parameters),
        feature_ref=FeatureFrameRef(
            frame_id=f"frame_{strategy_name}_{_serialize_date_like(as_of)}",
            as_of=as_of,
            symbols=list(by_symbol_history.keys()),
            columns=["open", "high", "low", "close", "volume"],
        ),
    )
    return strategy.generate_signals(context)


def _generate_signals_for_symbol_task(
    *,
    symbol: Symbol,
    history: Sequence[OHLCVBar],
    strategy_name: str,
    parameters: dict[str, Any],
    as_of: date,
) -> list[SignalRecord]:
    if not history:
        return []
    return _generate_strategy_signals(
        strategy_name=strategy_name,
        parameters=parameters,
        as_of=as_of,
        by_symbol_history={symbol: list(history)},
    )


def _generate_signals_for_symbol_chunk_task(
    *,
    chunk_histories: dict[Symbol, list[OHLCVBar]],
    strategy_name: str,
    parameters: dict[str, Any],
    as_of: date,
) -> list[SignalRecord]:
    signals: list[SignalRecord] = []
    for symbol, history in chunk_histories.items():
        if not history:
            continue
        signals.extend(
            _generate_strategy_signals(
                strategy_name=strategy_name,
                parameters=parameters,
                as_of=as_of,
                by_symbol_history={symbol: list(history)},
            )
        )
    return signals


def _process_daily_selection_chunk_task(
    *,
    app_config: AppConfig,
    symbols_chunk: Sequence[Symbol],
    as_of: date,
    strategy_name: str,
    parameters: dict[str, Any],
    lookback_bars: int,
) -> dict[str, list[Any]]:
    ctx = build_app_context(app_config)
    if ctx.market_data_provider is None:
        return {"signals": [], "symbols_with_history": []}
    start = as_of - timedelta(days=max(lookback_bars * 3, lookback_bars + 30))
    fetch_end = as_of + timedelta(days=1)
    bars = ctx.market_data_provider.fetch_ohlcv(list(symbols_chunk), start, fetch_end)
    grouped = _group_bars_by_symbol(bars, as_of=as_of)
    signals: list[SignalRecord] = []
    symbols_with_history: list[Symbol] = []
    for symbol in symbols_chunk:
        history = grouped.get(symbol, [])
        if not history:
            continue
        symbols_with_history.append(symbol)
        signals.extend(
            _generate_strategy_signals(
                strategy_name=strategy_name,
                parameters=parameters,
                as_of=as_of,
                by_symbol_history={symbol: history},
            )
        )
    return {"signals": signals, "symbols_with_history": symbols_with_history}


def _process_daily_selection_chunk_with_provider_task(
    *,
    market_data_provider: MarketDataProvider,
    symbols_chunk: Sequence[Symbol],
    as_of: date,
    strategy_name: str,
    parameters: dict[str, Any],
    start: date,
    fetch_end: date,
) -> dict[str, list[Any]]:
    bars = market_data_provider.fetch_ohlcv(list(symbols_chunk), start, fetch_end)
    grouped = _group_bars_by_symbol(bars, as_of=as_of)
    signals: list[SignalRecord] = []
    symbols_with_history: list[Symbol] = []
    for symbol in symbols_chunk:
        history = grouped.get(symbol, [])
        if not history:
            continue
        symbols_with_history.append(symbol)
        signals.extend(
            _generate_strategy_signals(
                strategy_name=strategy_name,
                parameters=parameters,
                as_of=as_of,
                by_symbol_history={symbol: history},
            )
        )
    return {"signals": signals, "symbols_with_history": symbols_with_history}


def _recover_missing_daily_selection_symbols(
    *,
    market_data_provider: MarketDataProvider,
    missing_symbols: Sequence[Symbol],
    as_of: date,
    strategy_name: str,
    parameters: dict[str, Any],
    start: date,
    fetch_end: date,
) -> dict[str, list[Any]]:
    if not missing_symbols:
        return {"signals": [], "symbols_with_history": []}
    bars = market_data_provider.fetch_ohlcv(list(missing_symbols), start, fetch_end)
    grouped = _group_bars_by_symbol(bars, as_of=as_of)
    signals: list[SignalRecord] = []
    symbols_with_history: list[Symbol] = []
    for symbol in missing_symbols:
        history = grouped.get(symbol, [])
        if not history:
            continue
        symbols_with_history.append(symbol)
        signals.extend(
            _generate_strategy_signals(
                strategy_name=strategy_name,
                parameters=parameters,
                as_of=as_of,
                by_symbol_history={symbol: history},
            )
        )
    return {"signals": signals, "symbols_with_history": symbols_with_history}


def _build_daily_selection_rows(
    *,
    signals: Sequence[SignalRecord],
    selections: Sequence[SelectionRecord],
) -> list[dict[str, Any]]:
    signal_by_symbol = {
        str(signal.symbol).strip(): signal
        for signal in signals
        if str(signal.symbol).strip()
    }
    rows: list[dict[str, Any]] = []
    for selection in selections:
        symbol = str(selection.symbol).strip()
        signal = signal_by_symbol.get(symbol)
        criteria = dict(signal.metadata) if signal is not None else {}
        row: dict[str, Any] = {
            "symbol": selection.symbol,
            "timestamp": _serialize_date_like(selection.timestamp),
            "rank": selection.rank,
            "weight": selection.weight,
            "reason": selection.reason,
            "signal": (signal.signal if signal is not None else ""),
            "score": (signal.score if signal is not None else ""),
            "criteria": criteria,
            "criteria_json": json.dumps(criteria, ensure_ascii=False, sort_keys=True),
        }
        for key, value in criteria.items():
            row[f"criteria_{key}"] = value
        rows.append(row)
    return rows


def _build_daily_signal_rows(
    *,
    signals: Sequence[SignalRecord],
    selections: Sequence[SelectionRecord],
    stock_name_by_symbol: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    selection_by_symbol = {
        str(selection.symbol).strip(): selection
        for selection in selections
        if str(selection.symbol).strip()
    }
    rows: list[dict[str, Any]] = []
    buy_signals = [
        signal
        for signal in signals
        if str(signal.signal).strip().lower() == "buy" and str(signal.symbol).strip()
    ]
    for signal in buy_signals:
        symbol = str(signal.symbol).strip()
        selection = selection_by_symbol.get(symbol)
        criteria = dict(signal.metadata)
        row: dict[str, Any] = {
            "symbol": signal.symbol,
            "stock_name": (stock_name_by_symbol or {}).get(symbol, ""),
            "timestamp": _serialize_date_like(signal.timestamp),
            "rank": selection.rank if selection is not None else "",
            "weight": selection.weight if selection is not None else "",
            "reason": selection.reason if selection is not None else signal.signal,
            "signal": signal.signal,
            "score": signal.score,
            "selected": selection is not None,
            "criteria": criteria,
        }
        for key, value in criteria.items():
            row[f"criteria_{key}"] = value
        rows.append(row)
    return rows


def _resolve_selection_csv_fieldnames(rows: Sequence[dict[str, Any]]) -> list[str]:
    base_fields = ["symbol", "stock_name", "timestamp", "rank", "weight", "reason", "signal", "score", "selected"]
    dynamic_fields = sorted({
        key
        for row in rows
        for key in row.keys()
        if key.startswith("criteria_")
    })
    return [*base_fields, *dynamic_fields]


def _resolve_reentry_cooldown_days(strategy_name: str, parameters: dict[str, Any]) -> int:
    entry_config = parameters.get("entry")
    if isinstance(entry_config, dict):
        raw_days = entry_config.get("reentry_cooldown_days")
        if isinstance(raw_days, (int, float)):
            return max(0, int(raw_days))

    normalized = canonicalize_strategy_name(strategy_name)
    if normalized in {"pullback_trend_compression", "pullback", "pullback_trend_120d_optimized"}:
        return 30
    return 0


def _resolve_cooldown_apply_on(strategy_name: str, parameters: dict[str, Any]) -> str:
    entry_config = parameters.get("entry")
    if isinstance(entry_config, dict):
        raw_mode = entry_config.get("cooldown_apply_on")
        if isinstance(raw_mode, str):
            normalized = raw_mode.strip().lower()
            if normalized in {"any_exit", "stop_loss"}:
                return normalized

    normalized_strategy = canonicalize_strategy_name(strategy_name)
    if normalized_strategy in {"pullback_trend_compression", "pullback", "pullback_trend_120d_optimized"}:
        return "any_exit"
    return "any_exit"


def _resolve_position_cash(strategy_name: str, parameters: dict[str, Any]) -> float | None:
    entry_config = parameters.get("entry")
    if isinstance(entry_config, dict):
        raw_fallback_cash = entry_config.get("fallback_position_cash")
        if isinstance(raw_fallback_cash, (int, float)):
            fallback_value = float(raw_fallback_cash)
            if fallback_value > 0.0:
                return fallback_value

        raw_cash = entry_config.get("position_cash")
        if isinstance(raw_cash, (int, float)):
            value = float(raw_cash)
            return value if value > 0.0 else None

    normalized = canonicalize_strategy_name(strategy_name)
    if normalized in {"pullback_trend_compression", "pullback", "pullback_trend_120d_optimized"}:
        return 100_000.0
    return None


def _apply_position_cash_sizing(
    *,
    orders: Sequence[OrderIntent],
    current_bar: OHLCVBar | None,
    position_cash: float | None,
    risk_budget_cash: float | None = None,
    stop_distance: float | None = None,
) -> list[OrderIntent]:
    if current_bar is None:
        return list(orders)

    close_price = float(current_bar.close)
    if close_price <= 0.0:
        return list(orders)

    sized_orders: list[OrderIntent] = []
    for order in orders:
        if order.side != "buy":
            sized_orders.append(order)
            continue

        if (
            (risk_budget_cash is None or risk_budget_cash <= 0.0 or stop_distance is None or stop_distance <= 0.0)
            and (position_cash is None or position_cash <= 0.0)
        ):
            sized_orders.append(order)
            continue

        quantity = 0
        if (
            risk_budget_cash is not None
            and risk_budget_cash > 0.0
            and stop_distance is not None
            and stop_distance > 0.0
        ):
            quantity = int(risk_budget_cash // stop_distance)
        elif position_cash is not None and position_cash > 0.0:
            quantity = int(position_cash // close_price)

        if quantity <= 0:
            continue

        sized_orders.append(
            OrderIntent(
                symbol=order.symbol,
                timestamp=order.timestamp,
                side=order.side,
                quantity=float(quantity),
                order_type=order.order_type,
                limit_price=order.limit_price,
            )
        )

    return sized_orders


def _resolve_risk_budget_cash(strategy_name: str, parameters: dict[str, Any]) -> float | None:
    entry_config = parameters.get("entry")
    if not isinstance(entry_config, dict):
        return None

    raw_risk_budget_pct = entry_config.get("risk_budget_pct")
    if not isinstance(raw_risk_budget_pct, (int, float)):
        return None
    risk_budget_pct = float(raw_risk_budget_pct)
    if risk_budget_pct <= 0.0:
        return None

    base_cash = _resolve_position_cash(strategy_name, parameters)
    if base_cash is None or base_cash <= 0.0:
        return None
    return base_cash * risk_budget_pct


def _resolve_stop_distance(
    *,
    strategy_name: str,
    parameters: dict[str, Any],
    history: Sequence[OHLCVBar],
) -> float | None:
    entry_config = parameters.get("entry")
    if not isinstance(entry_config, dict):
        return None

    stop_distance_mode = str(entry_config.get("stop_distance_mode", "atr_initial_stop")).strip().lower()
    if stop_distance_mode != "atr_initial_stop":
        return None

    normalized = canonicalize_strategy_name(strategy_name)
    if normalized != "pullback_trend_120d_optimized":
        return None

    exit_config = parameters.get("exit") if isinstance(parameters.get("exit"), dict) else {}
    atr_period = int(exit_config.get("atr_period", 14))
    atr_multiplier = float(exit_config.get("atr_stop_mult", 2.5))
    if atr_period <= 0 or atr_multiplier <= 0.0 or len(history) < atr_period:
        return None

    true_ranges: list[float] = []
    for offset in range(atr_period):
        bar_index = len(history) - atr_period + offset
        current = history[bar_index]
        previous_close = history[bar_index - 1].close if bar_index > 0 else None
        if previous_close is None:
            tr = current.high - current.low
        else:
            tr = max(
                current.high - current.low,
                abs(current.high - previous_close),
                abs(current.low - previous_close),
            )
        true_ranges.append(float(tr))

    atr = sum(true_ranges) / len(true_ranges)
    if atr <= 0.0:
        return None
    return atr * atr_multiplier


def _build_strategy(
    strategy_name: str,
    parameters: dict[str, Any],
    *,
    by_symbol_history: dict[Symbol, list[OHLCVBar]],
):
    normalized = canonicalize_strategy_name(strategy_name)
    if normalized in {"pullback_trend_compression", "pullback"}:
        return PullbackTrendCompressionStrategy(
            feature_source=lambda _feature_ref: {
                symbol: _build_ohlcv_payload(history)
                for symbol, history in by_symbol_history.items()
            }
        )

    if normalized == "pullback_trend_120d_optimized":
        return PullbackTrend120dOptimizedStrategy(
            feature_source=lambda _feature_ref: {
                symbol: _build_ohlcv_payload(history)
                for symbol, history in by_symbol_history.items()
            },
            config={
                key: value
                for key, value in parameters.items()
                if key in {
                    "basic",
                    "entry",
                    "liquidity",
                    "ma",
                    "pullback",
                    "volume",
                    "chip",
                    "margin",
                    "borrow",
                    "atr_pullback",
                    "price_contraction",
                    "close_strength",
                    "short_momentum",
                    "chip_scoring",
                    "exit",
                }
            },
        )

    if normalized == "qizhang_selection_strategy":
        return QizhangSignalStrategy(
            history_source=lambda: {
                symbol: list(history)
                for symbol, history in by_symbol_history.items()
            }
        )

    if normalized == "qizhang_improve_strategy":
        return QizhangSignalStrategy(
            history_source=lambda: {
                symbol: list(history)
                for symbol, history in by_symbol_history.items()
            },
            profile="improve",
        )

    if normalized == "qizhang_improve_strategy_v15":
        return QizhangSignalStrategy(
            history_source=lambda: {
                symbol: list(history)
                for symbol, history in by_symbol_history.items()
            },
            profile="improve_v15",
        )

    if normalized in {"ma_bullish_stack", "bullish_stack", "ma_stack", "bull_stack"}:
        short_window = int(parameters.get("short_window", parameters.get("short", 5)))
        mid_window = int(parameters.get("mid_window", parameters.get("mid", 20)))
        long_window = int(parameters.get("long_window", parameters.get("long", 60)))
        return MovingAverageBullishStackStrategy(
            feature_source=lambda _feature_ref: {
                symbol: [bar.close for bar in history]
                for symbol, history in by_symbol_history.items()
            },
            short_window=short_window,
            mid_window=mid_window,
            long_window=long_window,
        )

    short_window = int(parameters.get("short_window", parameters.get("short", 5)))
    long_window = int(parameters.get("long_window", parameters.get("long", 20)))
    return MovingAverageCrossoverStrategy(
        feature_source=lambda _feature_ref: {
            symbol: [bar.close for bar in history]
            for symbol, history in by_symbol_history.items()
        },
        short_window=short_window,
        long_window=long_window,
    )


def _build_ohlcv_payload(history: Sequence[OHLCVBar]) -> dict[str, list[float] | str]:
    return {
        "interval": "1d",
        "open": [bar.open for bar in history],
        "high": [bar.high for bar in history],
        "low": [bar.low for bar in history],
        "close": [bar.close for bar in history],
        "volume": [bar.volume for bar in history],
    }


def _group_bars_by_symbol(bars: Sequence[OHLCVBar], *, as_of: date) -> dict[Symbol, list[OHLCVBar]]:
    grouped: dict[Symbol, list[OHLCVBar]] = {}
    for bar in bars:
        if _to_date(bar.date) > as_of:
            continue
        grouped.setdefault(bar.symbol, []).append(bar)

    for history in grouped.values():
        history.sort(key=lambda item: _to_date(item.date))

    return grouped


def _safe_divide(numerator: float, denominator: float | None) -> float | None:
    if denominator in (None, 0.0):
        return None
    return numerator / denominator


def _safe_pct_from_base(current: float, base: float | None) -> float | None:
    if base in (None, 0.0):
        return None
    return (current / base) - 1.0


def _resolve_period_return(values: list[float], *, index: int, lookback: int) -> float | None:
    if lookback <= 0 or index < lookback:
        return None
    base = values[index - lookback]
    if base == 0.0:
        return None
    return (values[index] / base) - 1.0


def _resolve_close_position(*, close: float, rolling_low: float | None, rolling_high: float | None) -> float | None:
    if rolling_low is None or rolling_high is None:
        return None
    price_range = rolling_high - rolling_low
    if price_range == 0.0:
        return 0.5
    return (close - rolling_low) / price_range


def _compute_true_ranges(history: Sequence[OHLCVBar]) -> list[float]:
    true_ranges: list[float] = []
    for index, bar in enumerate(history):
        previous_close = float(history[index - 1].close) if index > 0 else None
        if previous_close is None:
            tr = float(bar.high) - float(bar.low)
        else:
            tr = max(
                float(bar.high) - float(bar.low),
                abs(float(bar.high) - previous_close),
                abs(float(bar.low) - previous_close),
            )
        true_ranges.append(float(tr))
    return true_ranges


def _evaluate_qizhang_snapshot(history: Sequence[OHLCVBar]) -> dict[str, Any]:
    strategy = QizhangSignalStrategy(history_source=lambda: {})
    _, metadata, signal, score = strategy._evaluate_symbol(list(history), "qizhang_selection_strategy")
    return {
        "signal": signal,
        "score": score,
        "selected_setup": metadata.get("selected_setup", ""),
        "sig_anchor": metadata.get("sig_anchor", False),
        "sig_explosive": metadata.get("sig_explosive", False),
        "close_pos": metadata.get("close_pos"),
        "close_vs_ma60": metadata.get("close_vs_ma60"),
        "net_flow": metadata.get("net_flow"),
        "check_sig_explosive_price_change_pct": metadata.get("check_sig_explosive_price_change_pct", False),
        "check_sig_explosive_volume_ratio_5": metadata.get("check_sig_explosive_volume_ratio_5", False),
        "check_sig_explosive_volume_ratio_20": metadata.get("check_sig_explosive_volume_ratio_20", False),
        "check_sig_explosive_close_pos": metadata.get("check_sig_explosive_close_pos", False),
        "check_sig_explosive_close_gt_ma_20": metadata.get("check_sig_explosive_close_gt_ma_20", False),
        "check_sig_explosive_net_flow": metadata.get("check_sig_explosive_net_flow", False),
        "check_sig_anchor_volume_ratio_5": metadata.get("check_sig_anchor_volume_ratio_5", False),
        "check_sig_anchor_volume_ratio_20": metadata.get("check_sig_anchor_volume_ratio_20", False),
        "check_sig_anchor_close_pos": metadata.get("check_sig_anchor_close_pos", False),
        "check_sig_anchor_close_gt_ma_20": metadata.get("check_sig_anchor_close_gt_ma_20", False),
        "check_sig_anchor_net_flow": metadata.get("check_sig_anchor_net_flow", False),
        "check_sig_anchor_rsi_14": metadata.get("check_sig_anchor_rsi_14", False),
        "check_sig_anchor_macd_histogram": metadata.get("check_sig_anchor_macd_histogram", False),
        "check_sig_anchor_close_vs_ma60": metadata.get("check_sig_anchor_close_vs_ma60", False),
    }


def _to_date(value: DateLike) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if "T" in value:
        return datetime.fromisoformat(value).date()
    return date.fromisoformat(value)


def _serialize_date_like(value: DateLike) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _create_progress_bar(*, total: int, desc: str, unit: str):
    if tqdm is None:
        return None
    return tqdm(
        total=total,
        desc=desc,
        unit=unit,
        file=sys.stdout,
        dynamic_ncols=True,
        mininterval=0.2,
        leave=True,
        ascii=True,
    )


def _create_progress_iterable(*, iterable, desc: str, unit: str):
    if tqdm is None:
        return iterable
    return tqdm(
        iterable,
        desc=desc,
        unit=unit,
        file=sys.stdout,
        dynamic_ncols=True,
        mininterval=0.2,
        leave=True,
        ascii=True,
    )


def _resolve_parallel_chunk_size(*, symbol_count: int, worker_count: int) -> int:
    if symbol_count <= 0:
        return 1
    if worker_count <= 1:
        return 1
    target_chunks = max(worker_count * 4, worker_count)
    return max(1, min(25, (symbol_count + target_chunks - 1) // target_chunks))


def _chunk_symbols(symbols: Sequence[Symbol], *, chunk_size: int) -> list[list[Symbol]]:
    if chunk_size <= 1:
        return [[symbol] for symbol in symbols]
    return [list(symbols[index:index + chunk_size]) for index in range(0, len(symbols), chunk_size)]


def _resolve_daily_selection_parallel_mode(
    *,
    app_config: AppConfig | None,
    requested_workers: int,
    symbol_count: int,
) -> tuple[str, int]:
    if requested_workers <= 1 or symbol_count <= 1:
        return ("single-process", 1)
    market_provider = ""
    app_data = getattr(app_config, "data", None) if app_config is not None else None
    if app_data is not None:
        market_provider = str(getattr(app_data, "market_provider", "") or "").strip().lower()
    if market_provider == "yfinance_ohlcv":
        return ("thread-chunk-yfinance", min(requested_workers, 8))
    return ("process-chunk", requested_workers)
