"""Helpers for building config-driven backtest exit rules."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable

from src.tw_quant.backtest.exits import (
    AtrInitialStopRule,
    ExitRule,
    MaxHoldingPeriodRule,
    PositionClosePolicy,
    PriorityClosePolicy,
    ProfitProtectionExitRule,
    StopLossRule,
    TakeProfitRule,
    TrendBreakExitRule,
)
from src.tw_quant.config.models import BacktestConfig, BacktestExitConfig

RULE_ORDER: tuple[str, ...] = (
    "stop_loss_pct",
    "take_profit_pct",
    "max_holding_days",
)

STRATEGY_NAME_ALIASES: dict[str, str] = {
    "pullback": "pullback_trend_compression",
    "pullback_trend_compression": "pullback_trend_compression",
    "pullback_trend_120d_optimized": "pullback_trend_120d_optimized",
    "pullback_120d_optimized": "pullback_trend_120d_optimized",
    "pullback_optimized": "pullback_trend_120d_optimized",
}

RuleFactory = Callable[[object], ExitRule]

RULE_REGISTRY: dict[str, RuleFactory] = {
    "stop_loss_pct": lambda value: StopLossRule(threshold_pct=float(value)),
    "take_profit_pct": lambda value: TakeProfitRule(threshold_pct=float(value)),
    "max_holding_days": lambda value: MaxHoldingPeriodRule(max_holding_days=int(value)),
}


def canonicalize_strategy_name(strategy_name: str) -> str:
    normalized = strategy_name.strip().lower()
    return STRATEGY_NAME_ALIASES.get(normalized, normalized)


def resolve_effective_exit_params(
    *,
    strategy_name: str,
    parameters: Mapping[str, Any] | None,
    backtest_config: BacktestConfig | None,
) -> dict[str, object]:
    canonical_strategy_name = canonicalize_strategy_name(strategy_name)
    if canonical_strategy_name == "pullback_trend_120d_optimized":
        return _resolve_pullback_optimized_exit_params(parameters)

    effective: dict[str, object] = {}
    if backtest_config is not None:
        defaults = backtest_config.strategy_defaults.get(canonical_strategy_name)
        if defaults is not None:
            effective.update(_to_exit_mapping(defaults.exits))

    overrides = parameters.get("exits") if parameters is not None else None
    if isinstance(overrides, Mapping):
        for rule_key in RULE_ORDER:
            if rule_key not in overrides:
                continue
            override_value = overrides[rule_key]
            if override_value is None:
                effective.pop(rule_key, None)
                continue
            effective[rule_key] = override_value

    return {
        rule_key: effective[rule_key]
        for rule_key in RULE_ORDER
        if rule_key in effective
    }


def build_exit_rules(
    *,
    strategy_name: str,
    parameters: Mapping[str, Any] | None,
    backtest_config: BacktestConfig | None,
) -> tuple[ExitRule, ...]:
    canonical_strategy_name = canonicalize_strategy_name(strategy_name)
    if canonical_strategy_name == "pullback_trend_120d_optimized":
        return _build_pullback_optimized_exit_rules(parameters)

    effective_params = resolve_effective_exit_params(
        strategy_name=strategy_name,
        parameters=parameters,
        backtest_config=backtest_config,
    )
    return tuple(
        RULE_REGISTRY[rule_key](effective_params[rule_key])
        for rule_key in RULE_ORDER
        if rule_key in effective_params
    )


def build_close_policy(*, strategy_name: str) -> PositionClosePolicy | None:
    canonical_strategy_name = canonicalize_strategy_name(strategy_name)
    if canonical_strategy_name != "pullback_trend_120d_optimized":
        return None
    return PriorityClosePolicy(
        precedence=(
            "stop_loss",
            "trend_break",
            "profit_protection",
            "max_holding_period",
        )
    )


def _to_exit_mapping(config: BacktestExitConfig | None) -> dict[str, object]:
    if config is None:
        return {}

    mapping = {
        "stop_loss_pct": config.stop_loss_pct,
        "take_profit_pct": config.take_profit_pct,
        "max_holding_days": config.max_holding_days,
    }
    return {
        rule_key: value
        for rule_key, value in mapping.items()
        if value is not None
    }


def _resolve_pullback_optimized_exit_params(
    parameters: Mapping[str, Any] | None,
) -> dict[str, object]:
    effective: dict[str, object] = {
        "initial_stop_mode": "atr",
        "atr_period": 14,
        "atr_stop_mult": 2.5,
        "trend_break_ma60_window": 60,
        "trend_break_ma120_window": 120,
        "trend_break_below_ma60_days": 3,
        "profit_protect_trigger": 0.25,
        "profit_protect_pullback": 0.18,
        "profit_protection_mode": "percent_drawdown",
        "profit_protection_atr_trailing_enabled": False,
        "profit_protection_atr_period": 14,
        "profit_protection_atr_trail_mult": 2.0,
        "max_hold_days": 140,
    }

    if parameters is None:
        return effective

    exit_overrides = parameters.get("exit")
    if isinstance(exit_overrides, Mapping):
        initial_stop_mode = exit_overrides.get("initial_stop_mode")
        if initial_stop_mode is not None:
            effective["initial_stop_mode"] = str(initial_stop_mode)
        if exit_overrides.get("atr_period") is not None:
            effective["atr_period"] = int(exit_overrides["atr_period"])
        if exit_overrides.get("atr_stop_mult") is not None:
            effective["atr_stop_mult"] = float(exit_overrides["atr_stop_mult"])

        trend_break = exit_overrides.get("trend_break")
        if isinstance(trend_break, Mapping):
            if trend_break.get("ma60_window") is not None:
                effective["trend_break_ma60_window"] = int(trend_break["ma60_window"])
            if trend_break.get("ma120_window") is not None:
                effective["trend_break_ma120_window"] = int(trend_break["ma120_window"])
            if trend_break.get("trend_break_below_ma60_days") is not None:
                effective["trend_break_below_ma60_days"] = int(trend_break["trend_break_below_ma60_days"])

        profit_protection = exit_overrides.get("profit_protection")
        if isinstance(profit_protection, Mapping):
            if profit_protection.get("profit_protect_trigger") is not None:
                effective["profit_protect_trigger"] = float(profit_protection["profit_protect_trigger"])
            if profit_protection.get("profit_protect_pullback") is not None:
                effective["profit_protect_pullback"] = float(profit_protection["profit_protect_pullback"])
            if profit_protection.get("mode") is not None:
                effective["profit_protection_mode"] = str(profit_protection["mode"])
            if profit_protection.get("atr_trailing_enabled") is not None:
                effective["profit_protection_atr_trailing_enabled"] = bool(profit_protection["atr_trailing_enabled"])
            if profit_protection.get("atr_period") is not None:
                effective["profit_protection_atr_period"] = int(profit_protection["atr_period"])
            if profit_protection.get("atr_trail_mult") is not None:
                effective["profit_protection_atr_trail_mult"] = float(profit_protection["atr_trail_mult"])

        if exit_overrides.get("max_hold_days") is not None:
            effective["max_hold_days"] = int(exit_overrides["max_hold_days"])

    legacy_overrides = parameters.get("exits")
    if isinstance(legacy_overrides, Mapping) and legacy_overrides.get("max_hold_days") is not None:
        effective["max_hold_days"] = int(legacy_overrides["max_hold_days"])

    return effective


def _build_pullback_optimized_exit_rules(
    parameters: Mapping[str, Any] | None,
) -> tuple[ExitRule, ...]:
    effective = _resolve_pullback_optimized_exit_params(parameters)
    initial_stop_mode = str(effective["initial_stop_mode"]).lower()
    rules: list[ExitRule] = []

    if initial_stop_mode == "atr":
        rules.append(
            AtrInitialStopRule(
                atr_window=int(effective["atr_period"]),
                atr_multiplier=float(effective["atr_stop_mult"]),
            )
        )
    else:
        raise ValueError(f"Unsupported initial stop mode: {initial_stop_mode}")

    rules.append(
        TrendBreakExitRule(
            ma60_window=int(effective["trend_break_ma60_window"]),
            ma120_window=int(effective["trend_break_ma120_window"]),
            two_close_below_ma60=int(effective["trend_break_below_ma60_days"]),
        )
    )
    rules.append(
        ProfitProtectionExitRule(
            arm_profit_pct=float(effective["profit_protect_trigger"]),
            drawdown_from_high_pct=float(effective["profit_protect_pullback"]),
            mode=str(effective["profit_protection_mode"]),
            atr_trailing_enabled=bool(effective["profit_protection_atr_trailing_enabled"]),
            atr_period=int(effective["profit_protection_atr_period"]),
            atr_trail_mult=float(effective["profit_protection_atr_trail_mult"]),
        )
    )
    rules.append(MaxHoldingPeriodRule(max_holding_days=int(effective["max_hold_days"])))
    return tuple(rules)


__all__ = [
    "RULE_ORDER",
    "RULE_REGISTRY",
    "STRATEGY_NAME_ALIASES",
    "build_exit_rules",
    "build_close_policy",
    "canonicalize_strategy_name",
    "resolve_effective_exit_params",
]