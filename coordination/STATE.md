# WAGMI State — Single Source of Truth

Both Claudes update this file on any material change. Nunu reads this to know where everything stands in 30 seconds.

**Last updated:** 2026-06-02 ~16:00 UTC — laptop-claude (rebase resolved, branch pushed, fee fix acknowledged)

---

## TL;DR for Nunu

- **Bot is alive on the desktop** (hit session limit overnight, recovers at 5:30pm CDT = 22:30 UTC)
- **Overnight laptop work:** 5 commits — quant alpha rules corrected, SOL SHORT stat traced and fixed, record_outcome bug fixed
- **Knowledge base updated:** agents now see HYPE BUY 88% WR, SOL SELL 62% WR US session, HYPE SELL hard-block, BTC LONG US session block
- **Live paper WR before tonight's fixes:** 35.3% (17 matched trades) — should improve
- **15-day LLM backtest:** run at 22:30 UTC today (first thing after session reset)
- **Two computers, two Claudes, coordinating via this repo** (no OneDrive, no networking)
- **Identity**: this project uses "Nunu" everywhere it's user-facing. The username "vince" only appears in OS-level file paths.

---

## Machines

### Desktop (stationary workhorse)
- **Role:** Bot host. Runs the live paper-trading bot 24/7.
- **Status:** Healthy. python PID 1864, heartbeat fresh, supervised.
- **Owns:** `bot/`, live data in `bot/data/`, the running process.
- **Nunu uses for:** development, monitoring, Claude Code work, multiple parallel terminals.
- **Branch with today's surgery:** `desktop-overdrive-2026-05-30`

### Laptop (mobile)
- **Role:** Analysis hub + Nunu's mobile trading / remote-control station.
- **Status:** Nothing running (correct — this is not a bot host).
- **Owns:** Historical bot data from the OLD bot (pre-blackout). Already pushed to `historical/old-bot-pre-2026-04-23/`.
- **Nunu uses for:** travel, ask-Claude analysis, dashboard browsing.
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

- [x] **laptop-claude:** Phase 1 quant synthesis (edge_analysis_raw, time_edge_results, strategy_fingerprints)
- [x] **laptop-claude:** Fix subprocess hang on Windows (taskkill /F /T)
- [x] **laptop-claude:** Fix CLI session limit preflight
- [x] **laptop-claude:** Phase 2 graduated_rules corrections (4 rules: hype_short re-enabled, sol_short disabled, 2 new US-session rules)
- [x] **laptop-claude:** insight_journal SOL SHORT hard-block corrected
- [x] **laptop-claude:** record_outcome() hour_utc bug fixed
- [x] **laptop-claude:** knowledge_base.json updated with quant alpha rules
- [x] **laptop-claude:** SOL "n=42 WR=36%" stat traced and fixed at source
- [x] **laptop-claude:** Resolve handshake.md rebase conflict (desktop + laptop entries both preserved)
- [x] **laptop-claude:** Push `historical-import-2026-05-30` to origin (303cc5e..50b9a1c)
- [x] **laptop-claude:** Acknowledged fee fix (+$125 real PnL), cap raise 5→7, braver leverage prompt
- [x] **laptop-claude:** Pull desktop's `e02f265` fee fix into laptop branch (trading_config.py: 45 bps → 5 bps)
- [x] **laptop-claude:** Fix HYPE liquidation gate — pre-LLM check now uses min(max_lev, 10) not 15x (commit `c5ea228`)
- [ ] **laptop-claude:** Run rolling backtests at 22:30 UTC session reset (queue: BTC/ETH, raw+normal modes)
- [ ] **laptop-claude:** Aggregate real_pnl_by_exit_type.md and real_graduated_rules_seed.md after backtests
- [ ] **desktop-claude:** Pull `historical-import-2026-05-30` — get Phase 2 rule changes + KB update
- [ ] **desktop-claude:** Verify agents no longer cite "WR=36% n=42" after next pipeline cycles
- [ ] **desktop-claude:** Monitor if `sol_sell_us_session_boost_v1` fires during 14-22 UTC windows
- [ ] **Nunu:** When ready, merge both branches to main after review
- [ ] **both:** Track OVERDRIVE paper trade outcomes for feedback loop

## Recent laptop-claude bug fixes (2026-05-30)

| Fix | File | Status |
|---|---|---|
| EV gate blocks all signals in LLM backtest | `bot/backtest/engine.py` | APPLIED — `[DESKTOP-IMPACT-REVIEWED-OK]` |
| System prompt → prompt injection detection | `bot/llm/claude_cli_client.py` | APPLIED |
| QUANT agent ignores `AGENT_QUANT_ENABLED=false` | `bot/backtest/llm_integration.py` | APPLIED |
| Per-call budget too low for Sonnet ($0.10 < $0.11) | `bot/llm/claude_cli_client.py` | APPLIED |

## What's deliberately NOT a priority right now

- OneDrive sync (decided against)
- USB data transfers (decided against)
- Adding an Anthropic API key (intentional — subscription is doing the work)
- Renaming the OS-level `vince` user account (out of scope; only public docs use "Nunu")
- The architecture doc's specific schema for `decisions.jsonl` (the bot's actual structure is in `bot/data/llm/agent_performance.jsonl` + `counterfactual_pending.jsonl`; may align eventually but not today)

---

## How to verify any of this in 30 seconds

```powershell
powershell -File C:\Users\vince\WAGMI\bot\bot_alive.ps1
```

Or open the dashboard: http://localhost:8080
