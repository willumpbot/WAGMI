# WAGMI Proof Window — 2026-09-27 05:00 UTC
Clean window = closes on/after the HONEST-NUMBERS foundation 2026-07-15T02:52:00+00:00 (real fees+funding, fixed self-knowledge). Source: trade_ledger.csv net_pnl. Measurement only.

## Readiness: **READY_CONFIDENT — enough to judge edge**
- clean trades **74** / 30 to judge (0 more needed) / 50 for confidence

_Canonical epoch (operational $5k reset, separate from the honest-numbers cutoff above): 2026-07-15T12:40:51.929991+00:00 — 71 trades, net $-268.91, derived equity $4731.09._

## PRE-foundation (optimistic / contaminated)
- closes **213** | W/L **76/134** | WR **36%** | net **$+21.46** | avg win $+17.55 / avg loss $-9.79 | PF **1.02**

## POST-foundation (CLEAN honest window)
- closes **74** | W/L **26/47** | WR **35%** | net **$-268.92** | avg win $+0.95 / avg loss $-6.25 | PF **0.08**

## Clean-window honest accounting
- gross P&L $-216.87 | fees $+52.03 | funding $+0.00 | net $-268.90
- avg realized R:R **-0.16** (n=72 with recorded RR)

## Clean-window edge by symbol_side (n>=3)
- BTC_LONG: avg **$-0.43**/trade, WR 17%, n=6
- XRP_LONG: avg **$-0.49**/trade, WR 17%, n=6
- HYPE_SHORT: avg **$-0.55**/trade, WR 40%, n=10
- SOL_SHORT: avg **$-0.64**/trade, WR 38%, n=13
- XRP_SHORT: avg **$-2.01**/trade, WR 50%, n=10
- ETH_SHORT: avg **$-3.41**/trade, WR 0%, n=3
- SOL_LONG: avg **$-9.49**/trade, WR 50%, n=10
- ETH_LONG: avg **$-9.56**/trade, WR 40%, n=5
- NEAR_SHORT: avg **$-13.49**/trade, WR 17%, n=6

## Thesis directional accuracy (clean window)
- graded **64** | correct 22 | partial 0 | incorrect 42 | hit-rate **34%**

## Loop liveness
- kelly_weights.json updated 2.0h ago | ic_history.json 2.0h ago (FRESH)

**Read:** only the POST-foundation honest window reflects the real system — pre-foundation P&L was optimistic (understated fees/funding) and self-knowledge was corrupted. Give it clean closes before judging profitability; the readiness line above says when there are enough.
