# WAGMI Autonomous Quant Audit
**Timestamp:** 2026-06-20T12:03:38Z (Run 96, Day 64.58 offline)
**Auditor:** Claude Autonomous Quant Agent | **Standard:** Institutional-grade quant review
**Prior Audit:** 2026-06-20T10:06:37Z (Run 95, ~2h gap)
**Cadence Streak:** 19 consecutive ~2h runs (Runs 78–96)
**Datasets analyzed:** 10d_v3 backtest (n=32), 100d_v2 backtest (n=16), feedback state files, meta_learning/insights.json (19 total, 6 active), graduated_rules.json (25 rules), deep_memory insight_journal (213 entries)

---

## EXECUTIVE SUMMARY

**P0: Bot OFFLINE Day 64.58. No state changes since Run 95 (10:06 UTC, 2h ago). No new trades.**

Three critical findings from this run vs. prior:

1. **NEW P0: Veto rules appear INVERTED relative to recent performance.** `sol_long_veto_v1` blocks SOL BUY (34 live trades, 24% WR from historical period) — but 10d_v3 backtest shows SOL LONG at **100% WR, 8/8, +$1,895 net**. Meanwhile `sol_short_penalize_v1` only penalizes (not vetoes) SOL SHORT, which shows **17% WR, 1/6, -$1,125 net** in the same backtest. The veto and penalty are pointing at the wrong direction.

2. **NEW P0: SHORT trades are catastrophically failing (18% WR across 11 trades, -$2,104 net).** SOL SHORT = 17% WR (-$1,125), BTC SHORT = 20% WR (-$979). Only `sol_short_penalize_v1` (penalize, not veto) and `btc_short_conf70_80_penalize_v1` (narrow confidence band only) protect against this. The system is missing a general SHORT direction veto.

3. **CONFIRMED: EVENING_session_boost / graduated rules TOD data conflict persists (Day 9+ unresolved).** Insights.json (post-dedup) shows evening at 29% WR (n=14), afternoon at 27% WR (n=15) — not invalidated. But `tod_evening_edge_v1` and `tod_afternoon_edge_v1` in graduated_rules.json claim 65%/64% WR with active BOOST of +5pt. These cannot both be correct.

**Changes since Run 95 (10:06 UTC → 12:03 UTC, 2h gap):**
- No bot activity (offline). All state files unchanged.
- Morning window (06:00–12:00 UTC, 71–74% WR): now 6h03m into active phase, still missed (Day 64.58).
- EVENING/AFTERNOON TOD rule conflict: Day 9, no fix.
- 5/7 feedback state files still missing (persisted since Jun 5).
- Graduated rules lifecycle: all 25 rules still at 0 observations.
- SOL LONG veto and SOL SHORT penalize (not veto) mismatch: no fix.

---

## PHASE 1: SYSTEM AUDIT

**AUDIT COMPLETE: 7 systems verified, 7 gaps found**

### Feedback State Files

| File | Present | Last Modified | Status |
|------|---------|---------------|---------|
| `feedback/adaptive_risk_state.json` | ✅ | 2026-06-05 02:01 UTC (15.6d stale) | 20 recent outcomes: 35% WR; trending=51.9%, illiquid=28.1%, ranging=25.0% |
| `feedback/hold_time_rules_state.json` | ✅ | 2026-06-05 02:01 UTC (15.6d stale) | trend min_hold=3.0h (conf=0.80) |
| `feedback/signal_quality.json` | ❌ MISSING | — | Will init fresh on restart; session/hour/entry_type WR lost |
| `feedback/regime_feedback_state.json` | ❌ MISSING | — | Will init fresh on restart; all regime-confidence history lost |
| `feedback/tuner_state.json` | ❌ MISSING | — | Will init fresh on restart; parameter tuning history lost |
| `feedback/strategy_weights.json` | ❌ MISSING | — | Will init fresh on restart; strategy weight history lost |
| `feedback/confidence_floor_state.json` | ❌ MISSING | — | Will init fresh on restart; adaptive floor history lost |

**Persist gap (unresolved since Run 87, now Day 15.6 stale):** 5/7 feedback subsystems have no persisted state files. On restart, 5 subsystems re-initialize from zero — all pre-shutdown learning permanently lost.

### Feedback System Instantiation (`multi_strategy_main.py`)

All 7 feedback systems correctly instantiated (verified lines 412–424, 804–808, 909–913):
- `RegimeFeedbackManager` → line 412 ✅
- `AdaptiveConfidenceFloor` → line 415 ✅
- `HoldTimeRuleManager` → line 418 ✅
- `SignalQualityScorer` → line 421 ✅
- `ParameterTuner` → line 424 ✅
- `FeedbackLoop` → line 804 ✅
- `AutoOptimizer` → line 909 (lazy-init on first tick) ✅

### `record_outcome()` Coverage (lines 3100–3200)

All 7 systems verified with `record_outcome()` calls on trade close:
- `weight_mgr.record_outcome()` → line 3123 ✅
- `regime_feedback.record_trade()` → line 3144 ✅
- `confidence_floor.record_outcome()` → line 3144 ✅
- `hold_time_rules.record_trade()` → line 3155 ✅
- `signal_quality.record_outcome()` → line 3159 ✅
- `parameter_tuner.record_outcome()` → line 3166 ✅
- `feedback.record_outcome()` (FeedbackLoop) ✅

**Gap 1 (Structural):** Code is correct; ops gap is missing serialization or a missing flush-on-shutdown. 5/7 have no persistence file.

**Gap 2 (NEW — Graduated Rules Lifecycle):** All 25 graduated rules show 0 observations recorded (`times_correct=0`, `times_incorrect=0`). Root cause: `llm_regime` field is blank in all trade records. The `get_graduated_rules_engine().record_outcome()` call at line 3256 depends on `llm_regime` being populated — it never fires. CSV_REGIME_FIELD_FIX still unimplemented (Day 4).

### Graduated Rules Breakdown (25 rules total)

| Action | Count | Examples |
|--------|-------|----------|
| boost | 11 | BTC_TREND, BTC_SHORT_90+, ETH_TRENDING, TOD_morning/evening/afternoon, HIGH_VOL |
| penalize | 9 | ILLIQUID, BTC_SHORT_70-80, CONF_FLOOR_70, BTC_TREND_LONG, SOL_SHORT, HIGH_CONF_80-85, RANGING |
| veto | 5 | HYPE_BUY, SOL_BUY, NIGHT_SESSION, HYPE_SELL, BTC_BUY |

---

## PHASE 2: TRADE FORENSICS

**FORENSICS COMPLETE: 4 high-value sub-conditions found, 3 regression areas**

**Dataset:** backtest_10d_v3.csv (n=32 trades), supplemented with 100d_v2 (n=16 trades) for directional confirmation.

### Overall Performance

| Metric | Value |
|--------|-------|
| Trades | 32 |
| Win Rate | 16/32 = 50.0% |
| Net PnL | -$167.14 |
| Avg PnL/trade | -$5.22 |
| Gross wins | +$3,575.85 (TP1+TP2) |
| Gross losses | -$3,742.99 (SL+losing trails) |

### By Symbol

| Symbol | W/T | WR | Net PnL | Avg/Trade | Verdict |
|--------|-----|----|---------|-----------|----------|
| SOL | 9/14 | 64% | +$769.53 | +$54.97 | ✅ POSITIVE |
| BTC | 5/12 | 42% | -$720.94 | -$60.08 | ❌ DRAG |
| HYPE | 2/6 | 33% | -$215.73 | -$35.96 | ❌ DRAG |
| ETH | 0/0 | — | — | — | Not traded |

### By Side (CRITICAL)

| Side | W/T | WR | Avg PnL | Net PnL | Verdict |
|------|-----|----|---------|---------|----------|
| LONG | 14/21 | **67%** | +$92.24 | +$1,936.95 | ✅ STRONG |
| SHORT | 2/11 | **18%** | -$191.28 | -$2,104.09 | ❌ CRITICAL FAILURE |

**SHORT breakdown:** SOL SHORT 1/6 WR=17% (-$1,125); BTC SHORT 1/5 WR=20% (-$979). Both are deeply net negative. The entire system's negative PnL is driven by SHORT positions.

### By Confidence Bin

| Bin | W/T | WR | Avg PnL | Note |
|-----|-----|----|---------|------|
| <50% | 0/0 | — | — | Not traded |
| 50-60% | 0/0 | — | — | Not traded |
| 60-70% | 1/7 | **14%** | -$131.49 | ❌ Major drag — mostly SL exits |
| 70-80% | 7/12 | **58%** | -$50.74 | Marginally positive WR but negative PnL due to tail losses |
| 80-90% | 8/12 | **67%** | +$127.93 | ✅ Only profitable bin |
| 90%+ | 0/1 | **0%** | -$172.99 | Inadequate sample (n=1) |

### By Close Reason

| Reason | Count | WR | Avg PnL | Net PnL |
|--------|-------|----|---------|----------|
| SL | 12 | 0% | -$310.51 | -$3,726.15 |
| TP1 | 10 | 100% | +$348.18 | +$3,481.78 |
| TP2 | 2 | 100% | +$47.03 | +$94.07 |
| TRAILING_STOP | 8 | 50% | -$2.11 | -$16.84 |

**Key finding:** The SL/TP1 count imbalance (12 SL vs 10 TP1) drives negative PnL. Large SL outliers (SOL SHORT -$767, BTC SHORT -$710) skew the mean. Note: `duration_h=0.0` for all trades — hold-time analysis not possible (data quality bug).

### Top 5 Wins vs. Top 5 Losses

**Wins (all LONG TP1):**
1. SOL LONG TP1, conf=82.0, pnl=+$532
2. SOL LONG TP1, conf=87.5, pnl=+$502
3. SOL LONG TP1, conf=71.2, pnl=+$426
4. BTC LONG TP1, conf=73.9, pnl=+$421
5. BTC LONG TP1, conf=87.5, pnl=+$414

**Losses (all SL):**
1. SOL SHORT SL, conf=78.2, pnl=-$768
2. BTC SHORT SL, conf=79.8, pnl=-$711
3. HYPE LONG SL, conf=71.7, pnl=-$341
4. BTC SHORT SL, conf=68.3, pnl=-$247
5. BTC LONG SL, conf=66.2, pnl=-$246

### High-Value Sub-Conditions (4)

1. **SOL LONG: 100% WR (8/8), +$1,895 net** — Contradicts `sol_long_veto_v1`. Veto may be outdated.
2. **LONG 80-90% confidence: 67% WR, +$127 avg** — Only profitable confidence bin.
3. **TP1 exits: 100% WR, avg +$348** — TP1 placement is well-calibrated.
4. **LONG direction overall: 67% WR, +$1,937 net** — Directional LONG bias strongly favored in this period.

### Regression Areas (3)

1. **SHORT trades: 18% WR, -$2,104** — Not adequately protected.
2. **60-70% confidence: 14% WR** — Well below breakeven. Should be filtered.
3. **HYPE LONG (veto active): 2/6 WR=33%** — 2 trades still through in backtest (veto not applied to simulation).

---

## PHASE 3: HYPOTHESIS VALIDATION

**VALIDATION COMPLETE: 3 confirmed, 1 stale, 2 direction conflicts**

### Insight 1 — Morning edge 71% WR (n=20, conf=0.73)
- **Verdict:** ✅ CONFIRMED — consistent with `tod_morning_edge_v1` (74% WR, n=7). Action taken: boost +5pt active.

### Insight 2 — Night weakness 15% WR (n=13, conf=0.80)
- **Verdict:** ✅ CONFIRMED — consistent with `night_session_block_v1` (19% WR, n=27, veto active).

### Insight 3 — Strategy concentration: ensemble 94%, 45% WR (n=47, conf=0.80)
- **Verdict:** ✅ CONFIRMED — 100% of 10d_v3 trades are ensemble. WR improved to 50% but concentration unchanged.

### Insight 4 — Evening weakness 29% WR (n=14, conf=0.80)
- **Verdict:** ⚠️ DIRECTION CONFLICT — `tod_evening_edge_v1` claims 65% WR, BOOST active. Insight says 29%. Cannot both be right. Likely graduated rule based on pre-dedup inflated data (same n=27 as the invalidated insight).

### Insight 5 — sniper_premium 33% WR (n=6, conf=0.65)
- **Verdict:** ❌ STALE — conf=0.65 below 0.70 threshold, n=6 below minimum, strategy not present in backtest.

### Insight 6 — Afternoon weakness 27% WR (n=15, conf=0.80)
- **Verdict:** ⚠️ DIRECTION CONFLICT — `tod_afternoon_edge_v1` claims 64% WR, BOOST active. Same root cause as Insight 4.

---

## PHASE 4: FEEDBACK LOOP CLOSURE

**LOOP CLOSURE: 0 trades fully propagated (bot offline, no new trades)**

All 7 feedback links verified as wired in code (lines 3100–3200). Structural gap: 5/7 state files missing persistence — all learning lost on restart. Graduated rules lifecycle blind (0 observations, `llm_regime` field blank in CSVs). LLM memory: 1 note in short-term, 213 entries in deep_memory insight_journal.

---

## PHASE 5: RECOMMENDATIONS

**RECOMMENDATIONS: 3 changes proposed, ~$2,500+ PnL impact per 30-trade cycle**

### REC-1 (P0): Add Global SHORT Veto Until SHORT WR Recovers to ≥45%

**Problem:** SHORT: 2/11 WR=18%, net -$2,104. SOL SHORT 17% (-$1,125), BTC SHORT 20% (-$979). Current protection (penalize only) is absorbed by other boosts.

**Root cause:** Bull trend regime. SHORT entries fighting prevailing direction. Signal generator not regime-gating SHORT entries.

**Fix:** Add to graduated_rules.json:
- `sol_short_veto_v1`: veto SOL SELL (17% WR, n=6, conf=0.72)
- `btc_short_veto_below90_v1`: veto BTC SELL at conf<90% (BTC SHORT 90%+ is profitable at 67% WR per prior analysis; sub-90% is the loss bucket)

**Expected impact:** +$1,625 per 32-trade cycle (saves $2,104 losses, misses ~$479 of SHORT wins). ~$5,000/100 trades.

**A/B test:** Paper trade 30 signals with SHORT veto. Track (a) trades taken, (b) SHORT WR before vs after, (c) LONG WR as control.

**Rollback:** Set `status='paused'` in graduated_rules.json. Immediate.

**Confidence:** 72% — Strong directional evidence but n=6 for SOL SHORT. Replicate against 100d before production.

---

### REC-2 (P1): Re-evaluate SOL_LONG Veto — Move to Probe Mode

**Problem:** `sol_long_veto_v1` vetoes SOL BUY (24% WR, n=34 historical live). But 10d_v3 backtest shows SOL LONG at 100% WR (8/8), +$1,895 net — the single best setup in the dataset. Top 3 wins are all SOL LONG TP1.

**Root cause:** Veto learned from unfavorable historical period. Lifecycle tracker broken (CSV_REGIME_FIELD_FIX unimplemented) — rule cannot self-update. Backtest does not apply veto rules, so conflict cannot be resolved from backtest data alone.

**Fix:** Move to probe mode: `gate=0.10` (10% of SOL LONG signals allowed through). Collect 15–20 live observations. Decision: if WR ≥45% on 15 trades → escalate gate to 50%; if WR <35% → reinstate full veto.

**Expected impact:** ~+$340 per 32-trade cycle if SOL LONG recovers to 50%+ WR live. Minimal downside at 10% gate.

**Rollback:** Set gate to 0%. Zero downside from probe.

**Confidence:** 55% — Genuine data conflict. Probe mode is the correct institutional approach.

---

### REC-3 (P2): Suspend Evening/Afternoon TOD Boost Rules Pending Revalidation

**Problem:** `tod_evening_edge_v1` (65% WR, +5pt boost) and `tod_afternoon_edge_v1` (64% WR, +5pt boost) contradict active insights (evening=29% WR, afternoon=27% WR, both post-dedup). Graduated rules likely built from pre-dedup insight_journal (213 entries, no dedup).

**Fix:** Set `confidence=0.40` and `status='SUSPENDED_PENDING_REVALIDATION'` on both rules. Run fresh TOD WR analysis from backtest CSVs. Re-create rules from clean dataset.

**Expected impact:** +$100–$300/week from fewer incorrect boosts on losing windows.

**Rollback:** Reset confidence to 0.85. Immediate.

**Confidence:** 65% — Dedup explicitly invalidated the pre-dedup evening/afternoon claims. Graduated rules use same n=27 count as the invalidated insights.

---

## KNOWN OPEN ISSUES

| Issue | Days Open | Status | Impact |
|-------|-----------|--------|--------|
| 5/7 feedback state files missing | 15.6d | Unresolved | Learning lost on restart |
| Graduated rules lifecycle broken | 4d | Unresolved | 25 rules at 0 observations |
| TOD evening/afternoon rule conflict | 9d | Unresolved | Boosting possibly-losing windows |
| Bot OFFLINE | 64.58d | Unresolved | All live learning stalled |
| SOL_LONG veto vs backtest 100% WR | NEW | NEW FINDING | Blocking best-performing setup |
| SHORT not vetoed (18% WR) | NEW | NEW FINDING | -$2,104 per 32-trade cycle |
| `duration_h=0` in backtest CSVs | Persistent | Unresolved | Hold-time analysis impossible |

---

*Audit complete. Next run expected ~2026-06-20T14:00 UTC (Run 97).*
*Priority for human review: REC-1 (SHORT veto) and REC-2 (SOL_LONG probe mode).*
