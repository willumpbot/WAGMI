# Export integrity

_Written by `crunch/j4_integrity.py` every hour. Reports presence, growth, fill
rates and gaps. Flags regressions; does not interpret them._

_Updated 2026-10-14 10:20._

## Growth -- is each export still being written?

| export | size | class | change since last run |
|---|---|---|---|
| `LIQ_MAGNET_RECHECK.md` | 1797 bytes | reference | reference — present |
| `README_DATA_RESPONSE.md` | 2908 bytes | reference | reference — present |
| `SYNDICATE_DUDS_PREREG.md` | 4026 bytes | reference | reference — present |
| `SYNDICATE_DUDS_REPORT.md` | 3478 bytes | reference | reference — present |
| `SYNDICATE_RECALL_PREREG.md` | 3896 bytes | reference | reference — present |
| `agent_grades_resolved.jsonl` | 3102 rows | append | +24 rows |
| `ai_plans.json` | 20522 bytes | snapshot | snapshot — ok |
| `archive` | 248013 rows+bytes | append | unchanged |
| `board_feed.json` | 7139 bytes | snapshot | snapshot — info: retired upstream -- not refreshed, so staleness carries no information |
| `bulk` | 849938 rows+bytes | append | unchanged |
| `call_caller_form_anon.384rows_20261012.jsonl` | 384 rows | append | unchanged |
| `call_caller_form_anon.NEW.jsonl` | 2442 rows | append | unchanged |
| `call_caller_form_anon.jsonl` | 2442 rows | append | unchanged |
| `call_snapshots.jsonl` | 51 rows | append | +2 rows |
| `candles_5m` | 37782 rows+bytes | append | +90 rows+bytes |
| `chief.py` | 12441 bytes | reference | reference — present |
| `chief_calls.jsonl` | 224 rows | append | +6 rows |
| `chief_scorecard.json` | 662 bytes | snapshot | snapshot — ok |
| `conf_floor_decisions.jsonl` | 491 rows | append | unchanged |
| `conf_floor_resolutions.jsonl` | 917 rows | append | unchanged |
| `confidence_state.json` | 3204 bytes | snapshot | snapshot — stale 56.2h — EXPECTED: written on trade close and the last close was 57.0h ago. Not a fault. |
| `copilot_call_ledger.jsonl` | 413 rows | append | +9 rows |
| `copilot_call_ledger_resolved.jsonl` | 393 rows | append | +9 rows |
| `ctx_snapshots` | 67640 rows+bytes | append | +1068 rows+bytes |
| `discrepancies.json` | 14713 bytes | snapshot | snapshot — ok |
| `dissent_log.jsonl` | 300 rows | append | +36 rows |
| `entry_gate_log.jsonl.gz` | 5387 rows | append | unchanged |
| `entry_mom.jsonl` | 1634 rows | append | unchanged |
| `execution_analytics.csv` | 174 rows | append | unchanged |
| `exit_decisions.jsonl` | 1336 rows | append | unchanged |
| `expmove_log.jsonl` | 258 rows | append | unchanged |
| `floor_decisions_log.jsonl.gz` | 1369 rows | append | unchanged |
| `funding_oi_history.jsonl.gz` | 51506 rows | append | +45 rows |
| `geometry_shadow.json` | 646 bytes | snapshot | snapshot — ok |
| `geometry_shadow_results.jsonl` | 758 rows | append | +6 rows |
| `ic_dropped_resolved.jsonl` | 998 rows | append | unchanged |
| `live_scorecard.json` | 1344 bytes | snapshot | snapshot — ok |
| `llm_exits_resolved.jsonl` | 29 rows | append | unchanged |
| `owner_fills.jsonl` | 8 rows | append | +1 rows |
| `owner_plan_sims.json` | 5851 bytes | snapshot | snapshot — ok |
| `owner_plan_sims_resolved.jsonl` | 2 rows | append | unchanged |
| `owner_plans.jsonl` | 23 rows | append | unchanged |
| `plans.json` | 41797 bytes | snapshot | snapshot — ok |
| `position_journal.jsonl` | 3112 rows | append | unchanged |
| `position_manager.py` | 144251 bytes | reference | reference — present |
| `scan_grades.json` | 29116 bytes | snapshot | snapshot — ok |
| `scan_log.jsonl` | 624 rows | append | +19 rows |
| `scanner.py` | 11125 bytes | reference | reference — present |
| `signal_filtered.jsonl.gz` | 9845 rows | append | unchanged |
| `state` | 529599 rows+bytes | snapshot | snapshot — ok (10 files, newest 14.2h of 26h budget) |
| `stop_shadow.json` | 1818 bytes | snapshot | snapshot — ok |
| `syndicate_calls_anon.jsonl` | 222 rows | append | +2 rows |
| `syndicate_features_anon.jsonl` | 313 rows | append | unchanged |
| `syndicate_paths_anon.jsonl.gz` | 56 rows | append | unchanged |
| `syndicate_recall_coins_anon.jsonl` | 300 rows | append | unchanged |
| `tg_calls_history_anon.jsonl.gz` | 18437 rows | append | unchanged |
| `tg_card_snapshots_anon.jsonl.gz` | 15539 rows | append | unchanged |
| `tg_mentions_anon.jsonl.gz` | 50447 rows | append | unchanged |
| `trade_ledger.csv` | 296 rows | append | unchanged |
| `trades.csv` | 238 rows | append | unchanged |
| `uptime.jsonl` | 343 rows | append | +6 rows |

## Known failure modes

- `uptime.jsonl` 343 rows, 2 alive:false of which **2 are read errors** (hb_age_s > 1e8) and 0 are real. Read errors must never alert.
- `ctx_snapshots/` 2026-10-12: 103 stamps, median cadence 900s, **0 gaps > 3x**; 2026-10-13: 102 stamps, median cadence 898s, **0 gaps > 3x**; 2026-10-14: 60 stamps, median cadence 899s, **0 gaps > 3x**

## Fill rates on the ledgers that get reasoned about

- `agent_grades_resolved.jsonl` 3102 rows, 34 columns. **always-empty: `sig_strats`**. 
- `exit_decisions.jsonl` 1336 rows, 15 columns. **always-empty: `new_tp`**. under-50% filled: `new_sl` 9%
- `chief_calls.jsonl` 224 rows, 13 columns. no always-empty columns. 
- `owner_plans.jsonl` 23 rows, 19 columns. no always-empty columns. 
- `llm_exits_resolved.jsonl` 29 rows, 28 columns. no always-empty columns. under-50% filled: `position_id` 17%

## Is the layer itself still running?

_The jobs report what they did. Nothing reported whether the SCHEDULER fired, and a
stopped scheduler leaves a stale STATUS.md that reads exactly like `nothing changed`._

- fresh -- previous run was 1.0 h ago, inside the 2.5 h alarm Scheduler says: state **Running**, last result **267009**, next 10/14/2026 11:10:00 AM, missed 0.

- server feed fresh -- `.last_sync` 0.2 h old, alarm at 3 h

- all three reports are trackable by git, so the hourly commit can carry them


## Panel store

- `candles_1h` 888186 rows, 178 coins, 211.3 days pooled span  (every coin current within 3 days)
- `candles_5m` 427057 rows, 75 coins, 21.9 days pooled span  (every coin current within 3 days)
- `ctx` 67640 rows, 178 coins, 3.6 days pooled span  (every coin current within 3 days)
- `funding_hist` 1519232 rows, 178 coins, 367.8 days pooled span  (every coin current within 3 days)

No regressions this run.
