# WAGMI Co-Pilot MICRO-CAP / SOLANA CAT-COIN COLLECTOR - supervised long-running launcher.
# Mirrors run_liq_collector.ps1's pattern: self-loops on exit so a crash
# auto-restarts within seconds; Task Scheduler restarts THIS script if it
# dies outright (two layers of resilience, same as the main bot).
#
# microcap_collector.py --daemon already loops its own discover/universe/
# history/snapshot cycle internally with its own sleep interval - this
# wrapper only matters if the WHOLE PROCESS exits (uncaught exception,
# OOM, etc).
#
# Read-only w.r.t. the live paper bot. Only ever launches
# tools\copilot\microcap_collector.py; only touches data\microcap\.
#
# Usage (manual):
#   powershell -File tools\copilot\run_microcap_collector.ps1
#
# Scheduling: NOT registered by this file or by the build task that created
# it - per instructions, build only. To register later (owner's call):
#   schtasks /Create /TN "WAGMI-Microcap-Collector" /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\Users\vince\WAGMI\bot\tools\copilot\run_microcap_collector.ps1" /SC ONSTART /RU "%USERNAME%" /RL LIMITED /F

$ErrorActionPreference = "Continue"
$BotDir = "C:\Users\vince\WAGMI\bot"
$OutDir = Join-Path $BotDir "data\microcap"
$WrapperLog = Join-Path $OutDir "supervisor.log"
$py = "C:\Users\vince\AppData\Local\Programs\Python\Python313\python.exe"

if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir -Force | Out-Null }

function Write-WrapperLog {
    param([string]$msg)
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path $WrapperLog -Value $line -Encoding utf8
}

Write-WrapperLog "=== microcap_collector supervisor started (PID $PID) ==="
Set-Location $BotDir

$RestartCount = 0
while ($true) {
    $RestartCount++
    Write-WrapperLog "Launching microcap_collector.py --daemon (attempt #$RestartCount)"

    try {
        & $py "tools\copilot\microcap_collector.py" --daemon 2>&1 | Out-File -Append -Encoding utf8 (Join-Path $OutDir "python_stdout.log")
        $exitCode = $LASTEXITCODE
    } catch {
        $exitCode = -1
        Write-WrapperLog "EXCEPTION launching python: $($_.Exception.Message)"
    }

    Write-WrapperLog "microcap_collector.py exited with code $exitCode. Restarting in 30s..."

    if ($RestartCount -gt 5) {
        $sleep = [Math]::Min(300, 30 * ($RestartCount - 4))
        Write-WrapperLog "Restart loop detected ($RestartCount attempts), backing off ${sleep}s"
        Start-Sleep -Seconds $sleep
    } else {
        Start-Sleep -Seconds 30
    }
}
