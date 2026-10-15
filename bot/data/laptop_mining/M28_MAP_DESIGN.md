# M28 DESIGN — the MAP: every coin, every moment, both sides, replayed under the live machinery; owner decisions as labels. (Owner priority, 2026-10-15)

**Status: DESIGN, written before any M28 code or data exists.** Split sealed FIRST in
`M28_SPLIT_SEAL.md` (cc950c1f). Red-team panel reviews this doc before the first run (mandatory since
M13's panel found 6 pre-run FATALs). Exploratory on the discovery population; confirmation reads happen
ONCE, after a condition freeze amendment, on the sealed held-out half.

Owner: *"run our own trading decisions on already-mined conditions ... it should be identical to live
trading"*, then *"rules like that only give us limited thought processes"* → map-first (1160c517): no
stated rules; the whole outcome space; his real decisions placed on the map as labels.

## 1. The twin (stage 0 — gate before anything is read)

One engine, reused: `exit_style.play` semantics via the M13 machinery (em lagged one closed day; ONE
point-in-time ATR14 feeding engine and features; leg fees on actual notionals; funding carry accrued
per leg hold; conservative within-bar ordering; fills AT levels — stated optimism). Entry at the NEXT
5m bar's open after the signal moment (no same-bar fill). Stop 1.65 × em; runner default (half at +1R,
1.0 × ATR14 trail floored at stop, 48h limit); 0.5% risk cap sets size; 9 bps round-trip.

**TWIN-MATCH GATE:** replay every real owner plan and bot trade (discovery-population ones only until
the freeze) from its actual fill ts/price under the same engine and compare leg-for-leg against the
graded record (`owner_plan_sims` / `cases_index`). Tolerance: |ΔR| ≤ fee + one-bar slippage per leg.
ANY gap beyond tolerance = simulator bug → fix before any map cell is read. Late-logged and
status=duplicate rows excluded from the gate population (they are excluded everywhere).

## 2. The map (stage 1 — build)

Grid: all ~174 coins × every 4th hour of the panel (~212d) × both sides ≈ **450k cells**
(subsampled to respect compute; spacing ≥ 24 bars within coin-side as in M13). Each cell: the
control-subtracted outcome of OUR machinery (R net, bps net beside) + per-entry K=8 martingale control
+ one independent `nullreal` draw (null gate in every fit). Outcome columns per cell: runner (default)
AND full (alt), so style is an outcome dimension, not a knob.

Condition columns (ALL point-in-time at the cell's moment; backward asof joins; coverage fraction
reported per column, NaN never imputed):
- From the panel: atr_em, atr_pct, stop_atr, trend (20/50 side-signed), room (confirmed fractals),
  ret7, hour bucket, BTC beta/R², BTC regime (BTC shock within last 24h per M5's trigger), vol tercile.
- From the mined streams (as far back as each exists; coverage stated): funding pctl/side-cost
  (funding_hist, 368d); funding_hot (scan_log flags); waking_up / attention flags (M11 trigger
  recomputed from bars — NOT the logged alert, which is young); liq-burst within 24h (Bybit venue
  coverage stated); voice agreement (voices, young + 6 coins — likely too thin, carried as
  partial-coverage); OI 24h change (31 syms / 130d).
- EXCLUDED: all dissent_log-derived columns until the M3 gate clears (the corpus is gated for the M3
  fit; its use as a condition column before that read risks contaminating a sealed study). LLM-decision
  rows excluded from replay entirely (model may remember outcomes) — forward-graded only.

## 3. The labels (stage 2)

Owner decisions = plans (incl. expired/blocked — the DECISION is the label, not the fill), calls,
watchlist adds, mentions (from exports; late_logged rows carry their flag and are marked on the map but
NEVER pooled into label statistics). Each label maps to its nearest grid cell (same coin, the cell at
or before the decision ts). Questions, pre-stated:
- L1: What do his picks share vs the rest of the map? (descriptive: feature distributions of labelled
  vs unlabelled cells, equal-weighted by coin and by week beside pooled.)
- L2: Do cells with his picks' profile replay BETTER under our machinery than random cells? (the
  profile is fit on DISCOVERY labels only — a depth-≤2 tree or quintile score, winner's-curse floors
  as in M13 — and its gain is measured with the M13 validation kit: grouped leave-coins-out,
  day-shift placebo B=200, null gate first, MDE stated before the verdict, R governs.)
- L3: Within labelled cells, does runner-vs-full split by any condition? (the M13 question re-asked on
  the owner's OWN selection — exploratory; the S2 vol-class anecdote is the pre-stated expectation and
  may die.)

## 4. Verdict structure (pre-stated)

Discovery phase produces: the map summary (which regions of condition-space our machinery earns/bleeds
in, with eqw-by-coin and eqw-by-week beside pooled, two-way CI act-on-wider), the label answers L1–L3,
and a FROZEN condition list (each with effect size, predicted sign, n) recorded as an amendment to
M28_SPLIT_SEAL.md. Only then is the confirmation population read, once: each frozen condition's effect
re-estimated on held-out coins/dates; survives if same sign and |z| > 2.24 under coin+week clustering.
Expected outcome stated now: MOST conditions will not survive (that is the fishing guard working).
UNDERPOWERED rule: CI covers 0 AND half-width > 9 bps → UNDERPOWERED, never "no structure".

## 5. Govern

Exploratory → HYPOTHESIS cap until the confirmation read; survivors cap at the prereg level the server
assigns. No sealed prereg is touched. Snapshot stamped; harness HALTs with missing data; every rate
carries n; placebo must be able to fail (day-shift, not row permutation); per-entry controls because
no-edge pricing depends on features; sim-fill optimism carried on every forward claim.
