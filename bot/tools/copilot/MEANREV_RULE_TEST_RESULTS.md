# 3-Day Mean-Reversion RULE Test — Results

**Run date:** 2026-08-05. Script: `tools/copilot/meanrev_rule_test.py` (read-only,
no Discord, no live/paper state touched). Engine: `tools/copilot/confluence_harness.py`
(the verified OOS/FDR/liquidity-cost/dedup machinery — unmodified). Raw dump:
`tools/copilot/meanrev_rule_test_output.json`.

**Origin:** `MEANREV_STRUCTURE_RESULTS.md` found that 72% of alts show negative
3-day return autocorrelation in both eras, and that reversion *amplitude*
clears realistic cost at the 3d horizon. This is a test of whether that
population-level statistical property converts into an actual TRADEABLE RULE:
buy after an N-day drop, hold N days, unlevered, net of realistic per-liquidity
cost.

## 1. The rule and the grid

For coin X on day t: if trailing N-day return `c[t]/c[t-N]-1 <= threshold`, buy
at t's close, hold exactly N days, sell at t+N's close. Unlevered 1x. Swept:

- N ∈ {2, 3, 5}
- threshold ∈ {-5%, -10%, -15%} (fixed) plus a **percentile** version: the
  coin's own trailing (expanding, entry-time-safe, `.shift(1)`) 10th-percentile
  of its N-day-return distribution
- Each of the 12 base specs also broken into pooled + thin/mid/liquid
  liquidity buckets (confluence_harness's built-in `with_liquidity_buckets=True`)
  → **47 FDR-family entries** with a computable p-value (out of 48 possible;
  N=2/thin/15% has only 4 raw obs, no p-value computed — correctly excluded,
  not silently dropped)
- `dedup_gap_days=N` per spec — consecutive triggers within the hold window
  collapse to ONE episode (a coin sitting under threshold for several days
  can't manufacture several overlapping "trades" out of one drawdown)
- Universe: 25 longtail alts (13mo) + BTC/SOL/ETH/HYPE/XRP (stale, ends
  2026-07-13, ~208d) — 30 symbols, same corpus as the structure study
- Cost: per-triggering-bar liquidity bucket (12.5/32.5/75bps RT), same as
  every other confluence-harness test
- BH-FDR alpha=0.05 across all 47 entries; perm_iters=5000 (resolves finer
  than this family's strictest critical value 0.05/47≈0.00106, no coarseness
  warning)

**Engine bug found and worked around (disclosed, not silent):**
`confluence_harness.compute_price_indicators()` only precomputes
`fwd_raw_{1,3,5,10}` — N=2 has no forward-return column, and without a fix
every N=2 spec silently reports n=0 (confirmed: the entry condition itself
fires ~76/399 bars on AAVE alone; the mask is fine, the join to forward
returns was the hole). Fixed in `meanrev_rule_test.py` by attaching
`fwd_raw_2` externally using the identical formula (`c.shift(-2)/c-1`) —
same pattern `confluence_campaign_run.py` already uses for its own proxy
columns, not an edit to the verified engine file itself.

## 2. Headline (pooled entries)

| test_id | h | train n | train p | train net | test n | test p | test net | FDR | CONFIRMED |
|---|---|---|---|---|---|---|---|---|---|
| drop2d_fixed5pct | 2 | 941 | 0.63 | −0.24% | 308 | 0.11 | +0.26% | . | . |
| **drop2d_fixed10pct** | 2 | 343 | 0.0004 | +1.03% | 85 | **0.053** | **+1.26%** | Y | . (test p misses by 0.003) |
| drop2d_fixed15pct | 2 | 119 | 0.0002 | +4.39% | 28 | 0.34 | +0.93% | Y | . |
| drop2d_pctile10 | 2 | 323 | 0.14 | +0.51% | 148 | 0.64 | −0.01% | . | . |
| drop3d_fixed5pct | 3 | 836 | 0.98 | −0.47% | 289 | 0.88 | −0.60% | . | . |
| drop3d_fixed10pct | 3 | 401 | 0.0006 | +1.24% | 109 | 0.49 | −0.86% | Y | . (sign flip) |
| drop3d_fixed15pct | 3 | 175 | 0.0002 | +4.93% | 38 | 0.42 | +0.56% | Y | . |
| drop3d_pctile10 | 3 | 264 | 0.0002 | +1.82% | 123 | 0.16 | −1.65% | Y | . (sign flip) |
| drop5d_fixed5pct | 5 | 651 | 0.0002 | **−2.08%** | 227 | 0.70 | −0.68% | Y | . (confirmed-negative, not an edge) |
| drop5d_fixed10pct | 5 | 410 | 0.21 | −1.56% | 115 | 0.60 | −1.41% | . | . |
| drop5d_fixed15pct | 5 | 217 | 0.15 | −1.86% | 59 | 0.61 | −0.14% | . | . |
| drop5d_pctile10 | 5 | 202 | 0.40 | −1.52% | 82 | 0.53 | −1.84% | . | . |

**FDR family n_tested=47, expected false positives at raw p<0.05 = 2.35.
Train-fold BH-FDR survivors = 19. CONFIRMED (train-FDR AND test p<0.05 AND
same sign AND test n≥20 AND no dominance) = 0.**

The full liquidity-bucket breakdown (36 more entries) is in the JSON dump —
same pattern: several bucket cells clear train FDR, none confirm on test.

## 3. Is any cell even close? (the closest near-miss)

`drop2d_fixed10pct` (buy when 2-day trailing return ≤ −10%, hold 2 days) is
the one cell worth a full look — it is positive in **every** cut, broad-based,
and test p misses the 0.05 bar by only 0.012 (0.062, re-measured with a
dedicated re-run for the deeper diagnostics below):

| split | n | n_symbols | dominance | gross | net | p |
|---|---|---|---|---|---|---|
| full | 428 | 29 | 9% | +1.40% | +1.07% | 0.0024 |
| train | 343 | 29 | 9% | +1.35% | +1.03% | 0.0018 |
| test | 85 | 26 | 11% | +1.57% | **+1.26%** | **0.062** |
| pre-era | 283 | 27 | 9% | +0.74% | +0.42% | 0.153 |
| post-era | 145 | 28 | 10% | +2.67% | +2.34% | 0.0004 |
| train, excl. crash window | 286 | — | — | — | +0.90% | 0.016 |
| test, excl. crash window | 85 | — | — | — | +1.26% | 0.055 |

Refute-yourself checks on this cell:
- **(a) pre-Feb-only?** No — same sign both eras (+0.42% pre, +2.34% post),
  though pre-era alone isn't individually significant (p=0.15, n=283 — this
  is a WEAK-era, not a dead one).
- **(b) single-coin dominance?** No — 9-11% max share, 26-29/30 symbols
  participate every split.
- **(c) clears net cost, not just gross?** Yes — gross +1.40%, net +1.07%,
  cost drag is the expected ~30bps blended, doesn't erase the edge.
- **(d) crash-window dependence?** No — excluding 2026-01-26..02-15 (±10
  days around the -14% BTC day flagged in `corr_stress_test.py`), train net
  actually holds (+0.90%, p=0.016) and test is essentially unchanged
  (+1.26%, p=0.055). Not a single-event artifact.
- **(e) crowding sanity:** post-era net (+2.34%) is LARGER than pre-era
  (+0.42%), i.e. strengthening not decaying — inconsistent with a crowding
  story, but also inconsistent with "real edge should be getting arbitraged
  away," so treat as descriptive, not exculpatory.
- **(f) pseudoreplication:** dedup collapsed 621 raw triggers to 428
  independent episodes (1.45x) — real, not overlapping-window inflation.

**Verdict on this cell: it does NOT clear the pre-registered bar.** Test p=0.053-0.062
is on the wrong side of 0.05 by a small but real margin, and this project's
own standing discipline (`PREREGISTRATION.md`: *"Do not lower the bar to get
a faster answer — an underpowered 'significant' result here is exactly the
overfit-ceiling problem this tool exists to avoid"*) applies here identically.
This is reported as the closest near-miss for transparency, not as a finding.

## 4. Reconciling with the CONFLUENCE campaign's null

`CONFLUENCE_RESULTS.md` tested indicator-THRESHOLD triggers (BB%B, RSI,
support-distance, breakout, confluence combinations) — 0/133 confirmed OOS.
This test used a structurally different trigger (trailing N-day RETURN,
unconditional on any other indicator) precisely because the structure study
flagged that as the one lead that looked different from a bounded oscillator
reading. The result is the same shape anyway: strong, clean-looking train
significance (11 of 12 base specs would individually look like a "discovery"
on train alone — p as low as 0.0002) that does not replicate on the held-out
test fold. This is the textbook train/test-reversal pattern the whole
CONFLUENCE campaign exists to catch, now confirmed on the unconditional-drop
formulation too — the drop threshold isn't a materially different bet than
an oversold-oscillator threshold from the market's point of view, and it
dies the same way OOS.

## 5. Honest bottom line

**Zero (N, threshold) cells clear the full bar** (train-FDR survivor AND
test p<0.05 AND same sign AND test n≥20 AND no dominance AND economically
positive in both folds). The structure study's finding — 72% of alts show
same-sign negative 3d autocorrelation in both eras, and the reversion
*amplitude* clears cost — is **not refuted** by this test (that was a
population-level, in-sample statistical description, not a claim about a
tradeable rule), but it does **not translate into a discrete buy-N-day-drop/
hold-N-days RULE that survives an honest OOS split**. `drop2d_fixed10pct` is
a genuine near-miss (broad-based, cost-clearing, era-consistent, not
crash-dependent) that just misses the pre-registered p<0.05 test-fold bar —
worth remembering if more history accrues, but not pre-registered today,
because the bar exists precisely to prevent shipping a p=0.06 result as a
confirmed finding.

**This is the same verdict category as the deep-oversold trigger that died
Feb-2026 and the CONFLUENCE campaign's 0/133: real, measurable structure in
this market that does not survive being turned into an actual trade.**
Nothing added to `PREREGISTRATION.md` — no cell meets the bar required to
promote a backtest result into a forward-validation hypothesis.
