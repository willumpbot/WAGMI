# M16 AMENDMENT 1 — panel (3 judges, 4 FATAL / 6 MATERIAL): design sound at its core (the null algebra is CLEAN — E[L−M] = 0 exactly under the null by optional stopping), but the dedupe, the grid, the claim wording, and the units all needed fixing. Adopted before any code; supersedes the design.

**Power statement corrected: this is NOT a huge-effects screen.** Measured: 25,965 raw moments →
**8,713 kept moments** (moment-level dedupe), paired pooled MDE **0.011–0.015 R** vs objects of
interest 0.32–0.96 R (the price improvement itself) — effects 20–60× the MDE. DEFER will not trigger
on population.

## FATALs closed
1. **Dedupe at the MOMENT level, keep BOTH sides** (the either-side keep-first would have deleted the
   short side deterministically). n reported as moments / moment-sides / fills.
2. **Family re-gridded to d ∈ {0.25, 0.5, 0.75}** (measured 24h fills 64.0% / 37.2% / 21.4%); d=0.75
   pre-committed even though it hugs the 20% floor — floors are measured-then-frozen, never tuned.
   **d=1.0 is descriptive-only** (12.5% fill — born below its own floor). **W = 24h is frozen now and
   may not move after any outcome exists**; W=12h/48h, per-side splits, and the pessimistic-fill
   variant are descriptive, no verdict language.
3. **The claim is renamed to what ITT answers**: "the limit PLAN vs the market PLAN at distance d."
   ITT = p·E[L−M | fill] + (1−p)·(−E[M | no-fill]), and the complement term mechanically reproduces
   the adverse-selection signature from pure missed-trend (measured: −0.014/−0.024/−0.034 R, monotone
   in d). So: **the mandatory two-term decomposition ships next to every headline**; "adverse
   selection" language may attach ONLY to the fill-stratum term (descriptive — fill is post-treatment),
   never to the ITT sign. The fill-stratum term is benchmarked against the identically fill-conditioned
   contrast on control draws (its mechanical baseline).
4. **Pooled-side cells are the z ≥ 3.0 family (exactly 3)**: per-chain scalar built FIRST as the
   within-moment average of the two sides' [(L−M) − (ctrl_L−ctrl_M)] — the paired-design variance
   advantage is real and d-dependent (corr 0.57 → −0.10) and must be exploited by differencing before
   bootstrapping, never by differencing cell means. Widest of coin-eqw / chain-level / coin×week CI.

## MATERIALs and conventions pinned
- **Common denominator**: both arms normalized by the MOMENT's sf = 1.65 × em(t); own-em_f
  normalization reported as sensitivity. Engine stop/trail widths still re-resolve at the fill day
  (live-consistent); control-path fills resolve em_f/ATR_f from the real calendar (stated limit).
- **Mechanical cost term stated**: E[L−M] carries +fee·(1−p) under the null (unfilled limits pay no
  fees; +0.006 to +0.015 R by d — same order as the MDE). The identical-logic control prices it down
  to the real-vs-control fill-rate mismatch (measured residual +0.0003–0.0008 R — two orders below
  MDE); the per-cell **"fill rate real vs control" line ships with every read**.
- **Placement anchor**: limit = close of bar t; watch starts bar t+1; a first-watch-bar open already
  through the limit fills AT THE LIMIT level (the maker convention — a resting order executes at its
  price), share reported (measured ~0.03% at d=0.25, zero above).
- **Maker-fee note (mine, not the panel's)**: real limit entries pay maker fees (< taker); the engine
  charges taker on both arms — conservative AGAINST the limit arm; stated as a limit, favors no
  false positive for L.
- **Era rule said out loud**: the headline runs on the full panel (acceptable for an exploratory
  HYPOTHESIS-cap study); any condition split stays m28-discovery-era until the freeze protocol allows.
- Fill-bar convention transfers from M14's A3 (fill at level, bar participates stop-first, no same-bar
  arming); em-vintage drift between arms reported (median 8.1% day-over-day when fills cross a day).
- Owner bridge: his real limit distances (plans.json histogram, descriptive) mapped against the tested
  d's before verdict language is drafted.
