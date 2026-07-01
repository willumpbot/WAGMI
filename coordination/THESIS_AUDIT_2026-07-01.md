# THESIS AUDIT — 2026-07-01

Auditor: Claude (read-only pass over `bot/data/*`). All timestamps UTC.
Sources: `data/llm/thesis_history.jsonl` (209 records, 2026-05-31 → 2026-06-30), `data/llm/decisions.jsonl` (3,222 records), `data/trades.csv` (89 closes), `data/logs/exit_decisions.jsonl` (602), `data/logs/exit_closes.jsonl`, `data/trade_events.jsonl` (470 TRADE_OPENED), `logs/python_stdout.log`, `data/circuit_breaker_state.json`, `data/logs/safety_events.csv`.

---

## DELIVERABLE 1 — The live BTC LONG: full decision trail

### Headline verdict
**The LLM never wanted this trade. It is an EXPLORATION entry that converted an LLM "skip" into a "go", and the skip's own rationale was pasted into the position notes.** The conf 82.0 on the position is the *mechanical ensemble signal* confidence (solo `confidence_scorer`), not LLM conviction — the LLM's entry confidence was 0.0 (skip). Post-entry, the exit agent has been trying to kill the trade since 2.7h in; policy prevented full close, so it has been bleeding it out via 2×50% partials and an SL ratchet to above entry. The trade is currently green by luck (BTC rallied to 60,291 peak), and the management — while internally consistent — is managing a thesis that never existed.

### Timeline (all 2026-07-01 UTC)

| Time | Event | Evidence |
|---|---|---|
| 12:42:29 | **Circuit breaker TRIPS**: "10 consecutive losses >= 10 limit", daily_pnl −$3.93 | `data/logs/safety_events.csv` last row |
| ~13:42 | CB auto-resets — `CIRCUIT_BREAKER_COOLDOWN_MIN=60` (`.env` line 56). So by entry time the *mechanical* CB object was un-tripped | `.env`; current `circuit_breaker_state.json`: `tripped:false` |
| 13:52:23 | Mechanical ensemble emits **BTC BUY conf 82.0**, solo `confidence_scorer`, n_agree=1, entry 59372, SL 58417, TP1 61281 | `trade_events.jsonl` line 61380 |
| ~13:53–13:55 | LLM-FIRST coordinator evaluates → **action=skip**. Thesis: *"BTC range-bound near 59.3k; circuit breaker tripped (10 consecutive losses) mandates hard skip regardless of setup quality"*. (The LLM's prompt context still said CB was tripped — it had reset ~13 min earlier; the LLM skipped on stale CB state, which was nonetheless the "right" answer for the wrong freshness reason.) | position `notes`; `logs/python_stdout.log:311361` |
| 13:55:16 | **EXPLORATION ENTRY: skip→go** qty=0.008220, lev 1.0x, risk $7.85 (= equity 1962 × EXPLORATION_RISK_PCT 0.004 / stop width 954.9 — sizing math confirms exploration path) | `python_stdout.log:311361`; `multi_strategy_main.py` ~line 7660 exploration block |
| 13:55:27 | TRADE_OPENED BTC LONG 0.00821 @ 59420.5, SL 58465.6, TP1 61330.2, conf 82.0, `entry_type: LLM_FIRST` | `trade_events.jsonl:61384`; `position_backups/BTC.json` |
| 13:55:27 | `signal_outcomes.jsonl` logs it as **"LLM approved", passed=true** — with `llm_confidence: 0.0` and the skip thesis in metadata. **Measurement fault: exploration overrides are recorded as LLM approvals.** | signal_outcomes record ts 1782914127 |
| 13:50 & 13:57 | Bracketing multi-agent cycles both said **FLAT** — "CB tripped… mandatory skip", "BTC_LONG 0% WR (n=5) in trend", noise_prob 95%. The 13:57 record even flags: *"[memory-worthy event] Entry type 'LLM_FIRST' on 5-trade loss streak (recent WR: 0%)"* | `decisions.jsonl` lines 3141-3144 |
| 15:57:06 | Exit agent: **CLOSE (conf 0.75)** — "Thesis invalidation via regime mismatch. High_volatility 0% WR (n=2)". **NOT APPLIED** — "Exit-agent full-close disabled except dead-capital/thesis-invalid losers (measured 0/71 on discretionary closes)" | `exit_decisions.jsonl` |
| 17:48:54 | Exit agent: **PARTIAL 50% — APPLIED** (qty 0.00821 → 0.004105). "MFE 1.261% exceeds 1.0% threshold; high_volatility structurally losing regime for BTC (0% WR, 2 trades)" | `exit_decisions.jsonl` |
| 18:21:05 | **SL tighten APPLIED**: 58465.6 → 58752.1. "Thesis weakening, not invalidated. 0% WR in trend (n=7)" | `exit_decisions.jsonl` |
| 18:53:50 | **SL tighten APPLIED**: 58752.1 → **59539.3 (above entry — locks ≥ +$0.24)**. "Regime invalidation: high_volatility 0% WR on BTC LONG (2 trades)" | `exit_decisions.jsonl` |
| 19:30:23 | Exit agent: **CLOSE (conf 0.75)** again — "Thesis invalidated. confidence_scorer BTC LONG trending_bull 0% WR (n=3)". **NOT APPLIED** (same policy) | `exit_decisions.jsonl` |
| 20:08:36 | Exit agent: **PARTIAL 50% — APPLIED** (qty 0.004105 → 0.0020525). "Range regime + MFE retrace 41.8% from peak + confidence_scorer 11% WR in range (n=9)" | `exit_decisions.jsonl` |
| 20:37:55 | POSITION_UPDATE: price 59984.5, unrealized +$1.16 on the remaining quarter position. Peak was 60291.5; TP1 61330.2 never reached | `trade_events.jsonl:61883` |

### Answers to the specific questions

**When/why entered:** 13:55:27 UTC. Not because of any thesis — the mechanical solo confidence_scorer signal (conf 82) was fed to the LLM, the LLM **skipped**, and `EXPLORATION_MODE=true` (epsilon 0.12) rolled the dice and converted the skip to a reduced-size entry ($7.85 risk, ~0.4% equity). There was no regime/trade/risk/critic "go" consensus; the two nearest full multi-agent cycles (13:50, 13:57) were both hard-skip vetoes. **"Why conf 82"**: that number is the *ensemble signal's* confidence carried onto the position record; LLM entry confidence was 0.0.

**The circuit-breaker reference in the notes:** Real event — CB tripped 12:42:29 on 10 consecutive losses (daily −$3.93). It is NOT tripped now (`tripped:false`, consecutive_losses 3, saved 19:37). The 60-min cooldown auto-reset it at ~13:42, so the exploration gate's `not cb.tripped` check passed at 13:55. The bot did not enter "despite" a live CB in the mechanical sense — but the LLM *believed* the CB was still active (stale context) and mandated a skip, and exploration overrode that anyway. Not a hedge, not a recovery trade: an epsilon-greedy edge-data sample taken 73 minutes after a 10-loss halt.

**Partials + SL raise:** Exit agent wanted a full close at 15:57 (2.7h in) on regime/thesis-invalidation grounds but full closes are policy-disabled (discretionary closes measured 0/71). It then did what the policy allows: 50% partial at 17:48 (MFE>1% rule), SL to 58752 at 18:21, SL to 59539 (above entry, profit-locked) at 18:53, second 50% partial at 20:08 (41.8% MFE retrace). Quantity 0.00821 → 0.0020525 = two halvings, matching the two applied partials exactly.

**Is it being managed well?** Mechanically, yes — this is the best-managed part of the trade's life: risk was cut early, breakeven was locked before any giveback, and the remaining quarter position is a free roll with SL above entry. But "does the management match the thesis?" is unanswerable in the way the question intends, because **there is no long thesis to match** — the recorded thesis argues for NOT being in the trade. The exit agent is effectively unwinding an entry the entry-brain never endorsed, citing 0%-WR cells with n=2, 3, 7, 9 (tiny samples) as "regime invalidation". Verdict: **good damage-control wrapped around an entry-governance fault.** The same pattern applies to every position opened today: BTC (13:55), XRP (15:31), ETH (16:01), HYPE (18:37), SOL (19:27) were ALL exploration skip→go conversions — the LLM skipped every one of them (see log lines 311361, 315120, 316212, 321519, 323174). At ~7 exploration conversions in one day this is not "~2 selective trades/day"; exploration frequency, not the LLM, is currently setting the trade count.

---

## DELIVERABLE 2 — All 209 theses through quant analysis

### 2.1 Corpus overview

- **209 thesis records**, 2026-05-31 14:57 → 2026-06-30 06:48, all `agent_name: trade_agent`.
- By symbol: BTC 87, SOL 63, ETH 36, HYPE 18, **empty-symbol 5, XRP 0** (XRP traded 2× but has zero theses — symbol capture gap).
- Claimed regimes: trending_bear 71, trend 52, consolidation 37, range 32, high_volatility 11, trending_bull 6.
- Confidence: 0–90, heavily skewed low (median band 20–40).
- **Capture leaks (hard bugs):**
  1. **`side` is 100% "BUY"** — all 209 records, including ~140 explicitly bearish theses. The field is unwired, not merely mismatched.
  2. **`outcome` is 100% "pending"** — the resolution loop (exit_price/pnl_pct/max_favorable) has never run once. Zero theses have ever been graded.
  3. **`setup_type` is 100% "unknown"**, `target_price`/`expected_hold_h` 100% null.
  4. Recording **stopped 2026-06-30 06:48** — none of today's 11 closes/5 opens have a thesis row; today's theses survive only in `python_stdout.log` and position `notes` (truncated at 100 chars).

### 2.2 Side/text mismatch quantified (the side-vocab wiring fault)

Text-derived direction vs recorded `side`:

| Text direction | n | Recorded side |
|---|---|---|
| Explicit SHORT/SELL token | **120** | all "BUY" ← **mismatch** |
| Bearish-implied (breakdown/decline/lower, no token) | **20** | all "BUY" ← mismatch |
| Explicit LONG/BUY token | 22 | "BUY" (coincidentally right) |
| Both tokens present | 1 | ambiguous |
| Unclear | 46 | ungradable |

**Mismatch count: 120 hard (explicit token), 140 including implied — 57–67% of the corpus.** Example: `thesis_20260601_120748_1` — *"ETH SHORT to 1923 within 10-22h…"* recorded `side: "BUY"`. Combined with outcome-never-resolved, thesis_history is currently unusable as a learning signal: even if grading is switched on, it would grade 2/3 of shorts as longs.

### 2.3 Thesis ↔ trade cross-match (honest match-rate)

Method: trades.csv rows joined to TRADE_OPENED events (89/89 matched on symbol+side+entry±0.05%), then thesis matched on symbol + created_at within [−5 min, +2 h] of open, nearest-first, each thesis used once.

- **Matched: 47 of 89 trades (53%).** 162/209 theses match no trade (mostly genuine skips, plus capture gaps). Numbers below are for the matched subset only.

**By thesis type (multi-label, matched trades, full period):**

| Type | n | WR | PnL |
|---|---|---|---|
| trend-continuation | 22 | 23% | **+1345.72** |
| squeeze | 6 | 50% | +676.89 |
| range/mean-revert | 16 | 25% | +300.79 |
| OI/funding/liq | 8 | 38% | +5.43 |
| breakout/resolve | 15 | 13% | −230.99 |
| **stats-cited (quotes WR/n=/EV)** | 24 | 17% | **−669.73** |

**Era-controlled (Jun 17+ matched only, n=20): every type is negative.** stats-cited −299.86 (n=12), OI/liq −30.24, breakout −27.59, range/mean-revert −17.54, trend-continuation −10.56. The apparent "winners" above are entirely a Jun 1–6 artifact (11 matched early trades = +1524.75 of the total).

**By claimed regime (matched):** consolidation +1081.07 (n=17), high_volatility +373.97 (n=3) — both early-June-driven; trend −101.84 (n=7, 14% WR), range −168.32 (n=9), trending_bull −250.25 (n=3, incl. HYPE longs).

**Thesis-direction vs executed side (matched):** thesis-agrees-side n=42, 26% WR, −147.88; the +985 residual sits in 5 direction-unclear matches (big early shorts). I.e. even direction-agreement does not rescue the post-Jun-7 period.

### 2.4 ETH LONG + XRP LONG "vanished" positions — resolved

They did not vanish; they were **closed by the LLM exit agent**, and `trades.csv` failed to record them:

- **XRP LONG** (exploration entry 15:31:43 @ 1.062, LLM had skipped: "XRP 4h bounce off 1.034 lows… likely fades back toward range mid") → closed 18:22:40 @ 1.06145, **PnL −$0.50**, exit_type LLM_EXIT_AGENT. In `exit_closes.jsonl` line 53 and `trade_events.jsonl:61727`; **absent from trades.csv**.
- **ETH LONG** (exploration entry 16:01:39 @ 1616.25, LLM had skipped: "ETH LONG solo confidence_scorer… lacks confluence") → closed 20:09:59 @ 1613.35, **PnL −$0.96**, exit_type LLM_EXIT_AGENT. In `exit_closes.jsonl` line 54 and `trade_events.jsonl:61856`; **absent from trades.csv**.
- Scale of the ledger gap: **11 closes on Jul 1 in exit_closes.jsonl, only 2 rows in trades.csv** (XRP 09:32, HYPE 18:28). trades.csv is systematically dropping closes — every downstream WR/EV stat computed from it (including the Quant Brain numbers injected into prompts) is running on a leaky ledger. This directly supports the "Quant Brain suspect" hypothesis.

### 2.5 The 5 load-bearing WHEN/WHERE/WHY patterns (data, not vibes)

1. **WHEN dominates everything: selectivity era vs volume era.** Jun 1–6: n=13, **62% WR, +$1,536.56** (~2.2 trades/day). Jun 7–16: n=16, 19% WR, −$373.58. Jun 17–Jul 1: n=60, 22% WR, −$414.79 (~4/day). No thesis type, regime, or symbol survives the volume era. The single strongest lever is trade count, not thesis content.
2. **WHERE: short side carries the entire book.** SHORT n=62, 32% WR, **+$1,438.26**; LONG n=27, 15% WR, **−$690.07**. Worst cell HYPE_LONG n=8, 12% WR, −$584.82 (two blowups −264, −223). Late-era (Jun 17+) the only green cells are SOL_SHORT (+37.54, n=5) and HYPE_SHORT (+9.21, n=10); every LONG cell is red and BTC_SHORT degraded to 7% WR (n=14, −61.12) — the June short edge decayed too.
3. **WHY-red-flag: theses that cite Quant-Brain stats lose the most.** "stats-cited" theses (quoting WR/n=/EV in their own text): n=24, 17% WR, **−$669.73** full period; still the worst bucket late-era (n=12, −$299.86). The injected WR/EV numbers are computed from a ledger that drops closes (§2.4) and cites n=2–9 cells as "0% WR regime invalidation" — the stats are anti-signal as currently wired.
4. **WHY entries happen at all no longer comes from the LLM.** 31 of 89 closed trades carry the EXPLORATION flag (−$86.68 total, 26% WR — cheap per trade at ~0.4% risk, but noisy), and **all 5 of today's opens were exploration skip→go conversions**, logged in signal_outcomes as "LLM approved" with llm_confidence 0.0. The system's recorded "decisions" and its actual entries have decoupled; measurement says the brain trades, the logs say the dice do.
5. **The thesis feedback loop has never closed once.** 209/209 outcomes "pending", 209/209 side "BUY", 0 setup_types, recording dead since Jun 30, XRP never captured, trades.csv missing ≥9 of 11 closes today. Until side-wiring + outcome resolution + ledger completeness are fixed, "which theses win" is only answerable via this kind of forensic join — the bot itself cannot see it, which is why it keeps re-citing broken stats (pattern 3).

### Appendix: current book (20:20 snapshot)
- BTC LONG 0.0020525 @ 59420.5, SL 59539.3 (profit-locked), price 59984.5 — exploration remnant, free roll.
- HYPE LONG 3.0 @ 64.3455 (18:37, exploration; LLM skip cited OI-liquidation divergence + falling funding *against* longs).
- SOL LONG 4.14 @ 77.193 (19:27, exploration; LLM thesis empty = pipeline failure/skip).
- Equity $1,958.08 vs peak $1,962.38; CB not tripped, consecutive_losses 3.
