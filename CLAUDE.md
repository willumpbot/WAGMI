# CLAUDE.md — Project Guide for AI Assistants

## Project Overview
**nunuIRL Trading Bot** — Autonomous crypto trading bot for Hyperliquid with LLM-powered decision making (Claude API), multi-strategy ensemble, multi-agent specialist system, and Telegram/Discord monitoring.

## Architecture (key directories)
```
bot/                    # Main bot code (run from here: cd bot && python run.py paper)
  ├── run.py            # Entry point (starts the bot loop)
  ├── cli.py            # CLI: --mode paper|live|replay|evolve|tiers|optimize
  ├── core/             # Signal pipeline, portfolio analytics, structured logging
  ├── strategies/       # 4 trading strategies + ensemble voting (weighted_veto mode)
  ├── llm/              # Claude AI meta-brain (50+ files)
  │   ├── decision_engine.py  # Monolithic LLM pipeline (snapshot → prompt → parse)
  │   ├── agents/             # Multi-agent specialist system (5 agents)
  │   │   ├── coordinator.py  # Agent pipeline orchestration
  │   │   ├── prompts.py      # 5 specialist prompts (regime/trade/risk/critic/learning)
  │   │   ├── base.py         # Agent types, configs, defaults
  │   │   ├── shared_context.py    # Shared reasoning framework
  │   │   ├── thought_protocol.py  # Structured OBSERVE→RECALL→REASON→DECIDE→JUSTIFY
  │   │   └── consistency_checker.py  # Cross-agent coherence validation
  │   ├── client.py           # Raw Anthropic API call wrapper
  │   ├── usage_tiers.py      # Smart model routing (Opus/Sonnet/Haiku by trigger)
  │   ├── memory_store.py     # Short-term memory (100 notes, 7-day TTL)
  │   ├── deep_memory.py      # Long-term structured memory (trade DNA, patterns)
  │   ├── self_teaching.py    # Self-improvement curriculum (5 levels)
  │   ├── autonomy_router.py  # LLM autonomy levels (0-5)
  │   └── growth/             # Hypothesis tracking, recommendations, self-improvement
  ├── execution/        # Position manager, leverage, risk, reconciliation
  ├── feedback/         # Signal quality, evolution tracker, parameter tuner
  ├── data/             # Runtime data (trades.csv, decisions.jsonl, memory)
  └── tests/            # 20 test files, 664+ tests
.claude/                # Claude Code configuration
  ├── settings.json     # Hooks, context rules, preferences
  ├── rules/            # Domain-specific rules (auto-loaded by file pattern)
  │   ├── llm-agents.md       # Rules for agent development
  │   ├── strategies.md       # Rules for strategy changes
  │   ├── execution-safety.md # Rules for execution/risk code
  │   ├── testing.md          # Testing requirements
  │   └── data-pipeline.md    # Data pipeline rules
  └── prompts/          # Reusable prompt templates
      ├── add-agent.md        # Checklist for adding new agents
      ├── debug-agent.md      # Steps to debug agent decisions
      └── refactor-checklist.md  # Safe refactoring workflow
```

## Key Commands
```bash
cd bot && python run.py paper          # Paper trading (safe)
cd bot && python run.py backtest       # Run backtest
cd bot && python run.py signals        # One-shot signal check
cd bot && python cli.py --mode tiers   # Show LLM tier comparison
cd bot && python cli.py --mode evolve  # Strategy evolution report
cd bot && python cli.py --mode optimize  # Parameter optimization
cd bot && pytest tests/                # Run all tests
cd bot && pytest tests/ -k "agent"     # Agent-specific tests
```

## Environment Setup
- Copy `.env.example` → `.env`, fill in `ANTHROPIC_API_KEY` and Telegram/Discord creds
- Key env vars:
  - `LLM_USAGE_TIER` (CONSERVATIVE/RECOMMENDED/AGGRESSIVE/UNLEASHED)
  - `LLM_MODE` (0-5 autonomy: OFF/ADVISORY/VETO_ONLY/SIZING/DIRECTION/FULL)
  - `LLM_MULTI_AGENT` (true/false — enables specialist agent pipeline)
  - `ENVIRONMENT` (paper/production)

## Multi-Agent System
Enable with `LLM_MULTI_AGENT=true`. Pipeline: Regime → Trade → Risk → Critic → (Learning post-close)
- **Regime Agent** (Haiku): Classifies market regime from raw data
- **Trade Agent** (Sonnet): Decides go/skip/flip with full context
- **Risk Agent** (Haiku): Sizes positions, flags portfolio risks
- **Critic Agent** (Sonnet): Reviews decision, can approve or challenge/veto
- **Learning Agent** (Haiku): Extracts lessons from closed trades into deep memory

Per-agent model overrides: `AGENT_REGIME_MODEL`, `AGENT_TRADE_MODEL`, etc.

## Agent Consistency Framework
All agents share:
- **Shared vocabulary**: Identical regime names, action names, confidence scales
- **Thought protocol**: OBSERVE → RECALL → REASON → DECIDE → JUSTIFY
- **Shared memory bus**: Upstream agents write to scratchpad, downstream agents read it
- **Cross-agent calibration**: Each agent's accuracy tracked independently
- See `bot/llm/agents/shared_context.py` and `bot/llm/agents/thought_protocol.py`

## LLM Usage Tier System
Smart model routing based on trigger importance:
- **High-value** (PRE_TRADE, REGIME_SHIFT): Opus ($15/1M tokens)
- **Medium** (POSITION_CLOSED, HIGH_CONFIDENCE): Sonnet ($3/1M tokens)
- **Low** (PERIODIC, MEMORY_EVENT): Haiku ($1/1M tokens)
- Set via `LLM_USAGE_TIER=RECOMMENDED` in `.env`

## Development Notes
- Python 3.10+, dependencies in `requirements.txt`
- CCXT for exchange connectivity (Hyperliquid primary)
- All trade decisions logged to `bot/data/llm/decisions.jsonl`
- LLM memory: short-term in `bot/data/llm/llm_memory.json`, deep in `bot/data/llm/deep_memory/`
- Ensemble: weighted veto mode with chop detection and multi-TF trend scoring
- Circuit breakers: consecutive loss limits, daily drawdown caps
- **Always use Context7 when needing library/API docs or code examples**
- See `ROADMAP.md` for full development roadmap and priority order

## Claude Code Rules
Domain-specific rules in `.claude/rules/` auto-load when editing matching files:
- Editing `bot/llm/**` → loads `llm-agents.md` (agent dev rules)
- Editing `bot/strategies/**` → loads `strategies.md` (signal contract)
- Editing `bot/execution/**` → loads `execution-safety.md` (safety rules)
- Editing `bot/tests/**` → loads `testing.md` (test requirements)
- Editing `bot/data/**` → loads `data-pipeline.md` (data pipeline rules)

## Branch Strategy
- `main` — stable
- `claude/*` — active development branches
