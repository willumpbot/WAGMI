# Export integrity

_Written by `crunch/j4_integrity.py` every hour. Reports presence, growth, fill
rates and gaps. Flags regressions; does not interpret them._

_Updated 2026-10-11 20:17._

## Growth -- is each export still being written?

| export | size | class | change since last run |
|---|---|---|---|
| `LIQ_MAGNET_RECHECK.md` | 1797 bytes | reference | reference — present |
| `README_DATA_RESPONSE.md` | 2908 bytes | reference | reference — present |
| `agent_grades_resolved.jsonl` | 1788 rows | append | +24 rows |
| `ai_plans.json` | 3957 bytes | snapshot | snapshot — ok |
| `archive` | 176978 rows+bytes | append | +15873 rows+bytes |
| `candles_5m` | 33372 rows+bytes | append | +84 rows+bytes |
| `chief.py` | 12373 bytes | reference | reference — present |
| `chief_calls.jsonl` | 128 rows | append | unchanged |
| `chief_scorecard.json` | 547 bytes | snapshot | snapshot — ok |
| `confidence_state.json` | 3181 bytes | snapshot | snapshot — stale 24.4h — EXPECTED: written on trade close and the last close was 24.9h ago. Not a fault. |
| `copilot_call_ledger.jsonl` | 385 rows | append | unchanged |
| `copilot_call_ledger_resolved.jsonl` | 364 rows | append | unchanged |
| `ctx_snapshots` | 21182 rows+bytes | append | +890 rows+bytes |
| `entry_gate_log.jsonl.gz` | 5386 rows | append | unchanged |
| `entry_mom.jsonl` | 1555 rows | append | +300 rows |
| `execution_analytics.csv` | 174 rows | append | unchanged |
| `exit_decisions.jsonl` | 1324 rows | append | unchanged |
| `expmove_log.jsonl` | 119 rows | append | +59 rows |
| `floor_decisions_log.jsonl.gz` | 1369 rows | append | unchanged |
| `funding_oi_history.jsonl.gz` | 50064 rows | append | +46 rows |
| `geometry_shadow.json` | 630 bytes | snapshot | snapshot — ok |
| `geometry_shadow_results.jsonl` | 390 rows | append | +6 rows |
| `ic_dropped_resolved.jsonl` | 998 rows | append | unchanged |
| `live_scorecard.json` | 1345 bytes | snapshot | snapshot — ok |
| `llm_exits_resolved.jsonl` | 29 rows | append | unchanged |
| `owner_fills.jsonl` | 4 rows | append | +1 rows |
| `owner_plans.jsonl` | 6 rows | append | +1 rows |
| `plans.json` | 9619 bytes | snapshot | snapshot — ok |
| `position_journal.jsonl` | 3108 rows | append | +2 rows |
| `position_manager.py` | 137439 bytes | reference | reference — present |
| `scan_grades.json` | 9397 bytes | snapshot | snapshot — ok |
| `scan_log.jsonl` | 321 rows | append | +42 rows |
| `scanner.py` | 10667 bytes | reference | reference — present |
| `signal_filtered.jsonl.gz` | 9845 rows | append | unchanged |
| `state` | 532100 rows+bytes | append | +2318 rows+bytes |
| `syndicate_calls_anon.jsonl` | 200 rows | append | unchanged |
| `syndicate_paths_anon.jsonl.gz` | 56 rows | append | unchanged |
| `tg_calls_history_anon.jsonl.gz` | 18437 rows | append | new |
| `trade_ledger.csv` | 295 rows | append | unchanged |
| `trades.csv` | 237 rows | append | unchanged |
| `uptime.jsonl` | 85 rows | append | +5 rows |

## Known failure modes

- `uptime.jsonl` 85 rows, 2 alive:false of which **2 are read errors** (hb_age_s > 1e8) and 0 are real. Read errors must never alert.
- `ctx_snapshots/` 2026-10-10: 7 stamps, median cadence 870s, **0 gaps > 3x**; 2026-10-11: 108 stamps, median cadence 898s, **0 gaps > 3x**; 2026-10-12: 4 stamps, median cadence 900s, **0 gaps > 3x**

## Fill rates on the ledgers that get reasoned about

- `agent_grades_resolved.jsonl` 1788 rows, 32 columns. **always-empty: `sig_strats`**. under-50% filled: `r12h` 23%
- `exit_decisions.jsonl` 1324 rows, 15 columns. **always-empty: `new_tp`**. under-50% filled: `new_sl` 9%
- `chief_calls.jsonl` 128 rows, 12 columns. no always-empty columns. 
- `owner_plans.jsonl` 6 rows, 19 columns. no always-empty columns. 
- `llm_exits_resolved.jsonl` 29 rows, 28 columns. no always-empty columns. under-50% filled: `position_id` 17%

## Is the layer itself still running?

_The jobs report what they did. Nothing reported whether the SCHEDULER fired, and a
stopped scheduler leaves a stale STATUS.md that reads exactly like `nothing changed`._

- fresh -- previous run was 1.0 h ago, inside the 2.5 h alarm Scheduler says: state **Running**, last result **267009**, next 10/11/2026 9:10:00 PM, missed 0.

- server feed fresh -- `.last_sync` 0.2 h old, alarm at 3 h

- all three reports are trackable by git, so the hourly commit can carry them


## Panel store

- `candles_1h` 877148 rows, 178 coins, 208.8 days pooled span  (every coin current within 3 days)
- `candles_5m` 305199 rows, 60 coins, 19.3 days pooled span  (every coin current within 3 days)
- `ctx` 21182 rows, 178 coins, 1.1 days pooled span  (every coin current within 3 days)
- `funding_hist` 1508196 rows, 178 coins, 365.2 days pooled span  (every coin current within 3 days)

No regressions this run.
