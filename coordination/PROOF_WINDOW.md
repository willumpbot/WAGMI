# WAGMI Proof Window — 2026-10-08 11:00 UTC
Clean window = closes on/after the HONEST-NUMBERS foundation 2026-07-15T02:52:00+00:00 (real fees+funding, fixed self-knowledge). Source: trade_ledger.csv net_pnl. Measurement only.

## Readiness: **READY_CONFIDENT — enough to judge edge**
- clean trades **78** / 30 to judge (0 more needed) / 50 for confidence

_Canonical epoch (operational $5k reset, separate from the honest-numbers cutoff above): 2026-07-15T12:40:51.929991+00:00 — 75 trades, net $-226.55, derived equity $4773.45._

## PRE-foundation (optimistic / contaminated)
- closes **213** | W/L **76/134** | WR **36%** | net **$+21.46** | avg win $+17.55 / avg loss $-9.79 | PF **1.02**

## POST-foundation (CLEAN honest window)
- closes **78** | W/L **29/48** | WR **37%** | net **$-226.56** | avg win $+2.61 / avg loss $-6.30 | PF **0.25**

## Clean-window honest accounting
- gross P&L $-169.44 | fees $+57.10 | funding $+0.00 | net $-226.54
- avg realized R:R **-0.14** (n=76 with recorded RR)

## Clean-window edge by symbol_side (n>=3)
- XRP_SHORT: avg **$+2.78**/trade, WR 55%, n=11
- NEAR_LONG: avg **$+0.38**/trade, WR 75%, n=4
- BTC_LONG: avg **$-0.43**/trade, WR 17%, n=6
- XRP_LONG: avg **$-0.49**/trade, WR 17%, n=6
- HYPE_SHORT: avg **$-0.55**/trade, WR 40%, n=10
- SOL_SHORT: avg **$-0.64**/trade, WR 38%, n=13
- ETH_SHORT: avg **$-3.41**/trade, WR 0%, n=3
- SOL_LONG: avg **$-9.49**/trade, WR 50%, n=10
- ETH_LONG: avg **$-9.56**/trade, WR 40%, n=5
- NEAR_SHORT: avg **$-12.81**/trade, WR 14%, n=7

## Thesis directional accuracy (clean window)
- graded **68** | correct 25 | partial 0 | incorrect 43 | hit-rate **37%**

## Loop liveness
- kelly_weights.json updated 10.0h ago | ic_history.json 10.0h ago (FRESH)

**Read:** only the POST-foundation honest window reflects the real system — pre-foundation P&L was optimistic (understated fees/funding) and self-knowledge was corrupted. Give it clean closes before judging profitability; the readiness line above says when there are enough.
