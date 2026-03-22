# Stock Report Date-Range Support

## Overview

Add a dedicated CLI command that exports a single stock report for a user-specified inclusive date range. The report should include daily OHLCV rows plus derived volume, technical, flow, and chip-style metrics that can be computed from the repository's existing market-data layer.

## Scope

- Add a new CLI command: `stock-report`.
- Require a target symbol and inclusive `--start` / `--end` dates.
- Accept Taiwan stock symbols in either normalized or shorthand form when possible.
- Fetch only the requested stock history plus the warmup window required for derived indicators.
- Output a JSON payload containing:
  - command metadata,
  - stock metadata,
  - date range metadata,
  - a list of per-day report rows.
- Support optional CSV export for the same row-level output.
- Include daily fields for:
  - OHLCV,
  - turnover when available,
  - volume ratios and flow approximations,
  - moving averages,
  - MACD histogram,
  - RSI,
  - rolling highs/lows,
  - chip-style concentration/distribution proxies based on existing repo utilities.
- Provide clear errors for invalid dates, missing symbol history, or empty result windows.
- Add tests for argument validation, report payload shape, and CSV export.

## Non-Goals

- No new third-party market, broker, or institutional chip-data provider integration.
- No changes to daily-selection strategy behavior.
- No redesign of existing data provider interfaces.

## Data Boundary

- The report must use the existing `MarketDataProvider.fetch_ohlcv(...)` interface.
- "籌碼" output in this task means repo-native derived chip metrics computed from price/volume-derived proxies or existing chip utilities, not exchange-native institutional flow data.
- If `turnover` is unavailable from the provider, keep the field present with `null`.

## Affected Files

- `src/tw_quant/runner.py`
- `src/tw_quant/workflows.py`
- `tests/test_tw_quant_runner_params.py`
- `tests/test_tw_quant_stock_report_contracts.py` (new)

## Implementation Plan

1. Add a stock-report CLI parser:
- required `--symbol`
- required `--start`
- required `--end`
- optional `--output-csv`

2. Add symbol/date helpers:
- normalize symbol input using the existing TW symbol normalization path when possible,
- validate `end >= start`,
- calculate an internal warmup window long enough for MA, MACD, RSI, and rolling metrics.

3. Add a workflow/helper that builds a stock report:
- fetch OHLCV for the symbol over warmup + requested range,
- sort/filter bars to the requested inclusive range,
- derive row-level metrics using existing utility functions where available.

4. Define row fields:
- `date`, `symbol`, `open`, `high`, `low`, `close`, `volume`, `turnover`
- `price_change`, `price_change_pct`
- `volume_ratio_5`, `volume_ratio_20`
- `ma_5`, `ma_10`, `ma_20`, `ma_60`
- `rolling_high_20`, `rolling_low_20`
- `macd_histogram`, `rsi_14`
- `estimated_inflow`, `estimated_outflow`, `flow_ratio_5`, `flow_momentum_5`
- `chip_concentration_proxy`, `chip_distribution_5_proxy`, `cost_basis_ratio_proxy`

5. Add output writers:
- print JSON to stdout,
- optionally write CSV with stable column order and parent-directory creation.

6. Add tests:
- date validation rejects `end < start`,
- report generation returns only requested dates,
- report includes derived fields and stock metadata,
- CSV export writes expected rows and headers.

## Acceptance Criteria

- `python -m src.tw_quant.runner stock-report --symbol 2330 --start 2025-09-01 --end 2025-09-05` prints JSON output for the requested stock and date window.
- `python -m src.tw_quant.runner stock-report --symbol 2330.TW --start 2025-09-01 --end 2025-09-05 --output-csv reports/2330_2025-09-01_2025-09-05.csv` writes a CSV file.
- Output rows include OHLCV and derived volume / technical / flow / chip-style metrics.
- Empty or missing history fails fast with a clear message.
- Added tests pass.

## Open Questions

- None. For shorthand Taiwan symbols, prefer existing normalization behavior and fall back to the raw symbol only if normalization returns `None`.
