# Server audit: hard-coded rules on the live path (2026-10-13, Opus agent, read-only)

Headline: the rules that should LEARN have stopped updating. Window bot_20261011.log (~37h): ONE signal reached the
LLM entry pipeline; the approved NEAR long was cut 114.85 -> 11.49 -> 2.85 qty (~$17, ~$0.60 risk) by three penalties
built on the same July evidence (long block outside trending_bull + 0.1x probe + 0.25x side multiplier). The
"living" gates read the whole ledger through a $0.50-fee dust filter, so every probe since 07-27 (17 longs, 6 wins,
-$6.31) is ignored; long-gate evidence last moved 2026-07-23. EXPLORATION_MODE=true never runs: multi_strategy_main.py
~:8767 references removed `_setup`, exception swallowed at debug (:8873); 0 EXPLORATION lines.

Rules (file:lines, flag, evidence, fires/37h):
1 IC mute - feedback/ic_tracker.py:36-39,167-195; drop strategies/ensemble.py:2481 - last-30 IC < 0 => weight 0 - KEEP
  verdict 10-09 (-0.52%), confidence_scorer untestable - 765 drops
2 Solo gate - core/entry_selectivity.py:254-297; msm 8925-9042 - ENTRY_SELECTIVITY - n=32 old - 0
3 Long block outside trending_bull - entry_selectivity.py:364-396,535-545 - LONG_REGIME_VETO, UPTREND_REGIMES - n=22
  June; LONG_SIDE says one-month artifact - 1
4 Probe valve - msm 8979-9070 - rate 0.5 (cap), 0.1x - 1
5 Side size mult - feedback/live_edge.py:179-183 - 1+avg$/20 clipped 0.25-1.5 - same July data - 1
6 Dust filter - live_edge.py:63, entry_selectivity.py:66 - fees < $0.50 ignored - set 07-24 when notional ~$278
7 Risk cap 0.5% - coordinator.py:4340 - PROMPT-ONLY, not enforced in code - 193
8 Fallback risk 10% x size mult if Risk Agent omits risk - coordinator.py:2024
9 Post-AI caps (notional 15x, portfolio 7x, OpsGuard 500%, min $11.50) - msm 9081-9124 - leverage-unit mismatch
10 Profit lock 0.3R -> BE+fees+0.1%, 0.6R -> +0.3R - position_manager.py:1091-1124,1203-1219 - 07-02 in-sample n=90;
   conflicts with refuted BE ratchet + GEOMETRY_V3; with 50 bps fill slip a "BE" lock books a loss (NEAR +0.35R -> -0.2R)
11 SL fill slip up to 50 bps - position_manager.py:465-468
12 Exit-agent keyword close rules 0.60/0.80/0.90 - llm/exit_engine.py:181-235 - 10 blocked
13 2h min exit hold - core/position_wiring.py:714-725 - 10
14 Time stop hands to exit agent; real close only at 1.5x max hold - position_manager.py:1250-1324
15 Regime stickiness >60% - strategies/regime_detector.py:26 - ~590 (367 held high_volatility vs trend)
16 Trigger-path living conf floor (P90 ~0.38) - llm/risk_gating.py:86-160 - 52 rejections, likely no effect in LLM-first
17 Per-symbol -$30/day, 2 per risk tier - msm 950,959

Conflicts: one July evidence base -> three stacked penalties (0.025x); profit lock vs refuted BE ratchet; LLM approves
then regime gate blocks on a sticky high_volatility label; time stop -> exit agent -> 0.80 floor -> nothing until 1.5x;
cap unit mismatch; trigger-path floor without effect.
Stale: $0.50 dust filter; $20 / -$30 dollar scales vs cent-sized trades; LIVE_EDGE_WINDOW_DAYS=0 (whole ledger, era
confound); exploration dead.
Ranked conversions (shadow-first): 1 scale-free evidence (R or PnL/notional) so probes count; 2 windowed, R-unit long
block with the LLM's regime source; 3 collapse stacked size penalties into one, enforce the 0.5% cap in code; 4 IC mute
only when IC significantly < 0; 5 profit lock (shadow + candle replay with placebo); 6 structured exit reason codes;
7 fix or remove exploration. Circuit breakers / daily loss limits untouched.
