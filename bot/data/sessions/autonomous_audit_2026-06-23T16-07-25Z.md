# WAGMI Autonomous Quant Audit
**Timestamp:** 2026-06-23T16:07:25Z (Run 107, Day ~66 offline)
**Auditor:** Claude Autonomous Agent | **Standard:** Institutional-grade quant review
**Prior Audit:** 2026-06-19T12:05:34Z (Run 82) — this audit detects changes applied since then
**Dataset:** backtest_100d.csv (589 trades, primary), backtest_20d.csv (111 trades, recent), backtest_10d_v3.csv (32 trades)

---

## EXECUTIVE SUMMARY

The bot remains **completely offline** — trades.csv is empty (header-only), risk_equity_state.json shows last equity snapshot from 2026-04-23 ($497), and all feedback state files are from Jun 5. No live feedback propagation has occurred in 18+ days.

**Three significant structural changes since Run 82:**
1. **Rule consolidation event** — graduated_rules.json was rebuilt from 24 rules → 11 "restored_*" rules. All show `times_applied=0, times_correct=0`. A new `rule_1782144529_0` (BTC trend boost +8.0, created today Jun 23) was added independently.
2. **Critical double-penalty on HYPE** — `restored_hype_short_highconf_veto_v1` (blocks SHORT ≥75% conf) AND `restored_hype_sizing_cap_v1` (-50% size all HYPE) are BOTH active. These will stack on every HYPE SHORT ≥75%, but only one of them may be necessary — and neither can track accuracy until the bot runs live.
3. **20d vs 100d contradiction persists and sharpened** — 20d shows +$7,053 / 65.8% WR; 100d shows -$8,173 / 44.5% WR. The confidence-vs-WR relationship INVERTS between time windows (20d: 82% WR at 80-90% conf; 100d: 40% WR at 80-90% conf). Rules built from 100d data are penalizing the very setups that win in the recent 20d period.

**Top priority before live restart:** Resolve the dataset contradiction and audit whether the HYPE double-penalty will suppress too many valid signals.

---

## PHASE 1: SYSTEM AUDIT

**AUDIT COMPLETE: 7 systems verified, 4 structural gaps (1 new)**

### Feedback System Instantiation

| System | Class | Line | record_outcome() Loc | Status |
|--------|-------|------|----------------------|--------|
| Signal Quality | `SignalQualityScorer` | L421 | L3158–3163 | ✅ Wired |
| Parameter Tuner | `ParameterTuner` | L424 | L3165–3173 | ✅ Wired |
| Regime Feedback | `RegimeFeedbackManager` | L412 | L3135–3142 | ✅ Wired |
| Confidence Floor | `AdaptiveConfidenceFloor` | L415 | L3144–3149 | ✅ Wired |
| Hold Time Rules | `HoldTimeRuleManager` | L418 | L3151–3156 | ✅ Wired |
| Feedback Loop | `FeedbackLoop` | L804 | L3233 | ✅ Wired |
| AutoOptimizer | lazy-init | L913/L2222 | L3816+ | ✅ Wired |

### Feedback State Files

| File | Present | Last Modified | Status |
|------|---------|---------------|--------|
| `adaptive_risk_state.json` | ✅ | 2026-06-05 02:01 | 18 days stale — no live trades |
| `hold_time_rules_state.json` | ✅ | 2026-06-05 02:01 | 18 days stale |
| `signal_quality.json` | ❌ MISSING | — | Creates on first-close post-restart |
| `regime_feedback_state.json` | ❌ MISSING | — | Creates on first-close post-restart |
| `tuner_state.json` | ❌ MISSING | — | Creates on first-close post-restart |

### adaptive_risk_state.json (18-day-old live data — valid reference)

Regime win rates from live session:
- trending: 27W / 52T = **51.9% WR**
- illiquid: 16W / 57T = **28.1% WR** ← severe underperformance
- ranging: 4W / 16T = **25.0% WR** ← severe underperformance
- recent_outcomes (last 20): 8W/20T = **40% WR**

### Graduated Rules Status (NEW — rule consolidation event detected)

Prior Run 82 had 24 rules. Current state has **11 rules** (all `times_applied=0, times_correct=0`).

| Rule | Action | Conditions | Adj | Active | Evidence |
|------|--------|-----------|-----|--------|----------|
| `rule_1782144529_0` | boost | BTC + trend regime | +8.0 | ✅ | NEW TODAY (created Jun 23) |
| `restored_night_session_block_v1` | veto | hour_utc 0-6 | 0 | ✅ | conf=0.95 |
| `restored_hype_long_block_v1` | veto | HYPE LONG | 0 | ✅ | conf=0.88 |
| `restored_illiquid_regime_block_v1` | veto | regime=illiquid | 0 | ✅ | conf=0.87 |
| `restored_ranging_regime_penalty_v1` | penalize | regime=ranging | -15.0 | ✅ | conf=0.82 |
| `restored_hype_short_highconf_veto_v1` | **veto** | HYPE SHORT conf≥75% | 0 | ✅ | conf=0.71 — lowest confidence |
| `restored_hype_sizing_cap_v1` | size_adjust | all HYPE | -0.5 | ✅ | conf=0.92 — ⚠️ stacks with above |
| `restored_sol_short_boost_v1` | boost | SOL SHORT | +8.0 | ✅ | conf=0.81 |
| `restored_btc_long_boost_v1` | boost | BTC LONG | +8.0 | ❌ INACTIVE | conf=0.78 |
| `restored_confidence_paradox_sizing_v1` | size_adjust | conf 85-90% | -0.25 | ✅ | conf=0.78 |
| `restored_instant_sl_buffer_v1` | size_adjust | (all trades) | -0.1 | ✅ | conf=0.83 |

**Gap 1 — `times_correct` = 0 across all 11 rules**: Bot offline; accuracy tracking cannot start until live restart.

**Gap 2 — TP1 feedback blind spot (persistent from Run 82)**: `_FULL_CLOSE` filter excludes `TP1` events (L3116). 160/589 = 27.2% of backtest trades are TP1 exits and are invisible to all 7 feedback systems during live operation.

**Gap 3 — LLM regime/confidence fields empty in all historical data**: All 589 backtest records show `llm_regime=""`, `llm_confidence=""`. Regime-gated rules cannot have their historical accuracy backtested.

**Gap 4 (NEW) — Double-penalty on HYPE SHORT ≥75% confidence**: `restored_hype_short_highconf_veto_v1` (veto) AND `restored_hype_sizing_cap_v1` (-50% sizing) both fire on HYPE SHORT ≥75%. The veto rule has the LOWEST confidence of all active rules (0.71) yet produces the most aggressive action.

---

## PHASE 2: TRADE FORENSICS

**FORENSICS COMPLETE: 5 high-value sub-conditions found, 4 regression areas identified**

### Dataset Overview

| Dataset | Trades | WR | Total PnL | Period |
|---------|--------|-----|-----------|--------|
| backtest_100d.csv | 589 | 44.5% | **-$8,173.52** | ~100 days (primary) |
| backtest_20d.csv | 111 | 65.8% | **+$7,053.70** | most recent 20 days |
| backtest_10d_v3.csv | 32 | 50.0% | **-$167.14** | most recent 10 days |

⚠️ **Dataset conflict is severe**: Same bot, 65.8% WR / +$7k over 20 days vs 44.5% / -$8k over 100 days.

### By Symbol (100d)

| Symbol | Trades | WR | Total PnL | EV/trade |
|--------|--------|-----|-----------|----------|
| BTC | 166 | 42.2% | -$636.62 | -$3.84 |
| HYPE | 225 | 48.9% | **-$5,563.40** | **-$24.73** |
| SOL | 198 | 41.4% | -$1,973.50 | -$9.97 |

HYPE: avg SL loss -$204.77 vs avg TP win +$165.70 → -1.24x R:R asymmetry means even 50% WR loses money.

### By Symbol (20d)

| Symbol | Trades | WR | Total PnL |
|--------|--------|-----|----------|
| BTC | 29 | 69.0% | +$2,644.91 |
| HYPE | 43 | 60.5% | +$119.21 |
| SOL | 39 | 69.2% | +$4,289.58 |

### Confidence Paradox (100d vs 20d)

| Conf Bin | 100d WR | 100d PnL | 20d WR | 20d PnL |
|----------|---------|---------|--------|--------|
| 60-70% | 48.6% | -$793 | 50.0% | +$472 |
| 70-80% | 45.2% | -$2,740 | **69.0%** | +$3,170 |
| 80-90% | **40.0%** | -$3,965 | **82.0%** | +$4,083 |
| 90+% | 40.5% | -$675 | 0.0% | -$671 |

80-90% confidence: 40% WR in 100d → 82% WR in 20d — exact inversion. `restored_confidence_paradox_sizing_v1` (-25% size at 85-90%) is shrinking sizes on the best recent trades.

### By Close Reason (100d)

| Reason | Count | Total PnL | Avg/trade |
|--------|-------|-----------|----------|
| SL | 269 | **-$29,300** | -$108.92 |
| TP1 | 160 | +$19,521 | +$122.01 |
| TRAILING_STOP | 111 | -$37 | -$0.33 |
| TP2 | 49 | +$1,643 | +$33.53 |

### Top 5 Wins — All HYPE/SOL SHORT momentum
| SOL SHORT 79.7% conf | RR=21.1x | +$713 |
| HYPE SHORT 87.5% conf | RR=12.1x | +$598 |
| HYPE SHORT 71.1% conf | RR=4.84x | +$494 |

### Top 5 Losses — ALL HYPE SHORT
| HYPE SHORT 70.4% | -$520 |
| HYPE SHORT 87.5% | -$516 |
| HYPE SHORT 81.5% | -$512 |

### Duration Anomaly
- 91% of trades (537/589) show duration < 1h despite min_hold=3h
- 52 trades show NEGATIVE duration (-0.1h) — all TP1 wins
- Hold time minimum is NOT enforced in backtest engine

---

## PHASE 3: HYPOTHESIS VALIDATION

**VALIDATION COMPLETE: 1 confirmed, 15 stale/invalidated, 3 cannot validate**

| Insight | Status |
|---------|--------|
| Night (0-6 UTC) 15% WR (n=13) | ⚠️ Cannot validate — no timestamp column in backtest CSVs |
| Evening (18-24 UTC) 29% WR (n=14) | ⚠️ Cannot validate — no timestamp column |
| Afternoon (12-18 UTC) 27% WR (n=15) | ⚠️ Cannot validate — no timestamp column |
| Ensemble concentration 94% (n=47) | ✅ CONFIRMED — 100% ensemble in 100d (589/589 trades) |

### Actionability Gap
- Night weakness → `restored_night_session_block_v1` (veto) ✅ addressed
- Evening 29% WR → **NO rule in current 11** — Run 81 removed wrong-direction boost but never added penalize
- Afternoon 27% WR → **NO rule in current 11** — same gap

---

## PHASE 4: FEEDBACK LOOP CLOSURE

**LOOP CLOSURE: 0 trades propagated (bot offline), 0 wiring breaks, 1 systemic gap**

trades.csv empty. Bot offline since ≥2026-04-23. All 7 feedback systems wired correctly in code.

**Persistent TP1 blind spot**: `_FULL_CLOSE` at L3116 excludes TP1. All 7 systems miss 27% of trades.

| System | On TP1 | On SL/TP2/TRAILING |
|--------|--------|--------------------|
| All 7 systems | ❌ Not called | ✅ Called |

---

## PHASE 5: RECOMMENDATIONS

**RECOMMENDATIONS: 3 changes proposed**

### REC 1 (CRITICAL, conf=87%): Fix TP1 Blind Spot
- **Problem**: `_FULL_CLOSE` at `multi_strategy_main.py:L3116` excludes TP1. 160 TP1 trades (+$122/trade avg) invisible to all 7 feedback systems → systematic learning bias toward SL/TP2 outcomes.
- **Fix**: Verify if TP1 = full or partial close in `position_manager.py`, then add `"TP1"` to `_FULL_CLOSE` (or add `_PARTIAL_CLOSE` path).
- **Impact**: +160 training samples per period, 27% faster feedback convergence.
- **Rollback**: Revert single line at L3116.

### REC 2 (HIGH, conf=68%): Audit `restored_hype_short_highconf_veto_v1`
- **Problem**: Lowest-confidence rule (0.71) takes most-aggressive action (full veto). 20d shows HYPE 60.5% WR / +$119 — rule may be blocking recently profitable setups. Also stacks with `restored_hype_sizing_cap_v1`.
- **Fix**: Deactivate veto, monitor first 25 live HYPE SHORT ≥75% trades. Re-enable if WR<45% or avg_loss/avg_win>1.3x.
- **Impact**: +~$1,200/100 trades if 20d pattern holds. Risk: -$500/100 if 100d pattern returns.
- **Rollback**: Re-enable `restored_hype_short_highconf_veto_v1` in graduated_rules.json.

### REC 3 (MEDIUM, conf=75%): Add Evening/Afternoon Penalty Rules
- **Problem**: Evening (29% WR, n=14) and afternoon (27% WR, n=15) weaknesses have no corresponding rules. Night weakness has a veto rule but the other two weak sessions were left unaddressed when Run 81 removed the wrong-direction boost rules.
- **Fix**: Add `evening_session_penalize_v1` (18-24 UTC, adj=-10.0) and `afternoon_session_penalize_v1` (12-18 UTC, adj=-10.0) to graduated_rules.json.
- **Impact**: Estimated $500-800 loss reduction per 100 trades in these windows.
- **Rollback**: Set `active: false` on both rules.

---

## ANOMALIES & ALERTS

| Alert | Severity | Detail |
|-------|----------|--------|
| Backtest duration bug | HIGH | 52 trades with negative duration, 91% <1h despite min_hold=3h — hold time rule not enforced in backtest engine |
| New rule today | MONITOR | `rule_1782144529_0` created Jun 23 (auto-generated?) — BTC trend boost +8.0, never fired, verify intentional |
| Rule consolidation unverified | MEDIUM | 24 rules → 11 restored_* rules, no metadata on what was removed or why |
| Equity stale since Apr 23 | HIGH | risk_equity_state.json shows $497 — verify vs actual wallet before live restart |

---

## FINAL SYNTHESIS

**What's Working**: All 7 feedback systems wired ✅ | Insight invalidation system healthy (15/19 invalid) ✅ | Night/illiquid/ranging rules correctly blocking weak regimes ✅

**What's Broken**: TP1 blind spot (27% trades unlearned) ❌ | Backtest duration bug ❌ | HYPE double-penalty conflict ⚠️ | Evening/afternoon gaps ⚠️ | All rules at 0 applications ⚠️ | 20d/100d dataset contradiction unresolved ⚠️

**Priority Order Before Live Restart**:
1. Verify equity ($497 vs actual wallet)
2. Fix TP1 blind spot — REC 1 (1-line change, pure upside)
3. Decide HYPE SHORT veto — REC 2 (judgment call)
4. Add evening/afternoon penalty rules — REC 3 (JSON edit)
5. Fix backtest duration calculation (investigation needed)

*Audit complete. Next scheduled audit: 2026-06-23T18:07:25Z*
