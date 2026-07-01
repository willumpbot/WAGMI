# BT_SIZING_LADDER — Confidence-Calibrated Sizing Ladder Backtest (Master-Plan P3)

Date: 2026-07-01 | Lane: sizing ladder replay | Script: `bot/tools/backtests/sizing_ladder_backtest.py`
Data: `bot/data/trades.csv` (90 closed trades, 2026-06-01 → 2026-07-01, `pnl` column is NET of fees per `multi_strategy_main.py:3805-3808`).

## Method & reproduction-fidelity caveats (read first)

- **Replay method:** variant PnL per trade = actual net PnL x band multiplier. This is exact where PnL scales linearly with notional (1x-leverage era, 47/90 trades) and a linear approximation for the early 1.5x–5.6x leverage trades (no actual trade was liquidated, so no path-dependence break, but margin effects are ignored).
- **This is a resizing replay, not a re-simulation.** Entries/exits/SL/TP paths are taken as they actually happened. A real ladder would also change adaptive-streak state (e.g. cold-streak multipliers depend on prior PnL), which is NOT modeled.
- **19 of 90 trades (21%) have confidence == 0 and empty `entry_reasons`** — the pre-fix metadata gap (fixed in `position_manager.py` ~line 407, "81/85 zeros" bug). The ladder cannot be applied to them. Both scenarios reported: KEEP (held at 1.0x in every variant) and DROP (excluded everywhere, incl. baseline).
- **Recovery attempt failed honestly:** matching the 19 UNK trades to `thesis_history.jsonl` by symbol + entry price found same-day matches for the two biggest wins (BTC +378.59 → thesis conf 45; ETH +1010.37 → thesis conf 45) but thesis confidence is the LLM 0–100 scale, NOT the ensemble-confidence scale the ladder bands use (e.g. trade 1: ensemble 68.8 vs llm 27). Several other "matches" were days-stale price coincidences. UNK stays UNK. Note the uncomfortable hint: the two giant wins may have been ~mid/low-LLM-confidence trades.
- Band multipliers for conf <60 (n=3, not defined in the mandate): assigned the lowest defined band's multiplier (V1 0.3x, V2 0.15x, V3 0x).

## Band summary — actual PnL, honest denominators (n=90)

| Band  | n  | Wins | WR    | PnL sum ($) | Avg ($) |
|-------|----|------|-------|-------------|---------|
| UNK   | 19 | 10   | 52.6% | **+1,749.61** | +92.08 |
| <60   | 3  | 1    | 33.3% | +2.58       | +0.86   |
| 60-69 | 46 | 8    | 17.4% | -374.49     | -8.14   |
| 70-79 | 14 | 0    | **0.0%** | **-721.64** | -51.55 |
| 80-89 | 7  | 4    | 57.1% | +67.98      | +9.71   |
| 90+   | 1  | 1    | 100%  | +17.07      | +17.07  |

Era split (actual): pre-Jun-7 n=13, **+1,536.56**; post-Jun-7 n=77, **-795.45**.
The entire positive book is 3 pre-Jun-7 UNK-band high-leverage wins (+1,010.37 ETH, +378.59 BTC, +377.05 SOL = +1,766 of the +1,750 UNK total).

## Variant results

Variants (multiplier on top of actual sizing): V0 actual; V1 ladder (<80→0.3x, 80-89→1.1x, 90+→1.3x); V2 harsher (<80→0.15x, 80+ as V1); V2b = V2 but NO 80+ upweight (1.0x); V3 80+-only (<80→0x, 80+ as V1).

### Scenario KEEP (19 UNK trades held at 1.0x in all variants)

| Variant | Total PnL ($) | Max DD ($) | Top-1 win share | Top-3 win share | Pre-Jun7 ($) | Post-Jun7 ($) |
|---------|--------------|-----------|-----------------|-----------------|--------------|---------------|
| V0 actual  | +741.11  | 818.85 | 48.1% | 84.0% | +1,536.56 | -795.45 |
| V1 ladder  | +1,518.51 | 269.23 | 50.6% | 88.5% | +1,746.16 | -227.65 |
| V2 harsher | +1,682.55 | 157.44 | 51.3% | 89.7% | +1,789.74 | -107.20 |
| V2b no-up  | +1,670.63 | 156.09 | 51.7% | 90.3% | +1,783.51 | -112.88 |
| V3 80+only | +1,846.58 | 60.03  | 52.0% | 90.9% | +1,833.32 | +13.26 |

### Scenario DROP (19 UNK trades excluded everywhere — the "known-confidence book")

| Variant | Total PnL ($) | Max DD ($) | n traded | Top-3 win share | Pre-Jun7 ($) | Post-Jun7 ($) |
|---------|--------------|-----------|----------|-----------------|--------------|---------------|
| V0 actual  | **-1,008.50** | 1,008.50 | 71 | 59.1% | -228.21 | -780.29 |
| V1 ladder  | -231.10  | 257.08 | 71 | 58.0% | -18.61  | -212.49 |
| V2 harsher | -67.06   | 126.68 | 71 | 63.4% | +24.97  | -92.04  |
| V2b no-up  | -78.98   | 125.33 | 71 | 61.3% | +18.74  | -97.72  |
| V3 80+only | +96.97   | 14.89  | 8  | 77.7% | +68.55  | +28.42  |

Win-dollar concentration is high in every variant (top-3 wins = 58–91% of gross win dollars); against ~$497 equity, V0's $818–1,008 max DD vs V2's ~$126–157 is the material risk difference.

## Fragility check — the 80+ band (mandated)

n=7 in 80-89 plus n=1 at 90+ → **n=8 total in 80+**. All 8, listed:

| Time (UTC) | Sym | Side | Conf | Lev | PnL ($) |
|---|---|---|---|---|---|
| Jun 5 19:30 | BTC | SHORT | 85.00 | 5.6 | +39.03 |
| Jun 6 04:38 | BTC | SHORT | 87.70 | 5.6 | +15.09 |
| Jun 6 11:38 | HYPE | SHORT | 82.90 | 4.0 | +8.20 |
| Jun 22 01:28 | BTC | SHORT | 87.78 | 1.0 | -4.09 |
| Jun 24 11:52 | BTC | SHORT | 82.41 | 1.0 | -9.45 |
| Jun 24 16:27 | ETH | SHORT | 82.87 | 1.0 | +21.83 |
| Jun 25 14:33 | SOL | SHORT | 94.76 | 2.0 | +17.07 |
| Jul 1 18:28 | HYPE | SHORT | 82.90 | 1.0 | -2.63 |

- **100% of the 80+ band's win evidence sits in 5 wins totaling $101.22 gross ($85.05 net for the band).** Largest single win ($39.03) is 38.6% of the band's gross wins and came in the 5.6x-leverage era.
- All 8 are SHORTs (June was a downtrending month) — the band has zero evidence in an up-regime.
- The 90+ band is **n=1**. A 1.3x multiplier there is fitted to a single trade.
- Verdict on upweighting: **not supported yet.** V2b (harsh cut, no upweight) captures ~99% of V2's improvement (-78.98 vs -67.06 DROP; 1,670.63 vs 1,682.55 KEEP). The ladder's value is ~entirely in CUTTING 60-79, not in boosting 80+.

## What is robust vs. fragile

**Robust (n=60):** the 60-79 confidence region is toxic — 8/60 wins (13.3% WR), -$1,096 combined, with 70-79 a perfect 0-for-14. Downsizing it to 0.15–0.3x improves every metric in both scenarios and cuts max DD by 75–85%. This is the actionable result.

**Fragile (n=8):** upweighting 80+ to 1.1x/1.3x adds ~$12–16 total across a month — noise-level, single-regime, leverage-era-confounded. Per the n>=13 evidence rule, do not encode the upweight yet.

**Unknown (n=19):** the trades that made all the actual money have no confidence metadata. The ladder is therefore validated only on the losing 71-trade subset; whether high confidence would have caught the June-2/3/4 giants is unknowable from this data.

## Recommendation

1. Adopt the CUT side of the ladder now: conf 60-79 → 0.15x (V2 posture). Reversible, validated on n=60, biggest DD reducer.
2. Hold 80+ at 1.0x (V2b) until the band reaches n>=13 with positive expectancy in more than one regime; then revisit 1.1x/1.3x.
3. Do NOT adopt V3 (80+-only) yet: best numbers but only 8 qualifying trades in a month (~0.27/day) — starves the learning loop and the ~2-trades/day mandate; its post-Jun-7 edge (+$28 on 5 trades) is not evidence.
4. Confidence logging gap is closed going forward; re-run this ladder when the post-fix sample reaches ~150 trades.
