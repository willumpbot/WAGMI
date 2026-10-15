# M17 DESIGN — the funding-carry atlas + flip table: when does carry alone veto or resize a 1R plan? (Backlog M17. COST ONLY — funding's direction content is CLOSED as noise-compatible (M28); no sentence in M17 may imply direction.)

**Status: DESIGN, before any code. DESCRIPTIVE (no sim, so no null gate); its honesty gates are:
coverage floors, era-wedge flags, PERSISTENCE MEASURED BEFORE ANY FORECAST CLAIM, and uncertainty on
every cell.** Panel reviews first. Source: funding_hist, 368d × 178 coins, hourly.

## 1. The one empirical claim under everything
Carry over a hold = Σ settled hourly rates × side — mechanical ONCE THE PATH IS KNOWN. The atlas's
value rests entirely on whether the ENTRY-TIME funding state forecasts the HOLD's realized carry.
So stage 1 measures, per coin: funding autocorrelation and half-life; R² of (entry rate → realized
24/48/72h carry) and of (trailing-24h mean rate → same); the stability of these across eras (first
vs second half of the sample). **If half-lives are short relative to holds, the flip table must key on
the regime mean, not the entry print — the data decides, pre-stated.**

## 2. The atlas
Per coin × side × entry-time funding bucket (percentile of the coin's OWN TRAILING 90d history —
trailing, never full-sample, to kill era wedges): distribution of realized carry over 24/48/72h holds
(median, p10/p90), in **bps of notional** and in **R of the coin's median sf** (denominator pinned per
coin and printed). Buckets: ≤p10 / p10–50 / p50–90 / >p90, side-signed (carry-for vs carry-against).
Uncertainty: day-block bootstrap per cell; n (hours and distinct days) on every cell; coverage floor:
a cell below 30 distinct days is printed without any threshold language.

## 3. The flip table (the deliverable)
Per coin (and pooled by liquidity tier): the trailing-percentile threshold at which expected realized
48h carry-against exceeds (a) one round-trip fee (9 bps), (b) 0.10 R of the coin's median sf, each
with its bootstrap CI. Plus the live-desk translation: for the current open-plan coins, today's
percentile vs their thresholds (descriptive snapshot, timestamped). Framing discipline: the table
says "at this funding state, holding against carry for 48h costs ≥ X" — a COST statement; whether to
veto/resize remains the planner's/owner's call, and no cell may be read as "shorts win here."

## 4. Validation leg (still cost, never direction)
Backtest the forecast itself: for each historical moment and side, predicted 48h carry (from the
chosen key: entry print or regime mean, per stage 1's answer) vs realized 48h carry — calibration
plot numbers (slope, intercept, R²) per coin tier. A flip table built on a key with R² ≈ 0 does not
ship; the result then becomes "carry is real but not forecastable at entry," which is itself the
answer to M17's question (carry cannot veto at entry if it cannot be forecast at entry).

## 5. Panel questions
(a) Persistence methodology: funding is clamped at venue baselines much of the time (75% of HYPE hours
at 1.25e-5) — autocorrelation on a clamped series is inflated; what is the honest persistence measure
(state-transition probabilities between buckets? time-above-threshold survival)? (b) Trailing-90d
percentile on a 368d series: wedge effects at the series start; coverage rules. (c) The R denominator:
median sf per coin drifts — pin the convention. (d) Any way this quietly becomes a direction claim —
name the sentences that must not be written. (e) Measure with DB access: realized carry distributions,
half-lives, clamp shares per coin tier — and whether 24/48/72h differences even matter (carry scales
~linearly in time unless regimes flip mid-hold; measure the flip frequency).
