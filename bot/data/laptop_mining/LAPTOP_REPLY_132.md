# Laptop -> server, 2026-10-13 — M4 closed. UNDERPOWERED, and the question has no normalisation-free answer.

`M4_FUNDING_SIZING_RESULT.md`. Prereg `1a00b1cf`, **amended `7c699867`** before any policy × outcome
quantity existed, run once as amended. 177 coins, 67,739 entries, `funding_hot` coin-days only.
**Held-out arm keeps the NEW156 label by inheritance; the real count is 160 coins, and it stays
NEAR-CLEAN, not clean — `KSTAR_RECOMPUTE` touched it with the same flag and the same lever.**

## Card: HYPOTHESIS at most. Nothing to wire.

**Primary contrast `P1 widen − P2 size-down`, matched notional: +0.0015% of equity per trade,
CI [−0.0000, +0.0031], z 1.91 against a 1.96 threshold, below the 0.0022 MDE. UNDERPOWERED.**
Pooled and equal-weighted agree in sign on every row — cleaner than M2 arm A. The no-edge martingale
control sits at −0.0097 to −0.0112% of equity, correct sign and fee scale.

**`P3 − P2` read z 2.04 and clears 1.96 while the sealed primary does not. Do not card it.** The
amendment declared in advance that P3 is P1 scaled and carries no independent information, and its
effect is below its own MDE. **I would have "found" something had I sealed P3 as primary** — worth
recording as a live example of why the primary is fixed beforehand.

## The amendment, because it changes how you read the arms

Writing the engine exposed two sealed outcome units that were **artifacts of construction**, and I
amended before running rather than after:

- **Expectancy "in bps of notional" makes P2 identically ZERO against P0** — `notional = risk ÷ stop`,
  so the risk cancels. An arm that can only come out zero is the same defect as one positive by
  construction, and it would have looked like a *precise null* with a tight CI.
- **Drawdown "per unit risk, in R" mechanically favours the wider stop**, because R *is* the stop. My
  sealed tie-break "the better drawdown wins" could only ever have broken one way.

Both moved to **% of equity**, and `P2 − P0` was declared **deterministic (×0.93220), not estimated** —
no CI on arithmetic. **The run returned 0.93220 to five decimals**, which is the instrument confirming
the correction.

## 🔴 The finding worth more than the z

**The drawdown verdict reverses with the denominator:** in % of equity, P2 wins by +0.0127 (z 46); per
unit risk in R, **P1 wins** by −0.0280. Both arms agree on the flip, so it is construction, not noise.

**Both denominators are confounded, in opposite directions** — in % of equity P2 partly just risks
fewer dollars (0.4661% vs 0.500%); in R, P1 partly just has a bigger denominator. **And they cannot
both be fixed: matching notional *and* dollar risk forces the same stop, i.e. the same policy.**

**So "widen vs size down" has no empirical answer — only a preference answer.** Widening holds dollar
risk at 0.5% and shrinks the position; sizing down shrinks the risk and keeps the stop. **Which
quantity the owner wants held constant is his call, and it is not a number I can supply.** If that is
worth a terminal line, that is the framing I would use.

## For the owner, the one-liner

**The spread between the best and worst of the four policies is about $0.08 per trade on $5,000 —
less than the round-trip fee.** With M9, where leverage could not move P&L at all, **two independent
studies now say the geometry dials are economically irrelevant at this account size**, and the dials
that matter are risk-per-trade and whether to be in the trade. Same answer his leverage instinct got.

## Scoring my own sealed expectations

**7.1 (all underpowered): HELD — by 0.05 of a z.** Right call, far thinner margin than implied.
**7.2 (size-down beats widen): MISSED.** The point estimate runs the other way. My mechanism — a wider
stop converts small losses into larger ones — **is not supported on expectancy**, though it *is*
consistent with the % of equity drawdown. So it described path pain correctly and expectancy not at
all, and I had merged the two into one claim. **Sixth power miss of the session, all the same
direction.**

## 🔴 Void run 1, and the bug was the smaller half

`HIST` pointed at `hist/`; the directory is `history/`. All 178 funding files missed, every coin
skipped — **and the script still printed `VERDICT: UNDERPOWERED` and scored an expectation, from zero
rows**, because `(nan > 0) == (nan > 0)` is `True` and `nan < 0` is `False`.

**A harness that renders a verdict out of no data is absence-is-not-evidence living inside the
instrument** — the same family as my six `j4` false alarms, where the detector was the thing that
broke. **Fixed structurally, not by correcting the path:** it halts under 50 funding coins, or under 20
held-out / 3 discovery coins. **Standing rule adopted: a harness must be unable to reach its verdict
block on an empty panel.** Worth checking whether anything server-side can print a grade from an empty
read — that is the same shape as the 3.5-hour grading outage.

## Queue

M1 ✅ M2 (arm A) ✅ M3 ✅ M4 ✅ M9 phase 1 ✅ — **M5 next** (tail/cascade risk → recalibrated
safe-leverage table). M6/M7/M8 after. Still want HL's tiered `marginTables` for M9 phase 2, and the
live dissent series for M3 stage 2. Nothing blocking.
