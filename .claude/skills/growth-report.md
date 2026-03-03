# /growth-report — Comprehensive Learning Intelligence Report

## Description
Generate a unified intelligence report across all growth systems: hypotheses, recommendations, self-improvement proposals, veto feedback, parameter changes, and curriculum progress. The "state of the brain" report.

## Arguments
- `$ARGUMENTS` — Optional: "summary" (one-page), "deep" (full analysis), or specific section ("hypotheses", "recommendations", "curriculum", "vetoes", "parameters")

## Workflow

### 1. Load All Growth Data
Read from all growth system files:
- `bot/data/llm/growth/hypotheses.json` — hypothesis tracker
- `bot/data/llm/growth/recommendations.json` — recommendation engine
- `bot/data/llm/growth/self_improvement_proposals.json` — self-improvement proposals
- `bot/data/llm/growth/veto_tracker.json` — veto feedback
- `bot/data/llm/growth/parameter_changes.json` — explainability/parameter audit trail
- `bot/data/llm/growth/growth_reports.json` — previous growth reports
- `bot/data/llm/teaching/curriculum_state.json` — self-teaching curriculum

Also read:
- `bot/data/feedback/confidence_state.json` — adaptive confidence state
- `bot/data/feedback/tuner_state.json` — parameter tuner trust score
- `bot/data/feedback/signal_quality.json` — signal quality dimensions

### 2. Curriculum Status
```
SELF-TEACHING CURRICULUM
━━━━━━━━━━━━━━━━━━━━━━━━
Current Level:    X — <LEVEL_NAME>
Time at Level:    XX hours
Total Runtime:    XXX hours
Trades Analyzed:  XXX
Knowledge Entries: XXX

Level Progression:
  ✓ Level 1: PATTERN_RECOGNITION (completed)
  ✓ Level 2: CAUSAL_ANALYSIS (completed)
  → Level 3: PREDICTIVE_MODELING (in progress — XX% complete)
    Level 4: OPTIMIZATION (upcoming)
    Level 5: MASTERY (upcoming)

Knowledge Breakdown:
  Axioms:       X (hard rules)
  Principles:   X (data-backed beliefs)
  Observations: X (raw patterns)
  Anti-patterns: X (things to avoid)
```

### 3. Hypothesis Pipeline Health
```
HYPOTHESIS TRACKER
━━━━━━━━━━━━━━━━━━
Total Active: N (max 300)

Pipeline Flow:
  PROPOSED → TESTING → VALIDATED → CODIFIED
  N          N         N           N

Newly Graduated (last 7d): N
  [List top 3 with statement and confidence]

Stuck in Testing (>30 days): N
  [List top 3 that need more evidence]

Top Active Hypotheses:
  1. "..." (XX% confidence, N evidence entries)
  2. "..." (XX% confidence, N evidence entries)
  3. "..." (XX% confidence, N evidence entries)
```

### 4. Recommendation Status
```
RECOMMENDATION ENGINE
━━━━━━━━━━━━━━━━━━━━━
Total: N | Pending: N | Applied: N | Validated: N

Source Accuracy:
  adaptive_confidence:  XX% (N recommendations)
  feedback_loop:        XX% (N recommendations)
  self_teaching:        XX% (N recommendations)
  llm_decision:         XX% (N recommendations)

Top Pending (by impact score):
  1. [Title] — confidence: XX%, expected impact: +XX%
  2. [Title] — confidence: XX%, expected impact: +XX%
  3. [Title] — confidence: XX%, expected impact: +XX%

Recently Applied:
  1. [Title] — outcome: POSITIVE/NEGATIVE/PENDING
  2. [Title] — outcome: POSITIVE/NEGATIVE/PENDING
```

### 5. Self-Improvement Proposals
```
SELF-IMPROVEMENT ENGINE
━━━━━━━━━━━━━━━━━━━━━━━
Total Proposals: N
Auto-Applicable: N (safe to auto-apply)
Pending Review: N (needs human approval)

Meta-Learning (source accuracy):
  self_improvement: XX% accurate
  feedback_loop:    XX% accurate
  llm_decision:     XX% accurate

Recent Proposals:
  1. [RULE] "..." — safety: AUTO_SAFE, confidence: XX%
  2. [PARAM] "..." — safety: REVIEW_NEEDED, confidence: XX%
  3. [STRATEGY] "..." — safety: CODE_CHANGE, confidence: XX%
```

### 6. Parameter Change Trail
```
PARAMETER CHANGES (last 30d)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total Changes: N
Positive Impact: N (XX%)
Negative Impact: N (XX%)
Pending Assessment: N

Source Effectiveness:
  adaptive_confidence: XX% positive
  parameter_tuner:     XX% positive
  backtest:            XX% positive

Recent Changes:
  confidence_floor: 65 → 72 (POSITIVE, +3% WR since)
  max_leverage: 8x → 6x (POSITIVE, -2% drawdown)
  risk_per_trade: 0.015 → 0.012 (PENDING, 8 trades since)

Trust Score: X.XX / 0.95 (parameter tuner confidence)
```

### 7. Veto Feedback Summary
```
VETO TRACKER
━━━━━━━━━━━━
Total Vetoes: N | Resolved: N | Accuracy: XX%
PnL Saved: $X,XXX | PnL Missed: $X,XXX | Net: $X,XXX

Best Veto Context: [regime/symbol] (XX% accurate)
Worst Veto Context: [regime/symbol] (XX% accurate)
```

### 8. Feedback Loop Status
```
FEEDBACK LOOPS
━━━━━━━━━━━━━━
Adaptive Confidence Floor: XX% (±X.X% from baseline)
Signal Quality Multiplier: X.XX (avg across dimensions)
Calibration Error: ±X.X% (target: ±3%)
Continuous Backtest: Running (last: Xh ago)
Parameter Tuner Trust: X.XX

System Health:
  Quality dimensions active: X/8
  Backtest windows active: X/3
  Feedback data freshness: XX minutes
```

### 9. Cross-System Insights
Synthesize across all systems:
- Are recommendations aligned with hypotheses?
- Are parameter changes matching recommendation suggestions?
- Is the curriculum advancing at the expected rate?
- Are veto decisions improving with more learning?
- Is there a positive feedback loop (learning → better decisions → more learning)?

### 10. Unified Report
```
GROWTH INTELLIGENCE REPORT — <timestamp>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LEARNING VELOCITY: [accelerating/steady/slowing]
SYSTEM MATURITY: Level X — <LEVEL_NAME>

KEY METRICS:
  Hypothesis graduation rate: X/month
  Recommendation accuracy: XX%
  Parameter trust score: X.XX
  Veto net value: $X,XXX/month
  Calibration error: ±X.X%

TOP 3 ACTIONS:
  1. [Highest impact recommendation with evidence]
  2. [Most mature hypothesis ready to codify]
  3. [Most needed parameter adjustment]

SYSTEM HEALTH: [THRIVING / GROWING / STABLE / STALLED / REGRESSING]
```
