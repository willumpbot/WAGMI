# Decision -> Outcome Join Gap: findings + minimal fix spec

Date: 2026-09-27. Read-only investigation (streamed/sampled; no live state touched).
Test case: NEAR SHORT, opened 2026-09-27 18:24:39Z, closed 18:51:33Z, net -8.70,
ledger trade_id f50c94986b5e, position_id 74d680a2e9574747ba9b7e257c718a46.

## 0. Headline (what the memory got wrong, and what is actually broken)

1. The NEAR short's decision EXISTS. It is in `data/llm/agent_performance.jsonl`, not
   `data/llm/decisions.jsonl`: pipeline_id `915b5357-057`, 18:24:18Z, symbol NEAR,
   regime=consolidation / quant=ev=neutral / trade=go / risk=size=0.3,override=reduce /
   critic=approve. TRADE_OPENED followed 21 s later. An exit pipeline `exit_184324dd`
   (NEAR SHORT full_close) is logged at 18:29:02Z.
2. `decisions.jsonl` is fed ONLY by the trigger-system path
   (`llm/decision_engine.py:105 _log_audit`, called at :439/:550/:592/:617/:636/:811,
   reached via `core/llm_integration.py:123,869`). Trigger reasons in the last 2000
   records: lead-lag 723, cross-market divergence 247, position closed 11,
   memory-worthy 3. It has NO `symbol`, `side`, `pipeline_id` or `trace_id` field
   (0/7659 lines contain `"symbol"` or `"pipeline_id"`). It had zero writes between
   12:00:01Z and 18:46:28Z on Sep 27 while the NEAR short opened at 18:24Z. Searching
   it for entry decisions is a category error, not a timing miss.
3. The LLM-first entry path (`multi_strategy_main.py:8584 coordinator.get_entry_decision`)
   internally calls `coordinator.get_trading_decision` (`llm/agents/coordinator.py:1924`),
   which mints `_pipeline_id = str(uuid4())[:12]` at `coordinator.py:1676`, writes the
   per-agent records via `record_pipeline_run` (:1677 -> agent_performance.jsonl), and
   then DROPS the id: it is a local variable, not stored on `self`, not on the returned
   `LLMDecision`, not on `EntryDecision` (`llm/decision_types.py:203-235` has no id field),
   not in `entry_reasons` (`multi_strategy_main.py:9113-9135`), not on `Position`, not in
   the ledger. `performance_tracker.score_trade(pipeline_id, outcome)` (:268) is never
   called from live code (only its own docstring at :153). This is the gap.
4. `position_id` is populated in `trade_ledger.csv` (30/30 recent rows) but appears in
   0/152,849 `trade_events.jsonl` lines: `position_manager.py:976` (TRADE_OPENED) and
   :2306 (SL_HIT/TP_HIT/TRADE_CLOSED) do not pass it to `tel.log`.
5. Fuzzy join against the RIGHT file works today: 30/30 of the last 30 ledger closes
   match exactly one trade-agent `go` record of the same symbol 24-36 s before entry
   (section 3). Stopgap is viable; permanent fix is a 6-line stamp (section 2).

## 1. Exact fields available on each side

### 1a. `data/llm/decisions.jsonl` (7,659 lines, 42.7 MB) - trigger path only
Two record shapes alternate (each trigger run writes a pair), plus errors:
- Full: `ts` (float epoch), `action` (`flat`|`proceed`; values seen since line 6000:
  flat 620, proceed 195), `original_action`, `confidence`, `regime`, `size_multiplier`,
  `entry_adjustment` (str), `allowed`, `gate_reason`, `is_veto`, `mode`, `mode_overrides`,
  `notes` (free text; symbol only inferable from "THESIS: NEAR ..." prose), `memory_update`,
  `strategy_weights`, `trigger_reason`, `trigger_context` (str), `usage`, `snapshot`
  (portfolio-wide: `m` = list of ALL symbols, `sd` = per-symbol vote dict, `g`, `t`, `tc`,
  `mem`, `rules`, ...). 45/7659 lines contain `thesis_id=` inside `notes`.
- Short: `ts`, `action:"multi_agent_decision"`, `pipeline_action`, `confidence`, `regime`,
  `agent_stats`.
- Error: `ts`, `action:"api_error"|"sanitization_failed"`, `error`.
No symbol, side, id, or trace key at any level. A decision here is not symbol-scoped.

### 1b. `data/llm/agent_performance.jsonl` (28.6 MB) - the real per-symbol decision log
Written by `llm/agents/performance_tracker.py:175 record_pipeline_run` (path :15/:36).
Every record (400/400 sampled): `type:"decision"`, `record_id` (uuid[:12]),
`pipeline_id` (uuid[:12]; prefixes `exit_`/`scout_`/`overseer_`/`learning_` for non-entry
pipelines, bare for entry), `timestamp` (float epoch), `agent_role`
(regime|quant|trade|risk|critic|scout|exit|learning), `symbol`, `side` (EMPTY on entry
pipelines - Trade Agent schema emits no side, see coordinator.py:1606 audit #49; populated
on exit pipelines), `decision` (trade: go|skip; risk: "size=0.3,override=reduce"),
`confidence`, `confidence_source`, `reasoning_summary`, `model_used`, `latency_ms`.
Note: `api_server.py:1204-1275 /v1/reasoning/feed` and `:1533-1600 /v1/trade/{id}/trail`
filter for exactly this schema but read `decisions.jsonl` - they can never match anything.

### 1c. `data/trade_ledger.csv` (289 rows) - canonical closes
Header (`feedback/trade_ledger.py:30-80 LEDGER_COLUMNS`): trade_id (uuid[:12] minted at
write, :223), timestamp (= record time at CLOSE, not entry; measured 0.1-560 s after the
close event, typically 2-9 min), symbol, side (LONG|SHORT), regime_1h, regime_4h,
agreement_level, contributing_factors, confidence_score, kelly_weight_applied,
compound_size_multiplier, leverage, hold_hours, exit_type, entry_price, snapshot_entry,
exit_price, gross_pnl, fees, funding, net_pnl, running_equity, session_dd_pct,
ab_gate_hash, predicted_ev, realized_rr, win, epoch_id, position_id (32-hex, populated),
funding_rate_entry, open_interest_entry, premium_entry.
There is NO entry-timestamp column; entry time must be derived (timestamp - hold_hours*3600,
+/- the record lag) or taken from TRADE_OPENED. No thesis_id / pipeline_id column.
Writer: `multi_strategy_main.py:4226 self.trade_ledger.record_trade({...})` - `pos` (with
`pos.entry_reasons`) is in scope there (:4217), so any key on entry_reasons can be
projected onto a new column. Header growth is handled by additive migration (:123-155).

### 1d. `data/trade_events.jsonl` (152,849 lines, 54 MB)
Emitter: `core/structured_logging.py TradeEventLogger.log` via `position_manager.py`.
- TRADE_OPENED (:976): timestamp (ISO), event, symbol, side (LONG|SHORT), strategy,
  confidence, entry, sl, tp1, tp2, leverage, position_size, atr, regime, entry_type
  (LLM_FIRST|EXPLORATION; Sep: 10 EXPLORATION, 4 LLM_FIRST).
- SL_HIT / TP_HIT / TRADE_CLOSED (:2301-2336): symbol, side, exit_price, entry_price, pnl,
  total_pnl, fee, funding, hold_time, exit_reason, leverage, strategy, outcome,
  confidence, regime.
- position_id: absent from every event type (grep count 0).

### 1e. Already-existing but unlinked ids
- `thesis_id` (e.g. `thesis_20260927_182418_2`) minted at `coordinator.py:1613 record_thesis`,
  appended to `notes` (:1629), re-extracted at `multi_strategy_main.py:9107-9112`, stored
  in `entry_reasons["thesis_id"]` (:9133) and therefore in `data/trades.csv` entry_reasons -
  but NOT in the ledger and NOT in agent_performance.jsonl. thesis_id and pipeline_id are
  minted in the same call and never associated with each other.
- `trace_id` (`multi_strategy_main.py:2196 uuid4().hex[:8]`, per scan tick) is passed into
  the LLM-first path (:8342, :9344) and printed in log lines only.
- `position_id` minted at `execution/position_manager.py:117/171` (Position field).

## 2. Recommended fix: stamp `pipeline_id` end-to-end (single chokepoint)

The chokepoint is `coordinator.get_trading_decision`, `llm/agents/coordinator.py:1676`:
the ONE place where the entry pipeline's identity is created and already written to the
decision log. Everything downstream just needs to carry it. All steps are additive,
metadata-only, fail-neutral, and do not change any trading decision.

S1. `coordinator.py:1676-1682` - move `_pipeline_id` mint ABOVE the try, then after
    `record_pipeline_run` set `self._last_pipeline_id = _pipeline_id`
    (also set it to "" at the top of the method so a failed run never reuses a stale id).
    Also pass it to `record_thesis` context if cheap; otherwise leave (thesis_id is
    already recoverable from entry_reasons).
S2. `llm/decision_types.py:203 EntryDecision` - add `pipeline_id: str = ""` and include it
    in `to_dict()`.
S3. `coordinator.py:2139` - construct with `pipeline_id=getattr(self, "_last_pipeline_id", "")`.
    Cached-skip returns (:1769) and `EntryDecision.skip(...)` (:1944/:1948) naturally carry "".
S4. `multi_strategy_main.py:9113 entry_reasons = {...}` - add
    `"pipeline_id": getattr(entry_decision, "pipeline_id", "") or ""`.
    (entry_reasons already flows into Position and into trades.csv.)
S5. `feedback/trade_ledger.py:80` - append column `"pipeline_id"` at END of LEDGER_COLUMNS
    (additive migration :123-155 pads old rows); `multi_strategy_main.py:4226` dict - add
    `"pipeline_id": _er_mf.get("pipeline_id", "") or ""` (`_er_mf` already built at :4217).
    Optional same change for `"thesis_id"` (also in `_er_mf`), which closes the
    thesis_id<->ledger gap for free.
S6. `execution/position_manager.py:976` (TRADE_OPENED) and `:2306` (close events) - add
    `position_id=pos.position_id` and `pipeline_id=(pos.entry_reasons or {}).get("pipeline_id","")`
    to the `tel.log(...)` kwargs. `tel.log` already accepts arbitrary kwargs
    (tests/test_dashboard_health.py:166).
S7. Point `api_server.py:1210,1262,1552` at `agent_performance.jsonl` (the schema it
    already expects); with S5 the trail endpoint becomes an exact `pipeline_id` lookup
    instead of nearest-timestamp.

Resulting exact join: ledger.pipeline_id == agent_performance.pipeline_id (all 5 agent
rows + the trade-agent verdict), ledger.position_id == events.position_id (open + close).
Backfill for pre-fix rows: the fuzzy rule in section 3 (30/30 on recent data) can populate
`pipeline_id` offline from a copy - not proposed for live files.

Non-goals / cautions: do not touch `decisions.jsonl` - it is the trigger-path audit and is
consumed by `llm/self_performance.py`, `llm/replay_engine.py`, `feedback/evolution_tracker.py`.
Do not restart the bot to ship this (memory: no singleton lock, ~0.4 GB free RAM); the
change is safe to stage for the next planned restart. Flag-gate if house style requires
(e.g. `LINEAGE_STAMP=true`), though all steps are pure metadata.

## 3. Fuzzy-join stopgap: measured

Method (offline, streamed): last 30 `trade_ledger.csv` rows -> exact TRADE_OPENED match on
(symbol, side, entry_price within 1e-6 rel) to get entry time (30/30 matched, 1 with two
candidate events; resolved by nearest to timestamp - hold_hours) -> nearest
`agent_performance.jsonl` record with `agent_role=="trade"` and same `symbol` in a window
before entry.

Result: 30/30 closes have exactly one trade-agent `go` record of the same symbol inside
5 minutes before entry; every one is 24-36 s before TRADE_OPENED (0.4-0.6 min). The same
30/30 holds at 15/30/60/120-min windows, and the 5-min window had no second candidate in
any of the 30 cases. Test case: f50c94986b5e -> `915b5357-057` (0.4 min).

Rule for a stopgap joiner (this is NOT what `llm/joiner.py:254` or `api_server.py:1552` do -
both read decisions.jsonl, which cannot match):
  entry_ts  = TRADE_OPENED.timestamp for (symbol, side, entry_price)   # not ledger.timestamp
  pipeline  = argmin over agent_performance rows with agent_role=="trade", symbol==sym,
              decision in ("go","proceed"), 0 <= entry_ts - timestamp <= 300 s
Reliability caveats: (a) the 24-36 s lag is an empirical property of the current pipeline
(sub-second order path); a slower LLM or a retry would widen it - keep the window at
5 min, not 60 s; (b) entry pipelines have `side==""`, so side cannot disambiguate a
long-vs-short flip on the same symbol within 5 min - unobserved in 30/30 but possible;
(c) EXPLORATION entries (10 of 14 Sep opens) are LLM `skip` verdicts overridden at
`multi_strategy_main.py:~8700-8790`: the matching trade-agent record will say `skip`, not
`go`, so the joiner must accept any trade-agent verdict for `entry_type==EXPLORATION`
(all 30 sampled matched a `go`, so the sample may not contain an override case - verify
before relying on it); (d) ledger.timestamp is close-record time lagging the close event
by 0-9 min, so never use it as the entry anchor.

## 4. What blocks a clean trace today

B1. pipeline_id dropped at `coordinator.py:1676` (local var) - root cause; fixed by S1-S5.
B2. position_id absent from all trade_events (0/152,849) - fixed by S6.
B3. Ledger has no entry timestamp; `timestamp` is close-record time - mitigated by S5
    (exact key) or TRADE_OPENED lookup (stopgap).
B4. Entry-pipeline records carry `side==""` (Trade Agent schema; coordinator.py:1606).
    Not needed once S5 exists; matters only for the fuzzy path.
B5. Two decision logs with confusable names: `decisions.jsonl` (trigger path, portfolio
    wide, no symbol) vs `agent_performance.jsonl` (per-symbol entry pipelines). Three
    consumers (`llm/joiner.py`, `api_server.py` reasoning feed/trail, and the prior
    NEAR investigation) queried the wrong one.
B6. `thesis_id` and `pipeline_id` are minted for the same run but never cross-linked;
    the thesis grader keys on thesis_id, the agent scorer on pipeline_id.
B7. `performance_tracker.score_trade` (agent outcome scoring) has no live caller, so
    agent-level accuracy is currently unfed regardless of the join - separate issue,
    unblocked by S5.

Not verified (out of scope, read-only): whether the mechanical/exploration open path at
`multi_strategy_main.py:7893` shares the same `entry_reasons` build; whether any consumer
of `EntryDecision.to_dict()` rejects unknown keys.
