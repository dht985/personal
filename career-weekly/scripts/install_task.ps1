# Per-user weekly task, no elevation required.
$ErrorActionPreference = "Stop"
$projectDir = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path $projectDir "scripts\run_weekly.ps1"
$taskName = "CareerWeekly"

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$scriptPath`""
$weeklyTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 9am
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -DontStopOnIdleEnd `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask -TaskName $taskName -Action $action `
    -Trigger @($weeklyTrigger, $logonTrigger) `
    -Settings $settings -Description "Weekly career intelligence report" -Force | Out-Null

Write-Output "Scheduled task registered: $taskName (Monday 09:00 + logon catch-up)"
Write-Output "Run now: Start-ScheduledTask -TaskName '$taskName'"
