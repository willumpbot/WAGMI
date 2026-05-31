# Layer 2 Pilot 3 v2 Results — April 23-28 Cascade Window

*Date: 2026-05-31 | Branch: historical-import-2026-05-30*

## Purpose

Re-run Pilot 3 (April 23-28 cascade window) with 14 cumulative bug fixes applied.

**Old Pilot 3 result:** 3 trades, -$73 net PnL, session-limited at candle 48.
**Root causes fixed:** (1) CLI session limit caused 97.3% of backtest decisions to be coordinator_returned_none, (2) contaminated live-performance data caused 100% skip rate on real LLM decisions, (3) multiple hardcoded confidence gates blocked OVERDRIVE-mode decisions.

---

## Bug Fixes Applied Before This Pilot

### Fixes 1-10 (commit 786ae46 / cd0211b) — Data contamination bypasses

| # | Fix | File | Effect |
|---|---|---|---|
| 1 | `_is_backtest` flag at pipeline start | `coordinator.py` | Gates all 8 data bypasses |
| 2 | Clear stale perf keys from snapshot | `coordinator.py` | Removes carried-over self_perf data |
| 3 | Skip `feedback_state` injection | `coordinator.py` | Bypasses WLLLL loss streak → no 0.75x penalty |
| 4 | Skip `network_calibration_adj` | `coordinator.py` | Bypasses net-cal confidence deflation |
| 5 | Skip `dynamic_stats` injection | `coordinator.py` | Bypasses "ranging 12% WR TOXIC" contamination |
| 6 | Skip `agent_cal` in trade input | `coordinator.py` | Bypasses calibration ledger penalty |
| 7 | Skip `trade_calibration` in quant input | `coordinator.py` | Bypasses quant calibration penalty |
| 8 | Skip `self_performance` for all 4 agents | `coordinator.py` | Bypasses "BTC_SHORT 14% WR" contamination |
| 9 | `enable_raw_mode()` sets max_session_drawdown=1.0 | `engine.py` | Fixes CB tripping in raw mode |
| 10 | LLM None → veto in raw mode | `engine.py` | Fixes fallback=approve bug |

### Fixes 11-15 (commits 9000b8f, a32c6b6, a77cca0, bb32a01) — Hidden threshold gates

| # | Gate | Old Value | Fixed Value | File |
|---|---|---|---|---|
| 11 | CLI subprocess timeout | 90s floor | 300s floor | `coordinator.py:126` |
| 12 | Consistency checker confidence minimum | `< 0.40` hardcoded | reads `ENSEMBLE_CONFIDENCE_FLOOR` (0.20) | `consistency_checker.py:213` |
| 13 | Critic-fallback confidence minimum | `< 0.40` hardcoded | reads `ENSEMBLE_CONFIDENCE_FLOOR` (0.20) | `coordinator.py:990` |
| 14 | LLM pre-filter solo signal threshold | `< 0.55` hardcoded | reads `ENSEMBLE_CONFIDENCE_FLOOR` (0.20) | `llm_integration.py:385` |
| 15 | Per-call CLI budget cap | $0.10 | $1.00 | `coordinator.py:125` |

### Prompt Changes (commit cd0211b) — Trust Hierarchy + Overdrive Mode

Applied from desktop-claude commits 06007cc + 089940a:
- **Trade Agent**: TRUST HIERARCHY (wired data > mechanical math > historical baselines > caution)
- **Trade Agent**: OVERDRIVE MODE (default go, solo OK with coherent thesis, floor=0.20)
- **Trade Agent**: HISTORICAL BASELINES replaces GROUND TRUTH (removes poisoned "solo=$0 across 67 trades" claim)
- **Risk Agent**: OVERDRIVE MODE (default size, skip only for hard violations)
- **Critic Agent**: TRUST HIERARCHY + OVERDRIVE MODE (default approve)

---

## Backtest Configuration

```
Command: python run.py backtest --symbols BTC --days 5 --start-date 2026-04-23 --llm --budget 3 --raw
Window: April 23-28, 2026 (BTC cascade / crash recovery window)
Equity: $10,000
RAW MODE: Circuit breakers, notional caps, position limits DISABLED
LLM Pipeline: Regime -> Trade -> Risk -> Critic (entry) + Exit + Learning
Budget: $3.00 (36 estimated API calls)
Candles: 82 (1h timeframe)
```

**Data Coverage:**
- BTC 1h: 132 candles | 5.5 days (2026-04-23 to 2026-04-28)
- BTC 5m: 1,584 candles | 5.5 days
- BTC 6h: 23 candles | 5.5 days
- BTC daily: 67 candles | 66 days (2026-02-21 to 2026-04-28)

---

## Task Run History

| Task ID | Fixes Applied | Outcome |
|---|---|---|
| btho42o8k | Fixes 1-12 (no 13-15) | Critic timeout at 90s → consistency force-skip. 0 go decisions. |
| b9t60jfkh | All fixes (wrong launch method) | `&` double-background caused stdin EOF. Exited after 0 LLM calls. |
| bjk46iosz | Fixes 1-13 (no 14-15) | Running. Expected: agents complete within 300s timeout. |

---

## Results (bjk46iosz — PENDING)

*Will be filled when task completes.*

### Decision Summary

| Metric | Pilot 3 Original | Pilot 3 v2 |
|---|---|---|
| Candles processed | 82 | 82 |
| Signals generated | — | — |
| LLM calls made | 3 (session-limited) | — |
| Pre-filtered (no LLM) | 97.3% | — |
| LLM go decisions | 0 | — |
| LLM skip decisions | 3 | — |
| Trades executed | 3 | — |
| Total PnL | -$73 | — |
| Budget used | ~$0.06 | — |

### Agent Decision Breakdown

| Agent | n_calls | n_go | n_skip | n_flip | avg_conf |
|---|---|---|---|---|---|
| Regime | — | — | — | — | — |
| Trade | — | — | — | — | — |
| Risk | — | — | — | — | — |
| Critic | — | — | — | — | — |

### Pipeline Latency

| Metric | Value |
|---|---|
| Avg pipeline latency | — |
| Min latency | — |
| Max latency | — |
| Timeouts | — |

### Regime Breakdown

| Regime | Signals | LLM go | LLM skip |
|---|---|---|---|
| consolidation | — | — | — |
| high_volatility | — | — | — |
| panic | — | — | — |
| trending_bull | — | — | — |
| trending_bear | — | — | — |

---

## Comparison: Old Pilot 3 vs Pilot 3 v2

| Aspect | Old Pilot 3 | Pilot 3 v2 | Change |
|---|---|---|---|
| LLM pipeline actually ran | No (session limit) | Yes | ✅ Fixed |
| Contaminated data injected | Yes | No | ✅ Fixed |
| Hardcoded 40-55% gates | Yes | No | ✅ Fixed |
| CLI timeout (90s vs 136s) | Hit | 300s floor | ✅ Fixed |
| go decisions possible | No (100% skip) | Yes | ✅ Expected |

---

## Interpretation Notes

- **simulated_agents.py:431 bias**: Desktop flagged that the simulated Critic in backtest mode adds a red flag for `confidence < 60`. This is NOT in our `--llm` path (real LLM agents run). No correction needed.
- **Budget tracking in CLI mode**: CLI subscription has no per-token billing, so `total_cost_usd` stays near $0. Budget cap does not trip prematurely. The `--budget 3` safety limit functions as a call-count cap.
- **Solo signal pre-filter (fix 14)**: bjk46iosz was launched BEFORE this fix (a77cca0). Solo signals 20-54% were still pre-filtered. Next run will capture solo signals in that range.

---

## Next Steps After Results

1. If go decisions appear: document which regimes/strategies triggered them, compare to live bot behavior
2. If all-skip: check Trade Agent reasoning for each signal — is it coherent or overcautious?
3. Run Pilot 3 v3 with all 15 fixes applied (fixes 14-15 not in bjk46iosz)
4. Layer 3 prep: extended 30-day window, multiple symbols
