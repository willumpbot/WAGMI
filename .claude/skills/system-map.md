# /system-map — Full System Introspection

## Description
Generate a comprehensive map of the entire trading bot: what's built, what's working, what's stubbed, how systems connect, and what data flows where. The "what do we actually have?" skill.

## Arguments
- `$ARGUMENTS` — Optional: specific layer ("strategies", "agents", "execution", "data", "web", "alerts", "feedback", "growth"), "connections" for dependency map, or "full"

## Workflow

### 1. Code Inventory
Scan the entire codebase and catalog every module:

```bash
cd bot && find . -name "*.py" -not -path "./__pycache__/*" | wc -l
cd bot && find . -name "*.py" -not -path "./__pycache__/*" -exec wc -l {} + | sort -n | tail -20
```

Build inventory table:
```
SYSTEM INVENTORY
━━━━━━━━━━━━━━━━
Layer                Files   Lines   Status
Core Pipeline        XX      X,XXX   WORKING
Strategies           XX      X,XXX   WORKING
LLM Agents           XX      X,XXX   WORKING
Execution            XX      X,XXX   WORKING
Feedback Loops       XX      X,XXX   WORKING
Growth Systems       XX      X,XXX   WORKING
Data Pipeline        XX      X,XXX   WORKING
Alerts               XX      X,XXX   WORKING
Monitoring           XX      X,XXX   WORKING
Dashboard            XX      X,XXX   WORKING
API                  XX      X,XXX   WORKING
Tests                XX      X,XXX   XXX tests
Scripts              XX      X,XXX   READY
Infrastructure       XX      X,XXX   READY
Strategy Discovery   XX      X,XXX   BUILT (not activated)
Total:               XXX     XX,XXX
```

### 2. Per-Layer Deep Scan

**Strategies Layer:**
- Read `bot/strategies/*.py` — list all strategies, their evaluate() method status
- Read `bot/strategies/ensemble.py` — voting mode, MIN_VOTES, VETO_RATIO
- Read `bot/strategies/chop_detector.py` — chop detection status
- Read `bot/strategies/regime_detector.py` — regime classification

**LLM Agent Layer:**
- Read `bot/llm/agents/*.py` — all 5 agents, their prompts, models, token budgets
- Read `bot/llm/decision_engine.py` — monolithic pipeline status
- Read `bot/llm/agents/coordinator.py` — multi-agent pipeline status
- Check: shared_context.py, thought_protocol.py, consistency_checker.py existence and status

**Execution Layer:**
- Read `bot/execution/*.py` — position manager, leverage, risk, ops guard
- Check reconciliation.py — is it complete or stubbed?
- Check adaptive_risk.py — is it active?

**Data Layer:**
- Read `bot/data/fetcher.py` — exchanges supported, fallback chains
- Read `bot/data/db.py` — schema, migrations status
- Check data files: trades.csv, decisions.jsonl, memory files

**Web/Alert Layer:**
- Read `bot/alerts/*.py` — Telegram bot commands, Discord webhooks, alert router
- Read `bot/signals/telegram_ingest.py` — signal ingestion status
- Read `bot/monitoring/*.py` — health server, watchdog
- Read `bot/dashboard/server.py` — dashboard endpoints

**Feedback Layer:**
- Read `bot/feedback/*.py` — signal quality, evolution, continuous backtest, parameter tuner
- Check data freshness of feedback state files

**Growth Layer:**
- Read `bot/llm/growth/*.py` — hypothesis tracker, recommendations, self-improvement
- Read `bot/llm/self_teaching.py` — curriculum level, knowledge entries

### 3. Connection Map
Build a data flow diagram showing how systems connect:

```
DATA FLOW MAP
━━━━━━━━━━━━━

Exchange APIs (CCXT/CoinGecko)
    ↓
Data Fetcher (multi-exchange, circuit breaker)
    ↓
┌─────────────────────────┐
│ 4 Trading Strategies    │ ← Trading Config
│ regime_trend             │
│ monte_carlo_zones        │
│ confidence_scorer        │
│ multi_tier_quality       │
└──────────┬──────────────┘
           ↓
Ensemble (weighted veto) ← Strategy Weights (feedback loop)
           ↓
Signal Pipeline (6 risk gates)
           ↓
┌─────────────────────────┐
│ Multi-Agent LLM Pipeline│ ← Memory (short-term + deep)
│ Regime → Trade → Risk   │ ← Knowledge Base (self-teaching)
│ → Critic                │ ← Growth Context (hypotheses)
└──────────┬──────────────┘
           ↓
Autonomy Router (mode 0-5)
           ↓
Position Manager (state machine)
           ↓
┌──────────┴──────────────┐
│ Trade Outcome           │
└──────────┬──────────────┘
           ↓
┌──────────────────────────────────────┐
│ Feedback Loops                       │
│ Signal Quality → Strategy Weights    │
│ Adaptive Confidence → Floor/Ceiling  │
│ Continuous Backtest → Parameter Tuner│
│ Evolution Tracker → Reports          │
└──────────┬───────────────────────────┘
           ↓
┌──────────────────────────────────────┐
│ Growth Systems                       │
│ Learning Agent → Deep Memory         │
│ Hypothesis Tracker → Rules           │
│ Self-Improvement → Proposals         │
│ Veto Tracker → Critic Calibration    │
│ Self-Teaching → Curriculum           │
└──────────────────────────────────────┘

EXTERNAL CONNECTIONS:
  ← Telegram Commands (/status, /signals, /llm, etc.)
  ← Telegram Signal Channels (ingested signals)
  → Discord Webhooks (priority + regular alerts)
  → Telegram Alerts (signals + events)
  → Dashboard (HTTP SPA + JSON API)
  → Health Server (/healthz, /readyz, /status)
  ← REST API (FastAPI: signals, trades, metrics)
  → Prometheus → Grafana → Alertmanager → Discord
```

### 4. Status Assessment
For each system, determine:
- **WORKING**: Actively used in production/paper pipeline
- **BUILT**: Code exists, tested, but not activated
- **STUBBED**: Code exists but incomplete
- **PLANNED**: In ROADMAP but not started
- **BROKEN**: Exists but has known bugs (cross-ref ROADMAP section 8)

### 5. Known Bugs Cross-Reference
Read ROADMAP.md section 8 and cross-reference with current code:
- Which bugs are still present?
- Which have been fixed since ROADMAP was written?
- Are there new bugs not in the ROADMAP?

### 6. Configuration Map
Read `bot/trading_config.py` and `.env.example`:
- List every configurable parameter with current value and description
- Identify hardcoded values that should be configurable (per ROADMAP Phase 4)
- Show which env vars are set vs. missing

### 7. Test Coverage Map
```bash
cd bot && pytest tests/ --co -q | wc -l
```
Map test files to source modules:
- Which modules have test coverage?
- Which modules have NO test coverage?
- Which are the most critical uncovered modules?

### 8. Report
```
SYSTEM MAP — nunuIRL Trading Bot — <timestamp>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CODEBASE: XXX Python files, XX,XXX lines
TESTS: XX test files, XXX+ tests

LAYER STATUS:
  Core Pipeline:      WORKING ✓ (strategies → ensemble → execution)
  LLM Agents:         WORKING ✓ (5 agents, multi-agent pipeline)
  Feedback Loops:     WORKING ✓ (signal quality, evolution, backtest)
  Growth Systems:     WORKING ✓ (hypotheses, recommendations, curriculum)
  Alerts:             WORKING ✓ (Telegram commands + Discord webhooks)
  Signal Ingestion:   WORKING ✓ (Telegram channel monitoring)
  Dashboard:          WORKING ✓ (HTTP SPA + API)
  Strategy Discovery: BUILT (not activated)
  Reconciliation:     STUBBED (needs completion)

KNOWN BUGS: X critical, X reliability
HARDCODED VALUES: ~XX identified for extraction
PHASE PROGRESS: Phase 1 ✅, Phase 2 ✅, Phase 3 in progress

NEXT PRIORITIES:
  1. [From ROADMAP current phase]
  2. [Critical bug with highest impact]
  3. [Highest value unactivated system]
```
