# Export integrity

_Written by `crunch/j4_integrity.py` every hour. Reports presence, growth, fill
rates and gaps. Flags regressions; does not interpret them._

_Updated 2026-10-12 02:20._

## Growth -- is each export still being written?

| export | size | class | change since last run |
|---|---|---|---|
| `LIQ_MAGNET_RECHECK.md` | 1797 bytes | reference | reference — present |
| `README_DATA_RESPONSE.md` | 2908 bytes | reference | reference — present |
| `SYNDICATE_DUDS_PREREG.md` | 4026 bytes | reference | reference — present |
| `SYNDICATE_DUDS_REPORT.md` | 3478 bytes | reference | reference — present |
| `SYNDICATE_RECALL_PREREG.md` | 3896 bytes | reference | reference — present |
| `agent_grades_resolved.jsonl` | 1933 rows | append | +32 rows |
| `ai_plans.json` | 4095 bytes | snapshot | snapshot — ok |
| `archive` | 176978 rows+bytes | append | unchanged |
| `bulk` | 835223 rows+bytes | append | unchanged |
| `call_snapshots.jsonl` | 1 rows | append | new |
| `candles_5m` | 33792 rows+bytes | append | +78 rows+bytes |
| `chief.py` | 12373 bytes | reference | reference — present |
| `chief_calls.jsonl` | 140 rows | append | unchanged |
| `chief_scorecard.json` | 660 bytes | snapshot | snapshot — ok |
| `confidence_state.json` | 3204 bytes | snapshot | snapshot — ok |
| `copilot_call_ledger.jsonl` | 385 rows | append | unchanged |
| `copilot_call_ledger_resolved.jsonl` | 364 rows | append | unchanged |
| `ctx_snapshots` | 25632 rows+bytes | append | +712 rows+bytes |
| `entry_gate_log.jsonl.gz` | 5386 rows | append | unchanged |
| `entry_mom.jsonl` | 1632 rows | append | unchanged |
| `execution_analytics.csv` | 174 rows | append | unchanged |
| `exit_decisions.jsonl` | 1336 rows | append | +1 rows |
| `expmove_log.jsonl` | 119 rows | append | unchanged |
| `floor_decisions_log.jsonl.gz` | 1369 rows | append | unchanged |
| `funding_oi_history.jsonl.gz` | 50287 rows | append | +48 rows |
| `geometry_shadow.json` | 631 bytes | snapshot | snapshot — ok |
| `geometry_shadow_results.jsonl` | 427 rows | append | +6 rows |
| `ic_dropped_resolved.jsonl` | 998 rows | append | unchanged |
| `live_scorecard.json` | 1344 bytes | snapshot | snapshot — ok |
| `llm_exits_resolved.jsonl` | 29 rows | append | unchanged |
| `owner_fills.jsonl` | 4 rows | append | unchanged |
| `owner_plans.jsonl` | 6 rows | append | unchanged |
| `plans.json` | 9617 bytes | snapshot | snapshot — ok |
| `position_journal.jsonl` | 3110 rows | append | +2 rows |
| `position_manager.py` | 138005 bytes | reference | reference — present |
| `scan_grades.json` | 11358 bytes | snapshot | snapshot — ok |
| `scan_log.jsonl` | 344 rows | append | unchanged |
| `scanner.py` | 10667 bytes | reference | reference — present |
| `signal_filtered.jsonl.gz` | 9845 rows | append | unchanged |
| `state` | 532100 rows+bytes | append | unchanged |
| `syndicate_calls_anon.jsonl` | 201 rows | append | +1 rows |
| `syndicate_features_anon.jsonl` | 313 rows | append | unchanged |
| `syndicate_paths_anon.jsonl.gz` | 56 rows | append | unchanged |
| `syndicate_recall_coins_anon.jsonl` | 300 rows | append | unchanged |
| `tg_calls_history_anon.jsonl.gz` | 18437 rows | append | unchanged |
| `tg_card_snapshots_anon.jsonl.gz` | 15539 rows | append | unchanged |
| `tg_mentions_anon.jsonl.gz` | 50447 rows | append | unchanged |
| `trade_ledger.csv` | 296 rows | append | +1 rows |
| `trades.csv` | 238 rows | append | +1 rows |
| `uptime.jsonl` | 110 rows | append | +4 rows |

## Known failure modes

- `uptime.jsonl` 110 rows, 2 alive:false of which **2 are read errors** (hb_age_s > 1e8) and 0 are real. Read errors must never alert.
- `ctx_snapshots/` 2026-10-10: 7 stamps, median cadence 870s, **0 gaps > 3x**; 2026-10-11: 108 stamps, median cadence 898s, **0 gaps > 3x**; 2026-10-12: 29 stamps, median cadence 899s, **0 gaps > 3x**

## Fill rates on the ledgers that get reasoned about

- `agent_grades_resolved.jsonl` 1933 rows, 34 columns. **always-empty: `sig_strats`**. under-50% filled: `r12h` 28%
- `exit_decisions.jsonl` 1336 rows, 15 columns. **always-empty: `new_tp`**. under-50% filled: `new_sl` 9%
- `chief_calls.jsonl` 140 rows, 12 columns. no always-empty columns. 
- `owner_plans.jsonl` 6 rows, 19 columns. no always-empty columns. 
- `llm_exits_resolved.jsonl` 29 rows, 28 columns. no always-empty columns. under-50% filled: `position_id` 17%

## Is the layer itself still running?

_The jobs report what they did. Nothing reported whether the SCHEDULER fired, and a
stopped scheduler leaves a stale STATUS.md that reads exactly like `nothing changed`._

- fresh -- previous run was 1.0 h ago, inside the 2.5 h alarm Scheduler says: state **Running**, last result **267009**, next 10/12/2026 3:10:00 AM, missed 0.

- server feed fresh -- `.last_sync` 0.2 h old, alarm at 3 h

- all three reports are trackable by git, so the hourly commit can carry them


## Panel store

- `candles_1h` 878214 rows, 178 coins, 209.0 days pooled span  (every coin current within 3 days)
- `candles_5m` 314567 rows, 61 coins, 19.6 days pooled span  (every coin current within 3 days)
- `ctx` 25632 rows, 178 coins, 1.3 days pooled span  (every coin current within 3 days)
- `funding_hist` 1509264 rows, 178 coins, 365.5 days pooled span  (every coin current within 3 days)

No regressions this run.
