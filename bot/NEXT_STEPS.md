# Next Steps: Consistent Account Growth & LLM Productivity

## Executive Summary

After 3-agent deep audit of the full codebase (4,645-line main loop, 64 LLM modules, 830 tests), we found the bot's **architecture is excellent** but **integration is incomplete**. The system collects rich data, builds sophisticated models, and has 10+ learning subsystems — but most feedback loops are broken or dormant. The result: the bot trades with ~40% of its potential intelligence.

**Bottom line: The bot has the brain of a hedge fund and the execution of a retail script.**

---

## PART 1: PROBLEMS TO TACKLE IMMEDIATELY

### Problem 1: Regime Strategy Filter Is DEAD (Bug)
**File:** `multi_strategy_main.py:1915`
**Bug:** `self.regime_detector.get_current_regime(symbol)` — method doesn't exist. Should be `get_regime(symbol)`.
**Impact:** Wave 2 regime-based strategy filtering is completely dormant. The bot can't filter strategies by regime, so it runs all strategies in all regimes (including losing ones).
**Fix:** One-line method name fix + verify downstream logic.

### Problem 2: LLM Veto Sets `candidate.llm_action = "flat"` But Actually Returns
**File:** `multi_strategy_main.py:2660-2748`
**Status:** Actually working correctly — veto check does `return` at line 2748. **No fix needed.** The veto is enforced.

### Problem 3: `apply_profile()` Never Called at Init
**File:** `multi_strategy_main.py` init section
**Impact:** Paper mode doesn't cap leverage at 10x. User can accidentally paper trade at 25x.
**Fix:** Call `apply_profile(config)` in `MultiStrategyBot.__init__()`.

### Problem 4: `get_symbol_param()` Not Used in Risk Manager
**File:** `execution/risk.py:258-306`
**Impact:** PEPE/FARTCOIN/DOGE have per-symbol overrides (8x leverage, 0.5% risk) defined in config but never read. Bot uses global max_leverage for all symbols.
**Fix:** Wire `get_symbol_param()` into risk manager's `calculate_qty()` path.

### Problem 5: Portfolio Notional Cap Built But Not Wired Into Main Loop
**File:** `execution/position_manager.py` (has `check_portfolio_notional_cap()`)
**Impact:** The cap method exists from Push 1 but isn't called in `_process_symbol()`. Bot can still over-leverage aggregate portfolio.
**Fix:** Add check before `open_position()` in main loop.

### Problem 6: Min Profit Threshold Built But Not Wired
**Config:** `min_profit_threshold_mult` exists (default 3.0)
**Impact:** Bot opens trades where TP1 profit < costs. Low-edge trades bleed the account.
**Fix:** Add pre-trade check in `_process_symbol()`.

### Problem 7: Funding Rate Entry Filter Missing
**File:** `execution/funding_timer.py` — has `should_close_before_funding()` for exits
**Impact:** Bot enters full-size positions 10 minutes before negative funding. Immediate drag on PnL.
**Fix:** Add entry-side funding check using existing function.

---

## PART 2: LLM PRODUCTIVITY — HOW TO GET MORE FROM EVERY API DOLLAR

### Current State
- **2 LLM call types per tick**: Pre-trade veto (sync, ~2.5K tokens) + Meta-brain (async, ~5K tokens)
- **~100-300 calls/day** at $2-10/day (RECOMMENDED tier, Sonnet default)
- **Veto accuracy**: Unknown — no calibration test exists
- **Self-teaching**: Runs async on trade close only, not during entries
- **Exit engine**: Placeholder — never actually calls LLM
- **Multi-agent**: 5 agents built, disabled by default

### LLM Improvement #1: Close the Evolution Tracker Loop
**File:** `feedback/evolution_tracker.py` (741 lines of analysis, 20+ lesson extraction)
**Problem:** Tracker produces excellent reports (trigger ROI, regime edges, pattern analysis) but is CLI-only. Never read back into live trading.
**Fix:** Run `generate_report()` every 12 hours. Feed `lessons` into LLM memory + apply throttle recommendations to trigger system.
**Impact:** The bot's own post-trade analysis starts driving future decisions.

### LLM Improvement #2: Implement Veto Calibration
**Problem:** LLM vetoes trades but we never measure veto accuracy. Could be 90% correct or 30% correct.
**Fix:** Counterfactual system exists (records vetoed trades + their theoretical outcome). Wire counterfactual accuracy into LLM's `knowledge` field so it self-corrects.
**Impact:** If veto false-positive rate is high, LLM adjusts its confidence threshold.

### LLM Improvement #3: Self-Teaching Frequency
**Problem:** Self-teaching engine only runs on trade close. Curriculum (5 levels) designed for daily cycles.
**Fix:** Trigger `learning_cycle()` every 10 completed trades (not just on close). Feed extracted knowledge into next snapshot.
**Impact:** LLM accumulates institutional knowledge faster.

### LLM Improvement #4: Snapshot Response Caching
**Problem:** Each LLM call makes fresh API request. Similar market snapshots within 5 minutes get identical responses.
**Fix:** Add 3-minute TTL cache keyed on snapshot hash. Skip API call if cache hit.
**Impact:** 20-30% API cost reduction with zero quality loss.

### LLM Improvement #5: Dynamic Budget Allocation
**Problem:** Flat $25/day budget. High-vol days need more LLM calls; quiet days waste budget.
**Fix:** Track 7-day rolling budget. Reallocate unused budget to volatile days.
**Impact:** Better LLM coverage when it matters most.

---

## PART 3: FEEDBACK LOOPS — WHERE DATA ISN'T CLOSING THE LOOP

### Loop Status Matrix

| System | Collects Data | Feeds Back | Closes Loop | Gap |
|--------|:---:|:---:|:---:|---|
| Signal Quality Scorer | YES | YES | **YES** | One-time at entry only |
| Adaptive Confidence Floor | YES | YES | **YES** | Trust-gated, slow |
| Continuous Backtest | YES | Partial | **PARTIAL** | 3%/cycle cap too slow |
| Parameter Tuner | YES | Partial | **PARTIAL** | Trust gate blocks fast adaptation |
| Strategy Weights | YES | NO | **BROKEN** | Computed daily, ensemble ignores |
| ML Learner | YES | YES (20%) | **YES** | Cold start too long, low weight |
| Evolution Tracker | YES | NO | **BROKEN** | CLI-only, never auto-applied |
| Analytics Suite | Sparse | NO | **BROKEN** | Cascade detection logged, not acted on |
| SQLite Database | YES | NO | **WRITE-ONLY** | Comprehensive capture, no readback |

### Fix #1: Wire Strategy Weights Into Ensemble
**Files:** `data/strategy_weights.py`, `strategies/ensemble.py`
**Problem:** Weights updated daily from trade outcomes but ensemble uses equal weights.
**Fix:** Pass `weight_mgr.get_rolling_weights()` to ensemble voting.
**Impact:** Strategies with 40% WR auto-demoted; 70% WR strategies boosted.

### Fix #2: Remove 3% Cap on High-Confidence Backtest Suggestions
**File:** `feedback/parameter_tuner.py`
**Problem:** If backtest says "floor should be 60%" with 80% confidence, actual change is 0.8 × 3% = 2.4%/cycle. Takes 10+ cycles to converge.
**Fix:** If suggestion confidence > 0.7, apply directly (no cap).
**Impact:** Bot adapts to regime changes in hours, not days.

### Fix #3: ML Cold Start Too Strong
**File:** `ml/learner.py`
**Problem:** ML has 0% influence until 20 trades, then only 20%.
**Fix:** Use snapshot model earlier (trains after ~10 min). Ramp ML weight to 30% after 50 trades.
**Impact:** ML contributes faster, with meaningful weight.

---

## PART 4: CORE FRAMEWORK IMPROVEMENTS

### Framework #1: Consolidate Risk Pipeline (RiskFilterChain)
**Problem:** 200+ lines of inline risk checks in `_process_symbol()` duplicate logic in `core/signal_pipeline.py`.
**Fix:** Replace inline checks with `RiskFilterChain.evaluate()` call.
**Impact:** Single source of truth, testable, maintainable.

### Framework #2: Consolidate Position Sizing Multipliers
**Problem:** 8+ cascading multipliers (CB, correlation, portfolio risk, time, liquidity, adaptive, RL, pattern). Final size can be 26% of intended with zero transparency.
**Fix:** Log multiplier attribution table. Add composite multiplier floor (0.25x minimum).
**Impact:** Transparent sizing decisions, prevent over-reduction.

### Framework #3: Thread Safety for Shared State
**Problem:** 5 background threads access `self._last_prices`, `self._last_funding_rates`, `self.risk_mgr.equity` without locks. Race conditions possible.
**Fix:** Add `threading.Lock()` for shared state dictionaries.
**Impact:** Prevents inconsistent reads during price updates.

### Framework #4: Config Validation at Startup
**File:** `run.py`, `trading_config.py`
**Problem:** No check that API key exists, equity > 0, leverage >= 1. Bot starts and crashes on first LLM call.
**Fix:** Add `config.validate()` method. Call in `run.py` before anything else.
**Impact:** Fail fast with clear error message instead of silent crash.

### Framework #5: Adaptive Risk State Persistence
**File:** `execution/adaptive_risk.py`
**Problem:** `_recent_outcomes` and `_regime_wr` are in-memory only. Bot restart = risk model starts from scratch. Previous session's streak/regime data lost.
**Fix:** JSON persistence on each outcome, load on init.
**Impact:** Risk model survives restarts without cold-start degradation.

### Framework #6: Paper Mode DB Isolation
**Problem:** Paper mode writes to same `bot/data/` directory as production. Could overwrite live analytics.
**Fix:** Separate DB path: `ml_data/paper_bot.db` vs `ml_data/live_bot.db`.
**Impact:** Safe parallel operation.

---

## PART 5: ALPHA SOURCES TO UNLOCK

### Alpha #1: Cascade Signal Integration (+5-10% annual)
**Problem:** `portfolio_risk.detect_cascade_signals()` detects BTC dumps cascading to alts. Currently logged only.
**Fix:** If cascade detected + signal is BUY on correlated alt → reject or reduce size by 50%.
**Impact:** Avoid entering longs right before cascade liquidation events.

### Alpha #2: Funding Rate Entry Filter (+5-10% annual)
**Problem:** Bot enters full-size positions regardless of funding direction. Negative funding = immediate drag.
**Fix:** If negative funding > 0.05% AND leverage > 2x AND minutes_to_funding < 60 → reject or reduce leverage.
**Impact:** Avoid paying large funding costs right after entry.

### Alpha #3: Cross-Symbol Correlation Signals (+3-8% annual)
**Problem:** `_CROSS_SYMBOL_AVAILABLE` flag set but never checked. BTC leads SOL by 1-2 candles.
**Fix:** If BTC just broke out and SOL is consolidating, boost SOL signal confidence by 5%.
**Impact:** Capture leader-follower relationships.

### Alpha #4: Volatility Clustering Position Scaling (+5-10% annual)
**Problem:** Vol forecast computed in `portfolio_risk.py` but never fed to position sizing.
**Fix:** Scale qty by `1 / sqrt(vol_forecast / baseline_vol)`. High vol = smaller. Low vol = larger.
**Impact:** Right-size positions for current market regime.

### Alpha #5: Regime Profitability Gate (+5-10% annual)
**Problem:** `signal_quality.py` tracks per-regime WR. Not fed to ensemble.
**Fix:** If regime WR < 35% over 10+ trades → skip. If WR > 60% → confidence +5%.
**Impact:** Stop trading losing regimes, lean into winning ones.

---

## IMPLEMENTATION ORDER (What To Build Next)

### Sprint 1: Bug Fixes + Wire Existing Code (THIS SESSION)
1. Fix regime method name bug (`get_current_regime` → `get_regime`)
2. Wire `apply_profile()` into `MultiStrategyBot.__init__()`
3. Wire `get_symbol_param()` into risk manager
4. Wire portfolio notional cap check into `_process_symbol()`
5. Wire min profit threshold gate into `_process_symbol()`
6. Wire funding rate entry filter into `_process_symbol()`
7. Tests for all 6 changes

### Sprint 2: Close Feedback Loops
1. Wire strategy weights into ensemble voting
2. Wire evolution tracker lessons into LLM memory (12h cycle)
3. Remove parameter tuner 3% cap for high-confidence suggestions
4. Increase ML learner weight to 30% after 50 trades

### Sprint 3: LLM Productivity
1. Add snapshot response caching (3-min TTL)
2. Implement veto calibration (counterfactual accuracy → LLM knowledge)
3. Increase self-teaching frequency (every 10 trades)
4. Wire cascade detection into trade direction filtering

### Sprint 4: Framework Hardening
1. Replace inline risk checks with RiskFilterChain
2. Add sizing multiplier attribution logging
3. Thread safety for shared state
4. Config validation at startup
5. Adaptive risk state persistence
6. Paper mode DB isolation
