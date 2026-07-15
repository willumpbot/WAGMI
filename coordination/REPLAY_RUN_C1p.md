# REPLAY_RUN_C1p — full-system historical replay
Generated 2026-07-03 00:25 UTC by tools/replay_harness.py (THE_STANDARD v1.3 compliant reporting)

## What this is
Historical candles replayed through the REAL pipeline: ensemble -> RiskFilterChain (6 gates) -> 9-agent LLM coordinator (CLI-routed claude -p, default agent models) -> restored profit-lock exit engine (PositionManager: TP1 partial + BE stop, progressive trailing, 5m intra-bar fills). Manufactured clean-close sample for the live ledger.

## Window & config
- Window: 2025-07-07 -> 2025-07-14 (walk); fetch depth 11d (extra = indicator warmup)
- Symbols: BTC,ETH,SOL
- Starting equity: $500 (matches live account scale)
- Fee model: {'taker_fee_bps_per_side': 5, 'slippage_bps': 3, 'funding_rate_per_8h': 0.0001} (taker both sides; entry slippage rescales SL/TP proportionally; exit slippage on stop fills; conservative worst->best->close fill order inside each bar)
- LLM cap: 180 calls, sleep 6.0s/pipeline (live-bot quota protection)

## Results
- Closes generated: 2
- Win rate: 50.0% (1W/1L)
- Net PnL (after fees+funding): $-3.03 on $500 equity | fees paid $0.12
- Final equity: $497.01
- Per-side: {"LONG": {"n": 2, "wins": 1, "wr": 50.0, "pnl": -3.03}}
- Per-regime: {"trending_bull": {"n": 2, "wins": 1, "wr": 50.0, "pnl": -3.03}}

## LLM usage (honest accounting)
- Total LLM calls: 143 (cap 180; cap reached: False)
- Journal entries: 65 | failures: 0 | pre-filter skips: 416
- Entry-event filter: 143 qualifying events | starved by caps: 37 | cooldown-suppressed: 46 | per-symbol calls: {"BTC": 60, "ETH": 60, "SOL": 23}
- Wall time: 72 min
- SCALING MATH: ~0.8 closes per 60 LLM calls at this signal density (2 closes / 143 calls)

## Isolation proof
- Sandbox: bot/data/replay/C1p/sandbox (code copy + empty data tree; runner refuses to start outside a marked sandbox)
- Production data diff (bot/data, bot/ml_data, bot/backtest_ml_data, bot/trades.csv; before vs after): 66 paths changed
- CHANGED PATHS (expected: live-bot churn only — the replay process has no handle to these by construction; verify none are backtest/replay artifacts):
    - data/analysis/performance.json
    - data/bot_heartbeat.txt
    - data/circuit_breaker_state.json
    - data/counterfactuals/scenarios.json
    - data/execution_analytics.csv
    - data/feedback/adaptive_sizer_state.json
    - data/feedback/backtest_state.json
    - data/feedback/regime_feedback_state.json
    - data/feedback/tuner_state.json
    - data/funding_oi_history.jsonl
    - data/heartbeat.json
    - data/learning/auto_fix_state.json
    - data/llm/agent_costs.json
    - data/llm/agent_performance.jsonl
    - data/llm/bot_perception/percepts.jsonl
    - data/llm/counterfactual_pending.jsonl
    - data/llm/counterfactual_resolved.jsonl
    - data/llm/critic_shadow_state.json
    - data/llm/decisions.jsonl
    - data/llm/deep_memory/insight_journal.json
    - data/llm/graduated_rules.json
    - data/llm/growth/growth_reports.json
    - data/llm/growth/recommendations.json
    - data/llm/growth/veto_tracker.json
    - data/llm/learning_state.json
    - data/llm/llm_memory.json
    - data/llm/network_learning.json
    - data/llm/neuroplasticity_state.json
    - data/llm/operator_messages.json
    - data/llm/overseer_memo.json
    - data/llm/pattern_cache.json
    - data/llm/roadmap_state.json
    - data/llm/survival_state.json
    - data/llm/teaching/knowledge_base.json
    - data/llm/thesis_history.jsonl
    - data/logs/exit_regret_scores.jsonl
    - data/logs/safety_events.csv
    - data/logs/signal_outcomes.jsonl
    - data/logs/state_transitions.csv
    - data/manual/anticipatory_history.jsonl

## Fidelity caveats (honest, per THE_STANDARD)
- DATA SOURCE: candles pre-seeded from Coinbase SPOT (exchange perp history does not reach this era) — spot prices proxy Hyperliquid perp prices; basis/funding divergence not modeled.
- EMPTY MEMORY: the replay brain starts with empty memory/rules/stats stores (prevents future-knowledge leaks, but the live bot carries accumulated memory the replay lacks).
- SNAPSHOT SCOPE: replay prompts contain candle-derived stats only (price changes, volume ratio, ATR); live prompts also carry funding/OI/intel feeds not reconstructed point-in-time here.
- FILL MODEL: 1h bars with 5m intra-bar sub-fills where 5m data exists; stop fills assume candle-low/high touch = fill (conservative); funding approximated at a flat rate per 8h.
- NON-DETERMINISM: LLM outputs vary run-to-run; a replay is one sample of the policy, not a deterministic backtest.
- REPLAY_MODE veto rule: entries with no LLM opinion (failure/cap/pre-filter) are skipped, not traded mechanically — the sample is 100% LLM-approved trades (live has a mechanical fallback path).

Artifacts: bot/data/replay/C1p/replay_trades.csv, run.log, isolation_report.json, sandbox/replay_out/*