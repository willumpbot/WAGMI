# REPLAY_RUN_SOL_RUN1 — full-system historical replay
Generated 2026-07-28 14:23 UTC by tools/replay_harness.py (THE_STANDARD v1.3 compliant reporting)

## What this is
Historical candles replayed through the REAL pipeline: ensemble -> RiskFilterChain (6 gates) -> 9-agent LLM coordinator (CLI-routed claude -p, default agent models) -> restored profit-lock exit engine (PositionManager: TP1 partial + BE stop, progressive trailing, 5m intra-bar fills). Manufactured clean-close sample for the live ledger.

## Window & config
- Window: 2026-07-24 -> 2026-07-28 (walk); fetch depth 9d (extra = indicator warmup)
- Symbols: SOL
- Starting equity: $5000 (matches live account scale)
- Fee model: {'taker_fee_bps_per_side': 4.5, 'slippage_bps': 3, 'funding_rate_per_8h': 0.0001} (taker both sides; entry slippage rescales SL/TP proportionally; exit slippage on stop fills; conservative worst->best->close fill order inside each bar)
- LLM cap: 30 calls, sleep 20.0s/pipeline (live-bot quota protection)

## Results
- Closes generated: 0
- Win rate: 0% (0W/0L)
- Net PnL (after fees+funding): $+0.00 on $5000 equity | fees paid $0.00
- Final equity: $5000.00
- Per-side: {}
- Per-regime: {}

## LLM usage (honest accounting)
- Total LLM calls: 33 (cap 30; cap reached: True)
- Journal entries: 8 | failures: 0 | pre-filter skips: 33
- Entry-event filter: 12 qualifying events | starved by caps: 22 | cooldown-suppressed: 4 | per-symbol calls: {"SOL": 33}
- Wall time: 27 min
- SCALING MATH: ~0.0 closes per 60 LLM calls at this signal density (0 closes / 33 calls)

## Isolation proof
- Sandbox: bot/data/replay/SOL_RUN1/sandbox (code copy + empty data tree; runner refuses to start outside a marked sandbox)
- Production data diff (bot/data, bot/ml_data, bot/backtest_ml_data, bot/trades.csv; before vs after): 32 paths changed
- CHANGED PATHS (expected: live-bot churn only — the replay process has no handle to these by construction; verify none are backtest/replay artifacts):
    - data/bot_heartbeat.txt
    - data/circuit_breaker_state.json
    - data/counterfactuals/scenarios.json
    - data/feedback/backtest_state.json
    - data/feedback/tuner_state.json
    - data/funding_oi_history.jsonl
    - data/heartbeat.json
    - data/llm/agent_performance.jsonl
    - data/llm/bot_perception/percepts.jsonl
    - data/llm/counterfactual_pending.jsonl
    - data/llm/counterfactual_resolved.jsonl
    - data/llm/deep_memory/insight_journal.json
    - data/llm/growth/growth_reports.json
    - data/llm/teaching/curriculum_state.json
    - data/llm/teaching/knowledge_base.json
    - data/llm/thesis_history.jsonl
    - data/logs/signal_outcomes.jsonl
    - data/manual/sim_status.json
    - data/manual/sim_trades.jsonl
    - data/manual/sniper_rejections.jsonl
    - data/manual/sniper_signals.jsonl
    - data/manual/trade_learner_state.json
    - data/manual/trade_lessons.jsonl
    - data/manual/trade_scorecards.jsonl
    - data/market_depth_history.jsonl
    - data/missed_trades.jsonl
    - data/position_state.json
    - data/reflections/move_exhaustion.json
    - data/trade_events.jsonl
    - ml_data/confidence_signal_log.json
    - ml_data/strategy_weights.json
    - ml_data/strategy_weights_per_symbol.json

## Fidelity caveats (honest, per THE_STANDARD)
- EMPTY MEMORY: the replay brain starts with empty memory/rules/stats stores (prevents future-knowledge leaks, but the live bot carries accumulated memory the replay lacks).
- SNAPSHOT SCOPE: replay prompts contain candle-derived stats only (price changes, volume ratio, ATR); live prompts also carry funding/OI/intel feeds not reconstructed point-in-time here.
- FILL MODEL: 1h bars with 5m intra-bar sub-fills where 5m data exists; stop fills assume candle-low/high touch = fill (conservative); funding approximated at a flat rate per 8h.
- NON-DETERMINISM: LLM outputs vary run-to-run; a replay is one sample of the policy, not a deterministic backtest.
- REPLAY_MODE veto rule: entries with no LLM opinion (failure/cap/pre-filter) are skipped, not traded mechanically — the sample is 100% LLM-approved trades (live has a mechanical fallback path).

Artifacts: bot/data/replay/SOL_RUN1/replay_trades.csv, run.log, isolation_report.json, sandbox/replay_out/*