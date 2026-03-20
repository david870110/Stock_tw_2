"""Field mappers for TWSE/TPEX open-data universe APIs.

TWSE endpoint: https://openapi.twse.com.tw/v1/opendata/t187ap03_L
TPEX endpoint:  https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes

Both endpoints return JSON arrays.  The field names differ between exchanges,
so each mapper normalises the raw row to the internal schema keys expected by
parse_universe_csv_rows(): symbol, exchange, market, listing_status.
"""

from __future__ import annotations


def _classify_market(row: dict[str, str]) -> str:
    text = " ".join(str(value or "") for value in row.values()).upper()
    etf_markers = (
        "ETF",
        "ETN",
        "指數股票型",
        "受益憑證",
        "受益證券",
        "槓桿",
        "反向",
    )
    if any(marker.upper() in text for marker in etf_markers):
        return "etf"
    return "stock"


def map_twse_row(row: dict[str, str]) -> dict[str, str]:
    """Remap a TWSE t187ap03_L JSON row to internal universe schema keys."""
    symbol_raw = (
        row.get("公司代號", "")
        or row.get("有價證券代號", "")
        or row.get("SecuritiesCode", "")
    ).strip()
    return {
        "symbol": symbol_raw,
        "exchange": "TWSE",
        "market": _classify_market(row),
        "listing_status": "listed",
    }


def map_tpex_row(row: dict[str, str]) -> dict[str, str]:
    """Remap a TPEX tpex_mainboard_quotes JSON row to internal universe schema keys."""
    symbol_raw = (
        row.get("SecuritiesCode", "")
        or row.get("股票代號", "")
        or row.get("代號", "")
        or row.get("StockCode", "")
        or row.get("SecuritiesCompanyCode", "")
    ).strip()
    return {
        "symbol": symbol_raw,
        "exchange": "TPEX",
        "market": _classify_market(row),
        "listing_status": "listed",
    }
