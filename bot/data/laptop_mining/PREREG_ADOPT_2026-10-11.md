# PRE-REGISTRATION — does the owner's adopt/skip choice add anything over taking every Claude idea? Written 2026-10-11, at n=0 recorded decisions.

**Status: SEALED. Written the day `source_idea_id` / `adopt_mode` went live (`602291cb`), before a
single prospectively-recorded adopt decision exists.**

Server agenda item 2. Companion to `PREREG_IDEAS_2026-10-11.md` (SHA `ad0d9f06…`). The server will quote
this file's SHA-256; **if it is edited afterwards the pre-registration is void and must be declared void
here.**

---

## 1. 🔴 Inferred links are excluded. This is the whole reason the document exists.

Yesterday I declined to pre-register this because the adopt/skip choice was **not recorded** — "he
adopted the BTC short twice" could only be inferred by matching coin and side, which cannot distinguish
*adopting an idea* from *independently reaching the same view*. Three of the owner's five plans are BTC
shorts in a bearish structure; independent agreement is entirely plausible.

**The server has now wired it properly**, and importantly **the backfill is marked**: older plans whose
link was recovered from the reason text carry **`source_inferred: true`**.

**Fixed now, and not revisable:**

> **Only rows where `source_inferred` is absent or false count as decisions.** Backfilled links are
> reported separately and **never enter the test statistic.**

The backfill regex (`Claude idea (ai[0-9a-f]{8})`) requires an explicit idea id in the text, so it is far
safer than a coin/side match — **but it is still a reconstruction, and reconstructions do not go in.**

## 2. The hypotheses

**H1 (the one that matters).** Ideas the owner **adopts** beat ideas he **skips**, on the same
geometry-relative measure used in the ideas prereg.

**H2 (secondary, reported second).** Adopted ideas beat **all** ideas — i.e. his selection adds something
over a policy of taking everything.

**H0.** No difference. His adopt/skip carries no information about which ideas work.

**Statistic:** `mean(hit_i − null_i | adopted) − mean(hit_i − null_i | skipped)`, with
`null_i = risk_i/(risk_i + reward_i)` exactly as in the ideas prereg.

**Arms, fixed now:**
- **adopted** — `adopt_mode == "adopt"` (one-click take, levels unchanged)
- **adjusted** — `adopt_mode == "adjust"` (took the idea, moved the levels) — **reported separately, not
  merged into "adopted"**, because changing the levels changes `null_i` and is a different act
- **skipped** — an idea with **no** linked plan, once its entry window has closed

**Counting rule (the server's, adopted here):** one decision per `(source_idea_id, levels)`.

## 3. Power — and this is the part to read before hoping

Two-sample on a Bernoulli-centred statistic, SD ≈ 0.5 per arm, so
MDE ≈ `2.8 × 0.5 × √(1/n₁ + 1/n₂)`.

| difference to detect | needed **per arm** | ideas total at a 50/50 adopt rate | days at 2/day |
|---|---|---|---|
| **10 points** | 392 | 784 | **392** |
| **15 points** | 174 | 348 | **174** |
| **20 points** | **98** | **196** | **98** |
| 30 points | 44 | 88 | 44 |

**And it is governed by the smaller arm.** At a 20% adopt rate, 98 adopted decisions needs **~490 ideas
→ ~245 days.** At a 90% adopt rate the *skipped* arm becomes the constraint and it is worse.

**Pre-committed schedule:**
- **One interim look when both arms reach 44** (a 30-point difference is detectable), at **α = 0.005**.
- **Final when both arms reach 98**, at **α = 0.048**.
- **No other looks.** Until then I report only the two arm counts.

**Stated plainly: this needs a 20-point difference to be visible within ~3 months, and 20 points is a
large effect for a human selection layer.** If the owner's judgement adds 5 points, **this test will
never see it** and I will say so rather than implying a null means no value.

## 4. Decision rules — fixed now

| condition | verdict |
|---|---|
| either arm < 98 at the final date | **UNDERPOWERED** — report both arm means and the MDE, no verdict |
| CI excludes zero, both arms ≥ 98 | **FINDING** — his selection adds (or subtracts) X points |
| CI includes zero, both arms ≥ 98 | **NULL**, reported as "no effect larger than the MDE" |
| adopt rate > 85% or < 15% | **VOID** — one arm is too thin, and this is the likeliest outcome |

## 5. ⚠️ The degenerate case I expect, written down now

**The likeliest failure is not a null — it is that he adopts almost everything or almost nothing.** Either
makes the comparison empty. A one-click adopt button makes high adoption easy; a busy phone-first day
makes zero adoption easy.

**If the adopt rate is outside 15–85% I will declare VOID, not null**, and the useful question becomes a
different one: *"does he adopt at all, and what does he do instead?"*

## 6. Commitments
1. **Published either way**, in `ADOPT_GRADED.md`.
2. **Inferred links never enter the statistic** (§1). They are reported as a separate count.
3. **`adjusted` is never merged into `adopted`.**
4. **`confidence` is not a predictor here** — same reasoning as the ideas prereg; it would be a second
   hypothesis riding on this one.
5. **No subgroup hunting** if the primary is null.
6. **What would make me abandon H1:** both arms ≥ 98 with the CI inside ±10 points.

## 7. Limits acknowledged in advance
- **This inherits everything from the ideas prereg**, including the limit-order fill selection: if most
  ideas do not fill, both arms are selected on price having reached the level. **Fill rate under 50% voids
  this one too.**
- **Skips are defined by absence** — an idea with no linked plan. If the owner takes an idea *outside*
  the terminal (manually, on the exchange), it will be recorded as a skip. **There is no way to detect
  that from here**, and it biases toward making skips look better than they were.
- The owner has **4–5 plans total** as of today and **zero recorded adopt decisions**. Everything above
  is a plan for data that does not exist yet.
- `owner_plans.jsonl` currently has a duplicate id and one malformed null-coin row. Both must be cleaned
  before any count is taken, or they will skew the denominator.
