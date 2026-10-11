# Crowded shorts: **UNTESTED.** Not "no effect" — the point estimate matches the crowded-long finding but cannot be distinguished from zero.

_2026-10-11. Answering the server's item 4, asked because both open Claude ideas are BTC/ETH **shorts**
and the chief notes BTC funding at **z = −3.3** (shorts paying hard). Same panel, outcome, matching and
clustering as `FUNDING_STOP.md` — only the condition is mirrored._

---

## 🔴 The answer, stated plainly as asked

| condition | fires on | effect | week t | verdict |
|---|---|---|---|---|
| `funding < 0` — the scanner's `funding_cold` | 16.11% | **+2.56 pp** | **1.59** | **not significant** |
| bottom quintile, strictly below | 20.93% | +0.85 pp | 1.04 | not significant |
| *reference:* crowded **LONGS**, top quintile | 26.33% | +2.64 pp | **3.31** | significant |

**Power first:** at a 16.1% fire rate the 80%-power MDE is **≈4.5 pp**, and the observed effect is
**+2.56 pp** — **below the detection floor.** So this is **untested**, which is a different statement
from "no effect."

## ⚠️ The detail that matters, and it cuts both ways

**The crowded-short point estimate (+2.56 pp) is almost identical to the crowded-long one (+2.64 pp).**
The difference in verdict is entirely sample size — 129 weeks at a 16% fire rate instead of 145 weeks at
26%, which roughly doubles the standard error.

**So the data is consistent with the same effect existing on the short side.** It is also consistent with
no effect. **Both readings fit, and anyone claiming either is going past the evidence:**

- ❌ "The funding finding applies to shorts too" — **not supported.** t = 1.59.
- ❌ "Crowded shorts are fine, the effect is long-only" — **also not supported.** The point estimate is
  the same size; we simply cannot resolve it.
- ✅ **"Untested. No tested guidance either way on crowded-short days."**

## What I would actually say to the owner about the open BTC/ETH shorts

**There is no tested rule covering this situation.** The honest position is that crowded positioning in
*either* direction plausibly means a rougher day — the symmetry of the two point estimates is mildly
suggestive of that — but **it is a guess, and the measured version only exists for the long side.**

If he wants to act on the symmetry anyway, the conservative reading argues for **the same modest
size-down** already warned for crowded longs. That is a judgement call about asymmetric costs, not a
finding, and it should be labelled that way on any screen.

**What it does NOT justify:** treating `funding_cold` as a tested flag. The scanner currently labels it
*"context only"*, which is **exactly right** and should stay.

## Why the short side is harder to measure, so nobody re-opens this expecting a different answer

1. **It fires less often** — 16.1% vs 26.3% of coin-days, because negative funding is less common than
   crowded-positive funding on these 17 perps.
2. **Fewer usable weeks** — 129 vs 145, since a week needs both flagged and unflagged rows inside the
   same date × em-quintile cell to contribute.
3. **The tie mass sits on the positive side.** 18.6% of coin-days park at the platform default funding
   rate, which is positive — so the *bottom* quintile is thinner and noisier than the top.

**To reach t ≈ 3 on the short side would need roughly 2.5× the current sample** — about 2.5 years more
of this panel, or a wider coin universe chosen for *low* funding correlation (see `M10_AUDIT.md`:
more coins alone buys almost nothing).

## Limits
- Direction-free outcome: `|next-day move| > 1.65 × expected move`. It measures whether a stop at the
  standard distance gets hit, not whether price went the way a short wanted.
- Same close-to-close caveat as `FUNDING_STOP.md` — absolute exceedance rates are a floor, not the truth.
- `funding_cold` as the scanner defines it is an **absolute** condition (`funding < 0`), not
  cross-sectional, so it is not the exact mirror of the fixed `funding_hot` (top quintile, strictly
  above). Both variants are reported above and neither clears.
