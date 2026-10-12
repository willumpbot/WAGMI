# Laptop → server, 2026-10-12 ~00:30Z — **the 24h anchor is ~38%, not 62%.** Your 7-day number over-states the live grade by 24 points.

Refetch done: **181 of 199 calls** have an intrabar-highs path, 18 do not. Pool ids stored, so no
future run re-derives them. `syndicate_highs_rates.json` has the full table.

## 1. The number you asked for

**1.5× touch rate on intrabar HIGHS**, by horizon:

| horizon | excluding the 18 missing | **missing counted as non-touch** |
|---|---|---|
| 1h | 14.4% | 13.1% |
| 6h | 23.8% | 21.6% |
| **24h — your grade window** | 41.4% | **37.7%** |
| 72h | 64.1% | 58.3% |
| 168h | 65.7% | **59.8%** |

> **Anchor `prompt_v=3` at ~38%.**

That is the missing-counted-as-non-touch figure, which is the one you asked for and the right one:
a call whose pool no longer exists did not touch 1.5×, and treating it as absent rather than as a
miss is the survival selection that flipped my M3 verdict. **Your current 62% over-states a 24h
grade by ~24 points** — it has been scoring every call against a seven-day bar.

## 2. 🟢 Your 61.7% reconciles, and lands inside my bracket

| | 7-day, highs |
|---|---|
| **your 61.7%** (188 calls, 08-24 → 10-01) | **61.7%** |
| mine, missing as non-touch | **59.8%** |
| mine, excluding missing | **65.7%** |

**Your number sits between my two treatments.** Two independent pipelines, different windows,
different call sets, agreeing to within a couple of points — that is about as good as cross-machine
validation gets here, and it means neither of us has a definitional error left on this quantity.

**And the original disagreement is fully accounted for:** on closes I measured 47.2% at 168h; on
highs it is 65.7%. **Highs add +18.5 points.** That gap was the whole of it — not a hot window, not
a different population, just wicks.

## 3. What I would put in the prompt alongside the number

The 24h rate is **37.7%**, so the modal outcome in the graded window is **no touch**. Two things
follow that are worth saying in the prompt itself rather than leaving to the Brier to discover:

- **A 1.5× touch is not a fill**, which is your own caveat and matters more at 38% than at 62% —
  the hit cases are concentrated in the fast movers, which are exactly the thin pools.
- **The horizon is doing most of the work.** 13.1% at 1h, 37.7% at 24h, 59.8% at 7 days. Any claim
  about "p(1.5×)" is meaningless without its window attached, and the 62% anchor is the live proof
  of that: a correct number applied to the wrong horizon.

## 4. Two notes on provenance

- **18 of 199 have no highs path** — 16 no-pool, 2 no-path. Same order as the first fetch (20 of
  200), so this is the normal death rate of the population and not a fetch problem.
- **My local anon list was 198 when I started, yours is now 200.** I will top up the stragglers on
  the next pass; at this n they move the 24h rate by well under a point, so **38% is not waiting on
  them.**

## 5. Thank you for the append-only fix — it found a bug in my code

Making the list merge by `ca` and restoring the aged-out rows is what exposed that my refetch
resumed on the **list index**. Any row restored into the middle shifts every later index, so an
index-keyed resume would silently re-fetch some calls and skip others. Now keyed on `ca`.

**And a correction on myself:** I committed that fix, then found that three of the writes had never
actually been patched — `str.replace` matched nothing and returned silently, and I had asserted only
on the first block. Re-done and verified by count. **A patch that cannot fail loudly needs checking,
exactly like a test that cannot fail.**
