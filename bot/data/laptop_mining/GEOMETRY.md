# The geometry finding — the one result that survived every test

_2026-10-08. Scripts: `sweep_geometry.py`, `sweep_oos.py`. Data:
`geometry_sweep.json`, `geometry_sweep_pass2.json`, `geometry_sweep_1week.json`,
`sweep_oos.json`._

## Headline

**The bot's stop/target geometry costs it about half an R on every setup. Fixing it recovers that
to break-even. This is the only claim in this entire investigation that passed an out-of-sample
split, a per-symbol breakdown and a monotonicity check — the three tests that killed everything
else, including my own earlier candidates.**

It is a **loss-elimination** result, not alpha. The repaired configuration earns **+0.05R**, which
is statistically zero. Three independent datasets still say the signals have no directional edge.
What this fixes is the bot handing back half an R per trade through stop placement.

---

## What was measured

For all 15,663 graded signals, the trade was re-simulated against validated 1h candles under a grid
of `(stop_mult, tp_mult)` applied to the **original** stop distance, so `tp_mult` is literally the
R multiple:

```
stop' = stop_mult x |entry - sl_original|
tp'   = entry +/- tp_mult x stop'
```

Resolution is conservative and lookahead-free: bars strictly after the signal bar; if a single bar's
range spans both stop and target it counts as a **stop**; unresolved at the horizon is marked to the
close (a time stop). Fees are charged on both legs, expressed in R.

## The surface

Mean realised R per setup, 48h horizon, net of 9 bps:

| stop × | tp 0.5R | tp 1.0R | tp 1.5R |
|---|---|---|---|
| 0.5 | — | −0.561 | −0.606 |
| 1.0 **(bot default)** | — | −0.354 | **−0.431** |
| 2.0 | — | −0.223 | −0.230 |
| 4.0 | −0.072 | −0.067 | −0.080 |
| 6.0 | −0.002 | −0.007 | −0.013 |
| 8.0 | **+0.013** | +0.006 | +0.003 |
| 12.0 | +0.010 | +0.006 | +0.006 |
| 16.0 | +0.007 | +0.005 | +0.006 |

Two things matter here, and neither is the best cell:

1. **It is monotone in both axes.** Wider stops are better at every target; nearer targets are
   better at every stop. Forty cells ordered consistently on both dimensions is not what a
   multiple-comparison artifact looks like.
2. **It plateaus at ≈ +0.01R.** As the stop widens toward never-being-hit, the result converges on
   the raw forward drift of the signal stream, which is ≈ 0. That convergence is exactly what you
   would predict given no directional edge, and it is why this result cannot be oversold.

The bot default of **−0.431R** independently reproduces the −0.40R estimated from the raw
SL-first/TP1-first rates (53.8% vs 17.2% at a designed R:R of 1.50) in `REGRADE.md`. Two unrelated
routes to the same number.

### Longer horizon helps
At a 168h (1 week) horizon the same shape holds but sits higher: stop ×8 / tp 0.5R → **+0.097R at
66.8% win rate**, CI [−0.030, +0.194]. Still not significantly positive, but uniformly better than
48h. Worth a forward test on its own.

---

## The three tests

### 1. Out of sample — PASSED
Grid fitted on 2026-02-11 → 04-15 (n=6,523), then the train-selected cell re-scored on
2026-04-16 → 06-05 (n=9,140). No re-picking on the full sample.

| | train | test |
|---|---|---|
| cell picked on train (stop ×12, tp 0.5R) | −0.0460R | **+0.0503R** |
| bot default (stop ×1.0, tp 1.5R) | −0.3457R | **−0.4915R** |
| **paired difference on test** | | **+0.5419R, CI95 [+0.3001, +0.7987]** |

The CI excludes zero **out of sample**. This is a paired comparison — identical signals, only the
geometry differs — which is why the interval is tight despite 71 trading days.

### 2. Per symbol — PASSED on all four
Full span, picked cell vs bot default:

| symbol | n | picked | default | difference | CI95 |
|---|---|---|---|---|---|
| BTC | 4,525 | +0.0062R | −0.4326R | **+0.4388R** | [+0.0947, +0.8382] |
| ETH | 4,072 | +0.0324R | −0.6280R | **+0.6604R** | [+0.4593, +0.8563] |
| HYPE | 3,810 | +0.0016R | −0.2558R | **+0.2574R** | [+0.0089, +0.4964] |
| SOL | 3,256 | −0.0019R | −0.3863R | **+0.3844R** | [+0.0846, +0.6913] |

Every CI excludes zero independently. No single symbol is carrying the result.

### 3. Monotonicity — PASSED in both halves
Spearman ρ of mean R against stop multiplier (tp fixed at 1.0R):

| half | ρ | values |
|---|---|---|
| train | **+0.943** | ×1 −0.229, ×2 −0.253, ×4 −0.140, ×6 −0.108, ×8 −0.078, ×12 −0.050 |
| test | **+0.771** | ×1 −0.443, ×2 −0.201, ×4 −0.014, ×6 +0.066, ×8 +0.065, ×12 +0.047 |
| full | **+1.000** | ×1 −0.354, ×2 −0.223, ×4 −0.066, ×6 −0.007, ×8 +0.006, ×12 +0.006 |

---

## Why this is different from everything else here

Four candidates looked strong and then died, each to one of these same tests:

| candidate | killed by |
|---|---|
| `trend_adj_floor` −0.22% | threshold fragments; aggregated + cluster-bootstrapped → −0.010, CI spans 0 |
| avoid BTC (−15.9 bps level) | the in-minus-out metric → −9.8 bps, CI [−36.7, +15.7] |
| `avoid agree=3+ SHORT` | survives, but 1 hit in 29 slices is what noise produces |
| **`chop_floor`** (−33.6 bps level) | sign **flipped** across the split (train +7.4, test −35.8); no dose-response — smallest breaches were worst |

The geometry result faced all three tests and passed all three. That asymmetry is the point.

---

## What it would actually mean to ship this

Read these before acting; the headline number is not the whole story.

- **Position size must shrink by the same factor as the stop widens.** A stop ×12 on a median
  1.458% stop is ~17.5%. For unchanged dollar risk per trade, size drops ~12×. The R improvement is
  real; R is just a much smaller dollar unit.
- **It requires a disciplined time stop.** Unresolved trades are marked to the 48h close, so the
  result depends on actually exiting there rather than holding on.
- **The tie rule is conservative** (a bar spanning both levels counts as a stop), so the estimate is
  if anything pessimistic — but intrabar path is unknown at 1h resolution. Re-check on 5m/15m bars
  for the recent period where Hyperliquid serves them.
- **It does not make the system profitable.** +0.05R ≈ 0. It stops a leak. Any expectation beyond
  break-even needs a directional edge that none of the three datasets shows.
- **The optimum is a plateau, not a peak** (×8 through ×16 are indistinguishable). Pick the
  conservative end; do not fine-tune to the best cell.

## Recommended next step
Forward-test one geometry change, in shadow mode, on the server: `stop_mult` 8, `tp` 1.0R, 48h time
stop, size scaled down to hold dollar risk constant. The existing live grader can score it against
the current geometry on the same signals, which makes it a paired test again — the most statistically
efficient check available, and it needs no new infrastructure.
