# /edge-finder — Discover What Actually Makes Money

## Description
Ruthlessly analyze every trade to find WHERE the edge is, HOW BIG it is, and whether it's growing or dying. No vanity metrics — only PnL truth. This is the most important skill for a profitable bot.

## Arguments
- `$ARGUMENTS` — Optional: "by-regime", "by-strategy", "by-symbol", "by-time", "by-setup", or "full"

## Workflow

### 1. Load ALL Trade Data
Read `bot/data/trades.csv` — every closed trade with full context.
Read `bot/data/llm/decisions.jsonl` — LLM decision that led to each trade.
Read `bot/data/llm/deep_memory/` — trade DNA, strategy fingerprints.

Reject any analysis with <20 trades. Need statistical minimum.

### 2. Edge by Regime (WHERE does the bot make money?)
For each regime (trend, range, panic, high_volatility, low_liquidity, unknown):
```
Regime          Trades  Win Rate  Avg R    Total PnL   Edge?
trend           XX      XX%       +X.XXR   +$X,XXX     ✓ EDGE
range           XX      XX%       -X.XXR   -$XXX       ✗ LEAK
panic           XX      XX%       +X.XXR   +$XXX       ? (small sample)
high_volatility XX      XX%       -X.XXR   -$XXX       ✗ LEAK
```

**KEY OUTPUT:** Which regimes to TRADE and which to SKIP.
If a regime is net negative over 15+ trades → it's a leak. Stop trading it.

### 3. Edge by Strategy (WHAT generates the alpha?)
For each strategy (regime_trend, monte_carlo_zones, confidence_scorer, multi_tier_quality):
- Solo win rate (when only this strategy voted for the trade)
- Contribution: how much PnL is attributable to this strategy?
- Agreement value: does adding this strategy to consensus improve or hurt?
- Which strategy is carrying the others?

**KEY OUTPUT:** Strategy weight recommendations based on actual PnL, not theory.

### 4. Edge by Symbol (WHERE to focus capital?)
For each traded symbol:
```
Symbol  Trades  Win Rate  Avg PnL   Total PnL   PnL/Trade
BTC     XX      XX%       $XXX      $X,XXX      $XX
ETH     XX      XX%       $XXX      $X,XXX      $XX
SOL     XX      XX%       -$XX      -$XXX       -$XX
```

**KEY OUTPUT:** Which symbols are profitable. Kill symbols that consistently lose.
Rank by PnL/Trade (not just total PnL — a symbol with fewer trades but higher PnL/trade is more efficient).

### 5. Edge by Confidence Level (IS THE BOT CALIBRATED?)
Bin all trades by confidence at entry:
```
Confidence  Trades  Win Rate  Avg R    EV/Trade
50-60%      XX      XX%       X.XXR    -$XX     ← SHOULD WE EVEN TRADE THIS?
60-70%      XX      XX%       X.XXR    +$XX
70-80%      XX      XX%       X.XXR    +$XX
80-90%      XX      XX%       X.XXR    +$XX
90-100%     XX      XX%       X.XXR    +$XX
```

**KEY OUTPUT:** The OPTIMAL confidence floor. Below this = negative EV.
If 50-60% confidence trades lose money → raise the floor to 60%.
This is the single most impactful parameter change for profitability.

### 6. Edge by Setup Type (WHICH ENTRIES WIN?)
Categorize trades by how they were entered:
- Trade profile: SCALP / MEDIUM / TREND / REGIME
- Number of strategies agreeing: 2/3/4
- LLM action: go (confirmed) vs. go (against LLM advice)
- Entry timing: first candle vs. delayed entry

**KEY OUTPUT:** The "sniper profile" — what do the top 20% of trades by R-multiple have in common?

### 7. Edge by Exit Type (ARE WE LEAVING MONEY ON THE TABLE?)
```
Exit Type       Trades  Avg R    Best Case?
TP1 Hit         XX      +X.XXR   Could we hold for TP2 more?
TP2 Hit         XX      +X.XXR   Ideal — the system is right
SL Hit          XX      -X.XXR   Could SL be tighter?
Trailing Stop   XX      +X.XXR   Is trailing capturing the move?
Manual Close    XX      +X.XXR   Why are we closing manually?
```

**KEY OUTPUT:** Are exits optimized? If most winning trades exit at TP1 but the move continues, the TP system needs work.

### 8. Edge by Time (WHEN to trade?)
- Hour of day (UTC): win rate and PnL by hour
- Day of week: any pattern?
- Session: Asian / London / NY overlap

**KEY OUTPUT:** If certain hours consistently lose money, consider a trading schedule.

### 9. Edge Decay Detection
Compare recent performance vs historical:
```
Period     Win Rate  Avg R    PnL/Day   Trajectory
Last 24h   XX%       X.XXR    $XXX      —
Last 7d    XX%       X.XXR    $XXX      ↑/↓
Last 30d   XX%       X.XXR    $XXX      ↑/↓
All Time   XX%       X.XXR    $XXX      baseline
```

If recent << all-time → edge is decaying. Something changed in the market or the bot.

### 10. The Profit Report
```
EDGE FINDER REPORT — <timestamp>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TOTAL TRADES: N | WIN RATE: XX% | TOTAL PnL: $X,XXX

#1 PROFIT SOURCE: [regime] + [strategy] + [symbol] = +$X,XXX
#1 PROFIT KILLER: [regime] + [setup type] = -$XXX

IMMEDIATE ACTIONS (highest PnL impact first):
  1. STOP trading in [regime] — saves ~$XXX/month
  2. RAISE confidence floor to XX% — eliminates XX losing trades
  3. INCREASE weight on [strategy] — captures XX% more edge
  4. KILL [symbol] — consistent loser, no edge found
  5. ADJUST exits — TP2 hit rate too low, consider tighter TP1

ESTIMATED IMPACT: +$X,XXX/month if all actions applied
```

This is the skill you run before any other optimization. Find the edge first, then protect it.
