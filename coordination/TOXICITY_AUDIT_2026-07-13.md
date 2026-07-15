# WAGMI Toxicity Audit — 2026-07-13 (mechanical layer → neural net)

Mission (owner): make the bot idle-safe by finding every silently-wrong data extraction that the mechanical
layer feeds the LLM agents as "fact". 6 adversarial Fable audits (A prompt-stats, B regime/quality, C
learning/veto, D collectors, E call-waste, F reasoning-quality). This doc is the living synthesis; fixes are
batched into ONE restart after review. Nothing here weakens risk/circuit-breaker/exit-safety.

Legend: 🔴 TOXIC (feeds a wrong "fact" to live decisions) · 🟠 moderate · 🟡 low · ✅ clean.

---

## Front D — raw collectors / feeds (COMPLETE)

Collectors' RAW data is mostly CLEAN; the corruption is in **fetcher conversions + prompt formatters**.

- 🔴 **T1 Open interest fed in COIN units, rendered as USD.** `fetcher.py:1047-1069` returns `openInterestAmount`
  (base coin) but `coordinator.py:623-634` `_fmt_oi` prints "$xM/$xB" → BTC OI ≈35,000 → **"$0M"** (true ~$2.1B);
  HYPE "$21M" vs ~$1.4B (65× off). Same prompt also carries the CORRECT USD OI → agents see two contradictory
  magnitudes. Fix: return `openInterestAmount * price` (or `openInterestValue`), matching the collector.
- 🔴 **T2 Hourly funding labeled "%/8h" → permanently "neutral".** `coordinator.py:642-649` prints `%/8h` with
  ±0.02% thresholds, but HL funding is HOURLY (p50 1.1e-5 ≈ 9.9%/yr) → never crosses "crowded"; `external_data.py:427`
  labels the same rate `%/h`. Fix: label `%/1h`, divide thresholds by 8 (or annualize).
- 🔴 **T3 Two "basis" fields, opposite sign conventions, one biased -5bps.** `fetcher.py:1039` `(oracle-mark)/mark`
  (neg=overheated) vs `market_collector.py:214` `(mark-index)/index` (pos=overheated); OKX basis_bps negative in
  5602/5609 records (persistent ~-5bps offset) → fake perpetual discount / bearish tilt. Fix: unify convention,
  de-mean or drop basis_bps from the depth line. (Fetcher docstring `:1016` states the sign BACKWARDS — landmine.)
- 🔴 **T4 Forming/partial candles served as complete.** `fetcher.py:542-567` / `_aggregate_ohlcv:650-669` keep the
  in-progress last bar; disk cache shows a daily candle 25% formed served as "close". Corrupts RSI/ATR/MC-zones +
  bakes look-ahead into backtest caches. Fix: drop last row when `open_time + tf > now`.
- 🔴 **T5 5-second "tape" (last 10 trades) fed as "the tape"; honest `taker_15m` has ZERO consumers.**
  `market_depth.py:209-215,266-270` uses `trades` (trade_count==10 always, buy_ratio pure noise) though the
  collector itself says "muted — use taker_15m". Fix: source the tape block from `rec["taker_15m"]`.
- 🟠 **T6 mark/funding/OI up to 30-60min stale, unlabeled, cached FOREVER on fetch failure** (no TTL).
  `multi_strategy_main.py:3262-3302,3446-3453`. Fix: store `(value, ts)`, skip injection when age > ~15min.
- 🟠 **T7 funding_oi collector: per-symbol silent dropouts** (XRP missing 141 ticks) + single-process no-watchdog.
  Fix: move to the scheduled-task `--once` pattern like market_collector.
- 🟠 **T8 CoinGecko fallback fabricates volume (24h-rolling summed) + zero-range candles.** `fetcher.py:714-747`.
  Fix: mark `df.attrs["synthetic"]=True`, skip volume/ATR gates when set.
- 🟡 **T9 dead staleness API** (`fetcher.py:253-268`, no callers) + only 5m/1h TF staleness-guarded (4h/6h/daily
  never checked). Fix: wire `is_data_stale` to candle timestamps.

✅ Clean: L2 spread/mid/depth/imbalance (zero collector gaps, 15min cadence), long_short_account_ratio (source-ts
dedup works), funding_oi values (plausible ranges), reader auto-mutes (depth 45min, funding 2h), market_ctx fields
populated (no NameError). **Corruption is conversions/formatters, not the raw feed.**

---

## Front A — prompt-injected stats / edge_data (COMPLETE)

GOOD NEWS: the PRIMARY live edge block `dynamic_stats` (CURRENT EDGES/regime/calibration, coordinator.py:872) is
CLEAN — recomputed from fresh trades.csv, stale-gated (kelly_weights 36d excluded), hand-verified. Mechanical
baseline + trades.csv pnl (net of fees) correct. The toxicity is in the SECONDARY quant/edge/fallback layers:

- 🔴 **A-T1 Corrupted legacy pnl_pct poisons the Quant package (Kelly/fat-tail) to Quant+Trade agents.**
  `quant_data.py:29-37` `_get_trades` returns ALL trade_dna rows, no era filter; 7 pre-M12-fix rows have
  `pnl_pct = dollars/price` (e.g. −3.4% move logged as **−904.26%**). Distorts avg_loss to 46% (clean 3.51%),
  Kelly ~9-13×, fabricates a +14.5× payoff cell. Injected every entry. Fix: drop rows `abs(pnl_pct)>50` or pre-fix
  epoch in `_get_trades` (read filter, no risk code).
- 🔴 **A-T2 Regime fallback always fabricates "range" (key mismatch).** `coordinator.py:3705-3757` reads
  `pct_24h/chg24h` but snapshots write `d24h` → pct all 0 → `avg_move<1.0 → "range"` ALWAYS fires; overwrites
  agent's `unknown` with `range` conf 0.5. Applied at :997-1006. Fix: read `d24h` (or keep `unknown` when all-zero).
- 🟠 **A-T3 "THE KEY DATA" is permanently empty + is_toxic still miskeyed.** `_quant_backtest_2026_03_26` has NO
  writer (your FALLACY_AUDIT flagged it) → edge_data/historical_edge/setup_mfe always {} though prompts.py:1820
  calls it "THE KEY DATA"; CONFIRMED_EDGE fast-path dead. Also `multi_strategy_main.py:7984` reads
  `ensemble.by_symbol_regime` (1 trade, bucket "HYPE_") not the per-strategy fingerprints the 07-02 fix populated →
  `is_toxic` constant False, "now fixed" comment wrong. Fix: repoint reader to per-strategy fps / delete dead keys.
- 🟠 **A-T4 g.edge = one ""-keyed pooled 36% bucket.** `llm_integration.py:562-574` builds setup_edge_map but
  setup_type empty for 168/180 trades → every setup shows same pessimistic 36% WR, defeats the ">60% → size up"
  rule by construction. Fix: skip empty setup_type keys (→ honest {} + regime×strategy fallback activates).
- 🟠 **A-T5 Exit/Critic prompts hardcode stale backtest claims as current fact.** prompts.py:1163-1175 ("cutting
  losers in first 2h is the single largest leak") + Critic %s (:990-1004) — frozen, no as-of date, contradict the
  file's own "no hardcoded numbers" header; LLM_EXIT closes are 8.8% winners all-time. Steers exits. Fix: date/label
  or move to dynamic_stats (prompt-text only → adversarial-review before ship).
- 🟡 **A-T6 comprehensive_snapshot.py = unused prototype** (only tests import it) with latent bugs (MACD line not
  histogram; MFE/MAE side-blind swapped for shorts; _adx unsmoothed). Dead code — keep it out of any wiring.

✅ Clean: dynamic_stats block, regime_priors/mechanical baseline, deep_memory summary, shadow-edges (dead),
trades.csv pnl semantics.

## Front B — regime + signal-quality (COMPLETE) — highest live-decision impact

- 🔴🔴 **B-T1 The "ADX" gating every decision is raw single-bar DX, not smoothed ADX.** `quant_regime.py:108-111`
  returns `dx` (comment even says "approximation"). corr(quant, Wilder ADX)=**0.34**; ~**24% of hours in the wrong
  trend/range bucket**; label flips **32%/bar**; live ADX reads 1.7/2.8/5.4 (impossible). Feeds ensemble regime
  allowlist, REGIME_MIN_VOTES (2 vs 3), SELL SL-widen, conf floors, 4h-align, quality buckets → **every** decision.
  Fix: delegate to the correct Wilder ADX in `llm/agents/mech_regime.py` (env-flag the old body). Sub-bugs: forming
  candle → intra-hour regime flap (8-11%); ATR-percentile methodologically inconsistent (33% of ticks labeled
  high_vol/panic → blocks trend strategies); dead-code direction branch (:200-206).
- 🔴 **B-T2 Validated high-vol overlay is DEAD; the unvalidated variant is ON.** `mech_regime` fed only `tail(50)`
  (llm_integration.py:300) but ATR-ptile needs ≥100 → always None → RQ10 high-vol override NEVER fires (once in
  whole log). Also the overlay HARD-overrides (docstring claims additive-only — lie). `.env MECH_REGIME_OVERLAY=true`
  is the UNVALIDATED A/B arm. Fix: `tail(400)` (or compute pre-truncation); flip `MECH_REGIME_OVERLAY=false`.
- 🔴 **B-T3 Swallowed TypeError kills 3 learners + quality multiplier applied TWICE (squared).**
  `multi_strategy_main.py:3790` calls `record_outcome(features_key=...)` but sig is `record_outcome(features,...)`
  → TypeError swallowed at :3818 → `parameter_tuner` (:3796) + `continuous_backtest` (:3806) after it in the same
  try NEVER run on trade close. Two quality-scorer instances both fire (main:667 + main:976) → boosts/penalties
  squared. Dead `side` dim (LONG/SHORT recorded vs BUY/SELL queried → losing longs never penalize buys). Fix:
  delete main:667; fix :3790 to build QualityFeatures (or drop — :3866 records correctly); map LONG/SHORT→BUY/SELL.
- 🟠 **B-T4 Strategy-weight learning is fiction.** 98% of mass in phantom `""` (98%WR) / `"ensemble"` (94.7%WR)
  keys stuffed with SYNTHETIC wins (`learning_integrator.py:154-163`); real strategies frozen at 0.30 floor →
  uniform ≈ unweighted voting. Self-neutralizing today but reports built on it are corrupt + loaded gun. Fix:
  reject `strategy in ("","ensemble")` in record_outcome; env-gate synthetic writes (default off).

✅ Clean: `mech_regime.compute_mech_regime` math correct (just starved of bars); ensemble veto mechanics
(soft-veto, opposition cap, deep-copy, _flip_signal geometry) sound; `_merge_signals` level/R:R math correct;
signal_quality Bayesian prior + 0.5-1.3 clamp sane.

## Front C — learning / graduated-veto integrity (COMPLETE)

Corruption reaches BEHAVIOR only via (a) veto counters (F1-F7) and (b) LLM prompts (F10). Risk gates / circuit
breakers / confidence-calibrator run on REAL closed-trade pnl and are UNTOUCHED. Active rules: 4 (sol_long_veto_v1,
illiquid_regime_penalize_v1, btc_short_conf70_80_penalize_v1, btc_short_90plus_boost_v1).

- 🔴 **F1 Resolver fix NOT enabled → corruption continues daily.** `.env` lacks `CF_RESOLVE_TIME_BASED`; legacy
  8.9h-median bar-counting is live; 413 new sol_long_veto scorings in last 7d on the broken window. Fix: add
  `CF_RESOLVE_TIME_BASED=true` to `.env` (THE #1 fix — stops the bleed). [also = staged resolver enable]
- 🔴 **F2 Garbage-priced counterfactuals permanently killed a GOOD veto.** `record_veto_counterfactual`
  (`counterfactual_learner.py:370-462`) has NO price-sanity check → `hype_long_veto_v1` got 10 records stamped
  entry=$25 (real HYPE ~$63) → instant TP2 "+16% missed" ×10 → auto-retired (true blocked-loser rate 88.9%). Ledger
  has NO unretire API → permanent. 131 instant(<1h) |pnl|≥8% resolutions globally. Fix: force `denominator_only`
  when stamped entry deviates >5% from current close (1 line); add owner-only unretire tool.
- 🔴 **F3 Hardcoded SOL+BUY block SILENTLY FIRING live (owner-forbidden), divergent from its "shadow" measurement.**
  `sol_long_veto_v1` = {SOL,BUY} no conditions. Provenance-gated (shadow) at pre-filter `coordinator.py:1786` ✔ but
  ENFORCED with no provenance/LLM-override at `_merge_outputs` `coordinator.py:5148-5155` (`if _vetoed: action=flat`)
  → LLM-approved SOL longs silently flattened. Fix: apply the 2b-provenance guard / LLM_FIRST override before
  `action="flat"` at :5153.
- 🟠 **F4 9h-drift timeouts corrupt the one live veto's counters** — sol_long_veto real hard-resolution accuracy
  97.5% (345/354, net +516%) shown as 64% due to 370 premature timeouts adding fake "veto wrong". Bias = makes good
  vetoes look bad → drives retirement. Fix: enable F1 then rescore via `tools/backtests/veto_rescore*`.
- 🟠 **F10 KB prompt contamination from the same resolver.** `knowledge_base.json`: 47 `[FILTER_MISS] consider
  relaxing this filter` + a retired rule's `[AVOID]` entry, injected via `coordinator.py:3268 problem_filters` →
  nudges agents to loosen filters on 9h-drift pseudo-winners. Fix: purge KB entries whose rule_id is retired; pause
  `_maybe_write_kb_entry` until F1 on.
- 🟡 **F5** both-hit TP1/SL scored WIN (178 recs, 0 veto-stamped today) → score `won=None`. **F6** no dead-zone
  (+0.01% = "veto wrong") → neutral band |pnl|<0.5%. **F7** shadow fires enter veto denominator → separate
  shadow_applied fields. **F8/F9** retired rules still accrue (cosmetic); lifetime (not rolling) retirement test.

✅ Clean: retirement-ledger enforcement + load-time re-retire; 52 keyword rules all inactive (quarantine holds);
arming enforces n≥13 + lands active=False (manual promotion only); feedback tuner / adaptive floor (20-80, ±5/day)
/ confidence calibrator all fed by REAL pnl, NOT counterfactuals. Nothing weakens risk/CB.
## Front E — wasted / redundant LLM calls (COMPLETE) — ~1,590 calls/day, 34-56% recoverable

All reversible, none touch risk/exit-safety logic. Entry brain (the part that TRADES) = ~520 calls/day, lean, output
consumed. Waste is in advisory side-paths:

- 🔴 **E1 PRE_CLOSE metabrain = ~495 calls/day (31% of ALL quota) with structurally ZERO actionable output.**
  Trigger `multi_strategy_main.py:3498` → full 5-agent pipeline (`llm_integration.py:869`) ~125×/30h → 113 flat,
  12 proceed — **12/12 rejected** by conf<0.60 gate (`risk_gating.py:76`). Even an allowed proceed only logs/caches
  (entries execute ONLY via LLM-FIRST path). Fix: `DISABLE_LLM_TRIGGER_PRE_CLOSE=1` (`triggers.py:21`). −495/day.
- 🔴 **E2 Exit agent re-asks a settled question every 2 min — ~485/day, ≥60% redundant.** `position_wiring.py:752`
  every `EXIT_EVAL_COOLDOWN_S=120`s (`exit_engine.py:36`); 209 full_close recs, **0 executed** (blocked post-LLM by
  validated safety gates), same position re-asked (HYPE: 41 identical). Fix: `EXIT_EVAL_COOLDOWN_S=600` + block-aware
  backoff (skip until price moves ≥0.3% / regime/PnL-sign flips). −250-350/day. **⚠️ RECONCILE:** my item-2 throttle
  added `EXIT_AGENT_COOLDOWN_S` to `_run_exit_agent_checks` (llm_integration.py:1135) — a DIFFERENT path than the live
  612-call one (position_wiring.py:752). The real live lever is EXIT_EVAL_COOLDOWN_S. Fix both / the right one.
- 🟠 **E3 Overseer = pure overhead: 291 recs/30h, 0 applied.** `growth/orchestrator.py:452` every 30min; only reader
  is the report file. Fix: `AGENT_OVERSEER_ENABLED=false`. −46/day.
- 🟠 **E4 Quant agent ~200/day, verdicts shadow-discarded** BUT its analysis IS injected as Trade/Risk context.
  "Measure first" — A/B its context value before `AGENT_QUANT_ENABLED=false`. (mechanical `compute_quant_context`
  already computes EV/kelly LLM-free.)

✅ Right (don't touch): COOLDOWN-DROP is PRE-LLM (saves ~2,400 calls/day), SafetyFilterChain pre-LLM (461 dup-blocks
before the coordinator), entry go-decisions execute (16/17 → FILL, 0 post-go rejections), R5 degraded-guard 0
firings, old post-LLM entry gates demoted to shadow (May-31 classic fixed), learning agent consumed, background
thinker zero-API.

## Front F — reasoning / thesis quality (COMPLETE) — the NET is healthy; the scaffolding inverts it

GOOD: agents cite injected data (kelly/EV 79%, edge_data WR 71-80%, technicals 66%), write concrete falsifiable
theses ("SOL breaks $75.50 toward $74, invalidate above $77"), real cross-agent argument, Critic vetoes require
falsifiable structure. Reasoning is the healthiest layer.

- 🔴 **F-2 NET_CAL = constant −15pp tax gates out the agents' approved path.** `network_learning.get_calibration_
  adjustment()` compares ENSEMBLE conf (64.8) vs outcomes (35% WR) → −0.30 capped −0.15, subtracted from the TRADE
  agent's honest 0.35-0.45 → every proceed lands 0.26-0.37 → rejected by `risk_gating.py:76` (<0.60). Appears
  488/488. THIS is why E1's 12/12 proceeds die. Fix: separate ensemble-conf from agent-conf (or make log-only).
  [behavioral → validate]
- 🔴 **F-1 Thesis grading has NEVER run — 772/772 pending.** `coordinator.py:1608` appends `thesis_id=` to notes
  END, but `multi_strategy_main.py:8454` truncates notes `[:500]` → id cut off → grader (`:4156`) finds 0. So
  thesis-accuracy block never injected; agents fall back on confounded counterfactuals. Fix: carry `thesis_id` as
  its own `entry_reasons` key + pass target_price/expected_hold_h through record_thesis. Data plumbing (no prompt
  change). Highest value-per-line.
- 🟠 **F-3 Two contradictory agreement-counts injected every call.** `_compute_confluence_from_snapshot`
  (coordinator.py:5430) reports "1strat solo" in 178/178 while num_agree says 2-3 in 29 → constant falsehood
  depressing conviction. Fix: source confluence.count from `signal_metadata.num_agree` (or drop block).
- 🟠 **F-4 Exploration dominates entries + poisons learning (NEEDS OWNER).** 39/56 July entries were ε=0.40
  overrides taken AGAINST the agents' skip; skip-rationale stored as "thesis" (anti-thesis); exploration outcomes
  flow into pattern/WR/lesson tables → learns from rejected trades. ε itself owner-authorized; contamination isn't.
  Fix: tag/weight-down EXPLORATION in WR/lesson extraction; stop storing skip-rationale as thesis.
- 🟡 **F-5** ~2k redundant tokens/call (duplicate `enriched` blob vs named fields; prompt says "prefer named"),
  dead `g.cf` ({} in 400/400), never-cited blocks (mark/basis, session_perf, sim) → flag-gated trim.
  **F-6** consistency checker = 0.95 in 751/757, never fires, doesn't check real contradictions.
  **F-7** agent_output_logger dead (agent_outputs.jsonl absent); theses truncated 80-char in permanent record.
  **F-8** Exit agent proposes impossible partials (not told min lot size).

✅ Clean: OBSERVE→RECALL protocol produces genuine chained reasoning; downstream agents consume upstream output;
Critic veto structure enforced; sampled end-to-end trades (HYPE +$6.87) had coherent thesis→sizing→exit chains.

---

# ════════ SYNTHESIS & STAGED FIX PLAN ════════

**Master finding:** the 9-agent NET is sound. A vast mechanical layer feeds it wrong "facts" (A,B,C,D), wastes
~half its calls (E), and gates/overrides its good output (F). Fixing the scaffolding unlocks the healthy net AND
makes it idle-safe. **Containment verified:** risk gates, circuit breakers, and the confidence calibrator run on
REAL closed-trade pnl — untouched by all of this. Everything below is reversible; nothing weakens risk/CB.

## BATCH 1 — quota flags — ✅ SHIPPED + RESTART-VERIFIED 2026-07-13 ~15:33 UTC
- `DISABLE_LLM_TRIGGER_PRE_CLOSE=1` (E1, −495/day) — VERIFIED: 0 pre-close triggers since restart.
- `EXIT_EVAL_COOLDOWN_S=600` (E2, −250-350/day). (Item-2 also throttles the 2nd path `_run_exit_agent_checks`
  via EXIT_AGENT_COOLDOWN_S=600 — BOTH live exit paths now throttled: position_wiring.py:752 + llm_integration.py:1135.)
- `AGENT_OVERSEER_ENABLED=false` (E3, −46/day) — VERIFIED: "overseer agent disabled" in startup log.
Restart: bot pid 9364→3372, 0 errors/tracebacks, LLM-FIRST ACTIVE, equity preserved $4942.83, positions reconciled.
Also activated this restart: exit throttle (item 2), collector-stale alert (finally live), runtime degrade detector.
Resolver fix present but OFF (CF_RESOLVE_TIME_BASED unset — Batch 3). Revert Batch 1: delete the 3 .env lines.

## BATCH 2 — correctness (fix lies→truth; code, flag-gated, validated each):

- ✅✅ **B-T1 real ADX — SHIPPED + LIVE + VERIFIED (`QUANT_REGIME_TRUE_ADX=true`, restart pid 20572, 17:13 UTC).**
  Downstream-safety review: SAFE — thresholds were calibrated on correct-ADX-style labels all along (backtest engine
  + 4h regime use proper smoothed ADX; the buggy 1h DX was the outlier). REGIME_MIN_VOTES is dead code, dynamic
  floors key off a different label system, SL-widen is risk-normalized (wider stop→smaller position), learned
  per-regime stores are advisory/shadow/dead. LIVE PROOF: ADX now 14.9-36.4 (was 1.7-5.4 garbage), SOL/XRP correctly
  "trend", ETH "range", 0 errors, equity preserved. Watch: solo-bypass freq + SL-widen rate first days. Revert=false.
- ✅ **D-T1 OI units — SHIPPED + LIVE (`data/fetcher.py` fetch_open_interest, restart 17:13 UTC).** Returns USD
  notional (openInterestValue, else coin×price) not raw coin count → no more "$0M". Code fix, revert=git. OI value
  in prompts verifies on next pipeline.
- ~~staged flag-OFF, ENABLE pending review~~ (was:) **B-T1 real ADX — CODE DONE + VALIDATED.**
  `core/quant_regime.py` `_adx` now delegates to the validated Wilder ADX in `mech_regime.compute_mech_regime`
  (lazy import, falls back to legacy DX on any failure). **Validated** (scratchpad/validate_adx.py, real BTC 1h, 492
  windows, independent textbook-Wilder reference): legacy corr **0.34** / 11% impossible <8 readings → new corr
  **1.000** / 0% garbage (matches reference exactly). ⚠️ **Behavioral: 34% of regime labels change** (mostly
  range→trend — raw DX under-detected trends). Do NOT enable blind: downstream allowlist/vote-count/SL-widen may be
  implicitly tuned to the BUGGY range-heavy distribution → needs a downstream-interaction check + owner nod before
  flip. Revert: `QUANT_REGIME_TRUE_ADX=false`.
- ⏳ TODO: OI units ×price (D-T1) ‖ funding %/1h (D-T2) ‖ basis sign unify (D-T3) ‖ drop forming candle (D-T4) ‖
  filter corrupted pnl_pct (A-T1) ‖ regime-fallback key d24h (A-T2) ‖ thesis_id plumbing (F-1) ‖ confluence from
  num_agree (F-3) ‖ NET_CAL un-tax (F-2, behavioral→validate).

## BATCH 3 — learning/veto integrity (flag-gated): enable resolver CF_RESOLVE_TIME_BASED (C-F1) ‖ SOL merge-site
provenance guard (C-F3, stops hardcoded block) ‖ price-sanity + unretire tool (C-F2) ‖ both-hit/dead-zone/shadow
scoring (C-F5/6/7) ‖ KB purge + pause writer (C-F10) ‖ exploration learning hygiene (F-4).

## BATCH 4 — cleanup/owner-review: dead `_quant_backtest_2026_03_26` readers (A-T3) ‖ g.edge empty-key (A-T4) ‖
exit/critic hardcoded claims (A-T5) ‖ strategy-weight phantom keys (B-T4) ‖ context trim (F-5) ‖ consistency
checker (F-6) ‖ agent_output_logger wiring (F-7) ‖ collector robustness (D-T6/7/8/9).

**Execution:** ship BATCH 1 now → implement BATCH 2/3 code (validated) → ONE restart activating everything +
staged EXIT throttle + resolver → VERIFY health/behavior → BATCH 4 + owner-review items follow. Loop paused.

---

## Fix batch (staged, activate on ONE restart after synthesis)
- Resolver time-based fix `CF_RESOLVE_TIME_BASED=true` (+window), exit throttle `EXIT_AGENT_COOLDOWN_S=600`.
- D fixes: T1-T5 (correctness, likely flag-gated behavioral), T6-T9 (robustness).
- (More from A/B/C/E/F.)
