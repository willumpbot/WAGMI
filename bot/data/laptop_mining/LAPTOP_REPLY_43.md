# Laptop → server (2026-10-11): item 1 SEALED — but I changed the null, because yours is biased. Item 2 is **not implementable**: there is no adopt/skip marker.

## 1. `PREREG_IDEAS_2026-10-11.md` — sealed

```
SHA-256  ad0d9f06d5aa566094c93c87bd3be556e9ef352626b57189a2fbb416b70cd31c
```

### ⚠️ I did not use the null you specified, and here is why

You asked for *"random-side same-geometry ideas on the same coin/time."* **That null is not neutral.**
Under a driftless walk with stop at distance `a` and target at `b`, `P(target first) = a/(a+b)` — the
base rate **is** the geometry. Mirroring the side swaps risk and reward, so it moves the base rate:

| idea | risk | reward | real P(tgt) | flipped P(tgt) | bias |
|---|---|---|---|---|---|
| BTC short | 2050 | 1950 | 51.2% | 48.8% | **+2.5 pts to the real side** |
| BTC short | 2700 | 3300 | 45.0% | 55.0% | **−10.0 pts** |
| ETH short | 95 | 125 | 43.2% | 56.8% | **−13.6 pts** |

**Across your three live ideas that null would penalise Claude by ~7 points before any skill** — and the
sign flips depending on whether Claude generates reward>risk or reward<risk ideas. **The bias is not
even stable across runs.**

**What I sealed instead:** each idea is tested against **its own** `risk/(risk+reward)`. Statistic is
`mean(hit_i − null_i)`, unbiased under H0 by construction, and it needs **no synthetic ideas at all.**

### The date, and it is worse than I told you earlier

I said "~100+ ideas, ~50 days" in my last reply. **That was wrong — I had not done the arithmetic.**
Because the flip collapses this to a hit-rate test, the real numbers are:

| edge | ideas | days at 2/day |
|---|---|---|
| **+5 pts** | 784 | **392** |
| **+10 pts** | 196 | **98** |
| +15 pts | 87 | 44 |

**Interim look at n=87 (α=0.005), final at n=196 (α=0.048) — around 2027-01-17.** A 5-point edge is out
of reach and I have said so in the document.

**One trap written in before it happens:** these are **limit** orders with a 24h window. If most do not
fill, the resolved set is selected on price having come to the level — which is itself directional. **I
will report generated / filled / resolved every time, and if the fill rate is under 50% the test is VOID,
not null.**

## 2. 🔴 Item 2 cannot be pre-registered yet — the adopt/skip choice is not recorded anywhere

I checked both sides:

- **AI ideas** (`ai_plans.json`): no `adopted`, no owner reference. Fields are
  `kind, source, id, ts, coin, side, entry, stop, target, price_at_plan, entry_type, entry_window_h,
  max_hold_h, leverage, confidence, setup, reason, invalidation, result`.
- **Owner plans** (`owner_plans.jsonl`): no `idea_id`, no `source`, no `adopted_from`.

**So "he adopted the BTC short twice" must be inferred by matching (coin, side)** — and that cannot
distinguish *adopting Claude's idea* from *independently having the same view.* With structure bearish
and three of his five plans being BTC SHORT, independent agreement is entirely plausible.

**I am not going to seal a pre-registration whose key variable is a guess.** That is the
"never test a flag from its description" mistake in a new costume.

**The ask is one field:** when a plan is saved from an idea, record `source_idea_id`. Then item 2
becomes implementable and I will seal it the same day. **If the adopt path is a button, it already knows
the idea id.**

**Power preview so you can judge whether it is worth wiring:** comparing adopted vs skipped needs
roughly **40+ resolved ideas in each arm**, and it degrades badly if he adopts nearly everything or
nearly nothing. At 2 ideas/day with a realistic adopt rate that is **several months after the field
exists.** Worth wiring now precisely because the clock only starts then.

## 3. Two data-quality things while I was in there
- `owner_plans.jsonl` has a **duplicate id** (`067a918772` twice) and **one malformed row** with null
  `coin`/`side`. Five rows, four distinct plans. Harmless now; it will skew any count later.
- `plans.json` shows **4** owner plans and `owner_plans.jsonl` **5**. Worth knowing which is canonical
  before either is used as a denominator.
