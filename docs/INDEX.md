# WAGMI Documentation Index

**Your complete roadmap to understanding and using the WAGMI autonomous trading bot.**

---

## Start Here

### For Everyone
- **[README](./README.md)** — Overview and quick links
- **[AI System Architecture](./AI-SYSTEM-ARCHITECTURE.md)** ⭐ — Complete explanation of 9-agent pipeline + 6-agent swarm
- **[System Overview](./system-overview.md)** — Philosophy and core concepts

### For Dashboard Users
- **[AI Pages Guide](./AI-PAGES-GUIDE.md)** — How to read the three AI dashboards:
  - `/ai-decisions` — Real-time decision transparency
  - `/agent-intelligence` — Agent performance and accuracy
  - `/llm-audit` — Cost tracking and model routing

---

## By Role

### 👨‍💼 Traders (Want to understand decisions)
1. Read: [AI Pages Guide](./AI-PAGES-GUIDE.md)
2. Check: [/ai-decisions](/ai-decisions) page daily
3. Monitor: [/agent-intelligence](/agent-intelligence) weekly
4. Use skill: `/paper-status` for health check

### 👨‍💻 Developers (Want to modify agents)
1. Read: [AI System Architecture](./AI-SYSTEM-ARCHITECTURE.md)
2. Read: `bot/llm/agents/coordinator.py` comments
3. Read: `bot/llm/agents/prompts.py` for agent prompts
4. Study: `bot/tests/test_multi_agent.py` for examples
5. Use skill: `/agent-debug [symbol]` to trace decisions

### 🔧 Operators (Want to deploy and monitor)
1. Read: [Quick Start](./quick-start.md)
2. Read: [Deployment Guide](./deployment.md) (if exists)
3. Run: `cd bot && python run.py paper`
4. Monitor: Web dashboard at http://localhost:3000
5. Use skill: `/health-check [quick|deep]`

### 📊 Analysts (Want to optimize performance)
1. Read: [AI Pages Guide](./AI-PAGES-GUIDE.md) — especially Agent Intelligence section
2. Check: [Agent Intelligence](/agent-intelligence) weekly
3. Analyze: Accuracy by regime on each agent
4. Use skill: `/growth-report` for learning summary
5. Use skill: `/edge-finder` to find profitable setups

---

## Documentation Map

### Core Architecture
- **[AI-SYSTEM-ARCHITECTURE.md](./AI-SYSTEM-ARCHITECTURE.md)** — 9-agent pipeline + 6-agent swarm
  - The Core 9-Agent Pipeline
  - The 6-Agent Optimization Swarm
  - Memory systems
  - Decision logging
  - Autonomy levels

- **[System Overview](./system-overview.md)** — Philosophy and design decisions
  - Why WAGMI is different
  - Core concepts
  - How it works

### User Guides
- **[Quick Start](./quick-start.md)** — Deploy in 5 minutes
- **[AI Pages Guide](./AI-PAGES-GUIDE.md)** — Dashboard walkthrough
  - AI Decisions page (/ai-decisions)
  - Agent Intelligence page (/agent-intelligence)
  - LLM Audit page (/llm-audit)

### Safety & Risk
- **[AUTONOMY.md](./AUTONOMY.md)** — LLM autonomy levels and safety invariants
- **[Execution-Safety Rules](./../.claude/rules/execution-safety.md)** — Risk gating and circuit breakers

### Specialized Topics
- **[Agents](./agents/)** — Per-agent documentation (if exists)
- **[Performance](./performance.md)** — Expected results and ROI
- **[Architecture](./architecture.md)** — Detailed system design (if exists)

---

## Quick Navigation by Topic

### Understanding AI Decisions
- Start: [AI Pages Guide - AI Decisions Section](./AI-PAGES-GUIDE.md#page-1-ai-decisions-the-decision-theater)
- Deep: [AI System Architecture - Pipeline Flow](./AI-SYSTEM-ARCHITECTURE.md#pipeline-flow)
- Code: `bot/llm/agents/coordinator.py`
- Debug: Use `/agent-debug [symbol]` skill

### Agent Performance
- Start: [AI Pages Guide - Agent Intelligence Section](./AI-PAGES-GUIDE.md#page-2-agent-intelligence-the-agent-brain-dashboard)
- Deep: [AI System Architecture - The 9 Core Agents](./AI-SYSTEM-ARCHITECTURE.md#the-9-core-agents-explained)
- Monitor: [/agent-intelligence](/agent-intelligence) page
- Optimize: Use `/prompt-calibrate [agent]` skill

### Cost Optimization
- Start: [AI Pages Guide - LLM Audit Section](./AI-PAGES-GUIDE.md#page-3-llm-audit-cost--model-routing)
- Deep: [AI System Architecture - LLM Usage Tiers](./AI-SYSTEM-ARCHITECTURE.md#llm-usage-tiers--model-routing)
- Monitor: [/llm-audit](/llm-audit) page
- Optimize: Use `/cost-audit [period]` skill

### Finding and Fixing Bugs
- See decision anomalies: Check [/ai-decisions](/ai-decisions) for patterns
- Check agent accuracy: [/agent-intelligence](/agent-intelligence) by regime
- Trace full pipeline: Use `/agent-debug` skill
- Deep dive: `bot/llm/agents/consistency_checker.py`

### Configuration & Customization
- Autonomy levels: [AUTONOMY.md](./AUTONOMY.md)
- Environment vars: [AI System Architecture - Configuration](./AI-SYSTEM-ARCHITECTURE.md#environment-configuration)
- LLM tiers: `bot/llm/usage_tiers.py`
- Agent prompts: `bot/llm/agents/prompts.py`

---

## Key Files Reference

### Core Agent System
```
bot/llm/agents/
├── coordinator.py              # Orchestrates 9-agent pipeline
├── prompts.py                  # Agent system prompts (all agents)
├── base.py                     # Agent types and configs
├── shared_context.py           # Shared reasoning framework
├── thought_protocol.py         # OBSERVE→REASON→DECIDE flow
├── consistency_checker.py      # Cross-agent coherence validation
├── swarm_master.py             # 6-agent offline optimizer
└── knowledge/                  # Agent knowledge bases
```

### Decision & Memory Systems
```
bot/llm/
├── decision_engine.py          # Monolithic LLM pipeline (fallback)
├── client.py                   # Anthropic API wrapper
├── usage_tiers.py              # Smart model routing
├── memory_store.py             # Short-term memory
├── deep_memory.py              # Long-term structured memory
└── growth/                     # Self-improvement systems
```

### Data Files
```
bot/data/llm/
├── decisions.jsonl             # All LLM decisions (append-only)
├── llm_memory.json             # Short-term memory
├── deep_memory/                # Long-term memory
├── brains/                     # Per-agent brain state
│   ├── regime_brain.json
│   ├── trade_brain.json
│   ├── risk_brain.json
│   ├── critic_brain.json
│   └── ... (9 total)
└── calibration/                # Calibration curves
```

### Web Dashboard
```
web/pages/
├── ai-decisions.tsx            # Decision Theater page
├── agent-intelligence.tsx      # Agent Brain Dashboard page
├── llm-audit.tsx               # Cost & Routing Audit page
└── ...
```

### API Backend
```
api/app/
├── routes_agents.py            # /v1/agents/* endpoints
├── routes_llm.py               # /v1/llm/* endpoints
├── routes_activity.py          # /v1/activity/* endpoints
└── ...
```

---

## Configuration Checklist

Before deploying to production:

- [ ] `.env` file configured with `ANTHROPIC_API_KEY`
- [ ] `LLM_MULTI_AGENT=true` enabled
- [ ] `LLM_MODE` set to desired autonomy level (0-5)
- [ ] `LLM_USAGE_TIER` set to CONSERVATIVE/RECOMMENDED/AGGRESSIVE
- [ ] `ENVIRONMENT=paper` for paper trading, `production` for live
- [ ] All agent environment variables optional (will use defaults)

See: [AI System Architecture - Environment Configuration](./AI-SYSTEM-ARCHITECTURE.md#environment-configuration)

---

## Support & Debugging

### Common Questions

**Q: Why was my trade vetoed?**
→ Check [/ai-decisions](/ai-decisions) page, expand the decision entry to see Critic's reasoning

**Q: Is my agent trustworthy?**
→ Check [/agent-intelligence](/agent-intelligence) page, look at accuracy by regime and calibration curves

**Q: Am I spending too much on LLM?**
→ Check [/llm-audit](/llm-audit) page, see cost per decision type

**Q: Which regime is the system worst at?**
→ [/agent-intelligence](/agent-intelligence), drill into Trade Agent, sort by accuracy by regime

### Debug Tools

- `/paper-status` — Real-time paper trading health
- `/agent-debug [symbol]` — Trace full pipeline for a symbol
- `/health-check [quick|deep]` — System health and anomalies
- `/growth-report` — Learning summary across all systems
- `/veto-review [period]` — Critic veto accuracy analysis

---

## Version History

- **v2.0** (2024) — Two-tier architecture (9-agent + 6-agent)
- **v1.0** (2023) — Initial multi-agent foundation

---

## FAQ

**Q: Do I need to read all the documentation?**
A: No! Start with [AI Pages Guide](./AI-PAGES-GUIDE.md) if you just want to use the dashboard. Go to [AI System Architecture](./AI-SYSTEM-ARCHITECTURE.md) if you want deep understanding.

**Q: How often should I check the dashboards?**
A: Daily for [/ai-decisions](/ai-decisions) (spot check), weekly for [/agent-intelligence](/agent-intelligence) (optimization), monthly for [/llm-audit](/llm-audit) (cost review).

**Q: Can I modify agent prompts?**
A: Yes, in `bot/llm/agents/prompts.py`. See rules in [.claude/rules/llm-agents.md](./../.claude/rules/llm-agents.md).

**Q: What's the expected learning curve?**
A: Agents start at ~55% accuracy and reach 70-80% after 1-2 weeks of trading. Accuracy improves with more diverse market conditions.

**Q: Can I run with just one agent?**
A: The system needs at least Regime → Trade → Critic for safety. You can disable optional agents (Exit, Scout) with env vars.

---

## Related Documentation

- [CLAUDE.md](../CLAUDE.md) — Project guide for Claude Code
- [ROADMAP.md](../ROADMAP.md) — Development roadmap and priorities
- [ARCHITECTURE_AND_OPERATIONS_GUIDE.md](../ARCHITECTURE_AND_OPERATIONS_GUIDE.md) — Detailed operations guide

