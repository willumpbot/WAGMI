# WAGMI Shift Briefing runner - PUSHES to Discord (owner opted in 2026-09-08).
#
# Sibling of run_briefing.ps1, which intentionally stays dry-run. This one adds
# --send because the owner explicitly asked for a scannable full-picture briefing
# on their phone across a 12h work shift. Read-only w.r.t. the live paper bot:
# `cli.py brief` only composes already-computed honest components and pushes one
# Discord message. Windowless, self-logging, no console to close.
$ErrorActionPreference = "Continue"
Set-Location "C:\Users\vince\WAGMI\bot"
$py  = "C:\Users\vince\AppData\Local\Programs\Python\Python313\python.exe"
$log = "data\copilot\briefing.log"
$ts  = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
"[$ts] shift briefing run (--send)" | Out-File -Append -Encoding utf8 $log
& $py "tools\copilot\cli.py" brief --equity 5000 --send 2>&1 | Out-File -Append -Encoding utf8 $log
