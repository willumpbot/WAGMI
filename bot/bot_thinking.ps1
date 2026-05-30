# WAGMI Bot -- Live LLM thinking view (v3)
# Comprehensive diagnosis + alpha understanding for the visual learner.
# Refresh every 10s. Ctrl+C to exit. Use -Once for single snapshot.
#
# Sections (top to bottom):
#   STATUS         - alive/dead, equity, PnL today, trades today, uptime
#   RISK           - CB headroom, consecutive losses, daily loss %
#   TIMING         - is now a historically good trading window?
#   MARKET         - price + 24h% + vol ratio + regime + ADX + ATR% per symbol
#   EXPECTATIONS   - what each symbol needs to fire; distance to trigger
#   DECISION CHAIN - last full Regime->Trade->Risk->Critic with REASONING
#   AGENT HEALTH   - latency + success rate per agent, model used
#   SIGNAL FLOW    - strategy fire counts, direction split, confidence dist
#   ALPHA EDGES    - 6 shadow edges, status, last seen
#   GRADUATED RULES- learned rules currently active
#   COUNTERFACTUALS- recent skips with hindsight (did skip prove right?)
#   RECENT SKIPS   - last 5 with full reasoning
#   WHY NO TRADE   - plain-English synthesis

param(
    [switch]$Once,
    [int]$RefreshSeconds = 10
)

$ErrorActionPreference = "Continue"
$BotDir = "C:\Users\vince\WAGMI\bot"
$LogsDir = Join-Path $BotDir "logs"
$DataDir = Join-Path $BotDir "data"
$LlmDir  = Join-Path $DataDir "llm"

# ----- helpers -----

function Get-LatestBotLog {
    Get-ChildItem (Join-Path $LogsDir "bot_*.log") -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
}

function Get-BotStatus {
    $hb = Join-Path $DataDir "bot_heartbeat.txt"
    $py = Get-Process python -ErrorAction SilentlyContinue | Sort-Object StartTime | Select-Object -First 1
    $status = [PSCustomObject]@{
        Alive = $false; PID = "?"; HeartbeatAgeS = -1; Uptime = "?"
        EquityUSD = $null; PeakUSD = $null
    }
    if (Test-Path $hb) {
        $status.HeartbeatAgeS = ((Get-Date) - (Get-Item $hb).LastWriteTime).TotalSeconds
        $status.Alive = $status.HeartbeatAgeS -lt 90
    }
    if ($py) {
        $status.PID = $py.Id
        $span = (Get-Date) - $py.StartTime
        $status.Uptime = "{0}h{1:00}m" -f [int]$span.TotalHours, $span.Minutes
    }
    $eqFile = Join-Path $DataDir "risk_equity_state.json"
    if (Test-Path $eqFile) {
        try {
            $eq = Get-Content $eqFile -Raw | ConvertFrom-Json
            $status.EquityUSD = [double]$eq.equity
            $status.PeakUSD = [double]$eq.peak_equity
        } catch {}
    }
    return $status
}

function Get-RiskState {
    $f = Join-Path $DataDir "circuit_breaker_state.json"
    if (-not (Test-Path $f)) { return $null }
    try { return Get-Content $f -Raw | ConvertFrom-Json } catch { return $null }
}

function Get-MarketSnapshot {
    $log = Get-LatestBotLog
    $market = @{}
    foreach ($sym in @("BTC","ETH","SOL","HYPE")) {
        $market[$sym] = [PSCustomObject]@{
            Symbol = $sym; Price = $null; Regime = "?"
            ADX = $null; ATRpct = $null; VolRatio = $null
        }
    }
    if (-not $log) { return $market }
    $tail = Get-Content $log.FullName -Tail 2500
    [array]::Reverse($tail)
    foreach ($line in $tail) {
        if ($line -match '\[REGIME\]\s+(BTC|ETH|SOL|HYPE):\s+(\w+)\s+\|\s+ADX=([\d.]+)\s+ATR%=([\d.]+)') {
            $sym = $Matches[1]
            if (-not $market[$sym].Regime -or $market[$sym].Regime -eq "?") {
                $market[$sym].Regime = $Matches[2]
                $market[$sym].ADX = [double]$Matches[3]
                $market[$sym].ATRpct = [double]$Matches[4]
            }
        }
        if ($line -match '^\s*(BTC|ETH|SOL|HYPE)\s+\|\s+\w+\s+\|\s+price=\s*\$([\d,.]+)') {
            $sym = $Matches[1]
            if (-not $market[$sym].Price) {
                $market[$sym].Price = [double]($Matches[2] -replace ',','')
            }
        }
        if ($line -match 'MARKET UPDATE') {
            foreach ($sym in @("BTC","ETH","SOL","HYPE")) {
                if ($line -match "$sym\s+\`$([\d,.]+)\s+vol=([\d.]+)x") {
                    if (-not $market[$sym].Price) {
                        $market[$sym].Price = [double]($Matches[1] -replace ',','')
                    }
                    if (-not $market[$sym].VolRatio) {
                        $market[$sym].VolRatio = [double]$Matches[2]
                    }
                }
            }
        }
        if ($line -match '\[(BTC|ETH|SOL|HYPE)\]\s+Volume ratio\s+([\d.]+)') {
            $sym = $Matches[1]
            if (-not $market[$sym].VolRatio) {
                $market[$sym].VolRatio = [double]$Matches[2]
            }
        }
    }
    return $market
}

function Get-SignalActivity {
    $log = Get-LatestBotLog
    if (-not $log) { return $null }
    $allLines = Get-Content $log.FullName
    $stratCount = @{}
    $dirCount = @{ "BUY" = 0; "SELL" = 0 }
    $symCount = @{ "BTC" = 0; "ETH" = 0; "SOL" = 0; "HYPE" = 0 }
    $confs = @()
    $multiStrat = 0
    foreach ($line in $allLines) {
        if ($line -match 'Strategy map: fired=\[([^\]]+)\] silent') {
            $fired = $Matches[1] -split "', '" | ForEach-Object { ($_ -replace "['\[\] ]", '') }
            foreach ($s in $fired) {
                if ($s) {
                    if (-not $stratCount.ContainsKey($s)) { $stratCount[$s] = 0 }
                    $stratCount[$s] += 1
                }
            }
            if ($fired.Count -ge 2) { $multiStrat += 1 }
        }
        if ($line -match '\[(BTC|ETH|SOL|HYPE)\][^\[]+(BUY|SELL).*conf=(\d+)') {
            $symCount[$Matches[1]] += 1
            $dirCount[$Matches[2]] += 1
            $confs += [int]$Matches[3]
        }
    }
    $highConf = ($confs | Where-Object { $_ -ge 65 }).Count
    return [PSCustomObject]@{
        StratCount = $stratCount; DirCount = $dirCount; SymCount = $symCount
        Total = $confs.Count; HighConf = $highConf; MultiStrategy = $multiStrat
    }
}

function Get-LatestPipelineChain {
    $f = Join-Path $LlmDir "agent_performance.jsonl"
    if (-not (Test-Path $f)) { return $null }
    $lines = Get-Content $f -Tail 60
    [array]::Reverse($lines)
    $chain = [ordered]@{ regime=$null; quant=$null; trade=$null; risk=$null; critic=$null }
    $symbol = "?"; $pipelineId = $null
    foreach ($line in $lines) {
        try {
            $d = $line | ConvertFrom-Json
            if ($d.type -ne "decision") { continue }
            $role = "$($d.agent_role)".ToLower()
            if ($chain.Contains($role) -and -not $chain[$role]) {
                $chain[$role] = $d
                if ($symbol -eq "?" -and $d.symbol -and $d.symbol -ne "GLOBAL") {
                    $symbol = $d.symbol
                    $pipelineId = $d.pipeline_id
                }
            }
        } catch {}
    }
    return [PSCustomObject]@{
        Symbol = $symbol; PipelineId = $pipelineId; Roles = $chain
    }
}

function Get-LatestScoutWatchlist {
    $f = Join-Path $LlmDir "agent_performance.jsonl"
    if (-not (Test-Path $f)) { return @() }
    $lines = Get-Content $f -Tail 150
    [array]::Reverse($lines)
    foreach ($line in $lines) {
        try {
            $d = $line | ConvertFrom-Json
            if ($d.agent_role -eq "scout" -and $d.reasoning_summary) {
                $text = "$($d.reasoning_summary)"
                $entries = @()
                $watchPattern = "'symbol':\s*'([^']+)'.*?'priority':\s*'([^']+)'.*?'setup_forming':\s*'([^']*)'.*?'pre_thesis':\s*'([^']{0,300})"
                $regexMatches = [regex]::Matches($text, $watchPattern)
                foreach ($m in $regexMatches) {
                    $entries += [PSCustomObject]@{
                        Symbol = $m.Groups[1].Value; Priority = $m.Groups[2].Value
                        Setup = $m.Groups[3].Value; Thesis = $m.Groups[4].Value
                    }
                }
                return ,$entries
            }
        } catch {}
    }
    return @()
}

function Get-AgentHealth {
    $f = Join-Path $LlmDir "agent_performance.jsonl"
    if (-not (Test-Path $f)) { return @{} }
    $lines = Get-Content $f -Tail 200
    $health = @{}
    foreach ($line in $lines) {
        try {
            $d = $line | ConvertFrom-Json
            if ($d.type -ne "decision") { continue }
            $role = "$($d.agent_role)"
            if (-not $health.ContainsKey($role)) {
                $health[$role] = [PSCustomObject]@{
                    Role = $role; Calls = 0; LastModel = "?"; TotalLatencyMs = 0; AvgConf = 0
                    Confs = @()
                }
            }
            $health[$role].Calls += 1
            $health[$role].LastModel = "$($d.model_used)"
            if ($d.latency_ms) { $health[$role].TotalLatencyMs += [int]$d.latency_ms }
            if ($d.confidence -ne $null) { $health[$role].Confs += [double]$d.confidence }
        } catch {}
    }
    foreach ($k in $health.Keys) {
        if ($health[$k].Calls -gt 0) {
            $health[$k] | Add-Member -NotePropertyName AvgLatencyMs -NotePropertyValue ([int]($health[$k].TotalLatencyMs / $health[$k].Calls)) -Force
        }
        if ($health[$k].Confs.Count -gt 0) {
            $health[$k].AvgConf = ($health[$k].Confs | Measure-Object -Average).Average
        }
    }
    return $health
}

function Get-RecentSkips {
    param([int]$Limit = 8)
    $f = Join-Path $LlmDir "counterfactual_pending.jsonl"
    if (-not (Test-Path $f)) { return @() }
    $lines = Get-Content $f -Tail $Limit
    $items = @()
    foreach ($line in $lines) {
        try {
            $d = $line | ConvertFrom-Json
            $items += [PSCustomObject]@{
                Time = $d.created_at.Substring(11,8)
                Symbol = $d.symbol; Side = $d.side
                EntryPrice = [double]$d.entry_price
                Confidence = [double]$d.confidence
                Reason = $d.skip_reason; Regime = $d.regime
                Resolved = [bool]$d.resolved
                WouldHitTP1 = $d.would_hit_tp1
                WouldHitSL = $d.would_hit_sl
            }
        } catch {}
    }
    return $items
}

function Get-ResolvedCounterfactuals {
    # Count how many skip-counterfactuals were resolved and what the outcome was
    $f = Join-Path $LlmDir "..\counterfactuals\scenarios.json"
    $fAlt = Join-Path $DataDir "counterfactuals\scenarios.json"
    $path = if (Test-Path $f) { $f } elseif (Test-Path $fAlt) { $fAlt } else { return $null }
    try {
        $data = Get-Content $path -Raw | ConvertFrom-Json
        $resolved = 0; $tpHits = 0; $slHits = 0
        foreach ($scenarios in $data.PSObject.Properties.Value) {
            if ($scenarios -is [System.Array]) {
                foreach ($s in $scenarios) {
                    if ($s.resolved) {
                        $resolved += 1
                        if ($s.would_hit_tp1) { $tpHits += 1 }
                        if ($s.would_hit_sl) { $slHits += 1 }
                    }
                }
            }
        }
        return [PSCustomObject]@{
            Resolved = $resolved; TpHits = $tpHits; SlHits = $slHits
        }
    } catch { return $null }
}

function Get-GraduatedRules {
    $f = Join-Path $LlmDir "graduated_rules.json"
    if (-not (Test-Path $f)) { return @() }
    try {
        $data = Get-Content $f -Raw | ConvertFrom-Json
        $rules = @()
        # graduated_rules.json structure may vary; try common shapes
        if ($data.rules) {
            foreach ($r in $data.rules) {
                $rules += [PSCustomObject]@{
                    Name = "$($r.name)"; Confidence = $r.confidence; Action = "$($r.action)"
                    Applications = $r.applications
                }
            }
        }
        return $rules | Select-Object -First 8
    } catch { return @() }
}

# Mirror of bot/strategies/ensemble.py _SHADOW_EDGES
$ShadowEdges = @(
    @{ Symbol="ETH";  Side="BUY";  Strategy="regime_trend";       WR=100;  N=135; Floor=0.90 }
    @{ Symbol="HYPE"; Side="BUY";  Strategy="bollinger_squeeze";  WR=61.2; N=196; Floor=0.80 }
    @{ Symbol="SOL";  Side="SELL"; Strategy="multi_tier_quality"; WR=72.1; N=68;  Floor=0.80 }
    @{ Symbol="SOL";  Side="SELL"; Strategy="bollinger_squeeze";  WR=72.1; N=68;  Floor=0.80 }
    @{ Symbol="BTC";  Side="BUY";  Strategy="regime_trend";       WR=55.1; N=78;  Floor=0.65 }
    @{ Symbol="HYPE"; Side="BUY";  Strategy="regime_trend";       WR=80.0; N=40;  Floor=0.72 }
)

function Get-EdgeStatus {
    param($market, $watchlist)
    $statuses = @()
    foreach ($e in $ShadowEdges) {
        $watching = @($watchlist) | Where-Object { $_ -and $_.Symbol -eq $e.Symbol }
        $regime = if ($market.ContainsKey($e.Symbol)) { $market[$e.Symbol].Regime } else { "?" }

        $status = "INACTIVE"; $color = "DarkGray"; $note = ""
        if ($watching) {
            $status = "PRIMING"; $color = "Yellow"
            $note = "scout sees setup forming"
        } elseif ($regime -match "trending_bull|trend") {
            if ($e.Side -eq "BUY") {
                $status = "regime ok"; $color = "Gray"
                $note = "trend supports direction, no signal fire yet"
            } else {
                $status = "wrong direction"; $color = "DarkRed"
                $note = "trending up; SELL edge would fight regime"
            }
        } elseif ($regime -match "consolidat|range") {
            $status = "regime weak"; $color = "DarkGray"
            $note = "consolidation; no directional edge"
        }
        $statuses += [PSCustomObject]@{
            Symbol = $e.Symbol; Side = $e.Side; Strategy = $e.Strategy
            WR = $e.WR; N = $e.N; Status = $status; Color = $color
            Regime = $regime; Note = $note
        }
    }
    return $statuses
}

# ----- formatters / rendering -----

function Format-Money { param([double]$v) "{0:N2}" -f $v }
function Format-Price { param([double]$v) if ($v -ge 1000) { "{0:N1}" -f $v } else { "{0:N4}" -f $v } }

function Get-TradingWindow {
    # Reports indicate 06:00-12:00 UTC = best WR (71-75%), 00:00-06:00 = worst
    $h = (Get-Date).ToUniversalTime().Hour
    if ($h -ge 6 -and $h -lt 12) {
        return [PSCustomObject]@{ Label = "PRIME"; Color = "Green"; Note = "06:00-12:00 UTC = highest historical WR (71-75%)" }
    } elseif ($h -ge 12 -and $h -lt 20) {
        return [PSCustomObject]@{ Label = "STANDARD"; Color = "Yellow"; Note = "midday/afternoon UTC; mixed historical WR" }
    } elseif ($h -ge 20 -or $h -lt 2) {
        return [PSCustomObject]@{ Label = "LOWER"; Color = "Yellow"; Note = "evening UTC; weaker historical performance" }
    } else {
        return [PSCustomObject]@{ Label = "AVOID"; Color = "Red"; Note = "00:00-06:00 UTC = lowest historical WR" }
    }
}

function Render-Banner { param([string]$Title)
    Write-Host ""
    Write-Host (" === $Title ===") -ForegroundColor Yellow
}

function Synthesize-WhyNoTrade {
    param($status, $market, $watchlist, $chain, $risk)
    $reasons = @()
    if (-not $status.Alive) { return @("Bot is DEAD - heartbeat stale. Check supervisor.log.") }

    # Recent decision chain reasoning
    if ($chain -and $chain.Roles -and $chain.Roles["trade"]) {
        $td = "$($chain.Roles["trade"].reasoning_summary)"
        if ($td.Length -gt 200) { $td = $td.Substring(0,200) + "..." }
        $reasons += "Last Trade-agent verdict on $($chain.Symbol): $td"
    }

    # Are we in prime trading window?
    $window = Get-TradingWindow
    if ($window.Label -eq "AVOID") {
        $reasons += "Currently in low-WR UTC window (00:00-06:00) - LLM tends to be more selective here."
    }

    # Are any symbols in priming state?
    $primingSyms = @($watchlist) | Where-Object { $_.Priority -eq "high" } | ForEach-Object { $_.Symbol }
    if ($primingSyms.Count -gt 0) {
        $reasons += "Scout is priming on $($primingSyms -join ', ') - waiting for trigger (compression activation, BB squeeze, etc.)"
    }

    # Volume check
    $lowVol = @()
    foreach ($sym in @("BTC","ETH","SOL","HYPE")) {
        if ($market[$sym].VolRatio -and $market[$sym].VolRatio -lt 0.5) { $lowVol += $sym }
    }
    if ($lowVol.Count -ge 2) {
        $reasons += "Volume is low (<50% of avg) on $($lowVol -join ', ') - LLM weighs this as chop/no-edge."
    }

    # CB headroom
    if ($risk -and $risk.consecutive_losses) {
        if ($risk.consecutive_losses -ge 7) {
            $reasons += "Consecutive losses at $($risk.consecutive_losses)/10 - LLM tightening up to preserve CB headroom."
        }
    }

    if ($reasons.Count -eq 0) {
        $reasons += "All gates open, market conditions OK - LLM just hasn't seen a high-conviction setup. Bot is being patient."
    }
    return $reasons
}

function Render {
    Clear-Host
    Write-Host ""
    Write-Host ("=" * 90) -ForegroundColor Cyan
    Write-Host (" WAGMI BOT THINKING                                       $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')") -ForegroundColor Cyan
    Write-Host ("=" * 90) -ForegroundColor Cyan

    # 1. STATUS
    $s = Get-BotStatus
    $aliveStr = if ($s.Alive) { "ALIVE" } else { "DEAD" }
    $aliveColor = if ($s.Alive) { "Green" } else { "Red" }
    $hbStr = if ($s.HeartbeatAgeS -ge 0) { "{0:N0}s ago" -f $s.HeartbeatAgeS } else { "n/a" }
    $eqStr = if ($s.EquityUSD) { "`$" + (Format-Money $s.EquityUSD) } else { "?" }
    $peakStr = if ($s.PeakUSD) { "`$" + (Format-Money $s.PeakUSD) } else { "?" }
    $pnlToday = if ($s.EquityUSD) { $s.EquityUSD - 5000 } else { 0 }
    $pnlStr = "{0}`${1:N2}" -f $(if ($pnlToday -ge 0) { "+" } else { "" }), $pnlToday
    Write-Host ""
    Write-Host (" STATUS  ") -NoNewline
    Write-Host $aliveStr -NoNewline -ForegroundColor $aliveColor
    Write-Host ("   PID $($s.PID)   Uptime $($s.Uptime)   Heartbeat $hbStr")
    Write-Host (" EQUITY  $eqStr  (peak $peakStr, session $pnlStr)")

    # 2. RISK STATE
    $risk = Get-RiskState
    Render-Banner "RISK STATE"
    if ($risk) {
        $cl = if ($risk.consecutive_losses) { [int]$risk.consecutive_losses } else { 0 }
        $maxCl = 10
        $clBar = "#" * $cl + "." * ($maxCl - $cl)
        $clColor = if ($cl -ge 8) { "Red" } elseif ($cl -ge 5) { "Yellow" } else { "Green" }
        Write-Host ("   Consecutive losses:  [{0}] {1}/{2}" -f $clBar, $cl, $maxCl) -ForegroundColor $clColor
        $dpnl = if ($risk.daily_pnl_pct) { [double]$risk.daily_pnl_pct } else { 0 }
        $dThresh = 7
        $dpcolor = if ($dpnl -le -5) { "Red" } elseif ($dpnl -le -3) { "Yellow" } else { "Green" }
        Write-Host ("   Daily PnL %: {0:N2}% / -{1}% CB threshold" -f $dpnl, $dThresh) -ForegroundColor $dpcolor
        if ($risk.tripped) {
            Write-Host "   *** CIRCUIT BREAKER TRIPPED ***" -ForegroundColor Red
        }
    } else {
        Write-Host "   (no CB state file)" -ForegroundColor DarkGray
    }

    # 3. TIMING
    $window = Get-TradingWindow
    Render-Banner "TIMING WINDOW"
    Write-Host ("   Current window: $($window.Label) ($($window.Note))") -ForegroundColor $window.Color

    # 4. MARKET
    $market = Get-MarketSnapshot
    Render-Banner "MARKET (latest scan)"
    Write-Host ("   {0,-5} {1,12}  {2,-8} {3,-15}  {4,5}  {5,8}" -f "SYM","PRICE","VOL/AVG","REGIME","ADX","ATR%")
    foreach ($sym in @("BTC","ETH","SOL","HYPE")) {
        $m = $market[$sym]
        $priceStr = if ($m.Price) { "`$" + (Format-Price $m.Price) } else { "?" }
        $volStr = if ($m.VolRatio) { "{0:N2}x" -f $m.VolRatio } else { "?" }
        $adxStr = if ($m.ADX) { "{0:N0}" -f $m.ADX } else { "?" }
        $atrStr = if ($m.ATRpct) { "{0:N3}%" -f $m.ATRpct } else { "?" }
        $color = if ($m.Regime -match "trending_bull") { "Green" }
                 elseif ($m.Regime -match "trend") { "Green" }
                 elseif ($m.Regime -match "consolidat") { "Yellow" }
                 elseif ($m.Regime -match "range") { "Gray" }
                 else { "White" }
        Write-Host ("   {0,-5} {1,12}  {2,-8} {3,-15}  {4,5}  {5,8}" -f $sym, $priceStr, $volStr, $m.Regime, $adxStr, $atrStr) -ForegroundColor $color
    }

    # 5. EXPECTATIONS
    $watchlist = Get-LatestScoutWatchlist
    Render-Banner "LLM EXPECTATIONS (what each symbol needs to fire)"
    $watchedSyms = @()
    if ($watchlist) {
        foreach ($w in $watchlist) {
            $priColor = if ($w.Priority -eq "high") { "Green" } else { "White" }
            $marker = if ($w.Priority -eq "high") { ">>>" } else { "   " }
            Write-Host ("   $marker [{0,4}] {1,-5}  setup: {2}" -f $w.Priority.ToUpper(), $w.Symbol, $w.Setup) -ForegroundColor $priColor
            $thesis = $w.Thesis -replace "`r?`n", " "
            if ($thesis.Length -gt 110) { $thesis = $thesis.Substring(0,110) + "..." }
            Write-Host ("         $thesis") -ForegroundColor DarkGray
            $watchedSyms += $w.Symbol
        }
    }
    foreach ($sym in @("BTC","ETH","SOL","HYPE")) {
        if ($watchedSyms -notcontains $sym) {
            $regime = "$($market[$sym].Regime)"
            $note = switch -Regex ($regime) {
                'consolidat' { "consolidating - waiting for breakout (>1% directional move)" }
                'range'      { "ranging - no directional edge available" }
                'trending_bull' { "trending up - waiting for pullback OR confluence entry" }
                'trend'      { "trending - no clean entry setup yet" }
                default      { "monitoring" }
            }
            Write-Host ("       [    ] {0,-5}  {1}" -f $sym, $note) -ForegroundColor DarkGray
        }
    }

    # 6. DECISION CHAIN
    Render-Banner "DECISION CHAIN (most recent full pipeline)"
    $chain = Get-LatestPipelineChain
    if ($chain -and $chain.Symbol -ne "?") {
        Write-Host ("   Subject: $($chain.Symbol)  pipeline=$($chain.PipelineId)")
        foreach ($role in @("regime","quant","trade","risk","critic")) {
            $d = $chain.Roles[$role]
            if ($d) {
                $dec = "$($d.decision)"
                $r = "$($d.reasoning_summary)" -replace "`r?`n", " "
                if ($r.Length -gt 130) { $r = $r.Substring(0,130) + "..." }
                $color = if ($dec -match "go|proceed|enter|approve") { "Green" }
                         elseif ($dec -match "skip|flat|monitor") { "Yellow" }
                         elseif ($dec -match "flip|reverse|veto|reduce") { "Magenta" }
                         else { "White" }
                Write-Host ("   {0,-7}  {1,-22}" -f $role.ToUpper(), $dec) -NoNewline -ForegroundColor $color
                Write-Host ("  $r") -ForegroundColor DarkGray
            } else {
                Write-Host ("   {0,-7}  (not in this cycle)" -f $role.ToUpper()) -ForegroundColor DarkGray
            }
        }
    } else {
        Write-Host "   (no complete pipeline yet)" -ForegroundColor DarkGray
    }

    # 7. AGENT HEALTH
    $health = Get-AgentHealth
    Render-Banner "AGENT HEALTH (last 200 calls)"
    Write-Host ("   {0,-9}  {1,5}  {2,8}  {3,-22}  {4,9}" -f "AGENT","CALLS","AVGLAT","MODEL","AVGCONF")
    foreach ($role in @("regime","trade","risk","critic","quant","scout")) {
        if ($health.ContainsKey($role)) {
            $h = $health[$role]
            $latColor = if ($h.AvgLatencyMs -gt 30000) { "Red" } elseif ($h.AvgLatencyMs -gt 15000) { "Yellow" } else { "Green" }
            $conf = "{0:N2}" -f $h.AvgConf
            Write-Host ("   {0,-9}  {1,5}  {2,7}ms  {3,-22}  {4,9}" -f $role, $h.Calls, $h.AvgLatencyMs, $h.LastModel, $conf) -ForegroundColor $latColor
        } else {
            Write-Host ("   {0,-9}  (no calls)" -f $role) -ForegroundColor DarkGray
        }
    }

    # 8. SIGNAL FLOW
    $sig = Get-SignalActivity
    Render-Banner "SIGNAL FLOW (today)"
    if ($sig) {
        $highPct = if ($sig.Total -gt 0) { $sig.HighConf * 100.0 / $sig.Total } else { 0 }
        Write-Host ("   Total: {0}    >=65% conf: {1} ({2:N0}%)    Multi-strategy: {3}" -f $sig.Total, $sig.HighConf, $highPct, $sig.MultiStrategy)
        Write-Host ("   Direction: BUY {0}  SELL {1}    By symbol: BTC {2}  ETH {3}  SOL {4}  HYPE {5}" -f $sig.DirCount.BUY, $sig.DirCount.SELL, $sig.SymCount.BTC, $sig.SymCount.ETH, $sig.SymCount.SOL, $sig.SymCount.HYPE)
        $stratTop = $sig.StratCount.GetEnumerator() | Sort-Object Value -Descending | Select-Object -First 5
        $stratStr = ($stratTop | ForEach-Object { "$($_.Key):$($_.Value)" }) -join "  "
        Write-Host ("   Top strategies: $stratStr") -ForegroundColor DarkGray
    } else {
        Write-Host "   (no signal data parsed yet)" -ForegroundColor DarkGray
    }

    # 9. ALPHA EDGES
    Render-Banner "ALPHA EDGES (6 validated setups, status now)"
    $edges = Get-EdgeStatus -market $market -watchlist $watchlist
    foreach ($e in $edges) {
        Write-Host ("   {0,-5} {1,-5} via {2,-22}  {3,5}% WR / n={4,3}  -> {5,-15}  {6}" -f $e.Symbol, $e.Side, $e.Strategy, $e.WR, $e.N, $e.Status, $e.Note) -ForegroundColor $e.Color
    }

    # 10. COUNTERFACTUALS
    $cf = Get-ResolvedCounterfactuals
    Render-Banner "COUNTERFACTUAL OUTCOMES (skipped trades, resolved)"
    if ($cf) {
        Write-Host ("   Resolved: $($cf.Resolved)   Would-have-won (TP1 hit): $($cf.TpHits)   Would-have-lost (SL hit): $($cf.SlHits)")
        if ($cf.Resolved -gt 0) {
            $skipQuality = if (($cf.TpHits + $cf.SlHits) -gt 0) { 1.0 - ($cf.TpHits / [double]($cf.TpHits + $cf.SlHits)) } else { 0 }
            $skipQualityPct = $skipQuality * 100
            $color = if ($skipQualityPct -ge 60) { "Green" } elseif ($skipQualityPct -ge 40) { "Yellow" } else { "Red" }
            Write-Host ("   Skip quality (% skips that would have lost):  {0:N0}%" -f $skipQualityPct) -ForegroundColor $color
        }
    } else {
        Write-Host "   (no resolved counterfactuals yet)" -ForegroundColor DarkGray
    }

    # 11. RECENT SKIPS
    Render-Banner "RECENT SKIPS (last 5)"
    $skips = Get-RecentSkips -Limit 5
    if ($skips.Count -gt 0) {
        foreach ($k in $skips) {
            Write-Host ("   {0}  {1,-5} {2,-5} @ `${3,9:N2}  conf={4,5:N1}%  regime={5,-13}  {6}" -f $k.Time, $k.Symbol, $k.Side, $k.EntryPrice, $k.Confidence, $k.Regime, $k.Reason) -ForegroundColor DarkGray
        }
    } else {
        Write-Host "   (no recent skips)" -ForegroundColor DarkGray
    }

    # 12. WHY NO TRADE
    Render-Banner "WHY NO TRADE RIGHT NOW (plain-English synthesis)"
    $reasons = Synthesize-WhyNoTrade -status $s -market $market -watchlist $watchlist -chain $chain -risk $risk
    foreach ($r in $reasons) {
        Write-Host ("   * $r") -ForegroundColor White
    }

    Write-Host ""
    Write-Host ("=" * 90) -ForegroundColor DarkGray
    if (-not $Once) {
        Write-Host (" Refresh: {0}s   |   Ctrl+C exit" -f $RefreshSeconds) -ForegroundColor DarkGray
    }
    Write-Host ""
}

if ($Once) { Render } else { while ($true) { Render; Start-Sleep -Seconds $RefreshSeconds } }
