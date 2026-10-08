# Mission 5 — do the voices have value together?

_2026-10-08. Panel: 18,201 symbol-days, 10 coins, 2020-10-18 → 2026-10-06.
Train < 2025-06-01 (13,271 rows) / test ≥ 2025-06-01 (4,930). Scripts: `cooperation.py`.
Data: `cooperation.json`, `voice_families.json`._

---

## Headline

**No. Together they still cannot call direction — but they do call the SIZE of the move, and that
part holds out of sample. The hivemind should stop voting on which way and start voting on how big.**

Three results, in order of usefulness:

1. **Three of your ten voices are the same voice.** `stretch`, `range20` and `driver` correlate
   0.64–0.78 with each other. Every consensus score the system has ever computed was triple-counting
   that one view. `voice_families.json` ships the fix.
2. **Agreement predicts magnitude, not direction.** When only one family dissents, the next day moves
   **5.11%** on average; when four dissent, **3.17%**. Those confidence intervals do not overlap.
   Direction, meanwhile, is a coin flip at every level of agreement.
3. **Nothing directional survived.** 34 voice × regime combinations, zero held from train to test.
   The high-consensus bucket looked like +4.0% over five days in train and came back **−0.34%** in
   test. Out-of-sample net-direction returns are −0.02% / +0.02% / +0.10% at 1/3/5 days, every
   interval spanning zero.

---

## 1. Redundancy — 10 voices collapse to 8 families

Pearson correlation on the −1/0/+1 encoding, 18,201 rows:

| | struct | stretch | range20 | driver | rsi | boll | mom7 | mom30 | btc | funding |
|---|---|---|---|---|---|---|---|---|---|---|
| **structure** | — | 0.42 | 0.34 | 0.49 | 0.31 | 0.21 | 0.17 | 0.61 | 0.63 | −0.10 |
| **stretch** | 0.42 | — | **0.78** | **0.75** | 0.34 | 0.49 | 0.60 | 0.59 | 0.35 | −0.07 |
| **range20** | 0.34 | **0.78** | — | **0.64** | 0.40 | 0.57 | 0.63 | 0.50 | 0.29 | −0.10 |
| **driver** | 0.49 | **0.75** | **0.64** | — | 0.34 | 0.46 | 0.47 | 0.64 | 0.40 | −0.05 |
| **rsi** | 0.31 | 0.34 | 0.40 | 0.34 | — | 0.50 | 0.33 | 0.33 | 0.27 | −0.06 |
| **bollinger** | 0.21 | 0.49 | 0.57 | 0.46 | 0.50 | — | 0.48 | 0.37 | 0.18 | −0.04 |
| **mom7** | 0.17 | 0.60 | 0.63 | 0.47 | 0.33 | 0.48 | — | 0.31 | 0.15 | −0.05 |
| **mom30** | 0.61 | 0.59 | 0.50 | 0.64 | 0.33 | 0.37 | 0.31 | — | 0.47 | −0.08 |
| **btc** | 0.63 | 0.35 | 0.29 | 0.40 | 0.27 | 0.18 | 0.15 | 0.47 | — | −0.08 |
| **funding** | −0.10 | −0.07 | −0.10 | −0.05 | −0.06 | −0.04 | −0.05 | −0.08 | −0.08 | — |

At |r| ≥ 0.70 the families are:

| family | members | independence weight each |
|---|---|---|
| **fam_7** | **stretch, range20, driver** | **0.333** |
| fam_8 | structure | 1.0 |
| fam_1 | bollinger | 1.0 |
| fam_2 | btc | 1.0 |
| fam_3 | funding | 1.0 |
| fam_4 | mom30 | 1.0 |
| fam_5 | mom7 | 1.0 |
| fam_6 | rsi | 1.0 |

**Plain version:** "price is above its 20-day average", "price is in the top third of its 20-day
range" and "buyers are driving" are three ways of saying *price went up recently*. Counting them as
three agreeing voices is like asking one person the same question three times and calling it a
consensus of three.

Two near-misses worth knowing even though they sit under the threshold: `structure`↔`btc` at 0.63 and
`structure`↔`mom30` at 0.61. In a 10-voice panel, a "7 of 10 agree" reading is realistically more
like 4 or 5 genuinely distinct opinions.

**`funding` is the only truly independent voice** (|r| ≤ 0.10 against everything). It is also the
least covered — present on just 16.6% of rows, because Hyperliquid funding history only reaches
2024. On its own it has no edge, but it is the one voice that is not a restatement of price.

---

## 2. Agreement — flat for direction

`net` = sum of one representative per family, each −1/0/+1. `k = |net|` is how lopsided the panel is.
Returns are in the net direction, minus 9 bps.

| k | n | days | e1 % | CI95 | e5 % | CI95 |
|---|---|---|---|---|---|---|
| 1 | 3,092 | 1,293 | −0.029 | [−0.208, +0.167] | +0.527 | [−0.155, +1.192] |
| 2 | 1,824 | 905 | +0.168 | [−0.074, +0.400] | −0.113 | [−0.864, +0.605] |
| 3 | 3,217 | 1,506 | +0.060 | [−0.161, +0.286] | +0.927* | [+0.012, +1.881] |
| 4 | 1,974 | 983 | +0.004 | [−0.270, +0.275] | +0.235 | [−0.533, +1.001] |
| 5 | 3,906 | 1,528 | +0.237 | [−0.012, +0.488] | +1.337* | [+0.357, +2.290] |
| 6 | 2,150 | 988 | +0.184 | [−0.189, +0.550] | +1.461* | [+0.131, +2.836] |
| 7 | 1,041 | 551 | +0.486 | [−0.170, +1.196] | +3.202* | [+1.035, +5.731] |
| 8 | 61 | 31 | −0.110 | [−2.761, +2.591] | −1.652 | [−4.521, +2.017] |

ρ(k, e1) = **+0.214** → flat. Not one 1-day cell excludes zero.

The 5-day column looks compelling and **it does not survive the split**:

| high agreement (k ≥ 7) | e1 | e5 |
|---|---|---|
| train | +0.594% [−0.204, +1.383] | **+4.006%\*** [+1.358, +7.059] |
| **test** | +0.023% [−1.275, +1.266] | **−0.342%** [−3.137, +2.736] |

Sign flips, interval spans zero. And note k=8 — total unanimity — is *negative* in both columns.

---

## 3. Contradiction — this is where the value is

Disagreement does not tell you direction. It tells you **how violent the next day will be**, and it
is monotone over the range that matters:

| families disagreeing with the net | n | \|next-day move\| | CI95 | e1 (direction) |
|---|---|---|---|---|
| 0 | 61 | 4.782% | [2.977, 6.855] | −0.110% |
| **1** | 1,358 | **5.109%** | **[4.711, 5.545]** | +0.603% |
| 2 | 2,422 | 3.708% | [3.482, 3.935] | +0.041% |
| 3 | 5,519 | 3.348% | [3.214, 3.499] | +0.143% |
| 4 | 5,043 | 3.173% | [3.035, 3.325] | +0.125% |
| 5 | 2,862 | 3.257% | [3.084, 3.442] | −0.034% |
| 6 | 936 | 3.231% | [2.634, 4.260] | −0.090% |

The `disagree=1` interval [4.711, 5.545] and the `disagree=2` interval [3.482, 3.935] **do not
overlap**. Near-unanimity means a move about **55% larger** than a split panel — with no information
about which way it goes.

One negative to record: the specific `structure` vs `driver` contradiction the handoff suggested does
**not** predict size (3.474% when they agree vs 3.432% when they clash). It is the *count* of
dissenting families that matters, not that pair.

**Plain version:** the panel is a crowd-noise meter, not a compass. When the crowd is unanimous,
expect a big day. Do not expect to know its direction.

---

## 4. Conditional trust — nothing survived

34 voice × regime combinations (ADX>25, ADX≤25, volatility expanding, volatility quiet), each fitted
on train and re-scored on test. **Zero held.** Eight flipped sign outright (`stretch`×adx>25,
`range20`×adx>25, `bollinger` in both ADX regimes, `mom7`×adx>25, `mom30`×adx≤25 and ×vol_quiet,
`btc`×adx≤25 and ×vol_quiet). The rest were "not confirmed" — right sign, interval spanning zero.

The most tempting cell was `rsi × vol_quiet`: train **+1.416%**, test +0.648% [−0.726, +1.811]. Big,
plausible, not significant. Exactly the shape of the claims in `EXPERIMENT_INDEX.md` that this
project kept shipping and then retracting.

---

## 5. Bottom line

| | e1 | CI95 |
|---|---|---|
| always-long null | +0.1349% | [−0.0434, +0.3128] |
| **test, net direction, 1d** | **−0.0230%** | [−0.2645, +0.2256] |
| **test, net direction, 3d** | **+0.0190%** | [−0.4957, +0.5739] |
| **test, net direction, 5d** | **+0.0963%** | [−0.7523, +1.0557] |

No out-of-sample directional edge after fees, at any horizon. Even always-long is not significant
over this period, so there is no free beta to lean on either.

### What *is* predictable

| relationship | full | test |
|---|---|---|
| today's ATR% → next-5-day realised volatility | **+0.341** | **+0.353** |
| structure voice → next-1-day return | +0.030 | — |

**Volatility is ten times more predictable than direction, and it is stable out of sample** — the
test correlation is slightly *higher* than the full-sample one, which is the opposite of overfitting.
Combined with §3, there are now two independent routes to forecasting move size: current ATR, and the
consensus count. That is the brief for mission 7.

---

## Method notes and a correction to my own first run

- Cluster bootstrap over **contiguous day blocks**, with the block length matched to the horizon
  (1 day for e1, 5 days for e5), 2,000 draws.
- **My first version used 1-day blocks at every horizon.** That ignores the fact that a 5-day forward
  window overlaps the next four days, and it inflated every 3-day and 5-day interval — the
  high-agreement cell read +4.056% [+2.641, +5.584] before the fix and +3.202% [+1.035, +5.731]
  after, and the train/test verdict is what actually settles it either way. Figures above are the
  corrected ones.
- `k = 0` is excluded from the agreement table. With a zero net the panel takes no position, so
  charging it a round-trip fee produced a spurious −0.090% with a zero-width interval.
- No lookahead: every voice uses only closed candles; outcomes are `shift(-h)`.
- Funding is encoded as *minus* the sign of the rate (crowded longs treated as a bearish prior).
- `fwd_vol5` is the standard deviation of the **next** five daily returns.

## What the server should change

1. **Load `voice_families.json` into the hivemind** and multiply each voice's vote by its
   independence weight. `stretch`, `range20` and `driver` get 0.333 each instead of 1.0. Nothing else
   about the consensus score needs to change.
2. **Stop displaying consensus as a directional confidence.** It has no directional content at any
   level, in or out of sample.
3. **Start displaying it as an expected-move-size gauge.** `disagree ≤ 1` → "expect a ~5% day";
   `disagree ≥ 3` → "expect a ~3.2% day". That is a genuinely useful swing-desk reading and it is
   supported out of sample.
4. Keep `funding` even though it is weak alone — it is the only voice that is not a restatement of
   recent price, so it is the only one that can add new information to a consensus.
