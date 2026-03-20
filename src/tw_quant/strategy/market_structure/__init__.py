"""Market-structure strategy helpers and adapters.

Market structure analysis identifies key support and resistance levels
that can be used to generate mean-reversion signals and trend-following
signals based on structural patterns.
"""

from src.tw_quant.strategy.market_structure.levels import (
    mean_reversion_signal,
    structure_trend,
    support_resistance,
)
from src.tw_quant.strategy.market_structure.structure_strategy import (
    MarketStructureStrategy,
)

__all__ = [
    "support_resistance",
    "structure_trend",
    "mean_reversion_signal",
    "MarketStructureStrategy",
]
