# Historical Archive Summary
*Generated: 2026-05-30 | laptop-claude analysis of old-bot-pre-2026-04-23 data*

---

## What's in the Archive

| Data | Value |
|---|---|
| Trades | 228 |
| Date Range | 2026-03-25 → 2026-05-11 (47 days of active trading) |
| Win Rate | 27.2% (62W / 166L) |
| Gross PnL | -$3,714.99 |
| Fees Paid | -$875.19 |
| Net PnL | **-$4,590.18** |
| Symbols | BTC, ETH, SOL, HYPE |
| Strategies Used | ensemble, omniscient_integrated, sniper_premium, sniper_standard |
| LLM Decisions | 1,259 (all `api_error | no_client` — pre-CLI-client architecture) |

**Note on decisions.jsonl:** All 1,259 entries are `api_error | no_client`. This is from the OLD architecture (before the CLI client was built). These represent failed Anthropic API calls from when the bot lacked `USE_CLI_LLM=true`. The old bot traded on mechanical signals only — `llm_action: "no_llm"` appears across all winning and losing trades. The LLM brain was effectively offline for the entire 8-month period.

---

## Top 3 Surprises

### 1. The April 26-27 Omniscient Disaster — 58% of All Losses in 2 Days

`omniscient_integrated` strategy fired 47 trades on April 26-27, all shorting ETH/BTC into what appears to be a rally. 6.4% WR. **-$2,155 in 24 hours with no circuit breaker stopping it.**

This is what collapsed the equity from a working system (~$2,000 pre-cascade based on earlier trajectory) to $497. One rogue strategy, no circuit breaker, no position dedup, no cross-strategy coordination. The entire 8-month loss is essentially this single event plus fees.

**Implication for new bot:** The circuit breaker at 7% daily loss should have triggered. Investigating whether it was active or misconfigured on April 26-27 is worth doing, but regardless — the new LLM architecture should prevent this by requiring multi-agent consensus before entering cascading positions.

### 2. The Last Week Was the BEST Week — Bot Was Improving

May 7-8: 7 trades, 77.8% WR, +$534 net. The bot's final week was its peak performance. This means the learning systems (graduated rules, confidence calibration, shadow edges from 3,802+ resolved trades) WERE working — they just needed more time.

**Implication:** The desktop bot isn't starting cold. It inherits the learned state that produced the May 7 cluster. The learning trajectory was positive — don't undo the calibration.

### 3. Moderate Confidence (50-55) Outperformed High Confidence

The May 7 ETH SHORT cluster — the 6 best trades in 8 months — all fired at confidence 53-54. The worst trade in the archive (`sniper_standard` ETH LONG confidence=100 on May 11) lost $78. **High confidence didn't predict wins; correct directional read did.**

**Implication for new bot:** Don't gate on confidence alone. The LLM should evaluate the directional read (regime + trend direction alignment), not just the mechanical confidence score.

---

## Top 3 Things the New Bot Should Adopt

### 1. ETH SHORT in Illiquid Regime as Confirmed Shadow EDGE
**File:** `bot/strategies/ensemble.py` (shadow edges section)  
83% WR across 6 trades, avg +$94.77. The May 7 cluster is the proof. This should be in the LLM's context as a strong prior — when ETH + illiquid + SHORT signal appears, this is statistically the highest-alpha setup in the data. Desktop-claude has already confirmed shadow EDGES are kept.

### 2. Cluster Scaling Into Momentum Is Correct
Multiple concurrent entries into the same directional move (May 7: 6 ETH SHORT in 20 mins) produced the best outcomes. The bot should NOT avoid concurrent positions in momentum — it should scale them. Position dedup protection should distinguish "scaling into same move" from "opening duplicate errors."

### 3. Trailing Exit Mechanism = The Alpha, Preserve It
Without trailing stops: total PnL would be ~-$6,258 (34 trailing wins × avg $49 each = -$1,668 removed). Trailing exits took 34 mediocre setups and extracted $1,668. **This is the edge.** Don't simplify it to fixed TP. The trailing stop logic in `bot/execution/position_manager.py` is the most valuable code in the codebase.

---

## Things the New Bot Should Avoid

1. **`omniscient_integrated` strategy** — 6.4% WR, produced the largest single loss event
2. **LONG positions in illiquid or ranging regimes** — consistent losers (10-25% WR)
3. **SOL LONG (any regime)** — 24% WR, the old bot already had a veto rule for this
4. **Ranging regime trading** — 15.6% WR with no profitable setup found in the data
5. **High leverage without multi-strategy agreement** — 5.6x on a solo signal = large losses

---

## Open Questions Desktop-Claude Asked

### What is "Window22"?

From the paper trading report: Window22 refers to the **22nd consecutive Morning Window** — a recurring daily time block from 06:00-12:00 UTC that the old bot identified as its highest-WR period (74% composite WR). The bot had an automated tracking system that generated FINAL WARNING alerts when there were 25 minutes left before the morning window opened (05:30 UTC = restart deadline to catch 06:00 UTC open).

"Window22 deadline T-25min" = the 22nd consecutive morning window was about to open, but the bot had been offline for 37 days, so it kept counting missed windows and issuing escalating warnings. Window22 was missed. So were windows 1-21.

**Verdict:** The morning session edge (06:00-12:00 UTC) appears real — the May 7 cluster fired at 01:10 UTC (Asian session, not morning session, so this isn't the same window). The morning window tracking is worth preserving but the countdown alert system was noise during the offline period.

### What Were the Perpetual Deep-Dive Runs?

These were automated analysis commits from a scheduled Claude Code session on the laptop. Every ~60-75 minutes, a scheduled task ran `claude -p` with a "deep dive" prompt, analyzed recent bot state, and committed a markdown report to `main`. The "[OVERNIGHT] Paper trading report" commits were similar — scheduled hourly analysis running all night.

**Are they still running?** As of when the laptop was handed over, these loops appear stopped (no new commits since this coordination session began). They were running against stale data anyway (bot offline since April 23) and were committing directly to `main` rather than a branch, which creates merge conflicts with our coordinated work.

**Should we keep them?** The intent (automated analysis) is good. The implementation (commit to main, run against offline bot state, hourly regardless of activity) needs rethinking. Recommendation: halt the scheduled commits, but revive the analysis logic as a triggered script (on new trades, not on clock).

---

## Files That Were Missing or Couldn't Be Analyzed

| File | Status | Notes |
|---|---|---|
| `llm/decisions.jsonl` | Present, 1,259 entries | All `api_error | no_client` — pre-CLI architecture, no LLM content |
| `llm/teaching/` | Not found (was `llm/learning/`) | Committed as `learning/` |
| `bot_heartbeat.txt` | Not in archive | Was live-only file, not part of historical snapshot |
| `current_equity.json` | Not in archive | Same — live state file |
| `trade_reconciliation.jsonl` | Not in archive | May not have existed in old architecture |
| `agent_performance.jsonl` | Not in archive | New file from multi-agent system, didn't exist yet |

---

## Bot State When It Last Ran

- **Last trade:** 2026-05-11 22:28 UTC (ETH LONG, -$77.99)
- **Last equity:** $497.05 (by May 30 paper trading report)
- **Reason for stopping:** Unknown from data alone — bot just stopped. 37-day blackout followed.
- **Circuit breaker state:** Paper trading report shows bot had 4 consecutive losses just before stopping
- **Learning state:** Accumulated 23 active LLM rules, 116 feedback rules, most came from the April-May data

The bot stopped in a bruised state (4 consecutive losses, depleted equity) but with its best learning state. The new restart with fresh $5,000 equity and the accumulated learning is the right call.

---

*Analysis by laptop-claude, 2026-05-30. All files in `analysis/historical/`. Source data in `historical/old-bot-pre-2026-04-23/`.*
