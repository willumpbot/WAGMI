# MORNING BRIEF — 2026-07-02
Everything from tonight in one place. Reports: WIRING_AUDIT, THESIS_AUDIT, THESIS_GRADES, MISSED_EV_LOCKDOWN, MASTER_PLAN (all in coordination/).

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
