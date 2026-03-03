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
  ├── prompts/          # Reusable prompt templates
  │   ├── add-agent.md        # Checklist for adding new agents
  │   ├── debug-agent.md      # Steps to debug agent decisions
  │   └── refactor-checklist.md  # Safe refactoring workflow
  └── skills/           # Custom slash command skills (invoke with /skill-name)
      ├── backtest.md         # /backtest — Smart backtesting with comparison
      ├── agent-debug.md      # /agent-debug — Trace and debug agent decisions
      ├── add-agent.md        # /add-agent — Full agent creation workflow
      ├── refactor.md         # /refactor — Safe refactoring checklist
      ├── optimize.md         # /optimize — Quick parameter optimization
      ├── signal-check.md     # /signal-check — Live signal analysis
      ├── trade-postmortem.md # /trade-postmortem — Closed trade analysis
      ├── deploy-paper.md     # /deploy-paper — Safe paper trading deployment
      ├── health-check.md     # /health-check — Bot health and anomaly audit
      ├── evolution.md        # /evolution — Strategy evolution summary
      ├── cost-audit.md       # /cost-audit — LLM cost tracking and optimization
      ├── safety-audit.md     # /safety-audit — Review all safety systems
      ├── stress-test.md      # /stress-test — Scenario and stress testing
      ├── prompt-calibrate.md  # /prompt-calibrate — Benchmark and tune agent prompts
      ├── agent-consistency.md # /agent-consistency — Cross-agent consistency audit
      ├── memory-optimize.md   # /memory-optimize — Prune and audit memory stores
      ├── confidence-calibrate.md # /confidence-calibrate — Fix calibration drift
      ├── knowledge-distill.md # /knowledge-distill — Graduate hypotheses into rules
      ├── veto-review.md       # /veto-review — Analyze veto decisions and accuracy
      ├── agent-replay.md      # /agent-replay — Replay data through agent pipeline
      ├── growth-report.md     # /growth-report — Learning intelligence report
      ├── curriculum-advance.md # /curriculum-advance — Self-teaching level advancement
      └── model-route-tune.md  # /model-route-tune — Optimize model routing
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

## Custom Skills (Slash Commands)
Invoke these with `/skill-name` in Claude Code sessions:

**Daily Operations:**
- `/signal-check [symbols]` — One-shot signal analysis with per-strategy breakdown
- `/health-check [quick|deep]` — Bot health, positions, error scan, anomaly detection
- `/evolution [24h|7d|30d]` — Strategy evolution: what's working, what's degrading
- `/trade-postmortem [last|last N|today|week]` — Deep analysis of closed trades

**Development Workflows:**
- `/backtest [symbols days compare]` — Smart backtesting with auto-comparison
- `/optimize [quick|deep] [symbols]` — Parameter optimization with sensitivity analysis
- `/stress-test [flash-crash|vol-spike|chop|gap|all]` — Extreme scenario testing
- `/deploy-paper [symbols]` — Full pre-flight validation before paper trading

**Code Quality:**
- `/refactor [target]` — Safe refactoring with contract preservation
- `/safety-audit [quick|deep]` — Verify all safety gates, circuit breakers, risk limits
- `/cost-audit [today|7d|30d]` — LLM spending analysis and optimization

**Agent Development:**
- `/add-agent [name and purpose]` — Guided workflow for new specialist agents
- `/agent-debug [symbol|trade-id|last]` — Trace full agent decision pipeline

**LLM Agent Efficiency & Consistency:**
- `/prompt-calibrate [agent|all]` — Benchmark agent prompts against outcomes, tune for accuracy
- `/agent-consistency [quick|deep]` — Audit cross-agent vocabulary, reasoning, contradictions
- `/confidence-calibrate [agent|system]` — Fix calibration drift, build calibration curves
- `/memory-optimize [short-term|deep|prune]` — Audit memory stores, prune noise, optimize tokens
- `/knowledge-distill [hypotheses|rules|gaps]` — Graduate validated hypotheses into codified rules
- `/veto-review [today|7d|30d]` — Analyze Critic veto accuracy, PnL saved/missed
- `/agent-replay [last N|7d|compare]` — Replay historical data through pipeline, A/B test prompts
- `/growth-report [summary|deep]` — Unified learning intelligence across all growth systems
- `/curriculum-advance [status|evaluate|advance]` — Self-teaching curriculum progress and level-up
- `/model-route-tune [cost|accuracy|balanced]` — Optimize Haiku/Sonnet/Opus routing per agent/trigger

**Profitability (the skills that matter most):**
- `/pnl-maximize [quick|deep|execute]` — Master skill: end-to-end profitability optimization
- `/edge-finder [by-regime|by-strategy|by-symbol|full]` — Discover where the bot makes and loses money
- `/loss-autopsy [worst|patterns|preventable]` — Forensic analysis of losses, find profit killers
- `/sniper-setup [top10|template]` — Reverse-engineer best trades, build reusable sniper profile
- `/strategy-discover [scan|propose|test]` — Activate strategy discovery, find new alpha sources
- `/bug-triage [critical|all]` — Fix money-losing bugs ranked by PnL impact
- `/config-audit [hardcoded|current|recommend]` — Find and tune every parameter that affects PnL

**System Understanding:**
- `/system-map [layer|connections|full]` — Full inventory of what's built, working, stubbed, planned
- `/roadmap-status [status|next]` — ROADMAP progress, profitability-ranked next steps
- `/telegram-signals [setup|test|analyze|debug]` — Telegram signal ingestion pipeline
- `/alert-config [setup|test|status|tune]` — Discord/Telegram alert configuration
- `/web-dashboard [dashboard|api|health|monitoring]` — Web systems health check

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
