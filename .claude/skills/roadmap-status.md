# /roadmap-status — Check ROADMAP Progress and Plan Next Phase

## Description
Review ROADMAP.md against actual codebase state, identify what's done vs planned vs stalled, and recommend the highest-impact next work based on profitability goals.

## Arguments
- `$ARGUMENTS` — Optional: "status" (just show progress), "next" (what to work on), or specific phase number ("3", "5", "6")

## Workflow

### 1. Load ROADMAP
Read `ROADMAP.md` — parse all phases, tasks, and their checkbox status.

### 2. Verify Against Code
For each ROADMAP task marked as TODO:
- Does the code exist? (file present, functions implemented)
- Is it tested?
- Is it wired into the pipeline?
- Status: DONE / PARTIALLY DONE / NOT STARTED / BLOCKED

For tasks marked DONE:
- Quick verify: is the code actually working?

### 3. Phase Progress
```
ROADMAP STATUS — <timestamp>
━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 1: Stop Losing Money          ✅ COMPLETE
Phase 2: Multi-Agent LLM            ✅ COMPLETE
Phase 3: Agent Consistency           🔶 XX% complete
Phase 4: Configuration Extraction    ⬜ NOT STARTED
Phase 5: Production Hardening        ⬜ NOT STARTED
Phase 6: Alpha Generation            ⬜ NOT STARTED
Phase 7: Advanced Evolution           ⬜ NOT STARTED
```

### 4. Profitability-Ranked Next Steps
From all unfinished tasks, rank by estimated PnL impact:

The question isn't "what's next on the roadmap" but "what makes the most money soonest?"

Priority 1: Bug fixes that stop losing money (ROADMAP section 8)
Priority 2: Configuration changes that cut losses (Phase 4 items)
Priority 3: New strategies that add alpha (Phase 6 items)
Priority 4: Architecture that enables future alpha (Phase 3, 5)
Priority 5: Long-term evolution (Phase 7)

### 5. Recommend Session Focus
Based on current PnL and progress:
- If losing money → focus on Phase 1 bugs and config
- If breakeven → focus on edge optimization and loss elimination
- If profitable → focus on scaling (new strategies, more symbols)

### 6. Report
```
NEXT WORK — ranked by PnL impact
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. [Task] from Phase X — est +$XXX/mo — [X hours]
2. [Task] from Phase X — est +$XXX/mo — [X hours]
3. [Task] from Phase X — est +$XXX/mo — [X hours]
```
