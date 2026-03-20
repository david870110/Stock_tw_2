"""Contract tests for technical feature utility primitives."""

import pytest

from src.tw_quant.strategy.technical.features import (
    crossover_direction,
    exponential_moving_average,
    is_negative_histogram_above_prior_negative_min,
    macd_histogram,
    rolling_max,
    rolling_min,
    simple_moving_average,
)


def test_simple_moving_average_shape_and_warmup_none_entries() -> None:
    values = [1.0, 2.0, 3.0, 4.0]
    result = simple_moving_average(values, window=3)

    assert len(result) == len(values)
    assert result[:2] == [None, None]
    assert result[2:] == [2.0, 3.0]


def test_simple_moving_average_empty_input_returns_empty() -> None:
    assert simple_moving_average([], window=2) == []


def test_simple_moving_average_invalid_window_raises_value_error() -> None:
    with pytest.raises(ValueError):
        simple_moving_average([1.0, 2.0], window=0)

    with pytest.raises(ValueError):
        simple_moving_average([1.0, 2.0], window=-1)


def test_crossover_direction_detects_bullish_cross_case() -> None:
    short_ma = [None, 1.0, 2.0]
    long_ma = [None, 1.5, 1.6]

    result = crossover_direction(short_ma, long_ma)
    assert result == ["no_cross", "no_cross", "bullish_cross"]


def test_crossover_direction_detects_bearish_cross_case() -> None:
    short_ma = [None, 2.0, 1.0]
    long_ma = [None, 1.5, 1.4]

    result = crossover_direction(short_ma, long_ma)
    assert result == ["no_cross", "no_cross", "bearish_cross"]


def test_crossover_direction_no_cross_with_none_handling() -> None:
    short_ma = [None, None, 3.0]
    long_ma = [None, 2.0, 2.5]

    result = crossover_direction(short_ma, long_ma)
    assert result == ["no_cross", "no_cross", "no_cross"]


def test_exponential_moving_average_shape_and_seed() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0]

    ema = exponential_moving_average(values, window=3)

    assert len(ema) == len(values)
    assert ema[:2] == [None, None]
    assert ema[2] == 2.0
    assert ema[3] == 3.0
    assert ema[4] == 4.0


def test_rolling_max_and_min_match_windowed_extrema() -> None:
    values = [3.0, 1.0, 4.0, 2.0, 5.0]

    assert rolling_max(values, window=3) == [None, None, 4.0, 4.0, 5.0]
    assert rolling_min(values, window=3) == [None, None, 1.0, 1.0, 2.0]


def test_macd_histogram_respects_warmup_and_produces_tail_values() -> None:
    values = [100.0 + float(index) for index in range(60)]

    histogram = macd_histogram(values)

    assert len(histogram) == len(values)
    assert histogram[0] is None
    assert histogram[10] is None
    assert histogram[-1] is not None


def test_negative_histogram_helper_requires_prior_negative_and_negative_current() -> None:
    histogram = [
        None,
        -0.4,
        -0.6,
        -0.2,
    ]
    assert (
        is_negative_histogram_above_prior_negative_min(histogram, lookback=3, index=3)
        is True
    )

    no_prior_negative = [None, 0.2, 0.1, -0.1]
    assert (
        is_negative_histogram_above_prior_negative_min(
            no_prior_negative,
            lookback=3,
            index=3,
        )
        is False
    )

    non_negative_current = [None, -0.4, -0.6, 0.1]
    assert (
        is_negative_histogram_above_prior_negative_min(
            non_negative_current,
            lookback=3,
            index=3,
        )
        is False
    )
