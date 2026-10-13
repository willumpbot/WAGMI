# RV input export: check D3 (exp_move drift)

Snapshot taken 2026-10-13 03:3x UTC by `rv_input_export.py`, which is read-only. Full numbers are in `RV_INPUT_EXPORT.json`.
Each implementation is computed two ways: through its real function, and through a step-by-step replica with line refs. The two agree to the rounding for every coin, and A and B also match the live `state/<SYM>.json` and `scan.json`.

| impl | where | bars | stage |
|---|---|---|---|
| **A** assemble vol voice | `assemble.py:288-297` → `volforecast.forecast(closes, dis6, fday, btc_rv5)` | basemap 1d **file cache** (`basemap.py:28,31-49`, 20h TTL) + `_closed` | HAR → stage-2 (`volforecast.py:26-33,54-61`), x0.8 if ≥3.66 |
| **B** scanner exp_move | `scanner.py:88-101` (stop_shadow `:54-58` same recipe) | fresh `hl.candles` 1d, `t+1d<=now` | HAR stage-1, x0.8 if ≥3.9 (`volforecast.py:64-65`) |
| **C** risk voice | `assemble.py:312-326` → `risk_voice.risk_read` (`risk_voice.py:81-103`) | **same df as A** (`.tail(60)`) | HAR stage-1, **no haircut at all** |
| **D** Opus chief | `chief_calls.jsonl` (01:08 UTC call) | none; it is shown A's `har_move_pct` | LLM |

## Per-coin (exp_move %, rv in % simple daily returns)

| coin | rv1/rv5/rv22 A=C (basemap) | rv1/rv5/rv22 B (fresh) | z A=C | z B | A | B | C | D (har shown) | max/min gap |
|---|---|---|---|---|---|---|---|---|---|
| BTC | 2.12 / 1.57 / 1.91 | 2.29 / 1.62 / 1.92 | 0.080 | 0.093 | 1.97 | 1.91 | 1.88 | 1.8 (1.76) | 9.7% (A vs D) |
| ETH | 3.29 / 2.44 / 2.01 | 3.55 / 2.50 / 2.03 | 0.224 | 0.239 | 2.06 | 2.21 | 2.18 | 2.1 (2.02) | 7.1% |
| SOL | 4.77 / 3.25 / 2.79 | 5.05 / 3.31 / 2.81 | 0.475 | 0.487 | 2.73 | 2.83 | 2.80 | 2.8 (2.71) | 3.6% |
| HYPE | 5.17 / 3.35 / 2.98 | 6.64 / 3.79 / 3.11 | 0.521 | 0.582 | 2.89 | 3.11 | 2.93 | 2.9 (2.83) | 7.5% |
| NEAR | 13.95 / 13.76 / 7.94 | 13.72 / 13.70 / 7.92 | 1.384 | 1.381 | 5.40 | 5.54 | **6.94** | 5.5 (5.24) | **28.6% (C vs A)** |
| XRP | 4.79 / 2.60 / 3.01 | 4.87 / 2.62 / 3.02 | 0.468 | 0.472 | 2.71 | 2.79 | 2.78 | 2.8 (2.84) | 3.3% |

The laptop's figures of "NEAR ~27%, BTC ~10%" come back as the max/min spread across A, B, C and D.

## Where the disagreement localises

The betas match across implementations: all three use `y1_beta` from `volatility_forecast.json`. Returns are percent simple returns everywhere, rv uses ddof=1, and the windows are 1/5/22 everywhere. A and C read the identical DataFrame, so `zA - zC = 0` for every coin. Their rv inputs do not differ at all today.

1. **NEAR, 25.2 of the 25.2 log-point gap between C and A.** The cause is the post-smearing haircut, not an rv input. `risk_voice.py:103` returns `exp(z)*1.7389` with no top-quintile haircut. `volforecast.py:33` applies x0.8 at ≥3.66 on the stage-2 path, and `volforecast.py:64-65` applies x0.8 at ≥3.9 on the stage-1 path. The haircut alone is -22.3 log points. The rest is the stage-2 multiplier: +14.3 fixed (net of intercept -36.3, the smearing swap -2.2 and stage-2 smearing +52.8), disagree -17.1, funding +1.6, btc -1.7. The risk-voice docstring says to "shade them down ~20%" (`risk_voice.py:166`) but the code never does it.
2. **All other coins, gaps of ±5% between A and C.** The cause is entirely the stage-2 multiplier: `exp(-0.0216 + (-0.3632) + 0.5282 - 0.06397*dis6 + 0.52144*fday - 0.03793*ln(btc_rv5))`. The variable part is `dis6`, dissent on a 0-6 scale. For BTC, dis6=1.33 gives +4.8%, and dis6≈2.4-2.7 gives about -1 to -5%. Two definition drifts sit inside this multiplier:
   - **disagree.** It was trained as the number of 6 TA families (structure/stretch/rsi/boll/mom7/mom30) disagreeing with their net sign (`vol_error.py:74-83`). Live, it is voice-consensus dissent families rescaled by `/n_families*6` (`assemble.py:412`). These are different constructs on the same scale.
   - **funding.** It was trained on *yesterday's summed realised* funding in %/day (`vol_error.py:46-54`, `.shift(1)` at `:101`). Live, it is the *current hourly rate* x24x100 (`assemble.py:292`). The units match but the quantity differs. Its effect is small today (≤1.6 log points).
   - **stage-1 smearing.** Stage 2 uses `stage1_smearing=1.7017` from `vol_error.json`, which belongs to `vol_error.py`'s own refit of b1. `volforecast.py:52,57` pairs it with the `volatility_forecast.json` betas, where the smearing is 1.7389. That is a constant -2.2 log points.
3. **A or C vs B: bar source and bar-close convention. This is the rv-input effect the laptop suspected, and it is real but intermittent.** A and C read `data/hivemind/basemap/<SYM>_1d.json`, which is rebuilt at most every 20h (`basemap.py:28,33`). `_closed` (`basemap.py:45-49`) only drops the last bar if it is still forming *relative to now*. So after 00:00 UTC, a bar that was cached part-way through its day is treated as **closed**.
   - Today the cache was written at 23:05 UTC, so the "closed" Oct-12 bar is the 23h snapshot. The HYPE close used was 82.169 against a true close of 80.894, giving rv1 5.17 vs 6.64. Effect on the forecast (zB - zC): HYPE +6.1, ETH +1.5, BTC +1.3, SOL +1.1, XRP +0.4, NEAR -0.3 log points.
   - It gets worse when the rebuild lands earlier in the UTC day. The rebuild hour drifts about 4h per day, so every hour is eventually hit. The table below shows the |log error| from a partial last bar h hours into the day, over the last 20 days. It is the median / p90 across the 6 coins, from `stale_bar_sensitivity` in the JSON.

| partial bar age | h2 | h6 | h12 | h18 | h23 |
|---|---|---|---|---|---|
| median | 10-14 | 6-12 | 5-10 | 4-6 | 1-2 |
| p90 | 23-32 | 19-39 | 18-32 | 12-20 | 4-9 |

   The bug window lasts from 00:00 UTC until the next rebuild, about (h-4) hours. It affects A, C, `assemble._btc_rv5` (`assemble.py:280-285`, which feeds stage-2) and `geometry_shadow._forecast_at` (`geometry_shadow.py:110-123`).
4. **D (the chief)** reads A's `har_move_pct` (`chief.py:130`) and rounds or nudges it by +0.0 to +0.3. It has no rv of its own.

**One-line localisation.** At NEAR scale the gap is the missing 0.8 top-quintile haircut in `risk_voice.py:103`, compared with `volforecast.py:33/64-65`. Everywhere else it is the stage-2 multiplier (`volforecast.py:31`), driven by a re-defined `disagree` input (`assemble.py:412` vs `vol_error.py:83`). The rv inputs differ only through the stale basemap partial bar (`basemap.py:28` plus `:45-49`): ≤6 log points today, but a p90 of 20-39 when the cache is rebuilt early in the UTC day.

## Unfiltered candles: server-side rv/vol writers

No writer filters `n==0` bars. In the HL 1d history, `n==0` bars are pre-listing backfill: BTC has 921 bars from 2020-08-19 to 2023-02-25, all with v=0 and **not flat** (h≠l), so they are real prices with no HL volume. NEAR has 991, XRP 999, SOL 901, ETH 921 and HYPE 0. **None fall in the last 23 bars of any coin**, so none of the six current rv windows is affected. They do enter anything that uses full history, such as the basemap table and any refit on HL 1d.

Forming bar, per writer:

| writer | bars | forming bar handling | n==0 filter |
|---|---|---|---|
| `scanner.scan_coin` (`scanner.py:88-92`) | fresh HL, ttl 600 | excluded correctly (`t+1d<=now`) | no |
| `stop_shadow._exp_move` (`:54-58`) | fresh HL to entry ts | excluded correctly | no |
| `expmove_grade` | logs scanner's exp_move/rv5 | inherits B | no |
| `assemble.voice_vol` / `_btc_rv5` / `voice_risk` | basemap 20h cache | **stale partial bar is counted as closed after 00:00 UTC** | no |
| `geometry_shadow._forecast_at` (`:110-123`) | basemap cache, `t<day0` | same stale-partial issue (it also only loads once per process) | no |
| `chief` | none (reads A) | inherits A | n/a |

## Could not determine

- The exact snapshot behind the laptop's 27% and 10%. The server D3 cross-check (`tools/knowledge/check.py:260-313`) compares only state.vol, scan and chief_latest, not risk_voice. It shows no current exp_move alarm.
- Whether the laptop's own history CSVs drop `n==0` rows. `history/` is not on this machine.
- The historical exposure of the stale-bar bug: the cache rebuild times were never logged. The h-table above shows the size per occurrence, not how often it happened.
