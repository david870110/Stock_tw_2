# Strategy Improve Bucketed Stock Report

## Overview

Add a new CLI workflow that samples strategy selection dates across five years, runs the existing daily-selection process for each sampled month-end, evaluates each selected stock one calendar month later, buckets the realized return into four ranges, and writes grouped stock-report artifacts under `artifacts/Stratage_improve/`.

This feature is intended for strategy optimization analysis rather than portfolio simulation. It must reuse existing daily-selection and stock-report behavior where possible, keep all generated data under one strategy-specific artifact root, and expose the selection-stage parallelism knobs requested by the user.

## Scope

- Add a new CLI subcommand dedicated to strategy improvement analysis.
- Sample `5` unique months per year across `5` years by default, producing `25` selection dates total.
- Use the existing `DailySelectionRunner` for Step0 selection on each sampled date.
- For every selected stock on every sampled date:
  - resolve the entry close on or after the selection date,
  - resolve the evaluation close on or after one calendar month later,
  - compute `return_pct = (evaluation_close / entry_close) - 1`.
- Bucket each evaluated stock into these four ranges:
  - `gte_0_2`: `return_pct >= 0.2`
  - `between_0_2_and_0`: `0 < return_pct < 0.2`
  - `between_0_and_neg_0_2`: `-0.2 <= return_pct <= 0`
  - `lt_neg_0_2`: `return_pct < -0.2`
- Generate grouped stock-report CSV artifacts by selection date and bucket.
- Keep all outputs under `artifacts/Stratage_improve/<strategy_name>/` with subfolders allowed.
- Provide tqdm-based progress visibility for the multi-step workflow.

## Non-Goals

- No change to strategy signal logic.
- No portfolio allocation, position sizing, slippage, or execution simulation.
- No optimization scoring/ranking beyond the requested return buckets and grouped reports.
- No requirement to support arbitrary holding windows in this task; Step1 is fixed to one calendar month.
- No deletion or cleanup of pre-existing files under `artifacts/Stratage_improve/`.

## CLI Contract

Add a new CLI subcommand in `src/tw_quant/runner.py`:

- Command name: `strategy-improve-report`

Required/primary args:

- `--strategy`, default `qizhang_selection_strategy`

Sampling and reproducibility args:

- `--years`, default `5`
- `--sample-start-year`, default `2014`
- `--months-per-year`, default `5`
- `--sample-end-year`, optional; when omitted, default to `today.year - 1`
- `--sample-seed`, default `42`

Selection execution args:

- `--workers`, default `20`
- `--missing-history-threshold`, default `0.2`
- `--top-n`, default `30` for Step0 daily-selection compatibility only; Step1-Step4 must evaluate all buy-signal rows regardless of whether they were top-N selected
- `--max-symbols`, optional
- `--symbols`, optional explicit symbol subset
- `--show-progress`, boolean flag to enable tqdm progress bars for this workflow and the Step0 daily-selection runs

Output args:

- `--output-root`, optional override; default is `artifacts/Stratage_improve`

## Sampling Rules

1. Determine the sampled year pool as every year from `sample_start_year` through `sample_end_year`, inclusive.
2. Randomly choose `years` unique sample years from that pool using `random.Random(sample_seed)`.
3. For each sampled year:
   - randomly choose `months_per_year` unique month numbers from `1..12`,
   - use the deterministic random generator seeded by `sample_seed`,
   - convert each selected month to the calendar month-end date.
4. Sort the final sampled dates in ascending order before execution.
5. Validation:
   - `years` must be greater than `0`,
   - `sample_start_year` must be less than or equal to `sample_end_year`,
   - `years` must not exceed the number of years in the `[sample_start_year, sample_end_year]` pool,
   - `months_per_year` must be between `1` and `12`,
   - `months_per_year` must not exceed `12`.

## Output Layout

All output for one run must live under:

- `artifacts/Stratage_improve/<strategy_name>/`

Recommended structure:

- `manifest/`
  - `run_manifest.json`
  - `sample_plan.csv`
- `selection_cache/`
  - reuse `DailySelectionRunner(output_base=...)` so daily selection artifacts land beneath this subtree
- `forward_returns/`
  - `forward_returns.csv`
  - `forward_returns_summary.csv`
- `buckets/`
  - `bucket_membership.csv`
  - `bucket_summary.csv`
- `stock_reports/<selection_date>/`
  - one grouped CSV per bucket, even when a bucket is empty

PNG previews should be generated for every written CSV by reusing the existing CSV image helper.

## Forward Return Rules

1. Use the Step0 daily-selection output rows for each sampled date.
2. Step1-Step4 must use all buy-signal rows from that date, including rows marked `selected=False`.
3. For each buy-signal symbol:
   - `entry_date` is the first OHLCV bar on or after `selection_date`,
   - `target_date` is `selection_date + 1 calendar month`,
   - `evaluation_date` is the first OHLCV bar on or after `target_date`,
   - if either price is missing, keep the row with a non-`ok` status rather than failing the whole workflow.
4. `return_pct` uses six-decimal rounding, matching the existing forward report convention.

## Missing-History Threshold Behavior

- `strategy-improve-report` must continue running even when an individual sampled date exceeds `--missing-history-threshold`.
- When a sampled date exceeds the threshold:
  - emit a human-readable warning to stdout,
  - skip Step1-Step4 for that sampled date,
  - record the skipped date and threshold details in the final manifest JSON,
  - continue processing the remaining sampled dates.
- This skip-with-warning behavior applies only to the strategy-improve workflow in this task.
- Existing `daily-selection` command behavior remains unchanged and may still abort when the threshold is exceeded.

## Bucketed Stock Report Rules

For each `selection_date` and each bucket:

1. Build a grouped report over the window `[selection_date, evaluation_date]` for every symbol assigned to that bucket.
2. Reuse `build_stock_report()` per symbol and flatten the symbol-level rows into one grouped CSV.
3. Each grouped stock-report row must include the original stock-report fields plus these added fields:
   - `selection_date`
   - `target_date`
   - `evaluation_date`
   - `bucket`
   - `return_pct`
   - `entry_close`
   - `evaluation_close`
4. Empty buckets should still produce a CSV with headers and zero data rows so the artifact layout is predictable.

## Stdout JSON Contract

The command should print one JSON object that includes at least:

- `mode`: `strategy_improve_report`
- `strategy`
- `artifact_root`
- `sample_seed`
- `sample_years`
- `sampled_dates`
- `selection_run_count`
- `selected_symbol_count`
- `evaluated_row_count`
- `bucket_counts`
- `output_paths`

## Affected Files or Components

- `src/tw_quant/runner.py`
- `tests/test_tw_quant_runner_params.py`
- `tests/test_tw_quant_runner_strategy_improve_report.py` (new)
- `specs/task-007-strategy-improve-bucketed-stock-report.md`

## Implementation Steps

1. Add the `strategy-improve-report` CLI parser and argument validation helpers.
2. Add deterministic sample-date planning helpers.
3. Add workflow helpers that:
   - run daily selection into the strategy-improve artifact root,
   - collect selected rows,
   - fetch one-month-forward prices,
   - bucket return rows,
   - write manifest / forward / bucket summary artifacts,
   - write grouped stock-report CSVs and preview PNGs.
4. Reuse existing `DailySelectionRunner`, `_find_first_bar_on_or_after`, `_add_calendar_months`, `build_stock_report`, and CSV preview helpers where practical.
5. Add tests for:
   - sample-plan determinism and validation,
   - bucket classification boundaries,
   - end-to-end artifact generation for grouped stock reports,
   - skip-with-warning behavior when a sampled date exceeds the missing-history threshold,
   - CLI defaults for `--workers` and `--missing-history-threshold`.

## Acceptance Criteria

- Running `strategy-improve-report` with defaults samples `25` month-end dates from `5` years using deterministic randomness.
- Step0 daily selection uses `--workers` default `20` and `--missing-history-threshold` default `0.2`.
- When a sampled date exceeds the missing-history threshold, the workflow logs a warning, skips that date, and continues instead of aborting the whole run.
- The workflow evaluates one calendar month forward for every buy-signal stock from the sampled-date CSV, not only top-N selected rows.
- The workflow classifies returns into exactly four buckets using the requested boundaries.
- All generated files are written under `artifacts/Stratage_improve/<strategy_name>/` or an explicit `--output-root` override.
- Grouped stock-report CSVs are written by selection date and bucket, and include bucket metadata columns.
- The workflow supports tqdm progress when `--show-progress` is enabled.
- Added tests pass.

## Open Questions

- None. This spec resolves reproducibility by using a deterministic seed default of `42`, and resolves the year range by defaulting `sample_end_year` to the previous calendar year so one-month-forward evaluation remains available.
