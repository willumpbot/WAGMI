# Export integrity

_Written by `crunch/j4_integrity.py` every hour. Reports presence, growth, fill
rates and gaps. Flags regressions; does not interpret them._

_Updated 2026-10-14 21:21._

## Growth -- is each export still being written?

| export | size | class | change since last run |
|---|---|---|---|
| `LIQ_MAGNET_RECHECK.md` | 1797 bytes | reference | reference — present |
| `README_DATA_RESPONSE.md` | 2908 bytes | reference | reference — present |
| `SYNDICATE_DUDS_PREREG.md` | 4026 bytes | reference | reference — present |
| `SYNDICATE_DUDS_REPORT.md` | 3478 bytes | reference | reference — present |
| `SYNDICATE_RECALL_PREREG.md` | 3896 bytes | reference | reference — present |
| `agent_grades_resolved.jsonl` | 3333 rows | append | +90 rows |
| `ai_plans.json` | 24420 bytes | snapshot | snapshot — ok |
| `archive` | 281999 rows+bytes | append | +33986 rows+bytes |
| `board_feed.json` | 7139 bytes | snapshot | snapshot — info: retired upstream -- not refreshed, so staleness carries no information |
| `bulk` | 856704 rows+bytes | append | +6766 rows+bytes |
| `call_caller_form_anon.384rows_20261012.jsonl` | 384 rows | append | unchanged |
| `call_caller_form_anon.NEW.jsonl` | 2442 rows | append | unchanged |
| `call_caller_form_anon.jsonl` | 2442 rows | append | unchanged |
| `call_snapshots.jsonl` | 62 rows | append | +2 rows |
| `candles_5m` | 38580 rows+bytes | append | +294 rows+bytes |
| `cases_index.json` | 2694 bytes | snapshot | snapshot — ok |
| `chief.py` | 12441 bytes | reference | reference — present |
| `chief_calls.jsonl` | 242 rows | append | +12 rows |
| `chief_scorecard.json` | 669 bytes | snapshot | snapshot — ok |
| `conf_floor_decisions.jsonl` | 502 rows | append | unchanged |
| `conf_floor_resolutions.jsonl` | 949 rows | append | +1 rows |
| `confidence_state.json` | 3204 bytes | snapshot | snapshot — stale 67.2h — EXPECTED: written on trade close and the last close was 68.0h ago. Not a fault. |
| `copilot_call_ledger.jsonl` | 414 rows | append | unchanged |
| `copilot_call_ledger_resolved.jsonl` | 393 rows | append | unchanged |
| `ctx_snapshots` | 75294 rows+bytes | append | +2848 rows+bytes |
| `discrepancies.json` | 14963 bytes | snapshot | snapshot — ok |
| `dissent_log.jsonl` | 575 rows | append | +108 rows |
| `dive_requests.jsonl` | 14 rows | append | new |
| `entry_gate_log.jsonl.gz` | 5387 rows | append | unchanged |
| `entry_mom.jsonl` | 1634 rows | append | unchanged |
| `execution_analytics.csv` | 174 rows | append | unchanged |
| `exit_decisions.jsonl` | 1336 rows | append | unchanged |
| `expmove_log.jsonl` | 319 rows | append | +60 rows |
| `floor_decisions_log.jsonl.gz` | 1369 rows | append | unchanged |
| `funding_oi_history.jsonl.gz` | 51925 rows | append | +164 rows |
| `geometry_shadow.json` | 638 bytes | snapshot | snapshot — ok |
| `geometry_shadow_results.jsonl` | 830 rows | append | +29 rows |
| `ic_dropped_resolved.jsonl` | 998 rows | append | unchanged |
| `live_scorecard.json` | 1343 bytes | snapshot | snapshot — ok |
| `llm_exits_resolved.jsonl` | 29 rows | append | unchanged |
| `owner_fills.jsonl` | 8 rows | append | unchanged |
| `owner_plan_sims.json` | 8134 bytes | snapshot | snapshot — ok |
| `owner_plan_sims_resolved.jsonl` | 3 rows | append | +1 rows |
| `owner_plans.jsonl` | 26 rows | append | +3 rows |
| `plans.json` | 48606 bytes | snapshot | snapshot — ok |
| `position_journal.jsonl` | 3112 rows | append | unchanged |
| `position_manager.py` | 144251 bytes | reference | reference — present |
| `scan_grades.json` | 32939 bytes | snapshot | snapshot — ok |
| `scan_log.jsonl` | 677 rows | append | +38 rows |
| `scanner.py` | 11125 bytes | reference | reference — present |
| `signal_filtered.jsonl.gz` | 9845 rows | append | unchanged |
| `state` | 531504 rows+bytes | snapshot | snapshot — ok (10 files, newest 0.2h of 26h budget) |
| `stop_shadow.json` | 1881 bytes | snapshot | snapshot — info: event-driven quiet — content moves only on a new position or an arm resolving; 3 arms, 3 done, no unmatched TRADE_OPENED past 1h. Age 10.2h carries no information. |
| `syndicate_calls_anon.jsonl` | 224 rows | append | unchanged |
| `syndicate_features_anon.jsonl` | 313 rows | append | unchanged |
| `syndicate_paths_anon.jsonl.gz` | 56 rows | append | unchanged |
| `syndicate_recall_coins_anon.jsonl` | 300 rows | append | unchanged |
| `tg_calls_history_anon.jsonl.gz` | 18437 rows | append | unchanged |
| `tg_card_snapshots_anon.jsonl.gz` | 15539 rows | append | unchanged |
| `tg_mentions_anon.jsonl.gz` | 50447 rows | append | unchanged |
| `trade_ledger.csv` | 296 rows | append | unchanged |
| `trades.csv` | 238 rows | append | unchanged |
| `uptime.jsonl` | 386 rows | append | +15 rows |

## Known failure modes

- `uptime.jsonl` 386 rows, 2 alive:false of which **2 are read errors** (hb_age_s > 1e8) and 0 are real. Read errors must never alert.
- `ctx_snapshots/` 2026-10-13: 102 stamps, median cadence 898s, **0 gaps > 3x**; 2026-10-14: 97 stamps, median cadence 899s, **0 gaps > 3x**; 2026-10-15: 6 stamps, median cadence 898s, **0 gaps > 3x**

## Fill rates on the ledgers that get reasoned about

- `agent_grades_resolved.jsonl` 3333 rows, 34 columns. **always-empty: `sig_strats`**. 
- `exit_decisions.jsonl` 1336 rows, 15 columns. **always-empty: `new_tp`**. under-50% filled: `new_sl` 9%
- `chief_calls.jsonl` 242 rows, 13 columns. no always-empty columns. 
- `owner_plans.jsonl` 26 rows, 23 columns. no always-empty columns. 
- `llm_exits_resolved.jsonl` 29 rows, 28 columns. no always-empty columns. under-50% filled: `position_id` 17%

## Is the layer itself still running?

_The jobs report what they did. Nothing reported whether the SCHEDULER fired, and a
stopped scheduler leaves a stale STATUS.md that reads exactly like `nothing changed`._

- 🔴 **STALE: the layer has not run for 4.2 h** (alarm at 2.5 h, which is two missed hourly runs). Check the scheduled task: `schtasks /query /tn WAGMI-LaptopCrunch /fo LIST` Scheduler says: state **Running**, last result **267009**, next 10/14/2026 10:10:00 PM, missed 0.

- server feed fresh -- `.last_sync` 0.2 h old, alarm at 3 h

- all three reports are trackable by git, so the hourly commit can carry them


## Panel store

- `candles_1h` 890144 rows, 178 coins, 211.8 days pooled span  (every coin current within 3 days)
- `candles_5m` 445394 rows, 77 coins, 22.4 days pooled span  (every coin current within 3 days)
- `ctx` 75294 rows, 178 coins, 4.1 days pooled span  (every coin current within 3 days)
- `funding_hist` 1521190 rows, 178 coins, 368.3 days pooled span  (every coin current within 3 days)

No regressions this run.
