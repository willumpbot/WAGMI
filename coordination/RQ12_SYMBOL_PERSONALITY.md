# RQ12: Symbol Personality — Per-Symbol Parameter Cards

**Date:** 2026-07-01 | **Author:** RQ12 agent | **Standard:** THE_STANDARD.md compliant
**Data:** `bot/data/trade_ledger.csv` — 156 closed trades, 2026-06-01 17:24 → 2026-07-01 20:56 UTC (BTC 43, ETH 43, SOL 31, HYPE 29, XRP 10). Ground truth: Hyperliquid 1h + 15m candles (745 / 2,982 per symbol, full coverage of trade window). Replay at 15m resolution; ATR = ATR14 on 1h candles at entry. Fee estimate from actual ledger fees: **0.041%/side (0.082% round trip), n=155**.
**Script:** `bot/tools/research/rq12_symbol_personality.py` (re-runnable; fetches candles live).
**Era split:** era1 = Jun 1–15 (pre-blackout, big sizing), era2 = Jun 16–Jul 1 (recovery, small sizing). Median notional era1 **$2,640** (n=63) vs era2 **$391** (n=92) — a 6.8x sizing shift that dominates all $-denominated comparisons.

---

## Headline findings (the personality that matters)

### 1. Winners don't breathe. Trades are decided immediately.
Across all 36 winning trades, **26 had ZERO adverse excursion (MAE) before their peak favorable move** (15m resolution). Max MAE-before-peak by symbol: BTC 0.35 ATR (10 winners, 8 at zero), ETH 1.21 ATR (11 winners, 6 at zero, p80≈0.7), SOL 0.82 ATR (7 winners, 5 at zero), HYPE 1.79 ATR (5 winners, 4 at zero), XRP 1.13 ATR (3 winners).
Mirror image: **losers rarely go favorable first** — of 120 losers, the majority show MFE = 0.0 ATR; symbol medians of losers' best excursion are 0.0–0.15 ATR.
**Implication:** wide stops do NOT protect winners (winners never test the stop); they only deepen the cost of losers. The "let it breathe" hypothesis is **killed** for this trade set.

### 2. Time-to-peak is short. Median hours from entry to max-favorable (winners only): SOL ~0.25h (5/7 peak within 1.75h), ETH ~2.75h, HYPE ~2.75h, BTC ~3.4h, XRP ~5.5h. Nothing needs >18h. Long holds are pure loser-marination: hold-cap grids improve every symbol at 2–8h caps (see cards).

### 3. Exit-type P&L is brutally lopsided (n=156, fee-inclusive $):
| Exit type | n | Net $ |
|---|---|---|
| TRAILING_STOP | 16 | **+$1,268** |
| TP2 | 3 | +$771 |
| TIME_STOP | 7 | +$132 |
| SL | 45 | −$590 |
| **LLM_EXIT_AGENT** | **85** | **−$1,535** |

The entire profit engine is trail-and-runner (19 trades, +$2,039). The LLM exit agent closed 85/156 trades for −$1,535 (−$18/trade avg). This is the single largest exit-side leak. (Caveat: LLM exits include salvage-closes of trades that were already dead — not all −$1,535 is exit-attributable. But SL+LLM together closing 130/156 trades at −$2,125 vs 26 mechanical-favorable exits at +$2,171 is the shape of the book.)

### 4. Per-trade expectancy is negative for EVERY symbol, fee-adjusted.
Avg return/trade: BTC −0.14%, ETH −0.29%, SOL −0.55%, HYPE −0.66%, XRP −0.51%. The +$959 total net $ P&L is **size skew, not per-trade edge**: era1's 6.8x-larger positions happened to contain the big trailing winners (ETH trailing: +$1,076 on 5 trades). Do not credit exit skill for the $ line.

### 5. Vol-by-hour is universal, not per-symbol: **hour 13 UTC is the #1 vol hour for all 5 symbols** (US morning). Top-4 hours everywhere ⊂ {13,14,15,17,21,3,4}; dead zone = 6–11 UTC (and 22–23). HYPE hour-13 mean |1h return| = 1.52% vs 0.65% at 09:00 — same trade, 2.3x the noise depending on clock. Median 1h ATR%: HYPE 1.94%, SOL 1.34%, ETH 0.99%, XRP 0.83%, BTC 0.77%.

### 6. HYPE vs BTC contrast — HYPE is not "choppier," it's just 2.5x bigger.
1h candle direction-reversal rates: BTC 0.538, HYPE 0.528, ETH 0.517, XRP 0.516, SOL 0.508 — statistically indistinguishable coin-flips. **Killed hypothesis:** "HYPE both-sides chop is a special microstructure." HYPE's damage comes from (a) 1.94% ATR amplifying the same directional noise 2.5x vs BTC, and (b) thesis quality: HYPE LONG is **1/13 winners (7.7% WR), −$916** — essentially all of HYPE's −$914 total. HYPE SHORT is 16 trades, 25% WR, +$2 (flat). n=13 on HYPE-long meets the data-learned veto threshold (n≥13).

### 7. Long/short asymmetry (tape-conditional, NOT a personality claim):
LONG: n=45, ~11% WR, −$1,089. SHORT: n=111, ~27% WR, +$1,135. June was a down/chop tape; this is regime, not symbol character. Flag for the regime engine — do NOT hardcode a directional block.

---

## Stop-width & hold-cap grids (15m candle replay, fee-adj 0.082% RT, sum of per-trade returns in pct-points; "None" = actual behavior)

Stop = k×ATR14(1h) from entry, conservative fill at stop level; hold-cap = force market exit at cap.

| Symbol | actual | k=0.5 | k=0.75 | k=1.0 | k=1.5 | k=2.5 | best hold-cap | best combo (k,H) |
|---|---|---|---|---|---|---|---|---|
| BTC | −9.5 | **−1.3** | −6.7 | −11.1 | −5.0 | −6.5 | 8h: −5.3 | 2.5/8h: −2.5 |
| ETH | −15.9 | **−5.8** | −10.0 | −12.7 | −14.7 | −22.6 | 2h: −8.0 | 0.75/4h: −2.9 |
| SOL | −19.6 | **+0.7** | −5.4 | −4.7 | −9.5 | −13.0 | 48h: −11.1 | 0.75/4h: −0.5 |
| HYPE | −21.6 | −17.5 | −24.7 | −30.2 | −30.4 | −23.1 | **2h: −11.1** | 0.75/4h: −16.2 |
| XRP | −5.9 | −5.2 | −6.5 | −7.7 | −9.2 | −7.3 | 4h: −2.1 | 1.25/4h: −1.9 |

**Reading:** tight stops (0.5–0.75 ATR) + short hold caps (4–8h) roughly halve-to-eliminate the bleed everywhere except HYPE, where NOTHING tested goes positive. The only positive cell in the entire grid is SOL k=0.5 (+0.7pp).

**Fragility check (mandatory):** remove each symbol's single best trade and the best-combo value collapses: BTC −2.5→−6.7, ETH −2.9→−7.4, SOL −0.5→−4.6, HYPE −16.2→−22.1, XRP −1.9→−3.3. **No configuration graduates.** Exit-geometry tuning is loss-reduction, not alpha. The gap is entry quality.

**Replay caveats (adversarial self-check):** (1) stop fills assumed at stop level on 15m bars — live wicks/slippage make tight stops worse than modeled; (2) replay doesn't model re-entry churn a tight stop would cause live (more trades → more fees); (3) k=0.5 on BTC = 0.39% price distance ≈ 4.7x the round-trip fee — thin but viable; on HYPE 0.5 ATR = 0.97%. Treat k=0.5 results as optimistic upper bounds; recommend 0.75 as the deployable floor.

---

## Per-symbol parameter cards

**BTC** — ATR 0.77% | vol peak 13–15 UTC
Stop: **0.75× ATR(1h)** (all 10 winners had MAE≤0.35 ATR; 0.5 is grid-best but fee-thin at 0.39% distance). Min hold: none needed; **hold cap 8h** (winners peak ≤5.25h, one outlier 16h). Trim: don't target-trim; trail (TP2+trailing +$483 vs LLM exits −$156/23). **Warning: era2 BTC is broken — 2/26 wins (7.7% WR), −$114; era1 was 47% WR.** Whatever changed Jun 16+ (sizing regime, entry mix), BTC entries stopped working; investigate before trusting any BTC card.

**ETH** — ATR 0.99% | best trail symbol
Stop: **0.75× ATR** (keeps 9/11 winners; the 1.21-ATR winner is one trade — fragility rule says don't widen for it). Hold cap **4–8h** (winners peak median 2.75h). Trim: **trail aggressively — ETH trailing stops made +$1,076 on 5 trades, the single biggest profit line in the book.** ETH is the "runner" symbol: rare wins, but they extend.

**SOL** — ATR 1.34% | instant-verdict symbol
Stop: **0.5–0.75× ATR**, tightest in book (5/7 winners peaked within 1.75h, 5/7 had zero MAE). Hold cap **4h** — if SOL hasn't paid in 4h it won't (hold-cap grid worst at 8–12h). Trim: take TP1-style partials early; one TP2 = +$377 shows follow-through exists but is rare. Only symbol with a positive grid cell.

**HYPE** — ATR 1.94% | **DOES NOT PAY (as currently traded)**
29 trades, 17% WR, −$914, negative in BOTH eras (era1 −$618, era2 −$296), negative in EVERY stop/hold configuration tested (best: 2h hard cap, still −11.1pp). HYPE-LONG: 1/13, −$916 → qualifies for a data-learned veto at n=13. HYPE-SHORT: flat (+$2, 25% WR, n=16) — not edge, just not bleeding. If HYPE stays tradable: stop 0.75× ATR, **hard 2h hold cap**, half-size (2.5x BTC vol on $497 equity), and require the thesis engine to clear a higher bar (HYPE theses 18% right per prior audit). The problem is entries, not exits — no card fixes it.

**XRP** — ATR 0.83% | **n=10: NO VERDICT (under n=15 floor)**
−$15 net, 30% WR. Grid suggests 1.25 ATR / 4h cap (−1.9pp vs −5.9 actual) but n forbids graduation. Keep collecting; re-run card at n≥15.

---

## Killed hypotheses (wins)
1. **"Wider stops let winners breathe"** — killed. 26/36 winners had zero adverse excursion before peak; widening stops only raises loser cost (ETH: k=2.5 is −22.6 vs −5.8 at k=0.5).
2. **"HYPE chop is unique microstructure"** — killed. Reversal rate 52.8%, mid-pack. HYPE = ordinary chop × 2.5 ATR × bad long theses.
3. **"Exit tuning can make current entries profitable"** — killed (with one fragile exception). Best fee-adjusted combo is negative for 4/5 symbols; SOL's +0.7pp dies under single-trade removal.

## Week-1 artifact test
Deployable within a day as config deltas: per-symbol stop mults (0.75 ATR), hold caps (SOL/HYPE 2–4h, BTC/ETH 8h), HYPE-long data-learned veto (n=13, 7.7% WR), prefer-trail-over-LLM-exit for in-profit positions. Honest expected value: **cuts modeled bleed by ~7–19pp cumulative per symbol; creates zero alpha.** The entry side (BTC era2 collapse, HYPE thesis quality, LLM exit agent −$1,535/85) is where the money is.

## Denominators
156 trades / 36 winners / 120 losers; 745 1h + 2,982 15m candles per symbol; fee basis n=155; era1 n=63, era2 n=92 (XRP era2-only). All grids = full trade set per symbol, no cherry-picks; fragility values reported inline.
