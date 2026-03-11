# ACTION PLAN — Step-by-Step Profitability Roadmap

> Generated: 2026-03-11
> Based on: 7-agent deep audit of entire codebase
> Goal: Go from -$1k backtest → profitable paper trading → live

---

## Phase A: Validate Anti-Spam (Tonight/Tomorrow)

### Step A0: Pre-flight check (verify config is clean)
```bash
cd bot
# Verify config defaults are what we set:
python -c "from trading_config import TradingConfig; c=TradingConfig(); print(f'min_votes={c.min_votes_required} conf_floor={c.ensemble_confidence_floor} min_rr={c.min_signal_rr} min_ev={c.min_signal_ev} veto={c.veto_ratio} scan={c.scan_interval_s}s loss_cd={c.loss_cooldown_s}s')"
# Expected: min_votes=3 conf_floor=80.0 min_rr=1.8 min_ev=0.2 veto=1.5 scan=60s loss_cd=300s

# Check no env vars override:
env | grep -i "MIN_VOTES\|CONFIDENCE\|SIGNAL_RR\|SIGNAL_EV\|VETO_RATIO"
# Should be empty (no overrides)
```

### Step A1: Run 30-day smoke test first, then 100-day
```bash
cd bot
# Quick 30-day smoke test (validates data pipeline + outputs):
python run.py backtest --symbols BTC,SOL,HYPE --days 30

# Full 100-day validation:
python run.py backtest --symbols BTC,SOL,HYPE --days 100

# With learning bridge (feeds results to self-teaching):
python run.py backtest --symbols BTC,SOL,HYPE --days 100 --learn
```
**What to look for:**
- Total trade count (should be 60-80% fewer than before)
- Win rate (target: >55%)
- Profit factor (target: >2.0)
- Sharpe ratio (target: >0.5)
- 3-agree vs 2-agree breakdown
- Fee drag as % of gross PnL (target: <20%)

**Config verified (7-agent audit):** Both `backtest/engine.py` (line 174) and `multi_strategy_main.py` (line 397) pass `min_votes`, `confidence_floor`, `veto_ratio` from TradingConfig to EnsembleStrategy. All 10 anti-spam parameters flow correctly. No hardcoded bypasses found.

### Step A2: Analyze results, tune if needed
- **Too few signals?** → Soften `ENSEMBLE_CONFIDENCE_FLOOR` (80→78) or `MIN_SIGNAL_RR` (1.8→1.6)
- **Still losing?** → Check which gate rejects most signals (add logging)
- **Fee drag still >30%?** → Raise `MIN_STOP_WIDTH_PCT` from 0.002 to 0.005

### Step A3: Run walk-forward validation
```bash
cd bot && python cli.py --mode walkforward --days 120 --symbols BTC,SOL,HYPE
```
Confirms we're not overfitting to the 100-day window.

---

## Phase B: Strategy-Level Fixes (High Impact, ~2 hours)

### Step B1: Raise ADX minimum in strategies from 20 → 22
**Files:** `regime_trend.py`, `confidence_scorer.py`, `multi_tier_quality.py`
**Why:** ADX 20-22 is "maybe trending" — signals here have terrible WR. Raising to 22 eliminates ~30% of weak signals at the source (before they even reach ensemble).
**Risk:** Low. ADX 22 is still conservative.

### Step B2: Make 6h regime filter AND-based (not OR-based)
**Files:** `confidence_scorer.py` (lines ~345-348), `multi_tier_quality.py`
**Why:** Currently rejects only if EITHER MACD_h < 0 OR MFI < 45 contradicts. Should require BOTH to agree (AND). This is why confidence_scorer generates weak signals that correlate with multi_tier_quality.
**Risk:** Medium. Could reduce signal count further, but the signals it removes are the weakest.

### Step B3: Hard-reject multi_tier_quality in neutral regime
**File:** `multi_tier_quality.py` (lines ~286-291)
**Why:** Currently soft-caps to 68% confidence in neutral regime. These are the losing trades — trading on zero directional conviction.
**Risk:** Low. Neutral regime trades are net losers.

### Step B4: Add internal squeeze detection to confidence_scorer + multi_tier_quality
**Why:** Both strategies currently fire during Bollinger Band squeezes (low vol periods) without checking breakout direction. Adding a "don't trade during squeeze" filter prevents whipsaws.
**Risk:** Low. Squeezes are 50/50 by definition.

### Step B5: Run tests after strategy fixes
```bash
cd bot && pytest tests/ -x -q
```

### Step B6: Re-run 100-day backtest to measure improvement
Compare before vs after. Should see higher WR and fewer trades.

---

## Phase C: Execution Improvements (Medium Impact, ~1 hour)

### Step C1: Wire stale data guard before trading
**File:** `multi_strategy_main.py` — Add `is_data_stale()` check before `_process_symbol()`
**Why:** Bot currently trades on stale data after restarts or API failures. A 5-minute staleness check prevents bad entries.
**Risk:** None. Skipping a trade on stale data is always correct.

### Step C2: Wire periodic position reconciliation
**File:** `multi_strategy_main.py` — Call `periodic_reconciliation_check()` every 50 ticks
**Why:** If a position is manually closed on exchange mid-session, bot still tracks it. Could lead to phantom positions.
**Risk:** None. Reconciliation is read-only.

### Step C3: Review trailing stop tightness per trade profile
**Check:** Are MEDIUM and TREND trailing stops too loose? Review ATR multipliers.
**Files:** `trade_profile.py`, `position_manager.py`

---

## Phase D: Paper Trading Validation (48-72 hours)

### Step D1: Set up environment
```bash
cd bot
cp .env.example .env
# Edit .env:
#   ENVIRONMENT=paper
#   STARTING_EQUITY=10000
#   ANTHROPIC_API_KEY=sk-...
#   TELEGRAM_TOKEN=<bot_token>
#   TELEGRAM_CHAT_ID=<chat_id>
```

### Step D2: Start paper trading
```bash
cd bot && python run.py paper
```

### Step D3: Monitor for 48-72 hours
**Watch for:**
- Signal frequency: 2-4 trades/day (not 20+)
- Win rate per trade profile (SCALP vs MEDIUM vs TREND)
- Fee drag as % of gross PnL
- Circuit breaker activations
- LLM veto rate (~20% is healthy)
- Position hold times vs trade profile expectations

### Step D4: Daily review via Telegram
- `/status` — Equity, positions, daily PnL
- `/positions` — Open position details
- `/health` — Data freshness, circuit breaker, LLM status

---

## Phase E: LLM Agent Optimization (After Paper Validation)

### Step E1: Enable multi-agent mode
```
LLM_MULTI_AGENT=true
LLM_MODE=2  # VETO_ONLY (safest for initial testing)
```

### Step E2: Monitor agent impact on signal quality
- Does LLM veto rate improve WR?
- Are vetoed trades actually losers? (veto accuracy)
- Is the Critic Agent providing useful counter-theses?

### Step E3: Tune agent prompts if needed
- Regime Agent: calibrate regime detection accuracy
- Trade Agent: calibrate directional thesis quality
- Critic Agent: calibrate veto threshold (too many vetoes = missed profit)

### Step E4: Enable Exit Agent for open positions
```
AGENT_EXIT_ENABLED=true
```
Monitors open positions, recommends hold/adjust/close.

---

## Phase F: Go Live (After Successful Paper Trading)

### Step F1: Conservative live config
```
ENVIRONMENT=production
STARTING_EQUITY=<real_balance>
RISK_PER_TRADE=0.01  # 1% risk (half of paper)
MAX_LEVERAGE=3.0
MIN_VOTES_REQUIRED=3
MAX_OPEN_POSITIONS=2
```

### Step F2: Start with 2 symbols only
SOL + HYPE (best historical performance)

### Step F3: Monitor daily, scale gradually
- Week 1: 1% risk, 2 symbols, max 3x leverage
- Week 2: If profitable → add BTC, raise to 2% risk
- Week 3: If still profitable → add DOGE/FARTCOIN, raise max leverage to 5x

---

## Quick Reference: What's Working vs What Needs Fixing

### Working Well ✅
- 3-agree PF=4.05 (86% WR) — the core edge is real
- Anti-spam overhaul in config (10 parameters tightened)
- Config properly passed to both backtest and main loop
- Chop detection + graduated confidence floor
- Circuit breakers, leverage tiers, liquidation checks
- Trailing stops with progressive tightening
- 1006 tests passing
- ✅ **ADX raised to 22** — eliminates weak "maybe trending" signals (DONE)
- ✅ **Stale data guard wired** — rejects signals on old data (DONE)
- ✅ **Squeeze detection** — confidence_scorer + multi_tier_quality (DONE)
- ✅ **Neutral regime hard-reject** in multi_tier_quality (DONE)
- ✅ **Evolution→Tuner feedback loop** wired (DONE)
- ✅ Periodic reconciliation already wired (every 60 ticks)
- ✅ Adaptive risk already wired to sizing pipeline
- ✅ OpsGuard enforced at all trade entry points
- ✅ Breakeven SL logic verified correct (gives remaining qty more room via banked profit cushion)
- ✅ Floor SL for shorts verified correct (locks profit correctly)

### Needs Fixing 🔴
- **Self-teaching learning cycles** — records trades but never runs learning cycles
- **Parameter tuner outcome validation** — receives evolution lessons but can't validate suggestions

### Nice to Have 🟡
- Prompt versioning & A/B testing
- Re-enable monte_carlo_zones (highest quality signals, currently disabled)
- Strategy discovery agent
- Break up `multi_strategy_main.py` (4,700 lines)

---

## Daily Workflow for This Week

| Day | Focus | Command |
|-----|-------|---------|
| Day 1 | Run 100d backtest, analyze results | `python run.py backtest --days 100 --symbols BTC,SOL,HYPE` |
| Day 1 | Tune if needed, walk-forward validate | `python cli.py --mode walkforward --days 120` |
| Day 2 | Strategy fixes (B1-B4), retest | Edit strategies, `pytest tests/`, re-run backtest |
| Day 2 | Wire stale data guard + reconciliation | Edit `multi_strategy_main.py` |
| Day 3-5 | Paper trading 48-72h | `python run.py paper` |
| Day 5 | Review paper results, decide go-live | Telegram `/status`, analyze trades |
| Day 6-7 | Go live conservative (if paper profitable) | `ENVIRONMENT=production python run.py live` |
