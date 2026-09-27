# WAGMI Live-Bot — Risk-Mechanic Audit

**Date:** 2026-08-01. A read-only audit of the **live paper bot's actual risk
mechanics**, run against its real 274-trade history (`data/trade_ledger.csv` +
`data/trade_events.jsonl`). Distinct from the co-pilot signal scorecard — this is
about what actually protects the account when it trades. Every finding is
reproducible from the `*_test.py` scripts in `tools/copilot/`. **Nothing here was
shipped — every fix is a live-bot change and is owner-gated.**

## The headline

**What actually protects the account is real and mostly sound: per-symbol Kelly
leverage (validated) and the stop-loss.** But **three separate "adaptive risk
management" subsystems that look active are dead, decorative, or inert** — the bot
believes it has smart drawdown-aware protection it does not actually run. This
matches the project's known "AutoOptimizer never ran / graduated rules dead" theme.

## What's SOUND (keep)

- **Position sizing (leverage) — wash-to-mild-help, not variance-for-nothing.**
  Counterfactual vs flat sizing: actual had a *better* terminal (−$99 vs −$610) and
  drawdown-adjusted return, survives an outlier-drop check (88% bootstrap, not 95%).
  Keep it. *(`kelly_counterfactual_test.py`)*
- **Liquidation geometry — safe at the leverage actually used.** On all 274 trades
  the stop-loss sat well short of the modeled HL liquidation price (buffer never
  above 45% of the liq runway); 0 non-protective trades, 0 liquidations. And it
  **independently validates the co-pilot's horizon-leverage math** — actual leverage
  exceeded the co-pilot's safe ceiling in only 2/274 trades. *(`liq_distance_calibration_test.py`)*

## What's a FACADE (dead / inert — decide: wire it or delete it)

- **`self_tuning.py`'s 3/5/8% drawdown-tiered risk profiles are decorative** —
  `evaluate_and_adjust()` only sets a status string for Telegram/LLM prompts; it
  never writes back to the real circuit breaker or position limits.
- **The circuit breaker is functionally inert.** On 274 trades it "tripped" 3× but
  skipped **0 trades, net $0** — a 10-loss streak takes hours of wall-clock to build,
  so the next trade always arrives *after* the 60-min cooldown has already expired.
  One free pass was a real −$264 loss. *(`circuit_breaker_test.py`)*
- **`get_drawdown_dial()` (graduated drawdown size-down tiers) is dead code** — zero
  production callers. No live mechanism reads drawdown state at sizing time at all.
  *(`dd_tilt_test.py`)*
- **No actionable "tilt when down" effect exists anyway** — tested and null (the one
  significant-looking result was a single mid-June episode; the tautology guard
  confirmed the naive signal was definitional). So a pause-when-down rule isn't
  justified by this data even if you wired the dial.
- **The strategy-reactivation instrument is broken and already fired a false
  positive.** `feedback/shadow_ledger.py` logs what disabled strategies would have
  predicted and recommends re-enabling one at n≥50 / WR≥55%. But `resolve_shadows()`
  is only called from live trade-close handlers — so a shadow prediction gets scored
  against *whatever price the live bot happened to close an unrelated position at*
  (72 seconds to 8 hours later, median ~4h), not a fixed horizon tied to the signal.
  **74% of shadow rows (8,520/11,528) never resolve**, and the resolved ones pool
  72-second noise with 8-hour moves. Smoking gun: it logged a WARNING-level
  `"REACTIVATION SIGNAL: regime_trend shows significant edge (WR=57.5%, n≈500)"` on
  2026-06-25; one week later that factor's WR had crashed to **29%** on n≈1210. A
  real n>500 edge can't flip 29 points in a week — the instrument measures noise.
  `feedback/shadow_ledger.py`, call sites `multi_strategy_main.py:4286` /
  `core/close_pipeline/close_subscribers_misc.py:217`.
- **`llm/agents/decision_ledger.py` is fully dead code** (zero callers) — one more
  instance of the same "self-improvement scaffolding built but never wired" pattern.

## Owner-gated recommendations, ranked

1. **Outage protection (highest — matters more as leverage rises).** The stop-loss
   is bot-process-dependent, not exchange-side. One SOL short slipped **11.48%
   through its stop during a confirmed 153-hour bot outage** (Jun 10–16); it only
   survived because leverage was 1.5×. Consider an **exchange-side resting stop
   order** and a **startup reconciliation** that re-validates SL-vs-liq geometry for
   any position found open after a gap. `execution/risk.py` / `leverage.py`.
2. **Confidence-ladder sizing flaw.** The un-logged confidence risk-multiplier sizes
   *up* on high-confidence trades, but confidence is **anti-predictive** in this
   ledger (high-conf 32% WR / $934 avg notional vs low-conf 58% WR / $295). It sizes
   up exactly where outcomes are worse. A notional cap at ~1.5× median (~$356) would
   have cut max drawdown ~75% for a ~$92 terminal cost. `execution/leverage.py`.
3. **Resolve the risk-management facade.** Either wire `self_tuning.py` / the
   drawdown dial into the real breaker, fix the circuit-breaker cooldown-vs-streak
   mismatch so it actually bites, or **delete the dead code** so the system's
   self-picture is honest. Leaving inert "safety" in place is its own risk — it reads
   as protection that isn't there.
4. **Distrust the strategy-reactivation instrument — it has TWO compounding bugs.**
   (a) `resolve_shadows()` scores against live-trade-close timing, not a fixed horizon
   (74% never resolve; a correct fixed-horizon resolution lifts that to ~90%). (b)
   `record_shadow_signal` fires **every bot-loop tick** a disabled strategy stays
   active, so ~76-88 near-duplicate signals get counted as independent trades —
   pseudoreplication that inflates a 28-symbol-day sample into a fake "n≈500". A
   corrected re-resolution (`shadow_resolver_test.py`) confirms **all four disabled
   strategies are dead** at honest cluster-level N (regime_trend WR 40-51%; the two
   that looked strong are one-era relics, none significant). Fixing only bug (a) —
   the obvious one — would STILL produce false reactivation alerts because of (b). Any
   real fix needs entry-time-safe fixed-horizon resolution AND counting independent
   symbol-days, not raw signal hits. Until then, treat `get_reactivation_candidates()`
   and its WARNING logs as noise. `feedback/shadow_ledger.py`, `validation/power_analysis.py`.

## Measurement integrity of the LLM's decision inputs — AUDITED CLEAN

Because the shadow-ledger's bugs (pseudoreplication + wrong-horizon resolution) are a
*pattern*, every stat that feeds the LLM's decision prompts was traced end-to-end
(`measurement_integrity_audit.py`, `measurement_audit_followup.py`). Result — **the
LLM is not deciding on corrupted self-knowledge:**

- **Clean by construction:** per-agent calibration ledger, thesis tracker (verified:
  1,142 rows → 1,086 unique theses → 56 graded, the expected shape), live-edge EV
  gate, and the TradeDNA/quant priors (248 unique trade IDs, own-horizon, WR 38.8% vs
  ledger 36.1% — matches).
- **Had the bug, already patched (verified live-active):** the counterfactual learner
  ("missed opportunities", was 13× inflated) and graduated rules (can veto trades) —
  both fixed by default-on flags (`DEDUPE_CF_AGGREGATION`, `DEDUPE_VETO_RECORDING`),
  which I confirmed are not disabled anywhere in `.env` or code.
- **Inert, not corrupt:** `get_historical_patterns()` injects an *empty* object —
  `decisions.jsonl` never gets outcomes stamped (0/4,606 rows). Wire-or-remove ticket,
  low priority.
- The **"Quant Brain suspect"** question from project memory is resolved: **not
  confirmed corrupt** — it routes through close-event-gated paths, not per-tick logs.

Owner-gated hardening (optional): hard-delete the undeduped code paths so the two
load-bearing dedup flags can't be reverted; wire or remove the dead `decisions.jsonl`
outcome-stamper.

## Caveats

At the account's **current collapsed size** (~$278 median notional post-2026-07-26),
the *dollar* impact of all of these is small. These findings are about
**mechanic validity** — they matter the moment size or leverage scales back up.
All results are in-sample on 274 trades; the grid-swept "optimal" thresholds are
peaky/overfit and were explicitly *not* recommended as specific numbers — the
recommendations above are structural, not tuned constants.
