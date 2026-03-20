param(
    [int]$MaxParallel = 6,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$runner = Join-Path $scriptDir "run_pullback_backtest_all.ps1"
if (-not (Test-Path $runner)) {
    throw "Runner not found: $runner"
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logDir = Join-Path $scriptDir ("parallel_status\run_" + $stamp)
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

$cases = @(
    @{ Name = "case01_a1"; Args = @("-BatchLabel", "case01_${stamp}_a1", "-MaxSymbols", "100", "-EntrySemanticsMode", "setup_trigger", "-SetupOffsetBars", "1", "-CooldownApplyOn", "any_exit", "-TriggerVolumeRatioWarnMax", "1.0", "-TriggerVolumeHardBlock", "-RiskBudgetPct", "0.01", "-EnableAtrTrailingProfitProtection", "-TrendBreakBelowMa60Days", "2", "-MaxHoldingDays", "110", "-ProgressStepSymbols", "1", "-RandomMode") },
    @{ Name = "case02_b1"; Args = @("-BatchLabel", "case02_${stamp}_b1", "-MaxSymbols", "100", "-EntrySemanticsMode", "setup_trigger", "-CooldownApplyOn", "stop_loss", "-RiskBudgetPct", "0.01", "-EnableAtrTrailingProfitProtection", "-RandomMode") },
    @{ Name = "case03_c1"; Args = @("-BatchLabel", "case03_${stamp}_c1", "-EntrySemanticsMode", "setup_trigger", "-SetupOffsetBars", "1", "-CooldownApplyOn", "stop_loss", "-RiskBudgetPct", "0.0", "-AtrStopMult", "2.8", "-TrendBreakBelowMa60Days", "4", "-ProfitProtectTrigger", "0.40", "-ProfitProtectPullback", "0.28", "-DisableMaxHoldingDays", "-TriggerVolumeRatioWarnMax", "1.6", "-ProgressStepSymbols", "1", "-MaxSymbols", "100", "-RandomMode") },
    @{ Name = "case04_a2"; Args = @("-BatchLabel", "case04_${stamp}_a2", "-MaxSymbols", "100", "-EntrySemanticsMode", "setup_trigger", "-SetupOffsetBars", "1", "-CooldownApplyOn", "any_exit", "-TriggerVolumeRatioWarnMax", "1.0", "-TriggerVolumeHardBlock", "-RiskBudgetPct", "0.01", "-EnableAtrTrailingProfitProtection", "-TrendBreakBelowMa60Days", "2", "-MaxHoldingDays", "110", "-ProgressStepSymbols", "1", "-RandomMode") },
    @{ Name = "case05_b2"; Args = @("-BatchLabel", "case05_${stamp}_b2", "-MaxSymbols", "100", "-EntrySemanticsMode", "setup_trigger", "-CooldownApplyOn", "stop_loss", "-RiskBudgetPct", "0.01", "-EnableAtrTrailingProfitProtection", "-RandomMode") },
    @{ Name = "case06_c2"; Args = @("-BatchLabel", "case06_${stamp}_c2", "-EntrySemanticsMode", "setup_trigger", "-SetupOffsetBars", "1", "-CooldownApplyOn", "stop_loss", "-RiskBudgetPct", "0.0", "-AtrStopMult", "2.8", "-TrendBreakBelowMa60Days", "4", "-ProfitProtectTrigger", "0.40", "-ProfitProtectPullback", "0.28", "-DisableMaxHoldingDays", "-TriggerVolumeRatioWarnMax", "1.6", "-ProgressStepSymbols", "1", "-MaxSymbols", "100", "-RandomMode") },
    @{ Name = "case07_a3"; Args = @("-BatchLabel", "case07_${stamp}_a3", "-MaxSymbols", "100", "-EntrySemanticsMode", "setup_trigger", "-SetupOffsetBars", "1", "-CooldownApplyOn", "any_exit", "-TriggerVolumeRatioWarnMax", "1.0", "-TriggerVolumeHardBlock", "-RiskBudgetPct", "0.01", "-EnableAtrTrailingProfitProtection", "-TrendBreakBelowMa60Days", "2", "-MaxHoldingDays", "110", "-ProgressStepSymbols", "1", "-RandomMode") },
    @{ Name = "case08_b3"; Args = @("-BatchLabel", "case08_${stamp}_b3", "-MaxSymbols", "100", "-EntrySemanticsMode", "setup_trigger", "-CooldownApplyOn", "stop_loss", "-RiskBudgetPct", "0.01", "-EnableAtrTrailingProfitProtection", "-RandomMode") },
    @{ Name = "case09_c3"; Args = @("-BatchLabel", "case09_${stamp}_c3", "-EntrySemanticsMode", "setup_trigger", "-SetupOffsetBars", "1", "-CooldownApplyOn", "stop_loss", "-RiskBudgetPct", "0.0", "-AtrStopMult", "2.8", "-TrendBreakBelowMa60Days", "4", "-ProfitProtectTrigger", "0.40", "-ProfitProtectPullback", "0.28", "-DisableMaxHoldingDays", "-TriggerVolumeRatioWarnMax", "1.6", "-ProgressStepSymbols", "1", "-MaxSymbols", "100", "-RandomMode") },
    @{ Name = "case10_a4"; Args = @("-BatchLabel", "case10_${stamp}_a4", "-MaxSymbols", "100", "-EntrySemanticsMode", "setup_trigger", "-SetupOffsetBars", "1", "-CooldownApplyOn", "any_exit", "-TriggerVolumeRatioWarnMax", "1.0", "-TriggerVolumeHardBlock", "-RiskBudgetPct", "0.01", "-EnableAtrTrailingProfitProtection", "-TrendBreakBelowMa60Days", "2", "-MaxHoldingDays", "110", "-ProgressStepSymbols", "1", "-RandomMode") },
    @{ Name = "case11_b4"; Args = @("-BatchLabel", "case11_${stamp}_b4", "-MaxSymbols", "100", "-EntrySemanticsMode", "setup_trigger", "-CooldownApplyOn", "stop_loss", "-RiskBudgetPct", "0.01", "-EnableAtrTrailingProfitProtection", "-RandomMode") },
    @{ Name = "case12_c4"; Args = @("-BatchLabel", "case12_${stamp}_c4", "-EntrySemanticsMode", "setup_trigger", "-SetupOffsetBars", "1", "-CooldownApplyOn", "stop_loss", "-RiskBudgetPct", "0.0", "-AtrStopMult", "2.8", "-TrendBreakBelowMa60Days", "4", "-ProfitProtectTrigger", "0.40", "-ProfitProtectPullback", "0.28", "-DisableMaxHoldingDays", "-TriggerVolumeRatioWarnMax", "1.6", "-ProgressStepSymbols", "1", "-MaxSymbols", "100", "-RandomMode") }
)

if ($DryRun.IsPresent) {
    Write-Host "DRY RUN: no jobs started"
    $cases | ForEach-Object {
        Write-Host ("- " + $_.Name + " => " + ($_.Args -join " "))
    }
    Write-Host "Log dir: $logDir"
    exit 0
}

$results = New-Object System.Collections.Generic.List[object]

foreach ($case in $cases) {
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

    $jobArgs = @($runner, $scriptDir, $logDir, $case.Name) + $case.Args
    Start-Job -Name $case.Name -ArgumentList $jobArgs -ScriptBlock {
        param(
            $runnerPath,
            $workDir,
            $logs,
            $name,
            [Parameter(ValueFromRemainingArguments = $true)]
            [string[]]$runnerArgs
        )
        $ErrorActionPreference = "Continue"
        $logPath = Join-Path $logs ("$name.log")
        $startAt = Get-Date

        if ($null -eq $runnerArgs) { $runnerArgs = @() }

        Set-Location $workDir
        "[$($startAt.ToString('s'))] START $name" | Out-File -FilePath $logPath -Encoding utf8 -Append
        "[$($startAt.ToString('s'))] CMD   $runnerPath $($runnerArgs -join ' ')" | Out-File -FilePath $logPath -Encoding utf8 -Append

        try {
            $invokeArgs = @(
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-File", $runnerPath
            ) + @($runnerArgs | ForEach-Object { [string]$_ })

            & powershell @invokeArgs *>&1 | Tee-Object -FilePath $logPath -Append | Out-Null
            $exitCode = $LASTEXITCODE
            if ($null -eq $exitCode) { $exitCode = 0 }
        }
        catch {
            $_ | Out-String | Out-File -FilePath $logPath -Encoding utf8 -Append
            $exitCode = 999
        }

        $endAt = Get-Date
        $status = if ($exitCode -eq 0) { "SUCCESS" } else { "FAILED" }
        "[$($endAt.ToString('s'))] END $name exit=$exitCode status=$status" | Out-File -FilePath $logPath -Encoding utf8 -Append

        [pscustomobject]@{
            Name = $name
            ExitCode = [int]$exitCode
            Status = $status
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

$summaryPath = Join-Path $logDir "summary.csv"
$results |
    Sort-Object Name |
    Select-Object Name, Status, ExitCode, StartedAt, EndedAt, LogPath |
    Export-Csv -Path $summaryPath -NoTypeInformation -Encoding utf8

$ok = ($results | Where-Object { $_.ExitCode -eq 0 }).Count
$fail = ($results | Where-Object { $_.ExitCode -ne 0 }).Count
Write-Host "Completed: success=$ok failed=$fail"
Write-Host "Summary: $summaryPath"
if ($fail -gt 0) {
    Write-Warning "Some runs failed. Check summary/log files above."
}
