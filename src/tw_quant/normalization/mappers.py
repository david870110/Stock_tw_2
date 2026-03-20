"""Canonical normalization mappers for OHLCV, fundamentals, and corporate actions."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from math import isfinite
from typing import Any, Mapping

from src.tw_quant.normalization.models import (
    AliasMap,
    BoundaryValidationResult,
    NormalizationError,
)
from src.tw_quant.schema.models import CorporateAction, FundamentalPoint, OHLCVBar


OHLCV_ALIASES: tuple[AliasMap, ...] = (
    AliasMap("symbol", ("ticker", "code", "stock_id")),
    AliasMap("date", ("trade_date", "timestamp", "ts")),
    AliasMap("open", ("o", "open_price")),
    AliasMap("high", ("h", "high_price")),
    AliasMap("low", ("l", "low_price")),
    AliasMap("close", ("c", "close_price", "price")),
    AliasMap("volume", ("vol", "qty", "shares")),
    AliasMap("turnover", ("amount", "value")),
)

FUNDAMENTAL_ALIASES: tuple[AliasMap, ...] = (
    AliasMap("symbol", ("ticker", "code", "stock_id")),
    AliasMap("date", ("as_of", "report_date", "timestamp")),
    AliasMap("metric", ("field", "name", "item")),
    AliasMap("value", ("metric_value", "val")),
    AliasMap("source", ("provider", "vendor")),
)

CORPORATE_ACTION_ALIASES: tuple[AliasMap, ...] = (
    AliasMap("symbol", ("ticker", "code", "stock_id")),
    AliasMap("ex_date", ("date", "effective_date", "timestamp")),
    AliasMap("action_type", ("type", "event", "action")),
    AliasMap("value", ("amount", "ratio")),
)


def normalize_ohlcv_rows(
    rows: list[Mapping[str, Any]],
) -> BoundaryValidationResult[OHLCVBar]:
    """Map source rows to canonical OHLCV records without raising."""

    result: BoundaryValidationResult[OHLCVBar] = BoundaryValidationResult()
    for idx, row in enumerate(rows):
        mapped, row_errors = map_ohlcv_row(row, row_index=idx)
        if mapped is not None:
            result.records.append(mapped)
        result.errors.extend(row_errors)
    return result


def normalize_fundamental_rows(
    rows: list[Mapping[str, Any]],
) -> BoundaryValidationResult[FundamentalPoint]:
    """Map source rows to canonical fundamental records without raising."""

    result: BoundaryValidationResult[FundamentalPoint] = BoundaryValidationResult()
    for idx, row in enumerate(rows):
        mapped, row_errors = map_fundamental_row(row, row_index=idx)
        if mapped is not None:
            result.records.append(mapped)
        result.errors.extend(row_errors)
    return result


def normalize_corporate_action_rows(
    rows: list[Mapping[str, Any]],
) -> BoundaryValidationResult[CorporateAction]:
    """Map source rows to canonical corporate action records without raising."""

    result: BoundaryValidationResult[CorporateAction] = BoundaryValidationResult()
    for idx, row in enumerate(rows):
        mapped, row_errors = map_corporate_action_row(row, row_index=idx)
        if mapped is not None:
            result.records.append(mapped)
        result.errors.extend(row_errors)
    return result


def map_ohlcv_row(
    row: Mapping[str, Any],
    *,
    row_index: int,
) -> tuple[OHLCVBar | None, list[NormalizationError]]:
    errors: list[NormalizationError] = []

    symbol = _coerce_symbol(_resolve_alias(row, OHLCV_ALIASES, "symbol"))
    if symbol is None:
        errors.append(_error(row_index, "missing_or_invalid", "symbol", row))

    record_date = _coerce_date(_resolve_alias(row, OHLCV_ALIASES, "date"))
    if record_date is None:
        errors.append(_error(row_index, "missing_or_invalid", "date", row))

    open_price = _coerce_float(_resolve_alias(row, OHLCV_ALIASES, "open"))
    high_price = _coerce_float(_resolve_alias(row, OHLCV_ALIASES, "high"))
    low_price = _coerce_float(_resolve_alias(row, OHLCV_ALIASES, "low"))
    close_price = _coerce_float(_resolve_alias(row, OHLCV_ALIASES, "close"))
    volume = _coerce_float(_resolve_alias(row, OHLCV_ALIASES, "volume"))

    numeric_fields = {
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "volume": volume,
    }
    for field_name, value in numeric_fields.items():
        if value is None:
            errors.append(_error(row_index, "missing_or_invalid", field_name, row))

    if None in (open_price, high_price, low_price, close_price, volume):
        return None, errors

    if high_price < low_price:
        errors.append(
            NormalizationError(
                row_index=row_index,
                code="boundary_violation",
                message="high must be greater than or equal to low",
                field="high",
            )
        )

    if volume < 0:
        errors.append(
            NormalizationError(
                row_index=row_index,
                code="boundary_violation",
                message="volume must be non-negative",
                field="volume",
            )
        )

    turnover = _coerce_float(_resolve_alias(row, OHLCV_ALIASES, "turnover"))
    if turnover is None:
        turnover = close_price * volume

    if errors:
        return None, errors

    return (
        OHLCVBar(
            symbol=symbol,
            date=record_date,
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            volume=volume,
            turnover=turnover,
        ),
        [],
    )


def map_fundamental_row(
    row: Mapping[str, Any],
    *,
    row_index: int,
) -> tuple[FundamentalPoint | None, list[NormalizationError]]:
    errors: list[NormalizationError] = []

    symbol = _coerce_symbol(_resolve_alias(row, FUNDAMENTAL_ALIASES, "symbol"))
    record_date = _coerce_date(_resolve_alias(row, FUNDAMENTAL_ALIASES, "date"))
    metric = _coerce_string(_resolve_alias(row, FUNDAMENTAL_ALIASES, "metric"))
    value = _coerce_float(_resolve_alias(row, FUNDAMENTAL_ALIASES, "value"))
    source = _coerce_string(_resolve_alias(row, FUNDAMENTAL_ALIASES, "source")) or "unknown"

    if symbol is None:
        errors.append(_error(row_index, "missing_or_invalid", "symbol", row))
    if record_date is None:
        errors.append(_error(row_index, "missing_or_invalid", "date", row))
    if metric is None:
        errors.append(_error(row_index, "missing_or_invalid", "metric", row))
    if value is None:
        errors.append(_error(row_index, "missing_or_invalid", "value", row))

    if errors:
        return None, errors

    return (
        FundamentalPoint(
            symbol=symbol,
            date=record_date,
            metric=metric.lower(),
            value=value,
            source=source,
        ),
        [],
    )


def map_corporate_action_row(
    row: Mapping[str, Any],
    *,
    row_index: int,
) -> tuple[CorporateAction | None, list[NormalizationError]]:
    errors: list[NormalizationError] = []

    symbol = _coerce_symbol(_resolve_alias(row, CORPORATE_ACTION_ALIASES, "symbol"))
    ex_date = _coerce_date(_resolve_alias(row, CORPORATE_ACTION_ALIASES, "ex_date"))
    action_type = _coerce_string(_resolve_alias(row, CORPORATE_ACTION_ALIASES, "action_type"))
    value = _coerce_float(_resolve_alias(row, CORPORATE_ACTION_ALIASES, "value"))

    if symbol is None:
        errors.append(_error(row_index, "missing_or_invalid", "symbol", row))
    if ex_date is None:
        errors.append(_error(row_index, "missing_or_invalid", "ex_date", row))
    if action_type is None:
        errors.append(_error(row_index, "missing_or_invalid", "action_type", row))
    if value is None:
        errors.append(_error(row_index, "missing_or_invalid", "value", row))

    if value is not None and value < 0:
        errors.append(
            NormalizationError(
                row_index=row_index,
                code="boundary_violation",
                message="corporate action value must be non-negative",
                field="value",
                value=str(value),
            )
        )

    if errors:
        return None, errors

    metadata = dict(row)
    for alias in CORPORATE_ACTION_ALIASES:
        metadata.pop(alias.canonical, None)
        for alias_name in alias.aliases:
            metadata.pop(alias_name, None)

    return (
        CorporateAction(
            symbol=symbol,
            ex_date=ex_date,
            action_type=action_type.lower(),
            value=value,
            metadata=metadata,
        ),
        [],
    )


def _resolve_alias(
    row: Mapping[str, Any],
    alias_maps: tuple[AliasMap, ...],
    canonical_field: str,
) -> Any | None:
    for alias_map in alias_maps:
        if alias_map.canonical != canonical_field:
            continue

        if canonical_field in row:
            return row[canonical_field]

        for alias in alias_map.aliases:
            if alias in row:
                return row[alias]
        return None

    return None


def _coerce_symbol(value: Any) -> str | None:
    text = _coerce_string(value)
    if text is None:
        return None
    return text.upper()


def _coerce_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return str(value).strip() or None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None

    if not isfinite(parsed):
        return None
    return parsed


def _coerce_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return date.fromisoformat(text)
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(text).date()
        except ValueError:
            return None
    return None


def _error(
    row_index: int,
    code: str,
    field: str,
    row: Mapping[str, Any],
) -> NormalizationError:
    value = _resolve_debug_value(row, field)
    return NormalizationError(
        row_index=row_index,
        code=code,
        message=f"Invalid field: {field}",
        field=field,
        value=value,
    )


def _resolve_debug_value(row: Mapping[str, Any], field: str) -> str:
    if field in row:
        return str(row[field])
    return ""


def normalize_error_to_dict(error: NormalizationError) -> dict[str, Any]:
    """Convenience function to serialize normalization errors for logging."""

    return asdict(error)
