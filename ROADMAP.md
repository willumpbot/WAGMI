# nunuIRL Trading Bot — Complete Roadmap

> **Last updated**: 2026-03-03
> **Current state**: Multi-agent LLM architecture built, risk gates wired, feedback loops closed.
> **What's next**: Agent consistency hardening, production resilience, alpha generation.

---

## Table of Contents
1. [System Inventory — What We Have](#1-system-inventory)
2. [What's Done (Phases 1-2 Complete)](#2-whats-done)
3. [Phase 3: Agent Consistency & Thought Process Alignment](#3-phase-3)
4. [Phase 4: Configuration Extraction & Tunability](#4-phase-4)
5. [Phase 5: Production Hardening](#5-phase-5)
6. [Phase 6: Alpha Generation & Backtesting](#6-phase-6)
7. [Phase 7: Advanced Multi-Agent Evolution](#7-phase-7)
8. [Critical Bugs Still Open](#8-critical-bugs)
9. [Claude Code Plugin Stack Integration](#9-plugin-stack)
10. [File Reference Map](#10-file-reference)

---

## 1. System Inventory — What We Have <a id="1-system-inventory"></a>

### Core Pipeline (Working)
| Layer | Files | Status |
|---|---|---|
| **4 Trading Strategies** | `bot/strategies/{regime_trend,monte_carlo_zones,confidence_scorer,multi_tier_quality}.py` | Working — produce signals |
| **Ensemble Voting** | `bot/strategies/ensemble.py` (27KB) | Working — weighted veto with chop detection |
| **LLM Meta-Brain** | `bot/llm/` (50+ files, 595KB) | Working — 6 autonomy levels, smart model routing |
| **Multi-Agent System** | `bot/llm/agents/{base,coordinator,prompts,learning_integration}.py` | Built — 5 specialist agents |
| **Position Management** | `bot/execution/position_manager.py` (27KB) | Working — state machine, trailing stops, trade profiles |
| **Risk Management** | `bot/execution/risk.py` + `adaptive_risk.py` + `ops_guard.py` | Working — circuit breakers, leverage tiers |
| **Data Pipeline** | `bot/data/fetcher.py` (25KB) + `bot/data/fetchers/` | Working — CCXT multi-exchange |
| **Feedback Loop** | `bot/feedback/{signal_quality,evolution_tracker,loop,continuous_backtest,parameter_tuner}.py` | Working — signal scoring, evolution reports |
| **Memory System** | `bot/llm/{memory_store,deep_memory}.py` | Working — short-term (50 notes) + deep memory |
| **Self-Teaching** | `bot/llm/self_teaching.py` (45KB) | Working — curriculum, knowledge base |
| **Growth System** | `bot/llm/growth/{orchestrator,hypothesis_tracker,recommendation_engine,self_improvement}.py` | Working — hypotheses, recommendations |
| **Strategy Discovery** | `bot/llm/strategy_discovery/{corpus,proposals,research_agent,sandbox}.py` | Built — auto-discovery framework |
| **Analytics** | `bot/analytics/` + `bot/llm/{metrics,uplift_analytics,self_performance}.py` | Working — attribution, A/B, counterfactual, meta-learning |
| **Alerts** | `bot/alerts/` | Working — Telegram + Discord with rate limiting |
| **Dashboard** | `web/` | Working — full web UI with charts |
| **Database** | `bot/data/db.py` (24KB) + `migrations.py` | Working — SQLite with migrations |
| **Tests** | `bot/tests/` (20 test files) | 664+ tests passing |
| **Configuration** | `bot/trading_config.py` (484 lines) | Dataclass-based, per-symbol overrides |

### Multi-Agent Architecture (Built, Needs Tuning)
| Agent | Role | Default Model | When Called |
|---|---|---|---|
| **Regime Analyst** | Classify market regime from raw data | Haiku | Every decision cycle |
| **Trade Evaluator** | Given regime + signal, decide go/skip/flip with reasoning | Sonnet | Pre-trade |
| **Risk Manager** | Position sizing, strategy weights, risk flags | Haiku | Pre-trade |
| **Critic** | Review trade decision, approve or challenge | Sonnet | Pre-trade |
| **Learning Agent** | Extract lessons from closed trades | Haiku | Post-close |

**Enable**: `LLM_MULTI_AGENT=true` in `.env`

---

## 2. What's Done (Phases 1-2 Complete) <a id="2-whats-done"></a>

### Phase 1: Stop Losing Money ✅
- [x] Fixed leverage math (liquidation formula, position sizing) — `bot/execution/leverage.py`
- [x] Added R:R sanity bounds to Signal class — `bot/strategies/base.py`
- [x] Fixed daily loss calculation (current equity, not peak) — `bot/execution/risk.py`
- [x] Added graceful strategy degradation (dynamic MIN_VOTES) — `bot/execution/graceful_degradation.py`
- [x] Weighted timeframes in trend scoring (5m=0.5, 1h=1.0, 6h=1.5, D=2.0) — `bot/trading_config.py`
- [x] Portfolio cap, spread-aware sizing, funding cost tracking
- [x] Ops guard, price guard, liquidity guard

### Phase 2: Multi-Agent LLM Architecture ✅
- [x] Agent base types (AgentRole, AgentOutput, AgentConfig) — `bot/llm/agents/base.py`
- [x] Agent coordinator (sequencing, context passing, failure handling) — `bot/llm/agents/coordinator.py`
- [x] 5 specialist prompts (regime, trade, risk, learning, critic) — `bot/llm/agents/prompts.py`
- [x] Learning integration (deep memory, hypotheses, knowledge base) — `bot/llm/agents/learning_integration.py`
- [x] Risk gates wired into live execution path
- [x] Feedback loops closed (signal quality → strategy weights → ensemble)

---

## 3. Phase 3: Agent Consistency & Thought Process Alignment <a id="3-phase-3"></a>

> **Goal**: Make all 5 agents think consistently, share a unified mental model, and reinforce each other's learning.

### 3.1 Shared Reasoning Framework
- [ ] **Create `bot/llm/agents/shared_context.py`** — Unified context builder
  - Shared market axioms all agents reference (e.g., "never long alts into BTC nuke")
  - Shared vocabulary/definitions (what "trend" means numerically, not vibes)
  - Shared regime-action mapping (if regime=X, then acceptable actions are Y)
  - Version the framework so agents evolve together

- [ ] **Create `bot/llm/agents/thought_protocol.py`** — Structured reasoning template
  - Force all agents to follow: OBSERVE → RECALL → REASON → DECIDE → JUSTIFY
  - Each step has explicit requirements (OBSERVE must cite data, RECALL must reference memory)
  - This eliminates agents "winging it" with different reasoning styles
  - Inject as a prefix to every agent prompt

- [ ] **Create `bot/llm/agents/consistency_checker.py`** — Cross-agent coherence validation
  - After all agents run, check for contradictions (e.g., Regime says "panic" but Trade says "go")
  - Score consistency 0-1, log disagreements
  - If consistency < 0.5, re-run the Trade Agent with explicit conflict resolution prompt
  - Track consistency over time to detect drift

### 3.2 Shared Memory Protocol
- [ ] **Create `bot/llm/agents/shared_memory.py`** — Agent-to-agent memory bus
  - Each agent writes to a shared scratchpad during the pipeline
  - Downstream agents read upstream scratchpad entries
  - Persistent cross-session memory: lessons that apply to ALL agents
  - Replace the current "inject everything" approach with structured memory routing

- [ ] **Upgrade memory TTL** — Replace 50-note/48h limit
  - Tier memory by importance: critical (no TTL), important (7 days), normal (48h), ephemeral (4h)
  - Allow agents to promote/demote memories based on validation
  - Learning Agent's "strong" lessons → critical tier automatically

### 3.3 Agent Calibration Loop
- [ ] **Create `bot/llm/agents/calibration.py`** — Per-agent performance tracking
  - Track each agent's accuracy independently (Regime accuracy, Trade win rate, Critic veto value)
  - Use calibration data to adjust agent confidence weights in the merger
  - If Critic is consistently wrong, reduce its override power
  - If Regime Agent nails panic detection, trust it more in panic regimes
  - Feed calibration stats INTO each agent's prompt (they already see `self_perf`)

- [ ] **Implement inter-agent feedback**
  - After trade closes: score which agent was RIGHT and which was WRONG
  - "Regime said trend, Trade said go, Critic approved → WIN" → all agents reinforced
  - "Regime said range, Trade said go, Critic challenged → LOSS" → Trade penalized, Critic validated
  - Store as structured feedback in deep memory

### 3.4 Prompt Versioning & A/B Testing
- [ ] **Create `bot/llm/agents/prompt_registry.py`** — Versioned prompt management
  - Store prompt versions with timestamps and performance metrics
  - A/B test prompt variations (e.g., more aggressive Trade Agent vs conservative)
  - Track which prompt version produces better outcomes
  - Rollback to previous version if new one underperforms

---

## 4. Phase 4: Configuration Extraction & Tunability <a id="4-phase-4"></a>

> **Goal**: Make every hardcoded value configurable, per-symbol, per-environment.

### 4.1 Config Audit
- [ ] Audit all hardcoded values across codebase (30+ identified)
  - ATR multipliers in strategies
  - Confidence floors and ceilings
  - Monte Carlo simulation parameters
  - Leverage tier thresholds
  - Stop width minimums
  - Memory TTL values
  - Agent timeout values
  - Rate limits

### 4.2 Config Infrastructure
- [ ] Extend `bot/trading_config.py` with missing parameters
- [ ] Add per-symbol config overrides for ALL parameters (not just risk tiers)
- [ ] Add paper-vs-live config profiles with different defaults
- [ ] Environment variable overrides for every parameter
- [ ] Config validation on startup (catch invalid combinations)
- [ ] Hot-reload config without restart (file watcher or signal handler)

### 4.3 Agent-Specific Config
- [ ] Per-agent model overrides (already supported via env vars)
- [ ] Per-agent prompt temperature settings
- [ ] Per-agent timeout and retry policies
- [ ] Agent enable/disable per symbol or regime
- [ ] Agent priority weights (how much the merger trusts each agent)

---

## 5. Phase 5: Production Hardening <a id="5-phase-5"></a>

> **Goal**: Make the bot reliable enough for real money at scale.

### 5.1 Code Architecture
- [ ] **Break up `multi_strategy_main.py`** (4,585 lines → modules)
  - Extract tick processing → `bot/core/tick_processor.py`
  - Extract LLM integration → `bot/core/llm_integration.py`
  - Extract position management wiring → `bot/core/position_wiring.py`
  - Extract alert dispatching → `bot/core/alert_dispatcher.py`
  - Extract analytics collection → `bot/core/analytics_collector.py`
  - Main file becomes a thin orchestrator (~200 lines)

### 5.2 Exchange Connection Resilience
- [ ] **Add exponential backoff to `bot/data/fetcher.py`**
  - Retry with 1s, 2s, 4s, 8s, 16s backoff
  - Circuit breaker: if 5 consecutive failures, pause data fetching for 60s
  - Stale data detection: if last candle is >5min old, flag it
  - Fallback data sources (if Hyperliquid API down, try Kraken/Bybit for reference)

- [ ] **Add connection health monitoring**
  - Track API response times, error rates, data freshness
  - Alert on degraded connectivity (Telegram/Discord)
  - Auto-close new trades if data is stale (safety net)

### 5.3 Position Reconciliation
- [ ] **Complete `bot/execution/reconciliation.py`**
  - On startup: read actual positions from exchange API
  - Compare with in-memory state
  - Reconcile differences (orphan positions, missing state)
  - Alert on mismatches
  - Periodic reconciliation (every 5 minutes)

### 5.4 Logging & Monitoring
- [ ] **Structured JSON logging** — `bot/core/structured_logging.py` exists, wire it everywhere
  - Every log line: JSON with timestamp, level, module, structured fields
  - Separate log streams: trades, decisions, errors, performance
  - Log rotation and archival

- [ ] **Health check endpoint**
  - `/healthz` endpoint on dashboard server
  - Reports: uptime, last trade time, data freshness, API status, memory usage
  - Container orchestration compatible (Docker, k8s)

### 5.5 Integration Tests
- [ ] **Full pipeline integration test**
  - Mock exchange data → strategies → ensemble → LLM agents → execution → feedback
  - Test the complete signal→trade→close→learn cycle
  - Test error paths (API failure, parse failure, circuit breaker trigger)
  - Test multi-agent pipeline with mock LLM responses
  - Golden path replay tests (replay known good/bad scenarios)

---

## 6. Phase 6: Alpha Generation & Backtesting <a id="6-phase-6"></a>

> **Goal**: Find and validate new edges systematically.

### 6.1 Backtesting Framework
- [ ] **Create `bot/backtest/full_pipeline_replay.py`**
  - Replay historical data through the COMPLETE pipeline (not just strategies)
  - Include LLM agent decisions (cached or mocked)
  - Include ensemble voting, risk gating, position sizing
  - Compare: strategies-only vs strategies+LLM vs multi-agent
  - Output: equity curve, drawdown, Sharpe, win rate, trade list

### 6.2 Strategy Parameter Optimization
- [ ] **Extend `bot/optimization/`**
  - Grid search over strategy parameters (ATR multipliers, confidence thresholds)
  - Bayesian optimization for high-dimensional parameter spaces
  - Walk-forward optimization (train on period 1, test on period 2)
  - Out-of-sample validation to prevent overfitting
  - Integration with the feedback loop (auto-update trading_config.py)

### 6.3 New Strategy Development
- [ ] **Order flow analysis** — Hyperliquid provides order book depth
  - Detect large limit orders (support/resistance levels)
  - Detect aggressive market orders (momentum signals)
  - Detect order book imbalance (directional bias)

- [ ] **Funding rate arbitrage**
  - When funding is extreme (>0.05%), counter-trade with tight stops
  - Funding reversals are predictable and high-WR
  - Already have funding data in pipeline, just need strategy logic

- [ ] **Cross-exchange signals**
  - Use Kraken/Bybit data as leading indicators for Hyperliquid
  - Price dislocations between exchanges → arbitrage signals
  - Volume spikes on one exchange → momentum on another

### 6.4 Strategy Discovery Agent
- [ ] **Activate `bot/llm/strategy_discovery/`**
  - `research_agent.py` — LLM proposes new strategy ideas from market data
  - `sandbox.py` — Safe backtesting environment for proposed strategies
  - `proposals.py` — Track and evaluate strategy proposals
  - Wire into the growth orchestrator for automated discovery

---

## 7. Phase 7: Advanced Multi-Agent Evolution <a id="7-phase-7"></a>

> **Goal**: Make the agents self-improving and adaptive.

### 7.1 Portfolio Strategist Agent (New)
- [ ] **Add 6th agent: Portfolio Strategist**
  - Runs every 15 minutes (not per-trade)
  - Cross-asset correlation analysis
  - Portfolio-level position sizing recommendations
  - Rebalancing suggestions
  - Uses `bot/core/portfolio_analytics.py` data

### 7.2 Agent Self-Improvement Loop
- [ ] **Automated prompt evolution**
  - Track agent performance per prompt version
  - Learning Agent proposes prompt modifications based on failure patterns
  - A/B test modifications automatically
  - Promote winning prompts, retire losers
  - Guardrail: never modify prompts that touch safety rules

### 7.3 Deep RL Integration
- [ ] **Upgrade `bot/ml/` RL policy**
  - Replace simple Q-table with deep Q-network (DQN)
  - Use agent decision history as training data
  - RL policy as a "7th voter" alongside 5 agents + ensemble
  - Transition buffer in `bot/data/` already records state-action-reward tuples

### 7.4 Multi-Bot Coordination
- [ ] **If running multiple bot instances**
  - Shared memory across instances (Redis or shared SQLite)
  - Cross-instance position awareness (don't double up)
  - Ensemble of ensembles: each instance votes on portfolio-level decisions

---

## 8. Critical Bugs Still Open <a id="8-critical-bugs"></a>

### Must Fix Before Live Trading
| Bug | Location | Impact | Fix |
|---|---|---|---|
| Ensemble modifies signals in-place | `ensemble.py:326-366` | Downstream logging sees flipped signal, not original | Deep-copy signal before mutation |
| No exchange connection resilience | `data/fetcher.py` | Bot crashes on API outage | Add exponential backoff + circuit breaker |
| Strategy data requirements incompatible | Multiple strategies | Silent no-signal when data is missing | Validate data availability before strategy eval |
| Telegram can't parse decimals | `telegram_ingest.py:122` | Misses "97,500.50" format | Fix regex to handle comma+decimal |
| Strategy weights recompute from ALL history equally | `data/strategy_weights.py` | Ancient trades have same weight as recent | Exponential decay weighting |
| No position reconciliation on startup | `execution/reconciliation.py` | Lost positions after restart | Read exchange positions on boot |

### Should Fix for Reliability
| Bug | Location | Impact | Fix |
|---|---|---|---|
| LLM memory 50-note/48h limit | `memory_store.py` | Hard-won lessons forgotten | Tiered memory with variable TTL |
| Self-teaching expensive/infrequent | `self_teaching.py` | Learning is periodic, not continuous | Learning Agent already solves this |
| `multi_strategy_main.py` is 4,585 lines | `multi_strategy_main.py` | God object, hard to maintain | Break into modules (Phase 5) |
| No structured logging | Various | Logs are text, hard to parse | Wire `structured_logging.py` everywhere |

---

## 9. Claude Code Plugin Stack Integration <a id="9-plugin-stack"></a>

### What We're Setting Up
Claude Code plugins extend the AI coding agent with tools, hooks, and specialized capabilities.

### Plugin Stack (Recommended for This Project)
| Plugin | What It Does | Priority |
|---|---|---|
| **Superpowers** (obra/superpowers) | Planning mode, TDD, systematic debugging, verification gates | HIGH — forces structured thinking |
| **Context7** (Upstash) | Live, version-specific docs for libraries (ccxt, anthropic, pandas, etc.) | HIGH — accurate API usage |
| **Security Guidance** | Auto-scan every edit for XSS, injection, secret leaks | HIGH — protecting API keys, exchange creds |
| **LSP (TypeScript/Python)** | Real symbol navigation, go-to-definition for dashboard/web code | MEDIUM — useful for web/ directory |
| **Playwright** | Browser automation for dashboard testing | LOW — nice to have for E2E |
| **Frontend Design** | Design systems thinking for dashboard UI | LOW — only if redesigning dashboard |

### How This Maps to Our Bot
- **Superpowers planning mode** → Use for multi-step refactors (breaking up main.py, adding new agents)
- **Context7 docs** → Pull latest ccxt, anthropic, pandas docs when coding exchange integration or LLM calls
- **Security hooks** → Catch leaked API keys in `.env`, unsafe eval/exec patterns, SQL injection in db.py
- **LSP** → Navigate 55K lines efficiently, find all references to a function across 197 files

### Implementation in `.claude/`
We set up the configuration structure in `.claude/` with:
- `settings.json` — Claude Code settings (hooks, tools, MCP servers)
- `rules/` — Domain-specific rules that activate on relevant tasks
- `prompts/` — Reusable prompt templates for common operations

---

## 10. File Reference Map <a id="10-file-reference"></a>

### Entry Points
```
bot/run.py          → Quick launcher (paper, backtest, signals, status, positions)
bot/cli.py          → Full CLI (paper, replay, live, evolve, tiers, optimize)
bot/bot.py          → Bot class
bot/multi_strategy_main.py → Multi-strategy main loop (4,585 lines — needs breakup)
```

### LLM Pipeline
```
bot/llm/decision_engine.py     → Monolithic LLM decision pipeline
bot/llm/agents/coordinator.py  → Multi-agent pipeline (replaces monolithic)
bot/llm/agents/prompts.py      → 5 specialist prompts
bot/llm/agents/base.py         → Agent types, configs, defaults
bot/llm/agents/learning_integration.py → Wires agent output to learning systems
bot/llm/system_prompt.py       → Monolithic system prompt (for non-multi-agent)
bot/llm/usage_tiers.py         → Model routing (Haiku/Sonnet/Opus)
bot/llm/client.py              → Raw Anthropic API wrapper
bot/llm/autonomy.py            → Autonomy levels 0-5
bot/llm/autonomy_router.py     → Mode constraints
```

### Memory & Learning
```
bot/llm/memory_store.py        → Short-term memory (50 notes, 48h TTL)
bot/llm/deep_memory.py         → Long-term structured memory
bot/llm/self_teaching.py       → Self-improvement curriculum
bot/llm/knowledge_seed.py      → Pre-trained knowledge
bot/llm/knowledge_roadmap.py   → Learning progression
bot/llm/post_trade_learner.py  → Deterministic post-trade lessons
```

### Strategies & Ensemble
```
bot/strategies/base.py             → Signal dataclass, BaseStrategy abstract class
bot/strategies/ensemble.py         → Weighted veto ensemble voting (27KB)
bot/strategies/regime_trend.py     → Regime-based trend following
bot/strategies/monte_carlo_zones.py → Monte Carlo support/resistance
bot/strategies/confidence_scorer.py → Multi-factor confidence scoring
bot/strategies/multi_tier_quality.py → Multi-timeframe signal quality
bot/strategies/chop_detector.py    → Market chop detection
bot/strategies/regime_detector.py  → Regime classification
```

### Execution
```
bot/execution/position_manager.py  → Position lifecycle (27KB)
bot/execution/leverage.py          → Leverage tiers and sizing
bot/execution/risk.py              → Circuit breakers, daily loss limits
bot/execution/adaptive_risk.py     → Dynamic risk adjustment
bot/execution/reconciliation.py    → Position reconciliation (needs completion)
bot/execution/ops_guard.py         → Operational safety checks
bot/execution/pnl_engine.py        → PnL calculation
bot/execution/tp_sl_engine.py      → Take-profit/stop-loss engine
```

### Configuration
```
bot/trading_config.py   → Centralized config (484 lines, dataclass-based)
bot/.env.example        → Environment variable template
.env.example            → Root-level env template
```

### Data & Feedback
```
bot/data/db.py                     → SQLite persistence (24KB)
bot/data/fetcher.py                → Multi-exchange OHLCV (25KB)
bot/feedback/signal_quality.py     → Signal quality scoring (18KB)
bot/feedback/evolution_tracker.py  → Strategy evolution reports (38KB)
bot/feedback/continuous_backtest.py → Continuous backtesting (20KB)
bot/feedback/parameter_tuner.py    → Parameter optimization (14KB)
```

---

## Priority Order (What to Work On Next)

1. **Phase 3.1-3.2**: Agent consistency framework (shared context, thought protocol, shared memory)
2. **Critical bugs**: Signal mutation, exchange resilience, data compatibility
3. **Phase 3.3**: Agent calibration loop
4. **Phase 4**: Configuration extraction
5. **Phase 5**: Production hardening (break up main.py, integration tests)
6. **Phase 6**: Backtesting + new strategies
7. **Phase 7**: Advanced evolution (portfolio agent, prompt evolution, deep RL)

---

*This document is the single source of truth for the nunuIRL roadmap. Update it as phases are completed.*
