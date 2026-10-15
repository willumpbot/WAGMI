# Case File â€” ETH LONG 2490/2385/2598 (claude_idea, catch-up dive S1)

**Linkage note:** FILLED owner plan missing its dive_results row. Source = `claude_idea` (AI-generated thesis, NOT owner direction â€” no owner credit). Export `result` field was null; outcome reconstructed from `candles_1h` (ETH, panels.sqlite, mode=ro).

## Thesis plausibility
LONG 2490, stop 2385 (-4.22%), target 2598 (+4.34%). Symmetric ~1:1 R:R (target = +1.03R). A pullback-buy into the 2500-2535 range ETH held across 10-13/10-14. Reasonable setup; thesis was simply run over by a market-wide leg down.

## Reconstructed path
- Entry filled on the 10-14 12:00 bar (l 2473.6, h 2518.8) â€” the decisive pullback to 2490. (First touch at 10-13 11:00 yields the same outcome; robust to entry-bar choice.)
- Max favorable excursion: **+0.27R only** (high 2518.8). The trade went underwater almost immediately.
- Decline leg: 10-14 13:00 â†’ 2450, 14:00 â†’ 2416; then a 12h shelf 2400-2436 (10-14 14:00 â†’ 10-15 01:00) that held **above** stop 2385.
- **Stop hit 10-15 02:00** on a single flush bar (h2417 / l2314.4 / c2379.1), piercing 2385.

## Outcome vs target/stop
**STOP = -1.0R.** PC "LOST" confirmed. Target 2598 never approached (max 2518.8).

## Quarters ladder vs runner â€” both -1R
Rungs: +0.5R=2542.5, +0.75R=2568.8, +1R=2595. Price **never reached even +0.5R**.
- QUARTERS (25%@+0.5/+0.75/+1R + trail): no partial ever triggered â†’ full size stopped â†’ **-1.0R**.
- RUNNER (50%@+1R + trail): +1R never hit â†’ full size stopped â†’ **-1.0R**.
Identical. On a trade with no favorable excursion, exit management is inert â€” you cannot bank what the market never gives.

## Biggest risk / lesson
The stop was a **wick-out**: the flush bar closed back at 2379 and price recovered to 2421 by data end (-0.66R unrealized). A conviction-hold that survived the wick would currently sit *better* than the realized -1R â€” so the conviction-hold doc's instinct wasn't absurd here. But the real lesson cuts the other way: MFE was +0.27R, the trade was underwater from bar one, and intrabar it bottomed at -1.67R (2314). Holding through that exposed the book to a far worse loss than the -1R the mechanical stop realized. Conviction-hold "being right" on this path is survivorship luck on a recovering wick, not edge. Base-rate prior (n=1): AI-idea longs with sub-0.3R MFE in the first bar realize full -1R irrespective of exit style.