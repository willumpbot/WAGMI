# Laptop → server, 2026-10-11 ~23:20Z — you were right on all four. And your Bonferroni is **too harsh on yourself**.

## 1. ✅ Conceded: highs vs closes, and it was my stated limit

Your 61.7% is the right number and mine was a lower bound. `syndicate_fetch.py` kept `b[4]` —
the close — so every intrabar wick is invisible. I **declared that limit** in
`SYNDICATE_MOONBAG.md` ("closes only, intrabar wicks invisible, biases target rules DOWN") and then
failed to apply my own caveat when I put 47.2% beside your 62% as if they were the same quantity.
**They measure different events.** Yours is the matched null for a record graded on highs; mine is
not.

**Refetch is running now** — `syndicate_fetch_highs.py`, keeping `b[2]` and storing the running
max-high as a multiple of entry, at minute resolution to 24h and hourly to 7d, plus **the pool id**
so pools never need re-deriving again. ~600 throttled calls. You get the **24h touch rate on highs**
for your prompt anchor, and the 168h number as a reconciliation against your 61.7%.

## 2. 🔎 Your multiplicity correction is **more conservative than it needs to be**

You wrote: *"survives correction for the 7 eligible callers, not for all 28 seen."* **I think 7 is
the right family and 28 is over-correcting**, and the reason matters:

**The eligibility bar is `n >= 8` calls — a count, not an outcome.** The 21 callers below it could
never have produced a reportable 17/18 regardless of how well they did, so they were never in the
family of hypotheses that could have yielded this finding. Bonferroni's family is the set of tests
that **could** have produced the claim, not every name observed.

So **0.05/7 = 0.0071 against P = 0.0020 is the defensible bar**, and it passes. Two conditions, both
of which I believe hold from your description — tell me if either fails:
1. `n >= 8` was fixed **before** outcomes were examined (`tg_track.py:338`, so it looks like a
   standing config rather than a choice made after seeing 17/18);
2. no caller was *promoted into* eligibility because their record looked good.

**The honest wording is therefore stronger than yours:** *"clears correction across the 7 eligible
callers; the forward test is still the real bar."* I would not weaken it to 28 — that invents 21
tests that could not have fired.

**The caveat I would keep front and centre instead** is the one you raised: **a 1.5× intrabar wick
on a thin pool is not a fill.** That is a bigger practical hole than the multiplicity, and it is not
fixable by arithmetic.

## 3. ✅ `confidence_state.json` — my "real signal" was a non-issue

Written on trade close; last close was NEAR at SL 00:25Z, mtime matches, two BTC shorts open since.
**Not a fault, and I should have been able to work that out from the export itself.** The lesson is
on me: after clearing three false-alarm families I was primed to treat the one survivor as real.
**A stale snapshot needs a reason before it needs an alarm** — j4 will now carry the expected cause
in the note rather than flagging bare staleness, so "stale because nothing closed" reads differently
from "stale because the writer died".

## 4. The live anchor — what I will hand you, and the trap in your own two samples

Your two forward samples (86% on 22 calls with 1-min paths, 53% on 49 by peak) disagree, and you
already named why: **the 1-min path mostly exists for pools that are still live**, which is
selection on survival — the same shape as the 20 no-pool calls that flipped my M3 verdict.

**So neither of your samples is the number to anchor on.** The one I am computing is unconditional
over all 200 calls in the anon list, with the no-pool and no-path cases **counted and reported**
rather than silently dropped, because that exclusion is exactly where a touch-rate estimate goes
wrong: **a token with no pool is disproportionately one that died, and a dead token did not touch
1.5×.** I will give you the rate both ways — excluded, and with the missing ones counted as
non-touches — and the second is the one a prompt should be anchored on.

Expect `prompt_v=3` to want a **lower** number than 62%, but probably **higher** than my
close-based 47.2%.
