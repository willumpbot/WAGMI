# Project X part 5 (NOW 89% COVERED via data.binance.vision) - "how much of my loss was exits vs entries?" UPDATED ANSWER: once the thin-book small-caps are in, GIVING BACK WINNERS is the bigger dollar loss (-$831 over 38 trips) vs never-went-my-way (-$483 over 60). The majors alone are ~even; the small-caps add the big exit-give-back - the SUI/ENA spike-then-reverse shape the ladder + fade-lean target.

_2026-10-15. wallet_exit_vs_entry.py. 261 round-trips from hl_fills (wallet A-I, gitignored). Candle paths
SELF-SOURCED: Coinbase 1h for its listed coins (BTC/SOL/ETH/XRP/AVAX/PUMP/PENGU/DOT/LTC) + the Binance
public bulk archive data.binance.vision for the small-caps (HYPE/BNB/ASTER/XPL; PC reply 7c3c30a9). 233
of 261 trips covered (89%). GAP: JUP (69 fills, ~18 trips) is not on the Binance futures archive (404)._

## The split (covered trips, closedPnl $)
| bucket | trips | $ | per trip |
|---|---|---|---|
| winners | 104 | +$1,569 | +$15.1 |
| ENTRY-driven losers (never went his way, MFE<0.5%) | 60 | -$483 | -$8.0 |
| **EXIT-driven losers (went green >=1% then closed red)** | 38 | **-$831** | **-$21.9** |
mean MFE available 1.73%, mean realised -0.20%, capture -11%, mean give-back 1.93%/trip.

## The update vs the majors-only read
- Majors alone were ~even (entry -$420 vs exit -$338). Adding the thin-book small-caps FLIPS it: the
  EXIT give-back (-$831) is now the biggest dollar loss - and it is ENTIRELY the small-caps. They spike
  (go green >=1%) then V-reverse and close red - the SUI/ENA thin-book pattern, which is exit-shaped.
- So the bleed is not "bad entries" - it is GIVING BACK WINNERS on thin coins. That is exactly the slice
  the quarters ladder (SUI saved ~0.8R) and the fade-lean are built for.

## Honest caveat (don't over-read the small-cap exit figure)
Small-cap MFE comes from Binance perp; on a THIN coin the spike shown there may not have been exitable on
HL's thinner book. So part of the "-$831 exit give-back" is really "shouldn't have traded a spiky thin
coin" - the line between a bad EXIT and a bad INSTRUMENT choice blurs for thin-book small-caps. Either
framing points to the same fix: ladder/trim the thin-coin spikes, or trade them smaller/not at all. JUP
(~-? , 69 fills) still uncovered -> the one remaining gap; covered net is -$130 of the -$726 total, so
JUP + the uncovered tail hold ~-$596 (likely a big chunk - flag to re-pull if JUP lists elsewhere).

## Rules for the owner (one number each)
1. Your biggest dollar loss is GIVING BACK WINNERS, not bad entries - especially on thin small-caps that
   spike then reverse. (exit give-backs -$831 vs entry misses -$483)
2. That is exactly what your new ladder is for - it banked +0.5R/+0.75R on SUI and turned a -1R into
   -0.21R. Use it (or trim) on thin-coin spikes. (SUI ladder saved ~0.8R)
3. On the big liquid coins you're about even - the thin small-caps are where the money goes. Trade them
   smaller, or not at all. (majors ~even; small-caps hold the loss)
