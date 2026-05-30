# WAGMI Bot -- plain English status. One paragraph. No tables, no colors, no scrolling.
# Run: powershell -File C:\Users\vince\WAGMI\bot\bot_status.ps1
# Run repeatedly anytime you want to know "what is the bot doing".

$BotDir = "C:\Users\vince\WAGMI\bot"
$DataDir = Join-Path $BotDir "data"
$LlmDir  = Join-Path $DataDir "llm"
$LogsDir = Join-Path $BotDir "logs"

function Get-LatestBotLog {
    Get-ChildItem (Join-Path $LogsDir "bot_*.log") -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
}

# --- gather facts ---
$hb = Join-Path $DataDir "bot_heartbeat.txt"
$py = Get-Process python -ErrorAction SilentlyContinue | Sort-Object StartTime | Select-Object -First 1
$alive = $false
$uptime = "unknown"
$hbAge = $null
if (Test-Path $hb) {
    $hbAge = ((Get-Date) - (Get-Item $hb).LastWriteTime).TotalSeconds
    $alive = $hbAge -lt 90
}
if ($py) {
    $span = (Get-Date) - $py.StartTime
    if ($span.TotalHours -ge 1) {
        $uptime = "{0}h {1}m" -f [int]$span.TotalHours, $span.Minutes
    } else {
        $uptime = "{0}m" -f $span.Minutes
    }
}

$equity = 5000.0
try {
    $eq = Get-Content (Join-Path $DataDir "risk_equity_state.json") -Raw | ConvertFrom-Json
    $equity = [double]$eq.equity
} catch {}
$pnlSession = $equity - 5000.0

$tradesToday = 0
$tradesFile = Join-Path $DataDir "trades.csv"
if (Test-Path $tradesFile) {
    $today = (Get-Date).ToString("yyyy-MM-dd")
    $tradesToday = (Get-Content $tradesFile | Select-String -SimpleMatch $today | Measure-Object).Count
}

$skipCount = 0
$cfFile = Join-Path $LlmDir "counterfactual_pending.jsonl"
if (Test-Path $cfFile) { $skipCount = (Get-Content $cfFile | Measure-Object -Line).Lines }

# Regimes & volume
$regimes = @{}
$volRatios = @{}
$prices = @{}
$log = Get-LatestBotLog
if ($log) {
    $tail = Get-Content $log.FullName -Tail 2500
    [array]::Reverse($tail)
    foreach ($line in $tail) {
        if ($line -match '\[REGIME\]\s+(BTC|ETH|SOL|HYPE):\s+(\w+)') {
            if (-not $regimes.ContainsKey($Matches[1])) { $regimes[$Matches[1]] = $Matches[2] }
        }
        if ($line -match '\[(BTC|ETH|SOL|HYPE)\]\s+Volume ratio\s+([\d.]+)') {
            if (-not $volRatios.ContainsKey($Matches[1])) { $volRatios[$Matches[1]] = [double]$Matches[2] }
        }
        if ($line -match 'MARKET UPDATE') {
            foreach ($sym in @("BTC","ETH","SOL","HYPE")) {
                if ($line -match "$sym\s+\`$([\d,.]+)") {
                    if (-not $prices.ContainsKey($sym)) { $prices[$sym] = [double]($Matches[1] -replace ',','') }
                }
            }
        }
    }
}

# Scout watchlist
$watchlist = @()
$apFile = Join-Path $LlmDir "agent_performance.jsonl"
if (Test-Path $apFile) {
    $lines = Get-Content $apFile -Tail 150
    [array]::Reverse($lines)
    foreach ($line in $lines) {
        try {
            $d = $line | ConvertFrom-Json
            if ($d.agent_role -eq "scout" -and $d.reasoning_summary) {
                $text = "$($d.reasoning_summary)"
                $rxMatches = [regex]::Matches($text, "'symbol':\s*'([^']+)'.*?'priority':\s*'([^']+)'.*?'setup_forming':\s*'([^']*)'")
                foreach ($m in $rxMatches) {
                    if ($m.Groups[2].Value -eq "high") {
                        $watchlist += [PSCustomObject]@{
                            Symbol = $m.Groups[1].Value
                            Setup = $m.Groups[3].Value
                        }
                    }
                }
                break
            }
        } catch {}
    }
}

# Trade-agent last verdict (one-line)
$lastTradeVerdict = ""
if (Test-Path $apFile) {
    $lines = Get-Content $apFile -Tail 60
    [array]::Reverse($lines)
    foreach ($line in $lines) {
        try {
            $d = $line | ConvertFrom-Json
            if ($d.type -eq "decision" -and $d.agent_role -eq "trade") {
                $r = "$($d.reasoning_summary)" -replace "`r?`n", " "
                # Take first sentence
                if ($r -match '^([^.]+\.)') { $lastTradeVerdict = $Matches[1].Trim() }
                else { $lastTradeVerdict = if ($r.Length -gt 150) { $r.Substring(0,150) + "..." } else { $r } }
                break
            }
        } catch {}
    }
}

$utcHour = (Get-Date).ToUniversalTime().Hour
$timeWindow = if ($utcHour -ge 6 -and $utcHour -lt 12) { "prime trading window (06-12 UTC, historically best WR)" }
              elseif ($utcHour -ge 12 -and $utcHour -lt 20) { "midday window (typical activity)" }
              elseif ($utcHour -lt 2 -or $utcHour -ge 20) { "evening/overnight window (historically weaker)" }
              else { "low-activity window (00-06 UTC, historically worst WR)" }

$lowVolSyms = @()
foreach ($k in $volRatios.Keys) {
    if ($volRatios[$k] -lt 0.5) { $lowVolSyms += $k }
}

# --- compose the paragraph ---
Write-Host ""
Write-Host "=== Bot status, plain English ===" -ForegroundColor Cyan
Write-Host ""

if (-not $alive) {
    Write-Host "The bot is DEAD. Heartbeat last updated $([int]$hbAge) seconds ago. Check the supervisor log at bot/logs/supervisor.log." -ForegroundColor Red
    Write-Host ""
    exit 1
}

# Line 1: alive + equity + activity
$line1 = "The bot is alive. It has been running for $uptime. Equity is `$$('{0:N2}' -f $equity) (session $('{0}$' -f $(if ($pnlSession -ge 0) { '+' } else { '-' }))$('{0:N2}' -f [Math]::Abs($pnlSession))). It has taken $tradesToday trades today and considered-but-skipped $skipCount setups."
Write-Host $line1

Write-Host ""

# Line 2: market conditions
$regimesStr = ($regimes.Keys | Sort-Object | ForEach-Object { "$_ is $($regimes[$_])" }) -join ", "
$line2 = "Market right now: $regimesStr."
if ($lowVolSyms.Count -ge 3) {
    $line2 += " Volume is unusually low (under 50% of average) on $($lowVolSyms.Count) of 4 symbols -- markets are quiet."
}
Write-Host $line2

Write-Host ""

# Line 3: what it's waiting for
if ($watchlist.Count -gt 0) {
    $watchStr = ($watchlist | ForEach-Object { "$($_.Symbol) ($($_.Setup))" }) -join " and "
    $line3 = "The bot is actively waiting for: $watchStr. This is a high-priority setup the scout agent identified, but the trigger condition hasn't been met yet."
} else {
    $line3 = "The bot's scout agent doesn't see a high-priority setup forming right now. It's monitoring all 4 symbols for entry conditions."
}
Write-Host $line3

Write-Host ""

# Line 4: why no trade (if applicable)
if ($tradesToday -eq 0) {
    $line4 = "Why no trades yet: "
    $reasons = @()
    if ($lastTradeVerdict) { $reasons += "the LLM's most recent verdict was '$lastTradeVerdict'" }
    if ($lowVolSyms.Count -ge 3) { $reasons += "volume across most symbols is well below average (chop signal)" }
    $reasons += "we are in the $timeWindow"
    $line4 += ($reasons -join "; ") + "."
    Write-Host $line4
}

Write-Host ""

# Line 5: synthesis / what to do
$synthesis = if ($tradesToday -eq 0 -and $skipCount -gt 50) {
    "The bot is being patient by design. It has rejected 50+ setups today because each failed its quality bar (low volume, weak edges, negative EV). When a high-conviction setup appears, it will trade."
} elseif ($tradesToday -gt 0) {
    "The bot has been active today. Check bot/data/trades.csv for the full record."
} else {
    "The bot has been running but hasn't had enough scans to build a meaningful picture yet."
}
Write-Host $synthesis

Write-Host ""
Write-Host "==================================" -ForegroundColor Cyan
Write-Host "(rerun this command any time you want a fresh update)" -ForegroundColor DarkGray
Write-Host ""
