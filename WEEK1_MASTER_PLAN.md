# WAGMI Week 1 Master Plan — Mechanical Stability & Regime Filter Audit

**Objective:** Establish mechanical confidence in the trading system. Lock in behavior parity between backtest and paper trading. Stabilize website. Baseline performance metrics.

**Timeline:** 7 days (this week)
**Scope:** Bug fixes, regime filter audit, mechanical testing, data collection
**Next Week:** LLM activation (phased per original Master Plan)
**Week 3:** Full capital deployment

---

## CRITICAL: REGIME FILTER BEHAVIOR PARITY

### The Issue
Your paper trading log shows:
```
[HYPE] Regime filter: disabled {'regime_trend'} in range regime
```

This is controlled by the `STRATEGY_REGIME_FIT` table in `bot/llm/agents/shared_context.py`, which marks `regime_trend = "avoid"` in range markets.

**Problem:** If your backtests DO NOT have this filter applied the same way, your paper results won't match backtest expectations.

### What We Found
- **Backtest Code** (`bot/backtest/engine.py:688-716`): Always applies regime filter. No condition. regime_trend gets disabled in range markets.
- **Paper Trading Code** (`bot/multi_strategy_main.py:2651-2675`): Applies regime filter IF `self.config.enable_regime_strategy_filter = True`
- **Config Default** (`bot/trading_config.py:270`): `ENABLE_REGIME_STRATEGY_FILTER=True` (enabled by default)

### The Real Discrepancy
**Possibility 1 (Most Likely):** Your .env file or local config explicitly set `ENABLE_REGIME_STRATEGY_FILTER=false` for testing, but backtest has no such control — it always applies the filter.

**Possibility 2:** You backtested before the regime filter was added to backtest code.

### This Week: Action Items

**FIRST THING:** Audit your backtest vs paper config
```bash
# In /home/user/WAGMI/.env, check if this exists:
ENABLE_REGIME_STRATEGY_FILTER=false   # ← If this exists, this is the problem

# Check backtest code to confirm it ignores this flag:
grep -n "enable_regime_strategy_filter" bot/backtest/engine.py
# Should return: NOTHING (backtest always applies filter)
```

**Decision Tree:**

```
Is ENABLE_REGIME_STRATEGY_FILTER in your .env?
│
├─ NO → Good! Both backtest and paper use defaults (both TRUE)
│       Config is aligned. Proceed with rest of plan.
│
└─ YES, set to FALSE → BAD! This is the mismatch.
    ACTION REQUIRED:

    Option A (Recommended):
      1. Remove ENABLE_REGIME_STRATEGY_FILTER=false from .env
      2. Set it to TRUE (match backtest behavior)
      3. Re-run paper trading fresh
      4. Accept that regime_trend gets disabled in ranges
         (this is correct — regime_trend performs poorly in ranges)

    Option B (If you hate the filter):
      1. Go to bot/backtest/engine.py lines 688-716
      2. Comment out the regime filter logic
      3. Re-run backtest to get new baseline
      4. THEN run paper trading to match new baseline
      5. ⚠️  WARNING: Disabling this filter will likely HURT win rate
         regime_trend is a trend-following strategy, it sucks in ranges.
```

**Confidence:** This is likely THE issue. Once aligned, paper trading should match backtest behavior.

---

## WEEK 1 CHECKLIST

### Phase 0: Critical Pre-Flight (Day 1, ~30 min)

- [ ] **Regime Filter Audit**
  - [ ] Check `.env` for `ENABLE_REGIME_STRATEGY_FILTER` flag
  - [ ] Confirm setting (true or false)
  - [ ] Decision: keep aligned or explicitly change
  - [ ] Document your choice in this plan

- [ ] **Bug Fixes (3 bugs, ~30 min total)**
  1. **Bug 1: Trades not showing on website**
     - File: `api/app/routes_trades.py:23`
     - Change: Point CSV path to `trades_10d.csv` (where real trades are)
     - Test: Website > Trades page should now show data

  2. **Bug 2: Copy-trade crash**
     - File: `web/pages/copy-trade.tsx` lines 771, 823
     - Change: Add null guard, fix symbol replace
     - Before: `const gradSuffix = symbol.replace(/[^a-zA-Z0-9]/g, '');`
     - After: `const gradSuffix = (symbol || '').replace(/[^a-zA-Z0-9]/g, '');`
     - Test: Copy-trade page loads without errors

  3. **Bug 3: Signal persistence (monitor, only fix if needed)**
     - Signals disappear on API restart
     - File: `api/app/services/signals.py` ~line 319-322
     - Only fix this IF signals keep vanishing in testing
     - Otherwise defer to next week

### Phase 1: Mechanical Baseline Collection (Days 2-4)

**Goal:** Run paper trading with LLM OFF. Establish baseline performance. Ensure no crashes.

- [ ] **Prep**
  - [ ] Start fresh: clear any stale position state
  - [ ] Verify `LLM_MODE=0` in `.env` (off)
  - [ ] Verify `ENABLE_REGIME_STRATEGY_FILTER={your choice}` is set
  - [ ] Confirm all 3 bugs are fixed

- [ ] **Run Paper Trading (3 days)**
  - [ ] Kick off: `cd bot && python run.py paper`
  - [ ] Expected: Bot starts, runs signal pipeline, takes trades
  - [ ] Monitor: Check logs for crashes, errors, anomalies
  - [ ] Website: Trades should appear on website within 10 min of execution

- [ ] **Data Collection (track these metrics daily)**
  - [ ] Total trades executed (target: 5+ per day, 15+ total by day 4)
  - [ ] Win rate (even if negative, we just need baseline)
  - [ ] Avg win / avg loss
  - [ ] Equity curve (starting $1,000)
  - [ ] Any error logs or signal pipeline rejections
  - [ ] Which symbols are trading? (BTC, SOL, HYPE)
  - [ ] Which strategies are firing? (ensemble voting patterns)

- [ ] **Website Validation**
  - [ ] [ ] Dashboard loads without errors
  - [ ] [ ] Trades page shows all executed trades (not empty)
  - [ ] [ ] Copy-trade page works (no crashes)
  - [ ] [ ] Performance page shows equity curve
  - [ ] [ ] Signals panel shows recent activity

### Phase 2: Mechanical Analysis (Days 5-6)

**Goal:** Understand what happened. Compare to backtest. Identify any discrepancies.

- [ ] **Performance Review**
  - [ ] Extract all trades from `bot/trades_10d.csv`
  - [ ] Calculate:
    - Win rate %
    - Profit factor
    - Max drawdown
    - Consecutive losses
  - [ ] Compare to backtest expectations
    - If backtest said 45% win rate, did we get ~45%?
    - If backtest said 1.5x profit factor, did we get ~1.5x?
    - If not, diagnose why (regime filter, ensemble voting, data quality, etc.)

- [ ] **Mechanical Behavior Analysis**
  - [ ] Count ensemble rejections
    - How many signals did strategies generate?
    - How many passed ensemble (2+ vote requirement)?
    - What's the rejection rate?
  - [ ] Regime breakdown
    - Which regimes did we trade in? (trend, range, panic, etc.)
    - Did regime_trend get disabled during range periods? (expected: yes, if filter enabled)
    - Performance per regime (win rate by regime)
  - [ ] Strategy performance
    - Which strategies had best WR?
    - Which strategies worst?
    - Any strategy combinations firing consistently?

- [ ] **Backtest Comparison Report**
  - Create a simple table:
    | Metric | Backtest Expected | Paper Trading Actual | Match? |
    |--------|-------------------|----------------------|--------|
    | Win Rate % | XX% | YY% | ✓/✗ |
    | Profit Factor | X.Xx | Y.Yy | ✓/✗ |
    | Max Drawdown % | X% | Y% | ✓/✗ |
    | Trades/Week | N | N | ✓/✗ |
    | Regime Filter Active | Yes/No | Yes/No | ✓/✗ |
  - If "Match?" is ✗, document the discrepancy for next week's debugging

- [ ] **System Health Audit**
  - [ ] Zero crashes or hangs (ok if API rate-limit warnings)
  - [ ] Data freshness (OHLCV candles within 5 min of real time)
  - [ ] Position reconciliation (no stuck positions)
  - [ ] Circuit breaker state (is it ever triggered? expected: rarely)
  - [ ] LLM cost (should be $0, since LLM_MODE=0)

### Phase 3: LLM Veto Mode Prep (Days 6-7)

**Goal:** Get infrastructure ready for Phase 1 of LLM activation next week.

- [ ] **Veto Mode Setup**
  - [ ] Review `bot/multi_strategy_main.py` lines 2748-2759 (veto wiring)
  - [ ] Confirm API key pre-flight check will work
  - [ ] File: `bot/run.py` or `bot/multi_strategy_main.py` startup
  - [ ] Add: Check `ANTHROPIC_API_KEY` exists at startup
  - [ ] If missing: Log warning, set `LLM_MODE=0` automatically

- [ ] **Veto Outcome Tracking**
  - [ ] Create new file: `bot/data/llm/veto_outcomes.jsonl`
  - [ ] After each LLM veto: Log `{signal, veto_reason, market_price_after, pnl_avoided_or_missed}`
  - [ ] This is how we'll measure LLM value next week

- [ ] **Confidence Calibration Prep**
  - [ ] Review `bot/llm/feedback/` (feedback loop system)
  - [ ] Note current trust score settings (should be 0.30 or similar)
  - [ ] Plan: Once LLMs activate, we'll start calibrating these

- [ ] **Test Mock Veto** (optional, if time permits)
  - [ ] Manually inject a mock veto into signal pipeline
  - [ ] Confirm: Signal gets dropped, logged, system doesn't crash
  - [ ] This validates the wiring before we go live with LLM

### Phase 4: Final Week 1 Review (Day 7)

- [ ] **Stabilization Checklist**
  - [ ] ✓ All 3 bugs fixed and tested
  - [ ] ✓ Website shows trades
  - [ ] ✓ No crashes in 3+ days of paper trading
  - [ ] ✓ Baseline performance metrics captured
  - [ ] ✓ Backtest/paper parity confirmed (or discrepancies documented)
  - [ ] ✓ Regime filter behavior understood and intentional
  - [ ] ✓ Veto mode infrastructure ready

- [ ] **Sign-Off**
  - [ ] Create Week 1 Summary:
    - Trades executed: N
    - Win rate: X%
    - Max drawdown: Y%
    - Biggest issue: [regime filter / ensemble bottleneck / other]
    - Recommendation for Week 2: [proceed to LLM veto / fix issue first]

---

## CSV PATH FIX (PRIORITY 1)

**File:** `api/app/routes_trades.py:23`

**Current (Wrong):**
```python
df = pd.read_csv(os.path.join(DATA_DIR, "trades.csv"))  # empty header only
```

**Fix:**
```python
# Option A: Read from actual trades file
df = pd.read_csv(os.path.join(DATA_DIR, "trades_10d.csv"))  # real trades here

# Option B: Make bot write to trades.csv (preferred for long-term)
# Ensure bot/multi_strategy_main.py writes to bot/trades.csv on each close
```

**Test:**
```bash
curl http://localhost:8000/api/trades | jq '.trades | length'
# Should return: number > 0 (not empty)
```

---

## CSV PATH FIX (PRIORITY 2 & 3)

See original Master Plan bugs (copy-trade crash, signal persistence).

---

## REGIME FILTER DECISION TABLE

| Decision | Action | Impact |
|----------|--------|--------|
| **Keep filter TRUE** (default) | Leave as is. regime_trend disables in ranges. | Paper matches backtest. Correct behavior — regime_trend is terrible in ranges. |
| **Set filter FALSE** | Change .env: `ENABLE_REGIME_STRATEGY_FILTER=false` | More trades. But paper won't match backtest unless you also disable in backtest code. ⚠️  This is a mismatch problem. |
| **Disable in backtest too** | Edit `bot/backtest/engine.py:688-716`, comment out filter. | Both run without filter. Need new backtest baseline. Likely worse performance. |

**Recommendation:** Keep filter TRUE (default). regime_trend honestly does perform worse in ranges. The filter is correct.

---

## CONFIG VERIFICATION COMMANDS

```bash
# Check current .env settings
grep -i "ENABLE_REGIME_STRATEGY_FILTER\|LLM_MODE" /home/user/WAGMI/.env

# Verify defaults in code
grep -n "enable_regime_strategy_filter" /home/user/WAGMI/bot/trading_config.py

# Check backtest behavior
grep -n "enable_regime_strategy_filter" /home/user/WAGMI/bot/backtest/engine.py
# Should return NOTHING (backtest always applies filter)

# Check paper trading behavior
grep -n "enable_regime_strategy_filter" /home/user/WAGMI/bot/multi_strategy_main.py
# Should return line 2651 (paper trading checks config flag)
```

---

## FILES TOUCHED THIS WEEK

| File | Change | Reason |
|------|--------|--------|
| `api/app/routes_trades.py:23` | Point to `trades_10d.csv` | Bug fix: trades not visible |
| `web/pages/copy-trade.tsx:771,823` | Add null guards | Bug fix: crash on undefined symbol |
| `bot/run.py` or startup | Add API key check | Pre-flight validation |
| `bot/data/llm/veto_outcomes.jsonl` | Create file (new) | Track veto outcomes for next week |
| `.env` | Verify/set `ENABLE_REGIME_STRATEGY_FILTER` | Align config between backtest & paper |
| `.env` | Ensure `LLM_MODE=0` | Keep LLM off this week |
| `bot/multi_strategy_main.py` | Review lines 2748-2759 | Understand veto wiring |

---

## SUCCESS CRITERIA FOR WEEK 1

**MUST HAVE:**
- [ ] 10+ trades executed in paper trading
- [ ] Website displays all trades
- [ ] No crashes or hangs in 3+ days
- [ ] Backtest/paper behavior parity confirmed OR discrepancies documented
- [ ] Regime filter setting intentional (not accidental)

**NICE TO HAVE:**
- [ ] Win rate baseline established (any %, just a number)
- [ ] Max drawdown understood
- [ ] Veto mode infrastructure ready to go

**IF NOT MET BY END OF WEEK:**
- Extend week 1 until "MUST HAVE" items are done
- Do NOT proceed to LLM activation until mechanical system is stable

---

## WEEK 2 PREVIEW (NOT THIS WEEK, BUT PLAN AHEAD)

Once Week 1 is done and we have mechanical confidence:

1. **Phase 1: Veto Mode** (LLM_MODE=2)
   - LLM can block bad trades before execution
   - Cost: ~$0.003/veto (very cheap)
   - Duration: 2-3 days
   - Success metric: 1+ vetoes logged, system stable

2. **Phase 2: Multi-Agent Pipeline** (LLM_MULTI_AGENT=true)
   - 5 specialist agents (Regime, Trade, Risk, Critic, Learning)
   - Cost: ~$0.007/decision
   - Duration: 3-4 days
   - Success metric: 10+ agent decisions captured, thesis accuracy tracked

3. **Closed-Loop Learning**
   - Learning Agent extracts lessons from closed trades
   - Future decisions read past lessons
   - Deep memory gets smarter over time

---

## KEY CONTACTS & RESOURCES

- **Backtest baseline:** `bot/backtest_60d_equity_curve.csv` or similar
- **Paper trades:** `bot/trades_10d.csv`
- **Regime filter logic:** `bot/llm/agents/shared_context.py` (STRATEGY_REGIME_FIT table)
- **Main trading loop:** `bot/multi_strategy_main.py` (2651-2675 regime filter, 2748-2759 veto)
- **Backtest engine:** `bot/backtest/engine.py` (688-716 regime filter)

---

## QUESTIONS TO ANSWER BY END OF WEEK 1

1. **Regime Filter:** Is it intentional that regime_trend disables in range markets? YES/NO
2. **Performance Parity:** Does paper trading match backtest win rate? YES/NO / UNKNOWN
3. **Trade Volume:** Are we getting 10+ trades per week? YES/NO
4. **System Stability:** Zero crashes in 3+ days? YES/NO
5. **Ready for LLM?** Is mechanical system stable enough to layer LLMs on top? YES/NO

---

**End of WEEK 1 MASTER PLAN**

Next week we activate LLMs. Next next week we go live with capital.

This week: mechanical confidence. That's it. That's the goal.
