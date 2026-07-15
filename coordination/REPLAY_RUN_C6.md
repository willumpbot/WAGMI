# REPLAY_RUN_C6 — full-system historical replay
Generated 2026-07-03 01:00 UTC by tools/replay_harness.py (THE_STANDARD v1.3 compliant reporting)

## What this is
Historical candles replayed through the REAL pipeline: ensemble -> RiskFilterChain (6 gates) -> 9-agent LLM coordinator (CLI-routed claude -p, default agent models) -> restored profit-lock exit engine (PositionManager: TP1 partial + BE stop, progressive trailing, 5m intra-bar fills). Manufactured clean-close sample for the live ledger.

## Window & config
- Window: 2026-06-20 -> 2026-06-27 (walk); fetch depth 11d (extra = indicator warmup)
- Symbols: BTC,ETH,SOL
- Starting equity: $500 (matches live account scale)
- Fee model: {'taker_fee_bps_per_side': 5, 'slippage_bps': 3, 'funding_rate_per_8h': 0.0001} (taker both sides; entry slippage rescales SL/TP proportionally; exit slippage on stop fills; conservative worst->best->close fill order inside each bar)
- LLM cap: 180 calls, sleep 15.0s/pipeline (live-bot quota protection)

## Results
- Closes generated: 0
- Win rate: 0% (0W/0L)
- Net PnL (after fees+funding): $+0.00 on $500 equity | fees paid $0.00
- Final equity: $500.00
- Per-side: {}
- Per-regime: {}

## LLM usage (honest accounting)
- Total LLM calls: 0 (cap 180; cap reached: False)
- Journal entries: 0 | failures: 0 | pre-filter skips: 0
- Entry-event filter: 0 qualifying events | starved by caps: 0 | cooldown-suppressed: 0 | per-symbol calls: {}
- Wall time: 0 min
- SCALING MATH: ~0.0 closes per 60 LLM calls at this signal density (0 closes / 0 calls)

## Isolation proof
- Sandbox: bot/data/replay/C6/sandbox (code copy + empty data tree; runner refuses to start outside a marked sandbox)
- Production data diff (bot/data, bot/ml_data, bot/backtest_ml_data, bot/trades.csv; before vs after): 3 paths changed
- CHANGED PATHS (expected: live-bot churn only — the replay process has no handle to these by construction; verify none are backtest/replay artifacts):
    - data/bot_heartbeat.txt
    - data/heartbeat.json
    - data/llm/bot_perception/percepts.jsonl

## Fidelity caveats (honest, per THE_STANDARD)
- EMPTY MEMORY: the replay brain starts with empty memory/rules/stats stores (prevents future-knowledge leaks, but the live bot carries accumulated memory the replay lacks).
- SNAPSHOT SCOPE: replay prompts contain candle-derived stats only (price changes, volume ratio, ATR); live prompts also carry funding/OI/intel feeds not reconstructed point-in-time here.
- FILL MODEL: 1h bars with 5m intra-bar sub-fills where 5m data exists; stop fills assume candle-low/high touch = fill (conservative); funding approximated at a flat rate per 8h.
- NON-DETERMINISM: LLM outputs vary run-to-run; a replay is one sample of the policy, not a deterministic backtest.
- REPLAY_MODE veto rule: entries with no LLM opinion (failure/cap/pre-filter) are skipped, not traded mechanically — the sample is 100% LLM-approved trades (live has a mechanical fallback path).

Artifacts: bot/data/replay/C6/replay_trades.csv, run.log, isolation_report.json, sandbox/replay_out/*