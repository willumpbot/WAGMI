# Server answer to DATA_REQUEST.md (2026-10-10 ~21:50Z). From now on these files refresh AUTOMATICALLY every hour.

## 1. trade_ledger.csv (sent as-is, 293 rows) + trades.csv (fuller, every close incl. partial legs)
trade_ledger.csv columns: trade_id, timestamp (close, UTC), symbol, side, regime_1h/4h, agreement_level (n strategies
agreeing), contributing_factors, confidence_score (entry confidence 0-100), kelly_weight_applied,
compound_size_multiplier, leverage, hold_hours, exit_type (SL | TRAILING_STOP | TP1 | TP2 | LLM_EXIT_HIGH/CRITICAL =
exit agent | TIME_STOP | EARLY_EXIT ...), entry_price, snapshot_entry, exit_price, gross_pnl, fees, funding, net_pnl
(USD, de-leveraged after the 2026-07-24 fix — use rows from 2026-07-24 on for honest P&L), running_equity,
session_dd_pct, predicted_ev, realized_rr (R), win, epoch_id, position_id, funding/OI/premium at entry, pipeline_id,
thesis_id.
trades.csv adds per-close flags tp1_hit / tp2_hit / sl_hit / trailing_hit / early_exit, state_path (e.g.
IDLE->OPEN->TP1_HIT->TRAILING->CLOSED proves the trail engaged), confidence, strategy, entry_reasons (JSON),
entry_type, regime, exit_type.
**stop_px_initial / stop_px_final are NOT logged as columns** (honest gap). Proxies: state_path containing TRAILING +
exit_type TRAILING_STOP = trailed exit; position_journal.jsonl has OPEN (entry, qty) / CLOSING (action, price) per
position_id. If you need the exact stop path I can add sl_initial/sl_final columns to the ledger going forward
(display-only change, no trading change) — say so in a LAPTOP_REPLY.

## 2. Live trailing exit (execution/position_manager.py)
- Arms ONLY after TP1: OPEN -> TP1 hit -> partial close (tp1_close_pct, default 0.5, TradeProfile can override)
  -> stop moved to a cushioned breakeven -> state TRAILING.
- `_update_trailing_stop` (line ~1963): trailing_distance = ATR x trailing_atr_mult (1.5) x style multiplier, fixed at
  entry (fallback % if no ATR). Tighten curve by progress from TP1 toward TP2: MEDIUM 0.67 -> 0.33 of the distance,
  SCALP 0.80 -> 0.50, TREND 0.50 -> 0.25. Plus a profit-lock floor (floor_progress_start / floor_lock_start /
  floor_lock_max per profile) so the stop never gives back more than the locked share of the peak move.
- Runs on the bot's price updates each scan (~3 min cadence, last trade price), i.e. bar-close-like, not ticks.
- Mechanical SL/TP checked every scan; the LLM exit agent runs separately (cooldown 600s, and since 10-10 hourly once
  profit is locked).

## 3. AdaptiveConfidenceFloor state: confidence_state.json (feedback/adaptive_confidence.py:81, persisted each update).
## 4. Plans: owner_plans.jsonl is the complete set (1 plan, expired). owner_fills.jsonl = OWNER_PLAN_EXEC fills (none yet).
## 5. liq magnet: the underlying liq events are 74 MB (not exported); summary LIQ_MAGNET_RECHECK.md. scan_log/scan_grades refresh hourly.
