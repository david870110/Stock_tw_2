"""Reusable market-structure level utilities."""

from __future__ import annotations


def support_resistance(
    prices: list[float], window: int
) -> tuple[list[float], list[float]]:
    """Identify support and resistance levels.
    
    Support: local minimum within window
    Resistance: local maximum within window
    
    Args:
        prices: List of closing prices.
        window: Window size for local extrema identification.
        
    Returns:
        Tuple of (supports, resistances) lists.
    """
    if window < 1:
        raise ValueError("window must be >= 1")
    if not prices:
        return [], []
    
    supports: list[float] = []
    resistances: list[float] = []
    
    for index in range(len(prices)):
        if index < window - 1:
            # Not enough data yet - use current price as both support and resistance
            supports.append(prices[index])
            resistances.append(prices[index])
        else:
            # Use window ending at current index
            window_prices = prices[index - window + 1 : index + 1]
            support = min(window_prices)
            resistance = max(window_prices)
            
            supports.append(support)
            resistances.append(resistance)
    
    return supports, resistances


def structure_trend(structure_levels: list[float]) -> str:
    """Determine market trend from structure levels.
    
    Analyzes the direction of support/resistance levels to infer trend:
    - Uptrend: levels rising
    - Downtrend: levels falling
    - Sideways: levels stable
    
    Args:
        structure_levels: List of support or resistance levels.
        
    Returns:
        One of: 'uptrend', 'downtrend', 'sideways'
    """
    if len(structure_levels) < 2:
        return "sideways"
    
    # Compare recent levels to older levels
    first_half_avg = sum(structure_levels[: len(structure_levels) // 2]) / (
        len(structure_levels) // 2 or 1
    )
    second_half_avg = sum(structure_levels[len(structure_levels) // 2 :]) / (
        len(structure_levels) - len(structure_levels) // 2 or 1
    )
    
    diff_pct = (second_half_avg - first_half_avg) / first_half_avg if first_half_avg != 0 else 0
    
    if diff_pct > 0.02:
        return "uptrend"
    elif diff_pct < -0.02:
        return "downtrend"
    else:
        return "sideways"


def mean_reversion_signal(
    price: float, support: float, resistance: float
) -> float:
    """Generate mean-reversion signal based on distance to support/resistance.
    
    Returns a value between -1 and 1:
    - -1: price at resistance (sell)
    - 0: price at midpoint
    - 1: price at support (buy)
    
    Args:
        price: Current price.
        support: Support level.
        resistance: Resistance level.
        
    Returns:
        Signal value between -1 and 1.
    """
    if support == resistance:
        return 0.0
    
    # Normalize price within [support, resistance]
    norm_price = (price - support) / (resistance - support)
    norm_price = max(0.0, min(1.0, norm_price))
    
    # Convert to [-1, 1] where -1 = resistance (sell), 1 = support (buy)
    signal = 1.0 - 2.0 * norm_price
    return signal
