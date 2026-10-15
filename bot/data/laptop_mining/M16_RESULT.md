# M16 - limit plan vs market plan: NULL at every tested distance. The limit's better fills and its missed winners cancel; no adverse-selection case, and no reason to change how the owner enters.

_2026-10-16. m16_run.py to M16_AMENDMENT_1 (162069a7). EXPLORATORY, HYPOTHESIS cap. 8,713 moments
(both sides), paired pooled-side cells, common sf0 denominator, W=24h frozen. Null gate passed
(|z|<=1.44); positive control passed (fill-weighted linearity exact; detection at 1.5x own MDE).
Per-cell MDE ~0.021 R - a real measurement, not a screen._

## The read (ITT, fully control-subtracted; family z>=3.0)

| d (ATR) | ITT L-M | 95% CI | z | fill p (real vs ctrl) | fill-term* | miss-term* |
|---|---|---|---|---|---|---|
| 0.25 | +0.032 | [-0.004, +0.073] | +1.62 | 0.66 / 0.68 | +0.206 | -0.173 |
| 0.50 | +0.028 | [-0.004, +0.064] | +1.62 | 0.38 / 0.43 | +0.241 | -0.203 |
| 0.75 | +0.024 | [-0.006, +0.053] | +1.59 | 0.20 / 0.26 | +0.190 | -0.152 |
| 1.00 (descriptive) | +0.016 | [-0.011, +0.042] | +1.20 | 0.11 / 0.15 | +0.120 | -0.087 |

*Decomposition terms are RAW (real-path) per the amendment's discipline: descriptive, no causal
language - the fill stratum is post-treatment. The ITT row is the controlled claim.

## What it means
- NO family cell clears z>=3; the consistent +0.02-0.03 lean is 1.5x the MDE's SE but not a verdict.
  The pre-feared "adverse selection" signature (negative, worsening in d) DID NOT APPEAR - the sign
  leans the other way.
- The decomposition shows why the net is small: on moments where the limit fills, the limit plan beat
  the market plan by ~0.2 R (bought the dip the market plan absorbed as drawdown); on moments it
  missed, the market plan's winners cost the limit ~0.17-0.20 R of opportunity. Near-perfect cancel.
- Real fill rates sit 2-6pp BELOW control at every d (real paths trend more than martingale
  continuations) - the fee*(1-p) mechanical term and this gap are both inside the stated bounds.
- For the owner: his limit-at-a-level habit costs nothing measurable vs entering at market, at any
  distance up to 1 ATR, down to ~2% of risk sensitivity. Keep whichever suits the plan; neither is
  an edge, neither is a leak.

## Limits
Maker-fee conservatism (engine charges taker on the limit leg - reality slightly favors limits beyond
what is shown); sim fills at levels (carried); one 212d regime; fill-stratum terms unbenchmarked
against the control's own fill-conditioned contrast in this print (the ITT scalar is fully
benchmarked; the stratum lines are labeled raw); W sensitivity not run (frozen window).
