# Export integrity

_Written by `crunch/j4_integrity.py` every hour. Reports presence, growth, fill
rates and gaps. Flags regressions; does not interpret them._


## 🔴 REGRESSIONS THIS RUN

- veto_tracker.json snapshot stale 4.2h
_Updated 2026-10-15 11:21._

## Growth -- is each export still being written?

| export | size | class | change since last run |
|---|---|---|---|
| `LIQ_MAGNET_RECHECK.md` | 1797 bytes | reference | reference — present |
| `README_DATA_RESPONSE.md` | 2908 bytes | reference | reference — present |
| `SYNDICATE_DUDS_PREREG.md` | 4026 bytes | reference | reference — present |
| `SYNDICATE_DUDS_REPORT.md` | 3478 bytes | reference | reference — present |
| `SYNDICATE_RECALL_PREREG.md` | 3896 bytes | reference | reference — present |
| `_manifest.json` | 3584 bytes | snapshot | snapshot — ok |
| `accumulation_log.jsonl` | 506 rows | append | unchanged |
| `agent_grades_resolved.jsonl` | 3592 rows | append | +21 rows |
| `ai_plans.json` | 32034 bytes | snapshot | snapshot — ok |
| `archive` | 281999 rows+bytes | append | unchanged |
| `board_feed.json` | 7139 bytes | snapshot | snapshot — info: retired upstream -- not refreshed, so staleness carries no information |
| `bulk` | 856704 rows+bytes | append | unchanged |
| `calibration_observations.jsonl` | 77 rows | append | unchanged |
| `call_caller_form_anon.384rows_20261012.jsonl` | 384 rows | append | unchanged |
| `call_caller_form_anon.NEW.jsonl` | 2442 rows | append | unchanged |
| `call_caller_form_anon.jsonl` | 2442 rows | append | unchanged |
| `call_snapshots.jsonl` | 65 rows | append | unchanged |
| `candles_5m` | 39582 rows+bytes | append | +72 rows+bytes |
| `cases_index.json` | 2707 bytes | snapshot | snapshot — ok |
| `chief.py` | 12441 bytes | reference | reference — present |
| `chief_calls.jsonl` | 260 rows | append | unchanged |
| `chief_scorecard.json` | 669 bytes | snapshot | snapshot — ok |
| `conf_floor_decisions.jsonl` | 547 rows | append | unchanged |
| `conf_floor_resolutions.jsonl` | 961 rows | append | +2 rows |
| `confidence_state.json` | 3204 bytes | snapshot | snapshot — stale 81.2h — EXPECTED: written on trade close and the last close was 82.0h ago. Not a fault. |
| `copilot_alerts.log` | 418611 bytes | reference | reference — present |
| `copilot_call_ledger.jsonl` | 423 rows | append | unchanged |
| `copilot_call_ledger_resolved.jsonl` | 403 rows | append | unchanged |
| `ctx_snapshots` | 85796 rows+bytes | append | +712 rows+bytes |
| `discrepancies.json` | 16344 bytes | snapshot | snapshot — ok |
| `dissent_log.jsonl` | 1276 rows | append | +54 rows |
| `dive_requests.jsonl` | 19 rows | append | +4 rows |
| `entry_gate_log.jsonl.gz` | 5387 rows | append | unchanged |
| `entry_mom.jsonl` | 1636 rows | append | +2 rows |
| `execution_analytics.csv` | 174 rows | append | unchanged |
| `exit_decisions.jsonl` | 1336 rows | append | unchanged |
| `expmove_log.jsonl` | 326 rows | append | unchanged |
| `floor_decisions_log.jsonl.gz` | 1369 rows | append | unchanged |
| `funding_oi_history.jsonl.gz` | 52334 rows | append | +7 rows |
| `geometry_shadow.json` | 636 bytes | snapshot | snapshot — ok |
| `geometry_shadow_results.jsonl` | 910 rows | append | +6 rows |
| `ic_dropped_resolved.jsonl` | 998 rows | append | unchanged |
| `live_scorecard.json` | 1343 bytes | snapshot | snapshot — ok |
| `llm_exits_resolved.jsonl` | 29 rows | append | unchanged |
| `nearmiss_reversion_log.jsonl` | 45 rows | append | unchanged |
| `owner_fills.jsonl` | 11 rows | append | +2 rows |
| `owner_plan_reviews.jsonl` | 29 rows | append | unchanged |
| `owner_plan_sims.json` | 9652 bytes | snapshot | snapshot — ok |
| `owner_plan_sims_resolved.jsonl` | 8 rows | append | +1 rows |
| `owner_plans.jsonl` | 33 rows | append | unchanged |
| `owner_watchlist.json` | 11 bytes | snapshot | snapshot — info: event-driven quiet — manifest shows a fresh export with src_mtime unmoved (last changed 2026-10-12); age 13.2h carries no information. |
| `plans.json` | 61648 bytes | snapshot | snapshot — ok |
| `position_journal.jsonl` | 3116 rows | append | +2 rows |
| `position_manager.py` | 159028 bytes | reference | reference — present |
| `promoted_log.jsonl` | 56 rows | append | +4 rows |
| `scan_grades.json` | 36530 bytes | snapshot | snapshot — ok |
| `scan_log.jsonl` | 770 rows | append | +13 rows |
| `scanner.py` | 11125 bytes | reference | reference — present |
| `signal_filtered.jsonl.gz` | 9845 rows | append | unchanged |
| `signal_value_tracker.jsonl` | 440 rows | append | +2 rows |
| `state` | 531504 rows+bytes | snapshot | snapshot — ok (10 files, newest 14.2h of 26h budget) |
| `state_transitions.csv` | 19089 rows | append | unchanged |
| `stop_shadow.json` | 1881 bytes | snapshot | snapshot — info: event-driven quiet — content moves only on a new position or an arm resolving; 3 arms, 3 done, no unmatched TRADE_OPENED past 1h. Age 24.2h carries no information. |
| `syndicate_calls_anon.jsonl` | 225 rows | append | unchanged |
| `syndicate_features_anon.jsonl` | 313 rows | append | unchanged |
| `syndicate_paths_anon.jsonl.gz` | 56 rows | append | unchanged |
| `syndicate_recall_coins_anon.jsonl` | 300 rows | append | unchanged |
| `tg_calls_history_anon.jsonl.gz` | 18437 rows | append | unchanged |
| `tg_card_snapshots_anon.jsonl.gz` | 15539 rows | append | unchanged |
| `tg_mentions_anon.jsonl.gz` | 50447 rows | append | unchanged |
| `today` | 56545 rows+bytes | append | +3728 rows+bytes |
| `trade_ledger.csv` | 296 rows | append | unchanged |
| `trade_reflections.jsonl` | 272 rows | append | unchanged |
| `trades.csv` | 238 rows | append | unchanged |
| `uptime.jsonl` | 445 rows | append | +4 rows |
| `veto_tracker.json` | 841570 bytes | snapshot | snapshot — **stale 4.2h** |
| `voice_grades.json` | 11680 bytes | snapshot | snapshot — ok |
| `wallet_snapshots.jsonl` | 15 rows | append | +1 rows |
| `watch_log.jsonl` | 15 rows | append | +4 rows |

## Known failure modes

- `uptime.jsonl` 445 rows, 2 alive:false of which **2 are read errors** (hb_age_s > 1e8) and 0 are real. Read errors must never alert.
- `ctx_snapshots/` 2026-10-13: 102 stamps, median cadence 898s, **0 gaps > 3x**; 2026-10-14: 97 stamps, median cadence 899s, **0 gaps > 3x**; 2026-10-15: 65 stamps, median cadence 900s, **0 gaps > 3x**

## Fill rates on the ledgers that get reasoned about

- `agent_grades_resolved.jsonl` 3592 rows, 34 columns. **always-empty: `sig_strats`**. 
- `exit_decisions.jsonl` 1336 rows, 15 columns. **always-empty: `new_tp`**. under-50% filled: `new_sl` 9%
- `chief_calls.jsonl` 260 rows, 13 columns. no always-empty columns. 
- `owner_plans.jsonl` 33 rows, 26 columns. no always-empty columns. 
- `llm_exits_resolved.jsonl` 29 rows, 28 columns. no always-empty columns. under-50% filled: `position_id` 17%

## Is the layer itself still running?

_The jobs report what they did. Nothing reported whether the SCHEDULER fired, and a
stopped scheduler leaves a stale STATUS.md that reads exactly like `nothing changed`._

- fresh -- previous run was 1.0 h ago, inside the 2.5 h alarm Scheduler says: state **Running**, last result **267009**, next 10/15/2026 12:10:00 PM, missed 0.

- server feed fresh -- `.last_sync` 0.2 h old, alarm at 3 h

- all three reports are trackable by git, so the hourly commit can carry them


## Panel store

- `candles_1h` 892636 rows, 178 coins, 212.4 days pooled span  (every coin current within 3 days)
- `candles_5m` 472692 rows, 80 coins, 23.0 days pooled span  🔴 **2 of 80 coins have no row newer than 3 days** -- the span above is the POOLED min-to-max and does not mean the table is current
- `ctx` 85796 rows, 178 coins, 4.7 days pooled span  (every coin current within 3 days)
- `funding_hist` 1523682 rows, 178 coins, 368.9 days pooled span  (every coin current within 3 days)