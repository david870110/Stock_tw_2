from __future__ import annotations

from .basic_selection_contract import BasicSelectionContract
from ..utils.data_source import get_daily_data
from ..utils.indicators import calculate_ma, calculate_macd, calculate_rsi


class QizhangSelectionStrategy(BasicSelectionContract):
    """Report-aligned breakout selection with explosive and early-entry setups."""

    def get_candidates(self, stock_list, as_of_date):
        candidates = []
        for stock in stock_list:
            data = get_daily_data(stock, as_of_date, lookback=80)
            snapshot = self._build_snapshot(data)
            if snapshot is None:
                continue

            setup_a_checks = {
                "price_change_pct_ge_0_05": snapshot["price_change_pct"] >= 0.05,
                "volume_ratio_5_ge_1_45": snapshot["volume_ratio_5"] >= 1.45,
                "volume_ratio_20_ge_1_70": snapshot["volume_ratio_20"] >= 1.70,
                "close_pos_ge_0_60": snapshot["close_pos"] >= 0.60,
                "close_gt_ma_20": snapshot["close"] > snapshot["ma_20"],
                "net_flow_positive": snapshot["net_flow"] > 0,
            }
            setup_b_checks = {
                "volume_ratio_5_ge_3_0": snapshot["volume_ratio_5"] >= 3.0,
                "volume_ratio_20_ge_1_70": snapshot["volume_ratio_20"] >= 1.70,
                "close_pos_ge_0_50": snapshot["close_pos"] >= 0.50,
                "close_gt_ma_20": snapshot["close"] > snapshot["ma_20"],
                "net_flow_positive": snapshot["net_flow"] > 0,
                "rsi_14_ge_45": snapshot["rsi_14"] >= 45,
                "macd_histogram_gt_0": snapshot["macd_histogram"] > 0,
                "close_vs_ma60_ge_neg_0_03": snapshot["close_vs_ma60"] >= -0.03,
            }

            setup_a = all(setup_a_checks.values())
            setup_b = all(setup_b_checks.values())

            if setup_a:
                setup_b = False

            if not (setup_a or setup_b):
                continue

            candidates.append(
                {
                    "stock": stock,
                    "date": as_of_date,
                    "reason": {
                        "setup_a": setup_a,
                        "setup_b": setup_b,
                        "selected_setup": "A" if setup_a else "B",
                        "setup_a_checks": setup_a_checks,
                        "setup_b_checks": setup_b_checks,
                    },
                    "indicators": {
                        "price_change_pct": snapshot["price_change_pct"],
                        "close_pos": snapshot["close_pos"],
                        "volume_ratio_5": snapshot["volume_ratio_5"],
                        "volume_ratio_20": snapshot["volume_ratio_20"],
                        "net_flow": snapshot["net_flow"],
                        "ma_20": snapshot["ma_20"],
                        "ma_60": snapshot["ma_60"],
                        "close_vs_ma60": snapshot["close_vs_ma60"],
                        "rsi_14": snapshot["rsi_14"],
                        "macd_histogram": snapshot["macd_histogram"],
                        "prior_20d_high": snapshot["prior_20d_high"],
                        "close": snapshot["close"],
                        "open": snapshot["open"],
                        "high": snapshot["high"],
                        "low": snapshot["low"],
                        "volume": snapshot["volume"],
                    },
                }
            )
        return candidates

    def _build_snapshot(self, data):
        if not data or len(data) < 61:
            return None

        current = data[-1]
        previous = data[-2]
        prior_5 = data[-6:-1]
        prior_20 = data[-21:-1]
        if len(prior_5) < 5 or len(prior_20) < 20:
            return None

        ma_20_series = calculate_ma(data, period=20)
        ma_60_series = calculate_ma(data, period=60)
        macd = calculate_macd(data)
        rsi = calculate_rsi(data)
        ma_20 = ma_20_series[-1]
        ma_60 = ma_60_series[-1]
        macd_histogram = None
        if macd["macd"][-1] is not None and macd["signal"][-1] is not None:
            macd_histogram = macd["macd"][-1] - macd["signal"][-1]
        rsi_14 = rsi[-1]
        if ma_20 is None or ma_60 is None:
            return None
        if macd_histogram is None or rsi_14 is None:
            return None

        prev_close = previous["close"]
        day_range = current["high"] - current["low"]
        close_pos = 0.5 if day_range == 0 else (current["close"] - current["low"]) / day_range
        avg_volume_5 = sum(row["volume"] for row in prior_5) / len(prior_5)
        avg_volume_20 = sum(row["volume"] for row in prior_20) / len(prior_20)
        if avg_volume_5 <= 0 or avg_volume_20 <= 0 or prev_close <= 0:
            return None

        volume_ratio_5 = current["volume"] / avg_volume_5
        volume_ratio_20 = current["volume"] / avg_volume_20
        prior_20d_high = max(row["high"] for row in prior_20)
        price_change_pct = current["close"] / prev_close - 1
        net_flow = 1 if (
            current["close"] > current["open"]
            and close_pos >= 0.5
            and volume_ratio_5 > 1.0
        ) else 0
        close_vs_ma60 = current["close"] / ma_60 - 1

        return {
            "open": current["open"],
            "high": current["high"],
            "low": current["low"],
            "close": current["close"],
            "volume": current["volume"],
            "price_change_pct": price_change_pct,
            "close_pos": close_pos,
            "volume_ratio_5": volume_ratio_5,
            "volume_ratio_20": volume_ratio_20,
            "net_flow": net_flow,
            "ma_20": ma_20,
            "ma_60": ma_60,
            "close_vs_ma60": close_vs_ma60,
            "rsi_14": rsi_14,
            "macd_histogram": macd_histogram,
            "prior_20d_high": prior_20d_high,
        }
