# /pnl-maximize — End-to-End Profitability Optimization

## Description
The master skill. Runs every other profit-impacting analysis in sequence, synthesizes findings, and produces a single prioritized action plan ranked by estimated dollar impact. Everything the bot does should flow through this lens.

## Arguments
- `$ARGUMENTS` — Optional: "quick" (top 3 actions only), "deep" (full analysis), or "execute" (apply approved changes)

## Workflow

### 1. Current P&L Baseline
Read `bot/data/trades.csv` and establish the current reality:

```
P&L BASELINE
━━━━━━━━━━━━
Total Trades:     N
Win Rate:         XX%
Total PnL:        $X,XXX
PnL per Trade:    $XX
PnL per Day:      $XX
Max Drawdown:     -$XXX (-X.X%)
Sharpe Ratio:     X.XX
Current Streak:   [W/L] × N
```

If PnL is negative: this is a "stop the bleeding" session.
If PnL is positive: this is a "grow the edge" session.

### 2. Run Edge Analysis
Perform the core `/edge-finder` analysis:
- Where is the edge? (regime, strategy, symbol, confidence level)
- How big is it?
- Is it growing or decaying?
- What's the optimal confidence floor?

### 3. Run Loss Analysis
Perform the core `/loss-autopsy` analysis:
- What categories of losses exist?
- How much is preventable?
- What are the top 3 profit killers?

### 4. Run Sniper Analysis
Perform the core `/sniper-setup` analysis:
- What do the best trades have in common?
- Can we trade MORE selectively and MORE profitably?
- What's the sniper template?

### 5. Check for Money-Losing Bugs
Quick scan of ROADMAP section 8:
- Is the signal mutation bug still present?
- Is exchange resilience still missing?
- Is position reconciliation still stubbed?
- Each unfixed critical bug = potential money lost.

### 6. Synthesize: The Profit Action Plan
Combine all findings into a SINGLE prioritized list:

```
PROFIT ACTION PLAN — <timestamp>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Current: $XX/day PnL | XX% Win Rate | N trades/day

TIER 1: STOP LOSING MONEY (implement THIS SESSION)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Action                          Est Impact    Difficulty
1  [Raise confidence floor to XX%] +$XXX/mo      Config change
2  [Stop trading range regime]     +$XXX/mo      Config change
3  [Fix signal mutation bug]       +$XXX/mo      1h code fix
4  [Kill symbol X (no edge)]       +$XXX/mo      Config change

TIER 2: MAKE MORE MONEY (implement THIS WEEK)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5  [Increase weight on regime_trend] +$XXX/mo   Config change
6  [Add sniper sizing boost]         +$XXX/mo   Code change
7  [Widen SL by 0.5 ATR]            +$XXX/mo   Config change
8  [Fix strategy weight decay]       +$XXX/mo   Code fix

TIER 3: GROW THE EDGE (implement THIS MONTH)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
9  [Add funding rate strategy]       +$XXX/mo   New strategy
10 [Activate strategy discovery]     +$XXX/mo   Activation
11 [Add exchange resilience]         risk reduction  Code fix

TOTAL ESTIMATED IMPACT: +$X,XXX/month
```

### 7. Quick Mode (if "quick")
Skip the deep analysis. Just show the top 3 highest-impact actions:
- Read most recent edge-finder data (if available)
- Read most recent loss-autopsy data (if available)
- Prioritize by estimated dollar impact
- Show the 3 changes that move the needle most

### 8. Execute Mode (if "execute")
For each approved action:
1. Make the config/code change
2. Run tests: `cd bot && pytest tests/ -x`
3. Run signal check to verify: `cd bot && python run.py signals`
4. Commit with clear message
5. Track the change in `bot/data/llm/growth/parameter_changes.json`

After all changes:
- Run a comparison backtest (before vs after)
- Show projected improvement
- Set a review date (7 days) to validate actual impact

### 9. Ongoing Tracking
After changes are applied:
- Monitor win rate and PnL daily
- Compare against baseline established in step 1
- If metrics worsen after 7 days → revert changes
- If metrics improve → lock in and move to next tier

### 10. The Only Metric That Matters
```
BOTTOM LINE
━━━━━━━━━━━
Before this session:  $XX/day
After planned changes: $XX/day (estimated)
Improvement:          +XX%

Days until profitable: [N days at current rate / ALREADY PROFITABLE]
Monthly run rate:      $X,XXX/month (projected)
```
