# WAGMI Morning Briefing runner — intended for a daily Task Scheduler job (NOT yet registered;
# hand the owner the schtasks command separately). Composes the co-pilot's weather/watchlist/
# radar/liquidations read into ONE scannable digest and logs it. Read-only w.r.t. the live paper
# bot. DEFAULT --dry-run: this script NEVER pushes to Discord on its own — it only computes +
# logs the digest. To get a real Discord push on the scheduled run, edit this file and add --send
# (after confirming with a manual dry run first); this file intentionally ships without it so a
# freshly-registered task can never surprise-ping the owner.
$ErrorActionPreference = "Continue"
Set-Location "C:\Users\vince\WAGMI\bot"
$py = "C:\Users\vince\AppData\Local\Programs\Python\Python313\python.exe"
$ts = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
"[$ts] briefing run (dry-run: print + log only, no Discord push)" | Out-File -Append -Encoding utf8 "data\copilot\briefing.log"
& $py "tools\copilot\cli.py" brief --equity 5000 --dry-run 2>&1 | Out-File -Append -Encoding utf8 "data\copilot\briefing.log"
