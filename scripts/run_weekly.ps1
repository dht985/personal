# Weekly run of the competition radar.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\run_weekly.ps1
#
# NOTE: this file is intentionally ASCII-only. Windows PowerShell 5.1 reads .ps1
# files as ANSI/GBK unless they carry a UTF-8 BOM, which would corrupt any
# non-ASCII text in this script. Chinese output still works: the python side
# emits UTF-8 and we decode it explicitly below.

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$projectDir = Split-Path -Parent $PSScriptRoot
Set-Location $projectDir

$env:PYTHONIOENCODING = "utf-8"

# The scheduled task may inherit a stale environment block, so read the user-level
# variable straight from the registry when it is missing from the process.
if (-not $env:COMPRADAR_SERPAPI_KEY) {
    $apiKey = [Environment]::GetEnvironmentVariable("COMPRADAR_SERPAPI_KEY", "User")
    if ($apiKey) { $env:COMPRADAR_SERPAPI_KEY = $apiKey }
}

$outboxDir = Join-Path $projectDir "outbox"
if (-not (Test-Path -LiteralPath $outboxDir)) {
    New-Item -ItemType Directory -Path $outboxDir | Out-Null
}
$logFile = Join-Path $outboxDir "run.log"

function Write-Log([string]$Message) {
    Write-Output $Message
    # UTF8 with BOM in PS 5.1: keeps the log readable in Notepad and editors.
    Add-Content -LiteralPath $logFile -Value $Message -Encoding UTF8
}

function Get-Stamp {
    return (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
}

Write-Log "[$(Get-Stamp)] competition radar: weekly run started"

try {
    $runLog = Join-Path $outboxDir "last-run.log"
    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    python -m radar run *> $runLog
    $runCode = $LASTEXITCODE
    $ErrorActionPreference = $previousEap

    if (Test-Path -LiteralPath $runLog) {
        Get-Content -LiteralPath $runLog -Encoding UTF8 | ForEach-Object { Write-Log $_ }
    }
    if ($runCode -ne 0) {
        throw "radar run exited with code $runCode (full output above)"
    }

    python -m radar verify --limit 40 2>&1 | ForEach-Object { Write-Log $_ }

    # 只有本轮真的有需要行动的信息时才自动打开仪表盘，避免每周无意义弹浏览器
    $alertFile = Join-Path $outboxDir ("notifications-" + (Get-Date -Format "yyyy-MM-dd") + ".md")
    $candidates = Join-Path $projectDir "data\candidates.json"
    $shouldOpen = $false
    if (Test-Path -LiteralPath $candidates) {
        try {
            $data = Get-Content -LiteralPath $candidates -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($data.stats.notifications -gt 0) { $shouldOpen = $true }
        } catch {
            $shouldOpen = $false
        }
    }
    if ($shouldOpen) {
        Write-Log "there are $($data.stats.notifications) actionable notifications; opening dashboard"
        python -m radar dashboard --open 2>&1 | ForEach-Object { Write-Log $_ }
    }

    Write-Log "[$(Get-Stamp)] finished. reports are in outbox\"
}
catch {
    Write-Log "[$(Get-Stamp)] FAILED: $($_.Exception.Message)"
    exit 1
}
