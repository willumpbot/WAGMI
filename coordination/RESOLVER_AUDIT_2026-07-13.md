# Counterfactual Resolver Audit — 2026-07-13 (OWNER DECISION required)

Surfaced by an adversarial review while vetting a (now-killed) proposal to inject skip-outcome
stats into the live prompt. **These are NOT fixed** — they touch the live veto/learning path, so
per THE_STANDARD they wait for your review + a backtest. Filing so you can decide.

**Why you should care:** defect #1 below silently corrupts **graduated-rule veto outcome scoring**
(`bot/llm/counterfactual_learner.py:553-576`, `record_veto_outcome`), which decides whether learned
vetoes arm/retire — and armed vetoes gate real signals. So this isn't just a dead analysis feature;
it biases what the bot trades. Not an acute emergency (measurement-window bias, not a crash), but a
real correctness bug in the learning loop.

## Defects (file: `bot/llm/counterfactual_learner.py`)

1. **"48h" tracking window is really ~9h.** `MAX_TRACKING_BARS = 48  # 48h for 1h candles` (:143),
   but `is_new_candle` fires on ANY (high,low) change (:474-476), which happens many times *within* a
   forming candle. Measured on 45,337 timeout-resolved records: **median 9.0h** (p10 6.2h, p90 13.1h).
   → the window also shrinks when volatility is high, so any cross-cell `tp1_rate` comparison is
   volatility-confounded by construction. **This same bar counter drives `record_veto_outcome` (:553-576)
   → veto accuracy is scored over ~9h instead of 48h.**
2. **Same-candle look-back (leakage).** The first `update_with_price` after a skip applies the current
   candle's full high/low (:489-513), including action *before* the skip — a skip can be credited a TP1
   touch that already happened.
3. **Optimistic TP1/SL tiebreak.** Both-hit-same-bar is scored as a partial WIN at TP1×0.65 (:527-529);
   no SL-first rule (TABLE_C deliberately used SL-first). → `tp1_rate` upward-biased.
4. **Contaminated "resolved" set:** 812 capacity-evicted records force-stamped `hypothetical_pnl_pct=0.0`
   (:350-358, :451-459); 4,685 duplicate lines; 41 `test_reason` records still in the production file.
5. **No fees.** `hypothetical_pnl_pct` is gross; TABLE_C round-trip is 0.10% — on ±0.1-0.2% cells that's
   the whole signal.

## Evidence the downstream stats are unusable today (why #3 was killed)
- The "74k" numbers everyone cites are actually the **last-14-day slice** (`RESOLVED_MEMORY_DAYS=14`, :149).
- **Every standout cell flips sign between era-halves** (split @ 2026-07-01): ETH BUY-vs-SELL asymmetry
  reverses; HYPE-SELL "0% TP1" was positive-pnl in H1; BTC-BUY/XRP-BUY flip. → momentum snapshot, not
  a filter diagnostic.
- **Pseudo-replication:** signals re-fire ~every 50s; dedup by (symbol,side,30min) collapses 69,629 →
  6,573 unique opportunities (10.6×). Reported n's are inflated. 827 of 889 cells have n<30.

## Proposed fix (needs your OK + a backtest — do NOT ship unattended)
Order by impact: (1) fix bar counting to true elapsed candles (biggest — also un-corrupts veto scoring);
(2) SL-first tiebreak; (3) exclude evicted/`test_reason`/duplicate records from resolved reads;
(4) dedup re-fires before any aggregation; (5) subtract 0.10% fees from `hypothetical_pnl_pct`.
After that, re-check whether ANY veto's armed/retired status changes — that's the real deliverable.

**Recommendation:** treat defect #1's effect on `record_veto_outcome` as the priority (live path).
The prompt-injection idea (#3) stays dead regardless.
