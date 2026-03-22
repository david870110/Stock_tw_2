"""Qizhang signal adapter for daily selection workflows."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.tw_quant.schema.models import OHLCVBar, OrderIntent, SignalRecord
from src.tw_quant.strategy.interfaces import StrategyContext
from src.tw_quant.strategy.technical.features import exponential_moving_average
from src.tw_quant.utils.indicators import calculate_rsi

HistorySource = Callable[[], dict[str, list[OHLCVBar]]]


class QizhangSignalStrategy:
    def __init__(self, history_source: HistorySource) -> None:
        self._history_source = history_source

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
            "indicator": "qizhang_signal",
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

        sig_explosive_checks = {
            "price_change_pct": snapshot["price_change_pct"] >= 0.05,
            "volume_ratio_5": snapshot["volume_ratio_5"] >= 1.45,
            "volume_ratio_20": snapshot["volume_ratio_20"] >= 1.70,
            "close_pos": snapshot["close_pos"] >= 0.60,
            "close_gt_ma_20": snapshot["close"] > snapshot["ma_20"],
            "net_flow": snapshot["net_flow"] > 0,
        }
        sig_anchor_checks = {
            "volume_ratio_5": snapshot["volume_ratio_5"] >= 3.0,
            "volume_ratio_20": snapshot["volume_ratio_20"] >= 1.70,
            "close_pos": snapshot["close_pos"] >= 0.50,
            "close_gt_ma_20": snapshot["close"] > snapshot["ma_20"],
            "net_flow": snapshot["net_flow"] > 0,
            "rsi_14": snapshot["rsi_14"] >= 45.0,
            "macd_histogram": snapshot["macd_histogram"] > 0.0,
            "close_vs_ma60": snapshot["close_vs_ma60"] >= -0.03,
        }
        sig_explosive = all(sig_explosive_checks.values())
        sig_anchor = all(sig_anchor_checks.values())
        if sig_explosive:
            sig_anchor = False

        metadata.update(
            {
                "selected_setup": "sig_explosive" if sig_explosive else ("sig_anchor" if sig_anchor else ""),
                "signal_formula": "sig_explosive | sig_anchor",
                "price_change_pct": snapshot["price_change_pct"],
                "volume_ratio_5": snapshot["volume_ratio_5"],
                "volume_ratio_20": snapshot["volume_ratio_20"],
                "close_pos": snapshot["close_pos"],
                "close": snapshot["close"],
                "ma_20": snapshot["ma_20"],
                "ma_60": snapshot["ma_60"],
                "close_vs_ma60": snapshot["close_vs_ma60"],
                "rsi_14": snapshot["rsi_14"],
                "macd_histogram": snapshot["macd_histogram"],
                "net_flow": snapshot["net_flow"],
                "threshold_sig_explosive_price_change_pct_min": 0.05,
                "threshold_sig_explosive_volume_ratio_5_min": 1.45,
                "threshold_sig_explosive_volume_ratio_20_min": 1.70,
                "threshold_sig_explosive_close_pos_min": 0.60,
                "threshold_sig_anchor_volume_ratio_5_min": 3.0,
                "threshold_sig_anchor_volume_ratio_20_min": 1.70,
                "threshold_sig_anchor_close_pos_min": 0.50,
                "threshold_sig_anchor_rsi_14_min": 45.0,
                "threshold_sig_anchor_macd_histogram_min": 0.0,
                "threshold_sig_anchor_close_vs_ma60_min": -0.03,
                "check_sig_explosive_price_change_pct": sig_explosive_checks["price_change_pct"],
                "check_sig_explosive_volume_ratio_5": sig_explosive_checks["volume_ratio_5"],
                "check_sig_explosive_volume_ratio_20": sig_explosive_checks["volume_ratio_20"],
                "check_sig_explosive_close_pos": sig_explosive_checks["close_pos"],
                "check_sig_explosive_close_gt_ma_20": sig_explosive_checks["close_gt_ma_20"],
                "check_sig_explosive_net_flow": sig_explosive_checks["net_flow"],
                "check_sig_anchor_volume_ratio_5": sig_anchor_checks["volume_ratio_5"],
                "check_sig_anchor_volume_ratio_20": sig_anchor_checks["volume_ratio_20"],
                "check_sig_anchor_close_pos": sig_anchor_checks["close_pos"],
                "check_sig_anchor_close_gt_ma_20": sig_anchor_checks["close_gt_ma_20"],
                "check_sig_anchor_net_flow": sig_anchor_checks["net_flow"],
                "check_sig_anchor_rsi_14": sig_anchor_checks["rsi_14"],
                "check_sig_anchor_macd_histogram": sig_anchor_checks["macd_histogram"],
                "check_sig_anchor_close_vs_ma60": sig_anchor_checks["close_vs_ma60"],
                "sig_explosive": sig_explosive,
                "sig_anchor": sig_anchor,
            }
        )

        if sig_explosive or sig_anchor:
            score = 1.0 if sig_explosive else 0.9
            return True, metadata, "buy", score
        return False, metadata, "hold", 0.0


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
        "close": float(current.close),
        "ma_20": ma_20,
        "ma_60": ma_60,
        "close_vs_ma60": float(current.close) / ma_60 - 1.0,
        "rsi_14": float(rsi_14),
        "macd_histogram": macd_hist,
        "net_flow": net_flow,
    }


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
