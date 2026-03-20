"""Reusable flow-analysis metric utilities."""

from __future__ import annotations


def inflow_outflow(
    volumes: list[float], prices: list[float]
) -> tuple[list[float], list[float]]:
    """Separate buy and sell flow based on volume and price changes.
    
    Approximates inflow (demand) and outflow (supply) by analyzing
    price changes and corresponding volumes.
    
    Args:
        volumes: List of trading volumes.
        prices: List of closing prices.
        
    Returns:
        Tuple of (inflows, outflows) lists.
    """
    if len(volumes) != len(prices):
        raise ValueError("volumes and prices must have same length")
    
    if not volumes or not prices:
        return [], []
    
    inflows: list[float] = []
    outflows: list[float] = []
    
    for index in range(len(volumes)):
        if index == 0:
            inflows.append(0.0)
            outflows.append(0.0)
            continue
        
        price_change = prices[index] - prices[index - 1]
        volume = volumes[index]
        
        if price_change > 0:
            inflows.append(volume)
            outflows.append(0.0)
        elif price_change < 0:
            inflows.append(0.0)
            outflows.append(volume)
        else:
            inflows.append(0.0)
            outflows.append(0.0)
    
    return inflows, outflows


def flow_momentum(inflows: list[float], window: int) -> list[float | None]:
    """Calculate flow momentum as rate of change in flows.
    
    Momentum = average rate of change of flows over window.
    Positive momentum = increasing flows, Negative = decreasing flows.
    
    Args:
        inflows: List of flow values.
        window: Rolling window size for momentum calculation.
        
    Returns:
        List of momentum values (None for insufficient data).
    """
    if window < 1:
        raise ValueError("window must be >= 1")
    if not inflows:
        return []
    
    result: list[float | None] = [None] * len(inflows)
    
    # Calculate changes
    changes: list[float | None] = [None] + [
        inflows[i] - inflows[i - 1] for i in range(1, len(inflows))
    ]
    
    # Momentum is the average change over the window
    for index in range(len(inflows)):
        if index < window - 1 or changes[index] is None:
            continue
        
        window_changes = [
            c for c in changes[max(0, index - window + 2) : index + 1] if c is not None
        ]
        if window_changes:
            momentum = sum(window_changes) / len(window_changes)
            result[index] = momentum
    
    return result


def flow_ratio(volumes: list[float], window: int) -> list[float | None]:
    """Calculate flow ratio showing buy/sell pressure balance.
    
    Returns None when insufficient data or division by zero occurs.
    
    Args:
        volumes: List of volumes (used here as proxy for flow).
        window: Rolling window size.
        
    Returns:
        List of flow ratio values.
    """
    if window < 1:
        raise ValueError("window must be >= 1")
    if not volumes:
        return []
    
    result: list[float | None] = [None] * len(volumes)
    
    for index in range(len(volumes)):
        if index < window - 1:
            continue
        
        window_volumes = volumes[index - window + 1 : index + 1]
        total_volume = sum(window_volumes)
        
        if total_volume == 0:
            result[index] = None
            continue
        
        # Simple ratio: recent volume / average volume
        avg_volume = total_volume / window
        current_volume = volumes[index]
        ratio = current_volume / avg_volume if avg_volume > 0 else None
        result[index] = ratio
    
    return result
