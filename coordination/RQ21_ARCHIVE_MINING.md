# RQ21 — Archive Mining: Every Already-Paid-For Lesson (2026-07-01)

**Scope mined:** 61 paper_trading reports (Apr 25 – May 30), 12 session files (incl. AUTONOMOUS_SESSION_2026_04_15.md, 1,622 lines), 10 daily_synthesis JSONs (May), sniper simulator `bot/data/manual/sim_trades.jsonl` (59 trades May 31 – Jul 1), shadow_ledger.csv (8,714 rows May 30 – Jul 1), learning/live_edge_data.json (run 36, May 30), graduated_rules backup (33 rules, Jun 19), meta_learning/insights.json, missed_opportunities_20260530_1640.md. Cross-checked against THESIS_GRADES_2026-07-01.md and TRADE_AUDIT_2026-07-01.md.

**Denominator honesty — what is GONE:** the actual store of the "82 frozen high-confidence A/B rules" (`learning/auto_fix_state.json`) was emptied (0 active_fixes, last_run 2026-05-30); llm_memory/network_learning were purged 2026-06-07. The 82 rules survive only as *names + claimed stats quoted in reports*. The "SOL_SHORT #1 alpha +$5,807 / 63.7% WR / n=179" claim has **no surviving primary data** — treat as unverifiable folklore until re-derived. `graduated_rules.json` was reset today (Jul 1): 1 rule, fresh.

---

## A. VALIDATED PATTERNS (survive era-split + independent corroboration)

| # | Pattern | Archive evidence (denominator) | Current corroboration | Verdict |
|---|---|---|---|---|
| A1 | **Shorts on majors in strong trend = the edge** | ETH_SHORT 80% WR (4/5), BTC_SHORT 57% (4/7), reports Apr–May; `trending` regime 51.9% (27/52) vs illiquid 28.1% (16/57), ranging 25% (4/16) | TRADE_AUDIT: pooled SHORT +$1,441/61 vs LONG −$690/27. THESIS_GRADES: all 10 best theses are high-ADX (59–66) ETH/BTC trend shorts | **VALIDATED, 3 independent eras** |
| A2 | **HYPE LONG is toxic** | 23% WR (8/35), −$77.26 (Apr reports) | TRADE_AUDIT: 12% WR (1/8), −$585. THESIS_GRADES: HYPE theses 18% right @24h (n=22), −3.77% avg | **VALIDATED — most-confirmed negative in the estate** |
| A3 | **Long-side bleed generally** | meta_learning (Apr): "74% of trades LONG but LONG WR 30% vs 77% other side" (n=50); BTC_LONG 18–19% WR (n=16–17) | TRADE_AUDIT: LONG 14% WR both eras; THESIS_GRADES: LONG targets hit only 28% (7/25) | **VALIDATED** |
| A4 | **Mid-band confidence (60–79) is noise-to-anti-signal** | Old `conf_floor_70_v1`: 46.3% WR / n=123 net-negative | TRADE_AUDIT: 60–69 → 18% WR (n=45), 70–79 → **0%** (n=14), 80+ → 67–100% (n=7). THESIS_GRADES: 30–44 conf band (67%) BEATS 60–74 band (43%) @24h | **VALIDATED — also kills `confidence_60_70_sweet_spot` (93% conf rule): dead** |
| A5 | **Skipping is usually right (selectivity is alpha)** | Missed-opportunity audit May 30: 86% skip quality (37 good / 6 missed of 43 resolved). Caveat: ETH skips 0% quality (0/6) — every resolved ETH skip was a missed win | Matches Jun posture (~2 trades/day worked) | **VALIDATED, with ETH exception worth watching** |
| A6 | **Learning loop was never wired (meta-lesson)** | `evaluate_active_fixes()` was a TODO stub; rules with 1,420 / 1,161 / 752 applications had `times_correct=0`; 82 rules "frozen" for 48+ days | Recovery memo: learning-loop bugs are the real gap; thesis `outcome` never graded until Jul 1 pass | **VALIDATED — every archive stat below inherits this measurement debt** |

## B. FAILED EXPERIMENTS / KILLED HYPOTHESES (wins — do not re-litigate without new data)

1. **`confidence_60_70_sweet_spot` (93% conf, "+$2.19 avg")** — killed by trades.csv: 60–69 band 18% WR / n=45. The May 7 synthesis flagged the conflict; it's now resolved against it.
2. **"Validated edge" stat-citation as thesis fuel** — the two loudest thesis failures cite "85–88% WR n=395 US session" (−10.5%, −8.7%) and "PF 12.21, n=4" (−9.1%). THESIS_GRADES: EV-citing theses 48% vs 57% for non-citing (n=46 vs 126). Quant-Brain-style stat injection is a mild **anti-signal** (Nunu's suspicion confirmed).
3. **Chasing SOL/HYPE breakdowns after crash bars** — 4 of the 10 worst theses (−7% to −9%). Old "dead-cat bounce short" heuristic: dead.
4. **`INSTANT_SL_stop_buffer`** — 11% WR at gate=80, flagged "worst rule in system" (live_edge_data run 36). Dead.
5. **Volume-pushing / high epsilon era** — Apr all-time WR 13.4%, equity −90.1%. Killed by owner decision; archive confirms.
6. **HYPE BUY shadow mirage** — shadow_ledger shows HYPE BUY regime_trend **91% WR (n=90)** while live HYPE LONG is 12–23%. Adversarial read: shadow "resolution" is TP/SL-race with 83% expiry (7,245/8,714 expired) — resolved subset is survivorship-biased. **Lesson: never trust shadow-ledger WR without expiry accounting.** This same bias likely inflated the BB_golden "n=2172" claims (identical n for ETH/BTC/SOL = one shared denominator, not per-setup).

## C. FROZEN RULES WORTH RE-TESTING (top of the 82; store purged — stats are as-quoted, unverified)

| Rule | Claimed | Status today |
|---|---|---|
| `BB_solo_signal_boost` | solo BB 67.6% vs ensemble 51.9% | Partially alive: shadow BTC SELL bollinger_squeeze 74% (n=68) but ETH SELL BB **6%** (n=68) → symbol-conditional at best |
| `ETH_SHORT_BB_golden` | 70% WR "n=2172", trending | Direction corroborated by A1; the n is suspect |
| `BTC_BUY_BB_golden` | 69% WR "n=2172" | **Contradicted** by all live long-side data (A3) — likely shadow-bias artifact |
| `night_session_block_v1` | 19% WR (n=27), 00–06 UTC | Never re-tested on the 88 current-era trades; cheap to check |
| `TOD_morning_edge` | 71–75% WR (n=7!) | n too small; the related "US session n=395" citation blew up (B2) |
| `streak_momentum_gate` / `TIGHT_TP_preference` | 90% conf, zero live evidence | Pure hypothesis; only revive inside a measured A/B |
| `btc_short_90plus_boost_v1` | 67% WR, "+$102.92/trade" | Consistent with A4 (80+ conf works); n unknown |

## D. CONTRADICTIONS WITH CURRENT KNOWLEDGE (need adjudication)

1. **SOL_SHORT**: archive says both "#1 alpha +$5,807/179/63.7%" AND "Kill, −$154/30/33%" *in the same reports* (sniper path vs ensemble path — the Apr 15 session shows the alpha was specifically `sniper_premium` SOL SHORT). Current sniper sim: SOL SELL n=53, **64% WR replicates but PF only 1.02** (+$5.91 on $100) — the WR survived, the expectancy didn't; tranche/exit geometry eats the wins. Old worst sim trade −$11.63 vs best +$4.22 confirms asymmetry is inverted vs the live-trade 4:1.
2. **BTC longs**: `rule_1777922205_0` "BTC strong in trend regime" logged 27/27 correct (Jun 19 backup) and was re-created today — vs live BTC_LONG 18% WR. The 27/27 is almost certainly the counterfactual-counting bug (rule_1781693230_24 shows `applied 6, correct 12` — correct > applied is impossible).
3. **Veto self-measurement**: hype_long_veto auto-retired at "53% correct" while HYPE LONG is 12% WR / −$585 live (TRADE_AUDIT #4). Retire logic ignores PnL.
4. **XRP SELL regime_trend**: 23% WR on n=465 resolved shadow signals — biggest-n anti-signal in the estate; either a fade candidate or the strongest proof of shadow-resolution bias. Same caveat as B6.

## E. TOP 5 REVIVAL CANDIDATES (with the evidence each needs)

1. **High-ADX trend-continuation short boost (ETH/BTC)** — merges `ETH_SHORT_BB_golden` + `eth_trending_regime_boost` + THESIS_GRADES best-10 pattern. Evidence needed: backtest on HL/Binance 1h candles May 30→now (bridging the 536h funding hole with candles), entry = ADX≥55 + EMA stack + short thesis, n≥15 fresh signals, era-split pre/post Jun 7, fragility check (drop best trade). Week-1 artifact: signal×outcome table.
2. **Confidence gate: full size only at conf≥80, downsize 60–79** — corroborated 3 independent ways (A4). Evidence: counterfactual A/B on next 15 live signals + retro replay of the 88 closed trades; reversible, no hardcoded direction.
3. **Night-session (00–06 UTC) data-learned penalty** — old n=27 @19% WR, never checked on current era. Evidence: hour-of-day split of trades.csv (88) + deduped thesis grades by hour; needs n≥13 in-window before acting (graduation bar).
4. **Sniper auto-execute** — the only path that was live-profitable in April (+$328 on 34 trades vs everything else −$76). Sim replicates WR (62.7%, n=59) but PF 1.02. Evidence: fix exit geometry first (tranches cap winners — compare sim tranche PnL vs hold-to-swing-TP counterfactual on same 59 trades), then require PF≥1.3 over 20 more sim trades before flipping `SNIPER_AUTO_EXECUTE`. Verify the 5x leverage cap actually binds (Apr 15 finding: −$147 trade ran at 9.7x).
5. **BB-squeeze short, BTC-only** — shadow BTC SELL squeeze 74% (n=68) + THESIS_GRADES squeeze type 63% @24h (n=27); explicitly NOT ETH (6%, n=68). Evidence: re-resolve the 68 shadow signals against exchange candles (kill the expiry bias), require ≥60% WR and positive avg return on the unbiased set.

**Adversarial self-check:** most archive WRs trace to two contaminated instruments (shadow-ledger expiry bias; counterfactual correct-counting bug), and the whole Apr–May report series describes a bot that was OFFLINE — the stats are historical-analysis claims, not live results. That is why every revival above demands fresh-candle re-derivation, not report quotes. Killed: confidence_60_70_sweet_spot, stat-citation-in-prompts, post-crash breakdown chasing, INSTANT_SL_stop_buffer, HYPE-long-anything.
