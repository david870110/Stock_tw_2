# Strategy Improve Random Year Sampling Range

## Overview

Update `strategy-improve-report` so sampled years are chosen randomly without replacement from a bounded year range, instead of always using a contiguous block ending at `sample_end_year`.

## Scope

- Add `--sample-start-year` to define the lower bound of the year pool.
- Keep `--years` as the number of unique years to sample.
- Sample years randomly without replacement from `[sample_start_year, sample_end_year]` using `sample_seed`.
- Keep month sampling random and deterministic within each sampled year.
- Preserve ascending `selection_date` ordering in the final sample plan.

## Required Behavior

1. Defaults:
   - `--years = 5`
   - `--sample-start-year = 2014`
   - `--sample-end-year` remains configurable and defaults to `today.year - 1`
2. The sampled-year pool is every year from `sample_start_year` through `sample_end_year`, inclusive.
3. The workflow randomly selects `years` distinct years from that pool using `random.Random(sample_seed)`.
4. If `years` exceeds the number of available years in the pool, exit with a clear validation error.
5. If `sample-start-year > sample-end-year`, exit with a clear validation error.

## Acceptance Criteria

- The sample plan no longer implies a contiguous year block.
- With defaults on 2026-03-24, sampled years come from the bounded pool `2014..2025`.
- Sample-year selection is deterministic for the same seed.
- Tests cover deterministic random-year sampling and year-range validation.
