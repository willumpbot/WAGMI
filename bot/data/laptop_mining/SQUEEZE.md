# Squeeze predictor — forecasting the tail, not the direction

_2026-10-08. 27,170 coin-days, 17 coins, 2020-09-10 → 2026-10-06. Train < 2025-06-01 / test after.
Script: `squeeze.py`. Data: `squeeze.json`._

---

## Headline

**A leveraged trader is killed by tails, not averages — and the tail is modestly forecastable. The
best model lifts the top decile's squeeze rate to 20.1% against a 12.0% base rate on the short side,
and it is well calibrated. The useful ingredient is not the volatility forecast and not funding: it
is how much the voices agree.**

Definition used throughout: a **squeeze** is an adverse move larger than **2× the forecast move**
within one day. Scaling the threshold by each coin's own forecast makes it mean the same thing for
BTC and for a meme.

---

## Results, out of sample

### Short side (base rate 12.0% on test)
| features | test AUC | top-decile rate | calibration slope |
|---|---|---|---|
| forecast only | 0.5071 | 12.1% | 0.68 |
| + funding | 0.5073 | 13.5% | 0.16 |
| **+ consensus** | **0.5590** | **20.1%** | **1.06** |
| all three | 0.5533 | 19.5% | 1.00 |

### Long side (base rate 8.3% on test)
| features | test AUC | top-decile rate | calibration slope |
|---|---|---|---|
| forecast only | 0.5748 | 10.0% | 1.13 |
| + funding | 0.5804 | 10.8% | 1.05 |
| **+ consensus** | **0.6068** | **15.0%** | **1.04** |
| all three | 0.6046 | 15.3% | 1.03 |

**Lift over base: 1.68× (short), 1.81× (long).** AUC in the 0.56–0.61 range is modest and honest —
this ranks risk, it does not call the future.

### Calibration on test — the part that makes it usable
A probability is only useful if 20% means 20%.

| decile | short predicted | short actual | long predicted | long actual |
|---|---|---|---|---|
| 1 | 8.1% | 8.8% | 7.0% | 5.6% |
| 2 | 9.2% | 11.1% | 8.3% | 6.4% |
| 3 | 10.0% | 11.2% | 9.1% | 5.2% |
| 5 | 11.2% | 11.9% | 10.5% | 5.5% |
| 8 | 12.8% | 12.7% | 12.7% | 11.1% |
| 10 | **17.0%** | **20.1%** | **16.7%** | **15.0%** |

Short-side calibration is good throughout (slope 1.06). Long-side is well-ranked but
**over-predicts in the middle deciles** — predicted 9–10%, actual 5–6%. Use the long-side model for
ranking, and the short-side model for absolute probabilities.

---

## What the coefficients say — two independent confirmations

`all three` model, coefficient signs:

| | intercept | log forecast | trailing funding | disagree |
|---|---|---|---|---|
| long | −0.983 | −0.517 | **+1.530** | **−0.203** |
| short | −1.350 | −0.129 | **+1.300** | **−0.213** |

1. **Higher funding → more squeeze risk, on both sides** (+1.53 / +1.30). This independently
   reproduces the tail finding in `FUNDING_CARRY.md` (p99 adverse 21.6% → 29.0% in high-funding
   regimes), now in a regression that controls for the volatility forecast.
2. **More agreement → more squeeze risk** (negative on `disagree`, i.e. fewer dissenters means
   higher probability). That reproduces `COOPERATION.md`'s magnitude finding and sharpens it: the
   consensus gauge does not merely predict a bigger *average* move, it predicts a fatter *tail*.

The negative coefficient on the forecast is not a contradiction — the threshold is itself 2× the
forecast, so a higher forecast raises the bar proportionally. It is a scaling artefact of the target
definition, not a claim that calm days are more dangerous.

**Honest note on funding:** its sign is meaningful and consistent, but its *incremental* predictive
value is nil — AUC moves 0.5071 → 0.5073 on the short side, and adding it on top of consensus makes
things slightly worse (0.5590 → 0.5533). Funding confirms the story; it does not improve the model.
It is also missing on 43% of rows, since Hyperliquid funding history only reaches 2023–24.

---

## How to use it

1. **Read it as a position-size dial, not a signal.** Top decile means roughly 1.7× the usual chance
   of a violent move against you. Halve size rather than skipping the trade.
2. **Pair it with `SAFE_LEVERAGE.md`.** That table gives the p99 adverse move for a volatility
   bucket; this gives the probability that *today* is worse than usual within that bucket. Together:
   how far it can go, and how likely a bad day is.
3. **Watch the short side when the book is unanimous and funding is high.** Both coefficients push
   the same way, and `FUNDING_CARRY.md` showed p99 adverse reaching 29% in exactly that regime —
   which liquidates anything above ~3.3x.
4. **Do not read direction into it.** It is symmetric by construction; both sides are modelled.

## Limits
- AUC 0.56–0.61. Real, modest, and not a substitute for sizing discipline.
- Long-side probabilities over-predict in the middle deciles; use that model for ranking only.
- Funding covers 57% of rows; the model falls back on a zero plus an indicator when it is missing.
- Threshold of 2× the forecast is a choice. A different multiple would shift the base rate, though
  the ranking should be stable.
- Logistic regression with four features, Newton-fitted, no regularisation beyond a 1e-6 ridge. It is
  deliberately simple — nothing in this project has rewarded complexity.
