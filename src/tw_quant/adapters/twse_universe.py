"""Field mappers for TWSE/TPEX open-data universe APIs.

TWSE endpoint: https://openapi.twse.com.tw/v1/opendata/t187ap03_L
TPEX endpoint: https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes

Both endpoints return JSON arrays. The field names differ between exchanges,
so each mapper normalizes the raw row to the internal schema keys expected by
parse_universe_csv_rows(): symbol, name, exchange, market, listing_status.
"""

from __future__ import annotations


def _classify_market(row: dict[str, str]) -> str:
    text = " ".join(str(value or "") for value in row.values()).upper()
    etf_markers = (
        "ETF",
        "ETN",
        "指數股票型",
        "受益憑證",
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
        or row.get("證券代號", "")
        or row.get("SecuritiesCode", "")
        or row.get("StockCode", "")
    ).strip()
    return {
        "symbol": symbol_raw,
        "name": (
            row.get("公司簡稱", "")
            or row.get("公司名稱", "")
            or row.get("證券名稱", "")
            or row.get("name", "")
            or row.get("stock_name", "")
            or row.get("company_name", "")
            or row.get("SecurityName", "")
            or row.get("SecuritiesCompanyName", "")
            or row.get("CompanyName", "")
        ).strip(),
        "exchange": "TWSE",
        "market": _classify_market(row),
        "listing_status": "listed",
    }


def map_tpex_row(row: dict[str, str]) -> dict[str, str]:
    """Remap a TPEX tpex_mainboard_quotes JSON row to internal universe schema keys."""
    symbol_raw = (
        row.get("SecuritiesCode", "")
        or row.get("SecuritiesCompanyCode", "")
        or row.get("公司代號", "")
        or row.get("StockCode", "")
    ).strip()
    return {
        "symbol": symbol_raw,
        "name": (
            row.get("CompanyName", "")
            or row.get("公司名稱", "")
            or row.get("公司簡稱", "")
            or row.get("name", "")
            or row.get("stock_name", "")
            or row.get("company_name", "")
            or row.get("SecurityName", "")
            or row.get("SecuritiesCompanyName", "")
        ).strip(),
        "exchange": "TPEX",
        "market": _classify_market(row),
        "listing_status": "listed",
    }
