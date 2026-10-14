# Replications -- OBSERVATIONS ONLY, no verdicts

_Written by `crunch/j3_replications.py` every hour. It recomputes the live scan-flag
definitions and the chief Brier on days the original tests never saw, and appends what
it measures to the `replications` table in `panels.sqlite`. **It never concludes
anything.** There is no verdict column here and there will not be one._

_Do not read this for a verdict before **2026-12-10**, or earlier only to check whether a
metric's MDE has fallen below the in-sample effect it is replicating. Both numbers are
printed below, every run. A replication read before it could have come out the other
way is not a replication._

_Updated 2026-10-14 14:20. 5 out-of-sample day-block(s) evaluated since 2026-10-09._

## What accrued

| asof | metric | n | value | note |
|---|---|---|---|---|
| run | `meta.oos_boundary` | 205 | — | OOS outcome days start 2026-10-09. 205 earlier closed days are WITHHELD as in-sample for the flag tests (all built on history through 2026-10-08) -- counted here so the small n below reads as a deliberate exclusion, not as missing data. |
| run | `meta.panel` | 176 | 356 | 176 coins with >=60 closed 24-bar days; 356 partial days excluded; universe capped at the top 60 by candle USD volume (live caps at the top 60 by ctx.dayNtlVlm -- a stated deviation) |
| run | `meta.em` | — | — | live em = volforecast.forecast(closes), stage 1 + the 0.8 haircut at >= 3.9, exactly as scanner.py calls it |
| run | `meta.oos_days` | 5 | — | evaluated 2026-10-09 .. 2026-10-13; scanned universe 60..60 coins/day; coin-days skipped: gap=0, no_em=0, short_history=0 |
| 2026-10-09 | `scan.squeeze.day.diff_ret_pct` | 0 | — | flag fired on none of the 60 coins scanned on 2026-10-09. A real non-firing: every input was present. |
| 2026-10-10 | `scan.squeeze.day.diff_ret_pct` | 0 | — | flag fired on none of the 60 coins scanned on 2026-10-10. A real non-firing: every input was present. |
| 2026-10-11 | `scan.squeeze.day.diff_ret_pct` | 0 | — | flag fired on none of the 60 coins scanned on 2026-10-11. A real non-firing: every input was present. |
| 2026-10-12 | `scan.squeeze.day.diff_ret_pct` | 0 | — | flag fired on none of the 60 coins scanned on 2026-10-12. A real non-firing: every input was present. |
| 2026-10-13 | `scan.squeeze.day.diff_ret_pct` | 0 | — | flag fired on none of the 60 coins scanned on 2026-10-13. A real non-firing: every input was present. |
| run | `scan.squeeze.cum.blockmean_diff_pct` | 0 | — | no day-block in the OOS window produced a flagged-vs-unflagged comparison, so there is nothing to average. EXACT: closed daily candles + the live em only, no price input |
| 2026-10-09 | `scan.vol_expanding.day.diff_ret_pct` | 1 | -10.5091 | within-day: mean next-day % of the 1 flagged coins minus the 59 unflagged coins scanned the same day (flagged level was -7.4765%). EXACT: rv5/rv22 from closed daily closes only |
| 2026-10-10 | `scan.vol_expanding.day.diff_ret_pct` | 6 | -1.7936 | within-day: mean next-day % of the 6 flagged coins minus the 54 unflagged coins scanned the same day (flagged level was +1.5328%). EXACT: rv5/rv22 from closed daily closes only |
| 2026-10-11 | `scan.vol_expanding.day.diff_ret_pct` | 13 | -0.9875 | within-day: mean next-day % of the 13 flagged coins minus the 47 unflagged coins scanned the same day (flagged level was +3.4964%). EXACT: rv5/rv22 from closed daily closes only |
| 2026-10-12 | `scan.vol_expanding.day.diff_ret_pct` | 13 | -1.4457 | within-day: mean next-day % of the 13 flagged coins minus the 47 unflagged coins scanned the same day (flagged level was -10.1313%). EXACT: rv5/rv22 from closed daily closes only |
| 2026-10-13 | `scan.vol_expanding.day.diff_ret_pct` | 18 | -0.2135 | within-day: mean next-day % of the 18 flagged coins minus the 42 unflagged coins scanned the same day (flagged level was +1.6890%). EXACT: rv5/rv22 from closed daily closes only |
| run | `scan.vol_expanding.cum.level_pooled_pct` | 51 | -1.0614 | DESCRIPTION ONLY, not the number to act on: event-weighted mean return of the flagged coins, which contains the whole market move of every day it spans. Equal-weighted by day it is -2.1779% -- the gap between those two is the clustering trap, printed here rather than hidden. |
| run | `scan.vol_expanding.cum.pooled_diff_pct` | 51 | -1.1127 | event-weighted (by flagged coin-days) within-day difference over 51 coin-days. EXACT: rv5/rv22 from closed daily closes only |
| run | `scan.vol_expanding.cum.blockmean_diff_pct` | 5 | -2.9899 | EQUAL-WEIGHTED over 5 day-blocks -- THE FIGURE TO ACT ON, printed beside the pooled one above. EXACT: rv5/rv22 from closed daily closes only |
| run | `scan.vol_expanding.cum.mde_diff_pct` | 5 | 7.056 | DETECTION FLOOR, STATED BEFORE ANY READING: 80% power, two-sided 0.05, clustered on 5 day-blocks |
| run | `scan.vol_expanding.cum.size_mean_corr` | 5 | 0.8434 | corr(day n, day difference) over 5 blocks. If this is large, the pooled figure is the WRONG number rather than merely the imprecise one |
| run | `scan.vol_expanding.cum.placebo_reject_rate` | 5 | 0.0333 | 300 reps, within-day label permutation of the DIFFERENCE, nominal 0.05, 5 blocks. This is the test's REALIZED SIZE, and it is what licenses reading the figures above. The placebo CAN fail and has: run on the flagged LEVEL it rejected at 0.17-0.27, which is what forced the switch to the within-day difference. HOW TO READ IT: at 0.05 the MDE above is as advertised; above 0.05 the MDE is optimistic by roughly the ratio (a realized 0.10 means treat the floor as about 9.88), and a rate far above indicts the figures rather than merely widening them. |
| 2026-10-09 | `scan.ma50_pullback.day.diff_ret_pct` | 5 | -0.9107 | within-day: mean next-day % of the 5 flagged coins minus the 55 unflagged coins scanned the same day (flagged level was +2.0227%). DEVIATION: px = close(D-1) stands in for the live intraday markPx |
| 2026-10-10 | `scan.ma50_pullback.day.diff_ret_pct` | 4 | -1.6982 | within-day: mean next-day % of the 4 flagged coins minus the 56 unflagged coins scanned the same day (flagged level was +1.5621%). DEVIATION: px = close(D-1) stands in for the live intraday markPx |
| 2026-10-11 | `scan.ma50_pullback.day.diff_ret_pct` | 3 | -4.2592 | within-day: mean next-day % of the 3 flagged coins minus the 57 unflagged coins scanned the same day (flagged level was +0.2237%). DEVIATION: px = close(D-1) stands in for the live intraday markPx |
| 2026-10-12 | `scan.ma50_pullback.day.diff_ret_pct` | 2 | 3.3815 | within-day: mean next-day % of the 2 flagged coins minus the 58 unflagged coins scanned the same day (flagged level was -5.7300%). DEVIATION: px = close(D-1) stands in for the live intraday markPx |
| 2026-10-13 | `scan.ma50_pullback.day.diff_ret_pct` | 5 | 0.8542 | within-day: mean next-day % of the 5 flagged coins minus the 55 unflagged coins scanned the same day (flagged level was +2.6215%). DEVIATION: px = close(D-1) stands in for the live intraday markPx |
| run | `scan.ma50_pullback.cum.level_pooled_pct` | 19 | 0.9832 | DESCRIPTION ONLY, not the number to act on: event-weighted mean return of the flagged coins, which contains the whole market move of every day it spans. Equal-weighted by day it is +0.1400% -- the gap between those two is the clustering trap, printed here rather than hidden. |
| run | `scan.ma50_pullback.cum.pooled_diff_pct` | 19 | -0.6889 | event-weighted (by flagged coin-days) within-day difference over 19 coin-days. DEVIATION: px = close(D-1) stands in for the live intraday markPx |
| run | `scan.ma50_pullback.cum.blockmean_diff_pct` | 5 | -0.5264 | EQUAL-WEIGHTED over 5 day-blocks -- THE FIGURE TO ACT ON, printed beside the pooled one above. DEVIATION: px = close(D-1) stands in for the live intraday markPx |
| run | `scan.ma50_pullback.cum.mde_diff_pct` | 5 | 4.7479 | DETECTION FLOOR, STATED BEFORE ANY READING: 80% power, two-sided 0.05, clustered on 5 day-blocks |
| run | `scan.ma50_pullback.cum.size_mean_corr` | 5 | -0.2072 | corr(day n, day difference) over 5 blocks. If this is large, the pooled figure is the WRONG number rather than merely the imprecise one |
| run | `scan.ma50_pullback.cum.placebo_reject_rate` | 5 | 0.0567 | 300 reps, within-day label permutation of the DIFFERENCE, nominal 0.05, 5 blocks. This is the test's REALIZED SIZE, and it is what licenses reading the figures above. The placebo CAN fail and has: run on the flagged LEVEL it rejected at 0.17-0.27, which is what forced the switch to the within-day difference. HOW TO READ IT: at 0.05 the MDE above is as advertised; above 0.05 the MDE is optimistic by roughly the ratio (a realized 0.10 means treat the floor as about 6.65), and a rate far above indicts the figures rather than merely widening them. |
| 2026-10-09 | `scan.on_20d_low.day.diff_ret_pct` | 1 | -0.0884 | within-day: mean next-day % of the 1 flagged coins minus the 59 unflagged coins scanned the same day (flagged level was +2.7705%). DEVIATION: px = close(D-1) stands in for the live intraday markPx, and the `lo20 <= px` half of the live condition is vacuous at the close |
| 2026-10-10 | `scan.on_20d_low.day.diff_ret_pct` | 2 | -3.3224 | within-day: mean next-day % of the 2 flagged coins minus the 58 unflagged coins scanned the same day (flagged level was -0.0646%). DEVIATION: px = close(D-1) stands in for the live intraday markPx, and the `lo20 <= px` half of the live condition is vacuous at the close |
| 2026-10-11 | `scan.on_20d_low.day.diff_ret_pct` | 0 | — | flag fired on none of the 60 coins scanned on 2026-10-11. A real non-firing: every input was present. |
| 2026-10-12 | `scan.on_20d_low.day.diff_ret_pct` | 0 | — | flag fired on none of the 60 coins scanned on 2026-10-12. A real non-firing: every input was present. |
| 2026-10-13 | `scan.on_20d_low.day.diff_ret_pct` | 10 | 1.1851 | within-day: mean next-day % of the 10 flagged coins minus the 50 unflagged coins scanned the same day (flagged level was +2.8261%). DEVIATION: px = close(D-1) stands in for the live intraday markPx, and the `lo20 <= px` half of the live condition is vacuous at the close |
| run | `scan.on_20d_low.cum.level_pooled_pct` | 13 | 2.3771 | DESCRIPTION ONLY, not the number to act on: event-weighted mean return of the flagged coins, which contains the whole market move of every day it spans. Equal-weighted by day it is +1.8440% -- the gap between those two is the clustering trap, printed here rather than hidden. |
| run | `scan.on_20d_low.cum.pooled_diff_pct` | 13 | 0.3937 | event-weighted (by flagged coin-days) within-day difference over 13 coin-days. DEVIATION: px = close(D-1) stands in for the live intraday markPx, and the `lo20 <= px` half of the live condition is vacuous at the close |
| run | `scan.on_20d_low.cum.blockmean_diff_pct` | 3 | -0.7419 | EQUAL-WEIGHTED over 3 day-blocks -- THE FIGURE TO ACT ON, printed beside the pooled one above. DEVIATION: px = close(D-1) stands in for the live intraday markPx, and the `lo20 <= px` half of the live condition is vacuous at the close |
| run | `scan.on_20d_low.cum.mde_diff_pct` | 3 | 7.1964 | DETECTION FLOOR, STATED BEFORE ANY READING: 80% power, two-sided 0.05, clustered on 3 day-blocks |
| run | `scan.on_20d_low.cum.size_mean_corr` | 3 | 0.6439 | corr(day n, day difference) over 3 blocks. If this is large, the pooled figure is the WRONG number rather than merely the imprecise one |
| run | `scan.on_20d_low.cum.placebo_reject_rate` | 3 | 0.0233 | 300 reps, within-day label permutation of the DIFFERENCE, nominal 0.05, 3 blocks. This is the test's REALIZED SIZE, and it is what licenses reading the figures above. The placebo CAN fail and has: run on the flagged LEVEL it rejected at 0.17-0.27, which is what forced the switch to the within-day difference. HOW TO READ IT: at 0.05 the MDE above is as advertised; above 0.05 the MDE is optimistic by roughly the ratio (a realized 0.10 means treat the floor as about 10.07), and a rate far above indicts the figures rather than merely widening them. |
| 2026-10-09 | `scan.volume_surge_candlevol.day.diff_ret_pct` | 7 | 0.9827 | within-day: mean next-day % of the 7 flagged coins minus the 53 unflagged coins scanned the same day (flagged level was +3.7255%). PROXY: candle USD volume for both terms; live uses ctx.dayNtlVlm |
| 2026-10-10 | `scan.volume_surge_candlevol.day.diff_ret_pct` | 3 | 11.9929 | within-day: mean next-day % of the 3 flagged coins minus the 57 unflagged coins scanned the same day (flagged level was +14.5402%). PROXY: candle USD volume for both terms; live uses ctx.dayNtlVlm |
| 2026-10-11 | `scan.volume_surge_candlevol.day.diff_ret_pct` | 8 | -1.4186 | within-day: mean next-day % of the 8 flagged coins minus the 52 unflagged coins scanned the same day (flagged level was +3.0405%). PROXY: candle USD volume for both terms; live uses ctx.dayNtlVlm |
| 2026-10-12 | `scan.volume_surge_candlevol.day.diff_ret_pct` | 8 | -6.0642 | within-day: mean next-day % of the 8 flagged coins minus the 52 unflagged coins scanned the same day (flagged level was -14.2545%). PROXY: candle USD volume for both terms; live uses ctx.dayNtlVlm |
| 2026-10-13 | `scan.volume_surge_candlevol.day.diff_ret_pct` | 13 | -1.9515 | within-day: mean next-day % of the 13 flagged coins minus the 47 unflagged coins scanned the same day (flagged level was +0.3098%). PROXY: candle USD volume for both terms; live uses ctx.dayNtlVlm |
| run | `scan.volume_surge_candlevol.cum.level_pooled_pct` | 39 | -0.4099 | DESCRIPTION ONLY, not the number to act on: event-weighted mean return of the flagged coins, which contains the whole market move of every day it spans. Equal-weighted by day it is +1.4723% -- the gap between those two is the clustering trap, printed here rather than hidden. |
| run | `scan.volume_surge_candlevol.cum.pooled_diff_pct` | 39 | -1.0865 | event-weighted (by flagged coin-days) within-day difference over 39 coin-days. PROXY: candle USD volume for both terms; live uses ctx.dayNtlVlm |
| run | `scan.volume_surge_candlevol.cum.blockmean_diff_pct` | 5 | 0.7083 | EQUAL-WEIGHTED over 5 day-blocks -- THE FIGURE TO ACT ON, printed beside the pooled one above. PROXY: candle USD volume for both terms; live uses ctx.dayNtlVlm |
| run | `scan.volume_surge_candlevol.cum.mde_diff_pct` | 5 | 11.3012 | DETECTION FLOOR, STATED BEFORE ANY READING: 80% power, two-sided 0.05, clustered on 5 day-blocks |
| run | `scan.volume_surge_candlevol.cum.size_mean_corr` | 5 | -0.7223 | corr(day n, day difference) over 5 blocks. If this is large, the pooled figure is the WRONG number rather than merely the imprecise one |
| run | `scan.volume_surge_candlevol.cum.placebo_reject_rate` | 5 | 0.0433 | 300 reps, within-day label permutation of the DIFFERENCE, nominal 0.05, 5 blocks. This is the test's REALIZED SIZE, and it is what licenses reading the figures above. The placebo CAN fail and has: run on the flagged LEVEL it rejected at 0.17-0.27, which is what forced the switch to the within-day difference. HOW TO READ IT: at 0.05 the MDE above is as advertised; above 0.05 the MDE is optimistic by roughly the ratio (a realized 0.10 means treat the floor as about 15.82), and a rate far above indicts the figures rather than merely widening them. |
| run | `scan.above_20d_high.status` | — | — | STRUCTURAL-ZERO, NOT an observation: the live condition is markPx > max(high) over a window that INCLUDES the evaluation day's predecessor, and this job's only price is that predecessor's close, which cannot exceed its own high. The flag can never fire here, so no n is reported -- an n of 0 would be an artifact of the reconstruction. Becomes replicable once ctx.mark has an intraday series (archived since 2026-10-10). |
| run | `scan.funding_hot.status` | — | — | SOURCE-MISSING: needs a funding cross-section of >=20 coins on the evaluation day. funding_hist holds 999 rows/coin (the API page cap) ending Nov 2025 for 176 of 178 coins; history/*_funding.csv (40 coins) all end 2026-10-08 19:00; ctx begins 2026-10-10 22:42. Coverage actually found -- 2026-10-09: 178 coins via funding_hist; 2026-10-10: 178 coins via funding_hist; 2026-10-11: 178 coins via ctx; 2026-10-12: 178 coins via ctx; 2026-10-13: 178 coins via ctx |
| run | `scan.funding_cold.status` | — | — | SOURCE-MISSING: needs a funding cross-section of >=20 coins on the evaluation day. funding_hist holds 999 rows/coin (the API page cap) ending Nov 2025 for 176 of 178 coins; history/*_funding.csv (40 coins) all end 2026-10-08 19:00; ctx begins 2026-10-10 22:42. Coverage actually found -- 2026-10-09: 178 coins via funding_hist; 2026-10-10: 178 coins via funding_hist; 2026-10-11: 178 coins via ctx; 2026-10-12: 178 coins via ctx; 2026-10-13: 178 coins via ctx |
| run | `scan.volume_surge.status` | — | — | SOURCE-MISSING for the LIVE definition: its numerator is ctx.dayNtlVlm, a rolling 24h figure of which the laptop holds under one day. What accrues instead is `volume_surge_candlevol`, a candle-volume proxy, named apart on purpose so the two can never be read as the same flag. |
| run | `stop.panel_exceedance_rate.pooled` | 300 | 0.20667 | event-weighted. /next-day close-to-close move/ > 1.65 x em, em from funding_stop.py's hardcoded HAR, NOT the live volforecast em. ALL scanned coins: the in-sample 21.72% reference was the UNFLAGGED rate within date x em-quintile cells on 17 clean perps, a different population, so this is a companion figure and not that number. |
| run | `stop.panel_exceedance_rate.blockmean` | 5 | 0.20667 | EQUAL-WEIGHTED by day -- the figure to act on. /next-day close-to-close move/ > 1.65 x em, em from funding_stop.py's hardcoded HAR, NOT the live volforecast em. ALL scanned coins: the in-sample 21.72% reference was the UNFLAGGED rate within date x em-quintile cells on 17 clean perps, a different population, so this is a companion figure and not that number. |
| run | `stop.panel_exceedance_rate.mde` | 5 | 0.32933 | DETECTION FLOOR on the day-clustered rate, 80% power, two-sided 0.05 |
| run | `stop.panel_exceedance_rate.size_mean_corr` | 5 | — | corr(day n, day rate) over 5 blocks -- UNDEFINED, and benignly so: the scanned universe is a fixed top-60 every day, so every block has identical n and the pooled and equal-weighted figures above coincide by construction rather than by luck |
| run | `stop.funding_hot_matched_diff_pp.status` | — | — | SOURCE-MISSING: the +2.64pp matched difference needs funding_hot, which needs the funding cross-section recorded above. Nothing is appended for it, and its absence is not a difference of zero. |
| run | `stop.definition_divergence` | — | — | RECORDED FOR WHEN FUNDING ARRIVES: live scanner.py flags funding > p80 (STRICT, interpolated) on the INSTANTANEOUS hourly rate across the top 60 by volume; tested funding_stop.py used >= pandas quantile(0.80) on the DAY-SUMMED rate across 17 clean perps. Inclusive-vs-strict on a mass point, and instantaneous-vs-daily-sum, are different flags. Replicating the live flag and replicating the published claim are two different jobs, and this job will have to be told which one is wanted. |
| run | `chief.definition_source.status` | — | — | CODE-VERIFIED against server_exports/chief.py (208 lines): it defines both `brier` and `p_up`. Its no-information baseline is 0.25 (always_50) -- note that the correct no-information benchmark is p(1-p), which is 0.172 on the graded rows, so 0.25 credits as skill anything beating a coin flip while losing to a constant. |
| run | `chief.brier_24h.n_calls_with_p` | 138 | — | p_up_24h arrives as integer percent (observed range 46..52) and is divided by 100 to a probability. The scale is DETECTED, not assumed: read at face value a percent would make every Brier ~2300. |
| run | `chief.brier_24h.baseline` | 138 | 0.25 | the stated coin-flip reference, recorded so this log is self-contained |
| run | `chief.brier_24h.attainable_skill` | 138 | 0.00883 | CEILING: the largest possible improvement on 0.25 given the observed spread of p (max /p-0.5/ = 0.040). Best attainable Brier is 0.24117; a perfectly ordered forecaster could not beat it. Read any Brier against this, not against 0.25 alone. |
| run | `chief.brier_24h.pooled` | 102 | 0.24864 | event-weighted. p from the record /100; outcome = the 1h close at/before ts+24h > the call's own `price`; chief.py ABSENT so neither choice is verified against code |
| run | `chief.brier_24h.blockmean` | 3 | 0.24858 | EQUAL-WEIGHTED by call day -- the figure to act on, since calls arrive in batches of ~6 coins that share one market. p from the record /100; outcome = the 1h close at/before ts+24h > the call's own `price`; chief.py ABSENT so neither choice is verified against code |
| run | `chief.brier_24h.vs_baseline_blockmean` | 3 | -0.00142 | negative = better than a coin flip. Compare the magnitude against attainable_skill before reading anything into the sign. |
| run | `chief.brier_24h.mde` | 3 | 0.00559 | DETECTION FLOOR: 80% power, two-sided 0.05, on 3 call-day blocks |
| run | `chief.brier_24h.size_mean_corr` | 3 | 0.5336 | corr(block n, block mean). Large = the pooled figure is wrong, not just noisy |

## The refusals, restated

Each of these is a **refusal, not a zero**. A missing input reported as 0 reads as 'the
flag never fired' or 'the forecaster has no skill', and this project has already
published one false null that way.

- `funding_hot`, `funding_cold`, and the matched +2.64pp stop difference -- no funding
  cross-section exists on any out-of-sample day. Stated per day in the table above.
- `above_20d_high` -- cannot fire in a day-boundary reconstruction. Declared, not counted.
- `volume_surge` -- the live input is `ctx.dayNtlVlm`; the proxy accrues under a
  different metric name so the two can never be confused.
- the chief Brier definition -- `server_exports/chief.py` is absent, so the Brier is
  implemented from prose and says so in every row it writes.

## What would unblock what

- a funding rate per coin per day, or ~20 more days of `ctx` accrual, turns on
  `funding_hot`, `funding_cold` and the matched stop difference;
- `server_exports/chief.py` turns the Brier from prose-derived into code-verified;
- `ctx.mark` accrual turns `above_20d_high` from a structural zero into an observation.
