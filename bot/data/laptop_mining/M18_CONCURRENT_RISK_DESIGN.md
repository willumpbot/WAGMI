# M18 DESIGN — the concurrent-risk rule: turn M7's settled λ into ONE planner-facing rule and price it. (Backlog M18. RISK ARITHMETIC ONLY — no sentence here may imply direction.)

**Status: DESIGN, before any code. EXPLORATORY, HYPOTHESIS cap; the recommended rule ships to the
planner only as a WARNING (the M17 precedent) unless the server chooses otherwise.** Panel first.

## 0. What is settled and what is not
SETTLED (M7, 5/5 replications): two same-direction positions stop together within 24h at λ = 1.637
[1.538, 1.737] × independence, marginals within regime. NOT settled: how λ behaves for TRIPLES, at
48h, or as a function of pairwise correlation — M18 measures these on the m28 moment machinery rather
than extrapolating (any cell that must extrapolate carries an EXTRAPOLATED flag).

## 1. Candidate rules (pre-named; one will be recommended)
- **R-eff cap**: k same-direction positions with pairwise 60d corr ≥ ρ₀ count as 1 + λ̂·(k−1)
  effective positions against the risk budget (λ̂ from this study's own joint-stop measurement).
- **Corr gate**: warn/block adding a same-direction position when its 60d corr with any open one ≥ ρ₀
  (ρ₀ scanned over a pre-named grid {0.3, 0.4, 0.5}; chosen by the cost/benefit table, stated).
- **Beta budget**: cap the portfolio's net |Σ side·β_BTC·risk| at B₀ × single-position risk
  (B₀ grid {1.5, 2, 3}).

## 2. Pricing machinery
Sample same-direction SETS (pairs and triples) of simultaneous positions from m28-style moments:
same-timestamp entries on different coins, both directions, runner engine, 48h — stratified by the
set's min/mean pairwise 60d correlation. Measure per set: joint-stop frequency (all members stop
within the hold), portfolio outcome in R (sum of members), and tail metrics (P(set ≤ −1.5R), ≤ −2.5R).
Unit = set-chains (overlapping-window dedupe as in M14/M16); controls: per-set K-draw martingale
continuations sharing the moment (the M28 shared-path discipline per coin; ACROSS coins the real
correlation is the object — the control's cross-coin independence IS the independence benchmark, which
makes the joint-stop excess directly measurable per set: real joint-stop rate vs control joint-stop
rate).
Each rule is then run over the sampled sets: which sets it would have blocked/downsized; benefit =
reduction in tail events among allowed sets; cost = forgone sets that did NOT jointly stop (and their
foregone outcome distribution — which, per M13–M16, should be ≈ 0 in expectation: the cost is breadth,
not expectancy; pre-stated).

## 3. Verdict structure
The deliverable is a COST/BENEFIT TABLE per rule × parameter, with the recommendation chosen by a
pre-stated criterion: the rule minimizing tail probability per unit of blocked-breadth at the desk's
actual scale (2–3 concurrent positions — the rule's stated domain; cells beyond k=3 are EXTRAPOLATED).
λ̂ re-measured here must be CONSISTENT with M7's [1.538, 1.737] — a λ̂ outside it is a red flag on this
machinery, not a new finding (M7 is the confirmatory anchor). Uncertainty: set-chain + coin×week
bootstrap, widest acts; n as sets/chains everywhere; no direction language anywhere.

## 4. Panel questions
(a) Joint-stop measurement on overlapping windows and shared coins across sets — the dedupe/clustering
spec; (b) the control-as-independence-benchmark claim: per-coin shared-path martingales are independent
ACROSS coins — verify that makes the real-vs-control joint-stop ratio a clean λ estimator and what
biases remain (shared calendar vol regimes are IN the real sets and NOT in the controls — is that the
measurand or a confound; M7 solved this with within-regime marginals — must M18 condition the controls
on regime too?); (c) rule-gaming: a cap binding only in cascades also binds in the best breadth
regimes — measure the overlap; (d) MEASURE with DB access: how many same-direction correlated sets the
grid yields per correlation stratum, expected MDEs on tail probabilities (binomial), and whether
triples have any power at all; DEFER per-cell where they don't.
