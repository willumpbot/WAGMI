# M18 AMENDMENT 1 - panel (measured): two-level lambda decomposition; parameter choice through the existing m28 seal; the grid is pre-declared likely UNRESOLVABLE at this n (deferral thresholds pre-registered); sets redefined to match desk behavior. Adopted before any code.

Measured foundations: compound lambda (real joint / unconditional marginal product) = 2.04-2.38 at
corr>=0.5 vs within-regime ~1.6-2.0; regime swing in marginal stop rates alone is 2.3x (0.148/0.261/
0.338 across BTC vol terciles); day-clustered design effects 37-74 -> n_eff 265-366 per corr stratum;
MDE on tail probabilities 5-7pp vs baselines 13.5-22.3% - adjacent grid cells differ by less; triples
have no per-cell power; blocked-population E[R] measured at -0.08 (high corr) vs +0.02..+0.07 below.

1. TWO-LEVEL DECOMPOSITION (the estimator ruling):
   - LAMBDA_TOTAL = real joint-stop / product of REAL unconditional PER-DIRECTION marginals - the
     compound (co-movement x regime mixing) quantity. THIS is what a planner risk rule prices (a cap
     must bind under regime mixing too) and what feeds the R-eff formula.
   - LAMBDA_WITHIN = the M7 anchor ONLY, computed at M7's exact definitions: all-corr-pooled
     same-direction PAIRS, 24h co-stop window, marginals conditioned on the realized-window regime,
     per-direction. Only THIS number is compared to [1.538, 1.737]. mixing = total/within ships as an
     exploratory row. Controls are demoted to machinery validation (martingale marginal calibration).
2. PARAMETER CHOICE THROUGH THE SEAL: the rule x parameter grid is scanned on the m28 DISCOVERY era
   (daykey < 20693 or ORIG17) only; the chosen cell is priced ONCE on the confirmation era and that
   number is the deliverable (LOO coin-week blocks as the fallback if confirmation set counts are
   thin, stated which was used).
3. POWER HONESTY PRE-REGISTERED: every cell reports n_eff (set-chain + coin-day blocks); a cell is
   DEFERRED unless its tail-prob CI half-width < the claimed effect; the recommendation must beat the
   runner-up by MORE than the clustered MDE, else the verdict is "grid unresolvable at this n -
   recommend the SIMPLEST rule at the COARSEST parameter" (pre-declared as the likely outcome).
   Triples: ONE pooled existence test (lambda_3 > 1); all per-cell triple pricing DEFERRED; k>3
   EXTRAPOLATED.
4. SETS = OVERLAPPING HOLDS with entry lag <= L, L in {0, 12, 24h} pre-named; the cost/benefit table
   is reported at the lag profile matching the desk's observed concurrency; lambda-vs-lag is one
   robustness row; same-ts is a cell, not the definition.
5. COST = the FULL counterfactual outcome distribution of ALL blocked sets (E[R] net, tail
   contribution, breadth), eqw day/block mean beside pooled; the jointly-stopped split is a
   decomposition row; the 'breadth not expectancy' claim becomes the testable prediction
   |E[R_blocked]| < 0.1 R eqw (measured proxy -0.08 pooled at high corr - conservative, shown not
   assumed).
6. Minors adopted: independence products per direction; anchor at 24h; R-eff consumes LAMBDA_TOTAL
   (stated as a modeling choice); beta-budget overlap with regime mixing flagged so tail reduction is
   never credited twice; point-in-time 60d lagged betas (m28 convention).
