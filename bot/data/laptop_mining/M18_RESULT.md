# M18 - concurrent risk: the co-stop gradient is real (lambda 1.28 -> 1.71 by correlation; TRIPLES at 3.34), but the rule grid is UNRESOLVABLE at this n - per the pre-registered fallback, the recommendation is the SIMPLEST rule at the COARSEST parameter, warn-only.

_2026-10-16. m18_run.py to M18_AMENDMENT_1 (c990810e). EXPLORATORY, HYPOTHESIS cap; risk arithmetic
only. 51,930 entries / 13,410 sampled pairs (9,305 discovery / 4,105 confirmation; chains ~= pairs
after dedupe). The confirmation-era pricing below is M18's ONE sanctioned read of that era (the sealed
m28 npz was never opened)._

## 1. The measurements (the durable part)
- LAMBDA_TOTAL (compound: co-movement x regime mixing - what a planner cap must price):
  corr <0.3: **1.28** | 0.3-0.5: **1.49** | >=0.5: **1.71** (n=4,470/stratum). Monotone in
  correlation, as the mechanism requires.
- **TRIPLES: lambda_3 = 3.34 pooled** (250 sampled triples, longs) - three same-direction positions
  jointly stop 3.3x more often than independence. The one number with teeth at the desk's scale.
- Blocked-set expectancy prediction HELD: |E[R_blocked]| <= 0.084 eqw everywhere (pre-stated bound
  0.1) - blocking costs breadth, not expectancy, as predicted and now shown.

## 2. The machinery flag (reported, not resolved)
LAMBDA_WITHIN computed at M7's definitions came out **1.31 - BELOW M7's confirmed [1.538, 1.737]**.
Per the amendment this flags THIS study's regime-conditioning machinery (my BTC-48h-vol terciles vs
M7's regime bins; thin per-(coin,side,regime) marginal cells), not a revision of M7 - **M7 remains the
confirmatory anchor.** For any live arithmetic, use the CONSERVATIVE (higher) co-stop estimates: M7's
1.64 for pairs, this study's 1.71 at high corr, 3.34 for triples.

## 3. The rule grid: UNRESOLVABLE (the pre-declared outcome fired)
The discovery scan's "winner" (beta budget 1.5) blocks **92% of all pairs** - a near-ban on
concurrency dressed as a rule - and its tail-drop edge over the runner-up (3.5pp vs 1.6pp) is inside
the clustered MDE (5-7pp). Its confirmation-era pricing (tail 20.0% -> 14.1%, blocked E[R] +0.008)
is honest but priced on a rule no desk would run. **Per the pre-registered condition: grid
unresolvable -> recommend the SIMPLEST rule at the COARSEST parameter:**

> **WARN when adding a same-direction position whose 60d correlation with any open position is >= 0.5,
> with the arithmetic attached: "these two stop together ~1.6-1.7x more than independent positions;
> three such positions ~3.3x. Count them accordingly against your risk budget."**

Warn-only (the M17 precedent); no block. At k=2 the corr-gate and the R-eff cap are the same rule in
different clothes (stated); the beta budget double-prices regime mixing and is not separable at this n.

## Limits
Sampled pairs (cap 30/day/stratum, seeded); 24h-lag sets dominate (lag robustness not split at this
n); lambda_within machinery discrepancy unresolved; one 212d regime; price-touch stop definition
(engine-free, matches M7's harness); triples existence-tested only.
