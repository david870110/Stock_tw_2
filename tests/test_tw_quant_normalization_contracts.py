from datetime import date, datetime

from src.tw_quant.normalization import (
    map_corporate_action_row,
    map_fundamental_row,
    map_ohlcv_row,
    normalize_corporate_action_rows,
    normalize_error_to_dict,
    normalize_fundamental_rows,
    normalize_ohlcv_rows,
)


def test_map_ohlcv_row_resolves_aliases_and_applies_turnover_fallback() -> None:
    row = {
        "ticker": "2330.tw",
        "trade_date": "2024-01-03",
        "o": "100",
        "h": "110",
        "l": "95",
        "c": "108",
        "vol": "1000",
    }

    record, errors = map_ohlcv_row(row, row_index=0)

    assert errors == []
    assert record is not None
    assert record.symbol == "2330.TW"
    assert record.date == date(2024, 1, 3)
    assert record.turnover == 108000.0


def test_map_fundamental_row_coerces_types_and_uses_source_fallback() -> None:
    row = {
        "stock_id": "2317.tw",
        "as_of": datetime(2024, 1, 2, 9, 30, 0),
        "field": "PE",
        "metric_value": "12.5",
    }

    record, errors = map_fundamental_row(row, row_index=0)

    assert errors == []
    assert record is not None
    assert record.symbol == "2317.TW"
    assert record.date == date(2024, 1, 2)
    assert record.metric == "pe"
    assert record.value == 12.5
    assert record.source == "unknown"


def test_map_corporate_action_row_extracts_metadata_and_normalizes_action_type() -> None:
    row = {
        "code": "2603.tw",
        "effective_date": "2024-03-01",
        "event": "Cash_Dividend",
        "amount": "1.8",
        "announcement_id": "A-123",
    }

    record, errors = map_corporate_action_row(row, row_index=0)

    assert errors == []
    assert record is not None
    assert record.symbol == "2603.TW"
    assert record.ex_date == date(2024, 3, 1)
    assert record.action_type == "cash_dividend"
    assert record.value == 1.8
    assert record.metadata == {"announcement_id": "A-123"}


def test_normalize_ohlcv_rows_returns_records_and_errors_without_throwing() -> None:
    rows = [
        {
            "symbol": "2330.TW",
            "date": "2024-01-01",
            "open": 100,
            "high": 110,
            "low": 95,
            "close": 108,
            "volume": 1000,
        },
        {
            "symbol": "2330.TW",
            "date": "2024-01-02",
            "open": 100,
            "high": 90,
            "low": 95,
            "close": 96,
            "volume": 1000,
        },
        {
            "symbol": "2330.TW",
            "date": "2024-01-03",
            "open": 100,
            "high": 110,
            "low": 95,
            "close": 108,
            "volume": -1,
        },
    ]

    result = normalize_ohlcv_rows(rows)

    assert len(result.records) == 1
    assert len(result.errors) == 2
    assert {error.row_index for error in result.errors} == {1, 2}
    assert {error.code for error in result.errors} == {"boundary_violation"}


def test_normalize_fundamental_rows_collects_missing_field_errors() -> None:
    rows = [
        {
            "symbol": "2330.TW",
            "date": "2024-01-01",
            "metric": "pe",
            "value": "20.1",
        },
        {
            "symbol": "2330.TW",
            "date": "2024-01-02",
            "metric": "pb",
        },
    ]

    result = normalize_fundamental_rows(rows)

    assert len(result.records) == 1
    assert len(result.errors) == 1
    assert result.errors[0].row_index == 1
    assert result.errors[0].field == "value"
    assert result.errors[0].code == "missing_or_invalid"


def test_normalize_corporate_action_rows_collects_validation_errors() -> None:
    rows = [
        {
            "symbol": "2330.TW",
            "ex_date": "2024-07-01",
            "action_type": "cash_dividend",
            "value": "2.5",
        },
        {
            "symbol": "2330.TW",
            "ex_date": "not-a-date",
            "action_type": "cash_dividend",
            "value": "2.5",
        },
        {
            "symbol": "2330.TW",
            "ex_date": "2024-07-02",
            "action_type": "cash_dividend",
            "value": "-1",
        },
    ]

    result = normalize_corporate_action_rows(rows)

    assert len(result.records) == 1
    assert len(result.errors) == 2
    assert {error.row_index for error in result.errors} == {1, 2}
    assert {error.field for error in result.errors} == {"ex_date", "value"}


def test_normalize_error_to_dict_serializes_error_model() -> None:
    result = normalize_ohlcv_rows(
        [
            {
                "symbol": "2330.TW",
                "date": "2024-01-01",
                "open": 100,
                "high": 110,
                "low": 95,
                "close": 108,
            }
        ]
    )

    serialized = normalize_error_to_dict(result.errors[0])

    assert serialized["row_index"] == 0
    assert serialized["field"] == "volume"
    assert serialized["code"] == "missing_or_invalid"
