# M32 ladder atlas (Project X parts 1-2): the mean is a wash for EVERY scale-out style (NET real-null ~0, convergence holds) - but the DISTRIBUTION genuinely differs. Quarters buys a SMOOTHER ride (fewer losing trades, lower variance) by capping big runners ~0.24R; fully scaling out (no trailing quarter) WRECKS the loss tail. Keep a trailing remainder.

_2026-10-15. m32_ladder.py, 51,930 moments / 176 coins, m28 grid, point-in-time, persistence-preserving
null. EXPLORATORY. Fees = bps of NOTIONAL (constant across styles; the SUI dive's thin-book lane
corrected an earlier per-leg model). Matches the server's 28-trade seed (runner +0.168R, quarters +0.162)._

## The surface (vs the runner; mean control-subtracted vs the null)
| style | NET mean (real-null) | P(loss) | P(<=-1R) | variance (SD) | big-runner cost |
|---|---|---|---|---|---|
| runner (50%@+1R+trail) | 0.000 (ref) | 0.536 | 0.050 | 0.800 | 0 (ref) |
| **quarters** 25%@.5/.75/1R+trail | **+0.0007** | **0.468** | 0.078 | **0.712** | **-0.236** |
| thirds 33%@.5/1R+trail | +0.0005 | 0.486 | 0.064 | 0.713 | -0.195 |
| 25/25 25%@.5+25%@1R+50%trail | +0.0004 | 0.517 | 0.050 | 0.738 | -0.114 |
| aggr 33%@.5/.75/1R, ~0 trail | +0.0008 | 0.441 | **0.258** | 0.711 | -0.359 |

## What it means
1. **MEAN is a wash** - NET (real minus the persistence-preserving null) is within +/-0.001R of zero for
   every style. No ladder adds or subtracts expectancy. (8th time the mean hasn't moved; convergence
   holds, exactly as the PC framed Project X - this is about SHAPE, not mean.)
2. **The distribution is where ladders live.** Quarters cuts the losing-trade rate 53.6% -> 46.8% and
   variance 0.80 -> 0.71 - a smoother equity curve, which has real value to a human trader at equal
   mean. The price: it caps the big runners by -0.24R and slightly RAISES the full-stop rate
   (5.0% -> 7.8%), because trimming early leaves the last leg exposed on the trades that reverse.
3. **Do NOT fully scale out.** "aggr" (no trailing quarter) has the lowest loss rate (44%) but its
   P(<=-1R) explodes to 25.8% - dropping the trailing remainder removes the cushion that keeps a
   reversal from becoming a full stop. The trailing quarter in the owner's QUARTERS default is doing
   real work.
4. **25/25 is the gentlest** (keeps 50% trailing): barely changes P(loss) or the tail, lowest
   big-runner cost (-0.11R) - a milder smoothing than quarters.

## Owner rules (one number each)
1. Laddering doesn't make or lose you money on average - it makes the ride SMOOTHER. (mean change: ~0)
2. Quarters = fewer red trades and a calmer curve, paid for by clipping your big winners. (big-runner
   cost: -0.24R)
3. Never scale out your WHOLE position - always leave a piece trailing, or your worst-loss rate jumps.
   (P(-1R): 5% with a trail -> 26% without)

## Next (Project X)
Part 3 (the prize): a point-in-time atlas of WHICH trades fade after +0.5R (velocity/volume/funding/BTC/
liq/time-of-day) - if fade is predictable at the peak, THAT tells you when to ladder harder (a
conditional signal, not a dial). Swarm next. Also parts 4-6 (fee/slippage done qualitatively here;
wallet A/B exit-vs-entry; his plans as labels).
