# CLAUDE.md — Project Guide for AI Assistants

## Project Overview
**nunuIRL Trading Bot** — Autonomous crypto trading bot for Hyperliquid with LLM-powered decision making (Claude API), multi-strategy ensemble, and Telegram monitoring.

## Architecture (key directories)
```
bot/                    # Main bot code (run from here: cd bot && python run.py paper)
  ├── run.py            # Entry point (starts the bot loop)
  ├── cli.py            # CLI: --mode paper|live|replay|evolve|tiers
  ├── core/             # Trading engine, position manager, risk management
  ├── strategies/       # Individual trading strategies (momentum, mean-rev, breakout, etc.)
  ├── ensemble/         # Multi-strategy voting (weighted_veto mode)
  ├── llm/              # Claude AI meta-brain
  │   ├── decision_engine.py  # Main LLM call pipeline (snapshot → prompt → parse)
  │   ├── caller.py           # Raw Anthropic API call wrapper
  │   ├── usage_tiers.py      # Smart model routing (Opus/Sonnet/Haiku by trigger type)
  │   ├── memory_store.py     # LLM memory persistence
  │   ├── self_teacher.py     # Self-improvement loop
  │   └── autonomy_router.py  # LLM autonomy levels (0-5)
  ├── feedback/         # Performance tracking
  │   ├── signal_quality.py   # Signal scoring
  │   └── evolution_tracker.py # Strategy evolution reports
  ├── data/             # Runtime data (trades.csv, decisions.jsonl, memory)
  └── tests/            # Pytest tests
```

## Key Commands
```bash
cd bot && python run.py paper     # Paper trading (safe)
cd bot && python cli.py --mode tiers   # Show LLM tier comparison
cd bot && python cli.py --mode evolve  # Strategy evolution report
cd bot && pytest tests/                # Run tests
```

## Environment Setup
- Copy `.env.example` → `.env`, fill in `ANTHROPIC_API_KEY` and Telegram creds
- Key env vars: `LLM_USAGE_TIER` (CONSERVATIVE/RECOMMENDED/AGGRESSIVE/UNLEASHED), `LLM_MODE` (0-5 autonomy), `ENVIRONMENT` (paper/production)

## LLM Usage Tier System
The bot uses smart model routing based on trigger importance:
- **High-value triggers** (PRE_TRADE, REGIME_SHIFT): can use Opus for maximum intelligence
- **Medium triggers** (POSITION_CLOSED, HIGH_CONFIDENCE): Sonnet
- **Low triggers** (PERIODIC, MEMORY_EVENT): Haiku or Sonnet
- Set via `LLM_USAGE_TIER=RECOMMENDED` in `.env`

## Development Notes
- Python 3.10+, dependencies in `requirements.txt`
- Bot uses CCXT for exchange connectivity (Hyperliquid primary)
- All trade decisions are logged to `bot/data/decisions.jsonl`
- LLM memory persists in `bot/data/llm_memory.json`
- The ensemble system uses weighted voting with veto capability
- Circuit breakers protect against consecutive losses and daily drawdown limits

## Branch Strategy
- `main` — stable
- `claude/auto-trading-signal-bots-*` — active development branches
