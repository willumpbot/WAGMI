# WAGMI Co-Pilot daily forward-evidence job (Task Scheduler "WAGMI-Copilot-Daily", once/day).
# (1) Logs a full-featured daily snapshot (WITH weather) for the watchlist into data/copilot/call_ledger.jsonl
#     — this is the pre-registered forward-evidence the co-pilot's claims (H1/H2) get judged on.
# (2) Runs the resolver to stamp forward 1d/3d/5d returns onto matured rows.
# (3) Runs the H3/H5 liquidation-hypothesis harness (maturity/gated mode) — STRICTLY gated
#     (n>=30 independent episodes AND >=14d span before any p-value), so daily runs just log
#     maturity progress and auto-produce the H3/H5 readout the moment the bars clear (no peeking:
#     the gating is in the compute layer, cannot leak a premature result).
# (5) Runs the H6 near-miss reversion tracker (drop2d_fixed10pct, see PREREGISTRATION.md) —
#     detects/logs any of the 25 longtail alts currently in the 2-day-drop trigger state (live
#     HLNative fetch, entry-time-safe, no backfill of the spent in-sample corpus), resolves
#     matured (2-settled-day) triggers, and prints the STRICTLY gated (n>=30 forward triggers
#     before any p-value) maturity readout.
# Read-only w.r.t. the live paper bot. No Discord push (read/resolve/harness never push).
$ErrorActionPreference = "Continue"
Set-Location "C:\Users\vince\WAGMI\bot"
$py = "C:\Users\vince\AppData\Local\Programs\Python\Python313\python.exe"
$ts = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
"[$ts] copilot-daily: snapshot + resolve + H3/H5 + H4 + H6 maturity" | Out-File -Append -Encoding utf8 "data\copilot\daily.log"
& $py "tools\copilot\cli.py" read --symbol "BTC,SOL,POPCAT,WIF,FARTCOIN,PENGU,kPEPE,kBONK,kSHIB" --equity 5000 2>&1 | Out-File -Append -Encoding utf8 "data\copilot\daily.log"
& $py "tools\copilot\resolve_calls.py" 2>&1 | Out-File -Append -Encoding utf8 "data\copilot\daily.log"
# Owner's OWN discretionary calls (cli.py call ...) - stamp forward 1d/7d/30d
# outcomes onto matured rows. Gated (no edge verdict below n>=20); his calls
# accrue faster than passive discovery. Read-only, no push. Added 2026-08-06.
& $py "tools\copilot\cli.py" call resolve 2>&1 | Out-File -Append -Encoding utf8 "data\copilot\daily.log"
& $py "tools\copilot\liq_hypothesis_harness.py" 2>&1 | Out-File -Append -Encoding utf8 "data\copilot\daily.log"
& $py "tools\copilot\oi_hypothesis_harness.py" 2>&1 | Out-File -Append -Encoding utf8 "data\copilot\daily.log"
& $py "tools\copilot\nearmiss_reversion_tracker.py" 2>&1 | Out-File -Append -Encoding utf8 "data\copilot\daily.log"
