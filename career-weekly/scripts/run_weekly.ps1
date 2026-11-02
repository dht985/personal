# Weekly run of career intelligence. ASCII-only on purpose.
param([switch]$Force)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$projectDir = Split-Path -Parent $PSScriptRoot
Set-Location $projectDir
$env:PYTHONIOENCODING = "utf-8"

$outbox = Join-Path $projectDir "outbox"
if (-not (Test-Path -LiteralPath $outbox)) { New-Item -ItemType Directory -Path $outbox | Out-Null }
$logFile = Join-Path $outbox "run.log"
$lockFile = Join-Path $outbox ".run.lock"

function Write-Log([string]$Message) {
    Write-Output $Message
    Add-Content -LiteralPath $logFile -Value $Message -Encoding UTF8
}

$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Write-Log "[$stamp] career-weekly started"

if (Test-Path -LiteralPath $lockFile) {
    $lockAge = (Get-Date) - (Get-Item -LiteralPath $lockFile).LastWriteTime
    if ($lockAge.TotalMinutes -lt 120) {
        Write-Log "[$stamp] another run is active; skipped"
        exit 0
    }
    Remove-Item -LiteralPath $lockFile -Force
}
New-Item -ItemType File -Path $lockFile -Force | Out-Null

try {
    if (-not $Force) {
        python -m cw due --max-age-hours 144
        $dueCode = $LASTEXITCODE
        if ($dueCode -eq 0) {
            Write-Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] no run due"
            exit 0
        }
        if ($dueCode -ne 20) { throw "cw due exited with code $dueCode" }
    }

    $discLog = Join-Path $outbox "discover.log"
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    python -m cw discover-sources --limit 4 *> $discLog
    $ErrorActionPreference = $prevEap
    if (Test-Path -LiteralPath $discLog) {
        Get-Content -LiteralPath $discLog -Encoding UTF8 | ForEach-Object { Write-Log $_ }
    }

    $runLog = Join-Path $outbox "last-run.log"
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    python -m cw run *> $runLog
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prev
    if (Test-Path -LiteralPath $runLog) {
        Get-Content -LiteralPath $runLog -Encoding UTF8 | ForEach-Object { Write-Log $_ }
    }
    if ($code -ne 0) { throw "cw run exited with code $code" }

    Write-Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] finished"
}
catch {
    Write-Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] FAILED: $($_.Exception.Message)"
    Remove-Item -LiteralPath $lockFile -Force -ErrorAction SilentlyContinue
    exit 1
}
finally {
    Remove-Item -LiteralPath $lockFile -Force -ErrorAction SilentlyContinue
}
