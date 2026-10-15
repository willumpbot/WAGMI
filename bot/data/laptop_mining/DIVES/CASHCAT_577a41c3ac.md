# S1 Catch-up Dive â€” CASHCAT LONG (late_logged, AI-idea)

**Source:** `claude_idea` â€” this is an AI-generated plan, NOT owner-directed. No owner credit.
**Linkage:** FILLED plan missing its dive_results row; export result field null, reconstructed from 1h candles.

## Setup
- Entry 0.10558 | Stop 0.094747 | Target 0.116413 | LONG | max_hold 48h
- stop_dist = entry-stop = 0.010833; tgt_dist = target-entry = 0.010833
- 1R = 0.010833/0.10558 = 10.26%. Target = tgt_dist/stop_dist = **+1.000R exactly**; stop = -1.0R.

## Entry reconstruction (the load-bearing choice)
Export carries no entry timestamp, so the entry bar = nearest candle. 82 CASHCAT 1h bars have a low/high straddling 0.10558 (the coin plateaus near 0.105 for weeks), so "contains entry price" is useless. Used **global min |open-entry|**: bar at 2026-07-15 20:00 UTC, open 0.10557 (diff -1e-5) â€” the single closest. (Bar 108 @16:00 open 0.1056, diff -2e-5, would falsely "hit target" only because target 0.116413 sits inside that bar's own 0.1195 wick â€” an artifact of a worse-matched entry bar, rejected.)

## Walk (up to 48 bars, stop-first within a bar)
- Entry bar (20:00): high 0.10568, low 0.10054 â€” neither target nor stop touched.
- **Bar +1 (21:00): low pierces 0.094747 â†’ STOP. Target not reached in-bar (clean stop, not ambiguous).**
- Outcome: **STOP, R = -1.0**, filled in ~1h.

## Quarters vs Runner on this path
Price high after entry = 0.10568; +0.5R trigger = 0.11100. **+0.5R never reached**, so no scale-outs fired under QUARTERS (25%@+0.5/+0.75/+1R+trail) and no half-off under RUNNER (50%@+1R+trail). Both strategies hold full size into the stop â†’ **identical -1.0R**. Exit style was irrelevant on a one-bar reversal.

## Risk / lesson
- Biggest risk is entry-bar ambiguity: with the price plateauing near 0.105 for weeks, nearest-open is defensible but the true logged entry could differ by hours and flip the sign. Flagged, not hidden.
- Thesis (long continuation off 0.1056) failed immediately â€” entered into a local plateau that rolled over within the hour. Matches a base-rate prior: breakout-longs entered at a flat consolidation shelf stop fast when there's no momentum (n=1).
- Correctly excluded from pooled stats (late_logged); this row is linkage catch-up only.