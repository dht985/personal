# Weekly run of career intelligence. ASCII-only on purpose.
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$projectDir = Split-Path -Parent $PSScriptRoot
Set-Location $projectDir
$env:PYTHONIOENCODING = "utf-8"

$outbox = Join-Path $projectDir "outbox"
if (-not (Test-Path -LiteralPath $outbox)) { New-Item -ItemType Directory -Path $outbox | Out-Null }
$logFile = Join-Path $outbox "run.log"

function Write-Log([string]$Message) {
    Write-Output $Message
    Add-Content -LiteralPath $logFile -Value $Message -Encoding UTF8
}

$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Write-Log "[$stamp] career-weekly started"

try {
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
    exit 1
}
