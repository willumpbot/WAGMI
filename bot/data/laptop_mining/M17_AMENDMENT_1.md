# M17 AMENDMENT 1 - panel (measured): the percentile scheme collapsed under clamping and is replaced; the key choice gets a real decision rule; ACF is demoted. Adopted before any code.

Measured foundations: median clamp share 59.9% across 178 coins (127 >50%, 34 >75%); 61.3% of trailing
windows have p50==p90 (8.4% fully flat); the same baseline print classifies anywhere from p0.01 to
p0.93 by tie rule. Key-choice R2s differ by coin (entry print wins VVV 0.35 vs 0.26; trailing-24h mean
wins HYPE 0.29 vs 0.14; both fail HMSTR). BTC/ETH's >p90 bucket spans only 26/9 distinct days.
median-sf drift >25% on 42/174 coins. Mid-hold sign flips occur in 54-76% of 48h holds yet carry
scales ~linearly (1.89-1.97x for 48/24) because flips average around the decaying mean.

1. STATE SPACE replaces raw percentiles: explicit AT-BASELINE state (rate == venue modal; share
   printed per coin) + below-baseline + off-baseline percentile buckets computed over OFF-BASELINE
   hours only, trailing 90d, midrank ties, no bucket before 90d of own history (warmup hours excluded
   everywhere; never-bucketable coins listed with NO CELLS).
2. KEY DECISION RULE pre-registered: per liquidity TIER (top-20 / next-60 / rest by trailing-90d
   median dollar volume), entry print vs trailing-24h mean chosen by out-of-sample R2 (fit first half,
   evaluate second half); difference <0.05 defaults to trailing-24h mean; winning OOS R2 < 0.10 ->
   that tier ships "carry real but NOT FORECASTABLE at entry" instead of a flip table. Half-life plays
   NO role in any decision.
3. PERSISTENCE = state-transition matrices (24/48h) + time-in-state survival. ACF printed only as a
   diagnostic, always raw-AND-clamp-excluded side by side with the clamp share, never used in a rule.
4. ONE 48h atlas/flip table; 24h/72h replaced by a measured per-tier scaling line. The design's
   mid-hold-flip mechanism sentence is corrected (flips are common AND scaling stays linear).
5. COVERAGE fallback: an extreme bucket under 30 distinct days takes the tier-pooled cell with a
   POOLED flag and the coin's own n printed; buckets are never widened per coin.
6. R DENOMINATOR: trailing-90d median sf stamped at publication; DRIFT flag where half-sample medians
   differ >25%; the live snapshot recomputes against the HARSHER (smaller-sf) of trailing-90d and
   full-sample so a veto threshold never loosens from drift.
7. LANGUAGE (verbatim rules): carry-FOR cells exist only to show magnitude symmetry - no threshold,
   fee-comparison, or earns/pays-you language on them, ever; the live snapshot prints ONLY
   against-side cost for coins with a CURRENT OPEN PLAN (never a panel-wide screen of threshold
   crossers); forbidden sentence forms: "shorts/longs win here", "paid to hold", "carry favors
   entering", any cell cited as expected income. Quotable cells pre-stated: flip thresholds and
   per-tier medians only; anything else requires the full table attached.
8. Flip threshold family pre-stated: {1 fee = 9 bps, 2 fees = 18 bps, 0.10 R(trailing-90d sf)}.
