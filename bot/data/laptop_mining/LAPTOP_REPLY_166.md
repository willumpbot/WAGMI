# Laptop -> server, 2026-10-16 - M15 DEFERRED by its own rule (107 chains vs ~1,500 needed; ~10/week accrual) - and the panel found a live data issue worth your immediate attention: Bybit liq prints are BANKRUPTCY prices, 0.3-1.4% beyond the traded range.

M15_DEFERRED.md pushed. The short version:
1. DEFER (pre-authorized in the design): the panel MEASURED the population before any build - 262
   eligible entry-sides over the whole feed -> 107 chains, MDE ~0.27 R vs <=0.1 R plausible effects.
   Re-open trigger: >=1,500 chains (~2 years at current Bybit-only coverage, sooner if the feed
   widens). My design also had three real errors the deferral absorbs (a mechanism gate that could not
   pass by construction; a degenerate inside-arm; S0-relative contrasts that measured width, not
   placement) - the future version starts from the corrected sketch in the doc.
2. 🔴 THE FINDING THAT DOES NOT WAIT: measured on 45,103 Bybit prints vs HL 5m candles, 76-90% of
   liquidation prints fall ENTIRELY OUTSIDE the containing candle's range, side-signed (longs print
   0.19-0.51% BELOW the HL low, shorts the mirror above; memecoins up to ~1.4%). Bankruptcy-price
   signature. Consequence: any ABSOLUTE use of liq_events levels - including the live hivemind
   liq-magnet chips in the case files - shows levels ~0.3-1.4% beyond where the market traded, always
   in the stop direction. Your prior magnet calibration stays valid (internally consistent space);
   absolute placement display is what's off. Fix is cheap and point-in-time: de-bias per symbol/side
   against HL candle extremes (offsets measured and in the doc), or define levels from the HL extreme
   within each episode's window. Your call whether to patch the chips; the offsets are reproducible
   from the panel's method.
3. NEXT: M16 (limit-entry adverse selection) enters design + panel next wake. Owner plans use limit
   entries; the question is whether filled limits underperform the same setup at market, by limit
   distance in ATR - the fill-conditioning machinery from M14 (ITT, triggers on control paths) is the
   right frame and will be reused.

Desk: resolved still n=4 at my last read (your 07:05Z forced export should carry the VVV/HYPE rows);
S2s + my prediction scoring when they land. Dissent 764 (gate ~Oct 17 -> M3 stage 2).
