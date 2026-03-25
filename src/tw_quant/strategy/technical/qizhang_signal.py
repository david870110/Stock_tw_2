"""Qizhang signal adapter for daily selection workflows."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.tw_quant.schema.models import OHLCVBar, OrderIntent, SignalRecord
from src.tw_quant.strategy.interfaces import StrategyContext
from src.tw_quant.strategy.technical.features import exponential_moving_average
from src.tw_quant.utils.indicators import calculate_rsi

HistorySource = Callable[[], dict[str, list[OHLCVBar]]]


@dataclass(frozen=True, slots=True)
class _QizhangSignalProfile:
    name: str
    indicator: str
    explosive_close_metric_key: str
    explosive_close_metric_threshold: float
    explosive_requires_ma60: bool
    explosive_rsi_min: float | None
    explosive_macd_min: float | None
    anchor_close_metric_key: str
    anchor_close_metric_threshold: float
    anchor_requires_ma60: bool
    anchor_rsi_min: float
    anchor_macd_min: float
    anchor_close_vs_ma60_min: float | None


_LEGACY_QIZHANG_SIGNAL_PROFILE = _QizhangSignalProfile(
    name="legacy",
    indicator="qizhang_signal",
    explosive_close_metric_key="close_pos",
    explosive_close_metric_threshold=0.60,
    explosive_requires_ma60=False,
    explosive_rsi_min=None,
    explosive_macd_min=None,
    anchor_close_metric_key="close_pos",
    anchor_close_metric_threshold=0.50,
    anchor_requires_ma60=False,
    anchor_rsi_min=45.0,
    anchor_macd_min=0.0,
    anchor_close_vs_ma60_min=-0.03,
)

_IMPROVE_QIZHANG_SIGNAL_PROFILE = _QizhangSignalProfile(
    name="improve",
    indicator="qizhang_improve_signal",
    explosive_close_metric_key="close_pos",
    explosive_close_metric_threshold=0.70,
    explosive_requires_ma60=True,
    explosive_rsi_min=55.0,
    explosive_macd_min=0.0,
    anchor_close_metric_key="close_pos",
    anchor_close_metric_threshold=0.70,
    anchor_requires_ma60=True,
    anchor_rsi_min=55.0,
    anchor_macd_min=0.0,
    anchor_close_vs_ma60_min=None,
)

_IMPROVE_V15_QIZHANG_SIGNAL_PROFILE = _QizhangSignalProfile(
    name="improve_v15",
    indicator="qizhang_improve_signal_v15",
    explosive_close_metric_key="close_position_20d",
    explosive_close_metric_threshold=0.70,
    explosive_requires_ma60=False,
    explosive_rsi_min=50.0,
    explosive_macd_min=0.15,
    anchor_close_metric_key="close_position_20d",
    anchor_close_metric_threshold=0.70,
    anchor_requires_ma60=False,
    anchor_rsi_min=50.0,
    anchor_macd_min=0.15,
    anchor_close_vs_ma60_min=0.0,
)

_QIZHANG_SIGNAL_PROFILES = {
    "legacy": _LEGACY_QIZHANG_SIGNAL_PROFILE,
    "improve": _IMPROVE_QIZHANG_SIGNAL_PROFILE,
    "improve_v15": _IMPROVE_V15_QIZHANG_SIGNAL_PROFILE,
}


class QizhangSignalStrategy:
    def __init__(self, history_source: HistorySource, *, profile: str = "legacy") -> None:
        normalized_profile = str(profile).strip().lower()
        if normalized_profile not in _QIZHANG_SIGNAL_PROFILES:
            raise ValueError(f"Unsupported qizhang signal profile: {profile}")
        self._history_source = history_source
        self._profile = _QIZHANG_SIGNAL_PROFILES[normalized_profile]

    def generate_signals(self, context: StrategyContext) -> list[SignalRecord]:
        signals: list[SignalRecord] = []
        for symbol, history in self._history_source().items():
            passed, metadata, signal, score = self._evaluate_symbol(history, context.strategy_name)
            signals.append(
                SignalRecord(
                    symbol=symbol,
                    timestamp=context.as_of,
                    signal=signal,
                    score=score,
                    metadata=metadata,
                )
            )
        return signals

    def build_orders(self, context: StrategyContext, selections: list[SignalRecord]) -> list[OrderIntent]:
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
        history: list[OHLCVBar],
        strategy_name: str,
    ) -> tuple[bool, dict[str, Any], str, float]:
        metadata: dict[str, Any] = {
            "strategy": strategy_name,
            "indicator": self._profile.indicator,
        }
        if len(history) < 61:
            metadata.update(
                {
                    "reason": "insufficient_history",
                    "required_bars": 61,
                    "provided_bars": len(history),
                }
            )
            return False, metadata, "hold", 0.0

        snapshot = _build_snapshot(history)
        if snapshot is None:
            metadata.update({"reason": "snapshot_unavailable"})
            return False, metadata, "hold", 0.0

        if self._profile.name == "improve_v15":
            sig_explosive_checks = self._build_sig_explosive_checks_v15(snapshot)
            sig_anchor_checks = self._build_sig_anchor_checks_v15(snapshot)
        else:
            sig_explosive_checks = self._build_sig_explosive_checks(snapshot)
            sig_anchor_checks = self._build_sig_anchor_checks(snapshot)
        sig_explosive = all(sig_explosive_checks.values())
        sig_anchor = all(sig_anchor_checks.values())
        if sig_explosive:
            sig_anchor = False

        metadata.update(
            {
                "selected_setup": "sig_explosive" if sig_explosive else ("sig_anchor" if sig_anchor else ""),
                "signal_formula": "sig_explosive | sig_anchor",
                "profile": self._profile.name,
                "price_change_pct": snapshot["price_change_pct"],
                "volume_ratio_5": snapshot["volume_ratio_5"],
                "volume_ratio_20": snapshot["volume_ratio_20"],
                "close_pos": snapshot["close_pos"],
                "close_position_20d": snapshot["close_position_20d"],
                "close": snapshot["close"],
                "ma_20": snapshot["ma_20"],
                "ma_60": snapshot["ma_60"],
                "close_vs_ma20": snapshot["close_vs_ma20"],
                "close_vs_ma60": snapshot["close_vs_ma60"],
                "rsi_14": snapshot["rsi_14"],
                "macd_histogram": snapshot["macd_histogram"],
                "net_flow": snapshot["net_flow"],
                "sig_explosive": sig_explosive,
                "sig_anchor": sig_anchor,
            }
        )
        metadata.update(self._build_threshold_metadata())
        metadata.update(_prefix_check_keys("sig_explosive", sig_explosive_checks))
        metadata.update(_prefix_check_keys("sig_anchor", sig_anchor_checks))

        if sig_explosive or sig_anchor:
            score = 1.0 if sig_explosive else 0.9
            return True, metadata, "buy", score
        return False, metadata, "hold", 0.0

    def _build_sig_explosive_checks(self, snapshot: dict[str, float | int]) -> dict[str, bool]:
        checks = {
            "price_change_pct": snapshot["price_change_pct"] >= 0.05,
            "volume_ratio_5": snapshot["volume_ratio_5"] >= 1.45,
            "volume_ratio_20": snapshot["volume_ratio_20"] >= 1.70,
            self._profile.explosive_close_metric_key: (
                snapshot[self._profile.explosive_close_metric_key] >= self._profile.explosive_close_metric_threshold
            ),
            "close_gt_ma_20": snapshot["close"] > snapshot["ma_20"],
            "net_flow": snapshot["net_flow"] > 0,
        }
        if self._profile.explosive_requires_ma60:
            checks["close_gt_ma_60"] = snapshot["close"] > snapshot["ma_60"]
        if self._profile.explosive_rsi_min is not None:
            checks["rsi_14"] = snapshot["rsi_14"] >= self._profile.explosive_rsi_min
        if self._profile.explosive_macd_min is not None:
            checks["macd_histogram"] = snapshot["macd_histogram"] > self._profile.explosive_macd_min
        return checks

    def _build_sig_anchor_checks(self, snapshot: dict[str, float | int]) -> dict[str, bool]:
        checks = {
            "volume_ratio_5": snapshot["volume_ratio_5"] >= 3.0,
            "volume_ratio_20": snapshot["volume_ratio_20"] >= 1.70,
            self._profile.anchor_close_metric_key: (
                snapshot[self._profile.anchor_close_metric_key] >= self._profile.anchor_close_metric_threshold
            ),
            "close_gt_ma_20": snapshot["close"] > snapshot["ma_20"],
            "net_flow": snapshot["net_flow"] > 0,
            "rsi_14": snapshot["rsi_14"] >= self._profile.anchor_rsi_min,
            "macd_histogram": snapshot["macd_histogram"] > self._profile.anchor_macd_min,
        }
        if self._profile.anchor_requires_ma60:
            checks["close_gt_ma_60"] = snapshot["close"] > snapshot["ma_60"]
        if self._profile.anchor_close_vs_ma60_min is not None:
            checks["close_vs_ma60"] = snapshot["close_vs_ma60"] >= self._profile.anchor_close_vs_ma60_min
        return checks

    def _build_threshold_metadata(self) -> dict[str, float]:
        metadata: dict[str, float] = {
            "threshold_sig_explosive_price_change_pct_min": 0.05,
            "threshold_sig_explosive_volume_ratio_5_min": 1.45,
            "threshold_sig_explosive_volume_ratio_20_min": 1.70,
            "threshold_sig_anchor_volume_ratio_5_min": 3.0,
            "threshold_sig_anchor_volume_ratio_20_min": 1.70,
            f"threshold_sig_explosive_{self._profile.explosive_close_metric_key}_min": self._profile.explosive_close_metric_threshold,
            f"threshold_sig_anchor_{self._profile.anchor_close_metric_key}_min": self._profile.anchor_close_metric_threshold,
        }
        if self._profile.explosive_rsi_min is not None:
            metadata["threshold_sig_explosive_rsi_14_min"] = self._profile.explosive_rsi_min
        if self._profile.explosive_macd_min is not None:
            metadata["threshold_sig_explosive_macd_histogram_min"] = self._profile.explosive_macd_min
        metadata["threshold_sig_anchor_rsi_14_min"] = self._profile.anchor_rsi_min
        metadata["threshold_sig_anchor_macd_histogram_min"] = self._profile.anchor_macd_min
        if self._profile.anchor_close_vs_ma60_min is not None:
            metadata["threshold_sig_anchor_close_vs_ma60_min"] = self._profile.anchor_close_vs_ma60_min
        if self._profile.name == "improve_v15":
            metadata.update(
                {
                    "threshold_sig_explosive_close_vs_ma20_max": 0.30,
                    "threshold_sig_explosive_close_vs_ma60_min": 0.0,
                    "threshold_sig_explosive_close_vs_ma60_max": 0.45,
                    "threshold_sig_explosive_rsi_14_max": 82.0,
                    "threshold_sig_anchor_branch_rsi_14_min": 45.0,
                    "threshold_sig_anchor_branch_macd_histogram_min": 0.0,
                    "threshold_sig_anchor_close_vs_ma20_max": 0.30,
                    "threshold_sig_anchor_close_vs_ma60_min": 0.0,
                    "threshold_sig_anchor_close_vs_ma60_max": 0.45,
                    "threshold_sig_anchor_rsi_14_max": 82.0,
                }
            )
        return metadata

    def _build_sig_explosive_checks_v15(self, snapshot: dict[str, float | int]) -> dict[str, bool]:
        return {
            "price_change_pct": snapshot["price_change_pct"] >= 0.05,
            "volume_ratio_5": snapshot["volume_ratio_5"] >= 1.45,
            "volume_ratio_20": snapshot["volume_ratio_20"] >= 1.70,
            "close_position_20d": snapshot["close_position_20d"] >= 0.70,
            "close_gt_ma_20": snapshot["close"] > snapshot["ma_20"],
            "close_vs_ma20_max": snapshot["close_vs_ma20"] <= 0.30,
            "close_vs_ma60_min": snapshot["close_vs_ma60"] >= 0.0,
            "close_vs_ma60_max": snapshot["close_vs_ma60"] <= 0.45,
            "net_flow": snapshot["net_flow"] > 0,
            "rsi_14": snapshot["rsi_14"] >= 50.0,
            "rsi_14_max": snapshot["rsi_14"] <= 82.0,
            "macd_histogram": snapshot["macd_histogram"] > 0.15,
        }

    def _build_sig_anchor_checks_v15(self, snapshot: dict[str, float | int]) -> dict[str, bool]:
        return {
            "volume_ratio_5": snapshot["volume_ratio_5"] >= 3.0,
            "volume_ratio_20": snapshot["volume_ratio_20"] >= 1.70,
            "branch_rsi_14": snapshot["rsi_14"] >= 45.0,
            "branch_macd_histogram": snapshot["macd_histogram"] > 0.0,
            "close_position_20d": snapshot["close_position_20d"] >= 0.70,
            "close_gt_ma_20": snapshot["close"] > snapshot["ma_20"],
            "close_vs_ma20_max": snapshot["close_vs_ma20"] <= 0.30,
            "close_vs_ma60_min": snapshot["close_vs_ma60"] >= 0.0,
            "close_vs_ma60_max": snapshot["close_vs_ma60"] <= 0.45,
            "net_flow": snapshot["net_flow"] > 0,
            "rsi_14": snapshot["rsi_14"] >= 50.0,
            "rsi_14_max": snapshot["rsi_14"] <= 82.0,
            "macd_histogram": snapshot["macd_histogram"] > 0.15,
        }


def _build_snapshot(history: list[OHLCVBar]) -> dict[str, float | int] | None:
    current = history[-1]
    previous = history[-2]
    prior_5 = history[-6:-1]
    prior_20 = history[-21:-1]
    if len(prior_5) < 5 or len(prior_20) < 20:
        return None

    closes = [float(bar.close) for bar in history]
    ma_20 = _simple_ma(closes, 20)
    ma_60 = _simple_ma(closes, 60)
    rsi_14 = calculate_rsi(
        [{"close": float(bar.close)} for bar in history],
        period=14,
    )[-1]
    macd_hist = _macd_histogram(closes)
    if ma_20 is None or ma_60 is None or rsi_14 is None or macd_hist is None:
        return None

    day_range = float(current.high) - float(current.low)
    close_pos = 0.5 if day_range == 0 else (float(current.close) - float(current.low)) / day_range
    rolling_close_20 = closes[-20:]
    close_position_20d = _resolve_close_position(
        close=float(current.close),
        rolling_low=min(rolling_close_20),
        rolling_high=max(rolling_close_20),
    )
    avg_volume_5 = sum(float(bar.volume) for bar in prior_5) / len(prior_5)
    avg_volume_20 = sum(float(bar.volume) for bar in prior_20) / len(prior_20)
    prev_close = float(previous.close)
    if avg_volume_5 <= 0 or avg_volume_20 <= 0 or prev_close <= 0:
        return None

    volume_ratio_5 = float(current.volume) / avg_volume_5
    volume_ratio_20 = float(current.volume) / avg_volume_20
    net_flow = 1 if (
        float(current.close) > float(current.open)
        and close_pos >= 0.5
        and volume_ratio_5 > 1.0
    ) else 0
    return {
        "price_change_pct": float(current.close) / prev_close - 1.0,
        "volume_ratio_5": volume_ratio_5,
        "volume_ratio_20": volume_ratio_20,
        "close_pos": close_pos,
        "close_position_20d": close_position_20d,
        "close": float(current.close),
        "ma_20": ma_20,
        "ma_60": ma_60,
        "close_vs_ma20": float(current.close) / ma_20 - 1.0,
        "close_vs_ma60": float(current.close) / ma_60 - 1.0,
        "rsi_14": float(rsi_14),
        "macd_histogram": macd_hist,
        "net_flow": net_flow,
    }


def _prefix_check_keys(prefix: str, checks: dict[str, bool]) -> dict[str, bool]:
    return {
        f"check_{prefix}_{key}": value
        for key, value in checks.items()
    }


def _resolve_close_position(*, close: float, rolling_low: float, rolling_high: float) -> float:
    price_range = rolling_high - rolling_low
    if price_range == 0.0:
        return 0.5
    return (close - rolling_low) / price_range


def _simple_ma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def _macd_histogram(values: list[float]) -> float | None:
    if len(values) < 35:
        return None
    ema12 = exponential_moving_average(values, 12)
    ema26 = exponential_moving_average(values, 26)
    macd_line = [
        (fast - slow) if fast is not None and slow is not None else None
        for fast, slow in zip(ema12, ema26)
    ]
    usable_macd = [value if value is not None else 0.0 for value in macd_line]
    signal = exponential_moving_average(usable_macd, 9)
    if macd_line[-1] is None or signal[-1] is None:
        return None
    return float(macd_line[-1] - signal[-1])
