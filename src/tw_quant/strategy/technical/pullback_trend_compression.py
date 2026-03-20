"""Pullback trend-compression strategy adapter."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any

from src.tw_quant.schema.models import FeatureFrameRef, OrderIntent, SignalRecord
from src.tw_quant.strategy.interfaces import StrategyContext
from src.tw_quant.strategy.technical.features import (
    is_negative_histogram_above_prior_negative_min,
    macd_histogram,
    rolling_max,
    rolling_min,
    simple_moving_average,
)

OHLCVSeries = dict[str, list[float] | str]
FeatureSource = Callable[[FeatureFrameRef], dict[str, OHLCVSeries]]


class PullbackTrendCompressionStrategy:
    def __init__(
        self,
        feature_source: FeatureSource,
        *,
        low_tolerance: float = 1e-9,
    ) -> None:
        self._feature_source = feature_source
        self._low_tolerance = low_tolerance

    def generate_signals(self, context: StrategyContext) -> list[SignalRecord]:
        if context.feature_ref is None:
            return []

        by_symbol = self._feature_source(context.feature_ref)
        signals: list[SignalRecord] = []

        for symbol, payload in by_symbol.items():
            passed, metadata = self._evaluate_symbol(payload, context.strategy_name)
            signals.append(
                SignalRecord(
                    symbol=symbol,
                    timestamp=context.as_of,
                    signal="buy" if passed else "hold",
                    score=1.0 if passed else 0.0,
                    metadata=metadata,
                )
            )

        return signals

    def build_orders(
        self, context: StrategyContext, selections: list[SignalRecord]
    ) -> list[OrderIntent]:
        return [
            OrderIntent(
                symbol=signal.symbol,
                timestamp=context.as_of,
                side="buy",
                quantity=1.0,
                order_type="market",
            )
            for signal in selections
            if signal.signal == "buy"
        ]

    def _evaluate_symbol(
        self,
        payload: OHLCVSeries,
        strategy_name: str,
    ) -> tuple[bool, dict[str, Any]]:
        open_values = self._as_float_list(payload.get("open"))
        high_values = self._as_float_list(payload.get("high"))
        low_values = self._as_float_list(payload.get("low"))
        close_values = self._as_float_list(payload.get("close"))
        volume_values = self._as_float_list(payload.get("volume"))

        if not self._is_daily_bar_payload(payload):
            return False, {
                "strategy": strategy_name,
                "indicator": "pullback_trend_compression",
                "reason": "non_daily_interval",
            }

        lengths = {
            len(open_values),
            len(high_values),
            len(low_values),
            len(close_values),
            len(volume_values),
        }
        if lengths != {len(close_values)} or not close_values:
            return False, {
                "strategy": strategy_name,
                "indicator": "pullback_trend_compression",
                "reason": "invalid_ohlcv_series",
            }

        index = len(close_values) - 1
        if len(close_values) < 200:
            return False, {
                "strategy": strategy_name,
                "indicator": "pullback_trend_compression",
                "reason": "insufficient_history",
                "required_bars": 200,
                "provided_bars": len(close_values),
            }

        ma60 = simple_moving_average(close_values, window=60)
        ma120 = simple_moving_average(close_values, window=120)
        ma200 = simple_moving_average(close_values, window=200)
        high60 = rolling_max(high_values, window=60)
        volume_ma5 = simple_moving_average(volume_values, window=5)
        histogram = macd_histogram(close_values)

        ma60_current = ma60[index]
        ma120_current = ma120[index]
        ma200_current = ma200[index]
        ma60_prior_5 = ma60[index - 5] if index - 5 >= 0 else None
        ma120_prior_5 = ma120[index - 5] if index - 5 >= 0 else None
        high60_current = high60[index]
        volume_ma5_current = volume_ma5[index]
        prior_low10 = min(low_values[index - 9 : index]) if index - 9 >= 0 else None

        if (
            ma60_current is None
            or ma120_current is None
            or ma200_current is None
            or ma60_prior_5 is None
            or ma120_prior_5 is None
            or high60_current is None
            or volume_ma5_current is None
            or prior_low10 is None
        ):
            return False, {
                "strategy": strategy_name,
                "indicator": "pullback_trend_compression",
                "reason": "insufficient_indicator_history",
            }

        close_current = close_values[index]
        open_current = open_values[index]
        low_current = low_values[index]
        volume_current = volume_values[index]

        trend_stack = ma60_current > ma120_current > ma200_current
        proximity = abs((close_current - ma60_current) / ma60_current) <= 0.10
        ma60_slope = ma60_current > ma60_prior_5
        ma120_slope = ma120_current > ma120_prior_5
        compression_ratio = (high60_current - close_current) / high60_current
        compression = 0.10 <= compression_ratio <= 0.30
        volume_condition = volume_current < volume_ma5_current
        macd_condition = self._passes_macd_condition(histogram, index=index)
        bearish_candle = close_current < open_current
        low_break = low_current <= prior_low10 + self._low_tolerance

        conditions = {
            "trend_stack": trend_stack,
            "ma60_proximity": proximity,
            "ma60_slope": ma60_slope,
            "ma120_slope": ma120_slope,
            "compression": compression,
            "volume": volume_condition,
            "macd": macd_condition,
            "bearish_candle": bearish_candle,
            "rolling_low10": low_break,
        }

        return all(conditions.values()), {
            "strategy": strategy_name,
            "indicator": "pullback_trend_compression",
            "conditions": conditions,
            "compression_ratio": compression_ratio,
        }

    def _passes_macd_condition(
        self,
        histogram: list[float | None],
        *,
        index: int,
    ) -> bool:
        return is_negative_histogram_above_prior_negative_min(
            histogram,
            lookback=30,
            index=index,
        )

    @staticmethod
    def _is_daily_bar_payload(payload: OHLCVSeries) -> bool:
        interval = payload.get("interval")
        if interval is None:
            return True
        if not isinstance(interval, str):
            return False
        return interval.lower() in {"1d", "d", "day", "daily"}

    @staticmethod
    def _as_float_list(value: object) -> list[float]:
        if not isinstance(value, list):
            return []
        return [float(item) for item in value]


class PullbackTrend120dOptimizedStrategy:
    _DEFAULTS: dict[str, dict[str, Any]] = {
        "basic": {
            "require_daily": True,
            "min_bars": 200,
        },
        "liquidity": {
            "liquidity_amt_ma20_min": 0_000_000.0,
            "min_price_enabled": False,
            "min_price": 10.0,
        },
        "ma": {
            "ma_short": 20,
            "ma20_slope_lookback": 5,
            "ma_fast": 60,
            "ma_mid": 120,
            "ma_slow": 200,
            "slope_lookback": 20,
            "require_stack": True,
                "require_ma60_slope_up": False,
            "require_ma120_slope_up": True,
        },
        "pullback": {
            "high_lookback": 80,
            "drawdown_min": 0.08,
            "drawdown_max": 0.22,
                "ma60_dist_min": -0.05,
                "ma60_dist_max": 0.9,
        },
        "entry": {
            "entry_semantics_mode": "legacy",
            "setup_offset_bars": 1,
            "reentry_cooldown_days": 30,
            "cooldown_apply_on": "any_exit",
            "position_cash": 100000.0,
            "risk_budget_pct": None,
            "stop_distance_mode": "atr_initial_stop",
            "fallback_position_cash": 100000.0,
        },
        "volume": {
            "volume_short_ma": 10,
            "volume_long_ma": 20,
            "volume_contract_enabled": True,
            "volume_contract_ratio_max": 1.0,
            "setup_volume_contract_enabled": True,
            "setup_volume_contract_ratio_max": 1.0,
            "trigger_volume_check_enabled": True,
            "trigger_volume_ratio_warn_max": 1.2,
            "trigger_volume_hard_block": False,
        },
        "chip": {
            "enable_chip_filter": False,
            "enable_foreign_buy_filter": False,
            "enable_investment_trust_filter": False,
            "chip_lookback": 20,
        },
        "margin": {
            "enable_margin_filter": False,
            "margin_lookback": 20,
            "margin_growth_limit": 0.15,
        },
        "borrow": {
            "enable_borrow_filter": False,
            "borrow_lookback": 20,
            "borrow_balance_growth_limit": 0.15,
        },
        "atr_pullback": {
            "use_atr_normalized_pullback": False,
            "drawdown_atr_norm_min": 0.5,
            "drawdown_atr_norm_max": 3.0,
            "dist_to_ma60_atr_max": 1.5,
            "atr_period": 14,
        },
        "price_contraction": {
            "price_contract_enabled": True,
            "range_short_lookback": 5,
            "range_long_lookback": 20,
            "range_contract_ratio_max": 0.7,
            "range_percentile_max": None,
        },
        "close_strength": {
            "close_strength_enabled": True,
            "close_vs_5d_high_min": 0.95,
            "close_position_5d_min": None,
        },
        "short_momentum": {
              "short_momentum_enabled": False,
            "short_momentum_lookback": 5,
        },
        "chip_scoring": {
            "enable_chip_scoring": False,
            "foreign_score_weight": 1.0,
            "investment_trust_score_weight": 1.0,
            "margin_score_weight": 0.5,
            "borrow_score_weight": 0.5,
            "chip_scoring_lookback": 20,
        },
        "exit": {
            "initial_stop_mode": "atr",
            "atr_period": 14,
            "atr_stop_mult": 2.5,
            "trend_break": {
                "ma60_window": 60,
                "ma120_window": 120,
                "trend_break_below_ma60_days": 3,
            },
            "profit_protection": {
                "profit_protect_trigger": 0.25,
                "profit_protect_pullback": 0.18,
            },
            "max_hold_days": 140,
        },
    }

    def __init__(
        self,
        feature_source: FeatureSource,
        *,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._feature_source = feature_source
        self._config = self._merge_nested_dicts(self._DEFAULTS, config or {})

    def generate_signals(self, context: StrategyContext) -> list[SignalRecord]:
        if context.feature_ref is None:
            return []

        by_symbol = self._feature_source(context.feature_ref)
        signals: list[SignalRecord] = []

        for symbol, payload in by_symbol.items():
            passed, metadata = self._evaluate_symbol(payload, context.strategy_name)
            signals.append(
                SignalRecord(
                    symbol=symbol,
                    timestamp=context.as_of,
                    signal="buy" if passed else "hold",
                    score=1.0 if passed else 0.0,
                    metadata=metadata,
                )
            )

        return signals

    def build_orders(
        self, context: StrategyContext, selections: list[SignalRecord]
    ) -> list[OrderIntent]:
        return [
            OrderIntent(
                symbol=signal.symbol,
                timestamp=context.as_of,
                side="buy",
                quantity=1.0,
                order_type="market",
            )
            for signal in selections
            if signal.signal == "buy"
        ]

    def _evaluate_symbol(
        self,
        payload: OHLCVSeries,
        strategy_name: str,
    ) -> tuple[bool, dict[str, Any]]:
        close_values = self._as_float_list(payload.get("close"))
        open_values = self._as_float_list(payload.get("open"))
        high_values = self._as_float_list(payload.get("high"))
        low_values = self._as_float_list(payload.get("low"))
        volume_values = self._as_float_list(payload.get("volume"))

        index = len(close_values) - 1
        entry_semantics_mode = self._cfg_str("entry", "entry_semantics_mode", "legacy").strip().lower()
        if entry_semantics_mode not in {"legacy", "setup_trigger"}:
            entry_semantics_mode = "legacy"
        setup_offset_bars = max(0, self._cfg_int("entry", "setup_offset_bars", 1))
        trigger_index = index
        setup_index = trigger_index if entry_semantics_mode == "legacy" else trigger_index - setup_offset_bars
        setup_index_valid = 0 <= setup_index < len(close_values)
        module_debug: dict[str, dict[str, Any]] = {}

        interval_ok = (not self._cfg_bool("basic", "require_daily", True)) or self._is_daily_bar_payload(payload)
        min_bars = self._cfg_int("basic", "min_bars", 120)
        basic_pass = interval_ok and len(close_values) >= min_bars
        module_debug["basic"] = {
            "enabled": True,
            "passed": basic_pass,
            "metrics": {
                "bars": len(close_values),
                "min_bars": min_bars,
                "is_daily": self._is_daily_bar_payload(payload),
            },
            "reason": None
            if basic_pass
            else ("non_daily_interval" if not interval_ok else "insufficient_history"),
        }

        if not basic_pass:
            return False, self._build_metadata(strategy_name, module_debug)

        lengths = {
            len(open_values),
            len(high_values),
            len(low_values),
            len(close_values),
            len(volume_values),
        }
        if lengths != {len(close_values)}:
            module_debug["basic"] = {
                "enabled": True,
                "passed": False,
                "metrics": {
                    "bars": len(close_values),
                    "lengths": sorted(lengths),
                },
                "reason": "invalid_ohlcv_series",
            }
            return False, self._build_metadata(strategy_name, module_debug)

        close_current = close_values[index]
        high_lookback = self._cfg_int("pullback", "high_lookback", 80)
        high_n = rolling_max(high_values, window=high_lookback)
        volume_short_ma_window = self._cfg_int("volume", "volume_short_ma", 10)
        volume_long_ma_window = self._cfg_int("volume", "volume_long_ma", 20)
        vol_ma_short = simple_moving_average(volume_values, window=volume_short_ma_window)
        vol_ma_long = simple_moving_average(volume_values, window=volume_long_ma_window)

        ma60_window = self._cfg_int("ma", "ma_fast", 60)
        ma120_window = self._cfg_int("ma", "ma_mid", 120)
        ma200_window = self._cfg_int("ma", "ma_slow", 200)
        ma20_window = self._cfg_int("ma", "ma_short", 20)
        ma60 = simple_moving_average(close_values, window=ma60_window)
        ma120 = simple_moving_average(close_values, window=ma120_window)
        ma200 = simple_moving_average(close_values, window=ma200_window)
        ma20 = simple_moving_average(close_values, window=ma20_window)

        # Compute 20-day average amount for liquidity (use turnover series if available)
        turnover_values = self._as_float_list(payload.get("turnover"))
        if turnover_values and len(turnover_values) == len(close_values):
            amount_values: list[float] = turnover_values
        else:
            amount_values = [c * v for c, v in zip(close_values, volume_values)]
        amt_ma20_series = simple_moving_average(amount_values, window=20)

        ma60_current = ma60[index]
        ma120_current = ma120[index]
        ma200_current = ma200[index]
        ma20_current = ma20[index]
        high_n_current = high_n[index]
        vol_ma_short_current = vol_ma_short[index]
        vol_ma_long_current = vol_ma_long[index]

        if (
            ma60_current is None
            or ma120_current is None
            or ma200_current is None
            or ma20_current is None
            or high_n_current is None
            or vol_ma_short_current is None
            or vol_ma_long_current is None
        ):
            module_debug["basic"] = {
                "enabled": True,
                "passed": False,
                "metrics": {
                    "bars": len(close_values),
                    "ma60_ready": ma60_current is not None,
                    "ma120_ready": ma120_current is not None,
                    "ma200_ready": ma200_current is not None,
                    "ma20_ready": ma20_current is not None,
                    "high_window_ready": high_n_current is not None,
                    "vol_short_ma_ready": vol_ma_short_current is not None,
                    "vol_long_ma_ready": vol_ma_long_current is not None,
                },
                "reason": "insufficient_indicator_history",
            }
            return False, self._build_metadata(strategy_name, module_debug)

        volume_current = volume_values[index]
        amt_ma20_current = amt_ma20_series[index] if amt_ma20_series else None
        liquidity_amt_ma20_min = self._cfg_float("liquidity", "liquidity_amt_ma20_min", 0_000_000.0)
        min_price_enabled = self._cfg_bool("liquidity", "min_price_enabled", False)
        min_price = self._cfg_float("liquidity", "min_price", 10.0)
        price_ok = (not min_price_enabled) or close_current >= min_price
        amt_ok = amt_ma20_current is not None and amt_ma20_current >= liquidity_amt_ma20_min
        liquidity_pass = amt_ok and price_ok
        module_debug["liquidity"] = {
            "enabled": True,
            "passed": liquidity_pass,
            "metrics": {
                "amt_ma20": amt_ma20_current,
                "liquidity_amt_ma20_min": liquidity_amt_ma20_min,
                "close": close_current,
                "min_price_enabled": min_price_enabled,
                "min_price": min_price,
            },
            "reason": None if liquidity_pass else "liquidity_threshold_not_met",
        }

        slope_lookback = self._cfg_int("ma", "slope_lookback", 20)
        ma20_slope_lookback = self._cfg_int("ma", "ma20_slope_lookback", 5)
        ma60_prior = ma60[index - slope_lookback] if index - slope_lookback >= 0 else None
        ma120_prior = ma120[index - slope_lookback] if index - slope_lookback >= 0 else None
        ma200_prior = ma200[index - slope_lookback] if index - slope_lookback >= 0 else None
        ma20_prior = ma20[index - ma20_slope_lookback] if index - ma20_slope_lookback >= 0 else None
        close_above_ma20_pass = ma20_current is not None and close_current >= ma20_current
        ma20_slope_pass = ma20_prior is not None and ma20_current >= ma20_prior
        stack_ok = ma60_current > ma120_current > ma200_current
        ma60_slope_ok = ma60_prior is not None and ma60_current > ma60_prior
        ma120_slope_ok = ma120_prior is not None and ma120_current > ma120_prior
        ma200_slope_ok = ma200_prior is not None and ma200_current >= ma200_prior
        close_above_ma120 = close_current > ma120_current
        ma_pass = True
        if self._cfg_bool("ma", "require_stack", True):
            ma_pass = ma_pass and stack_ok
        if self._cfg_bool("ma", "require_ma60_slope_up", True):
            ma_pass = ma_pass and ma60_slope_ok
        if self._cfg_bool("ma", "require_ma120_slope_up", True):
            ma_pass = ma_pass and ma120_slope_ok
        ma_pass = ma_pass and ma200_slope_ok and close_above_ma120
        module_debug["ma"] = {
            "enabled": True,
            "passed": ma_pass,
            "metrics": {
                "close": close_current,
                "ma60": ma60_current,
                "ma120": ma120_current,
                "ma200": ma200_current,
                "ma20": ma20_current,
                "ma20_slope_lookback": ma20_slope_lookback,
                "close_above_ma20_pass": close_above_ma20_pass,
                "ma20_slope_pass": ma20_slope_pass,
                "stack_ok": stack_ok,
                "ma60_slope_ok": ma60_slope_ok,
                "ma120_slope_ok": ma120_slope_ok,
                "ma200_slope_ok": ma200_slope_ok,
                "close_above_ma120": close_above_ma120,
            },
            "reason": None if ma_pass else "ma_trend_not_met",
        }

        pullback_pct = (high_n_current - close_current) / high_n_current if high_n_current else 0.0
        drawdown_min = self._cfg_float("pullback", "drawdown_min", 0.08)
        drawdown_max = self._cfg_float("pullback", "drawdown_max", 0.22)
        ma60_dist_min = self._cfg_float("pullback", "ma60_dist_min", -0.05)
        ma60_dist_max = self._cfg_float("pullback", "ma60_dist_max", 0.08)
        signed_dist_to_ma60 = (close_current - ma60_current) / ma60_current if ma60_current else 0.0
        pullback_pass = (
            drawdown_min <= pullback_pct <= drawdown_max
            and ma60_dist_min <= signed_dist_to_ma60 <= ma60_dist_max
        )
        module_debug["pullback"] = {
            "enabled": True,
            "passed": pullback_pass,
            "metrics": {
                "pullback_pct": pullback_pct,
                "drawdown_min": drawdown_min,
                "drawdown_max": drawdown_max,
                "signed_dist_to_ma60": signed_dist_to_ma60,
                "ma60_dist_min": ma60_dist_min,
                "ma60_dist_max": ma60_dist_max,
            },
            "reason": None if pullback_pass else "pullback_range_not_met",
        }

        vol_contracted = vol_ma_short_current < vol_ma_long_current
        setup_volume_contract_enabled = self._cfg_bool(
            "volume",
            "setup_volume_contract_enabled",
            self._cfg_bool("volume", "volume_contract_enabled", True),
        )
        setup_volume_contract_ratio_max = self._cfg_float(
            "volume",
            "setup_volume_contract_ratio_max",
            self._cfg_float("volume", "volume_contract_ratio_max", 1.0),
        )
        trigger_volume_check_enabled = self._cfg_bool("volume", "trigger_volume_check_enabled", True)
        trigger_volume_ratio_warn_max = self._cfg_float("volume", "trigger_volume_ratio_warn_max", 1.2)
        trigger_volume_hard_block = self._cfg_bool("volume", "trigger_volume_hard_block", False)

        volume_ratio = volume_current / vol_ma_long_current if vol_ma_long_current else 0.0
        setup_volume_ratio: float | None = None
        if setup_index_valid and 0 <= setup_index < len(volume_values):
            setup_volume = volume_values[setup_index]
            setup_vol_ma_long = vol_ma_long[setup_index] if 0 <= setup_index < len(vol_ma_long) else None
            if setup_vol_ma_long is not None and setup_vol_ma_long > 0.0:
                setup_volume_ratio = setup_volume / setup_vol_ma_long

        if not setup_volume_contract_enabled:
            setup_volume_pass = True
            setup_volume_reason: str | None = "disabled"
        elif setup_volume_ratio is None:
            setup_volume_pass = False
            setup_volume_reason = "insufficient_setup_volume_history"
        else:
            setup_volume_pass = setup_volume_ratio <= setup_volume_contract_ratio_max
            setup_volume_reason = None if setup_volume_pass else "setup_volume_ratio_exceeded"

        if not trigger_volume_check_enabled:
            trigger_volume_pass = True
            trigger_volume_reason: str | None = "disabled"
        else:
            trigger_volume_pass = volume_ratio <= trigger_volume_ratio_warn_max
            trigger_volume_reason = None if trigger_volume_pass else "trigger_volume_warn_exceeded"

        volume_pass = setup_volume_pass and (trigger_volume_pass or not trigger_volume_hard_block)
        module_debug["volume"] = {
            "enabled": True,
            "passed": volume_pass,
            "metrics": {
                "volume": volume_current,
                "vol_ma_short": vol_ma_short_current,
                "vol_ma_long": vol_ma_long_current,
                "vol_contracted": vol_contracted,
                "volume_contract_enabled": self._cfg_bool("volume", "volume_contract_enabled", True),
                "volume_ratio": volume_ratio,
                "volume_contract_ratio_max": self._cfg_float("volume", "volume_contract_ratio_max", 1.0),
                "setup_volume_contract_enabled": setup_volume_contract_enabled,
                "setup_volume_contract_ratio_max": setup_volume_contract_ratio_max,
                "setup_volume_ratio": setup_volume_ratio,
                "trigger_volume_check_enabled": trigger_volume_check_enabled,
                "trigger_volume_ratio_warn_max": trigger_volume_ratio_warn_max,
                "trigger_volume_hard_block": trigger_volume_hard_block,
                "setup_index": setup_index,
                "trigger_index": trigger_index,
            },
            "reason": None
            if volume_pass
            else "volume_not_contracted",
        }

        module_debug["chip"] = self._evaluate_chip_module(payload, index)
        module_debug["margin"] = self._evaluate_margin_module(payload, close_values, index)
        module_debug["borrow"] = self._evaluate_borrow_module(payload, close_values, index)
        module_debug["atr_pullback"] = self._evaluate_atr_pullback_module(
            high_values, low_values, close_values, index, high_n_current, ma60_current
        )
        module_debug["price_contraction"] = self._evaluate_price_contraction_module(
            high_values, low_values, close_values, index
        )
        close_strength_enabled = self._cfg_bool("close_strength", "close_strength_enabled", True)
        close_vs_5d_high_min = self._cfg_float("close_strength", "close_vs_5d_high_min", 0.95)
        close_position_5d_min = self._cfg_optional_float("close_strength", "close_position_5d_min")
        close_5d_high_series = rolling_max(close_values, window=5)
        close_5d_high = close_5d_high_series[index] if close_5d_high_series else None
        high_5d_series = rolling_max(high_values, window=5)
        low_5d_series = rolling_min(low_values, window=5)
        high_5d = high_5d_series[index] if high_5d_series else None
        low_5d = low_5d_series[index] if low_5d_series else None

        close_vs_5d_high = (
            close_current / close_5d_high
            if close_5d_high is not None and close_5d_high > 0.0
            else None
        )
        close_position_5d: float | None = None
        if high_5d is not None and low_5d is not None:
            denominator = high_5d - low_5d
            if denominator > 0.0:
                close_position_5d = (close_current - low_5d) / denominator

        if not close_strength_enabled:
            close_strength_pass = True
            close_strength_reason: str | None = "disabled"
        elif close_vs_5d_high is None:
            close_strength_pass = False
            close_strength_reason = "insufficient_history"
        else:
            primary_ok = close_vs_5d_high >= close_vs_5d_high_min
            position_ok = True
            if close_position_5d_min is not None:
                position_ok = close_position_5d is not None and close_position_5d >= close_position_5d_min
            close_strength_pass = primary_ok and position_ok
            close_strength_reason = None if close_strength_pass else "close_strength_not_met"

        module_debug["close_strength"] = {
            "enabled": close_strength_enabled,
            "passed": close_strength_pass,
            "metrics": {
                "close": close_current,
                "close_5d_high": close_5d_high,
                "high_5d": high_5d,
                "low_5d": low_5d,
                "close_vs_5d_high": close_vs_5d_high,
                "close_vs_5d_high_min": close_vs_5d_high_min,
                "close_position_5d": close_position_5d,
                "close_position_5d_min": close_position_5d_min,
            },
            "reason": close_strength_reason,
        }

        short_momentum_enabled = self._cfg_bool("short_momentum", "short_momentum_enabled", True)
        short_momentum_lookback = self._cfg_int("short_momentum", "short_momentum_lookback", 5)
        short_momentum_lookback = max(short_momentum_lookback, 1)
        close_lookback = close_values[index - short_momentum_lookback] if index - short_momentum_lookback >= 0 else None
        if not short_momentum_enabled:
            short_momentum_pass = True
            short_momentum_reason: str | None = "disabled"
        elif close_lookback is None:
            short_momentum_pass = False
            short_momentum_reason = "insufficient_history"
        else:
            short_momentum_pass = close_current > close_lookback
            short_momentum_reason = None if short_momentum_pass else "short_momentum_not_met"

        module_debug["short_momentum"] = {
            "enabled": short_momentum_enabled,
            "passed": short_momentum_pass,
            "metrics": {
                "close": close_current,
                "close_lookback": close_lookback,
                "short_momentum_lookback": short_momentum_lookback,
            },
            "reason": short_momentum_reason,
        }

        module_debug["chip_scoring"] = self._evaluate_chip_scoring_module(payload, close_values, index)
        price_contraction_pass = bool(module_debug["price_contraction"]["passed"])
        module_debug["price_contraction"]["metrics"]["price_contraction_pass"] = price_contraction_pass

        _GATE_MODULES = {
            "basic", "liquidity", "ma", "pullback", "volume",
            "chip", "margin", "borrow", "atr_pullback", "price_contraction", "close_strength", "short_momentum",
        }
        all_pass = (
            all(module_debug[k]["passed"] for k in _GATE_MODULES if k in module_debug)
            and close_above_ma20_pass
            and ma20_slope_pass
            and price_contraction_pass
            and close_strength_pass
            and short_momentum_pass
        )
        setup_pass = all_pass if entry_semantics_mode == "legacy" else (setup_index_valid and setup_volume_pass)
        trigger_pass = all_pass if entry_semantics_mode == "legacy" else trigger_volume_pass
        if entry_semantics_mode != "legacy":
            all_pass = all_pass and setup_pass and (trigger_pass or not trigger_volume_hard_block)

        metadata = self._build_metadata(strategy_name, module_debug)
        metadata["entry_semantics_mode"] = entry_semantics_mode
        metadata["setup_index"] = setup_index
        metadata["trigger_index"] = trigger_index
        metadata["setup_pass"] = bool(setup_pass)
        metadata["trigger_pass"] = bool(trigger_pass)
        metadata["setup_volume_pass"] = bool(setup_volume_pass)
        metadata["setup_volume_reason"] = setup_volume_reason
        metadata["trigger_volume_pass"] = bool(trigger_volume_pass)
        metadata["trigger_volume_reason"] = trigger_volume_reason
        metadata["close_above_ma20_pass"] = close_above_ma20_pass
        metadata["ma20_slope_pass"] = ma20_slope_pass
        metadata["price_contraction_pass"] = price_contraction_pass
        metadata["close_strength_pass"] = close_strength_pass
        metadata["short_momentum_pass"] = short_momentum_pass
        metadata["final_selected"] = all_pass
        metadata["is_selected"] = all_pass
        return all_pass, metadata

    def _evaluate_chip_module(
        self,
        payload: OHLCVSeries,
        index: int,
    ) -> dict[str, Any]:
        enabled = self._cfg_bool("chip", "enable_chip_filter", False)
        foreign_enabled = self._cfg_bool("chip", "enable_foreign_buy_filter", False)
        trust_enabled = self._cfg_bool("chip", "enable_investment_trust_filter", False)
        lookback = self._cfg_int("chip", "chip_lookback", 20)

        if not enabled:
            return {
                "enabled": False,
                "passed": True,
                "metrics": {
                    "chip_lookback": lookback,
                    "enable_foreign_buy_filter": foreign_enabled,
                    "enable_investment_trust_filter": trust_enabled,
                    "foreign_field": None,
                    "foreign_cumulative_net_buy": None,
                    "investment_trust_field": None,
                    "investment_trust_cumulative_net_buy": None,
                },
                "reason": "disabled",
            }

        if index < 1:
            return {
                "enabled": True,
                "passed": False,
                "metrics": {
                    "chip_lookback": lookback,
                    "enable_foreign_buy_filter": foreign_enabled,
                    "enable_investment_trust_filter": trust_enabled,
                    "foreign_field": None,
                    "foreign_cumulative_net_buy": None,
                    "investment_trust_field": None,
                    "investment_trust_cumulative_net_buy": None,
                },
                "reason": "insufficient_history",
            }

        foreign_field, foreign_series = self._find_first_series(
            payload,
            "foreign_net_buy",
            "foreign_net_buy_shares",
            "foreign_buy_sell",
        )
        trust_field, trust_series = self._find_first_series(
            payload,
            "investment_trust_net_buy",
            "investment_trust_net_buy_shares",
            "trust_net_buy",
        )

        foreign_sum = self._window_sum(foreign_series, index=index - 1, lookback=lookback) if foreign_enabled else None
        trust_sum = self._window_sum(trust_series, index=index - 1, lookback=lookback) if trust_enabled else None
        active_checks = 0
        checks: list[bool] = []

        if foreign_enabled:
            active_checks += 1
            checks.append(foreign_sum is not None and foreign_sum > 0.0)
        if trust_enabled:
            active_checks += 1
            checks.append(trust_sum is not None and trust_sum > 0.0)

        if active_checks == 0:
            return {
                "enabled": True,
                "passed": True,
                "metrics": {
                    "chip_lookback": lookback,
                    "enable_foreign_buy_filter": foreign_enabled,
                    "enable_investment_trust_filter": trust_enabled,
                    "foreign_field": foreign_field,
                    "foreign_cumulative_net_buy": foreign_sum,
                    "investment_trust_field": trust_field,
                    "investment_trust_cumulative_net_buy": trust_sum,
                },
                "reason": "no_active_subfilter",
            }

        passed = any(checks)
        reason = None if passed else "chip_filter_not_met"
        if foreign_enabled and foreign_sum is None and trust_sum is None:
            reason = "missing_chip_data"
        if trust_enabled and trust_sum is None and foreign_sum is None:
            reason = "missing_chip_data"

        return {
            "enabled": True,
            "passed": passed,
            "metrics": {
                "chip_lookback": lookback,
                "enable_foreign_buy_filter": foreign_enabled,
                "enable_investment_trust_filter": trust_enabled,
                "foreign_field": foreign_field,
                "foreign_cumulative_net_buy": foreign_sum,
                "investment_trust_field": trust_field,
                "investment_trust_cumulative_net_buy": trust_sum,
            },
            "reason": reason,
        }

    def _evaluate_margin_module(
        self,
        payload: OHLCVSeries,
        close_values: list[float],
        index: int,
    ) -> dict[str, Any]:
        enabled = self._cfg_bool("margin", "enable_margin_filter", False)
        lookback = self._cfg_int("margin", "margin_lookback", 20)
        growth_limit = self._cfg_float("margin", "margin_growth_limit", 0.15)

        margin_field, margin_series = self._find_first_series(
            payload,
            "margin_balance",
            "margin_balance_shares",
            "margin_ratio",
        )

        if not enabled:
            return {
                "enabled": False,
                "passed": True,
                "metrics": {
                    "margin_field": margin_field,
                    "margin_lookback": lookback,
                    "margin_growth_limit": growth_limit,
                    "margin_today": None,
                    "margin_lookback_ago": None,
                    "margin_growth": None,
                    "close_at_lookback_high": None,
                    "margin_at_lookback_high": None,
                },
                "reason": "disabled",
            }

        if index < 1:
            return {
                "enabled": True,
                "passed": False,
                "metrics": {
                    "margin_field": margin_field,
                    "margin_lookback": lookback,
                    "margin_growth_limit": growth_limit,
                    "margin_today": None,
                    "margin_lookback_ago": None,
                    "margin_growth": None,
                    "close_at_lookback_high": None,
                    "margin_at_lookback_high": None,
                },
                "reason": "insufficient_history",
            }

        margin_today = self._series_value(margin_series, index - 1)
        margin_lookback_ago = self._series_value(margin_series, index - 1 - lookback)
        close_window_high = self._window_max(close_values, index=index, lookback=lookback)  # OHLCV unchanged
        margin_window_high = self._window_max(margin_series, index=index - 1, lookback=lookback)
        close_at_high = close_window_high is not None and close_values[index] >= close_window_high
        margin_at_high = margin_window_high is not None and margin_today is not None and margin_today >= margin_window_high

        if margin_today is None or margin_lookback_ago is None or margin_lookback_ago == 0.0:
            return {
                "enabled": True,
                "passed": False,
                "metrics": {
                    "margin_field": margin_field,
                    "margin_lookback": lookback,
                    "margin_growth_limit": growth_limit,
                    "margin_today": margin_today,
                    "margin_lookback_ago": margin_lookback_ago,
                    "margin_growth": None,
                    "close_at_lookback_high": close_at_high,
                    "margin_at_lookback_high": margin_at_high,
                },
                "reason": "missing_margin_data",
            }

        growth = (margin_today - margin_lookback_ago) / margin_lookback_ago
        growth_ok = growth <= growth_limit
        divergence_fail = (not close_at_high) and margin_at_high
        passed = growth_ok and (not divergence_fail)
        reason = None
        if not growth_ok:
            reason = "margin_growth_limit_exceeded"
        elif divergence_fail:
            reason = "margin_divergence_exclusion"

        return {
            "enabled": True,
            "passed": passed,
            "metrics": {
                "margin_field": margin_field,
                "margin_lookback": lookback,
                "margin_growth_limit": growth_limit,
                "margin_today": margin_today,
                "margin_lookback_ago": margin_lookback_ago,
                "margin_growth": growth,
                "close_at_lookback_high": close_at_high,
                "margin_at_lookback_high": margin_at_high,
            },
            "reason": reason,
        }

    def _evaluate_borrow_module(
        self,
        payload: OHLCVSeries,
        close_values: list[float],
        index: int,
    ) -> dict[str, Any]:
        enabled = self._cfg_bool("borrow", "enable_borrow_filter", False)
        lookback = self._cfg_int("borrow", "borrow_lookback", 20)
        growth_limit = self._cfg_float("borrow", "borrow_balance_growth_limit", 0.15)

        borrow_field, borrow_series = self._find_first_series(
            payload,
            "borrow_balance",
            "borrow_balance_shares",
            "borrow_ratio",
        )

        if not enabled:
            return {
                "enabled": False,
                "passed": True,
                "metrics": {
                    "borrow_field": borrow_field,
                    "borrow_lookback": lookback,
                    "borrow_balance_growth_limit": growth_limit,
                    "borrow_today": None,
                    "borrow_lookback_ago": None,
                    "borrow_growth": None,
                    "close_below_rolling_max": None,
                },
                "reason": "disabled",
            }

        if index < 1:
            return {
                "enabled": True,
                "passed": False,
                "metrics": {
                    "borrow_field": borrow_field,
                    "borrow_lookback": lookback,
                    "borrow_balance_growth_limit": growth_limit,
                    "borrow_today": None,
                    "borrow_lookback_ago": None,
                    "borrow_growth": None,
                    "close_below_rolling_max": None,
                },
                "reason": "insufficient_history",
            }

        borrow_today = self._series_value(borrow_series, index - 1)
        borrow_lookback_ago = self._series_value(borrow_series, index - 1 - lookback)
        close_window_high = self._window_max(close_values, index=index, lookback=lookback)  # OHLCV unchanged
        close_below_rolling_max = close_window_high is not None and close_values[index] < close_window_high

        if borrow_today is None or borrow_lookback_ago is None or borrow_lookback_ago == 0.0:
            return {
                "enabled": True,
                "passed": False,
                "metrics": {
                    "borrow_field": borrow_field,
                    "borrow_lookback": lookback,
                    "borrow_balance_growth_limit": growth_limit,
                    "borrow_today": borrow_today,
                    "borrow_lookback_ago": borrow_lookback_ago,
                    "borrow_growth": None,
                    "close_below_rolling_max": close_below_rolling_max,
                },
                "reason": "missing_borrow_data",
            }

        growth = (borrow_today - borrow_lookback_ago) / borrow_lookback_ago
        passed = not (growth > growth_limit and close_below_rolling_max)

        return {
            "enabled": True,
            "passed": passed,
            "metrics": {
                "borrow_field": borrow_field,
                "borrow_lookback": lookback,
                "borrow_balance_growth_limit": growth_limit,
                "borrow_today": borrow_today,
                "borrow_lookback_ago": borrow_lookback_ago,
                "borrow_growth": growth,
                "close_below_rolling_max": close_below_rolling_max,
            },
            "reason": None if passed else "borrow_growth_with_price_divergence",
        }

    def _evaluate_atr_pullback_module(
        self,
        high_values: list[float],
        low_values: list[float],
        close_values: list[float],
        index: int,
        high_n_current: float,
        ma60_current: float,
    ) -> dict[str, Any]:
        enabled = self._cfg_bool("atr_pullback", "use_atr_normalized_pullback", False)
        atr_period = self._cfg_int("atr_pullback", "atr_period", 14)
        drawdown_atr_norm_min = self._cfg_float("atr_pullback", "drawdown_atr_norm_min", 0.5)
        drawdown_atr_norm_max = self._cfg_float("atr_pullback", "drawdown_atr_norm_max", 3.0)
        dist_to_ma60_atr_max = self._cfg_float("atr_pullback", "dist_to_ma60_atr_max", 1.5)

        blank_metrics: dict[str, Any] = {
            "atr": None,
            "atr_pct": None,
            "drawdown_atr_norm": None,
            "dist_to_ma60_atr": None,
            "drawdown_atr_norm_min": drawdown_atr_norm_min,
            "drawdown_atr_norm_max": drawdown_atr_norm_max,
            "dist_to_ma60_atr_max": dist_to_ma60_atr_max,
            "atr_period": atr_period,
        }

        if not enabled:
            return {"enabled": False, "passed": True, "metrics": blank_metrics, "reason": "disabled"}

        if index < atr_period - 1:
            return {"enabled": True, "passed": False, "metrics": blank_metrics, "reason": "insufficient_history"}

        tr_values: list[float] = []
        for i in range(index - atr_period + 1, index + 1):
            if i == 0:
                tr = high_values[i] - low_values[i]
            else:
                tr = max(
                    high_values[i] - low_values[i],
                    abs(high_values[i] - close_values[i - 1]),
                    abs(low_values[i] - close_values[i - 1]),
                )
            tr_values.append(tr)

        atr = sum(tr_values) / len(tr_values)
        close_current = close_values[index]

        if close_current <= 0.0 or atr <= 0.0:
            return {"enabled": True, "passed": False, "metrics": blank_metrics, "reason": "invalid_price_or_atr"}

        atr_pct = atr / close_current
        drawdown_atr_norm = (
            (high_n_current - close_current) / high_n_current / atr_pct
            if high_n_current > 0.0 else 0.0
        )
        dist_to_ma60_atr = abs(close_current - ma60_current) / atr

        metrics: dict[str, Any] = {
            "atr": atr,
            "atr_pct": atr_pct,
            "drawdown_atr_norm": drawdown_atr_norm,
            "dist_to_ma60_atr": dist_to_ma60_atr,
            "drawdown_atr_norm_min": drawdown_atr_norm_min,
            "drawdown_atr_norm_max": drawdown_atr_norm_max,
            "dist_to_ma60_atr_max": dist_to_ma60_atr_max,
            "atr_period": atr_period,
        }

        passed = (
            drawdown_atr_norm_min <= drawdown_atr_norm <= drawdown_atr_norm_max
            and dist_to_ma60_atr <= dist_to_ma60_atr_max
        )
        return {
            "enabled": True,
            "passed": passed,
            "metrics": metrics,
            "reason": None if passed else "atr_pullback_range_not_met",
        }

    def _evaluate_price_contraction_module(
        self,
        high_values: list[float],
        low_values: list[float],
        close_values: list[float],
        index: int,
    ) -> dict[str, Any]:
        config_enabled = self._cfg_bool("price_contraction", "price_contract_enabled", True)
        range_short_lookback = self._cfg_int("price_contraction", "range_short_lookback", 5)
        range_long_lookback = self._cfg_int("price_contraction", "range_long_lookback", 20)
        range_contract_ratio_max = self._cfg_float("price_contraction", "range_contract_ratio_max", 0.7)
        range_percentile_max = self._cfg_optional_float("price_contraction", "range_percentile_max")

        blank_metrics: dict[str, Any] = {
            "range_short": None,
            "range_long": None,
            "range_ratio": None,
            "range_short_lookback": range_short_lookback,
            "range_long_lookback": range_long_lookback,
            "range_contract_ratio_max": range_contract_ratio_max,
            "range_percentile_max": range_percentile_max,
            "range_percentile_value": None,
            "price_contract_enabled_config": config_enabled,
            "ratio_gate_required": True,
        }

        high_short_max_list = rolling_max(high_values, window=range_short_lookback)
        low_short_min_list = rolling_min(low_values, window=range_short_lookback)
        high_long_max_list = rolling_max(high_values, window=range_long_lookback)
        low_long_min_list = rolling_min(low_values, window=range_long_lookback)

        high_short_max = high_short_max_list[index] if index < len(high_short_max_list) else None
        low_short_min = low_short_min_list[index] if index < len(low_short_min_list) else None
        high_long_max = high_long_max_list[index] if index < len(high_long_max_list) else None
        low_long_min = low_long_min_list[index] if index < len(low_long_min_list) else None

        if any(v is None for v in [high_short_max, low_short_min, high_long_max, low_long_min]):
            return {"enabled": True, "passed": False, "metrics": blank_metrics, "reason": "insufficient_history"}

        close_current = close_values[index]
        if close_current <= 0.0:
            return {"enabled": True, "passed": False, "metrics": blank_metrics, "reason": "invalid_close"}

        range_short = (high_short_max - low_short_min) / close_current
        range_long = (high_long_max - low_long_min) / close_current
        range_ratio = range_short / range_long if range_long > 0.0 else None
        range_percentile_value: float | None = None
        reason: str | None = None

        if range_percentile_max is None:
            percentile_pass = True
        else:
            start_idx = index - range_long_lookback + 1
            if start_idx < range_short_lookback - 1:
                return {"enabled": True, "passed": False, "metrics": blank_metrics, "reason": "insufficient_history"}
            short_ranges: list[float] = []
            for i in range(start_idx, index + 1):
                h = high_short_max_list[i] if i < len(high_short_max_list) else None
                lo = low_short_min_list[i] if i < len(low_short_min_list) else None
                c = close_values[i] if i < len(close_values) else 0.0
                if h is not None and lo is not None and c > 0.0:
                    short_ranges.append((h - lo) / c)
            if not short_ranges:
                return {"enabled": True, "passed": False, "metrics": blank_metrics, "reason": "insufficient_history"}
            short_ranges_sorted = sorted(short_ranges)
            pct_idx = min(
                int(len(short_ranges_sorted) * range_percentile_max / 100.0),
                len(short_ranges_sorted) - 1,
            )
            range_percentile_value = short_ranges_sorted[pct_idx]
            percentile_pass = range_short <= range_percentile_value

        if range_ratio is None:
            passed = False
            reason = "invalid_range_long_zero"
        else:
            ratio_pass = range_ratio <= range_contract_ratio_max
            passed = ratio_pass and percentile_pass
            reason = None if passed else "price_contraction_not_met"

        return {
            "enabled": True,
            "passed": passed,
            "metrics": {
                "range_short": range_short,
                "range_long": range_long,
                "range_ratio": range_ratio,
                "range_short_lookback": range_short_lookback,
                "range_long_lookback": range_long_lookback,
                "range_contract_ratio_max": range_contract_ratio_max,
                "range_percentile_max": range_percentile_max,
                "range_percentile_value": range_percentile_value,
                "price_contract_enabled_config": config_enabled,
                "ratio_gate_required": True,
            },
            "reason": reason,
        }

    def _evaluate_chip_scoring_module(
        self,
        payload: OHLCVSeries,
        close_values: list[float],
        index: int,
    ) -> dict[str, Any]:
        enabled = self._cfg_bool("chip_scoring", "enable_chip_scoring", False)
        foreign_weight = self._cfg_float("chip_scoring", "foreign_score_weight", 1.0)
        trust_weight = self._cfg_float("chip_scoring", "investment_trust_score_weight", 1.0)
        margin_weight = self._cfg_float("chip_scoring", "margin_score_weight", 0.5)
        borrow_weight = self._cfg_float("chip_scoring", "borrow_score_weight", 0.5)
        lookback = self._cfg_int("chip_scoring", "chip_scoring_lookback", 20)

        blank_metrics: dict[str, Any] = {
            "enable_chip_scoring": enabled,
            "foreign_score": None,
            "trust_score": None,
            "margin_score": None,
            "borrow_score": None,
            "total_chip_score": None,
            "chip_scoring_lookback": lookback,
        }

        if not enabled:
            return {"enabled": False, "passed": True, "metrics": blank_metrics, "reason": "disabled"}

        if index < 1:
            return {"enabled": True, "passed": True, "metrics": blank_metrics, "reason": "insufficient_history"}

        _, foreign_series = self._find_first_series(
            payload, "foreign_net_buy", "foreign_net_buy_shares", "foreign_buy_sell"
        )
        _, trust_series = self._find_first_series(
            payload, "investment_trust_net_buy", "investment_trust_net_buy_shares", "trust_net_buy"
        )
        _, margin_series = self._find_first_series(
            payload, "margin_balance", "margin_balance_shares", "margin_ratio"
        )
        _, borrow_series = self._find_first_series(
            payload, "borrow_balance", "borrow_balance_shares", "borrow_ratio"
        )

        foreign_sum = self._window_sum(foreign_series, index=index - 1, lookback=lookback) if foreign_series else None
        foreign_score: float | None = (1.0 if foreign_sum is not None and foreign_sum > 0.0 else 0.0) if foreign_series else None

        trust_sum = self._window_sum(trust_series, index=index - 1, lookback=lookback) if trust_series else None
        trust_score: float | None = (1.0 if trust_sum is not None and trust_sum > 0.0 else 0.0) if trust_series else None

        margin_today = self._series_value(margin_series, index - 1)
        margin_ago = self._series_value(margin_series, index - 1 - lookback)
        if margin_today is not None and margin_ago is not None:
            margin_score: float | None = 1.0 if margin_today <= margin_ago else 0.0
        else:
            margin_score = None

        borrow_today = self._series_value(borrow_series, index - 1)
        borrow_ago = self._series_value(borrow_series, index - 1 - lookback)
        if borrow_today is not None and borrow_ago is not None:
            borrow_growth = (borrow_today - borrow_ago) / borrow_ago if borrow_ago != 0.0 else 0.0
            borrow_score: float | None = 1.0 if borrow_growth <= 0.0 else 0.0
        else:
            borrow_score = None

        scores = [foreign_score, trust_score, margin_score, borrow_score]
        weights = [foreign_weight, trust_weight, margin_weight, borrow_weight]
        total = sum(w * s for w, s in zip(weights, scores) if s is not None)
        total_weight = sum(w for w, s in zip(weights, scores) if s is not None)
        total_chip_score = total / total_weight if total_weight > 0.0 else 0.0

        return {
            "enabled": True,
            "passed": True,
            "metrics": {
                "enable_chip_scoring": enabled,
                "foreign_score": foreign_score,
                "trust_score": trust_score,
                "margin_score": margin_score,
                "borrow_score": borrow_score,
                "total_chip_score": total_chip_score,
                "chip_scoring_lookback": lookback,
            },
            "reason": None,
        }

    def _build_metadata(
        self,
        strategy_name: str,
        module_debug: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        failure_reason = next(
            (
                f"{module_name}:{module_result['reason']}"
                for module_name, module_result in module_debug.items()
                if not module_result["passed"]
            ),
            None,
        )
        return {
            "strategy": strategy_name,
            "indicator": "pullback_trend_120d_optimized",
            "module_debug": module_debug,
            "failure_reason": failure_reason,
        }

    def _cfg_section(self, section: str) -> dict[str, Any]:
        value = self._config.get(section, {})
        if not isinstance(value, dict):
            return {}
        return value

    def _cfg_bool(self, section: str, key: str, default: bool) -> bool:
        return bool(self._cfg_section(section).get(key, default))

    def _cfg_int(self, section: str, key: str, default: int) -> int:
        return int(self._cfg_section(section).get(key, default))

    def _cfg_float(self, section: str, key: str, default: float) -> float:
        return float(self._cfg_section(section).get(key, default))

    def _cfg_optional_float(self, section: str, key: str) -> float | None:
        value = self._cfg_section(section).get(key)
        if value is None:
            return None
        return float(value)

    def _cfg_str(self, section: str, key: str, default: str) -> str:
        value = self._cfg_section(section).get(key, default)
        return str(value)

    @staticmethod
    def _merge_nested_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(base)
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = PullbackTrend120dOptimizedStrategy._merge_nested_dicts(merged[key], value)
                continue
            merged[key] = value
        return merged

    @staticmethod
    def _is_daily_bar_payload(payload: OHLCVSeries) -> bool:
        interval = payload.get("interval")
        if interval is None:
            return True
        if not isinstance(interval, str):
            return False
        return interval.lower() in {"1d", "d", "day", "daily"}

    @staticmethod
    def _as_float_list(value: object) -> list[float]:
        if not isinstance(value, list):
            return []
        return [float(item) for item in value]

    @staticmethod
    def _latest_optional_float(value: object, *, index: int) -> float | None:
        if isinstance(value, list):
            if not value:
                return None
            if index >= len(value):
                return None
            return float(value[index])
        if value is None:
            return None
        return float(value)

    @staticmethod
    def _find_first_series(
        payload: OHLCVSeries,
        *field_names: str,
    ) -> tuple[str | None, list[float]]:
        for field_name in field_names:
            values = payload.get(field_name)
            if isinstance(values, list):
                return field_name, [float(item) for item in values]
        return None, []

    @staticmethod
    def _series_value(values: list[float], index: int) -> float | None:
        if index < 0 or index >= len(values):
            return None
        return float(values[index])

    @staticmethod
    def _window_sum(values: list[float], *, index: int, lookback: int) -> float | None:
        start = index - lookback + 1
        if start < 0 or index >= len(values):
            return None
        return float(sum(values[start : index + 1]))

    @staticmethod
    def _window_max(values: list[float], *, index: int, lookback: int) -> float | None:
        start = index - lookback + 1
        if start < 0 or index >= len(values):
            return None
        return float(max(values[start : index + 1]))
