# /veto-review — Analyze Veto Decisions and Accuracy

## Description
Deep analysis of the Critic Agent's veto decisions — were they correct? How much money did they save (or miss)? Are there patterns in veto accuracy by regime, symbol, or trigger?

## Arguments
- `$ARGUMENTS` — Optional: time range ("today", "7d", "30d"), "accuracy" for stats only, or "all"

## Workflow

### 1. Load Veto Data
Read `bot/data/llm/growth/veto_tracker.json`:
- All recorded vetoes with: symbol, side, confidence, entry_price, SL, TP1, TP2
- Resolution status: "would_have_won", "would_have_lost", "unclear"
- LLM reason for each veto
- Regime and trigger context

Read `bot/data/llm/decisions.jsonl`:
- All decisions where `is_veto == true`
- Filter by time range from `$ARGUMENTS`

### 2. Veto Accuracy Analysis
Overall veto accuracy:
```
VETO ACCURACY SUMMARY
━━━━━━━━━━━━━━━━━━━━━
Total Vetoes:        N
Resolved:            N
Would have lost:     N (XX%) — CORRECT vetoes ✓
Would have won:      N (XX%) — MISSED opportunities ✗
Unclear:             N (XX%)

Veto Accuracy:       XX%
PnL Saved:           $X,XXX (from correct vetoes)
PnL Missed:          $X,XXX (from wrong vetoes)
Net Value:           $X,XXX (saved - missed)
```

### 3. Veto Accuracy by Context

**By Regime:**
```
Regime          Vetoes  Correct  Accuracy  Net Value
trend           N       N        XX%       $XXX
range           N       N        XX%       $XXX
panic           N       N        XX%       $XXX
high_volatility N       N        XX%       $XXX
```
- Identify regimes where vetoes are valuable vs harmful

**By Symbol:**
- Which symbols benefit most from veto protection?
- Which symbols are over-vetoed (missing profitable trades)?

**By Confidence Level:**
- Vetoes on high-confidence signals (>75%): are these correct?
- Vetoes on marginal signals (60-70%): expected to be more correct

**By Trigger:**
- PRE_TRADE vetoes vs REGIME_SHIFT vetoes
- Which trigger types produce the most valuable vetoes?

**By Time:**
- Veto accuracy trend over time (improving or degrading?)
- Time-of-day patterns in veto accuracy

### 4. Veto Reason Analysis
Categorize the LLM's stated reasons for vetoing:
- "High funding rate" → how often correct?
- "Regime mismatch" → how often correct?
- "Conflicting signals" → how often correct?
- "Recent loss streak" → how often correct?
- "Low liquidity" → how often correct?

Identify:
- **High-value reasons**: consistently correct (>70% accuracy)
- **Low-value reasons**: often wrong (<50% accuracy) — Critic may be miscalibrated here
- **New reasons**: not seen before — worth tracking

### 5. Missed Vetoes
Look at losing trades that were NOT vetoed:
- Read trades from `bot/data/trades.csv` where PnL < 0
- Cross-reference with decisions: was a veto considered?
- Were there warning signs the Critic missed?

Categorize missed vetoes:
- Critic approved but should have challenged
- Critic wasn't consulted (pipeline didn't reach Critic)
- No warning signs available (legitimate loss)

### 6. Critic Agent Prompt Effectiveness
Based on accuracy analysis:
- Is the Critic's review checklist comprehensive?
  - Regime-action match ✓
  - Confidence calibration ✓
  - Consistency check ✓
  - Risk flags ✓
  - Memory lessons ✓
  - Leverage check ✓
- Are there missing checklist items based on missed veto patterns?
- Is the Critic's threshold for vetoing too high or too low?

### 7. Recommendations
Based on analysis:

**Adjust veto threshold:**
- If accuracy <60%: Critic is too aggressive (vetoing too much)
- If accuracy >80% but few vetoes: Critic may be too passive
- Optimal veto rate depends on regime

**Prompt improvements:**
- Add guidance for regime-specific veto thresholds
- Strengthen checking for high-accuracy veto reasons
- Reduce emphasis on low-accuracy veto reasons
- Add missed-veto scenarios as negative examples

**System improvements:**
- Inject veto accuracy stats into Critic's prompt context
- Adjust confidence adjustment in coordinator when Critic challenges
- Consider per-regime veto sensitivity

### 8. Report
```
VETO REVIEW — <date range>
━━━━━━━━━━━━━━━━━━━━━━━━━

OVERALL: XX% veto accuracy, $X,XXX net value

BEST VETO CONTEXTS:
  ✓ In 'panic' regime: XX% accurate, saved $XXX
  ✓ On 'funding rate' signals: XX% accurate, saved $XXX

WORST VETO CONTEXTS:
  ✗ In 'trend' regime: XX% accurate, LOST $XXX opportunity
  ✗ On high-confidence (>80%): XX% accurate, LOST $XXX

MISSED VETOES:
  X losing trades that could have been caught
  Common pattern: [description]

CRITIC AGENT HEALTH:
  Veto rate: X per day (target: Y per day)
  Confidence adjustment accuracy: XX%
  Review checklist coverage: XX%

RECOMMENDATIONS:
  1. [Specific change with expected impact]
  2. [Specific change with expected impact]
  3. [Specific change with expected impact]
```
