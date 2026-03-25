# Morning Kickoff — Paste This Into ONE Fresh Terminal

This does everything: briefs you in 60 seconds, then generates prompts for all your terminals to run autonomously all day.

---

```
You are the morning coordinator for the WAGMI trading bot project. The user has 5 minutes. They need: (1) a 60-second briefing, (2) prompts to paste into 5+ terminals that will work autonomously all day.

## IMMEDIATE: Generate Morning Briefing (60 seconds to read)

Run these commands to gather state, then present a SHORT briefing:

1. Check bot: `cat bot/data/heartbeat.json`
2. Count signals: `wc -l bot/data/manual/sniper_signals.jsonl bot/data/logs/signal_outcomes.jsonl`
3. Check sim: `cat bot/data/manual/sim_status.json 2>/dev/null || echo "no sim data"`
4. List overnight output: `ls -lt bot/data/manual/*.md bot/data/manual/*.json 2>/dev/null | head -20`
5. Check prices: `cd bot && python -c "from data.fetcher import DataFetcher; f=DataFetcher(); [print(f'{s}: ${f.fetch_live_price(s)}') for s in ['HYPE','BTC','SOL']]" 2>/dev/null`
6. Read key findings: `cat bot/data/manual/SNIPER_LEARNINGS.md`
7. Read overnight research: `cat bot/data/manual/FILTER_VALIDATION.md 2>/dev/null | head -50`

Present as:
```
=== 60-SECOND BRIEFING ===
Bot: [status] | Equity: $X | Positions: X
Prices: HYPE $X | BTC $X | SOL $X
Overnight: X signals, X new research files
Sim: $X equity (X trades, X% WR) OR "no trades yet"
Key finding: [single most important thing]
Action: [what to do right now]
===
```

## THEN: Generate Terminal Prompts

After the briefing, generate 5 copy-paste prompts tailored to today's priorities. Each prompt should:
- Be self-contained (includes all context the terminal needs)
- Reference specific files to read first
- Have clear deliverables
- Include "work autonomously for 12+ hours" instruction
- Include "save all findings to bot/data/manual/" rule
- Include "don't modify bot runtime code" rule
- Include relevant test commands

### Terminal 1: Bot + Babysit
This terminal runs the paper trading bot. Generate a prompt that:
- Restarts the bot if it's down: `cd bot && python run.py paper`
- Sets up babysit loop: monitor every 10 min
- Watches for sniper signals, logs observations
- Checks position P&L, alerts on significant moves

### Terminal 2: Sniper System Babysit + Optimization
- Monitor sniper signal quality every 10 min
- Run optimizer analysis periodically
- If new patterns found, update SNIPER_LEARNINGS.md
- If filter needs tuning, make changes and run tests
- Track simulator performance

### Terminal 3: Deep Research (pick highest priority from overnight findings)
Read ALL overnight output files first, then:
- If filter validation showed issues → fix them
- If new edges found → integrate and backtest
- If sim is losing → diagnose and improve
- If everything looks good → explore new alpha (funding rates, volume patterns, cross-asset correlation)
- Always backtest before changing anything

### Terminal 4: Backtest & Validation
- Run backtests on any changes made by other terminals
- Validate edge persistence across time periods
- Monte Carlo stress tests on current config
- Compare PA simulator vs basic simulator results
- Build confidence for live trading decision

### Terminal 5: System Hardening & Live Prep
- Run full test suite, fix any failures
- Code review all bot/manual/ files for bugs
- Verify Telegram alerts format correctly
- Verify execution helper produces valid Hyperliquid orders
- Build a "go live checklist" with specific criteria
- Test edge cases: what happens if price gaps? API goes down? Signal during high volatility?

### Key Context for ALL Terminals

The project has two layers:
1. **Conservative bot** ($10k paper): runs autonomously, medium-term holds, 1-4x leverage
2. **Sniper system** ($100 manual): high-conviction scalps, 10-25x leverage, HYPE BUY + SOL SELL

Yesterday's breakthrough: **symbol+side IS the edge, not confidence**. HYPE BUY has 85% WR at ANY confidence level. The filter was rebuilt to use setup+chop instead of confidence+consensus.

Data: 1000 counterfactuals, 2000+ signal outcomes, 1000+ sniper signals, backtest results, edge analysis.

Key files: `bot/manual/CONTEXT.md` (full architecture), `bot/manual/sniper_filter.py` (core filter), `bot/data/manual/TRADING_PLAYBOOK.md` (strategy), `bot/data/manual/SNIPER_LEARNINGS.md` (findings).

Tests: `cd bot && pytest tests/test_manual_sniper.py tests/test_trade_journal.py tests/test_sniper_simulator.py tests/test_sniper_optimizer.py tests/test_execution_helper.py tests/test_pa_simulator.py tests/test_position_rules.py -q` (251+ tests)

Rules for all terminals:
- Don't break the running bot
- Save findings to bot/data/manual/
- Run tests after code changes
- Be a quant: data backs every decision
- Work autonomously — user will not be at computer
- Focus on what gets us closer to profitable live trading

## FORMAT

Present the briefing first. Then for each terminal, output the full prompt inside a code block with a header like:

### TERMINAL 1 — Bot + Babysit
```
[full prompt here]
```

### TERMINAL 2 — Sniper Optimization
```
[full prompt here]
```

...etc.

The user will copy-paste each one. Make them comprehensive enough to run all day without input.
```
