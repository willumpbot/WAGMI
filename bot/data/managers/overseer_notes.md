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
- 2026-10-08, the geometry shadow on SERVER signals (Sep 1 – Oct 8, n=205, out of sample for the laptop's choice):
  current -0.27R vs proposal (stop×8, 1R, 48h) -0.05R; paired +0.23R, CI [-0.07, +0.43] over 18 days.
  Same sign as the laptop (+0.54R), not yet significant. The HAR vol model beat naive in 22/22 walk-forward folds.
- 2026-10-08, laptop missions 8+9:
  - Adaptive stops: stop 2× the forecast move, tp 0.5R, 48h time stop = +0.093R on test vs the bot's -0.431R. Width alone is +0.48R (confirmed again).
    Vol-scaling adds +0.19–0.21R only with a near target (0.5R), and it was observed on test, not pre-registered. Treat as a hypothesis.
  - Safe leverage (13k coin-days, OOS p95 94.6%, p99 97.7%) roughly halves from calm to hot: BTC 16.8x→7.7x.
    HYPE's calmest quintile is worse than BTC's hottest. Divide the table by 1.5.
- 2026-10-08, laptop:
  - Geometry walk-forward: wider stops beat the bot default in 4/4 folds, CI excluding 0 in all (mean +0.50R). It cannot make bad periods good.
  - Funding is 99.3% persistent when in its top quintile, but cross-asset carry (BTC hedge) loses: hedge drift is 25–38x the funding.
  - The same-asset spot/perp basis version may be +0.49% per 3 days: UNVERIFIED, needs HL spot availability.
  - Squeeze odds (adverse >2x forecast in 1d) are modestly predictable: more voice agreement means more squeeze risk (top decile 1.7–1.8x base). Funding sign agrees but adds ~no AUC.
