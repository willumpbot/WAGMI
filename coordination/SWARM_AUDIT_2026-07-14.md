# WAGMI SWARM AUDIT — 2026-07-14 (8-agent deep dive)

## META-CONCLUSION
The system computes CORRECT values at close, then LOSES them at the last hop — wrong metadata key,
missing ledger column, zeroed pos.qty, duplicate-instance clobber, dropped field, SIGN FLIP, UNIT
mismatch, or a THREADING RACE. Result: (a) we cannot trust ANY performance number, (b) the trading
sabotages itself (zeroes winning factors, flat "unknown" sizing, noise-sized LLM trades). The +$337
was a sizing bug + one lucky oversized trade + 3 equity resets; the "no edge" verdict is ALSO
unreliable because the machine fought itself. Both directions corrupted. NOT 40 random bugs — a few
root patterns. Highly fixable, several one-line.

## TIER 0 — DATA INTEGRITY (closes must record exactly ONCE before any number means anything)
- RACE on `_pending_exit_events` (multi_strategy_main.py:3664-3670, SCAN_PARALLEL_SYMBOLS=true):
  unsynchronized read-modify-write across 2 symbol threads -> resurrects a consumed close (the double-log
  ROOT) OR silently DROPS a close (lost forever). FIX: lock + consumed-once event ids.
- STALE-DATA early-return strands closes (msm:3338-3347): a just-closed (qty=0) position isn't "open",
  so the stale-candle return fires BEFORE the event loop injects pending closes -> close never records.
  LIVE PROOF: HYPE close 2026-07-14 22:25 never wrote to ledger (zombie qty=0). Restart = close lost.
  FIX: process _pending_exit_events BEFORE the stale return, or persist the queue.
- CLOSE_DEDUP_GUARD insufficient (msm:3969-3983): only guards the ledger. On a re-fired close, equity
  (+CB feed), IC (:3952), Kelly (:3959, both BEFORE the guard), weight_mgr, regime/conf/hold-time, feedback,
  growth, DNA, ML — ALL double-fire. June dup burst still lives in signal_quality/regime/ML/memory/grad-rules.
  FIX: hoist dedup to top of _FULL_CLOSE block; then scrub/recompute downstream stores.

## TIER 1 — ONE-LINE POISON FIXES (un-corrupt learning in a single hop each)
- exit_price always 0 -> every trade teaches "-100% crash" (data-flow #1): metadata has no exit_price
  key (real value = event.price). msm:4230 -> _price_move_pct = -100% -> regime calibration grades bull
  always WRONG / bear always RIGHT (feeds agent self-trust into prompts), reflection engine, learning-agent
  lessons all poisoned. FIX: event.metadata.get("exit_price") -> event.price. HIGHEST-LEVERAGE ONE-LINER.
- IC sign bug zeroes WINNING strategies (subtle #1, data-flow #6): IC fed direction-adjusted pnl
  (total_pnl/equity) not MARKET return -> a winning SHORT scores "inverted" -> vote weight set 0 -> best
  strategy removed from consensus; losing shorts keep full weight. My 2026-07-13 Kelly/IC revival un-froze
  this poisoned feed -> actively corrupting voting NOW. FIX: feed raw market move.
- regime dropped at ensemble merge -> everything "unknown" (subtle #2): _merge_signals (ensemble.py:2795)
  doesn't propagate regime -> get_regime_risk_mult("unknown")=0.45x FLAT on every mechanical trade; graduated
  regime rules NEVER match; per-regime living-value tables starve. FIX: stamp regime in _merge_signals.

## TIER 2 — RISK SAFETY (strengthens risk; do carefully)
- No margin<=equity cap anywhere (sizing agent, exec #3): all caps notional; unclamped risk_pct
  (coordinator.py:1969) + 10% fallback (:2005) + no stop-width floor (:2011) -> 2x-account oversize can recur.
  FIX: clamp risk_pct, fix 10% fallback -> config, stop-width floor, add hard sum(notional/lev)<=k*equity cap.
- Live MTM drawdown breaker DEAD (exec #4): check_unrealized_risk called only in backtest -> open losers
  bleed past MAX_DRAWDOWN before any close trips CB. FIX: wire into live tick.
- Session-halt bypass on restart (exec #5): _session_halted/session_peak not persisted -> watchdog bounce
  resets the 20% hard stop. FIX: persist + restore.
- Signal-override can bypass tripped CB on mechanical fallback (exec #6, enable_signal_override default true).

## TIER 3 — SIZING/FEE UNIT BUGS (make paper transfer to live)
- LLM-first sizing = noise (subtle #4/#5): stop_width fraction/percent mixup (under-size ~100x) +
  leverage-convention mismatch (over-size by lev x). Two opposing bugs partially cancel.
- Fees understated by ~leverage x (subtle #6, meas #4): fee on qty not qty*leverage -> high-lev/tight-TP
  setups flattered in every learning loop. order_executor hardcodes 2.5bps (real 4.5).
- funding hidden/asymmetric (data-flow #13, meas #11): ledger funding=0 hardcoded; equity doesn't deduct
  funding; accrue_funding uses abs() -> always a cost, never a credit (biases against carry-favorable holds).

## TIER 4 — MY-OWN-FIXES-FED-BAD-DATA (recompute after Tier 0-1)
- live_edge side-mults built on ALL-history DOLLAR pnl (meas #8): HYPE_BUY 0.25 driven by the June
  -$222 OVERSIZED trade, not per-unit edge; ETH/BTC/SOL_SELL saturate 1.5 same way. My living-values
  sizing is built on oversized-era, dollar-scaled, contaminated data. FIX: use R/pct-of-equity + a window.
- Kelly/IC/thesis reset-not-recomputed: near-blind (n<=7); clean 213-row ledger unused; scripts/
  recompute_kelly_from_ledger.py exists. Downstream stores still carry double-counted June data.
- WIN_PROB_PRIOR_DECAY fix touched a DISABLED system: QUANT_BRAIN_ENABLED=false -> _quant_brain=None.

## TIER 5 — DEAD/ADVISORY/CONTRADICTORY WIRING (know before trusting)
- master_engine DEAD since 2026-05-30 (meas #3): trade_ledger.all_trades() doesn't exist, AttributeError
  swallowed -> auto_fix/forensics/synthesis/prompt-injection all dead.
- 11 "enforce" dials ALL shadow/advisory (orphaned): ROUTER_*, NET_CAL, QUANT_AGENT, CRITIC, MERGE_GRAD_VETO,
  TIME_SIZING, EV_BLOCK, HYPE_BUY_BYPASS. Every router/calibration/critic/quant veto is log-only.
- win_prob=0.50 constant outside trending (orphaned #2) -> exploration/EV gates are rubber stamps.
- Shadow DUPLICATE instances clobber state: 2x ParameterTuner/ContinuousBacktester/QualityScorer/
  RegimeFeedback on same files, last-writer-wins. FEEDBACK_RECORD_FIX revived a standalone pair nothing reads.
- EXIT_AGENT_CLOSE_WINNERS default true — ties to edge agent: LLM_EXIT_AGENT is the biggest P&L drag
  (13.8% WR, -$1157 full sample). Needs counterfactual verify (villain vs hero).
- Orphans: pipeline_telemetry (dead output, growing), MissedTradeTracker (live writer/backtest reader),
  ShadowLedger (no consumer), RL (flag-dead), comprehensive_snapshot (never called in prod), dead modules.
- Reflection engine branches on SELL/BUY but gets LONG/SHORT (every short reflected with long math).
- entry_reasons key mismatches (win_prob vs win_prob_deflated, rr_tp1 vs rr1) -> reflection reads 0 forever.
- realized_rr always 0 (pos.qty=0 at close); predicted_ev/realized_rr/win DROPPED (not in LEDGER_COLUMNS).
- counterfactual_resolved: 25% (32,734/133,103) are FAKE zeros from capacity eviction.
- 3 different pnl_pct unit conventions across learning stores; regime label vocab fragmentation.

## EDGE VERDICT (agent 3, size-normalized)
No statistically defensible edge. +$337 = one ETH_SHORT +$1010 (a sub-noise-stop oversize). Strip it: -$673.
Clean window (>=Jun10, margin<=1x): -$338 / 160 trades. "Shorts win" = "market fell -9.5% while oversized short".
Need ~100+ CLEAN (bug-free, properly-sized) trades to know. Currently 5-9. BUT that "clean" data was itself
corrupted by the wiring bugs above -> the negative verdict is ALSO unreliable. TRUE test = post-fix window.

## FIX ORDER (each flag-gated/reversible, verify, don't rush; never weaken risk)
Tier 0 (record once) -> Tier 1 (one-line poison) -> Tier 2 (risk safety) -> RECOMPUTE learning stores from
clean ledger -> Tier 3 (sizing/fee units) -> re-baseline the proof window. Do NOT judge edge or go live
until Tier 0-3 done + a fresh clean window accumulates.
