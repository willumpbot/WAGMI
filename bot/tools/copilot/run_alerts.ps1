# WAGMI Co-Pilot alert runner — scheduled every 2h via Task Scheduler "WAGMI-Copilot-Alerts".
# Watches POPCAT + SOL, pushes a Discord alert ONLY on a genuine state transition (add zone /
# falling-knife / leverage escalation). Anti-spam: state-change-only + 6h cooldown (see copilot_alerts.py).
# Read-only w.r.t. the live paper bot. Leverage/liq numbers use the placeholder $1000/2x until the
# owner sets real --equity/--leverage; the timing signals (add/knife) are accurate regardless.
$ErrorActionPreference = "Continue"
Set-Location "C:\Users\vince\WAGMI\bot"
$py = "C:\Users\vince\AppData\Local\Programs\Python\Python313\python.exe"
$ts = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
"[$ts] copilot_alerts run" | Out-File -Append -Encoding utf8 "data\copilot\alerts.log"

# --- LIQ-COLLECTOR WATCHDOG (added 2026-08-01) ---------------------------------
# The liquidation-cascade collector produces UN-BACKFILLABLE forward evidence but
# is NOT its own scheduled task (registration needs elevation the setup session
# lacked). Left alone it dies on reboot and the evidence stops SILENTLY - the exact
# 22-day-outage failure mode the OI corpus already suffered. This piggybacks on
# this already-scheduled 2h task (survives reboot) to relaunch it if it's not
# running, capping any silent gap at ~2h instead of permanent. Purely additive /
# read-only w.r.t. trading; only ever (re)starts the collector's own supervisor.
try {
    $liq = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*liq_collector*' }
    if (-not $liq) {
        "[$ts] WATCHDOG: liq_collector not running - relaunching run_liq_collector.ps1" |
            Out-File -Append -Encoding utf8 "data\copilot\alerts.log"
        Start-Process powershell.exe -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File',`
            'C:\Users\vince\WAGMI\bot\tools\copilot\run_liq_collector.ps1' -WindowStyle Hidden
    }
    # MICRO-CAP COLLECTOR (added 2026-08-05) - same un-backfillable / no-scheduled-task
    # situation: its forward-discovery log is the survivorship-bias fix and must not die
    # silently on reboot. Relaunch if not running.
    $mc = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*microcap_collector*' }
    if (-not $mc) {
        "[$ts] WATCHDOG: microcap_collector not running - relaunching run_microcap_collector.ps1" |
            Out-File -Append -Encoding utf8 "data\copilot\alerts.log"
        Start-Process powershell.exe -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File',`
            'C:\Users\vince\WAGMI\bot\tools\copilot\run_microcap_collector.ps1' -WindowStyle Hidden
    }
    # DISCORD CALL LISTENER (added 2026-08-06) - same relaunch-if-dead pattern, but
    # GATED on WAGMI_DISCORD_BOT_TOKEN being set: the listener stays dormant until
    # the owner adds his token, so we only ever (re)launch its supervisor when a
    # token exists. The token is never logged. Purely additive / read-only w.r.t.
    # trading; only ever starts the listener's own token-gated supervisor.
    if (-not [string]::IsNullOrWhiteSpace($env:WAGMI_DISCORD_BOT_TOKEN)) {
        $dl = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -like '*discord_call_listener*' }
        if (-not $dl) {
            "[$ts] WATCHDOG: discord_call_listener not running - relaunching run_discord_listener.ps1" |
                Out-File -Append -Encoding utf8 "data\copilot\alerts.log"
            Start-Process powershell.exe -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File',`
                'C:\Users\vince\WAGMI\bot\tools\copilot\run_discord_listener.ps1' -WindowStyle Hidden
        }
    }
} catch {
    "[$ts] WATCHDOG error (non-fatal): $($_.Exception.Message)" |
        Out-File -Append -Encoding utf8 "data\copilot\alerts.log"
}
# ------------------------------------------------------------------------------
# --leverage 3: the alerter's job is the ADD/knife TIMING signals (equity/leverage-independent);
# a fixed leverage only exists so the leverage-risk check has a value. 3x is safe on all coins
# (POPCAT's real HL cap), so no false leverage-SUICIDAL fires. Per-coin leverage guidance lives
# in the human-facing range-aware brief (copilot.py --lev-range 3-15), not in the alerts.
& $py "tools\copilot\copilot_alerts.py" --equity 5000 --leverage 3 2>&1 | Out-File -Append -Encoding utf8 "data\copilot\alerts.log"
