# Audit of Mission 9 (`SAFE_LEVERAGE.md`) — the direction holds. ⚠️ The p99 column is a sample maximum, and it is biased in the unsafe direction.

_2026-10-11. First review this doc has ever had. Written because it is the only never-reviewed document
carrying a **live recommendation** ("cut leverage roughly in half when the forecast is hot")._

---

## 🔴 Three results

1. **"Leverage should be lower when volatility is hot" is solid.** Keep it.
2. **⚠️ Every `p99` cell rests on `n_train = 68`, where the empirical p99 *is the sample maximum*.** Its
   own 95% sampling range spans a factor of **2.1–3.3×**.
3. **⚠️ And the estimator is biased LOW, which makes the leverage caps biased HIGH.** For a risk table
   that is the wrong direction to be wrong. **Use the `p95` column instead** — the doc's own
   out-of-sample check validates it almost exactly.

## Why a p99 at n=68 is not a p99

The quantile's position depends only on `n`, so this needs no refit:

| n | where the p99 falls | what it actually is |
|---|---|---|
| **68** (the train cells) | order statistic **67.3 of 68** | **the sample maximum** |
| 181 (test cells) | 179.2 of 181 | the 3rd largest |
| 500 | 495.0 | the 6th largest |
| 2,000 | 1,980.0 | the 21st largest |

By contrast **`p95` at n=68 is the 4th largest** — noisy, but a real order statistic rather than the
extreme.

## How much noise, and what it does to the recommendation

Simulated by calibrating three tail shapes so each has a **true** p99 of 11.73% (BTC Q5's reported
figure), then drawing n=68 four thousand times. This measures the **estimator**, not the data.

| tail shape | p99 estimate, median | 95% range | spread |
|---|---|---|---|
| lognormal, mild | **10.44%** | [7.53%, 15.58%] | **2.1×** |
| lognormal, fat | **9.75%** | [5.86%, 19.48%] | **3.3×** |
| Pareto α=3 | 9.77% | [6.30%, 20.82%] | 3.3× |

Carried through to the number the table actually reports:

| | implied max leverage, 95% range |
|---|---|
| **reported for BTC Q5** | **7.7×** |
| mild tail | **[5.8×, 12.0×]** |
| fat tail | **[4.9×, 15.2×]** |

**"17× when calm, 8× when hot" rests on a quantity whose own 95% range is about a factor of two.** The
*ordering* across quintiles and coins is far more reliable than any single level, because it is driven
by the forecast quintile, which has the whole panel behind it.

## 🔴 The bias, which is the part I would act on

In all three simulations the **median estimate (9.75–10.44%) sits below the true 11.73%** — the maximum
of 68 draws systematically **understates** the true 99th percentile, by roughly **11–17%**.

**A p99 that is too small makes the derived "max safe leverage" too large.** The table is therefore
**optimistic about safety**, which for a risk table is the dangerous direction.

**This is not speculation — the doc's own validation already shows it:**

> *"the p95 level built on train covers **94.6%** of test days (claimed 95), and p99 covers **97.7%**
> (claimed 99)"*

**p95 lands almost exactly on target. p99 misses by 1.3 points** — precisely the signature of a sample
maximum standing in for a tail quantile. The doc says "apply a haircut" but does not quantify one; the
simulation puts it at roughly **×1.15 on the adverse move**, i.e. about **13% lower leverage** than the
table states (BTC Q5: 7.7× → ~6.7×).

## 🔧 What to do, cheapest first

1. **Use the `p95` column for the live caps.** It is validated at 94.6% against a claimed 95%, it is a
   real order statistic at n=68, and it needs no correction. This is a one-line change in which key is
   read from `safe_leverage.json`.
2. **If `p99` is wanted, de-bias it by ~×1.15** on the adverse move before deriving leverage, and say
   in the doc that it is a corrected figure.
3. **Fit a tail distribution rather than taking an empirical quantile.** A GPD / peaks-over-threshold
   fit is the standard tool for exactly this situation and would use all 68 points to estimate the tail
   instead of just the largest one. That is the real methodological fix.
4. **Do not simply pool coins to raise n.** The M10 audit measured cross-coin funding correlation at
   **ρ = 0.33**, and adverse excursions cluster harder than funding does — crash days hit everything at
   once. Pooling would inflate the apparent n without adding independent extremes, which is how you get
   a confidently wrong risk number.

## What survives untouched

- **The calm-vs-hot ordering**, which is the headline and the useful part.
- **The alts-are-not-majors point.** ARB's hot-quintile adverse move being ~2.5× BTC's is far too large
  a gap to be an artifact of estimator noise.
- **The HYPE observation** — its calm-day adverse move exceeding BTC's hottest — is a bigger gap than
  the noise band, and it matters given how much of the book sits there.
- **The out-of-sample validation itself.** Running it at all is what made this audit easy, and it is
  more than most of the docs in this folder did.

## Limits of this audit
- **I did not refit the panel.** The noise and bias figures are properties of the estimator at n=68 and
  are therefore simulation-based, calibrated to the doc's own reported quantiles. The exact haircut
  depends on the true tail shape, which is what step 3 above would establish.
- `n_train = 68` is read from `safe_leverage.json`; I checked several cells, all ~67–68. If some cells
  are materially larger, their p99 is correspondingly better behaved.
- Nothing here questions the adverse-excursion measurement itself, only the quantile taken from it.
