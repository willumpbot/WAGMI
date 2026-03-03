# /agent-replay — Replay Historical Data Through Agent Pipeline

## Description
Replay historical market snapshots through the multi-agent pipeline to test prompt changes, model routing adjustments, or consistency fixes without live trading. Compare old decisions vs new ones.

## Arguments
- `$ARGUMENTS` — Optional: number of decisions to replay ("last 10", "last 50"), time range ("7d", "30d"), or "compare" to diff old vs new

## Workflow

### 1. Select Replay Window
Parse `$ARGUMENTS`:
- Default: last 20 decisions
- Time range: "7d" = all decisions from last 7 days
- "compare" mode: will run pipeline twice (old prompt vs new prompt)

### 2. Load Historical Snapshots
Read `bot/data/llm/decisions.jsonl`:
- For each decision in the replay window, extract:
  - The market snapshot that was used as input
  - The agent outputs that were produced
  - The final merged decision
  - The actual trade outcome (if resolved)

This is the "ground truth" — what the agents said, and what actually happened.

### 3. Reconstruct Pipeline Inputs
For each historical decision:
- Rebuild the input that each agent received
- Include: market data, regime classification, memory state, knowledge context
- Read `bot/llm/agents/coordinator.py` — understand `_build_*_input()` methods
- Reconstruct as closely as possible (some context may be lost)

### 4. Run Replay (Current Prompts)
For each historical snapshot, run through the current agent pipeline:

**Option A: Mock Mode (no API calls)**
- Use `bot/llm/test_harness.py` with mock responses
- Fast, free, but doesn't test actual LLM behavior

**Option B: Live Mode (real API calls)**
- Run actual LLM calls with current prompts
- Costs money ($0.007/decision × N decisions)
- Most accurate comparison
- Warn user about cost before proceeding

For each decision, capture:
- New Regime Agent output vs old
- New Trade Agent output vs old
- New Risk Agent output vs old
- New Critic Agent output vs old
- New merged decision vs old

### 5. Decision Comparison
For each replayed decision, compare old vs new:

```
DECISION #N: BTC — <timestamp>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

                    OLD             NEW             ACTUAL
Regime:             trend           trend           (price went up ✓)
Action:             go              go              —
Side:               LONG            LONG            —
Confidence:         0.78            0.72            —
Size Mult:          1.2             1.0             —
Critic Verdict:     approve         approve         —
Outcome:            WIN (+$230)     —               WIN

CHANGES: confidence -6pp, size -17% (more conservative)
VERDICT: Both correct, new is more conservative
```

### 6. Aggregate Analysis
Across all replayed decisions:

```
REPLAY SUMMARY — N decisions
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

AGREEMENT: XX% of decisions unchanged
IMPROVED:  XX% would have been better (avoided losses or caught wins)
DEGRADED:  XX% would have been worse (missed wins or took losses)
NEUTRAL:   XX% outcome unchanged

OLD PIPELINE:
  Wins: N, Losses: N, Win Rate: XX%, Total PnL: $X,XXX

NEW PIPELINE (projected):
  Wins: N, Losses: N, Win Rate: XX%, Total PnL: $X,XXX

DELTA: +X% win rate, +$XXX PnL
```

### 7. Compare Mode (A/B Prompt Testing)
If `$ARGUMENTS` contains "compare":
- Run replay once with current prompts (version A)
- User makes prompt changes
- Run replay again with new prompts (version B)
- Side-by-side comparison:

```
A/B PROMPT COMPARISON — N decisions
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

                 Version A (old)    Version B (new)
Win Rate:        XX%                XX%
Avg Confidence:  X.XX               X.XX
Calibration:     ±X.X%              ±X.X%
Veto Rate:       XX%                XX%
Consistency:     X.XX               X.XX
Projected PnL:   $X,XXX             $X,XXX

VERDICT: Version B is [better/worse/same] by [margin]
Statistical significance: [low/medium/high] (N=XX samples)
```

### 8. Edge Case Discovery
Flag decisions where old and new pipelines disagree:
- These are the "interesting" cases where prompt changes matter
- For each: what was the input, what changed, and which was correct?
- Use these as few-shot examples for future prompt tuning

### 9. Recommendations
Based on replay:
- Should the prompt changes be deployed? (only if win rate improves)
- Are there specific scenarios where new prompts are worse? (need more work)
- What's the confidence level in the comparison? (N=10 is low, N=50 is moderate)
- Suggest running paper trading for N days before going live

### 10. Cost Summary
```
REPLAY COST
  Decisions replayed: N
  API calls made: N × 4 agents = N calls
  Tokens used: ~XXX,XXX
  Total cost: $X.XX
```
