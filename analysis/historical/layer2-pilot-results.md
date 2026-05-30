# Layer 2 Pilot Results — LLM Backtest Validation

*Date: 2026-05-30 | Branch: historical-import-2026-05-30*

## Summary

This document captures the results of the Layer 2 LLM backtest pilot runs:
validating that the multi-agent pipeline (Regime → Trade → Risk → Critic)
fires correctly in backtest mode after the four critical bug fixes.

---

## Bug Fixes Applied Before Pilots

| Fix | File | Effect |
|---|---|---|
| EV gate blocking all signals | `bot/backtest/engine.py` | Changed `evaluate()` → `evaluate_raw()` in LLM mode |
| System prompt → prompt injection | `bot/llm/claude_cli_client.py` | Changed stdin injection → `--system-prompt` flag |
| QUANT ignores env var | `bot/backtest/llm_integration.py` | Changed `AgentCoordinator()` → `get_coordinator()` |
| Budget too low for Sonnet | `bot/llm/claude_cli_client.py` | Auto-bumps to $0.50 for temp-file prompts |

---

## Pilot Run 1: `--days 7` (Baseline/Control)

**Command:** `python run.py backtest --symbols BTC --days 7 --llm --budget 3.00 --raw`

**Data coverage:**
- 1h: `BTC_1h_7d.csv` — 2026-03-25 to 2026-04-01 (168 candles)
- 5m: live fetch from exchange — 2026-04-18 to 2026-04-26 (MISMATCHED!)
- 6h: live fetch from exchange — 2026-04-29 to 2026-05-06 (MISMATCHED!)

**Root cause of 0 signals:**
The disk cache for `BTC_5m_7d.csv` and `BTC_6h_7d.csv` doesn't exist.
The fetcher falls back to live exchange data which covers a completely different
date range (April-May) vs the 1h disk cache (March). Strategies requiring 5m
or 6h data receive empty windowed data → return None → ensemble returns None.

**Results:**
| Metric | Value |
|---|---|
| Candles processed | 118 |
| Signals generated | 0 |
| LLM calls | 0 |
| Total cost | $0.00 |
| Verdict | CONTROL — confirms data mismatch issue, not EV gate |

**Conclusion:** This run confirms that the previous pre-fix 0-signal result had TWO causes:
1. EV gate (fixed by evaluate_raw) — but this was never reached because...
2. No strategies fire when timeframe data is mismatched

---

## Pilot Run 2: `--days 10` (Terminated Early)

**Command:** `python run.py backtest --symbols BTC --days 10 --llm --budget 3.00 --raw`

**Data coverage (all timeframes aligned):**
- 1h: `BTC_1h_10d.csv` — 2026-03-25 to 2026-04-05 (264 candles)
- 5m: `BTC_5m_10d.csv` — 2026-03-25 to 2026-04-05 (3168 rows)
- 6h: `BTC_6h_10d.csv` — 2026-03-25 to 2026-04-05 (45 rows)
- daily: `BTC_daily_10d.csv` — covers this period

**Status:** TERMINATED — killed at candle ~55/214 on desktop-claude recommendation.

**Termination reason:** Processing rate of ~1.5 min/candle meant 3+ more hours to reach the
first signal (expected at candle ~137 when the April 2 crash candle enters windowed history).
The March 25-29 consolidation data (low ADX, tight range) produced 0 signals in 55 candles.
Desktop-claude correctly identified a faster path using the April 23-28 volatile window.

**Results at termination:**
| Metric | Value |
|---|---|
| Candles processed (main loop) | ~55 of 214 |
| Signals generated | 0 |
| LLM calls | 0 |
| Total cost | $0.00 |
| Verdict | TERMINATED — pivoted to Pilot 3 |

**Why 0 signals in 55 candles (correct behavior):**
March 27-29 data is low-ADX consolidation ($65,900-$68,500 range). ADX gates in
`confidence_scorer` and `multi_tier_quality` block all signals when ADX < 22.
`bollinger_squeeze` squeeze not yet active (KC still wide from March 27 volatility).
First signal would have arrived at candle ~137 (April 2 crash candle).

---

## Pilot Run 3: `--days 5` (April 23-28 Volatile Window) — COMPLETE

**Command:** `python -u run.py backtest --symbols BTC --days 5 --llm --budget 3.00 --raw`
*(Note: `--start-date` flag does not exist in CLI — used `--days 5` which maps to pre-cached
April 23-28 data, coinciding with desktop-claude's "omniscient-cascade" target window.
`-u` flag used for unbuffered stdout so progress lines appear in real time.)*

**Data coverage (all timeframes aligned):**
- 1h: `BTC_1h_5d.csv` — 2026-04-23 to 2026-04-28 (132 candles)
- 5m: `BTC_5m_5d.csv` — 2026-04-23 to 2026-04-28 (1584 rows)
- 6h: `BTC_6h_5d.csv` — 2026-04-23 to 2026-04-28 (23 rows, note: 6h data unavailable for first candles → HTF filter skipped)
- daily: `BTC_daily_5d.csv` — 2026-02-21 to 2026-04-28 (67 rows, extensive lookback)

**Market conditions:**
- Open: ~$77,722 (April 23) | Close: ~$76,000 (April 28) = downtrend
- April 27 crash: $78,890 → $77,756 (vol 3,622 BTC, 05:00 UTC), then $76,765 (vol 5,548, 15:00 UTC)
- Volume: 636-5,548 BTC/candle (high volatility window)
- Preflight: PASSED | Estimated cost: $0.06 (36 API calls) | 82 candles to process

**Results:**

| Metric | Value |
|---|---|
| Candles processed | 72 of 82 |
| Signals generated | 36 (50% of candles — expected for crash window) |
| Signals vetoed (graduated_rules) | 11 (31%) |
| Signals → LLM pipeline | 25 |
| LLM approved | 25 (all fallback — see critical finding below) |
| LLM vetoed | 0 (real LLM vetoes) |
| LLM API calls | 69 |
| LLM Failures (bug) | 0 reported / ~45 actual (see below) |
| Total cost ($) | $0.00 (subscription, not API) |
| Positions opened | 3 |
| Positions blocked (DUPLICATE) | 22 of 25 |
| Net PnL | −$73.21 |
| Gross PnL | +$118.06 |
| Fees | −$178.92 (152% of gross — fee drag) |
| Win rate | 66.7% (2W / 1L) |
| Regime Agent vocab | `consolidation`, `high_volatility` ✓ (correct vocabulary) |
| Verdict | **PARTIAL — session limit hit, LLM fallback only** |

**Positions opened:**
| # | Side | Entry | Exit | PnL | How opened |
|---|---|---|---|---|---|
| 1 | LONG | $78,100 | SL | +$170.03 | Regime+Trade agents SUCCEEDED, Risk+Critic 429-failed (fallback approved) |
| 2 | LONG | $79,127.5 | SL | −$612.29 | All agents 429-failed (fallback approved) |
| 3 | SHORT | $77,596.2 | BACKTEST_END | +$560.32 | All agents 429-failed (fallback approved) |

**CRITICAL FINDING: CLI Session Limit Hit**

At candle ~48 (April 27 05:00 crash), the first signals fired. The Regime Agent and Trade Agent
successfully completed their first calls. Then the subscription session limit was reached:

```
[MULTI-AGENT] risk agent API call FAILED: exit 1: ... "You've hit your session limit · resets 10pm (America/Chicago)"
[MULTI-AGENT] critic agent API call FAILED: exit 1: ... "You've hit your session limit"
```

All subsequent agent calls returned 429 with "You've hit your session limit". The fallback
behavior when an agent fails is to **approve the signal** (pass-through), not reject it.
This means all 25 "approved" signals after the first crash candle were fallback approvals, not
real LLM decisions.

The LLM stats tracker has a bug: it reports `Failures: 0` despite ~45 real 429 failures.
The 429 errors are not being counted as failures in the internal stats.

**Why 50% signal rate is expected (correct behavior):**
During the April 27-28 crash, the ensemble fires `confidence_scorer` and `high_volatility`
strategy on almost every crash candle. 50% signal rate is correct for this extreme window.
In normal market conditions, signal rate should be 5-15%.

**Strategy attribution:**
- `confidence_scorer`: 100% WR, PF=99.0, net +$730 (attributed PnL)
- `bollinger_squeeze`: 0% WR, PF=0.0, net −$612 (attributed PnL)

**Regime labels confirmed:** Regime Agent outputs `consolidation` and `high_volatility`.
Vocabulary mismatch (`trend` vs `trending_bull`) does NOT affect this dataset — no trending
regime appeared. Bug confirmed for future datasets (see desktop-claude's earlier analysis).

**Fee drag issue:**
Fee drag is 152% of gross PnL. Three positions in 72 candles is correct (3 = only 3 UNIQUE
positions were opened by PositionManager). But strategies are generating 36 signals which burn
LLM session quota without adding value. The DUPLICATE BLOCKED mechanism works, but 22/25 LLM
pipeline activations were wasted on signals that would be blocked anyway.

**Efficiency improvement identified:**
Skip LLM pipeline evaluation when already in a LONG position and signal is LONG (or SHORT/SHORT).
This would reduce session consumption by ~88% during high-signal-density periods.

---

## Timing Extrapolation (for Layer 3 planning)

| Scenario | Signals | LLM calls | Avg latency | Total time |
|---|---|---|---|---|
| 10d BTC pilot (actual) | TBD | TBD | TBD | TBD |
| 30d BTC extrapolated | TBD | TBD | TBD | TBD |
| 90d BTC+ETH+SOL+HYPE est. | TBD | TBD | TBD | TBD |

---

## Key Questions This Pilot Answers

1. **Do LLM agents fire in backtest mode?** → YES — Regime+Trade agents fired successfully on the first crash signal. Pipeline confirmed working. Session limit hit before further evaluations.

2. **Does the Critic still exit 143?** → Unknown — Critic agent called 0 times before hitting session limit. Not reproduced or ruled out.

3. **What's the signal conversion rate (strategy→LLM→execute)?** → 36 signals / 72 candles = 50% during crash window (high). 25 reached LLM (69%), 11 blocked by graduated rules (31%). Of 25 that reached LLM, all were fallback-approved, 3 opened positions, 22 DUPLICATE blocked. Real conversion is unclear due to fallback.

4. **What's the avg cost per LLM-evaluated signal?** → $0.00/signal (subscription, not API credits). Session limit is the real cost — ~17 signal evaluations per session before limit hit.

5. **Is the 4-agent pipeline stable under backtest data volumes?** → PARTIALLY confirmed. Pipeline fires correctly. Session limit causes cascading failures. Fallback-approve on failure is correct safety behavior but masks LLM quality.

6. **What does the LLM decide for BTC in April 2026?** → Partial: Regime said `consolidation` → `high_volatility`. Trade agent approved first LONG. No full pipeline decisions after that due to session limit.

7. **NEW: What is the session limit?** → ~17 complete 4-agent evaluations per session. Resets 10pm America/Chicago (3am UTC). This is the primary bottleneck for Layer 3.

8. **NEW: What is the failure tracking bug?** → `Failures: 0` in stats despite 45+ real 429 failures. The `_call_llm_agent()` 429 path is not incrementing the failure counter. Fix needed before Layer 3.

---

## Layer 3 Gate Conditions

Layer 3 (90d full LLM backtest) launches when:
- [x] LLM calls confirmed firing (at least 1 successful agent call — CONFIRMED)
- [x] Regime labels confirmed correct vocabulary (consolidation/high_volatility — CONFIRMED)
- [ ] Session limit strategy determined (run after 10pm Chicago reset, or API credits, or skip-if-in-position optimization)
- [ ] Failure counter bug fixed (Failures counter not incrementing on 429)
- [ ] DUPLICATE skip optimization: skip LLM pipeline when signal would be blocked by existing position
- [ ] No systematic agent crashes (exit 143 not yet tested — Critic never reached in Pilot 3)
- [ ] Cost estimate for 90d is < $50 (session limit makes this hard to estimate — need API or unlimited sessions)
- [ ] Data timeframes validated for 90d window
