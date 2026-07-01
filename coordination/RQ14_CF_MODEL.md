# RQ14 — Counterfactual Skip Model: does anything beat the confidence floors out-of-sample?

**Date:** 2026-07-01 | **Author:** research agent (Q14) | **Status:** evidence only, NO deployment
**Script:** `bot/tools/research/rq14_cf_model.py` (reproduces every number below)
**Data:** `bot/data/llm/counterfactual_resolved.jsonl` — 39,121 resolved skips at run time (prompt said 36,541; file grew, all resolved records used). Labels: `would_hit_tp1` under a ~48-bar resolution window (60% of test records resolve neither TP1 nor SL — label is "TP1 touched first within window").

## Setup (no leakage)
- Split BY TIME on `created_at`: **train < 2026-06-15** (n=5,017; May 30–Jun 10), **test >= 2026-06-15** (n=34,104; Jun 16–Jul 1, 16 days). Data gap Jun 11–15 (blackout) falls exactly on the split.
- Features (all available at skip time): confidence, symbol, side, hour, skip_reason class (confidence_floor / trend_adj_floor / grad_veto / grad_veto_overridden / ma_regime / other), parsed floor level, confidence−floor, regime tag, strategy, RR ratio.
- Baseline = **raw confidence as ranker**. The floors are monotone-in-confidence gates, so confidence rank IS the floor policy's implied ordering.
- Models: logistic regression (one-hot), HistGradientBoosting.

## Headline numbers (test, denominator = 34,104 skips)
| Scorer | AUC (full test) | AUC (deduped, n=5,589) |
|---|---|---|
| Confidence (= floors) | **0.516** | 0.512 |
| Logistic, all features | **0.616** | 0.576 |
| GBM | 0.507 (overfit, worse than nothing) | 0.521 |

- **Killer finding #1: the confidence floors carry ~zero out-of-sample rank signal.** AUC 0.516 ≈ coin flip. TP1 rate by confidence decile on test is NON-monotone: the 46–49 confidence band hits 10.4%, the top decile (64–95) hits 9.0%, bottom decile 4.7%. Confidence weakly separates "terrible" from "average" but the floor levels (55/58/62/66/71) do not order outcomes.
- Base TP1 rate: train **27.8%**, test **6.75%** — a 4x era shift (train era SELL skips hit TP1 54.7%!). Any model calibrated pre-Jun-15 is miscalibrated in level after; only rank comparisons are meaningful.

## Precision at matched volume (deduped test: 1 record per symbol/side/hour/~0.2% entry bucket, n=5,589; base=9.5%)
| Top-k by score (~volume) | Confidence | Logistic |
|---|---|---|
| top-32 (~2/day, the actual target posture) | 21.9% (7/32) | **37.5% (12/32)** |
| top-111 (2%) | 10.8% (12/111) | **18.9% (21/111)** |
| top-279 (5%) | 11.8% | 11.8% (tie) |

- Logistic top-32 vs base: binomial p=2.0e-05. Top-111 vs base: p=3.0e-03. **But logistic vs confidence head-to-head is NOT significant: Fisher p=0.27 (top-32), p=0.13 (top-111).** The difference is 5 hits out of 32.
- Mean `hypothetical_pnl_pct`: logit-top32 **+0.29%**/trade vs conf-top32 **−0.18%** vs all-skips −0.37%. Same sign at top-111 (+0.21% vs −0.70%).

## What drives the logistic edge (adversarial decomposition)
- Top coefficients: regime=trending_bear +1.79, reason=grad_veto −1.45 (the graduated veto's skips almost never hit TP1 — **the veto works**), conf_minus_floor +1.31, regime=trending_bull −1.30, HYPE −1.17, side=BUY −1.11, ETH +0.90.
- NOT just "SELL in a bear era": side+regime-only logit AUC = 0.528; ablating side+regime from the full model keeps AUC at 0.604. The load-bearing feature is **conf_minus_floor** (distance to the floor that fired) plus symbol effects — i.e., a refinement of the floor signal, not a repudiation of gating per se.
- Concentration check: all 32 top picks are SELL; 0/14 hits on BTC+HYPE picks, 12/18 on ETH+SOL. Picks cluster on Jun 17/18/21 (28 of 32 across 3+3 days). Fragility: dropping the single best day (Jun 17) leaves 6/21 = 28.6% vs base 9.5% — survives, but n is tiny.
- Weekly stability: logit AUC W25=0.515, W26=0.639, W27=0.567. Edge is real-looking but lumpy; W25 is chance-level.
- Excl-HYPE AUC 0.633, excl-XRP 0.613 — not carried by one symbol. XRP oddity: 17/4,183 test skips hit TP1 (0.4%) and confidence is INVERTED there (AUC 0.226).

## Verdict
1. **The existing confidence floors do not predict TP1 out-of-sample (AUC 0.516, non-monotone deciles).** They function as volume throttles, not skill filters. This is the valuable answer regardless of the model.
2. A trivially simple logistic (floors-distance + symbol + regime) ranks better (AUC 0.616; 37.5% vs 21.9% TP1 at 2-trades/day volume; positive vs negative hypothetical PnL) — **but the improvement over confidence-rank is not statistically significant at realistic volume (p=0.13–0.27)** and is week-unstable. Under THE_STANDARD's small-n humility, this does NOT graduate.
3. GBM overfits the era shift completely (AUC 0.507) — more capacity is worse here.
4. Week-1 artifact if pursued: re-run `rq14_cf_model.py` weekly as skips accrue; the logit-vs-conf top-k gap either reaches significance in ~2–3 more weeks of data or dies. Cheapest honest next step; no bot changes required.

## Caveats (self-check)
- Label = TP1 touch within ~48 bars, not realized PnL with fees/slippage; 60% of test skips resolve neither.
- Records are heavily cluster-correlated (34k → 5.6k after dedup); all significance quoted on deduped data, but temporal correlation across adjacent hours remains → quoted p-values are still optimistic.
- Train era (n=5,017, 12 days) is one regime (bull-then-chop); test is another. A model this era-sensitive should be retrained on rolling windows before any use.
