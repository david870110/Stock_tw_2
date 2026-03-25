# Qizhang Improve Strategy

## Overview

Add a new selectable strategy variant named `qizhang_improve_strategy_v15` based on the latest user-provided qizhang 1.5 conditions. The existing `qizhang_selection_strategy` and `qizhang_improve_strategy` behaviors must remain unchanged.

## Scope

- Introduce `qizhang_improve_strategy` as a distinct strategy name for `daily-selection`, `backtest-batch`, and `strategy-improve-report`.
- Introduce `qizhang_improve_strategy_v15` as an additional distinct strategy name for `daily-selection`, `backtest-batch`, and `strategy-improve-report`.
- Reuse the existing qizhang signal pipeline where practical, but keep old and new rule sets isolated so the legacy strategy output does not regress.
- Implement the revised improved rule set with two qualifying branches plus shared confirmation gates.
- Expose improved-rule metadata in selection artifacts so CSV / JSON outputs can explain why a symbol passed or failed.
- Add or update tests that prove the new strategy is wired and its improved thresholds are enforced.
- Improve `strategy-improve-report` diagnostics so forward-price fetch failures are visible in the manifest without requiring manual CSV inspection.

## Non-Goals

- Do not change the rule thresholds or behavior of `qizhang_selection_strategy`.
- Do not change the rule thresholds or behavior of the existing `qizhang_improve_strategy`.
- Do not redesign the existing stock-report schema or rename existing `qizhang_*` columns.
- Do not change CLI defaults away from `qizhang_selection_strategy`.
- Do not change bucket boundaries or the existing `forward_returns.csv` column layout.

## Affected Files or Components

- `src/tw_quant/strategy/technical/qizhang_signal.py`
- `src/tw_quant/strategy/technical/__init__.py`
- `src/tw_quant/workflows.py`
- `src/tw_quant/runner.py`
- `tests/test_tw_quant_daily_selection_runtime.py`
- `tests/test_tw_quant_runner_strategy_improve_report.py`
- Additional focused technical-strategy test file(s) if needed

## Improved Strategy Rules

The existing `qizhang_improve_strategy` rules remain unchanged.

## V1.5 Strategy Rules

### Branch A

The first qualifying branch for `qizhang_improve_strategy_v15` must require all of:

- `price_change_pct >= 0.05`
- `volume_ratio_5 >= 1.45`
- `volume_ratio_20 >= 1.70`

### Branch B

The second qualifying branch for `qizhang_improve_strategy_v15` must require all of:

- `volume_ratio_5 >= 3.0`
- `volume_ratio_20 >= 1.70`
- `rsi_14 >= 45`
- `macd_histogram > 0`

### Shared Confirmation Gates

At least one branch above must pass, and all of the following shared gates must also pass:

- `close_position_20d >= 0.70`
- `close > ma_20`
- `close_vs_ma_60 >= 0.00`
- `net_flow > 0`
- `rsi_14 >= 50`
- `macd_histogram > 0.15`

### Upper-Bound Filters

The v1.5 strategy must also reject overheated setups using all of:

- `close_vs_ma_20 <= 0.30`
- `close_vs_ma_60 <= 0.45`
- `rsi_14 <= 82`

### Shared Evaluation Notes

- `sig_explosive` and `sig_anchor` remain mutually exclusive in metadata selection, with `sig_explosive` taking priority if both branch patterns would otherwise qualify.
- `close_position_20d` refers to the existing 20-day close-range position metric already produced by the qizhang snapshot.
- Existing snapshot calculations for `price_change_pct`, `volume_ratio_5`, `volume_ratio_20`, `ma_20`, `ma_60`, `close_vs_ma_20`, `close_vs_ma_60`, `rsi_14`, `macd_histogram`, and `net_flow` should continue to be reused where possible.

## Implementation Steps

1. Extend qizhang strategy evaluation so it can support the legacy, improve, and v1.5 rule sets without changing the legacy or existing improve outputs.
2. Register `qizhang_improve_strategy_v15` in workflow strategy resolution so CLI commands can invoke it.
3. Ensure v1.5 strategy metadata includes:
   - distinct indicator / strategy identity,
   - selected setup,
   - branch thresholds,
   - shared confirmation thresholds,
   - upper-bound thresholds,
   - per-check booleans for both branch checks and shared checks,
   - values used by the shared confirmation gates and upper-bound filters.
4. Add tests covering:
   - a passing v1.5 `sig_explosive` case,
   - a passing v1.5 `sig_anchor` case,
   - a rejection case where old improve qizhang would pass but v1.5 fails because of the new upper-bound or stricter shared gates,
   - daily-selection artifact generation for `qizhang_improve_strategy_v15`,
   - strategy-improve-report acceptance of `qizhang_improve_strategy_v15` as the strategy name,
   - manifest diagnostics that list forward-stage missing symbols and statuses when price fetches fail.

## Forward Diagnostics

- `strategy-improve-report` must continue writing `forward_returns.csv`, `bucket_membership.csv`, and grouped stock reports using the existing schemas.
- When forward evaluation rows are missing entry and/or evaluation prices, the manifest must include a dedicated diagnostics object summarizing the failure.
- The diagnostics object must include:
  - total failed row count,
  - per-status counts,
  - distinct missing symbols,
  - per-row failure details with at least `selection_date`, `target_date`, `symbol`, `stock_name`, and `status`.
- When there are no forward failures, the diagnostics object should still be present with zero/empty values so downstream tooling can rely on a stable shape.

## YFinance Rate-Limit Handling

- When Yahoo Finance responds with a yfinance rate-limit error, the market-data path must not immediately treat the symbol as missing data.
- Rate-limited OHLCV requests must wait 5 minutes before each retry.
- The default retry path should therefore allow up to 20 total attempts for a rate-limited symbol request before returning an empty result.
- Non-rate-limit errors may continue to use the existing shorter retry backoff behavior.
- Tests must verify that rate-limit exceptions trigger the 5-minute waits and eventual success path without being silently swallowed inside the yfinance adapter.

## Acceptance Criteria

- `qizhang_improve_strategy_v15` is accepted by workflow strategy resolution and no longer falls back to the moving-average crossover strategy.
- Running `daily-selection --strategy qizhang_improve_strategy_v15` produces artifacts under the v1.5 strategy file name.
- The v1.5 Branch A requires `price_change_pct >= 0.05`, `volume_ratio_5 >= 1.45`, and `volume_ratio_20 >= 1.70`.
- The v1.5 Branch B requires `volume_ratio_5 >= 3.0`, `volume_ratio_20 >= 1.70`, `rsi_14 >= 45`, and `macd_histogram > 0`.
- Both v1.5 branches are gated by `close_position_20d >= 0.70`, `close > ma_20`, `close_vs_ma_60 >= 0.0`, `net_flow > 0`, `rsi_14 >= 50`, and `macd_histogram > 0.15`.
- The v1.5 strategy rejects overheated setups unless `close_vs_ma_20 <= 0.30`, `close_vs_ma_60 <= 0.45`, and `rsi_14 <= 82`.
- `qizhang_selection_strategy` tests continue to reflect the legacy thresholds and behavior.
- `qizhang_improve_strategy` tests continue to reflect the existing improve thresholds and behavior.
- Automated tests cover the new strategy wiring and at least one improved-rule pass/fail distinction.
- `strategy-improve-report` manifests include stable forward diagnostics, and a failing forward fetch lists the affected symbol rows directly in `run_manifest.json`.
- Yahoo Finance rate-limit errors trigger repeated 5-minute retry waits up to a 20-attempt ceiling, instead of being immediately skipped as empty data.

## Open Questions

- None.
