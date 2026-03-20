"""Universe provider contract."""

from __future__ import annotations

from typing import Protocol

from src.tw_quant.core.types import DateLike, Symbol
from src.tw_quant.universe.models import UniverseEntry


class UniverseProvider(Protocol):
    def get_universe(self, as_of: DateLike | None = None) -> list[UniverseEntry]:
        """Return all universe entries.

        If as_of is None, return all known entries without date filtering.
        If as_of is provided, return only entries whose updated_at <= as_of.
        """

    def get_symbol(
        self,
        symbol: Symbol,
        as_of: DateLike | None = None,
    ) -> UniverseEntry | None:
        """Return the most recent UniverseEntry for symbol whose updated_at <= as_of.

        If as_of is None, return the entry with the greatest updated_at across all
        entries for that symbol.
        Returns None when no matching entry exists.
        """
