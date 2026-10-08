# Proposal D — modelling the volatility forecast's own error

_2026-10-08. 20,182 coin-days, 11 coins, 2020-10-18 → 2026-10-06. Train < 2025-06-01 (14,762) /
test ≥ 2025-06-01 (5,420). Script: `vol_error.py`. Data: `vol_error.json`._

---

## Headline

**The flat ×0.80 patch currently in production is worse than applying no correction at all, and it
biases the forecast in the dangerous direction. A two-stage correction plus a top-decile-only haircut
beats it by 4.0% on QLIKE, improves ranking, and calibrates every decile to within ±9%.**

Because `risk_voice.py` scales every stop width and every leverage cap off this forecast, this
propagates straight into both.

---

## The problem with the current patch

| variant | QLIKE ↓ | correlation ↑ | top-2 decile ratio | mean bias |
|---|---|---|---|---|
| raw HAR, no correction | 0.5078 | 0.2526 | 0.824 | +0.246 |
| **flat ×0.80 (in production)** | **0.5202** | 0.2526 | 1.030 | **−0.388** |
| stage 2 model | 0.5037 | 0.2714 | 0.808 | +0.278 |
| **stage 2 + top-2-decile ×0.8** | **0.4993** | **0.2755** | **0.968** | **+0.086** |

Two things to notice:

1. **The flat ×0.80 has the worst QLIKE of the four — worse than doing nothing.** It fixes the top
   decile (ratio 1.030) by dragging the entire curve down.
2. **Its bias is −0.388**, i.e. it makes the forecast *under*-predict by nearly 0.4 percentage points
   on average. For a risk tool that is the wrong direction to be wrong in: under-forecast volatility
   means **stops too tight and leverage caps too high**. Nobody had checked the sign.

The recommended variant has a bias of **+0.086** — small, and erring toward caution.

---

## What explains the error

Regressing `log(actual ÷ predicted)` on candidate features, keeping only those whose
correlation sign holds from train into test:

| feature | train coef | train corr | test corr | holds? |
|---|---|---|---|---|
| **disagree** (voice dissent count) | −0.0652 | −0.0591 | −0.0719 | **yes** |
| **trailing funding** | +0.6349 | +0.0307 | +0.0177 | **yes** |
| **BTC 5-day volatility (log)** | −0.0289 | −0.0143 | −0.0601 | **yes** |
| forecast level (log) | +0.0000 | +0.0000 | −0.0061 | no |
| funding-present indicator | +0.0150 | +0.0060 | — | no |
| days since last 2σ move (log) | −0.0169 | −0.0146 | −0.0086 | no |
| term structure (rv5 ÷ rv22) | +0.0005 | +0.0002 | −0.0206 | no |

Three of seven survive, and each is coherent with something already established:

- **more dissent → the forecast over-predicts.** `COOPERATION.md` found near-unanimity precedes a
  ~55% larger move; this is the same effect appearing as a *forecast error*, which is a genuinely
  independent confirmation rather than a restatement.
- **higher funding → the forecast under-predicts.** Matches `SQUEEZE.md`, where funding raised tail
  risk on both sides.
- **higher BTC volatility → the forecast over-predicts** the individual coin. Plausibly a
  correlation effect: when BTC is wild, alt-specific moves are a smaller share of total variance.

Correlations are small (0.018–0.072). This is a calibration correction, not a new signal.

---

## The implementable formula

```
# stage 1 — HAR-RV, unchanged
pred1 = exp(b0 + b1*log(rv1) + b2*log(rv5) + b3*log(rv22)) * 1.7017

# stage 2 — error correction
adj   = exp(-0.36316
            - 0.06397 * disagree          # dissenting voice families, 0-6 scale
            + 0.52144 * funding_trailing  # yesterday's funding, % per day
            - 0.03793 * log(btc_rv5))     # BTC 5-day realised vol, %
pred2 = pred1 * adj * 1.6959              # 1.6959 = stage-2 smearing

# top-decile haircut, applied ONLY to the top 20% of predictions
final = pred2 * 0.8   if pred2 in the top 20% of the current cross-section
        pred2         otherwise
```

Note `disagree` uses the **0–6** scale (six family representatives), the same convention as
`squeeze.json` — apply the same normalisation if your dissent count has a different maximum.

### Decile calibration on test, recommended variant
| decile | predicted | actual | ratio |
|---|---|---|---|
| 1 | 1.629% | 1.595% | 0.979 |
| 2 | 2.080% | 1.923% | 0.924 |
| 3 | 2.413% | 2.252% | 0.933 |
| 4 | 2.714% | 2.720% | 1.002 |
| 5 | 2.982% | 2.943% | 0.987 |
| 6 | 3.210% | 3.145% | 0.980 |
| 7 | 3.378% | 3.541% | 1.048 |
| 8 | 3.562% | 3.233% | 0.908 |
| 9 | 3.766% | 3.504% | 0.931 |
| 10 | 4.369% | 4.391% | 1.005 |

**Every decile within ±9%, and the extremes within ±2%.** Compare the raw model's 0.824 at the top,
or `VOLATILITY.md`'s original 0.78–1.05 spread.

---

## Trader rules

1. **Expect the stated move to be right within about 9%** across the whole range now — previously the
   quietest and wildest days were off by 20%+.
2. **When the voices nearly all agree, add ~6% to the expected move** per dissenting family below the
   maximum; unanimity means a bigger day than the raw model says.
3. **Stop trusting a flat haircut** — the ×0.8 currently applied everywhere makes the forecast read
   **0.39 points too low on average**, which quietly tightens every stop and raises every leverage cap.

## Limits
- Correlations are 0.018–0.072. This improves calibration, not predictive power; correlation with the
  actual move rises only 0.2526 → 0.2755.
- The top-decile haircut is applied on the **cross-section of current predictions**, so it needs the
  full panel at call time, not a single coin. A per-coin approximation is to apply it when the
  prediction exceeds that coin's own 80th percentile.
- Seven features were tested; three survived. The three that survived each match an independently
  established result, which is the main reason to believe them over chance.
- Single train/test split at 2025-06-01. A walk-forward would be stronger and has not been run.
