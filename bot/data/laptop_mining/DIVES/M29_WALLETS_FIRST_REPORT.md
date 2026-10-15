# M29 — the owner's wallets, first full report (addresses live only in the laptop's local config; wallets lettered by that file's order: A–B Hyperliquid, C–I Solana)

_2026-10-15. Full chain/API pull completed and RECONCILED against the owner's own pasted history
before anything below was read as fact._

## Reconciliation — the gate passed exactly
Wallet A (HL): API shows **1,108 fills, closedPnl −$726.29, fees −$1,020.41, net −$1,746.70** —
my independent parse of the owner's pasted UI history said **−$1,746.77**: match to 7 cents. (The
paste's 598 rows are the UI's aggregated fills; the API's 1,108 are the raw ones.) Funding adds −$17.33
(96 events). Span 2025-09-18 → 2026-02-26.
**Wallet B (HL): ZERO fills, ever.** It has never traded on Hyperliquid — worth confirming with the
owner that this is the intended second address.

## The one-line truth of wallet A, now decomposed
**Fees were 58% of the account's loss — $1,020 of fees against $726 of actual trading losses.**
With the already-verified behaviour (18-minute median hold, 50 opposite-side flips within 10 minutes,
no stop orders, 9 liquidation events in the UI history), the account didn't lose a market battle — it
paid a toll booth 1,108 times.

## Solana (wallets C–I): the same signature, different venue
**306 FIFO round trips (253 closed / 53 still held), 21% win rate, net −8.81 SOL**, median hold
**0.9 hours** (a quarter closed inside ~6 minutes). Activity concentrates in wallets G (104 trips),
D (62), I (54), C (53). Worst single trip −2.31 SOL; best +3.02. Combined with HL, the relayed wallets
show ≈ −$3,500 total with one mechanism on both venues: scalp-speed churn, fee bleed, exits by
impulse or not at all.

## KILROY (dive request 98558213) — mint CONFIRMED, timeline corrected
The exact mint the server named is the one his wallets hold. The position lives in **wallet I**:
**12 accumulation events 2026-02-17 → 2026-09-29, ~4.9M tokens, ZERO sells across all seven wallets.**
(Wallet E bought 40.9k in Feb and transferred the full amount out in April — consistent with
consolidation; wallet G bought 192.7k in Feb.) Most adds carry zero SOL delta — acquired against USD
or received, not SOL-swapped; sizing his cost basis needs the pool-trade data. **Timeline correction
for the owner: first touch is 2026-02-17 — he has held 8 months, not a year.** The rest of the dive
(price history, holder concentration, liquidity vs his exit size) waits on pool_trades/external data.

---
**What matters:** wallet A's loss was mostly fees, not direction — the exact thing the bot's rules
exist to prevent; KILROY is a confirmed, genuinely held, never-sold position in wallet I since Feb.
**What would change the plan:** nothing live; the owner should confirm wallet B is the right address
(it is empty on HL), and the KILROY liquidity-vs-exit-size question is the open risk on his real hold.
**Confidence:** high — the headline numbers reconciled against the owner's own record to 7 cents;
Solana trip stats depend on the FIFO reducer (SOL-quoted legs only; zero-SOL acquisitions like the
KILROY adds sit outside PnL until priced).
