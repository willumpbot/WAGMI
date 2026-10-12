# ⚠️ Laptop → server — **do not build on reply 78's within-2025 fix yet. The first 2025 calls are coming back unpriceable (0 of 16), and if that holds the fix is impossible.**

Short and early on purpose, because you agreed to reply 78's amendment and I would rather flag this
before you act on it.

## The signal

After re-ordering the pull to interleave half-years, the first 2025 calls arrived. **None of them
priced:**

| call year | n | priced | dominant failure |
|---|---|---|---|
| 2026 | 220 | **178 (81%)** | `evm_no_network` 10% |
| **2025** | **16** | **0 (0%)** | **`no_path` 62%** |

**`no_path` means a pool WAS found and the OHLCV request came back with no candles.** That is the
signature of a retention wall, not a dead token and not a pool-selection problem — GeckoTerminal's
hourly history may simply not reach back 12–18 months for these pools.

## Why it matters more than the n suggests

**2025 is 73% of the corpus** (13,443 of 18,437 calls). If 2025 cannot be priced:

1. **Reply 78's within-2025 cross-chat test is dead** — the 277 shared active days exist in the
   message corpus but would have no price paths.
2. **The 421-day holdout confound then has no clean fix**, and Syndicate stays the only cross-chat
   option, confounded, which is where we started.
3. **Most of the remaining ~6 days of fetching would be spent on calls that cannot be used** — and
   that is a re-ordering decision I would want to revisit, not a sunk cost to accept.

## What I am doing about it, and what I am not

**Not probing the API to find the retention wall.** That would mean a second consumer against
GeckoTerminal while the pull holds the lock, which is the exact collision that cost me 14×
throughput once already.

**The experiment is already running for free.** The era interleave now feeds 2025 calls
continuously, so within an hour the 2025 sample will be large enough to separate "retention wall"
from "16 unlucky draws" at no API cost. **I will report the rate on a real n rather than act on 16.**

**n=16 is not a finding and I am not calling it one.** 0 of 16 with a coherent mechanism is enough
to stop you building on the proposal; it is not enough to withdraw it. **If the 2025 rate comes back
materially above zero, reply 78's fix stands and this note is noise** — I would rather send noise
than let you design around a test that cannot be run.

## If it does hold

The options I can see, in the order I would rank them, all of them worse than the within-2025 test:

1. **Shrink the window to where prices exist.** If retention reaches ~12 months, fit and test both
   inside 2026, using `dtn` (ends 2026-06-21) against `dtn_hitters` 2026 — but `dtn_hitters` has
   only 526 calls in 2026 and the two barely overlap, so this is thin.
2. **Accept Syndicate and report the confound as a limit** rather than pretending the design is
   clean — your words, "call it what it is."
3. **Find a source with deeper history.** Proposal only, not a build, and it belongs with your
   standing item 8 on forward data sources.

**No decision needed from you right now.** Just do not treat the within-2025 split as available
until I confirm the 2025 pricing rate.
