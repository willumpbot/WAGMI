# Addendum to `PREREG_OI_2026-10-11`: the assumed SD was wrong, and the prereg is **better** powered than it claimed

_2026-10-11. Measured on `history1h/` — 169 coins, 31,002 coin-days, 187 days with ≥30 coins._

## Why this addendum is legitimate and does not break the seal

`PREREG_OI` §8 states: *"SD of `y` is taken as **0.40** from the `funding_hot` work."* A swarm audit
then found that **0.40 is not derivable from any artifact in the repo** — `size_flags.json` gives a
*weekly* block SD of 0.272, and the audit could only bound the day-block SD to **[0.27, 0.72]**,
warning that at the upper end the 2027-05 final look would be powered for ~14% against the effect it
was sized to detect.

**SD(`y`) is a nuisance parameter, not the test statistic.** It appears only in the MDE, which is
descriptive. **Nothing in the decision rule changes:** the interim is still at `n_days ≥ 106` at
α = 0.005, the final at 212, the predictor, horizon and clustering are untouched, and no outcome has
been looked at. Refining a power calculation with better information is permitted precisely because
it cannot move the bar the test must clear.

## What was measured

`y = log(realised_move / HAR forecast)`, with `realised_move = (high − low) / open` per coin-day
built from the hourly panel, and a HAR(1, 5, 22) forecast using the **same fixed betas
(0.35 / 0.35 / 0.30)** that `funding_stop.py` hardcodes.

| quantity | value |
|---|---|
| SD of `y` per **coin-day** | **0.475** |
| **SD of the day MEAN of `y`** | **0.245** |
| implied design effect | **44.3** |
| mean coins per day | 166 |

**The design effect is the interesting number.** If coins were independent, averaging 166 of them
would give a day-mean SD of **0.037**. The measured 0.245 is **6.6× larger**, i.e. a design effect of
44 — these coins move together, so a day with 166 coins is worth roughly **4 independent
observations**, not 166. That is the same clustering fact that has governed every result in this
project, measured here directly.

## Consequence: the schedule is comfortably reachable

| n_days | MDE at the assumed 0.40 | **MDE at the measured 0.245** |
|---|---|---|
| **106** (pre-committed interim) | 10.9% | **6.7%** |
| **212** (final) | 7.7% | **4.7%** |
| 365 | 5.9% | 3.6% |

**And the abandonment criterion becomes achievable.** §9.5 says H1 is abandoned on *"a null at
n_days = 212 with the CI inside ±5%"*. The audit estimated that needed **≈800 day-blocks ≈ 2.2
years**. At the measured SD it needs **≈188 day-blocks ≈ 0.5 years** — so the criterion is
satisfiable at roughly the n the prereg already committed to, rather than being unreachable.

## 🔴 Limits, because this is an estimate standing in for the server's number

- **This is not the server's forecast.** `har_move_pct` comes from `volforecast`, which is
  *trained*; mine is fixed-beta HAR. A better forecast leaves a **smaller** residual, so **0.245 is
  most likely an upper bound** on the true SD — the prereg is, if anything, better powered still.
  But it is not the same quantity, and the number should be re-derived from `har_move_pct` once
  enough of it is archived.
- **166 coins/day is the panel's width, not necessarily the test's.** If the OI test runs on a
  narrower universe, its day-mean SD will be larger than 0.245 and the MDEs above are optimistic.
  The design effect of 44 means the penalty for narrowing is much smaller than `1/√n` would suggest,
  but it is not zero.
- **187 days, one regime.** The SD of a volatility ratio is itself regime-dependent.

**Net:** the direction of the correction is firm — the prereg under-estimated its own power — while
the exact figure should be replaced by one computed from the server's own forecast when it exists.
