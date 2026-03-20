"""Exit-rule contracts and concrete policies for symbol backtests."""

from collections import deque
from dataclasses import dataclass, field
from typing import Protocol, Sequence

from src.tw_quant.core.types import DateLike, Symbol
from src.tw_quant.schema.models import OHLCVBar, OrderIntent


@dataclass(slots=True, frozen=True)
class OpenPositionState:
    symbol: Symbol
    quantity: float
    entry_price: float
    opened_at: DateLike
    holding_bar_count: int = 0


@dataclass(slots=True, frozen=True)
class ExitEvaluationContext:
    symbol: Symbol
    timestamp: DateLike
    bar: OHLCVBar
    position: OpenPositionState
    intents: Sequence[OrderIntent] = field(default_factory=tuple)


@dataclass(slots=True, frozen=True)
class ExitTrigger:
    cause: str
    timestamp: DateLike


class ExitRule(Protocol):
    def evaluate(self, context: ExitEvaluationContext) -> ExitTrigger | None:
        """Return an exit trigger when the rule should close the current position."""


class PositionClosePolicy(Protocol):
    def select_trigger(self, triggers: Sequence[ExitTrigger]) -> ExitTrigger | None:
        """Choose a single trigger when multiple exit conditions fire together."""


class SignalExitRule:
    """Closes when the current step includes any sell intent for the symbol."""

    def evaluate(self, context: ExitEvaluationContext) -> ExitTrigger | None:
        for intent in context.intents:
            if intent.symbol == context.symbol and intent.side == "sell":
                return ExitTrigger(cause="signal_exit", timestamp=context.timestamp)
        return None


class StopLossRule:
    """Closes when the bar close breaches the configured loss threshold."""

    def __init__(self, threshold_pct: float) -> None:
        if threshold_pct <= 0.0:
            raise ValueError("threshold_pct must be positive")
        self._threshold_pct = threshold_pct

    def evaluate(self, context: ExitEvaluationContext) -> ExitTrigger | None:
        stop_price = context.position.entry_price * (1.0 - self._threshold_pct)
        if context.bar.close <= stop_price:
            return ExitTrigger(cause="stop_loss", timestamp=context.timestamp)
        return None


class TakeProfitRule:
    """Closes when the bar close reaches the configured profit threshold."""

    def __init__(self, threshold_pct: float) -> None:
        if threshold_pct <= 0.0:
            raise ValueError("threshold_pct must be positive")
        self._threshold_pct = threshold_pct

    def evaluate(self, context: ExitEvaluationContext) -> ExitTrigger | None:
        take_profit_price = context.position.entry_price * (1.0 + self._threshold_pct)
        # Use small epsilon for floating-point comparison
        if context.bar.close >= take_profit_price - 1e-9:
            return ExitTrigger(cause="take_profit", timestamp=context.timestamp)
        return None


class MaxHoldingPeriodRule:
    """Closes once the held-bar count reaches the configured limit."""

    def __init__(self, max_holding_days: int) -> None:
        if max_holding_days <= 0:
            raise ValueError("max_holding_days must be positive")
        self._max_holding_days = max_holding_days

    def evaluate(self, context: ExitEvaluationContext) -> ExitTrigger | None:
        if context.position.holding_bar_count >= self._max_holding_days:
            return ExitTrigger(cause="max_holding_period", timestamp=context.timestamp)
        return None


class AtrInitialStopRule:
    """Closes when close breaches entry minus ATR-multiple initial stop."""

    def __init__(self, *, atr_window: int = 14, atr_multiplier: float = 2.0) -> None:
        if atr_window <= 0:
            raise ValueError("atr_window must be positive")
        if atr_multiplier <= 0.0:
            raise ValueError("atr_multiplier must be positive")
        self._atr_window = atr_window
        self._atr_multiplier = atr_multiplier
        self._true_ranges: deque[float] = deque(maxlen=atr_window)
        self._previous_close: float | None = None
        self._entry_marker: tuple[DateLike, float] | None = None
        self._initial_stop_price: float | None = None

    def evaluate(self, context: ExitEvaluationContext) -> ExitTrigger | None:
        current_bar = context.bar
        tr = self._true_range(
            high=current_bar.high,
            low=current_bar.low,
            previous_close=self._previous_close,
        )
        self._true_ranges.append(tr)
        self._previous_close = current_bar.close

        current_marker = (context.position.opened_at, context.position.entry_price)
        if self._entry_marker != current_marker:
            self._entry_marker = current_marker
            atr = self._average_true_range()
            self._initial_stop_price = context.position.entry_price - (atr * self._atr_multiplier)

        if self._initial_stop_price is None:
            return None

        if current_bar.close <= self._initial_stop_price:
            return ExitTrigger(cause="stop_loss", timestamp=context.timestamp)
        return None

    def _average_true_range(self) -> float:
        if not self._true_ranges:
            return 0.0
        return sum(self._true_ranges) / len(self._true_ranges)

    @staticmethod
    def _true_range(*, high: float, low: float, previous_close: float | None) -> float:
        if previous_close is None:
            return high - low
        return max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close),
        )


class TrendBreakExitRule:
    """Closes on trend break: N closes below MA60 or one close below MA120."""

    def __init__(
        self,
        *,
        ma60_window: int = 60,
        ma120_window: int = 120,
        two_close_below_ma60: int = 2,
    ) -> None:
        if ma60_window <= 0 or ma120_window <= 0:
            raise ValueError("moving-average windows must be positive")
        if two_close_below_ma60 <= 0:
            raise ValueError("two_close_below_ma60 must be positive")

        self._ma60_window = ma60_window
        self._ma120_window = ma120_window
        self._close_history: list[float] = []
        self._below_ma60_streak = 0
        self._two_close_below_ma60 = two_close_below_ma60
        self._entry_marker: tuple[DateLike, float] | None = None

    def evaluate(self, context: ExitEvaluationContext) -> ExitTrigger | None:
        current_marker = (context.position.opened_at, context.position.entry_price)
        if current_marker != self._entry_marker:
            self._entry_marker = current_marker
            self._close_history = []
            self._below_ma60_streak = 0

        self._close_history.append(context.bar.close)
        ma60 = self._moving_average(self._ma60_window)
        ma120 = self._moving_average(self._ma120_window)
        if ma60 is None or ma120 is None:
            return None

        if context.bar.close < ma60:
            self._below_ma60_streak += 1
        else:
            self._below_ma60_streak = 0

        if self._below_ma60_streak >= self._two_close_below_ma60:
            return ExitTrigger(cause="trend_break", timestamp=context.timestamp)
        if context.bar.close < ma120:
            return ExitTrigger(cause="trend_break", timestamp=context.timestamp)
        return None

    def _moving_average(self, window: int) -> float | None:
        if len(self._close_history) < window:
            return None
        values = self._close_history[-window:]
        return sum(values) / window


class ProfitProtectionExitRule:
    """Closes after profit arm threshold then drawdown threshold from highest close."""

    def __init__(
        self,
        *,
        arm_profit_pct: float = 0.20,
        drawdown_from_high_pct: float = 0.15,
        mode: str = "percent_drawdown",
        atr_trailing_enabled: bool = False,
        atr_period: int = 14,
        atr_trail_mult: float = 2.0,
    ) -> None:
        if arm_profit_pct <= 0.0:
            raise ValueError("arm_profit_pct must be positive")
        if drawdown_from_high_pct <= 0.0:
            raise ValueError("drawdown_from_high_pct must be positive")
        if atr_period <= 0:
            raise ValueError("atr_period must be positive")
        if atr_trail_mult <= 0.0:
            raise ValueError("atr_trail_mult must be positive")

        self._arm_profit_pct = arm_profit_pct
        self._drawdown_from_high_pct = drawdown_from_high_pct
        self._mode = mode.strip().lower()
        self._atr_trailing_enabled = bool(atr_trailing_enabled)
        self._atr_period = atr_period
        self._atr_trail_mult = atr_trail_mult
        self._entry_marker: tuple[DateLike, float] | None = None
        self._highest_close_since_entry: float | None = None
        self._armed = False
        self._true_ranges: deque[float] = deque(maxlen=atr_period)
        self._previous_close: float | None = None

    def evaluate(self, context: ExitEvaluationContext) -> ExitTrigger | None:
        current_marker = (context.position.opened_at, context.position.entry_price)
        if current_marker != self._entry_marker:
            self._entry_marker = current_marker
            self._highest_close_since_entry = context.bar.close
            self._armed = False
            self._true_ranges.clear()
            self._previous_close = None

        tr = self._true_range(
            high=context.bar.high,
            low=context.bar.low,
            previous_close=self._previous_close,
        )
        self._true_ranges.append(tr)
        self._previous_close = context.bar.close

        if self._highest_close_since_entry is None:
            self._highest_close_since_entry = context.bar.close
        else:
            self._highest_close_since_entry = max(self._highest_close_since_entry, context.bar.close)

        entry_price = context.position.entry_price
        if entry_price > 0:
            max_unrealized = (self._highest_close_since_entry - entry_price) / entry_price
            if max_unrealized >= self._arm_profit_pct:
                self._armed = True

        if not self._armed:
            return None

        use_atr_trailing = self._atr_trailing_enabled or self._mode == "atr_trailing"
        if use_atr_trailing:
            atr = self._average_true_range()
            trail_stop = self._highest_close_since_entry - (atr * self._atr_trail_mult)
            if context.bar.close <= trail_stop:
                return ExitTrigger(cause="profit_protection", timestamp=context.timestamp)
            return None

        drawdown = (self._highest_close_since_entry - context.bar.close) / self._highest_close_since_entry
        if drawdown >= self._drawdown_from_high_pct:
            return ExitTrigger(cause="profit_protection", timestamp=context.timestamp)
        return None

    def _average_true_range(self) -> float:
        if not self._true_ranges:
            return 0.0
        return sum(self._true_ranges) / len(self._true_ranges)

    @staticmethod
    def _true_range(*, high: float, low: float, previous_close: float | None) -> float:
        if previous_close is None:
            return high - low
        return max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close),
        )


class PriorityClosePolicy:
    """Deterministically resolves simultaneous triggers by configured precedence."""

    DEFAULT_PRECEDENCE: tuple[str, ...] = (
        "stop_loss",
        "take_profit",
        "signal_exit",
        "max_holding_period",
    )

    def __init__(self, precedence: Sequence[str] | None = None) -> None:
        self._precedence = tuple(precedence or self.DEFAULT_PRECEDENCE)
        self._priority = {cause: index for index, cause in enumerate(self._precedence)}

    def select_trigger(self, triggers: Sequence[ExitTrigger]) -> ExitTrigger | None:
        if not triggers:
            return None
        return min(triggers, key=lambda trigger: self._priority.get(trigger.cause, len(self._priority)))


__all__ = [
    "ExitRule",
    "PositionClosePolicy",
    "OpenPositionState",
    "ExitEvaluationContext",
    "ExitTrigger",
    "SignalExitRule",
    "StopLossRule",
    "TakeProfitRule",
    "MaxHoldingPeriodRule",
    "AtrInitialStopRule",
    "TrendBreakExitRule",
    "ProfitProtectionExitRule",
    "PriorityClosePolicy",
]