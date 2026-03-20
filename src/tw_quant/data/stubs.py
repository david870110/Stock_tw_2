"""In-memory data provider stubs for unit tests."""
from __future__ import annotations

from datetime import date, datetime
from typing import Sequence

from src.tw_quant.core.types import DateLike, Symbol
from src.tw_quant.schema.models import CorporateAction, FundamentalPoint, OHLCVBar


def _to_date(v: DateLike) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return datetime.fromisoformat(v).date()


class InMemoryMarketDataProvider:
    """Thread-unsafe in-memory market data provider for unit testing."""

    def __init__(self, entries: list[OHLCVBar]) -> None:
        self._entries: list[OHLCVBar] = list(entries)

    def fetch_ohlcv(
        self, symbols: Sequence[Symbol], start: DateLike, end: DateLike
    ) -> list[OHLCVBar]:
        symbol_set = set(symbols)
        start_date = _to_date(start)
        end_date = _to_date(end)
        return [
            bar
            for bar in self._entries
            if bar.symbol in symbol_set and start_date <= _to_date(bar.date) <= end_date
        ]


class InMemoryFundamentalDataProvider:
    """Thread-unsafe in-memory fundamental data provider for unit testing."""

    def __init__(self, entries: list[FundamentalPoint]) -> None:
        self._entries: list[FundamentalPoint] = list(entries)

    def fetch_fundamentals(
        self, symbols: Sequence[Symbol], start: DateLike, end: DateLike
    ) -> list[FundamentalPoint]:
        symbol_set = set(symbols)
        start_date = _to_date(start)
        end_date = _to_date(end)
        return [
            point
            for point in self._entries
            if point.symbol in symbol_set
            and start_date <= _to_date(point.date) <= end_date
        ]


class InMemoryCorporateActionProvider:
    """Thread-unsafe in-memory corporate action provider for unit testing."""

    def __init__(self, entries: list[CorporateAction]) -> None:
        self._entries: list[CorporateAction] = list(entries)

    def fetch_actions(
        self, symbols: Sequence[Symbol], start: DateLike, end: DateLike
    ) -> list[CorporateAction]:
        symbol_set = set(symbols)
        start_date = _to_date(start)
        end_date = _to_date(end)
        return [
            action
            for action in self._entries
            if action.symbol in symbol_set
            and start_date <= _to_date(action.ex_date) <= end_date
        ]
