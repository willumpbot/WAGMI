# CHIEF levels re-test (pre-registered for 2026-10-16, run 10-15 on the ready 260-call sample) - STILL NULL. The chief's named invalidation levels are indistinguishable from random levels at the same distance/side; side-flip ~0 confirms NO edge beyond distance. And the prereg's power assumption was wrong: the binding cluster is the DAY (only ~8), so more calls did NOT buy power - re-run at ~20-30 DISTINCT DAYS, not more calls.

_2026-10-15. chief_levels_retest.py (built by a Fable agent, numbers VERIFIED by me in-code - reproduces
exactly). n_calls=260 (vs 86 at 10-10), 489 levels, 6 symbols, 8 day-clusters. Time-matched null =
reference bars from the local regime (+/-WREG=72 bars) holding distance+side EXACT; side-flip control =
same distance/moment, opposite side; DAY-clustered CI; eqw day-block beside pooled._

## Result (touch rate %, diff = chief - time-matched null, day-clustered 95% CI, MDE=2.8*SD)
| H | n | days | chief | null | diff | CI | MDE | side-flip | verdict |
|---|---|---|---|---|---|---|---|---|---|
| 12h | 489 | 8 | 16.2 | 18.6 | -2.4 | [-10.7,+6.6] | 12.5 | -2.2 | no difference |
| 24h | 447 | 7 | 23.7 | 27.9 | -4.2 | [-14.4,+7.0] | 15.7 | -0.7 | no difference |
| 48h | 366 | 6 | 36.9 | 41.8 | -4.9 | [-17.4,+7.6] | 18.4 | +0.3 | no difference |

Same sign as 10-10 (chief touched slightly LESS), still inside the CI and below the MDE. Side-flip diffs
~0 -> no structural edge beyond the level's distance. Confounded (all-history) null has collapsed to ~0
(vs the biased -6.8/-9.8/-14.3 at 10-10), confirming the 10-10 confounding was specific to that 1.9-day
quiet window.

## The prereg's power assumption was WRONG (methodological finding)
It expected 4x the sample to HALVE the MDE (-> ~3.5). Instead the day-clustered MDE went UP (12.5/15.7/
18.4). The binding cluster is the DAY; day-clustered CIs are driven by BETWEEN-DAY variance, which does
NOT shrink by adding more levels per day. The level count tripled but distinct days only went ~2 -> ~8.
Per the house standard (cluster the ESTIMATE, not just the CI), the day figure governs and the test is
still underpowered to resolve an effect this small.

## Verdict + updated re-test condition
STILL NULL (confirms the M9 extension: KEEP the chief, but its named levels carry no tradeable info).
UPDATE the prereg re-test trigger: re-run at ~20-30 DISTINCT DAYS of chief calls (NOT a call count) -
days are the binding cluster. Until then the chief's levels are "not yet measurable", consistent at both
reads. Chief stays as-is (the real-function grading - risk overlay - still needs the bot action log).
