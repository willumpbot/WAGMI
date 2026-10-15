# Scalping guard (owner's #1 leak) - PROPOSAL (planner-side, warn/nudge; server builds what I SUPPORT; owner go for any live change). His realised P&L is a U-curve: the 1-6h hold window is the ONLY profitable one; both tails bleed, and the scalp tail bleeds on FEES.

_From his real fills (hl_fills, 261 round-trips). Numbers are descriptive on his history - forward-check._

## The U-curve (closedPnl $ by hold time)
| hold | trips | pnl $ | fees $ | pnl/trip |
|---|---|---|---|---|
| sub-10min | 106 | -571 | 497 | -5.4 |
| sub-1h (incl above) | 193 | -324 | 918 | -1.7 |
| **1-6h (the edge)** | 44 | **+184** | 215 | **+4.2** |
| >=6h | 24 | -586 | 78 | -24.4 |
Total 261 / -$726 / fees $1,211. The ONLY green bucket is 1-6h. Both tails lose.

## Two distinct failure modes -> two guards
1. SCALP tail (sub-1h, 193 trips): bleeds on FEES - $918 of fees to net -$324 (gross ~+$594 eaten by
   fees). Mechanism = overtrading, target too small vs the round-trip toll. PROPOSE: a FEE-FLOOR planner
   check - warn when a plan's target (entry->target) is < K x round-trip fee (K~3-4), i.e. the move it's
   reaching for can't clear the toll; and/or a soft size cap / cooldown on sub-1h-intent trades.
2. STALE-HOLD tail (>=6h, 24 trips): -$24.4/trip, the stop-less long holds (matches M29's stop-less
   >6h -$653). PROPOSE: a MAX-HOLD / stop-discipline nudge - "you're 6h in, is the stop still where it
   should be?" (not a hard close - his discretion).

## Framing
These are WARN/NUDGE (owner is a discretionary trader), NOT hard blocks. I PROPOSE; the server builds
whatever I SUPPORT after review; a live planner change needs the owner's go. Insight-only until then.
The fee-floor is the higher-value one (the scalp fee-bleed is the biggest, most mechanical leak).

## Rules for the owner (one number each)
1. Your money is made holding 1-6 hours (+$184). Scalps and overnight-ish holds both lose.
2. 5-minute scalps lose mostly to FEES - 193 quick trades paid $918 in fees. Don't take a trade whose
   target can't clear ~3-4x the fee. (fees $918)
3. 6h+ holds bleed ~$24 each because they run without a tight stop - set a time/stop limit. (-$586 / 24)
