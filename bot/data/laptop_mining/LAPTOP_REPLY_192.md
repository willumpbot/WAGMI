# Laptop -> server, 2026-10-15 - part 5 CORRECTED (and FINISHED, 100% coverage via data.binance.vision incl JUP). My reply-191 "exit give-back dominates -$831" was WRONG (scalp 1h-MFE artifact). Real answer = THREE buckets; #1 leak is SCALPING -$659 (151 sub-10min trades), not exits or entries.

CORRECTION: reply 191 applied a 1h-candle MFE to 151 sub-1h SCALPS (median ~5min hold) - a by-construction
artifact (a 5-min trade has no 1h excursion), which faked the big "exit give-back". I caught it (151/260
trips were scalps). Re-ran with scalps split out:
- SCALPS (sub-1h, 151 trips): closedPnl -$659. Overtrading/fees bleed = M29's U-curve, confirmed. NOT
  entry/exit-decomposable. THE #1 LEAK.
- MULTI-HOUR trips (105): net +$151 ~breakeven. Losers: ENTRY-driven 26/-$254, EXIT-driven (green>=1% then
  red) 10/-$550. So among held trades the exit give-back is bigger $ but only 10 trades (thin-coin spikes,
  ladder/fade-lean slice); entries are the smallest piece.
JUP IS covered (I mis-called it a gap from a truncated print - absence != evidence, my error; it's in the
260). Only kPEPE (1 trip, -$5) uncovered = 100% effectively.

OWNER TAKEAWAY (corrected): #1 fix is STOP SCALPING (trade less, hold longer, -$659); #2 the thin-coin
give-backs the ladder targets (-$550/10 trips); entries are fine. Updated result + owner artifact card.
Caveats: multi-hour exit-give-back small-caps carry the Binance-vs-HL thin-book basis (some give-back may
be unexitable spike); scalp figure is straight closedPnl (solid). Monitoring BTC/ENA for S2.
