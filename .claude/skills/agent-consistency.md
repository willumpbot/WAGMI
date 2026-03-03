# /agent-consistency — Cross-Agent Consistency Audit

## Description
Audit the multi-agent pipeline for vocabulary drift, reasoning contradictions, confidence miscalibration, and flip-flopping. Uses the consistency checker framework and historical decision data.

## Arguments
- `$ARGUMENTS` — Optional: "quick" (last 10 decisions), "deep" (full 50-decision window), or specific agent pair ("regime-trade", "trade-critic")

## Workflow

### 1. Load Consistency History
- Read `bot/llm/agents/consistency_checker.py` — understand the 5 core checks
- Query the `ConsistencyTracker` (50-decision window) via code or by reading data files
- Read `bot/data/llm/decisions.jsonl` — last N decisions with full agent outputs

### 2. Run 5 Core Consistency Checks

**Check 1: Regime-Action Alignment (CRITICAL)**
For each recent decision:
- Read Regime Agent's output: `{"rg": "...", "conf": ...}`
- Read Trade Agent's action: go/skip/flip
- Cross-reference with `REGIME_ACTION_MAP` in `bot/llm/agents/shared_context.py`
- Flag: forbidden actions taken, non-preferred actions chosen
- Example violation: Regime="panic" + Trade Action="go long" (forbidden)

**Check 2: Confidence Coherence (WARNING)**
- Trade Agent confidence >0.7 but Regime confidence <0.3 → suspicious
- Any agent proceeding with confidence <0.5 → CRITICAL
- Risk Agent sizing contradicts trade confidence (high conf + low size or vice versa)

**Check 3: Sizing Sanity (WARNING)**
- Risk Agent's `size_multiplier` vs regime's `sizing_range` from shared context
- 20% tolerance buffer — flag anything outside
- Zero size with "go" action = contradiction

**Check 4: Critic-Trade Alignment (INFO)**
- Critic approved a low-confidence trade (<60%) → why?
- Critic increased confidence above Trade Agent's → suspicious
- Critic challenged but final decision still proceeded → was override correct?

**Check 5: Flip Consistency (CRITICAL)**
- Count flips in last 20 decisions
- >30% flip rate → "likely destroying edge"
- Flip → reverse flip within 3 decisions → "flip-flopping"

### 3. Vocabulary Audit
Read all recent agent outputs and verify:
- Regime names: only `trend`, `range`, `panic`, `high_volatility`, `low_liquidity`, `news_dislocation`, `unknown`
- Action names: only `go`/`proceed`, `skip`/`flat`, `flip`/`reverse`
- Confidence: 0.0-1.0 scale (not 0-100, not percentages)
- All outputs valid JSON (no prose leaks)

Flag any non-canonical vocabulary.

### 4. Thought Protocol Compliance
Read `bot/llm/agents/thought_protocol.py` — per-agent protocol definitions.
For each agent's recent outputs:
- Does Regime Agent follow OBSERVE → RECALL → CLASSIFY?
- Does Trade Agent follow OBSERVE → RECALL → REASON → DECIDE → JUSTIFY?
- Does Risk Agent follow OBSERVE → SIZE → FLAG?
- Does Critic follow OBSERVE → CHALLENGE → VERDICT?
- Run `validate_agent_output_against_protocol()` heuristics

### 5. Cross-Agent Communication Audit
Read `bot/llm/agents/shared_context.py` — `PipelineScratchpad` class.
For each pipeline run:
- Did Regime Agent write regime/regime_conf/bias to scratchpad?
- Did Trade Agent read regime from scratchpad correctly?
- Did Risk Agent read trade decision from scratchpad correctly?
- Did Critic Agent receive all prior outputs?
- Were any scratchpad values missing or malformed?

### 6. Trend Analysis
Using the ConsistencyTracker's 50-decision window:
- Average consistency score over time (improving/declining/stable?)
- Most common issues (which check fails most often?)
- Per-agent error attribution (which agent causes the most issues?)
- Regime-specific consistency (more consistent in trend vs. range?)

### 7. Report
```
AGENT CONSISTENCY AUDIT — <timestamp>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CONSISTENCY SCORE: 0.XX (trend: improving/stable/declining)
Decisions Analyzed: N

CHECK RESULTS:
  1. Regime-Action Alignment:  X/N passed  [CRITICAL issues: X]
  2. Confidence Coherence:     X/N passed  [WARNING issues: X]
  3. Sizing Sanity:            X/N passed  [WARNING issues: X]
  4. Critic-Trade Alignment:   X/N passed  [INFO issues: X]
  5. Flip Consistency:         X/N passed  [CRITICAL issues: X]

VOCABULARY COMPLIANCE: XX% (N violations found)
THOUGHT PROTOCOL COMPLIANCE: XX% per agent

MOST COMMON ISSUES:
  1. [Issue description] — occurred X times
  2. [Issue description] — occurred X times

WORST AGENT PAIR: <agent1>-<agent2> (X contradictions)

RECOMMENDATIONS:
  1. [Specific prompt fix for most common issue]
  2. [Shared context adjustment]
  3. [Model tier change if complexity is the problem]
```

### 8. Auto-Fix Proposals
For each CRITICAL or recurring issue:
- Propose specific prompt edit (file + line + change)
- Propose shared context update (regime-action map, sizing ranges)
- Propose consistency checker threshold adjustment
- Always verify fix wouldn't break downstream agents
