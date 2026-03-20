"""In-memory universe provider for unit tests."""

from __future__ import annotations

from datetime import date, datetime

from src.tw_quant.core.types import DateLike, Symbol
from src.tw_quant.universe.models import UniverseEntry


def _to_datetime(as_of: DateLike) -> datetime:
    """Normalise DateLike to datetime for comparison with updated_at."""
    if isinstance(as_of, datetime):
        return as_of
    if isinstance(as_of, date):
        return datetime(as_of.year, as_of.month, as_of.day)
    parsed = datetime.fromisoformat(as_of)
    if not isinstance(parsed, datetime):
        parsed = datetime(parsed.year, parsed.month, parsed.day)
    return parsed


class InMemoryUniverseProvider:
    """Thread-unsafe in-memory universe provider for unit testing."""

    def __init__(self, entries: list[UniverseEntry]) -> None:
        self._entries: list[UniverseEntry] = list(entries)

    def get_universe(self, as_of: DateLike | None = None) -> list[UniverseEntry]:
        if as_of is None:
            return list(self._entries)
        cutoff = _to_datetime(as_of)
        return [e for e in self._entries if e.updated_at <= cutoff]

    def get_symbol(
        self,
        symbol: Symbol,
        as_of: DateLike | None = None,
    ) -> UniverseEntry | None:
        if as_of is None:
            candidates = [e for e in self._entries if e.symbol == symbol]
        else:
            cutoff = _to_datetime(as_of)
            candidates = [
                e for e in self._entries if e.symbol == symbol and e.updated_at <= cutoff
            ]
        if not candidates:
            return None
        return max(candidates, key=lambda e: e.updated_at)
