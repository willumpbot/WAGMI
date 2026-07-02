# MORNING BRIEF — 2026-07-02
Everything from tonight in one place. Reports: WIRING_AUDIT, THESIS_AUDIT, THESIS_GRADES, MISSED_EV_LOCKDOWN, MASTER_PLAN (all in coordination/).

## WAKE-UP UPDATE (overnight wave 2)
Written ~04:10 UTC. Everything below the "WHAT GOT FIXED TONIGHT" line is wave 1 (unchanged history). This section is what happened after you slept.

### 1. Shipped overnight (spine → approvals → ship-list → fallacy burns)
**Spine hardening + standard:**
- WIRING_INVARIANTS.md (10 testable invariants) + `check_invariants.py` leak detector — first run caught a P0 rules-file clobber + the equity divergence. (e89f054)
- THE_STANDARD.md v1→v1.3 — evidence/change/learning standards; v1.1 = your directive: validated+reversible ships autonomously, you get results not requests; v1.2 = learned-rule provenance/quarantine; v1.3 = LLM-input standard (honest stats only). (0528f95→0448739)
- HOLES.md master registry — 84 distinct holes tracked, deduped, lane-tagged. (c09e7a2)

**Your 6 decisions from the section below — ALL EXECUTED under v1.1 (do not re-answer them):**
- D1+D4: exploration sized through risk_mgr.calculate_qty at 0.1x risk — kills the $628-tight-stop class. (1b42b53)
- D2: hype_long_veto restored + counters reset. (6279a70)
- D3: exit geometry backtested (12-variant replay + 2.5-year sim, n=1,131) → shipped as S1/S2 below.
- D5: LLM-first entries now submit exchange orders before position registration. (c9f9eed)
- D6: pytest no longer clobbers prod state; equity drift sentinel; equity trackers unified — heartbeat and persisted both read $1,943.42, 0.0% divergence. (28f02e9, 6279a70)

**Ship-list (all flag-gated/env-tunable, watch window = next 15-20 closes):**
- S1: restored Apr-1 profit-lock ratchet (BE 0.3R, lock 0.3R@0.6R) + post-TP1 floor fix — +$1,589 backtested; 2.5y sim: beats current+naive in EVERY year/symbol/side. (3dedd38, 3ce6127)
- S2: un-pinned TRAILING_STOP_ATR_MULT. (333aebe)
- S3: cut-only confidence sizing ladder — conf 60-79 → 0.15x, NO 80+ upweight. (3d2283f)
- S4: retired 8 dollar-negative graduated rules (BT_VETO_RESCORE dollar re-score of all 59). (a095eb0)
- S5: muted stale-kelly prompt injection (7-day staleness gate). (c25f8d5)

**Goldmine (160k records mined: 79k rejections + 56k signals + 24k agent calls → GOLDMINE_2026-07-02.md):** the problem is upstream signal generation, not gates; confidence doesn't rank outcomes (anti-signal above 70); only REGIME has skill; 12 hypotheses killed and logged.

**Fallacy audit (FALLACY_AUDIT_2026-07-02.md): 30 claims audited, 28 confirmed → 8 autonomous fix batches shipped:**
- Fix 1: quarantined 44 keyword-graduated rules (incl. provably inverted vetoes/boosts firing live); durable retirement ledger; graduation now shadow-only until n>=13 dollar-positive. (69ada2a, df8bf64)
- Fix 2: self_teaching serve-time provenance [n, validated, era]; pre-July unvalidated "principles" quarantined; degenerate relevance filter fixed. (6dbbc01)
- Fix 3: single-trade "strong" lessons enter as n=1 HYPOTHESIS, never permanent PRINCIPLE at conf 0.80. (afc1ed8)
- Fix 4: hypothesis validation bar anchors to live era-matched baseline (was hardcoded 40% vs contaminated 35% — inverted test). (7fbd350)
- Fix 5: deep_memory integrity — PERFORMANCE split by exit-type/era (the "26% WR" self-distrust line is dead), pnl% denominator, key mismatches. (1bea70f)
- Fix 6: dynamic_stats population symmetry — no more profitable-setup-labeled-TOXIC; Kelly lines suppressed at n<13. (c1c968f)
- Fix 7: rejection/calibration loop — look-ahead "missed_profit" grading replaced with first-touch SL/TP + fees; backtest no longer writes live calibrator state; contaminated 28/0 state reset. (71acd8c)
- Fix 8: Monte Carlo first-passage accounting — TP counts only if touched BEFORE the stop; "Truth. Math." prompt cutoffs removed. (791ea86)

**Wave-2 research lanes (the 4 that just landed):** RQ9 exit-agent skill, RQ10 regime accuracy, RQ17 fee drag, RQ18 golden era — results in §3. Plus earlier overnight: RQ11-16/20/21 mass-research pass, DATA_CENSUS (97 artifacts), RQ28 market-data expansion collector (L2 depth/tape/OKX ctx accruing every 15min), BT_ADX_SURVIVOR (the missed-EV "survivor" FAILED forward-validation — W23 artifact, do not encode).

### 2. Owner decisions — the consolidated list (9 items, deduped; the old 6 below are DONE)
Gate-stack changes per THE_STANDARD v1.1 — these wait for you; everything else already shipped.
1. **volume_chop gate: remove or re-threshold** — fires on a broken 0.0 input, 59% of all rejections, uniquely blocked +36.6bps/24h signals. Evidence: GM_GATE_ROC_56K.md. Lean: fix input wiring (autonomous), then REMOVE; shadow-log a week.
2. **CRITIC veto → shadow mode** — veto value is a week-1 artifact; mid-era ordering INVERTED (vetoed −79 vs approved −196bps). Evidence: GM_AGENT_SKILL_24K.md. Lean: shadow, auto-restore if shadow scoring turns dollar-positive.
3. **Delete dead gates** (trend_alignment: 0 firings in 52,954 evals; rr/fee/ev floors unwired). Evidence: GM_GATE_ROC_56K.md. Lean: delete — it's wiring cleanup that happens to touch the gate stack.
4. **Confidence floors incl. the 65-ceiling idea** — floors 66/71 actively select TOWARD the worst slice; but no threshold makes the stream positive anyway. Evidence: GOLDMINE §2. Lean: NO change now — S3 cut-only ladder already covers the downside; revisit after 15-20 clean closes.
5. **Quant Agent demotion (fallacy D8)** — ungated ±0.15 conf mutation, forced skips, Kelly sizing, zero accuracy gating, runs AFTER Critic. Evidence: FALLACY_AUDIT D8. Lean: demote to advisory + shadow-log until dollar-scored n>=13.
6. **Slippage gate (fallacy D9)** — hard-rejects pre-LLM at its own measured 44.6% accuracy (blocks winners more than losers). Evidence: FALLACY_AUDIT D9. Lean: advisory until fresh dollar re-score.
7. **TOXIC pre-LLM block (fallacy D17)** — currently DEAD via key mismatch; a loaded-but-misaligned gun. Evidence: FALLACY_AUDIT D17. Lean: fix keys + provenance, SHADOW-only, never enforce without dollar re-validation.
8. **Exit-agent full closes: restrict to its real skill** — closes are 0/57 net-positive across ALL eras (fee-guaranteed losers, median move ≈ 2× fees) while tightens are genuinely protective (18/21, 0 premature in E3). Evidence: RQ17_FEE_DRAG.md + RQ9_EXIT_AGENT_SKILL.md. Lean: keep tighten/partial, raise the full-close bar; backtest the restriction first.
9. **Limit/maker exits** — W1 maker fills ran 1.4-5.7bps vs 10.4bps taker floor; halves the round trip. Evidence: RQ17_FEE_DRAG.md. Lean: backtest-first, then flag-gate on non-urgent exits.

### 3. New knowledge (wave-2 lanes, one line each)
- **RQ9 (exit-agent skill):** WASH — net −$346@24h vs mechanical null, carried by one bad ETH close; "0/71" was a denominator error (real: 51-57% correct closes); tightens are the actual skill; killer gap: HOLD decisions are never logged (0 records).
- **RQ10 (regime labels):** the agent is a decent DIRECTION oracle (54.0% vs mech 40.2%) inside a poor regime CLASSIFIER (trending precision 12.7%, below base rate; confidence inverted); cheapest validated upgrade = mech ATR-ptile/ADX hybrid overlay, accuracy .600→.652 era-stable — shipping next (prompt-input change, autonomous).
- **RQ17 (fee drag):** floor = 10.4bps round-trip uniform across symbols; need ~40bps move for fees ≤25% of gross; fees are NOT the killer ex-W1 ($85 vs −$712 gross) — except LLM_EXIT_AGENT closes (0/57); NEW integrity hole: 35 ledger rows Jun 2-10 have blank fees (~$90-360 understated).
- **RQ18 (golden era):** June 1-6 was ONE era of regime BETA, not alpha — passive 2x short matched the bot; the "+$1,756 pre-May" premise is FALSE (old bot = −$3,715); what's real is the loss side (LONGs 4/28 lifetime, chop-trading −$796); "short the high-rv bear leg, stop when it dies" survives only as an n=2 hypothesis with falsifiers logged.

### 4. Live status (as of 04:07 UTC)
- Bot ALIVE — pid 41040, scan 73, errors 0, equity **$1,943.42**, heartbeat + persisted agree (0.0% divergence).
- Invariants: **6/7 PASS, 1 FAIL** — one unlabeled close since the spine cut (XRP SHORT 03:58, −$0.52); label path needs a look on the 2-per-day cadence, queued as an autonomous burn.
- Clean closes accrued toward the 15-20 ground-truth sample: **2** (BTC LONG −$0.13 02:27, XRP SHORT −$0.52 03:58 — both small, both CLEAN_LOSS, both honestly recorded).
- hype_long_veto ACTIVE (16/16 vetoes dollar-aware); funding/OI collector alive (16m); RQ28 expansion collector accruing.
- Replay harness: **no REPLAY_RUN_*.md exists yet** — counterfactual replay of the shipped exit stack has not produced output; it's next in the autonomous queue behind the invariant FAIL.

**Read first:** GOLDMINE_2026-07-02.md — it reframes everything (the problem is upstream signal generation, not gates), and decisions 1-4 above fall straight out of it.


## WHAT GOT FIXED TONIGHT (shipped, tested, bot running on it)
1. **Partial-close PnL black hole** — banked partial profits now produce real accounting (fee/leg-PnL/equity/TradeEvent). Was: qty reduced, profit invisible, win/loss labels inverted.
2. **Liquidation-avoid closes** — no longer discarded; reach equity/ledger/learning.
3. **THE ledger killer found+fixed** — parallel symbol scans were deleting *each other's* closing positions mid-pipeline (why 7/01 had 11 closes but 2 rows). Cleanup now symbol-scoped.
4. **Honest labeling** — exploration entries recorded as EXPLORATION (llm_agreed=false), never "LLM approved"; pipeline failures no longer feed veto stats.
5. **Thesis loop closed** — side recorded truthfully (was BUY on 209/209), theses auto-grade on close from price facts.
6. **Dollar-aware veto retirement** — retire needs acc<0.35 AND net_pnl_saved<=0 (was hit-rate only, which killed money-saving vetoes). hype_long_veto NOT restored (your call below).
7. **Quant Brain muted** (QUANT_BRAIN_ENABLED=false) — your call, confirmed right: it was a hardcoded pre-filter vetoing signals before Claude saw them, self-trained on the broken ledger, anti-signal when cited (17% WR).
Tests: 3499 pass; ~60 failures all pre-existing (verified vs baseline worktree). Bot restarted clean (pid 28884).

## WHAT THE GRADING PROVED
- **Thesis scoreboard (230 graded vs real price):** 54% right @24h; shorts 56% vs longs 48%; HYPE theses anti-signal (18%); **confidence inverted** (conf 30-44: 67% right; conf 60-74: 43%) — same inversion as trade outcomes.
- **Missed-EV = ARTIFACT.** 80% of "skipped winners" were week-1 (May30–Jun5) skipped shorts during the crash. Post-Jun-6 the agent's regime-skips correctly skip losers (~12% would-win). **Do NOT loosen agent caution** — it's earning money. Only survivor worth forward-testing: trend-continuation in confirmed high-ADX trends.
- Third+fourth thesis-writer bugs found: symbol field wrong on ~40 records; one stub duplicated 63x.

## LIVE VERIFICATION PENDING (next closes should show)
One trades.csv row per close (any path), truthful entry_type, partial-close rows with equity moves, `[THESIS] Graded` log lines, pnl_saved/pnl_missed accruing on vetoes, no more `conf=0%` ML records.

## ⚠ TWO ANOMALIES FOUND AT RESTART (pre-existing, need decisions/fixes)
- **Restart wipes the book:** recovery loaded 0 of 3 open paper positions (state file was there pre-restart; recovery path doesn't read it). Every restart orphans open positions — unrealized PnL never realizes, trades never close. (All 3 orphans were epsilon-noise trades, so no real loss tonight.)
- **Two equity trackers diverge:** persisted $2318.91 vs heartbeat $1951.01 (~$368 gap — plausibly the never-recorded partial profits). Needs a single-source-of-truth equity reconciliation.

## YOUR DECISIONS (each ~2 min)
1. **Exploration policy** ("trade claudes"): all 5 of 7/01's entries were epsilon overrides of LLM skips. Options: (a) tiny-size exploration (0.1x), (b) keep size, honest labels only (now done), (c) suspend exploration until instruments validated. My lean: (a) — keeps the learning data, caps the noise cost.
2. **hype_long_veto restore?** Under corrected dollar accounting it saved money (HYPE LONG: 12% WR, −$585; HYPE theses 18% right). My lean: restore — it's the system's own learned rule under fixed math.
3. **Exit geometry** (winners die at breakeven before TP1 — two verified mechanical causes). Approve a backtest-first fix behind a flag? My lean: yes, backtest only, then decide.
4. **Exploration sizing** — route exploration through risk_mgr.calculate_qty (kills the $628-tight-stop-long class). My lean: yes.
5. **LLM-first exchange submission** (critical #1) — entries never submit exchange orders (paper masks it). Must fix before ANY live thought. Approve wiring it mechanical-path-style? My lean: yes, it's correctness not behavior.
6. **Restart book-wipe + equity reconciliation** — fix recovery to reload open positions + unify equity trackers. Pure correctness. My lean: yes, autonomous next.

## THE ONE-LINE STATE
The machine's judgment was never the problem tonight proved — its bookkeeping was; the spine now tells the truth, the caution was earning not costing, and selectivity + shorts + honest instruments is the validated identity of this system.
