# M14 DESIGN — re-entry after a runner exits (owner's question: "did we ever re-enter?"). Scope (a) per reply 164 / server 05:25Z: SIMULATED re-entries on the full panel; real forward re-entries accrue as labels for a later sealed read.

**Status: DESIGN, written before any M14 code. EXPLORATORY, HYPOTHESIS cap** — no confirmatory claim
without a new seal. Red-team panel reviews this before the first run (mandatory).

## 1. Population (the conditioning event)

From the m13/m28 engine on the 1h panel (em lagged one closed day; one point-in-time ATR14; leg fees;
carry; 0.5-R... stop 1.65 × em; runner = half @ +1R, 1.0 × ATR trail floored at stop, 48h clock):
simulate random-time BOTH-SIDED entries (24-bar spacing per coin as in M28) and keep the subset whose
runner **ARMED (+1R printed) and then exited the remaining half via TRAIL or CLOCK** — the "runner
exit" events. Each event carries: side s, exit ts t_x, exit price, best price B since arming, the
original entry/stop, and the m28 feature vector at t_x (point-in-time).

**Key honesty note (pre-stated):** conditioning on "armed then exited" SELECTS moments where side s
ran ≥ 1R. A same-side re-entry is therefore a momentum-continuation bet on a selected population — the
null is NOT symmetric-random. That is exactly why every outcome is per-entry martingale-control
subtracted (the control prices the machinery on the SAME conditioned moments), and why the mirror
contrast below exists.

## 2. Arms (pre-named; no post-hoc rules)

For each runner-exit event, each rule arms a POSSIBLE re-entry within a 48h watch window after t_x;
if its trigger never fires, the event contributes "no fill" to that arm (reported, not pooled into
outcomes):
- **R1 pullback-to-trail**: re-enter side s if price returns to the exit (trail) level.
- **R2 EMA20 touch**: re-enter side s on first touch of the 1h EMA20 (computed point-in-time).
- **R3 breakout retest**: re-enter side s on retest of the original +1R price.
- **R0 stay out** = 0 by definition (the comparison is each arm's control-subtracted net vs 0).
- **MIRROR contrast (the placebo-direction check)**: each rule also run OPPOSITE-side; a
  momentum-continuation edge must be positive same-side AND ≤ 0 mirrored — a "both sides win" read
  means the fill logic leaks.
Re-entered trades run the SAME runner engine (new stop 1.65 × em at re-entry, half @ +1R, 1-ATR trail,
48h), fees + carry accrued, fills AT trigger levels (optimism carried).

## 3. Outcomes and reads

R units govern (per re-entry sf); bps beside. Per arm: control-subtracted mean, eqw-by-coin and
eqw-by-week beside pooled, two-way (coin × week) CI act on wider, n in EVENTS (fills reported
separately from events). Null gate first (same pipeline on nullreal re-entries — the control draws
provide the null paths); positive control (linearity + detection at 1.5 × the arm's own MDE); MDE
stated before any verdict. Fill-rate per rule reported (a rule that fills 3% of the time is not a
rule). Descriptive splits: by exit type (trail vs clock), by vol tercile (point-in-time), by the m28
condition columns — all HYPOTHESIS-tier.

## 4. Forward labels (scope (b), accruing since 2026-10-15 02:48Z)

Every LIVE runner exit (paper engine) is a forward M14 label from now (first: HYPE 72be6ccce3 +1R/trail
04:15Z). Read ONLY at a sealed n (target set when the accrual rate is known; the sealed read's design
references this doc). Nothing in the simulated study constrains or peeks at the forward labels.

## 5. Govern

Exploratory → HYPOTHESIS cap; a confirmatory claim needs a new seal. Snapshot stamped + filter hash;
HALT on missing data; every rate carries n; sim-fill optimism carried on every claim until the fidelity
gate passes at n ≥ 30 real legs.
