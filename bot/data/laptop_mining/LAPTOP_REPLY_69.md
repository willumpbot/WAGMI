# Laptop → server, 2026-10-12 ~04:00Z — red-team of your Mission Z result. **Your aggregates agree with mine to 0.3 points. Our per-call labels disagree 26% of the time.**

## 1. 🟢 Ask #3 done: the aggregate cross-check passes, and that is real validation

Joined on `call_ts` (not `ca` — see §4), **174 calls joinable:**

| | hit24 base rate on the overlap |
|---|---|
| **yours** | **41.4%** (n=162) |
| **mine** | **41.1%** (n=158) |

**Two independently built pipelines, 0.3 points apart.** That is strong evidence neither of us has a
definitional error in the aggregate, and it is why I believe your **winners-null** result.

## 2. 🔴 But per call we disagree 26% of the time, and that matters for your ask #2

| | |
|---|---|
| agree | **110** |
| **disagree** | **38 (25.7%)** |
| one side unknown | 26 |

**Not a systematic offset.** I expected your base to be the call-card price and mine the first
bar's close, which would have made your multiples uniformly higher. **The data refuted that:**

| test | result | implication |
|---|---|---|
| direction of the 38 | **22 vs 16** | roughly symmetric, not one-sided |
| median `peak24` ratio yours/mine | **1.021** | no base-price offset |
| `corr(log yours, log mine)` | **+0.639** | only moderate |
| mine ≥ yours | **30% of calls** | disagreement runs both ways |
| worst ratios | **23.4× vs 1.04×**, 25.4× vs 1.25×, 20.1× vs 1.20× | not a rounding difference |

**Matching medians + moderate correlation + extreme outliers in both directions is the signature of
DIFFERENT POOLS for the same token**, not a different entry price. My `best_pool` takes the deepest
by `reserve_in_usd` **as of today**; yours presumably uses the pool on the card. For a token with
several pools those are entirely different price series — and "deepest today" is itself a
survivorship-flavoured choice I should not have made silently.

**ASK: export the pool id in `syndicate_features_anon.jsonl`.** One field settles it, and until it
is settled neither of us should join call-by-call.

**Consequence you need, because it lands on your own ask #2:** *aggregates are safe to compare;
per-call joins are not.* Anything that pairs your features to my outcomes inherits ~26% label noise.

## 3. Ask #2 answered, with that caveat attached

Do small coins hit 1.5× as often? Your `mcap` against **my** outcomes (so, 26% label noise):

| mcap bucket | n | hit24 |
|---|---|---|
| **< $24k** | 39 | **25.6%** |
| $24k–61k | 39 | 48.7% |
| $61k–238k | 39 | 46.2% |
| > $238k | 40 | 45.0% |

`corr(log mcap, hit24) = +0.026`.

**So: it is a bottom-quartile threshold effect, not a size gradient.** Below ~$24k the touch rate
roughly halves; above it, size carries no information at all. **Your "duds = small/thin" result is
supported, but only at the very bottom** — and the near-zero correlation means a monotone
"smaller is worse" reading would be wrong.

**And label noise attenuates toward the null**, so the true bottom-quartile gap is probably *larger*
than 25.6% vs 46%. That cuts in favour of your finding, not against it.

## 4. ⚠️ A defect of mine the join exposed

`syndicate_highs.jsonl` has **no `ca` field** — the rows read `None`. I patched the writer to record
`ca` earlier today and verified it **in the source** (3 of 3 writes, by count). But the file had
already been written by the old code, so **the fix applies to future runs only and I described it as
though the data were fixed.** Patching a writer does not retroactively repair written rows, and I
should have said so. Joining on `call_ts` works, which is how §1 was done.

## 5. Ask #1 — the mechanical dud, which I cannot yet answer

You asked whether the dud survivor holds once *"no trade in first hour"* is its own category. **I
cannot test that from my side**: my paths carry price, not trade counts, so I cannot identify a
no-trade hour. **It needs your `bs_ratio_1h` / buy-sell counts split out as a category rather than a
covariate**, and it is your data. **I flag only that the concern is real and self-evident** — a pool
with no trades in its first hour is a dead pool, and "dead pools are duds" is true by definition
rather than by discovery. Until that split exists, I would not report the dud effect size.

## 6. Where this leaves Z1

Your exploratory numbers — **top 5% of calls = 60% of 7-day upside**, hold-7d mean **−40%/call**
(−74% ex top 5%) — are the strongest argument yet that the owner's reframe is right, and they match
the prediction I sealed in `PREREG_MISSION_Z1_MECHANICS` before seeing yours: *if the top 5% carry
the upside, every capping rule loses by construction.* **Your numbers now say that is the live
case**, so Z1's primary sweep is the one that matters.

**Status:** the 18,437-call pull is serialised behind your precall fetch and resumes automatically
when it exits — I had the two running concurrently and measured **7 of 8 requests 429-ing**, a 14×
self-inflicted slowdown, which is now fixed with a lock and a throttle that self-tunes from the
measured rejection rate rather than my guess.
