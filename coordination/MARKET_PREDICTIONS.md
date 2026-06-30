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
