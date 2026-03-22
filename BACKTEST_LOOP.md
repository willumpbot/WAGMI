# Iterative Backtest Optimization Loop

## Your Mission
You are an autonomous trading system optimizer. Your goal is to **increase win rate and expected value (EV)** through iterative backtesting and targeted code changes.

## Prerequisites
```bash
cd /path/to/WAGMI
pip install ccxt pandas   # Required for backtesting
```

## The Prompt
Copy-paste this into Claude CLI after running `claude` from the WAGMI directory:

---

```
I need you to run an iterative backtest optimization loop. Here's how it works:

CONTEXT:
- We're paper trading on Hyperliquid (HYPE, SOL, BTC)
- Paper trading has ~45 gates/filters vs backtest's ~10. Run with FULL gates (no --raw, no --relaxed-cb) to stay realistic
- Our previous 60-day raw backtest showed 802 trades with ~38% win rate — that was unrealistic (no gates, no LLM veto)
- We need the backtest to reflect what paper trading actually does
- Focus on: win rate, profit factor, EV per trade, max drawdown

ITERATION LOOP:
For each iteration, do exactly this:

1. RUN THE BACKTEST:
   cd bot && python run.py backtest --days 30 --equity 10000 --output data/bt_iteration_N.json --csv data/bt_iteration_N.csv
   (Replace N with iteration number, starting at 1)

2. ANALYZE THE RESULTS — Read the JSON output and answer:
   - Total trades, win rate, profit factor, net PnL, max drawdown
   - By-strategy breakdown: which strategy contributes most wins vs losses?
   - By-regime: which regime has worst performance?
   - Exit types: what % are SL hits vs TP1 vs TP2 vs trailing?
   - Confidence analysis: are high-confidence trades actually winning more?
   - Gate effectiveness: which gates are blocking the most signals? Are they blocking good or bad ones?
   - Trailing analysis: are trailing stops helping or hurting?
   - Signal funnel: how many signals generated vs how many become trades?
   - Recommendations section: what does the engine itself suggest?

3. IDENTIFY THE SINGLE WEAKEST LINK — Pick ONE specific problem:
   - "SL hits are 65% of exits — stops are too tight"
   - "Range regime has 25% win rate — should skip or filter harder"
   - "Confidence 60-70 trades lose money — raise the floor"
   - "Trailing stops give back too much — tighten the trail"
   - "Fee drag kills tight-stop trades — widen minimum stop width"
   - "One strategy has negative contribution — reduce its weight or disable"

4. MAKE A TARGETED FIX — Change ONE thing:
   - Adjust a parameter in trading_config.py
   - Modify a strategy threshold
   - Tune a gate setting in signal_pipeline.py
   - Adjust trailing stop behavior in position_manager.py
   - Change ensemble voting thresholds
   Keep changes small and isolated. Never change more than one thing per iteration.

5. DOCUMENT THE CHANGE — Before re-running, print:
   "ITERATION N: [what you changed] because [why, citing specific numbers from the backtest]"

6. RE-RUN AND COMPARE — Run the backtest again and compare key metrics:
   - Did win rate improve?
   - Did profit factor improve?
   - Did we lose too many trades (signal count dropped too much)?
   - Did max drawdown get worse?
   If the change made things worse, REVERT IT and try something different.

RULES:
- Never change more than 1 parameter per iteration
- Always compare iteration N vs N-1 before proceeding
- If a change hurts performance, revert immediately
- Keep a running log: iteration, change made, before/after metrics
- After 5 iterations, print a summary table of all iterations
- Prioritize changes that improve BOTH win rate and profit factor
- Don't chase trade count — fewer good trades > many bad trades
- Never weaken risk/safety gates to get more trades
- All changes must be in code files, not just config — commit-worthy changes

TARGETS:
- Win rate: > 50% (from current ~38%)
- Profit factor: > 1.5
- Max drawdown: < 15%
- EV per trade: positive and growing

Start iteration 1 now. Run the backtest and show me the baseline.
```

---

## What to Expect
- Each iteration takes 2-5 minutes (backtest runtime + analysis)
- Claude will make small, data-driven changes
- You'll see a clear before/after comparison each time
- After 5 iterations you get a summary table
- You can interrupt anytime and say "show me the summary so far"

## Useful Follow-up Commands
- "Focus on [strategy/regime/exits] for the next 3 iterations"
- "Revert the last change and try something different"
- "Run with --relaxed-cb to see if circuit breakers are too aggressive"
- "Compare iteration 1 vs current side by side"
- "Commit all improvements and push"
- "Now run a 60-day backtest to validate the changes hold up on longer data"

## After Optimization
Once you're happy with backtest results:
1. Run paper trading with the improved config
2. Compare paper results to backtest predictions
3. If they match within 10%, the backtest is calibrated
