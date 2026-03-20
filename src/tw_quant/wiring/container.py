"""App wiring container with placeholder dependencies."""

from dataclasses import dataclass
import csv
from http.client import IncompleteRead
import io
import json
from urllib.request import urlopen

from src.tw_quant.batch.interfaces import BatchRunner
from src.tw_quant.config.models import AppConfig
from src.tw_quant.data import InMemoryMarketDataProvider, ResilientMarketDataProvider
from src.tw_quant.data.interfaces import (
    CorporateActionProvider,
    FundamentalDataProvider,
    MarketDataProvider,
)
from src.tw_quant.reporting.interfaces import MetricsCalculator, ReportBuilder
from src.tw_quant.storage.interfaces import ArtifactStore, CanonicalDataStore, RawDataStore
from src.tw_quant.universe.interfaces import UniverseProvider
from src.tw_quant.adapters.yfinance_ohlcv import yfinance_fetcher
from src.tw_quant.adapters.twse_universe import map_twse_row, map_tpex_row
from src.tw_quant.universe.providers import CsvUniverseProvider, TaiwanMarketUniverseProvider
from src.tw_quant.universe.stub import InMemoryUniverseProvider


_TPEX_FALLBACK_UNIVERSE_URLS = (
    "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes",
    "https://www.tpex.org.tw/openapi/v1/tpex_esb_capitals_rank",
)


@dataclass(slots=True)
class AppContext:
    config: AppConfig
    universe_provider: UniverseProvider | None = None
    market_data_provider: MarketDataProvider | None = None
    fundamental_data_provider: FundamentalDataProvider | None = None
    corporate_action_provider: CorporateActionProvider | None = None
    raw_data_store: RawDataStore | None = None
    canonical_data_store: CanonicalDataStore | None = None
    artifact_store: ArtifactStore | None = None
    metrics_calculator: MetricsCalculator | None = None
    report_builder: ReportBuilder | None = None
    batch_runner: BatchRunner | None = None


def build_app_context(config: AppConfig) -> AppContext:
    """Build a typed dependency context with placeholder or runtime implementations."""
    if config.data.wiring_mode != "active":
        return AppContext(config=config)

    return AppContext(
        config=config,
        universe_provider=_build_universe_provider(config),
        market_data_provider=_build_market_data_provider(config),
    )


def _build_universe_provider(config: AppConfig) -> UniverseProvider:
    kind = config.data.universe_provider.strip().lower()
    if kind in {"stub_universe", "memory", "in_memory"}:
        return InMemoryUniverseProvider([])

    if kind == "csv_universe":
        return CsvUniverseProvider(csv_path=config.data.universe_csv_path)

    if kind == "remote_universe":
        twse_url = config.data.universe_twse_url
        tpex_url = config.data.universe_tpex_url
        if not twse_url or not tpex_url:
            raise ValueError("remote_universe requires universe_twse_url and universe_tpex_url")
        return TaiwanMarketUniverseProvider(
            twse_fetcher=lambda timeout: [
                map_twse_row(r) for r in _fetch_universe_rows(twse_url, timeout)
            ],
            tpex_fetcher=lambda timeout: _fetch_tpex_rows_with_fallback(
                primary_url=tpex_url,
                timeout=timeout,
            ),
            timeout_seconds=config.data.timeout_seconds,
            max_retries=config.data.max_retries,
            retry_backoff_seconds=config.data.retry_backoff_seconds,
            min_interval_seconds=config.data.min_interval_seconds,
        )

    raise ValueError(f"Unsupported universe provider: {config.data.universe_provider!r}")


def _build_market_data_provider(config: AppConfig) -> MarketDataProvider:
    kind = config.data.market_provider.strip().lower()
    if kind in {"stub_market", "memory", "in_memory"}:
        return InMemoryMarketDataProvider([])

    if kind == "yfinance_ohlcv":
        return ResilientMarketDataProvider(
            fetcher=yfinance_fetcher,
            timeout_seconds=config.data.timeout_seconds,
            max_retries=config.data.max_retries,
            retry_backoff_seconds=config.data.retry_backoff_seconds,
            min_interval_seconds=config.data.min_interval_seconds,
            batch_size=config.data.batch_size,
        )

    if kind == "remote_ohlcv":
        template = config.data.market_ohlcv_url_template
        if not template:
            raise ValueError("remote_ohlcv requires market_ohlcv_url_template")

        def fetcher(symbol: str, start, end, timeout: float):
            url = template.format(symbol=symbol, start=start, end=end)
            return _fetch_ohlcv_rows(url, timeout)

        return ResilientMarketDataProvider(
            fetcher=fetcher,
            timeout_seconds=config.data.timeout_seconds,
            max_retries=config.data.max_retries,
            retry_backoff_seconds=config.data.retry_backoff_seconds,
            min_interval_seconds=config.data.min_interval_seconds,
            batch_size=config.data.batch_size,
        )

    raise ValueError(f"Unsupported market provider: {config.data.market_provider!r}")


def _fetch_universe_rows(url: str, timeout: float) -> list[dict[str, str]]:
    with urlopen(url, timeout=timeout) as response:
        raw = _read_response_text(response)

    stripped = raw.lstrip()
    if stripped.startswith("["):
        payload_rows = _parse_json_rows(raw)
        if payload_rows:
            return payload_rows
        raise ValueError("Universe payload appears to be JSON but no valid rows were parsed")

    reader = csv.DictReader(io.StringIO(raw))
    return [{k: "" if value is None else value for k, value in row.items()} for row in reader]


def _fetch_ohlcv_rows(url: str, timeout: float) -> list[dict[str, object]]:
    with urlopen(url, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if isinstance(payload, dict):
        data = payload.get("data", [])
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _read_response_text(response) -> str:
    chunks: list[bytes] = []
    while True:
        try:
            chunk = response.read(64 * 1024)
        except IncompleteRead as exc:
            if exc.partial:
                chunks.append(exc.partial)
            break
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks).decode("utf-8-sig", errors="ignore")


def _parse_json_rows(raw: str) -> list[dict[str, str]]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = _parse_partial_json_array(raw)

    if not isinstance(payload, list):
        return []
    return [
        {k: "" if value is None else str(value) for k, value in dict(item).items()}
        for item in payload
        if isinstance(item, dict)
    ]


def _parse_partial_json_array(raw: str) -> list[object]:
    stripped = raw.lstrip()
    if not stripped.startswith("["):
        return []

    decoder = json.JSONDecoder()
    values: list[object] = []
    idx = stripped.find("[") + 1
    length = len(stripped)

    while idx < length:
        while idx < length and stripped[idx] in " \t\r\n,":
            idx += 1
        if idx >= length or stripped[idx] == "]":
            break
        try:
            value, next_idx = decoder.raw_decode(stripped, idx)
        except json.JSONDecodeError:
            break
        values.append(value)
        idx = next_idx

    return values


def _fetch_tpex_rows_with_fallback(*, primary_url: str, timeout: float) -> list[dict[str, str]]:
    candidate_urls: list[str] = []
    for url in [primary_url, *_TPEX_FALLBACK_UNIVERSE_URLS]:
        if url and url not in candidate_urls:
            candidate_urls.append(url)

    merged_rows: list[dict[str, str]] = []
    seen_symbols: set[str] = set()
    last_error: Exception | None = None

    for url in candidate_urls:
        try:
            raw_rows = _fetch_universe_rows(url, timeout)
        except Exception as exc:  # pragma: no cover - network variability
            last_error = exc
            continue

        for row in raw_rows:
            mapped = map_tpex_row(row)
            symbol = str(mapped.get("symbol", "")).strip().upper()
            if not symbol or symbol in seen_symbols:
                continue
            seen_symbols.add(symbol)
            merged_rows.append(mapped)

    if merged_rows:
        return merged_rows
    if last_error is not None:
        raise last_error
    return []
