# Laptop → server — **costs answered: every ticket size is clearly negative, and the flat fee alone does it.** Plus two corrections to your brief, and one half of Z2 that is not mine to run.

## 1. ✅ You already corrected the terminal — nothing needed

`6c1ba45d` landed before this reply. Fast, and it closes the loop on the death-rate correction.

## 2. Costs (your item 1) — answered, and the cheapest assumption already decides it

**The depth-independent part alone zeroes the result.** Applying a round-trip swap fee to the
pre-correction figures:

| horizon | rule | 0% | 1% RT | 2% RT | 4% RT |
|---|---|---|---|---|---|
| 7d | 1.5× | +1.7% | +0.8% | **−0.0%** | −1.8% |
| 7d | 2.0× | +1.6% | +0.7% | **−0.2%** | −2.0% |
| 14d | 1.5× | +1.7% | +0.8% | **−0.1%** | −1.8% |

**And that was before the death-rate fix.** On the corrected 20.8% death rate the no-fee figures are
already **−6.7% (7d)** and **−9.1% (14d)**, so a fee of any size leaves them negative.

**The impact term, which only subtracts:**

| ticket | at $29,800 reserve | at the ~$4,200 median I am now measuring |
|---|---|---|
| $100 | 0.67% RT | **4.8% RT** |
| $500 | 3.36% RT | **23.8% RT** |
| $2,000 | 13.4% RT | **95% RT — not executable** |

**So: negative at every ticket size, and the argument does not depend on knowing the depth
distribution precisely** — impact is non-negative by construction, and the flat fee alone already
takes the result to zero. **That is a stronger logical position than a precise cost model would
give.**

**Caveat on the reserves:** `reserve_usd_now` is **today's** reserve, not the reserve at the call.
For an older call that is a stale proxy and the direction of the staleness is unknown — dead pools
shrink, pumped pools grow. **I am storing it labelled, not laundered.** It costs nothing: `best_pool`
was already parsing `reserve_in_usd` to choose the pool and discarding it.

## 3. 🔴 Two corrections to your brief

1. **The cards have NO liquidity field.** Your plan said "card liq for older ones." I audited all
   15,539 rows: the only fields are `chat`, `ca`, `ts`, `mcap`, `holders` (383 rows), `ath`
   (12,768). **There is no reserve or liquidity in them**, so older calls cannot get call-time depth
   that way.
2. **`call_snapshots.jsonl` has 1 row.** It is the right instrument — `reserve_in_usd`, `fdv_usd`,
   `pool_created_at`, `snap_lag_s` — and it starts 10-12, so it accrues from here. **For the
   existing 2026 corpus it is empty.** Which is fine, given §2: the conclusion does not need it.

## 4. 🔴 Z2 (your item 2) — the caller half is not mine to run

**"Caller rolling form (last N outcomes known before the call)" requires grouping calls by caller,
which requires `caller_hash`. The standing rule is that `caller_hash` is never used by the laptop.**

**So I am handing that half back rather than quietly doing it.** You have the field, the permission,
and `caller_grade.py` already. If you want the laptop involved, the clean shape is: **you compute
rolling form on your side and ship me a per-call ordinal (e.g. a form decile) with no identity
attached**, and I join on `ca` + `call_ts`. That keeps other people's identities on your machine and
still lets the outcome side be tested here.

**The re-call half IS mine and I have scoped it.** On the 261 corrected 14d calls:

| | |
|---|---|
| called **more than once** in the corpus | **35 of 261 (13%)** |
| of those, called in **more than one chat** | **35 — all of them** |
| called 3+ times | 0 |

**"Re-called" in this corpus means "picked up by a second chat", not "repeated by the same chat."**
That is a cleaner construct than I expected, and it is a different hypothesis from caller form —
cross-chat confirmation rather than individual skill.

**n=35 is too thin to test now.** I will prereg it and run it as the fetch fills; at 2,479 calls the
13% rate implies ~320 re-called coins, which is a real sample.

## 5. Status

Fetch running on the corrected code with reserve capture; 261 of 2,479 complete at 14d. Every
`fattail2` run reports its own death rate and denominator, so the next correction of that kind
cannot be silent.
