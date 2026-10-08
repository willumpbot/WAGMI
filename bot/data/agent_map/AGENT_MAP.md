# WAGMI Agent Map — every decider/observer/learner and whether it reflects real data

Generated 2026-10-07 ~18:40Z, read-only. Machine-readable version: `agent_map.json` (same folder). Times UTC.

## Headline

- **Bot right now:** restarted 18:11Z on new models, 0 positions, equity $4,773.34. **Last trade closed 2026-10-02 18:40Z — 5 days with no trades.**
- **Why:** in the previous run (~81h) the Regime agent (claude-haiku-4-5) failed **167 of 212** calls, so 79% of LLM pipelines aborted. The 13 'proceed' decisions that did complete were all rejected by the living confidence floor (0.30-0.39 vs 0.40). **No alert fired:** health_alert stayed green and telemetry showed llm_errors=0.
- **Grading:** confirmed that `performance_tracker.score_trade` has no live caller (startup log: '0 scored outcomes'). Per-agent accuracy does accrue in `agent_calibration.json`, but it is labelled by the Learning LLM's own judgment and only updates when a trade closes (~0.4/day).
- **Verdicts:** ALIVE-UNGRADED 41, ALIVE-BUT-UNREAD 18, ALIVE+GRADED 15, STALE 6, DISABLED 5, DEAD 5 (total 90).

## One-screen verdict table

| # | Component | Layer | Consumer (who acts on it) | Live status | Graded? | Verdict |
|---|---|---|---|---|---|---|
| 1 | Regime agent | LLM agent | ACTED ON: regime for merge (coord:5007), overwrites regime_detector for all symbols (llm_integration.py:907);  | Prev run (Oct4 09:00Z-Oct7 18:10Z, ~81h): FAILED 167/212 calls (claude-haiku-4-5, exit 1, 0 tokens) -> pipelin | Graded via agent_calibration.json regime:* (accuracy derived from Learning LLM's own judgment, n~85) | **ALIVE+GRADED** |
| 2 | Trade agent | LLM agent | ACTED ON: base of merge -> EntryDecision; confidence passed through frozen calibration curve (coord:4993) then | Prev run: 41 completed pipelines (28 flat, 13 proceed); all 13 proceeds rejected at conf 0.30-0.39 < floor 0.4 | Graded: thesis close-grading (only when a position with thesis_id closes: 72 graded of 1559 theses)  | **ALIVE+GRADED** |
| 3 | Agent calibration ledger | Agent grading | Injected into Trade/Critic/Regime/Risk prompts (coord:3471); api_server reads wrong filename (calibration_ledg | Last write 10-02 (last close). trade ~120 obs, regime ~85, risk 1, critic 0. | This IS the live per-agent grading, but label = LLM's own thesis_correct. | **ALIVE+GRADED** |
| 4 | Prompt enricher | LLM context | Injected into every agent prompt | 549 ENRICHER log lines prev run (drops stale rules e.g. SOL range live_acc=28% n=40). | Re-checks graduated KB rules vs trades.csv (n>=13, drop <40% acc). Other sections ungraded. | **ALIVE+GRADED** |
| 5 | Deep memory / trade DNA / fingerprints | Memory | prompt_enricher sections; decision_engine snapshot | trade_dna 10-02; insight_journal 10-05. | Outcome-labelled (close). | **ALIVE+GRADED** |
| 6 | IC tracker | Weights | ensemble weight (ensemble.py:2652) | Last write 10-02. | Graded (Spearman, window 30). | **ALIVE+GRADED** |
| 7 | Entry selectivity gate (+BLOCKED_GO_PROBE) | Gate | ACTED ON: msm:8860-8960 | Not reached in prev run (0 log lines) because every proceed died at the LLM floor first. Probe forward evidenc | Self-graded vs breakeven WR (solo n=32 WR 18.8%; long-drain n=22 WR 9%). Thresholds n>=13 hardcoded. | **ALIVE+GRADED** |
| 8 | Signal quality scorer | Weights | ensemble confidence (applied TWICE: loop instance + startup snapshot instance) | Last write 10-02. | Bucket WR. | **ALIVE+GRADED** |
| 9 | Regime feedback | Weights | prompt context (brain_wiring, coord:3323) | Last 10-02; only consolidation bucket populated (10W/29L). | WR. | **ALIVE+GRADED** |
| 10 | Counterfactual learner (LLM skips/vetoes) | Counterfactual | Trade agent brain context (brain_wiring:274); KB; api | resolved file rewritten 18:14Z; ~87 resolutions on 10-04 and 10-07. Newest pending created 10-02. | Graded vs price. | **ALIVE+GRADED** |
| 11 | Counterfactual engine (analytics) | Counterfactual | Critic snapshot; enricher exit patterns | Last 10-03. | Graded. | **ALIVE+GRADED** |
| 12 | Thesis tracker | Counterfactual | Trade context, calibrator, proof_window | Last 10-05. | 1,559 theses: 26 correct / 46 incorrect / 1,487 pending forever (only graded if executed + closed). | **ALIVE+GRADED** |
| 13 | ML SignalLearner | ML | LLM snapshot only (adjust_confidence is mechanical-path) | ml_stats 18:14Z; model_weights 18:22Z. | Graded. | **ALIVE+GRADED** |
| 14 | Manual sniper + simulator + trade learner | Parallel sim | sim_status -> prompt enricher; otherwise its own loop | Scorecards 18:13Z; sim closes ~1-2/day. | Graded (sim closes, 5m-12h forward checkpoints). | **ALIVE+GRADED** |
| 15 | WAGMI-Copilot-Daily | Scheduled task | see output | every daily; last 13:13Z ok | GRADED forward (1d) | **ALIVE+GRADED** |
| 16 | Risk agent | LLM agent | ACTED ON: leverage/risk_pct/qty (coord:1965-2014); override=skip forces flat (coord:5048) | Runs every completed pipeline (86 records in last 4d, haiku-4-5). | Effectively ungraded: 1 ledger entry ever. | **ALIVE-UNGRADED** |
| 17 | Critic agent | LLM agent | SHADOW (CRITIC_ENFORCE unset=false): notes only + [SHADOW-CRITIC] log; skips -> counterfactual store | 16 SHADOW-CRITIC would_veto lines in prev run. | Not graded live (calibration_ledger critic n=0 because critic_challenged never passed, msm:4538). Sh | **ALIVE-UNGRADED** |
| 18 | Quant agent | LLM agent | SHADOW (QUANT_AGENT_ENFORCE=false): logs [SHADOW-QUANT]; text into Risk prompt as advisory | 57 SHADOW-QUANT lines prev run (typical would_adjust -0.15). | No grading. | **ALIVE-UNGRADED** |
| 19 | Exit agent | LLM agent | ACTED ON: exit_engine.apply_exit_decision (RQ9 gate) AND direct force-close at llm_integration.py:1250 (bypass | Only runs with open positions; 0 positions since Oct 2. exit_decisions.jsonl last 09-28. LLM_EXIT_HIGH/CRITICA | Offline only (exit_regret_scores.jsonl computed live but unread; RQ9 scripts). | **ALIVE-UNGRADED** |
| 20 | Scout agent | LLM agent | Weak: _scout_thesis_cache -> entry snapshot; re-entry gate (llm_integration.py:1092) | Ran 18:14Z on new model (5 items). Prev run: 54 failures (haiku). | No grading (regime_forecast never checked). | **ALIVE-UNGRADED** |
| 21 | Learning agent | LLM agent | Feeds memory_store, deep memory, KB, hypotheses, network_learning, calibration ledger | Only on close; last 10-02. | Its own thesis_correct is the label for agent_calibration but is never checked itself. | **ALIVE-UNGRADED** |
| 22 | agent_brain self-summary | Agent grading | Injected into Regime/Trade/Risk/Critic/Quant system prompts every call | In-memory only, never saved. | Broken: correct_decisions always 0. | **ALIVE-UNGRADED** |
| 23 | Network learning loop | Agent learning | Trade/Risk/Critic inputs; risk hard_constraints | Last write 10-02; 539 lessons processed. | Lessons selected by recency, never graded. | **ALIVE-UNGRADED** |
| 24 | Pre-trade simulator | LLM support | Trade + Risk prompts | Every pipeline. | Never graded vs outcome. | **ALIVE-UNGRADED** |
| 25 | Consistency checker | LLM support | ACTED ON: critical issue forces skip; score<0.7 scales confidence | Every pipeline (consistency=0.95 typical). | None. | **ALIVE-UNGRADED** |
| 26 | Post-hoc debate / structured debate | LLM support | Confidence blend when consensus < conf-0.1 (coord:5213) | 24 [DEBATE] lines prev run (mostly no_consensus). | None. | **ALIVE-UNGRADED** |
| 27 | mech_regime overlay | Mechanical regime | ACTED ON: overrides LLM regime label (REGIME_OVERLAY_ENFORCE default true) | ~206 overlay lines prev run. | Offline RQ10 only. | **ALIVE-UNGRADED** |
| 28 | Metabrain decision engine + LLM risk gate | Gate | ACTED ON: log shows 'main: [LLM] No decision: gated: confidence_too_low' after every sub-floor proceed | 13/13 proceeds rejected prev run. | Not graded. | **ALIVE-UNGRADED** |
| 29 | Living confidence floor | Gate | risk_gating Rule 2 | Store last saved 10-05 (55h old); evaluated per decision. | NOT graded vs outcomes by design (self-referential percentile: only top 10% of own confidences pass) | **ALIVE-UNGRADED** |
| 30 | LLM memory (short-term) | Memory | Trade prompt (800 chars), Critic prompt | Last write 10-05 (55h). | Lessons from W/L but never validated. | **ALIVE-UNGRADED** |
| 31 | Teaching knowledge base / self-teaching | Memory | coord:892 KNOWLEDGE BASE section; enricher (servable filter) | Written 18:14Z today; TEACH cycle #20 '+9 knowledge items' each cycle. | curriculum predictions_made: 0 -> never graded. | **ALIVE-UNGRADED** |
| 32 | Growth: veto tracker / hypotheses / growth reports | Meta | hypotheses -> enricher; reports -> nobody live | growth_reports written 18:05Z; veto_tracker 10-05. | Veto tracker: 500 vetoes, 1 resolved (0% acc) — records have symbol='[cross-market' side='DIVERGENCE | **ALIVE-UNGRADED** |
| 33 | Decision audit log | Audit | replay_engine (coord:3267), self_performance, evolution tracker, api/dashboard | Last 17:56Z. Last 7d: 337 multi_agent_decision, 294 flat, 43 proceed, 176 api_error. | Joined to outcomes via self_performance/joiner (no position_id -> weak join, see LINEAGE_JOIN_GAP.md | **ALIVE-UNGRADED** |
| 34 | Strategy: funding_rate | Ensemble strategy | strategies/ensemble.py _weighted_veto (2436) -> confidence handed to LLM pipeline | Fires every scan (RAW strategy map logged per symbol; e.g. 2/9 fired). | Graded only via IC tracker (data/ic_history.json, last 10-02). | **ALIVE-UNGRADED** |
| 35 | Strategy: oi_delta | Ensemble strategy | strategies/ensemble.py _weighted_veto (2436) -> confidence handed to LLM pipeline | Fires every scan (RAW strategy map logged per symbol; e.g. 2/9 fired). | Graded only via IC tracker (data/ic_history.json, last 10-02). | **ALIVE-UNGRADED** |
| 36 | Strategy: liquidation_cascade | Ensemble strategy | strategies/ensemble.py _weighted_veto (2436) -> confidence handed to LLM pipeline | Fires every scan (RAW strategy map logged per symbol; e.g. 2/9 fired). | Graded only via IC tracker (data/ic_history.json, last 10-02). | **ALIVE-UNGRADED** |
| 37 | Strategy: probability_engine | Ensemble strategy | strategies/ensemble.py _weighted_veto (2436) -> confidence handed to LLM pipeline | Fires every scan (RAW strategy map logged per symbol; e.g. 2/9 fired). | Graded only via IC tracker (data/ic_history.json, last 10-02). | **ALIVE-UNGRADED** |
| 38 | Side multiplier (live_edge) | Sizing | ACTED ON: qty | Computed on demand. | Adapts from ledger; no predictiveness check. | **ALIVE-UNGRADED** |
| 39 | Fee guard (exit) | Exit | ACTED ON | Only with open positions. | Not graded. | **ALIVE-UNGRADED** |
| 40 | Correlation boost | Weights | EV metadata for LLM (clamped to 0.5 in non-trending) | Refreshed at init. | Side WR only. | **ALIVE-UNGRADED** |
| 41 | Quant regime classifier | Mechanical regime | regime cache, filters, ledger regime fields | 6,959 log lines prev run. | Not graded. | **ALIVE-UNGRADED** |
| 42 | Shadow router (R21d FIT table) | Ensemble | annotation only | 4,199 lines prev run (most frequent advisory). | Not graded in-loop (other agent grading shadows). | **ALIVE-UNGRADED** |
| 43 | Volume-chop shadow gate | Gate | advisory only (VOLUME_CHOP_ENFORCE) | 1,330 lines prev run. | Graded by the parallel manager_audit agent — not duplicated here. | **ALIVE-UNGRADED** |
| 44 | Degradation module | Safety | ACTED ON | 161 DEGRADATION lines prev run ('LLM probe attempt'); heartbeat llm_first_degraded=false throughout. | Not graded. | **ALIVE-UNGRADED** |
| 45 | Go-live gate | Safety | log only | At startup. | - | **ALIVE-UNGRADED** |
| 46 | WAGMI-HealthAlert | Scheduled task | owner (Discord/dashboard/site) | every 15 min; last 18:14Z ok | Blind to intermittent LLM failure (keys off llm_first_degraded only) | **ALIVE-UNGRADED** |
| 47 | WAGMI-DroughtAlert | Scheduled task | owner (Discord/dashboard/site) | every daily; last 14:15Z ok | Fired correctly | **ALIVE-UNGRADED** |
| 48 | WAGMI-TradeNotify | Scheduled task | owner (Discord/dashboard/site) | every 5 min; last 18:19Z ok | - | **ALIVE-UNGRADED** |
| 49 | WAGMI-DailyDigest | Scheduled task | owner (Discord/dashboard/site) | every daily 20:00Z; last 10-06 20:00Z ok | - | **ALIVE-UNGRADED** |
| 50 | WAGMI-ProofWindow | Scheduled task | owner (Discord/dashboard/site) | every 6 h; last 17:00Z ok | - | **ALIVE-UNGRADED** |
| 51 | WAGMI-Accumulate | Scheduled task | see output | every 3 h; last 16:01Z ok | - | **ALIVE-UNGRADED** |
| 52 | WAGMI-WeeklyResearch | Scheduled task | see output | every weekly; last 10-04 ok | human-only | **ALIVE-UNGRADED** |
| 53 | WAGMI-Copilot-Alerts | Scheduled task | owner (Discord/dashboard/site) | every 2 h; last 16:33Z ok | - | **ALIVE-UNGRADED** |
| 54 | WAGMI-ShiftBriefing | Scheduled task | owner (Discord/dashboard/site) | every 4 h; last 17:50Z ok | - | **ALIVE-UNGRADED** |
| 55 | WAGMI-Dashboard | Scheduled task | owner (Discord/dashboard/site) | every 1 min; last 18:23Z ok | - | **ALIVE-UNGRADED** |
| 56 | WAGMI-Snapshot / PublishSite | Scheduled task | see output | every 15m/1h; ok | Calibration endpoint empty (wrong filename) | **ALIVE-UNGRADED** |
| 57 | Per-agent performance tracker | Agent grading | Only api_server health + offline tools; nothing in decision loop | Written 18:14Z today. Log at startup: 'Loaded 20076 pipeline records, 0 scored outcomes'. | VERIFIED: score_trade has NO live caller (only its docstring); pipeline_id is a fresh uuid4 never st | **ALIVE-BUT-UNREAD** |
| 58 | Background thinker | LLM support | Coordinator constructs its own EMPTY instance (coord:781); msm runs think() on another (msm:2233) -> never rea | 749 log lines prev run (Thought cycle #545). | None. | **ALIVE-BUT-UNREAD** |
| 59 | Meta-learning insights/ideas | Meta | insights -> enricher; ideas -> global_ctx.extra but never serialized into prompt | Last write 10-06 20:24Z. | evaluate_idea inside own tick. | **ALIVE-BUT-UNREAD** |
| 60 | Bot perception capture | Audit | Only research analyzer/report scripts | Written continuously (18:22Z). | quality/consistency scores, never vs outcome. | **ALIVE-BUT-UNREAD** |
| 61 | Strategy: confidence_scorer | Ensemble strategy | strategies/ensemble.py _weighted_veto (2436) -> confidence handed to LLM pipeline | Fires every scan (RAW strategy map logged per symbol; e.g. 2/9 fired). | Graded only via IC tracker (data/ic_history.json, last 10-02). | **ALIVE-BUT-UNREAD** |
| 62 | Strategy: bollinger_squeeze | Ensemble strategy | strategies/ensemble.py _weighted_veto (2436) -> confidence handed to LLM pipeline | Fires every scan (RAW strategy map logged per symbol; e.g. 2/9 fired). | Graded only via IC tracker (data/ic_history.json, last 10-02). | **ALIVE-BUT-UNREAD** |
| 63 | Strategy: regime_trend | Ensemble strategy | strategies/ensemble.py _weighted_veto (2436) -> confidence handed to LLM pipeline | Fires every scan (RAW strategy map logged per symbol; e.g. 2/9 fired). | Graded only via IC tracker (data/ic_history.json, last 10-02). | **ALIVE-BUT-UNREAD** |
| 64 | Strategy: mean_reversion | Ensemble strategy | strategies/ensemble.py _weighted_veto (2436) -> confidence handed to LLM pipeline | Fires every scan (RAW strategy map logged per symbol; e.g. 2/9 fired). | Graded only via IC tracker (data/ic_history.json, last 10-02). | **ALIVE-BUT-UNREAD** |
| 65 | Strategy weight manager | Weights | ensemble._get_strategy_weight (2625) | File rewritten every scan (18:24Z) but content static. | VERIFIED: every named strategy trials=0 -> flat 0.30; outcomes land on 'ensemble' (209.9/211.4 'wins | **ALIVE-BUT-UNREAD** |
| 66 | Kelly engine | Sizing | Only fills a ledger column (blank 286/290) + daily report | Last write 10-02. | Graded but output not used for sizing. | **ALIVE-BUT-UNREAD** |
| 67 | Adaptive confidence floor | Gate | capped back to configured 20 under LLM-first (msm:2284) | Last write 10-02. | Graded by bin. | **ALIVE-BUT-UNREAD** |
| 68 | Parameter tuner / continuous backtest / AutoOptimizer / FeedbackLoop | Tuning | Only feedback.evaluate_signal / get_leverage_cap on the MECHANICAL path, which LLM-first returns before | tuner_state written 18:05Z; auto_optimizer last 10-04 (llm_insights null); 753 reload lines prev run (re-insta | Graded (WR/PnL). | **ALIVE-BUT-UNREAD** |
| 69 | Adaptive risk / sizer | Sizing | mechanical fallback only; state text reaches enricher | Last write 10-02. | Graded WR. | **ALIVE-BUT-UNREAD** |
| 70 | Graduated rules | Gate | ensemble.py:1042/1545 + prompt | Last write 10-02. | times_correct tracked. | **ALIVE-BUT-UNREAD** |
| 71 | Missed-trade tracker + resolver | Counterfactual | Bot NEVER reads resolved file (only tools/cross_sectional_edge.py offline) | Logged 18:03Z; resolved 15:41Z. | Graded vs price. | **ALIVE-BUT-UNREAD** |
| 72 | Exit-regret scorer | Exit | nobody | Last 10-02 (last close). | Graded. | **ALIVE-BUT-UNREAD** |
| 73 | WAGMI-MarketCollector | Scheduled task | see output | every 15 min; last 18:22Z ok | Collected funding/OI/depth (46k + 52MB) mostly unused by decisions | **ALIVE-BUT-UNREAD** |
| 74 | WAGMI-ResolveMissedTrades | Scheduled task | see output | every 4 h; last 15:41Z ok | Unread by bot | **ALIVE-BUT-UNREAD** |
| 75 | agent_performance.py (network summary) | Agent grading | Injected into prompt (coord:766) | Decisions last 2026-06-06 (28 total, 5 matched); outcomes 232 but match nothing. File 10-02. | Nominally graded but join is broken under LLM-first. | **STALE** |
| 76 | Confidence calibrator (curve) | Calibration | ACTED ON: applied to Trade agent confidence (coord:4993) | Curve last rebuilt 2026-07-28 (50-60 band n=43, adj -20.92). rebuild needs >=40 obs in 60d; only ~16 -> never  | Graded once; now frozen but still applied, no staleness check. | **STALE** |
| 77 | Hold-time rules | Exit | LLM exit context | State 10-02; 39 trades in 'unknown' bucket. | Self-referential. | **STALE** |
| 78 | Shadow ledger | Audit | reader hardcoded empty (_SHADOW_EDGES={}) | last row 07-26, actual_return blank. | Never resolved. | **STALE** |
| 79 | LLM-exit resolver | Exit | nobody | Last 07-30; not scheduled. | Graded. | **STALE** |
| 80 | WAGMI-Watchdog | Scheduled task | see output | every logon; last 09-28, result 0xC000013A | Task not running; hidden supervisor may cover it (UNVERIFIED) | **STALE** |
| 81 | Overseer agent | LLM agent | overseer_memo.json (last 07-13; enricher ignores after 2h) | AGENT_OVERSEER_ENABLED=false | - | **DISABLED** |
| 82 | Strategy: multi_tier_quality | Ensemble strategy | strategies/ensemble.py _weighted_veto (2436) -> confidence handed to LLM pipeline | Fires every scan (RAW strategy map logged per symbol; e.g. 2/9 fired). | Graded only via IC tracker (data/ic_history.json, last 10-02). | **DISABLED** |
| 83 | Breakeven ratchet | Exit | none | BREAKEVEN_RATCHET=shadow | Refuted 07-30. | **DISABLED** |
| 84 | RL buffer / policy | ML | ENABLE_RL_POLICY unset=false -> never applied | transitions 10-02. | - | **DISABLED** |
| 85 | Quant Brain | Stats | - | QUANT_BRAIN_ENABLED=false | - | **DISABLED** |
| 86 | Dead agent modules | LLM agent | no callers | - | - | **DEAD** |
| 87 | Dead strategies | Ensemble strategy | - | - | - | **DEAD** |
| 88 | EV calibrator / rejection tracker | Gate | No effect (LLM_MODE>=4 overrides; shadow) | ev_calibrator_state 07-01; rejection_outcomes.jsonl never created. | n=0. | **DEAD** |
| 89 | learning/master_engine | Meta | msm:2592 calls non-existent TradeLedger.all_trades(); swallowed | data/learning/* June/July | - | **DEAD** |
| 90 | Swarm system / filter_accuracy / strategy_pruning override / RegimeStrategyWeighter | Misc | - | - | - | **DEAD** |

Table cells are abbreviated; the JSON has full inputs, outputs, files and notes for every row.

## Biggest real-time reflection gaps (ranked by expected P&L / learning impact)

**1. LLM brain was mostly down and nobody was told**  
Evidence: Prev run: regime agent failed 167/212 calls on claude-haiku-4-5 (exit 1, 0 tokens) -> 79% of pipelines aborted; health_alert green, telemetry llm_errors=0, heartbeat llm_first_degraded=false; digest 'LLM degraded: no'. Models changed 18:11Z; outcome not yet observed.  
Impact: Whole decision stack inert; 0 trades for 5 days. What a manager would do: Manager metric: pipeline completion rate per hour + alert at <80%.

**2. No price-graded score for any LLM agent**  
Evidence: performance_tracker.score_trade has no caller ('0 scored outcomes' at startup); pipeline_id never joined to positions; agent_calibration uses Learning-LLM self-label and only fires on ~0.4 closes/day; agent_brain tells every agent WR=0%.  
Impact: Cannot know which agent adds/destroys edge; Opus spend ungoverned. What a manager would do: Grade every agent output vs forward price (decision hook #2).

**3. Confidence pipeline gated by stale + self-referential numbers**  
Evidence: Calibration curve frozen 07-28 (-20.9 in 50-60 band) still applied; living floor = P90 of those deflated confidences (0.40); 13/13 proceeds rejected at 0.30-0.39. Floor is by design not outcome-graded.  
Impact: Entry throughput decided by two ungraded transforms. What a manager would do: Grade floor-rejected proceeds via missed/counterfactual resolution; add staleness expiry to curve.

**4. Ensemble learning routed into dead keys + IC lock-in**  
Evidence: Ledger strategy column blank -> all outcomes to 'ensemble'/'' keys; every named strategy flat 0.30; IC weight 0 for confidence_scorer/bollinger/regime_trend/mean_reversion on n=10-30 -> can never re-earn samples.  
Impact: Signal mix frozen by small-n negative IC; ensemble confidence fed to LLM is a stale artefact. What a manager would do: Stamp strategy on close; grade strategies on all fired signals vs forward price.

**5. Resolved outcome streams that nothing learns from**  
Evidence: missed_trades_resolved (1,407), exit_regret_scores (556), counterfactual resolutions, thesis pendings (1,487), percepts (1.59M/200MB), funding/OI/depth history — all graded or gradable, zero live consumer. Mechanical learners (tuner, adaptive floor, adaptive risk, kelly, autooptimizer) adapt but are off the LLM-first path.  
Impact: Most of the bot's learning is write-only. What a manager would do: Manager layer reads these as its grade book.

**6. Data integrity in the graded substrates**  
Evidence: Counterfactual 07-14 backlog re-resolved up to 51x (25% duplicate rows); veto_tracker 500 rows unresolvable (symbol parse bug); regime_feedback PF=999 on losses; trade_ledger position_id only 46/290, regime_4h 33/290; Learning agent runs twice per close; signal_quality applied twice.  
Impact: Any manager grading these raw would be wrong. What a manager would do: Dedupe/validate before grading.

**7. Exit decisions least supervised**  
Evidence: Exit agent force-close path bypasses EXIT_AGENT_FULL_CLOSE gate; LLM_EXIT_* is the dominant ledger exit type; exit_regret computed but unread; resolve_llm_exits unscheduled since 07-30.  
Impact: Prior finding: early LLM exits + fees are the main leak. What a manager would do: Exit-regret as a graded manager hook.

## Graded hooks a manager layer can use

| Hook | Resolves | Frequency (measured) | File | Manager use |
|---|---|---|---|---|
| Trade close (main close handler, msm ~3960-5010) | every acted-on decision: entry, size, exit, thesis, calibration, IC, kelly, regime, DNA | 16 closes since 2026-09-01 (~0.44/day); last 2026-10-02 18:40Z; 0 in last 5 days | trade_ledger.csv (290 rows; position_id filled 46, regime_4h 33) | Primary ground truth but too sparse to grade 9 agents; needs pipeline_id/thesis_id/position_id join. |
| LLM pipeline decision -> forward price (NOT IMPLEMENTED) | every Regime/Trade/Risk/Critic/Quant/Scout output incl. flats | ~60 attempts/day (prev run); decisions.jsonl ~96 rows/day; agent_performance.jsonl 56k rows | llm/agent_performance.jsonl, llm/decisions.jsonl | Highest-volume gradable stream: score each agent's call vs +1h/+4h/+24h price, exactly like counterfactuals. Biggest unbuilt hook. |
| Thesis resolution | Trade agent thesis (target_price, expected_hold_h) | ~10 theses/day created; graded only on close (72 ever) | llm/thesis_history.jsonl | Price-resolve pending theses at expected_hold_h -> ~10 graded/day instead of ~0. |
| Counterfactual learner resolution | LLM skips/vetoes/critic challenges | ~87/day on recent days (16h window); new rows stopped 10-02 | llm/counterfactual_resolved.jsonl | Grade skip quality; MUST dedupe by record_id and purge the 07-14 backlog first. |
| Missed-trade resolution | gate rejections (would_have_won) | ~25 distinct setups/day (4h task); 350-900 raw rejections/day | missed_trades_resolved.jsonl | Grade each gate (entry selectivity, living floor, solo) by rejection_gate. |
| Analytics counterfactual scenarios | vetoes + exit alternatives | per veto/close; last 10-03 | counterfactuals/scenarios.json | Exit-alternative grading. |
| Exit regret | each exit vs price +1/2/4h | per close (556 total) | logs/exit_regret_scores.jsonl | Grade the Exit agent + fee guard; currently unread. |
| Agent calibration (Learning-agent label) | per-agent correctness | per close | llm/agent_calibration.json | Exists, but label is LLM self-judgment; replace with price label. |
| Veto tracker (growth) | LLM vetoes | ~8/day recorded, 1 resolved ever | llm/growth/veto_tracker.json | Broken parser (symbol='[cross-market'); fix before use. |
| BLOCKED_GO probes | was the entry gate right to block? | 11 of 30 probes closed (3W/8L, -$5.39) | trade_ledger.csv (probe-sized rows) | Direct A/B of the gate. |
| Manual sniper simulator closes + signal_value_tracker checkpoints | scorecard-approved setups; signal forward returns 5m..12h | sim 1-2 closes/day (153 total); tracker 2-6 signals/day with 9 checkpoints | manual/sim_trades.jsonl, manual/signal_value_tracker.jsonl | Independent baseline stream to compare the LLM brain against. |
| Copilot call ledger | daily discretionary call vs 1d forward | 1/day (324 resolved) | copilot/call_ledger_resolved.jsonl | Owner-side forward evidence; already a working graded loop. |
| Scout regime_forecast (NOT IMPLEMENTED) | regime forecast vs realized regime | every 15 ticks (~6/h) | (none) | Cheap to grade against quant_regime labels later. |
| IC tracker sample | strategy direction vs trade return | per close | ic_history.json | Fix lock-in: grade strategies on ALL signals vs forward price, not only traded ones. |

## Not verified / caveats

- The previous run's log has no dates. Its span (Oct 4 09:00Z to Oct 7 18:10Z) is inferred from 3 midnight wraps and the supervisor restart timestamp.
- Since the 18:11Z restart, no LLM pipeline had completed by 18:25Z, so it is not yet confirmed that the new models fix the Regime failures.
- Path conflict: one subagent said the living-floor/risk_gating path only feeds the regime cache. The log shows `main: [LLM] No decision: gated` right after it, so it is treated here as the live entry gate. The exact dual-path wiring (`coordinator.get_entry_decision` vs `decision_engine`) is not fully traced.
- The Quant agent's model is not overridden in .env. In the last 4 days agent_performance.jsonl shows it on haiku-4-5. Whether it still runs on haiku is unverified.
- Several file:line call-graph claims (exit gate bypass, double Learning run, agent_brain caller absence, signal_quality double-apply) come from code-reading subagents and were spot-checked, not exhaustively.
- The WAGMI-Watchdog task last ran 09-28 (0xC000013A). Whether a hidden supervisor replaces it is unverified.
- The daily digest showed 'Equity $0.00 / Uptime 0.0h' on 10-06. The heartbeat variant that caused it is unverified.
- Grading of shadow advisories (SHADOW-QUANT, SHADOW-CRITIC, volume_chop, shadow router) was deliberately left to the parallel manager_audit work.