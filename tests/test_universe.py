"""Tests for the universe domain model and in-memory provider."""

from datetime import date, datetime

import pytest

from src.tw_quant.universe import (
    InMemoryUniverseProvider,
    ListingStatus,
    UniverseEntry,
    UniverseProvider,
)


@pytest.fixture
def sample_entries() -> list[UniverseEntry]:
    """Three entries: two for 2330.TW at different timestamps, one for 2317.TW."""
    return [
        UniverseEntry(
            symbol="2330.TW",
            exchange="TWSE",
            market="main",
            listing_status=ListingStatus.LISTED,
            updated_at=datetime(2024, 1, 1),
        ),
        UniverseEntry(
            symbol="2330.TW",
            exchange="TWSE",
            market="main",
            listing_status=ListingStatus.SUSPENDED,
            updated_at=datetime(2024, 6, 1),
        ),
        UniverseEntry(
            symbol="2317.TW",
            exchange="TWSE",
            market="main",
            listing_status=ListingStatus.LISTED,
            updated_at=datetime(2024, 3, 1),
        ),
    ]


# --- AC1: Model fields ---


def test_universe_entry_fields() -> None:
    e = UniverseEntry(
        symbol="2330.TW",
        exchange="TWSE",
        market="main",
        listing_status=ListingStatus.LISTED,
        updated_at=datetime(2024, 1, 1),
    )
    assert e.symbol == "2330.TW"
    assert e.exchange == "TWSE"
    assert e.market == "main"
    assert e.listing_status == ListingStatus.LISTED
    assert e.updated_at == datetime(2024, 1, 1)


def test_universe_entry_is_frozen() -> None:
    e = UniverseEntry(
        symbol="2330.TW",
        exchange="TWSE",
        market="main",
        listing_status=ListingStatus.LISTED,
        updated_at=datetime(2024, 1, 1),
    )
    with pytest.raises(Exception):
        e.symbol = "XXXX"  # type: ignore[misc]


def test_listing_status_values() -> None:
    assert ListingStatus.LISTED == "listed"
    assert ListingStatus.DELISTED == "delisted"
    assert ListingStatus.SUSPENDED == "suspended"
    assert set(ListingStatus) == {
        ListingStatus.LISTED,
        ListingStatus.DELISTED,
        ListingStatus.SUSPENDED,
    }


# --- AC2: Provider interface ---


def test_inmemory_implements_universe_provider(
    sample_entries: list[UniverseEntry],
) -> None:
    provider = InMemoryUniverseProvider(sample_entries)
    assert hasattr(provider, "get_universe")
    assert hasattr(provider, "get_symbol")


def test_get_universe_no_asof_returns_all(
    sample_entries: list[UniverseEntry],
) -> None:
    provider = InMemoryUniverseProvider(sample_entries)
    result = provider.get_universe()
    assert len(result) == 3


def test_get_universe_with_asof_filters(
    sample_entries: list[UniverseEntry],
) -> None:
    provider = InMemoryUniverseProvider(sample_entries)
    result = provider.get_universe(as_of=date(2024, 2, 1))
    assert len(result) == 1
    assert result[0].symbol == "2330.TW"
    assert result[0].updated_at == datetime(2024, 1, 1)


def test_get_universe_with_asof_string(
    sample_entries: list[UniverseEntry],
) -> None:
    provider = InMemoryUniverseProvider(sample_entries)
    result = provider.get_universe(as_of="2024-04-01")
    assert len(result) == 2


# --- AC3: Mock/in-memory provider ---


def test_get_symbol_no_asof_returns_most_recent(
    sample_entries: list[UniverseEntry],
) -> None:
    provider = InMemoryUniverseProvider(sample_entries)
    entry = provider.get_symbol("2330.TW")
    assert entry is not None
    assert entry.updated_at == datetime(2024, 6, 1)
    assert entry.listing_status == ListingStatus.SUSPENDED


def test_get_symbol_with_asof_returns_most_recent_before(
    sample_entries: list[UniverseEntry],
) -> None:
    provider = InMemoryUniverseProvider(sample_entries)
    entry = provider.get_symbol("2330.TW", as_of=date(2024, 3, 1))
    assert entry is not None
    assert entry.updated_at == datetime(2024, 1, 1)
    assert entry.listing_status == ListingStatus.LISTED


def test_get_symbol_returns_none_for_unknown(
    sample_entries: list[UniverseEntry],
) -> None:
    provider = InMemoryUniverseProvider(sample_entries)
    assert provider.get_symbol("9999.TW") is None


def test_get_symbol_returns_none_when_asof_before_all(
    sample_entries: list[UniverseEntry],
) -> None:
    provider = InMemoryUniverseProvider(sample_entries)
    assert provider.get_symbol("2330.TW", as_of=date(2023, 12, 31)) is None


def test_constructor_makes_defensive_copy(
    sample_entries: list[UniverseEntry],
) -> None:
    original = list(sample_entries)
    provider = InMemoryUniverseProvider(original)
    original.clear()
    assert len(provider.get_universe()) == 3


# --- Package exports ---


def test_package_exports_all_public_names() -> None:
    import src.tw_quant.universe as pkg

    for name in ("ListingStatus", "UniverseEntry", "UniverseProvider", "InMemoryUniverseProvider"):
        assert hasattr(pkg, name), f"{name} not exported from src.tw_quant.universe"
