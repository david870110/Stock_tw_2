"""Execution workflows for batch backtests and daily market selection."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Sequence

from src.tw_quant.backtest import InMemoryPortfolioBook, SimpleExecutionModel, SymbolBacktestEngine
from src.tw_quant.backtest.exit_builder import build_close_policy, build_exit_rules, canonicalize_strategy_name
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
from src.tw_quant.strategy.interfaces import StrategyContext
from src.tw_quant.strategy.technical.ma_bullish_stack import (
    MovingAverageBullishStackStrategy,
)
from src.tw_quant.strategy.technical.ma_crossover import MovingAverageCrossoverStrategy
from src.tw_quant.strategy.technical.pullback_trend_compression import (
    PullbackTrend120dOptimizedStrategy,
    PullbackTrendCompressionStrategy,
)
from src.tw_quant.universe.interfaces import UniverseProvider
from src.tw_quant.universe.models import ListingStatus


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
    ) -> None:
        self._universe_provider = universe_provider
        self._market_data_provider = market_data_provider
        self._output_base = output_base

    def run(
        self,
        *,
        as_of: DateLike,
        strategy_name: str,
        strategy_parameters: dict[str, Any] | None = None,
        lookback_bars: int = 220,
        selection_config: SelectionConfig | None = None,
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

        start = as_of_date - timedelta(days=max(lookback_bars * 3, lookback_bars + 30))
        fetch_end = as_of_date + timedelta(days=1)
        bars = self._market_data_provider.fetch_ohlcv(symbols, start, fetch_end)
        grouped = _group_bars_by_symbol(bars, as_of=as_of_date)

        signals: list[SignalRecord] = []
        parameters = dict(strategy_parameters or {})

        # Progress bar integration
        show_progress = False
        try:
            from tqdm import tqdm
            show_progress = len(symbols) > 1
        except ImportError:
            show_progress = False

        iterator = symbols
        progress_bar = None
        if show_progress:
            progress_bar = tqdm(symbols, desc="Daily Selection", unit="symbol")
            iterator = progress_bar

        for symbol in iterator:
            history = grouped.get(symbol, [])
            if not history:
                continue
            symbol_signals = _generate_strategy_signals(
                strategy_name=strategy_name,
                parameters=parameters,
                as_of=as_of_date,
                by_symbol_history={symbol: history},
            )
            signals.extend(symbol_signals)
            if progress_bar:
                progress_bar.update(1)

        if progress_bar:
            progress_bar.close()
        for symbol in symbols:
            history = grouped.get(symbol, [])
            if not history:
                continue
            symbol_signals = _generate_strategy_signals(
                strategy_name=strategy_name,
                parameters=parameters,
                as_of=as_of_date,
                by_symbol_history={symbol: history},
            )
            signals.extend(symbol_signals)

        config = selection_config or SelectionConfig(signal_type_whitelist=["buy"], min_score=0.0, top_n=30)
        selections = SelectionPipeline(config).run(signals, as_of_date)
        self._persist_daily_selection(
            as_of=as_of_date,
            strategy_name=strategy_name,
            signals=signals,
            selections=selections,
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
    ) -> None:
        output_dir = Path(self._output_base) / "tw_quant" / "daily_selection" / as_of.isoformat()
        output_dir.mkdir(parents=True, exist_ok=True)

        payload = {
            "as_of": as_of.isoformat(),
            "strategy_name": strategy_name,
            "signal_count": len(signals),
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
            "selections": [
                {
                    "symbol": selection.symbol,
                    "timestamp": _serialize_date_like(selection.timestamp),
                    "rank": selection.rank,
                    "weight": selection.weight,
                    "reason": selection.reason,
                }
                for selection in selections
            ],
        }

        json_path = output_dir / f"{strategy_name}.json"
        json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

        csv_path = output_dir / f"{strategy_name}.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["symbol", "timestamp", "rank", "weight", "reason"])
            writer.writeheader()
            for row in payload["selections"]:
                writer.writerow(row)


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
