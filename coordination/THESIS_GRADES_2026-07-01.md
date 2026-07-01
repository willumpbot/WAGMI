# Retroactive Thesis Grading — 2026-07-01

**Source:** `bot/data/llm/thesis_history.jsonl` snapshot taken 2026-07-01 ~21:50 UTC (**237 records** — file is live-appending; the brief said 209, it grew during the session).
**Price source:** Hyperliquid public API 1h candles, 2026-05-30 → 2026-07-01 21:00 UTC (free, full coverage). `funding_oi_history.jsonl` alone was unusable — it has a **536-hour gap (Jun 7 08:52 → Jun 29 17:10)**; the HL API fill made ALL periods gradeable, including pre-Jun-6.

## Known bugs handled (all confirmed)
1. `side` is always "BUY" (223→237/237). TRUE direction derived from thesis text (explicit SHORT/LONG token > parsed target-vs-entry > bearish/bullish verbs).
2. `outcome` always "pending" — nothing was ever graded. This report is the first grading pass.
3. **NEW BUG FOUND: `symbol` field is often wrong** — ~40 records say `symbol: BTC` while the thesis text is about ETH/SOL/HYPE (entry_price is then the wrong asset's price too). Graded against the TEXT symbol, with entry re-derived from candles when entry_price mismatched by >3%.
4. **NEW: duplicate spam** — one stub, "SOL breaking below key support with volume confirmation", appears **63×** (mostly Jun 25 and tonight Jul 1); "trend aligns" 5×. Deduped stats reported alongside raw.

## Honest denominator
| bucket | n |
|---|---|
| snapshot total | 237 |
| graded (direction + price data) | 230 (deduped: 172 unique) |
| ungradeable — no derivable direction ("trend aligns" stubs) | 7 |
| graded but too recent for any horizon (logged 21:xx tonight) | 26 |
| pre-Jun-6 ungradeable | **0** (HL API fill covers May 30 onward) |

Grading rule: signed move ≥0.3% in thesis direction at horizon = right; ≤−0.3% against = wrong; else flat. Win% shown as right/all and right/(right+wrong) ex-flat.

## Accuracy by horizon
| set | n | +6h | +12h | +24h | avg signed 24h ret |
|---|---|---|---|---|---|
| raw (all graded) | 230 | 31% (ex-flat 38%) | 46% (ex-flat 59%) | 58% (ex-flat 62%) | +0.30% |
| **deduped** | 172 | 37% (48%) | 54% (62%) | 54% (58%) | +0.57% |

Read: theses are **bad at +6h** (more wrong than right), roughly coin-flip-plus at +12/24h. The raw +24h number is inflated by the 63-copy SOL stub; use deduped.

## By symbol (deduped, +12h / +24h, avg 24h ret)
| sym | n | +12h | +24h | avg ret |
|---|---|---|---|---|
| BTC | 55 | 60% | 64% | +1.61% |
| ETH | 51 | 57% | 65% | +2.02% |
| SOL | 44 | 58% | 49% | −0.25% |
| **HYPE** | 22 | **27%** | **18%** | **−3.77%** |

**HYPE theses are anti-signal** — 18% right at 24h, −3.8% avg. 6 of the worst-10 theses are HYPE.

## By direction (deduped)
| dir | n | +6h | +12h | +24h | avg ret |
|---|---|---|---|---|---|
| SHORT | 145 | 39% | 56% | 56% | +0.93% |
| LONG | 27 | 30% | 44% | 48% | −1.33% |

Short-thesis > long-thesis at every horizon, consistent with the closed-trade short edge. But note: 84% of all theses were shorts in a falling market — some of this is beta, not skill.

## By confidence band (deduped, +24h)
| band | n | +24h | avg ret |
|---|---|---|---|
| <30 | 29 | 48% | +0.13% |
| 30–44 | 52 | **67%** | +1.44% |
| 45–59 | 52 | 49% | −0.12% |
| 60–74 | 35 | **43%** | +0.47% |
| 75+ | 4 | 100% | +2.29% (n too small) |

**Confidence is uncalibrated / mildly inverted:** the 30–44 band beats the 60–74 band by 24 points at +24h. Stated confidence carries no usable information right now.

## By thesis type (deduped, +24h)
| type | n | +24h | avg ret |
|---|---|---|---|
| squeeze (BB/compression) | 27 | 63% | +0.11% |
| trend/continuation | 115 | 54% | +0.88% |
| mean-revert/fade | 19 | 58% | −0.04% |
| EV-citing (quotes WR/n=/EV) | 46 | 48% | +0.41% |
| non-EV-citing | 126 | 57% | +0.63% |

**Theses that cite Quant-Brain-style stats (WR, n=, EV) do WORSE than those that don't** (48% vs 57% at 24h) — supports the "Quant Brain stats injected into prompts are wrong/stale" hypothesis. Worst-10 includes two "validated edge" citations: "85-88% WR n=395" (−10.5%, −8.7%) and "PF 12.21, n=4" (−9.1%).

## Target grading (did price hit stated target before an equal opposite excursion?)
157 deduped theses had parseable targets: **87 target_hit (55%) / 57 stopped (36%) / 11 neither / 2 ambiguous**.
- SHORT targets: 80/132 hit (61%)
- LONG targets: 7/25 hit (**28%** — longs got stopped 72% of the time)

## By week (deduped, +24h right%, avg ret)
| week | n | +24h | avg ret |
|---|---|---|---|
| May31–Jun06 | 112 | 58% | **+1.25%** |
| Jun07–13 | 21 | 43% | −0.19% |
| Jun14–20 | 16 | 62% | −0.70% |
| Jun21–27 | 20 | 40% | −1.41% |
| Jun28–Jul01 | 3 | (n too small) | — |

All of the positive expectancy comes from the first week (the early-June melt-down, when 90%+ of theses were shorts). Post-Jun-7 theses are net-negative.

## 10 best (by signed 24h move; all target_hit)
1. +7.84% ETH SHORT 06-03 11:47 c40 — "ETH declines 2-3% toward $1,825 … BTC ADX=66 STRONG_TREND bearish structure pulls ETH down; graduated rule BOOST active"
2. +7.84% ETH SHORT 06-03 11:54 c58 — "ETH SHORT to ~$1,820: trending_bear 82% conf, BTC ADX=66 STRONG confirms downtrend, ETH −4.9% 24h weakest performer"
3. +7.47% ETH SHORT 06-04 07:15 c70 — "ETH SHORT to ~$1740: trending_bear ADX=64 regime, HYPE lead-lag −2.7% (ETH expected follow ~10.9min lag), 6h EMA bearish"
4. +7.28% BTC SHORT 06-03 11:27 c40 — "BTC SHORT to ~66,500 within 4h: ADX=66 strong bear stack (EMA9<20<50, VWAP below); HYPE→BTC lead-lag (n=327)"
5. +7.21% BTC SHORT 06-01 23:52 c20 — "BTC continues lower to $69,400 … ADX=61 trending_bear with full EMA alignment despite short-term oversold"
6. +6.84% ETH LONG 06-07 01:53 c70 — "ETH LONG to $1641 TP1: trending_bull regime, OI expanding +3.9% with bullish divergence" (the one great long)
7. +6.78% ETH SHORT 06-04 07:23 c43 — "ETH SHORT to 1638 — trending_bear 1h regime + cross-asset bearish alignment"
8. +6.76% BTC SHORT 06-03 12:35 c45 — "BTC SHORT to ~66,400 within 4h as consolidation transitions to trend — regime_trend + MTQ 2-agree, ADX=59"
9. +6.75% ETH SHORT 06-03 12:02 c47 — "ETH SHORT to ~$1840: trending_bear confirmed (ADX=66, EMA20<50, 24h=−5%), below VWAP, BTC leading bear"
10. +6.70% BTC SHORT 06-03 12:14 c52 — "BTC SHORT to ~$66,500 within 1-2h: trending_bear ADX=64, HYPE led +1.52% with 40.5min avg lag"

Pattern: **high-ADX (59–66) trend-continuation shorts on ETH/BTC with cross-asset confirmation, at LOW stated confidence (20–58)**.

## 10 worst (by signed 24h move)
1. −13.76% HYPE LONG 06-04 00:38 c52 stopped — "HYPE BUY to ~80.45: BB squeeze breakout in trending_bull while ETH/SOL both losing ~1% — relative strength"
2. −10.53% HYPE LONG 06-17 18:25 c48 stopped — "UTC hour 18 is the peak of the validated A+ US session edge (85-88% WR n=395)"
3. −9.10% SOL SHORT 06-25 18:33 c45 stopped — "validated SOL_SHORT_consolidation edge (50% WR, PF 12.21, n=4)"
4. −8.71% HYPE LONG 06-17 16:01 c51 stopped — "US-session validated edge (85-88% WR n=395) + ensemble HOT (100% WR)"
5. −8.59% HYPE SHORT 06-25 14:14 c42 stopped — "7.2% crash on 4x-volume confirms sellers in control; dead-cat bounce"
6. −8.12% SOL SHORT 06-25 18:00 c72 — "SOL breaking below key support with volume confirmation" (the 63× spam stub, at conf 72)
7. −7.69% HYPE LONG 06-01 23:35 c45 stopped — "HYPE targeting ~$76-77 as high_volatility transitions to trend"
8. −7.13% HYPE SHORT 06-24 18:25 c25 — "HYPE SHORT resumes downtrend after relief bounce"
9. −7.07% SOL SHORT 06-25 14:47 c32 stopped — "continues lower after massive breakdown candle; dead-cat bounce to 66 as short entry"
10. −6.71% HYPE LONG 06-03 10:09 c38 — "HYPE holds 71.70 support after pullback"

Pattern: **HYPE longs on "relative strength / session edge" claims, and chasing SOL/HYPE breakdowns AFTER a crash bar** (fading exhaustion, entered late). The "validated edge" citations (n=4! PF 12.21!) are the loudest failures.

## Bottom line
- True thesis accuracy (deduped): **~54% at 12–24h, 37% at 6h** — the bot's theses need 12h+ to be right, and time horizons stated in theses ("within 4-8h") are systematically too short.
- Edge is concentrated: **BTC/ETH shorts in strong trends = good (60-65%); HYPE anything = bad (18%); confidence numbers = noise; Quant-Brain stat citations = mild anti-signal.**
- Fix the pipeline bugs: side always BUY, symbol field wrong ~17% of the time, outcome never graded, duplicate thesis spam (63×). Grading infrastructure (this pass) should run automatically post-hoc.
