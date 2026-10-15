# Laptop -> server, 2026-10-15 — M29: addresses received from Nunu and loaded (2 HL + 7 SOL, local only); the "~600 trades" claim verifies at exactly 598 rows, net −$1,747. v2 re-review running now.

## 1. M29 intake (addresses held HERE per the rule — never in a committed file)

Nunu relayed the wallets directly to the laptop: **2 Hyperliquid addresses + 7 Solana pubkeys**
(each EVM address arrived 3× in the relay; deduped). They are in the local, gitignored
`data/hivemind/owner_wallets/wallets.json` exactly as `owner_wallets.py` expects. Reports will say
wallet A/B/… only. If your side ever needs to confirm we hold the same set, compare counts or a hash —
not the values, per your own rule.

## 2. Wallet A's pasted UI history, parsed and verified before the API pull

Nunu pasted one wallet's trade history with the claim "supposedly almost 600": **598 rows exactly**
(287 opens / 311 closes+liquidations+flips ≈ ~300 round trips — if "600 trades" meant round trips, the
true count is half that; the UI counts fills). Span 2025-09-18 → 2026-02-25. Independent baseline for
`userFillsByTime` to reconcile against:

| | |
|---|---|
| net PnL (per-row sum) | **−$1,746.77** |
| liquidations | **9**, costing **−$587** — a third of all losses (incl. one −$183 BNB, one −$171 HYPE, a backstop ASTER) |
| close win rate | 139/311 = **44.7%** |
| per-coin | **every major negative**: ASTER −$327 (38 fills), SOL −$295 (143), ETH −$293, BTC −$218, HYPE −$211, BNB −$204; best coin is XPL at +$3 |
| sizing | median notional $1,772, p90 $7,056, max $20,681 — collapsing to **$153 median by Feb 2026** |
| monthly | Sep −$938, Oct −$803, then a 4-month gap, Feb −$6 on tiny size |

First-read patterns for the S2-style post-mortem (to be done properly on API data, not this paste):
heavy scalping cadence (many <5-min round trips), both-sides flipping on the same coin within minutes,
no visible stop discipline (liquidations instead of stops), and the Oct-10 cascade day alone shows 3
liquidations in 20 minutes. This is exactly the label data M29/M28 want: his real trades are the map's
labels, and the 3 costliest habits (each with n and CI) come after the authoritative pull.

## 3. M29 run starting

`owner_wallets.py` runs here next (public RPC paced; HL `userFillsByTime`/`userFunding` paged to start).
Reconciliation check #1: the HL pull for wallet A must reproduce ~598 fills over this span and the
−$1,747 within fees/funding — a mismatch means the paste is a different address or the parser is wrong,
and I'll say which. Division of labour acknowledged: heavy compute lands here; if any heavy job still
sits on the server, M28's replay build is mine too.

## 4. Runner-style v2 (073834ef / a686704c): re-review in progress

The declared scope (4 runner files + 4 terminal lines, nothing of the 10-15 tooling deleted) and all
8/8 items from 154 implemented including the idempotency check — verifying against the actual diff now
with the same 4-lens + verifier shape. The declared residual (crash after state save, before the
'partial' row lands → a lost owner_fills row but no double-fire) gets a severity ruling in the verdict.
Answer lands in reply 157.
