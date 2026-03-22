"""Production-oriented universe providers for TW market workflows."""

from __future__ import annotations

import csv
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Iterable, Sequence

from src.tw_quant.core.types import DateLike
from src.tw_quant.universe.models import ListingStatus, UniverseEntry


_TW_SYMBOL_NUMERIC_PATTERN = re.compile(r"^\d{4,6}$")
_TW_SYMBOL_SUFFIX_PATTERN = re.compile(r"^(\d{4,6})\.(TW|TWO|TPE)$", re.IGNORECASE)


def normalize_tw_symbol(value: str) -> str | None:
    raw = value.strip().upper()
    if not raw:
        return None

    suffix_match = _TW_SYMBOL_SUFFIX_PATTERN.match(raw)
    if suffix_match is not None:
        suffix = suffix_match.group(2).upper()
        normalized_suffix = "TWO" if suffix in {"TWO", "TPE"} else "TW"
        return f"{suffix_match.group(1)}.{normalized_suffix}"

    if _TW_SYMBOL_NUMERIC_PATTERN.match(raw) is not None:
        return f"{raw}.TW"

    return None


def normalize_listing_status(value: str) -> ListingStatus:
    raw = value.strip().lower()
    if raw in {"listed", "normal", "active"}:
        return ListingStatus.LISTED
    if raw in {"suspended", "halted", "halt"}:
        return ListingStatus.SUSPENDED
    if raw in {"delisted", "terminated", "inactive"}:
        return ListingStatus.DELISTED
    return ListingStatus.LISTED


def parse_universe_csv_rows(
    rows: Iterable[dict[str, str]],
    *,
    updated_at: datetime,
) -> list[UniverseEntry]:
    entries: list[UniverseEntry] = []
    seen: set[str] = set()

    for row in rows:
        symbol_raw = row.get("symbol", "")
        exchange = row.get("exchange", "TWSE").strip().upper() or "TWSE"
        symbol = _normalize_symbol_for_exchange(symbol_raw, exchange=exchange)
        if symbol is None or symbol in seen:
            continue

        market = row.get("market", "stock").strip().lower() or "stock"
        status = normalize_listing_status(row.get("listing_status", "listed"))

        entries.append(
            UniverseEntry(
                symbol=symbol,
                name=_extract_security_name(row),
                exchange=exchange,
                market=market,
                listing_status=status,
                updated_at=updated_at,
            )
        )
        seen.add(symbol)

    return entries


def _normalize_symbol_for_exchange(value: str, *, exchange: str) -> str | None:
    raw = value.strip().upper()
    if not raw:
        return None

    suffix_match = _TW_SYMBOL_SUFFIX_PATTERN.match(raw)
    if suffix_match is not None:
        suffix = suffix_match.group(2).upper()
        normalized_suffix = "TWO" if suffix in {"TWO", "TPE"} else "TW"
        return f"{suffix_match.group(1)}.{normalized_suffix}"

    if _TW_SYMBOL_NUMERIC_PATTERN.match(raw) is None:
        return None

    normalized_exchange = exchange.strip().upper()
    suffix = "TWO" if normalized_exchange == "TPEX" else "TW"
    return f"{raw}.{suffix}"


def _extract_security_name(row: dict[str, str]) -> str:
    for key in (
        "name",
        "stock_name",
        "company_name",
        "security_name",
        "SecurityName",
        "CompanyName",
        "CompanyShortName",
        "SecuritiesCompanyName",
    ):
        value = str(row.get(key, "") or "").strip()
        if value:
            return value
    return ""


@dataclass(slots=True)
class CsvUniverseProvider:
    """Load universe snapshots from a CSV file.

    Expected columns: symbol, exchange, market, listing_status.
    """

    csv_path: str
    default_exchange: str = "TWSE"
    default_market: str = "stock"

    def get_universe(self, as_of: DateLike | None = None) -> list[UniverseEntry]:
        path = Path(self.csv_path)
        if not path.exists():
            return []

        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            snapshot_time = _to_datetime(as_of) if as_of is not None else datetime.utcnow()
            entries = parse_universe_csv_rows(reader, updated_at=snapshot_time)

        return [
            UniverseEntry(
                symbol=entry.symbol,
                name=entry.name,
                exchange=entry.exchange or self.default_exchange,
                market=entry.market or self.default_market,
                listing_status=entry.listing_status,
                updated_at=entry.updated_at,
            )
            for entry in entries
        ]

    def get_symbol(self, symbol: str, as_of: DateLike | None = None) -> UniverseEntry | None:
        normalized = normalize_tw_symbol(symbol)
        if normalized is None:
            return None
        entries = [item for item in self.get_universe(as_of=as_of) if item.symbol == normalized]
        if not entries:
            return None
        return max(entries, key=lambda item: item.updated_at)


class TaiwanMarketUniverseProvider:
    """Fetch and merge TWSE/TPEX symbol universes with basic resiliency controls."""

    def __init__(
        self,
        *,
        twse_fetcher: Callable[[float], Sequence[dict[str, str]]],
        tpex_fetcher: Callable[[float], Sequence[dict[str, str]]],
        timeout_seconds: float = 10.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.25,
        min_interval_seconds: float = 0.0,
    ) -> None:
        self._twse_fetcher = twse_fetcher
        self._tpex_fetcher = tpex_fetcher
        self._timeout_seconds = timeout_seconds
        self._max_retries = max(max_retries, 0)
        self._retry_backoff_seconds = max(retry_backoff_seconds, 0.0)
        self._min_interval_seconds = max(min_interval_seconds, 0.0)
        self._last_call_ts = 0.0

    def get_universe(self, as_of: DateLike | None = None) -> list[UniverseEntry]:
        snapshot_time = _to_datetime(as_of) if as_of is not None else datetime.utcnow()

        twse_rows = self._run_with_retry(self._twse_fetcher)
        tpex_rows = self._run_with_retry(self._tpex_fetcher)

        merged_rows = [*twse_rows, *tpex_rows]
        return parse_universe_csv_rows(merged_rows, updated_at=snapshot_time)

    def get_symbol(self, symbol: str, as_of: DateLike | None = None) -> UniverseEntry | None:
        normalized = normalize_tw_symbol(symbol)
        if normalized is None:
            return None
        matches = [entry for entry in self.get_universe(as_of=as_of) if entry.symbol == normalized]
        if not matches:
            return None
        return max(matches, key=lambda item: item.updated_at)

    def _run_with_retry(
        self,
        fetcher: Callable[[float], Sequence[dict[str, str]]],
    ) -> Sequence[dict[str, str]]:
        attempts = self._max_retries + 1
        last_error: Exception | None = None

        for attempt in range(attempts):
            self._enforce_rate_limit()
            try:
                return fetcher(self._timeout_seconds)
            except Exception as exc:  # pragma: no cover - validated in contracts
                last_error = exc
                if attempt + 1 >= attempts:
                    break
                time.sleep(self._retry_backoff_seconds * (attempt + 1))

        if last_error is None:
            return []
        raise last_error

    def _enforce_rate_limit(self) -> None:
        if self._min_interval_seconds <= 0.0:
            return
        now = time.monotonic()
        elapsed = now - self._last_call_ts
        if elapsed < self._min_interval_seconds:
            time.sleep(self._min_interval_seconds - elapsed)
        self._last_call_ts = time.monotonic()


def _to_datetime(value: DateLike) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    return datetime.fromisoformat(value)
