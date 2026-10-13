# Register a weekly Windows scheduled task for the competition radar.
# Run this in an elevated (Administrator) PowerShell window.
#
# NOTE: ASCII-only on purpose - Windows PowerShell 5.1 reads .ps1 as ANSI/GBK
# unless the file has a UTF-8 BOM, which would break non-ASCII text here.

$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path $projectDir "scripts\run_weekly.ps1"
$taskName = "CompRadar-Weekly"

if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "script not found: $scriptPath"
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 9am
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings `
    -Description "Weekly crawl of CS competitions, report refresh and alerts" -Force | Out-Null

Write-Output "Scheduled task registered: $taskName (every Monday 09:00)"
Write-Output "Run it now      : Start-ScheduledTask -TaskName '$taskName'"
Write-Output "Check last run  : Get-ScheduledTaskInfo -TaskName '$taskName'"
Write-Output "Remove the task : Unregister-ScheduledTask -TaskName '$taskName' -Confirm:`$false"
