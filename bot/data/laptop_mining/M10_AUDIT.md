# Audit of Mission 10 (`FUNDING_CARRY.md`) — the finding survives. ⚠️ The planned 60-coin widening would mostly manufacture false precision.

_2026-10-11. First review this doc has ever had. Funding history for 38 coins, 267 common days.
Written now because **queue item 8 is the widening**, and it should be done differently._

---

## 🔴 Three results, in order of what to do about them

1. **The headline finding survives clustering.** It is real.
2. **Every confidence interval in the doc is about 2.4× too narrow.** No conclusion changes.
3. **⚠️ Widening from 16 to ~60 coins multiplies rows by 3.8× and effective information by 1.09×
   (+9%), while making every interval look 49% tighter.** That is the one thing worth changing.

## 1. What the doc never checked: funding is a market-wide regime

Nobody had measured how independent the 14,344 coin-days are. Across 38 coins and 267 common days:

| | value |
|---|---|
| mean pairwise cross-coin funding correlation | **0.330** (median 0.335, range −0.08 to 0.80) |
| coins with positive funding on an average day | **80.4%** |
| days where ≥90% of coins share the funding sign | **30%** |
| days where **all** coins share the sign | 9% |

So a "coin-day" is not an independent observation — funding moves as a market. Design effect
`1 + (m−1)ρ` is **6.0** for a 16-coin block and **13.2** for 38. The 10,146 coin-days I could load
behave like roughly **767 independent observations**.

## 2. The persistence claim survives anyway

The doc reports P(next-day funding > 0) rising from an unconditional **83.2%** to **99.3%** in the top
trailing quintile (n = 1,662).

| assumption | effective n | z |
|---|---|---|
| no clustering (as published) | 1,662 | **17.6** |
| 16-coin same-day block (ρ = 0.33) | 277 | **7.2** |
| 38-coin block | 126 | **4.8** |

**It survives at the most deflated sample I can justify.** This is the strongest single result in the
project and the audit confirms it rather than killing it.

**One presentation fix:** the headline says *"99.3% persistent"* without the **83.2% unconditional
baseline** beside it. The honest sentence is "funding is positive 83.2% of the time, rising to 99.3% in
the top trailing quintile." The baseline *is* in §1 of the doc, so this is phrasing, not a hidden figure —
but 99.3% quoted alone overstates what was learned, and that is how it will get repeated.

## 3. The negative conclusions are robust — clustering only helps them

Inflating each published interval by √6:

| cell | published CI | clustered CI | verdict |
|---|---|---|---|
| ≥80th / train | [−0.603, +0.197] | [−1.183, +0.777] | still spans zero |
| ≥80th / test | [−1.290, +0.967] | [−2.926, +2.603] | still spans zero |
| ≥95th / train | [−1.467, +0.352] | [−2.785, +1.670] | still spans zero |

**"The carry trade as tested does not pay" stands, and stands more firmly.** Wider intervals can only
reinforce a conclusion that already spanned zero. The doc's own refusal to quote the n=19 test cell was
correct.

## 4. ⚠️ The time-critical part: do the widening differently

| coins | design effect | independent obs per day |
|---|---|---|
| 16 | 6.0 | 2.69 |
| 30 | 10.6 | 2.83 |
| **60** | **20.5** | **2.93** |

**Rows × 3.8. Effective information × 1.09.** And a naive CI computed on 3.8× the rows tightens by
√3.8 = **1.95×** — so every cell would look **49% more precise** while carrying **9% more information**.
That is the exact mechanism behind this project's reversals, applied prospectively.

**It is not that widening is useless — it is that coin *count* is the wrong lever. Coin *correlation* is
the lever.** Pairwise correlations run from **−0.08 to 0.80**. Thirty coins chosen for low mutual
correlation would carry far more information than sixty chosen for having a funding history.

**So, concretely, for queue item 8:**
1. **Compute the correlation matrix first and select for diversity**, not for coin count.
2. **Report clustered intervals** — block-bootstrap by *day* (all coins on a day resample together),
   which is the cluster that matters here, not by coin.
3. **Put the equal-weighted day mean next to every pooled figure**, as elsewhere in this project.
4. **Expect it not to rescue the underpowered cells.** The ≥95th-percentile test cell has n = 19 and a
   ±4.7% interval; ×3.8 rows at ρ = 0.33 will not fix that, and it should stay unquoted.

## Trader rules — one number each
1. **Funding persistence is real: 83.2% → 99.3%, and it survives clustering at z = 4.8.** It remains the
   most reliable thing in this project.
2. **Funding is one market-wide trade, not 16 independent ones** — mean cross-coin correlation **0.33**,
   and on 30% of days ≥90% of coins share the sign. Do not size it as diversified.
3. **More coins will not buy precision.** 16 → 60 adds **9%** real information.

## Limits
- ρ = 0.330 is measured on the **38 coins and 267 common days** I could load locally, not on the exact
  16-coin / 14,344-coin-day panel the doc used. The design-effect arithmetic is therefore indicative;
  the server should recompute ρ on the real panel. **The direction and rough magnitude will not change** —
  funding is visibly a market-wide variable.
- The design-effect formula assumes roughly equal correlation within a block. With correlations ranging
  −0.08 to 0.80 that is an approximation, and it will understate the deflation for tightly-coupled
  majors and overstate it for idiosyncratic alts.
- I did not re-run `funding_carry.py`. This audits the reported figures and their stated precision, not
  the underlying computation.
