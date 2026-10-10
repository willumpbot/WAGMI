# Mission 9 — the chief is unfalsifiable by construction. Fix the prompt, then re-test on 2026-10-16.

_2026-10-10. 86 calls, 165 named levels, 6 symbols, 2026-10-08 18:57 → 10-10 17:08 (1.9 days).
Fresh 1h/1d candles fetched for the window. Data: `chief_levels.json`.
Answering `SERVER_REPLY.md` mission 9._

---

## 🔴 The answer in three parts

1. **Direction cannot be graded, and that is a prompt problem, not a grading problem.** 86 of 86 calls
   are `NEUTRAL`, 75 of them at conviction 1. **A forecaster that never commits cannot be wrong, so it
   cannot be right either.** No grading scheme fixes this.
2. **Its named levels carry no measurable information** — but the test is weak (MDE 6–14 points), so
   this is *"not yet measurable"*, not *"useless"*.
3. **This is the fastest-accumulating gradeable thing in the project: 86 levels/day.** Four times the
   sample — enough to halve the MDE — lands in **~6 days**. Re-run this exact test on **2026-10-16**.

---

## What the chief actually emits

| | |
|---|---|
| calls | 86 over 1.9 days, 6 symbols (BTC, ETH, SOL, HYPE, XRP, NEAR) |
| lean | **NEUTRAL, 86 of 86** |
| conviction | 1 on 75 calls, 2 on 11 |
| named levels | 165 usable, **2.1 per call**, parsed from `invalidation` |
| level distance | median **4.30%** from price = **0.89 ATR-1d** (p25 0.62, p75 1.08) |

The level *placement* is sensible — about one daily range out, which is where an invalidation point
belongs. The chief is not producing nonsense; it is producing something unfalsifiable.

## Are the named levels better than arbitrary levels at the same distance?

Tested three ways. The first was wrong and I am showing it because the error is the point.

### ❌ First attempt — random-time null (confounded)

| window | chief | random time, same distance | difference | verdict |
|---|---|---|---|---|
| 12h | 6.6% | 13.4% | **−6.8 pt** | "informative" |
| 24h | 11.9% | 21.7% | **−9.8 pt** | "informative" |
| 48h | 20.3% | 34.6% | **−14.3 pt** | "informative" |

Three windows, all significant, all consistent — and **all confound.** Every call sits inside one
quiet 1.9-day window while the null sampled random times across 20 days, including far more volatile
ones. "Chief levels get touched less" was "the last two days were quiet."

### ✓ Time-matched null — same timestamp, same symbol, only the level randomised

| window | n | chief | time-matched | difference | **MDE** | verdict |
|---|---|---|---|---|---|---|
| 12h | 152 | 6.6% | 7.5% | −0.9 pt | 6.2 pt | no difference |
| 24h | 126 | 11.9% | 15.2% | −3.3 pt | 9.0 pt | no difference |
| 48h | 79 | 20.3% | 21.8% | −1.5 pt | 13.9 pt | no difference |

### ✓ Side-flip control — same distance, same moment, opposite side

| window | n | chief's side | flipped side | difference | verdict |
|---|---|---|---|---|---|
| 12h | 152 | 6.6% | 8.6% | −2.0 pt | no difference |
| 24h | 126 | 11.9% | 13.5% | −1.6 pt | no difference |
| 48h | 79 | 20.3% | 16.5% | +3.8 pt | no difference |

Both honest controls agree: **the levels are indistinguishable from arbitrary levels at the same
distance.** But at n = 79–152 the MDE is 6–14 points, so only a large effect would show. Do not put
"no edge" on screen for this.

---

## Recommendation: change the prompt, keep the frequency, re-test 2026-10-16

**Change the prompt.** The chief's job as written produces a call that cannot be scored. Two options,
cheapest first:

1. **Force a committed lean whenever conviction ≥ 2** (11 of 86 calls). Keep NEUTRAL available at
   conviction 1, but at conviction 2 require UP or DOWN. That creates a gradeable record immediately
   without making it guess constantly.
2. **Ask it for a probability, not a lean** — "chance BTC closes above X in 24h" — which is scoreable
   on every single call via a Brier score, and never requires it to commit to a direction it does not
   have. This is strictly better if the prompt budget allows it.

**Keep the 4-hourly frequency.** It is what makes 86 levels/day possible, and that accumulation rate
is the project's fastest route to any statistically resolvable answer. Cutting it would be the one
change that makes grading harder.

**Re-test on 2026-10-16.** At 86 levels/day, six more days gives ~680 levels. That takes the 24h MDE
from 9.0 points to roughly **3.5 points** — enough to detect the kind of edge a good level-picker
would have. If it is still flat at that MDE, then cut the frequency.

## Trader rules — one number each

1. **The chief has never once committed to a direction** — 86 of 86 NEUTRAL. Treat it as a
   describer, not a forecaster, until the prompt changes.
2. **Its invalidation levels sit about one daily range out** (median 0.89 ATR-1d), which is sensible
   placement even though their *selection* shows no measurable skill.
3. **Six more days makes this answerable.** 86 levels/day → ~680 levels by 2026-10-16, halving the
   detection threshold to ~3.5 points.

## What I did not test, and why
- **Part (a) of the mission — "its expected move vs realised vs HAR alone".** `chief_calls.jsonl` has
  no expected-move field; it carries `atr_pct_1d` and `ret_1d` only. The expected move appears inside
  the `read` prose. **Export it as a numeric field and I can test whether Opus adds anything over
  HAR** — that is a clean, high-value test and it is one column away.
- Daily-close invalidation ("neutral view ends on a daily close below X") needs multiple forward daily
  closes; only 2 exist for the earliest calls. I tested *touch* on 1h bars instead, which is the more
  sensitive version and the one with enough resolution.

## Limits
- **1.9 days, one regime.** The confounded first attempt is proof of how much that matters.
- Levels parsed by regex from prose, filtered to within ±100% of price and >0.2% away: 165 of a raw
  168. Mis-parses would add noise, not bias.
- 1h touch resolution; a level pierced and reclaimed inside an hour reads as touched.
- `NEAR` had no entry in the long `history/` set, so all six symbols use freshly fetched candles for
  consistency.
