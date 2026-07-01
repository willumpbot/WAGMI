# Market Predictions Scorecard — alpha-brain validation

Made 2026-06-30 ~16:00 UTC (owner away 6-12h). Resolve each vs actual price. Goal: confirm the directional read is correct.

| # | Symbol | Price @ call | Call | Falsifiable condition | Conf | Outcome |
|---|--------|-------------|------|----------------------|------|---------|
| p1 | BTC | 58434.5 | **down** | BTC < 58434.5 in ~12h (falling funding = longs unwinding, no fuel for upside) | 55%% | _pending_ |
| p2 | ETH | 1566.75 | **flat** | ETH within +/-1.5%% of 1566.75 in ~12h (chop) | 50%% | _pending_ |
| p3 | SOL | 73.2465 | **down** | SOL < 73.2465 in ~12h AND underperforms BTC | 62%% | _pending_ |
| p4 | HYPE | 65.2105 | **down** | HYPE <= 65.2105 in ~12h | 55%% | _pending_ |
| p5 | XRP | 1.03555 | **up_or_flat** | XRP > 1.025 in ~12h (no breakdown; do NOT short) | 55%% | _pending_ |

## Rationale (the alpha read)
- **BTC (down)**: funding falling 8%/yr, OI flat, no divergence -> mild bearish/neutral
- **ETH (flat)**: low funding 4.3%/yr, flat OI -> no catalyst, range
- **SOL (down)**: crowded longs (funding +10.8%/yr) + liquidation OI-divergence + sol_long_veto 14/14 toxic-long edge -> biased DOWN (highest conviction)
- **HYPE (down)**: crowded longs (funding +11%/yr), flat OI -> mean-revert lean down
- **XRP (up_or_flat)**: funding rising but NEGATIVE -9%/yr = crowded SHORTS -> squeeze risk up / avoid-short

## Resolutions
(autonomous loop appends actual price + right/wrong + running accuracy as the horizon elapses)

### Interim reading — 2026-06-30 17:08 UTC (~1.1h / 12h elapsed; NOT resolved, noise-level)
| # | Sym | price0 | now | move | call | on-track? | driver |
|---|-----|--------|-----|------|------|-----------|--------|
| p1 | BTC | 58434.5 | 58578.5 | +0.25% | down | no (above) | funding-crowding (weak) |
| p2 | ETH | 1566.75 | 1575.65 | +0.57% | flat | yes (in ±1.5%) | low-funding/no-catalyst |
| p3 | SOL | 73.2465 | 73.8385 | +0.81% | down | no (above) | sol_long_veto 14/14 + OI-div |
| p4 | HYPE | 65.2105 | 65.0645 | -0.22% | down | yes (below) | funding-crowding |
| p5 | XRP | 1.03555 | 1.04275 | +0.70% | up_or_flat | yes (>1.025) | crowded-shorts squeeze |

Interim: 3/5 currently on-track, but ~1h is below signal — the two "down" highest-conviction calls (SOL, BTC) are slightly red against us so far. Real scoring at the 12h horizon (~04:00 UTC Jul 1).

## FINAL RESOLUTION — 2026-07-01 03:55 UTC (~12h horizon)
| # | Sym | price0 | final | %move | call | driver | RESULT |
|---|-----|--------|-------|-------|------|--------|--------|
| p1 | BTC | 58434.5 | 59241.5 | +1.38% | down | funding-crowding (mild) | WRONG |
| p2 | ETH | 1566.75 | 1596.8 | +1.92% | flat | low-funding/no-catalyst | WRONG (broke above +1.5% band) |
| p3 | SOL | 73.2465 | 75.5985 | +3.21% | down | funding-crowd + OI-div + sol_long_veto | WRONG |
| p4 | HYPE | 65.2105 | 65.6425 | +0.66% | down | funding-crowding | WRONG |
| p5 | XRP | 1.03555 | 1.05175 | +1.56% | up_or_flat | crowded-shorts squeeze (funding) | CORRECT |

**RUNNING ACCURACY: 1 / 5 (20%).**

### Honest verdict — did the directional alpha work?
NO, not this window. 1/5. A broad market melt-up (+1.4% to +3.2% across majors) ran over every "crowded longs -> mean-revert DOWN" call (BTC/SOL/HYPE all wrong; ETH trended out of its flat band too). The ONLY hit was the contrarian XRP "crowded SHORTS -> squeeze UP" call.

### The signal that actually scored — and the lesson
Funding-crowding worked as a **SQUEEZE detector** (XRP: crowded shorts -> price squeezed UP into their pain = correct) but **FAILED as a mean-reversion FADE** (crowded longs did NOT revert down; trend/momentum won). Hypothesis to log + test (n=1, do NOT overfit): *crowding predicts continuation toward the squeezed side / max pain, not reversal.* If it holds up, the fix is to flip the sign of the crowding->direction mapping for the "crowded longs" case (or gate it to only fire as a squeeze/breakout signal, not a fade).

### sol_long_veto note (owner flagged)
The sol_long_veto DOWN thesis was **doubly contradicted**: SOL rose +3.21% AND the bot's own epsilon-override SOL LONG (opened 19:38 against the veto) was the session's winning position. The veto's *historical* live edge is still 14/14 on closed trades — but as a same-day directional PRICE forecast it was wrong here. Keep the veto (trade-level edge stands); do NOT treat it as a short-horizon price predictor.
