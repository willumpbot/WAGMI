# Decision-Lineage Substrate Inventory

Measured 2026-09-27 by streaming `data/llm/decisions.jsonl` (7,659 lines, 42.7 MB, 2026-05-31 22:53Z to
2026-09-27 23:56Z) line-by-line, plus one pass each over `agent_performance.jsonl`, `trade_ledger.csv`,
`trades.csv`, `thesis_history.jsonl`, `llm_memory.json`. Read-only; nothing was modified. All percentages are
exact counts over the stated denominator. Where a number is an inference rather than a count it is marked.

## 0. What a "decision record" actually is (denominators matter)

| action value | count | what it is |
|---|---|---|
| `flat` | 2,861 | full record: LLM said no trade (always `gate_reason=flat_passthrough`, `is_veto=True`) |
| `proceed` | 461 | full record: LLM proposed an entry; risk gate then allowed 64 / blocked 397 |
| `multi_agent_decision` | 3,343 | thin meta-record (ts, pipeline_action, confidence, regime, agent_stats) written by `llm/decision_engine.py:439` immediately before the paired full record. No snapshot, no trigger. |
| `api_error` | 973 | `{ts, action, error}` only. 994 records carry an `error` key. |
| `sanitization_failed` | 21 | no causal payload |

So the tracer's real substrate is **3,322 full records** (flat + proceed). Per month (all actions):
May 2 / Jun 3,054 / Jul 1,550 / Aug 145 / Sep 2,908.

There is no `buy`/`sell`/`long`/`short` action anywhere in the file. The record for an *executed* entry is a
`proceed` with `allowed=True` (64 total: Jun 24, Jul 2, Aug 0, Sep 38). The trade ledger has 288 trades
(Jun 132, Jul 142, Sep 14). **224 of 288 executed trades have no allowed-proceed record in decisions.jsonl** -
see Blind Spot 1.

## 1. Causal-field fill rates (denominator = 3,322 full records unless noted)

Top-level fields. "flat" n=2,861, "proceed" n=461.

| field | flat | proceed | notes |
|---|---|---|---|
| `trigger_reason` | 100.0% | 100.0% | the "first domino"; catalog in section 2 |
| `trigger_context` | 100.0% | 100.0% | untruncated at top level; `snapshot.tc` copy is capped at 200 chars (`snapshot_builder.py:407`) |
| `regime` | 100.0% | 100.0% | values: range 2,169 / trend 1,905 / trending_bear 858 / trending_bull 813 / consolidation 772 / high_volatility 122 / low_liquidity 16 / panic 10 (incl. thin records) |
| `confidence` | 100.0% | 100.0% | allowed entries: min 0.40, max 0.82, mean 0.55 (n=64) |
| `gate_reason` | 100.0% | 100.0% | flat: `flat_passthrough` 100%. proceed: `confidence_too_low (x < floor)` 395 (85.7%), `all_checks_passed` 64 (13.9%), `loss_streak` 2 (0.4%) |
| `is_veto` | 100.0% | 100.0% | flat: True 100%; proceed: False 100% - it is a pure function of action, carries no extra information |
| `allowed` | 100.0% | 100.0% | flat: True 100% (misleading: "allowed to do nothing"); proceed: True 64, False 397 |
| `notes` | 100.0% | 100.0% | **capped at 1,000 chars**; proceed lengths min 790 / median 1,000 / max 1,000, i.e. most hit the cap and the tail (`RISKS:`) is cut mid-word |
| `memory_update` | 99.0% | 100.0% | free-text string, not structured |
| `strategy_weights` | 100.0% | 100.0% | dict of 8 strategies |
| `size_multiplier` | 100.0% | 100.0% | flat always 0.0 |
| `entry_adjustment` | 23.0% | 100.0% | on proceed it is always the literal `"market now"` (0 information) |
| `mode_overrides` | 0.1% | 0.2% | effectively unused |
| `original_action` | 100.0% | 100.0% | always equals `action` (0 flips observed) |
| `snapshot` | 100.0% | 100.0% | the compact JSON that was sent to the LLM |

Sub-tags inside `notes` (string-contains test; the parser has to split on ` | `):

| tag | flat | proceed | caveat |
|---|---|---|---|
| `[MA] regime=..` | 100.0% | 100.0% | regime agent verdict + probability |
| `CONFLUENCE:` | 100.0% | 100.0% | `Nstrat q=.. type=.. setup=..` - the best structured confluence signal that exists |
| `THESIS:` | 99.7% | 100.0% | **truncated to 80 chars** at `coordinator.py:5245` |
| `OUTLOOK:` | 97.4% | 92.8% | truncated to 80 chars (`coordinator.py:5243`) |
| `RISKS:` | 75.7% | 61.8% | sits at the end, so it is the part lost to the 1,000-char cap |
| `VETO` | 13.9% | 11.5% | |
| `KELLY:` | 13.6% | 8.5% | sizing math only when Kelly ran |
| `QUANT_ADJ:` | 3.7% | 4.6% | |
| `BLOCKED` | 0.6% | 0.0% | entry-gate probe stamps, Sep only |

Snapshot sub-keys (what the LLM saw). flat / proceed:

| key | flat | proceed | content |
|---|---|---|---|
| `m` (markets + per-strategy signals `sg`) | 100.0% | 100.0% | each `sg` = {st, sd, c, rf, rg?, meta?}; `meta` (MTQ tier/EMA/VWAP context) present on 1,868 / 5,184 = 36.0% of strategy readings (proceed subset) |
| `g`, `rules`, `t`, `tc`, `growth`, `survival`, `knowledge`, `deep_memory` | 100.0% | 100.0% | `rules` capped 400 chars, `mem` capped 800 |
| `sd` (per-symbol vote: n, side, agree, dissent, avg_conf, pass_votes, readings[]) | 99.9% | 100.0% | **this is the only structured `num_agree`/side proxy that is actually logged** |
| `mem` | 99.7% | 100.0% | |
| `self_perf` | 99.4% | 99.8% | |
| `recent_dec` | 97.4% | 98.5% | |
| `session_perf` | 96.3% | 97.2% | |
| `cross_pat` | 75.0% | 87.9% | |
| `recent_lessons` | 76.5% | 49.7% | |
| `regime_shifts` | 66.9% | 68.5% | |
| `cross_sym` | 63.0% | 77.7% | |
| `near` / `pos` / `port_lev` | 52.7 / 50.2 / 49.2% | 18.4 / 22.1 / 20.6% | conditional on open positions |
| `filt` | 33.1% | 32.1% | |
| `autopsy` / `examples` / `corr_risk` / `patterns` | 31.1 / 29.6 / 29.4 / 20.4% | 11.3 / 18.0 / 10.8 / 7.6% | |
| `funding_cost_pct` | 1.0% | 0.4% | |
| **`signal_metadata`** | **0.0%** | **0.0%** | 0 of 3,322 records. See Blind Spot 2. |

`signal_metadata` sub-fields the task asked about (`side`, `regime_1h`, `regime_4h`, `num_agree`,
`strategies_agree`, `stop_width_pct`, `is_toxic`, `setup_verdict`, `regime_wr`): **0.0% each, on every record type.**
There is no entry-vs-skip difference because the key never reaches the file at all.

## 2. First-domino catalog: `trigger_reason` (n = 3,322 full records)

| trigger_reason | count | share | of the 64 allowed entries | months seen |
|---|---|---|---|---|
| `lead-lag signal (follower expected to move)` | 1,751 | 52.7% | 33 | Jun 536, Jul 72, Aug 54, Sep 1,089 |
| `pre-close assessment` | 841 | 25.3% | 15 | Jun 493, Jul 348, then 0 |
| `cross-market divergence` | 358 | 10.8% | 10 | Jun 8, Jul 18, Aug 2, Sep 330 |
| `memory-worthy event` | 166 | 5.0% | 1 | Jun 93, Jul 70, Sep 3 |
| `position closed` | 163 | 4.9% | 2 | Jun 67, Jul 84, Sep 12 |
| `pre_trade_veto` | 23 | 0.7% | 0 | Jun only |
| `pre-trade validation` | 20 | 0.6% | 3 | Jun only |

`trigger_context` shapes per trigger (all parseable, none structured as JSON):
lead-lag -> python-dict repr `{'leader','follower','leader_move','expected_follower_move','avg_lag_min'}`;
pre-close -> `SYM SIDE approaching TP1/TP2/SL (price=.. tp1=.. dist=..)`; position closed -> `Closed SIDE SYM via
EXIT_TYPE PnL=$..`; cross-market -> `SYM outlier +x% vs market avg y%`; memory-worthy -> `Strategy '' outperforming:
73% win rate over last 11 trades` (**strategy name is blank in every sampled instance**); pre-trade -> `Opening SHORT
BTC @ .. lev=.. conf=..`. Multiple triggers can be joined by newline in one context.

Defined in `llm/triggers.py:69` but **never fired in this file**: `regime shift`, `high-confidence signal` (appears
only as a sub-line inside another trigger's context, Jun), `strategy consensus`, `strategy disagreement`,
`periodic update`. Also never present: `llm_first_entry` (`coordinator.py:1926`) - see Blind Spot 1. Since August
the first domino is essentially binary: lead-lag or cross-market divergence (1,419 of 1,434 Sep triggers).

## 3. Blind spots that break a full trace

**1. The trades that actually executed are mostly not in decisions.jsonl.** 288 ledger trades vs 64 allowed
`proceed` records (4.5x). Entries taken via the LLM-first path (`coordinator.py:1917-1929`, trigger
`llm_first_entry`) never reach `decision_engine._log_audit`; their only trail is `data/llm/agent_performance.jsonl`
(52,705 per-agent rows; 8,481 distinct trade-agent pipelines; roles regime/trade/quant/risk/critic ~8.3-8.5k each,
exit 7,784, scout 1,320, overseer 1,058, learning 540). That file has `pipeline_id`, `agent_role`, `decision`,
`confidence`, `model_used`, `latency_ms` - but **no trigger_reason (0 rows), no snapshot, and `reasoning_summary`
is capped at 400 chars** (`performance_tracker.py:215`). Overall ratio: 8,481 pipelines vs 3,343 pipeline records
in decisions.jsonl = 2.5x under-logging on a whole-file basis (the "~6x" figure in memory was not reproduced here;
it may hold for a specific window or denominator - not verified).

**2. `signal_metadata` is built but never persisted.** `coordinator._build_entry_snapshot` (`coordinator.py:2293-2335`)
assembles side/regime_1h/regime_4h/num_agree/strategies_agree/stop_width_pct/is_toxic/setup_verdict/regime_wr, but
the audit entry stores `json.loads(snapshot_json)` from `snapshot_builder.snapshot_to_json`, which has no such key.
Result: 0 / 3,322. The trace must reconstruct agreement from `snapshot.sd` (99.9%) and the `CONFLUENCE:` note tag
instead; `stop_width_pct`, `is_toxic`, `setup_verdict`, `regime_wr`, `regime_4h` are simply not recoverable per
decision from any logged file.

**3. No join key between the three trails.** decisions.jsonl has no `pipeline_id`, no `symbol` field (symbol is only
inferable from `trigger_context` / `notes`), no `trade_id` / `position_id`. `trade_ledger.csv` has `position_id` on
15.3% of rows and `epoch_id` on 0%. `llm_memory.json` notes have `source_trade_id` blank on 100 / 100. Linking a
decision to its trade is nearest-timestamp matching (which is what `api_server.py:1537` already does) - not a lookup.
Side note: `api_server.py:1207` (`/v1/reasoning/feed`) buckets decisions.jsonl by `pipeline_id`/`type=="decision"`,
keys that exist only in agent_performance.jsonl; on this file it would return zero pipelines.

**4. The thesis text is truncated before it is logged.** `THESIS:` and `OUTLOOK:` are cut at 80 chars, `notes` at
1,000 (most proceed records hit it), `snapshot.tc` at 200, `rules` at 400, `mem` at 800. The full agent thesis
exists in `thesis_history.jsonl` (1,554 rows) but there `outcome` is `pending` on 1,484 (95.5%; correct 24 /
incorrect 46), `setup_type` is `unknown` on 100%, and there is no decision or trade id.

**5. Ledger causal columns are half-empty, worst on winners.** `trade_ledger.csv` (n=288): `regime_1h` 88.2%,
`regime_4h` 10.8%, `agreement_level` 99.7%, `contributing_factors` 38.2% (and when filled it is the literal string
`ensemble`), `confidence_score` 59.4%, `predicted_ev` 25.7%, `kelly_weight_applied` 1.4%, `funding_rate_entry` /
`open_interest_entry` 7.6%. Of 103 winners, `contributing_factors` is blank on 63 (61.2%) and `confidence_score`
on 30 (29.1%). `trades.csv` (n=230) is better on narrative (`entry_reasons` 90.0%, `primary_driver` 88.3%) but
`strategy` is filled on 1.7%.

**6. Trigger coverage has collapsed.** `pre-close assessment` (841) and `pre-trade validation`/`pre_trade_veto`
stopped after July; `regime shift`, `strategy consensus/disagreement`, `periodic` have never fired. A tracer built
today would show every Sep decision starting from a lead-lag or divergence ping and nothing else.

**7. Fields that look causal but carry no information:** `is_veto` (= action=="flat"), `allowed` on flat (always
True), `entry_adjustment` on proceed (always `"market now"`), `original_action` (always == `action`),
`mode_overrides` (0.1%), memory-worthy trigger's `Strategy ''` (blank name).

## 4. What a tracer CAN reliably show today (from decisions.jsonl alone)

For any of the 3,322 full records: the trigger and its parsed context; the regime agent's verdict; the per-symbol
strategy votes (`sd`, `m[].sg`); the confluence line (`Nstrat / setup=`); an 80-char thesis and outlook; risk flags
(when not truncated); the gate outcome and, on proceed, the numeric confidence-vs-floor comparison; the snapshot's
self-performance / lessons / rules context as the LLM saw it. For roughly 1 in 4.5 executed trades it can also show
the allowed-proceed record; for the rest the entry trail is the 400-char per-agent summaries in
agent_performance.jsonl, matched by timestamp.
