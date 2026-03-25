# Morning Prompt — Paste Into Any Terminal

Copy everything below the line into a fresh Claude Code terminal.

---

```
You are continuing an autonomous quant research and trading optimization session for the WAGMI trading bot. The user has been sleeping. Multiple terminals worked overnight. Your job: assess what happened, what was built, what's working, and what to do next.

## Step 1: Read the Overnight Output (do this FIRST)

Read these files to understand what happened while the user slept:

1. `bot/data/manual/SNIPER_LEARNINGS.md` — Live findings log (updated continuously)
2. `bot/data/manual/FILTER_VALIDATION.md` — Validation of the setup-driven filter change (if exists)
3. `bot/data/manual/MORNING_BRIEFING.md` — Overnight report (if exists)
4. `bot/data/manual/DIP_BUY_ANALYSIS.md` — HYPE dip-buy pattern research (if exists)
5. `bot/data/manual/TIME_EDGE_ANALYSIS.md` — Time-of-day edge (if exists)
6. `bot/data/manual/RISK_OPTIMIZATION.md` — Risk level optimization (if exists)
7. `bot/data/manual/MEAN_REVERSION_RESEARCH.md` — Mean reversion exploration (if exists)
8. `bot/data/manual/CODE_AUDIT.md` — Code quality review (if exists)
9. `bot/data/manual/TRADING_PLAYBOOK.md` — The playbook (may have been updated overnight)
10. `bot/manual/CONTEXT.md` — Full system architecture

Also check:
- `bot/data/heartbeat.json` — Is the bot still running?
- `bot/data/manual/sniper_signals.jsonl` — How many signals overnight? (wc -l)
- `bot/data/logs/signal_outcomes.jsonl` — Total bot signals (wc -l)
- `bot/data/manual/sim_status.json` — Did the simulator close any trades?
- `bot/data/manual/sim_trades.jsonl` — Sim trade details (if exists)
- `bot/data/manual/pa_sim_trades.jsonl` — PA simulator trades
- `bot/data/manual/pa_vs_basic_comparison.json` — PA vs basic sim comparison

List all files in `bot/data/manual/` sorted by modification time to see what's new.

## Step 2: Generate Morning Briefing

After reading everything, present a concise morning briefing to the user:

### Format:
```
MORNING BRIEFING — [date]

BOT STATUS: [running/down] | [uptime] | $[equity] | [positions] open

OVERNIGHT SIGNALS:
- Total signals generated: X
- HYPE BUY signals: X (our primary edge)
- SOL SELL signals: X (secondary edge)
- Sniper alerts sent: X

SIMULATOR:
- Starting equity: $100
- Current equity: $X
- Trades closed: X (W:X L:X)
- Win rate: X%

PRICE ACTION:
- HYPE: $X (overnight high/low if available)
- BTC: $X
- SOL: $X

KEY OVERNIGHT FINDINGS:
1. [Most important finding]
2. [Second finding]
3. [Third finding]

WHAT WAS BUILT/IMPROVED:
- [New files created]
- [Code changes made]
- [Tests added/updated]

ACTION ITEMS FOR TODAY:
1. [Highest priority]
2. [Second priority]
3. [Third priority]

OPEN QUESTIONS:
- [Anything needing user decision]
```

## Step 3: Identify Today's Priorities

Based on overnight findings, recommend what to work on today. Consider:

1. **Is the filter validated?** If FILTER_VALIDATION.md exists, does the data support the setup-driven approach? If not, what needs to change?

2. **Did the simulator make money?** If sim trades closed, analyze: WR, avg win, avg loss, which setups won/lost.

3. **Any new edges discovered?** Check if the overnight research found time-of-day patterns, dip-buy patterns, or mean-reversion opportunities.

4. **Is the system ready for real money?** The user wants to fund $100 on Hyperliquid. What's the confidence level? What's still missing?

5. **Bot health** — Any errors, position issues, or anomalies overnight?

## Step 4: Continue Working

After briefing the user, continue with the highest-impact work:

- If filter not validated: run the validation
- If sim is losing: diagnose why and fix
- If new edges found: integrate into the sniper filter
- If system is ready: prepare a "go live" checklist
- If nothing urgent: keep optimizing, backtesting, researching

## Key Context

### What This Project Is
- WAGMI Trading Bot: autonomous crypto trading on Hyperliquid
- Two-layer system: conservative bot ($10k paper) + aggressive sniper ($100 manual scalps)
- The sniper system generates high-leverage (10-25x) signals for manual execution
- Target: $100 → $1000 in 45 days using proven edges

### The Big Discovery Yesterday
- Symbol+side IS the edge, not confidence score
- HYPE BUY: 85% WR at ANY confidence level (data from 1000 counterfactuals)
- SOL SELL: 59% WR at any confidence
- The old confidence filter was rejecting 171 winning HYPE BUY trades worth ~$25K
- Rebuilt the filter to use setup+chop instead of confidence+consensus
- Live proof: saw 29/30 HYPE BUY signals at 68% conf that old filter would reject, price bounced +0.5%

### Data Available
- 1000+ counterfactual resolved records
- 2000+ signal outcomes from bot
- 1000+ sniper signals generated
- 500+ PA simulator trades
- Backtest results, edge analysis, threshold validation

### Key Files
- `bot/manual/sniper_filter.py` — The core filter (setup-driven, just rebuilt)
- `bot/manual/config.py` — Configuration
- `bot/manual/simulator.py` — Basic simulator
- `bot/manual/pa_simulator.py` — PA-enhanced simulator (670 lines)
- `bot/manual/position_rules.py` — Position management rules
- `bot/manual/execution_helper.py` — Hyperliquid order builder
- `bot/manual/trade_journal.py` — Trade logging
- `bot/manual/optimizer.py` — Continuous optimization
- `bot/manual/edge_analysis.py` — Edge analysis engine
- `bot/manual/CONTEXT.md` — Full architecture doc

### Tests
```bash
cd bot && pytest tests/test_manual_sniper.py tests/test_trade_journal.py tests/test_sniper_simulator.py tests/test_sniper_optimizer.py tests/test_execution_helper.py tests/test_pa_simulator.py tests/test_position_rules.py -q
# Should be 251+ tests passing
```

### Rules
- Don't break the running bot (terminal 1)
- Save findings to bot/data/manual/
- Run tests after code changes
- Be a quant: data backs every decision
- The user wants to make real money. Focus on what gets us closer to live trading.
```
