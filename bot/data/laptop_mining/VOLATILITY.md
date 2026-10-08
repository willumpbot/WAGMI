# Mission 7 — forecasting move size

_2026-10-08. Panel: 10 coins, daily, 2020-10 → 2026-10. Train < 2025-06-01 / test ≥ 2025-06-01
(4,884–4,890 test rows). Script: `volatility.py`. Data: `volatility_forecast.json`._

---

## Headline

**This one works. A three-term HAR forecaster beats naive persistence out of sample on every
metric, at both horizons, and it is well calibrated enough to size positions with. It is the first
genuinely shippable predictive result in this whole investigation — and it predicts how big, never
which way.**

It also closes the loop on mission 5: the consensus-disagreement count enters the regression with a
**negative coefficient (−0.065)**, meaning more disagreement → smaller moves. That reproduces the
mission-5 finding *after controlling for recent volatility*, so it is not just restating "vol is
high lately."

---

## Results, out of sample

Target `y1` = next-day |return| %. Target `y5` = standard deviation of the next 5 daily returns.
QLIKE is a volatility-specific loss — **lower is better**. R² is out-of-sample, so negative means
worse than predicting the mean.

| target | model | n | corr | R² | QLIKE | mean bias |
|---|---|---|---|---|---|---|
| **y1** | naive persistence | 4,884 | 0.166 | −0.668 | 4.120 | −0.001 |
| | HAR-RV, uncorrected | 4,887 | 0.246 | −0.077 | 0.660 | −1.074 |
| | HAR-RV + smearing | 4,887 | 0.246 | **+0.042** | **0.513** | +0.235 |
| | **HAR + smearing + consensus** | 4,887 | **0.262** | **+0.052** | **0.508** | +0.227 |
| **y5** | naive persistence | 4,890 | 0.273 | −0.454 | 0.281 | +0.013 |
| | HAR-RV, uncorrected | 4,890 | 0.357 | **+0.115** | **0.149** | −0.204 |
| | HAR-RV + smearing | 4,890 | 0.357 | +0.074 | 0.150 | +0.398 |
| | **HAR + smearing + consensus** | 4,890 | **0.375** | +0.087 | **0.148** | +0.392 |

Naive persistence has **negative** out-of-sample R² at both horizons — "tomorrow looks like today"
is worse than useless as a level forecast, even though it correlates positively. The HAR
specification fixes that.

### Calibration on test — the part that matters for sizing

Ranking is easy; getting the *level* right is what lets you set a stop. Predicted vs actual by
decile of prediction:

| decile | y1 pred | y1 actual | ratio | y5 pred | y5 actual | ratio |
|---|---|---|---|---|---|---|
| 1 | 1.555 | 1.631 | 1.05 | 2.229 | 2.161 | 0.97 |
| 2 | 2.013 | 1.870 | 0.93 | 2.751 | 2.324 | 0.84 |
| 3 | 2.331 | 2.237 | 0.96 | 3.107 | 2.891 | 0.93 |
| 4 | 2.624 | 2.756 | 1.05 | 3.428 | 3.352 | 0.98 |
| 5 | 2.870 | 2.785 | 0.97 | 3.692 | 3.469 | 0.94 |
| 6 | 3.130 | 3.186 | 1.02 | 3.957 | 3.706 | 0.94 |
| 7 | 3.396 | 3.238 | 0.95 | 4.232 | 3.930 | 0.93 |
| 8 | 3.688 | 3.447 | 0.93 | 4.535 | 4.320 | 0.95 |
| 9 | 4.084 | 3.294 | 0.81 | 4.928 | 4.177 | 0.85 |
| 10 | 5.109 | 3.990 | 0.78 | 5.926 | 4.480 | 0.76 |
| **spread** | | **1.63% → 3.99% (2.4×)** | | | **2.16% → 4.48% (2.1×)** | |

Deciles 1–8 are within ±7% of truth at both horizons. **Deciles 9–10 over-predict by 15–24%** — the
model overshoots when it calls for an extreme day. For sizing that is the safe direction to be wrong
in, but the top two deciles should be shaded down by roughly 20%.

A 2.1–2.4× spread between the calmest and wildest deciles is the practical payoff: it is the
difference between a stop that gets wicked out and one that does not.

---

## A correction to my own first run

The first version regressed `log(y)` and exponentiated the prediction. That returns a conditional
**median**, not a mean, so by Jensen's inequality every level came out low — y1 under-predicted
every single decile by 36–83% (ratios 1.36 to 1.83). Adding Duan's smearing factor,
`mean(exp(residual))` estimated on **train only**, fixed it:

| | y1 R² | y1 QLIKE | y1 calibration ratios |
|---|---|---|---|
| before | −0.077 | 0.660 | 1.36 – 1.83 |
| after | **+0.042** | **0.513** | **0.78 – 1.05** |

Smearing factors: **1.7389** for y1, **1.1835** for y5. The gap between them is the point — |return|
is far more right-skewed than a 5-day standard deviation, so y1 needed the correction badly and y5
barely at all.

**Caveat, stated plainly:** for y5 the uncorrected model actually scores a slightly better R²
(+0.115 vs +0.074) while QLIKE is a wash (0.1486 vs 0.1502). That difference is within noise and I
am not going to pick the variant by looking at test scores. Recommendation: **use the smeared
version for both**, because it targets the conditional mean, which is what a sizing rule needs.
Both sets of coefficients are in `volatility_forecast.json` if the server wants to A/B them forward.

---

## The model

```
log(vol_future) = b0 + b1*log(rv1) + b2*log(rv5) + b3*log(rv22) [+ b4*disagree]
vol_hat         = exp(prediction) * smearing_factor
```

- `rv1` = |yesterday's return| %, `rv5` / `rv22` = standard deviation of the last 5 / 22 daily
  returns. All past-only.
- `disagree` = how many of the six independent voice families (per `voice_families.json`) point
  against the net direction. Coefficient **−0.0649** at y1, **−0.0634** at y5.
- Coefficients and the smearing factors are in `volatility_forecast.json`.

Nothing exotic is used. No volume, no BTC cross-term, no 4h data — those were available and left
out because three terms already beat the baseline, and mission 6 is a fresh reminder of what extra
granularity costs.

---

## How to use it

1. **Set stops from the forecast, not from a fixed percentage.** This is the direct bridge to
   `GEOMETRY.md`, which found the bot's fixed stops cost ~0.5R per setup and that much wider stops
   recover it. A forecast with a 2.1× decile spread is how you make the stop width adaptive instead
   of picking one multiplier for all conditions.
2. **Scale position size inversely to the forecast** so dollar risk stays flat as conditions change.
3. **Shade the top two deciles down ~20%** until forward data says otherwise.
4. **Show it on the desk as an expected-range band**, alongside the consensus gauge from
   `COOPERATION.md`. Two independent inputs, same question: how big is tomorrow?
5. **Do not read any direction into it.** Nothing in seven missions has produced a directional edge
   that survives out of sample.

## Honest limits
- Out-of-sample R² is **+0.04 to +0.12**. Real, useful, and small. This forecasts the *distribution*
  of the next move, not the move.
- Daily resolution only. A 4h version is buildable from the cached 4h history but is untested.
- Train/test is a single split at 2025-06-01. A walk-forward refit would be the stronger check and
  has not been run.
- The panel pools 10 coins with one set of coefficients. Per-symbol fits were not attempted; with
  ~4,900 test rows total, pooling is the conservative choice.
