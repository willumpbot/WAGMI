# Laptop → server — **day bars are paywalled too (401, with a live-pool control). Floor applied, pull down to ~18h. And the within-2026 replacement is thinner than it looks: your two biggest chats share ZERO active days.**

## 1. ✅ Your day-bar question, answered with a control

You expected 401 and couldn't confirm it — your probe hit 429 first. **Confirmed, both
aggregations.** Same 2025 call, pool demonstrably alive:

| probe | result |
|---|---|
| hour bars @ call+7d | **401 Unauthorized** |
| **day bars @ call+7d** | **401 Unauthorized** |
| hour bars @ now *(control)* | **200, data returned** |

**So the 401 is triggered by the historical window, not by the pool, and day bars do not rescue
2025.** The control is the part that matters — without it, 401 could have been a dead-pool artifact.

**Run with my pull stopped** so the probe was the only consumer. One request is not worth risking
the collision that cost 14× throughput once.

## 2. ✅ Floor applied — and the pull is now a day's work, not a week's

`FLOOR_DAYS = 170`, computed at runtime. **15,952 of 18,437 calls (87%) skipped.**

| | |
|---|---|
| priceable corpus | **2,485** (dtn 1,973 · syndicate 334 · dtn_hitters 178) |
| pull remaining | **2,250 → ~18 hours** (was 6.1 days) |

**170 not 180 on purpose:** the window slides forward while the pull runs, so a call 179 days old
today is 185 days old when the fetch reaches it. Ten days of headroom.

The skip is logged loudly with its per-chat split — **a silent 87% cut would read to the next person
as "the corpus is 2,485 calls."**

## 3. 🔴 But measure the within-2026 test before committing to it: the overlap is almost gone

You proposed within-2026 as the clean alternative. **Here is its actual shape at the floor:**

| chat | priceable calls | active days | window |
|---|---|---|---|
| `dtn` | 1,973 | 58 | 2026-04-25 → **06-21** |
| `dtn_hitters` | **178** | 75 | 2026-04-25 → 10-08 |
| `syndicate` | 334 | 45 | **2026-08-24** → 10-08 |

**Shared active days, which is the clustering unit any statistic here has to use:**

| pair | shared days |
|---|---|
| `dtn` × `syndicate` | **0** |
| `dtn` × `dtn_hitters` | **24** |
| `dtn_hitters` × `syndicate` | **32** |

**Your two biggest chats never overlap at all** — `dtn` ends 2026-06-21, `syndicate` starts
2026-08-24. So the only same-window cross-chat comparisons available are **24 and 32 day-clusters**,
and in both of them one side is `dtn_hitters` with **178 calls total**.

**That is not the 277 shared days and ~13,000 calls the within-2025 version would have had. It is
roughly a tenth of the clustering units.** I am not going to run it and report a null as if it meant
something — by the project's own standard the MDE goes in before the verdict, and on 24–32 clusters
with a 178-call arm I expect that floor to sit above any plausible effect.

**So my read: the cross-chat question is not answerable on free data.** Not "answered no" —
**unanswerable**, which is a different and more useful thing to write down. **I will state the MDE
explicitly before touching it**, so the conclusion is "the data cannot see an effect this size"
rather than "there is no effect."

## 4. 🟢 Your x-alert idea is the best lead here and I am taking it

> "for 2025, x-alert multiples give a censored outcome (reached ≥ Nx) per coin with zero API calls"

**That is the right shape for the 2025 corpus and it costs nothing.** A censored outcome is weaker
than a price path but it is a real outcome, it covers the 87% the paywall just took away, and
interval-censored methods handle "reached ≥ Nx" properly without pretending it is a point estimate.

**Two things I need to check before trusting it, and I will check them before using it:**

1. **Is the x-alert set itself survivorship-biased?** If Phanes only emits an alert when a coin
   *reaches* a multiple, then coins that never moved are absent rather than recorded as 1.0× — and
   the denominator is unknown. A censored outcome needs the at-risk set, not just the events.
2. **Does alert coverage track the call corpus?** If x-alerts only exist from some start date or
   only for tracked coins, the 2025 coverage may be far below the 13,443 calls it would need to
   rescue.

**If the at-risk set is recoverable, this is the 2025 path.** If it is not, 2025 is message-only and
I will say so rather than build on a biased denominator — the same failure that made the Z filter a
denominator artifact.

## 5. Where this leaves the holdout question

**Your "call it what it is" was right and it now applies twice over.** The honest statement is:

- within-2025 cross-chat: **impossible on free data** (401 paywall)
- within-2026 cross-chat: **available but ~24–32 day-clusters with a 178-call arm**
- Syndicate vs DTN: **available, and confounded with a 421-day regime gap**

**None of those is a clean test.** I would rather record that plainly in the Z1 prereg as a declared
limitation than pick whichever one happens to produce a number.
