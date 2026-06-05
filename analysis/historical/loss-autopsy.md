# Loss Autopsy — Forensic Analysis of Worst Losses
*Generated: 2026-05-30 | Source: historical/old-bot-pre-2026-04-23/trades.csv*

---

## Summary of Loss Damage

| Category | Trades | PnL |
|---|---|---|
| `omniscient_integrated` strategy (ALL losses) | 47 | -$2,155.16 |
| ETH LONG in illiquid regime | 13 | -$1,114.05 |
| ETH SHORT + omniscient + ranging | 7 | -$564.42 |
| SOL LONG (all regimes) | 25 | -$661.13 |
| ETH LONG with no regime tag | 7 | -$540.48 |
| **Total explainable losses** | | **~$5,035** |

---

## Loss #1: The April 26-27 Omniscient Disaster

**The single biggest preventable event in 8 months of data.**

### What Happened

On 2026-04-26 at ~04:37 UTC and again at ~23:45 UTC, and continuing through 2026-04-27 at 03:40 UTC, the bot made **47 consecutive trades** using the `omniscient_integrated` strategy. **All but 3 were losses.** Total damage: **-$2,155.16**.

### The Timeline

```
2026-04-26 04:37 UTC — BTC SHORT begins (×12 entries in 9 minutes)
  All losses, small ($0.52–$4.43 each) = -$39.94

2026-04-26 14:22 UTC — One more BTC SHORT = -$2.49

2026-04-26 21:56 UTC — ETH SHORT begins (×2 small wins)
2026-04-26 23:41 UTC — ETH SHORT = -$2.40
2026-04-26 23:45 UTC — ETH SHORT ×2 = -$62.07, -$5.42

2026-04-27 00:40 UTC — ETH SHORT ×2 = -$0.59, -$5.33
2026-04-27 00:42 UTC — ETH SHORT ×5 in 1 minute = -$8.35, -$7.86, -$130.78, -$169.83, -$78.06
2026-04-27 00:43 UTC — ETH SHORT = +$104.62 (the one that worked)
2026-04-27 00:44 UTC — ETH SHORT = -$0.89

2026-04-27 02:17 UTC — ETH SHORT ×2 same minute = -$310.36, -$310.36
2026-04-27 02:34 UTC — ETH SHORT = -$323.68
2026-04-27 02:39 UTC — ETH SHORT = -$213.29

2026-04-27 03:39 UTC — ETH SHORT ×2 = -$142.01, -$109.46
```

### Root Cause

1. **ETH was in a RALLY on April 26-27** (likely the HYPE/ETH momentum surge). The bot kept shorting into a rising market.
2. **No circuit breaker stopped the cascade.** 47 trades with no intervention — the circuit breaker did not fire.
3. **omniscient_integrated was not ensemble-gated.** The strategy operated independently and kept re-entering without coordinating with other strategies.
4. **Duplicate/concurrent entries.** Multiple entries at the same timestamp (02:17 UTC: two identical -$310.36 trades) suggest either a race condition or intentional multi-position entry without position deduplication.

### Preventability

**Fully preventable.** Three interventions would have stopped this:
1. Circuit breaker should have tripped after 5-7 consecutive losses
2. `omniscient_integrated` had no cross-strategy coordination requirement
3. No duplicate-entry protection (same timestamp, same symbol, same side)

---

## Loss #2: ETH LONG in Illiquid Regime

**13 trades, -$1,114.05, 15.4% WR**

ETH LONGs in illiquid regime were the second biggest loser. Pattern:
- Entered when liquidity was low (illiquid regime)
- Market made random, directional moves against position
- 85% of these trades were losses

**Why:** Illiquid regime = low liquidity = price moves are driven by order flow imbalances, not trend. A LONG in illiquid is a bet on a specific direction with no underlying momentum to support it.

**Fix:** LLM should learn to avoid LONG bias in illiquid regime. The old graduated_rules.json had `illiquid_regime_penalize_v1` at gate=100% but this was made informational — the LLM needs to ACTUALLY apply this learning.

---

## Loss #3: SOL LONG (All Regimes)

**25 trades total, -$661 combined**

SOL LONG had a 24% WR. The paper trading report confirms `sol_long_veto_v1` was set to gate=100% — meaning the old bot itself recognized this and blocked it. But 25 trades still happened before or after that rule was created.

**Fix:** This is already handled by the shadow rules learned from old data. Ensure the LLM context includes this when evaluating SOL LONG signals.

---

## Loss #4: Large Single-Trade Losses

Top 5 worst single trades:
| Trade | PnL | What It Was |
|---|---|---|
| 2026-04-27 02:34 ETH SHORT | -$323.68 | omniscient cascade, 5.6x lev |
| 2026-04-26 23:51 ETH SHORT | -$310.38 | omniscient cascade, 5.6x lev |
| 2026-04-27 02:17 ETH SHORT | -$310.36 | omniscient cascade, 5.6x lev |
| 2026-04-27 02:17 ETH SHORT | -$310.36 | DUPLICATE of above same second |
| 2026-04-27 02:39 ETH SHORT | -$213.29 | omniscient cascade, 5.6x lev |

**Pattern:** All 5 are ETH SHORT, all from the same cascade, all at 5.6x leverage. The $310 losses = roughly $55 position × 5.6x leverage × $ETH move. At 5.6x, a 1% move = 5.6% loss on position.

---

## Loss Pattern: Fee Drag

From the paper trading report: 24.7% of SL exits (87/352) had TP1 reachable afterward. Estimated missed value: **$1,119.29**.

This means the stop loss was too tight — it was firing at the exact level of natural volatility, then the trade would have recovered and hit TP1. The LLM in the new bot should widen stop losses slightly when volatility is high.

---

## What NOT to Repeat

| Pattern | Why |
|---|---|
| `omniscient_integrated` strategy | 6.4% WR, no circuit breaker, cascades |
| ETH LONG in illiquid regime | 15% WR, structural loser |
| SOL LONG (any regime) | 24% WR, confirmed edge against |
| LONG in ranging regime | 25% WR, no directional bias to trade with |
| Multiple concurrent entries without position dedup | Created duplicate -$310 trades |
| Shorting into a rally (no regime check) | April 27 disaster — no uptrend check |
| 5.6x leverage on low-confidence setups | Amplified all losses significantly |
