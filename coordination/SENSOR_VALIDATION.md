# SENSOR VALIDATION — the mechanical/diagnostic layer vs years of free data

Run: 2026-07-03 00:13 UTC | runtime 0.8 min | THE_STANDARD v1.4 | ZERO LLM calls (pure computation)
Harness: `bot/tools/research/sensor_validation.py` (imports the REAL strategy code + `llm/agents/mech_regime.py`, read-only). Candle cache: `bot/tools/research/candle_cache/`.

## Data

| symbol | source | bars (1h) | span |
|---|---|---|---|
| BTC | Binance spot (data-api.binance.vision) | 2000 | 2026-04-10 → 2026-07-03 |
| funding | Hyperliquid fundingHistory (hourly) | 26983 records | 1 coins |

Total n = **2000 symbol-bars**; strategy signal events = **2554**; confluence bars = **1408**.

### Honesty ledger (degradations & method notes)
- **Binance direct + fapi are geo-blocked (HTTP 451) from this box** → spot klines via the official data-api.binance.vision mirror; **Binance funding history unavailable** → HL fundingHistory used instead (hourly, the venue the bot actually trades — arguably more relevant, but it is NOT Binance basis).
- **HYPE**: HL API retains only ~5000 1h bars → HYPE covers ~7 months, not years. All HYPE cells are short-era by construction.
- **5m unavailable historically** → `multi_tier_quality` runs 1h+6h, which is exactly its ported `get_required_timeframes()` — no degradation vs live. `regime_trend` builds its 16h HTF from 1h (same as live). `monte_carlo_zones` runs on Binance/HL UTC daily resampled from 1h; live uses CoinGecko daily — minor source drift.
- `confidence_scorer` historical-WR feedback is DISABLED (backtest_mode=True, per its own cold-start guard) and its signal-log disk writes are stubbed. Live confidence may differ by the ±10 hist-WR adjustment.
- 6h/daily frames are resampled from 1h with the final bucket PARTIAL (same information a live intra-bucket scan has). No lookahead anywhere: bar i sees only bars ≤ i; outcomes are forward returns from bar i close.
- Mech-regime vectorization validated against the REAL `compute_mech_regime` on sampled 800-bar trailing windows: label agreement BTC 100.0% (n=40). Residual disagreement = Wilder warm-up inside a finite window; treated as measurement noise.
- **No fitting anywhere** — every sensor is fixed code measured as-is (pure measurement, nothing in-sample). BUT: several thresholds inside the strategies (ADX 22, conf floors) were historically tuned on 2024-26 data, so year-splits are era-stability checks, not true out-of-sample for those constants.
- t-stats use effective n = n/horizon (overlap correction for autocorrelated forward windows); event sensors that re-fire on consecutive bars are still somewhat overstated — treat |t| near 2 as marginal.
- Hit rates are vs the SAME-bucket directional base rate (symbol × year × regime), shown alongside.
- Fees/slippage excluded deliberately: this validates INFORMATION content of sensors, not tradability.

## 1. Strategy sensors (real code, every closed 1h bar)

`hit` = P(direction correct at horizon); `base` = same-direction base rate in the same symbol/year/regime bucket; `mean_bps` = mean direction-signed fwd return; `conf_IC` = Spearman rank-IC of the strategy's OWN confidence value vs signed outcome.

### confidence_scorer — verdict: **MUTE-FROM-CONTEXT**

| sensor | horizon | slice | n | hit | base | edge | mean_bps | t | conf_IC | IC_t |
|---|---|---|---|---|---|---|---|---|---|---|
| confidence_scorer | 1h | pooled | 1518 | 0.494 | 0.504 | -1.0pp | -0.5 | -0.42 | -0.001 | -0.03 |
| confidence_scorer | 6h | pooled | 1515 | 0.510 | 0.507 | 0.3pp | 3.1 | 0.49 | 0.002 | 0.03 |
| confidence_scorer | 24h | pooled | 1497 | 0.557 | 0.508 | 4.9pp | 26.3 | 1.07 | 0.022 | 0.17 |

Era-split (24h horizon):

| sensor | horizon | slice | n | hit | base | edge | mean_bps | t | conf_IC | IC_t |
|---|---|---|---|---|---|---|---|---|---|---|
| confidence_scorer | 24h | 2026 | 1497 | 0.557 | 0.508 | 4.9pp | 26.3 | 1.07 | 0.022 | 0.17 |

Regime-split (24h horizon):

| sensor | horizon | slice | n | hit | base | edge | mean_bps | t | conf_IC | IC_t |
|---|---|---|---|---|---|---|---|---|---|---|
| confidence_scorer | 24h | high_vol | 220 | 0.636 | 0.583 | 5.3pp | 125.8 | 1.50 | 0.011 | 0.03 |
| confidence_scorer | 24h | range | 631 | 0.572 | 0.501 | 7.2pp | 28.9 | 0.85 | 0.032 | 0.16 |
| confidence_scorer | 24h | trend | 646 | 0.515 | 0.491 | 2.5pp | -10.2 | -0.30 | 0.058 | 0.29 |

### multi_tier_quality — verdict: **MUTE-FROM-CONTEXT**

| sensor | horizon | slice | n | hit | base | edge | mean_bps | t | conf_IC | IC_t |
|---|---|---|---|---|---|---|---|---|---|---|
| multi_tier_quality | 1h | pooled | 941 | 0.499 | 0.507 | -0.8pp | 0.6 | 0.36 | -0.059 | -1.83 |
| multi_tier_quality | 6h | pooled | 936 | 0.507 | 0.511 | -0.3pp | 8.7 | 1.03 | -0.095 | -1.18 |
| multi_tier_quality | 24h | pooled | 931 | 0.510 | 0.517 | -0.7pp | 19.2 | 0.58 | 0.013 | 0.08 |

Era-split (24h horizon):

| sensor | horizon | slice | n | hit | base | edge | mean_bps | t | conf_IC | IC_t |
|---|---|---|---|---|---|---|---|---|---|---|
| multi_tier_quality | 24h | 2026 | 931 | 0.510 | 0.517 | -0.7pp | 19.2 | 0.58 | 0.013 | 0.08 |

Regime-split (24h horizon):

| sensor | horizon | slice | n | hit | base | edge | mean_bps | t | conf_IC | IC_t |
|---|---|---|---|---|---|---|---|---|---|---|
| multi_tier_quality | 24h | high_vol | 193 | 0.596 | 0.592 | 0.4pp | 127.6 | 1.46 | -0.132 | -0.33 |
| multi_tier_quality | 24h | range | 332 | 0.458 | 0.516 | -5.8pp | -7.0 | -0.14 | 0.072 | 0.25 |
| multi_tier_quality | 24h | trend | 406 | 0.512 | 0.483 | 2.9pp | -11.0 | -0.26 | -0.065 | -0.25 |

### regime_trend — verdict: **MUTE-FROM-CONTEXT**

| sensor | horizon | slice | n | hit | base | edge | mean_bps | t | conf_IC | IC_t |
|---|---|---|---|---|---|---|---|---|---|---|
| regime_trend | 1h | pooled | 94 | 0.511 | 0.510 | 0.1pp | 7.6 | 1.35 | 0.150 | 1.46 |
| regime_trend | 6h | pooled | 94 | 0.447 | 0.517 | -7.0pp | -0.9 | -0.04 | -0.025 | -0.09 |
| regime_trend | 24h | pooled | 94 | 0.479 | 0.531 | -5.2pp | 36.7 | 0.38 | -0.051 | -0.07 |

Era-split (24h horizon):

| sensor | horizon | slice | n | hit | base | edge | mean_bps | t | conf_IC | IC_t |
|---|---|---|---|---|---|---|---|---|---|---|
| regime_trend | 24h | 2026 | 94 | 0.479 | 0.531 | -5.2pp | 36.7 | 0.38 | -0.051 | -0.07 |

Regime-split (24h horizon):

| sensor | horizon | slice | n | hit | base | edge | mean_bps | t | conf_IC | IC_t |
|---|---|---|---|---|---|---|---|---|---|---|
| regime_trend | 24h | high_vol | 26 | 0.615 | 0.595 | 2.0pp | 128.7 | 0.97 | — | — |
| regime_trend | 24h | range | 33 | 0.545 | 0.520 | 2.6pp | 40.7 | 0.41 | -0.342 | -0.51 |
| regime_trend | 24h | trend | 35 | 0.314 | 0.493 | -17.9pp | -35.5 | -0.41 | -0.045 | -0.06 |

## 2. Vote confluence (reconstructed ensemble agreement)

Votes at each bar = hourly strategy signals at that bar + monte_carlo's most recent daily signal (applies to the following day). Ties (1-1) skipped. Question: does num_agree rank outcomes?

### confluence_agree=1 — verdict: **MUTE-FROM-CONTEXT**

| sensor | horizon | slice | n | hit | base | edge | mean_bps | t | conf_IC | IC_t |
|---|---|---|---|---|---|---|---|---|---|---|
| confluence_agree=1 | 1h | pooled | 675 | 0.489 | 0.501 | -1.3pp | -0.0 | -0.01 | — | — |
| confluence_agree=1 | 6h | pooled | 673 | 0.525 | 0.504 | 2.0pp | 3.8 | 0.45 | — | — |
| confluence_agree=1 | 24h | pooled | 660 | 0.559 | 0.502 | 5.7pp | 22.8 | 0.67 | — | — |

Era-split (24h):

| sensor | horizon | slice | n | hit | base | edge | mean_bps | t | conf_IC | IC_t |
|---|---|---|---|---|---|---|---|---|---|---|
| confluence_agree=1 | 24h | 2026 | 660 | 0.559 | 0.502 | 5.7pp | 22.8 | 0.67 | — | — |

### confluence_agree=2 — verdict: **MUTE-FROM-CONTEXT**

| sensor | horizon | slice | n | hit | base | edge | mean_bps | t | conf_IC | IC_t |
|---|---|---|---|---|---|---|---|---|---|---|
| confluence_agree=2 | 1h | pooled | 666 | 0.491 | 0.508 | -1.7pp | -1.4 | -0.75 | — | — |
| confluence_agree=2 | 6h | pooled | 663 | 0.507 | 0.511 | -0.4pp | 7.7 | 0.79 | — | — |
| confluence_agree=2 | 24h | pooled | 658 | 0.543 | 0.516 | 2.6pp | 26.4 | 0.66 | — | — |

Era-split (24h):

| sensor | horizon | slice | n | hit | base | edge | mean_bps | t | conf_IC | IC_t |
|---|---|---|---|---|---|---|---|---|---|---|
| confluence_agree=2 | 24h | 2026 | 658 | 0.543 | 0.516 | 2.6pp | 26.4 | 0.66 | — | — |

### confluence_agree=3 — verdict: **MUTE-FROM-CONTEXT**

| sensor | horizon | slice | n | hit | base | edge | mean_bps | t | conf_IC | IC_t |
|---|---|---|---|---|---|---|---|---|---|---|
| confluence_agree=3 | 1h | pooled | 66 | 0.545 | 0.512 | 3.3pp | 11.1 | 1.76 | — | — |
| confluence_agree=3 | 6h | pooled | 66 | 0.455 | 0.523 | -6.9pp | 0.6 | 0.02 | — | — |
| confluence_agree=3 | 24h | pooled | 66 | 0.485 | 0.543 | -5.8pp | 54.2 | 0.47 | — | — |

Era-split (24h):

| sensor | horizon | slice | n | hit | base | edge | mean_bps | t | conf_IC | IC_t |
|---|---|---|---|---|---|---|---|---|---|---|
| confluence_agree=3 | 24h | 2026 | 66 | 0.485 | 0.543 | -5.8pp | 54.2 | 0.47 | — | — |

### confluence_agree>=2 — verdict: **MUTE-FROM-CONTEXT**

| sensor | horizon | slice | n | hit | base | edge | mean_bps | t | conf_IC | IC_t |
|---|---|---|---|---|---|---|---|---|---|---|
| confluence_agree>=2 | 1h | pooled | 732 | 0.496 | 0.508 | -1.3pp | -0.3 | -0.14 | 0.061 | 1.65 |
| confluence_agree>=2 | 6h | pooled | 729 | 0.502 | 0.512 | -1.0pp | 7.0 | 0.76 | -0.021 | -0.23 |
| confluence_agree>=2 | 24h | pooled | 724 | 0.537 | 0.519 | 1.8pp | 28.9 | 0.76 | 0.032 | 0.17 |

Era-split (24h):

| sensor | horizon | slice | n | hit | base | edge | mean_bps | t | conf_IC | IC_t |
|---|---|---|---|---|---|---|---|---|---|---|
| confluence_agree>=2 | 24h | 2026 | 724 | 0.537 | 0.519 | 1.8pp | 28.9 | 0.76 | 0.032 | 0.17 |

## 3. Regime nowcast (mech_regime.py — the RQ10 hybrid)

| symbol | check | n | accuracy | base | edge |
|---|---|---|---|---|---|
| BTC | trending_bull->fwd24>0 | 385 | 0.603 | 0.486 | 11.6pp |
| BTC | trending_bear->fwd24<0 | 468 | 0.434 | 0.514 | -8.0pp |
| BTC | high_vol->rv_fwd24>med | 253 | 0.711 | 0.500 | 21.1pp |
| BTC | ranging->|fwd24|<med | 843 | 0.529 | 0.500 | 2.9pp |

Transition timing (5% zigzag legs → first matching trending_bull/bear flag):

| symbol | legs | flagged | median lag (h) | p75 lag (h) |
|---|---|---|---|---|

## 4. Classic context indicators (what the prompts cite)

Directional state sensors (same table format as strategies):

### ema20_50_state — verdict: **MUTE-FROM-CONTEXT**

| sensor | horizon | slice | n | hit | base | edge | mean_bps | t | conf_IC | IC_t |
|---|---|---|---|---|---|---|---|---|---|---|
| ema20_50_state | 1h | pooled | 1972 | 0.496 | 0.503 | -0.6pp | 0.7 | 0.72 | — | — |
| ema20_50_state | 6h | pooled | 1967 | 0.496 | 0.506 | -1.0pp | 4.6 | 0.85 | — | — |
| ema20_50_state | 24h | pooled | 1949 | 0.468 | 0.504 | -3.7pp | 1.1 | 0.05 | — | — |

Era-split (24h):

| sensor | horizon | slice | n | hit | base | edge | mean_bps | t | conf_IC | IC_t |
|---|---|---|---|---|---|---|---|---|---|---|
| ema20_50_state | 24h | 2026 | 1949 | 0.468 | 0.504 | -3.7pp | 1.1 | 0.05 | — | — |

Regime-split (24h):

| sensor | horizon | slice | n | hit | base | edge | mean_bps | t | conf_IC | IC_t |
|---|---|---|---|---|---|---|---|---|---|---|
| ema20_50_state | 24h | high_vol | 253 | 0.632 | 0.578 | 5.4pp | 139.1 | 1.82 | — | — |
| ema20_50_state | 24h | range | 843 | 0.418 | 0.492 | -7.5pp | -15.9 | -0.54 | — | — |
| ema20_50_state | 24h | trend | 853 | 0.469 | 0.495 | -2.6pp | -23.0 | -0.76 | — | — |

### mech_regime_dir — verdict: **MUTE-FROM-CONTEXT**

| sensor | horizon | slice | n | hit | base | edge | mean_bps | t | conf_IC | IC_t |
|---|---|---|---|---|---|---|---|---|---|---|
| mech_regime_dir | 1h | pooled | 876 | 0.492 | 0.500 | -0.8pp | -1.4 | -1.07 | — | — |
| mech_regime_dir | 6h | pooled | 871 | 0.465 | 0.498 | -3.3pp | -8.3 | -1.17 | — | — |
| mech_regime_dir | 24h | pooled | 853 | 0.510 | 0.492 | 1.8pp | -13.5 | -0.44 | — | — |

Era-split (24h):

| sensor | horizon | slice | n | hit | base | edge | mean_bps | t | conf_IC | IC_t |
|---|---|---|---|---|---|---|---|---|---|---|
| mech_regime_dir | 24h | 2026 | 853 | 0.510 | 0.492 | 1.8pp | -13.5 | -0.44 | — | — |

Regime-split (24h):

| sensor | horizon | slice | n | hit | base | edge | mean_bps | t | conf_IC | IC_t |
|---|---|---|---|---|---|---|---|---|---|---|
| mech_regime_dir | 24h | trend | 853 | 0.510 | 0.492 | 1.8pp | -13.5 | -0.44 | — | — |

### funding_8h_contrarian — verdict: **MUTE-FROM-CONTEXT**

| sensor | horizon | slice | n | hit | base | edge | mean_bps | t | conf_IC | IC_t |
|---|---|---|---|---|---|---|---|---|---|---|
| funding_8h_contrarian | 1h | pooled | 1972 | 0.504 | 0.505 | -0.2pp | 0.4 | 0.40 | 0.038 | 1.67 |
| funding_8h_contrarian | 6h | pooled | 1967 | 0.493 | 0.501 | -0.8pp | 2.3 | 0.43 | 0.040 | 0.73 |
| funding_8h_contrarian | 24h | pooled | 1949 | 0.530 | 0.509 | 2.1pp | 18.3 | 0.85 | 0.008 | 0.07 |

Era-split (24h):

| sensor | horizon | slice | n | hit | base | edge | mean_bps | t | conf_IC | IC_t |
|---|---|---|---|---|---|---|---|---|---|---|
| funding_8h_contrarian | 24h | 2026 | 1949 | 0.530 | 0.509 | 2.1pp | 18.3 | 0.85 | 0.008 | 0.07 |

Regime-split (24h):

| sensor | horizon | slice | n | hit | base | edge | mean_bps | t | conf_IC | IC_t |
|---|---|---|---|---|---|---|---|---|---|---|
| funding_8h_contrarian | 24h | high_vol | 253 | 0.719 | 0.551 | 16.8pp | 149.4 | 2.01 | 0.130 | 0.38 |
| funding_8h_contrarian | 24h | range | 843 | 0.556 | 0.538 | 1.8pp | 29.0 | 1.00 | 0.035 | 0.20 |
| funding_8h_contrarian | 24h | trend | 853 | 0.448 | 0.469 | -2.1pp | -31.2 | -1.04 | -0.051 | -0.29 |

### Continuous ICs (honest orientation: vol sensors scored vs future VOL, and vs direction to prove they are NOT directional)

| sensor | target | n | IC | t (n_eff=n/24) | per-year ICs | verdict |
|---|---|---|---|---|---|---|
| atr_ptile | rv_fwd24 | 1862 | 0.273 | 2.5 | 2026:0.27 | WEIGHT-DOWN |
| adx | rv_fwd24 | 1949 | 0.307 | 2.9 | 2026:0.31 | WEIGHT-DOWN |
| atr_ptile_vs_dir | fwd24h | 1862 | -0.082 | -0.7 | 2026:-0.08 | MUTE-FROM-CONTEXT |
| adx_vs_dir | fwd24h | 1949 | 0.050 | 0.4 | 2026:0.05 | MUTE-FROM-CONTEXT |
| fund8h_vs_dir_raw | fwd24h | 1973 | -0.070 | -0.6 | 2026:-0.07 | MUTE-FROM-CONTEXT |

ADX band → 24h trend continuation (P(sign of next 24h == sign of past 24h)); coin-flip base 0.500:

| ADX band | n | continuation rate | t vs 0.5 |
|---|---|---|---|
| <20 | 488 | 0.533 | 0.30 |
| 20-25 | 409 | 0.584 | 0.71 |
| 25-35 | 681 | 0.507 | 0.07 |
| >35 | 371 | 0.569 | 0.54 |

## 5. Cross-sensor redundancy (Spearman, pooled bars; signal columns 0-filled off-signal)

| | ema_state | mech_dir | adx | atr_ptile | fund_8h | sig_regime_trend | sig_confidence_scorer | sig_multi_tier_quality | sig_monte_carlo_zones |
|---|---|---|---|---|---|---|---|---|---|
| ema_state | 1.00 | 0.48 | -0.15 | -0.23 | -0.08 | 0.19 | 0.38 | 0.69 | — |
| mech_dir | 0.48 | 1.00 | -0.04 | -0.06 | 0.02 | 0.08 | 0.46 | 0.40 | — |
| adx | -0.15 | -0.04 | 1.00 | 0.25 | -0.05 | -0.04 | -0.12 | -0.09 | — |
| atr_ptile | -0.23 | -0.06 | 0.25 | 1.00 | 0.00 | -0.13 | -0.25 | -0.30 | — |
| fund_8h | -0.08 | 0.02 | -0.05 | 0.00 | 1.00 | -0.06 | -0.03 | -0.08 | — |
| sig_regime_trend | 0.19 | 0.08 | -0.04 | -0.13 | -0.06 | 1.00 | 0.16 | 0.23 | — |
| sig_confidence_scorer | 0.38 | 0.46 | -0.12 | -0.25 | -0.03 | 0.16 | 1.00 | 0.45 | — |
| sig_multi_tier_quality | 0.69 | 0.40 | -0.09 | -0.30 | -0.08 | 0.23 | 0.45 | 1.00 | — |
| sig_monte_carlo_zones | — | — | — | — | — | — | — | — | — |

Note: 0-filling sparse signal columns deflates their correlations; read the sign/magnitude of the dense-column block (ema_state/mech_dir/adx/atr_ptile/fund_8h) as the redundancy map.

## GRAND VERDICT — the validated sensor panel

| rank | sensor | 24h t | n | mean_bps | verdict |
|---|---|---|---|---|---|
| 1 | confidence_scorer | 1.07 | 1497 | 26.3 | **MUTE-FROM-CONTEXT** |
| 2 | funding_8h_contrarian | 0.85 | 1949 | 18.3 | **MUTE-FROM-CONTEXT** |
| 3 | confluence_agree>=2 | 0.76 | 724 | 28.9 | **MUTE-FROM-CONTEXT** |
| 4 | confluence_agree=1 | 0.67 | 660 | 22.8 | **MUTE-FROM-CONTEXT** |
| 5 | confluence_agree=2 | 0.66 | 658 | 26.4 | **MUTE-FROM-CONTEXT** |
| 6 | multi_tier_quality | 0.58 | 931 | 19.2 | **MUTE-FROM-CONTEXT** |
| 7 | confluence_agree=3 | 0.47 | 66 | 54.2 | **MUTE-FROM-CONTEXT** |
| 8 | mech_regime_dir | -0.44 | 853 | -13.5 | **MUTE-FROM-CONTEXT** |
| 9 | regime_trend | 0.38 | 94 | 36.7 | **MUTE-FROM-CONTEXT** |
| 10 | ema20_50_state | 0.05 | 1949 | 1.1 | **MUTE-FROM-CONTEXT** |

- Vol sensor `atr_ptile` vs future realized vol: IC 0.27 (t 2.5) — WEIGHT-DOWN.
- Vol sensor `adx` vs future realized vol: IC 0.31 (t 2.9) — WEIGHT-DOWN.

Per THE_STANDARD §1, every MUTE verdict above is a WIN: a sensor with no information stops spending prompt tokens and stops steering the LLM. Log these into RESEARCH_AGENDA ANSWERED.

_Total runtime 0.8 min; 2000 bars × 4 strategies + per-bar context panel; zero LLM calls._