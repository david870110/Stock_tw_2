"""Data layer contracts for market and fundamental acquisition."""

from typing import Protocol, Sequence

from src.tw_quant.core.types import DateLike, Symbol
from src.tw_quant.schema.models import CorporateAction, FundamentalPoint, OHLCVBar


class MarketDataProvider(Protocol):
    def fetch_ohlcv(
        self, symbols: Sequence[Symbol], start: DateLike, end: DateLike
    ) -> list[OHLCVBar]:
        """Fetch canonical OHLCV bars for a symbol set and date range."""


class FundamentalDataProvider(Protocol):
    def fetch_fundamentals(
        self, symbols: Sequence[Symbol], start: DateLike, end: DateLike
    ) -> list[FundamentalPoint]:
        """Fetch canonical fundamental datapoints."""


class CorporateActionProvider(Protocol):
    def fetch_actions(
        self, symbols: Sequence[Symbol], start: DateLike, end: DateLike
    ) -> list[CorporateAction]:
        """Fetch canonical corporate action records."""
