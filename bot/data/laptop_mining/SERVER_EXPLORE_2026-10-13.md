# Server exploratory batch 2026-10-13 (Opus agents; EXPLORATORY - nothing here is an edge)

## A. Frozen gates recomputed scale-free (scripts in scratch_gates/)
Exact reproduction of the live gates: longs n=22, -$29.7/trade, WR 9% vs breakeven 93% -> block on, size mult 0.25;
shorts n=43, +$18.4 -> 1.5; solo gate n=32, WR 18.8% vs 57% -> on. Last long passing the $0.50 fee filter closed
2026-07-23.
R per trade: realized_rr (81/295 rows) else reconstructed from the TRADE_OPENED sl (293 matched; agrees with
realized_rr to about ±0.01 where both exist). % of notional net of fees via each trade's fee/gross ratio.

| Gate | Current | R all-time | R last 30/60d | R 90d | R by month (Jun/Jul/Sep/Oct) |
|---|---|---|---|---|---|
| Side mult LONG | 0.25 | n 119, -0.173R (t -2.5) -> 0.78 | n 15, -0.163R -> 0.80 | n 35, -0.267R (t -3.2) -> 0.67 | -0.43 / -0.04 / -0.12 / -0.29 |
| Side mult SHORT | 1.5 | n 176, -0.040R (t -0.5) -> 0.95 | n 6 -> neutral | n 47, -0.067R -> 0.92 | -0.03 / -0.05 / -0.25 / +0.28 |
| Long block | on | DRAIN | DRAIN (t -1.9) | DRAIN (t -3.2) | Jun/Jul drain; Sep/Oct n<13 |
| Solo gate | on | on (n 68, -0.288R, t -2.4; multi-signal -0.04R, n 78) | 0 trades -> would switch off (starved) | n 12 (<13) | -0.21 / -0.49 |

So: the short 1.5x boost is a June-dollar artifact (gone in R); the long 0.25x relaxes to ~0.66-0.80; the long block
SURVIVES every definition; the solo gate only "switches off" when windowed because it starved its own data.
Probes since 07-27: LONG 17 (all under the fee filter) -0.14R (t -1.9), -44 bps; SHORT 22 (17 under) -0.10R by ledger
R but +4.9 bps net (t 0.1) - unit-dependent (wide-stop winners vs tight-stop losers) -> pick ONE canonical unit.

Proposed shadow definition (for laptop red-team):
- R_i = realized_rr, else (side*(exit-entry)/entry - fee_frac) * entry/|entry-stop| (stop = stop_initial else
  TRADE_OPENED sl; fee_frac = fees*|ret|/|gross|), clipped to [-3, +5]; no fee filter, no dollars.
- Recency: w_i = 0.5^(age_days/45); n_eff = (Σw)²/Σw²; m = Σw·R/Σw; se = sqrt(Σw(R-m)²/Σw / n_eff).
- Size mult = clip(1 + 1.25·m·n_eff/(n_eff+13), 0.25, 1.5) - never boosts a cell without its own evidence
  (today LONG 0.81, SHORT 0.96).
- Long block on iff n_eff >= 13 and m + 0.84·se < 0 (today LONG on: m -0.179, upper -0.116; SHORT upper +0.022).
- Solo gate: same rule; if fewer than 13 recent trades, fall back to all-time (don't switch off from starvation).
- Exploration / blocked-go probes count as evidence, flagged.

## B. Chief expected_move vs HAR
The chief COPIES HAR (HAR is in its input via voice_vol): mean |chief - HAR| 0.12 pts; 44 of 60 calls within 5%.
Graded n=24 (4 batches, one day): MAE chief 1.568 vs HAR 1.566; QLIKE 0.962 vs 0.971 - indistinguishable. All
forecasts under-forecast (realized mean 3.16% vs ~2.7%).
Prereg only after removing next_day_move_pct from the chief's input; otherwise cut the field / its Opus spend.
Sketch: QLIKE(chief - HAR) at 24h, day clusters, 30 days x 6 coins, one-sided, block bootstrap; drop the field if not
better by ~0.05 QLIKE.

## C. Forgotten 10-07 leads
- Risk veto: live (coordinator.py ~5099-5102: override == "skip" -> skip) but 0 blocks in 23 GOs since the Sonnet risk
  agent. The +18.6 bps (CI +3.5..+34.7, p 0.015, 611 vs 332) came from the old Haiku agent that blocked ~35%; it was a
  loss-reducer (let-through still -17 bps), concentrated in June and HYPE/NEAR. Not testable forward as-is; only a
  token-costing shadow re-run of the old prompt could test it - laptop design question.
- Overseer themes (data/manager_audit/scorecard.json curated_theme_grades; 410 calls Jun 1-Jul 13, 63% untestable):
  RIGHT: avoid consolidation (+$474, n 160), avoid range (+$97), avoid trend-family (+$310), avoid LONG (+$247), favor
  SHORT (+$146), cap leverage 2x (+$200, n 31), block HYPE LONG (+$387, n 14), night block 0-12 UTC (+$277, n 135).
  WRONG: block ETH/SOL SHORT (-$499), focus HYPE LONG (-$807). THIN: cap 5x (n 5). Caveats: themes picked after the
  fact, overlapping, regime labels weak. Never applied (Overseer disabled: AGENT_OVERSEER_ENABLED=false).
  Prereg proposal: seal 5 as shadow slice rules (avoid LONG, cap leverage 2x, night 0-12 UTC, avoid consolidation/range,
  block HYPE LONG) on forward ledger trades; activate only at n >= 13 in-slice with a one-sided bootstrap + Holm across
  the 5; regime-based ones need regime filled at entry first; night/leverage can start now; ~60-90 days at ~2/day.

## D. Microcap x Syndicate
16 of 334 called coins were seen by the microcap pipeline before their call (8 with flow data) - too thin to use.
Fix is a collector: call_snapshot now also snapshots each call at +1h and +6h (stages call / h1 / h6), live 2026-10-13.

## E. Positioning/liquidity streams as SIZE predictors (scratch_streams/)
Outcome y = next-day |close-to-close| / HAR stage-1 (stage 2 already contains funding). 672 coin-days, 13 coins, day
clusters, per-day Spearman + top-20% gap. Nothing reaches |t| > 2.5 (bar ~3.1 after ~20 tests). Positive control
funding_hot: +18.8% (t 2.25, 38 days) - right sign, but MDE ~+23% vs the known +7.7% -> ~330 13-coin days needed.
OI change, liquidation imbalance: null (|t| <= 1.6). Liquidation burst (24h notional / own 30d median): +30.5%,
t 1.89, only 14 usable days. Data gaps: funding_oi 13 coins only from Aug 1 (5 before), gaps Aug 13-Sep 6, Sep 16-17,
Sep 29-Oct 3; liq collector down Aug 12-Sep 7 + partial days. Recommendation: no prereg yet; optional forward-only
liq_burst prereg (n=120 eligible days, SUPPORT t >= 2.5 and >= +10%, funding_hot control under the same machinery).
