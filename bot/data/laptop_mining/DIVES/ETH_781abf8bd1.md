## ETH SHORT 2400/2472/2310 â€” "new wave" (AI idea, catch-up dive S1)

**Provenance.** source=`claude_idea` â€” this is an AI-generated thesis, NOT an owner-labeled direction; the owner gets no credit for the call. Export `result` was null (linkage gap: FILLED plan with no dive_results row). Outcome reconstructed here from `candles_1h` (ETH, panels.sqlite, mode=ro).

**Geometry.** entry 2400, stop 2472, target 2310. stop_dist=72, target_dist=90 -> 1R=72/2400=3.0%; a win = +90/72 = **+1.25R**. RR=1.25.

**Thesis plausibility.** Reasonable mean-reversion/continuation short near a round 2400 level with a tight 3% stop and a 1.25:1 payoff. Breakeven win-rate ~44%.

**Reconstructed path (first-touch limit fill, deterministic â€” no timestamp in export).**
- Entry bar 2026-04-14 14:00 UTC: O2389 H2413.8 L2351 C2351.1 â€” high pierces 2400, short fills.
- 15:00 L2329.4 Â· 16:00 L2327.0 Â· 17:00 L2322 Â· **18:00 L2307.6 -> target 2310 hit (bar 4).**
- Max high over the hold = 2413.8; stop 2472 never came within ~58pts. Zero meaningful adverse excursion.

**Outcome vs target/stop: TARGET, R = +1.25.** Won in 4h of a 48h budget.

**Quarters ladder vs runner on THIS path** (levels: +0.5R=2364, +0.75R=2346, +1R=2328, tgt=2310/+1.25R; extreme low 2301.3/+1.37R at 19:00, then first higher-high trail-out ~2320 by 20:00-21:00 â‰ˆ +1.10R):
- QUARTERS (25% @ +0.5/+0.75/+1R + trail): (0.5+0.75+1.0+1.10)/4 â‰ˆ **+0.84R**.
- RUNNER (50% @ +1R + trail 50%): (1.0+1.10)/2 â‰ˆ **+1.05R**.
- Naive hold-to-fixed-target: **+1.25R**.
Ranking: hold > runner > quarters. On a no-heat straight-line winner, scaling out early only sheds upside; the back-weighted runner keeps more R, quarters bleeds the most to partials.

**Biggest risk / lesson.** Entry-bar ambiguity: "new wave" carries no timestamp, so I took the first candle to touch 2400 (2026-04-14). Later 2400 touches sit in chop near the 2472 stop (e.g., late-Aug highs ~2470-2518) and could have stopped out â€” so the +1.25R is specific to the first-wave reconstruction, not a claim the thesis wins at every 2400 tag. Lesson for exits: when a signal runs clean with ~0 heat, prefer the runner over the quarters ladder; the ladder's early partials are insurance you pay for and don't need here.

**Base-rate prior (n=1).** RR=1.25 shorts need >44% win rate to be +EV; this instance resolved win (+1.25R). Logged as a single observation, not a validated edge.