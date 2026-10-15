# Export integrity

_Written by `crunch/j4_integrity.py` every hour. Reports presence, growth, fill
rates and gaps. Flags regressions; does not interpret them._

_Updated 2026-10-15 18:20._

## Growth -- is each export still being written?

| export | size | class | change since last run |
|---|---|---|---|
| `LIQ_MAGNET_RECHECK.md` | 1797 bytes | reference | reference — present |
| `README_DATA_RESPONSE.md` | 2908 bytes | reference | reference — present |
| `SYNDICATE_DUDS_PREREG.md` | 4026 bytes | reference | reference — present |
| `SYNDICATE_DUDS_REPORT.md` | 3478 bytes | reference | reference — present |
| `SYNDICATE_RECALL_PREREG.md` | 3896 bytes | reference | reference — present |
| `_manifest.json` | 3648 bytes | snapshot | snapshot — ok |
| `accumulation_log.jsonl` | 509 rows | append | +1 rows |
| `agent_grades_resolved.jsonl` | 3733 rows | append | +23 rows |
| `ai_plans.json` | 34379 bytes | snapshot | snapshot — ok |
| `archive` | 281999 rows+bytes | append | unchanged |
| `board_feed.json` | 7139 bytes | snapshot | snapshot — info: retired upstream -- not refreshed, so staleness carries no information |
| `bulk` | 856704 rows+bytes | append | unchanged |
| `calibration_observations.jsonl` | 77 rows | append | unchanged |
| `call_caller_form_anon.384rows_20261012.jsonl` | 384 rows | append | unchanged |
| `call_caller_form_anon.NEW.jsonl` | 2442 rows | append | unchanged |
| `call_caller_form_anon.jsonl` | 2442 rows | append | unchanged |
| `call_snapshots.jsonl` | 72 rows | append | +3 rows |
| `candles_5m` | 40086 rows+bytes | append | +66 rows+bytes |
| `cases_index.json` | 3332 bytes | snapshot | snapshot — ok |
| `chief.py` | 12441 bytes | reference | reference — present |
| `chief_calls.jsonl` | 272 rows | append | unchanged |
| `chief_scorecard.json` | 669 bytes | snapshot | snapshot — ok |
| `conf_floor_decisions.jsonl` | 548 rows | append | unchanged |
| `conf_floor_resolutions.jsonl` | 973 rows | append | unchanged |
| `confidence_state.json` | 3204 bytes | snapshot | snapshot — stale 88.2h — EXPECTED: written on trade close and the last close was 89.0h ago. Not a fault. |
| `copilot_alerts.log` | 420970 bytes | reference | reference — present |
| `copilot_call_ledger.jsonl` | 423 rows | append | unchanged |
| `copilot_call_ledger_resolved.jsonl` | 403 rows | append | unchanged |
| `ctx_snapshots` | 91136 rows+bytes | append | +712 rows+bytes |
| `discrepancies.json` | 14926 bytes | snapshot | snapshot — ok |
| `dissent_log.jsonl` | 1649 rows | append | +44 rows |
| `dive_requests.jsonl` | 22 rows | append | unchanged |
| `entry_gate_log.jsonl.gz` | 5387 rows | append | unchanged |
| `entry_mom.jsonl` | 1636 rows | append | unchanged |
| `execution_analytics.csv` | 174 rows | append | unchanged |
| `exit_decisions.jsonl` | 1336 rows | append | unchanged |
| `expmove_log.jsonl` | 327 rows | append | unchanged |
| `floor_decisions_log.jsonl.gz` | 1369 rows | append | unchanged |
| `funding_oi_history.jsonl.gz` | 52524 rows | append | +28 rows |
| `geometry_shadow.json` | 637 bytes | snapshot | snapshot — ok |
| `geometry_shadow_results.jsonl` | 953 rows | append | +2 rows |
| `ic_dropped_resolved.jsonl` | 998 rows | append | unchanged |
| `linkage.json` | 134 bytes | snapshot | snapshot — ok |
| `live_scorecard.json` | 1342 bytes | snapshot | snapshot — ok |
| `llm_exits_resolved.jsonl` | 29 rows | append | unchanged |
| `nearmiss_reversion_log.jsonl` | 45 rows | append | unchanged |
| `owner_fills.jsonl` | 12 rows | append | unchanged |
| `owner_plan_reviews.jsonl` | 29 rows | append | unchanged |
| `owner_plan_sims.json` | 12496 bytes | snapshot | snapshot — ok |
| `owner_plan_sims_resolved.jsonl` | 11 rows | append | unchanged |
| `owner_plans.jsonl` | 34 rows | append | unchanged |
| `owner_watchlist.json` | 11 bytes | snapshot | snapshot — info: event-driven quiet — manifest shows a fresh export with src_mtime unmoved (last changed 2026-10-12); age 20.2h carries no information. |
| `plans.json` | 65234 bytes | snapshot | snapshot — ok |
| `position_journal.jsonl` | 3118 rows | append | unchanged |
| `position_manager.py` | 180025 bytes | reference | reference — present |
| `promoted_log.jsonl` | 86 rows | append | +4 rows |
| `scan_grades.json` | 37874 bytes | snapshot | snapshot — ok |
| `scan_log.jsonl` | 783 rows | append | unchanged |
| `scanner.py` | 11125 bytes | reference | reference — present |
| `signal_filtered.jsonl.gz` | 9845 rows | append | unchanged |
| `signal_value_tracker.jsonl` | 440 rows | append | unchanged |
| `state` | 531504 rows+bytes | snapshot | snapshot — ok (10 files, newest 21.2h of 26h budget) |
| `state_transitions.csv` | 19089 rows | append | unchanged |
| `stop_shadow.json` | 1881 bytes | snapshot | snapshot — info: event-driven quiet — content moves only on a new position or an arm resolving; 3 arms, 3 done, no unmatched TRADE_OPENED past 1h. Age 31.2h carries no information. |
| `syndicate_calls_anon.jsonl` | 229 rows | append | +1 rows |
| `syndicate_features_anon.jsonl` | 313 rows | append | unchanged |
| `syndicate_paths_anon.jsonl.gz` | 56 rows | append | unchanged |
| `syndicate_recall_coins_anon.jsonl` | 300 rows | append | unchanged |
| `tg_calls_history_anon.jsonl.gz` | 18437 rows | append | unchanged |
| `tg_card_snapshots_anon.jsonl.gz` | 15539 rows | append | unchanged |
| `tg_mentions_anon.jsonl.gz` | 50447 rows | append | unchanged |
| `today` | 83648 rows+bytes | append | +3749 rows+bytes |
| `trade_ledger.csv` | 296 rows | append | unchanged |
| `trade_reflections.jsonl` | 272 rows | append | unchanged |
| `trades.csv` | 238 rows | append | unchanged |
| `uptime.jsonl` | 475 rows | append | +4 rows |
| `veto_tracker.json` | 842159 bytes | snapshot | snapshot — ok |
| `voice_grades.json` | 11680 bytes | snapshot | snapshot — ok |
| `wallet_snapshots.jsonl` | 22 rows | append | +1 rows |
| `watch_log.jsonl` | 27 rows | append | unchanged |

## Known failure modes

- `uptime.jsonl` 475 rows, 2 alive:false of which **2 are read errors** (hb_age_s > 1e8) and 0 are real. Read errors must never alert.
- `ctx_snapshots/` 2026-10-13: 102 stamps, median cadence 898s, **0 gaps > 3x**; 2026-10-14: 97 stamps, median cadence 899s, **0 gaps > 3x**; 2026-10-15: 95 stamps, median cadence 899s, **0 gaps > 3x**

## Fill rates on the ledgers that get reasoned about

- `agent_grades_resolved.jsonl` 3733 rows, 34 columns. **always-empty: `sig_strats`**. 
- `exit_decisions.jsonl` 1336 rows, 15 columns. **always-empty: `new_tp`**. under-50% filled: `new_sl` 9%
- `chief_calls.jsonl` 272 rows, 13 columns. no always-empty columns. 
- `owner_plans.jsonl` 34 rows, 26 columns. no always-empty columns. 
- `llm_exits_resolved.jsonl` 29 rows, 28 columns. no always-empty columns. under-50% filled: `position_id` 17%

## Is the layer itself still running?

_The jobs report what they did. Nothing reported whether the SCHEDULER fired, and a
stopped scheduler leaves a stale STATUS.md that reads exactly like `nothing changed`._

- fresh -- previous run was 1.0 h ago, inside the 2.5 h alarm Scheduler says: state **Running**, last result **267009**, next 10/15/2026 7:10:00 PM, missed 0.

- server feed fresh -- `.last_sync` 0.2 h old, alarm at 3 h

- all three reports are trackable by git, so the hourly commit can carry them


## Panel store

- `candles_1h` 893882 rows, 178 coins, 212.7 days pooled span  (every coin current within 3 days)
- `candles_5m` 478139 rows, 80 coins, 23.2 days pooled span  🔴 **3 of 80 coins have no row newer than 3 days** -- the span above is the POOLED min-to-max and does not mean the table is current
- `ctx` 91136 rows, 178 coins, 5.0 days pooled span  (every coin current within 3 days)
- `funding_hist` 1524928 rows, 178 coins, 369.2 days pooled span  (every coin current within 3 days)

No regressions this run.
