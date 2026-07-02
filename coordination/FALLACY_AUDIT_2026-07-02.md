# Fallacy Audit — LLM inputs & opportunity gates vs THE_STANDARD v1.3

Scope: 30 claims audited, 28 CONFIRMED (3 merged duplicates → 25 entries), 2 REFUTED. Ranked by EV impact (live+large first, latent last). AUTON = fix autonomously; OWNER = gate-behavior change needs owner.

---

## 1. Fallacies that DENY real EV (opportunity cost)

**D1. Graduated-rules engine hard-vetoes pre-LLM from keyword-parsed, sub-standard, INVERTED rules — ACTIVE NOW**
- Rule: §2b (n>=13, dollar-positive, provenance) + §1 (no graduation n<15)
- `bot/llm/graduated_rules.py:4-8,44-70,180-297`; enforcement `bot/core/signal_pipeline.py:456-478`, `coordinator.py:1687-1737`; `hypothesis_tracker.py:497-553` fast-tracks at n>=7 and graduates INVALIDATED (ratio<=0.3) hypotheses
- Offending: graduation at "10+ evidence, 70%+ ratio"; no era/ledger_version fields; live file has ~52 rules incl. provably inverted ones (rule_1782943853_2: "HYPE LONG 0% WR" parsed into a BOOST +8; SELL-side veto assigned to a LONG hypothesis; BTC SELL veto n=7 ratio=0.14 fired 3x)
- EV: whole (symbol,side,regime) classes vetoed before the LLM by garbage parses; ~40 keyword rules landed 06-30/07-01 and are firing
- Fix: quarantine the ~40 new rules NOW; add {era,n,ledger_version}; graduation n>=13 + dollar-positive; unprovenanced rules → shadow. **AUTON**

**D2. Edge map grades pooled dirty WRs against the decontaminated mechanical baseline — everything reads TOXIC**
- Rule: 3b full-information symmetry + §1 era-split
- `bot/llm/agents/dynamic_stats.py:199-305` vs `_wr_label:174-196` + `get_system_baseline` (mechanical-only, USE_MECHANICAL_BASELINE=true)
- Offending: live render "HYPE_SHORT: 30% WR (10), PF 1.66, $+9.21 — TOXIC" (profitable setup labeled TOXIC); numerator pools 30 LLM_EXIT_AGENT all-loss closes the baseline excludes
- EV: systematic false-TOXIC framing → reflexive skipping, the exact failure the flag was meant to fix, applied to one side only
- Fix: same population both sides (is_mechanical filter) + print population/era on emitted lines. **AUTON**

**D3. PERFORMANCE headline pools 0/57 LLM-exit contamination into "26% WR" self-knowledge in every agent prompt**
- Rule: 3b honest-stats (era/provenance missing)
- `bot/llm/deep_memory.py:870-931`; injected `snapshot_builder.py:497`, `coordinator.py:2442-2452,4614-4624`
- Offending: "PERFORMANCE: 122 trades, 26% WR, $+686 PnL" — mechanical-only truth is 32/65 (49%)
- EV: halves the WR every agent believes about itself → skip/veto bias (the self-distrust spiral)
- Fix: split by exit-type + era; label "ledger=vN, window=..". **AUTON**

**D4. win_prob/ev_per_dollar are confidence-in-drag; prompts rebuild a hidden confidence gate and call it "Real math. Hard to beat." (merged: 3 confirmed claims, same root)**
- Rule: 3b honest-stats + silent-gate pattern
- `bot/strategies/ensemble.py:2301` (`raw_win_prob = combined_conf/100`), `:2315` deflators {0.88-0.95}, `:2385-2392` own comment: "IC=-0.003 (p=0.976, pure noise)... reliability inverted" then clamps 0.50 non-trending, `:2421` ev_per_dollar; unlabeled to Trade/Risk/Critic (`coordinator.py:2070,3928,4083,4266`); `prompts.py:103-105,176-177,333-334` "win_prob<0.43 → skip", "ev_per_dollar<0.10 → skip", "Real math from real fees. Hard to beat"
- EV: both ways — hidden ~48% confidence floor denies wide-R:R setups; fake quant rigor manufactures EV when confidence is high
- Fix: label provenance ("conf/100 deflated, IC≈0, NOT measured WR" / "neutral_prior_0.50"); delete the <0.43/<0.10 skip thresholds; trust fee/R:R components only. **AUTON**

**D5. Fee-bug-era stats hardcoded in Exit/Risk/Learning/Critic prompts, written 7 weeks before the fee fix, never recomputed**
- Rule: 3b (broken-ledger stat banned; same era already stripped from shared_context 06-05)
- `bot/llm/agents/prompts.py:317,321,375,953-954,1011-1015,1032`
- Offending: "105 LIVE TRADES... 87 SL (82.9%)... 91% MFE capture", "101 LIVE TRADES... kelly=0.15 for 93/101", "97% of SL losses directionally correct", "Winners hold 4.3h, losers 1.6h", "100% of profit from 17 trades"
- EV: exit patience, partial-close, and sizing anchored to corrupted distributions on every decision
- Fix: mirror the 06-05 shared_context strip; let prompt_enricher runtime sections (which carry n) replace. Update tests pinning "101 LIVE TRADES". **AUTON**

**D6. 237 broken-era "principles" served evidence-stripped; relevance filter degenerate so all qualify**
- Rule: 3b naked-opinions + 2b suspect-by-construction
- `bot/llm/self_teaching.py:403-454` (serves content only; strips n/validation/date; `or not regime` short-circuit makes every principle "relevant"); via `coordinator.py:836-841`, `snapshot_builder.py:475-487`
- Offending: "Block SHORT_ETH when trending" (n=1), "HYPE SHORT veto... Enforce regardless of regime", "SOL_SELL... pnl=521.59%" (impossible, dirty ledger); 208/237 created 2026-06, ALL val=0/inv=0
- EV: blanket directional blocks steer off valid setups; fabricated PnL presented as fact
- Fix: append [n, validated, era, ledger] at serve time; quarantine pre-2026-07 principles until dollar re-scored; fix relevance filter. **AUTON**

**D7. Single-trade lessons graduate to permanent PRINCIPLE at conf 0.80 — 192 of the 237 served principles are n=1**
- Rule: 2b no-graduation-below-n>=13 + §1 small-n humility
- `bot/llm/agents/learning_integration.py:261,307-337`; permanence `bot/llm/self_teaching.py:463`
- Offending: strength=='strong' (LLM self-label) → knowledge_type='principle', confidence=0.80, evidence="{symbol} in {regime}" (one trade); compaction-exempt forever
- EV: whatever one trade did becomes permanent served doctrine ("Block directional SHORTs... in RANGE")
- Fix: 'strong' → HYPOTHESIS; principle only via validation path n>=13 dollar-positive; stamp {era,n,ledger}. **AUTON**

**D8. Quant Agent (alive, ungated) mechanically mutates confidence, forces skips, scales size via Kelly — zero accuracy gating**
- Rule: 2b opinion-enforcing-without-dollar-validation + 3b
- `coordinator.py:1260-1296` (±0.15 conf mutation; noise_prob>0.6 + conf<0.20 → forced skip, runs AFTER Critic so nothing overrides), `:4736-4744` (ungated kelly_fraction 0.5-1.5x size); noise score from checklist heuristics `prompts.py:1340-1341` ("+0.15 for each: solo strategy, volume below avg...")
- EV: Haiku-tier checklist opinion hard-skips and resizes every tier-3 decision; the only enforcer with no calibration gate (Risk and Critic both have one)
- Fix: demote QUANT_ADJ/QUANT_NOISE/kelly path to advisory + shadow-log until dollar-scored positive n>=13. **OWNER**

**D9. Slippage gate enforces despite its own measured 44.6% accuracy (blocks winners more than losers)**
- Rule: 2b (rule shown wrong must drop to shadow) + §5 meta-audit
- `bot/core/signal_pipeline.py:359-381`
- Offending: "Loosened from 40%: backtest shows 44.6% gate accuracy — blocking too many winners" — then still hard-rejects at >50% of stop, pre-LLM, threshold never re-scored (contrast Gate 5b, removed at 20%)
- EV: worse-than-coinflip block on the live path; LLM never sees the signal
- Fix: keep slippage arithmetic as labeled context; hard-block only after fresh dollar re-score. Shadow-logging counterfactual is autonomous; threshold change is **OWNER**

**D10. Static regime allowlists silently disenfranchise strategies with zero counterfactual — self-perpetuating denial**
- Rule: 2b provenance + 3b full-information
- `bot/strategies/ensemble.py:225-236` (STRATEGY_REGIME_ALLOWLIST; low_liquidity allows only confidence_scorer, which FIT marks 'avoid' → ZERO voters in that regime), `:208-219` REGIME_MIN_VOTES (no per-cell n/ledger); `multi_strategy_main.py:4747-4758` static 'avoid' disabling, "Dynamic WR-based disabling skipped"
- EV: banned strategies can't vote, can't reach evaluate_raw, generate no evidence to earn back their vote — unmeasured forever (allowlist gate has no shadow ledger; FIT-avoid path does)
- Fix: shadow-log would-have-voted for allowlist-suppressed strategies (reuse existing ShadowLedger); per-cell n+era or collapse to LLM-first context. **AUTON**

**D11. Time-of-day sizing runs on one April week and contradicts the Morning Edge boost — net size is an accident of multiplication**
- Rule: 2b (stale era, never re-scored) + §1 era-split
- `bot/execution/time_sizing.py:4,73-81,98-105` ("updated 2026-04-03"; 7 DEAD hours 0.5x; "17: short — 58-68% SHORT WR") vs `signal_pipeline.py:117-124` (06-12 UTC 1.2x "75% WR"; hours 6/7/10 are simultaneously DEAD 0.5x); also :127-130 says 18-23 was the profitable bucket while time_sizing marks 18/20/21 DEAD
- EV: 7 hours halved on stale data; hour 06-07 gets boost×penalty simultaneously
- Fix: neutralize both hour edges to 1.0x + shadow-log until clean-ledger hour study; one hour policy. **AUTON**

**D12. April volume-era hypotheses served as current "TESTING:" items; oldest-first crowds out fresh ones**
- Rule: 2b provenance + 3b honest-stats
- `bot/llm/self_teaching.py:386-393,443-446`
- Offending: live-executed today: 5 served items are all April ("High leverage (5x+) trades losing at 67%" ×4 near-dupes) — discredited volume-config stats biasing sizing/leverage agents 4x per decision under the selective regime
- Fix: era stamp + max-age filter; dedupe; newest-first ordering. **AUTON**

**D13. Hardcoded regime avoid-tables + forbidden-action maps injected into Trade/Critic/Overseer, contradicting the prompt's own Gate 1**
- Rule: §2 no-hardcoded-directional-opinion + 3b stats-without-n
- `bot/llm/agents/shared_context.py:214-233,435,452,467` ("avoid in high_vol (PF=0.65)" — no n/era; forbidden ["go","flip"]); injected `coordinator.py:3317-3325`; contradiction: `prompts.py:135` hard-skips panic while REGIME_ACTION_MAP:197-204 allows go in panic — agents get both
- EV: pre-decided action-class suppression from unspecified-era PF; contradiction adds noise
- Fix: convert prescriptive → descriptive runtime stats with n+era; single regime policy. **AUTON**

**D14. Fingerprint Strengths/Weaknesses inject denominator-free verdicts from n>=5 all-era cells**
- Rule: 3b stats-without-n + §1 (n>=5 threshold)
- `bot/llm/deep_memory.py:419-442,473-476`; live prompt today contains "Poor on BTC (0% WR)"; stored "Poor on HYPE (8% WR)", "Weak LONGs (5% WR)" — no n, all-era pooled (regime lines DO carry n — proving the omission)
- Fix: (n, era) on every line; threshold n>=13; mechanical clean-ledger closes only. **AUTON**

**D15. memory_store notes: unprovenanced LLM self-opinions reach Trade + Critic/veto prompts; 7-day TTL spans dirty→clean eras**
- Rule: 3b naked-opinions + 2b provenance
- `bot/llm/memory_store.py:45,163-190,305-310` → 'mem' via `snapshot_builder.py:157-163,422-423` → `coordinator.py:3780` (Trade) + `:4188` (Critic pattern-check); write schema has no ledger_version/source_trade_id; bonus bug: 3 live notes have corrupted symbol fields ("[POSITION", "[LEAD-LAG")
- EV: small today, structurally unbounded at the veto-adjacent surface
- Fix: write-time tags {ts, ledger_version, n:1, source_trade_id}; render provenance; fix symbol-parse bug. **AUTON**

**D16. QB sniper veto: the muted-as-anti-signal engine retains mechanical block power over the sniper channel, unmeasured**
- Rule: §2b shadow-until-revalidated (Quant Brain precedent, THE_STANDARD §3b:35)
- `bot/multi_strategy_main.py:4884-4893` (`continue` skips eval/sim/alert/auto-execution incl. real trades at :4918); no counterfactual recorded (main-path QB veto does record; this one doesn't); QB internals include frozen naked stat "SOL RSI < 20 death trap (0% up at 6h)" (`quant_brain.py:1201`)
- Fix: QB verdict → advisory metadata; log would-have-blocked; re-enable only after 2b dollar re-validation. **AUTON**

**D17. TOXIC hard-block: learned rule wired pre-LLM with no provenance/dollar re-validation — currently DEAD via key mismatch**
- Rule: 2b provenance/quarantine
- `bot/multi_strategy_main.py:7663,7685-7714` (`_reg_wr < 10.0 and _reg_n >= 20` → hard-block before LLM); writer `bot/llm/deep_memory.py:378-387` stores no dates/era AND keys `{symbol}_{regime}` while reader looks up `{base}_{side}_{regime}` — formats can never match; live bucket has one n=1 entry
- EV: latent — a loaded-but-misaligned gun; if keys ever align, dirty-era combos become permanently un-tradeable
- Fix: fix key mismatch + blank-regime write; add provenance; dollar re-score; SHADOW until validated. **OWNER**

**D18. Regime priors: hardcoded directional win-prob constants from the condemned n=101 ledger — flag OFF but armed**
- Rule: §2 + 2b dollar re-validation before enforcement
- `bot/llm/regime_priors.py:60,67-74,266` (SHORT.bear 0.60 vs LONG.bear 0.32; COLD_CELL_THRESHOLD=1.0 lets ~1 trade override; docstring admits 71/101 contaminated); USE_REGIME_PRIORS unset ("keep OFF")
- EV: latent — flag-on without rework blocks bear exploration longs (0.32 < EXPLORATION_MIN_WINPROB 0.40) from constants
- Fix (pre-flag-on): re-derive from clean ledger with per-cell n; cold threshold → weighted ~13; shadow first. **AUTON**

**D19. Committee-thesis veto: ungraded LLM opinion can hard-block another LLM's trade — flag OFF; grading exists but is unwired**
- Rule: 3b no-naked-opinions + 2b anchor
- `bot/core/signal_pipeline.py:505-525` (Gate 1.5, reason string is the only payload); `committee_reader.py:86-147` (also sizes 0.0/0.5x on the ungraded vote); thesis_tracker.py grades exist in `bot/data/thesis_grades.jsonl` but nothing reads them at the gate
- Fix: wire graded thesis accuracy (n, era) as a precondition for enforcement; until then labeled context only. **AUTON**

---

## 2. Fallacies that MANUFACTURE fake EV (the risk)

**M1. Hardcoded "proven quant rules" multiply confidence/size from unversioned dirty-era WRs — live, both pipeline paths, feeds CB override (merged: 2 confirmed claims)**
- Rule: §2 directional-opinion + 2b shadow-until-revalidated + 3b stats-without-n
- `bot/core/signal_pipeline.py:117-160,253-264,1007-1017,908-912`; default-enabled `trading_config.py:630-665`, no .env overrides
- Offending: "Morning Edge (06-12 UTC = 75% WR)" ×1.2; "BTC SHORT Edge (67% WR)" ×1.15 on EVERY BTC SELL (pure directional opinion, no condition); "HYPE BUY in High Vol" ×1.2 (sibling of the -$1,120 hype-boost precedent); conviction ×1.3 risk_mult; zero n/era/ledger anywhere; combined up to 1.44x, capped 95, can clear the circuit-breaker conf override (>=92, `risk.py:326`) and tip the 1.5x sizing tier
- EV: permanent pro-BTC-short/pro-HYPE-long bias sizing real capital from a pre-fee-fix era
- Fix: Rules 1-3 → SHADOW (log would-have-boosted, apply 1.0x) until clean-ledger n>=13 re-validation; delete Rule 2 outright; surface underlying stats to LLM with n+era. **AUTON**

**M2. Pre-trade simulator fabricates "EV: $+X → PROCEED" with the plain stop-loss scenario missing — 3 agent prompts, every decision**
- Rule: 3b naked-opinions + honest-stats
- `bot/llm/agents/pre_trade_simulator.py:12-17,63,73-96,207-211`; injected `coordinator.py:1019-1062` → Trade/Risk/Critic (`:3917,4073,4248`)
- Offending: base_case pays full TP1 no-fee; no (1-p) full-SL scenario — losing mass lands in fee-only "chop"; probs hardcoded; recent_win_rate never plumbed so base prob is always 0.50; corr matrix hardcoded "empirical"
- EV: structurally positive EV by loss-tail truncation (honest ~-$5.5 setup renders ~+$7), delivered as a recommendation — the muted-Quant-Brain shape, still running
- Fix: add SL-hit scenario at (1-p) paying -stop×lev×equity-fees; label probs "illustrative, not measured" or mute the EV line until backfit. **AUTON**

**M3. Monte Carlo EV ignores order of hit — SL-first-then-rally counts as a win; prompts call it "Truth. Math."**
- Rule: 3b honest-stats + §1 adversarial pass
- `bot/strategies/probability_engine.py:146-152,197-198,224-231,252-255`; `prompts.py:95` "signals.mc... Truth. Math... If p_tp1 > 0.50 and ev > 0.10 -> strong positive setup... USE THEM"
- EV: win prob overstated by construction (worst tight-stop/long-horizon); momentum-weighted resample bakes recent direction into the "probability"; realized 53% WR / -0.04% avg vs internal +0.10-0.20 EV gate confirms
- Fix: first-passage accounting (first bar SL-or-TP touched); soften prompts.py:95 to labeled context. **AUTON**

**M4. OVERDRIVE steering: "CAPITAL PRESERVATION IS NOT THE GOAL", default-go/default-approve — live, contradicts the selective posture**
- Rule: 3b structure-not-steering + 2b anchor (skip-counts are system-internal)
- `bot/llm/agents/prompts.py:100,113,119,234,830-834`
- Offending: "you have been over-filtering. Bias toward go"; "If... this_symbol_skips > 20... Take the next reasonable thesis as go"; Critic "Default to APPROVE"; Risk "if you skip 3+... you are over-overriding" (count-triggers dormant — live_skip_evidence unwired — but the unconditional pro-go prose is live every call)
- EV: approval driven by the system's own prior refusals, not price truth; pushes marginal volume against the owner-set ~2/day posture
- Fix: neutral framing ("skips are logged and graded against price; decide each setup on evidence"); selectivity dial = labeled env line, not prose. **AUTON**

**M5. HYPE BUY confidence-floor bypass on a hardcoded "88.6% WR from 40K counterfactuals" — no gap cap, no R:R, sizes live**
- Rule: 2b (system-internal stat, no dollar re-validation) + 3b stats-without-era
- `bot/strategies/ensemble.py:704-714` (any HYPE BUY >=55% admitted, risk_mult_override=0.70 consumed at `signal_pipeline.py:816,1299`); codebase elsewhere asserts 44%/31% WR for the same setup (`simulated_agents.py:463`) and prompts.py:283 tells agents NOT to anchor to hardcoded HYPE-EV claims
- Fix: shadow-mode advisory; recompute from clean ledger with n+era; show HYPE SELL base rate symmetrically. **AUTON**

**M6. Agents told to recommend 1.5-2x size to beat a multiplier chain the Risk prompt says was removed — one side is always false**
- Rule: 3b stats-without-n + internal incoherence
- `bot/llm/agents/shared_context.py:631-638,669-675` ("gates kill 91%... ~2.7% of intended risk"; "compensate by recommending 1.5-2x") vs `prompts.py:252-256` ("FINAL position size... Do NOT compensate — they have been removed"); both reach the same Risk call; signal_pipeline.py:692-921 still applies many multipliers
- EV: systematic over-sizing incentive baked into every agent
- Fix: compute the real end-to-end multiplier from live telemetry with timestamp, or delete the compensate instruction. **AUTON**

**M7. EVCalibrator: permanently-RELAXED gate, triple-dead measurement loop, impossible ledger (28 wins / 0 overrides)**
- Rule: 2b (enforce without n>=13 dollar-positive; SHADOW required) + 3b ("50%+ profitable", n hidden)
- `bot/feedback/ev_calibrator.py:40,94-97,153-160`; `multi_strategy_main.py:1023-1031` (no tracker passed; `ingest_outcome` doesn't exist → AttributeError → handle nulled but ensemble keeps the override); state file total_overrides=0/total_override_wins=28; cold-start re-forces RELAXED every restart
- EV: negative-EV signals admitted at 0.5x under a threshold no measurement can revoke (blunted today by LLM_MODE=5; becomes the enforcing path in any low-power mode)
- Fix: wire tracker + real callback; reset contaminated state; start SHADOW until n>=13 dollar-positive overrides. **AUTON** (gate-behavior change → report to owner)

**M8. Backtest engine writes the LIVE calibration state and logs every backtest close as an "override win"**
- Rule: 2b provenance (mixed sim+live population, no ledger tag)
- `bot/backtest/engine.py:296-300,1663-1666` — same `bot/data/ev_calibrator_state.json` the live bot loads; sole production caller of record_override_outcome; source of the impossible 28/0 state; a backtest run can flip the live gate STRICT↔RELAXED
- Fix: backtest data_dir → scratch/in-memory; record only actual override-admitted trades; add {source, ledger_version} to schema. **AUTON**

**M9. RejectionOutcomeTracker grades "missed_profit" by look-ahead best-excursion, missed-takes-precedence-over-stop-out → feeds the calibrator's relax logic**
- Rule: 3b honest-stats + §1 week-1-artifact class
- `bot/feedback/rejection_tracker.py:179-187` (max over 30/60/120/240min snapshots > +1.0% wins even when -0.5% also breached; asymmetric thresholds; no fees) → `ev_calibrator.py:195-205`; sibling `missed_trade_tracker.py:58-61` already does TP1-before-SL correctly
- EV: inflated miss_rate manufactures fake missed-EV, pushing the gate toward RELAXED; contaminates live via shared state file
- Fix: path-ordered SL/TP simulation with fees, symmetric thresholds; re-score backlog before it drives the calibrator. **AUTON**

**M10. Hypothesis validation "edge" bar (40%) sits below the TRUE mechanical baseline (~63/51%) because it anchors to the contaminated 35% — inverted test on 3-trade windows**
- Rule: 3b (broken-ledger stat) + §1 small-n + 2b anchoring
- `bot/llm/self_teaching.py:937-965` ("System baseline is 35% WR — 40%+ for a side = edge"; _calc_side_wr n>=3), runs hourly; validation shifts confidence of served entries
- EV: below-baseline sides "validate" directional-bias hypotheses → fake edges confirmed into knowledge (favored shorts in crash era)
- Fix: use live get_system_baseline (era-matched, USE_MECHANICAL_BASELINE); n>=13 windows; log baseline in evidence. **AUTON**

**M11. Critic told an empty, fee-poisoned dataset is "AUTHORITATIVE... strongest evidence" with a standing "NEVER veto" order**
- Rule: 3b naked-opinions/steering + 2b provenance
- `prompts.py:818,832,936,943` ("IS PROVEN. NEVER veto"; "derived from 3,802 resolved shadow trades"; "0% on 149") vs `comprehensive_snapshot.py:269-275` (_AGENT_SHADOW_EDGES = {} — emptied 06-05 as pre-fee-fix poison; sole source, so validated_edges is always [])
- EV: today burns Critic attention on dead references; any repopulation turns "NEVER veto" into an unconditional auto-approve channel keyed to poisoned provenance
- Fix: replace with "weigh shown wr/n/era"; delete the 3,802 authority claim and the 0%/149 relic; require era+ledger_version on future entries. **AUTON**

**M12. SNIPER MODELS: crash-week dirty winners with broken pnl math served as replication templates (active for strategy discovery)**
- Rule: 3b full-information + honest-stats + 2b anchoring
- `bot/llm/deep_memory.py:781` (pnl/(entry×leverage) → 260.79% artifacts), `:784-788` (was_sniper = outcome only), `:960-969`; live top snipers "ETH SHORT in  (conf=0%, +$1010)", "SOL SHORT in  (conf=0%, +$377)" both 2026-06-03; winners only, no base rate; currently truncated out of decision prompts but reaches research_agent.py:220 untrimmed
- Fix: fix denominator; exclude pre-clean-ledger; show base rate (n, wins/losses) alongside. **AUTON**

**M13. Confidence-tier sizing keyed to fossilized stats; the "22% WR" advisory promised to the LLM is dead wiring; duplicate path still enforces removed penalties (merged: 2 confirmed claims)**
- Rule: 3b stats-without-n + §5 drifted-duplicate + 2b provenance
- `bot/core/signal_pipeline.py:872-904` (×1.5/1.2/1.1 justified by "PF 7.89 (60% WR, +$2,202)" / "-$1,792" from a 10x-equity era; :878 contradicts with "PF 9.77"); `:891` advisory written to metadata nothing ever reads (comment "LLM sees this" is false); `:1338-1359` annotated path still applies the removed 0.4x + double 0.7x/0.5x penalties (diagnostics-only, corrupting filter-accuracy telemetry); confidence_scorer.py:378 pins the same 22% WR on a different bucket
- Fix: recompute bucket WR/PF live with n/era (no multiplier below n=13); wire or delete the advisory; unify paths on evaluate(). **AUTON**

**M14. Seeded folklore axioms (conf 0.9-0.95, 0 validations in 3+ months) always served first in the knowledge block**
- Rule: 3b steering + §2 no-hardcoded-directional-opinion
- `bot/llm/self_teaching.py:403-416,463,530-552`; live: 32 axioms dated 2026-03-23, compaction-exempt; served set includes fabricated stat "3-strategy agreement historically 2x better win rate" (vc=0)
- Fix: demote all 32 to hypotheses or delete; keep only re-derived, n+era-stamped facts. **AUTON**

**M15. "MISSION: Be profitable or die. Precision, not caution." prepended to every agent call (17+ roles)**
- Rule: 3b structure-not-steering
- `bot/llm/agents/shared_context.py:704-707` → `coordinator.py:3316-3325,3386,3396`
- EV: pressure framing inflates reported confidence/go-rates independent of evidence; unmeasured, every decision
- Fix: neutral role statement ("outputs are graded against price; report calibrated probabilities"); A/B against graded thesis accuracy if pressure framing is believed to help. **AUTON**

**M16. get_current_kelly prints full_kelly=1.000 (bet the bankroll) from n=1 into agent enriched context**
- Rule: 3b honest-stats (fabricated precision)
- `bot/llm/agents/dynamic_stats.py:425-455,542-547` → `coordinator.py:819-825`; live line: "ensemble: WR=100% (1 trades), payoff=0.16x, full_kelly=1.000, half_kelly=0.500"; _wr_label guard exists in 5 sibling sections, omitted here
- Fix: apply _wr_label-style n<13 suppression ("INSUFFICIENT DATA — do not weight"); print cleaned_at provenance. **AUTON**

**M17. Kelly engine falls back to 2026-04-12 pre-fee-fix priors (n=7-8), "live" at n=3 — reaches agents via feedback context**
- Rule: 2b provenance + §1 (MIN_TRADES_FOR_KELLY=3)
- `bot/feedback/kelly_engine.py:32,38-45,157,170-176` (header is the literal "35% WR" precedent); mechanical path currently disconnected (multi_strategy_main.py:5990 uses vol-targeting), but prior-tinted fractions reach agent prompts via `feedback_state.py`/`coordinator.py:645-647`
- Fix: stamp priors {n,era,ledger}; pre-fix priors → uniform floor 0.15 until n>=13 clean; raise/shrink MIN_TRADES toward 13. **AUTON**

**M18. Scout seeds direction upstream of Trade with hardcoded symbol/side calls; Overseer told to trust the muted-as-anti-signal quant brain**
- Rule: 3b naked-opinions/steering + provenance falsehood
- `prompts.py:1189` ("SOL extreme oversold = continuation SHORT, not bounce buy"), `:1195` ("HYPE BUY setup" in the HIGH-priority rubric), `:1248` ("quant brain pre-filters... trust its vetoes" — QUANT_BRAIN_ENABLED=false, owner-ruled anti-signal 17% WR); live paths: `_scout_pre_formed` + scratchpad scout_preparation (`coordinator.py:2039,3881-3887`; the :2044-2051 path is dead — keys wiped at :2106)
- Fix: strip symbol/direction lines from Scout rubric (data-conditional phrasing); correct Overseer's system description; clean the dead injection block. **AUTON**

**M19. Insight journal serves the top opinion per category with its evidence field stripped; "validated" = one confirmation**
- Rule: 3b naked-opinions (Quant Brain shape)
- `bot/llm/deep_memory.py:670,687,708-727,950-952`; live top meta insight: "Critic vacc=0%. Veto would destroy expected value (prior veto: +$8.20 missed)" — evidence stored (119 chars) but never served; currently truncated out of entry prompts, live via research_agent; max_tokens param accepted but unused (callers blind char-truncate)
- Fix: serve evidence + validation tally; require vc>=3; fix the truncation/token-budget plumbing. **AUTON**

**M20. Legacy proven-solo whitelist hardcodes "100% WR on 135 shadow signals" from the era the code itself condemns — dormant, silent-reactivation risk**
- Rule: 2b (learned on condemned ledger)
- `bot/multi_strategy_main.py:4851-4856` (_PROVEN_SOLOS: BTC SELL / ETH BUY / SOL SELL) vs `ensemble.py:2334-2341` ("fabricated certainty... SINGLE most impactful injection point"); multi_strategy_main.py:1568-1577 silently flips llm_first_mode=False if prereqs lapse, reactivating it with no flag change
- Fix: delete (LLM-first branch supersedes it) or gate behind clean-ledger recomputation. **AUTON**

**M21. ASSET_DNA injects literal "Edge: None Avoid: None" + unsourced autocorr "personality" into every agent on all 4 symbols**
- Rule: 3b naked-opinions + injection hygiene
- `bot/llm/agents/shared_context.py:135-173,726-729`; note: the "consider fading HYPE" axiom (:114) is dead text (only axioms[:5] served) — impact is the softer "mean-reverting tendency" phrasing + token noise signaling sloppy provenance
- Fix: guard None fields; label autocorr (value, n, window) or drop; delete the dead axiom. **AUTON**

**M22. Win-prob floor gate is inert — reads meta["win_prob"] that is never written; claimed "true noise floor" protection doesn't exist**
- Rule: §5 meta-audit (instrument drift) + 2b (n>=10 sub-standard floor if ever wired)
- `bot/core/signal_pipeline.py:388,394,397,423,433-439` — doubly dead (regime key also never in local meta); root cause: reads local meta instead of signal.metadata (EV gate at :341 reads the right dict)
- EV: none today; distorts the meta-picture — audits believe a win-prob gate exists
- Fix: delete, or wire from signal.metadata as advisory-only (input is the IC≈0 number — see D4) and raise n gate 10→13. **AUTON**

---

## 3. Gate inventory verdict table

| Gate / enforcer | Location | Class | Verdict |
|---|---|---|---|
| Fee/R:R/slippage arithmetic, CB itself, kill-switch | signal_pipeline / risk.py | SAFETY | Keep; keep as labeled LLM context |
| Quant rule boosts 1-3 (morning/BTC-short/HYPE) | signal_pipeline.py:117-148 | OPINION (stale WR, no n) | Shadow now; delete Rule 2 (M1) |
| Rule 4 conviction ×1.3 | signal_pipeline.py:150-160 | OPINION | Shadow until re-validated |
| Graduated-rule vetoes (Gate 1g) | signal_pipeline.py:456-478 | OPINION (keyword-parsed, inverted) | Quarantine ~40 new rules NOW (D1) |
| Slippage >50%-of-stop reject | signal_pipeline.py:359-381 | ARBITRARY threshold on real cost | Advisory until re-scored — OWNER (D9) |
| Win-prob floor (Gate 1f) | signal_pipeline.py:383-439 | INERT (dead read) | Delete or wire advisory (M22) |
| EV floor (Gate 1d) | signal_pipeline.py:341 | OPINION (IC≈0 input); off via MIN_SIGNAL_EV=-3.0 | Keep off; never re-enable on this input (D4) |
| EVCalibrator override | ensemble.py:2451-2462 | BROKEN INSTRUMENT | Reset state, SHADOW (M7/M8) |
| Confidence-tier sizing ×1.5/1.2/1.1 | signal_pipeline.py:872-904 | OPINION (fossil stats) | Recompute with n/era or 1.0x (M13) |
| Time-of-day DEAD/bias multipliers | time_sizing.py:73-105 | OPINION (one April week) | Neutralize 1.0x + shadow (D11) |
| STRATEGY_REGIME_ALLOWLIST + REGIME_MIN_VOTES | ensemble.py:208-236 | ARBITRARY (no per-cell n) | Shadow-log suppressed votes (D10) |
| STRATEGY_REGIME_FIT 'avoid' disabling | multi_strategy_main.py:4747-4758 | OPINION (static theory) | Has shadow ledger; make dynamic |
| TOXIC pre-LLM block | multi_strategy_main.py:7663-7714 | OPINION, currently dead (key mismatch) | Fix keys + provenance, SHADOW — OWNER (D17) |
| Quant Agent noise skip / conf mutation / Kelly size | coordinator.py:1260-1296,4736-4744 | OPINION, zero accuracy gating | Demote advisory — OWNER (D8) |
| QB sniper veto | multi_strategy_main.py:4884-4893 | OPINION (muted engine, unmeasured) | Advisory + counterfactual log (D16) |
| HYPE BUY floor bypass | ensemble.py:704-714 | OPINION (directional allow) | Shadow advisory (M5) |
| Committee thesis veto (Gate 1.5) | signal_pipeline.py:505-525 | OPINION, ungraded; flag OFF | Keep off until grades wired (D19) |
| _PROVEN_SOLOS whitelist | multi_strategy_main.py:4851-4856 | OPINION (condemned ledger); dormant | Delete (M20) |
| Regime priors win_prob | regime_priors.py:60-74 | OPINION (n=101 ledger); flag OFF | Keep off; re-derive before any flip (D18) |
| Prompt-level thresholds (win_prob<0.43, ev<0.10, EV<-2.0 skip) | prompts.py:95,103-105,176-177,333-334 | OPINION smuggled as math | Delete/relabel (D4, M3) |

---

## 4. Fix next — learning engine (all AUTONOMOUS, ranked)

1. **Quarantine the ~40 keyword-graduated rules** (live inverted vetoes/boosts); add {era, n, ledger_version} to GraduatedRule; graduation → n>=13 + dollar-positive; kill the INVALIDATED-graduates path in hypothesis_tracker.py:530-553. (D1)
2. **self_teaching serve-time provenance**: append [n, validated, era, ledger] in get_for_llm_prompt; quarantine pre-2026-07 principles; fix the degenerate relevance filter (`or not regime`); era/max-age + newest-first for hypotheses; dedupe leverage near-dupes. (D6, D12)
3. **Stop n=1 → PRINCIPLE**: learning_integration.py routes 'strong' to HYPOTHESIS; principle promotion only via validation n>=13 dollar-positive; stamp provenance. (D7)
4. **Fix the inverted validation bar**: replace hardcoded 35%/40% with get_system_baseline (era-matched); n>=13 windows; baseline logged in evidence. (M10)
5. **deep_memory integrity**: fix pnl_pct denominator (:781); fix by_symbol_regime writer/reader key mismatch + blank-regime write + add provenance; split PERFORMANCE by exit-type/era; add (n, era) to strengths/weaknesses at n>=13; serve insight evidence + require vc>=3; exclude pre-clean-ledger snipers + show base rates. (D3, D14, M12, M19, D17-prep)
6. **dynamic_stats population symmetry**: is_mechanical() filter (or pooled-vs-pooled) for edge map/regime/OVERALL lines; state population on emitted text; suppress Kelly lines n<13 + print cleaned_at. (D2, M16)
7. **Rejection/calibration loop**: first-touch SL/TP grading with fees (reuse missed_trade_tracker logic); fix the ingest_outcome AttributeError; backtest data_dir → scratch; reset ev_calibrator_state.json; SHADOW cold-start; re-score rejection backlog. (M7, M8, M9)
8. **Probability engine first-passage accounting**; re-run historical signals to quantify the prob_tp1 drop; relabel prompts.py:95. (M3)
9. **memory_store write-time tags** {ts, ledger_version, n:1, source_trade_id} + fix the corrupted-symbol write bug. (D15)
10. **Purge fee-bug-era prompt stats** (prompts.py 105/101-trade blocks + Critic validated_edges NEVER-veto clause + 3,802 authority claim); update pinned tests. (D5, M11)

---

## 5. Refuted (one line each)

- **March-26 backtest as current edge_data/setup_mfe**: plumbing is real (snapshot_builder.py:348-365, coordinator Tier-3 grant) but the `_quant_backtest_2026_03_26` key exists nowhere in live data and has no writer — dead code, never reaches a prompt; clean up to prevent reactivation.
- **Trend-alignment gate mechanically flips direction pre-LLM**: flip exists (ensemble.py:723-741) but the live LLM-first path rebuilds from evaluate_raw() which never calls it; flips are metadata-recorded and counterfactual-logged — legacy/mechanical-fallback path only.
