# Ready for Forensic Backtest Analysis
**Status: FRAMEWORK COMPLETE, WAITING FOR BACKTEST DATA**

## What's Ready

1. **QUARTERLY_FORENSIC_BACKTEST.md** — Complete forensic analysis template
   - Trade-by-trade walkthroughs (every decision, all 4 agents)
   - Agent accuracy matrix (Regime/Trade/Risk/Critic scores)
   - Feature importance analysis
   - Failure mode forensics
   - Confidence calibration audit
   - Leverage sizing analysis

2. **Backtest Framework Specifications**
   - 14 quarterly periods (Q1 2023 → Q2 2026)
   - All 4 symbols (BTC, ETH, SOL, HYPE)
   - Full multi-agent LLM pipeline
   - Maximum data extraction protocol

## What's Needed

**Bot Backtest Command** — Need to know actual signature:
```bash
cd bot && python run.py backtest --help
# Shows: actual parameters and options
```

Once we know the real command, we can:
1. Run all 14 quarters with proper parameters
2. Extract results JSON files
3. Feed them into the forensic analysis framework
4. Generate complete walkthroughs + synthesis report

## Next Steps

1. Run `python run.py backtest --help` from bot/ directory
2. Send output so we know actual CLI signature
3. I'll update the automation script with correct command
4. Launch full forensic backtest (seamless, autonomous, saves as we go)

## Alternative: Manual Path

If you want to start immediately without waiting:
```bash
cd bot
python run.py backtest --symbols BTC ETH SOL HYPE [other flags?]
# Then save output to: coordination/backtest_results/backtest_raw.json
# I'll process it through the forensic framework
```

**The framework is ready. Just need the backtest data.**
