# /trade-postmortem — Closed Trade Analysis

## Description
Deep analysis of closed trades to extract lessons, identify patterns, and feed improvements back into the system. Works on recent trades or specific trade IDs.

## Arguments
- `$ARGUMENTS` — Optional: "last", "last 5", trade ID, or "today"/"week" for time ranges

## Workflow

### 1. Load Trade Data
- Read `bot/data/trades.csv` for trade records
- Read `bot/data/llm/decisions.jsonl` for corresponding LLM decisions
- Filter based on `$ARGUMENTS`:
  - `last` → most recent closed trade
  - `last N` → last N closed trades
  - `today` → all trades closed today
  - `week` → all trades closed this week
  - Trade ID → specific trade

### 2. Per-Trade Analysis
For each closed trade, extract:

**Execution Quality:**
- Entry price vs signal entry (slippage)
- Actual fill vs intended size
- Time from signal to fill
- Exit type: TP1 hit, TP2 hit, SL hit, trailing stop, manual close

**PnL Breakdown:**
- Gross PnL (before fees)
- Fees paid
- Net PnL
- R-multiple (PnL / risk amount)
- % of account risked vs actual outcome

**Decision Quality:**
- What did each agent say? (Regime/Trade/Risk/Critic)
- Was the Critic's assessment correct?
- If Critic approved a loss: what did it miss?
- If Critic vetoed a would-be win: was the veto still correct? (risk management can be right even on missed profits)

**Market Context at Entry:**
- Regime at entry vs regime at exit (did it shift?)
- Volatility at entry vs during trade
- Was this a trend trade in a trending market? Or a counter-trend gamble?

### 3. Pattern Recognition
Across multiple trades, look for:
- **Winning patterns**: What do wins have in common? (regime, confidence level, strategy agreement, time of day)
- **Losing patterns**: What do losses have in common?
- **Regime-specific performance**: Win rate by regime type
- **Strategy attribution**: Which strategy's signals led to the best R-multiples?
- **Time-based patterns**: Better performance at certain hours/days?

### 4. Lesson Extraction
For each meaningful pattern found:
- Formulate as a testable hypothesis
- Example: "Trades in 'range' regime with confidence <65 have negative EV"
- Example: "SOL signals from monte_carlo_zones have 70% win rate in trending regimes"

### 5. Memory Integration Check
- Were relevant lessons from previous postmortems available in memory?
- Read `bot/data/llm/deep_memory/` for stored patterns
- Check if the Learning Agent captured the right lessons
- Identify any lessons that SHOULD have been applied but weren't

### 6. Actionable Recommendations
Based on analysis:
- **Parameter tweaks**: Adjust confidence floor, strategy weights, etc.
- **Agent prompt updates**: If agents consistently misjudge a scenario
- **New rules**: If a pattern is strong enough to become a hard rule
- **Memory updates**: Store new lessons in deep memory for future trades

### 7. Report Format
```
TRADE POSTMORTEM — <date range>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Trades Analyzed: N
Win Rate: XX.X%
Avg R-Multiple: X.XX
Total Net PnL: $X,XXX

BEST TRADE:  <symbol> <side> +$XXX (+X.XXR)
WORST TRADE: <symbol> <side> -$XXX (-X.XXR)

KEY LESSONS:
1. [Lesson with supporting data]
2. [Lesson with supporting data]

RECOMMENDED ACTIONS:
1. [Specific change with expected impact]
2. [Specific change with expected impact]
```
