# /knowledge-distill — Graduate Hypotheses into Actionable Rules

## Description
Review the hypothesis tracker, self-teaching curriculum, and deep memory to distill validated patterns into codified rules, principles, and anti-patterns. Bridges the gap between "we learned this" and "the system acts on it."

## Arguments
- `$ARGUMENTS` — Optional: "hypotheses" (focus on graduation), "rules" (review existing), "gaps" (find missing rules), or "full"

## Workflow

### 1. Hypothesis Inventory
Read `bot/data/llm/growth/hypotheses.json`:

**By Stage:**
```
HYPOTHESIS PIPELINE
━━━━━━━━━━━━━━━━━━
Stage         Count   Avg Confidence   Avg Evidence
PROPOSED      N       X.XX             X.X entries
TESTING       N       X.XX             X.X entries
VALIDATED     N       X.XX             X.X entries
INVALIDATED   N       X.XX             X.X entries
CODIFIED      N       X.XX             X.X entries
```

**By Category:**
- timing, regime, symbol, strategy, risk
- Which category has the most validated hypotheses?

**Ready for Graduation:**
Identify hypotheses in "testing" stage that meet graduation criteria:
- ≥10 evidence entries
- ≥70% supporting evidence (validates) OR ≤30% (invalidates)
- Sufficient confidence (>0.65)

### 2. Validated Pattern Review
For each validated hypothesis:
- Statement: what was the hypothesis?
- Evidence summary: how many supporting vs contradicting?
- Confidence level
- Graduation target: rule, principle, or anti-pattern?
- **Is it actually codified?** Check if it exists in the knowledge base

Flag "validated but not codified" — these are the highest priority items.

### 3. Knowledge Base Audit
Read self-teaching knowledge base (from `bot/llm/self_teaching.py`):

**By Type:**
- AXIOMS: hard rules (should never change) — count and list
- PRINCIPLES: strong beliefs (data-backed) — count and list
- OBSERVATIONS: raw data points — count
- ANTI-PATTERNS: things that don't work — count and list

**By Category:**
- entry_timing, regime, strategy, risk, execution, meta

**Quality Check:**
- Are axioms actually universally true? (no exceptions found in data?)
- Are principles still supported by recent trades? (or have they decayed?)
- Are anti-patterns still anti-patterns? (market conditions change)
- Are there redundant/conflicting entries?

### 4. Deep Memory Pattern Mining
Read `bot/data/llm/deep_memory/`:

**Sniper Trade Analysis:**
- Get sniper trades (quality_score >= 0.8)
- What do they have in common?
- Extract the "template" for high-quality setups
- Are these templates already captured as rules?

**Pattern Library Mining:**
- Which pattern types have the highest win rate?
- Are there undiscovered patterns (high frequency + high win rate + not yet a rule)?
- Which patterns were once good but have decayed?

**Insight Journal Review:**
- High-confidence validated insights → should these be rules?
- Cross-category insights (e.g., regime + timing = powerful combination)

### 5. Gap Analysis
Compare what the system has LEARNED vs what it ACTS ON:

**Learned but not acted on:**
- Validated hypothesis → no corresponding rule in knowledge base
- High-win-rate pattern → not referenced in agent prompts
- Validated insight → not injected into decision context

**Acted on but not validated:**
- Rules in knowledge base → no supporting evidence in hypothesis tracker
- Axioms → never tested against actual data
- Anti-patterns → based on intuition, not data

**Missing entirely:**
- Common failure modes not captured as anti-patterns
- Winning setups not captured as principles
- Regime-strategy mappings not formalized

### 6. Distillation Actions
For each gap found, propose:

**Codify (hypothesis → rule):**
- Specific knowledge entry to add
- Type: axiom, principle, or anti-pattern
- Exact content, confidence, category, tags
- Where in the prompt it should be injected

**Update (decayed rule):**
- Which rule needs refreshing
- New evidence that changes its applicability
- Updated confidence level

**Remove (invalidated):**
- Rules that data no longer supports
- Anti-patterns that are no longer anti-patterns
- Stale observations that clutter the context

**Promote (observation → principle):**
- Observations that have been consistently confirmed
- Should be elevated to principle status with higher injection priority

### 7. Execute Distillation (with confirmation)
If user approves:
- Add new knowledge entries via self-teaching API
- Update hypothesis stages (testing → codified)
- Prune invalidated entries
- Update deep memory insight validations
- Run: `cd bot && pytest tests/ -k "self_teaching" -v`

### 8. Report
```
KNOWLEDGE DISTILLATION REPORT — <timestamp>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

HYPOTHESIS PIPELINE:
  Ready to graduate: X hypotheses
  Validated but not codified: X (ACTION NEEDED)
  Invalidated (remove): X
  Still testing: X (need more evidence)

KNOWLEDGE BASE:
  Axioms: X | Principles: X | Anti-patterns: X | Observations: X
  Decayed rules (no longer supported): X
  Redundant entries: X

TOP DISTILLATION CANDIDATES:
  1. "SOL breakout longs fail in range regime" → ANTI-PATTERN
     Evidence: 15/18 supporting, 83% confidence
  2. "3+ strategy agreement in trend = 80% WR" → PRINCIPLE
     Evidence: 22/26 supporting, 85% confidence
  3. "High funding + declining OI predicts squeeze" → RULE
     Evidence: 12/14 supporting, 78% confidence

GAPS FOUND:
  Learned but not acted on: X patterns
  Acted on but not validated: X rules
  Missing entirely: X areas

ACTIONS:
  Codify: X new rules to add
  Update: X rules to refresh
  Remove: X entries to prune
  Promote: X observations to elevate
```
