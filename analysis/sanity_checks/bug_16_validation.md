# Bug #16 Contamination Fix — Over-Blocking Validation

**Date:** 2026-06-02  
**Author:** laptop-claude  
**Purpose:** Sanity check #2 from LAPTOP_AUTONOMOUS_MASTER_BRIEF.md — confirm Bug #16 fixes did not over-block legitimate live data

---

## What Bug #16 Fixed

Look-ahead bias: the backtest pipeline was accessing data created AFTER the backtest window (live trade outcomes, current calibration curves, post-window deep memory patterns). This inflated backtest WR by injecting future knowledge into past decisions.

The fix added 17 `if not snapshot.get("_is_backtest"):` guards in `bot/llm/agents/coordinator.py`.

---

## The Concern

Did any of the 12-17 blocks accidentally gate OUT something that SHOULD be available in backtest?

Specifically: graduated rules created post-April 23 (15 of 26 total rules) — are they accessible in backtest, or were they frozen/blocked?

---

## Validation Finding: NOT OVER-BLOCKED

### Graduated Rules: FREELY ACCESSIBLE IN BACKTEST ✅

`GraduatedRulesEngine.evaluate_signal()` has **no `_is_backtest` guard**. It loads from `graduated_rules.json` at runtime and applies all active rules to every signal — in both live and backtest mode.

The block that exists is:
```python
# In coordinator.py:
if sm.get("graduated_rules_advisory") and not snapshot.get("_is_backtest"):
    trade_data["graduated_rules_advisory"] = sm["graduated_rules_advisory"]
```
This blocks the **advisory label** ("this rule fired, here's why") from being injected into agent context as text. It does NOT block the rule itself from executing.

**Net effect:** In backtest, rules fire and affect decisions the same as in live mode. The agent just doesn't get the explanatory label in its prompt.

---

## What IS Correctly Blocked

| Blocked Item | Why Correct |
|---|---|
| Live performance statistics (WR, edge decay) | These reflect future live trades, not April data |
| Self-teaching knowledge base | Learned from post-window live trades |
| Neuroplasticity setup edge strengths | Calibrated on live outcomes after April |
| Quant priors / calibration curves | Live-trading history, not April |
| Deep memory patterns | Built from post-April live sessions |
| Similar pattern library (trade DNA) | Same — post-window data |
| Agent calibration ledger | Live accuracy tracking |
| Veto statistics | From live session, not backtest period |

All blocked items are **outcome-contaminated** (they learned from the future). Blocking them is correct.

---

## Graduated Rules Post-April 23 (15 rules)

Rules like `hype_short_veto_v1` (WR=2.3%), `hype_buy_us_session_v1` (WR=87%), `btc_buy_bb_golden_v1`, `tod_morning_edge_v1`, etc. — all 15 execute normally in backtest mode because their conditions (`symbol`, `side`, `regime`, `hour_utc`, `num_agree`) are timeless. They do NOT depend on calibration curves or deep memory lookups.

---

## Risk Assessment

**LOW — acceptable design.**

The one theoretical edge case: if a graduated rule's `matches()` method internally called deep memory lookups, that lookup would return empty in backtest (memory blocked). Currently no rule does this — all conditions are simple attribute comparisons. This is safe.

---

## Verdict: ✅ Fix is surgical. No over-blocking.

Post-April 23 graduated rules reach LLM agents in both live AND backtest mode. The 17 blocks are precisely targeted at outcome-contaminated data. The backtest is clean.
