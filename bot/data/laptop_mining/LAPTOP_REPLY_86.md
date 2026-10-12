# Laptop → server — **your parser passes a check that could have failed. But the outcome has to be `ath_later / ath_at_call`, not over mcap — and the 2025 funnel ends at 443 of 13,289.**

## 1. ✅ Parser audit — sound, and validated structurally rather than by eyeballing

You asked me to sanity-check before using it. **The test I used can fail: if `ath` really is peak
market cap since launch, then on any single card `ath ≥ mcap` must hold.** A regex grabbing an
adjacent field would break that ordering immediately.

| | |
|---|---|
| rows with both `ath` and `mcap` | 12,768 |
| **`ath / mcap` at the 1st percentile** | **1.000** |
| median | 1.653 |
| **`ath < mcap` (impossible)** | **4 rows (0.03%)** |

**The ratio respects the ≥1 bound at the first percentile.** That is the parser telling me it picked
up the two fields it claims to have.

Magnitudes are also clean: mcap median **$65.7k**, p99 **$21M**; only 11 of 15,539 below $1,000 and
7 above $1e10. No fixed-field repetition — the most-repeated `ath` value appears 35 times in 12,768,
which is coincidence, not a regex latching onto something constant. Holders are all integers
(median 350, max 9,470) but present on only **383 rows (2.5%)**, as you said.

**So: drop ~15 rows with a magnitude filter (`1000 ≤ v ≤ 1e10`) and the instrument is usable.** Your
four `ath < mcap` rows include one `ath=2` against a $1.17M mcap, which is the adjacent-field case
you predicted — it just happens to be rare.

## 2. 🔴 But your proposed ratio has look-ahead in it, backwards

You suggested `ath_later / mcap_call`. **That credits the call with peaks that happened before it.**
`ath` is peak since *launch*, so if a coin had already topped out before anyone called it,
`ath_later` still carries that old high and the ratio reports a move the call never caught.

**The fix is `ath_later / ath_at_call`.** If the coin had already peaked, `ath_at_call` captures that
too and the ratio correctly reads **1.00 — no new high after the call.**

**That distinction is doing real work here, not hypothetical work:**

| `ath_later / ath_at_call`, 443 usable 2025 calls | |
|---|---|
| p25 | **1.00×** |
| p50 | 1.23× |
| p75 | 2.42× |
| p90 | 5.09× |
| max | 138× |
| **ratio = 1.00 (coin made no new high after the call)** | **140 of 443 — 32%** |

**Nearly a third of these calls caught a coin that never went higher afterwards.** Under your version
all 140 of those would have been scored as winners or losers based on a pre-call peak.

## 3. ⚠️ The funnel, and why I think this is a weak instrument rather than a rescue

| 2025 calls (13,289 across 11,773 distinct CAs) | n |
|---|---|
| no card at all | **7,858 (59%)** |
| card at the call but **never re-mentioned** | 4,739 (36%) |
| no card near the call | 209 |
| both cards but ATH missing on one | 40 |
| **usable** | **443 (3.3%)** |

**And the selection is exactly the one you named, at full strength.** The at-risk set is "coins
someone mentioned again," and the 4,739 single-card coins cannot supply a control, because a coin
carded only at the call has **no later observation at all** — it is right-censored at time zero, not
a measured non-mover.

**So the only unbiased statistic available is a lower bound**, and it is a weak one: of 13,289 calls
we can *observe* roughly 130 reaching ≥2×, i.e. **≥1.0%**. The priced 2026 data puts the real rate
near **22%**. A bound 20× below the truth is honest and nearly useless.

## 4. 🟢 Where the cards ARE worth real money: validating the 2026 price pipeline for free

**The cards and GeckoTerminal overlap in 2026.** For a 2026 call with both a card-derived
`ath_later / ath_at_call` and a fetched hourly path, the two instruments measure the same quantity by
completely different routes — card text parsed from a Telegram bot, versus pool OHLCV.

**If they agree, both are validated at once. If they disagree, one of them is wrong and I would
rather find that out now than after a verdict rests on it.** This costs zero API calls and it is
the check I most want, given that this project has already shipped two findings that died to
instrument error rather than to the data.

**I will run it as the pull fills in** — currently ~306 of 2,485 priced, so the overlap is still
small.

## 5. What I will and will not claim from 2025

- **Will:** cadence, re-call structure, and a stated **lower bound** on outcome rates, labelled as
  such with the 3.3% coverage printed next to it.
- **Will not:** any rate, mean, or comparison that treats the 443 as representative of the 13,289.
  **The 443 are coins that got talked about twice.**
- **And the `ath_later / ath_at_call` definition replaces `/ mcap_call` everywhere**, including in
  anything you build on your side.
