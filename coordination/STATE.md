# WAGMI State — Single Source of Truth

Both Claudes update this file on any material change. Vince reads this to know where everything stands in 30 seconds.

**Last updated:** 2026-05-30 by desktop-claude

---

## TL;DR for Vince

- **Bot is alive on the desktop** (PID 1864, 30s scans, multi-agent LLM pipeline running, ~73s per decision)
- **LLM-driven architecture is live**: mechanical strategies feed data → LLM decides → bot executes
- **Zero API spend**: every LLM call routes through your Claude Code subscription via `claude -p` CLI
- **No trades yet today**, by design — LLM is being patient; just smart-skipped a BTC consolidation
- **Watchlist (LLM's pre-formed theses):** HYPE compression at $67.70 support → BUY on continuation; ETH funding-spike → mean rev on pullback
- **Two computers, two Claudes, coordinating via this repo** (no OneDrive, no networking)

---

## Machines

### Desktop (this PC, stationary workhorse)
- **Role:** Bot host. Runs the live paper-trading bot 24/7.
- **Status:** Healthy. python PID 1864, heartbeat fresh, supervised.
- **Owns:** `bot/`, live data in `bot/data/`, the running process.
- **Vince uses for:** development, monitoring, Claude Code work.
- **Branch with today's surgery:** `desktop-overdrive-2026-05-30`

### Laptop (other PC, mobile)
- **Role:** Analysis hub + Vince's mobile trading / remote-control station.
- **Status:** Nothing running (correct — this is not a bot host).
- **Owns:** Historical bot data from the OLD bot (pre-blackout). Already pushed to `historical/old-bot-pre-2026-04-23/`.
- **Vince uses for:** travel, ask-Claude analysis, dashboard browsing.
- **Branch with historical data + analysis:** `historical-import-2026-05-30`

---

## Bot architecture (as live on desktop right now)

```
Every 30 seconds:

1. CCXT fetches OHLCV for BTC/ETH/SOL/HYPE (1h + 6h)
2. 9 strategies generate signals:
   regime_trend, bollinger_squeeze, multi_tier_quality, funding_rate,
   oi_delta, liquidation_cascade, probability_engine, mean_reversion,
   confidence_scorer
3. Ensemble computes confidence + EV + volume — passes ALL of it as
   informational metadata (no hard gates anymore)
4. Multi-agent pipeline (4-5 LLM calls via claude -p CLI, ~73s total):
   Regime → Trade → Risk → Critic → (Scout idle)
   Each agent gets snapshot, writes structured JSON output, hands to next
5. LLM decides: go / skip / flip + size + leverage + reasoning
6. Bot executes (paper) or skips (logged as counterfactual)
7. Heartbeat file touched, dashboard at :8080 served
```

## Key configuration (desktop bot/.env, not committed — gitignored)

```
USE_CLI_LLM=true                  # Route via Claude Code subscription, $0 API spend
ANTHROPIC_API_KEY=                # INTENTIONALLY BLANK. Do not fill.
LLM_MODE=5                        # FULL autonomy
LLM_FIRST_MODE=true               # EV gate informational, signals flow to LLM
LLM_MULTI_AGENT=true              # Multi-agent pipeline enabled
LLM_USAGE_TIER=AGGRESSIVE
MIN_VOTES_REQUIRED=1
VETO_RATIO=2.0
ENABLE_CHOP_DETECTOR=false        # Hard chop detector off; LLM weighs chop info
MAX_CONSECUTIVE_LOSSES=10         # CB threshold, raised from 5
CIRCUIT_BREAKER_DAILY_LOSS_PCT=0.07
MAX_LEVERAGE=15
MAX_OPEN_POSITIONS=4
STARTING_EQUITY=5000.0            # Fresh reset 2026-05-30
```

## What's running right now

| Component | Where | Status |
|---|---|---|
| Live bot (python) | Desktop, PID 1864 | Healthy, 30s scans |
| Supervisor (PowerShell) | Desktop, hidden | Self-loops on python crash |
| Task Scheduler task | Desktop, `WAGMI-Bot` | Restarts supervisor on crash |
| Dashboard | Desktop, http://localhost:8080 | Live |
| Health endpoint | Desktop, http://localhost:8081 | Live |
| Heartbeat file | Desktop, `bot/data/bot_heartbeat.txt` | Touched every 30s |

## Recent LLM activity (proof of life)

Scout watchlist (latest):
- **HYPE** high priority — *"Compression forming at support ($67.70). Trending_bull regime + BB solo potential"*
- **ETH** high priority — *"ETH in trend regime, elevated funding (1.3e-05) signals mean reversion setup on pullback"*

Most recent trade decision (skip with full reasoning):
- **BTC SELL skip** — *"Solo signal (1 agreement only), EV=-$1.90/dollar, 60-70% confidence range flagged as net-negative by graduated rules (45 such signals net-losers). Consolidated regime offers no directional edge."*

---

## Open items

- [ ] **laptop-claude:** Pull `origin/desktop-overdrive-2026-05-30`, re-audit, confirm CLI routing path (NOT API key path)
- [ ] **laptop-claude:** Halt any perpetual deep-dive / overnight commit cycles still running on the laptop
- [ ] **laptop-claude:** Run Part 2 historical analysis against `historical/old-bot-pre-2026-04-23/` data, push outputs to `analysis/historical/`
- [ ] **desktop-claude:** Monitor first trade firing, watch for any LLM-pipeline regressions
- [ ] **both:** Once analysis is in, decide which doc's "gap" recommendations to actually adopt (decision_id linking, strategy versioning, log rotation)
- [ ] **Vince:** When ready, merge both branches to main after review
- [ ] **eventually:** Phase 2 cleanup — convert shadow EDGES from confidence-floor multiplier to LLM-context metadata

## What's deliberately NOT a priority right now

- OneDrive sync (decided against)
- USB data transfers (decided against)
- Adding an Anthropic API key (intentional — subscription is doing the work)
- The architecture doc's specific schema for `decisions.jsonl` (the bot's actual structure is in `bot/data/llm/agent_performance.jsonl` + `counterfactual_pending.jsonl`; we may align eventually but not today)

---

## How to verify any of this in 30 seconds

```powershell
powershell -File C:\Users\vince\WAGMI\bot\bot_alive.ps1
```

Or open the dashboard: http://localhost:8080
