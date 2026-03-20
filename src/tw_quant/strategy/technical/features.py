"""Reusable technical-indicator feature utilities."""

from __future__ import annotations


def exponential_moving_average(values: list[float], window: int) -> list[float | None]:
    if window < 1:
        raise ValueError("window must be >= 1")
    if not values:
        return []

    result: list[float | None] = [None] * len(values)
    if len(values) < window:
        return result

    alpha = 2.0 / (window + 1)
    seed = sum(values[:window]) / window
    result[window - 1] = seed
    ema_prev = seed

    for index in range(window, len(values)):
        ema_prev = (values[index] - ema_prev) * alpha + ema_prev
        result[index] = ema_prev

    return result


def rolling_max(values: list[float], window: int) -> list[float | None]:
    if window < 1:
        raise ValueError("window must be >= 1")
    if not values:
        return []

    result: list[float | None] = [None] * len(values)
    for index in range(window - 1, len(values)):
        result[index] = max(values[index - window + 1 : index + 1])
    return result


def rolling_min(values: list[float], window: int) -> list[float | None]:
    if window < 1:
        raise ValueError("window must be >= 1")
    if not values:
        return []

    result: list[float | None] = [None] * len(values)
    for index in range(window - 1, len(values)):
        result[index] = min(values[index - window + 1 : index + 1])
    return result


def macd_histogram(
    values: list[float],
    fast_window: int = 12,
    slow_window: int = 26,
    signal_window: int = 9,
) -> list[float | None]:
    if fast_window < 1 or slow_window < 1 or signal_window < 1:
        raise ValueError("window must be >= 1")
    if fast_window >= slow_window:
        raise ValueError("fast_window must be < slow_window")
    if not values:
        return []

    ema_fast = exponential_moving_average(values, fast_window)
    ema_slow = exponential_moving_average(values, slow_window)

    macd_line: list[float | None] = [None] * len(values)
    compact_macd: list[float] = []
    for index in range(len(values)):
        fast = ema_fast[index]
        slow = ema_slow[index]
        if fast is None or slow is None:
            continue
        macd_value = fast - slow
        macd_line[index] = macd_value
        compact_macd.append(macd_value)

    signal_compact = exponential_moving_average(compact_macd, signal_window)
    signal_line: list[float | None] = [None] * len(values)
    compact_index = 0
    for index, macd_value in enumerate(macd_line):
        if macd_value is None:
            continue
        signal_line[index] = signal_compact[compact_index]
        compact_index += 1

    histogram: list[float | None] = [None] * len(values)
    for index in range(len(values)):
        macd_value = macd_line[index]
        signal_value = signal_line[index]
        if macd_value is None or signal_value is None:
            continue
        histogram[index] = macd_value - signal_value

    return histogram


def is_negative_histogram_above_prior_negative_min(
    histogram: list[float | None],
    lookback: int,
    *,
    index: int | None = None,
) -> bool:
    if lookback < 1:
        raise ValueError("lookback must be >= 1")
    if not histogram:
        return False

    current_index = len(histogram) - 1 if index is None else index
    if current_index < 0 or current_index >= len(histogram):
        raise IndexError("index out of range")

    current = histogram[current_index]
    if current is None or current >= 0.0:
        return False

    start = max(0, current_index - lookback)
    prior_negatives = [
        value
        for value in histogram[start:current_index]
        if value is not None and value < 0.0
    ]
    if not prior_negatives:
        return False

    return current > min(prior_negatives)


def simple_moving_average(values: list[float], window: int) -> list[float | None]:
    if window < 1:
        raise ValueError("window must be >= 1")
    if not values:
        return []

    result: list[float | None] = [None] * len(values)
    running_sum = 0.0

    for index, value in enumerate(values):
        running_sum += value
        if index >= window:
            running_sum -= values[index - window]
        if index >= window - 1:
            result[index] = running_sum / window

    return result


def crossover_direction(
    short_ma: list[float | None], long_ma: list[float | None]
) -> list[str]:
    if len(short_ma) != len(long_ma):
        raise ValueError("short_ma and long_ma must have same length")

    directions: list[str] = []
    for index in range(len(short_ma)):
        if index == 0:
            directions.append("no_cross")
            continue

        prev_short = short_ma[index - 1]
        prev_long = long_ma[index - 1]
        current_short = short_ma[index]
        current_long = long_ma[index]

        if (
            prev_short is None
            or prev_long is None
            or current_short is None
            or current_long is None
        ):
            directions.append("no_cross")
            continue

        if prev_short <= prev_long and current_short > current_long:
            directions.append("bullish_cross")
        elif prev_short >= prev_long and current_short < current_long:
            directions.append("bearish_cross")
        else:
            directions.append("no_cross")

    return directions
