## HYPE SHORT 82 â€” catch-up dive (linkage audit)

**Source:** `claude_idea` (AI-generated idea). NOT owner-directed â€” no owner credit. Export `result` was null; outcome reconstructed from `candles_1h`.

### Plan
- Entry 82.0, Stop 86.4, Target 77.6 (SHORT), max_hold 48h.
- 1R = |entry-stop|/entry = 4.4/82 = **5.366%**. Target dist = 4.4/82 = 5.366% â†’ **target sits at exactly +1R** (symmetric).

### Thesis plausibility
Reasonable mean-reversion/breakdown short near 82 with tight symmetric 1R geometry. Validated hard by the path: price dumped straight through target within 2 hours.

### Reconstructed path
- Entry bar = first candle whose range contains 82: **2026-08-22 03:00 UTC** (idx 3786; h 82.535 / l 80.271 / c 82.147). No plan timestamp in export, so first-touch convention used.
- Bar +0: l 80.27 (+0.39R) â€” grazes toward target.
- Bar +1: l 80.70 (+0.30R).
- Bar +2: **low 72.52 (+2.15R)** on one big down candle â€” blows through +0.5R (79.80), +0.75R (78.70) and +1R (77.6) all in this bar. **Target filled here.**
- Bars +3..+13: retrace to ~78-79 then chop +1.0R..+1.5R. High over whole window 83.46 â€” never near stop 86.4.

### Outcome vs target/stop
- **TARGET hit, R = +1.00** at bar +2 (within 48h). Stop never threatened. MAE only -0.33R, MFE +2.15R.

### Quarters ladder vs runner on this path
All scale levels (+0.5/+0.75/+1R) fill in the single bar +2 spike. The move then holds above +1R for hours (settles ~+1.0..+1.3R), so retained size keeps earning.
- **Runner (50%@+1R + trail 50%):** 0.5Â·1.0 + 0.5Â·(~1.2R trail) â‰ˆ **+1.10R**.
- **Quarters (25%@+0.5/+0.75/+1R + trail 25%):** 0.125+0.1875+0.25 + 0.25Â·(~1.2R) â‰ˆ **+0.86R**.
- Runner wins by ~0.24R because the path extended well past the 1R target and held there â€” larger retained runner captures the extension.

### Biggest risk / lesson
- Intrabar fill ambiguity: the +2.15R was a single 1h down-candle (low 72.52). Target (77.6) is comfortably inside, so fill is not in doubt here â€” but 1h candles hide order of touch; only matters when stop and target share a bar (not the case).
- Entry-bar selection is the real discretion: no plan timestamp, so first-touch-of-82 was used. A different intended entry date would change the reconstruction.
- Base-rate prior (n=1): clean 1R-target shorts that overshoot the target favor the runner over the quarters ladder.