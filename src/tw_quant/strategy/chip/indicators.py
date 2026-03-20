"""Reusable chip-flow indicator utilities."""

from __future__ import annotations


def chip_distribution(holdings: list[float], window: int) -> list[float | None]:
    """Calculate chip distribution over a rolling window.
    
    Measures how evenly distributed holdings are within each window.
    Returns normalized values between 0 and 1, where:
    - 0 = perfectly distributed (uniform)
    - 1 = maximally concentrated
    
    Args:
        holdings: List of holder position sizes.
        window: Rolling window size for distribution calculation.
        
    Returns:
        List of distribution scores with None for insufficient data.
    """
    if window < 1:
        raise ValueError("window must be >= 1")
    if not holdings:
        return []

    result: list[float | None] = [None] * len(holdings)

    for index in range(len(holdings)):
        if index < window - 1:
            continue
        
        window_holdings = holdings[index - window + 1 : index + 1]
        if not window_holdings:
            continue
            
        total = sum(window_holdings)
        if total == 0:
            result[index] = 0.0
            continue
            
        # Normalized standard deviation as distribution metric
        mean = total / len(window_holdings)
        if mean == 0:
            result[index] = 0.0
            continue
            
        variance = sum((h - mean) ** 2 for h in window_holdings) / len(window_holdings)
        std_dev = variance ** 0.5
        
        # Normalize to [0, 1] using coefficient of variation
        cv = std_dev / mean if mean != 0 else 0
        result[index] = min(1.0, cv / 2.0)  # Scale by 2 to fit in [0, 1]

    return result


def chip_concentration(holdings: list[float]) -> float:
    """Calculate overall chip concentration across all holders.
    
    Returns a Herfindahl-like concentration index between 0 and 1.
    - 0 = uniform distribution
    - 1 = single holder controls all
    
    Args:
        holdings: List of holder position sizes.
        
    Returns:
        Concentration score between 0 and 1.
    """
    if not holdings:
        return 0.0
    
    total = sum(holdings)
    if total == 0:
        return 0.0
    
    # Herfindahl index normalized to [0, 1]
    market_shares = [h / total for h in holdings]
    herfindahl = sum(share ** 2 for share in market_shares)
    
    # Normalize from [1/n, 1] to [0, 1]
    n = len(holdings)
    min_herfindahl = 1.0 / n if n > 0 else 0.0
    max_herfindahl = 1.0
    
    if min_herfindahl == max_herfindahl:
        return 0.0
    
    normalized = (herfindahl - min_herfindahl) / (max_herfindahl - min_herfindahl)
    return max(0.0, min(1.0, normalized))


def cost_basis_ratio(prices: list[float], holdings: list[float]) -> list[float]:
    """Calculate cost basis ratio for each position.
    
    Simulates the ratio of position cost to current value, useful for
    understanding average entry point relative to current price.
    
    Args:
        prices: List of current prices for respective holdings.
        holdings: List of position sizes.
        
    Returns:
        List of cost basis ratios (same length as inputs).
    """
    if len(prices) != len(holdings):
        raise ValueError("prices and holdings must have same length")
    
    if not prices or not holdings:
        return []
    
    # Simple approximation: assume cost basis is average entry point
    total_value = sum(p * h for p, h in zip(prices, holdings))
    if total_value == 0:
        return [1.0] * len(prices)
    
    avg_price = total_value / sum(holdings)
    return [avg_price / p if p != 0 else 1.0 for p in prices]
