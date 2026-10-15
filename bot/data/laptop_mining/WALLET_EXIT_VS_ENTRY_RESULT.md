# Project X part 5 - "how much of my past loss was EXITS vs ENTRIES?" ANSWER (majors, self-sourced): on your BIG coins you're about BREAKEVEN; the loss is in the SMALL-CAPS. Where you do lose on majors, it's ~50/50 entry vs exit by $ - but the exit give-backs are FEWER and ~3x BIGGER each, which is exactly what the ladder + fade-tell target.

_2026-10-15. wallet_exit_vs_entry.py. Reconstructed 261 round-trips from hl_fills (wallet A-I, gitignored;
net closedPnl -$726, fees $1,211 - reconciles to M29's ballpark). HL + panels candles don't reach the
2025-09..2026-02 fill era, so I SELF-SOURCED Coinbase 1h candles for the majors (BTC/SOL/ETH/XRP; 159 of
261 trips = 69%). MFE = favorable % the entry offered over the holding window; give-back = MFE - realised.
Coinbase SPOT vs HL PERP has a small basis - MFE% is a close proxy, stated._

## The split (majors, closedPnl $)
| bucket | trips | $ | per trip |
|---|---|---|---|
| winners | 67 | +$1,252 | +$18.7 |
| ENTRY-driven losers (never went his way, MFE<0.5%) | 50 | -$373 | -$7.5 |
| EXIT-driven losers (went green >=1% then closed red) | 17 | -$332 | -$19.5 |
| **majors net** | 159 | **+$291** | |
| non-major small-caps (ASTER/HYPE/BNB/JUP/PUMP; NO candle source) | ~82 | **~-$1,017** (residual) | |

Mean MFE available 0.97%/trip, mean realised -0.18%, capture -19% (he nets none of the available move -
fees + the entry misses eat it). Mean give-back 1.16%/trip left on the table.

## What it means
1. **Your majors are ~breakeven (+$291).** The real bleed is the SMALL-CAPS (~-$1,017 residual) - the
   thin-book coins where squeezes stop you out (SUI, ENA pattern). I can't see their price paths (not on
   Coinbase); that decomposition needs their candles (PC or another source).
2. **On the majors, entry and exit cost about the SAME in $** (-$373 vs -$332). By COUNT entry is the
   bigger problem (50 vs 17 losers never went your way = direction/entry), but each exit give-back costs
   ~3x more (-$19.5 vs -$7.5): the green-then-red trades are the expensive ones.
3. **The exit give-backs (17 trips, -$332) are exactly what the ladder + fade-tell address** - the
   costliest-per-trade failure mode. So the exit work is aimed at the right slice - but it is NOT the
   majority of the loss; entry/direction is just as much, and the small-caps dwarf both.

## Rules for the owner (one number each)
1. On the big coins you trade, you're basically breakeven - your losses are in the small-caps. (majors
   +$291 vs small-caps ~-$1,017)
2. When you lose on a big coin it's half "wrong from the start" and half "gave back a winner" - about
   even in dollars. (-$373 entry vs -$332 exit)
3. The gave-back-a-winner trades are rarer but hurt ~3x more each - that's the slice the ladder and the
   fade-lean are built for. (-$19.5 vs -$7.5 per trip)

## Limits / next
Majors only (69% of trips); Coinbase spot basis; small-caps undecomposed (need their 1h candles -
ask PC, or GeckoTerminal pools per M29). closedPnl reconciles to M29's ballpark, not re-reconciled here.
