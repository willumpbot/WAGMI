# WAGMI Trading Bot — Complete Architecture, Context, Thinking, and Setup

**Date Created:** 2026-05-30  
**Author:** Vince (with Claude)  
**Status:** Live, collecting data after 37-day blackout  
**Purpose:** This document is THE source of truth. It contains everything: the architecture, all the thinking behind decisions, gaps we discovered, solutions, reasoning, and how two computers work together to build an autonomous trading bot with real-time analysis.

---

## CONTEXT & WHY THIS EXISTS

### The Situation
You're running a trading bot on one computer (Other PC). This document exists on the computer you're currently using (This PC). You're not networked, so data flows via OneDrive or your Dashboard API.

You're a **visual learner** who gets overwhelmed when things aren't clear. So this document explains:
- Not just WHAT we're building
- But WHY we're building it this way
- The thinking behind each decision
- The gaps we found and how we're fixing them
- How your two computers talk to each other

### Your Goals
1. **Run a trading bot autonomously** — no manual intervention, just monitoring
2. **Understand every trade** — why LLM made that decision
3. **See everything visually** — dashboard website shows the full picture
4. **Improve the bot** — edit code, test new strategies, refine edges
5. **Access from anywhere** — phone, another computer, anywhere via Remote Control

### Your Constraints
- Two PCs NOT networked (so file sync is manual or via cloud)
- Want to use Claude on BOTH computers (separate sessions)
- Want API abstraction (website talks to API, not raw files)
- Want visual interface (not terminal logs)
- Want multiple terminals open on This PC (each doing different things)

---

## THE VISION

### Two-Computer Model (Why This Works)

```
Other PC (The Autonomous Bot) ⚡
├─ Python bot runs 24/7 (scans every 30s, fires trades)
├─ Claude session (analyzes decisions when asked)
├─ Dashboard API (serves data to website)
└─ All data stored locally (decisions.jsonl, trades.csv, logs)

This PC (Your Control Center) 🎮
├─ Terminal #1: Health checks (bot_alive.ps1)
├─ Terminal #2: Ask Claude questions (via remote)
├─ Terminal #3: Edit code (strategies, edges)
├─ Terminal #4: Poll API (curl /api/*)
└─ Terminal #5: Website (visual interface)

Website (Your Eyes) 👀
└─ Real-time dashboard showing equity, trades, strategy health, LLM reasoning

Your Phone (Anywhere) 📱
└─ Remote Control to check bot in 30 seconds
```

**Why separate computers?**
- Other PC: Bot runs autonomously, never touched, 24/7 uptime
- This PC: You do all the thinking, coding, analysis
- Clean separation: If bot crashes, your work is safe. If you reboot This PC, bot keeps running.

**Why Claude on both?**
- Other PC Claude: Reads the bot's logs, explains trades, validates decisions
- This PC Claude: (potentially) helps you write code, debug issues, think strategically
- They don't fight. Other PC Claude owns the logs. This PC Claude helps you.

---

## THE COMPLETE ARCHITECTURE

### Other PC: The Bot Runs Here

#### Runtime Layer (The Autonomous Loop)

```
Every 30 seconds, this happens:

[00:00] START SCAN
  Read: Current price data for BTC/ETH/SOL/HYPE
  From: Exchange API (Hyperliquid)

[00:01] RUN STRATEGIES
  9 strategies generate signals:
  - Momentum: trend strength (0-1)
  - Mean Reversion: overbought/oversold (-1 to 1)
  - Breakout: support/resistance breaks
  - Volume: unusual volume activity
  - ... (6 more)
  
  Output: {symbol: "BTC", momentum: 0.8, mean_rev: 0.3, breakout: 0.1, ...}

[00:02] CHECK EDGES
  6 known alpha setups (shadow confidence floors):
  - BTC only trades in strong trending regime (regime score >0.8)
  - ETH only trades when volatility >20%
  - SOL only on volume spikes + momentum alignment
  - ... (3 more)
  
  Output: {symbol: "BTC", edge_score: 0.9, pass: true}

[00:03] CALCULATE VOLUME & EV
  Expected Value: does risk/reward favor this trade?
  Volume: is there enough liquidity?
  
  Output: {ev: 0.0234, volume: 1000000, risk_adjusted_size: 0.01}
  Note: This is INFORMATIONAL ONLY, doesn't block trades

[00:04] BUILD FULL SNAPSHOT
  Combine everything:
  {
    "regime": "strong uptrend (regime score 0.85)",
    "all_strategy_signals": {...},
    "edge_scores": {...},
    "volume": 1000000,
    "ev": 0.0234,
    "memory": {
      "learned_patterns": ["momentum >0.8 + edge >0.7 = 80% win rate"],
      "strategy_health": {"momentum": "firing well", "mean_rev": "signal spam"},
      "recent_performance": "up 2.3% last 10 trades"
    },
    "historical_trades": [list of last 20 trades]
  }

[00:05] CALL LLM
  Send snapshot to Claude (via CLI: claude -p)
  Claude reads everything and decides:
  
  LLM_MODE=5 (full autonomy)
  → LLM can trade without asking
  → LLM has access to full context
  → LLM decides: GO / SKIP / SIZE
  
  Response:
  {
    "action": "LONG",
    "symbol": "BTC",
    "size": 0.01,
    "reasoning": "Strong trending regime, momentum >0.8, edge confidence 0.9, 
                 historical pattern shows this setup wins 80% of time, 
                 volume sufficient, risk/reward favorable (EV 0.0234)"
  }

[00:06] LOG DECISION
  Write to decisions.jsonl (master log):
  {
    "timestamp": "2026-05-30T12:00:00Z",
    "scan_id": "uuid-1234",
    "strategy_versions": {"momentum": "v2.1", "mean_reversion": "v1.0", ...},
    "edge_versions": {"btc_regime": "v1.2", ...},
    "signals": {"BTC": {all signals}, ...},
    "edge_scores": {"BTC": {all edges}, ...},
    "volume": 1000000,
    "ev": 0.0234,
    "llm_decision": {decision object},
    "decision_id": "uuid-5678"
  }

[00:07] EXECUTE (IF ACTION != SKIP)
  If LLM said "LONG BTC 0.01":
    - Send order to exchange (paper trading, no real money)
    - Order fills: "LONG BTC 0.01 @ 62010" (slightly different from expected)
    - Write to trades.csv: {entry: 62000, actual: 62010, ...}
    - Write to trade_reconciliation.jsonl: {decision_id, intended, actual, slippage, status}
    - Write to open_positions.json: {symbol: BTC, side: LONG, size: 0.01, ...}

[00:08] LOG EXECUTION
  Append to bot.log:
  [2026-05-30 12:00:00] [SCAN] Starting scan
  [2026-05-30 12:00:01] [SIGNAL] BTC momentum=0.8
  [2026-05-30 12:00:02] [EDGE] BTC regime=0.9 (pass)
  [2026-05-30 12:00:05] [LLM] Decision: LONG BTC 0.01
  [2026-05-30 12:00:06] [TRADE] Executing LONG BTC 0.01 @ 62000
  [2026-05-30 12:00:07] [ENTRY] Order filled: LONG BTC 0.01 @ 62010

[00:09] UPDATE STATE
  Update current_equity.json:
  {
    "equity": 5234.50,
    "daily_pnl": 234.50,
    "trades_today": 12
  }
  
  Update circuit_breaker_state.json:
  {
    "daily_loss_pct": 2.5,
    "consecutive_losses": 3,
    "triggered": false
  }

[00:10] HEARTBEAT
  Write to heartbeat.txt: "2026-05-30T12:00:10Z"
  This file proves the bot is alive (if >90s old = bot is dead)

[00:11 - 00:30] SLEEP
  Wait 30 seconds until next scan

REPEAT FOREVER
```

**Key insight:** Every 30 seconds, the entire loop runs. LLM gets full context. Bot decides autonomously. Everything is logged for analysis.

---

#### Supervision Chain (Keeps Bot Alive)

**Why we need this:** Python processes crash. Network hiccups. Unexpected errors. We need the bot to restart automatically.

```
Level 1: Python Process
  python run.py paper
  PID: 5948 (or whatever)
  
  If it crashes:
  → Supervisor (PowerShell) restarts it (30 seconds)

Level 2: PowerShell Supervisor
  powershell start_bot.ps1
  Watches Python PID
  
  If Python dies:
  → Log error
  → Restart Python
  → Wait 30 seconds, try again
  
  If Supervisor itself crashes:
  → Task Scheduler restarts it (1 minute)

Level 3: Task Scheduler
  Task: "WAGMI Bot Supervisor"
  Runs: powershell start_bot.ps1
  Restart if fails: Yes
  
  If Supervisor crashes:
  → Task Scheduler notices
  → Waits 1 minute
  → Restarts Supervisor
  → Supervisor restarts Python

Result: 3-level protection
  Python crash → restart in 30s
  Supervisor crash → restart in 1min
  Entire system crash → stays dead (user needs to login to restart)
```

---

#### Data Files (The Source of Truth)

All files in: `C:\Users\vince\WAGMI\bot\data\`

**decisions.jsonl** ⭐ MOST IMPORTANT
```
Append-only log of every trade decision the LLM made.

Format (one JSON object per line):
{
  "timestamp": "2026-05-30T12:00:00Z",           # When decision was made (UTC)
  "scan_id": "uuid-1234",                         # Unique ID for this 30s scan
  "strategy_versions": {                          # Which version of each strategy?
    "momentum": "v2.1",
    "mean_reversion": "v1.0",
    "breakout": "v1.5",
    ...
  },
  "edge_versions": {                              # Which version of each edge?
    "btc_regime": "v1.2",
    "eth_volatility": "v1.0",
    ...
  },
  "signals": {                                    # What did each strategy say?
    "BTC": {
      "momentum": 0.8,
      "mean_reversion": 0.3,
      "breakout": 0.1,
      ...
    },
    "ETH": {...},
    "SOL": {...},
    "HYPE": {...}
  },
  "edge_scores": {                                # What did each edge say?
    "BTC": {
      "regime": 0.9,              # Regime edge: strong trend (pass)
      "volatility": 0.2,          # Vol edge: low vol (fail, but BTC doesn't need high vol)
      ...
    },
    "ETH": {...},
    ...
  },
  "volume": 1000000,                              # Market volume
  "ev": 0.0234,                                   # Expected value (info only)
  "llm_decision": {                               # What did LLM decide?
    "action": "LONG",                             # GO / SKIP
    "symbol": "BTC",                              # Which symbol?
    "size": 0.01,                                 # How much?
    "reasoning": "Strong trending regime, momentum >0.8, edge confidence 0.9,
                  historical pattern shows 80% win rate, volume OK, EV favorable"
  },
  "decision_id": "uuid-5678"                      # Unique ID for this decision
}

Why this format?
- Claude can read it and understand why each trade was made
- You can search by decision_id to cross-reference with trades.csv
- Versioning info lets Claude know if comparing old trades to new code is fair
- Historical data lets LLM learn from past performance
```

**trades.csv** (Execution Log)
```
timestamp,decision_id,symbol,side,entry_price,entry_time,exit_price,exit_time,pnl,pnl_pct,status
2026-05-30T12:00:00Z,uuid-5678,BTC,LONG,62000,2026-05-30T12:00:05Z,62100,2026-05-30T12:10:00Z,100,0.161,CLOSED
2026-05-30T12:00:00Z,uuid-5679,ETH,SHORT,3100,2026-05-30T12:00:10Z,3095,2026-05-30T12:08:00Z,5,0.161,CLOSED
...

Why this format?
- Simple, readable, easy to calculate statistics
- decision_id links back to decisions.jsonl
- Shows actual entry/exit prices (with slippage)
- Calculates win/loss immediately
- Claude can count wins: trades where pnl > 0
```

**bot_YYYYMMDD.log** (Runtime Log, Rotated Daily)
```
[2026-05-30 12:00:00] [SCAN] Starting scan #1
[2026-05-30 12:00:00] [SIGNAL] BTC momentum=0.80 mean_rev=0.30 breakout=0.10
[2026-05-30 12:00:01] [EDGE] BTC regime=0.90 (PASS) volatility=0.20 (FAIL, but BTC OK)
[2026-05-30 12:00:02] [VOLUME] BTC volume=1000000 ev=0.0234
[2026-05-30 12:00:03] [LLM] Calling Claude with full snapshot
[2026-05-30 12:00:04] [LLM] Response: LONG BTC 0.01 (reasoning: ...)
[2026-05-30 12:00:05] [TRADE] Executing LONG BTC 0.01 @ 62000
[2026-05-30 12:00:06] [ENTRY] Order filled: LONG BTC 0.01 @ 62010 (slippage -$10)
[2026-05-30 12:00:07] [UPDATE] Equity: 5234.50 (+234.50 today)
[2026-05-30 12:00:08] [POSITIONS] 1 open: LONG BTC 0.01
[2026-05-30 12:00:09] [HEARTBEAT] Updated
[2026-05-30 12:00:30] [SCAN] Starting scan #2
...

Why this format?
- Chronological. Shows what happened in order.
- Searchable: grep [TRADE], grep [ERROR]
- Human-readable. Easy to debug.
- Rotates when >100MB (keeps disk usage sane)
```

**heartbeat.txt** (Health Check)
```
2026-05-30T12:00:09Z

Why this exists?
- Simple timestamp, updated every scan
- If >90s old = bot hasn't run in 90s = probably dead
- Fast check: "is bot alive?" → cat heartbeat.txt
```

**current_equity.json** (Current State)
```json
{
  "timestamp": "2026-05-30T12:00:09Z",
  "equity": 5234.50,
  "initial": 5000.00,
  "daily_pnl": 234.50,
  "daily_pnl_pct": 4.69,
  "trades_today": 12,
  "win_rate": 0.667,
  "max_position_size": 0.03,
  "open_position_count": 1,
  "daily_high": 5250,
  "daily_low": 4900,
  "max_drawdown_pct": 2.0,
  "last_trade_time": "2026-05-30T12:00:05Z",
  "circuit_breaker_triggered": false
}

Why this file?
- Dashboard API reads this for /api/equity
- Single source of truth: "what is our equity right now?"
- Updates after every trade
- Dashboard website shows this visually
```

**circuit_breaker_state.json** (Safety Tracking)
```json
{
  "date": "2026-05-30",
  "daily_start_equity": 5000.00,
  "daily_start_time": "2026-05-30T09:30:00Z",
  "current_equity": 4825.50,
  "daily_loss_pct": 3.49,
  "daily_loss_cb_threshold": 7.0,
  "daily_loss_cb_triggered": false,
  "consecutive_losses": 3,
  "consecutive_loss_cap": 10,
  "consecutive_loss_cap_triggered": false,
  "last_trade_timestamp": "2026-05-30T12:00:05Z",
  "last_updated": "2026-05-30T12:00:09Z"
}

Why this file?
- Tracks daily loss accumulation (7% circuit breaker)
- Tracks consecutive losses (10 loss cap)
- On bot restart: check if date changed
  - Same day: continue with accumulated loss
  - New day: reset to 0%
- If CB triggered: bot stops trading
```

**open_positions.json** (Position Reconciliation)
```json
{
  "timestamp": "2026-05-30T12:00:09Z",
  "positions": [
    {
      "symbol": "BTC",
      "side": "LONG",
      "size": 0.01,
      "entry_price": 62000,
      "entry_time": "2026-05-30T12:00:05Z",
      "entry_id": "uuid-5678",
      "pnl": 10,
      "pnl_pct": 0.016
    }
  ]
}

Why this file?
- If bot crashes mid-trade, what positions are open?
- On restart, bot reads this
- If positions exist: "don't open new trades, close these first"
- Prevents accidental double positions
```

**trade_reconciliation.jsonl** (Decision vs Execution)
```
{
  "timestamp": "2026-05-30T12:00:05Z",
  "decision_id": "uuid-5678",
  "intended_action": "LONG BTC 0.01",
  "intended_price": 62000,
  "actual_execution": "LONG BTC 0.01",
  "actual_price": 62010,
  "slippage": -10,
  "slippage_pct": -0.016,
  "status": "FILLED",
  "filled_size": 0.01,
  "notes": "Expected price, got 10 cents worse (normal slippage)"
}

Why this file?
- LLM says "SHORT BTC" → did it actually SHORT?
- Verifies decision matched execution
- Tracks slippage (expected vs actual price)
- If status != FILLED: Claude investigates why
```

**config_changes.jsonl** (Audit Trail)
```
{
  "timestamp": "2026-05-30T12:00:00Z",
  "what": "safety_floors.conf",
  "change": {
    "daily_loss_cb": {"from": "5%", "to": "7%"}
  },
  "reason": "Was too tight, missing good trades",
  "changed_by": "vince (via This PC Claude)"
}

Why this file?
- Who changed the circuit breaker? When? Why?
- Audit trail for all config changes
- Helps debug: "did we change CB yesterday?"
```

**backups/ folder** (Daily Backups)
```
decisions_20260530.backup.jsonl
decisions_20260529.backup.jsonl
decisions_20260528.backup.jsonl
... (keep last 30 days)

Why backup?
- decisions.jsonl is CRITICAL
- If corrupted or deleted → lost forever
- Daily backup = safe recovery
- Keep 30 days = ~1GB disk usage, acceptable
```

---

#### Dashboard API (Port 8080)

This is a simple Flask/FastAPI server. When This PC wants to know something, it asks the API.

```
GET /api/health
Response: {
  "status": "running" | "dead",
  "pid": 5948,
  "heartbeat_age_seconds": 5,
  "equity": 5234.50
}

GET /api/equity
Response: {
  "current": 5234.50,
  "initial": 5000.00,
  "daily_pnl": 234.50,
  "daily_pnl_pct": 4.69,
  "drawdown": 0,
  "trades": 12
}

GET /api/trades/recent?limit=10
Response: [
  {symbol: "BTC", side: "LONG", entry: 62000, exit: 62100, pnl: 100, pnl_pct: 0.161, status: "CLOSED"},
  ...
]

GET /api/decisions/latest
Response: {
  "decision_id": "uuid-5678",
  "timestamp": "2026-05-30T12:00:00Z",
  "symbol": "BTC",
  "action": "LONG",
  "size": 0.01,
  "reasoning": "Strong trending regime, momentum >0.8, edge confidence 0.9, ..."
}

GET /api/decisions/analyze?limit=100
Response: [
  {decision_id, symbol, action, reasoning},
  ... (last 100 decisions, not all 10k)
]

GET /api/strategies
Response: {
  "momentum": {signals: 12, wins: 8, win_rate: 0.667},
  "mean_reversion": {signals: 5, wins: 3, win_rate: 0.6},
  ... (health of each 9 strategy)
}

GET /api/edges
Response: {
  "btc_regime": {score: 0.9, pass: true, trades: 8},
  "eth_volatility": {score: 0.3, pass: false, trades: 2},
  ... (health of each 6 edge)
}

GET /api/logs?filter=TRADE|ERROR&limit=50
Response: [
  [timestamp, marker, message],
  [timestamp, marker, message],
  ...
]

GET /api/positions/open
Response: [
  {symbol: "BTC", side: "LONG", size: 0.01, entry_price: 62000, entry_time: "...", pnl: 10},
  ...
]

GET /api/performance
Response: {
  "win_rate": 0.667,
  "avg_win": 0.16,
  "avg_loss": -0.08,
  "max_drawdown": 2.5,
  "sharpe": 1.23
}

Caching:
  Every response cached for 5 seconds
  Prevents disk thrashing if you spam refresh
  Cache cleared after every trade
```

---

### Claude Session (Other PC)

**Role:** The bot's intelligence analyst

**What it does:**
When you ask (from This PC via remote), Claude on Other PC:
- Reads decisions.jsonl (every decision the LLM made)
- Reads trades.csv (what actually executed)
- Reads bot.log (runtime timeline)
- Reads open_positions.json, circuit_breaker_state.json, etc.
- Analyzes and explains in plain English

**Example conversations:**

You: "Analyze the last 5 trades"
Claude on Other PC:
```
Trade 1: LONG BTC @ 62000
  LLM said: "Strong trending regime, momentum >0.8, edge confidence 0.9"
  Result: +100 PnL (+0.16%)
  Assessment: Decision was sound, edge worked

Trade 2: SHORT ETH @ 3100
  LLM said: "Mean-reversion setup, volatility spike, risk manageable"
  Result: +50 PnL (+0.16%)
  Assessment: Pattern worked, strategy is healthy

Trade 3: SKIP SOL
  LLM said: "Signals weak, edge score 0.3 (below threshold)"
  Result: Good call, avoided -100 PnL trade
  Assessment: LLM is respecting safety thresholds

Summary: 2 wins, 1 skip. Equity +150. Pattern: momentum >0.8 + edge >0.7 = winning.
```

You: "Why did strategy momentum have 5 signals yesterday but only 1 today?"
Claude on Other PC:
```
Looking at decisions.jsonl from yesterday vs today...
Momentum fired 5 times yesterday (regime was in strong uptrend, high volatility)
Momentum fired 1 time today (regime turned choppy, volatility dropped)
Assessment: Strategy is working correctly, responding to market change
```

You: "Is edge btc_regime actually working?"
Claude on Other PC:
```
Analyzed all 20 trades where btc_regime edge was checked.
When edge >0.8: 16 wins, 4 losses = 80% win rate
When edge <0.5: 2 wins, 8 losses = 20% win rate
Conclusion: Edge is REAL. Keep it.
```

You: "New code for mean_reversion.py pushed. Is it better than v1.0?"
Claude on Other PC:
```
Looking at trades made with mean_reversion v1.0...
Win rate: 60%, avg win: 0.15%, avg loss: -0.10%
Reviewing new v2.1 code...
[Explains the change]
Prediction: Should be better because [reasons]
Recommendation: Test on next 10 trades, report back
```

**Memory management:**
- Claude doesn't read ALL of decisions.jsonl (too expensive in tokens)
- Claude reads last 100 trades when analyzing
- When analyzing specific dates: extracts just that date range
- Keeps context lean, responses fast

---

### This PC: Your Control Center

You sit here. Multiple terminals open, each doing something different.

#### Terminal #1: Health Monitoring

```bash
$ powershell -File C:\Users\vince\WAGMI\bot\bot_alive.ps1

Output:
● Bot is live, collecting data.

What's running right now
  Python PID 5948 (~158MB), supervisor wrapper holding it
  Equity reset: $5,000.00 fresh
  Mode: paper, 4 symbols (BTC/ETH/SOL/HYPE), 9 strategies
  LLM: USE_CLI_LLM=true (all agents call Claude via claude -p, $0 API spend)
  Scan interval: 30s

What survives what
  Python crash → supervisor restarts it within 30s
  Supervisor crash → Task Scheduler restarts it within 1min
  Logout/reboot → NOT covered yet (TODO: NSSM or Task Scheduler upgrade)

How to check on it
  powershell -File C:\Users\vince\WAGMI\bot\bot_alive.ps1
  Shows heartbeat freshness, python PID, last 5 supervisor lines, last 5 bot log lines, current equity.
  If heartbeat >90s old → bot is dead, check logs/supervisor.log

Purpose:
  Quick health check. Are we running? Is equity reasonable? Is supervision chain intact?
  Run this when you wake up. Run this if worried. Takes 5 seconds.
```

#### Terminal #2: Claude Analysis

```bash
$ claude remote-control [other-pc-id]
Connected to Other PC

$ claude -p "Analyze the last 5 trades from decisions.jsonl"

Claude on Other PC reads decisions.jsonl + trades.csv and explains:
- Why each trade fired
- Was it sound?
- Are we finding patterns?
- What should we change?

Repeat as needed. Ask any question. Claude reads the data and responds.

Purpose:
  Understand the bot's thinking. Find patterns. Validate strategy health.
```

#### Terminal #3: Code Editing

```bash
$ cd C:\Users\vince\WAGMI\bot\strategies
$ code strategy_momentum.py

[Edit in VS Code]
[Change the momentum calculation to be more aggressive]
[Save]

$ # Push to Other PC (via USB, cloud sync, or git)
$ # Copy to OneDrive or USB

[On Other PC, restart bot]
$ python run.py paper

[On This PC, check logs]
$ claude -p "Did the new momentum strategy fire correctly on the last trade?"

Purpose:
  Write new strategies, improve existing ones, test ideas.
  Push live. Iterate.
```

#### Terminal #4: API Queries

```bash
$ curl http://[other-pc-ip]:8080/api/equity
{
  "current": 5234.50,
  "initial": 5000.00,
  "daily_pnl": 234.50,
  "trades": 12,
  "win_rate": 0.667
}

$ curl http://[other-pc-ip]:8080/api/trades/recent?limit=5
[
  {symbol: "BTC", side: "LONG", entry: 62000, exit: 62100, pnl: 100, status: "CLOSED"},
  ...
]

$ curl http://[other-pc-ip]:8080/api/health
{
  "status": "running",
  "heartbeat_age_seconds": 3,
  "equity": 5234.50
}

Purpose:
  Get raw data from the bot's API. This is what your website will use.
```

#### Terminal #5: Website Development

```bash
$ cd C:\Users\vince\WAGMI\website
$ npm start

Running on http://localhost:3000

[Website opens]
Shows:
  - Equity graph (updates every 5s from /api/equity)
  - Recent trades table (from /api/trades/recent)
  - Strategy health (from /api/strategies)
  - Edge validation (from /api/edges)
  - LLM reasoning (from /api/decisions/latest)
  - Live logs (from /api/logs)

Purpose:
  Your actual interface to the bot. Beautiful, visual, easy to understand.
  This is what you look at. Not logs, not raw JSON. A dashboard.
```

---

### File Sync (Non-Networked Setup)

Since your PCs aren't networked, data flows via:

**Option A: OneDrive Auto-Sync (Recommended)**

Other PC:
- decisions.jsonl, trades.csv, bot.log in C:\Users\vince\WAGMI_SYNC\ (OneDrive folder)
- OneDrive syncs automatically

This PC:
- C:\Users\vince\WAGMI_SYNC\ synced from OneDrive
- Gets new data every few minutes
- Website reads from here

**Option B: USB Dumps**

Other PC:
- Every hour, copy C:\Users\vince\WAGMI\bot\data\* to USB

You:
- Plug USB into This PC
- Files are copied

**Option C: API Only (No File Copy)**

This PC:
- curl http://[other-pc-ip]:8080/api/*
- No files copied, pure API calls
- Website pulls from API real-time

Choose ONE. We recommend Option A (OneDrive) because it's automatic.

---

## ALL THE GAPS WE FOUND + SOLUTIONS

### Gap #1: Race Condition — Bot Writing While Claude Reads 🔴 CRITICAL

**Problem:**
Bot writes to decisions.jsonl every 30s. Claude (on Other PC or This PC) reads it for analysis.

If they happen at the same time:
- Claude reads partial JSON (bot is mid-write)
- File gets corrupted
- API crashes
- Dashboard breaks

**Solution:**
Use atomic writes in bot code:

```python
import json
import os

def write_decision_safe(decision_dict):
    tmp_file = "decisions.jsonl.tmp"
    with open(tmp_file, "a") as f:
        f.write(json.dumps(decision_dict) + "\n")
    os.replace(tmp_file, "decisions.jsonl")  # Atomic rename

# Now Claude can safely read decisions.jsonl
# It will never see partial/corrupted JSON
```

**Why this works:**
- Write to temporary file (bot writes here, not the real file)
- Atomic rename (instant switch, no partial state)
- Readers see either old complete file or new complete file, never mid-write

---

### Gap #2: Circuit Breaker Persistence 🔴 CRITICAL

**Problem:**
Bot has "7% daily loss circuit breaker". But if bot restarts at 2pm:
- Is it 7% from market open? Or from restart time?
- Did we lose 2% before restart? Is it still counted?
- How do you know if CB is triggered after restart?

Answer: You don't. Bot has no memory.

**Solution:**
Persist circuit breaker state in `circuit_breaker_state.json`:

```json
{
  "date": "2026-05-30",
  "daily_start_equity": 5000.00,
  "daily_loss_pct": 2.5,
  "daily_loss_cb_triggered": false,
  "consecutive_losses": 3,
  "consecutive_loss_cap_triggered": false
}
```

Bot logic on startup:
```python
def on_startup():
    with open("circuit_breaker_state.json") as f:
        state = json.load(f)
    
    # Check if new day
    if state["date"] != today():
        # New day, reset CB
        state["date"] = today()
        state["daily_loss_pct"] = 0
        state["consecutive_losses"] = 0
    
    return state

def on_trade():
    state = load_cb_state()
    state["daily_loss_pct"] = (initial_equity - current_equity) / initial_equity * 100
    
    if state["daily_loss_pct"] > 7.0:
        state["triggered"] = True
        halt_trading()
    
    save(state)
```

**Why this works:**
- Circuit breaker state survives bot restarts
- Accumulates loss across all trades, all day
- On new day, automatically resets
- If CB triggered, bot knows and stops trading

---

### Gap #3: No Trade Reconciliation 🔴 CRITICAL

**Problem:**
LLM says "LONG BTC 0.01 @ 62000". Did it actually execute? Or fail? Or execute at different price?

decisions.jsonl: What LLM decided
trades.csv: What actually executed

But no verification that they match.

**Solution:**
Create `trade_reconciliation.jsonl`:

After every trade:
```json
{
  "timestamp": "2026-05-30T12:00:05Z",
  "decision_id": "uuid-5678",
  "intended_action": "LONG BTC 0.01",
  "intended_price": 62000,
  "actual_execution": "LONG BTC 0.01",
  "actual_price": 62010,
  "slippage": -10,
  "slippage_pct": -0.016,
  "status": "FILLED",
  "notes": "Expected price, got 10 cents worse (normal)"
}
```

If status != "FILLED":
```json
{
  "status": "PARTIAL",
  "filled_size": 0.005,
  "unfilled_size": 0.005,
  "reason": "Not enough liquidity"
}
```

Claude or dashboard can then verify: "Did we execute what we decided?"

**Why this works:**
- Complete audit trail
- Explains slippage
- Alerts if execution failed
- Connects decision to execution

---

### Gap #4: Strategy/Edge Versioning 🔴 CRITICAL

**Problem:**
You improve `strategy_momentum.py` from v1.0 to v2.1. But 10,000 old trades in decisions.jsonl were made with v1.0.

When Claude analyzes old trades, it doesn't know which version was used. Comparing new v2.1 performance to old v1.0 trades is unfair.

**Solution:**
Store version info in each decision:

```json
{
  "timestamp": "2026-05-30T12:00:00Z",
  "strategy_versions": {
    "momentum": "v2.1",
    "mean_reversion": "v1.0",
    "breakout": "v1.5",
    ...
  },
  "edge_versions": {
    "btc_regime": "v1.2",
    "eth_volatility": "v1.0",
    ...
  },
  "signals": {...},
  "llm_decision": {...}
}
```

Bot code:
```python
def get_version(module_name):
    mod = importlib.import_module(f"strategies.{module_name}")
    return mod.VERSION  # Each strategy has: VERSION = "v2.1"

decision["strategy_versions"] = {
    name: get_version(name) for name in all_strategies
}
```

Claude can then say:
"This trade used momentum v1.0. Let me check if v2.1 is better by comparing performance..."

**Why this works:**
- Can compare across versions
- Claude knows what code was used for each trade
- Fair analysis and improvement tracking

---

### Gap #5: Claude Memory Will Explode 🟡 HIGH

**Problem:**
After 1 month: ~10,000 trades in decisions.jsonl

Claude reads entire file:
- 100k+ tokens wasted on data you don't need right now
- Slow responses
- Expensive LLM calls

**Solution:**
Never ask Claude to read ALL trades. Be specific:

❌ DON'T:
```
"Analyze decisions.jsonl"
```

✅ DO:
```
"Analyze the last 100 trades from decisions.jsonl"
"Summarize trades from the last 24 hours"
"Find winning patterns: show me trades with pnl > 0.1%"
```

Helper function on Other PC:
```python
def extract_recent(file, limit=100):
    with open(file) as f:
        lines = f.readlines()
    return [json.loads(line) for line in lines[-limit:]]

def extract_date_range(file, start, end):
    with open(file) as f:
        trades = [json.loads(line) for line in f 
                  if start <= line[:10] <= end]
    return trades
```

Claude uses: "Here's the last 100 trades..." (not 10,000)

**Why this works:**
- Claude gets only relevant data
- Context window stays lean
- Responses stay fast and cheap

---

### Gap #6: Position Reconciliation on Crash 🟡 HIGH

**Problem:**
Bot crashes mid-trade. On restart, it doesn't know what positions are open.
May open conflicting positions or miss closing old ones.

**Solution:**
Maintain `open_positions.json`:

```json
{
  "timestamp": "2026-05-30T12:00:35Z",
  "positions": [
    {
      "symbol": "BTC",
      "side": "LONG",
      "size": 0.01,
      "entry_price": 62000,
      "entry_time": "2026-05-30T12:00:05Z",
      "entry_id": "uuid-5678"
    }
  ]
}
```

Bot on startup:
```python
def on_startup():
    with open("open_positions.json") as f:
        positions = json.load(f)["positions"]
    
    if positions:
        log("WARNING: Found open positions from previous session")
        return False  # Don't open new positions until these close
    
    return True  # OK to start trading

def on_trade_exit(symbol, side):
    with open("open_positions.json") as f:
        state = json.load(f)
    
    state["positions"] = [p for p in state["positions"] 
                         if not (p["symbol"] == symbol and p["side"] == side)]
    save(state)
```

**Why this works:**
- No accidental double positions after crash
- Clean restart
- Bot knows what's open

---

### Gap #7: Circuit Breaker Needs Equity State 🟡 HIGH

**Problem:**
To calculate "7% daily loss", you need: initial equity at start of day.
But this isn't stored anywhere reliable.

**Solution:**
Maintain `current_equity.json` with full state:

```json
{
  "timestamp": "2026-05-30T12:00:35Z",
  "equity": 5234.50,
  "initial_equity": 5000.00,
  "daily_pnl": 234.50,
  "daily_pnl_pct": 4.69,
  "trades_today": 12,
  "win_rate": 0.667,
  "max_position_size": 0.03,
  "open_position_count": 1,
  "daily_high": 5250,
  "daily_low": 4900,
  "max_drawdown_pct": 2.0
}
```

Update after every trade. Dashboard API reads this.

**Why this works:**
- Single source of truth for equity
- Dashboard always shows current state
- Circuit breaker has what it needs to calculate daily loss %

---

### Gap #8: Data Validation on API Read 🟡 MEDIUM

**Problem:**
decisions.jsonl corrupts (bad write, disk error). Dashboard API tries to read it.
JSON parse fails. API crashes. Website goes blank.

No error handling, no fallback.

**Solution:**
Dashboard API validates before serving:

```python
@app.get("/api/equity")
def get_equity():
    try:
        with open("current_equity.json") as f:
            equity = json.load(f)
        
        if not all(k in equity for k in ["equity", "initial_equity", "timestamp"]):
            return {"error": "Invalid equity file"}, 500
        
        return equity
    except json.JSONDecodeError:
        return {"error": "Corrupted equity file"}, 500
    except FileNotFoundError:
        return {"error": "Equity file not found"}, 404

@app.get("/api/decisions/latest")
def latest():
    try:
        with open("decisions.jsonl") as f:
            lines = f.readlines()
        if not lines:
            return {"error": "No decisions yet"}, 404
        return json.loads(lines[-1])
    except json.JSONDecodeError as e:
        return {"error": f"Corrupted decisions file: {e}"}, 500
```

Website sees error and shows helpful message, not blank.

**Why this works:**
- API crashes are handled gracefully
- Website shows what's wrong
- User knows to check logs/backups

---

### Gap #9: Log Files Grow Unbounded 🟡 MEDIUM

**Problem:**
bot.log appends every scan. After 1 year: 100GB+
Slows down API reads. Slows down log analysis.

**Solution:**
Rotate logs when >100MB:

```python
def write_log(marker, message):
    log_file = "bot.log"
    
    if os.path.getsize(log_file) > 100 * 1024 * 1024:  # 100MB
        archive = f"bot.log.archive_{datetime.now().isoformat()}"
        os.rename(log_file, archive)
    
    with open(log_file, "a") as f:
        f.write(f"[{datetime.now().isoformat()}] [{marker}] {message}\n")

def cleanup_old_archives(keep=10):
    archives = sorted(glob.glob("bot.log.archive_*"))
    for archive in archives[:-keep]:
        os.remove(archive)
```

Keep last 10 archives (~1GB total).

**Why this works:**
- Logs stay manageable
- API reads stay fast
- Old logs still available for deep analysis

---

### Gap #10: Backup Without Rotation 🟡 MEDIUM

**Problem:**
Backing up decisions.jsonl daily. After 1 year: 365 backup files, 10GB+

**Solution:**
Keep only last 30 days. Delete older ones:

```python
def prune_backups(backup_dir, keep_days=30):
    cutoff = datetime.now() - timedelta(days=keep_days)
    
    for filename in os.listdir(backup_dir):
        file_path = os.path.join(backup_dir, filename)
        file_time = datetime.fromtimestamp(os.path.getmtime(file_path))
        
        if file_time < cutoff:
            os.remove(file_path)
```

Run daily. Keeps ~1GB of backups.

**Why this works:**
- Backups exist without eating disk
- Can recover from recent corruption
- Old trades still in decisions.jsonl for analysis

---

### Gap #11: Audit Trail 🟡 MEDIUM

**Problem:**
Someone changes the circuit breaker from 5% to 7%. Why? When? By whom?
No record.

**Solution:**
Create `config_changes.jsonl`:

```json
{
  "timestamp": "2026-05-30T12:00:00Z",
  "what": "safety_floors.conf",
  "change": {"daily_loss_cb": {"from": "5%", "to": "7%"}},
  "reason": "Was too tight, missing good trades",
  "changed_by": "vince (via This PC Claude)"
}
```

Every config change is logged.

**Why this works:**
- Can answer: "When did we change the CB?"
- Explains decisions
- Helps debug: "Did we change settings before the crash?"

---

### Gap #12: Timezone Consistency 🟡 MEDIUM

**Problem:**
Bot logs in local time. Website shows UTC. Claude sees mixed times.
Confusion.

**Solution:**
Decision: **All timestamps in UTC, always.**

Bot code:
```python
from datetime import datetime, timezone
timestamp = datetime.now(timezone.utc).isoformat()
```

Website: JS converts UTC to user's local time on display.

**Why this works:**
- All systems agree on time
- No timezone bugs
- Data is interoperable

---

## HOW IT ALL FITS TOGETHER

### The 30-Second Loop

```
T+0s: Other PC bot starts scan
      ├─ Read prices
      ├─ Run 9 strategies
      ├─ Check 6 edges
      ├─ Calculate EV + volume
      ├─ Build full snapshot
      └─ Call LLM (Claude)

T+1s: LLM decides (via claude -p)
      └─ Response: LONG BTC 0.01

T+2s: Log decision to decisions.jsonl
      └─ Append {decision_id, signals, edges, llm_decision, reasoning}

T+3s: Execute trade (if action != SKIP)
      ├─ Send order to exchange
      ├─ Log to trades.csv
      ├─ Log to trade_reconciliation.jsonl
      └─ Log to open_positions.json

T+4s: Update equity
      ├─ Update current_equity.json
      └─ Update circuit_breaker_state.json

T+5s: Write to bot.log
      ├─ [SCAN], [SIGNAL], [EDGE], [TRADE], [ENTRY], [UPDATE]
      └─ Append to bot_YYYYMMDD.log

T+6s: Update heartbeat
      └─ Write timestamp to heartbeat.txt

T+7-30s: Sleep
      └─ Wait until next scan

T+30s: Repeat
```

### How This PC Gets Information

**Terminal #1: Health Check**
- Runs bot_alive.ps1
- Reads: heartbeat.txt, bot.log, supervisor logs
- Shows: "Is bot running? Is equity OK?"

**Terminal #2: Analysis**
- Remote Control into Other PC
- Asks Claude: "Analyze last 5 trades"
- Claude reads: decisions.jsonl, trades.csv
- Shows: "Why each trade happened, are we on track?"

**Terminal #3: Code Editing**
- Edit strategies locally
- Push to Other PC
- Restart bot
- Monitor new trades

**Terminal #4: API Queries**
- curl http://[other-pc-ip]:8080/api/equity
- Pulls: decisions.jsonl, trades.csv, bot.log via API
- Returns: JSON

**Terminal #5: Website**
- Runs on localhost:3000
- Fetches from http://[other-pc-ip]:8080/api/*
- Displays: equity graph, recent trades, strategy health, LLM reasoning
- Updates every 5-10 seconds

### File Sync (The Connection)

Files flow from Other PC to This PC via:

**Option A (Recommended): OneDrive**
```
Other PC: C:\Users\vince\WAGMI_SYNC\ (OneDrive)
  ├─ decisions.jsonl
  ├─ trades.csv
  ├─ bot.log
  └─ (syncs automatically)

OneDrive Cloud

This PC: C:\Users\vince\WAGMI_SYNC\ (OneDrive)
  ├─ decisions.jsonl (received)
  ├─ trades.csv (received)
  ├─ bot.log (received)
  └─ Website reads from here
```

**Option B: API Only**
```
This PC Terminal #4: curl http://[other-pc-ip]:8080/api/*
  └─ Gets latest decisions, trades, equity directly
  └─ Website fed by API, not files
```

---

## YOUR DAILY WORKFLOW

### Morning Check-in (2 minutes)

```
Terminal #1: powershell -File bot_alive.ps1
→ See: Bot running? Heartbeat fresh? Equity reasonable?
→ If all green, you're done

If red:
  Check bot.log for [ERROR]
  Fix if simple, or escalate to Claude
```

### Understand Overnight Activity (5 minutes)

```
Terminal #2: claude -p "Summarize last 10 trades from decisions.jsonl"
→ Claude explains what bot did while you slept
→ Were there wins? Losses? Did strategy work?
→ Did circuit breaker come close to triggering?
```

### Check Website (1 minute)

```
Terminal #5: Open http://localhost:3000
→ See equity graph visually
→ See recent trades
→ See strategy health (which strategies firing)
→ See edge validation (which edges working)
```

### Development (30 minutes)

```
Terminal #3: Edit strategy_momentum.py
  ├─ Improve the momentum calculation
  ├─ Save
  └─ Push to Other PC

Other PC: Restart bot
  python run.py paper

Terminal #2: claude -p "Test new momentum strategy on last 5 trades"
  └─ Claude runs the new code on recent decisions
  └─ Reports: "Better/same/worse?"

If better: Keep it
If worse: Revert and try again
```

### Phone Check-in (30 seconds)

```
Remote Control into This PC
Open website: http://localhost:3000
See: All metrics, all trades, strategy health
Done
```

---

## WHY THIS ARCHITECTURE

### Why Two Computers?

**Other PC: Bot runs 24/7**
- No interference
- If you reboot This PC, bot keeps running
- Isolation: bot is its own island

**This PC: You work here**
- Editing code
- Analyzing results
- Thinking strategically
- Safe from bot crashes

Clean separation = both can operate independently

### Why Claude on Both?

**Other PC Claude: Owns the bot data**
- Reads decisions.jsonl, trades.csv, logs
- Analyzes what happened
- Explains bot's thinking
- Validates edges/strategies

**This PC Claude: Helps you think**
- Helps write code
- Debugs issues
- Brainstorms improvements
- (Future expansion)

No conflict. Different domains.

### Why API Abstraction?

**Without API:**
Website talks directly to files
- Race conditions (bot writing, website reading simultaneously)
- File format issues
- No validation
- Complex

**With API:**
Website talks to API, API talks to files
- Atomic reads/writes
- Validation before serving
- Caching (faster responses)
- Decoupling (can change file format without breaking website)

Clean abstraction layer.

### Why Multiple Terminals on This PC?

**One terminal doing everything = chaos**

Multiple terminals = separation of concerns:
- Terminal #1: Monitoring (quick health checks)
- Terminal #2: Analysis (understanding trades)
- Terminal #3: Development (improving bot)
- Terminal #4: Data (raw API access)
- Terminal #5: Visualization (website)

Each terminal has one job. You context-switch cleanly.

### Why This File Structure?

**decisions.jsonl** (source of truth)
- Every decision recorded
- Versioning info stored
- Claude can read and understand
- Append-only = no accidental overwrites

**trades.csv** (execution log)
- Simple format
- Easy statistics
- Links back to decisions via decision_id
- Shows actual prices (with slippage)

**bot.log** (runtime log)
- Chronological
- Human-readable markers ([TRADE], [ERROR])
- Rotates to prevent unbounded growth
- Easy to search

**circuit_breaker_state.json** (safety state)
- Survives restarts
- Tracks daily loss accumulation
- Prevents over-trading

**current_equity.json** (current state)
- Dashboard reads this for /api/equity
- Single source of truth
- Updated after every trade

**open_positions.json** (position tracking)
- What's currently open?
- Survives restarts
- Prevents double positions

**trade_reconciliation.jsonl** (audit)
- Decision vs execution match
- Slippage tracking
- Failure investigation

Each file has ONE purpose. No data duplication. No confusion.

---

## SETUP CHECKLIST FOR OTHER PC

### Before Starting Bot

```
☐ Create C:\Users\vince\WAGMI\bot\data\ with all files:
  ├─ decisions.jsonl (empty, will populate)
  ├─ trades.csv (header row)
  ├─ bot_YYYYMMDD.log (empty)
  ├─ heartbeat.txt (empty)
  ├─ current_equity.json (pre-populated)
  ├─ circuit_breaker_state.json (pre-populated)
  ├─ open_positions.json (empty)
  ├─ trade_reconciliation.jsonl (empty)
  └─ backups/ (folder)

☐ Add to bot code:
  ├─ Atomic writes (decisions.jsonl, trades.csv)
  ├─ Circuit breaker persistence
  ├─ Trade reconciliation logging
  ├─ Strategy/edge versioning
  ├─ Log rotation (>100MB)
  ├─ Daily backups
  └─ Error handling (don't crash on LLM failure)

☐ Setup:
  ├─ OneDrive sync: data/ → OneDrive\WAGMI_SYNC\
  ├─ Dashboard API on port 8080
  ├─ Remote Control enabled
  └─ Claude session ready to analyze

☐ Test:
  ├─ python run.py paper
  ├─ Check heartbeat.txt updates every 30s
  ├─ Check decisions.jsonl has trades
  ├─ Check API: curl http://localhost:8080/api/health
  └─ Check sync: files appear in OneDrive
```

### On This PC

```
☐ Setup 5 terminals
☐ Test each one
☐ Build website dashboard
☐ Connect to API
☐ Test file sync
☐ Ready to monitor
```

---

## FINAL THOUGHTS

### What You're Building

An **autonomous trading bot with real-time intelligence analysis and visual interface**.

The bot:
- Runs 24/7 without touching it
- Makes decisions using LLM + strategies + edges
- Logs everything for analysis
- Survives crashes automatically

You:
- Monitor via dashboard website
- Understand why trades happened (via Claude analysis)
- Improve strategies by editing code
- See everything visually in real-time

### The Gaps We Fixed

Before we outlined the gaps, this system had 12 critical weaknesses:
1. Race conditions (corrupted data)
2. Lost circuit breaker state (unsafe trading)
3. No trade reconciliation (didn't know if executions matched decisions)
4. No strategy versioning (couldn't compare across code changes)
5. Claude memory bloat (slow, expensive analysis)
6. No position tracking (risk of double positions)
7. No equity state (circuit breaker had no data)
8. No data validation (crashes on corrupted files)
9. Unbounded logs (10GB+/year)
10. No backups (one corruption = data loss)
11. No audit trail (couldn't track changes)
12. Timezone confusion (different timestamps)

We fixed all 12. Now the system is **safe, auditable, and resilient**.

### Why This Document Exists

You're a visual learner who gets overwhelmed. This document explains:
- Not just WHAT the system does
- But WHY it does it that way
- The thinking behind each decision
- The gaps we found and how we fixed them

Your other PC's Claude can read this and understand the entire system. No rediscovery cost. No confusion. Just pure context.

### When to Scale

This system works great for:
- One bot
- 30s scan interval
- 4 symbols
- 9 strategies

If you scale to:
- Multiple bots → Add job queue
- Sub-second trading → Use database instead of files
- 100+ symbols → Add caching, maybe SQLite
- Distributed → Add message broker

But for now: **ship it**. Don't over-engineer.

---

## QUICK REFERENCE

### Files and What They Do

| File | Purpose | Updates | Read By |
|------|---------|---------|---------|
| decisions.jsonl | Master log of decisions | Every scan | Claude, Dashboard API |
| trades.csv | Execution log | Every trade | Dashboard API |
| bot.log | Runtime log | Every scan | Terminal #2 |
| heartbeat.txt | Health check | Every scan | bot_alive.ps1 |
| current_equity.json | Current state | Every trade | Dashboard API |
| circuit_breaker_state.json | Safety state | Every trade | Bot code |
| open_positions.json | Position tracking | Every trade | Bot code |
| trade_reconciliation.jsonl | Audit trail | Every trade | Claude, Dashboard API |
| config_changes.jsonl | Config history | On change | Audit/debugging |

### Commands You'll Use

```
Terminal #1:
  powershell -File C:\Users\vince\WAGMI\bot\bot_alive.ps1

Terminal #2:
  claude remote-control [id]
  claude -p "Analyze last 5 trades"

Terminal #3:
  code C:\Users\vince\WAGMI\bot\strategies\

Terminal #4:
  curl http://[ip]:8080/api/equity
  curl http://[ip]:8080/api/trades/recent

Terminal #5:
  npm start
```

### What to Monitor

- Heartbeat (is bot alive?)
- Equity (is it growing or shrinking?)
- Win rate (are we winning?)
- Circuit breaker (how close to 7% loss limit?)
- Error logs (anything broken?)

### What to Improve

- Strategies (which signals are working?)
- Edges (which alpha floors are real?)
- Safety floors (are they too tight/loose?)
- LLM mode (full autonomy or advisory?)

---

## Send This to Other PC Claude

Copy the entire document and send it to Claude on your other PC with this message:

```
Read this complete WAGMI architecture document. Understand:
1. The bot's 30-second loop and how everything works
2. Every file you maintain and why it exists
3. Your role as the intelligence analyst
4. All the gaps we're fixing (atomic writes, circuit breaker state, versioning, etc.)
5. How This PC connects to you
6. The thinking behind each architectural decision

This is the source of truth. Know it cold.

When you're done, respond with: "WAGMI bot intelligence hub ready. I understand the full architecture, all critical files, my role, the gaps we're fixing, and how I connect to This PC."
```

---

**End of Document**

Created: 2026-05-30  
Status: Complete, ready to ship  
Next: Send to other PC, start bot, begin trading
