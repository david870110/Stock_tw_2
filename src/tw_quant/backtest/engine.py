"""Concrete backtest engine implementations."""

from datetime import date, datetime, timedelta
from typing import Callable, Iterator, Sequence

from src.tw_quant.backtest.exits import (
    ExitEvaluationContext,
    ExitRule,
    OpenPositionState,
    PositionClosePolicy,
    PriorityClosePolicy,
)
from src.tw_quant.core.types import DateLike, Symbol
from src.tw_quant.schema.models import (
    BacktestResult,
    FillRecord,
    OHLCVBar,
    OrderIntent,
    PortfolioSnapshot,
)


def _to_date(d: DateLike) -> date:
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return date.fromisoformat(d)


def _iter_dates(start: date, end: date) -> Iterator[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


class SimpleExecutionModel:
    """Fills every OrderIntent at close price; no slippage, no fee."""

    def __init__(self, data_provider: Callable[[Symbol, DateLike], OHLCVBar | None]) -> None:
        self._data_provider = data_provider

    def execute(self, intents: Sequence[OrderIntent], timestamp: DateLike) -> list[FillRecord]:
        fills: list[FillRecord] = []
        for intent in intents:
            bar = self._data_provider(intent.symbol, timestamp)
            if bar is None:
                continue
            fills.append(
                FillRecord(
                    symbol=intent.symbol,
                    timestamp=timestamp,
                    side=intent.side,
                    quantity=intent.quantity,
                    price=bar.close,
                    fee=0.0,
                )
            )
        return fills


class InMemoryPortfolioBook:
    """Tracks cash, holdings, and last prices in memory."""

    def __init__(self, initial_cash: float) -> None:
        self._cash: float = initial_cash
        self._holdings: dict[Symbol, float] = {}
        self._last_prices: dict[Symbol, float] = {}

    def apply_fills(self, fills: Sequence[FillRecord]) -> None:
        for fill in fills:
            self._last_prices[fill.symbol] = fill.price
            if fill.side == "buy":
                self._holdings[fill.symbol] = self._holdings.get(fill.symbol, 0.0) + fill.quantity
                self._cash -= fill.quantity * fill.price + fill.fee
            else:
                self._holdings[fill.symbol] = self._holdings.get(fill.symbol, 0.0) - fill.quantity
                self._cash += fill.quantity * fill.price - fill.fee

    def snapshot(self, timestamp: DateLike) -> PortfolioSnapshot:
        holdings_value = sum(
            qty * self._last_prices.get(sym, 0.0)
            for sym, qty in self._holdings.items()
        )
        nav = self._cash + holdings_value
        return PortfolioSnapshot(
            timestamp=timestamp,
            cash=self._cash,
            holdings=dict(self._holdings),
            nav=nav,
        )


class SymbolBacktestEngine:
    """Per-symbol backtest engine that drives a single symbol over a date range."""

    def __init__(
        self,
        symbol: Symbol,
        data_provider: Callable[[Symbol, DateLike], OHLCVBar | None],
        execution_model,
        portfolio_book,
        signal_source: Callable[[Symbol, DateLike], list[OrderIntent]],
        run_id: str,
        strategy_name: str = "",
        exit_rules: Sequence[ExitRule] | None = None,
        close_policy: PositionClosePolicy | None = None,
        reentry_cooldown_days: int = 0,
        cooldown_apply_on: str = "any_exit",
    ) -> None:
        self._symbol = symbol
        self._data_provider = data_provider
        self._execution_model = execution_model
        self._portfolio_book = portfolio_book
        self._signal_source = signal_source
        self._run_id = run_id
        self._strategy_name = strategy_name
        self._exit_rules = tuple(exit_rules or ())
        self._close_policy = close_policy or PriorityClosePolicy()
        self._reentry_cooldown_days = max(0, int(reentry_cooldown_days))
        normalized_cooldown_mode = cooldown_apply_on.strip().lower()
        if normalized_cooldown_mode not in {"any_exit", "stop_loss"}:
            normalized_cooldown_mode = "any_exit"
        self._cooldown_apply_on = normalized_cooldown_mode

    def _filter_reentry_intents(
        self,
        timestamp: date,
        intents: Sequence[OrderIntent],
        position: OpenPositionState | None,
        last_exit_date: date | None,
        last_exit_cause: str | None,
    ) -> list[OrderIntent]:
        if self._reentry_cooldown_days <= 0:
            return list(intents)

        if position is not None:
            opened_at = _to_date(position.opened_at)
            held_days = (timestamp - opened_at).days
            if held_days >= self._reentry_cooldown_days:
                return list(intents)
            return [
                intent
                for intent in intents
                if not (intent.symbol == self._symbol and intent.side == "buy")
            ]

        if last_exit_date is None:
            return list(intents)

        if self._cooldown_apply_on == "stop_loss" and last_exit_cause != "stop_loss":
            return list(intents)

        cooldown_elapsed = (timestamp - last_exit_date).days
        if cooldown_elapsed >= self._reentry_cooldown_days:
            return list(intents)

        return [
            intent
            for intent in intents
            if not (intent.symbol == self._symbol and intent.side == "buy")
        ]

    def _build_close_intent(
        self, timestamp: DateLike, position: OpenPositionState
    ) -> OrderIntent:
        return OrderIntent(
            symbol=self._symbol,
            timestamp=timestamp,
            side="sell",
            quantity=position.quantity,
        )

    def _advance_position_state_for_bar(
        self,
        position: OpenPositionState | None,
        bar: OHLCVBar | None,
    ) -> OpenPositionState | None:
        if position is None or bar is None:
            return position

        return OpenPositionState(
            symbol=position.symbol,
            quantity=position.quantity,
            entry_price=position.entry_price,
            opened_at=position.opened_at,
            holding_bar_count=position.holding_bar_count + 1,
        )

    def _update_position_state(
        self,
        position: OpenPositionState | None,
        fills: Sequence[FillRecord],
    ) -> OpenPositionState | None:
        next_position = position
        for fill in fills:
            if fill.symbol != self._symbol:
                continue
            if fill.side == "buy":
                if next_position is None:
                    next_position = OpenPositionState(
                        symbol=fill.symbol,
                        quantity=fill.quantity,
                        entry_price=fill.price,
                        opened_at=fill.timestamp,
                        holding_bar_count=0,
                    )
                    continue

                total_quantity = next_position.quantity + fill.quantity
                average_entry = (
                    next_position.entry_price * next_position.quantity
                    + fill.price * fill.quantity
                ) / total_quantity
                next_position = OpenPositionState(
                    symbol=next_position.symbol,
                    quantity=total_quantity,
                    entry_price=average_entry,
                    opened_at=next_position.opened_at,
                    holding_bar_count=next_position.holding_bar_count,
                )
                continue

            if next_position is None:
                continue

            remaining_quantity = next_position.quantity - fill.quantity
            if remaining_quantity <= 0.0:
                next_position = None
                continue

            next_position = OpenPositionState(
                symbol=next_position.symbol,
                quantity=remaining_quantity,
                entry_price=next_position.entry_price,
                opened_at=next_position.opened_at,
                holding_bar_count=next_position.holding_bar_count,
            )

        return next_position

    def run(self, start: DateLike, end: DateLike) -> BacktestResult:
        start_date = _to_date(start)
        end_date = _to_date(end)

        initial_nav = self._portfolio_book.snapshot(start_date).nav

        total_fills: list[FillRecord] = []
        snapshots: list[PortfolioSnapshot] = []
        trade_rows: list[dict[str, object]] = []
        equity_rows: list[dict[str, object]] = []
        position: OpenPositionState | None = None
        last_exit_date: date | None = None
        last_exit_cause: str | None = None
        stock_id = self._symbol.split(".", 1)[0]

        for current_date in _iter_dates(start_date, end_date):
            current_bar = self._data_provider(self._symbol, current_date)
            intents = self._signal_source(self._symbol, current_date)
            executable_intents = self._filter_reentry_intents(
                current_date,
                intents,
                position,
                last_exit_date,
                last_exit_cause,
            )
            selected_trigger = None

            if self._exit_rules and position is not None and current_bar is not None:
                context = ExitEvaluationContext(
                    symbol=self._symbol,
                    timestamp=current_date,
                    bar=current_bar,
                    position=position,
                    intents=intents,
                )
                triggers = [
                    trigger
                    for rule in self._exit_rules
                    if (trigger := rule.evaluate(context)) is not None
                ]
                selected_trigger = self._close_policy.select_trigger(triggers)
                if selected_trigger is not None:
                    executable_intents = [self._build_close_intent(current_date, position)]

            fills = self._execution_model.execute(executable_intents, current_date)

            active_position = position
            for fill in fills:
                if fill.symbol != self._symbol or fill.side != "sell":
                    continue

                last_exit_date = current_date
                last_exit_cause = selected_trigger.cause if selected_trigger is not None else "signal_exit"

                entry_price = active_position.entry_price if active_position is not None else fill.price
                entry_date = _to_date(active_position.opened_at) if active_position is not None else current_date
                holding_days = (
                    active_position.holding_bar_count
                    if active_position is not None
                    else (current_date - entry_date).days
                )
                denominator = entry_price if entry_price != 0.0 else 1.0
                return_pct = (fill.price - entry_price) / denominator

                trade_rows.append(
                    {
                        "stock_id": stock_id,
                        "stock_name": "",
                        "signal_date": entry_date.isoformat(),
                        "entry_date": entry_date.isoformat(),
                        "entry_price": float(entry_price),
                        "exit_date": current_date.isoformat(),
                        "exit_price": float(fill.price),
                        "holding_days": int(holding_days),
                        "exit_reason": last_exit_cause,
                        "return_pct": float(return_pct),
                        "exit_fraction": 1.0,
                        "exit_shares": float(fill.quantity),
                        "is_partial_exit": False,
                    }
                )

            total_fills.extend(fills)
            self._portfolio_book.apply_fills(fills)
            position = self._update_position_state(position, fills)
            position = self._advance_position_state_for_bar(position, current_bar)
            snap = self._portfolio_book.snapshot(current_date)
            snapshots.append(snap)
            equity_rows.append(
                {
                    "date": current_date.isoformat(),
                    "equity": float(snap.nav / (initial_nav if initial_nav != 0.0 else 1.0)),
                    "pos_count": sum(1 for quantity in snap.holdings.values() if quantity > 0.0),
                    "bench_equity": "",
                }
            )

        if position is not None:
            entry_date = _to_date(position.opened_at)
            trade_rows.append(
                {
                    "stock_id": stock_id,
                    "stock_name": "",
                    "signal_date": entry_date.isoformat(),
                    "entry_date": entry_date.isoformat(),
                    "entry_price": float(position.entry_price),
                    "exit_date": "",
                    "exit_price": "",
                    "holding_days": "",
                    "exit_reason": "",
                    "return_pct": "",
                    "exit_fraction": "",
                    "exit_shares": "",
                    "is_partial_exit": "",
                }
            )

        final_nav = snapshots[-1].nav if snapshots else initial_nav
        total_return = (final_nav - initial_nav) / (initial_nav if initial_nav != 0.0 else 1.0)
        num_trades = float(len(total_fills))

        return BacktestResult(
            run_id=self._run_id,
            strategy_name=self._strategy_name,
            start=start,
            end=end,
            metrics={
                "final_nav": final_nav,
                "total_return": total_return,
                "num_trades": num_trades,
            },
            equity_curve_ref=None,
            trades=trade_rows,
            equity_curve=equity_rows,
        )
