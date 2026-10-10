# Liquidation clusters as magnets: re-check 2026-10-09

Question (the owner's own reasoning on his SOL plan, "the liq?"): does price reach a nearby cluster of past
liquidations (>=3 independent episodes within 0.2%, 0.3-3% away) within 6h more often than a random level at the
same distance and side? Pre-registered harness `tools/copilot/liq_magnet_calibration.py`, BTC + SOL (Bybit feed).

| candles (HL keeps last 5000) | days | magnet episodes | magnet - matched random | day-clustered 95% CI | weeks positive |
|---|---|---|---|---|---|
| 5m | 18 | 875 | **+8.2 pts** (45.7% vs 38.4%) | [+2.2, +14.3] | 2 / 4 |
| 15m | 32 | 1,385 | +5.0 pts | [-0.7, +10.4] | 3 / 6 |
| 1h | 44 | 1,752 | +3.0 pts | [-1.7, +7.6] | 4 / 8 |

Original harness checks (5m): vol-matched control +5.6 pts [2.6, 8.8]; chronological OOS half +8.3 [4.1, 12.8];
price-shuffle negative control -0.8 pts (design does not manufacture an effect); K sweep 2/3/4 all positive.
Day-clustered check: `tools/copilot/liq_magnet_dayclustered.py --interval=5m|15m|1h`.

**Verdict: SUGGESTIVE, NOT ESTABLISHED.** Recent weeks show clusters get tagged a bit more than random levels, but
over the longer window the gap is not distinguishable from zero and flips sign week to week. Consistent with H3
(clusters = cascade risk, not direction). Coarser candles dilute "reach" for both arms, so the 1h number may
understate; the honest fix is more 5m history, which only time provides (liq feed for ETH/HYPE/XRP/NEAR began Oct 8).

Plain rules for the owner:
1. A liquidation cluster nearby is a place price *might* visit: maybe ~5 points more often than a random level. Not enough to trade on alone.
2. Use clusters for where NOT to put your stop (stops sitting on a cluster get swept), not as a target to bet on.
