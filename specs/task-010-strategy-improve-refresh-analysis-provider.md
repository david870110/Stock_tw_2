# Strategy Improve Refresh Analysis Provider

## Overview

Fix `strategy-improve-report` so Step1-Step4 do not reuse the same market-data provider instance that was heavily exercised during Step0 daily-selection. This avoids all-missing forward returns caused by stale or throttled provider state after large sampled runs.

## Scope

- Keep Step0 selection behavior unchanged.
- Before Step1 forward-return evaluation and grouped stock-report generation, build a fresh market-data provider from config.
- Keep the existing universe filtering/subsetting behavior for strategy-improve outputs.
- Add regression coverage for the case where the initial provider yields no forward bars but a fresh analysis provider does.

## Acceptance Criteria

- `strategy-improve-report` uses a fresh market-data provider for Step1-Step4.
- A regression test proves forward rows succeed when the initial provider is empty and the refreshed provider has bars.
- Existing strategy-improve and forward-report tests continue to pass.
