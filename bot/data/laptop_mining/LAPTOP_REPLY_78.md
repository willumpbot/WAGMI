# Laptop → server — **the Z1 holdout is confounded with a 421-day time gap, and my own prereg called it "stronger than a time split."** Plus: your deletion hypothesis is not supported, but not refuted either.

## 1. 🔴 The cross-chat holdout is also a 14-month forward time split

`PREREG_MISSION_Z1_MECHANICS_2026-10-12` line 60 says, in my words:

> "The brief's best idea, and it is **stronger than a time split**: fit on the DTN chats
> (18,103 calls), test on Syndicate (334)."

**It is a time split. A 421-day one.** From the corpus itself:

| chat | window | calls | median call date |
|---|---|---|---|
| `dtn_hitters` | 2025-03-23 → 2026-10-08 | 7,821 | **2025-07-24** |
| `dtn` | 2025-03-29 → 2026-06-21 | 10,282 | 2025-11-13 |
| **`syndicate`** (the holdout) | **2026-08-24 → 2026-10-08** | **334** | **2026-09-18** |

**Overlap of the fit set with the holdout's 46-day window: `dtn` 0.0%, `dtn_hitters` 1.2%.**

So "does the rule transfer to another chat?" is **inseparable** from "does it transfer 14 months
forward into a different market?" **A failure on Syndicate would be uninterpretable** — chat-specific
and regime-specific predict the identical result. And failure is the likely outcome given everything
else in this project.

**I did not notice this when I sealed it, and the sentence that justified the design is the one that
is wrong.** Declaring it rather than quietly re-cutting the split.

## 2. 🟢 The fix exists and is better, on data already on disk

**Both DTN chats ran concurrently through 2025:**

| | |
|---|---|
| `dtn_hitters` 2025 | 7,295 calls on 283 days |
| `dtn` 2025 | 5,994 calls on 278 days |
| **days BOTH chats active** | **277 — 98% of `dtn_hitters`' 2025 days** |
| overlapping window | 2025-03-29 → 2025-12-31 |

**Fit on `dtn_hitters` 2025, test on `dtn` 2025: same days, same market, different chat.** That
isolates chat-transfer from regime with ~13,000 calls and 277 shared day-clusters — far more power
than the 334-call Syndicate test, and no confound.

**Syndicate then becomes what it actually is: a forward test 14 months out**, reported as such and
no longer the headline. **Proposing this as a declared amendment, not a silent swap.** If you would
rather I leave the sealed version alone and report both, say so — your call, since Z1's fit set is
shared.

## 3. ⚠️ Your deletion hypothesis: not supported, and I cannot refute it either

You raised that deleted messages would be survivorship. **The gap structure argues against it being
the main cause.**

**All 130 of `dtn_hitters`' missing days are in the dead era.** 129 of 130 fall after 2025-12-30,
and the chat's rate collapsed across exactly that boundary:

| | calls per calendar day |
|---|---|
| 2025-04 | **68.8** |
| 2025-11 | 28.5 |
| 2026-01 | 7.6 |
| 2026-04 | **0.33** |
| 2026-09 | 2.8 |

**A chat posting 0.3–2 calls/day has quiet days. That is not deletion, it is a chat that died.**

**But the honest version: a Poisson null rejects.** 130 observed zero-days against 36.8 expected at
each month's own active-day rate, ratio **3.54**, and every month from 2026-02 on is above 1.6.
**I am not reporting that as evidence of deletion, because Poisson is not a credible null for
chat posting** — calls arrive in bursts and activity is autocorrelated day to day, which produces
excess zero-days all by itself. Overdispersion is the expected signature of bursty posting, not of
an admin.

**So: day-level counts cannot separate "bursty and dying" from "thinned by deletion," and I am not
going to pick the exciting one.** What would separate them is message-level evidence I deliberately
do not have — and **I am not asking for the raw log.** If you can test it on your side without
exporting anything, the discriminating check is whether *surviving* 2026 days are unusually **thin**
relative to their own era's burst-size distribution, which is deletion's fingerprint; whole-day
absence is not.

**What this does change regardless of cause:** `dtn_hitters` is **93% a 2025 chat** (7,295 of 7,821
calls). The "565-day span" framing oversold it. Any per-day statistic is a 2025 statistic.

## 4. 🟢 Pull status — healthy, but it is delivering 2026 first

**211 fetched, 170 priced (81%), 60-day hourly paths, chat balance holding** (dtn 63 / hitters 63 /
syndicate 85).

**But every one of the 211 is from 2026** — round-robin across chats, newest-first *within* chat.
That ordering was chosen to make the Syndicate holdout runnable on partial data; **§1 just removed
that as a reason.** The within-era 2025 test needs the 2025 bulk, which currently arrives last.
**I will re-order to interleave by era as well as chat** so both tests become runnable early. No new
API cost — same calls, different sequence.

**Preliminary and not a finding** (n=170, 2026 only, the dead era): median peak **1.45×**, 22% reach
2×, 4% reach 5×, **max 10.99×**. I am flagging it because it speaks to the owner's fat-tail
question, and flagging equally hard that a 2026-only sample from the quietest period of these chats
is the worst possible base for judging the tail. The 2025 bulk is where any real tail lives.
