# Qizhang Daily Selection CSV Detail

## Overview

Fix daily selection so `qizhang_selection_strategy` is executed by the workflow instead of falling back to `ma_crossover`, and expand CSV output so the selected rows expose detailed threshold, value, and pass/fail criteria fields.

## Scope

- Add a workflow-compatible qizhang strategy adapter under `src/tw_quant/strategy/`.
- Route `strategy_name=qizhang_selection_strategy` to that adapter in the daily selection workflow.
- Emit detailed metadata for qizhang signals so CSV output includes setup name, indicator values, thresholds, and boolean pass/fail checks.
- Daily selection CSV can favor readable columns over duplicated JSON blobs when equivalent flattened fields are present.
- Add or update tests for workflow integration and CSV field content.

## Non-Goals

- No redesign of the selection ranking pipeline.
- No changes to unrelated strategies' selection logic.
- No change to JSON artifact metadata structure.

## Affected Files or Components

- `src/tw_quant/workflows.py`
- `src/tw_quant/strategy/technical/` (new qizhang adapter)
- `tests/test_tw_quant_daily_selection_runtime.py`
- `tests/test_tw_quant_live_workflows_contracts.py`

## Implementation Steps

1. Add a qizhang workflow strategy implementation that:
- consumes `OHLCVBar` history by symbol,
- computes the same qizhang features used in the approved selection logic,
- emits `SignalRecord` objects with `buy` when either approved setup matches.

2. Add detailed qizhang metadata to each buy signal:
- base identity fields such as `strategy`, `indicator`, `selected_setup`,
- actual values such as `price_change_pct`, `volume_ratio_5`, `volume_ratio_20`, `close_pos`, `ma_20`, `ma_60`, `rsi_14`, `macd_histogram`, `close_vs_ma60`, `net_flow`,
- threshold fields such as `threshold_price_change_pct_min`, `threshold_volume_ratio_5_min`, and similar,
- pass/fail fields such as `check_price_change_pct`, `check_volume_ratio_5`, and similar.

3. Route workflow builds correctly:
- `_build_strategy(...)` must recognize `qizhang_selection_strategy`,
- the fallback `ma_crossover` branch must no longer handle qizhang requests.

4. Preserve CSV usability:
- JSON artifacts keep full `criteria` metadata,
- daily selection CSV removes the duplicated `criteria_json` column,
- daily selection CSV includes `stock_name`,
- flattened `criteria_*` columns include the new qizhang details,
- daily selection CSV writes all passed `buy` signals instead of only top-N `selections`,
- CSV rows include whether a signal was selected plus rank and weight when available.

## Acceptance Criteria

- Running daily selection with `--strategy qizhang_selection_strategy` no longer emits `indicator=ma_crossover`.
- Daily selection CSV for qizhang includes `criteria_selected_setup`.
- Daily selection CSV for qizhang includes threshold columns and actual value columns for the selected setup.
- Daily selection CSV for qizhang includes boolean pass/fail check columns.
- Daily selection CSV omits `criteria_json`.
- Daily selection CSV includes `stock_name`.
- Daily selection CSV includes symbols that passed signal generation even when they were excluded from final top-N `selections`.
- Existing non-qizhang strategies still write flattened `criteria_*` columns as before.
- Added tests pass.

## Open Questions

- None.
