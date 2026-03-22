# Selection Forward Report

## Overview

Add a CLI workflow that reads a previously generated daily-selection CSV, takes the selected symbols from that snapshot, projects each symbol forward by a user-specified holding window, and outputs the later close price plus realized return over that window.

## Scope

- Add a new CLI command for forward-performance reporting from an existing daily-selection CSV.
- Support projecting by calendar months or calendar days.
- Default to using all signal rows in the CSV rather than only top-N selected rows.
- Fetch market data for the candidate symbols, resolve an entry close from the selection date, resolve an evaluation close from the requested forward date, and compute return percentage.
- Support optional CSV export for the forward report.
- Reuse the existing CSV-to-image helper so the exported CSV also gets a PNG preview.

## Non-Goals

- No change to the daily-selection strategy logic.
- No attempt to simulate an execution engine, slippage, or portfolio allocation.
- No support for arbitrary CSV schemas outside this repository's daily-selection output shape.

## Inputs

- `--selection-csv`: path to a repository-generated daily-selection CSV.
- Exactly one of:
- `--forward-months`
- `--forward-days`
- `--output-csv` optional explicit output path.

## Output Behavior

- The command prints JSON to stdout.
- The command prints JSON to stdout, including aggregate forward-performance summary metrics.
- If `--output-csv` is supplied, write a row-level detail CSV plus a separate summary CSV, and generate PNG previews for both.
- If `--output-csv` is omitted, write a default CSV beside the source selection CSV using a deterministic suffix that includes the forward window.

## Data Resolution Rules

1. Read the selection CSV with `csv.DictReader`.
2. Determine candidate rows:
- keep all rows that have a valid `symbol` and `timestamp`,
- do not drop rows just because `selected=False`.
3. For each candidate row:
- `selection_date` comes from the row `timestamp`,
- `entry_close` comes from the first OHLCV bar on or after `selection_date`,
- `target_date` is `selection_date + forward window`,
- `evaluation_close` comes from the first OHLCV bar on or after `target_date`,
- if either close cannot be resolved inside the fetched history window, keep the row and mark it with a missing-data status instead of failing the whole report.
4. Return percentage is `(evaluation_close / entry_close) - 1`.

## Output Fields

- `symbol`
- `stock_name`
- `selection_date`
- `entry_date`
- `entry_close`
- `target_date`
- `evaluation_date`
- `evaluation_close`
- `return_pct`
- `holding_period_label`
- `selected`
- `rank`
- `weight`
- `status`

## Summary Fields

- `evaluated_count`
- `missing_count`
- `average_return_pct`
- `win_rate`
- `max_return_pct`
- `min_return_pct`

## CSV Layout

- The main forward report CSV contains only per-symbol detail rows.
- A separate summary CSV is written beside it using a deterministic `_summary` suffix.
- Both CSV files also generate same-stem PNG previews.

## Affected Files or Components

- `src/tw_quant/runner.py`
- `tests/test_tw_quant_runner_params.py`
- `tests/test_tw_quant_runner_selection_forward_report.py` (new)

## Implementation Steps

1. Add a new CLI subcommand, for example `selection-forward-report`.
2. Add helpers to:
- parse and validate forward-window arguments,
- read repository daily-selection CSV rows,
- resolve default output paths,
- add calendar months safely,
- fetch and align OHLCV closes for entry and evaluation dates.
3. Emit stdout JSON with run metadata, aggregate summary metrics, and per-symbol rows.
4. Add CSV export and PNG preview generation.
- keep the main CSV focused on row-level details,
- write summary metrics to a dedicated companion CSV.
5. Add tests for argument validation, all-signal row handling, return calculation, missing-data handling, and output artifact creation.

## Acceptance Criteria

- A command can consume a daily-selection CSV from a specific day and produce per-symbol forward return rows.
- All signal rows in the input CSV are used by default, including rows where `selected=False`.
- `--forward-months 1` on a `2026-02-11` selection snapshot evaluates each symbol using the first available trading bar on or after `2026-03-11`.
- The output includes both later close price and return percentage for each symbol.
- The stdout JSON includes average return, win rate, max return, and min return across rows with valid realized returns.
- Optional CSV export writes a detail CSV plus same-stem PNG preview, and a separate summary CSV plus same-stem PNG preview.
- Added tests pass.

## Open Questions

- None.
