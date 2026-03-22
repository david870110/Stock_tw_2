"""Universe domain models for Taiwan stock coverage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from src.tw_quant.core.types import Symbol


class ListingStatus(StrEnum):
    LISTED = "listed"
    DELISTED = "delisted"
    SUSPENDED = "suspended"


@dataclass(slots=True, frozen=True)
class UniverseEntry:
    symbol: Symbol
    exchange: str
    market: str
    listing_status: ListingStatus
    updated_at: datetime
    name: str = ""
