"""Technical-analysis strategy helpers and adapters."""

from src.tw_quant.strategy.technical.features import (
    crossover_direction,
    exponential_moving_average,
    is_negative_histogram_above_prior_negative_min,
    macd_histogram,
    rolling_max,
    rolling_min,
    simple_moving_average,
)
from src.tw_quant.strategy.technical.ma_bullish_stack import MovingAverageBullishStackStrategy
from src.tw_quant.strategy.technical.ma_crossover import MovingAverageCrossoverStrategy
from src.tw_quant.strategy.technical.pullback_trend_compression import (
    PullbackTrend120dOptimizedStrategy,
    PullbackTrendCompressionStrategy,
)

__all__ = [
    "simple_moving_average",
    "crossover_direction",
    "exponential_moving_average",
    "rolling_max",
    "rolling_min",
    "macd_histogram",
    "is_negative_histogram_above_prior_negative_min",
    "MovingAverageBullishStackStrategy",
    "MovingAverageCrossoverStrategy",
    "PullbackTrendCompressionStrategy",
    "PullbackTrend120dOptimizedStrategy",
]
