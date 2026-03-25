# Manual Sniper Signal System — Full Context

## What This Is
An aggressive manual copy-trade system that reads the WAGMI bot's signals and generates actionable alerts for manual execution on Hyperliquid. Target: scale a $100 account to $1000+ in 45 days.

## Architecture

```
bot/manual/                     # Everything lives here
├── __init__.py                 # Package
├── config.py                   # ManualSniperConfig — all settings (env-var driven)
├── sniper_filter.py            # ManualSniperFilter — evaluates signals, classifies tiers
├── alerts.py                   # ManualSniperAlerter — Telegram formatting and sending
├── simulator.py                # SniperSimulator — paper-trades every signal on virtual $100
├── trade_journal.py            # TradeJournal — log real manual trades, track equity
├── performance.py              # PerformanceAnalyzer — compare actual vs signals
├── optimizer.py                # SniperOptimizer — continuous learning, parameter suggestions
├── edge_analysis.py            # Deep edge analysis, Kelly criterion, Monte Carlo
├── expanded_setups.py          # New setup definitions from research
├── backtest_sniper.py          # Historical backtest of sniper system
├── runner.py                   # Standalone runner (python -m manual.runner)
├── health_check.py             # System health diagnostic (python -m manual.health_check)
├── generate_playbook.py        # Generate trading playbook (python -m manual.generate_playbook)
├── generate_report.py          # Generate weekly report (python -m manual.generate_report)
├── RESTART_GUIDE.md            # How to restart the bot
└── CONTEXT.md                  # This file
```

## Data Files
```
bot/data/manual/
├── sniper_signals.jsonl        # Every sniper signal generated (append-only)
├── sim_trades.jsonl            # Simulated trade history
├── sim_status.json             # Simulator state (equity, WR, etc.)
├── trade_journal.jsonl         # Real manual trades logged by user
├── runner.log                  # Standalone runner log
├── backtest_results.json       # Historical backtest results
├── edge_analysis_raw.json      # Edge analysis data
├── TRADING_PLAYBOOK.md         # 370+ line actionable playbook
├── SYMBOL_RESEARCH.md          # Symbol expansion research
└── weekly_reports/             # Optimizer weekly reports
```

## Signal Flow
```
Bot ensemble evaluates signal
  → ManualSniperFilter.evaluate(signal)
    → Gate 1: confidence >= 78%
    → Gate 2: num_agree >= 2
    → Gate 3: R:R >= 1.2
    → Gate 4: regime not in weak list (unless conf >= 85)
    → Gate 5: dedup (same symbol+side+conf_band, 10min window)
    → Gate 6: cooldown per symbol (5min)
    → Classify tier: STANDARD / PREMIUM / SNIPER
    → In aggressive mode: skip STANDARD tier
    → Dynamic leverage based on stop width + confidence
    → Position sizing for $100 account
    → Send Telegram alert
    → Feed to simulator
```

## Tier System
| Tier | Criteria | Leverage | Risk | Action |
|------|----------|----------|------|--------|
| SNIPER | 85%+ conf & 3 agree, OR 90%+ & 2 agree | 20-25x (dynamic) | 10% ($10) | FIRE — max conviction |
| PREMIUM | 80%+ conf & 3 agree, OR 80%+ & 2 agree in preferred symbol+strong regime | 15-20x | 8% ($8) | Execute with conviction |
| STANDARD | 78%+ conf & 2 agree | 10x | 5% ($5) | Skipped in aggressive mode |

## Dynamic Leverage
Leverage adjusts based on stop width (tighter stop = higher leverage):
- Stop <= 1.0%: 1.25x boost (tight = precise entry)
- Stop 1.0-1.5%: 1.1x boost
- Stop 1.5-2.5%: neutral
- Stop 2.5-3.5%: 0.8x cut
- Stop > 3.5%: 0.6x cut
Always capped at 25x max.

## Proven Edges (from data)
| Setup | WR | PF | Grade | Notes |
|-------|----|----|-------|-------|
| HYPE BUY | 88% | 12.07 | A+ | Best edge. Regime-dependent (uptrend). |
| SOL SELL | 62% (75% at conf>=80) | 2.12 (3.41) | B/A+ | Upgrade to conf>=80 for full size |
| BTC SHORT | 67% at conf>=90 | 1.98 | B+ | NEVER below 90% conf |
| BTC LONG | 69% at conf 70-80 | 1.85 | B+ | Gets WORSE above 85% — hard cap |

## AVOID List (negative EV at all confidence levels)
- HYPE SELL — 0% WR in counterfactual, PF<1 everywhere
- BTC SHORT 70-80% conf — largest dollar loser (-$9K/90d)
- BTC LONG 85%+ conf — system buys tops
- SOL LONG 85%+ conf — consistently wrong

## The Math ($100 Account)
- SNIPER signal: 25x leverage, 10% risk ($10), 2.5% stop
- Win: +$15 (+15% account growth)
- Loss: -$10 (-10% drawdown)
- At 85% WR: EV = 0.85 × $15 - 0.15 × $10 = +$11.25/trade
- 1 trade/day → $100 → $1000 in ~45 days compound

## Telegram Commands
| Command | What it does |
|---------|-------------|
| `/sniper` | Today's sniper signal summary |
| `/sim` | Simulator status ($100 → $X) |
| `/trade HYPE BUY 40.50 25x 10` | Log manual trade entry |
| `/exit HYPE 42.00 TP` | Log trade exit |
| `/journal` | Recent trades + stats |
| `/equity` | Compounding progress to $1000 |
| `/perf` | Performance vs signals |
| `/optimize` | Parameter suggestions |

## Tests
```bash
cd bot && pytest tests/test_manual_sniper.py tests/test_trade_journal.py tests/test_sniper_simulator.py tests/test_sniper_optimizer.py tests/test_execution_helper.py tests/test_position_rules.py tests/test_pa_simulator.py tests/test_hardening_edge_cases.py -v
# 308 tests, all passing (252 original + 56 hardening edge cases)
```

## How to Restart the Bot
See RESTART_GUIDE.md. TL;DR:
1. Ctrl+C in the paper trading terminal
2. `cd bot && python run.py paper`
3. Sniper system activates automatically

## How to Run Standalone (without restarting bot)
```bash
cd bot && python -m manual.runner              # Continuous (90s interval)
cd bot && python -m manual.runner --once       # Single scan
cd bot && python -m manual.runner --status     # Sim status
cd bot && python -m manual.health_check        # Health check
cd bot && python -m manual.health_check --json # Health check as JSON
```

## Key Config (ManualSniperConfig in config.py)
All env-var driven with defaults. Key settings:
- `MANUAL_MODE=aggressive` — only PREMIUM+SNIPER tier signals
- `MANUAL_EQUITY=100` — starting account
- `MANUAL_MAX_LEVERAGE=25` — cap
- `MANUAL_MIN_CONFIDENCE=78` — floor
- `MANUAL_MAX_DAILY_SIGNALS=5` — quality over quantity
- `MANUAL_COMPOUND_SIZING=true` — grow position size as account grows

## Hardening (2026-03-24)
System hardening pass completed. See `data/manual/CODE_AUDIT.md` for full report.
- 8 bugs found and fixed (NaN handling, division by zero, atomic writes, etc.)
- 56 edge case tests added (308 total)
- Telegram retry with backoff added
- Simulator circuit breaker at 10% equity
- Health check module: `python -m manual.health_check`
- Go-live checklist: `data/manual/GO_LIVE_CHECKLIST.md`
- Alert format simplified for faster reading
- Runner optimized (strategy ensemble cached between scans)

## What Needs Improvement
1. ~~Monte Carlo strategy needs `"daily"` key mapping~~ (fixed in runner.py)
2. Rate limiting when running standalone alongside bot (use 90s+ interval)
3. Expanded setups (BTC SHORT >=90, BTC LONG 70-80) need paper validation before live
4. Regime gating on HYPE BUY (88% WR may be uptrend-dependent)
5. Time-of-day analysis shows potential edge in specific hours (needs more data)
