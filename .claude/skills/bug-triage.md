# /bug-triage — Fix Money-Losing Bugs

## Description
Triage and fix the critical bugs documented in ROADMAP.md that are actively losing money or preventing profitable trading. Prioritized by PnL impact.

## Arguments
- `$ARGUMENTS` — Optional: "critical" (must-fix for live), "all" (every known bug), or specific bug name

## Workflow

### 1. Load Bug List
Read `ROADMAP.md` section 8 — "Critical Bugs Still Open."
Also scan codebase for TODO/FIXME/HACK/BUG comments:
```bash
cd bot && grep -rn "TODO\|FIXME\|HACK\|BUG\|XXX" --include="*.py" | grep -v __pycache__ | grep -v test
```

### 2. Critical Bugs (Must Fix for Live Trading)

**Bug 1: Signal mutation in-place (ensemble.py)**
- Location: `bot/strategies/ensemble.py:326-366`
- Impact: Downstream logging sees FLIPPED signal, not original. Trades may be executing on corrupted signals.
- PnL Impact: HIGH — wrong signal = wrong trade
- Fix: Deep-copy signal before mutation
- Verify: `cd bot && pytest tests/ -k "ensemble" -v`

**Bug 2: No exchange connection resilience (data/fetcher.py)**
- Location: `bot/data/fetcher.py`
- Impact: Bot CRASHES on API outage. During a crash, open positions have no management.
- PnL Impact: HIGH — unmanaged positions during volatility
- Fix: Add exponential backoff + circuit breaker (1s, 2s, 4s, 8s, 16s)
- Note: CoinGecko fallback exists but exchange-specific circuit breaker needed

**Bug 3: Strategy data requirements incompatible**
- Location: Multiple strategy files
- Impact: Silent no-signal when data is missing for a timeframe
- PnL Impact: MEDIUM — missing trades in profitable conditions
- Fix: Validate data availability before strategy eval, graceful degradation

**Bug 4: Telegram decimal parsing**
- Location: `bot/signals/telegram_ingest.py:122`
- Impact: Misses signals with "97,500.50" format
- PnL Impact: LOW-MEDIUM — missed external signals
- Fix: Fix regex to handle comma+decimal

**Bug 5: Strategy weights from ALL history equally**
- Location: `bot/data/strategy_weights.py`
- Impact: Ancient trades have same weight as recent ones
- PnL Impact: MEDIUM — strategy weights lag market changes
- Fix: Exponential decay weighting (recent trades weighted more)

**Bug 6: No position reconciliation on startup**
- Location: `bot/execution/reconciliation.py`
- Impact: Lost positions after restart — orphan positions with no SL
- PnL Impact: HIGH — unmanaged positions
- Fix: Read exchange positions on boot, reconcile with in-memory state

### 3. Reliability Bugs

**Bug 7: LLM memory 50-note/48h limit**
- Location: `bot/llm/memory_store.py`
- Impact: Hard-won lessons forgotten too quickly
- Note: ROADMAP says this was expanded to 100 notes/7 days. Verify current values.

**Bug 8: multi_strategy_main.py is 4,585 lines**
- Location: `bot/multi_strategy_main.py`
- Impact: God object, hard to maintain, easy to introduce bugs
- Fix: Break into modules (Phase 5 in ROADMAP)

### 4. Priority Scoring
Score each bug by:
- **PnL Impact**: How much money does this bug cost per month?
- **Fix Difficulty**: Hours to fix + test
- **Risk of Fix**: Could the fix break something else?

```
BUG PRIORITY MATRIX
━━━━━━━━━━━━━━━━━━━
#  Bug                      PnL Impact  Fix Time  Risk   Priority
1  Signal mutation           HIGH        1h        LOW    FIX NOW
2  Exchange resilience       HIGH        3h        LOW    FIX NOW
6  No position reconcile     HIGH        4h        MED    FIX NOW
5  Strategy weight decay     MEDIUM      2h        LOW    FIX SOON
3  Data requirement mismatch MEDIUM      3h        LOW    FIX SOON
4  Telegram decimal parse    LOW         30min     LOW    QUICK WIN
7  Memory limit              LOW         1h        LOW    NICE TO HAVE
8  Main.py breakup           NONE (maint) 8h+     HIGH   DEFER
```

### 5. Fix Each Bug
For the top-priority bugs, implement the fix:

1. Read the affected file(s) completely
2. Understand the bug mechanism
3. Write the fix
4. Write/update tests
5. Run tests: `cd bot && pytest tests/ -x -v`
6. Verify fix doesn't break anything else
7. Commit with clear message

### 6. Verification
After fixing:
- Run full test suite
- Run signal check: `cd bot && python run.py signals`
- Run backtest to verify no regression
- Check that the specific bug scenario is now handled

### 7. Report
```
BUG TRIAGE — <timestamp>
━━━━━━━━━━━━━━━━━━━━━━━

CRITICAL BUGS: X found
FIXED THIS SESSION: X
REMAINING: X

FIXES APPLIED:
  ✓ Signal mutation — deep copy added (est. savings: $XXX/mo)
  ✓ Exchange resilience — backoff + circuit breaker added
  ✗ Position reconciliation — needs exchange API testing

ESTIMATED PnL IMPACT OF FIXES: +$XXX/month

NEXT FIX: [Bug name] — [estimated time]
```
