# TOTAL DATA CENSUS — every artifact the WAGMI system has ever written
Date: 2026-07-01 | Scope: full repo walk (bot/data recursive + bot/logs, bot/ml_data, bot/llm/data, api/, web/, historical/, root archives) | ~937 MB total on disk.
Method: file inventory (size/mtime/record counts/first-last timestamps) cross-referenced against a full grep of every filename stem through bot/, scripts/, tasks/, api/ code.

Status legend: **LIVE** = written + read recently · **WRITE-ONLY** = actively written, no runtime consumer (offline/research reads at best) · **STALE(date)** = writer silent since date · **ORPHAN** = no writer in current code · **CONFIG** = config/state, not a data stream.

## 1. FULL CENSUS TABLE

### 1a. Core ledgers & root state (bot/data/)
| Artifact | What | Size / Records | Span | Writer | Reader | Status | Knowledge value |
|---|---|---|---|---|---|---|---|
| trade_ledger.csv | Canonical honest per-trade ledger | 22KB / 157 rows | →2026-07-01 | feedback/trade_ledger.py (via multi_strategy_main) | dynamic_stats, regime_priors, memory_seeder, quick_status, research tools, autonomous_learning_loop | LIVE | THE ground truth: WR/EV/regime/side tables |
| trades.csv | Legacy per-trade CSV (parallel ledger) | 90KB / 91 rows | →2026-07-01 | multi_strategy_main (csv_logger path) | ensemble, alpha_feed, cli | LIVE (redundant) | Disagrees with trade_ledger (91 vs 157) — era reconciliation |
| trade_events.jsonl | Structured event stream (every open/close/adjust) | 22.7MB / 63,528 | 05-30→07-01 | core/structured_logging.py | dashboard/server, backtest signal_extractor, exit-geometry BT, overnight_report | LIVE | Event-level replay of everything the bot did |
| shadow_ledger.csv | What-if ledger of unfiltered ensemble signals | 875KB / 8,715 | →07-01 | feedback/shadow_ledger.py | premium_filter, ensemble, multi_path_compare | LIVE | Filter cost: live vs shadow divergence |
| analysis/trade_outcomes.csv | Post-fix "honest window" outcome rows (reset 06-24) | 24KB / 25 rows | 06-24→07-01 | data/learning.py (via multi_strategy_main:4345) | analyze_backtest, telegram_bot | LIVE | The first trustworthy sample (agenda Q1) |
| analysis/performance.json + trade_candidates.csv + bt harness .py/.csv/.json | Research-harness outputs (veto replay, exploration gate, no-early-exit BT) | ~90KB | 06-23→07-01 | analysis harnesses in same dir | one-shot reads by their authors | WRITE-ONLY (research artifacts) | Already-computed veto/exit experiments |
| position_state.json | Open-position state machine | 2KB | 07-01 | execution/position_manager.py, auto_recovery | reconciliation, exit_engine, watchdog, api_server, gen_state | LIVE | none (operational) |
| position_backups/{ETH,XRP}.json | Per-symbol position crash backups | 0.6KB | 07-01 | position_manager | position_manager (recovery) | LIVE | none |
| risk_equity_state.json | Equity + risk budget state | 103B | 07-01 | execution/risk.py | multi_strategy_main, api_server | LIVE | none |
| circuit_breaker_state.json | CB trip/cooldown state | 200B | 07-01 | multi_strategy_main, reconciliation | quick_status, preflight, prompt_enricher | LIVE | CB trip history |
| heartbeat.json / bot_heartbeat.txt | Liveness (python loop / ps1 supervisor) | <1KB | 07-01 | multi_strategy_main daemon; bot_alive.ps1 | watchdog.py; bot_status.ps1 | LIVE | uptime forensics |
| funding_oi_history.jsonl | Funding + OI snapshots | 336KB / 1,569 | 06-06→07-01 **HOLE 06-07→06-29** | tools/funding_oi_collector.py + multi_strategy_main | external_data (agent prompts), liquidation_tracker, exit-geometry BT | LIVE (fragile) | Crowding/funding regime studies (agenda Q8) |
| market_depth_history.jsonl | Microstructure expansion (agenda Q28): HL L2 spread/mid + depth 0.1/0.5/1% bands + imbalance, trade-tape aggregates, futures ctx (funding/basis/L-S ratio/taker ratio; Binance geo-blocked 451 on this host → OKX fallback, incl. HYPE) | new 07-01, ~2.3KB/run (5 rows/15min) | 07-01→ | tools/market_collector.py (ISOLATED — own task "WAGMI-MarketCollector", zero bot-runtime contact) | none yet / research | LIVE | ★ can't be backfilled — every uncollected day lost; depth/imbalance vs entry EV, spread-regime gating |
| momentum_state.json | Cross-symbol momentum tracker state | 128B | 07-01 | execution/momentum_tracker.py | alpha_feed, intel_collector | LIVE | none |
| regime_predictions.json | Regime detector output | 491B | 07-01 | tools/regime_detector.py | manual/anticipatory_entries.py | LIVE | regime label accuracy (agenda Q10) |
| kelly_weights.json | Factor Kelly weights | 549B | **frozen 06-06** | feedback/kelly_engine.py | dynamic_stats, feedback_state → **agent prompts** | STALE(06-06) | ⚠ stale stats still injected into prompts |
| ic_history.json | Information-coefficient tracker | 243B | **frozen 06-06** | feedback/ic_tracker.py | feedback_state | STALE(06-06) | factor IC history (dead) |
| execution_analytics.csv | Fill/slippage records | 921B / 9 rows | **frozen 06-06** | execution/execution_analytics.py | multi_strategy_main (slippage summary) | STALE(06-06) | slippage/fee drag (agenda Q17) — starved |
| ev_calibrator_state.json | EV calibration state | 203B | 06-23 | feedback/ev_calibrator.py | feedback_state (prompts) | STALE(06-23) | EV calibration curve |
| alert_state.json | Alert router dedup state | 210B | 06-06 | alerts/router.py | alerts/router.py | STALE(06-06) | none |
| quant_brain_overrides.json | Manual mutes for Quant Brain stats | 402B | 06-07 | hand-edited | llm/quant_brain.py | CONFIG | record of what was muted & why |
| ab_tests/ | empty dir | 0 | — | none | none | ORPHAN | none |
| *.bak / *.backup / .corrupt files (12 across tree) | Purge/scrub-era snapshots (06-05..06-23) | ~1.5MB | frozen | one-off scripts | nothing | ORPHAN | pre-purge memory forensics (llm_memory 15KB vs 224B live; graduated_rules 20.6KB vs 629B live) |
| missed_opportunities_20260530.md, session_journal_2026-05-30.md | One-off session notes | 22KB | 05-30 | one-off | nothing | ORPHAN | restart-day context |
| db.py, fetcher.py, learning.py, ml_log.py, risk_log.py, trade_log.py, price_store.py, strategy_weights.py, migrations.py, storage/, fetchers/ | **code**, not data (lives inside data/) | ~130KB | — | — | — | CODE | — |

### 1b. Feedback & learning state (bot/data/feedback/, learning/, meta_learning/, rl/)
| Artifact | What | Size / Records | Span | Writer | Reader | Status | Knowledge value |
|---|---|---|---|---|---|---|---|
| feedback/backtest_state.json | Continuous-backtest engine state | 44KB | 07-01 | feedback/continuous_backtest.py | same | LIVE | rolling backtest verdicts |
| feedback/confidence_state.json | Adaptive confidence floors | 4.8KB | 07-01 | feedback/adaptive_confidence.py | dynamic_stats, prompt_enricher | LIVE | confidence-floor evolution |
| feedback/signal_quality.json | Per-signal quality scores | 16KB | 07-01 | feedback/signal_quality.py | deployment_gate, dashboard, evolution_tracker | LIVE | which signals earned trust |
| feedback/hold_time_rules_state.json | Learned hold-time rules | 6KB | 07-01 | feedback/hold_time_rules.py | position_manager | LIVE | hold-time edge (agenda Q12) |
| feedback/regime_feedback_state.json | Regime-level feedback | 5KB | 07-01 | feedback/regime_feedback.py | same | LIVE | per-regime P&L feedback |
| feedback/adaptive_risk_state.json / adaptive_sizer_state.json | Adaptive risk/sizing state | 1.4KB | 07-01 | execution/adaptive_risk.py | dynamic_stats, prompt_enricher | LIVE | sizing adaptation trace |
| feedback/tuner_state.json | Parameter tuner state | 361B | 07-01 | feedback/parameter_tuner.py | comprehensive_snapshot | LIVE | param drift |
| feedback/auto_optimizer_state.json + _log.jsonl | Auto-optimizer runs | 11KB / 20 log rows | 06-27→06-28 | feedback/auto_optimizer.py | continuous_audit | STALE(06-28) | what the optimizer changed |
| learning/auto_fix_state.json | Auto-fix pipeline state | 3.9KB | 07-01 | learning/auto_fix_pipeline.py | same | LIVE | self-repair log |
| learning/master_engine_state.json, execution_forensics.json, live_edge_data.json | Master learning engine + forensics | 12.8KB | **frozen 06-05** | learning/master_engine.py, execution_forensics.py | live_prompt_injection, daily_synthesis | STALE(06-05) | ⚠ tick() is wired in main loop but state never updates — silent failure |
| meta_learning/{ideas,insights,tick_state}.json | Meta-learning engine | 21KB | 06-29 | analytics/meta_learning.py | same | STALE-ish(06-29) | machine-generated improvement ideas, unread |
| rl/rl_policy.json | Offline-trained RL sizing policy | 490B | 06-27 | rl/train_offline.py, run.py | rl/apply_policy.py (runtime multiplier) | LIVE (slow retrain) | does RL multiplier help? |
| rl/transitions.jsonl | RL state-action-reward transitions | 52KB / 124 | 05-31→07-01 | rl/buffer.py | train_offline | LIVE | per-trade reward shaping data |

### 1c. LLM brain stores (bot/data/llm/)
| Artifact | What | Size / Records | Span | Writer | Reader | Status | Knowledge value |
|---|---|---|---|---|---|---|---|
| decisions.jsonl | Final LLM decision log | 15.8MB / 3,236 | 05-31→07-01 | llm/decision_engine.py, joiner, autonomy_router | replay_engine, self_performance, pnl_reconcile, dashboard, api_server | LIVE | decision→outcome attribution |
| agent_performance.jsonl (+ .json) | Every agent call w/ role, confidence, decision | 11.9MB / 24,291 | 05-31→07-01 | llm/agents/performance_tracker.py | api_server agent-health, coordinator | LIVE | per-agent skill/calibration (barely mined) |
| counterfactual_resolved.jsonl | Resolved skip counterfactuals (what price did after we skipped) | 24.8MB / 39,137 | 05-30→07-01 | llm/counterfactual_learner.py + tools/counterfactual_resolver.py | manual/* research, bt_signal_sources, veto_rescore, multilayer_sim | LIVE | ★ the gold mine (agenda Q14) |
| counterfactual_pending.jsonl | Unresolved skip queue | 355KB / 603 | 07-01 only | counterfactual_learner | resolver | LIVE | none (queue) |
| bot_perception/percepts.jsonl | Self-perception quality percepts, 1/cycle | **55.8MB / 440,468** | 05-31→07-01 | llm/bot_perception_aggregator.py | perception analyzer/report only (in-memory reload) | WRITE-ONLY | ⚠ sampled records all have quality/consistency/gap = 0.0 — 56MB of zeros |
| thesis_history.jsonl | Every trade thesis + grade | 168KB / 279 | 05-31→07-01 | llm/thesis_tracker.py | rq15_thesis_forensics | LIVE | thesis-language forensics (agenda Q15) |
| deep_memory/insight_journal.json | Distilled insights journal | 222KB | 07-01 | llm/deep_memory.py, deep_trade_analyst | prompt_enricher, coordinator, memory_seeder, dashboard | LIVE | what the bot believes it learned |
| deep_memory/trade_dna.json | Per-setup DNA (WR by symbol/side/regime) | 131KB | 07-01 | llm/deep_memory.py | 25+ modules incl. prompts, quant_brain, ensemble | LIVE | most-read knowledge store in the system |
| deep_memory/strategy_fingerprints.json | Strategy fingerprints | 27KB | 07-01 | deep_memory.py | prompt_enricher, snapshot_builder, dashboard | LIVE | strategy-level memory |
| graduated_rules.json | Rules graduated from evidence (vetoes etc.) | **629B** (backup 06-19: 20.6KB) | 07-01 | llm/graduated_rules.py + hypothesis_tracker + orchestrator + counterfactual_learner + auto_fix_pipeline + master_engine | signal_pipeline, position_wiring, ensemble, prompts, swarm_master | LIVE | ⚠ multi-writer clobber class; cleared 06-29 by design but 6 writers remain |
| growth/hypotheses.json | Auto-generated hypotheses + evidence | 946KB | 07-01 | llm/growth/hypothesis_tracker.py | prompt_enricher, orchestrator | LIVE | hypothesis graveyard: what was tested/abandoned |
| growth/veto_tracker.json | Every veto + counterfactual outcome | 826KB | 07-01 | llm/veto_tracker.py, growth/veto_feedback | growth_report, learning_integrator, post_trade_learner, self_performance | LIVE | veto dollar-accounting (agenda Q4) |
| growth/recommendations.json | Recommendation engine output | 465KB | 07-01 | growth/recommendation_engine.py | swarm_feedback_loop | WRITE-mostly | were any recs ever enacted? |
| growth/growth_reports.json | Periodic growth reports | 166KB | 07-01 | growth/growth_report.py | nothing else | WRITE-ONLY | self-assessment history |
| growth/self_improvement_proposals.json | Self-improvement proposals | 62KB | 07-01 | growth/self_improvement.py | same only | WRITE-ONLY | proposal→adoption rate = ? |
| growth/parameter_changes.json | Param change audit trail | **21B (empty)** | 07-01 | growth/explainability.py | growth_report, manual/generate_report | LIVE-empty | ⚠ audit trail exists but nothing logs to it |
| teaching/knowledge_base.json | Self-teaching KB (lessons) | 636KB | 07-01 | llm/self_teaching.py | prompt_enricher, counterfactual_learner, graduated_rules, self_analyst | LIVE | full lesson corpus |
| teaching/curriculum_state.json | Curriculum position | 640B | 07-01 | self_teaching.py | same | LIVE | none |
| active_learning.json | Active-learning queue/answers | 132KB | 07-01 | llm/agents/active_learning.py | same | LIVE | open questions machine asked itself |
| agent_calibration.json | Per-agent calibration ledger | 7.6KB | 07-01 | agents/calibration_ledger.py | coordinator, learning_integration, api_server, perception_api | LIVE | agent trust weights |
| agent_costs.json | LLM cost tracking | 469B | 07-01 | agents/cost_optimizer.py | backtest llm_integration | LIVE | cost per decision |
| network_learning.json | Cross-agent network learning | 106KB | 07-01 | agents/network_learning.py | coordinator, active_learning | LIVE | inter-agent signal weights |
| neuroplasticity_state.json | Neuroplasticity (pathway weights) | 37KB | 07-01 | llm/neuroplasticity.py | coordinator, position_manager | LIVE | pathway reinforcement history |
| pattern_cache.json | Cached market patterns | 20KB | 07-01 | llm/pattern_cache.py | deep_memory, snapshot_builder, backtest engine | LIVE | pattern hit rates |
| operator_messages.json | Bot→operator message channel | 51KB | 07-01 | llm/operator_channel.py | operator (human/CLI) | WRITE-mostly | unread bot-to-owner messages |
| overseer_memo.json | Overseer memo to next cycle | 1.5KB | 07-01 | core/llm_integration.py | prompt_enricher | LIVE | none |
| llm_memory.json | Compact LLM memory | 224B (was 15KB pre-purge) | 07-01 | llm/memory_store.py | autonomy_router, candidate, evolution_tracker | LIVE | purged 06-07; near-empty |
| learning_state.json | Learning-mode state | 452B | 07-01 | llm/learning_mode.py | analyze_backtest | LIVE | none |
| roadmap_state.json | Knowledge roadmap position | 1.4KB | 07-01 | llm/knowledge_roadmap.py | autonomy, analytics, telegram_bot | LIVE | none |
| survival_state.json | Survival-pressure state | 625B | 07-01 | llm/survival_pressure.py | coordinator | LIVE | none |
| auto_demotion.json | Agent auto-demotion record | 249B | 06-17 | llm/auto_demotion.py | knowledge_roadmap | STALE(06-17) | which agents got demoted & why |
| deep_analyst_state.json / self_analyst_last_run.json | Analyst cadence markers | 121B | 06-29/07-01 | deep_trade_analyst, self_analyst | same | LIVE | none |
| mechanical_bot_memory/, mechanical_bot_state/ | empty dirs | 0 | — | mechanical_bot_memory.py creates dirs, **never wrote a record** | mechanical_bot_* suite | ORPHAN | ⚠ whole subsystem initialized but inert |

### 1d. Gate/exit/signal logs (bot/data/logs/)
| Artifact | What | Size / Records | Span | Writer | Reader | Status | Knowledge value |
|---|---|---|---|---|---|---|---|
| signal_outcomes.jsonl | Every signal + every gate annotation (pass/reject) | 24.8MB / 56,379 | 05-31→07-01 | core/signal_tracker.py (via main) | offline research only (manual/*, tools/signal_funnel, bot_status) | WRITE-ONLY (runtime) | ★ the definitive gate-ROC dataset |
| exit_decisions.jsonl | Exit-agent decisions (hold/close/trim) | 351KB / 604 | 06-01→07-01 | llm/exit_engine.py | exit-geometry BT, backtest engine | LIVE | exit-agent skill audit (agenda Q9) |
| exit_closes.jsonl | Position close records | 19KB / 55 | 06-24→07-01 | position_manager | analytics/exit_regret.py | LIVE | close-quality vs price-after |
| exit_regret_scores.jsonl | Regret score per close | 24KB / 53 | 06-25→07-01 | analytics/exit_regret.py | multi_strategy_main | LIVE | quantified exit regret |
| state_transitions.csv | Position state-machine transitions | 140KB / 2,118 | →07-01 | execution/position_state.py | edge_analysis, terminal_status | LIVE | lifecycle timing forensics |
| safety_events.csv | Risk/safety events | 45KB / 333 | →07-01 | execution/risk.py | dump_rejections, backtest engine | LIVE | risk-trigger history |
| risk_rejections.csv | Risk-filter rejections | 2KB / 25 rows | **frozen 06-06** | data/risk_log.py | signal_funnel, terminal_status, telegram_bot | STALE(06-06) | either no risk rejections in 25 days or writer dead — verify |

### 1e. Sniper / manual simulation ecosystem (bot/data/manual/)
| Artifact | What | Size / Records | Span | Writer | Reader | Status | Knowledge value |
|---|---|---|---|---|---|---|---|
| sniper_rejections.jsonl | Every sniper-filter rejection w/ reason | **14.4MB / 79,233** | 05-30→07-01 | manual/sniper_filter.py | multi_path_compare, health_check (offline) | WRITE-ONLY (runtime) | ★ biggest untapped rejection dataset |
| sniper_signals.jsonl | Accepted sniper signals | 616KB / 706 | 05-31→07-01 | manual/sniper_filter.py | performance, playbook, replay tools, dashboard | LIVE | sniper edge validation |
| trade_scorecards.jsonl | Per-trade scorecards (graded) | 1.04MB / 2,506 | 05-30→07-01 | manual/trade_scorecard.py | nothing runtime | WRITE-ONLY | do scorecard grades predict PnL? |
| trade_lessons.jsonl + trade_learner_state.json | Lessons from closed trades | 163KB / 335 | 05-31→07-01 | manual/trade_learner.py | same | LIVE | lesson quality audit |
| sim_trades.jsonl + sim_status.json | Base sniper simulator | 52KB / 59 | 05-31→**06-30** | manual/simulator.py | daily_tracker, optimizer, overnight_report, prompt_enricher | STALE?(06-30) | sniper sim P&L (agenda #21) |
| pa_sim_trades.jsonl + pa_sim_status.json + pa_vs_basic_comparison.json | Price-action simulator variant | 46KB / 51 | 06-23→07-01 | manual/pa_simulator.py | edge_discovery, multi_path_compare, api_server | LIVE | PA vs basic entry comparison |
| anticipatory_history.jsonl | Anticipatory-entry engine log | 7.9KB / 20 | **started 07-01** | manual/anticipatory_entries.py | daily_report, multi_path_compare | LIVE (new) | anticipatory-entry EV |
| conviction_sizing.jsonl | Conviction-sizer decisions | 4.7KB / 12 | **started 07-01** | manual/conviction_sizer.py | same | LIVE (new) | sizing-ladder evidence (agenda Q6) |
| pending_entries.json | Pending anticipatory entries | 3KB | 07-01 | anticipatory_entries, pa_simulator | main, alpha_hunter, level_tracker | LIVE | none (queue) |
| signal_value_tracker.jsonl | Signal value over time | 68KB / 98 | 06-01→06-30 | manual/signal_tracker.py | same only | WRITE-ONLY | which signal sources add value (agenda Q3) |

### 1f. Analytics, reflections, corpus, telemetry (bot/data/*)
| Artifact | What | Size / Records | Span | Writer | Reader | Status | Knowledge value |
|---|---|---|---|---|---|---|---|
| counterfactuals/scenarios.json | Counterfactual scenario store | 373KB | 07-01 | analytics/counterfactual.py | prompt_enricher | LIVE | scenario-level lessons |
| reflections/trade_reflections.jsonl | Per-trade reflections | 76KB / 124 | 06-01→07-01 | llm/reflection_engine.py | coordinator (summary for agents) | LIVE | reflection quality vs outcomes |
| reflections/active_sequences.json, move_exhaustion.json | Reflection engine state | 3KB | 07-01 | reflection_engine | same | LIVE | none |
| reflections/periodic_summaries.jsonl | Periodic reflection summaries | 1.7KB / 3 | 06-18→06-27 | reflection_engine | nothing | WRITE-ONLY (rare) | none yet |
| ml/ml_stats.jsonl | ML cycle stats | 61KB / 332 | 05-30→07-01 | data/ml_log.py | generate_dashboards | LIVE | ML learner health over time |
| portfolio_risk/{price_history,correlation_cache,volatility_forecasts}.json | Portfolio risk inputs | 32KB | 07-01 | analytics/portfolio_risk.py | api_server, dashboard, correlation_tracking | LIVE | realized correlation regime |
| strategy_corpus/observations.jsonl | Strategy-discovery observations | 27KB / 124 | 05-31→07-01 | llm/strategy_discovery/corpus.py (via main) | confidence_calibrator, corpus | LIVE | raw material for strategy discovery |
| telemetry/latest.json | Latest fetcher telemetry snapshot | 849B | 07-01 | data/fetchers/telemetry.py | dashboard | LIVE | none |
| cache/*.csv (5m/1h/6h/daily per symbol) | OHLCV candle cache | ~4.3MB | 06-23/06-25 | data/fetcher.py + backtest tools | backtests | CACHE | free re-runnable candles |
| cache/exit_geometry_bt/*.json + results.json | Exit-geometry BT cache + results (in-flight) | ~1.2MB | 07-01 | tools/backtest_exit_geometry.py | same | LIVE (research) | agenda Q2 output |
| reports/paper_trading_*.md (63 files) | Hourly paper-trading reports Apr 25–May 30 (incl. 82 frozen A/B rules) | ~290KB | 04-25→05-30 | tools/overwatch_cycle.py (era) | **nothing reads** | STALE(05-30) | ★ archive mining (agenda #21) |
| sessions/daily_synthesis_*.json (10) | Daily learning syntheses | 51KB | 05-03→05-29 | learning/daily_synthesis.py | master_engine | STALE(05-29) | May-era distilled lessons |
| sessions/*.md (2) | Session logs / system map | 120KB | 04-15/05-17 | one-off | nothing | ORPHAN | historical context |

### 1g. Data OUTSIDE bot/data
| Artifact | What | Size / Records | Span | Writer | Reader | Status | Knowledge value |
|---|---|---|---|---|---|---|---|
| bot/logs/bot_YYYYMMDD.log (20 files) | Daily runtime logs | ~250MB | 05-30→07-01 (gaps 06-10→16, 06-17/18, 06-26/27 = blackouts) | logging config | humans/agents | LIVE | ★ root-cause forensics for every silent death |
| bot/logs/python_stdout.log + 3 archives | Supervisor stdout | ~377MB | →07-01 | run supervisor | nothing | LIVE (bloat) | same as above; 377MB candidate for rotation |
| bot/logs/supervisor.log, funding_oi_collector.log | Supervisor + collector logs | 435KB | collector log frozen 06-07 | supervisor / collector | nothing | LIVE / STALE | collector-death forensics |
| bot/ml_data/bot.db (SQLite) | Ops DB: trades(330), signals(91), equity_snapshots(1513), health_events(1611), signal_rejections(2716), performance_daily(90), signal_outcomes(124) | 1.9MB | →07-01 | data/db.py (DB_PATH=ml_data/bot.db) | api/app/routes_sniper.py, db.py consumers | LIVE | equity curve + health-event timeline; **trades table (330) disagrees with every CSV ledger** |
| bot/ml_data/{confidence_signal_log,market_snapshots,trade_outcomes,model_weights,strategy_stats,strategy_weights*}.json | ML learner stores | 1.2MB | 07-01 | ml/learner.py, strategies/confidence_scorer | ml/learner, dynamic_stats, learning_bridge | LIVE | confidence-scorer training corpus |
| bot/backtest_ml_data/confidence_signal_log.json | Backtest-mode copy of above | 87KB | 06-23 | backtest engine | backtest | STALE | none |
| bot/llm/data/llm/pipeline_telemetry.jsonl | Pipeline latency/token telemetry | 3MB / 3,518 | 05-31→07-01 | llm/agents/pipeline_extensions.py:489 (**path bug**: `__file__/../data/llm/` → bot/llm/data/, not bot/data/) | bot_perception_api expects it elsewhere | WRITE-ONLY (misplaced) | latency/cost per agent per cycle |
| bot/paper_trades/signals_*.csv + trades_*.csv (214 files) | Paper-session snapshots | 58KB | 05-30→06-05 | paper runner (era) | nothing | STALE(06-05) | little (tiny files) |
| bot/backtest_*.csv, bot/trades_10d*.csv, bot/report.json (root) | Apr/May backtest outputs | ~2.2MB | 05-17 | old backtest runs | nothing | ORPHAN | superseded by newer BT harnesses |
| bot/tools/backtests/adx_trades_*.csv | ADX-survivor lane outputs | 229KB | 07-01 | bt lane scripts | lane analysis | LIVE (research) | agenda Q5 evidence |
| historical/old-bot-pre-2026-04-23/ | Full archive of pre-April bot: decisions.jsonl (1.37MB), shadow_ledger.csv (583KB), trades.csv (191KB), deep_memory, feedback states | 3.5MB | ≤04-23 | archived | research only | ARCHIVE | ★ old-era archaeology (agenda Q18): the +$1,756 era |
| analysis/desktop-session/agent_performance_live_500.jsonl, analysis/historical/layer2_pilot_raw.json | Session research extracts | 273KB | 06-01/06-05 | session agents | nothing | ORPHAN | superseded snapshots |
| "backtest logs(Manual)", "paper trading 3-19 to 3-20" (root files) | Hand-kept March logs | 1.1MB | 03-19..05-17 | manual (Nunu) | nothing | ORPHAN | March-era manual observations |
| paper_trades/ (root, 2 files) | Feb 10 paper snapshot | 182B | 02-10 | old runner | nothing | ORPHAN | none |
| api/local.db | API scaffold DB — **all 6 tables empty** | 106KB | 05-17 | api/ scaffolding | api routes | ORPHAN | none |
| web/public/thesis/{btc,eth,hype,sol}/thesis.json | Frontend thesis JSONs | 2.2MB dir | 05-17 | old thesis pipeline | web frontend | STALE(05-17) | none |
| executor/config/symbols.json | Executor symbol config | 761B | 05-17 | hand | executor | CONFIG | none |
| coordination/*.md + predictions.json + PRESENCE.json | Agent-coordination reports & state | ~1MB | →07-01 | agents (incl. this census) | agents | LIVE | the meta-layer itself |

## 2. SUMMARY COUNTS
Artifact rows (families) cataloged: **97**
- LIVE: 58 · WRITE-ONLY (dormant knowledge): 9 · STALE: 14 · ORPHAN/ARCHIVE: 12 · CONFIG/CACHE/CODE: 4
- Total data on disk: **~937 MB** — of which bot/logs = 734MB (78%), bot/data = 189MB, everything else = 14MB.
- Largest knowledge streams: percepts 55.8MB (degenerate), signal_outcomes 24.8MB, counterfactual_resolved 24.8MB, trade_events 22.7MB, decisions 15.8MB, sniper_rejections 14.4MB, agent_performance 11.9MB.

## 3. DORMANT-KNOWLEDGE SHORTLIST (top 10, ranked by unmined value)
1. **sniper_rejections.jsonl** (79,233 records, WRITE-ONLY) — Which single rejection gate destroyed the most counterfactual EV, per regime? (5x the sample of any accepted-trade set.)
2. **signal_outcomes.jsonl** (56,379, gate annotations, runtime WRITE-ONLY) — The full ROC of every gate incl. confidence_floor: at what threshold does pass/reject flip EV-positive?
3. **counterfactual_resolved.jsonl** (39,137) — Train the "should-have-traded" logistic model (agenda Q14); already resolved with price-after outcomes.
4. **reports/paper_trading_*.md** (63 reports + 82 frozen A/B rules, dead since 05-30) — Which of the 82 frozen A/B rules were validated and silently lost in the May purges?
5. **agent_performance.jsonl** (24,291) — Which agent's confidence actually moves trade outcomes (skill vs noise per role)?
6. **trade_scorecards.jsonl** (2,506, WRITE-ONLY) — Do scorecard grades predict realized PnL, i.e. is the grader worth its tokens?
7. **historical/old-bot-pre-2026-04-23/** — What conditions produced the +$1,756 pre-May era and are they detectable live (agenda Q18)?
8. **growth/hypotheses.json + recommendations.json + self_improvement_proposals.json** (1.5MB combined, ~WRITE-ONLY) — What fraction of machine-generated proposals were ever enacted; did enacted ones outperform ignored ones?
9. **bot/logs/*.log** (734MB) — Reconstruct exact death timestamps/stack traces for every silent-death flag below (free root-cause data).
10. **signal_value_tracker.jsonl** (98, WRITE-ONLY, dead 06-30) — Per-source signal value: direct evidence for agenda Q3 (which entry source has edge).

## 4. INTEGRITY FLAGS
1. **Factor-analytics triple silent death 2026-06-06**: kelly_weights.json, ic_history.json, execution_analytics.csv all froze the same day (init block multi_strategy_main:981-1075 falls back to None on exception) — **yet dynamic_stats/feedback_state still read kelly_weights.json into agent prompts → 25-day-old factor stats injected as if current.** Same class as the Quant-Brain-stale-stats finding.
2. **pipeline_telemetry path bug**: pipeline_extensions.py:489 resolves `../data/llm/` relative to bot/llm/agents/ → writes to **bot/llm/data/llm/** instead of bot/data/llm/. 3MB of latency/token telemetry invisible to bot_perception_api which looks in the real data dir.
3. **percepts.jsonl is degenerate**: 440k records / 55.8MB and sampled records carry quality_score=0.0, consistency_score=0.0, gap=0.0 throughout — the self-perception instrument writes zeros every cycle. Fix the scorer or stop the write.
4. **funding_oi_history 22-day hole** (06-07→06-29, the known ~536h): collector log frozen 06-07; stream healthy again but has no watchdog — same failure mode will recur silently.
5. **graduated_rules.json clobber class**: 6 distinct writers (graduated_rules.py, hypothesis_tracker, growth/orchestrator, counterfactual_learner, auto_fix_pipeline, master_engine). Now 629B vs 20.6KB backup from 06-19 (cleared deliberately 06-29, but the multi-writer race remains).
6. **Five disagreeing trade stores**: trades.csv (91) vs trade_ledger.csv (157) vs ml_data/bot.db:trades (330) vs ml_data/trade_outcomes.json vs analysis/trade_outcomes.csv (25, post-fix). No reconciliation exists; any consumer picks a different truth.
7. **master_engine_state.json frozen 06-05** while multi_strategy_main:2395 calls master_engine.tick() every cycle — the learning master engine has silently no-oped for 26 days (execution_forensics + live_edge_data starved with it; daily_synthesis dead since 05-29).
8. **risk_rejections.csv frozen 06-06** (25 rows) while signal_outcomes shows thousands of gate rejections — either risk layer never fires (bypassed by LLM-first path) or risk_log.py writer is dead; signal_funnel/terminal_status read it and see a false-calm picture.
9. **mechanical_bot_memory/ + mechanical_bot_state/ empty**: a whole instrumented-memory subsystem (7 modules) creates its dirs and has never written one record.
10. **growth/parameter_changes.json empty (21 bytes)**: the parameter-change audit trail exists but nothing logs to it — parameter changes are currently unauditable, while auto_optimizer and tuner actively mutate state.
11. **log bloat**: python_stdout.log + archives = 377MB unrotated-in-practice; census-relevant but also a disk risk on a laptop-class host.
