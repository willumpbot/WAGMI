# M15 DESIGN — stop placement vs liquidation clusters: does "just beyond the cluster" beat "at it" or "inside it"? (Backlog M15; tests the LIQ_MAGNET_RECHECK rule-of-thumb #2 properly.)

**Status: DESIGN, before any code. EXPLORATORY, HYPOTHESIS cap.** Panel reviews before the first run.
Prior art honored: cluster definition is the server's calibrated one, verbatim (≥3 independent episodes
within 0.2%, 0.3–3% from price, Bybit feed — `liq_magnet_calibration.py`); the magnet-as-TARGET
question is CLOSED as "suggestive, not established" (LIQ_MAGNET_RECHECK 10-09) and is not re-asked.
The open claim under test is their own plain rule: *"stops sitting on a cluster get swept."*

## 0. The data reality, stated first (this study may legitimately end DEFERRED)
liq_events is Bybit-only, 13 symbols; BTC ≈ 74d, SOL similar; ETH/HYPE/XRP/NEAR only since 2026-10-08
(DAYS). The population is therefore **covered-majors-only and small**. The panel must size the expected
n and MDE; if the honest answer is "underpowered until the feed deepens," the design pre-authorizes the
verdict **DEFER with an accrual target** (events/week measured, target n stated) instead of a forced
read. A deferred M15 is a result, not a failure.

## 1. Population
Random-time BOTH-SIDED entries (24-bar spacing) on covered coins, eligibility: a point-in-time cluster
exists on the STOP side at entry — episodes strictly BEFORE the entry ts, distance 0.3–3%. The
population is thereby conditioned on recent cascade activity nearby; that is the live situation the
rule addresses and is stated, with the martingale controls sharing the same conditioned moments.
Overlapping-window chains as the unit where windows overlap (the M14 dedupe pattern).

## 2. Arms (stop geometry only; everything else the live engine)
Per entry, with C = the nearest stop-side cluster level:
- **S0 baseline**: stop = 1.65 × em (wherever it falls relative to C) — the live default.
- **S1 inside**: stop between entry and C (at C minus 0.25 × ATR14 toward entry).
- **S2 at**: stop exactly at C.
- **S3 beyond**: stop at C plus 0.25 × ATR14 past the cluster (the rule's recommendation).
Runner engine otherwise unchanged (half @ +1R OF EACH ARM'S OWN STOP, 1-ATR trail, 48h, leg fees,
carry). **Sizing honesty (M4's lesson): risk is fixed per entry, so wider stops mean smaller size by
construction; outcomes are in R of each arm's own stop with bps-of-fixed-risk beside, and per-entry
controls run with the SAME four stop geometries** so no-edge pricing differences are subtracted per arm.
Outcomes per arm: stop-hit rate within 48h AND control-subtracted net (R + bps).

## 3. Reads, gates, family
Null gate (nullreal, 4 cells) then positive control (linearity + 1.5× own-MDE detection) then the read:
family = 3 contrasts (S1−S0, S2−S0, S3−S0) at z ≥ 3.0, plus stop-hit-rate deltas as the mechanism check
(pre-stated expectation: hit-rate S2 > S1 > S3 — if S2's stop is NOT swept more often, the rule's
premise dies before its payoff question). eqw-by-coin beside pooled (few coins — coin list printed),
coin × week two-way CI act on wider, n as chains/events per cell, per-arm MDEs before any verdict.
Panel's standing question: clusters are path-information-dense — verify no element uses episodes at or
after entry, and probe what the cluster-existence conditioning does to the control's validity.

## 4. Govern
Exploratory → HYPOTHESIS cap; snapshot + filter hash; HALT on silent drops; sim fills optimistic
(carried); Bybit single-venue coverage carried on every claim; the owner's plain-rule update ships only
if S3−S2 clears the family bar AND the hit-rate mechanism agrees.
