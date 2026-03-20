param(
    [string]$Start = "2016-02-01",
    [string]$End = "2022-10-31",
    [string]$StrategyName = "pullback_trend_120d_optimized",
    [string]$BatchLabel = "",
    [int]$ChunkSize = $null,
    [int]$MaxRetries = 10,
    [int]$UniverseBuildRetries = 50,
    [double]$UniverseRetryDelaySeconds = 2.0,
    [int]$MaxSymbols = $null,
    [bool]$AllowCacheFallback = $true,
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
    [int]$ProgressStepSymbols = 0
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
$symbolsPath = Join-Path $scriptDir "all_symbols.txt"
$symbolsMetaPath = Join-Path $scriptDir "all_symbols_meta.json"

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
            use_atr_normalized_pullback = $false
            drawdown_atr_norm_min = 0.5
            drawdown_atr_norm_max = 3.0
            dist_to_ma60_atr_max = 1.5
            atr_period = 14
        }
        price_contraction = [ordered]@{
            price_contract_enabled = $true
            range_short_lookback = 5
            range_long_lookback = 20
            range_contract_ratio_max = 0.7
            range_percentile_max = $null
        }
        close_strength = [ordered]@{
            close_strength_enabled = $true
            close_vs_5d_high_min = 0.95
            close_position_5d_min = $null
        }
        short_momentum = [ordered]@{
            short_momentum_enabled = $true
            short_momentum_lookback = 5
        }
        entry = [ordered]@{
            entry_semantics_mode = $EntryMode
            setup_offset_bars = $EntrySetupOffsetBars
            position_cash = 100000
            reentry_cooldown_days = 30
            cooldown_apply_on = $EntryCooldownApplyOn
            risk_budget_pct = $(if ($EntryRiskBudgetPct -gt 0) { $EntryRiskBudgetPct } else { $null })
            stop_distance_mode = $EntryStopDistanceMode
            fallback_position_cash = $EntryFallbackPositionCash
        }
        chip_scoring = [ordered]@{
            enable_chip_scoring = $false
            foreign_score_weight = 1.0
            investment_trust_score_weight = 1.0
            margin_score_weight = 0.5
            borrow_score_weight = 0.5
            chip_scoring_lookback = 20
        }
        exit = [ordered]@{
            initial_stop_mode = "atr"
            atr_period = 14
            atr_stop_mult = $AtrStop
            trend_break = [ordered]@{
                ma60_window = 60
                ma120_window = 120
                trend_break_below_ma60_days = $TrendBreakDays
            }
            profit_protection = [ordered]@{
                profit_protect_trigger = $ProtectTrigger
                profit_protect_pullback = $ProtectPullback
                mode = $ProtectMode
                atr_trailing_enabled = $EnableAtrTrailingProtect
                atr_period = $ProtectAtrPeriod
                atr_trail_mult = $ProtectAtrTrailMult
            }
            max_hold_days = $(if ($RemoveHoldingDays) { $null } else { $HoldingDays })
        }
    }

    return ($params | ConvertTo-Json -Depth 10 -Compress)
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

function Show-RunConditions {
    param(
        [string]$Strategy,
        [string]$StartDate,
        [string]$EndDate,
        [int]$Chunk,
        [int]$LimitSymbols,
        [bool]$RandomEnabled,
        [int]$ProgressStep,
        [string]$ParamsJson
    )

    $paramsObj = $null
    try {
        $paramsObj = $ParamsJson | ConvertFrom-Json
    }
    catch {
        $paramsObj = $null
    }

    function Get-NestedValue {
        param(
            [object]$Obj,
            [string[]]$Path,
            [object]$Default
        )

        $current = $Obj
        foreach ($key in $Path) {
            if ($null -eq $current) { return $Default }

            if ($current -is [System.Collections.IDictionary]) {
                if (-not $current.Contains($key)) { return $Default }
                $current = $current[$key]
                continue
            }

            $prop = $current.PSObject.Properties[$key]
            if ($null -eq $prop) { return $Default }
            $current = $prop.Value
        }

        if ($null -eq $current) { return $Default }
        return $current
    }

    $conditionLines = New-Object System.Collections.Generic.List[string]

    $minBars = Get-NestedValue -Obj $paramsObj -Path @("basic", "min_bars") -Default 200
    $amtMa20Min = Get-NestedValue -Obj $paramsObj -Path @("liquidity", "liquidity_amt_ma20_min") -Default 30000000
    $minPriceEnabled = [bool](Get-NestedValue -Obj $paramsObj -Path @("liquidity", "min_price_enabled") -Default $false)
    $minPrice = Get-NestedValue -Obj $paramsObj -Path @("liquidity", "min_price") -Default 10.0

    $maShort = Get-NestedValue -Obj $paramsObj -Path @("ma", "ma_short") -Default 20
    $maFast = Get-NestedValue -Obj $paramsObj -Path @("ma", "ma_fast") -Default 60
    $maMid = Get-NestedValue -Obj $paramsObj -Path @("ma", "ma_mid") -Default 120
    $maSlow = Get-NestedValue -Obj $paramsObj -Path @("ma", "ma_slow") -Default 200
    $maSlopeLookback = Get-NestedValue -Obj $paramsObj -Path @("ma", "slope_lookback") -Default 20
    $ma20SlopeLookback = Get-NestedValue -Obj $paramsObj -Path @("ma", "ma20_slope_lookback") -Default 5

    $highLookback = Get-NestedValue -Obj $paramsObj -Path @("pullback", "high_lookback") -Default 80
    $drawdownMin = Get-NestedValue -Obj $paramsObj -Path @("pullback", "drawdown_min") -Default 0.08
    $drawdownMax = Get-NestedValue -Obj $paramsObj -Path @("pullback", "drawdown_max") -Default 0.22
    $ma60DistMin = Get-NestedValue -Obj $paramsObj -Path @("pullback", "ma60_dist_min") -Default -0.05
    $ma60DistMax = Get-NestedValue -Obj $paramsObj -Path @("pullback", "ma60_dist_max") -Default 0.08

    $volEnabled = [bool](Get-NestedValue -Obj $paramsObj -Path @("volume", "volume_contract_enabled") -Default $true)
    $volShort = Get-NestedValue -Obj $paramsObj -Path @("volume", "volume_short_ma") -Default 10
    $volLong = Get-NestedValue -Obj $paramsObj -Path @("volume", "volume_long_ma") -Default 20
    $volRatioMax = Get-NestedValue -Obj $paramsObj -Path @("volume", "volume_contract_ratio_max") -Default 1.0
    $setupVolumeEnabled = [bool](Get-NestedValue -Obj $paramsObj -Path @("volume", "setup_volume_contract_enabled") -Default $true)
    $setupVolumeRatioMax = Get-NestedValue -Obj $paramsObj -Path @("volume", "setup_volume_contract_ratio_max") -Default 1.0
    $triggerVolumeEnabled = [bool](Get-NestedValue -Obj $paramsObj -Path @("volume", "trigger_volume_check_enabled") -Default $true)
    $triggerVolumeWarnMax = Get-NestedValue -Obj $paramsObj -Path @("volume", "trigger_volume_ratio_warn_max") -Default 1.2
    $triggerVolumeHardBlock = [bool](Get-NestedValue -Obj $paramsObj -Path @("volume", "trigger_volume_hard_block") -Default $false)

    $priceContractionEnabled = [bool](Get-NestedValue -Obj $paramsObj -Path @("price_contraction", "price_contract_enabled") -Default $true)
    $rangeShort = Get-NestedValue -Obj $paramsObj -Path @("price_contraction", "range_short_lookback") -Default 5
    $rangeLong = Get-NestedValue -Obj $paramsObj -Path @("price_contraction", "range_long_lookback") -Default 20
    $rangeRatioMax = Get-NestedValue -Obj $paramsObj -Path @("price_contraction", "range_contract_ratio_max") -Default 0.7

    $closeStrengthEnabled = [bool](Get-NestedValue -Obj $paramsObj -Path @("close_strength", "close_strength_enabled") -Default $true)
    $closeVs5dHighMin = Get-NestedValue -Obj $paramsObj -Path @("close_strength", "close_vs_5d_high_min") -Default 0.95
    $closePosition5dMin = Get-NestedValue -Obj $paramsObj -Path @("close_strength", "close_position_5d_min") -Default $null

    $shortMomentumEnabled = [bool](Get-NestedValue -Obj $paramsObj -Path @("short_momentum", "short_momentum_enabled") -Default $true)
    $shortMomentumLookback = Get-NestedValue -Obj $paramsObj -Path @("short_momentum", "short_momentum_lookback") -Default 5

    $positionCash = Get-NestedValue -Obj $paramsObj -Path @("entry", "position_cash") -Default 100000
    $reentryCooldownDays = Get-NestedValue -Obj $paramsObj -Path @("entry", "reentry_cooldown_days") -Default 30
    $entrySemanticsMode = Get-NestedValue -Obj $paramsObj -Path @("entry", "entry_semantics_mode") -Default "legacy"
    $setupOffsetBars = Get-NestedValue -Obj $paramsObj -Path @("entry", "setup_offset_bars") -Default 1
    $cooldownApplyOn = Get-NestedValue -Obj $paramsObj -Path @("entry", "cooldown_apply_on") -Default "any_exit"
    $riskBudgetPct = Get-NestedValue -Obj $paramsObj -Path @("entry", "risk_budget_pct") -Default $null
    $stopDistanceMode = Get-NestedValue -Obj $paramsObj -Path @("entry", "stop_distance_mode") -Default "atr_initial_stop"
    $fallbackPositionCash = Get-NestedValue -Obj $paramsObj -Path @("entry", "fallback_position_cash") -Default 100000

    $atrPullbackEnabled = [bool](Get-NestedValue -Obj $paramsObj -Path @("atr_pullback", "use_atr_normalized_pullback") -Default $false)
    $atrNormMin = Get-NestedValue -Obj $paramsObj -Path @("atr_pullback", "drawdown_atr_norm_min") -Default 0.5
    $atrNormMax = Get-NestedValue -Obj $paramsObj -Path @("atr_pullback", "drawdown_atr_norm_max") -Default 3.0
    $distToMa60AtrMax = Get-NestedValue -Obj $paramsObj -Path @("atr_pullback", "dist_to_ma60_atr_max") -Default 1.5

    $chipFilterEnabled = [bool](Get-NestedValue -Obj $paramsObj -Path @("chip", "enable_chip_filter") -Default $false)
    $marginFilterEnabled = [bool](Get-NestedValue -Obj $paramsObj -Path @("margin", "enable_margin_filter") -Default $false)
    $borrowFilterEnabled = [bool](Get-NestedValue -Obj $paramsObj -Path @("borrow", "enable_borrow_filter") -Default $false)
    $chipScoringEnabled = [bool](Get-NestedValue -Obj $paramsObj -Path @("chip_scoring", "enable_chip_scoring") -Default $false)

    $exitMode = Get-NestedValue -Obj $paramsObj -Path @("exit", "initial_stop_mode") -Default "atr"
    $atrStopMult = Get-NestedValue -Obj $paramsObj -Path @("exit", "atr_stop_mult") -Default 2.5
    $trendBreakDays = Get-NestedValue -Obj $paramsObj -Path @("exit", "trend_break", "trend_break_below_ma60_days") -Default 3
    $profitTrigger = Get-NestedValue -Obj $paramsObj -Path @("exit", "profit_protection", "profit_protect_trigger") -Default 0.25
    $profitPullback = Get-NestedValue -Obj $paramsObj -Path @("exit", "profit_protection", "profit_protect_pullback") -Default 0.18
    $profitMode = Get-NestedValue -Obj $paramsObj -Path @("exit", "profit_protection", "mode") -Default "percent_drawdown"
    $profitAtrTrailingEnabled = [bool](Get-NestedValue -Obj $paramsObj -Path @("exit", "profit_protection", "atr_trailing_enabled") -Default $false)
    $profitAtrPeriod = Get-NestedValue -Obj $paramsObj -Path @("exit", "profit_protection", "atr_period") -Default 14
    $profitAtrTrailMult = Get-NestedValue -Obj $paramsObj -Path @("exit", "profit_protection", "atr_trail_mult") -Default 2.0
    $maxHoldDays = Get-NestedValue -Obj $paramsObj -Path @("exit", "max_hold_days") -Default 140

    $conditionLines.Add("Basic: daily bars, min_bars >= $minBars")
    $minPriceSuffix = ""
    if ($minPriceEnabled) {
        $minPriceSuffix = ", Close >= $minPrice"
    }
    $conditionLines.Add("Liquidity: AmtMA20 >= $amtMa20Min$minPriceSuffix")
    $conditionLines.Add("Trend skeleton: MA$maFast > MA$maMid > MA$maSlow, MA slopes lookback = $maSlopeLookback, Close > MA$maMid")
    $conditionLines.Add("Short trend quality: Close >= MA$maShort, MA$maShort(today) >= MA$maShort(today-$ma20SlopeLookback)")
    $conditionLines.Add("Pullback: high_lookback = $highLookback, drawdown in [$drawdownMin, $drawdownMax], dist_to_MA$maFast in [$ma60DistMin, $ma60DistMax]")
    if ($volEnabled) {
        $conditionLines.Add("Volume contraction: VolMA$volShort < VolMA$volLong, Volume/VolMA$volLong <= $volRatioMax")
        $conditionLines.Add("Setup volume gate: enabled=$setupVolumeEnabled, ratio_max=$setupVolumeRatioMax")
        $conditionLines.Add("Trigger volume gate: enabled=$triggerVolumeEnabled, warn_max=$triggerVolumeWarnMax, hard_block=$triggerVolumeHardBlock")
    }
    if ($priceContractionEnabled) {
        $conditionLines.Add("Price contraction: range_${rangeShort}d <= range_${rangeLong}d * $rangeRatioMax")
    }
    if ($closeStrengthEnabled) {
        $closeStrengthLine = "Close strength: Close/5dHigh >= $closeVs5dHighMin"
        if ($null -ne $closePosition5dMin) {
            $closeStrengthLine += ", close_position_5d >= $closePosition5dMin"
        }
        $conditionLines.Add($closeStrengthLine)
    }
    if ($shortMomentumEnabled) {
        $conditionLines.Add("Short momentum: Close > Close.shift($shortMomentumLookback)")
    }
    $conditionLines.Add("Entry sizing: allocate $positionCash capital per entry")
    $riskBudgetText = if ($null -eq $riskBudgetPct) { "disabled" } else { $riskBudgetPct }
    $conditionLines.Add("Entry semantics: mode=$entrySemanticsMode, setup_offset_bars=$setupOffsetBars")
    $conditionLines.Add("Cooldown apply on: $cooldownApplyOn")
    $conditionLines.Add("Risk budget sizing: risk_budget_pct=$riskBudgetText, stop_distance_mode=$stopDistanceMode, fallback_position_cash=$fallbackPositionCash")
    $conditionLines.Add("Re-entry cooldown: $reentryCooldownDays days")
    if ($atrPullbackEnabled) {
        $conditionLines.Add("ATR pullback enabled: drawdown_atr_norm in [$atrNormMin, $atrNormMax], dist_to_ma60_atr <= $distToMa60AtrMax")
    }
    if ($chipFilterEnabled) {
        $conditionLines.Add("Chip filter enabled")
    }
    if ($marginFilterEnabled) {
        $conditionLines.Add("Margin filter enabled")
    }
    if ($borrowFilterEnabled) {
        $conditionLines.Add("Borrow filter enabled")
    }
    if ($chipScoringEnabled) {
        $conditionLines.Add("Chip scoring enabled")
    }
    $conditionLines.Add("Exit: mode=$exitMode, ATR stop mult=$atrStopMult")
    $conditionLines.Add("Exit trend break: below MA60 for $trendBreakDays days OR below MA120")
    $conditionLines.Add("Exit profit protection: mode=$profitMode, trigger=$profitTrigger, pullback=$profitPullback")
    $conditionLines.Add("Exit ATR trailing protect: enabled=$profitAtrTrailingEnabled, atr_period=$profitAtrPeriod, atr_trail_mult=$profitAtrTrailMult")
    $conditionLines.Add("Exit max hold days: $maxHoldDays")

    Write-Host ""
    Write-Host "================ RUN SETTINGS ================"
    Write-Host "Strategy        : $Strategy"
    Write-Host "Date Range      : $StartDate ~ $EndDate"
    Write-Host "Chunk Size      : $Chunk"
    Write-Host "Max Symbols     : $(if ($LimitSymbols -gt 0) { $LimitSymbols } else { 'ALL' })"
    Write-Host "Random Mode     : $RandomEnabled"
    Write-Host "Progress Step   : $(if ($ProgressStep -gt 0) { "$ProgressStep symbols" } else { 'AUTO (~2%)' })"

    Write-Host "Enabled Conditions:"
    foreach ($line in $conditionLines) {
        Write-Host "- $line"
    }

    Write-Host "=============================================="
    Write-Host ""
}

Show-RunConditions `
    -Strategy $StrategyName `
    -StartDate $Start `
    -EndDate $End `
    -Chunk $ChunkSize `
    -LimitSymbols $MaxSymbols `
    -RandomEnabled $RandomMode.IsPresent `
    -ProgressStep $ProgressStepSymbols `
    -ParamsJson $effectiveBacktestParams

Write-Host "[1/4] Build listed symbol universe..."
$buildSymbolsCode = @'
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.tw_quant.runner import _load_config
from src.tw_quant.wiring.container import build_app_context
from src.tw_quant.universe.models import ListingStatus

if len(sys.argv) < 3:
    raise SystemExit("usage: _build_symbols_tmp.py <symbols_path> <meta_path>")

symbols_path = Path(sys.argv[1])
meta_path = Path(sys.argv[2])

cfg = _load_config()
ctx = build_app_context(cfg)
entries = ctx.universe_provider.get_universe()

def is_stock_equity(entry):
    if entry.listing_status != ListingStatus.LISTED:
        return False
    market = str(getattr(entry, "market", "") or "").strip().lower()
    if market and market != "stock":
        return False
    symbol = str(entry.symbol or "")
    code = symbol.split(".", 1)[0]
    if code.startswith("00"):
        return False
    return True

stock_entries = [e for e in entries if is_stock_equity(e)]
symbols = sorted({e.symbol for e in stock_entries})
twse_count = sum(1 for e in stock_entries if str(e.exchange).upper() == "TWSE")
tpex_count = sum(1 for e in stock_entries if str(e.exchange).upper() == "TPEX")

symbols_path.parent.mkdir(parents=True, exist_ok=True)
symbols_path.write_text(chr(10).join(symbols), encoding="utf-8")

meta = {
    "total": len(symbols),
    "twse_listed": twse_count,
    "tpex_listed": tpex_count,
}
meta_path.parent.mkdir(parents=True, exist_ok=True)
meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
print(json.dumps(meta, ensure_ascii=False))
'@

$tmpPy = Join-Path $scriptDir "_build_symbols_tmp.py"
Set-Content -Path $tmpPy -Value $buildSymbolsCode -Encoding UTF8

function Invoke-BuildUniverse {
    param(
        [string]$Python,
        [string]$TmpScript,
        [string]$OutSymbols,
        [string]$OutMeta
    )

    $output = & $Python $TmpScript $OutSymbols $OutMeta 2>&1
    $exitCode = $LASTEXITCODE
    return @($exitCode, ($output -join "`n"))
}

$buildSucceeded = $false
try {
    for ($attempt = 1; $attempt -le $UniverseBuildRetries; $attempt++) {
        Write-Host " -> Universe fetch attempt #$attempt/$UniverseBuildRetries"
        $result = Invoke-BuildUniverse -Python $PythonExe -TmpScript $tmpPy -OutSymbols $symbolsPath -OutMeta $symbolsMetaPath
        $exitCode = $result[0]
        $stdout = $result[1]

        if ($exitCode -eq 0 -and (Test-Path $symbolsPath)) {
            $meta = $null
            if (Test-Path $symbolsMetaPath) {
                try {
                    $meta = Get-Content $symbolsMetaPath -Raw | ConvertFrom-Json
                }
                catch {
                    $meta = $null
                }
            }

            if ($null -ne $meta) {
                Write-Host "    listed_total=$($meta.total) twse_listed=$($meta.twse_listed) tpex_listed=$($meta.tpex_listed)"
                if ($meta.twse_listed -gt 0 -and $meta.tpex_listed -gt 0) {
                    $buildSucceeded = $true
                    break
                }
                Write-Warning "Universe incomplete (TWSE or TPEX listed count is zero)."
            }
            else {
                Write-Warning "Universe metadata not available; will retry."
            }
        }
        else {
            Write-Warning "Universe build failed on attempt #$attempt"
            if ($stdout) {
                Write-Warning $stdout
            }
        }

        if ($attempt -lt $UniverseBuildRetries) {
            Start-Sleep -Seconds $UniverseRetryDelaySeconds
        }
    }
}
finally {
    if (Test-Path $tmpPy) {
        Remove-Item $tmpPy -Force
    }
}

if (-not $buildSucceeded) {
    if (-not $AllowCacheFallback) {
        throw "Failed to fetch complete universe from both TWSE and TPEX."
    }
    if (-not (Test-Path $symbolsPath)) {
        throw "Failed to fetch complete universe and no cached all_symbols.txt found."
    }
    Write-Warning "Using cached/incomplete universe from $symbolsPath"
}

$symbols = Get-Content $symbolsPath
if (-not $symbols -or $symbols.Count -eq 0) {
    throw "No listed symbols found in $symbolsPath"
}

if ($RandomMode.IsPresent) {
    Write-Host "Applying random symbol order..."
    $symbols = $symbols | Sort-Object { Get-Random }
}

if ($MaxSymbols -gt 0 -and $symbols.Count -gt $MaxSymbols) {
    $symbols = $symbols[0..($MaxSymbols - 1)]
}

Write-Host "[2/4] Backtest all symbols in single batch (symbols=$($symbols.Count))..."

$effectiveProgressStep = if ($ProgressStepSymbols -gt 0) {
    [Math]::Max(1, [int]$ProgressStepSymbols)
}
else {
    [Math]::Max(1, [int][Math]::Ceiling($symbols.Count / 50.0))
}

$runSymbolsPath = Join-Path $scriptDir "_run_symbols_tmp.txt"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($runSymbolsPath, ($symbols -join "`n"), $utf8NoBom)

try {
    Write-Host "Progress granularity: every $effectiveProgressStep symbols"
    Push-Location $repoRoot
    try {
        $backtestArgs = @(
            "-m", "src.tw_quant.runner", "backtest-batch",
            "--symbols-file", $runSymbolsPath,
            "--start", $Start,
            "--end", $End,
            "--strategy", $StrategyName,
            "--params", $effectiveBacktestParams,
            "--show-progress",
            "--progress-step", "$effectiveProgressStep"
        )

        if ($BatchLabel -and $BatchLabel.Trim()) {
            $backtestArgs += @("--batch-label", $BatchLabel.Trim())
        }

        & $PythonExe @backtestArgs
    }
    finally {
        Pop-Location
    }

    if ($LASTEXITCODE -ne 0) {
        throw "Single-batch backtest failed with exit code $LASTEXITCODE"
    }
}
finally {
    if (Test-Path $runSymbolsPath) {
        Remove-Item $runSymbolsPath -Force
    }
}

Write-Host "[3/4] Single-batch run completed"
Write-Host "[4/4] Done"
exit 0
