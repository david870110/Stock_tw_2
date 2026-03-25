# Stock_tw_2

這個 repo 目前主要透過 `python -m src.tw_quant.runner` 執行台股回測、選股、報表與策略優化流程。

## 執行入口

主 CLI：

```powershell
python -m src.tw_quant.runner -h
```

可用子指令：

- `backtest-batch`
- `daily-selection`
- `stock-report`
- `selection-forward-report`
- `strategy-improve-report`

## 可選策略

目前 `--strategy` 明確支援的策略名稱如下：

| 策略名稱 | 可用於 | 說明 |
| --- | --- | --- |
| `pullback_trend_compression` | `backtest-batch`, `daily-selection` | 拉回趨勢壓縮策略 |
| `pullback` | `backtest-batch`, `daily-selection` | `pullback_trend_compression` 的 alias |
| `pullback_trend_120d_optimized` | `backtest-batch`, `daily-selection` | 120 日優化版 pullback 策略 |
| `pullback_120d_optimized` | `backtest-batch`, `daily-selection` | `pullback_trend_120d_optimized` 的 alias |
| `pullback_optimized` | `backtest-batch`, `daily-selection` | `pullback_trend_120d_optimized` 的 alias |
| `qizhang_selection_strategy` | `backtest-batch`, `daily-selection`, `strategy-improve-report` | 漲停選股策略 |
| `ma_bullish_stack` | `backtest-batch`, `daily-selection` | 均線多頭排列策略 |
| `bullish_stack` | `backtest-batch`, `daily-selection` | `ma_bullish_stack` 的 alias |
| `ma_stack` | `backtest-batch`, `daily-selection` | `ma_bullish_stack` 的 alias |
| `bull_stack` | `backtest-batch`, `daily-selection` | `ma_bullish_stack` 的 alias |
| `ma_crossover` | `backtest-batch`, `daily-selection` | 均線交叉策略 |

補充：

- `strategy-improve-report` 的預設策略是 `qizhang_selection_strategy`。
- `ma_crossover` 沒有額外 alias。
- 程式目前對未識別的策略字串會 fallback 成 `ma_crossover`；文件建議仍只使用上表名稱，避免誤判。

## 指令總覽

### 1. 回測 `backtest-batch`

用途：對一批股票在指定區間做 deterministic batch backtest。

基本範例：

```powershell
python -m src.tw_quant.runner backtest-batch `
  --symbols 2330.TW 2317.TW `
  --start 2024-01-01 `
  --end 2024-12-31 `
  --strategy pullback_trend_120d_optimized
```

或使用股票清單檔：

```powershell
python -m src.tw_quant.runner backtest-batch `
  --symbols-file scripts\all_symbols.txt `
  --start 2024-01-01 `
  --end 2024-12-31 `
  --strategy qizhang_selection_strategy
```

參數：

| 參數 | 必填 | 說明 |
| --- | --- | --- |
| `--symbols SYMBOLS [SYMBOLS ...]` | 與 `--symbols-file` 二選一 | 直接指定股票代碼清單 |
| `--symbols-file SYMBOLS_FILE` | 與 `--symbols` 二選一 | newline-delimited 股票清單檔 |
| `--start START` | 是 | 起始日，格式 `YYYY-MM-DD` |
| `--end END` | 是 | 結束日，格式 `YYYY-MM-DD` |
| `--strategy STRATEGY` | 否 | 策略名稱，預設 `pullback_trend_compression` |
| `--batch-label BATCH_LABEL` | 否 | 自訂批次標籤；未填時會用策略名 |
| `--params PARAMS` | 否 | 策略參數 JSON 字串 |
| `--show-progress` | 否 | 顯示進度 |
| `--progress-step PROGRESS_STEP` | 否 | 每幾筆 run 顯示一次進度，`0` 代表自動 |

`--params` 常見補充：

- `pullback_trend_120d_optimized` 會讀取巢狀設定區塊，例如 `basic`、`entry`、`liquidity`、`ma`、`pullback`、`volume`、`chip`、`margin`、`borrow`、`atr_pullback`、`price_contraction`、`close_strength`、`short_momentum`、`chip_scoring`、`exit`。
- `ma_bullish_stack` 可用 `short_window`、`mid_window`、`long_window`，也接受簡寫 `short`、`mid`、`long`。
- `ma_crossover` 可用 `short_window`、`long_window`，也接受簡寫 `short`、`long`。
- `pullback_trend_compression` 與 `qizhang_selection_strategy` 沒有額外從 CLI 解析的自訂參數結構。

### 2. 選股 `daily-selection`

用途：做單日或日期區間的選股輸出。

單日範例：

```powershell
python -m src.tw_quant.runner daily-selection `
  --as-of 2026-03-20 `
  --strategy qizhang_selection_strategy `
  --show-progress
```

日期區間範例：

```powershell
python -m src.tw_quant.runner daily-selection `
  --start 2026-03-01 `
  --end 2026-03-20 `
  --strategy pullback_trend_120d_optimized `
  --output-csv reports\selection_range.csv
```

參數：

| 參數 | 必填 | 說明 |
| --- | --- | --- |
| `--as-of AS_OF` | 與 `--start` 二選一 | 單日選股日期，格式 `YYYY-MM-DD` |
| `--start START` | 與 `--as-of` 二選一 | 區間起始日，格式 `YYYY-MM-DD` |
| `--end END` | 條件必填 | 使用 `--start` 時必填，區間結束日 |
| `--strategy STRATEGY` | 否 | 策略名稱，預設 `pullback_trend_compression` |
| `--output-csv OUTPUT_CSV` | 否 | 日期區間彙整 CSV 輸出路徑 |
| `--workers WORKERS` | 否 | 每日股票評估平行 worker 數，預設 `1` |
| `--show-progress` | 否 | 顯示執行進度 |
| `--missing-history-threshold MISSING_HISTORY_THRESHOLD` | 否 | `missing_history_count / universe_size` 超過門檻就失敗；負值表示停用 |
| `--top-n TOP_N` | 否 | 輸出前 N 名，預設 `30` |
| `--max-symbols MAX_SYMBOLS` | 否 | 限制最多評估幾檔股票 |
| `--symbols SYMBOLS [SYMBOLS ...]` | 否 | 只跑指定股票，避免全市場抓取 |

### 3. 單股報表 `stock-report`

用途：輸出單一股票在指定區間的明細報表。

範例：

```powershell
python -m src.tw_quant.runner stock-report `
  --symbol 2330.TW `
  --start 2025-01-01 `
  --end 2025-03-31 `
  --output-csv reports\2330_q1.csv
```

參數：

| 參數 | 必填 | 說明 |
| --- | --- | --- |
| `--symbol SYMBOL` | 是 | 股票代碼，例如 `2330` 或 `2330.TW` |
| `--start START` | 是 | 起始日，格式 `YYYY-MM-DD` |
| `--end END` | 是 | 結束日，格式 `YYYY-MM-DD` |
| `--output-csv OUTPUT_CSV` | 否 | row-level CSV 輸出路徑 |

### 4. 選股後續追蹤 `selection-forward-report`

用途：讀取 `daily-selection` 產生的 CSV，往後推算指定天數或月數的收盤與報酬。

天數範例：

```powershell
python -m src.tw_quant.runner selection-forward-report `
  --selection-csv artifacts\tw_quant\daily_selection\2026-02-23\qizhang_selection_strategy.csv `
  --forward-days 20
```

月數範例：

```powershell
python -m src.tw_quant.runner selection-forward-report `
  --selection-csv artifacts\tw_quant\daily_selection\2026-02-11\qizhang_selection_strategy.csv `
  --forward-months 1 `
  --output-csv reports\qizhang_forward_1m.csv
```

參數：

| 參數 | 必填 | 說明 |
| --- | --- | --- |
| `--selection-csv SELECTION_CSV` | 是 | `daily-selection` 產生的 CSV 路徑 |
| `--forward-months FORWARD_MONTHS` | 與 `--forward-days` 二選一 | 往後推幾個月 |
| `--forward-days FORWARD_DAYS` | 與 `--forward-months` 二選一 | 往後推幾天 |
| `--output-csv OUTPUT_CSV` | 否 | row-level CSV 輸出路徑 |

### 5. 策略優化 `strategy-improve-report`

用途：針對策略做抽樣年度/月度分析、forward returns、bucket 分組與 stock reports。

範例：

```powershell
python -m src.tw_quant.runner strategy-improve-report `
  --strategy qizhang_selection_strategy `
  --years 5 `
  --sample-start-year 2018 `
  --sample-end-year 2025 `
  --months-per-year 4 `
  --sample-seed 42 `
  --workers 20 `
  --show-progress
```

參數：

| 參數 | 必填 | 說明 |
| --- | --- | --- |
| `--strategy STRATEGY` | 否 | 策略名稱，預設 `qizhang_selection_strategy` |
| `--years YEARS` | 否 | 抽樣幾個 calendar years，預設 `5` |
| `--sample-start-year SAMPLE_START_YEAR` | 否 | 抽樣池最早年份，預設 `2014` |
| `--months-per-year MONTHS_PER_YEAR` | 否 | 每年抽幾個不重複月份，預設 `5` |
| `--sample-end-year SAMPLE_END_YEAR` | 否 | 抽樣池最晚年份；未填時為前一個 calendar year |
| `--sample-seed SAMPLE_SEED` | 否 | 固定抽樣亂數種子，預設 `42` |
| `--workers WORKERS` | 否 | Step0 selection 平行 worker 數，預設 `20` |
| `--show-progress` | 否 | 顯示 tqdm progress bar |
| `--missing-history-threshold MISSING_HISTORY_THRESHOLD` | 否 | 歷史資料缺漏容忍門檻；負值表示停用 |
| `--top-n TOP_N` | 否 | 相容保留參數，預設 `30`；forward evaluation 目前用所有買進訊號 |
| `--max-symbols MAX_SYMBOLS` | 否 | 限制最多評估幾檔股票 |
| `--symbols SYMBOLS [SYMBOLS ...]` | 否 | 只跑指定股票 |
| `--output-root OUTPUT_ROOT` | 否 | 輸出根目錄，預設 `artifacts\Stratage_improve` |

## PowerShell 輔助腳本

除了主 CLI，repo 內也有幾個方便執行大量回測的 PowerShell 腳本。

### `scripts\run_pullback_backtest_all.ps1`

用途：建立上市櫃股票 universe 後，對全部股票做單批次回測。

範例：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_pullback_backtest_all.ps1 `
  -Start 2016-02-01 `
  -End 2022-10-31 `
  -StrategyName pullback_trend_120d_optimized `
  -MaxSymbols 100 `
  -ProgressStepSymbols 1
```

主要參數：

- `-Start`
- `-End`
- `-StrategyName`
- `-BatchLabel`
- `-ChunkSize`
- `-MaxRetries`
- `-UniverseBuildRetries`
- `-UniverseRetryDelaySeconds`
- `-MaxSymbols`
- `-AllowCacheFallback`
- `-PythonExe`
- `-BacktestParams`
- `-AtrStopMult`
- `-ProfitProtectTrigger`
- `-ProfitProtectPullback`
- `-ProfitProtectionMode`
- `-EnableAtrTrailingProfitProtection`
- `-ProfitProtectionAtrPeriod`
- `-ProfitProtectionAtrTrailMult`
- `-TrendBreakBelowMa60Days`
- `-MaxHoldingDays`
- `-EntrySemanticsMode`
- `-SetupOffsetBars`
- `-CooldownApplyOn`
- `-RiskBudgetPct`
- `-StopDistanceMode`
- `-FallbackPositionCash`
- `-TriggerVolumeRatioWarnMax`
- `-TriggerVolumeHardBlock`
- `-DisableMaxHoldingDays`
- `-RandomMode`
- `-ProgressStepSymbols`

### `scripts\run_single_strategy_chunk_parallel.ps1`

用途：把股票池切 chunk，平行執行多個 `backtest-batch`。

範例：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_single_strategy_chunk_parallel.ps1 `
  -StrategyName pullback_trend_120d_optimized `
  -MaxParallel 6 `
  -ChunkSize 30 `
  -MaxSymbols 300
```

主要參數：

- `-Start`
- `-End`
- `-StrategyName`
- `-BatchLabelPrefix`
- `-MaxParallel`
- `-ChunkSize`
- `-MaxSymbols`
- `-PythonExe`
- `-BacktestParams`
- `-AtrStopMult`
- `-ProfitProtectTrigger`
- `-ProfitProtectPullback`
- `-ProfitProtectionMode`
- `-EnableAtrTrailingProfitProtection`
- `-ProfitProtectionAtrPeriod`
- `-ProfitProtectionAtrTrailMult`
- `-TrendBreakBelowMa60Days`
- `-MaxHoldingDays`
- `-EntrySemanticsMode`
- `-SetupOffsetBars`
- `-CooldownApplyOn`
- `-RiskBudgetPct`
- `-StopDistanceMode`
- `-FallbackPositionCash`
- `-TriggerVolumeRatioWarnMax`
- `-TriggerVolumeHardBlock`
- `-DisableMaxHoldingDays`
- `-RandomMode`
- `-ProgressStepSymbols`
- `-DryRun`

### `scripts\run_pullback_6_parallel.ps1`

用途：一次平行啟動多組 pullback 參數組合，底層會呼叫 `run_pullback_backtest_all.ps1`。

範例：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_pullback_6_parallel.ps1 `
  -MaxParallel 6
```

參數：

| 參數 | 必填 | 說明 |
| --- | --- | --- |
| `-MaxParallel` | 否 | 同時最多平行幾組 case，預設 `6` |
| `-DryRun` | 否 | 只列出即將執行的 case，不真正啟動 |

## 常用 help 指令

```powershell
python -m src.tw_quant.runner -h
python -m src.tw_quant.runner backtest-batch -h
python -m src.tw_quant.runner daily-selection -h
python -m src.tw_quant.runner stock-report -h
python -m src.tw_quant.runner selection-forward-report -h
python -m src.tw_quant.runner strategy-improve-report -h
```
