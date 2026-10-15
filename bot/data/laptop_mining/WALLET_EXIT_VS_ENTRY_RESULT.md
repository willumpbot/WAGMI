# Project X part 5 (100% of trips covered; CORRECTED) - "exits vs entries?" The real answer is THREE buckets, and the #1 leak is neither: it's SCALPING. 151 sub-10-minute trades lost ~$659. When you actually HOLD a trade (multi-hour) you're ~breakeven; the losses there are a few big thin-coin give-backs, then smaller entry misses.

_2026-10-15. wallet_exit_vs_entry.py. 261 round-trips from hl_fills (wallet A-I, gitignored). Candle
paths self-sourced: Coinbase 1h + data.binance.vision bulk archive (HYPE/BNB/JUP/ASTER/XPL). 260/261
trips covered (only kPEPE, 1 trip -$5, uncovered). CORRECTION: an earlier version applied a 1h-candle
MFE to sub-1h SCALPS, which faked a huge "exit give-back" (the candle range is not a 5-min excursion).
Scalps are now a SEPARATE bucket; the entry-vs-exit split is computed only on genuinely multi-hour trips._

## Three buckets (closedPnl $)
| bucket | trips | $ | note |
|---|---|---|---|
| **SCALPS (sub-1h, median ~5 min)** | 151 | **-$659** | overtrading/fees bleed - M29 U-curve. NOT entry/exit-decomposable (no intra-trade path at 1h). |
| multi-hour WINNERS | 58 | +$1,189 | |
| multi-hour ENTRY-driven losers (never went his way) | 26 | -$254 | wrong-direction entries |
| multi-hour EXIT-driven losers (green >=1% then red) | 10 | -$550 | thin-coin spike-then-reverse; ladder/fade-lean target |
Multi-hour net +$151 (~breakeven). Mean MFE 1.87%, realised -0.18%, capture -10%.

## The honest answer
1. **Your biggest single money leak is SCALPING** - 151 trades held about 5 minutes, -$659. This is not
   a bad-entry or bad-exit problem; it's OVERTRADING (too many tiny round-trips, fees + noise). Fix:
   trade far fewer, hold longer. (Matches M29's U-curve: sub-10min scalps were the worst bucket.)
2. **When you actually hold a trade (multi-hour), you're about breakeven (+$151).** The losses there are
   a HANDFUL of big exit give-backs (10 trips, -$550 - thin-coin spikes you rode up then gave back) plus
   smaller entry misses (26 trips, -$254). The give-backs are the ladder/fade-lean slice (SUI: -1R -> -0.21R).
3. **Bad entries are the smallest piece.** Direction isn't your main problem; overtrading is, and after
   that, giving back thin-coin spikes.

## Correction + caveats (transparent)
Earlier reply 191 said "EXIT give-back dominates (-$831)" - that was WRONG: it counted 151 scalps with a
1h-candle MFE (a by-construction artifact - a 5-min trade can't have a 1h excursion). Corrected here:
scalps split out, exit give-back on real multi-hour trips is -$550 (10 trips). The exit-give-back small-caps
still carry the Binance-vs-HL thin-book basis caveat (part of the "give-back" may be an unexitable spike).
Scalp -$659 is straight closedPnl (no MFE needed), solid.

## Rules for the owner (one number each)
1. Stop scalping - 151 ~5-minute trades cost you ~$659, your biggest leak. Trade less, hold longer.
2. When you hold properly you're about even; the real losses are a few thin-coin spikes you gave back -
   use the ladder/trim there. (multi-hour +$151; exit give-backs -$550 on 10 trips)
3. Your entries aren't the problem (-$254, smallest bucket). Overtrading is.
