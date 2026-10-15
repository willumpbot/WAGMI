# Project X - funding-flip fade lens: funding at the +0.5R bar does NOT cleanly predict fade vs run. Every bucket's CI overlaps the base rate. One mild, UN-confirmed lean (paying carry = fades a touch less); not pursued. The sealed fade rule (surge+velocity) is unchanged.

_2026-10-15. m32d_funding_lens.py. 1,633 scored +0.5R moments / 30 coins (funding_oi_history covers only
31 symbols and starts 2026-06-06, so this is a thin subpopulation; base P(FADE) 0.606 here vs 0.642 on
the full atlas). Exploratory, candidate-only - does NOT touch the sealed M32C_FADE_PREREG composite._

## Result (P(FADE) by funding circumstance at +0.5R; coin-clustered CI; base 0.606)
| circumstance | P(FADE) | vs base |
|---|---|---|
| funding > 0 (longs pay) | 0.616 [0.596,0.634] | overlaps base |
| funding <= 0 (shorts pay) | 0.559 [0.505,0.621] | overlaps base |
| AGAINST position (we pay carry) | 0.578 [0.543,0.614] | mild lean to RUN, not CI-clean |
| WITH position (we receive carry) | 0.640 [0.598,0.678] | mild lean to FADE, not CI-clean |
| fresh funding flip (24h) | 0.691 [0.569,0.825] | n=55, underpowered |
| \|funding\| low / mid / extreme | 0.604 / 0.574 / 0.640 | all overlap base |

## Verdict
Funding adds NO clean fade/run tell on this data. Every bucket's CI includes the base rate. The only
directional hint is AGAINST-carry (we pay) fading a touch LESS (0.578) vs WITH-carry (we receive, i.e.
aligned with the crowd) fading a touch MORE (0.640) - plausible (being on the crowded side correlates
with the move continuing against you) but NOT CI-clean against the base and NOT de-confounded. Not
pursued (multiplicity: this is the 5th+ fade lens; a mild, unconfirmed lean on a 30-coin post-June
subpop does not clear the bar). Noted only as a possible future candidate IF a sealed funding lens is
ever warranted.

## Rule (one line)
Funding doesn't tell you which +0.5R winners give back - the move-quality tells (volume/velocity) do.
(every funding bucket within noise of the 61% base)
