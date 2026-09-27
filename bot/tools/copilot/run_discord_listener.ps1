# WAGMI Co-Pilot SECURE DISCORD CALL LISTENER - supervised long-running launcher.
# Mirrors run_microcap_collector.ps1 / run_liq_collector.ps1's pattern: self-loops
# on exit so a crash auto-restarts within seconds; Task Scheduler (or the
# run_alerts.ps1 watchdog) restarts THIS script if it dies outright.
#
# WHAT IT RUNS: tools\copilot\discord_call_listener.py - a locked-down bridge
# that lets ONLY the owner (by Discord user-id) fire `cli.py call ...` from ONE
# channel and get the risk brief back. Read-only w.r.t. the live paper bot; the
# `call` command it invokes only logs owner_call_ledger.jsonl + prints a brief.
#
# DORMANT UNTIL CONFIGURED: this wrapper does NOTHING unless
# WAGMI_DISCORD_BOT_TOKEN is set in the environment. With no token it logs
# "token not set, not starting" and EXITS (no connect, no crash-loop). This is
# the safe default so the file can ship idle until the owner adds his token.
# The token itself is NEVER written to the log.
#
# Usage (manual, once the env vars are set for this user):
#   powershell -File tools\copilot\run_discord_listener.ps1
#
# Scheduling: NOT registered by this file (build only, per instructions). To
# register later (owner's call, needs the env vars visible to the task's user):
#   schtasks /Create /TN "WAGMI-Discord-Listener" /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\Users\vince\WAGMI\bot\tools\copilot\run_discord_listener.ps1" /SC ONSTART /RU "%USERNAME%" /RL LIMITED /F

$ErrorActionPreference = "Continue"
$BotDir = "C:\Users\vince\WAGMI\bot"
$OutDir = Join-Path $BotDir "data\copilot"
$WrapperLog = Join-Path $OutDir "discord_listener_supervisor.log"
$py = "C:\Users\vince\AppData\Local\Programs\Python\Python313\python.exe"

if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir -Force | Out-Null }

function Write-WrapperLog {
    param([string]$msg)
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path $WrapperLog -Value $line -Encoding utf8
}

# --- TOKEN GATE: stay dormant until the owner sets his bot token --------------
if ([string]::IsNullOrWhiteSpace($env:WAGMI_DISCORD_BOT_TOKEN)) {
    Write-WrapperLog "WAGMI_DISCORD_BOT_TOKEN not set, not starting - staying dormant."
    return
}

Write-WrapperLog "=== discord_call_listener supervisor started (PID $PID) ==="
Set-Location $BotDir

$RestartCount = 0
while ($true) {
    # Re-check the token each loop so a later un-set also parks the supervisor
    # (the python side is fail-dormant too, but this avoids a hot relaunch loop).
    if ([string]::IsNullOrWhiteSpace($env:WAGMI_DISCORD_BOT_TOKEN)) {
        Write-WrapperLog "WAGMI_DISCORD_BOT_TOKEN cleared, not starting - staying dormant."
        return
    }

    $RestartCount++
    Write-WrapperLog "Launching discord_call_listener.py (attempt #$RestartCount)"

    try {
        & $py "tools\copilot\discord_call_listener.py" 2>&1 | Out-File -Append -Encoding utf8 (Join-Path $OutDir "discord_listener_stdout.log")
        $exitCode = $LASTEXITCODE
    } catch {
        $exitCode = -1
        Write-WrapperLog "EXCEPTION launching python: $($_.Exception.Message)"
    }

    Write-WrapperLog "discord_call_listener.py exited with code $exitCode. Restarting in 30s..."

    if ($RestartCount -gt 5) {
        $sleep = [Math]::Min(300, 30 * ($RestartCount - 4))
        Write-WrapperLog "Restart loop detected ($RestartCount attempts), backing off ${sleep}s"
        Start-Sleep -Seconds $sleep
    } else {
        Start-Sleep -Seconds 30
    }
}
