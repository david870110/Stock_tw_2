from datetime import date

from src.tw_quant.backtest import (
    AtrInitialStopRule,
    ExitEvaluationContext,
    ExitTrigger,
    InMemoryPortfolioBook,
    MaxHoldingPeriodRule,
    OpenPositionState,
    PriorityClosePolicy,
    ProfitProtectionExitRule,
    SignalExitRule,
    StopLossRule,
    SymbolBacktestEngine,
    TakeProfitRule,
    TrendBreakExitRule,
)
from src.tw_quant.backtest.exit_builder import (
    build_close_policy,
    build_exit_rules,
    canonicalize_strategy_name,
    resolve_effective_exit_params,
)
from src.tw_quant.backtest.exits import PositionClosePolicy
from src.tw_quant.config.models import BacktestConfig, BacktestExitConfig, BacktestStrategyDefaults
from src.tw_quant.backtest.engine import SimpleExecutionModel
from src.tw_quant.schema.models import OHLCVBar, OrderIntent


def _make_bar(
    symbol: str,
    dt: date,
    close: float,
    *,
    low: float | None = None,
    high: float | None = None,
) -> OHLCVBar:
    return OHLCVBar(
        symbol=symbol,
        date=dt,
        open=close,
        high=close if high is None else high,
        low=close if low is None else low,
        close=close,
        volume=1000.0,
    )


def _make_position(symbol: str = "AAA") -> OpenPositionState:
    return OpenPositionState(
        symbol=symbol,
        quantity=2.0,
        entry_price=100.0,
        opened_at=date(2024, 1, 1),
        holding_bar_count=1,
    )


def test_signal_exit_rule_triggers_on_sell_intent() -> None:
    rule = SignalExitRule()
    context = ExitEvaluationContext(
        symbol="AAA",
        timestamp=date(2024, 1, 2),
        bar=_make_bar("AAA", date(2024, 1, 2), 100.0),
        position=_make_position(),
        intents=[OrderIntent(symbol="AAA", timestamp=date(2024, 1, 2), side="sell", quantity=0.5)],
    )

    trigger = rule.evaluate(context)

    assert trigger == ExitTrigger(cause="signal_exit", timestamp=date(2024, 1, 2))


def test_stop_loss_rule_uses_close_with_inclusive_threshold() -> None:
    rule = StopLossRule(threshold_pct=0.1)
    context = ExitEvaluationContext(
        symbol="AAA",
        timestamp=date(2024, 1, 2),
        bar=_make_bar("AAA", date(2024, 1, 2), 90.0, low=80.0),
        position=_make_position(),
        intents=[],
    )

    trigger = rule.evaluate(context)

    assert trigger == ExitTrigger(cause="stop_loss", timestamp=date(2024, 1, 2))


def test_stop_loss_rule_does_not_trigger_from_intrabar_low_alone() -> None:
    rule = StopLossRule(threshold_pct=0.1)
    context = ExitEvaluationContext(
        symbol="AAA",
        timestamp=date(2024, 1, 2),
        bar=_make_bar("AAA", date(2024, 1, 2), 90.1, low=80.0),
        position=_make_position(),
        intents=[],
    )

    trigger = rule.evaluate(context)

    assert trigger is None


def test_take_profit_rule_uses_close_with_inclusive_threshold() -> None:
    rule = TakeProfitRule(threshold_pct=0.1)
    context = ExitEvaluationContext(
        symbol="AAA",
        timestamp=date(2024, 1, 2),
        bar=_make_bar("AAA", date(2024, 1, 2), 110.0, high=120.0),
        position=_make_position(),
        intents=[],
    )

    trigger = rule.evaluate(context)

    assert trigger == ExitTrigger(cause="take_profit", timestamp=date(2024, 1, 2))


def test_take_profit_rule_does_not_trigger_from_intrabar_high_alone() -> None:
    rule = TakeProfitRule(threshold_pct=0.1)
    context = ExitEvaluationContext(
        symbol="AAA",
        timestamp=date(2024, 1, 2),
        bar=_make_bar("AAA", date(2024, 1, 2), 109.9, high=120.0),
        position=_make_position(),
        intents=[],
    )

    trigger = rule.evaluate(context)

    assert trigger is None


def test_pullback_default_stop_loss_threshold_triggers_at_minus_sixty_percent() -> None:
    rule = StopLossRule(threshold_pct=0.6)
    context = ExitEvaluationContext(
        symbol="AAA",
        timestamp=date(2024, 1, 2),
        bar=_make_bar("AAA", date(2024, 1, 2), 40.0, low=35.0),
        position=_make_position(),
        intents=[],
    )

    trigger = rule.evaluate(context)

    assert trigger == ExitTrigger(cause="stop_loss", timestamp=date(2024, 1, 2))


def test_pullback_default_take_profit_threshold_triggers_at_plus_one_hundred_twenty_percent() -> None:
    rule = TakeProfitRule(threshold_pct=1.2)
    context = ExitEvaluationContext(
        symbol="AAA",
        timestamp=date(2024, 1, 2),
        bar=_make_bar("AAA", date(2024, 1, 2), 220.0, high=225.0),
        position=_make_position(),
        intents=[],
    )

    trigger = rule.evaluate(context)

    assert trigger == ExitTrigger(cause="take_profit", timestamp=date(2024, 1, 2))


def test_exit_builder_uses_canonical_strategy_defaults_in_rule_order() -> None:
    config = BacktestConfig(
        strategy_defaults={
            "pullback_trend_compression": BacktestStrategyDefaults(
                exits=BacktestExitConfig(
                    stop_loss_pct=0.6,
                    take_profit_pct=1.2,
                    max_holding_days=7,
                )
            )
        }
    )

    rules = build_exit_rules(
        strategy_name="pullback",
        parameters={},
        backtest_config=config,
    )

    assert canonicalize_strategy_name("pullback") == "pullback_trend_compression"
    assert [type(rule) for rule in rules] == [StopLossRule, TakeProfitRule, MaxHoldingPeriodRule]


def test_exit_builder_applies_nested_overrides_and_null_removals() -> None:
    config = BacktestConfig(
        strategy_defaults={
            "pullback_trend_compression": BacktestStrategyDefaults(
                exits=BacktestExitConfig(stop_loss_pct=0.6, take_profit_pct=1.2)
            )
        }
    )

    effective = resolve_effective_exit_params(
        strategy_name="pullback_trend_compression",
        parameters={
            "short": 10,
            "exits": {
                "stop_loss_pct": 0.15,
                "take_profit_pct": None,
                "max_holding_days": 5,
            },
        },
        backtest_config=config,
    )

    assert effective == {
        "stop_loss_pct": 0.15,
        "max_holding_days": 5,
    }


def test_exit_builder_returns_no_rules_when_no_defaults_or_overrides_exist() -> None:
    rules = build_exit_rules(
        strategy_name="ma_cross",
        parameters={"short": 2, "long": 3},
        backtest_config=BacktestConfig(),
    )

    assert rules == ()


def test_exit_builder_supports_pullback_optimized_alias_and_rule_priority_order() -> None:
    rules = build_exit_rules(
        strategy_name="pullback_120d_optimized",
        parameters={},
        backtest_config=BacktestConfig(),
    )

    assert canonicalize_strategy_name("pullback_120d_optimized") == "pullback_trend_120d_optimized"
    assert [type(rule) for rule in rules] == [
        AtrInitialStopRule,
        TrendBreakExitRule,
        ProfitProtectionExitRule,
        MaxHoldingPeriodRule,
    ]


def test_exit_builder_builds_custom_close_policy_for_pullback_optimized() -> None:
    policy = build_close_policy(strategy_name="pullback_trend_120d_optimized")
    assert policy is not None

    selected = policy.select_trigger(
        [
            ExitTrigger(cause="profit_protection", timestamp=date(2024, 1, 10)),
            ExitTrigger(cause="trend_break", timestamp=date(2024, 1, 10)),
            ExitTrigger(cause="max_holding_period", timestamp=date(2024, 1, 10)),
        ]
    )

    assert selected == ExitTrigger(cause="trend_break", timestamp=date(2024, 1, 10))


def test_pullback_optimized_exit_rules_trigger_trend_break_before_max_hold() -> None:
    symbol = "AAA"
    bars = {
        date(2024, 1, 1): _make_bar(symbol, date(2024, 1, 1), 100.0, high=106.0, low=94.0),
        date(2024, 1, 2): _make_bar(symbol, date(2024, 1, 2), 100.0, high=106.0, low=94.0),
        date(2024, 1, 3): _make_bar(symbol, date(2024, 1, 3), 98.0, high=104.0, low=92.0),
        date(2024, 1, 4): _make_bar(symbol, date(2024, 1, 4), 97.0, high=103.0, low=91.0),
        date(2024, 1, 5): _make_bar(symbol, date(2024, 1, 5), 96.0, high=102.0, low=90.0),
    }

    def provider(sym, dt):
        return bars[dt]

    def signal_source(sym, dt):
        if dt == date(2024, 1, 1):
            return [OrderIntent(symbol=sym, timestamp=dt, side="buy", quantity=1.0)]
        return []

    rules = build_exit_rules(
        strategy_name="pullback_trend_120d_optimized",
        parameters={
            "exit": {
                "atr_period": 2,
                "atr_stop_mult": 100.0,
                "trend_break": {"ma60_window": 2, "ma120_window": 3, "trend_break_below_ma60_days": 2},
                "profit_protection": {"profit_protect_trigger": 0.5, "profit_protect_pullback": 0.5},
                "max_hold_days": 5,
            }
        },
        backtest_config=BacktestConfig(),
    )
    policy = build_close_policy(strategy_name="pullback_trend_120d_optimized")

    book = InMemoryPortfolioBook(initial_cash=1_000.0)
    engine = SymbolBacktestEngine(
        symbol=symbol,
        data_provider=provider,
        execution_model=SimpleExecutionModel(provider),
        portfolio_book=book,
        signal_source=signal_source,
        run_id="pullback-opt-trend-break-priority",
        exit_rules=rules,
        close_policy=policy,
    )

    result = engine.run(date(2024, 1, 1), date(2024, 1, 5))

    assert result.metrics["num_trades"] == 2.0
    assert result.trades[0]["exit_reason"] == "trend_break"


def test_pullback_optimized_atr_initial_stop_rule_triggers() -> None:
    rule = AtrInitialStopRule(atr_window=2, atr_multiplier=1.0)
    position = OpenPositionState(
        symbol="AAA",
        quantity=1.0,
        entry_price=100.0,
        opened_at=date(2024, 1, 1),
        holding_bar_count=1,
    )

    no_trigger = rule.evaluate(
        ExitEvaluationContext(
            symbol="AAA",
            timestamp=date(2024, 1, 2),
            bar=_make_bar("AAA", date(2024, 1, 2), 99.0, high=101.0, low=99.0),
            position=position,
            intents=[],
        )
    )
    trigger = rule.evaluate(
        ExitEvaluationContext(
            symbol="AAA",
            timestamp=date(2024, 1, 3),
            bar=_make_bar("AAA", date(2024, 1, 3), 96.0, high=100.0, low=95.0),
            position=position,
            intents=[],
        )
    )

    assert no_trigger is None
    assert trigger == ExitTrigger(cause="stop_loss", timestamp=date(2024, 1, 3))


def test_pullback_optimized_profit_protection_arms_and_triggers_drawdown() -> None:
    rule = ProfitProtectionExitRule(arm_profit_pct=0.20, drawdown_from_high_pct=0.15)
    position = OpenPositionState(
        symbol="AAA",
        quantity=1.0,
        entry_price=100.0,
        opened_at=date(2024, 1, 1),
        holding_bar_count=1,
    )

    no_trigger = rule.evaluate(
        ExitEvaluationContext(
            symbol="AAA",
            timestamp=date(2024, 1, 2),
            bar=_make_bar("AAA", date(2024, 1, 2), 120.0),
            position=position,
            intents=[],
        )
    )
    trigger = rule.evaluate(
        ExitEvaluationContext(
            symbol="AAA",
            timestamp=date(2024, 1, 3),
            bar=_make_bar("AAA", date(2024, 1, 3), 100.0),
            position=position,
            intents=[],
        )
    )

    assert no_trigger is None
    assert trigger == ExitTrigger(cause="profit_protection", timestamp=date(2024, 1, 3))


def test_max_holding_period_rule_uses_holding_bar_count() -> None:
    rule = MaxHoldingPeriodRule(max_holding_days=2)
    context = ExitEvaluationContext(
        symbol="AAA",
        timestamp=date(2024, 1, 10),
        bar=_make_bar("AAA", date(2024, 1, 10), 100.0),
        position=OpenPositionState(
            symbol="AAA",
            quantity=2.0,
            entry_price=100.0,
            opened_at=date(2024, 1, 1),
            holding_bar_count=2,
        ),
        intents=[],
    )

    trigger = rule.evaluate(context)

    assert trigger == ExitTrigger(cause="max_holding_period", timestamp=date(2024, 1, 10))


def test_priority_close_policy_uses_default_precedence() -> None:
    policy = PriorityClosePolicy()
    triggers = [
        ExitTrigger(cause="signal_exit", timestamp=date(2024, 1, 2)),
        ExitTrigger(cause="max_holding_period", timestamp=date(2024, 1, 2)),
        ExitTrigger(cause="take_profit", timestamp=date(2024, 1, 2)),
        ExitTrigger(cause="stop_loss", timestamp=date(2024, 1, 2)),
    ]

    selected = policy.select_trigger(triggers)

    assert selected == ExitTrigger(cause="stop_loss", timestamp=date(2024, 1, 2))


class RecordingClosePolicy(PositionClosePolicy):
    def __init__(self) -> None:
        self.selected_cause: str | None = None

    def select_trigger(self, triggers):
        selected = next(trigger for trigger in triggers if trigger.cause == "signal_exit")
        self.selected_cause = selected.cause
        return selected


def test_symbol_backtest_engine_closes_full_position_without_same_step_reopen() -> None:
    symbol = "AAA"
    bars = {
        date(2024, 1, 1): _make_bar(symbol, date(2024, 1, 1), 100.0),
        date(2024, 1, 2): _make_bar(symbol, date(2024, 1, 2), 100.0),
    }

    def provider(sym, dt):
        return bars[dt]

    def signal_source(sym, dt):
        if dt == date(2024, 1, 1):
            return [OrderIntent(symbol=sym, timestamp=dt, side="buy", quantity=2.0)]
        if dt == date(2024, 1, 2):
            return [
                OrderIntent(symbol=sym, timestamp=dt, side="sell", quantity=0.5),
                OrderIntent(symbol=sym, timestamp=dt, side="buy", quantity=1.0),
            ]
        return []

    book = InMemoryPortfolioBook(initial_cash=1_000.0)
    engine = SymbolBacktestEngine(
        symbol=symbol,
        data_provider=provider,
        execution_model=SimpleExecutionModel(provider),
        portfolio_book=book,
        signal_source=signal_source,
        run_id="t14-signal-exit",
        exit_rules=[SignalExitRule()],
    )

    result = engine.run(date(2024, 1, 1), date(2024, 1, 2))
    final_snapshot = book.snapshot(date(2024, 1, 2))

    assert final_snapshot.holdings.get(symbol, 0.0) == 0.0
    assert final_snapshot.cash == 1_000.0
    assert result.metrics["num_trades"] == 2.0


def test_symbol_backtest_engine_preserves_raw_intents_when_no_exit_trigger_fires() -> None:
    symbol = "AAA"
    bars = {
        date(2024, 1, 1): _make_bar(symbol, date(2024, 1, 1), 100.0),
        date(2024, 1, 2): _make_bar(symbol, date(2024, 1, 2), 101.0),
    }

    def provider(sym, dt):
        return bars[dt]

    def signal_source(sym, dt):
        if dt == date(2024, 1, 1):
            return [OrderIntent(symbol=sym, timestamp=dt, side="buy", quantity=2.0)]
        if dt == date(2024, 1, 2):
            return [
                OrderIntent(symbol=sym, timestamp=dt, side="sell", quantity=0.5),
                OrderIntent(symbol=sym, timestamp=dt, side="buy", quantity=1.0),
            ]
        return []

    book = InMemoryPortfolioBook(initial_cash=1_000.0)
    engine = SymbolBacktestEngine(
        symbol=symbol,
        data_provider=provider,
        execution_model=SimpleExecutionModel(provider),
        portfolio_book=book,
        signal_source=signal_source,
        run_id="t14-no-trigger-pass-through",
        exit_rules=[StopLossRule(threshold_pct=0.2)],
    )

    result = engine.run(date(2024, 1, 1), date(2024, 1, 2))
    final_snapshot = book.snapshot(date(2024, 1, 2))

    assert final_snapshot.holdings.get(symbol, 0.0) == 2.5
    assert final_snapshot.cash == 749.5
    assert result.metrics["num_trades"] == 3.0


def test_symbol_backtest_engine_preserves_flat_position_sell_behavior_with_exit_rules() -> None:
    symbol = "AAA"
    bars = {
        date(2024, 1, 1): _make_bar(symbol, date(2024, 1, 1), 100.0),
    }

    def provider(sym, dt):
        return bars[dt]

    def signal_source(sym, dt):
        return [OrderIntent(symbol=sym, timestamp=dt, side="sell", quantity=1.0)]

    book = InMemoryPortfolioBook(initial_cash=1_000.0)
    engine = SymbolBacktestEngine(
        symbol=symbol,
        data_provider=provider,
        execution_model=SimpleExecutionModel(provider),
        portfolio_book=book,
        signal_source=signal_source,
        run_id="t14-flat-sell-compatible",
        exit_rules=[SignalExitRule()],
    )

    result = engine.run(date(2024, 1, 1), date(2024, 1, 1))
    final_snapshot = book.snapshot(date(2024, 1, 1))

    assert final_snapshot.holdings.get(symbol, 0.0) == -1.0
    assert final_snapshot.cash == 1_100.0
    assert result.metrics["num_trades"] == 1.0


def test_symbol_backtest_engine_uses_post_step_holding_count_for_max_holding_period() -> None:
    symbol = "AAA"
    bars = {
        date(2024, 1, 1): _make_bar(symbol, date(2024, 1, 1), 100.0),
        date(2024, 1, 3): _make_bar(symbol, date(2024, 1, 3), 101.0),
        date(2024, 1, 4): _make_bar(symbol, date(2024, 1, 4), 102.0),
    }

    def provider(sym, dt):
        return bars.get(dt)

    def signal_source(sym, dt):
        if dt == date(2024, 1, 1):
            return [OrderIntent(symbol=sym, timestamp=dt, side="buy", quantity=1.0)]
        return []

    book = InMemoryPortfolioBook(initial_cash=1_000.0)
    engine = SymbolBacktestEngine(
        symbol=symbol,
        data_provider=provider,
        execution_model=SimpleExecutionModel(provider),
        portfolio_book=book,
        signal_source=signal_source,
        run_id="t14-bar-count",
        exit_rules=[MaxHoldingPeriodRule(max_holding_days=2)],
    )

    result = engine.run(date(2024, 1, 1), date(2024, 1, 4))
    final_snapshot = book.snapshot(date(2024, 1, 4))

    assert final_snapshot.holdings.get(symbol, 0.0) == 0.0
    assert final_snapshot.cash == 1_002.0
    assert result.metrics["num_trades"] == 2.0
    assert result.trades[0]["holding_days"] == 2


def test_symbol_backtest_engine_uses_configured_close_policy_for_simultaneous_triggers() -> None:
    symbol = "AAA"
    bars = {
        date(2024, 1, 1): _make_bar(symbol, date(2024, 1, 1), 100.0),
        date(2024, 1, 2): _make_bar(symbol, date(2024, 1, 2), 100.0, low=80.0),
    }

    def provider(sym, dt):
        return bars[dt]

    def signal_source(sym, dt):
        if dt == date(2024, 1, 1):
            return [OrderIntent(symbol=sym, timestamp=dt, side="buy", quantity=1.0)]
        if dt == date(2024, 1, 2):
            return [OrderIntent(symbol=sym, timestamp=dt, side="sell", quantity=1.0)]
        return []

    policy = RecordingClosePolicy()
    book = InMemoryPortfolioBook(initial_cash=1_000.0)
    engine = SymbolBacktestEngine(
        symbol=symbol,
        data_provider=provider,
        execution_model=SimpleExecutionModel(provider),
        portfolio_book=book,
        signal_source=signal_source,
        run_id="t14-policy",
        exit_rules=[SignalExitRule(), StopLossRule(threshold_pct=0.1)],
        close_policy=policy,
    )

    engine.run(date(2024, 1, 1), date(2024, 1, 2))

    assert policy.selected_cause == "signal_exit"


def test_symbol_backtest_engine_preserves_behavior_when_exit_rules_omitted() -> None:
    symbol = "AAA"
    bars = {
        date(2024, 1, 1): _make_bar(symbol, date(2024, 1, 1), 100.0),
        date(2024, 1, 2): _make_bar(symbol, date(2024, 1, 2), 100.0),
    }

    def provider(sym, dt):
        return bars[dt]

    def signal_source(sym, dt):
        if dt == date(2024, 1, 1):
            return [OrderIntent(symbol=sym, timestamp=dt, side="buy", quantity=1.0)]
        if dt == date(2024, 1, 2):
            return [OrderIntent(symbol=sym, timestamp=dt, side="sell", quantity=1.0)]
        return []

    book = InMemoryPortfolioBook(initial_cash=1_000.0)
    engine = SymbolBacktestEngine(
        symbol=symbol,
        data_provider=provider,
        execution_model=SimpleExecutionModel(provider),
        portfolio_book=book,
        signal_source=signal_source,
        run_id="t14-backward-compatible",
    )

    result = engine.run(date(2024, 1, 1), date(2024, 1, 2))
    final_snapshot = book.snapshot(date(2024, 1, 2))

    assert final_snapshot.holdings.get(symbol, 0.0) == 0.0
    assert result.metrics["num_trades"] == 2.0


def test_pullback_optimized_default_exit_params_atr_stop_mult_is_2_point_5() -> None:
    """Verify that resolve_effective_exit_params defaults atr_stop_mult to 2.5."""
    effective = resolve_effective_exit_params(
        strategy_name="pullback_trend_120d_optimized",
        parameters=None,
        backtest_config=BacktestConfig(),
    )

    assert effective["atr_period"] == 14
    assert effective["atr_stop_mult"] == 2.5
    assert effective["max_hold_days"] == 140
    assert effective["trend_break_below_ma60_days"] == 3
    assert effective["profit_protect_trigger"] == 0.25
    assert effective["profit_protect_pullback"] == 0.18
    assert effective["profit_protection_mode"] == "percent_drawdown"
    assert effective["profit_protection_atr_trailing_enabled"] is False
    assert effective["profit_protection_atr_period"] == 14
    assert effective["profit_protection_atr_trail_mult"] == 2.0


def test_pullback_optimized_profit_protection_supports_atr_trailing_mode() -> None:
    rules = build_exit_rules(
        strategy_name="pullback_trend_120d_optimized",
        parameters={
            "exit": {
                "profit_protection": {
                    "mode": "atr_trailing",
                    "atr_trailing_enabled": True,
                    "atr_period": 2,
                    "atr_trail_mult": 1.0,
                    "profit_protect_trigger": 0.10,
                }
            }
        },
        backtest_config=BacktestConfig(),
    )

    profit_rule = next(rule for rule in rules if isinstance(rule, ProfitProtectionExitRule))
    position = OpenPositionState(
        symbol="AAA",
        quantity=1.0,
        entry_price=100.0,
        opened_at=date(2024, 1, 1),
        holding_bar_count=1,
    )

    no_trigger = profit_rule.evaluate(
        ExitEvaluationContext(
            symbol="AAA",
            timestamp=date(2024, 1, 2),
            bar=_make_bar("AAA", date(2024, 1, 2), 115.0, high=118.0, low=112.0),
            position=position,
            intents=[],
        )
    )
    trigger = profit_rule.evaluate(
        ExitEvaluationContext(
            symbol="AAA",
            timestamp=date(2024, 1, 3),
            bar=_make_bar("AAA", date(2024, 1, 3), 107.0, high=109.0, low=105.0),
            position=position,
            intents=[],
        )
    )

    assert no_trigger is None
    assert trigger == ExitTrigger(cause="profit_protection", timestamp=date(2024, 1, 3))


def test_symbol_backtest_engine_cooldown_stop_loss_mode_does_not_block_after_signal_exit() -> None:
    symbol = "AAA"
    bars = {
        date(2024, 1, 1): _make_bar(symbol, date(2024, 1, 1), 100.0),
        date(2024, 1, 2): _make_bar(symbol, date(2024, 1, 2), 100.0),
        date(2024, 1, 3): _make_bar(symbol, date(2024, 1, 3), 100.0),
    }

    def provider(sym, dt):
        return bars[dt]

    def signal_source(sym, dt):
        if dt == date(2024, 1, 1):
            return [OrderIntent(symbol=sym, timestamp=dt, side="buy", quantity=1.0)]
        if dt == date(2024, 1, 2):
            return [OrderIntent(symbol=sym, timestamp=dt, side="sell", quantity=1.0)]
        if dt == date(2024, 1, 3):
            return [OrderIntent(symbol=sym, timestamp=dt, side="buy", quantity=1.0)]
        return []

    book = InMemoryPortfolioBook(initial_cash=1_000.0)
    engine = SymbolBacktestEngine(
        symbol=symbol,
        data_provider=provider,
        execution_model=SimpleExecutionModel(provider),
        portfolio_book=book,
        signal_source=signal_source,
        run_id="cooldown-stop-loss-mode",
        reentry_cooldown_days=30,
        cooldown_apply_on="stop_loss",
    )

    engine.run(date(2024, 1, 1), date(2024, 1, 3))
    final_snapshot = book.snapshot(date(2024, 1, 3))

    assert final_snapshot.holdings.get(symbol, 0.0) == 1.0