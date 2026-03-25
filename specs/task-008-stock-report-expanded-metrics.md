# Stock Report Expanded Metrics

## Overview

Expand `stock-report` so it outputs substantially more analysis context across technical state, strategy state, volume/price action, chip/flow proxies, and report-level metadata.

## Scope

- Extend the existing `build_stock_report()` row payload.
- Extend the stock-report CSV export column set.
- Keep the existing command shape (`stock-report --symbol --start --end`) unchanged.
- Reuse existing repo utilities and strategy logic where practical.

## Non-Goals

- No new external data providers.
- No change to selection or backtest runtime behavior.
- No requirement to expose every internal strategy threshold as a top-level report field unless it is already derived from existing logic.

## Added Report-Level Metadata

Add these top-level fields to the JSON output:

- `requested_window_days`
- `latest_close`
- `latest_volume`
- `period_return_pct`
- `latest_qizhang_signal`
- `latest_qizhang_selected_setup`

## Added Row-Level Fields

### Technical expansion

- `close_vs_ma_5`
- `close_vs_ma_10`
- `close_vs_ma_20`
- `close_vs_ma_60`
- `close_position_20d`
- `distance_to_rolling_high_20_pct`
- `distance_to_rolling_low_20_pct`
- `return_5d`
- `return_20d`
- `true_range`
- `atr_14`

### Price / candle / volume action

- `volume_change_pct`
- `candle_body`
- `candle_body_pct`
- `upper_shadow`
- `lower_shadow`
- `intraday_range`
- `intraday_range_pct`

### Strategy analysis snapshot (Qizhang)

- `qizhang_signal`
- `qizhang_score`
- `qizhang_selected_setup`
- `qizhang_sig_anchor`
- `qizhang_sig_explosive`
- `qizhang_close_pos`
- `qizhang_close_vs_ma60`
- `qizhang_net_flow`
- `qizhang_check_sig_explosive_price_change_pct`
- `qizhang_check_sig_explosive_volume_ratio_5`
- `qizhang_check_sig_explosive_volume_ratio_20`
- `qizhang_check_sig_explosive_close_pos`
- `qizhang_check_sig_explosive_close_gt_ma_20`
- `qizhang_check_sig_explosive_net_flow`
- `qizhang_check_sig_anchor_volume_ratio_5`
- `qizhang_check_sig_anchor_volume_ratio_20`
- `qizhang_check_sig_anchor_close_pos`
- `qizhang_check_sig_anchor_close_gt_ma_20`
- `qizhang_check_sig_anchor_net_flow`
- `qizhang_check_sig_anchor_rsi_14`
- `qizhang_check_sig_anchor_macd_histogram`
- `qizhang_check_sig_anchor_close_vs_ma60`

## Implementation Notes

- Qizhang row analysis may reuse `QizhangSignalStrategy` private evaluation logic on the rolling history available up to each row date.
- Newly added row fields must remain present even when values are unavailable; use `null`/empty values consistently with existing report style.
- CSV writers for both direct stock-report export and grouped strategy-improve stock-report export must include the expanded stock-report fields.

## Acceptance Criteria

- `stock-report` JSON includes the new top-level metadata fields.
- Each row includes the expanded technical, candle/volume, and Qizhang analysis fields.
- CSV export includes the new columns in a stable order.
- Existing stock-report behavior remains backward-compatible for previously present fields.
- Tests are updated and pass.
