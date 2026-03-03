# /loss-autopsy — Find and Eliminate Profit Killers

## Description
Forensic analysis of every losing trade to identify systematic profit-killers. Not "why did this one trade lose" but "what pattern keeps killing us." The goal is to eliminate entire categories of losses.

## Arguments
- `$ARGUMENTS` — Optional: "worst" (biggest losses), "patterns" (loss categories), "preventable" (losses that should have been caught), or "all"

## Workflow

### 1. Load All Losing Trades
Read `bot/data/trades.csv` — filter to losses only.
Read `bot/data/llm/decisions.jsonl` — get the decision context for each loss.

Sort losses by magnitude: biggest dollar loss first.

### 2. Loss Categorization
For every losing trade, classify the root cause:

**Category A: BAD ENTRY (shouldn't have entered)**
- Entered against the regime (long in panic, short in trend)
- Entered below confidence floor that should have blocked it
- Entered during chop (chop detector should have caught it)
- Entered on stale data (data was >5 min old)
- All strategies barely agreed (minimum votes, low confidence)

**Category B: BAD EXIT (right direction, wrong management)**
- SL too tight (ATR-based SL hit on normal volatility)
- SL too wide (held through a reversal, gave back too much)
- Didn't trail soon enough (TP1 hit, then SL hit)
- Trailed too aggressively (stopped out on a dip before continuation)

**Category C: BAD SIZING (right trade, wrong size)**
- Position too large (loss magnitude disproportionate)
- Leverage too high for the setup
- Multiple correlated positions (SOL + ETH both long = double exposure)

**Category D: EXTERNAL (no fault of the bot)**
- Flash crash / black swan event
- Exchange issue (fill at worse price than expected)
- Funding rate ate the profit

**Category E: AGENT FAILURE**
- Regime Agent misclassified → wrong context for Trade Agent
- Critic Agent approved a bad trade (should have vetoed)
- Risk Agent sized too aggressively
- No agent was consulted (LLM mode too low)

### 3. Pattern Mining
Across all losses, find recurring patterns:

```
LOSS PATTERNS (by frequency)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Pattern                         Count  Total PnL   Preventable?
Entered in range regime         XX     -$X,XXX     YES — skip range
SL hit on normal volatility     XX     -$XXX       YES — widen SL
High leverage + low confidence  XX     -$XXX       YES — fix sizing
Counter-trend in strong trend   XX     -$XXX       YES — regime filter
Multiple correlated positions   XX     -$XXX       YES — correlation limit
```

### 4. The "Preventable Losses" Calculation
For each loss, ask: **Could this have been prevented with an existing system?**

- Was the signal below what should be the confidence floor? → Preventable
- Did the chop detector fire but was overridden? → Preventable
- Did the Critic veto but override happened? → Preventable
- Was the regime clearly wrong for this trade? → Preventable
- Was the position oversized vs risk limits? → Preventable

```
PREVENTABLE LOSS ANALYSIS
━━━━━━━━━━━━━━━━━━━━━━━━━
Total Losses:          $X,XXX
Preventable Losses:    $X,XXX (XX%)
Unavoidable Losses:    $XXX (XX%)

If we had prevented preventable losses:
  Win Rate:            XX% → XX% (+X%)
  Total PnL:           $X,XXX → $X,XXX (+$X,XXX)
```

This is the "money left on the table by not having tighter filters."

### 5. Worst Trades Deep Dive
For the 5 biggest losses:
- Full context: regime, signals, confidence, LLM decision
- What went wrong: specific root cause
- Was it preventable: yes/no, how
- What rule would have stopped it
- Code change needed (with file + line reference)

### 6. SL/TP Analysis
Across all trades:
- Average SL distance (as % of entry)
- Average TP1 distance
- Average TP2 distance
- How often does price hit SL vs TP1 first?
- Is SL optimally placed? (too tight = too many SL hits; too wide = too much risk per loss)

**Optimal SL calculation:** Find the SL distance that maximizes (win_rate × avg_win - loss_rate × avg_loss).

### 7. Correlation Losses
Check for simultaneous losing positions:
- Were losses on the same day across multiple symbols?
- Were correlated assets (ETH/SOL both following BTC) all losing together?
- Portfolio risk: max simultaneous drawdown

### 8. Fix Priority List
Rank all fixes by **dollars saved per month**:

```
FIX PRIORITY (by estimated monthly savings)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Fix                              Est Savings  Difficulty  File
1  Skip range regime trades         $XXX/mo      Config      trading_config.py
2  Raise confidence floor to XX%    $XXX/mo      Config      trading_config.py
3  Widen SL by X% ATR               $XXX/mo      Config      trading_config.py
4  Add correlation limit            $XXX/mo      Code        execution/risk.py
5  Fix signal mutation bug          $XXX/mo      Code        strategies/ensemble.py
```

### 9. Implementation
For the top 3 fixes by savings:
- Show the exact code/config change needed
- Show the estimated impact (trades eliminated, PnL saved)
- Verify with backtest if possible
- Apply with user confirmation

### 10. Report
```
LOSS AUTOPSY — <timestamp>
━━━━━━━━━━━━━━━━━━━━━━━━━

TOTAL LOSSES: $X,XXX across N losing trades

ROOT CAUSES:
  Bad Entry:    XX% of losses ($X,XXX)
  Bad Exit:     XX% of losses ($XXX)
  Bad Sizing:   XX% of losses ($XXX)
  External:     XX% of losses ($XXX)
  Agent Error:  XX% of losses ($XXX)

PREVENTABLE: $X,XXX (XX% of total losses)

TOP PROFIT KILLERS:
  1. [Pattern] — cost us $X,XXX — FIX: [specific change]
  2. [Pattern] — cost us $XXX — FIX: [specific change]
  3. [Pattern] — cost us $XXX — FIX: [specific change]

APPLYING ALL FIXES: estimated +$X,XXX/month improvement
```
