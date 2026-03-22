"""Tests for backtest parameter parsing normalization in runner."""

from __future__ import annotations

from argparse import Namespace
from datetime import date

import pytest

from src.tw_quant.runner import (
    _ExcludedUniverseProvider,
    _add_calendar_months,
    _filter_selection_forward_candidates,
    _load_excluded_symbols,
    _parse_backtest_params,
    _raise_if_missing_history_ratio_exceeded,
    _resolve_daily_selection_dates,
    _resolve_selection_forward_output_path,
    _resolve_selection_forward_window,
    _resolve_stock_report_dates,
    _resolve_stock_report_symbol,
)
from src.tw_quant.universe.models import ListingStatus, UniverseEntry
from src.tw_quant.universe.stub import InMemoryUniverseProvider


def test_parse_backtest_params_repairs_malformed_exit_pairs() -> None:
    parsed = _parse_backtest_params(
        "{exits:{stop_loss_pct:0.6,take_profit_pct:1.2,max_holding_days:360}}"
    )

    exits = parsed.get("exits")
    assert isinstance(exits, dict)
    assert exits == {
        "stop_loss_pct": 0.6,
        "take_profit_pct": 1.2,
        "max_holding_days": 360,
    }


def test_parse_backtest_params_keeps_regular_json_unchanged() -> None:
    parsed = _parse_backtest_params(
        '{"exits":{"stop_loss_pct":0.6,"take_profit_pct":1.2,"max_holding_days":360}}'
    )

    exits = parsed.get("exits")
    assert isinstance(exits, dict)
    assert exits["stop_loss_pct"] == 0.6
    assert exits["take_profit_pct"] == 1.2
    assert exits["max_holding_days"] == 360


def test_resolve_daily_selection_dates_accepts_single_day_as_of() -> None:
    args = Namespace(as_of="2026-03-09", start=None, end=None)
    resolved = _resolve_daily_selection_dates(args)
    assert resolved == [date(2026, 3, 9)]


def test_resolve_daily_selection_dates_builds_inclusive_range() -> None:
    args = Namespace(as_of=None, start="2026-03-09", end="2026-03-11")
    resolved = _resolve_daily_selection_dates(args)
    assert resolved == [date(2026, 3, 9), date(2026, 3, 10), date(2026, 3, 11)]


def test_resolve_daily_selection_dates_rejects_missing_range_end() -> None:
    args = Namespace(as_of=None, start="2026-03-09", end=None)
    with pytest.raises(SystemExit, match="--end is required"):
        _resolve_daily_selection_dates(args)


def test_resolve_daily_selection_dates_rejects_end_with_as_of() -> None:
    args = Namespace(as_of="2026-03-09", start=None, end="2026-03-15")
    with pytest.raises(SystemExit, match="cannot be used together"):
        _resolve_daily_selection_dates(args)


def test_resolve_stock_report_dates_accepts_inclusive_window() -> None:
    args = Namespace(start="2026-03-09", end="2026-03-15")
    assert _resolve_stock_report_dates(args) == (date(2026, 3, 9), date(2026, 3, 15))


def test_resolve_stock_report_dates_rejects_reversed_window() -> None:
    args = Namespace(start="2026-03-15", end="2026-03-09")
    with pytest.raises(SystemExit, match="greater than or equal"):
        _resolve_stock_report_dates(args)


def test_resolve_stock_report_symbol_normalizes_tw_numeric_symbol() -> None:
    assert _resolve_stock_report_symbol("2330") == "2330.TW"


def test_resolve_stock_report_symbol_keeps_unknown_symbol_format_when_nonempty() -> None:
    assert _resolve_stock_report_symbol("SPY") == "SPY"


def test_resolve_selection_forward_window_accepts_positive_months() -> None:
    args = Namespace(forward_months=1, forward_days=None)
    resolved = _resolve_selection_forward_window(args)
    assert resolved == {"kind": "months", "value": 1, "label": "1m"}


def test_resolve_selection_forward_window_rejects_nonpositive_days() -> None:
    args = Namespace(forward_months=None, forward_days=0)
    with pytest.raises(SystemExit, match="greater than 0"):
        _resolve_selection_forward_window(args)


def test_add_calendar_months_caps_day_at_month_end() -> None:
    assert _add_calendar_months(date(2026, 1, 31), 1) == date(2026, 2, 28)


def test_filter_selection_forward_candidates_keeps_all_valid_signal_rows() -> None:
    rows = [
        {"symbol": "2330.TW", "timestamp": "2026-02-11", "selected": "True"},
        {"symbol": "2317.TW", "timestamp": "2026-02-11", "selected": "False"},
    ]
    assert _filter_selection_forward_candidates(rows) == rows


def test_resolve_selection_forward_output_path_defaults_beside_selection_csv(tmp_path) -> None:
    selection_csv = tmp_path / "qizhang_selection_strategy.csv"
    resolved = _resolve_selection_forward_output_path(
        selection_csv_path=selection_csv,
        forward_window={"kind": "months", "value": 1, "label": "1m"},
        explicit_output_path=None,
    )
    assert resolved == tmp_path / "qizhang_selection_strategy_forward_1m.csv"


def test_load_excluded_symbols_ignores_comments_and_blank_lines(tmp_path) -> None:
    path = tmp_path / "symbols.txt"
    path.write_text("2330.TW\n# comment\n2317.TW  # inline comment\n\n", encoding="utf-8")

    assert _load_excluded_symbols(path) == {"2330.TW", "2317.TW"}


def test_excluded_universe_provider_filters_known_symbols() -> None:
    provider = InMemoryUniverseProvider(
        [
            UniverseEntry(
                symbol="2330.TW",
                exchange="TWSE",
                market="stock",
                listing_status=ListingStatus.LISTED,
                updated_at=date(2026, 3, 21),
                name="TSMC",
            ),
            UniverseEntry(
                symbol="2317.TW",
                exchange="TWSE",
                market="stock",
                listing_status=ListingStatus.LISTED,
                updated_at=date(2026, 3, 21),
                name="HonHai",
            ),
        ]
    )

    filtered = _ExcludedUniverseProvider(base_provider=provider, excluded_symbols={"2317.TW"})

    assert [entry.symbol for entry in filtered.get_universe()] == ["2330.TW"]
    assert filtered.get_symbol("2317.TW") is None


def test_raise_if_missing_history_ratio_exceeded_blocks_when_over_threshold() -> None:
    with pytest.raises(SystemExit, match="missing-history ratio exceeded threshold"):
        _raise_if_missing_history_ratio_exceeded(
            run_summary={"as_of": "2025-09-04", "universe_size": 100, "missing_history_count": 26},
            threshold=0.2,
        )


def test_raise_if_missing_history_ratio_exceeded_allows_when_under_threshold() -> None:
    _raise_if_missing_history_ratio_exceeded(
        run_summary={"as_of": "2025-09-04", "universe_size": 100, "missing_history_count": 5},
        threshold=0.2,
    )
