# Per-user weekly task, no elevation required.
$ErrorActionPreference = "Stop"
$projectDir = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path $projectDir "scripts\run_weekly.ps1"
$taskName = "CareerWeekly"

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$scriptPath`""
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 9am
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Description "Weekly career intelligence report" -Force | Out-Null

Write-Output "Scheduled task registered: $taskName (every Monday 09:00)"
Write-Output "Run now: Start-ScheduledTask -TaskName '$taskName'"
