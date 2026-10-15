# M14 — re-entry after a runner exits: **NULL on all three arms. Neither re-entering nor holding longer beats walking away — the 48h clock exits at the right time.**

_2026-10-16. `m14_run.py` to `M14_AMENDMENT_1.md` (panel: 10 FATALs adopted pre-build, arms rescoped).
EXPLORATORY, HYPOTHESIS cap. Sensitivity stated FIRST: per-arm MDEs 0.020–0.039 R — much better than
the feared 0.2 R (4,938 chains beat the panel's 1,057 estimate), but still a screen: effects under
~2–4% of risk per event are invisible. Snapshot stamped; sim fills optimistic (carried)._

## Population and gates
15,955 raw armed-then-exited runner events → **4,938 chains** after keep-first dedupe of overlapping
96h same-coin windows (69% dropped). Exit mix: **81% clock / 19% trail** (post-dedupe) — most runners
STALL rather than ratchet out. Null gate passed (all |z| ≤ 0.61); positive control passed (linearity
recovered to 4 decimals; detection at 1.5× A1's own MDE, z 4.08). Vol-sensitivity 0.88 — the control
slightly OVERprices post-exit vol, i.e. the conservative direction.

## The read (ITT, control-subtracted, R units; family bar z ≥ 3.0)

| arm | ITT mean | 95% CI | z | note |
|---|---|---|---|---|
| **A1 immediate re-entry** | −0.0087 R | [−0.035, +0.017] | −0.65 | fills 2 fresh legs for nothing |
| **A2 hold the original longer (96h, fee-free)** | −0.0049 R | [−0.018, +0.009] | −0.71 | the owner's real alternative — also null |
| **A3 true pullback (clock exits, 0.5-ATR displacement)** | +0.0005 R | [−0.015, +0.015] | +0.07 | fill 36% of clock events, n_fills 1,454 (above floor) |

Splits (descriptive): A1 after TRAIL exits +0.019 R [−0.048, +0.083] (n=926 — wide, nothing);
after CLOCK exits −0.015 R [−0.044, +0.013].

## What this answers, in the owner's words
*"Did we ever re-enter?"* — **you don't need to.** Down to ~0.02–0.04 R sensitivity: re-entering
immediately costs its fees, waiting for a genuine pullback earns nothing, and — the sharper half of
the answer — **holding the original position longer is ALSO worth nothing** (A2, which costs no fees
at all, is mildly negative). M10 said the 48h clock's cost lands on winners; M14 now says the clock's
exits are not leaving continuation money behind either. The exit machinery walks away at the right
time; the regret the owner feels after a runner keeps going is survivorship memory, not a measured
edge (CASHCAT's +2.43R continuation remains the n=1 that motivated this — the cross-section says it
does not generalize).

## Limits
Huge-effects-only below ~0.02–0.04 R; 1h bars with at-level fills (optimism carried; A1 uses the
tradeable next-bar open specifically to avoid the pre-triggered-level trap the panel measured);
depth-1 (re-entries don't spawn events); one 212d regime; condition splits deferred (the m28
discovery-era-only rule — nothing here warranted them). Forward real-exit labels keep accruing,
tagged by depth, for a sealed read at a target n set once the accrual rate is known.
