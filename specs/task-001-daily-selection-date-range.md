# Daily Selection Date-Range Support

## Overview

Extend `daily-selection` so it can run over an inclusive date range and output deduplicated symbols that matched selection conditions at least once in that period.

## Scope

- CLI supports `--start` and `--end` for `daily-selection`.
- Existing `--as-of` remains supported and backward compatible.
- Range mode runs selection day-by-day and aggregates symbol hits.
- Range mode optionally writes an aggregated CSV via `--output-csv`.
- Range mode shows stock-level execution progress when progress output is enabled.
- Parallel execution keeps `yfinance_ohlcv` on a bounded safe mode to avoid empty results under excessive concurrency.
- Daily selection artifacts include fetch-completeness diagnostics so missing market data is visible instead of silently degrading output.
- Daily selection can exclude known-unsupported `yfinance` symbols and fail fast when missing-history exceeds a configurable threshold.
- Daily selection prints selected-signal criteria in terminal output and persists them in CSV-friendly form.
- Daily selection CSV preserves stock names consistently across TWSE, TPEX, and CSV-backed universe sources.
- Range output includes:
  - first matched date,
  - last matched date,
  - matched day count.
- Add tests for date parsing and range output behavior.

## Non-Goals

- No changes to strategy internals.
- No changes to market data provider interfaces.
- No changes to backtest-batch command behavior.

## Affected Files

- `src/tw_quant/runner.py`
- `tests/test_tw_quant_runner_params.py`
- `tests/test_tw_quant_runner_daily_selection_range.py` (new)

## Implementation Plan

1. Add date argument model for `daily-selection`:
- Keep `--as-of`.
- Add `--start` and `--end`.
- Validate that:
  - exactly one mode is used (`as-of` vs range),
  - `--start` requires `--end`,
  - `end >= start`.

2. Add a helper to resolve execution dates:
- single date list for `--as-of`,
- inclusive date list for `--start` + `--end`.

3. Keep single-day output unchanged:
- output remains list of selection records.

4. Implement range output aggregation:
- run `DailySelectionRunner.run(...)` per date,
- dedupe symbols by day,
- aggregate first date, last date, and matched day count per symbol,
- output a summary object containing date range metadata and symbol stats.

5. Add optional CSV export:
- add `--output-csv` to `daily-selection`,
- write the aggregated range summary to the requested path,
- create parent directories automatically,
- keep console JSON output available for automation.

6. Add execution visibility and safe parallel behavior:
- print a per-day execution summary before work starts when `--show-progress` is enabled,
- keep progress reporting focused on processed symbols instead of processed dates,
- when `market_provider` is `yfinance_ohlcv`, cap effective worker fan-out to a safer bound and use chunked shared-provider execution.
- if chunked `yfinance_ohlcv` execution leaves symbols without history, retry those symbols through a low-concurrency recovery pass before final selection.
- persist fetch completeness diagnostics such as universe size, symbols with history, and missing-history samples in the daily artifact JSON.
- load a maintained denylist of known-unsupported `yfinance` symbols before daily selection universe expansion.
- expose a CLI threshold that blocks completion when `missing_history_count / universe_size` exceeds the accepted ratio.
- enrich single-day and range outputs with the selected signal metadata so filtering conditions are visible in terminal output, artifact JSON, and CSV.
- ensure stock-name mapping handles the current TWSE open-data field names and does not drop names when universe rows are rewrapped.

7. Add tests:
- date-resolution helper tests,
- range-mode output schema and values,
- CSV export file generation and contents,
- backward-compatible single-day output shape,
- progress summary output,
- safe worker capping for `yfinance_ohlcv`,
- unsupported-symbol filtering,
- missing-history threshold enforcement,
- selected-criteria terminal output,
- selected-criteria CSV columns,
- stock-name preservation across universe providers.

## Acceptance Criteria

- `python -m src.tw_quant.runner daily-selection --as-of 2026-03-09 --strategy qizhang_selection_strategy` still works and outputs the original list format.
- `python -m src.tw_quant.runner daily-selection --start 2026-03-09 --end 2026-03-15 --strategy qizhang_selection_strategy` works.
- Range output contains deduplicated symbols and includes `first_matched_date`, `last_matched_date`, `matched_days`.
- `python -m src.tw_quant.runner daily-selection --start 2026-03-09 --end 2026-03-15 --strategy qizhang_selection_strategy --output-csv reports/qizhang_2026-03-09_2026-03-15.csv` writes a CSV file.
- Invalid date argument combinations fail fast with clear errors.
- With `--show-progress`, each day prints a startup summary and symbol-level progress.
- With `market_provider: yfinance_ohlcv`, very large `--workers` values do not collapse selection output due to unsafe provider fan-out.
- Daily artifact JSON makes incomplete fetches visible via completeness counters and a sample of missing symbols.
- Known unsupported `yfinance` symbols can be excluded through repository-managed configuration.
- A run can be blocked automatically when missing-history ratio exceeds the configured threshold.
- Single-day terminal output includes the selected signal criteria for each chosen symbol.
- Daily selection CSV output includes a JSON criteria column and flattened `criteria_*` columns for selected rows.
- TWSE-listed symbols that expose `公司名稱` or `公司簡稱` populate `stock_name` in terminal output and range CSV.
- Added tests pass.

## Open Questions

- None. Default aggregation output sorts by `matched_days` descending then `symbol` ascending.
