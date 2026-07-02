# GM_REJECTIONS_79K — Per-gate counterfactual EV audit of sniper_rejections.jsonl
Date: 2026-07-02 (session dated 2026-07-01 local). Standard: THE_STANDARD.md v1.3.
Scripts: `bot/tools/research/rej79k_schema.py`, `rej79k_candles.py`, `rej79k_score.py`, `rej79k_excess.py`. Results cache: `rej79k_results.json`, `rej79k_candles.json`.

## 0. Verdict up front
- **No gate is provably denying era-stable real EV.** Every large "missed EV" signal dies under the week-1-artifact test or beta adjustment.
- **Two gates provably SAVE money**: `quality_floor_proven_solo` (raw −70bps/24h, n=428; BUY −227bps) and `aggressive_standard_skip` (raw −27bps overall, LATE −179bps, n=439).
- **One relative anomaly** (`quality_floor_conf`, 100% HYPE SELL) and **one small-n watch item** (`low_rr`, n=31) — neither graduates.
- Killed hypotheses (log as wins): "dedup/cooldown/daily_limit throttles are burning EV" — dead. "low_confidence thresholds destroy alpha" — dead outside week 1.

## 1. Schema (honest, first-ever read of this file)
79,869 lines; 79,855 parse, 14 bad. Fields — exactly 8, all present on every record:
`timestamp, symbol, side, confidence, reason, num_agree, regime, chop`.
**No entry/SL/TP prices. No outcomes annotated.** So true bracket EV is unknowable from this file; we forward-scored fixed horizons instead (stated below).
- Span: 2026-05-30 17:24 → 2026-07-02 02:50 UTC. 29 active days; dark 2026-06-11..15 (bot offline) — matches known blackout.
- Symbols: HYPE 23,841 / ETH 20,419 / BTC 15,456 / SOL 11,600 / XRP 8,532 / DOGE 7 (DOGE unscored).
- Reasons: 170+ raw strings, parameterized (e.g. `low_confidence_66`, `quality_floor_proven_solo_35`, `scorecard_33_min40`, `dangerous_regime_high_volatility_conf65_agree1`). Collapsed to 20 gate families.
- Volume is loop-driven, not signal-driven: Jun 28 alone has 12,340 records; `dedup` is 41% of the file. Record-count is a fake denominator.

## 2. Method + sampling frame
- **Scoring frame: ALL 79,855 records** (no sampling needed — candle lookups are cheap), collapsed to **5,528 episodes** = unique (gate_family, symbol, side, entry-hour). Episodes are the honest denominator; records are pseudo-replicated up to 100x.
- Price truth: HL 1h candles (candleSnapshot), 2026-05-29 → 2026-07-02 03:00, 819 candles/symbol, no gaps (funding_oi hole irrelevant — not used).
- Counterfactual: entry = open of first full hourly candle AFTER rejection ts (no lookahead); exit = open k hours later, k ∈ {1,4,24}; signed by side; **gross bps** (HL taker round-trip ≈ 9bps + slippage is the hurdle). 8 episodes unscorable (past candle end).
- Eras: **W1** = May30–Jun5 (crash week), **MID** = Jun6–25, **LATE** = Jun26–Jul2.
- Beta adjustment: per-episode excess vs mean 24h return of ALL rejection episodes in the same (era, side, symbol) cell — strips market direction, which dominates this window.

## 3. The baseline that explains almost everything (24h, episodes)
| era | side | n | WR | mean |
|---|---|---|---|---|
| W1 | BUY | 241 | 42% | −161bps |
| W1 | SELL | 771 | **92%** | **+385bps** |
| MID | BUY | 851 | 33% | −183bps |
| MID | SELL | 2034 | 59% | +69bps |
| LATE | BUY | 412 | 28% | −61bps |
| LATE | SELL | 941 | 39% | −115bps |
Crash week made EVERY rejected SELL look like genius (92% WR). Any gate's "missed EV" must be judged against this, not against zero. In LATE, both sides of the whole rejection pool lose — the market punished everything at 24h.

## 4. Per-gate table (episodes, 24h raw; W1-artifact + beta test applied)
| gate | rec | epis | WR | raw mean | W1 | MID | LATE | excess vs (era,side,sym) | verdict |
|---|---|---|---|---|---|---|---|---|---|
| dedup | 32,478 | 1,321 | 54% | +16 | +235 | −28 | −110 | −11 | throughput, neutral. W1 artifact. |
| low_confidence | 19,375 | 560 | 52% | +54 | **+409** | +89 | −65 | +7 | **W1 artifact**; ex-W1 ≈ beta. Not denying EV. |
| symbol_cooldown | 7,536 | 1,243 | 53% | +15 | +242 | −30 | −105 | −11 | throughput, neutral. |
| daily_limit | 6,549 | 204 | 61% | +88 | **+285** | +5 | −2 | +5 | **W1 artifact** (crash-week SELLs hit the cap). Ex-W1 ~zero. |
| quality_floor_proven_solo | 5,481 | 454 | 41% | **−70** | — | −28 | −148 | +3 | **SAVES MONEY.** BUY side −227bps (n=167). Keep. |
| low_consensus | 2,171 | 151 | 52% | +100 | **+585 (97% WR)** | −5 | −138 | −18 | **Purest W1 artifact in the file.** Ex-W1 negative. Keep gate. |
| quality_floor_conf | 1,894 | 144 | 64% | +112 | — | +225 | −81 | **+89** | See §5. Relative anomaly, not raw EV. |
| dangerous_regime_highvol | 1,302 | 116 | 57% | −6 | −81 (excess **−283**) | +39 | −34 | +17 | **Earned its keep in W1** (blocked stuff 283bps worse than peers). Keep. |
| scorecard_min40 | 1,060 | 717 | 57% | +40 | +203 | −0 | −51 | +19 | W1 artifact; ex-W1 raw ≤ 0. SELL +137 vs BUY −151 = pure beta. |
| aggressive_standard_skip | 749 | 477 | 48% | **−27** | +264 | −31 | **−179** | −24 | **SAVES MONEY** ex-W1, esp. LATE. Keep. |
| low_win_prob | 509 | 57 | 60% | +110 | +337 | +5 | — | +17 | W1 artifact; MID ≈ zero. |
| low_rr | 416 | 31 | 68% | +116 | +188(11) | +113(9) | +47(11) | +99 | Raw-positive in all 3 eras but **every era n<15**. Watch item, no graduation. |
| rsi_overbought | 284 | 22 | 55% | −21 | +159(4) | +36(8) | −139(10) | +129 | n too small; LATE negative. No action. |
| others (zero_risk, chop, panic, dipped, oversold, weak_regime) | ≤12 each | 1–2 | — | — | — | — | — | — | unscorable n. |
Fragility: all headline means survive drop-single-best (reported in rej79k_results.json).

## 5. The two things that are NOT noise (and why neither ships)
**quality_floor_conf (all 144 episodes = HYPE SELL, conf 30–54, spread over 18 days Jun9–Jul2, max 19/day — not day-clustered):** beats the peer rejection pool in BOTH eras it exists (excess +115 MID, +45 LATE; drop-best survives: +216 MID raw). BUT raw LATE = **−81bps**: trading these in LATE loses actual dollars. The finding is *relative ranking error* — this floor rejects HYPE SELLs that are better than what other gates reject — not a raw edge. Single-symbol, single-side, and excess-vs-rejections is not excess-vs-tradeable. **Do not open the gate.** Correct use: if a quality floor is ever re-tuned, HYPE-SELL-conf-30s is the first cell to re-examine with a real bracket backtest.

**low_rr:** rejected only for R:R < 1.2, drifts positive at 24h in all three eras (+188/+113/+47) with WR 68%. n=31 total, per-era n ≤ 11 → **small-n humility, does not graduate** (standard §1: n<15). Logged as a watch item: R:R computed from SL/TP geometry may misprice 24h-drift setups. Revisit at n≥50.

**Confidence gradient (calibration check, all 5,250 24h-scored episodes):** raw return rises monotonically with rejected confidence (conf<40: −113bps → conf 80+: +51bps) — confidence IS informative raw — but **excess turns negative above conf 70** (+59 at 50–60, −26 at 70–80, −24 at 80+). High-conf rejections ride beta, they don't out-select peers. The hardcoded confidence thresholds are not demonstrably burning alpha in this dataset.

## 6. What transfers to the current pipeline, what doesn't
This file is written by `bot/manual/sniper_filter.py` — the **manual-alert sniper layer** (filters bot signals into manual scalp alerts for a $100 aggressive account), NOT the autonomous 6-gate signal_pipeline or the LLM dispatcher. Transfers: the *input signals* are the same ensemble outputs, so conclusions about signal quality vs confidence/consensus/regime transfer directionally; the W1-SELL-beta lesson transfers everywhere. Does NOT transfer: dedup/daily_limit/cooldown are sniper-alert throttles (verdict "neutral" says nothing about live-pipeline throttles); sizing/leverage context differs; the sniper's scorecard/quality-floor thresholds are its own constants, not the live gates. Also: fixed-horizon scoring ≠ the sniper's actual TP/SL brackets — a gate could still deny EV under tight-scalp geometry that 24h drift can't see (entry/SL/TP were never logged; that's the dataset's real hole — worth logging going forward).

## 7. Adversarial self-check (what would break this)
- Entry-price approximation (next 1h open) ignores intra-hour scalp dynamics — biases against fast-TP setups, both directions equally.
- Baseline is rejections-only (accepted sniper signals live in sniper_signals.jsonl, not compared here — open follow-up: rejected-vs-ACCEPTED at same horizons).
- Episode collapse keeps max-confidence dupe; keeping first/min shifts means <10bps (thresholds are the reason strings themselves, so family membership is unaffected).
- Excess baseline includes the gate's own episodes → excess estimates are conservative (shrunk toward 0), which strengthens the null verdicts and weakens §5's anomaly — fine.
- The 92%-WR W1-SELL baseline is itself the artifact detector working: any pre-Jun6 "gates blocked winners" claim in prior docs should be re-read against it.

## 8. Dataset status
Consumed (Invariant 7): first read of 79,855 records, 100% scored where price exists. Follow-ups filed above: (a) rejected-vs-accepted comparison, (b) log entry/SL/TP in rejection records, (c) low_rr watch at n≥50.
