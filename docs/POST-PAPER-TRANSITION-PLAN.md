# Post-Paper-Trading Transition Plan

## Context
The WAGMI trading bot is currently paper trading, collecting data and improving the UI. After a couple days of paper trading, we need a structured 3-7 day transition plan to go live with $100-500 test capital on Hyperliquid. The focus areas are: **Agent/LLM accuracy tuning**, **data migration & memory seeding**, and **strategy weight & ensemble optimization**. This plan ensures we extract maximum value from paper trading data before risking real capital.

## Important Realities
- **Go-live gates expect 30 days of data** (Gate 2 = net PnL over 30d, Gate 5 = 30d Sharpe). With only a few days of paper trading, some gates will return `INSUFFICIENT DATA`. This is expected — we'll use the gates as aspirational targets while relying on manual analysis for the go-live decision.
- **LIVE_PROFILE_OVERRIDES in `trading_config.py` are currently identical to paper** (25x leverage, 0.5% risk, 8 positions). We need to update these for conservative live trading, OR override via `.env` vars (which take priority).
- **VETO_ONLY mode is not pure veto** — it also applies confidence-based size scaling (0.6x for weak LLM approval <55% confidence). This is actually good for live — a soft graduated approach.
- **There is no `MAX_SAME_DIRECTION` parameter** in trading_config.py. Correlation is managed via `enable_correlation_check` + `correlation_rejection_threshold` (default 0.8).
- **The existing PHASE_3_DEPLOYMENT_GUIDE.md** describes a 72-96h phased rollout. This plan supersedes it with more granular focus on LLM/agent tuning and data migration, but we should follow its server requirements for production (dedicated server, 1GB RAM, 10GB disk, 24/7 uptime).

---

## Day 1: Data Extraction & Diagnostic Analysis

### 1.1 Run All Existing Diagnostic Skills
Use the built-in skills to generate baseline reports — no new code needed.

```bash
cd bot
# Core diagnostics
/paper-status gates          # Go-live gate progress
/evolution 30d               # Strategy evolution over paper period
/growth-report deep          # Unified learning intelligence
/confidence-calibrate system # Calibration drift analysis
/veto-review 30d             # Critic Agent veto accuracy
/thesis-track deep           # Prediction accuracy by regime/symbol/setup
/edge-finder full            # Where money is made/lost
/loss-autopsy patterns       # Loss pattern forensics
```

**Decision criteria**: Document each report's findings. Flag any agent with <50% accuracy, any strategy with negative edge, any regime with 0 trades.

### 1.2 Build a Paper Trading Analysis Script
**New file**: `bot/scripts/paper_analysis.py`

This script consolidates paper trading data into a single actionable report. It uses existing APIs rather than parsing raw files:

```python
# Paper Analysis Script — uses existing analysis APIs
import sys; sys.path.insert(0, 'bot')

# 1. TRADE STATISTICS (TradeLedger has built-in analysis)
from feedback.trade_ledger import TradeLedger
ledger = TradeLedger("bot/data")
trades = ledger.get_trades(lookback_days=30)
by_regime = ledger.get_regime_breakdown(lookback_days=30)    # WR per regime
by_agreement = ledger.get_agreement_breakdown(lookback_days=30)  # WR by consensus level

# 2. AGENT ACCURACY (ThesisTracker has calibration built-in)
from llm.thesis_tracker import ThesisTracker
thesis = ThesisTracker("bot/data/llm")
stats = thesis.get_accuracy_stats(lookback_days=30)
# Returns: overall_accuracy, by_regime, by_symbol, by_setup_type, calibration

# 3. CONFIDENCE CALIBRATION (per-bin accuracy)
from llm.confidence_calibrator import ConfidenceCalibrator
calibrator = ConfidenceCalibrator("bot/data/llm")
summary = calibrator.get_calibration_summary()
# Returns: total_observations, bins (50-60, 60-70, etc → actual_wr), overall_bias

# 4. COUNTERFACTUAL ANALYSIS (what we left on the table)
from llm.counterfactual_learner import CounterfactualLearner
cf = CounterfactualLearner("bot/data/llm")
missed = cf.get_missed_opportunity_stats(lookback_days=14)
# Returns: total_skips, would_win, would_lose, win_rate_of_skips,
#           total_hypothetical_pnl, by_skip_reason, problem_filters

# 5. EVOLUTION REPORT (comprehensive edge attribution)
from feedback.evolution_tracker import EvolutionTracker
evo = EvolutionTracker("bot/data")
report = evo.generate_report()
# report.edge_by_regime, edge_by_strategy, edge_by_symbol, trigger_roi
print(evo.format_report(report))

# 6. STRATEGY WEIGHTS (current rolling weights)
from data.strategy_weights import StrategyWeightManager
weights = StrategyWeightManager("ml_data/strategy_weights.json")
all_weights = weights.get_all_weights()        # Laplace-smoothed
rolling = weights.get_rolling_weights(window=10)  # Recent performance

# 7. SIGNAL REJECTIONS (which gates block what)
from data.db import get_rejection_summary
rejections = get_rejection_summary(hours=24*7)  # 7-day breakdown
# Returns: {gate_name → {count, high_conf_count}}

# 8. DEEP MEMORY SUMMARY
from llm.deep_memory import DeepMemoryManager
dm = DeepMemoryManager("bot/data/llm/deep_memory")
full_report = dm.get_full_report()  # All stats, fingerprints, patterns
```

**What each analysis produces (decision outputs)**:

| Analysis | Key Output | Decision It Drives |
|----------|-----------|-------------------|
| Trade stats by regime | WR per regime (trend/range/panic) | Regime risk multiplier tuning (§2.4) |
| Trade stats by agreement | WR at 2-agree vs 3-agree | MIN_VOTES decision (§2.4) |
| Thesis accuracy | Confidence bins → actual WR | Calibration curve update (§2.2) |
| Counterfactual `problem_filters` | Gates blocking >50% would-be-winners | Loosen those specific gates |
| Evolution `trigger_roi` | Cost vs PnL saved per LLM trigger | Disable low-ROI triggers, upgrade high-ROI ones |
| Strategy rolling weights | Per-strategy recent performance | Lock weights or disable losers (§2.3) |
| Signal rejections | Gate rejection counts | Identify if pipeline is too tight/loose |
| Deep memory fingerprints | Strategy × regime × symbol win rates | Knowledge base seeding (§3.4) |

### 1.3 Run Go-Live Gates
```bash
cd bot && python cli.py --mode gate
```
**File**: `bot/validation/go_live_gate.py` — Evaluates 5 gates:
1. Walk-forward ratio > 0.7
2. Net PnL > $0 (30d, min 5 trades)
3. Max drawdown < 15%
4. All factor ICs > 0 (30d)
5. Sharpe ratio > 1.0

**Action**: Record which gates pass/fail. Failing gates determine Day 2-3 priorities.

**If gates return INSUFFICIENT DATA** (likely with <30 days paper):
- This is expected. The gates need 30d of trade data + 5 minimum trades.
- Use the manual analysis from §1.2 as the primary go/no-go decision.
- Re-run gates weekly once live to track progress toward full validation.

**Gate Failure Remediation**:
| Gate | If Failing | Remediation |
|------|-----------|-------------|
| Walk-forward < 0.7 | Overfitting detected | Reduce strategy complexity, raise MIN_VOTES to 3 |
| Net PnL < $0 | Losing money | Analyze per-strategy PnL — disable losers, don't go live |
| Max DD > 15% | Risk too high | Tighten circuit breakers, reduce leverage, reduce positions |
| Factor ICs < 0 | Signals not predictive | Review signal pipeline, check for stale data issues |
| Sharpe < 1.0 | Risk-adjusted returns poor | Improve win rate OR reduce loss size via tighter stops |

---

## Day 2-3: Tuning & Optimization

### 2.1 Agent Prompt Refinements
Based on Day 1 analysis, tune agent prompts in `bot/llm/agents/prompts.py`:

| Agent | What to Check | Potential Tuning |
|-------|--------------|-----------------|
| **Regime** | Classification accuracy vs. actual regime | Adjust regime boundary definitions, add examples from paper data |
| **Trade** | Go/skip decision accuracy per regime | Add regime-specific decision heuristics learned from paper |
| **Critic** | Veto rate & accuracy (saved PnL / missed PnL) | If over-vetoing (>30% rate, <50% accuracy): soften counter-thesis requirement. If under-vetoing: strengthen |
| **Exit** | Exit timing vs. mechanical trailing stops | If exits underperform mechanical stops: reduce Exit Agent influence |
| **Scout** | Watchlist quality (did scouted setups materialize?) | Prune low-hit-rate watchlist criteria |

**Rules** (from `.claude/rules/llm-agents.md`):
- All agents must use identical vocabulary (regime names, action names, confidence scales)
- Test after prompt changes: `cd bot && pytest tests/ -k "agent or multi_agent"`
- Keep prompts under max_tokens budget per agent

### 2.2 Confidence Calibration Update
**File**: `bot/llm/confidence_calibrator.py`
**Data**: `bot/data/llm/calibration_curve.json` + `calibration_observations.jsonl`

The calibrator already rebuilds automatically every 10 observations. What we need to verify:

1. **Check the curve** — `calibrator.get_calibration_summary()` returns per-bin data:
   - Each bin (50-60, 60-70, 70-80, 80-90, 90-100) shows `claimed_mid` vs `actual_win_rate`
   - The `adjustment` field shows how much each bin is deflated/inflated
   - `overall_bias` tells us if the system is systematically over/underconfident

2. **Validate minimum samples** — Each bin needs ≥5 observations (`MIN_SAMPLES_PER_BIN=5`) before calibration is applied. With few days of paper data, some bins may be empty.

3. **Check calibration strength** — `CALIBRATION_STRENGTH=0.7` controls blending (0=ignore calibration, 1=fully trust it). With limited data, consider lowering to 0.5.

4. **Max adjustment cap** — `MAX_ADJUSTMENT_PCT=15.0` prevents wild swings. Verify this is appropriate.

**Action**: Run `/confidence-calibrate system`. If bins with ≥5 samples show >10% gap between claimed and actual, the calibrator is working correctly — let it auto-correct. If bins have <5 samples, note which confidence ranges need more data during live trading.

### 2.3 Strategy Weight Finalization
**File**: `ml_data/strategy_weights.json`
**Source**: `bot/data/strategy_weights.py` (class: `StrategyWeightManager`)

**How weights work currently**:
- Formula: `(wins + 1) / (trials + 2)` (Laplace smoothing)
- Rolling weights: base × (rolling_WR / 0.5), floored at 0.2
- Hard mute: weight → 0.20 if recent_WR < 30% AND long_term < 35% AND 15+ trades
- Recovery boost: 1.5× if last 5 trades are all wins
- Daily decay: exponential smoothing (alpha=0.9) downweights old data

**Analysis approach**:
```python
from data.strategy_weights import StrategyWeightManager
weights = StrategyWeightManager("ml_data/strategy_weights.json")

# Compare static vs rolling weights
static = weights.get_all_weights()     # Laplace-smoothed (stable)
rolling = weights.get_rolling_weights(window=10)  # Recent performance (volatile)

# Check for strategies that should be muted
report = weights.get_report()  # {strategy → {wins, trials, weight}}
```

**Decision framework by strategy**:
| Strategy | Expected Edge | Paper Result → Action |
|----------|--------------|----------------------|
| `regime_trend` | Strong in trend | If PF >1.5 in trend → boost to 1.3x |
| `confidence_scorer` | Core, all regimes | If WR >50% → keep at 1.0x |
| `oi_delta` | Newer, unproven | If WR <40% after 10+ trades → weight 0.5x |
| `funding_rate` | Newer, unproven | Same as oi_delta |
| `bollinger_squeeze` | Newer | Evaluate independently |
| `vmc_cipher` | Newer | Evaluate independently |
| `liquidation_cascade` | Rare signals | If fired <3 times → can't evaluate, keep 1.0x |
| `probability_engine` | Newer | Evaluate independently |
| `lead_lag` | **Disabled** ($-1,100) | Keep disabled unless paper data reverses with 15+ profitable trades |
| `multi_tier_quality` | **Disabled** (toxic combo) | Keep disabled unless tested in isolation |
| `monte_carlo_zones` | Gated by env | Evaluate if enabled |

**Locking weights for live**: Rather than hardcoding, consider running `weights.apply_decay()` one final time and then NOT running decay during the first week of live (to preserve paper-validated weights). Re-enable decay after Week 1 when live data starts building.

### 2.4 Ensemble Parameter Finalization
**File**: `bot/trading_config.py`

Decisions to make based on paper data:
- **MIN_VOTES**: If 2-agree signals have PF > 1.5, keep at 2. If not, raise to 3.
- **VETO_RATIO**: If current 1.2 produces good signal quality, keep. Adjust ±0.1 based on data.
- **Confidence floors**: Replace adaptive floors with data-driven per-regime floors:
  ```python
  # Example (values from paper data analysis)
  CONFIDENCE_FLOORS = {
      "trend": 65,      # Lower bar in trending (high-probability)
      "range": 80,      # Higher bar in ranging (more false signals)
      "panic": 85,      # Very high bar in panic
      "high_volatility": 75,
      "unknown": 70,
  }
  ```

### 2.5 Hypothesis Graduation
**File**: `bot/llm/growth/hypothesis_tracker.py`
**Data**: `bot/data/llm/growth/hypotheses.json` (max 200 active)

The hypothesis system has a well-defined graduation lifecycle:
- **Stages**: `proposed` → `testing` → `validated`/`invalidated` → `codified`
- **Auto-graduation criteria** (`is_ready_for_graduation`):
  - Standard: ≥10 evidence entries AND (evidence_ratio ≥0.7 OR ≤0.3)
  - Fast-track: 7-9 evidence entries AND (evidence_ratio ≥0.85 OR ≤0.15)
- **Graduation targets**: validated → becomes `principle` or `rule`; invalidated → becomes `anti_pattern`

Use `/knowledge-distill hypotheses` to:
1. Run `hypothesis_tracker.check_graduation()` — returns all hypotheses ready to graduate
2. Validated hypotheses (ratio ≥0.7) → add as `principle` or `rule` to knowledge base
3. Invalidated hypotheses (ratio ≤0.3) → add as `anti_pattern` to knowledge base
4. Example: "SOL breakouts fail in high_vol" with 14/20 supporting → `anti_pattern` in Trade Agent prompt

**With limited paper data**: Many hypotheses may still be in `proposed` or early `testing` stage with <10 evidence entries. That's fine — they'll continue accumulating evidence during live trading. Don't force-graduate hypotheses with insufficient data.

**What to prune**: Hypotheses in `proposed` stage with 0 evidence after 7+ days — they're stale. Remove via direct edit of `hypotheses.json`.

### 2.6 Autonomy Level Decision
**File**: `bot/llm/autonomy_router.py`

Based on paper trading LLM performance:
- If LLM vetoes saved net positive PnL → promote from ADVISORY(1) to VETO_ONLY(2)
- If LLM sizing suggestions outperformed fixed sizing → promote to SIZING(3)
- **For initial live**: Start at VETO_ONLY(2) — safest with real money

**What VETO_ONLY actually does** (from `autonomy_router.py:_mode_veto_only()`):
- LLM says "flat" → trade rejected (full veto)
- LLM says "flip" → downgraded to flat (flip not allowed in VETO_ONLY)
- LLM says "proceed" with confidence ≥ 0.55 → full baseline size
- LLM says "proceed" with confidence < 0.55 → 0.6x size (weak approval scaling)
- LLM fails/missing → use baseline unchanged (graceful degradation)

This means VETO_ONLY is already a graduated system, not just binary pass/fail. The weak-approval sizing is effectively a lightweight SIZING mode. This is ideal for initial live.

**Divergence tracking** (ADVISORY mode data):
- `autonomy_router.py` tracks a 50-entry deque of LLM agree/disagree with baseline
- `get_divergence_rate()` returns what % of the time LLM disagrees
- If divergence rate > 30% AND LLM-preferred outcomes were better → validates promotion
- Re-evaluate after 1 week of live data

### 2.7 Alert System Verification
Before go-live, verify Telegram/Discord are configured and working:
```bash
# Check .env has these set:
# TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_ALLOWED_USER_ID
# DISCORD_WEBHOOK (optional)

# Test Telegram bot responds to /status command
# Test alert routing: priority signals go to both Discord + Telegram
```
**File**: `bot/alerts/router.py` — smart routing with rate limiting and dedup
- Priority signals (conf ≥ 75%): Discord priority webhook + Telegram
- Regular signals (conf ≥ 65%): Discord all channel + Telegram
- Rate limits: max 5 priority alerts per symbol per 10 min

This is critical for live — you need to know immediately if something goes wrong.

---

## Day 3-4: Data Migration & Memory Seeding

### 3.1 Memory Preservation
Back up all paper trading intelligence:

```bash
# Create paper trading snapshot
mkdir -p bot/data/paper_snapshots/$(date +%Y%m%d)
cp -r bot/data/llm/ bot/data/paper_snapshots/$(date +%Y%m%d)/
cp bot/data/trades.csv bot/data/paper_snapshots/$(date +%Y%m%d)/
cp bot/data/trade_ledger.csv bot/data/paper_snapshots/$(date +%Y%m%d)/
cp -r bot/data/feedback/ bot/data/paper_snapshots/$(date +%Y%m%d)/
```

### 3.2 Deep Memory Curation (File-by-File)
**Directory**: `bot/data/llm/deep_memory/`

| File | Action | Reasoning |
|------|--------|-----------|
| `trade_dna.json` | **KEEP ALL** (max 500 trades) | Core learning data. Auto-compresses older trades to archive. Every entry has full context: entry/exit, regime, strategies, LLM reasoning, lessons, quality score. |
| `trade_dna_archive.json` | **KEEP** | Compressed summaries of trades beyond 500. Has 30-day TTL on archive entries. |
| `strategy_fingerprints.json` | **KEEP ALL** | Per-strategy breakdowns by regime/symbol/side. Contains `confidence_vs_actual` arrays (max 200) for calibration. This is the highest-value migration data. |
| `pattern_library.json` | **PRUNE** to patterns with WIN outcome | Max 1000 entries. Remove patterns with LOSS outcome and low context. Keep winning patterns for LLM prompt injection. |
| `regime_history.json` | **KEEP recent 50** transitions | Max 500. Recent transitions are relevant; old ones from paper warmup aren't. |
| `insight_journal.json` | **PRUNE** to confidence ≥0.6 AND validated=true | Max 500 entries. Use `get_validated()` and `get_high_confidence(min_confidence=0.6)` to filter. Categories: strategy_insight, symbol_insight, regime_insight, timing_insight, risk_insight. |

**Access methods for curation**:
```python
from llm.deep_memory import DeepMemoryManager
dm = DeepMemoryManager("bot/data/llm/deep_memory")

# Get summary before pruning
report = dm.get_full_report()

# Get best trades for review
snipers = dm.trade_dna.get_sniper_trades(limit=20)
failures = dm.trade_dna.get_failures(limit=20)

# Get validated insights only
validated = dm.insight_journal.get_validated(limit=100)

# Build knowledge summary for review
summary = dm.build_llm_knowledge_summary(max_tokens=2000)
```

### 3.3 Short-Term Memory Reset
**File**: `bot/data/llm/llm_memory.json`
**Format**: `{last_updated: timestamp, notes: [{text, ts, symbol, regime}]}`

- **Capacity**: 100 notes, 7-day TTL, max 200 chars per note
- **Quality gate**: Notes must be >20 chars, contain structure (not just "went up")
- **Action**: Clear all notes (`memory_store.clear_memory()`) and inject 3-5 transition notes:
  ```python
  from llm.memory_store import MemoryStore
  mem = MemoryStore("bot/data/llm")
  mem.clear_memory()

  # Inject paper trading summary notes (examples — use actual data)
  mem.apply_memory_update(
      "Paper→live transition: SOL trend WR 68%, range WR 41%; "
      "3-agree signals PF 4.05; regime_trend strongest strategy",
      symbol="", regime=""
  )
  mem.apply_memory_update(
      "Calibration: 80% confidence trades actually win 62% — "
      "deflation applied; veto rate 18%, saved $X net positive",
      symbol="", regime=""
  )
  ```
  The 7-day TTL means these notes naturally expire as live data replaces them.

### 3.4 Knowledge Base Update
**File**: `bot/data/llm/teaching/knowledge_base.json` (~42 KB)
**Types**: `axiom` | `principle` | `hypothesis` | `observation` | `anti_pattern` | `sniper_profile` | `rule`

Use the knowledge base API to inject validated paper findings:
```python
from llm.self_teaching import LearningCycleEngine
engine = LearningCycleEngine("bot/data/llm/teaching")
kb = engine.knowledge_base

# Add validated paper trading principles
kb.add(
    knowledge_type="principle",
    content="3-agree signals have 4x profit factor vs 2-agree",
    confidence=0.85,
    category="strategy",
    tags=["ensemble", "agreement", "consensus"],
    source="paper_trading",
    evidence="Paper trading: 3-agree PF=4.05, 2-agree PF=1.2"
)

# Add anti-patterns from paper losses
kb.add(
    knowledge_type="anti_pattern",
    content="SOL range entries with <80% confidence lose 60% of the time",
    confidence=0.75,
    category="symbol",
    tags=["SOL", "range", "confidence"],
    source="paper_trading",
    evidence="Paper: 12/20 SOL range trades lost, avg confidence 72%"
)

# Add sniper profiles from best trades
kb.add(
    knowledge_type="sniper_profile",
    content="HYPE trend breakout with funding <0.01% and 3+ agree: 85% WR",
    confidence=0.80,
    category="symbol",
    tags=["HYPE", "trend", "breakout", "sniper"],
    source="paper_trading",
    evidence="Paper: 6/7 HYPE breakouts in these conditions = WIN"
)
```

**Reliability threshold**: Knowledge entries are `is_reliable()` when `validation_count >= 3` AND `confidence >= 0.6`. Paper entries start with validation_count=0 — they'll be validated/invalidated as live trades occur.

### 3.5 Curriculum State Check
**File**: `bot/data/llm/teaching/curriculum_state.json`
**Levels**: 1=Pattern Recognition → 2=Causal Analysis → 3=Predictive Modeling → 4=Sniper Replication → 5=Strategy Synthesis

Check current state:
```python
from llm.self_teaching import LearningCycleEngine
engine = LearningCycleEngine("bot/data/llm/teaching")
state = engine._load_curriculum()
print(f"Level: {state.current_level}, Trades analyzed: {state.trades_analyzed}")
print(f"Hypotheses: {state.hypotheses_total} (validated: {state.hypotheses_validated})")
print(f"Hours at level: {state.hours_at_level:.1f}")
```

**Decision**:
- If still Level 1 with <50 trades analyzed → **keep at Level 1** (not enough data to advance)
- If Level 1 with 50+ trades and 50%+ hypothesis validation rate → advance to Level 2 via `/curriculum-advance evaluate`
- **Do NOT reset curriculum** — preserve the `trades_analyzed`, `hypotheses_*`, and `predictions_*` counters. These represent real learning progress from paper trading.

### 3.6 Recommendation Engine Cleanup
**File**: `bot/data/llm/growth/recommendations.json` (max 500)

- **Clear all PENDING** recommendations — they were generated in paper context
- **Keep APPLIED + VALIDATED** — these are proven suggestions
- **Keep INVALIDATED** — to avoid re-proposing failed ideas
- **Clear EXPIRED** — no longer relevant
```python
from llm.growth.recommendation_engine import RecommendationEngine
recs = RecommendationEngine("bot/data/llm/growth")
stats = recs.get_stats()  # by_status breakdown
# Manually prune: keep applied/validated/invalidated, clear pending/expired
```

---

## Day 4-5: Configuration, Validation & Go-Live

### 4.1 Trading Config Changes for Live
**File**: `bot/trading_config.py`

Two approaches for config changes — choose one:

**Option A: Update LIVE_PROFILE_OVERRIDES** (recommended — keeps `.env` clean):
Update the `LIVE_PROFILE_OVERRIDES` dict in `trading_config.py` (line ~634):
```python
LIVE_PROFILE_OVERRIDES = {
    "max_leverage": 5.0,            # Was 25.0 — conservative start
    "risk_per_trade": 0.01,         # Was 0.005 — 1% risk ($3 per trade on $300)
    "max_open_positions": 2,        # Was 8 — start narrow
    "max_portfolio_leverage": 2.0,  # Was 4.0 — tighter notional cap
    "enable_smart_orders": True,    # Real limit orders for live
}
```

**Option B: Override via .env** (env vars take priority over profile overrides):
```bash
RISK_PER_TRADE=0.01
MAX_LEVERAGE=5.0
MAX_OPEN_POSITIONS=2
MAX_PORTFOLIO_LEVERAGE=2.0
```

**All config changes (both options need these in .env):**
```bash
# Environment
ENVIRONMENT=production

# Capital
STARTING_EQUITY=300                  # $300 test capital

# Circuit Breakers (tighter for live)
CIRCUIT_BREAKER_DAILY_LOSS_PCT=0.03  # 3% daily (was 5% paper)
MAX_CONSECUTIVE_LOSSES=3             # 3 losses (was 5 paper)
MAX_DRAWDOWN_PCT=0.10               # 10% (was 15% paper)

# Ensemble (validated from paper)
MIN_VOTES_REQUIRED=<from Day 2 analysis>
VETO_RATIO=<from Day 2 analysis>

# LLM
LLM_MODE=2                          # VETO_ONLY
LLM_MULTI_AGENT=true

# Correlation guard (replaces the non-existent MAX_SAME_DIRECTION)
ENABLE_CORRELATION_CHECK=true
CORRELATION_REJECTION_THRESHOLD=0.8  # Reject new position if >0.8 correlated with existing

# Hyperliquid credentials (NEVER commit)
HL_API_KEY=<wallet-address>
HL_API_SECRET=<private-key>

# Alerts (critical for live monitoring)
TELEGRAM_TOKEN=<bot-token>
TELEGRAM_CHAT_ID=<chat-id>
TELEGRAM_ALLOWED_USER_ID=<numeric-user-id>
```

**Regime risk multipliers** — review `REGIME_RISK_MULTIPLIERS` dict (line ~599) against paper data. Currently:
- `trending_bull/bear`: 0.7x (conservative — unproven edge)
- `consolidation`: 1.0x
- `panic`: 0.3x (very conservative)
- These are already conservative and likely fine for initial live

### 4.2 Reconciliation & Exchange Connectivity Test
Before first live trade, verify exchange integration:
1. **API key permissions**: Ensure Hyperliquid API key has trade permissions but NOT withdrawal
2. **Connectivity test**: Fetch account balance, open orders, positions via CCXT
3. **Reconciliation on startup**: `bot/execution/reconciliation.py` automatically reconciles in-memory positions with exchange state — verify this runs cleanly with zero positions
4. **Order placement test**: Place and immediately cancel a tiny limit order to verify order flow works

### 4.3 Pre-Flight Validation
Run the existing deployment checklist:
```bash
/deploy-paper  # Reuse this skill's validation stages but for live
cd bot && pytest tests/ -x  # All tests must pass
python cli.py --mode gate   # All 5 go-live gates must pass
```

### 4.4 Dry-Run (First 24h)
1. Start with `python run.py live` (requires "CONFIRM LIVE" prompt)
2. Monitor via:
   - `/paper-status quick` (works for live too)
   - `/health-check deep`
   - Telegram alerts (ensure configured)
   - Dashboard: `python -m bot.dashboard.server`
3. Watch for:
   - First trade execution (fills matching expectations?)
   - Slippage vs. paper fills
   - API rate limits / connection issues
   - Circuit breaker behavior with real PnL

### 4.5 First 48h Monitoring Checklist
| Check | Frequency | What to Look For |
|-------|-----------|-----------------|
| Position state | Every 2h | Positions match exchange state (reconciliation) |
| PnL accuracy | Every trade | Declared PnL matches exchange PnL |
| Slippage | Every trade | Entry/exit vs. expected price |
| Memory growth | Every 6h | <2 MB/hour, no runaway growth |
| Error logs | Every 4h | Zero ERROR entries |
| Circuit breakers | Every 4h | No false trips |
| LLM costs | Daily | Within tier budget |

---

## Day 5+: Scale-Up Plan (Post-Validation)

### Phase 1 (Week 1): 2 symbols, $300, 1% risk
- SOL + HYPE only (most volatile, best paper data)
- Validate: fills match expected prices, PnL matches exchange PnL
- Compare: live slippage vs. paper's `SLIPPAGE_BPS=3` assumption
- Track: actual fees vs. `TAKER_FEE_BPS=4` (HL charges 3.5 bps)
- **Promotion criteria**: 5+ trades, no position mismatches, slippage < 5 bps avg

### Phase 2 (Week 2): 3 symbols, $300-500, 1% risk
- **If Week 1 passes**: Add BTC (low risk tier, wider stops via `BTC_ATR_MULTIPLIER=1.75`)
- Keep same risk params — only add symbol diversity
- **Promotion criteria**: 10+ total trades, win rate within 10% of paper rate, no CB trips

### Phase 3 (Week 3): Full config, scale capital
- **If Week 2 passes**: Increase to paper-equivalent settings:
  - `RISK_PER_TRADE=0.005` (match paper's 0.5%)
  - `MAX_OPEN_POSITIONS=4-8`
  - `MAX_LEVERAGE=10-25` (match paper)
- Consider promoting LLM from VETO_ONLY(2) to SIZING(3) if veto accuracy > 60%
- Scale capital to $500+

### Phase 4 (Week 4+): Autonomy promotion
- If profitable through Week 3, evaluate SIZING(3) promotion
- Run `/agent-replay compare` to simulate SIZING vs VETO_ONLY on live data
- Consider DIRECTION(4) only after 30+ trades at SIZING show positive edge

### Rollback Triggers (Immediate Stop → Kill Switch)
| Trigger | Action | Recovery |
|---------|--------|----------|
| Drawdown > 10% | Kill switch (`data/.kill_switch`) | Review all trades, diagnose, re-paper |
| 3+ consecutive losses | Pause 60 min (circuit breaker handles this) | Automatic resume after cooldown |
| Slippage consistently > 10 bps | Reduce to limit orders only | Set `ENABLE_SMART_ORDERS=true` |
| API errors > 3/hour | Kill switch | Check API key, network, exchange status |
| Position state mismatch | Kill switch immediately | Manual reconciliation on exchange |
| LLM costs > $5/day at RECOMMENDED tier | Downgrade to CONSERVATIVE | Reduce agent call frequency |

**Kill switch**: `touch bot/data/.kill_switch` — file-persisted, survives restarts, handled by OpsGuard

---

## Files to Modify (Summary)

| File | Day | Changes |
|------|-----|---------|
| **NEW**: `bot/scripts/paper_analysis.py` | 1 | Paper trading analysis consolidation script |
| `bot/llm/agents/prompts.py` | 2 | Agent prompt tuning based on accuracy data |
| `bot/data/llm/calibration_curve.json` | 2 | Verify/adjust calibration strength and bins |
| `ml_data/strategy_weights.json` | 2 | Final decay, lock weights for live Week 1 |
| `bot/data/llm/deep_memory/pattern_library.json` | 3 | Prune to winning patterns only |
| `bot/data/llm/deep_memory/regime_history.json` | 3 | Keep recent 50 transitions |
| `bot/data/llm/deep_memory/insight_journal.json` | 3 | Prune to confidence ≥0.6 + validated |
| `bot/data/llm/llm_memory.json` | 3 | Clear and inject 3-5 transition summary notes |
| `bot/data/llm/teaching/knowledge_base.json` | 3 | Add principles, anti-patterns, sniper profiles from paper |
| `bot/data/llm/growth/recommendations.json` | 3 | Clear pending/expired, keep applied/validated |
| `bot/data/llm/growth/hypotheses.json` | 3 | Prune stale proposed, graduate ready ones |
| `bot/trading_config.py` (LIVE_PROFILE_OVERRIDES) | 4 | Conservative live profile: 5x lev, 1% risk, 2 positions |
| `.env` | 4 | ENVIRONMENT=production, HL credentials, circuit breakers, LLM_MODE=2, alerts |

**Files to KEEP UNCHANGED** (carry over from paper):
| File | Reasoning |
|------|-----------|
| `bot/data/llm/deep_memory/trade_dna.json` | Core learning — all 500 trades preserved |
| `bot/data/llm/deep_memory/trade_dna_archive.json` | Compressed historical summaries |
| `bot/data/llm/deep_memory/strategy_fingerprints.json` | Highest-value migration data — per-strategy calibration |
| `bot/data/llm/teaching/curriculum_state.json` | Preserve learning progress counters |
| `bot/data/llm/calibration_observations.jsonl` | Raw observations for rebuilding curves |
| `bot/data/llm/thesis_history.jsonl` | Prediction accuracy history |
| `bot/data/llm/counterfactual_log.jsonl` | Skipped trade tracking |

**Files NOT to modify** (already correct for live):
- `bot/execution/risk.py` — Circuit breakers are env-driven, no code changes needed
- `bot/execution/ops_guard.py` — Kill switch + rate limits already production-ready
- `bot/core/signal_pipeline.py` — 6-gate filter chain is environment-agnostic
- `bot/execution/reconciliation.py` — Already reconciles on startup

## Existing Tools to Leverage (No New Code Needed)

| Tool | Purpose |
|------|---------|
| `python cli.py --mode gate` | Go-live gate evaluation |
| `/paper-status gates` | Gate progress during paper |
| `/evolution 30d` | Strategy performance over paper period |
| `/confidence-calibrate system` | Agent calibration audit |
| `/veto-review 30d` | Critic accuracy analysis |
| `/knowledge-distill hypotheses` | Graduate validated hypotheses |
| `/memory-optimize prune` | Clean up memory stores |
| `/growth-report deep` | Unified learning report |
| `/edge-finder full` | Edge attribution |
| `/loss-autopsy patterns` | Loss pattern analysis |
| `/curriculum-advance evaluate` | Self-teaching level check |
| `/thesis-track deep` | Prediction accuracy |
| `/deploy-paper` | Pre-flight validation (10 stages) |

## Verification Plan
1. **Before tuning**: Run full test suite (`pytest tests/`) — must pass
2. **After each prompt change**: Run agent tests (`pytest tests/ -k "agent"`)
3. **After config changes**: Run safety tests (`pytest tests/ -k "safety"`)
4. **Before go-live**: Run all go-live gates (`python cli.py --mode gate`)
5. **After go-live**: Monitor via `/health-check deep` + Telegram alerts for 48h
