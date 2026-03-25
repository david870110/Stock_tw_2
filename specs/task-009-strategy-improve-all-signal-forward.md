# Strategy Improve All-Signal Forward Evaluation

## Overview

Update `strategy-improve-report` so Step1-Step4 evaluate all buy signals produced on each sampled selection date, not only the top-N rows marked as selected by the daily-selection pipeline.

## Scope

- Keep Step0 daily-selection execution unchanged.
- Change strategy-improve forward evaluation to consume all buy-signal rows from the persisted daily-selection CSV / run summary.
- Do not change the standalone `daily-selection` command semantics.
- Keep backward-compatible CLI parsing for `--top-n`, but strategy-improve forward evaluation must no longer depend on the `selected` flag.

## Required Behavior

1. `strategy-improve-report` still runs the existing `DailySelectionRunner`.
2. After each sampled-date run, the workflow must collect all rows where the daily-selection CSV indicates a buy signal.
3. Rows with `selected=False` must still proceed into forward-return evaluation and bucket classification.
4. If CSV-style signal rows are unavailable, the workflow may fall back to selected rows only as a degraded compatibility path.
5. Existing missing-history skip-with-warning behavior remains unchanged.

## Acceptance Criteria

- Forward-return rows include buy-signal rows even when they were not top-N selected.
- The regression test covers at least one sampled date with one `selected=True` buy row and one `selected=False` buy row, and both appear in `forward_returns.csv`.
- Existing strategy-improve tests continue to pass.
