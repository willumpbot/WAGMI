# /babysit — Claude Code Paper Trading Overwatch

## Description
Continuous monitoring loop that uses Claude Code as the AI brain. Each cycle: collects intel, analyzes signals, checks for regime mismatches and missed trades, and updates the knowledge base.

## Workflow

### Step 1: Collect Intel + Run Analyzer
```bash
cd bot && python tools/intel_collector.py 2>&1
cd bot && python tools/overwatch_analyzer.py 2>&1
```

### Step 2: Check for Price Movement on Prior Near-Misses
Read the last 20 near_miss entries from `bot/data/paper_trading_intel.jsonl`. For each, compare the rejection price to current price. If price moved >1% in the signal direction, that was a MISSED PROFITABLE TRADE — log it.

### Step 3: Check for New Trades
```bash
cat bot/data/trades.csv 2>/dev/null | tail -5
cat bot/data/heartbeat.json 2>/dev/null
```
If new trades appeared since last cycle, analyze entry quality.

### Step 4: Analyze & Summarize
Provide a SHORT (3-5 line) status update covering:
- Any new trades or position changes
- Near-misses that became profitable (missed opportunities)
- Regime mismatches (bot says consolidation but market is trending)
- Key risk flags

### Step 5: Update Knowledge Base
If you observe a NEW pattern not yet in `bot/data/PAPER_TRADING_LEARNINGS.md`, append it. Categories:
- **Regime classifier issues** (e.g., "BTC classified as consolidation during +4% trending day")
- **EV gate behavior** (e.g., "Solo signals in consolidation always rejected — need 2+ agreement")
- **Strategy agreement patterns** (e.g., "SOL rarely gets multi-strategy agreement during overbought")
- **Missed opportunity patterns** (e.g., "HYPE SELL near-miss at $38.10 later moved to $37.50")
- **Parameter sensitivity** (e.g., "Changing solo deflation from 0.50 to 0.55 would have passed BTC BUY")

DO NOT repeat findings already logged. Only add genuinely new observations.
