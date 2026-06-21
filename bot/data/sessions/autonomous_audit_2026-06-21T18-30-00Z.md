# AUTONOMOUS QUANT AUDIT — 2026-06-21T18:30:00Z
**Run**: 115 | **Bot Status**: OFFLINE — Day 69.25 | **Data**: backtest_100d.csv (n=589)

---

## EXECUTIVE SUMMARY

Bot remains offline for 69+ days; `trades.csv` is header-only. All 5 phases executed against `backtest_100d.csv` (589 trades, BTC/HYPE/SOL). Three structural issues stand out this cycle:

1. **HYPE SHORT confidence inversion**: trades at 75–85% confidence have only 30–33% WR and cost -$4,155 across 40 trades — while HYPE SHORT at <75% confidence earns +$808. The `hype_short_veto_v1` (gate=100%) is already live and blocks this; but the rule was built from 10d data and this 100d view confirms the veto was correct and should remain.

2. **SOL SHORT exclusion fix is structurally blocked**: Previous audit (Run 114) recommended adding `exclude_symbols=['SOL']` to `short_direction_veto_v1`. Code audit confirms `matches()` has **no `exclude_symbols` field** — this is a code change, not a JSON edit, and has not been made in 4+ consecutive runs despite the recommendation.

3. **`btc_short_90plus_boost_v1` (times_applied=0)**: This is the highest-confidence BTC SHORT boost rule (adj=+12, gate=20%) and has never fired. Either BTC SHORT at 90%+ confidence never occurs in live/paper mode, or there is a rule-evaluation path that skips it. Cannot monetize this edge until root cause is found.

Persistent bugs from prior runs: `duration_h=0.0` for 91.2% of trades (HoldTimeRuleManager blind), 3 feedback state files missing (auto-creates on restart), `record_outcome()` side-vocabulary mismatch (LONG/SHORT vs BUY/SELL).

---

## PHASE 1: System Audit

**AUDIT COMPLETE: 7 systems verified, 4 gaps found**

### Feedback System Instantiation (`multi_strategy_main.py`)
| System | Instantiated | Line | `record_outcome()` | State File |
|--------|-------------|------|-------------------|------------|
| `RegimeFeedbackManager` | ✓ | 412 | ✓ line 3135 | ✗ `regime_feedback_state.json` MISSING |
| `AdaptiveConfidenceFloor` | ✓ | 415 | ✓ line 3144 | ✗ `confidence_state.json` MISSING |
| `HoldTimeRuleManager` | ✓ | 418 | ✓ line 3151 | ✓ `hold_time_rules_state.json` (Jun 5) |
| `SignalQualityScorer` | ✓ | 421 | ✓ line 3159 | ✗ `signal_quality.json` MISSING |
| `ParameterTuner` | ✓ | 424 | ✓ line 3166 | — (in `data/feedback/`) |
| `FeedbackLoop` | ✓ | 804 | ✓ line 3233 | — (in `feedback/`) |
| `AutoOptimizer` | ✓ | 909 | ✓ line 3193 | ✓ (lazy-init on first tick) |

### Gaps Found

**GAP-1: 3 feedback state files missing** (`regime_feedback_state.json`, `signal_quality.json`, `confidence_state.json`)  
Root cause: created on first `record_outcome()` call; bot offline 69 days = zero trade closes = files never written.  
Impact: These 3 systems restart cold; any pre-shutdown calibration is lost. Auto-resolves on first live trade close.

**GAP-2: `duration_h` broken in backtest data (91.2% zeros)**  
Backtest engine code (engine.py line 2522–2540) attempts sim-time fallback when `hold_time_s < 60`, but fallback reads `entry_reasons.get("sim_time")` and `meta.get("close_sim_time")`. In the 100d backtest: 537/589 trades have `duration_h=0.0`, 52 have `duration_h<0` (invalid), 0 trades have valid positive duration.  
Impact: `HoldTimeRuleManager` cannot learn minimum hold rules. The `hold_time_rules_state.json` shows `min_hold_hours=3.0` set manually in May 2026, not from data.

**GAP-3: `record_outcome()` side-vocabulary mismatch (persistent)**  
Line 3256: `get_graduated_rules_engine().record_outcome(...)` passes `side=event.side` which is `"LONG"/"SHORT"` (position side). Rule conditions use `"BUY"/"SELL"`. `matches()` check at line 44: `side.upper() != c["side"].upper()` → "LONG" ≠ "SELL" → no match → `times_correct` never incremented for side-conditioned rules. All 21 active rules with a `side` condition show `times_correct=0`.

**GAP-4: `exclude_symbols` not implemented in `GraduatedRule.matches()`**  
The `matches()` method (graduated_rules.py line 44–100) has no `exclude_symbols` field. The recommendation to exclude SOL from `short_direction_veto_v1` cannot be done via JSON rule editing — requires a code change to `matches()`. This fix has been recommended for 4+ consecutive audit runs without implementation.

---

## PHASE 2: Trade Forensics

**FORENSICS COMPLETE: 3 high-value sub-conditions found, 2 regression areas**

### Dataset
- **Source**: `bot/backtest_100d.csv`, n=589 trades, symbols: BTC (n=166), HYPE (n=225), SOL (n=198)
- **Note**: `trades.csv` (live) is EMPTY — bot offline 69 days

### Overall Statistics
| Metric | Value |
|--------|-------|
| Total trades | 589 |
| Win rate | 44.5% (262W / 327L) |
| Total PnL | **-$8,173.52** |
| Avg PnL/trade | -$13.88 |
| Total fees | $859.76 |
| Avg SL loss | -$108.92 |
| Avg TP win | +$101.26 |
| Payoff ratio | **0.930x** |
| Break-even WR | 54.0% (system at 44.5% = net negative) |

### By Symbol
| Symbol | n | WR% | Total PnL | Avg PnL | Verdict |
|--------|---|-----|-----------|---------|--------|
| BTC | 166 | 42.2% | -$637 | -$3.84 | ✗ Marginal loser |
| HYPE | 225 | 48.9% | **-$5,564** | -$24.73 | ✗ Primary bleeder |
| SOL | 198 | 41.4% | **-$1,972** | -$9.97 | ✗ Structural loser |

### By Confidence Bin (inverse correlation detected)
| Confidence | n | WR% | Total PnL | Signal |
|-----------|---|-----|-----------|--------|
| 60–70% | 111 | 48.6% | -$794 | Marginally viable |
| 70–80% | 321 | 45.2% | -$2,742 | Below break-even |
| 80–90% | 120 | 40.0% | **-$3,965** | ✗ WORST BAND — inverse confidence |
| 90%+ | 37 | 40.5% | -$672 | ✗ Confidence fails to predict outcomes |

**Critical**: Higher confidence correlates with LOWER win rate in this 100d dataset. This is the inverse confidence paradox — the model's confidence score is miscalibrated.

### By Close Reason
| Close Reason | n | WR% | Total PnL |
|-------------|---|-----|----------|
| SL | 269 | 0% | **-$29,300** |
| TP1 | 160 | 100% | +$19,521 |
| TP2 | 49 | 100% | +$1,643 |
| TRAILING_STOP | 111 | 47.7% | -$37 |

### Hold Time Analysis
**All 589 trades: duration_h = 0.0 or negative (0 valid entries).**  
`HoldTimeRuleManager` is receiving garbage input — min_hold constraint is set from manual entry only.

### HYPE SHORT Confidence Inversion (Key Finding)
HYPE SHORT at 75–85% confidence is the single worst sub-condition in the 100d dataset:

| HYPE SHORT Band | n | WR% | Total PnL | Status |
|----------------|---|-----|-----------|-------|
| <70% | 15 | **60.0%** | +$229 | ✓ Profitable niche |
| 70–75% | 65 | **52.3%** | +$579 | ✓ Viable |
| 75–80% | 27 | **33.3%** | **-$2,727** | ✗ DANGER — veto justified |
| 80–85% | 13 | **30.8%** | **-$1,429** | ✗ DANGER — veto justified |
| 85%+ | 37 | 54.1% | -$1,239 | ✗ Wins but large asymmetric SL losses |

**`hype_short_veto_v1` (gate=100%) is already active** — this 100d data validates the veto was correct. Do not deactivate.

### Top 5 Losses (all HYPE SHORT SL hits)
| Symbol | Side | Entry | Confidence | PnL |
|--------|------|-------|------------|-----|
| HYPE | SHORT | 37.78 | 70.4% | **-$520.86** |
| HYPE | SHORT | 26.90 | 87.5% | -$516.46 |
| HYPE | SHORT | 37.53 | 81.5% | -$512.22 |
| HYPE | SHORT | 28.25 | 71.3% | -$511.20 |
| HYPE | SHORT | 37.62 | 85.4% | -$451.13 |

Common pattern: HYPE SHORT at any confidence level with large dollar-denominated SL (high leverage × wide stop). Avg top-10 loss = -$470.

### Top 5 Wins
| Symbol | Side | Entry | Confidence | PnL |
|--------|------|-------|------------|-----|
| SOL | SHORT | 130.75 | 79.7% | **+$713.84** |
| HYPE | SHORT | 30.51 | 87.5% | +$598.26 |
| HYPE | SHORT | 34.34 | 71.1% | +$494.33 |
| HYPE | SHORT | 33.42 | 69.0% | +$452.54 |
| HYPE | SHORT | 37.82 | 72.1% | +$425.95 |

Common pattern: SHORT direction at moderate confidence (69–80%), clean TP1 hit in <1h sim-time. SOL SHORT remains the best single-trade edge.

### HIGH-VALUE Sub-Conditions Found
1. **HYPE SHORT < 75% confidence**: 80 trades, 54.4% WR, +$808 total. Profitable niche within a losing symbol — already blocked by `hype_short_veto_v1`.
2. **SOL SHORT any confidence**: n=198, 41.4% WR overall but concentrated losses from wide SL hits. Sub-condition analysis needed by n_agree/regime (data not available in this CSV).
3. **HYPE/SOL SHORT TP1 hits**: 100% conversion when TP1 is hit → position sizing at TP1 exit is profitable unit; the P&L drain comes entirely from SL hits.

### Regression Areas
1. **All-symbol WR degraded** vs last audit's 10d view (57% WR on n=965) vs this 100d view (44.5% on n=589). The 100d includes older, lower-quality pre-optimization trades.
2. **Payoff ratio 0.930x** (100d) vs 0.686x (10d). 100d is slightly better but still below 1.0 break-even for a 50% WR system.

---

## PHASE 3: Hypothesis Validation

**VALIDATION COMPLETE: 3 confirmed, 3 stale/broken, 13 invalidated (pre-marked)**

### Active (non-invalidated) Insights — Re-checked Against 100d Data

| # | Insight | Status | Evidence |
|---|---------|--------|----------|
| 1 | Night 0-6 UTC: 15% WR (n=13 from backtest) | ✓ **CONFIRMED** | `night_session_block_v1` active, gate=100%. Structural: thin liquidity overnight. |
| 2 | Ensemble concentration 94% of trades | ✓ **CONFIRMED** | 100% ensemble in 100d (n=589, all `strategy=ensemble`). Diversification gap persists. |
| 3 | Size edge (larger positions 57% WR vs 31%) | ✗ **INVALIDATED** | Pre-marked invalidated (Run 91). In 100d data: 80–90% confidence (larger positions) WR=40.0% vs 60–70% (smaller positions) WR=48.6%. Contradicts size edge claim. |

### Stale Insights Flagged
- **Insight #2 "Night 0-6 UTC weakness" (evidence_count=13)**: Active and confirmed, but evidence base remains n=13. Low statistical power. Rule is correct but confidence should not be raised further until n≥50 live trades in this window are observed.
- **`btc_short_90plus_boost_v1` never fires**: Rule exists in graduated_rules.json with `times_applied=0`. Either BTC SHORT at 90%+ confidence never occurred in any live session, or there's a rule-matching path that skips boost rules. **This is a stale non-firing rule** — needs investigation (see Phase 5 Rec 2).

### Graduated Rules Accuracy Crisis
Of 21 active rules, **all show `times_correct=0`** for any rule with a `side` condition. Root cause confirmed: `record_outcome()` passes `side="LONG"/"SHORT"` but `matches()` expects `"BUY"/"SELL"`. The accuracy tracking system for side-conditioned rules is completely broken. Rules are applying and vetoing correctly (correct direction), but accuracy is never credited — so the engine cannot auto-deactivate rules based on accuracy.

---

## PHASE 4: Feedback Loop Closure

**LOOP CLOSURE: 0 live trades to propagate; 5 structural broken links (unchanged from Run 114)**

Bot has been offline 69.25 days. `trades.csv` = header only. No live trade data to trace through the feedback pipeline. Using the last 3 full-close trades from `backtest_100d.csv` as a reference scenario:

| Trade | Outcome | WR Signal |
|-------|---------|----------|
| BTC SHORT TRAILING_STOP, conf=70.3 | LOSS, -$4.05 | Would record to: weight_mgr ✓, regime_feedback ✗ (file missing), confidence_floor ✗ (file missing), signal_quality ✗ (file missing), hold_time_rules ✓ (file exists, but hold_hours=0.0 → useless), llm_memory ✓ (if LLM active) |
| BTC SHORT SL, conf=67.9 | LOSS, -$18.27 | Same as above |
| BTC LONG TRAILING_STOP, conf=67.2 | WIN, +$2.22 | Same as above |

### Broken Links Summary
| Link | Status | Impact |
|------|--------|--------|
| `regime_feedback_state.json` | MISSING — auto-creates on first trade | RegimeFeedbackManager cold on restart |
| `signal_quality.json` | MISSING — auto-creates on first trade | SignalQualityScorer cold on restart |
| `confidence_state.json` | MISSING — auto-creates on first trade | AdaptiveConfidenceFloor cold on restart |
| `hold_time_rules.record_trade(hold_hours=0.0)` | DATA CORRUPT | HoldTimeRuleManager receives invalid hold times; cannot learn regime-specific min-hold rules |
| `record_outcome(side="LONG"/"SHORT")` vs rule `side="BUY"/"SELL"` | MISMATCH (line 3256) | GraduatedRules accuracy tracking broken for all 16 side-conditioned rules |

---

## PHASE 5: Recommendations

**RECOMMENDATIONS: 3 changes proposed, estimated $150–250/day impact when live**

---

### REC 1 — Add `exclude_symbols` to `GraduatedRule.matches()` to unblock SOL SHORT

**Problem**: `short_direction_veto_v1` (gate=20%) blocks all SELL signals including SOL SHORT. SOL SHORT had WR=63.7% and EV=+$32.44/trade on n=179 in 10d data. In 100d data, SOL SHORT accounts for the best single trade (+$713.84). Estimated cost: 179 SOL SHORT trades/10d × $32.44/trade = **$5,806 foregone per 10-day period** if live.

**Root Cause**: `matches()` in `graduated_rules.py` has no `exclude_symbols` field. Previous audits recommended JSON-only fix; that is not possible.

**Proposed Fix** (specific, testable):
```python
# graduated_rules.py, in matches() after line ~55 (symbol check), add:
if c.get("exclude_symbols"):
    if symbol.upper() in [s.upper() for s in c["exclude_symbols"]]:
        return False
```
Then update `short_direction_veto_v1` in `data/llm/graduated_rules.json`:
```json
"conditions": {"side": "SELL", "exclude_symbols": ["SOL"]}
```

**Expected Impact**: Unlocks SOL SHORT edge. At current system WR, SOL SHORT profitable sub-conditions (WR>54%) would contribute +$32/trade × estimated 5 trades/day = **+$160/day when live**.

**A/B Test**: Enable in paper mode for 14 days. Compare SOL SHORT WR vs historical 63.7% baseline. Rollback if WR drops below 50% over 30+ trades.

**Rollback**: Remove `exclude_symbols` from the rule JSON condition (revert to blocking all SELL including SOL).

**Confidence**: 82%

---

### REC 2 — Investigate and fix `btc_short_90plus_boost_v1` (times_applied=0)

**Problem**: Rule `btc_short_90plus_boost_v1` (conditions: `symbol=BTC, side=SELL, confidence_min=90.0`, adjustment=+12, gate=20%) has `times_applied=0` across all audit runs. BTC SHORT at 90%+ confidence should be a rare but high-conviction edge. In 100d data, 37 trades had 90%+ confidence with 40.5% WR — but none were BTC SHORT specifically at this level.

**Root Cause Hypotheses**:
1. BTC SHORT at 90%+ confidence simply never occurs (signal too rare or confidence calibration peaks below 90 for BTC SHORT).
2. The rule evaluation path for boost rules at gate=20% is executed but not reaching BTC SHORT at that confidence level.
3. Side vocabulary mismatch: the rule uses `side=SELL` and the signal correctly passes `side=SELL` (via `cli.py` line 223–225 conversion), but `times_applied` may only increment on explicit signal processing path, not all call sites.

**Proposed Fix**:
1. Add a diagnostic log to `GraduatedRulesEngine.evaluate_signal()` that logs when `btc_short_90plus_boost_v1` matches (even at 0% gate). Run paper mode and check logs.
2. If rule never matches: lower `confidence_min` to 85.0 (there are 120 trades at 80–90% with 40.0% WR — BTC SHORT subset may be positive).
3. If rule matches but never applies due to gate=20%: this is expected (fires only 1-in-5 qualifying signals). Increase gate to 50% to observe real-world accuracy.

**Expected Impact**: If BTC SHORT 90%+ WR is 60%+ (analogous to 10d data's BTC SHORT edge), activating this rule fully could add **+$20–40/day** when live.

**A/B Test**: 30-day paper mode with diagnostic logging. Compare BTC SHORT outcomes when rule fires vs doesn't (gate=20% creates natural A/B split).

**Rollback**: Set `active=false` in graduated_rules.json.

**Confidence**: 65%

---

### REC 3 — Fix `record_outcome()` side-vocabulary mismatch (line 3256)

**Problem**: `multi_strategy_main.py` line 3256 calls `get_graduated_rules_engine().record_outcome(..., side=event.side)` where `event.side` is `"LONG"` or `"SHORT"` (position side). Rule conditions store `"BUY"` and `"SELL"`. `matches()` checks `side.upper() != c["side"].upper()` → "LONG" ≠ "SELL" → no match → `times_correct` permanently 0 → accuracy tracking broken → engine cannot auto-deactivate failing rules.

**Root Cause**: `event.side` reflects position direction, not signal direction. The signal's side uses BUY/SELL vocabulary (signal pipeline). When trade closes, position side (LONG/SHORT) is recorded instead of the original signal side.

**Proposed Fix** (minimal, targeted):
```python
# multi_strategy_main.py, around line 3256, before calling record_outcome:
# Convert LONG/SHORT to BUY/SELL for rule vocabulary compatibility
_signal_side = "BUY" if event.side == "LONG" else "SELL"
get_graduated_rules_engine().record_outcome(
    ..., side=_signal_side, ...
)
```
OR store original signal side in `event.metadata` at entry time and read it here.

**Expected Impact**: Enables the auto-deactivation system to work for failing side-conditioned rules. Rules with genuine accuracy can be confirmed; failing rules (e.g., `btc_trend_long_counter_v1` with `times_applied=0`) can be correctly evaluated. Prevents accumulation of "zombie" rules that never get accuracy feedback.

**A/B Test**: After fix, monitor `times_correct/times_applied` ratios over 50 trades. Expect rules like `hype_long_veto_v1` (blocking 23% WR setups) to show high accuracy as they prevent losses.

**Rollback**: Revert the one-line change in `multi_strategy_main.py`.

**Confidence**: 95% (this is a clear bug with a trivial fix)

---

## SYSTEM MAP SNAPSHOT (2026-06-21T18:30Z)

| Component | Status | Last Updated |
|-----------|--------|-------------|
| Bot (live) | OFFLINE — Day 69 | ~2026-04-13 |
| trades.csv | EMPTY (header only) | — |
| backtest_100d.csv | 589 trades, WR=44.5%, PnL=-$8,173 | Backtest artifact |
| GraduatedRules (active) | 21 active / 31 total | Recent (Run 114) |
| HYPE SHORT veto | ACTIVE, gate=100% | Correct |
| HYPE LONG veto | ACTIVE, gate=100% | Correct |
| Night block (0-6 UTC) | ACTIVE, gate=100% | Correct |
| SOL SHORT block | PARTIAL (short_direction_veto, gate=20%) | Needs exclude_symbols fix |
| BTC SHORT 90%+ boost | ACTIVE but never fired | Investigate |
| HoldTimeRuleManager | Instantiated but receives 0.0 hold hours | Bug: fix duration_h |
| 3 feedback state files | MISSING | Auto-creates on first live trade |
| LLM memory | 1 note | Minimal |
| Insights | 5 active / 19 total (14 invalidated) | Good hygiene |

---

## CHANGES VS RUN 114 (2026-06-21T16:09Z)

- **No code changes** between Run 114 and this run (2h gap, same codebase)
- **New dataset**: This run analyzed `backtest_100d.csv` (n=589) vs Run 114's `trades_10d.csv` (n=965)
- **New finding**: HYPE SHORT 75–85% confidence "danger zone" confirmed in 100d data (validates existing `hype_short_veto_v1`)
- **New confirmation**: `exclude_symbols` code gap confirmed in `graduated_rules.py:matches()` — prior runs assumed JSON fix was possible; it requires code addition
- **Persistent**: BOT_OFFLINE (Day 69), duration_h bug, side-vocabulary mismatch, `btc_short_90plus_boost_v1` times_applied=0

---

*Generated by Autonomous Quant Audit Agent — Run 115 — 2026-06-21T18:30:00Z*
