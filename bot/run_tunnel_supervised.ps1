# WAGMI Tunnel supervised launcher
#
# WHY THIS EXISTS
#   Same reason as run_watchdog_supervised.ps1: tunnel_manager.py was launched
#   as a bare python.exe Task Scheduler action with a VISIBLE console window,
#   so closing a stray PowerShell window killed the website tunnel
#   (exit 0xC000013A). Launched hidden here, there is no window to close.
#
#   tunnel_manager.py already restarts cloudflared internally; this wrapper
#   covers the case where tunnel_manager.py itself dies.

$ErrorActionPreference = "Continue"
$BotDir     = "C:\Users\vince\WAGMI\bot"
$LogsDir    = Join-Path $BotDir "logs"
$WrapperLog = Join-Path $LogsDir "tunnel_supervisor.log"
$Python     = "C:\Users\vince\AppData\Local\Programs\Python\Python313\python.exe"

if (-not (Test-Path $LogsDir)) { New-Item -ItemType Directory -Path $LogsDir | Out-Null }

function Write-WrapperLog {
    param([string]$msg)
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path $WrapperLog -Value $line -Encoding utf8
}

Write-WrapperLog "=== Tunnel supervisor started (PID $PID) ==="
Set-Location $BotDir

$RestartCount = 0
while ($true) {
    $RestartCount++
    Write-WrapperLog "Launching tools\tunnel_manager.py (attempt #$RestartCount)"

    try {
        & $Python "$BotDir\tools\tunnel_manager.py" 2>&1 |
            Tee-Object -FilePath (Join-Path $LogsDir "tunnel_stdout.log") -Append
        $exitCode = $LASTEXITCODE
    } catch {
        $exitCode = -1
        Write-WrapperLog "EXCEPTION launching tunnel_manager: $($_.Exception.Message)"
    }

    Write-WrapperLog "tunnel_manager exited with code $exitCode. Restarting in 30s..."

    if ($RestartCount -gt 5) {
        $sleep = [Math]::Min(300, 30 * ($RestartCount - 4))
        Write-WrapperLog "Restart loop detected ($RestartCount attempts), backing off ${sleep}s"
        Start-Sleep -Seconds $sleep
    } else {
        Start-Sleep -Seconds 30
    }
}
