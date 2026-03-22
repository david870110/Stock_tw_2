# Qizhang Selection Strategy Report Alignment

## Overview

Update `qizhang_selection_strategy` so it reflects the report "台股大趨勢起漲樣本的共同特徵萃取與量化策略設計" instead of the current simplified MA/MACD/RSI crossover logic.

The revised strategy should model two report-derived setups:

- Setup A: `sig_explosive`, a lower-threshold explosive launch with strong close, strong volume, and positive capital flow.
- Setup B: `sig_anchor`, an abnormal-volume anchor day with positive capital flow and momentum confirmation.

## Scope

- Replace the current hardcoded crossover rules in `QizhangSelectionStrategy`.
- Derive report-aligned features from the available daily OHLCV data.
- Support both setup A and setup B in one strategy output.
- Add candidate reasons and indicator payloads that explain which setup matched and why.
- Update tests so they validate deterministic setup A / setup B behavior and rejection cases.

## Non-Goals

- No changes to unrelated workflow, runner, or reporting modules.
- No integration of external monthly revenue or news datasets.
- No full event backtest engine implementation.
- No attempt to replicate every CSV column from the report when the repository does not provide that data source.

## Affected Files or Components

- `src/tw_quant/selection_contracts/qizhang_selection_strategy.py`
- `tests/test_tw_quant_qizhang_selection_strategy.py`

## Implementation Steps

1. Rework `QizhangSelectionStrategy` to compute report-inspired derived features from the local daily dataset:
- `price_change_pct` from consecutive closes.
- `close_pos` as `(close - low) / (high - low)` with a neutral fallback when range is zero.
- `volume_ratio_5` as latest volume divided by the prior 5-day average volume.
- `volume_ratio_20` as latest volume divided by the prior 20-day average volume.
- `net_flow_proxy` using available data only. Since the repo has no inflow/outflow feed, use a conservative proxy that is positive only when the session is an accumulation day:
  - `close > open`
  - `close_pos >= 0.5`
  - `volume_ratio_5 > 1.0`
- `breakout_above_recent_high` using the prior 20 trading days high, excluding the current day to avoid look-ahead bias.

2. Implement setup A rule set from the latest approved thresholds using repository-available fields:
- `price_change_pct >= 0.05`
- `volume_ratio_5 >= 1.45`
- `volume_ratio_20 >= 1.70`
- `close_pos >= 0.60`
- `close > ma_20`
- positive `net_flow_proxy`

3. Implement setup B rule set from the latest approved thresholds using repository-available fields:
- `volume_ratio_5 >= 3.0`
- `volume_ratio_20 >= 1.70`
- `close_pos >= 0.50`
- positive `net_flow_proxy`
- `close > ma_20`
- `rsi_14 >= 45`
- `macd_histogram > 0`
- `close / ma_60 - 1 >= -0.03`

4. Keep candidate output compatible with the current contract shape:
- return a list of dictionaries with `stock`, `date`, `reason`, and `indicators`.
- include `setup_a` / `setup_b` booleans in `reason`.
- include the specific threshold checks used by the selected candidate in `reason`.
- include derived feature values in `indicators` for QA and debugging.

5. Keep momentum filters aligned with the approved signal formulas:
- do not gate selection on MACD crossovers.
- do not use RSI overbought logic such as `RSI > 60/70`; use the explicit `rsi_14 >= 45` anchor filter instead.
- do not use negative-news filtering as a required pass/fail input for this implementation.

6. Make tests deterministic:
- mock `get_daily_data` with crafted histories for setup A pass, setup B pass, and fail cases.
- assert the strategy identifies the correct setup and exposes expected derived indicator fields.

## Acceptance Criteria

- A stock with `sig_explosive` characteristics is selected.
- A stock with `sig_anchor` characteristics is selected when the RSI, MACD histogram, and MA60-distance filters are present.
- A stock that has abnormal volume but fails the report thresholds is not selected.
- Candidate output still contains `stock`, `date`, `reason`, and `indicators`.
- Candidate `reason` clearly identifies whether setup A or setup B triggered.
- Candidate `indicators` include at least `price_change_pct`, `close_pos`, `volume_ratio_5`, `volume_ratio_20`, `ma_20`, `ma_60`, `rsi_14`, `macd_histogram`, and `net_flow`.
- Tests cover setup A success, setup B success, and rejection behavior.

## Open Questions

- None. Where the report references capital inflow fields unavailable in this repository, the strategy will use the explicit `net_flow_proxy` described above rather than inventing external dependencies.
