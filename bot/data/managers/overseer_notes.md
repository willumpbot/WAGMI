Curated by the overseer (Claude). External evidence, each item with its source and caveats.

- 2026-10-08, laptop mission 3: 15,476 signals from Mar 16 to Jun 5 (pre-May-30 era) were forward-graded independently.
  - Take-every-signal: -9.8 bps per 4h. This replicates the server's -14.
  - BTC looks negative at every horizon (4h -15.9 bps), BUT laptop mission 4 shows BTC vs non-BTC is only -9.8, CI [-36.7, +15.7]. BTC is negative because the whole book is. Do NOT propose avoid-BTC; it would be a false positive.
  - agree>=3 looks anti-predictive at 12h, but n_eff is only 20, so it's a hypothesis only.
- 2026-10-08, stop/target geometry, server check:
  - In the May–Oct signals, SL is hit first in 46.5% of setups and TP1 first in 27.5%. Among setups that hit either, TP1 comes first 37% of the time; a random walk would give about 40% at R:R 1.5.
  - So geometry is roughly a coin flip. The losses come from no directional edge plus fees, not from mis-placed stops.
  - The laptop era (Feb–Jun, TP1 first 24%) was worse than chance. Don't propose stop changes from this.
- 2026-10-08, the two recent wins (XRP short +$50.68 and NEAR short, +$15 realized so far) were both shorts with funding_rate agreeing. Only 3 ledger trades fit that slice (+$17), so it's a lead, not evidence.
- 2026-10-08, the laptop could not replicate the trend-adjusted floor's edge (-0.010, CI [-0.315, +0.300]). Treat that gate as unproven.
- 2026-10-08, laptop mission 4: 29 slices were trained on Mar 16 – Apr 29 and tested on May 1 – Jun 5. ZERO had a training CI excluding 0, so nothing qualifies.
  - Watchlist (sign held in both halves, nothing significant): agree=3+ & SHORT (-33 / -37 bps), agree=3+ overall.
  - This contradicts the consensus assumption ("more strategies agreeing = better") and agrees with the server's trade table (agree=3+ SHORT: -$62, n=10). It's cheap to watch forward.
- 2026-10-08, laptop mission 5: an 18k symbol-day panel from 2020 to 2026, train/test split. Results:
  - Stretch, range and driver are ONE voice (correlation 0.64–0.78).
  - Voice AGREEMENT does not predict direction out of sample: a high-consensus cell went +4.0% in train, -0.3% in test.
  - Consensus predicts MOVE SIZE: next-day move ~5.1% with 1 dissenting family vs ~3.2% with 4. ATR→vol corr is 0.35 out of sample.
  - Of 34 voice×regime combos, 0 survived.
  - Do not propose rules that rely on voice agreement for direction.
- 2026-10-08, laptop geometry sweep:
  - The bot's stop×1/TP 1.5R scores -0.43R per setup.
  - Wider stops remove the loss (OOS paired diff +0.54R, CI [+0.30, +0.80]; all four majors significant), but this converges to ~0R. It is loss elimination, not alpha.
  - The 18-filter gate stack has NEGATIVE value: passed signals returned -12.1 bps vs -8.9 for rejected.
- 2026-10-08, laptop mission 6: the daily base map's states REPEAT across halves (72.7% vs 44.5% shuffled null), so it is a valid base rate.
  Adding 4h fragments it to chance (50% / 37% vs ~47% null). Do not cite 4h-combined base rates.
