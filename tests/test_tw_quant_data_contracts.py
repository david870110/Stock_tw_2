"""Contract tests for in-memory TW quant data providers."""

from datetime import date, datetime

import pytest

from src.tw_quant.data import (
    InMemoryCorporateActionProvider,
    InMemoryFundamentalDataProvider,
    InMemoryMarketDataProvider,
)
from src.tw_quant.data.stubs import _to_date
from src.tw_quant.schema.models import CorporateAction, FundamentalPoint, OHLCVBar


@pytest.fixture
def market_entries() -> list[OHLCVBar]:
    return [
        OHLCVBar("2330.TW", date(2024, 1, 1), 100.0, 110.0, 95.0, 108.0, 1000.0, 108000.0),
        OHLCVBar("2317.TW", date(2024, 1, 2), 90.0, 92.0, 88.0, 91.0, 1500.0, 136500.0),
        OHLCVBar("2330.TW", date(2024, 1, 3), 109.0, 112.0, 107.0, 111.0, 900.0, 99900.0),
    ]


@pytest.fixture
def fundamental_entries() -> list[FundamentalPoint]:
    return [
        FundamentalPoint("2330.TW", date(2024, 1, 1), "pe", 20.1, "seed"),
        FundamentalPoint("2317.TW", date(2024, 1, 2), "pe", 12.5, "seed"),
        FundamentalPoint("2330.TW", date(2024, 1, 3), "pb", 5.4, "seed"),
    ]


@pytest.fixture
def action_entries() -> list[CorporateAction]:
    return [
        CorporateAction("2330.TW", date(2024, 1, 1), "cash_dividend", 3.0),
        CorporateAction("2317.TW", date(2024, 1, 2), "stock_dividend", 1.0),
        CorporateAction("2330.TW", date(2024, 1, 3), "cash_dividend", 3.2),
    ]


def test_inmemory_market_data_provider_has_fetch_ohlcv() -> None:
    provider = InMemoryMarketDataProvider([])
    assert hasattr(provider, "fetch_ohlcv")


def test_fetch_ohlcv_empty_seed_returns_empty() -> None:
    provider = InMemoryMarketDataProvider([])
    result = provider.fetch_ohlcv(["2330.TW"], date(2024, 1, 1), date(2024, 1, 3))
    assert result == []


def test_fetch_ohlcv_full_match_returns_all_records(
    market_entries: list[OHLCVBar],
) -> None:
    provider = InMemoryMarketDataProvider(market_entries)
    result = provider.fetch_ohlcv(["2330.TW", "2317.TW"], date(2024, 1, 1), date(2024, 1, 3))
    assert result == market_entries


def test_fetch_ohlcv_filters_symbol_subset(market_entries: list[OHLCVBar]) -> None:
    provider = InMemoryMarketDataProvider(market_entries)
    result = provider.fetch_ohlcv(["2330.TW"], date(2024, 1, 1), date(2024, 1, 3))
    assert len(result) == 2
    assert all(item.symbol == "2330.TW" for item in result)


def test_fetch_ohlcv_inclusive_start_and_end_boundaries(
    market_entries: list[OHLCVBar],
) -> None:
    provider = InMemoryMarketDataProvider(market_entries)
    result = provider.fetch_ohlcv(["2330.TW"], date(2024, 1, 1), date(2024, 1, 3))
    assert [item.date for item in result] == [date(2024, 1, 1), date(2024, 1, 3)]


def test_fetch_ohlcv_multi_symbol_query_returns_combined_results(
    market_entries: list[OHLCVBar],
) -> None:
    provider = InMemoryMarketDataProvider(market_entries)
    result = provider.fetch_ohlcv(["2330.TW", "2317.TW"], date(2024, 1, 2), date(2024, 1, 3))
    assert len(result) == 2
    assert {item.symbol for item in result} == {"2330.TW", "2317.TW"}


def test_fetch_ohlcv_constructor_makes_defensive_copy(
    market_entries: list[OHLCVBar],
) -> None:
    seed = list(market_entries)
    provider = InMemoryMarketDataProvider(seed)
    seed.clear()
    result = provider.fetch_ohlcv(["2330.TW", "2317.TW"], date(2024, 1, 1), date(2024, 1, 3))
    assert len(result) == 3


def test_inmemory_fundamental_data_provider_has_fetch_fundamentals() -> None:
    provider = InMemoryFundamentalDataProvider([])
    assert hasattr(provider, "fetch_fundamentals")


def test_fetch_fundamentals_empty_seed_returns_empty() -> None:
    provider = InMemoryFundamentalDataProvider([])
    result = provider.fetch_fundamentals(["2330.TW"], date(2024, 1, 1), date(2024, 1, 3))
    assert result == []


def test_fetch_fundamentals_full_match_returns_all_records(
    fundamental_entries: list[FundamentalPoint],
) -> None:
    provider = InMemoryFundamentalDataProvider(fundamental_entries)
    result = provider.fetch_fundamentals(
        ["2330.TW", "2317.TW"], date(2024, 1, 1), date(2024, 1, 3)
    )
    assert result == fundamental_entries


def test_fetch_fundamentals_filters_symbol_subset(
    fundamental_entries: list[FundamentalPoint],
) -> None:
    provider = InMemoryFundamentalDataProvider(fundamental_entries)
    result = provider.fetch_fundamentals(["2317.TW"], date(2024, 1, 1), date(2024, 1, 3))
    assert len(result) == 1
    assert result[0].symbol == "2317.TW"


def test_fetch_fundamentals_inclusive_start_and_end_boundaries(
    fundamental_entries: list[FundamentalPoint],
) -> None:
    provider = InMemoryFundamentalDataProvider(fundamental_entries)
    result = provider.fetch_fundamentals(["2330.TW"], date(2024, 1, 1), date(2024, 1, 3))
    assert [item.date for item in result] == [date(2024, 1, 1), date(2024, 1, 3)]


def test_fetch_fundamentals_multi_symbol_query_returns_combined_results(
    fundamental_entries: list[FundamentalPoint],
) -> None:
    provider = InMemoryFundamentalDataProvider(fundamental_entries)
    result = provider.fetch_fundamentals(
        ["2330.TW", "2317.TW"], date(2024, 1, 2), date(2024, 1, 3)
    )
    assert len(result) == 2
    assert {item.symbol for item in result} == {"2330.TW", "2317.TW"}


def test_inmemory_corporate_action_provider_has_fetch_actions() -> None:
    provider = InMemoryCorporateActionProvider([])
    assert hasattr(provider, "fetch_actions")


def test_fetch_actions_empty_seed_returns_empty() -> None:
    provider = InMemoryCorporateActionProvider([])
    result = provider.fetch_actions(["2330.TW"], date(2024, 1, 1), date(2024, 1, 3))
    assert result == []


def test_fetch_actions_full_match_returns_all_records(
    action_entries: list[CorporateAction],
) -> None:
    provider = InMemoryCorporateActionProvider(action_entries)
    result = provider.fetch_actions(["2330.TW", "2317.TW"], date(2024, 1, 1), date(2024, 1, 3))
    assert result == action_entries


def test_fetch_actions_filters_symbol_subset(
    action_entries: list[CorporateAction],
) -> None:
    provider = InMemoryCorporateActionProvider(action_entries)
    result = provider.fetch_actions(["2317.TW"], date(2024, 1, 1), date(2024, 1, 3))
    assert len(result) == 1
    assert result[0].symbol == "2317.TW"


def test_fetch_actions_inclusive_start_and_end_boundaries_using_ex_date(
    action_entries: list[CorporateAction],
) -> None:
    provider = InMemoryCorporateActionProvider(action_entries)
    result = provider.fetch_actions(["2330.TW"], date(2024, 1, 1), date(2024, 1, 3))
    assert [item.ex_date for item in result] == [date(2024, 1, 1), date(2024, 1, 3)]


def test_fetch_actions_multi_symbol_query_returns_combined_results(
    action_entries: list[CorporateAction],
) -> None:
    provider = InMemoryCorporateActionProvider(action_entries)
    result = provider.fetch_actions(["2330.TW", "2317.TW"], date(2024, 1, 2), date(2024, 1, 3))
    assert len(result) == 2
    assert {item.symbol for item in result} == {"2330.TW", "2317.TW"}


def test_fetch_actions_constructor_makes_defensive_copy(
    action_entries: list[CorporateAction],
) -> None:
    seed = list(action_entries)
    provider = InMemoryCorporateActionProvider(seed)
    seed.clear()
    result = provider.fetch_actions(["2330.TW", "2317.TW"], date(2024, 1, 1), date(2024, 1, 3))
    assert len(result) == 3


def test_data_package_exports_stub_provider_names() -> None:
    import src.tw_quant.data as data_pkg

    assert hasattr(data_pkg, "InMemoryMarketDataProvider")
    assert hasattr(data_pkg, "InMemoryFundamentalDataProvider")
    assert hasattr(data_pkg, "InMemoryCorporateActionProvider")


def test_to_date_normalizes_date_datetime_and_iso_string_for_comparison() -> None:
    target = date(2024, 1, 2)
    from_date = _to_date(date(2024, 1, 2))
    from_datetime = _to_date(datetime(2024, 1, 2, 9, 30, 0))
    from_iso = _to_date("2024-01-02")

    assert from_date == target
    assert from_datetime == target
    assert from_iso == target
