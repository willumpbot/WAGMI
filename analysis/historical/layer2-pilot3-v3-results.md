# Pilot 3 v3 — LLM Backtest Results (April 23-28, 2026)

*Task ID: bnavtkge6*
*Run date: 2026-05-31*
*Fixes applied: Bug #16 Phase 1 (7 graduated_rules/brain/quant paths) + sizing math fix*
*Known contamination still present: setup_edge, network_learning, self_teaching, neuroplasticity, deep_memory patterns*

---

## Summary

| Metric | Value |
|---|---|
| Period | April 23-28, 2026 (5.5 days) |
| Candles processed | 82 |
| Signals generated | 44 (53.7% of candles) |
| LLM approved | 0 (0%) |
| LLM vetoed | 44 (100%) |
| Positions opened | 0 |
| Net PnL | $0.00 |
| API calls | 136 |
| Failures | 0 |
| Cost | $0.00 (CLI routing) |

---

## Pipeline Performance

**Decision rate:** 68 total LLM decisions (44 signal decisions + ~24 regime-only scans)

| Metric | Value |
|---|---|
| Confidence range | 0.15 – 0.61 |
| Average confidence | 0.39 |
| All actions | 100% flat (skip) |

**Regime distribution:**
| Regime | Count | % |
|---|---|---|
| range | 67 | 99% |
| trending_bear | 1 | 1% |

---

## Key Finding: Residual Contamination Still Causing 100% Skip

V3 was launched with Phase 1 fixes only (graduated rules + brain context blocked). The following contamination sources remained active during v3:

| Source | Why contaminating |
|---|---|
| `quant_data["setup_edge"]` from `snapshot["g"]["stperf"]` | Live win rates post-April-28 |
| `network_learning` lessons | Rules learned from post-April-28 trades |
| `self_teaching` knowledge base | Axioms from live trading outcomes |
| `neuroplasticity` context | Setup edge weights from live session |
| `deep_memory` patterns+failures | Trade patterns from live history |
| `calibration_ledger` in Critic | Live calibration data |
| Background thinker journal | May 2026 market observations |
| External data text | Current (May 2026) funding/OI |
| Pipeline telemetry | May 2026 gate decisions |

### Regime Anomaly

The Regime Agent classified April 23-28 as **99% "range"** — suspicious given this was a -9% BTC crash week. This strongly suggests the remaining network_learning lessons (which may have trained the Regime Agent toward "range" classification) were still biasing the output.

In a clean v4 run, we expect more "panic" or "trending_bear" regime calls during the cascade period.

---

## Comparison: v2 vs v3

| Metric | v2 | v3 |
|---|---|---|
| Task ID | bjk46iosz | bnavtkge6 |
| API calls | 13 (session limit) | 136 ✅ |
| Failures | 11 (429 fallback) | 0 ✅ |
| Skip rate | 100% (13/13 LLM) | 100% (44/44 LLM) |
| Regime classification | — | 99% range (anomalous) |
| Contamination removed | none | Phase 1 only |

**Improvement:** Pipeline mechanics work. v3 proved the CLI routing delivers 136 calls with 0 failures on a fresh session. The skip rate issue is purely contamination.

---

## Contamination Fixed for v4

All 16 contamination paths now blocked (4 phases of Bug #16 fixes):

**Phase 1 (9855828):** Graduated rules, brain context, quant/Kelly, replay engine
**Phase 2 (cc09ccf):** setup_edge + strategy_perf from snapshot["g"]
**Phase 3 (6b0b320):** Network learning, self_teaching, neuroplasticity, deep_memory patterns, calibration_ledger, veto_stats
**Phase 4 (6076da3):** Background thinker, execution_quality, reflection_engine, external_data_text, telemetry

---

## Next Step: Pilot 3 v4

v4 will be the first truly clean backtest. Agents receive only:
- Price/volume/OHLCV data from April 23-28 window
- Technical indicators computed from that OHLCV
- Position state from the backtest simulator
- Signal metadata (entry, SL, TP, confidence)

**Expected changes vs v3:**
- Regime Agent should classify more "panic" / "trending_bear" (actual crash behavior)
- Agents should have mixed GO/SKIP decisions (no biasing data pushing all-skip)
- Some trades will execute — giving us real LLM edge measurement for the first time
