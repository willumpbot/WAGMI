# /sniper-setup — Replicate the Highest-R Winning Trades

## Description
Reverse-engineer the bot's best trades to build a "sniper profile" — the exact conditions that produce the highest R-multiple wins. Then tune the system to find more of those setups and size them aggressively.

## Arguments
- `$ARGUMENTS` — Optional: "top10" (top 10 trades), "template" (build reusable setup), or specific symbol

## Workflow

### 1. Identify Sniper Trades
Read `bot/data/llm/deep_memory/` — trade DNA store.
Read `bot/data/trades.csv` — all closed trades.

Filter to the **top 20% by R-multiple** (reward relative to risk taken).
These are the "sniper" trades — highest quality setups.

Minimum criteria: R > 2.0, PnL > $50

### 2. Sniper Trade Anatomy
For each sniper trade, extract the FULL context:

```
SNIPER TRADE #1: BTC LONG +$450 (+3.2R)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Regime at Entry:       trend (high confidence)
Strategies Agreed:     4/4 (regime_trend, monte_carlo, confidence, multi_tier)
Confidence:            82%
Entry Price:           $97,500
SL:                    $96,200 (1.3% away, 1.5 ATR)
TP1:                   $99,800 (hit after 4h)
TP2:                   $102,000 (hit after 11h)
Exit:                  TP2 hit
Hold Time:             11 hours
Leverage:              5x
LLM Action:            go (confirmed by Critic)
BTC Trend at Entry:    bullish (6h and daily aligned)
Funding Rate:          0.01% (neutral)
Volume:                1.3x average
ATR:                   $850 (normal)
Time of Day:           14:00 UTC (London/NY overlap)
```

### 3. Pattern Extraction
Across ALL sniper trades, find what they have in common:

**Regime Profile:**
- Which regimes produce snipers? (likely: trend >> range)
- What confidence level? (likely: >75%)

**Strategy Agreement:**
- How many strategies agreed? (likely: 3-4)
- Which strategy combinations?
- Does any single strategy appear in ALL snipers?

**Entry Conditions:**
- ATR range (is there a "sweet spot" volatility?)
- Volume relative to average
- Funding rate range
- BTC trend direction (do alts need BTC aligned?)

**Timing:**
- Time of day clusters
- Day of week patterns
- Session (Asian/London/NY)

**Risk/Reward Structure:**
- SL distance (as ATR multiple and %)
- TP1 distance
- TP2 distance
- Hit TP1 rate vs TP2 rate

### 4. Build Sniper Template
Distill into a concrete, testable template:

```
SNIPER TEMPLATE
━━━━━━━━━━━━━━━
REQUIRED (must all be true):
  ✓ Regime: trend or high_volatility
  ✓ Strategies agreeing: ≥3
  ✓ Confidence: ≥75%
  ✓ BTC trend aligned with trade direction
  ✓ Volume: ≥1.0x average
  ✓ Funding rate: <0.03% (not fighting funding)
  ✓ ATR: between 0.8x and 2.0x average

OPTIMAL (improve R if present):
  + All 4 strategies agree
  + London/NY overlap hours (12-18 UTC)
  + Regime freshly classified (not stale)
  + No recent loss streak (circuit breaker clear)

SIZING:
  Base match (all required): 1.0x position size
  Optimal conditions met: 1.3-1.5x position size
```

### 5. Backtest the Template
Run the sniper template against historical data:
- How many historical trades match the template?
- What's the win rate of template matches?
- What's the avg R-multiple?
- What's the expected PnL if we ONLY traded these setups?

Compare: current system PnL vs. sniper-only PnL
- If sniper-only is higher with fewer trades → the bot should be MORE selective

### 6. Anti-Sniper Analysis
Also look at the WORST trades (bottom 20% by R):
- What do they have in common?
- Build an "anti-template" — conditions that predict losses
- These are the trades to FILTER OUT

```
ANTI-SNIPER TEMPLATE (AVOID)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AVOID if any are true:
  ✗ Regime: range or unknown
  ✗ Strategies agreeing: only 2 (minimum)
  ✗ Confidence: <65%
  ✗ Counter-trend to BTC
  ✗ Funding rate: >0.03% against position
  ✗ Volume: <0.5x average (dead market)
```

### 7. Implementation
If the template is strong (>70% WR on 20+ historical matches):

**Immediate actions:**
- Update confidence floor to match template minimum
- Add regime filter (skip range/unknown if data supports it)
- Adjust strategy weights to favor sniper-producing strategies
- Add BTC trend alignment check

**Code changes needed:**
- Where to add the template check (signal_pipeline.py or ensemble.py)
- How to implement the sizing boost for template matches
- How to store and version the template for evolution

### 8. Report
```
SNIPER ANALYSIS — <timestamp>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SNIPER TRADES: N (top 20% by R-multiple)
AVG R-MULTIPLE: +X.XXR
AVG PnL: +$XXX

SNIPER DNA:
  Regime:     trend (XX%), high_vol (XX%)
  Agreement:  3.X strategies average
  Confidence: XX% average (min: XX%)
  Session:    London/NY overlap (XX%)
  BTC aligned: XX% of snipers

TEMPLATE BACKTEST:
  Historical matches: N trades
  Win Rate: XX%
  Avg R: +X.XXR
  Total PnL: +$X,XXX

CURRENT SYSTEM vs SNIPER-ONLY:
  Current: N trades/month, XX% WR, $XXX PnL
  Sniper:  N trades/month, XX% WR, $XXX PnL
  Verdict: [Trade less but win more / Keep current / Needs more data]

ACTIONS TO CAPTURE MORE SNIPERS:
  1. [Specific change with estimated PnL impact]
  2. [Specific change with estimated PnL impact]
```
