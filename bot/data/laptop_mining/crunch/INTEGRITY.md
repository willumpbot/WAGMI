# Export integrity

_Written by `crunch/j4_integrity.py` every hour. Reports presence, growth, fill
rates and gaps. Flags regressions; does not interpret them._

_Updated 2026-10-11 14:18._

## Growth -- is each export still being written?

| export | bytes | change since last run |
|---|---|---|
| `LIQ_MAGNET_RECHECK.md` | 1797 | unchanged |
| `README_DATA_RESPONSE.md` | 2908 | unchanged |
| `agent_grades_resolved.jsonl` | 685136 | unchanged |
| `ai_plans.json` | 2528 | unchanged |
| `candles_5m` | 2915914 | unchanged |
| `chief_calls.jsonl` | 70004 | unchanged |
| `chief_scorecard.json` | 547 | unchanged |
| `confidence_state.json` | 3181 | unchanged |
| `ctx_snapshots` | 671326 | unchanged |
| `entry_gate_log.jsonl.gz` | 192460 | unchanged |
| `entry_mom.jsonl` | 14674 | unchanged |
| `execution_analytics.csv` | 17075 | unchanged |
| `exit_decisions.jsonl` | 772406 | unchanged |
| `floor_decisions_log.jsonl.gz` | 1374 | unchanged |
| `geometry_shadow.json` | 630 | unchanged |
| `geometry_shadow_results.jsonl` | 73463 | unchanged |
| `ic_dropped_resolved.jsonl` | 417696 | unchanged |
| `live_scorecard.json` | 1345 | unchanged |
| `llm_exits_resolved.jsonl` | 21046 | unchanged |
| `owner_fills.jsonl` | 318 | unchanged |
| `owner_plans.jsonl` | 2454 | unchanged |
| `plans.json` | 7412 | unchanged |
| `position_journal.jsonl` | 567888 | unchanged |
| `position_manager.py` | 137439 | unchanged |
| `scan_grades.json` | 8227 | unchanged |
| `scan_log.jsonl` | 275077 | unchanged |
| `scanner.py` | 9440 | unchanged |
| `signal_filtered.jsonl.gz` | 191969 | unchanged |
| `syndicate_calls_anon.jsonl` | 31891 | unchanged |
| `trade_ledger.csv` | 56121 | unchanged |
| `trades.csv` | 388259 | unchanged |
| `uptime.jsonl` | 5723 | unchanged |

## Known failure modes

- `uptime.jsonl` 52 rows, 1 alive:false of which **1 are read errors** (hb_age_s > 1e8) and 0 are real. Read errors must never alert.
- `ctx_snapshots/` 2026-10-10: 7 stamps, median cadence 870s, **0 gaps > 3x**; 2026-10-11: 78 stamps, median cadence 898s, **0 gaps > 3x**

## Fill rates on the ledgers that get reasoned about

- `agent_grades_resolved.jsonl` 1624 rows, 32 columns. **always-empty: `sig_strats`**. under-50% filled: `r12h` 16%
- `exit_decisions.jsonl` 1324 rows, 15 columns. **always-empty: `new_tp`**. under-50% filled: `new_sl` 9%
- `chief_calls.jsonl` 122 rows, 12 columns. no always-empty columns. 
- `owner_plans.jsonl` 5 rows, 17 columns. no always-empty columns. 
- `llm_exits_resolved.jsonl` 29 rows, 28 columns. no always-empty columns. under-50% filled: `position_id` 17%

## Is the layer itself still running?

_The jobs report what they did. Nothing reported whether the SCHEDULER fired, and a
stopped scheduler leaves a stale STATUS.md that reads exactly like `nothing changed`._

- fresh -- previous run was 1.0 h ago, inside the 2.5 h alarm Scheduler says: state **Running**, last result **267009**, next 10/11/2026 3:10:00 PM, missed 0.

- all three reports are trackable by git, so the hourly commit can carry them


## Panel store

- `candles_1h` 876081 rows, 178 coins, 208.5 days
- `candles_5m` 32820 rows, 6 coins, 19.0 days
- `ctx` 15130 rows, 178 coins, 0.8 days
- `funding_hist` 264944 rows, 178 coins, 365.0 days

No regressions this run.
