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
