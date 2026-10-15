# M28 AMENDMENT 1 — red-team panel (3 judges, 7 FATAL / 9 MATERIAL / 4 MINOR), adopted BEFORE any code

Supersedes `M28_MAP_DESIGN.md` where it conflicts. Also amends the seal — see the SEAL AMENDMENT
section at the bottom, which governs.

## FATALs closed

1. **The unit is the MOMENT, not the cell.** Both sides at one (coin, ts) share one path: drift and
   carry cancel exactly in pooled-over-sides means (true by construction — zero market information) and
   the ≈−1 pair correlation fakes tight CIs. Every outcome decomposes into **D = (L−S)/2 (direction)**
   and **A = (L+S)/2 (machinery/cost)**; directional claims attach to D only, and a condition survives
   only if same-sign in BOTH side strata. Martingale controls and `nullreal` generate ONE path per
   (coin, ts) with both sides computed from it (the m13 `synth_paths` side-vector pattern), so null and
   real share the pair structure. Every n, floor, and MDE counts **moments**, never cells.
2. **Grid arithmetic fixed:** 24-bar (24h) spacing applies to the (coin, ts) PAIR — one retained ts per
   24h per coin, long AND short evaluated at that same ts. **~37k moments (~74k cells), not 450k.**
   Floors and MDE restated in moment units; clustering at coin × non-overlapping-72h-block (week blocks
   satisfy this), effective-n printed beside every count.
3. **Twin gate split in two, and it can be UNDECIDABLE:**
   - CONSISTENCY gate vs `owner_plan_sims` (same algorithm, same 5m bars via `exit_style.play` itself):
     tolerance ~0, **gross-to-gross** (fees/carry stripped for the match; verified separately against
     the ledger's own fee/funding columns). Any gap = bug.
   - FIDELITY gate vs REAL fills only (`owner_fills` + trade ledger), each trade replayed under its
     RECORDED parameters (not the map's config). Signed MEAN ΔR across gated legs ≈ 0 (one-sided
     systematic error check), plus per-leg |ΔR| ≤ one 5m-bar range.
   - **PASS requires ≥ 30 closed real legs; below that the gate status is UNDECIDABLE and no
     confirmation read unlocks.** Carried limit on every map claim: no population end-to-end validates
     the em-stop map config against reality; sim-fill optimism is never discharged by the gate.
   - The `cases_index.style_r` vs `sims.r` one-fee discrepancy is reconciled (one governing record
     named) before the gate runs.
4. **Expired/blocked labels replay under their OWN entry discipline** (entry type, limit level, entry
   window): no fill → no outcome row; never-filled decisions are a separate stratum, NEVER pooled with
   filled outcomes. Labels dedupe into clusters by (coin, side, overlapping 72h window). All L1/L2
   stats stratified by status; the filled stratum alone carries L2.
5. **Label-aftermath exclusion:** the L2 gain excludes ALL same-coin cells (both sides) whose 72h
   window overlaps (label_ts − 72h, label_ts + 72h); n excluded reported; the with-picks number shown
   beside it, labelled "includes the picks themselves".
6. **L2 is honest about its power:** at n≈25–30 label clusters the MDE is ~0.6–0.9 R — no verdict but
   UNDERPOWERED is reachable. **L1 descriptive is the deliverable.** L2 ships as a point estimate + CI,
   HYPOTHESIS-capped permanently, and **L2-derived conditions are BARRED from the frozen confirmation
   list.** The real L2 path is forward labels to n ≈ 240 (for a 0.2 R effect at z 2.8) — logged as a
   gated future read.
7. **Positive control before the confirmation read:** known effects (+10/+20/+30 bps tied to a
   frozen-style condition) injected into copies of `nullreal`; the full pipeline must recover them at
   the claimed MDE, recorded in the build meta. A pipeline that can only fail is not a guard.

## MATERIALs adopted (column hygiene and protocol)

- **Multiplicity capped:** ≤ 8 frozen conditions; survive = same predicted sign AND one-sided
  p < 0.0125/m (z ≈ 3.0 at m=8), same-sign in both side strata AND in eqw-by-coin AND eqw-by-week,
  |effect| ≥ max(MDE, 9 bps), held-out day-shift placebo p < 0.05. Styles and side-strata count inside
  m. Anything less = "noise-compatible survivor", logged not carded.
- **funding_hot recomputed point-in-time from funding_hist (368d)** with the frozen live definition —
  never read from the young scan_log wedge. General wedge rule: a column is fit-eligible only where the
  source is proven live; absence encodes NaN; any column whose coverage correlates with daykey beyond a
  stated threshold is descriptive-only.
- **waking_up spec pinned:** trailing 480h volume median over closed bars ending BEFORE the cell ts;
  one-day-lagged fitted em; thresholds frozen at M11's published values, no refit. Pre-stated expected
  sign: NEGATIVE (M11's fade) — a built-in direction check.
- **BTC shock pinned:** fitted HAR em, lagged one closed day (never naive constants, never same-day).
  **Vol terciles:** point-in-time trailing cutpoints, or discovery-frozen and applied unchanged.
- **liq-burst: descriptive-only** (pre-discredited by M5's placebo), heartbeat-gated baseline, NaN in
  the feed's first 7 covered days and under-coverage hours. **Voice agreement: DROPPED** as a column
  (6 coins/days of coverage is noise theatre); one-line aside at most.
- **Bar resolution pinned:** the map resolves on 1h bars (5m does not span the panel); the gates run on
  5m via `exit_style.play`; the 5m-vs-1h outcome delta on the gated trades is measured and carried as a
  stated optimism bound on every map number.
- **Controls' resampling pool restricted point-in-time** (bars strictly before the cell ts; at minimum
  discovery-window-only for non-ORIG17 coins) — the full-history pool was a technical breach of the
  seal for confirmation-era bars. Control is load-bearing for ABSOLUTE map claims only; it cancels in
  label contrasts (stated).
- **late_logged decisions are rendered NOWHERE before the condition freeze** (the leak is through the
  analyst); dropped from BOTH labelled and unlabelled pools; post-freeze appendix only.
- **Label staleness:** decision-ts minus cell-ts gap recorded per label; labels beyond the grid pitch
  excluded from L1–L3 (marked on the map only).

## SEAL AMENDMENT (governs; supersedes the recompute clause)

- **The discovery boundary is the calendar constant daykey 20693 (2026-08-28), unconditionally.** The
  recompute clause is struck — a built panel's median moves with builder choices and cannot define a
  seal. Panel imbalance is reported, never acted on. Builder coin-inclusion and date-filter rules are
  hashed into the build meta; changing them voids the run.
- **Row classes defined:** (a) owner-authored plan (regardless of executor) → replayable, labelable;
  (b) bot-agent-originated trade → FIDELITY-gate population only, never a label, excluded from
  LLM-replay concerns only if its entry rule is mechanical; (c) LLM-originated decisions (Claude ideas,
  bot agent model calls) → excluded from replay entirely, forward-graded only; an owner-ADOPTED LLM
  idea is class (c) for replay purposes (the model may remember the outcome) and is labelable only in
  the never-pooled descriptive stratum. The gate prints per-class counts.
- Frozen-condition cap m ≤ 8 and the survivor profile above are part of the seal.
