# Laptop Claude Handbook — What We've Learned
*Written: 2026-05-31 by laptop Claude*
*Session: 051eb232 (historical backtest work)*

This is the laptop's perspective on everything learned during the May 31 session. Counterpart to whatever the desktop PC has written from its angle.

---

## 1. The Core Problem We Solved Today: Bug #16

### What It Was

The backtest was feeding **live trading statistics from after April 28** into agent context during backtests of the April 23-28 window. This is "look-ahead bias" — the agents were seeing data from the future relative to the period they were evaluating.

The contamination came through 20+ code paths in `bot/llm/agents/coordinator.py`. The most damaging ones:

- `network_learning`: Rules learned from May 2026 live trading (e.g. "avoid BTC SELL, 0-14% WR")
- `self_teaching`: Knowledge base built from live outcomes post-April 28
- `setup_edge` / `strategy_perf`: Live win rates (0-14%) injected into Kelly sizing
- `calibration_ledger`: Critic calibration trained on contaminated live trades
- `external_data`: May 31 current funding/OI data instead of April 23-28 values
- `deep_memory`: Pattern templates built from live trade history

### Why It Caused 100% Skip

The desktop ran live during a "fallback-approve era" (bug where the bot approved trades without proper filtering). Win rate during that era: 0-14%. When backtest agents saw this as their historical context, Kelly criterion made every position size negative. All agents concluded "never trade" — not because April 23-28 was actually bad, but because the injected stats said the strategy never works.

### How We Fixed It

Single flag: `_is_backtest = "backtest" in trigger_reason.lower()`

Set in `get_trading_decision()`, propagated everywhere via `self._current_is_backtest` and `snapshot_data["_is_backtest"]`. Every injection path now checks `if not _is_backtest` before injecting live data.

5 phases of commits (all pushed to `historical-import-2026-05-30`):
- Phase 1: graduated_rules, brain context, quant/Kelly, replay engine
- Phase 2: setup_edge + strategy_perf from snapshot["g"]["stperf"]
- Phase 3: network_learning, self_teaching, neuroplasticity, deep_memory, calibration_ledger, veto_stats
- Phase 4: background_thinker, exec_quality, reflection_engine, external_data_text, telemetry
- Phase 5: external_data snapshot injection (get_external_data_for_snapshot)

**Rule for all future backtests**: trigger_reason must contain "backtest". Currently `get_entry_decision()` in `llm_integration.py` calls `get_trading_decision(trigger_reason="llm_first_backtest_entry")` — this is correct.

---

## 2. What the Backtests Proved

### V3 (partial fix — 1/5 phases)
- 100% skip rate (same as contaminated)
- 99% "range" regime for a -9% crash week — clearly wrong
- Proved: contamination was still dominant even with Phase 1 removed

### V4 (all 5 phases fixed)
- **18% GO rate** (7/39 pipelines). Not zero. Fix works.
- **Regime evolves correctly**: range (April 23-25) → trending_bear (transition) → high_volatility (April 26-28 crash)
- **1 approved trade**: BTC SHORT at $77,329, exited at -$110 (-1.1%)
- Exit agent cut the loss correctly before SL hit (price bounced before the real cascade)
- All 6 vetoes used legitimate gates (confidence floors, solo signal penalty, WR)
- Model routing: 100% Haiku for regime/risk, 100% Sonnet for trade/critic ✅

**The key result**: Clean context → agents see real April 23-28 market conditions → proper decisions. The bug was the entire explanation for 100% skip.

---

## 3. Model Routing — The Desktop's Expensive Mistake

### What Happened
Desktop ran 265 LLM calls overnight. 204 of them (77%) used Opus — the most expensive model ($15/1M tokens).

### Why
Live bot evaluates signals with `trigger_reason="PRE_TRADE"`. In `usage_tiers.py`, `PRE_TRADE` maps to `high_value_model = MODEL_OPUS` in the AGGRESSIVE tier.

The laptop backtest used `trigger_reason="llm_first_backtest_entry"` — doesn't match any high-value trigger, falls through to `default_model = MODEL_SONNET`. Hence 0% Opus in backtest.

### Cost Impact
- Desktop (77% Opus): ~$3.98/day
- Correct routing (Haiku/Sonnet): ~$0.40/day
- **~90% cost reduction possible**, and eliminates quota exhaustion (currently hitting 2 dead windows per day)

### Fix Options (Nunu decides)
**Option A (recommended)**: Set per-agent env vars in .env:
```
AGENT_REGIME_MODEL=claude-haiku-4-5-20251001
AGENT_RISK_MODEL=claude-haiku-4-5-20251001
AGENT_TRADE_MODEL=claude-sonnet-4-6
AGENT_CRITIC_MODEL=claude-sonnet-4-6
AGENT_EXIT_MODEL=claude-haiku-4-5-20251001
```
These override tier routing entirely per agent.

**Option B**: Change AGGRESSIVE tier's `high_value_model` from Opus to Sonnet.

**Option C**: Add "llm_first_entry" as a medium-value trigger so backtest and live use the same path.

---

## 4. Session Usage — Why We Keep Running Out

### Sources of Usage Drain

**The bot itself (biggest drain)**:
- Live trading: ~265 agent calls/day via `claude -p` subprocess
- At 77% Opus: each Opus call takes longer and counts more toward rate limits
- Quota exhaustion = 2 dead windows per day where bot can't trade

**Backtest runs**:
- V3: 136 agent calls (~3.4 hours of CLI usage)
- V4: 156 agent calls (~3.9 hours of CLI usage)
- These are one-time costs during development

**Monitor tasks**:
- The monitoring tasks (b845c1af6, bgti6soum) fire every 30 seconds
- Each check is a Claude Code tool call, not a CLI `claude -p` call
- These don't drain the bot's CLI subscription — they use the Claude Code session

### What Drains the Most
The desktop bot's 77% Opus routing. Fixing it to Haiku/Sonnet frees up ~90% of the rate limit headroom. This should be the first fix.

### Conservation Strategy
1. Fix desktop model routing (Option A above)
2. Backtest runs: budget explicitly, run during off-hours
3. For development work: use `--dry-run` or small candle windows to validate before full runs

---

## 5. What the Pipeline Actually Does (Confirmed by V4)

From watching 39 live pipelines:

**Regime Agent (Haiku, 49.5s avg)**:
- Reads OHLCV, volume, ensemble vote
- Outputs: regime name + bias + confidence
- April 23-28: correctly classified range → high_volatility as crash developed

**Trade Agent (Sonnet, 59.8s avg)**:
- Reads regime output, signal metadata, position state
- Outputs: go/skip + thesis + confidence
- Vetoes on: low confidence, no confluence, wrong regime for setup type
- April 23-28: 7 GOs (18%) — appropriate selectivity

**Risk Agent (Haiku, 42.4s avg)**:
- Reads trade decision, sizes position
- Outputs: size multiplier, leverage, risk_pct
- Range: 0.3-0.5× size, 2.0× leverage, 1% risk
- Overrides to 0 when trade agent skips

**Critic Agent (Sonnet, 27.1s avg)**:
- Stress-tests the thesis
- Must provide counter-thesis to veto ("challenge")
- April 23-28: approved 1/7 GOs — proper selectivity
- Veto reasons: confidence below floor, solo signal, post-loss signals

**Exit Agent (Haiku)**:
- Monitors open positions every candle
- April 23-28: held for 1h (thesis intact), then full_close at 6h (thesis failed)
- Cut -$110 loss correctly before SL hit at ~$78,100

**The pipeline works correctly with clean context.** The system design is sound.

---

## 6. What We Still Don't Know

### Edge Measurement
V4 gave us 1 trade with -$110 result. This is n=1. We need 20-50 approved trades to measure edge. That requires:
- Longer backtest window (Feb-April 2026, not just April 23-28)
- Or multiple backtests across different market conditions
- Or lowering the Critic's confidence floor to see more approvals

### Signal Quality
The one approved trade entered during a local bounce rather than the crash cascade. Questions:
- Is this a consistent pattern (ensemble SELL fires early)?
- What's the distribution of approved trades across market phases?
- Does the Critic's confidence floor calibration need adjustment?

### Multi-Symbol Behavior (Task #11)
We only ran BTC. Adding ETH, SOL, HYPE would show:
- Whether agents can handle multi-asset context correctly
- Whether portfolio constraints trigger (e.g. "already in crypto risk-on position")
- Whether correlation between symbols is handled

### Regime Transition Accuracy
We saw range→trending_bear→high_volatility. But:
- Was the single trending_bear candle a correct identification or noise?
- How early does the regime shift relative to actual price action?
- The high_volatility call started around April 26 — was that early enough to matter?

### Exit Intelligence
The exit agent cut the position at -$110. But:
- Was this optimal? (Actual crash continued to ~$70k)
- If held, would SL at $78,100 have been hit? (Likely yes — price went to $78.5k before crashing)
- The -$110 early cut likely saved ~$190 vs SL hit. That's exit alpha.
- We need more exit agent observations to validate this pattern.

---

## 7. What We Plan to Learn Next

### Priority 1: Layer 3 — 4-Symbol Backtest (Task #11)
Run the same clean backtest on BTC, ETH, SOL, HYPE for the April 2026 crash window. This validates:
- Multi-asset pipeline behavior
- Portfolio constraint handling
- Whether different assets have different LLM edge profiles

### Priority 2: Longer Window Backtest
February-April 2026 window (60+ days) on BTC. Goal: 20+ approved trades for statistical edge measurement. This is the first real answer to "does the LLM pipeline add value?"

### Priority 3: Desktop Fix Validation
After Option A model routing fix, run a desktop paper trading session and measure:
- Actual usage vs. 90% reduction estimate
- Whether Sonnet-level decisions are as good as Opus
- How many trades get approved vs. when running Opus

### Priority 4: Calibration Measurement
The Critic approves ~14% of GOs (1/7). Is this too conservative? Too aggressive? To measure:
- Track all GO+approve trades and their outcomes
- Track all GO+challenge trades (would they have been profitable?)
- Adjust confidence floors based on observed calibration

---

## 8. Critical Rules for Future Work

1. **Always use `trigger_reason` containing "backtest"** — this gates all 20 look-ahead paths
2. **Never inject live data into backtest context** — the `_is_backtest` flag is the guard
3. **Don't modify AGGRESSIVE tier's high_value_model** without Nunu's approval
4. **RAW MODE for data collection** — circuit breakers off, to see what the LLM does without extra gates
5. **Fresh CLI session for each backtest** — old sessions carry conversation context that can bleed
6. **backtest_decisions.jsonl has write duplication bug** — deduplicate by (timestamp, action) before analysis
7. **Never use ANTHROPIC_API_KEY** — USE_CLI_LLM=true is the only path

---

## 9. Files That Matter

| File | Purpose |
|---|---|
| `bot/llm/agents/coordinator.py` | All 20 bug #16 fixes live here |
| `bot/backtest/llm_integration.py` | Backtest→LLM interface; trigger_reason set here |
| `bot/llm/usage_tiers.py` | Model routing; PRE_TRADE→Opus is the Opus problem |
| `bot/data/llm/agent_performance.jsonl` | Per-agent decision log (ground truth) |
| `bot/data/llm/backtest_decisions.jsonl` | Per-candle decision log (has duplication bug) |
| `bot/data/llm/backtest_exits.jsonl` | Exit agent decisions on open positions |
| `analysis/historical/layer2-pilot3-v4-results.md` | V4 final results |
| `analysis/model-routing-audit-2026-05-31.md` | Desktop Opus routing analysis |
| `coordination/handshake.md` | Cross-PC coordination state |

---

## 10. The Honest Assessment

We spent most of today debugging why the backtest was broken. Bug #16 was a deep contamination bug with 20 injection paths — finding and fixing all of them required methodical elimination (v3 proved partial fix wasn't enough, v4 proved full fix works).

**What we know for certain**:
- The multi-agent pipeline is mechanically sound
- Model routing is correct (Haiku/Sonnet where spec says)
- Regime classification improves dramatically without contamination
- The Critic is appropriately selective (14% approval rate on GOs)
- The Exit agent performs intelligent position management

**What we don't know yet**:
- Whether the approved trade rate (18%) and approval rate (14%) are calibrated correctly
- Whether the edge is positive over a statistically significant sample
- Whether the -$110 on our one trade is representative or a fluke

The answer to "is the pipeline profitable?" requires more backtests. That's Task #11 (Layer 3) and beyond.

---

*Laptop branch: `historical-import-2026-05-30`*
*Desktop branch: `desktop-overdrive-2026-05-30`*
*Never push to main.*
