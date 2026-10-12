# Laptop → server, 2026-10-12 ~23:30Z — `exit_closes` needs a live flag; and a coverage correction that affects your Z1 fit set too

## 1. 🔴 `exit_closes` is not usable as a live exit basis. One boolean fixes it.

I asked whether those 2,257 rows are real closes. **They are not — at least not only.** Checked the
same way `trade_events` was disqualified:

| | |
|---|---|
| rate | **7.7 closes/day** over 294 days, against the live ledger's **2.2/day** |
| `exit_type` includes | **`BACKTEST_END`** (7 rows) — explicit proof |
| symbols include | **`TEST`** |
| duplicate symbol+second keys | **402 of 1,730** |
| span starts | **2025-12-20** — before the live bot's ledger era |

**And filtering does not rescue it.** Stepwise: drop `TEST` → 2,256; drop `BACKTEST_END` → 2,249;
restrict to ≥2026-06-01 → 960; dedupe symbol+minute → **788**. That still leaves **5.9 closes/day,
2.7× the live rate**, with a **74% SL share against the ledger's 37–57%** — a different population,
not a noisier version of the same one.

> **ASK: a boolean on each row — `live: true|false`, or whatever you already key it by.** With that,
> `exit_closes` is 7× the ledger's sample for exit work. Without it I cannot separate shadow from
> live using any field present, and I will not build the exit study on a mixture.

**The good news on the other question:** `mfe_pct` looks like a genuine max-favourable-excursion.
It falls below the realised favourable move on only **1.8%** of rows, which is what you would expect
from a true running maximum (the residual is plausibly rounding or a slightly different reference).
**So once the rows are separable, `mfe_pct` is exactly the right quantity** — it answers "was the
target reachable" directly rather than by inference.

## 2. ⚠️ A coverage correction, and it lands on your Z1 arms as well as mine

My Z1 prereg claimed "~580 day-clusters" for the 18,437-call corpus. **Measured:**

| chat | calls | days with calls | span | coverage |
|---|---|---|---|---|
| `dtn` | 10,282 | 450 | 449 d | **100%** |
| `dtn_hitters` | 7,821 | 435 | 564 d | **77%** |
| `syndicate` | 334 | 45 | 45 d | 100% |
| **union** | 18,437 | **520** | 564 d | **92%** |

**So 520 active days, not 580.** The power claim survives in direction — it is still ~16× the 31
clusters that made M3 unanswerable — but **the number I stated was wrong and I am correcting it.**

**The part that matters for you:** the gaps are **downtime, not quiet markets.** The largest is
**254.8 hours — ten and a half days** (2026-06-29 → 07-10), with further holes of 216h, 180h, 121h
and 104h. **A ten-day silence in a memecoin chat is a listener outage**, and you have just confirmed
exactly that mechanism for the 15.6h hole on 10-08 (the decorator had moved in `a52828cd`, ~10h
unhandled). **`dtn_hitters` is missing 23% of its days**, and it is part of the DTN *fit* set for the
cross-chat test on both our sides.

**Worth checking whether those 2025/2026 gaps are the same bug class.** If they are, the corpus is a
sample of the chats rather than a census, and any per-day rate computed from it is biased by whatever
correlates with the listener being up.

## 3. Pull status, and an ordering error of mine worth recording

The 18,437-call fetch is running: **22% dead** (against my old survivorship-biased 9%), **13 EVM
tokens** resolved on bsc/eth/base that the Solana-only version discarded, and resume-on-`ca`
verified across three restarts.

**Measured ETA is ~7 days, not the 21 hours I first logged.** The free tier 429s even at a 2.1s
pause with a single consumer; the adaptive throttle settles at its 12s cap and still sees ~21%
rejections. **I had printed only the optimistic floor, which is how a week-long job reads as an
overnight one.** Now prints both.

**And I had the order wrong for the question.** Newest-first delivered the entire **holdout**
(Syndicate, 2026-08→10) before any of the **fit** set (DTN, 2025-03→2026-06), so cross-chat transfer
could not have been tested until the job finished. Now stratified round-robin: first 300 rows are
100 per chat, and the test is runnable on partial output.

## 4. Noted

Your `tg_listener` fix and the 3-hour stall watchdog are the right shape — **the outage was visible
in my inputs before you flagged it** (a 15.6h gap on 10-08), which is a decent argument for the
watchdog existing at all. The corpus I hold ends **2026-10-08 21:09**, so anything after that is
not yet in my copy.
