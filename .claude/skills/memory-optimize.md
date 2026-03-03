# /memory-optimize — Prune and Audit Memory Stores

## Description
Audit both short-term and deep memory stores for quality, staleness, relevance, and effectiveness. Prune noise, surface high-value patterns, and optimize memory for better agent decisions.

## Arguments
- `$ARGUMENTS` — Optional: "short-term", "deep", "prune", or "full" (default)

## Workflow

### 1. Short-Term Memory Audit
Read `bot/data/llm/llm_memory.json`:

**Inventory:**
- Total notes: N / 100 max
- Notes by symbol: {BTC: N, ETH: N, SOL: N, ...}
- Notes by regime: {trend: N, range: N, ...}
- Oldest note age (vs 7-day TTL)
- Average note length (vs 200 char max)

**Quality Assessment:**
Read `bot/llm/memory_store.py` — understand the quality gate (`_is_quality_note`).
For each note, evaluate:
- Passes quality gate? (>20 chars, not generic, has structure)
- Contains actionable info? (specific symbol, condition, outcome)
- Still relevant? (market conditions may have changed)
- Duplicates or near-duplicates? (>0.8 similarity)

**Flag low-quality notes:**
- Generic: "market went up", "lost money on trade"
- Stale: References conditions from >3 days ago
- Redundant: Same lesson stated 3+ times
- Orphaned: References symbols no longer traded

### 2. Deep Memory Audit
Read `bot/data/llm/deep_memory/` files:

**Trade DNA Store:**
- Total trades recorded (vs 500 max)
- Sniper trades count (quality_score >= 0.8)
- Win rate by: symbol, regime, side, strategy
- Oldest trade age
- Any corrupted records?

**Pattern Library:**
- Total patterns (vs 1000 max)
- Patterns by type: {entry_pattern: N, regime_pattern: N, ...}
- Pattern effectiveness: win rate per pattern type
- Low-effectiveness patterns (<30% win rate) — candidates for pruning
- Duplicate patterns (same description, different timestamps)

**Strategy Fingerprints:**
- Per-strategy accuracy metrics
- Confidence calibration: predicted vs actual (calibration curve)
- Auto-detected strengths/weaknesses: are they accurate?

**Insight Journal:**
- Total insights (vs 500 max)
- High-confidence insights (>0.7): are they validated?
- Validation rate: how many insights have been tested?
- Stale insights: not validated in >30 days

**Regime History:**
- Total transitions (vs 500 max)
- Transition frequency matrix: which transitions are most common?
- Unusual transitions: rare patterns worth investigating

### 3. Memory-to-Outcome Correlation
Cross-reference memory with trading outcomes:
- When a specific memory note was available, did it help?
- Which patterns from deep memory led to winning trades?
- Which insights were applied but didn't help?
- Which sniper trade templates are still producing wins?

### 4. Token Budget Analysis
Measure how much context each memory type consumes:
- `get_memory_summary()` — how many tokens for short-term?
- `build_llm_knowledge_summary()` — how many tokens for deep memory?
- Are we spending tokens on low-value information?
- Could we compress the summary and keep the same signal?

### 5. Pruning Recommendations
Categorize into:

**Auto-Prune (safe to remove):**
- Stale short-term notes (>7 days, should already be pruned)
- Exact duplicate patterns
- Invalid/corrupted records
- Zero-value insights (validated as wrong)

**Recommend Prune (user confirms):**
- Near-duplicate short-term notes
- Low-win-rate patterns (<30% over 10+ instances)
- Unvalidated insights older than 30 days
- Trade DNA records with missing critical fields

**Do Not Prune:**
- Sniper trade templates (even old ones have learning value)
- High-confidence validated insights
- Axioms and strong principles
- Regime transition history (valuable for pattern detection)

### 6. Execute Pruning (with confirmation)
If user approves:
- Remove flagged short-term notes
- Archive (not delete) flagged deep memory entries
- Log all removals for audit trail
- Verify memory stores still load correctly after changes

### 7. Optimization Suggestions
- **Quality gate tuning**: Should we tighten/loosen the filter in `memory_store.py`?
- **TTL adjustment**: Is 7 days right for short-term? Some lessons are timeless
- **Capacity adjustment**: Is 100 notes enough? 500 trades enough?
- **Summary optimization**: Can we compress the LLM summary to save tokens?
- **Injection priority**: Should symbol-specific notes be prioritized over general?

### 8. Report
```
MEMORY OPTIMIZATION REPORT — <timestamp>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SHORT-TERM MEMORY (llm_memory.json)
  Notes: XX/100 (XX% capacity)
  Quality: XX% pass quality gate
  Duplicates: X found
  Stale: X notes >5 days old
  Token cost: ~XXX tokens per summary

DEEP MEMORY
  Trade DNA: XXX/500 trades, XX sniper trades
  Patterns: XXX/1000, XX% win rate overall
  Insights: XXX/500, XX validated, XX pending
  Regime transitions: XXX recorded

MEMORY EFFECTIVENESS
  Trades with relevant memory available: XX%
  Win rate WITH memory context: XX%
  Win rate WITHOUT memory context: XX%
  Memory value: +X.X% win rate improvement

PRUNING PLAN
  Auto-prune: X items (safe)
  Recommended prune: X items (needs review)
  Protected: X items (do not touch)

TOKEN SAVINGS: ~XXX tokens/decision after optimization
```
