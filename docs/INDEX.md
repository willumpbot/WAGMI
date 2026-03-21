# WAGMI Documentation Index

**Your complete roadmap to understanding and using the WAGMI autonomous trading bot.**

---

## Start Here

### ⭐ Start Here (Pick One)
- **[AI System Architecture](./AI-SYSTEM-ARCHITECTURE.md)** — Complete technical guide (9-agent + 6-agent)
- **[AI Pages Guide](./AI-PAGES-GUIDE.md)** — How to use the three dashboards
- **[System Overview](./system-overview.md)** — Philosophy and concepts

### Supporting Documentation
- **[README](./README.md)** — Overview and quick links
- **[AUTONOMY.md](./AUTONOMY.md)** — LLM autonomy levels (0-5)
- **[Runbook](./runbook.md)** — Operations guide

---

## By Role

### 👨‍💼 Traders (Want to understand decisions)
1. Read: [AI Pages Guide](./AI-PAGES-GUIDE.md)
2. Check: `/ai-decisions` page daily
3. Monitor: `/agent-intelligence` weekly
4. Use skill: `/paper-status` for health check

### 👨‍💻 Developers (Want to modify agents)
1. Read: [AI System Architecture](./AI-SYSTEM-ARCHITECTURE.md)
2. Study: `bot/llm/agents/coordinator.py` (orchestration)
3. Study: `bot/llm/agents/prompts.py` (all agent prompts)
4. Example: `bot/tests/test_multi_agent.py`
5. Debug: Use `/agent-debug [symbol]` skill

### 🔧 Operators (Want to deploy and monitor)
1. Read: [Runbook](./runbook.md) — Operations guide
2. Read: [AI System Architecture](./AI-SYSTEM-ARCHITECTURE.md) — Configuration section
3. Run: `cd bot && python run.py paper` to start
4. Monitor: Web dashboard at http://localhost:3000
5. Health: Use `/health-check [quick|deep]` skill

### 📊 Analysts (Want to optimize performance)
1. Read: [AI Pages Guide](./AI-PAGES-GUIDE.md) — Agent Intelligence section
2. Check: `/agent-intelligence` weekly
3. Analyze: Per-agent accuracy by regime
4. Use skill: `/growth-report` for learning summary
5. Use skill: `/veto-review [period]` for decision analysis

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

### Reference
- **[AUTONOMY.md](./AUTONOMY.md)** — LLM autonomy levels and safety rules
- **[Runbook](./runbook.md)** — Operations procedures
- **[LEARNINGS.md](./LEARNINGS.md)** — Learning outcomes and discoveries

---

## Quick Navigation by Topic

### Common Tasks

**Understand why a trade happened**
- Read: [AI Pages Guide](./AI-PAGES-GUIDE.md) (Page 1: AI Decisions)
- Check: `/ai-decisions` page for that symbol
- Debug: Use `/agent-debug [symbol]` skill

**Improve agent accuracy**
- Read: [AI Pages Guide](./AI-PAGES-GUIDE.md) (Page 2: Agent Intelligence)
- Check: `/agent-intelligence` page for accuracy by regime
- Optimize: Use `/prompt-calibrate [agent]` skill

**Reduce LLM costs**
- Read: [AI Pages Guide](./AI-PAGES-GUIDE.md) (Page 3: LLM Audit)
- Check: `/llm-audit` page for routing matrix
- Optimize: Use `/cost-audit [period]` skill

**Fix system issues**
- Check: `/health-check` skill for diagnostics
- Trace: Use `/agent-debug` skill for full pipeline
- Review: Check `bot/llm/agents/consistency_checker.py` logic

**Configure the system**
- Autonomy: See [AUTONOMY.md](./AUTONOMY.md)
- Models: See [AI System Architecture - Configuration](./AI-SYSTEM-ARCHITECTURE.md#environment-configuration)
- Prompts: Edit `bot/llm/agents/prompts.py`

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

Before deploying:

- [ ] `.env` file configured with `ANTHROPIC_API_KEY`
- [ ] `LLM_MULTI_AGENT=true` enabled
- [ ] `LLM_MODE` set to autonomy level (0-5)
- [ ] `LLM_USAGE_TIER` set (CONSERVATIVE/RECOMMENDED/AGGRESSIVE)
- [ ] `ENVIRONMENT=paper` for paper trading
- [ ] Agent environment variables optional (will use defaults)

See: [AI System Architecture](./AI-SYSTEM-ARCHITECTURE.md) for configuration details

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

