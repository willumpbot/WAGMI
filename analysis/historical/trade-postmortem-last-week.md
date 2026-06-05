# Trade Postmortem — Last Week of Historical Data
*Generated: 2026-05-30 | Period: 2026-05-05 → 2026-05-11 (last active week)*

The bot's final week before going offline May 11. The cleanest data — no omniscient_integrated, no cascade, just the ensemble doing its job.

---

## Week Summary

| Metric | Value |
|---|---|
| Trades | 9 |
| Win Rate | **77.8%** (7W / 2L) |
| Gross PnL | +$890.39 |
| Fees | -$355.58 |
| Net PnL | **+$534.81** |
| Active days | May 7 + May 8 + May 11 |

This was the best week in 8 months of data. The bot finally clicked in its final days.

---

## Trade-by-Trade Breakdown

### May 7 — The ETH SHORT Cluster (6 trades, 20 minutes)

All 6 trades fired between 01:10-01:31 UTC. ETH was breaking down.

| Time | Symbol | Side | Lev | PnL | Outcome | Regime |
|---|---|---|---|---|---|---|
| 01:10 | ETH | SHORT | 5.6x | +$170.27 | TRAILING_WIN | illiquid |
| 01:10 | ETH | SHORT | 5.6x | +$174.70 | TRAILING_WIN | (none) |
| 01:29 | ETH | SHORT | 5.6x | +$132.10 | TRAILING_WIN | (none) |
| 01:30 | ETH | SHORT | 5.6x | +$140.86 | TRAILING_WIN | illiquid |
| 01:31 | ETH | SHORT | 5.6x | +$128.88 | TRAILING_WIN | illiquid |
| 01:31 | ETH | SHORT | 5.6x | +$127.24 | TRAILING_WIN | illiquid |

**Subtotal: +$873.05 gross from 6 trades.**

**What went right:**
- All 6 triggered trailing stops that ran the full move
- Multiple concurrent positions captured the move at scale
- Strategy: trend_breakout (primary driver) with confidence 53-54 (not high — just directional)
- Regime classification: illiquid — low liquidity = directional price discovery, not noise
- Time of day: 01:00 UTC = Asian session, reduced interference

**What's worth noting:**
- Confidence was only 53-54. The bot DID NOT require high confidence to fire. In hindsight, this was correct — the move was clear directionally but mechanical signals weren't screaming.
- Multiple entries at same timestamp = position scaling, not a bug
- The trailing exit captured $130-175 per trade instead of a fixed $20-30 TP

---

### May 8 — BTC SHORT

| Time | Symbol | Side | Lev | PnL | Outcome | Regime |
|---|---|---|---|---|---|---|
| 03:16 | BTC | SHORT | 7.0x | +$145.29 | TRAILING_WIN | illiquid |

**What went right:** Higher leverage (7x vs 5.6x) on a BTC breakout. Two-strategy agreement (confidence_scorer + trend_breakout). Trailing exit again captured a full move.

---

### May 11 — Two Losses

| Time | Symbol | Side | Lev | PnL | Outcome | Regime |
|---|---|---|---|---|---|---|
| 20:16 | ETH | LONG | 7.0x | -$50.96 | CLEAN_LOSS | trending |
| 22:28 | ETH | LONG | 5.0x | -$77.99 | CLEAN_LOSS | (none) |

**What went wrong:**
- Both were ETH LONG positions — going against the prevailing short trend
- Trending regime on the first; second had no regime tag
- CLEAN_LOSS = hit stop directly, no TP1 touched
- The second trade (22:28) was `sniper_standard` strategy at confidence=100 — highest confidence in the system, still a loser, confirming that high confidence doesn't = profitable in wrong conditions

**Pattern:** The two losses were LONGs after a week of SHORT dominance. The market was in a SHORT phase and LONG entries were fading the primary direction.

---

## Week Lessons

### 1. The Bot's Best Mode = Cluster Entry + Trailing Exit

Six trades in 20 minutes, all the same setup, all trailing wins. This is the bot operating at peak efficiency. The key ingredients:
- Strong directional signal (ETH breaking down)
- Low-liquidity regime (illiquid = directional move, not noise)
- Trailing stop configuration (captures the full move)
- Multiple concurrent entries = size the winner

### 2. SHORT Bias Was Correct for This Period

7/9 profitable trades were SHORT. The 2 losses were both LONGs. The market was in a macro SHORT phase. The new bot's LLM should recognize prevailing regime direction and weight accordingly.

### 3. Confidence 50-55 Was the Sweet Spot

The ETH SHORT cluster fired at 53-54 confidence. If the bot had required 70+ confidence to trade, ALL SIX top trades would have been skipped. **Moderate confidence + correct directional bet = big win.**

### 4. The Final Trades Were the Best Trades

After months of losses, the bot's last active week was its best. This suggests the learning systems were improving — graduated rules had accumulated enough data to be useful, and the ensemble was better calibrated.

**The new bot starts with all those accumulated learnings in the memory stores.** It's starting from week-8, not week-1.

---

## What Stopped the Bot

After May 11, no more trades appear in trades.csv. The paper trading report (May 30) confirms the bot went offline on **2026-04-23** (the historical data had a gap — it kept running until ~May 11 based on the trade data, then stopped).

By May 30, equity had fallen to $497 from $5,000 start — 90% drawdown driven almost entirely by the April 26-27 omniscient_integrated disaster.
