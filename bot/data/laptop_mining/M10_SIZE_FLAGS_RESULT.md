# Mission 10 - do the size-flags beat HAR? Mostly NO: most flags just pick already-volatile coins (HAR already knows that), and TWO flags (funding_cold, ma50_pullback) actually mark coins that move LESS than their HAR baseline. Only the excess OVER HAR matters for sizing, and on 6 firing-days most of it is underpowered.

_2026-10-15. m10_flags.py. 388 coin-days, 6 firing-days (scan_log 2026-10-08..15), 82 coins with candle
coverage. realised_1d|move| ~ a + b*HAR + c*flag (pooled, day-block-clustered CI on c). HAR proxy =
mean(|ret|_1d, mean|ret|_5d, mean|ret|_22d), point-in-time at the firing bar. Value-add over the
server's scan_grades.json: the HAR-matched baseline (scan_grades reports flagged |move| but not whether
it beats a same-HAR coin)._

## Excess over HAR per flag (c = flagged |move| beyond what HAR predicts; + = adds, CI day-block)
| flag | n | flagged \|move\| | unflagged | EXCESS over HAR | verdict |
|---|---|---|---|---|---|
| funding_cold | 176 | 3.96% | 6.75% | **-2.19% [-3.37,-0.81]** | moves LESS than HAR - NOT a size-up flag |
| ma50_pullback | 78 | 3.61% | 5.96% | **-1.50% [-2.29,-0.54]** | moves LESS than HAR - NOT a size-up flag |
| funding_hot | 66 | 7.63% | 5.05% | +1.14% [-0.39,+2.49] | leans bigger, UNDERPOWERED |
| above_20d_high | 33 | 9.61% | 5.10% | +1.77% [-1.94,+4.11] | leans bigger, UNDERPOWERED |
| momentum_small | 18 | 8.88% | 5.32% | +1.28% [-1.21,+3.13] | UNDERPOWERED |
| vol_expanding | 57 | 7.01% | 5.22% | +0.58% [-1.19,+3.31] | UNDERPOWERED |
| volume_surge | 71 | 7.45% | 5.04% | +0.27% [-1.56,+2.11] | UNDERPOWERED - raw size is just HAR |
| on_20d_low | 38 | 3.90% | 5.66% | -0.97% [-2.18,+0.41] | leans smaller, UNDERPOWERED |

## Read
1. **funding_cold and ma50_pullback are the only CI-clean results, and both are NEGATIVE**: coins with
   these flags move ~1.5-2.2% LESS than their HAR baseline. If the bot sizes UP on them expecting a
   bigger move, that is backwards. (Makes sense: cold funding = quiet/low-leverage; ma50 pullback =
   mean-reverting into an average.) Do NOT treat them as size-UP inputs.
2. **volume_surge / funding_hot / vol_expanding / above_20d_high flag volatile coins** (raw |move|
   7-9% vs 5% unflagged) - but that is almost entirely explained by HAR (they ARE high-vol coins). The
   EXCESS over HAR is not distinguishable from 0 on 6 days. So the flag adds nothing PROVABLE beyond
   "this is a volatile coin", which the vol model already captures. funding_hot/above_20d_high lean
   positive and are the best re-grade candidates once more firing-days accrue.

## Caveats (honest)
HAR here is a trailing-realized proxy (1d/5d/22d |ret| blend), not the bot's fitted HAR - a different
HAR could shift the excess a little; the two CI-clean negatives are large enough to likely survive.
Only 6 firing-days -> day-block CIs are wide; the UNDERPOWERED verdicts are "not yet measurable", not
"no effect". No hard live change recommended from 6 days - re-grade at >=20 firing-days.

## Rules for the owner (one number each)
1. Your "big move" flags mostly just point at coins that are ALREADY jumpy - the vol model already
   knows that, so the flag adds little proven extra. (provable excess over HAR: ~0 for most)
2. Two flags mark coins that move LESS than usual - don't size UP on funding_cold or ma50_pullback.
   (funding_cold: -2.2% vs its own baseline)
3. Give it a few more weeks before trusting any flag as a real size booster. (days of data so far: 6)
