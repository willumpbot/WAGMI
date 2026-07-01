# BT_SIGNAL_SOURCES — Which entry source has edge? (2026-07-01)

Lane: entry-source attribution + ensemble-confidence counterfactual backtest.
Script: `bot/tools/backtests/bt_signal_sources.py` (read-only over `bot/data`). All PnL figures are **net of fees + funding** (verified in `multi_strategy_main.py` ~line 3805: `gross_pnl = pnl + fees_paid`; `position_manager.py` line 1170: `realized_pnl += pnl - fee - funding`).

## VERDICT (one paragraph)

**No entry source shows real edge. The entire historical profit is 11 early-era (Jun 1–6) SHORTS worth +$1,601 net — and the three trades that made almost all of it (+$1,766) have NO entry metadata, so we cannot even prove which brain produced them.** LLM-approved entries are the single worst bucket (n=44, 13.6% WR, −$990). Exploration overrides lose slowly (−$69 over 17 tiny trades) — epsilon is buying data, not alpha. On the 35k-record counterfactual sample, ensemble confidence ≥80 looks predictive overall (z=+3.6) but the effect is **entirely May 30–31**: post-May, conf ≥80 is NOT predictive (31.2% vs 34.8% would-win, z=−0.72, n=96). The apparent 70–80-band edge (n=996, z=+6.9) is regime-confounded — it is mostly early-June SELL signals during the bear trend (Jun 1–9: 65.4% would-win; Jun 10–19: 28.8%). Ensemble confidence is a weak, non-stationary signal, not a standalone edge.

---

## 1. TRUE-source classification of all 90 closes

### Method + classification confidence

`trades.csv.entry_type` is unreliable: all 66 "LLM_FIRST" rows record `llm_action:"go", llm_agreed:true` **even when the LLM skipped** (confirmed measurement fault — THESIS_AUDIT_2026-07-01 + `python_stdout.log` "EXPLORATION ENTRY: skip→go" lines, 34 occurrences, whose skip-theses match the trades' recorded theses verbatim). Rules used, in order:

| Rule | Class | Confidence |
|---|---|---|
| empty `entry_reasons` | unknown_no_metadata | LOW — unrecoverable (pre-fix metadata gap + intermittent) |
| `llm_action == "no_llm"` (MEDIUM/TREND era, Jun 5–6) | mechanical_ensemble | HIGH |
| `llm_confidence == 0.0` | exploration_override (skip→go) | HIGH — matches log skip→go lines; incl. 2 "LLM pipeline failure" rows |
| `llm_confidence == ensemble_conf/100` exactly, empty thesis | suspect_echo (almost certainly exploration; echo bug wrote ensemble conf into llm field) | MEDIUM |
| `llm_confidence > 0` + genuine thesis | llm_approved | MED-HIGH (some theses read as anti-trade skip rationales even here — e.g. rows w/ "SHORT has 0% WR (n=7)" as the 'thesis'; true LLM-approval count may be LOWER than 44) |

Counts: llm_approved 44, unknown_no_metadata 21, exploration_override 15 (+2 pipeline-fail), suspect_echo 5, mechanical_ensemble 3.

### Per-source results (net PnL, $)

| Source | n | WR | Total PnL | avg win | avg loss | LONG | SHORT |
|---|---|---|---|---|---|---|---|
| **llm_approved** | 44 | 13.6% | **−990.41** | +27.17 | −30.35 | 0/13, −639.11 | 6/31, −351.30 |
| exploration_override | 15 | 26.7% | −51.33 | +11.19 | −8.73 | 1/6, −62.54 | 3/9, +11.21 |
| explor. (pipeline-fail) | 2 | 0% | −17.98 | — | −8.99 | — | 0/2 |
| suspect_echo | 5 | 0% | −13.51 | — | −2.70 | 0/1 | 0/4 |
| mechanical_ensemble | 3 | 100% | +57.73 | +19.24 | — | — | 3/3 |
| unknown_no_metadata | 21 | 52.4% | **+1,756.61** | +167.01 | −8.05 | 3/8, +7.28 | 10/13, +1,749.33 |

- **LLM-approved LONGS are 0-for-13 (−$639).** The LLM's approvals have negative edge in both directions and both halves of the sample (Jun 1–9: 1/16, −$645; Jun 10+: 5/28, −$345). There is no sub-period where LLM approval was profitable.
- **The unknown bucket's profit is 3 trades**: BTC SHORT Jun 2 (+378.59), ETH SHORT Jun 3 (+1,010.37), SOL SHORT Jun 4 (+377.05) — closed with empty `entry_reasons`, blank `entry_type`, `confidence=0.0`. The other 18 unknowns sum to −$10. Attribution of the bot's entire lifetime profit is **unrecoverable from the records**.
- mechanical_ensemble 3/3 is real but tiny (+$57.73, Jun 5–6 shorts) — n=3 proves nothing.
- Exploration overrides (Jun 20+, ~$8 risk each): −$69.31 over 17 trades ≈ −$4/trade. Cheap data collection, negative expectancy so far, 4/26 win rate across explor+echo combined.

### Era split — the whole question in two rows

| Slice | n | WR | Total PnL |
|---|---|---|---|
| **Early-era SHORTS (close < Jun 7)** | 11 | 72.7% | **+1,600.78** |
| **Everything else (79 trades)** | 79 | 20.3% | **−859.67** |

Early era total +1,536.56 (13 trades) vs Jun 7+ total −795.45 (77 trades). Jun 7+ LONGs: 15.4% WR, −$633; Jun 7+ SHORTs: 23.5% WR, −$163. **Yes — the historical edge is entirely the early-era shorts**, i.e. one directional regime (the June bear leg) captured at large size, mostly by trades whose source is unrecorded.

## 2. Counterfactual backtest: is ensemble confidence predictive? (n=35,179)

Sample: `counterfactual_resolved.jsonl`, 39,127 lines → **35,179 unique resolved records** after record_id dedupe (≈3.9k duplicate lines, 9 malformed). "Would-win" = hypothetical_pnl_pct > 0 (TP1/SL first-touch on candles).

| Conf bucket | n | pnl>0 | TP1 hit | avg hyp pnl |
|---|---|---|---|---|
| <50 | 14,636 | 31.0% | 6.6% | −0.555% |
| 50–60 | 11,474 | 35.2% | 6.1% | −0.370% |
| 60–70 | 7,521 | 42.5% | 7.4% | −0.093% |
| 70–80 | 1,340 | 50.1% | 22.5% | **+0.427%** |
| 80–90 | 137 | 35.0% | 24.1% | −0.025% |
| ≥90 | 71 | 71.8% | 16.9% | +0.572% |

Headline ≥80 vs <80: 47.6% vs 35.6% would-win, z=+3.62 — looks significant. **But it is not stationary:**

- **May 30–31 only**: ≥80 n=112, 61.6% would-win, +0.854% avg. **Post-May (Jun 1–Jul 1): ≥80 n=96, 31.2% vs <80 34.8%, z=−0.72 — no edge.** Worse: post-May ≥80 SELL is 17.8% would-win, −1.18% avg (n=45). The entire ≥80 effect is two days of HYPE/SOL BUYs before June.
- The 70–80 band survives post-May (n=996, 45.1%, +0.278%, z=+6.9 vs <70) **but is regime-confounded**: by week — Jun 1–9: 65.4%/+1.48%; Jun 10–19: 28.8%/−1.09%; Jun 20–29: 40.1%/+0.10%; Jun 30: 7.7%; Jul: 50.0%. By side — SELL +0.844% vs BUY −0.210%. It is largely "being short during the early-June bear leg", the same regime that made the live early-era shorts.
- Monotonicity check (deciles): rough upward drift in would-win from 28.5% (lowest conf) to 45.2% (top decile), only the top decile has positive avg (+0.091%). So confidence carries *some* rank information, but the payoff at realistic fee/slippage (~0.1%+ round trip, unmodeled here) is ≈zero outside the confounded windows.
- By symbol ≥80 (whole sample): SOL good (n=34, 61.8%, +1.38%), ETH terrible (n=20, 5%, −1.86%, 90% SL), BTC flat — too thin to trade on.
- Skip-reason note: `graduated_rule_veto_overridden` (n=4,846) skips are ~coin-flip (47.6%, +0.03%) — the graduated vetoes are discarding roughly EV-neutral signals, i.e., they are not saving money either.

## 3. Reproduction-fidelity caveats (plain)

1. `hypothetical_pnl_pct` is unlevered price-% to first TP1/SL touch, **no fees, no funding, no slippage, no exit management** — live trades pay ~0.1%+ round trip and get partial-managed, so counterfactual "edges" under ~+0.3% avg are likely ≤0 net.
2. TP1/SL first-touch on bars is ambiguous when both are inside one bar; resolver's tie-breaking unknown — adds noise to WR levels (less to A-vs-B comparisons).
3. Source classification: HIGH confidence only for `no_llm` (3) and `llm_confidence==0` exploration rows (17). The 44 "llm_approved" is an **upper bound** — echo-bug rows with plausible-looking llm_confidence may hide inside it; true LLM-approval PnL could be even worse, not better. The 21 unknowns (incl. the 3 profit-makers) are permanently unattributable.
4. trades.csv has ~90 closes vs 470 TRADE_OPENED events in trade_events.jsonl (paper/replay mixed in); this lane used trades.csv closes only as the live-money denominator.
5. Counterfactual sample is skipped-signal-only (selection: things the gates rejected); it measures whether *confidence ranks signals*, not whether taking them would have replicated live fills.

## 4. What this implies (for the other lanes)

- Stop treating "LLM approved" in the records as meaning anything until the skip→go mislabeling is fixed — measurement first.
- The system has never demonstrated entry edge outside one bear regime. Selectivity work should target **regime/side conditioning** (short-in-downtrend was the alpha), not confidence thresholds — conf ≥80 post-May is noise (n=96, no lift).
- Exploration is functioning as designed (cheap samples, ~−$4/trade) but at ~7/day it sets the trade count and pollutes per-cell WR stats that the exit agent then cites (0% WR n=2 cells). Cap or tag it in stats.
