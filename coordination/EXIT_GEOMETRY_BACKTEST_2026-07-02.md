# Exit-Geometry Backtest — Owner Decision D3 Evidence (2026-07-02)

Scope: archaeology + extensive backtest of the WIRING_AUDIT #4/#5 exit fixes vs the
"bread-and-butter era" config. **No live change ships from this document — evidence only.**
Script: `bot/tools/backtest_exit_geometry.py` (standalone, no bot imports; machine-readable
output in `bot/data/cache/exit_geometry_bt/results.json`).

---

## PART A — Archaeology: what changed, and when

`git log -p --follow` on `bot/execution/trade_profile.py`, `bot/execution/position_manager.py`,
`bot/trading_config.py`. Timeline of every exit-geometry parameter change (MEDIUM profile —
the one every LLM-first/current trade uses, since LLM-first passes no trade_profile and
falls back to MEDIUM defaults everywhere):

| Date | Commit | Param | Old → New |
|---|---|---|---|
| 02-20 | 83ca238 | MEDIUM profile born | tp1/tp2/sl = 1.0/2.0/0.75 ATR, tp1_pct 0.50, trail tighten 0.67→0.33, floor 0.30/0.30/0.65 |
| 03-04 | b2e9dd5 | trail/floor loosened | tighten 0.60→0.30; floor 0.35/0.25/0.60 |
| 03-05 | 0f4aea6, 9c0f3df | tp1_pct, SL | tp1_pct 0.50→0.65→0.70; sl 0.75→0.50 |
| 03-07 | d127292 | ranging adjustments | sl 0.50→0.55, tp1_pct→0.65; **ranging: SL×1.2 widen introduced** (TP×0.8 existed from birth); illiquid SL 0.8×→1.15× |
| 03-10 | 2026f73 | tp1_pct | 0.65→0.50 |
| 03-11 | 8c6991e | trail_end | 0.30→0.45 (premature-trail fix) |
| 03-16 | 674aff5 → 0e2185c | tp1_pct | 0.50→0.80 ("trailing returns $272/trade vs TP1 $610") — **reverted same day** to 0.50 |
| **04-01** | **9eca84a** | **PROFIT LOCK born** | **BE at 0.3R; lock 0.3R at 0.6R (all trades)** ← the original pre-TP1 protection |
| 04-03 | 0c311cd | MEDIUM floor | 0.35/0.25/0.60 → 0.15/0.40/0.70 (SOL gave back $22 of $51 peak) |
| 04-04 | 851bfb4 | trail tighten | 0.60/0.45 → 0.80/0.65 (wider effective trail) |
| 04-05 | 115a3d4 → 107f0f1 | MEDIUM TP/SL | sl 0.55→1.2→**1.0**; tp1 1.0→1.5→**1.0**; tp2 2.0→3.0→**2.0** (81% SL-hit fix, then R:R study) — **current values, unchanged since** |
| 04-16 | b937691 | profit lock profile-aware | MEDIUM BE 0.3R→**0.6R**, lock 0.6R→**1.0R** (Finding 22: 0.3R = noise) |
| **04-20** | **585518d** | **profit lock raised again** | **MEDIUM BE 0.6R→1.2R, lock 1.0R→1.8R** (SHIP-2026-04-20 reversal study) ← **last mechanical-geometry change, still live** |
| 06-07/06-09 | c32cd1b, 57cfb1d | **not geometry — ownership** | TIME_STOP and EARLY_EXIT mechanical closes handed to **LLM Exit Agent review**; LLM-first partial closes land in position_wiring with broken accounting (audit #2) |
| live env | bot/.env | TRAILING_STOP_ATR_MULT | **1.5** (pins the pre-widening value; trading_config default 2.0 with comment "widened 1.5→2.0, tighter trailing caused premature exits" — the .env override silently keeps 1.5) |

### The bread-and-butter answer

**The SL/TP/trailing geometry did NOT change between the profitable eras and now.** The MEDIUM
TP/SL/trail/floor numbers have been frozen since 04-05; the BE ratchet since 04-20. Three things
actually changed:

1. **04-01 → 04-20: the profit-lock ratchet was progressively de-fanged** (BE 0.3R → 0.6R → 1.2R).
   The original April "bread-and-butter" trailing behavior protected profit from +0.3R onward.
   Today there is a **0–1.19R dead zone** with zero protection (WIRING_AUDIT #4), and ranging-regime
   TP×0.8/SL×1.2 makes TP1 sit at ~0.67R — often unreachable before the unprotected retrace.
2. **06-07/06-09: exit ownership moved from mechanical to LLM.** June 1–6 (+$1,537, rows 1–13;
   every winner ≥$3 went `OPEN→TP1_HIT→TRAILING`) ran essentially mechanical exits. From 06-07 the
   Exit Agent reviews time-stops, tightens SLs in flight, and partial-closes without accounting.
   trades.csv shows it: post-06-07 there are only 11 TP1→TRAILING paths in 77 trades, and wins are crumbs.
3. **Sizing collapsed** post-blackout (June 1–6 risk ≈ $100–300/trade; late-June ≈ $3–30/trade),
   so even correct trailing wins can no longer produce June-sized PnL. (Out of scope here, but it
   caps what any exit fix can show in $.)

---

## PART B — Backtest

### Method

- All 90 trades in `bot/data/trades.csv` (2026-06-01 → 2026-07-01), each matched to its
  `TRADE_OPENED` event in `trade_events.jsonl` for entry/SL/TP1/TP2/ATR/qty/leverage
  (90/90 matched, entry-price tolerance 0.05%).
- Replayed against fresh Hyperliquid 1h candles (free `/info candleSnapshot`; 729 candles ×
  5 symbols, cached). funding_oi_history.jsonl NOT used (536h hole Jun 7–29); funding ignored.
- Engine mirrors `position_manager.update_price`: profit-lock ratchet → SL → TP1 partial (50%,
  cushion-BE) → trailing (1.5×ATR, tighten 0.80→0.65, floor 0.15/0.40/0.70 + min-BE floor) → TP2;
  4bps taker fee both legs; 72h hard hold limit (48h×1.5). Intra-candle path: green O→L→H→C,
  red O→H→L→C; entry candle skipped.

### Reproduction fidelity (V0 vs actual) — read this first

| Slice | n | Actual | V0 sim | MAE | Sign agreement |
|---|---|---|---|---|---|
| ALL | 90 | +$741 | -$344 | $43 | 74% |
| pre-Jun7 (June 1–6) | 13 | +$1,537 | +$1,943 | $120 | 92% |
| Jun7+ | 77 | -$795 | -$2,288 | $30 | 71% |

**Where mechanical exits actually governed, reproduction is near-exact**: ETH SHORT 06-03
actual +$1,010.37 vs sim +$1,012.32 (TRAILING); BTC SHORT 06-02 +$378.59 vs +$384.05 (TP2);
SOL SHORT +$377.05 vs +$341.11. The aggregate gaps are NOT sim error — they are the **live LLM
exit layer**, which the sim deliberately excludes:

- BTC SHORT 06-03: live SL was tightened in flight (66,062 → hit at 65,739, sl_hit=True below the
  opened SL) for -$141; untouched geometry rode to TP2 for +$356. The LLM layer cost ~$500 there.
- HYPE LONG 06-08: LLM bailed at 62.31 for -$223; mechanical SL at 59.33 = -$1,227. The LLM layer
  saved ~$1,000 there.

So V0 is a faithful simulation of the mechanical geometry, and a valid apples-to-apples baseline
for the variants — but it is NOT a replay of the live system post-Jun-7. **Confidence cap:
conclusions are about the mechanical exit engine in isolation; the LLM exit layer is a separate,
unmodeled (and currently unaccounted, audit #2) actor that both cut winners and saved losers.**

### Variant table (all 90 trades)

| Variant | Total PnL | WR | Avg win | Avg loss | Max DD | Sum R |
|---|---|---|---|---|---|---|
| V0 current config | -$344 | 45.6% | $76 | -$71 | $2,413 | -0.7R |
| V1 pre-TP1 trail @0.5R (#4 literal) | +$865 | 65.6% | $41 | -$49 | $586 | +4.0R |
| V2 post-TP1 progress from TP1 (#5) | -$353 | 45.6% | $76 | -$71 | $2,413 | -0.3R |
| V3 = V1+V2 | +$861 | 65.6% | $40 | -$49 | $586 | +3.9R |
| **V4 = Apr-16 profit lock (BE 0.6R / lock 1.0R)** | **+$1,116** | 60.0% | $51 | -$46 | $973 | +2.3R |
| V5 = V3+V4 | +$861 | 65.6% | $40 | -$49 | $586 | +4.0R |

Sensitivity sweep:

| Variant | Total PnL | WR | Max DD | Sum R |
|---|---|---|---|---|
| **S3 Apr-1 original lock (BE 0.3R / lock 0.6R)** | **+$1,589** | **70.0%** | **$570** | +2.8R |
| S4 = V4 + pre-TP1 trail @0.75R | +$696 | 60.0% | $687 | +2.8R |
| S1 pre-TP1 trail @0.75R only | +$490 | 53.3% | $730 | -2.6R |
| S5 BE 0.8R / lock 1.2R | -$411 | 51.1% | $2,301 | -3.7R |
| S2 pre-TP1 trail @1.0R only | -$1,309 | 45.6% | $2,426 | -4.7R |

### Per-era

| Variant | pre-Jun7 (13) | Jun7+ (77) |
|---|---|---|
| V0 | +$1,943 (69% WR) | -$2,288 (42% WR) |
| V1/V3/V5 | +$982–988 (77% WR) | **-$121 (64% WR)** |
| V4 | +$1,819 (77% WR) | -$703 (57% WR) |
| **S3** | **+$1,856 (77% WR)** | -$267 (69% WR) |

### Per-side

| Variant | LONG (28) | SHORT (62) |
|---|---|---|
| V0 | -$2,386 (29% WR) | +$2,042 (53% WR) |
| V1/V3/V5 | **-$342 (54% WR)** | +$1,203–1,207 (71% WR) |
| V4 | -$794 (54% WR) | +$1,910 (63% WR) |
| S3 | -$468 (61% WR) | **+$2,057 (74% WR)** |

### What each lever actually does (single-trade evidence)

| Trade | V0 | V1 (trail@0.5R) | V4 (BE 0.6R) | S3 (BE 0.3R) |
|---|---|---|---|---|
| ETH SHORT 06-03 (the +$1,010 runner) | +$1,012 | **+$503 — halves the runner** | +$1,012 | +$1,012 |
| SOL SHORT 06-03 (+$377 actual) | +$341 | +$87 | +$12 | +$57 |
| HYPE LONG 06-08 ($1,220 risk outlier) | -$1,227 | +$429 | +$31 | +$359 |
| HYPE LONG 06-03 | -$201 | +$41 | +$5 | +$5 |

- **V1 (the literal #4 fix)** is the best loss-killer (Jun7+ -$121, DD $586) but it strangles
  runners: the pre-TP1 floor locks ~45% of peak from 0.5R, cutting avg win from $76 to $41.
- **V4/S3 (earlier BE+lock ratchet, no floor)** keeps runners intact (they only ratchet to
  BE/+0.3R) while still converting most dead-zone reversals into scratches.
- **V2 (the #5 fix)** is nearly free and nearly invisible at 1h granularity (-$9 total, +0.5R):
  once TP1 hits, the trade usually either keeps running or falls to any floor. Fine to ship with
  either package; do not expect it to move PnL alone.

### Robustness caveats (honest)

1. **n=90, one month, 5 symbols.** $ totals are dominated by 13 large golden-era trades plus two
   HYPE outliers. The V4-vs-S5 cliff (BE 0.6R vs 0.8R = +$1,116 vs -$411) is literally 2 trades,
   one of which carried $1,220 risk (10x era-typical). The *direction* (early protection >>
   current 1.2R dead zone) is robust — every variant with protection ≤0.6R is strongly positive,
   every variant ≥0.8R is negative — but the exact trigger level (0.3 vs 0.6) is not identified.
2. **V0 does not reproduce post-Jun-7 actuals** (see above): live results there were shaped by the
   LLM exit layer. All variant deltas are mechanical-engine-vs-mechanical-engine.
3. 1h candles + path heuristic; no slippage beyond exact-level fills; no funding; dynamic-TP
   overshoot/speed scaling not simulated; entry candle skipped.
4. Trades replayed with recorded entry/SL/TP levels — entry quality and sizing are held fixed.
   Exit geometry cannot fix the Jun7+ entry mix (28 longs at 29% mechanical WR in a bear); it can
   only stop paying full-R for it.

---

## RECOMMENDATION

**Restore the early profit-lock ratchet — the actual bread-and-butter mechanism — rather than
shipping the literal #4 pre-TP1 trailing floor.**

1. **Primary (owner decision): lower the MEDIUM profit-lock triggers** in
   `position_manager.py:580-585` from BE 1.2R / lock 1.8R back toward the April values.
   Backtest-preferred: **BE at 0.3R (fee-buffered), lock 0.3R at 0.6R (S3: +$1,589 vs -$344
   current, 70% WR, max DD $570, keeps 96% of golden-era PnL, best short-side result)**.
   If the 04-20 reversal-study concern (25% reversal at 0.5R) still worries us, BE 0.6R / lock
   1.0R (V4) captures most of the benefit (+$1,116) with one fewer disputed trade.
   Expected impact at current posture: converts most 0.3–1.2R-peak reversals (the crumb-win /
   full-loss signature in exit_closes.jsonl) into scratches or small locks; roughly +$1,400–1,900
   vs current geometry over a June-like month at June sizing, +2.7–3.5R at any sizing.
2. **Ship #5 (V2, progress-from-TP1) alongside** — costs nothing measurable, removes the
   57.5%-insta-lock dead-code contradiction with the cushion-BE, +0.5R.
3. **Do NOT ship the literal #4 floor-at-0.5R (V1/V3/V5) as the default**: best DD and best
   chop-era survival, but it halves runner wins (ETH +$1,010 → +$503). If the owner prioritizes
   drawdown over expectancy it is a defensible alternative (+4.0R, DD $586); the data says the
   BE/lock ratchet dominates it on total PnL in both eras.
4. **Separate but bigger lever the sim exposed**: the in-flight LLM exit layer (SL tightening,
   early closes) is what actually diverges from mechanical geometry post-Jun-7 — it saved ~$1,000
   on one outlier and cost ~$500 on a golden-era runner, and its partial closes are still an
   accounting black hole (audit #2). Fix the accounting before judging or expanding its authority.

Confidence: **medium-high on direction, low-medium on exact trigger level** (caveats 1–3 above).
Next validation step before shipping: re-run with `PROFILE_MEDIUM_*`/trigger values via a shadow
A/B (the ab_tests harness) or paper-fork for ≥2 weeks, per backtest-before-adding.

*Generated by `bot/tools/backtest_exit_geometry.py`; raw per-trade results in
`bot/data/cache/exit_geometry_bt/results.json`.*
