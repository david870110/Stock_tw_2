param(
    [string]$Start = "2016-02-01",
    [string]$End = "2022-10-31",
    [string]$StrategyName = "pullback_trend_120d_optimized",
    [string]$BatchLabelPrefix = "",
    [int]$MaxParallel = 6,
    [int]$ChunkSize = 30,
    [int]$MaxSymbols = 0,
    [string]$PythonExe = "python",
    [string]$BacktestParams = "",
    [double]$AtrStopMult = 2.5,
    [double]$ProfitProtectTrigger = 0.25,
    [double]$ProfitProtectPullback = 0.18,
    [string]$ProfitProtectionMode = "percent_drawdown",
    [switch]$EnableAtrTrailingProfitProtection,
    [int]$ProfitProtectionAtrPeriod = 14,
    [double]$ProfitProtectionAtrTrailMult = 2.0,
    [int]$TrendBreakBelowMa60Days = 3,
    [int]$MaxHoldingDays = 140,
    [string]$EntrySemanticsMode = "setup_trigger",
    [int]$SetupOffsetBars = 1,
    [string]$CooldownApplyOn = "any_exit",
    [double]$RiskBudgetPct = 0.0,
    [string]$StopDistanceMode = "atr_initial_stop",
    [double]$FallbackPositionCash = 100000,
    [double]$TriggerVolumeRatioWarnMax = 1.2,
    [switch]$TriggerVolumeHardBlock,
    [switch]$DisableMaxHoldingDays,
    [switch]$RandomMode,
    [int]$ProgressStepSymbols = 0,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

if ($MaxParallel -lt 1) { throw "MaxParallel must be >= 1" }
if ($ChunkSize -lt 1) { throw "ChunkSize must be >= 1" }

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
$symbolsPath = Join-Path $scriptDir "all_symbols.txt"

function Get-EffectiveBacktestParams {
    param(
        [string]$RawParams,
        [double]$AtrStop,
        [double]$ProtectTrigger,
        [double]$ProtectPullback,
        [string]$ProtectMode,
        [bool]$EnableAtrTrailingProtect,
        [int]$ProtectAtrPeriod,
        [double]$ProtectAtrTrailMult,
        [int]$TrendBreakDays,
        [int]$HoldingDays,
        [bool]$RemoveHoldingDays,
        [string]$EntryMode,
        [int]$EntrySetupOffsetBars,
        [string]$EntryCooldownApplyOn,
        [double]$EntryRiskBudgetPct,
        [string]$EntryStopDistanceMode,
        [double]$EntryFallbackPositionCash,
        [double]$VolumeTriggerWarnRatioMax,
        [bool]$VolumeTriggerHardBlock
    )

    if ($RawParams -and $RawParams.Trim()) {
        return $RawParams.Trim()
    }

    $params = [ordered]@{
        basic = [ordered]@{
            min_bars = 200
        }
        liquidity = [ordered]@{
            liquidity_amt_ma20_min = 10000000
            min_price_enabled = $false
            min_price = 10.0
        }
        ma = [ordered]@{
            ma_short = 20
            ma20_slope_lookback = 5
            ma_fast = 60
            ma_mid = 120
            ma_slow = 200
            slope_lookback = 20
        }
        pullback = [ordered]@{
            high_lookback = 80
            drawdown_min = 0.08
            drawdown_max = 0.22
            ma60_dist_min = -0.05
            ma60_dist_max = 0.08
        }
        volume = [ordered]@{
            volume_short_ma = 10
            volume_long_ma = 20
            volume_contract_enabled = $true
            volume_contract_ratio_max = 1.0
            setup_volume_contract_enabled = $true
            setup_volume_contract_ratio_max = 1.0
            trigger_volume_check_enabled = $true
            trigger_volume_ratio_warn_max = $VolumeTriggerWarnRatioMax
            trigger_volume_hard_block = $VolumeTriggerHardBlock
        }
        chip = [ordered]@{
            enable_chip_filter = $false
            enable_foreign_buy_filter = $false
            enable_investment_trust_filter = $false
            chip_lookback = 20
        }
        margin = [ordered]@{
            enable_margin_filter = $false
            margin_lookback = 20
            margin_growth_limit = 0.15
        }
        borrow = [ordered]@{
            enable_borrow_filter = $false
            borrow_lookback = 20
            borrow_balance_growth_limit = 0.15
        }
        atr_pullback = [ordered]@{
            atr_period = 14
            atr_drawdown_min = 1.0
            atr_drawdown_max = 4.0
        }
        breakout = [ordered]@{
            breakout_enabled = $true
            breakout_lookback = 20
            breakout_strength_min = 0.0
        }
        entry = [ordered]@{
            entry_semantics_mode = $EntryMode
            setup_offset_bars = $EntrySetupOffsetBars
            cooldown_apply_on = $EntryCooldownApplyOn
            risk_budget_pct = $EntryRiskBudgetPct
            stop_distance_mode = $EntryStopDistanceMode
            fallback_position_cash = $EntryFallbackPositionCash
        }
        exit = [ordered]@{
            atr_stop_mult = $AtrStop
            trend_break_exit = [ordered]@{
                enable = $true
                trend_break_below_ma60_days = $TrendBreakDays
            }
            profit_protection = [ordered]@{
                enable = $true
                mode = $ProtectMode
                profit_protect_trigger = $ProtectTrigger
                profit_protect_pullback = $ProtectPullback
                enable_atr_trailing_profit_protection = $EnableAtrTrailingProtect
                atr_period = $ProtectAtrPeriod
                atr_trail_mult = $ProtectAtrTrailMult
            }
            enable_max_holding_days = (-not $RemoveHoldingDays)
            max_holding_days = $HoldingDays
        }
    }

    return ($params | ConvertTo-Json -Depth 20 -Compress)
}

if (-not (Test-Path $symbolsPath)) {
    throw "Symbols file not found: $symbolsPath"
}

$symbols = Get-Content $symbolsPath | Where-Object { $_ -and $_.Trim() } | ForEach-Object { $_.Trim() }
if (-not $symbols -or $symbols.Count -eq 0) {
    throw "No symbols found in $symbolsPath"
}

if ($RandomMode.IsPresent) {
    Write-Host "Applying random symbol order..."
    $symbols = $symbols | Sort-Object { Get-Random }
}

if ($MaxSymbols -gt 0 -and $symbols.Count -gt $MaxSymbols) {
    $symbols = $symbols[0..($MaxSymbols - 1)]
}

$effectiveBacktestParams = Get-EffectiveBacktestParams `
    -RawParams $BacktestParams `
    -AtrStop $AtrStopMult `
    -ProtectTrigger $ProfitProtectTrigger `
    -ProtectPullback $ProfitProtectPullback `
    -ProtectMode $ProfitProtectionMode `
    -EnableAtrTrailingProtect $EnableAtrTrailingProfitProtection.IsPresent `
    -ProtectAtrPeriod $ProfitProtectionAtrPeriod `
    -ProtectAtrTrailMult $ProfitProtectionAtrTrailMult `
    -TrendBreakDays $TrendBreakBelowMa60Days `
    -HoldingDays $MaxHoldingDays `
    -RemoveHoldingDays $DisableMaxHoldingDays.IsPresent `
    -EntryMode $EntrySemanticsMode `
    -EntrySetupOffsetBars $SetupOffsetBars `
    -EntryCooldownApplyOn $CooldownApplyOn `
    -EntryRiskBudgetPct $RiskBudgetPct `
    -EntryStopDistanceMode $StopDistanceMode `
    -EntryFallbackPositionCash $FallbackPositionCash `
    -VolumeTriggerWarnRatioMax $TriggerVolumeRatioWarnMax `
    -VolumeTriggerHardBlock $TriggerVolumeHardBlock.IsPresent

$effectiveProgressStep = if ($ProgressStepSymbols -gt 0) {
    [Math]::Max(1, [int]$ProgressStepSymbols)
}
else {
    [Math]::Max(1, [int][Math]::Ceiling($ChunkSize / 20.0))
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$baseLabel = if ($BatchLabelPrefix -and $BatchLabelPrefix.Trim()) { $BatchLabelPrefix.Trim() } else { "${StrategyName}_${stamp}" }
$runDir = Join-Path $scriptDir ("parallel_chunks\run_" + $stamp)
$chunkDir = Join-Path $runDir "chunks"
$logDir = Join-Path $runDir "logs"
New-Item -ItemType Directory -Path $chunkDir -Force | Out-Null
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

$chunks = @()
for ($i = 0; $i -lt $symbols.Count; $i += $ChunkSize) {
    $endIndex = [Math]::Min($i + $ChunkSize - 1, $symbols.Count - 1)
    $chunks += ,@($symbols[$i..$endIndex])
}

Write-Host "Total symbols   : $($symbols.Count)"
Write-Host "Chunk size      : $ChunkSize"
Write-Host "Chunk count     : $($chunks.Count)"
Write-Host "Max parallel    : $MaxParallel"
Write-Host "Run folder      : $runDir"

if ($DryRun.IsPresent) {
    for ($idx = 0; $idx -lt $chunks.Count; $idx++) {
        $chunkNo = $idx + 1
        $chunkLabel = "${baseLabel}_chunk{0:D3}" -f $chunkNo
        Write-Host ("DRY - chunk {0}/{1}: symbols={2}, batch_label={3}" -f $chunkNo, $chunks.Count, $chunks[$idx].Count, $chunkLabel)
    }
    exit 0
}

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$results = New-Object System.Collections.Generic.List[object]

for ($idx = 0; $idx -lt $chunks.Count; $idx++) {
    while ($true) {
        $runningJobs = @(Get-Job -State Running -ErrorAction SilentlyContinue)
        if ($runningJobs.Count -lt $MaxParallel) { break }

        $finished = Wait-Job -Job $runningJobs -Any -Timeout 5
        if ($null -eq $finished) { continue }
        $out = Receive-Job -Job $finished -Keep -ErrorAction SilentlyContinue
        if ($out) {
            foreach ($item in $out) { [void]$results.Add($item) }
        }
        Remove-Job -Job $finished -Force
    }

    $chunkNo = $idx + 1
    $chunkName = "chunk{0:D3}" -f $chunkNo
    $chunkSymbols = $chunks[$idx]
    $chunkSymbolsPath = Join-Path $chunkDir ("${chunkName}_symbols.txt")
    [System.IO.File]::WriteAllText($chunkSymbolsPath, ($chunkSymbols -join "`n"), $utf8NoBom)
    $chunkLabel = "${baseLabel}_${chunkName}"
    $jobName = "run_${chunkName}"

    $jobArgs = @(
        $PythonExe,
        $repoRoot,
        $chunkSymbolsPath,
        $Start,
        $End,
        $StrategyName,
        $effectiveBacktestParams,
        $effectiveProgressStep,
        $chunkLabel,
        $logDir,
        $jobName,
        $chunkSymbols.Count
    )

    Start-Job -Name $jobName -ArgumentList $jobArgs -ScriptBlock {
        param(
            [string]$Py,
            [string]$Root,
            [string]$SymbolsFile,
            [string]$StartDate,
            [string]$EndDate,
            [string]$Strat,
            [string]$ParamsJson,
            [int]$ProgressStep,
            [string]$Label,
            [string]$Logs,
            [string]$Name,
            [int]$SymbolCount
        )

        $ErrorActionPreference = "Continue"
        $logPath = Join-Path $Logs ("$Name.log")
        $startAt = Get-Date
        "[$($startAt.ToString('s'))] START $Name symbols=$SymbolCount label=$Label" | Out-File -FilePath $logPath -Encoding utf8 -Append

        try {
            Push-Location $Root
            try {
                $args = @(
                    "-m", "src.tw_quant.runner", "backtest-batch",
                    "--symbols-file", $SymbolsFile,
                    "--start", $StartDate,
                    "--end", $EndDate,
                    "--strategy", $Strat,
                    "--params", $ParamsJson,
                    "--show-progress",
                    "--progress-step", "$ProgressStep",
                    "--batch-label", $Label
                )

                & $Py @args *>&1 | Tee-Object -FilePath $logPath -Append | Out-Null
                $exitCode = $LASTEXITCODE
                if ($null -eq $exitCode) { $exitCode = 0 }
            }
            finally {
                Pop-Location
            }
        }
        catch {
            $_ | Out-String | Out-File -FilePath $logPath -Encoding utf8 -Append
            $exitCode = 999
        }

        $endAt = Get-Date
        $status = if ($exitCode -eq 0) { "SUCCESS" } else { "FAILED" }
        "[$($endAt.ToString('s'))] END $Name exit=$exitCode status=$status" | Out-File -FilePath $logPath -Encoding utf8 -Append

        [pscustomobject]@{
            Chunk = $Name
            Symbols = [int]$SymbolCount
            BatchLabel = $Label
            Status = $status
            ExitCode = [int]$exitCode
            LogPath = $logPath
            StartedAt = $startAt
            EndedAt = $endAt
        }
    } | Out-Null
}

$allJobs = @(Get-Job -ErrorAction SilentlyContinue)
if ($allJobs.Count -gt 0) {
    Wait-Job -Job $allJobs | Out-Null
}

foreach ($job in @(Get-Job -ErrorAction SilentlyContinue)) {
    $out = Receive-Job -Job $job -Keep -ErrorAction SilentlyContinue
    if ($out) {
        foreach ($item in $out) { [void]$results.Add($item) }
    }
    Remove-Job -Job $job -Force
}

$summaryPath = Join-Path $runDir "chunk_summary.csv"
$results |
    Sort-Object Chunk |
    Select-Object Chunk, Symbols, BatchLabel, Status, ExitCode, StartedAt, EndedAt, LogPath |
    Export-Csv -Path $summaryPath -NoTypeInformation -Encoding utf8

$batchRoot = Join-Path $repoRoot "artifacts\tw_quant\batch"
$kpiSummaryPath = Join-Path $runDir "chunk_kpi_summary.csv"
$kpiRows = New-Object System.Collections.Generic.List[object]

foreach ($row in ($results | Sort-Object Chunk)) {
    $batchId = ""
    $backtestSummaryPath = ""
    $totalReturn = $null
    $benchReturn = $null
    $endEquity = $null
    $stocksUsed = $null
    $universeSize = $null
    $readError = ""

    if ($row.Status -eq "SUCCESS" -and $row.LogPath -and (Test-Path $row.LogPath)) {
        try {
            $batchMatch = Select-String -Path $row.LogPath -Pattern '"batch_id"\s*:\s*"([^"]+)"' -AllMatches -ErrorAction Stop |
                Select-Object -Last 1
            if ($batchMatch -and $batchMatch.Matches.Count -gt 0) {
                $batchId = [string]$batchMatch.Matches[0].Groups[1].Value
            }

            if ($batchId) {
                $backtestSummaryPath = Join-Path $batchRoot (Join-Path $batchId "backtest_summary.csv")
                if (Test-Path $backtestSummaryPath) {
                    $summaryRow = Import-Csv -Path $backtestSummaryPath | Select-Object -First 1
                    if ($summaryRow) {
                        $totalReturn = $summaryRow.total_return
                        $benchReturn = $summaryRow.bench_return
                        $endEquity = $summaryRow.end_equity
                        $stocksUsed = $summaryRow.stocks_used
                        $universeSize = $summaryRow.universe_size
                    }
                }
                else {
                    $readError = "backtest_summary_not_found"
                }
            }
            else {
                $readError = "batch_id_not_found_in_log"
            }
        }
        catch {
            $readError = "summary_parse_error"
        }
    }
    elseif ($row.Status -ne "SUCCESS") {
        $readError = "chunk_failed"
    }

    [void]$kpiRows.Add([pscustomobject]@{
        Chunk = $row.Chunk
        Symbols = $row.Symbols
        BatchLabel = $row.BatchLabel
        Status = $row.Status
        ExitCode = $row.ExitCode
        BatchId = $batchId
        TotalReturn = $totalReturn
        BenchReturn = $benchReturn
        EndEquity = $endEquity
        StocksUsed = $stocksUsed
        UniverseSize = $universeSize
        BacktestSummaryPath = $backtestSummaryPath
        LogPath = $row.LogPath
        ReadError = $readError
    })
}

$successRows = @($kpiRows | Where-Object { $_.Status -eq "SUCCESS" })

$totalReturnValues = New-Object System.Collections.Generic.List[double]
$benchReturnValues = New-Object System.Collections.Generic.List[double]

foreach ($item in $successRows) {
    $totalParsed = 0.0
    if ($null -ne $item.TotalReturn -and [double]::TryParse([string]$item.TotalReturn, [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$totalParsed)) {
        [void]$totalReturnValues.Add($totalParsed)
    }
    elseif ($null -ne $item.TotalReturn -and [double]::TryParse([string]$item.TotalReturn, [ref]$totalParsed)) {
        [void]$totalReturnValues.Add($totalParsed)
    }

    $benchParsed = 0.0
    if ($null -ne $item.BenchReturn -and [double]::TryParse([string]$item.BenchReturn, [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$benchParsed)) {
        [void]$benchReturnValues.Add($benchParsed)
    }
    elseif ($null -ne $item.BenchReturn -and [double]::TryParse([string]$item.BenchReturn, [ref]$benchParsed)) {
        [void]$benchReturnValues.Add($benchParsed)
    }
}

$sumTotalReturn = if ($totalReturnValues.Count -gt 0) { ($totalReturnValues | Measure-Object -Sum).Sum } else { $null }
$avgTotalReturn = if ($totalReturnValues.Count -gt 0) { ($totalReturnValues | Measure-Object -Average).Average } else { $null }
$sumBenchReturn = if ($benchReturnValues.Count -gt 0) { ($benchReturnValues | Measure-Object -Sum).Sum } else { $null }
$avgBenchReturn = if ($benchReturnValues.Count -gt 0) { ($benchReturnValues | Measure-Object -Average).Average } else { $null }

$kpiOutputRows = New-Object System.Collections.Generic.List[object]
foreach ($item in $kpiRows) {
    [void]$kpiOutputRows.Add([pscustomobject]@{
        Chunk = $item.Chunk
        Symbols = $item.Symbols
        BatchLabel = $item.BatchLabel
        Status = $item.Status
        ExitCode = $item.ExitCode
        BatchId = $item.BatchId
        TotalReturn = $item.TotalReturn
        BenchReturn = $item.BenchReturn
        EndEquity = $item.EndEquity
        StocksUsed = $item.StocksUsed
        UniverseSize = $item.UniverseSize
        BacktestSummaryPath = $item.BacktestSummaryPath
        LogPath = $item.LogPath
        ReadError = $item.ReadError
        TotalChunks = $null
        SuccessChunks = $null
        FailedChunks = $null
        AvgTotalReturn = $null
        SumTotalReturn = $null
        AvgBenchReturn = $null
        SumBenchReturn = $null
    })
}

[void]$kpiOutputRows.Add([pscustomobject]@{
    Chunk = "ALL_CHUNKS_SUMMARY"
    Symbols = ($kpiRows | Measure-Object -Property Symbols -Sum).Sum
    BatchLabel = ""
    Status = "SUMMARY"
    ExitCode = ""
    BatchId = ""
    TotalReturn = $null
    BenchReturn = $null
    EndEquity = $null
    StocksUsed = $null
    UniverseSize = $null
    BacktestSummaryPath = ""
    LogPath = ""
    ReadError = ""
    TotalChunks = $kpiRows.Count
    SuccessChunks = ($kpiRows | Where-Object { $_.Status -eq "SUCCESS" }).Count
    FailedChunks = ($kpiRows | Where-Object { $_.Status -ne "SUCCESS" }).Count
    AvgTotalReturn = if ($null -ne $avgTotalReturn) { [Math]::Round([double]$avgTotalReturn, 8) } else { $null }
    SumTotalReturn = if ($null -ne $sumTotalReturn) { [Math]::Round([double]$sumTotalReturn, 8) } else { $null }
    AvgBenchReturn = if ($null -ne $avgBenchReturn) { [Math]::Round([double]$avgBenchReturn, 8) } else { $null }
    SumBenchReturn = if ($null -ne $sumBenchReturn) { [Math]::Round([double]$sumBenchReturn, 8) } else { $null }
})

$kpiOutputRows | Export-Csv -Path $kpiSummaryPath -NoTypeInformation -Encoding utf8

$ok = ($results | Where-Object { $_.ExitCode -eq 0 }).Count
$fail = ($results | Where-Object { $_.ExitCode -ne 0 }).Count

Write-Host "Completed chunks: success=$ok failed=$fail"
Write-Host "Summary: $summaryPath"
Write-Host "KPI Summary: $kpiSummaryPath"
if ($fail -gt 0) {
    Write-Warning "Some chunks failed. Check chunk_summary.csv and chunk log files."
    exit 1
}

exit 0