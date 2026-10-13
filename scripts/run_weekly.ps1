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
    python -m radar run 2>&1 | ForEach-Object { Write-Log $_ }
    if ($LASTEXITCODE -ne 0) {
        throw "radar run exited with code $LASTEXITCODE"
    }

    python -m radar verify --limit 40 2>&1 | ForEach-Object { Write-Log $_ }

    Write-Log "[$(Get-Stamp)] finished. reports are in outbox\"
}
catch {
    Write-Log "[$(Get-Stamp)] FAILED: $($_.Exception.Message)"
    exit 1
}
