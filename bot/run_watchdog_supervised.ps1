# WAGMI Watchdog supervised launcher
#
# WHY THIS EXISTS
#   The watchdog used to be launched directly by Task Scheduler as a bare
#   python.exe action. That gave it a VISIBLE console window, and closing any
#   stray PowerShell window killed it (exit 0xC000013A). The watchdog is the
#   thing that notices the bot dying, so it was dying unnoticed.
#
#   This wrapper mirrors run_paper_supervised.ps1 exactly, which is the pattern
#   that has kept the bot and API alive through the same conditions:
#     - launched with -WindowStyle Hidden, so there is no window to close
#     - self-loops on python exit, so a crash restarts within seconds
#     - Task Scheduler restarts THIS script if it dies (two layers)

$ErrorActionPreference = "Continue"
$BotDir     = "C:\Users\vince\WAGMI\bot"
$LogsDir    = Join-Path $BotDir "logs"
$WrapperLog = Join-Path $LogsDir "watchdog_supervisor.log"
$Python     = "C:\Users\vince\AppData\Local\Programs\Python\Python313\python.exe"

if (-not (Test-Path $LogsDir)) { New-Item -ItemType Directory -Path $LogsDir | Out-Null }

function Write-WrapperLog {
    param([string]$msg)
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path $WrapperLog -Value $line -Encoding utf8
}

Write-WrapperLog "=== Watchdog supervisor started (PID $PID) ==="
Set-Location $BotDir

$RestartCount = 0
while ($true) {
    $RestartCount++
    Write-WrapperLog "Launching watchdog.py monitor (attempt #$RestartCount)"

    try {
        & $Python watchdog.py monitor 2>&1 |
            Tee-Object -FilePath (Join-Path $LogsDir "watchdog_stdout.log") -Append
        $exitCode = $LASTEXITCODE
    } catch {
        $exitCode = -1
        Write-WrapperLog "EXCEPTION launching watchdog: $($_.Exception.Message)"
    }

    Write-WrapperLog "Watchdog exited with code $exitCode. Restarting in 30s..."

    if ($RestartCount -gt 5) {
        $sleep = [Math]::Min(300, 30 * ($RestartCount - 4))
        Write-WrapperLog "Restart loop detected ($RestartCount attempts), backing off ${sleep}s"
        Start-Sleep -Seconds $sleep
    } else {
        Start-Sleep -Seconds 30
    }
}
