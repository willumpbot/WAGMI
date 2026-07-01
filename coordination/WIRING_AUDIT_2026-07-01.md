# WAGMI Wiring Audit — 2026-07-01 (micro-level interaction trace)

Scope: micro-level interaction tracing across five seams (signal-to-trade, llm-pipeline, sizing-wire, exit-wire, close-to-learning, data-plumbing). Every finding below survived adversarial verification against actual code + live data; severities are the corrected post-verification values. Ranked by PnL/learning impact. Tags: **AUTONOMOUS** = pure measurement/logging fix, **OWNER-GATED** = changes trading behavior (per backtest-before-adding rule, these need validation before shipping; full-autonomy mandate applies after that).

Counts: 3 critical, 17 high, 24 medium, 16 low (some overlapping raw findings merged). 4 refuted findings listed at bottom — do not re-chase.

---

## CRITICAL

### 1. LLM-first path never submits an exchange order — entries exist only in PositionManager
**critical | signal-to-trade | OWNER-GATED**
- Evidence: `multi_strategy_main.py:8016-8035` — after `# Submit order`, `_process_symbol_llm_first` calls `pos_mgr.open_position(...)` directly; `order_executor.open_position` exists only on the mechanical path (7027/7039, grep-confirmed). Closes DO route through the exchange (`order_executor.close_position` 3369/3418/3516) and are always reduce-only (`order_executor.py:359`), so live-mode closes of never-opened positions are rejected → CRITICAL branch at 3523-3529 → stuck phantom position retrying forever. Masked today by `ENVIRONMENT=paper`; `LLM_FIRST_MODE=true` makes this the active entry path.
- Impact: one env flip from live catastrophe — every production entry a phantom, PnL in-memory only. Even in paper, entries skip fill-price/qty reconciliation (7059-7060) and `ops_guard.record_trade()`/execution analytics (7055-7076).
- Fix: mirror mechanical path in `_process_symbol_llm_first`: `order_executor.open_position(...)` before `pos_mgr.open_position`, bail if not filled, use `order_result.fill_price/fill_qty`.

### 2. LLM/heuristic partial closes are a PnL black hole — qty reduced, profit leg never recorded anywhere
**critical | exit-wire / close-to-learning | OWNER-GATED**
- Evidence: `core/position_wiring.py:838-843` (LLM partial) and `:1026-1031` (heuristic partial) do only `pos.qty -= close_qty` after the fill — no fee, no leg PnL, no `realized_pnl`/funding update, no TradeEvent, no equity update, no `round_qty`. Compare mechanical TP1 full accounting at `execution/position_manager.py:1159-1172` + TradeEvent 1228-1252 → equity at `multi_strategy_main.py:3531`. Live proof: `exit_closes.jsonl` 2026-07-01 SOL LONG closed at qty 0.1546875 = 9.9 × 0.5^6 (six unaccounted 50% partials), recorded pnl -$0.06 — banked profit invisible. Final close computes PnL on remaining qty only (`position_manager.py:1400`).
- Impact: every partial-banked profit vanishes from paper equity (drives sizing + daily-loss CB), trades.csv, feedback, strategy weights. Win/loss labels can invert (partial at +2% then SL on remainder = recorded pure loss) — learning trains on falsified outcomes. Fires repeatedly in production.
- Fix: extract TP1 accounting into shared `PositionManager.partial_close(symbol, pct, price, action)` returning a TradeEvent; both wiring sites call it and append to `_pending_exit_events` so equity + log_trade flow through the main loop.

### 3. LIQUIDATION_AVOID force-close event discarded — close never reaches equity, trades.csv, or learning
**critical | close-to-learning | OWNER-GATED**
- Evidence: `multi_strategy_main.py:4506-4512` — `force_close(symbol, price, "LIQUIDATION_AVOID")` runs AFTER the events loop (3499); TradeEvent used only for an alert, then dropped. The four sibling force_close sites (3373/3422/3455/3463) append to `_force_close_events` (3346, injected 3487-3488) precisely to avoid this. Closed position deleted by stale cleanup 4528-4531 next tick; `update_equity` is incremental and persisted — the PnL is permanently missing.
- Impact: the largest leveraged losses (liq-proximity closes, 1.5-3% from liquidation) silently erased from equity → CB and sizing run on inflated equity, persisted across restarts; no trades.csv/ledger row, zero learning. This is the mechanism for "position count drops with no logged close."
- Fix: append event to a pending list injected into next events-loop pass (same `_force_close_events` pattern); refactor all force_close sites through one helper; persist `_pending_exit_events` to disk.

---

## HIGH

### 4. Exit asymmetry root cause A — no profit protection in the 0R-to-TP1 band
**high | exit-wire | OWNER-GATED**
- Evidence: `execution/position_manager.py:839` trailing gated on `state == TRAILING`, entered ONLY in `_partial_close_tp1` (:1200). Pre-TP1 only lock is BE ratchet needing 1.2R (MEDIUM, :580-585); MEDIUM TP1 = 1.0R (`trade_profile.py:131-139`) and ranging regime shrinks TP1 ×0.8 while widening SL ×1.2 (:334-338) — most excursions live in a 0–1.19R dead zone. Live proof (`exit_closes.jsonl`): XRP SHORT mfe 1.90% → -$0.004; ETH SHORT mfe 2.54% → +$0.011; HYPE mfe 5.61% → +$0.03; vs full losers BTC -$1.04, XRP -$2.78.
- Impact: primary mechanical source of crumb-wins/full-losses — structural avg_loss > avg_win independent of entry quality; poisons calibration (huge-MFE trades recorded as scratches).
- Fix: decouple peak-ratchet from the TP1 state gate — run trailing-floor logic in OPEN state once peak_move > ~0.5R, or lower `_be_trigger` so the lock band overlaps TP1. Backtest first.

### 5. Exit asymmetry root cause B — post-TP1 runner strangled: floor locks 57.5% of peak instantly, overwriting the cushion-BE in the same tick
**high | exit-wire | OWNER-GATED**
- Evidence: `position_manager.py:1300` progress = peak/(tp2-entry) = 0.5 the instant TP1 fills (MEDIUM TP1=1.0/TP2=2.0 ATR); floor branch 1321-1329 → lock_pct 0.575, tolerating only 0.425-ATR retrace. `_partial_close_tp1` had just set cushion SL ~1 ATR below entry (1180-1189, "more room for the runner") — the protective move at 1339-1355 yanks it up in the SAME update() call; the cushion block is dead code. Dynamic TP scaling (1119-1142) closes even more at TP1.
- Impact: mechanical ceiling ~0.79 ATR gross on winners vs 1.0-1.2 ATR full losses — every MEDIUM trade reaching TP1 is capped into a crumb.
- Fix: one owner of `pos.sl` post-TP1 — compute progress from TP1 (starts at 0 when trailing activates) or grace-window the floor; delete the dead cushion block if the floor wins. Backtest first.

### 6. Exploration path sizes inverse-to-stop-width and bypasses all sizing guards (the $628 XRP LONG)
**high | sizing-wire | OWNER-GATED**
- Evidence: `multi_strategy_main.py:7728-7739` — `_ex_qty = _risk_usd / (_stop_w * _ex_lev)` with `_ex_lev`≈1.0 (skips have leverage=1.0, `coordinator.py:1712-1714`); only check `_stop_w > 0`. Skips `risk_mgr.calculate_qty` entirely: no fee-padded stop, min-stop reject, notional cap, symbol mults (XRP 0.60), regime/adaptive multipliers. Verified: 07-01 XRP LONG ~$628 notional on $7.83 intended risk (fees $0.56 = 7%). `.env` `MIN_STOP_WIDTH_PCT=0.002` overrides the data-derived 0.005 default (`trading_config.py:430-434`) — worst case ~2x-equity notional, fees ~45% of intended risk. 06-25 exploration LONGs executed despite HARD_CONSTRAINT_VETO/KELLY_ZERO flags: -$52 in one night.
- Impact: tight-stop signals (the ones the LLM already vetoed) get 2-3x the notional of wide-stop trades; fee drag scales with notional not risk.
- Fix: route exploration qty through `risk_mgr.calculate_qty(..., risk_per_trade_override=EXPLORATION_RISK_PCT)`; enforce `stop_w >= entry*min_stop_width_pct`; restore `.env` MIN_STOP_WIDTH_PCT=0.005.

### 7. 'LLM pipeline failure' skips (conf=0.0) become live trades and are logged as LLM vetoes
**high | llm-pipeline | OWNER-GATED**
- Evidence: `coordinator.py:1752-1768` returns `EntryDecision.skip("LLM pipeline failure")` when the pipeline/CLI fails; the skip branch (`multi_strategy_main.py:7650+`) treats it like any judgment-skip — exploration converts it (quant-EV arm, :373-386/7706-7727) into a real entry. Live proof: trades.csv rows 82-83, two closed losses (ETH SHORT -$9.50, -$8.48) with thesis "LLM pipeline failure", llm_confidence 0.0, regime "unknown". Non-explored failures logged as vetoes: 167 "LLM pipeline failure" records in `data/counterfactuals/scenarios.json` (:7788-7813). (Note: Critic vacc gate is fed from a different, never-written store — that sub-chain refuted.)
- Impact: CLI outages open positions with zero LLM judgment; veto-counterfactual/outcome data heavily polluted — directly against fix-measurement-first.
- Fix: distinct failure sentinel (`pipeline_failed=True` / action='error'); exclude from exploration conversion and from record_veto/llm_skip tracking — log stage='pipeline_error'.

### 8. Sizing formula divides by leverage — every leverage CAP increases notional and dollar risk
**high | sizing-wire | OWNER-GATED**
- Evidence: `execution/risk.py:634` and `execution/leverage.py:254` `qty = risk_usd/(stop*leverage)` → dollar-at-stop ≈ risk_usd/leverage, contradicting the docstring (risk.py:594). All five live leverage caps (`multi_strategy_main.py:5729-5765, 5877-5883`) therefore ENLARGE qty; CB cap 7x→2x = 3.5x qty × 0.5 size_mult = 1.75x LARGER dollar risk during a circuit-breaker override. LLM-first path uses the opposite convention (`coordinator.py:1828-1832`, no leverage divisor) — identical signals size ~7x apart across the two live paths.
- Impact: safety mechanisms inverted ("reduce leverage" = bigger position); trades.csv per-trade risk incomparable between paths, corrupting Kelly/WR learning. Bounded: never exceeds risk_usd budget (leverage>=1), so under-sizing not blowup.
- Fix: one convention — `qty = risk_usd/effective_stop` (delete `* effective_leverage`), MUST ship with a risk_per_trade re-tune + backtest (the divisor currently hides ~5-7x inflation).

### 9. LLM Risk Agent risk_pct unclamped; omitted-field fallback hardcodes 10% risk ignoring RISK_PER_TRADE
**high | sizing-wire | OWNER-GATED**
- Evidence: `coordinator.py:1789-1793` parses risk_pct with NO bounds (leverage clamped 1-20, sz clamped 0.3-2.0 — risk_pct, the one that scales qty, is not); `:1825-1826` fallback `risk_pct = 0.10 * sz_mult` vs config RISK_PER_TRADE=0.015; `:1832` qty = equity*risk_pct/stop. OpsGuard (5x-equity/position) rejects the worst units-mismatch tails, but e.g. risk_pct=0.15 at a 3% stop fills → ~15% equity risked; the 10% fallback fills whenever the stop is >~2%.
- Impact: 6.7-10x oversized dollar risk can execute on the highest-authority sizing path.
- Fix: clamp post-parse `min(risk_pct, 0.05)`; treat >1.0 as percent-units (÷100); fallback = `config.risk_per_trade * sz_mult`.

### 10. All merged size modulation (Kelly, drawdown bands, Risk 'reduce') computed then dropped — never reaches position size
**high | llm-pipeline | OWNER-GATED**
- Evidence: `_merge_outputs` computes size_mult (Risk reduce→min 0.7 at `coordinator.py:4718-4722`, Kelly 4729-4737, drawdown 4740-4751) → `decision.size_multiplier` (4961). `get_entry_decision` assigns it to a dead local (:1811-1812, never read again); position_qty uses risk_pct only (:1820-1832); EntryDecision.size_multiplier carries the RAW `sz` (:1795/1914), which multi_strategy_main puts into a LeverageDecision (7996-8002) that is never passed to open_position. RISK_AGENT_PROMPT (prompts.py:252-255) promises downstream multiplication that never happens.
- Impact: drawdown de-risking, Kelly scaling, and Risk 'reduce' overrides are silent no-ops on live LLM-first sizing — three risk-reduction layers disabled.
- Fix: fold `decision.size_multiplier` into qty in get_entry_decision (`equity*risk_pct*size_mult/stop`), pass the post-Kelly/DD value into EntryDecision.

### 11. risk_mult_override set on pre-merge signals dropped by _merge_signals — solo/soft-veto size reductions never reach sizing
**high | signal-to-trade | OWNER-GATED**
- Evidence: `ensemble.py` writers on INPUT signals (1729 proven-solo 0.5x, 1745 HYPE-solo 0.4x, 1774, 1789, 1911-1913 soft-veto 0.3-1.0x); `_merge_signals` (2616-2659) builds a fresh metadata dict dropping all of them (plus solo_proven/opposition flags). Consumers read the FINAL signal (`core/signal_pipeline.py:816-819, 1299-1302`). `backtest/engine.py:967` reads the dropped flags too — backtests misclassify solo setups.
- Impact: solo and soft-vetoed (previously hard-blocked) trades execute at FULL size — 2-3.3x intended on exactly the lowest-conviction class; corrupts backtests that validated the solo paths.
- Fix: in `_merge_signals`, propagate `merged_rm = min(s.metadata.get('risk_mult_override', 1.0))` + flags; regression test: solo bollinger_squeeze → merged rm == 0.5.

### 12. Time-of-day sizing applied twice; second application inverts LONG direction (LONG/SHORT vs BUY/SELL clash)
**high | sizing-wire | OWNER-GATED**
- Evidence: first application `core/signal_pipeline.py:859-870` (correct BUY/SELL); second `multi_strategy_main.py:6050-6066` with side rebound to LONG/SHORT (:5180); `execution/time_sizing.py:180/263` map anything != "BUY" to short — every LONG scored as SHORT. `_HOUR_BIAS` (:98-105): hours 8/9/17/22 short-biased → LONGs get the 1.15x short-boost instead of 0.85x penalty; long-biased 14-15 inverted. DEAD-hour 0.5x double-applies to 0.25x. (XRP LONG opened 09:32 UTC — an inverted-boost slot.)
- Impact: longs systematically oversized in statistically short-favored hours — feeds the "losing longs sized bigger" pattern; DEAD-hour trades quartered.
- Fix: normalize in time_sizing (`side.upper() in ("BUY","LONG")`); delete the second application at 6049-6066 (chain already applied it).

### 13. RiskFilterChain Gate 1f (win-prob floor) dead; Gate 1g (graduated rules) runs with empty regime/num_agree/strategies
**high | signal-to-trade | OWNER-GATED**
- Evidence: `core/signal_pipeline.py:388` reads `meta.get('win_prob')` — never set anywhere in the file (win_prob lives in `signal.metadata`, ensemble.py:2652) → the 0.30 hard-reject (423-432) never fires. `:447-454` passes regime=""/num_agree=1/strategies=[] into graduated_rules. Under LLM_FIRST_MODE the ensemble's own graduated veto is advisory-only, making this misfed gate the only hard-block — regime/strategy/num_agree-conditioned learned vetoes are fail-open.
- Impact: two risk gates silently disabled/crippled on the live path (partially mitigated by ensemble win_prob clamp + EV gate).
- Fix: hydrate meta at top of `evaluate()` from `signal.metadata` (win_prob, regime, num_agree, strategies_agree).

### 14. LLM 'flip' action silently converted to 'go' — bot would trade the direction the LLM said to reverse
**high | llm-pipeline (also signal-to-trade) | OWNER-GATED**
- Evidence: `coordinator.py:1860-1861` `flip → "go"  # flip handled at caller level` — no caller handles it; EntryDecision has no side field (`decision_types.py:200-252`); `multi_strategy_main.py:7823` `side = raw_signal.side`; SL/TP safety block 7904-7915 rebuilds stops around the original side, hiding the inversion. Flip is reachable (prompts.py:127 schema; Critic adjusted_action 4796-4799); `agent_performance.jsonl` shows 3 real flips (low-conf), decisions.jsonl shows zero — masked before logging, corrupting attribution. autonomy_router's flip handling applies only to the bypassed monolithic path.
- Impact: when a flip survives the merge, the bot opens the exact opposite of LLM intent at full approved size; calibration attributes the outcome to 'go'.
- Fix: add `side_override` to EntryDecision (or return skip on flip until it exists); in `_process_symbol_llm_first` flip side + recompute SL/TP.

### 15. HOLD_LIMIT force-closes bypass exchange submission AND the whole post-trade pipeline
**high | exit-wire | OWNER-GATED**
- Evidence: `core/position_wiring.py:1066-1079` — `check_hold_limits` TradeEvent used only for log + Telegram, never appended to `_pending_exit_events`, never given to order_executor; `_close_position` is pure bookkeeping; `_close_actions` (multi_strategy_main.py:3509-3512) omits HOLD_LIMIT; the `_FULL_CLOSE` entry (3553) is dead code for this path.
- Impact: position marked CLOSED internally while the exchange position stays open (naked until reconciliation); skips equity, log_trade, all learning — same silent-drop class as the pre-06-06 LLM_EXIT_AGENT bug.
- Fix: submit `order_executor.close_position`, set `_exchange_submitted`, append event to `_pending_exit_events`; add HOLD_LIMIT to `_close_actions`.

### 16. Veto auto-retire scores block-hit-RATE on a biased estimator; retirement is a one-way door (killed the vindicated HYPE-long veto)
**high | close-to-learning | OWNER-GATED**
- Evidence: retire at `graduated_rules.py:456` (n>=10, acc<0.35); "correct" = sign-only `hypothetical_pnl_pct > 0` (`counterfactual_learner.py:565`), optimistic tie-break to WIN (516-529), no fees; forming-candle feed (`multi_strategy_main.py:3248-3254`) + per-extension bar counting (474-476) inflates the 48-bar timeout; `record_veto_outcome` (436-437) ignores `rule.active` — no reactivation path. Live: `hype_long_veto_v1` retired, now shows 52.6% CF-measured vs 88.9% TRUE blocked-loser rate (HYPE LONG 11.1% WR, -$592 in trades.csv).
- Impact: genuinely money-saving vetoes get retired on biased measurement and can never come back; HYPE longs flowed again post-retirement.
- Fix: score vetoes on fee-adjusted PnL-weighted EV; resolve first-touch conservatively; count completed candles only; rolling re-evaluation with reactivation; consistent active-checking.

### 17. event.metadata['exit_price'] never exists — Learning Agent price_move_pct is -100% on every close; regime calibration ledger is fiction
**high | close-to-learning | AUTONOMOUS**
- Evidence: full-close metadata (`position_manager.py:1480-1509`) has no 'exit_price' key (exit price is `event.price`); `multi_strategy_main.py:3970` → 0.0 → `:4003` price_move = exactly -100% → `learning_integration.py:448-457` `_regime_was_correct(regime, -100)` deterministically scores trend/panic ALWAYS correct, range/bull ALWAYS wrong. Reflection engine also gets exit_price=0 (:3914); Learning Agent prompt sees exit_price:0. This is the still-broken 2026-06-19 fix (comment 3998-4000).
- Impact: regime-agent calibration ledger is 100% fabricated; per-close lessons computed on fictional moves.
- Fix (one line each): `_exit_price_close = event.price`; reflection `exit_price=event.price` (or stamp metadata in `_close_position`).

### 18. Graduated record_outcome never passes strategy/setup_type — every strategy-conditioned rule fires forever, permanently unmeasured
**high | close-to-learning | AUTONOMOUS**
- Evidence: `graduated_rules.py:346-347` signature lacks strategy/setup_type; matches() call 371-373 defaults them to "" → matches() lines 92/106 reject any strategy/setup-conditioned rule. Caller (`multi_strategy_main.py:3734-3738`) has `event.strategy` in hand, doesn't pass it. Live JSON: all 5 strategy-conditioned rules at applied=0. They DO adjust live confidence on the coordinator path (coordinator.py:4918-4921 passes strategy) but can never accrue accuracy → auto-retire can never fire; reported "new" forever.
- Impact: un-killable confidence-adjusting rules; breaks the learning loop's self-correction guarantee.
- Fix: add `strategy=event.strategy` (+ setup_type) to record_outcome and its matches() call; better, stamp fired rule_ids into entry_reasons at entry and credit by id at close.

### 19. Regime and thesis recorded as 'unknown'/'' on every exploration/pipeline-failure trade — regime-keyed learning collapses into one bucket
**high | data-plumbing | AUTONOMOUS**
- Evidence: `multi_strategy_main.py:7933` and `coordinator.py:1908` `regime or "unknown"`; root cause: coordinator fast-path skip EntryDecisions hardcode regime='unknown' (:1712-1721, :1768) even though market_context regime is in scope. All 9 trades since 06-26 carry regime unknown/'' with empty thesis/sizing_rationale/agent_confidences; `trade_ledger.csv` regime_1h IS populated for the same period (consolidation=46, range=22, trending_bear=16) — computed but dropped at the handoff. Consumers: prompt_enricher regime edge + per-regime floors, dynamic_stats REGIME PERFORMANCE.
- Impact: 100% of current-posture trades feed 'unknown' to every regime-conditional learner and prompt stat.
- Fix: at the recording seam, fall back to the ledger regime_1h classifier / signal metadata regime when entry_decision.regime is empty; verify next trade row.

### 20. get_win_rate_by("strategy") in prompts groups ALL trades under 'unknown'; setup edge map injects an empty-string key
**high | data-plumbing | OWNER-GATED**
- Evidence: `coordinator.py:3047-3062` and `core/llm_integration.py:562-584` call `dm.trade_dna.get_win_rate_by("strategy")` — TradeDNA (`deep_memory.py:78-118`) has no 'strategy' field (only strategies_agreed list) → `{'unknown': {wr:27, n:120}}` injected as "strategy performance". Setup edge map keyed by setup_type: only n>=5 keys are ''/None (108+8 of 120 records) → `{'': {wr:27}}` labeled "setup edge map".
- Impact: agents told there is one strategy and one setup, both ~27% WR — pooled junk presented as per-strategy edge, actively teaching the LLM nothing has edge.
- Fix: iterate strategies_agreed (or use StrategyFingerprints, correctly populated); drop empty keys; fix setup_type recording (finding 21).

---

## MEDIUM

### 21. Quant Brain "live calibrations" are a silent no-op — gating runs on the frozen 2026-06-03 win-prob table
**medium | data-plumbing | OWNER-GATED**
- Evidence: `llm/quant_brain.py:330-336` keys calibrations by setup_type, but trade_dna.json has setup_type=''/missing on 116/120 records (LLM-first entry_reasons never writes 'setup_key' — `core/analytics.py:205`, `multi_strategy_main.py:7956-7970`); lookup key is `{symbol}_{side}` (:719/732) → never hits. Live log confirms: "live_sourced=2" = the dead ''/'unknown' cells. Tempering: frozen WPs (0.28-0.35) cannot veto under current thresholds (skip only at wp<0.10; wp<0.48 check is warning-only), and confidence_adj is heuristic-driven — so broken plumbing + misleading WP strings, not active vetoing.
- Fix: write `setup_key=f"{symbol}_{BUY|SELL}"` into LLM-first entry_reasons and/or derive calibration keys from symbol+side; startup assertion that ≥1 calibration key matches the lookup vocabulary.

### 22. Quant Brain calibrations refresh exactly once per process — refresh_calibrations() has zero callers
**medium | data-plumbing | OWNER-GATED**
- Evidence: `quant_brain.py:308` sole invocation (in `__init__`, module singleton at :1580); `_calibration_last_refresh` written (:389) never read; record_outcome only feeds the 2h chase window. Frozen values are load-bearing (:732).
- Impact: even after 21 is fixed, WPs freeze at bot start for multi-day uptimes.
- Fix: TTL re-refresh inside record_outcome (`> 3600s → _refresh_calibrations()`).

### 23. Exit Agent winner-close structurally unreachable: hardcoded 0.85 confidence vs 0.90 gate; EXIT_AGENT_FULL_CLOSE flag is a no-op for winners
**medium | exit-wire | OWNER-GATED**
- Evidence: `position_wiring.py:786-792` maps urgency→0.85/0.75 (agent schema has no confidence field — urgency IS its signal); `exit_engine.py:150-153` requires >=0.90 to close anything 1 tick past entry (fee-less is_profitable :135). Losers closable at 0.75 via dead-capital carve-out (:147). exit_closes.jsonl: 11/11 recent LLM_EXIT_AGENT closes negative. Note: blocking agent winner-closes is deliberate (documented 0/71, -$1,502 evidence) — the defects are (a) the documented re-enable flag silently doesn't work, (b) fee-blind is_profitable makes slightly-green dead capital unclosable.
- Fix: make the 0.90 gate honest (document unreachable, or map urgency ceiling above it when EXIT_AGENT_FULL_CLOSE=true); is_profitable = beyond entry ± round-trip fee buffer.

### 24. Dead-capital carve-out is fragile keyword matching on truncated free text; fee-blind is_profitable exempts marginally-green stuck positions
**medium | exit-wire | OWNER-GATED**
- Evidence: `exit_engine.py:137-141` substring match on 120-char-truncated reason (`position_wiring.py:791`); `:135` raw `current_price > entry`. exit_closes.jsonl shows the decay signature: mfe 0.19-1.02% positions closed at -$0.45..-$2.63 hours later, after decaying from green to red.
- Fix: structured field from the agent (`category='dead_capital'` / `thesis_valid=false`); fee-buffered is_profitable (reuse `position_manager.py:589` formula).

### 25. Circuit-breaker size_multiplier applied twice (0.25x instead of 0.5x), transiently 3x in the LLM-authoritative branch
**medium | sizing-wire | OWNER-GATED**
- Evidence: `core/signal_pipeline.py:690-692` (into chain risk_mult) → `multi_strategy_main.py:5719` → calculate_qty; re-applied to qty at `:5950-5952` (and 5938-5941, 6625-6630). Fails safe (undersizes) but quarters post-cooldown recovery trades.
- Fix: apply once — keep signal_pipeline.py:692, delete the re-applications.

### 26. Per-symbol risk_per_trade override fetched then clobbered; vol-target baseline has daily-vs-intraday ATR units mismatch
**medium | sizing-wire | OWNER-GATED**
- Evidence: `multi_strategy_main.py:5884` fetch → `:5903` unconditionally reassigns `config.risk_per_trade * _compound_mult`. `_compound_mult = 0.015/atr_pct` clamps at the 2.0 cap for typical 1h ATRs (0.2-0.8%) — vol targeting degenerates to a constant 2x boost. Stale XRP comment ('half the global 0.10') would 3.3x XRP risk if honored verbatim vs RISK_PER_TRADE=0.015.
- Fix: base on the fetched override; normalize ATR horizon (×sqrt(24) or re-baseline); update the stale comment.

### 27. Asymmetric floor/cap erases learned directional edge: 0.50 floor swallows long penalties; MAX_RISK_MULTIPLIER=2.0 env knob never wired (cap stuck at 1.5)
**medium | sizing-wire | OWNER-GATED**
- Evidence: `core/signal_pipeline.py:917` floors the full chain at 0.50 (SOL BUY 0.70 × SOL 0.80 × momentum 0.35 → 0.252 → floored to 0.50); `risk.py:630` caps at constructor-default 1.5 — RiskManager built without `max_risk_multiplier` (`multi_strategy_main.py:826-835`), `trading_config.py:123` read nowhere. Intended ~1:5.6 long:short ratio compressed to ≤1:3.
- Fix: lower floor to ~0.15 or apply learned symbol/side penalties after it; pass `max_risk_multiplier=config.max_risk_multiplier` into RiskManager.

### 28. Win/loss streak data counted three times via three parallel multipliers
**medium | sizing-wire | OWNER-GATED**
- Evidence: AdaptiveSizer heat (`signal_pipeline.py:771-790`) + MomentumTracker (:792-813) into risk_mult, then AdaptiveRiskManager onto qty again (`multi_strategy_main.py:6657-6672`) — all from recent outcomes. Post-loss ~0.30-0.38x effective (floor masks two systems' calibration); post-win boosts compound ~2.1x. Telemetry never matches realized sizing.
- Fix: keep exactly one streak sizer (AdaptiveSizer); delete the other two applications or make mutually exclusive by config.

### 29. LLM-first trades a different signal than the one that passed gating (evaluate_raw re-run diverges from evaluate)
**medium | signal-to-trade | OWNER-GATED**
- Evidence: dispatcher gates on `ensemble.evaluate()` output (`multi_strategy_main.py:5051-5083`), then `_process_symbol_llm_first` discards it and re-runs `evaluate_raw` (:7404), trading its side/entry/sl. evaluate() applies trend-flip (can INVERT side, ensemble.py:728/1550-1595); evaluate_raw never flips, uses min_votes=1, and applies the per-symbol profile filter (877-878) which evaluate() computes but never uses (dead `symbol_active`, :393-397).
- Impact: gated/measured signal ≠ traded signal — poisons attribution of every LLM-first outcome.
- Fix: gate and trade the same object; apply `symbol_active` in evaluate()'s loop so both paths share a voter set.

### 30. Quality multiplier applied twice in ensemble.evaluate() via two SignalQualityScorer instances over the same state file
**medium | signal-to-trade | OWNER-GATED**
- Evidence: two instances wired (`multi_strategy_main.py:667` standalone; `:976` feedback.quality) — evaluate() applies pre-floor adjust_confidence (ensemble.py:556-584) AND post-floor score_signal (786-807), same state → squared effect (0.9 → ~0.81). Standalone instance is frozen at startup (its record path is the dead block, finding 41).
- Fix: one scorer instance for both hooks; second application metadata-only (mirror evaluate_raw at 996-1000).

### 31. Side-vocab clash in quality scoring: LONG/SHORT recorded, BUY/SELL scored — directional learning dimension permanently neutral
**medium | signal-to-trade | OWNER-GATED**
- Evidence: recording passes `event.side` (LONG/SHORT, `multi_strategy_main.py:3698`, `position_manager.py:61`), scoring builds features with Signal side BUY/SELL (`ensemble.py:566/794/991`); `signal_quality.py:229-236` lookups never hit. Smoking gun in `signal_quality.json` by_side: LONG 5/38 (-$729) vs SHORT 27/83 (+$1415) — a huge measured skew scoring provably never reads.
- Fix: `canonicalize_side()` helper at every side write/read (mirror regime_canonical).

### 32. REGIME_MIN_VOTES table is dead config — regime-gated vote requirements never enforced
**medium | signal-to-trade | OWNER-GATED**
- Evidence: `ensemble.py:208-219` never read by production code; `_get_effective_min_votes` (238-249) consults only `data/symbol_strategy_profile` — which doesn't exist in the repo, so even symbol overrides are dead and min_votes is always the flat default 2. Practical exposure: trending_bear (7 allowlisted strategies) trades at 2-agree where backtest intent was 3. Tests assert the constant, not the wiring.
- Fix: `max(symbol_override, REGIME_MIN_VOTES.get(regime, min_votes))` in `_get_effective_min_votes`; wiring test (trending_bear + 2-agree → reject).

### 33. LLM-first open_position omits strategy/setup_type/tp1_close_pct/mode — attribution empty for 100% of active-path trades
**medium | signal-to-trade | AUTONOMOUS**
- Evidence: `multi_strategy_main.py:8017-8035` vs mechanical 7078-7096; Position.strategy defaults '' → regime_feedback (3593), confidence_floor (3602), _llm_triggers (3650), feedback (3695) all get ''; `_regime_strategy_weighter` (3681) fully skipped by its `and event.strategy` guard. (Time stops unaffected — they key off entry_reasons, which LLM-first populates.)
- Fix: add `strategy=raw_signal.strategy or 'ensemble'`, mode, setup_type, tp1_close_pct to the call.

### 34. Exploration skip→go mutation poisons the coordinator's entry-decision cache — mutated GO replays for up to 3 min
**medium | llm-pipeline | OWNER-GATED**
- Evidence: `coordinator.py:1929-1938` caches the SAME mutable EntryDecision it returns; `multi_strategy_main.py:7735-7742` mutates it in place (action='go', exploration qty/lev); cache-hit path (1631-1652) replays it with no skip re-check, bypassing the epsilon roll (7727) and conviction gate — violating the cache's own invariant (coordinator.py:381). Bounded: SafetyFilterChain, OpsGuard, caps, and slippage reject still gate the replay; entries are exploration-sized.
- Fix: cache `dataclasses.replace(entry_decision)` (defensive copy), and/or build a new EntryDecision in the exploration path.

### 35. Structured-debate Critic (Round 1) schema mismatch — 'challenge' verdicts can neither veto nor reduce confidence in the merge
**medium | llm-pipeline | OWNER-GATED**
- Evidence: R1 schema (`prompts.py:442-455`) lacks adjusted_confidence/adjusted_action/counter_thesis_timeframe/falsifiable; `_merge_outputs` requires them (coordinator.py:4787-4793) → challenge branch appends notes only (even logs "confidence reduction only" while reducing nothing); debate can still ADD +0.05 on maintain (4511-4515). Violates `.claude/rules/llm-agents.md` "Critic veto power must always be respected" on exactly the high-stakes trades.
- Fix: add the required fields to the R1 schema, or map R1 fields (confidence_in_assessment + thesis_invalid objections) onto the veto checks.

### 36. Structured debate calls call_llm() directly, bypassing CLI routing — has never run under the subscription setup
**medium | llm-pipeline | OWNER-GATED**
- Evidence: `coordinator.py:4412/4480` use `llm.client.call_llm` (raw API); `client.py:69-71` returns no_client with empty ANTHROPIC_API_KEY (which is the deployed state, USE_CLI_LLM=true) → "Critic Round 1 failed — falling back to simple critic" on every high-stakes trade. Same pattern latent in `decision_engine.py:527`.
- Fix: route R1/rebuttal through `_should_use_cli()` → `_call_llm_via_cli` like `_call_agent`.

### 37. Quant-noise 50% size reduction written to a key nobody reads (trade_out.data['sm'])
**medium | llm-pipeline | OWNER-GATED**
- Evidence: writer at `coordinator.py:1297-1310`; only other 'sm' reader is :1795 which reads the RISK agent's dict; `_merge_outputs` sizes exclusively from risk_out (4683-4690); pipeline_results never updated with the modified trade_out. Probable-noise trades execute at full size; only the note string survives.
- Fix: consume `trade_out.data['sm']` in `_merge_outputs` (multiply into size_mult).

### 38. Invalid LLMDecision constructors: Tier-1 routing skip and budget-exceeded return crash with TypeError
**medium | llm-pipeline | AUTONOMOUS**
- Evidence: `coordinator.py:979-986` and `decision_engine.py:485-486` pass kwargs that don't exist on LLMDecision (`decision_types.py:153-170`; reproduced TypeErrors). Tier-1 skip crashes propagate → monolithic fallback (burning the quota tiering was meant to save); the budget short-circuit is dead code, its failure masked as "Tier routing failed" (:494-495). Dormant (flags off) — fixing changes nothing live.
- Fix: valid constructors (`strategy_weights=StrategyWeights(), memory_update=None, notes=...`); decision_engine should return DecisionResult.

### 39. CLI adapter forces every agent timeout to >=300s, nullifying per-agent timeouts and the 90s Sonnet→Haiku fallback
**medium | llm-pipeline | AUTONOMOUS**
- Evidence: `coordinator.py:152-157` `timeout=max(timeout, 300)` overrides config.timeout_s (TRADE/CRITIC 60s, REGIME 30s, SCALPER 3s); the ">90s" fallback (1109-1118) can't fire before 300s on a hang; `_SONNET_SEMAPHORE=2` (:119) means hung sessions stall parallel symbols; no outer watchdog. Stale decisions then die at the slippage reject (7888-7895).
- Fix: respect caller timeout (floor at ~120s max, or only floor Haiku calls).

### 40. Exploration records LLM pipeline failures and forced trades as llm_agreed=true GO — poisons LLM-accuracy learning splits
**medium | sizing-wire | AUTONOMOUS**
- Evidence: LLM-first entry hardcodes llm_action="go"/llm_agreed=True (`multi_strategy_main.py:7967-7968`) for every executed trade incl. exploration-flipped skips; candidate path (:6583) treats ""/"no_llm"/None as agreement. trades.csv confirms: exploration rows whose thesis is an explicit LLM SKIP rationale recorded llm_agreed=true. Consumers: meta_learning llm_agreed splits (846-877), signal_quality agreement buckets. Nearly all recent trades are exploration → measured "LLM accuracy" is actually forced anti-LLM trades.
- Fix: `llm_agreed=False`, `llm_action="exploration_override"` on EXPLORATION/pipeline-failure entries; :6583 counts only ("proceed","go"). Also find the open path writing empty entry_reasons/conf=0 (3 recent rows).

### 41. Close-path learning block (signal_quality/parameter_tuner/continuous_backtest) is 100% dead — three signature-mismatched calls swallowed at debug
**medium | close-to-learning | AUTONOMOUS**
- Evidence: `multi_strategy_main.py:3614-3641` — `signal_quality.record_outcome(features_key=...)` TypeError (real sig: features, `signal_quality.py:113-118`); `parameter_tuner.record_outcome` doesn't exist (only record_trade_outcome); continuous_backtest kwargs don't match; all swallowed by `logger.debug` at 3642-3643, first failure aborts the rest. NOT a learning loss — the duplicate FeedbackLoop path at 3668-3709 records all three correctly. But: split-brain instances over the same data/feedback files, and the standalone scorer wired into the ensemble stays startup-stale intra-session.
- Fix: delete the dead block, route everything through `self.feedback` (single instances); elevate the except to warning.

### 42. BOOST/PENALIZE confidence deltas applied 2-3x to one signal (ensemble → pipeline gate → coordinator merge), accuracy credited once
**medium | close-to-learning | OWNER-GATED**
- Evidence: same GraduatedRulesEngine mutates confidence at `ensemble.py:595-620`, again at `signal_pipeline.py:450-483` (re-evaluating the already-adjusted value, despite the "advisory" comment at :443), again at `coordinator.py:4918-4950`. veto_only dedupes counters but not conf deltas. A -15 rule → -30/-45; silent-gate conversions of marginal passes. Pre-filter (1680-1684) also omits regime — regime vetoes can't fire there.
- Fix: apply conf adjustment at exactly one layer; others report delta as metadata; stamp `graduated_rules_adj_applied`.

### 43. predicted_ev / realized_rr / win silently dropped by trade_ledger schema; realized_rr would be 0 anyway (pos.qty zeroed pre-calc)
**medium | close-to-learning | AUTONOMOUS**
- Evidence: `multi_strategy_main.py:3808-3810` passes them; `trade_ledger.py:114-116` copies only LEDGER_COLUMNS keys (28-53 — none present), no warning. Guard at :3781 checks `pos.qty` after `_close_position` zeroed it (position_manager.py:1401) → rr always 0; same zeroed-qty at 4087-4089 → survival funding_cost always $0.
- Impact: the predicted-EV vs realized-RR calibration data (the Quant Brain audit Nunu wants) has never landed in the ledger.
- Fix: add the three columns; compute from `event.qty`/`pos.original_qty`/metadata total_fees; warn on unknown keys in record_trade.

### 44. MFE force-closes flip state to CLOSED before exchange fill confirmation and ignore the order result
**medium | close-to-learning | OWNER-GATED**
- Evidence: `multi_strategy_main.py:3453-3468` — force_close FIRST, then close_position with return unchecked, and `_exchange_submitted=True` set unconditionally (bypassing the failed-close safety net at 3513-3529). Siblings (liq 3369-3376, funding 3418-3425) do submit-then-confirm correctly. Latent in paper (fills always succeed); live: fabricated close + unmanaged exchange position until reconciliation.
- Fix: reorder to submit → confirm filled → force_close, matching 3418-3425.

### 45. Funding-rate units clash: Hyperliquid HOURLY funding treated as PER-8H inside Quant Brain — thresholds ~8x too strict
**medium | data-plumbing | OWNER-GATED**
- Evidence: `fetcher.py:990-1013` returns hourly HL rate (docstring wrongly says 8h); collector/external_data annualize as hourly (×24×365); `quant_brain.py:650/939-966/1264` use 8h-calibrated bands (0.0005 = "extreme" = ~438%/yr hourly — never occurs) and `daily_cost = abs_fr*3` (understates 8x).
- Impact: overleveraged-regime detection, funding confluence (±1..2), and the extreme-funding critic haircut are near-dead wires; funding cost misreported.
- Fix: standardize hourly — divide QB thresholds by 8 (or convert to 8h at ingestion); daily cost = abs_fr*24*100; fix the docstring.

### 46. Graduated-rule live-accuracy recompute can never score strategy-conditioned rules (trades.csv strategy empty, primary_driver always 'ensemble')
**medium | data-plumbing | OWNER-GATED**
- Evidence: `prompt_enricher.py:92-94` matches against primary_driver/strategy; LLM_FIRST rows hardcode primary_driver='ensemble' (`multi_strategy_main.py:7987`), strategy column empty in 85/89 rows; real strategies live only in the unparsed entry_reasons JSON. 14/49 rules are strategy-conditioned → n permanently <5; the acc<0.40 kill-switch (:174) can never fire.
- Fix: parse entry_reasons strategies_agree in `_trade_matches_conditions`, or write the winning strategy into trades.csv at close.

### 47. Deep-memory 'SIDE EDGE' prompt section can never render: looks up {symbol}_BUY/_SELL but fingerprints store _LONG/_SHORT
**medium | data-plumbing | OWNER-GATED**
- Evidence: `deep_memory.py:907-909` vs writer at :368 fed `pos.side` (LONG/SHORT via analytics.py:238); verified strategy_fingerprints.json has zero _BUY/_SELL keys. Four symbols would render strong asymmetries today (ETH LONG 0% n=8 vs SHORT 41% n=22; SOL 14% vs 35%) — the bot's strongest documented asymmetry signal never reaches any prompt.
- Fix: normalize LONG→BUY / SHORT→SELL at the fingerprint seam (or try both vocabs at lookup).

### 48. Absent collectors misrepresented as market conditions; funding staleness threshold 8x collection cadence, no age tag
**medium | data-plumbing | OWNER-GATED**
- Evidence: `data/liquidation_levels.jsonl` and `shadow_mr_signals.jsonl` DO NOT EXIST, yet `external_data.py:538` emits "MR_SHADOW: 0 signals (no extremes)" (live right now); LIQ line silently vanishes (:314-331). Funding accepted up to 2h old as current (:117-125) vs 15-min collector cadence, no STALE marker.
- Impact: agents can't distinguish "pipeline down" from "nothing happening" — prompts assert calm exactly when collectors crash during volatility.
- Fix: explicit sentinels ("COLLECTOR OFFLINE"); age tag + STALE marker on FUNDING; schedule the trackers alongside the bot.

---

## LOW

### 49. Trade Agent never emits 'side' — thesis metadata always BUY; critic-fallback counter-trend gate is dead code
**low | llm-pipeline | OWNER-GATED**
- `prompts.py:127` schema has no side; `coordinator.py:1495` defaults 'BUY', :1553-1555 always "", :1191-1195 `_fb_counter_trend` provably always False. Refuted sub-claims: thesis outcomes are pnl-scored (side-aware), calibration_ledger has no side usage — live loops unaffected. Residual: one dead fallback safety branch + wrong side metadata in thesis/performance records.
- Fix: populate side from signal_ctx at record time.

### 50. Mechanical overrides (critic-fallback, consistency, quant-noise) recorded as the Trade Agent's own decisions
**low | llm-pipeline | AUTONOMOUS**
- `coordinator.py:1199-1213/1244-1251/1290-1296` replace trade_out before `record_agent_decision` (:1330-1342); pipeline_results keeps the original — inconsistent views. Refuted sub-claim: calibration ledger is fed from the ORIGINAL output and skips open no trade; the mislabeled store (agent_brain) is currently unread. Latent risk if outcome path is wired.
- Fix: record before the override cascade (or record the original, carry overrides separately).

### 51. LLM_EXIT_ENGINE full closes: TradeEvent discarded, action missing from _FULL_CLOSE — currently latent (no rule emits 'close')
**low | exit-wire | OWNER-GATED**
- `position_wiring.py:1010` discards force_close's event; LLM_EXIT_ENGINE absent from `_close_actions`/`_FULL_CLOSE`. Heuristic rules only emit tighten/widen/partial today, so zero trades flow through — defensive fix.
- Fix: mirror the patched LLM_EXIT_AGENT pattern (816-823) + add to _FULL_CLOSE.

### 52. AdaptiveConfidenceFloor: two instances each record every close, clobbering the same state file
**low | signal-to-trade | OWNER-GATED**
- `multi_strategy_main.py:3598-3605` (standalone) + `loop.py:229-236` (feedback), both over data/feedback, both gating entries (:2060, :5456). NOT 2x n-inflation (separate in-memory instances) — but nondeterministic persisted state and two divergent floors fed different confidence/regime values.
- Fix: one instance (alias `self.confidence_floor = self.feedback.confidence`); same dedupe for tuner/quality/backtester.

### 53. Confidence-floor bypasses overwrite risk_mult_override instead of combining — 4h-regime penalty lost
**low | signal-to-trade | OWNER-GATED**
- `ensemble.py:545` multiplies (×0.7); bypasses at :698/:710 ASSIGN 0.65/0.70, clobbering it. Double-flagged marginal trades size ~43% larger than the stacked reductions intend. Every other writer combines defensively.
- Fix: `metadata.get('risk_mult_override', 1.0) * 0.65` (or min()).

### 54. Override-agent volume_ratio hardcoded by broken dir() check; close-path confidence fallback mixes 0-1 and 0-100 scales
**low | signal-to-trade | AUTONOMOUS**
- `ensemble.py:2487` `'_vol_ratio' in dir()` always False inside `_SigLike.__init__` → OverrideAgent always sees volume_ratio=1.0. `multi_strategy_main.py:3586` falls back to 0-1-scale llm_confidence/win_prob_deflated feeding 0-100 binned recorders (records dropped from bins, calibration_errors skewed). Latent.
- Fix: thread real volume ratio; ×100 the fallbacks (mirror position_manager.py:412).

### 55. CLI route zeroes all token/cost accounting — budget gates and /cost-audit blind on the production path
**low | llm-pipeline | AUTONOMOUS**
- `coordinator.py:161-178` returns input/output_tokens=0 on all paths; cost_usd produced but never consumed; client.py's cost tracker bypassed entirely under USE_CLI_LLM=true. Quota-burn visibility (the thing that took the bot down in June) is blind.
- Fix: record `resp.cost_usd` into cost_tracker with a CLI pseudo-model; surface CLI envelope usage fields.

### 56. Regime cache stores a mutable AgentOutput that the technical fallback mutates in place — cached for 30 min, shared across threads
**low | llm-pipeline | OWNER-GATED**
- `coordinator.py:919-924` caches; :944-951 mutates the cached dict (rg, factors, conf>=0.5) → cache hits serve the fallback as the LLM's classification (lr_regime distorted ~0.85→0.95). `_cache_lock` guards lookup, not the object.
- Fix: cache a deep copy; apply fallback to a fresh AgentOutput.

### 57. decision_engine: multi-agent success marker overwritten — with LLM_ENSEMBLE_ENABLED the multi-agent decision would be discarded and double-billed
**low | llm-pipeline | AUTONOMOUS**
- `decision_engine.py:451` dead store; :498-503 unconditionally recomputes `_ensemble_enabled`; ensemble block replaces `decision` at :547. Doubly env-gated (flags unset) — dormant.
- Fix: AND the recompute with `not _multi_agent_active`.

### 58. Stop-width leverage caps (tight-stop liquidation guard) are dead code; unknown symbols get max-tier Kelly leverage by dict-miss
**low | sizing-wire | OWNER-GATED**
- `signal_pipeline.py:698-709` caps at 8-20x but decide() maxes at 7.0 (`leverage.py:117-133,176`) — unreachable. `_SCALP_KELLY_LEV.get(sym, 7.0)` (:124) gives new symbols BTC-grade leverage. If the caps ever bound, the leverage-divisor inversion (finding 8) would ENLARGE the position.
- Fix: conservative fallback (min tier / 3.0 for n<10 symbols); re-derive or delete the caps after fixing the qty formula.

### 59. TP1 partial-close unconditionally overwrites pos.sl and can widen it (never-widen violation) — restored in the same tick, so no live exposure at current config
**low | exit-wire | OWNER-GATED**
- `position_manager.py:1180-1189` sets SL without protective-direction clamp (SCALP: ~4.5 ATR below entry); trailing floor restores it within the same update() call and the SL check runs before TP1 handling — no window with ENABLE_TRAILING_STOP=true (current). Persistent only if trailing disabled.
- Fix: one-line protective clamp (`max`/`min` vs current SL).

### 60. Measurement: get_trade_summary drops LLM/TIME_STOP/TP1_FULL closes; trailing WINs logged as SL_HIT; safety-gated exits skip mark_evaluated
**low | exit-wire | AUTONOMOUS**
- `position_manager.py:1722-1725` whitelist omits whole close categories (TP1_FULL = pure wins → WR biased down); :1554-1555 TRAILING_STOP→SL_HIT unconditionally; `exit_engine.py:76-77` returns before mark_evaluated → gated symbols re-evaluated every cycle. Consumers are backtest/replay summaries + event-type analytics.
- Fix: one shared CLOSE_ACTIONS constant; pnl-aware telemetry type; mark_evaluated in the gated return.

### 61. Funding costs deducted from learning PnL but never from equity
**low | exit-wire | OWNER-GATED**
- `multi_strategy_main.py:3531` uses `event.pnl - event.fee` (gross); funding only inside pos.realized_pnl (position_manager.py:1170/1400) → equity over-credits by cumulative funding; same trade can be equity-win/learning-loss near breakeven. Cents-per-trade magnitude.
- Fix: `update_equity(event.pnl - event.fee - event.metadata['funding_costs'])`.

### 62. record_veto_overridden is dead code — LLM_FIRST veto overrides never scored, times_overridden always 0
**low | close-to-learning | AUTONOMOUS**
- `graduated_rules.py:465-485` zero callers; override counterfactuals recorded without veto_rule_ids (`ensemble.py:606-612`) so resolution never routes back to the rule. "Was the LLM right to override?" audit trail structurally empty.
- Fix: stamp `overridden_rule_ids` on the counterfactual; call record_veto_overridden at resolution.

### 63. Quant Brain dead wires: vol-regime confluence unreachable, RSI>75 note overwritten, skip reason reports a fictional 48% floor
**low | data-plumbing | OWNER-GATED**
- `quant_brain.py:795` vol_adj=0.0 unconditionally vs branches at :897-902 needing ±0.06/0.08 (unreachable); :785-786 dead assignment loses the informative RSI note; :988-997 skips at wp<0.10 but the logged reason claims "< 48% floor" — wrong threshold fed to rejection forensics.
- Fix: delete/re-derive the vol branch; remove the duplicate rsi_note; interpolate the real 0.10 threshold.

### 64. CWD-relative data paths in prompt_enricher, deep_memory, quant_brain — enrichment silently empties if launched from any other directory
**low | data-plumbing | AUTONOMOUS**
- `prompt_enricher.py:31`, `deep_memory.py:30`, `quant_brain.py:1306` all CWD-relative; `_load_json_safe` returns {} silently. One Task-Scheduler "Start in" change strips the entire QUANT INTELLIGENCE BRIEFING with no error. Currently benign.
- Fix: anchor to `Path(__file__)` like dynamic_stats.py:24; WARNING on first missing critical file.

---

## Fix tonight (AUTONOMOUS — pure measurement/logging, no trading-behavior change)

1. **#17** exit_price: use `event.price` at multi_strategy_main.py:3970 and :3914 (unbreaks regime calibration + reflection). One line each.
2. **#19** regime fallback: populate regime from market_context/ledger classifier in the coordinator skip EntryDecisions and the entry_reasons write.
3. **#18** pass `strategy=event.strategy` (+setup_type) through graduated `record_outcome` → matches().
4. **#33** add strategy/mode/setup_type/tp1_close_pct to LLM-first `open_position` call (8017).
5. **#40 + #7 labeling half** `llm_agreed=False` / `llm_action="exploration_override"` on EXPLORATION entries; log pipeline failures as `stage='pipeline_error'`, stop record_veto on them; :6583 counts only ("proceed","go").
6. **#41** delete the dead learning block at 3614-3641; single feedback instances; except → warning.
7. **#43** add predicted_ev/realized_rr/win to LEDGER_COLUMNS; compute from event.qty/original_qty; fix the zeroed-qty funding calc at 4087-4089.
8. **#38** fix the two invalid LLMDecision constructors.
9. **#39** respect caller timeout in `_call_llm_via_cli`.
10. **#50** record_agent_decision before the override cascade.
11. **#54** volume_ratio thread-through + ×100 confidence fallbacks.
12. **#55** record CLI cost_usd into cost_tracker.
13. **#57** guard ensemble recompute with `not _multi_agent_active`.
14. **#60** shared CLOSE_ACTIONS constant; pnl-aware TRAILING telemetry; mark_evaluated on gated return.
15. **#62** wire record_veto_overridden via overridden_rule_ids.
16. **#64** anchor data paths to `__file__`; warn on missing critical files.

## Owner decisions needed (OWNER-GATED — change trading behavior; backtest + adversarial review before shipping)

1. **Execution integrity (do first):** #1 LLM-first exchange submission; #2 partial-close accounting via shared `partial_close()`; #3 LIQUIDATION_AVOID event injection; #15 HOLD_LIMIT exchange submission; #44 MFE submit-then-confirm ordering. These are correctness fixes, low judgment — recommend approving as a batch.
2. **Sizing convention:** #8 pick one qty formula (delete the leverage divisor) — MUST ship with a risk_per_trade re-tune + backtest; then re-derive #58's caps. Related clamps: #9 risk_pct clamp + config fallback; #25 CB single application; #27 floor/cap; #28 one streak sizer; #26 per-symbol override + ATR horizon; #12 time-sizing dedupe+normalize.
3. **Exploration:** #6 route through risk_mgr.calculate_qty + restore MIN_STOP_WIDTH_PCT=0.005; #7 exclude pipeline failures from exploration; #34 cache defensive copy.
4. **Exit asymmetry (biggest PnL lever):** #4/#5 pre-TP1 ratchet + post-TP1 floor redesign — one owner decision on who owns pos.sl and where protection starts; #23/#24 exit-agent gate honesty + fee-buffered is_profitable.
5. **Signal/LLM plumbing:** #11 risk_mult_override propagation; #13 Gate 1f/1g hydration; #14 flip side_override; #10 size_multiplier wiring; #29 gate-and-trade the same signal; #30/#31 single quality scorer + side canonicalization; #32 REGIME_MIN_VOTES; #35/#36/#37 critic/debate/sm wiring; #42 single-layer rule adjustment.
6. **Learning integrity:** #16 veto-retire scoring redesign (PnL-weighted, reactivation); #20/#21/#22 Quant Brain setup_key + strategy WR + TTL refresh; #45 funding units; #46/#47/#48 prompt-data fixes; #61 funding in equity.

## Refuted (verified false — do not re-chase)

- **Exploration safety premise unwired / risk = 1/leverage of configured** — qty=risk/(stop*lev) is the codebase-wide convention with leverage-multiplied PnL, loss-at-stop = risk_usd exactly; TOXIC hard block at 7583-7612 + unified exploration toxic gate DO enforce learned vetoes on the LLM-first path; epsilon is 0.12 not 0.40.
- **LLM size multiplier leaks into ADVISORY/VETO_ONLY modes** — upstream gates block it: llm_size_mult stays 1.0 in ADVISORY; `_apply_mode_constraints` forces 1.0 in VETO_ONLY; the None→TypeError path is unreachable.
- **Inconsistent notional definitions between paths** — mechanical path applies the identical qty*entry*leverage caps (6755/6768/6780-6788); only risk.py's internal sanity cap mislabels margin, affecting both paths equally.
- **Critic calibration confidence inverted (1.0 - critic_conf)** — critic_conf is confidence IN the trade; the ledger proposition is "trade was bad", so 1.0-conf is the correct polarity.
