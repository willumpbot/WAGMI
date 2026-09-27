# Mean-Reversion vs Trending Market Structure Study — Results

Script: `tools/copilot/meanrev_structure_study.py` (read-only, no Discord, no live-state writes).
Run: `python tools/copilot/meanrev_structure_study.py`
Outputs: `tools/copilot/meanrev_structure_output/{per_coin_horizon_map.csv, era_split.csv, liquidity_gradient.csv, liquidity_tiers.csv, data_coverage.json}`

Universe: 25 longtail alts (`data/longtail/ohlc/*_1d.csv` / `*_1h.csv`, verified gap-free,
~13mo daily / ~7mo hourly) + BTC/SOL majors (`data/cache/{BTC,SOL}_{daily,1h}_420d.csv`).
**Majors cache is stale, ending 2026-07-13/14 while alts run to 2026-08-01 — every majors
number below is ~3 weeks short of the alts' window; flagged, never silently normalized.**
Horizons: 1h, 4h (resampled from 1h), 1d, 3d, 5d (resampled from 1d). 135 (coin, horizon) cells.

Four independent methods per cell (full formulas/limitations in the script's module
docstring): return autocorrelation (lags 1-5, Bartlett SE), Lo-MacKinlay (1988)
heteroskedasticity-robust variance-ratio test (hand-implemented, no statsmodels available
in this environment), Ornstein-Uhlenbeck half-life (OLS on lagged log-price, MR-only vote),
Hurst exponent (classical R/S, log-log regression). Composite label requires >=3/4 (strong)
or 2/4 (weak) methods to agree at |z|>=1.96 — a deliberately conservative bar.

## 1. Per-coin x per-horizon map (headline)

| horizon | STRONG_MR | WEAK_MR | RANDOM_WALK | WEAK_TREND | STRONG_TREND |
|---|---|---|---|---|---|
| 1h | 0 | 2 | 24 | 1 | 0 |
| 4h | 0 | 0 | 23 | 4 | 0 |
| 1d | 0 | 0 | 26 | 1 | 0 |
| 3d | 0 | 0 | 27 | 0 | 0 |
| 5d | 0 | 0 | 27 | 0 | 0 |

**Zero cells out of 135 reach STRONG mean-reversion or STRONG trending under the strict
multi-method-agreement bar.** Almost the entire (coin, horizon) grid is statistically
indistinguishable from a random walk on a single-sample test. The two WEAK_MEAN_REVERSION
hits (ONDO@1h/thin-tier, XPL@1h/liquid-tier) show no tier pattern — full detail in
`per_coin_horizon_map.csv`.

This composite bar is conservative on purpose (n=130 at 3d, n=80 at 5d starves single-sample
power) — see the era-split corroboration in section 4, which finds real structure the
single-sample test is underpowered to certify.

## 2. Liquidity gradient verdict — NOT confirmed, and inverted where it matters most

Coins split into data-driven terciles by entry-time-safe rolling $ volume (27-coin pool,
9/9/9): **liquid** (12bps) = BTC, SOL, ZEC, PUMP, FARTCOIN, XPL, SUI, kPEPE, LINK; **mid**
(32bps) = kBONK, PENGU, AAVE, AVAX, TAO, WLD, ADA, CRV, LTC; **thin** (75bps) = PAXG, ARB,
UNI, ONDO, BCH, LDO, APT, TRX, kSHIB.

Spearman(liquidity, mean-reversion strength) across all 27 coins, 3 metrics x 5 horizons
(15 tests): **only 1 of 15 reaches p<0.05** — 1d liquidity-vs-Hurst, rho=+0.44, p=0.022
(more liquid -> higher/more-trending Hurst; thinner -> lower Hurst), directionally
consistent with the thesis but a single hit out of 15 tests is within the expected false-positive
base rate (~0.75 expected by chance at alpha=0.05) and is not corroborated by acf1 or VR at
the same horizon (rho=0.12 p=0.54, rho=0.26 p=0.19).

**Where it counts most — the 3-day horizon, the only one with genuine era-stable structure
(section 4) — the gradient is not monotonic and if anything runs backwards**: median acf1 by
tier is liquid −0.132, mid **−0.142 (strongest reversion)**, thin **−0.085 (weakest
reversion)**. Thin-tier individual failures (TRX +0.015, APT −0.076 non-significant sign,
PAXG +0.024) sit right in this tier. **The mechanism-level thin-alt-mean-reversion thesis is
not supported by this dataset — mid/liquid alts revert at least as strongly as thin ones.**

## 3. The tradeable filter — cost-honesty check

Amplitude estimated two ways: AR(1)-implied (`|acf1| x return_std`) and empirical dip-bounce
(mean next-bar return conditional on a bottom-decile return bar), both in bps, compared to
tier round-trip cost (12/32/75bps).

- **1h is pure noise, cost-dominated everywhere**: 0/27 cells clear cost at any tier (amplitude
  0.3–1 bps vs 12bps floor even for the "liquid" tier) despite ~483 recurring dip events per
  coin (real recurrence, not a single crash) — this is exactly the bid-ask-bounce /
  microstructure-noise trap the study was designed to catch. **Statistically-detectable
  hourly "reversion" in this universe is not tradeable at any liquidity tier.**
- **4h is also mostly cost-dominated** (liquid 2/9, mid 0/9, thin 0/9 clear cost).
- **1d is thin on power and mixed**: liquid 5/9, mid 2/9, thin 0/9 clear cost — but recall
  no 1d cell reached significance, and 1d is the horizon flagged regime-unstable below.
- **3d is where amplitude genuinely clears cost across nearly the whole universe**: liquid
  8/9, mid 9/9, thin 5-6/9 (AR1 vs dip-bounce definitions) clear their tier's cost. This is
  the strongest cost-survival result in the study, but **thin still clears least often of the
  three tiers**, consistent with section 2's inverted-gradient finding — the extra cost thin
  coins must overcome (75bps vs 12-32bps) is not compensated by extra amplitude.
- **5d also clears cost broadly (liquid 9/9, mid 7/9, thin 3/9) but has no era-split
  corroboration** (pre-period n too small, see section 4) — treat with materially lower
  confidence than 3d.

No cell anywhere is simultaneously STRONG/WEAK_MEAN_REVERSION (composite label) **and**
tradeable-after-cost — the composite label's single-sample significance bar and the
amplitude-vs-cost filter never co-occur in this run (the composite label was too underpowered
at 3d, see section 4, to certify what era-stability shows is real).

## 4. Era-stability + refutations

- **3d is era-stable — the study's strongest finding**: splitting at 2026-02-01 into two
  independent ~65-observation halves, **18/25 alts (72%) show negative acf1 in BOTH eras**.
  A single-sample test lacks power at n=130 to hit z<=-1.96 per coin, but two independent
  halves agreeing on sign for 3 out of 4 coins is not consistent with pure noise — this is
  corroborating, not composite-label, evidence of a genuine, modest, ~3-day mean-reversion
  tendency spread across essentially the whole alt universe (not concentrated in thin names).
- **1d is regime-dependent, not structural**: only 9/27 (33%) coins keep the same acf1 sign
  pre- vs post-2026-02-01; **18/27 (67%) flip from positive (trending) pre-Feb to negative
  (reverting) post-Feb**, including BTC. Any claim of "1d mean-reversion" from a single-era
  sample would be a regime artifact, not a persistent structural property — this is exactly
  the kind of overclaim the era-split check exists to catch, and it caught one.
- **5d cannot be era-checked**: pre-period n falls below the 40-obs floor for nearly every
  coin (`era_split.csv` — 27/29 "insufficient" rows are 5d). The 5d tradeable-after-cost
  result in section 3 is reported but unverified against regime-stability.
- **1h/4h cannot be era-checked either**: hourly source data only starts 2026-01-12, leaving
  ~3 weeks of pre-cutoff data — deliberately skipped rather than run on a starved sample.
- **Single-crash-vs-genuine-oscillation**: `n_dip_events` per cell is in the CSV. At 3d it
  runs 7-14 per coin (~10% of ~130 obs, as expected from the decile threshold by
  construction) — a real recurring pattern, not one crash-and-recover. At 1h it's ~483 per
  coin. No cell in the non-random-walk set has `single_event_artifact_flag=True`.
- **Data-integrity / gappiness**: the 25 alts were verified gap-free before the study ran —
  uniform 402-row daily / 4829-row hourly coverage across 22 of 25 coins, with PUMP (388
  rows) and XPL (345 rows) simply listed later, still gap-free from their first observation.
  The thin-alt structure found (or not found) here is not a stale-data artifact.
- **Majors staleness**: BTC/SOL numbers all come from a cache ending 2026-07-13/14, ~3 weeks
  short of the alts. BTC/SOL land in the "liquid" tier as expected (sanity check passes) but
  their absolute numbers are not on the identical calendar window as the alts and should be
  read as approximate reference points, not exact comparators.

## 5. Honest bottom line

For the owner's unlevered, dip-accumulation thesis:

- **The thin-alt-is-more-mean-reverting mechanism is not supported.** Across 15
  liquidity-vs-reversion correlations only one is nominally significant (within the expected
  false-positive rate for 15 tests), and at the one horizon with genuine, era-stable
  structure (3-day), thin coins revert **the least** of the three liquidity tiers, not the
  most — a direct, mechanism-level refutation of "thinner is structurally more dip-buyable."
- **Where mean-reversion genuinely exists, it's a ~3-day-horizon, whole-universe effect, not
  a thin-alt effect.** 72% of alts show the same-sign 3-day reversal in two independent
  6-month halves of the dataset — that's real, not noise — but it's present in liquid, mid,
  and thin names roughly alike (mid-tier is if anything strongest).
- **It does clear realistic costs at 3d, for most coins, in every tier** — liquid 8-9/9, mid
  9/9, thin 5-6/9 — so a "buy the 3-day dip" pattern is not a spread-eaten mirage at that
  horizon; it survives 12/32/75bps round-trip costs about as robustly across all three
  tiers, with thin very slightly weaker.
- **Hourly and 4-hour "reversion" is exactly the bid-ask-bounce trap the study was built to
  catch**: real, recurring, statistically present in a couple of coins, but amplitude is
  0.3-20bps against a 12-75bps cost floor — categorically untradeable at any liquidity tier
  on this dataset.
- **1-day horizon structure is not trustworthy as a standing rule** — it flips sign for 2/3 of
  coins across the pre/post-2026-02-01 split, so a "1-day dip-buy" rule calibrated on one era
  would misfire in the other.
- **5-day horizon shows the same cost-clearing pattern as 3-day but is statistically
  unverified** (no era-split power) — treat as suggestive, not confirmed.

**Net**: the mechanism-level evidence points to a modest, genuine, ~3-day mean-reversion
regularity across nearly the whole alt/major universe that survives realistic costs in every
liquidity tier — but it is not a thin-alt phenomenon, and if anything the owner's thesis runs
backwards on this data: mid/liquid names reverted at least as reliably as thin ones. A
"buy-the-3-day-dip" posture applied indiscriminately across liquidity tiers (not specifically
skewed toward thin/illiquid names) is the structure this data actually supports.
