# WAGMI Proof Window — 2026-07-16 17:00 UTC
Clean window = closes on/after the HONEST-NUMBERS foundation 2026-07-15T02:52:00+00:00 (real fees+funding, fixed self-knowledge). Source: trade_ledger.csv net_pnl. Measurement only.

## Readiness: **NOT_READY — window still thin**
- clean trades **7** / 30 to judge (23 more needed) / 50 for confidence

## PRE-foundation (optimistic / contaminated)
- closes **213** | W/L **76/134** | WR **36%** | net **$+337.41** | avg win $+30.83 / avg loss $-14.97 | PF **1.17**

## POST-foundation (CLEAN honest window)
- closes **7** | W/L **2/5** | WR **29%** | net **$-26.22** | avg win $+0.58 / avg loss $-5.48 | PF **0.04**

## Clean-window honest accounting
- gross P&L $-22.92 | fees $+3.28 | funding $-0.00 | net $-26.20
- avg realized R:R **-0.44** (n=7 with recorded RR)

## Clean-window edge by symbol_side (n>=3)
- SOL_LONG: avg **$-0.48**/trade, WR 33%, n=3

## Thesis directional accuracy (clean window)
- graded **5** | correct 2 | partial 0 | incorrect 3 | hit-rate **40%**

## Loop liveness
- kelly_weights.json updated 9.2h ago | ic_history.json 9.2h ago (FRESH)

**Read:** only the POST-foundation honest window reflects the real system — pre-foundation P&L was optimistic (understated fees/funding) and self-knowledge was corrupted. Give it clean closes before judging profitability; the readiness line above says when there are enough.
