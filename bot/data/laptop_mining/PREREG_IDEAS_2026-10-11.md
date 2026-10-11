# PRE-REGISTRATION — do Claude's trade ideas beat their own geometry? Written 2026-10-11, at n=0 resolved.

**Status: SEALED. Written when zero ideas have finished (3 open: BTC short ×2, ETH short).
Nothing here was chosen after seeing an outcome, because there are no outcomes.**

Server agenda item 1. Same discipline as `PREREG_OI_2026-10-11.md`. The server will quote this file's
SHA-256 so it is tamper-evident; **if it is edited after that commit, the pre-registration is void and
must be declared void here.**

---

## 1. ⚠️ First: the proposed null is biased, so I am not using it

The agenda asked for *"random-side same-geometry ideas on the same coin/time."* **That null is not
neutral.** Under a driftless random walk with a stop at distance `a` and a target at distance `b`,
`P(target first) = a/(a+b)` — **the base rate is set entirely by the geometry.** Mirroring the side
swaps risk and reward, so it changes the base rate:

| idea | risk | reward | real `P(target)` | flipped `P(target)` | bias |
|---|---|---|---|---|---|
| BTC short | 2050 | 1950 | 51.2% | 48.8% | **+2.5 pts to the real side** |
| BTC short | 2700 | 3300 | 45.0% | 55.0% | **−10.0 pts** |
| ETH short | 95 | 125 | 43.2% | 56.8% | **−13.6 pts** |

**Averaged over the three live ideas the flip null would penalise Claude by ~7 points before any skill
is involved** — and the sign depends on whether Claude happens to generate reward>risk or reward<risk
ideas. **The bias is not even stable.**

**Instead:** test each idea against **its own geometry-implied rate**. No synthetic ideas needed.

## 2. The hypothesis, as a falsifiable claim

**H1.** Claude's ideas hit their target before their stop **more often than their own geometry implies**
under a driftless random walk.

**H0.** They hit at exactly the geometry-implied rate — i.e. the ideas carry no directional information
beyond where the levels were placed.

**Statistic:** `mean( hit_i − null_i )` across resolved ideas, where
`null_i = risk_i / (risk_i + reward_i)` and `hit_i = 1` if the target resolved before the stop.
**Unbiased under H0 by construction.**

## 3. Data and grading — fixed now

- **Source:** `server_exports/ai_plans.json`, ideas with `source == "ai"`.
- **Grading:** the server's existing `plans._walk` — **limit fills, stop-first ties, adverse-side
  fill-candle rule, 48h max hold, 9 bps.** I am adopting the server's grader as-is and **not** writing
  my own, so there is no convention for me to pick.
- **Resolution:** an idea counts only once `result` is populated. Ideas that never fill, or that reach
  48h unresolved, are **excluded from the hit-rate test and counted separately** — see §6.
- **Fields used:** `coin, side, entry, stop, target, entry_type, entry_window_h, max_hold_h, result`.
  **`confidence` is NOT a predictor in this test** — see §7.

## 4. Power, and the date a verdict becomes possible

`hit_i − null_i` is Bernoulli-centred, so SD ≈ 0.5 and MDE at 80% power = `2.8 × 0.5 / √n`.
**Idea rate: 2/day** (the server's figure).

| edge over geometry | ideas needed | days at 2/day |
|---|---|---|
| **+5 points** | **784** | **392** |
| +7.5 points | 348 | 174 |
| **+10 points** | **196** | **98** |
| +15 points | 87 | 44 |
| +20 points | 49 | 24 |

**Pre-committed schedule:**
- **One interim look at n = 87** (a +15-point edge is detectable), at **α = 0.005**.
- **Final analysis at n = 196**, at **α = 0.048** — the smallest edge I consider plausibly real.
- **No other looks.** At 2/day, n=196 lands around **2027-01-17**.
- Until an analysis date, **the only thing I report is the resolved count.**

**I am stating plainly now: a 5-point edge is out of reach.** It would take over a year, and the idea
rate would have to hold. If the true edge is small, this test will never resolve it.

## 5. Decision rules — fixed now

| condition | verdict |
|---|---|
| CI excludes zero, and resolved n ≥ 196 | **FINDING**, with the edge in points |
| CI excludes zero at the interim, α = 0.005 | **FINDING**, reported early |
| CI includes zero at n ≥ 196 | **NULL**, reported with the MDE so it reads as "no edge above X points" |
| fill rate < 50% | **VOID** — see §6; the test would be about Claude's level-placing, not its direction |

## 6. The trap I expect, written down before it happens

**These are limit orders with a 24h entry window.** If Claude places entries that mostly do not fill,
the resolved set is **selected on price having come to the level** — which is itself directional
information, and the hit rate among fills would not be a clean test.

**So I will report, every time: ideas generated, ideas filled, ideas resolved.** If the fill rate is
below 50% the test is **VOID**, not null, and the honest question becomes a different one.

## 7. Commitments

1. **Published whichever way it comes out**, in `IDEAS_GRADED.md`.
2. **`confidence` (1–5) is not used as a predictor here.** Three separate measurements already suggest
   the project's confidence fields run mildly backwards (`LLM_PIPELINE.md`), so testing ideas × confidence
   would be a second hypothesis riding on this one. **If it is tested later it gets its own
   pre-registration.**
3. **No subgroup hunting.** If the primary is null I will not go looking for the coin, side, or setup
   where it works.
4. **No new predictor, horizon or exclusion** after an outcome is seen. Additions are amendments,
   declared as such.
5. **What would make me abandon H1:** a null at n = 196 with the CI inside ±5 points.

## 8. Known limits, acknowledged in advance
- **All three live ideas are SHORTS.** If that persists, the test measures Claude's short-side ideas and
  nothing else, and I will say so rather than generalising.
- `null_i` assumes a **driftless** walk. Real drift over 48h is small (the owner's trades run ~3h median;
  a 48h bracket sees roughly 0.03% of trend) but not zero, so `null_i` is approximate. **It is unbiased
  with respect to Claude's choices, which is what matters here.**
- The grader is the server's. If `plans._walk` changes, this pre-registration applies to the version
  live on 2026-10-11 and must be re-stated.
- One bot, one venue, one idea generator.
