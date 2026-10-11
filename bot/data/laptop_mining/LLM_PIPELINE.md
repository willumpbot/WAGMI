# The LLM pipeline cannot rank its own trades — and its confidence may run slightly backwards. Three measurements now agree; none is significant alone.

_2026-10-11. 236 trades from `server_exports/trades.csv`, `entry_reasons` parsed on **all 236**.
Prompted by the server establishing that the confidence floor is **inert** in LLM-first mode, so the
LLM pipeline is what actually decides entries now._

---

## Why this is the right thing to measure

The server confirmed (`c23c5055`) that `LLM_FIRST_MODE=true` since early June returns before the
feedback-floor check, and inside the LLM-first path the floor is only *recorded* as metadata, never
enforced. **So the floor is a red herring and the LLM pipeline is the live gate.** Its own forecasts are
logged in `entry_reasons`, which makes them testable against outcomes.

## 🔴 Result: the pipeline's own forecasts do not rank its trades

| predictor | n | ρ with win/loss | week-clustered CI | MDE | verdict |
|---|---|---|---|---|---|
| **predicted `win_prob`** | 78 | **−0.096** | [−0.251, +0.344] | 0.323 | no ranking ability |
| **predicted `ev_per_dollar`** | 81 | **−0.044** | [−0.311, +0.503] | 0.317 | no ranking ability |
| `llm_confidence` | 209 | **−0.164** | [−0.348, **+0.007**] | 0.195 | not significant — but see below |
| `num_agree` | 209 | +0.114 | [−0.073, +0.320] | 0.195 | not significant |

**The pipeline's two explicit forecasts — its predicted win probability and its predicted EV — carry no
detectable ranking information about its own trades.** Both point very slightly the wrong way.

### Calibration, separately

| | |
|---|---|
| mean **predicted** win probability | **46.3%** |
| **realized** win rate | **38.5%** |
| gap | **+7.9 points** (overconfident) |
| 95% CI on realized | [27.7%, 49.3%] — predicted sits **inside** |
| 80%-power MDE at n=78 | **15.4 points** |

**Not detectably miscalibrated.** The useful statement is a bound: **miscalibration worse than ~15
points is excluded**, and modest overconfidence is consistent with the data.

## ⚠️ The pattern I would not dismiss: confidence runs backwards, in two independent months

`llm_confidence` split at its median gives **30.5% win above vs 47.1% below** — a 16.6-point gap the
wrong way. **The correlation does not clear significance** (CI touches +0.007), and the median split was
a *second* look at the same data, not pre-registered. So on its own: not a finding.

**But it replicates month by month, which an artifact usually does not:**

| month | n | win% above median | win% below | gap |
|---|---|---|---|---|
| **2026-06** | 66 | **9.1%** | 30.3% | **−21.2** |
| **2026-07** | 123 | **38.5%** | 62.1% | **−23.6** |
| 2026-09 | 15 | 37.5% | 14.3% | +23.2 *(reverses, n=15 — noise)* |

**Two independent months, both ≈ −22 points.** June and July are different regimes, different configs
and different trade populations — the era confound that killed three earlier findings **does not apply
here**, because the effect appears *within* each era separately rather than between them.

### And this is now the third framing pointing the same way

| measurement | direction |
|---|---|
| `TP1_SCREEN.md` — trades that reached TP1 | **lower** entry confidence (27.7 vs 41.4) |
| `CONF_FLOOR.md` — ledger `confidence_score` vs P&L | ρ **−0.181** pooled, −0.087 by week |
| **this doc** — `llm_confidence`, median split | **−21 / −24 points** in June and July |

Three different fields, three different outcome definitions, **same sign every time.** Individually none
is significant. **The consistency is the evidence**, and it is suggestive rather than established — the
three overlap in data, so they are not fully independent.

**`num_agree` is the mirror image and much weaker:** +19.5 points, but **only July has a valid split**
(June has no spread in the field, Sep is too small). One month is not a pattern.

## Trader rules — one number each
1. **Do not size up on confidence.** Across three measurements the bot's confidence fields show no
   ranking ability and a consistent mild tilt the *wrong* way. Treating a high-confidence signal as a
   better signal is not supported by anything measured here.
2. **The pipeline's own win-probability forecast carries no ranking information** — ρ = −0.096 on 78
   trades, against an MDE of 0.32.
3. **It is overconfident by about 8 points** (46.3% predicted vs 38.5% realized), which is not
   statistically established but is the safe direction to assume.

## 🔧 What would settle it — one field

The server records **`would_pass_confidence_floor`** as metadata in the LLM-first path
(`multi_strategy_main.py:8509-8510`) but **it is null on the only 2 export rows that carry the key.**

**Populating it would create a rare natural experiment.** Because the floor is *inert*, its recorded
verdict is an **unselected prediction** — normally a gate cannot be evaluated because it removes the
very trades you would measure, but here it does not act, so the counterfactual is observable for free.
That turns "does the confidence floor select good trades?" from untestable into cleanly testable.

**Asked for, cheap, and the cleanest test available on this question.**

## Limits
- **Nothing here clears significance.** The primary statistic is the correlation and none of the four
  predictors cleared it. The median splits are secondary views of the same data.
- **209 rows but mostly two months** (66 June, 123 July), so this is substantially a June–July
  statement. Sep (15) and Oct (5) are too small to confirm or refute.
- `win_prob` and `ev_per_dollar` exist on only 78 and 81 rows, all post-June.
- **Not red-teamed.** Given that three findings in this project died to era and two to multiplicity,
  the month-by-month replication is the main reason I am reporting the confidence tilt at all.
