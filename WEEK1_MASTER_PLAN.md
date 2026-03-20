# WAGMI Week 1 Master Plan — Mechanical Stability

**Objective:** Establish mechanical confidence in the trading system. Stabilize website. Baseline performance metrics.

**Timeline:** 7 days (this week)
**Scope:** Bug fixes, mechanical testing, data collection
**Next Week:** LLM activation (phased per original Master Plan)
**Week 3:** Full capital deployment

---

## WEEK 1 CHECKLIST

### Phase 0: Critical Pre-Flight (Day 1, ~30 min)

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


## FILES TOUCHED THIS WEEK

| File | Change | Reason |
|------|--------|--------|
| `api/app/routes_trades.py:23` | Point to `trades_10d.csv` | Bug fix: trades not visible |
| `web/pages/copy-trade.tsx:771,823` | Add null guards | Bug fix: crash on undefined symbol |
| `bot/run.py` or startup | Add API key check | Pre-flight validation |
| `bot/data/llm/veto_outcomes.jsonl` | Create file (new) | Track veto outcomes for next week |
| `.env` | Ensure `LLM_MODE=0` | Keep LLM off this week |
| `bot/multi_strategy_main.py` | Review lines 2748-2759 | Understand veto wiring |

---

## SUCCESS CRITERIA FOR WEEK 1

**MUST HAVE:**
- [ ] 10+ trades executed in paper trading
- [ ] Website displays all trades
- [ ] No crashes or hangs in 3+ days
- [ ] Backtest/paper behavior parity confirmed OR discrepancies documented

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
- **Main trading loop:** `bot/multi_strategy_main.py` (2748-2759 veto)
- **Backtest engine:** `bot/backtest/engine.py` (688-716 regime filter)

---

## QUESTIONS TO ANSWER BY END OF WEEK 1

1. **Performance Parity:** Does paper trading match backtest win rate? YES/NO / UNKNOWN
2. **Trade Volume:** Are we getting 10+ trades per week? YES/NO
3. **System Stability:** Zero crashes in 3+ days? YES/NO
4. **Ready for LLM?** Is mechanical system stable enough to layer LLMs on top? YES/NO

---

**End of WEEK 1 MASTER PLAN**

Next week we activate LLMs. Next next week we go live with capital.

This week: mechanical confidence. That's it. That's the goal.
