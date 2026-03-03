# /curriculum-advance — Self-Teaching Progress and Level Advancement

## Description
Review the self-teaching curriculum progress, evaluate mastery at the current level, and determine if the system is ready to advance. Includes knowledge validation and gap analysis per curriculum level.

## Arguments
- `$ARGUMENTS` — Optional: "status" (just show progress), "evaluate" (check advancement readiness), "advance" (attempt level-up)

## Workflow

### 1. Current Curriculum Status
Read `bot/data/llm/teaching/curriculum_state.json`:

```
CURRICULUM STATUS
━━━━━━━━━━━━━━━━
Level:           X — <LEVEL_NAME>
Time at Level:   XX hours (requirement: ~XX hours)
Trades Analyzed: XXX
Knowledge Entries: XXX

Level Descriptions:
  Level 1: PATTERN_RECOGNITION — "What happened?"
  Level 2: CAUSAL_ANALYSIS — "Why did it happen?"
  Level 3: PREDICTIVE_MODELING — "What will happen next?"
  Level 4: OPTIMIZATION — "How can I improve?"
  Level 5: MASTERY — "What are the universal principles?"
```

### 2. Level-Specific Mastery Evaluation

**Level 1 — PATTERN_RECOGNITION:**
- Can the system identify winning/losing patterns by symbol?
- Does it track regime-specific performance?
- Has it mapped time-of-day and day-of-week patterns?
- Has it identified strategy strengths/weaknesses?
- Mastery indicators: ≥10 observations per category, covers all symbols

**Level 2 — CAUSAL_ANALYSIS:**
- Can it explain WHY patterns occur? (not just that they exist)
- Has it built "if X then Y" rules?
- Does it understand cross-market influences (BTC → alts)?
- Has it identified causal links between conditions and outcomes?
- Mastery indicators: ≥5 principles with evidence, ≥3 anti-patterns

**Level 3 — PREDICTIVE_MODELING:**
- Can it predict signal quality before execution?
- Is confidence calibration ±5% or better?
- Are predictions better than random (>55% accuracy)?
- Has it built confidence intervals per setup type?
- Mastery indicators: calibration error <5%, prediction accuracy >55%

**Level 4 — OPTIMIZATION:**
- Has it identified suboptimal parameters?
- Has it proposed and validated rule adjustments?
- Are hypotheses being tested and graduated?
- Is the parameter tuner trust score >0.6?
- Mastery indicators: ≥5 validated hypotheses, trust score >0.6, ≥3 positive parameter changes

**Level 5 — MASTERY:**
- Has it codified meta-rules (regime-strategy mappings)?
- Can it generate novel hypotheses from cross-pollination?
- Is it teaching itself effectively (positive learning velocity)?
- Are its recommendations consistently accurate (>70%)?
- Mastery indicators: ≥10 codified rules, recommendation accuracy >70%, self-sustaining improvement

### 3. Knowledge Audit by Level
Read self-teaching knowledge base and map knowledge to curriculum levels:

```
KNOWLEDGE BY CURRICULUM LEVEL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Level  Knowledge Type      Count   Quality
L1     Observations        XX      XX% actionable
L2     Principles/Rules    XX      XX% validated
L3     Predictions         XX      XX% calibrated
L4     Optimizations       XX      XX% positive impact
L5     Meta-rules          XX      XX% codified
```

### 4. Gap Analysis
For the current level, identify what's missing:
- Which knowledge categories lack coverage?
- Which patterns haven't been formalized?
- What evidence gaps exist?
- What data does the system need to collect?

```
CURRENT LEVEL GAPS
━━━━━━━━━━━━━━━━━━
Level X — <LEVEL_NAME>

Required for mastery:
  ✓ [Completed requirement]
  ✓ [Completed requirement]
  ✗ [Missing: description + what's needed]
  ✗ [Missing: description + what's needed]
  ~ [Partial: description + what's remaining]

Estimated time to mastery: XX hours / XX trades
```

### 5. Advancement Decision
Evaluate if the system should advance:

**Criteria for advancement:**
- All mastery indicators for current level met
- Sufficient time at level (not rushing)
- Knowledge quality is high (validated, not just accumulated)
- Previous level skills maintained (no regression)

**Decision:**
- **ADVANCE**: All criteria met → propose level-up
- **HOLD**: Close but gaps remain → show what's needed
- **CONCERN**: Regression detected → investigate

### 6. Regression Check
Verify that earlier level skills are maintained:
- Level 1 patterns still accurate?
- Level 2 causal models still valid?
- Level 3 predictions still calibrated?
- If regression detected: the system may need to revisit an earlier level

### 7. Execute Advancement (with confirmation)
If "advance" in `$ARGUMENTS` and criteria met:
- Update curriculum state to next level
- Log advancement with timestamp and evidence
- Set new mastery targets
- Adjust learning priorities for new level
- Run: `cd bot && pytest tests/ -k "self_teaching" -v`

NEVER auto-advance without user confirmation.

### 8. Report
```
CURRICULUM ADVANCEMENT REPORT — <timestamp>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CURRENT: Level X — <LEVEL_NAME>
TIME AT LEVEL: XX hours (XX trades analyzed)

MASTERY CHECKLIST:
  ✓ [Criterion 1] — evidence: [data]
  ✓ [Criterion 2] — evidence: [data]
  ✗ [Criterion 3] — gap: [what's missing]

ADVANCEMENT: [READY / NOT YET / REGRESSION DETECTED]

NEXT LEVEL PREVIEW: Level X+1 — <NEXT_LEVEL_NAME>
  Focus: [description]
  Requirements: [list]
  Estimated time: XX hours

LEARNING VELOCITY:
  Knowledge/day: X.X entries
  Hypotheses/week: X.X
  Graduation rate: X/month
  Trend: [accelerating/steady/slowing]
```
