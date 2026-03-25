"""yfinance OHLCV fetcher adapter for ResilientMarketDataProvider."""

from __future__ import annotations

import logging
from typing import Any


class YFinanceRateLimitError(RuntimeError):
    """Raised when Yahoo Finance explicitly rate-limits a request."""


def yfinance_fetcher(
    symbol: str,
    start: Any,
    end: Any,
    timeout: float,  # noqa: ARG001 — yfinance does not support per-request timeouts
) -> list[dict[str, object]]:
    """Download daily OHLCV for one symbol via yfinance and return plain dicts.

    Each dict has keys: date (date), open, high, low, close, volume (float).
    Returns [] if the ticker returns no data for the requested range.
    """
    import yfinance as yf  # lazy import — keeps the adapter testable without yfinance installed

    logging.getLogger("yfinance").setLevel(logging.CRITICAL)

    df = None
    for candidate in _build_symbol_candidates(symbol):
        try:
            ticker = yf.Ticker(candidate)
            candidate_df = ticker.history(
                start=str(start),
                end=str(end),
                interval="1d",
                auto_adjust=True,
                actions=False,
            )
        except Exception as exc:
            if _is_yfinance_rate_limit_error(exc):
                raise YFinanceRateLimitError(str(exc)) from exc
            continue

        if candidate_df is not None and not candidate_df.empty:
            df = candidate_df
            break

    if df is None or df.empty:
        return []

    rows: list[dict[str, object]] = []
    for dt, row in df.iterrows():
        rows.append({
            "date": dt.date() if hasattr(dt, "date") else str(dt)[:10],
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": float(row["Volume"]),
        })
    return rows


def _build_symbol_candidates(symbol: str) -> list[str]:
    raw = symbol.strip().upper()
    if raw.endswith(".TW"):
        return [raw, f"{raw[:-3]}.TWO"]
    if raw.endswith(".TWO"):
        return [raw, f"{raw[:-4]}.TW"]
    return [raw]


def _is_yfinance_rate_limit_error(exc: Exception) -> bool:
    name = exc.__class__.__name__.lower()
    message = str(exc).lower()
    return "yfratelimiterror" in name or "rate limited" in message or "too many requests" in message
