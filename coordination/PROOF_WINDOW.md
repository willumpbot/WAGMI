# WAGMI Proof Window — 2026-07-15 17:00 UTC
Clean window = closes on/after the HONEST-NUMBERS foundation 2026-07-15T02:52:00+00:00 (real fees+funding, fixed self-knowledge). Source: trade_ledger.csv net_pnl. Measurement only.

## Readiness: **NOT_READY — window still thin**
- clean trades **4** / 30 to judge (26 more needed) / 50 for confidence

## PRE-foundation (optimistic / contaminated)
- closes **213** | W/L **76/134** | WR **36%** | net **$+337.41** | avg win $+30.83 / avg loss $-14.97 | PF **1.17**

## POST-foundation (CLEAN honest window)
- closes **4** | W/L **1/3** | WR **25%** | net **$-19.92** | avg win $+0.37 / avg loss $-6.76 | PF **0.02**

## Clean-window honest accounting
- gross P&L $-17.57 | fees $+2.34 | funding $-0.00 | net $-19.91
- avg realized R:R **-0.26** (n=4 with recorded RR)

## Clean-window edge by symbol_side (n>=3)
- (waiting for n>=3 per cell — window still thin)

## Thesis directional accuracy (clean window)
- graded **3** | correct 1 | partial 0 | incorrect 2 | hit-rate **33%**

## Loop liveness
- kelly_weights.json updated 0.3h ago | ic_history.json 0.3h ago (FRESH)

**Read:** only the POST-foundation honest window reflects the real system — pre-foundation P&L was optimistic (understated fees/funding) and self-knowledge was corrupted. Give it clean closes before judging profitability; the readiness line above says when there are enough.
