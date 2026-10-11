# Export integrity

_Written by `crunch/j4_integrity.py` every hour. Reports presence, growth, fill
rates and gaps. Flags regressions; does not interpret them._

_Updated 2026-10-11 16:00._

## Growth -- is each export still being written?

| export | size | change since last run |
|---|---|---|
| `LIQ_MAGNET_RECHECK.md` | 1797 bytes | new |
| `README_DATA_RESPONSE.md` | 2908 bytes | new |
| `agent_grades_resolved.jsonl` | 1672 rows | new |
| `ai_plans.json` | 2528 bytes | new |
| `archive` | 0 rows+bytes | new |
| `candles_5m` | 32982 rows+bytes | new |
| `chief.py` | 11981 bytes | new |
| `chief_calls.jsonl` | 122 rows | new |
| `chief_scorecard.json` | 547 bytes | new |
| `confidence_state.json` | 3181 bytes | new |
| `copilot_call_ledger.jsonl` | 385 rows | new |
| `copilot_call_ledger_resolved.jsonl` | 364 rows | new |
| `ctx_snapshots` | 17088 rows+bytes | new |
| `entry_gate_log.jsonl.gz` | 5383 rows | new |
| `entry_mom.jsonl` | 175 rows | new |
| `execution_analytics.csv` | 173 rows | new |
| `exit_decisions.jsonl` | 1324 rows | new |
| `floor_decisions_log.jsonl.gz` | 61 rows | new |
| `funding_oi_history.jsonl.gz` | 49890 rows | new |
| `geometry_shadow.json` | 630 bytes | new |
| `geometry_shadow_results.jsonl` | 360 rows | new |
| `ic_dropped_resolved.jsonl` | 998 rows | new |
| `live_scorecard.json` | 1345 bytes | new |
| `llm_exits_resolved.jsonl` | 29 rows | new |
| `owner_fills.jsonl` | 1 rows | new |
| `owner_plans.jsonl` | 5 rows | new |
| `plans.json` | 7414 bytes | new |
| `position_journal.jsonl` | 3105 rows | new |
| `position_manager.py` | 137439 bytes | new |
| `scan_grades.json` | 8354 bytes | new |
| `scan_log.jsonl` | 267 rows | new |
| `scanner.py` | 10461 bytes | new |
| `signal_filtered.jsonl.gz` | 9845 rows | new |
| `syndicate_calls_anon.jsonl` | 199 rows | new |
| `syndicate_paths_anon.jsonl.gz` | 56 rows | new |
| `trade_ledger.csv` | 295 rows | new |
| `trades.csv` | 237 rows | new |
| `uptime.jsonl` | 62 rows | new |

## Known failure modes

- `uptime.jsonl` 62 rows, 2 alive:false of which **2 are read errors** (hb_age_s > 1e8) and 0 are real. Read errors must never alert.
- `ctx_snapshots/` 2026-10-10: 7 stamps, median cadence 870s, **0 gaps > 3x**; 2026-10-11: 89 stamps, median cadence 898s, **0 gaps > 3x**

## Fill rates on the ledgers that get reasoned about

- `agent_grades_resolved.jsonl` 1672 rows, 32 columns. **always-empty: `sig_strats`**. under-50% filled: `r12h` 18%
- `exit_decisions.jsonl` 1324 rows, 15 columns. **always-empty: `new_tp`**. under-50% filled: `new_sl` 9%
- `chief_calls.jsonl` 122 rows, 12 columns. no always-empty columns. 
- `owner_plans.jsonl` 5 rows, 17 columns. no always-empty columns. 
- `llm_exits_resolved.jsonl` 29 rows, 28 columns. no always-empty columns. under-50% filled: `position_id` 17%

## Is the layer itself still running?

_The jobs report what they did. Nothing reported whether the SCHEDULER fired, and a
stopped scheduler leaves a stale STATUS.md that reads exactly like `nothing changed`._

- fresh -- previous run was 0.4 h ago, inside the 2.5 h alarm Scheduler says: state **Running**, last result **267009**, next 10/11/2026 4:10:00 PM, missed 0.

- server feed fresh -- `.last_sync` 0.9 h old, alarm at 3 h

- all three reports are trackable by git, so the hourly commit can carry them


## Panel store

- `candles_1h` 876260 rows, 178 coins, 208.5 days pooled span  (every coin current within 3 days)
- `candles_5m` 32982 rows, 6 coins, 19.1 days pooled span  (every coin current within 3 days)
- `ctx` 17088 rows, 178 coins, 0.9 days pooled span  (every coin current within 3 days)
- `funding_hist` 1355931 rows, 178 coins, 365.0 days pooled span  🔴 **123 of 178 coins have no row newer than 3 days** -- the span above is the POOLED min-to-max and does not mean the table is current

No regressions this run.
