# WAGMI API server supervised launcher
# Serves the /v1/* endpoints the crazyonsol.online frontend fetches (bot/api_server.py, port 8000).
# Self-loops on python exit so a crash auto-restarts within seconds.
# Task Scheduler (WAGMI-API) restarts THIS script if it dies. Two layers of resilience.
# Mirrors run_paper_supervised.ps1.

$ErrorActionPreference = "Continue"
$BotDir = "C:\Users\vince\WAGMI\bot"
$LogsDir = Join-Path $BotDir "logs"
$WrapperLog = Join-Path $LogsDir "api_supervisor.log"

if (-not (Test-Path $LogsDir)) { New-Item -ItemType Directory -Path $LogsDir | Out-Null }

function Write-WrapperLog {
    param([string]$msg)
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path $WrapperLog -Value $line -Encoding utf8
}

Write-WrapperLog "=== API supervisor started (PID $PID) ==="

Set-Location $BotDir

$RestartCount = 0
while ($true) {
    $RestartCount++
    Write-WrapperLog "Launching python api_server.py (attempt #$RestartCount)"

    try {
        & python api_server.py 2>&1 | Tee-Object -FilePath (Join-Path $LogsDir "api_stdout.log") -Append
        $exitCode = $LASTEXITCODE
    } catch {
        $exitCode = -1
        Write-WrapperLog "EXCEPTION launching python: $($_.Exception.Message)"
    }

    Write-WrapperLog "api_server exited with code $exitCode. Restarting in 15s..."

    # Backoff: 15s default, longer if we're restart-looping rapidly
    if ($RestartCount -gt 5) {
        $sleep = [Math]::Min(300, 15 * ($RestartCount - 4))
        Write-WrapperLog "Restart loop detected ($RestartCount attempts), backing off ${sleep}s"
        Start-Sleep -Seconds $sleep
    } else {
        Start-Sleep -Seconds 15
    }
}
