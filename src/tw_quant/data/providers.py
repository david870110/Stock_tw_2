"""Production-oriented market data providers for OHLCV retrieval."""

from __future__ import annotations

import time
from datetime import date, datetime
from typing import Callable, Iterable, Sequence

from src.tw_quant.core.types import DateLike, Symbol
from src.tw_quant.schema.models import OHLCVBar


OHLCVFetcher = Callable[[Symbol, DateLike, DateLike, float], Sequence[dict[str, object]]]


class ResilientMarketDataProvider:
    """Fetch OHLCV by symbol with retry/rate-limit/batch controls.

    Errors are isolated per symbol to avoid failing a full batch run.
    """

    def __init__(
        self,
        *,
        fetcher: OHLCVFetcher,
        timeout_seconds: float = 10.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.25,
        min_interval_seconds: float = 0.0,
        batch_size: int = 50,
    ) -> None:
        self._fetcher = fetcher
        self._timeout_seconds = timeout_seconds
        self._max_retries = max(max_retries, 0)
        self._retry_backoff_seconds = max(retry_backoff_seconds, 0.0)
        self._min_interval_seconds = max(min_interval_seconds, 0.0)
        self._batch_size = max(batch_size, 1)
        self._last_request_ts = 0.0

    def fetch_ohlcv(
        self,
        symbols: Sequence[Symbol],
        start: DateLike,
        end: DateLike,
    ) -> list[OHLCVBar]:
        collected: list[OHLCVBar] = []
        seen: set[tuple[Symbol, str]] = set()

        for batch in _chunked(list(symbols), self._batch_size):
            for symbol in batch:
                rows = self._fetch_symbol_with_retry(symbol, start, end)
                for row in rows:
                    parsed = _parse_ohlcv_row(symbol, row)
                    if parsed is None:
                        continue
                    if not (_to_date(start) <= _to_date(parsed.date) <= _to_date(end)):
                        continue
                    dedupe_key = (parsed.symbol, _to_date(parsed.date).isoformat())
                    if dedupe_key in seen:
                        continue
                    seen.add(dedupe_key)
                    collected.append(parsed)

        collected.sort(key=lambda item: (item.symbol, _to_date(item.date)))
        return collected

    def _fetch_symbol_with_retry(
        self,
        symbol: Symbol,
        start: DateLike,
        end: DateLike,
    ) -> Sequence[dict[str, object]]:
        attempts = self._max_retries + 1

        for attempt in range(attempts):
            self._enforce_rate_limit()
            try:
                return self._fetcher(symbol, start, end, self._timeout_seconds)
            except Exception:  # pragma: no cover - covered by contracts indirectly
                if attempt + 1 >= attempts:
                    return []
                time.sleep(self._retry_backoff_seconds * (attempt + 1))

        return []

    def _enforce_rate_limit(self) -> None:
        if self._min_interval_seconds <= 0.0:
            return
        now = time.monotonic()
        elapsed = now - self._last_request_ts
        if elapsed < self._min_interval_seconds:
            time.sleep(self._min_interval_seconds - elapsed)
        self._last_request_ts = time.monotonic()


def _parse_ohlcv_row(symbol: Symbol, row: dict[str, object]) -> OHLCVBar | None:
    date_value = row.get("date")
    if date_value is None:
        return None

    try:
        return OHLCVBar(
            symbol=symbol,
            date=_coerce_date_like(date_value),
            open=float(row.get("open", 0.0)),
            high=float(row.get("high", 0.0)),
            low=float(row.get("low", 0.0)),
            close=float(row.get("close", 0.0)),
            volume=float(row.get("volume", 0.0)),
            turnover=(float(row["turnover"]) if row.get("turnover") is not None else None),
        )
    except (TypeError, ValueError):
        return None


def _coerce_date_like(value: object) -> DateLike:
    if isinstance(value, (date, datetime)):
        return value
    if isinstance(value, str):
        return value
    raise ValueError(f"Unsupported date value: {value!r}")


def _to_date(value: DateLike) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if "T" in value:
        return datetime.fromisoformat(value).date()
    return date.fromisoformat(value)


def _chunked(values: list[Symbol], size: int) -> Iterable[list[Symbol]]:
    for index in range(0, len(values), size):
        yield values[index:index + size]
