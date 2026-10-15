# DIVE — RSR LONG, two structures: tight `b33a49b78e` (0.00194/0.00172/0.00215, re-log `792413838f`) and wide `c0bf3a3124` (0.00196/0.00172/0.00245, re-log `93acec61e9`)

_2026-10-15. Per-trade team (3 miners + adversarial verifier; `exit_style.play` imported directly, no
re-implementation drift). Snapshot: candles_1h MAX(t) 2026-10-14T22:00Z; funding spans 368d (n=8,836
hourly rows); RSR 5m lags ~9h. R pre-fee. The 4 plan rows are 2 structures — the duplicates are
re-logs with identical `filled_at`._

## State (verified)
- Tight: **+0.209R** at export mark; wide **+0.108R** (sim matches export to one tick of mark drift).
- **+1R not hit on either** → no half banked, no trail armed, full size on the 0.00172 stop.
- Distances at the as_of ATR (0.0001906 — the verifier's corrected anchor): stop **1.40 ATR (−13.4%)**
  below; +1R **0.91 ATR (+8.8%)** away for tight, **1.12 ATR (+10.8%)** for wide.
- Clock: tight ~37h left, wide ~34h. Both are **winners being held** — M10's population; base case for
  the wide structure is a time-limit close.

## The coin's own prior (212d, n=1258 starts / 210 days, eqw beside pooled — verifier-reproduced to 0.01pp)
- **Tight structure: history favours it ~3.4:1** — target-first 11.2% vs stop-first 3.3% within 48h,
  against an implied R:R of only 0.955.
- **Wide structure: history is against it** — the 2.65-ATR target completed first in **1.27%** of
  windows, LESS often than its stop (2.15%); its realistic exit is the clock, and its P&L rides on
  what the timeout close prints.
- **Vol regime: ATR14 at its 212d MAXIMUM (100th pctile abs, 98th as % of price) and +48% in 14d.**
  Both the stop buffer and any future trail are measured against an ATR that grew by half in two weeks.
- Caveat the verifier kept: the up/down completion asymmetry partly reflects RSR's realized drift over
  this sample; base rates pool all regimes while current vol is the sample max.

## Flow (verified)
- **Funding flipped hard negative: this LONG EARNS ~21–39 bps/day** (latest −8.64e-5/h = 1.8th pctile
  of its own 368d history; 24h mean 0.6th pctile). 7d −94 bps/day pooled (−83 eqw) vs prior-30d +3.
- Sign convention independently confirmed (rate/premium co-sign 100% when |premium|>0.1%, n=324).
- Read it honestly: **the perp crowd is positioned short against this long** — paid carry is a tailwind
  inside a squeeze-or-breakdown regime, driven by a minority (39%) of deep-negative hours.
- Premium collapsed 0 → −0.37% in 7d (mark persistently under oracle).
- **RSR has ZERO rows in liq_events, whales, and depth** — flow beyond funding is a blind spot, and RSR
  5m candles lag peers by ~9h. Coverage gap, not calm.

## Engine notes
- Tight structure's target (0.00215) sits **1 tick INSIDE +1R (0.00216)**: under `full` it exits at
  target a tick before the runner's partial would trigger — the styles diverge inside a 1-tick band.
- Once +1R arms, the trail floor for tight = 0.001979 (−0.56% from last close); wide = 0.002019.

---
**What matters:** tight is the best-prior trade on the desk (3.4:1 for target at ~1:1 payoff) with carry
paying ~21–39 bps/day; wide's target is a 1-in-79 event in 48h — its exit is the clock; vol is at the
coin's all-time (212d) max while the crowd is short.
**What would change the plan:** nothing mechanical; the owner should know the wide target is
historically unreachable inside the clock — that is a target/time-limit choice for next time, not now.
**Confidence:** high on state/base rates (reproduced exactly); funding read high; flow beyond funding
is a stated blind spot.
