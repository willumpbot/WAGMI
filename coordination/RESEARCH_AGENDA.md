# RESEARCH AGENDA — the infinite queue
Owner mandate (2026-07-02): "take the long aggressive move to understand the mass data... we can continue backtesting to no end... damn near infinite opportunity."
This is the standing research backlog. The learning engine pulls the top unanswered question each pass (after spine verification + HOLES burns). Every answer gets a coordination/ report + a one-line verdict added here. Questions are cheap — add freely; answers require evidence.

## Rules of the program
- **TOKEN TARGETING (owner, 2026-07-02): spend goes to TRADE and MARKET data first** — trades ledger, counterfactuals, theses, candles, funding/OI, exit decisions. Infrastructure/meta audits (memory stores, dashboards, non-trading data) run only when trade-data questions are exhausted for the pass or a P0 integrity issue demands it.
- Every claim gets a denominator, an era-split, and an adversarial check (week-1-artifact test is mandatory).
- Negative results are wins — a killed hypothesis is compounded knowledge. Log them.
- Nothing graduates to live behavior without: backtest + counterfactual + owner sign-off (or A/B rule with auto-retire).

## Fallacy definition (owner, 2026-07-02 — broadened)
A fallacy = ANY of: (a) a standard violation (v1.2/v1.3), (b) code that could be wired MORE EFFICIENTLY, (c) wiring that could produce BETTER EV UNDERSTANDING if arranged differently. Hunts under this definition treat 'suboptimal but working' as findings, not passes.

## OPEN QUESTIONS (ranked by expected value)
1. What does the honest post-fix data say after 15-20 clean closes? (The first-ever trustworthy sample. Re-run WR/conf/side/regime tables on it alone.)
2. Exit intent restoration: does hold-and-trim beat current config? (IN FLIGHT — exit-geometry backtest.)
3. Which entry source has real edge? (IN FLIGHT — signal-sources lane.)
4. Are any graduated rules dollar-negative under honest accounting? (IN FLIGHT — veto-rescore lane.)
5. High-ADX continuation: real edge or artifact? (IN FLIGHT — adx-survivor lane.)
6. Confidence-ladder sizing: which variant wins? (IN FLIGHT — sizing-ladder lane.)
7. RECALL layer design: which clean-ledger stats, injected into which agent prompts, improve thesis grade rates? (Blocked on clean closes; then A/B prompt-with vs prompt-without.)
8. Funding-crowding regime gate: does the fade edge hold when gated by trend-state? (Needs multi-regime funding span; collector must stay alive — H61.)
9. Exit-agent skill: are its hold/close/partial calls better than a mechanical baseline? (exit_decisions.jsonl vs price-after.)
10. Regime classification accuracy: does the Regime agent's label match realized vol/trend measures? (Its labels gate everything downstream.)
11. Time-of-day/session structure: does the night-session veto hold in dollars across months? Is there a session edge at all?
12. Symbol personality: per-symbol optimal hold time / stop width / trim pct (HYPE clearly differs from BTC — quantify, don't vibe).
13. Cross-symbol lead-lag: does BTC direction lead alts at 1-6h in our data? (Scout agent claims it — test it.)
14. Counterfactual gold mine: 36.5k skip records — train a simple logistic "should-have-traded" model on skip features; does anything beat the confidence floors?
15. Thesis language forensics: do graded-right theses share linguistic features (specific levels, invalidation clauses) vs graded-wrong ones? (Feeds prompt design.)
16. Drawdown structure: what do losing STREAKS look like — clustered by regime/session/symbol? (Feeds the CB tuning conversation, never weakening it.)
17. Fee drag map: realized fees as % of gross per setup type — where does fee drag eat the edge?
18. Old eras archaeology: the pre-May trades (rows 1-21, +$1,756) — what conditions produced them and are they detectable live?
19. Ensemble strategy attribution: which of the 4 strategies' signals actually correlate with wins? (Needs H22 strategy-capture fix live first.)
21. ARCHIVE MINING: the under-mined historical estate — data/reports/paper_trading_*.md (Apr-May reports incl. the 82 frozen A/B rules), sim_trades.jsonl sniper simulations, pre-May trade eras: extract every validated pattern + failed experiment already paid for. Years of walkthroughs = free training data.
20. Equity-curve Monte Carlo: given honest per-trade distributions, what bankroll/leverage keeps risk-of-ruin <5% at each calibration level? (The math behind the leverage ramp.)
22. Gate ROC: signal_outcomes.jsonl carries 56k signals with per-gate pass/reject annotations — for each gate (esp. confidence_floor), at what threshold does pass/reject flip EV-positive? (Source: DATA_CENSUS 2026-07-01.)
23. Sniper rejection EV audit: sniper_rejections.jsonl (79k records, write-only) — which single rejection reason destroyed the most counterfactual EV, per regime? 5x the sample of any accepted-trade set.
24. Agent skill attribution: agent_performance.jsonl (24k calls) — which agent role's confidence actually moves trade outcomes (skill vs noise per role)? Feeds calibration weights and token budget.
25. Scorecard validity: trade_scorecards.jsonl (2.5k records, nothing reads it) — do scorecard grades predict realized PnL, i.e. is the grader worth its tokens?
26. Proposal→adoption audit: growth/hypotheses+recommendations+self_improvement_proposals (1.5MB, ~write-only) — what fraction of machine proposals were ever enacted, and did enacted beat ignored?
27. P0 INTEGRITY — single source of truth: five trade stores disagree (trades.csv 91 vs trade_ledger.csv 157 vs ml_data/bot.db trades 330 vs ml_data/trade_outcomes.json vs analysis/trade_outcomes.csv 25). Reconcile once, designate canon, alias the rest — every WR/EV answer depends on this denominator. (Full flag list: DATA_CENSUS.md §4.)

28. DATA EXPANSION: what free trade/market streams do we NOT collect that would sharpen EV? (HL: L2 book depth/spread/imbalance snapshots, liquidation events, trade-tape aggregates; Binance: long/short account ratio, taker buy/sell flow, basis.) Time-series can't be backfilled — every uncollected day is lost forever. Collector must be ISOLATED (own daemon/task, new files, zero contact with the trade path during the open rewire).

## ANSWERED (verdict + report)
- Missed-EV regime-skips: ARTIFACT (week-1 crash shorts) — MISSED_EV_LOCKDOWN_2026-07-01.md
- Funding-crowding as mean-revert fade: weak fade, regime-dominated; don't flip sign, gate by regime — CROWDING_STUDY.md
- Quant Brain stats value: anti-signal (17% WR when cited); muted — THESIS_AUDIT_2026-07-01.md
- Thesis confidence calibration: INVERTED (30-44 band 67% right vs 60-74 43%) — THESIS_GRADES_2026-07-01.md
