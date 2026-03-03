# /confidence-calibrate — Fix Calibration Drift Across Agents

## Description
Analyze confidence calibration across all agents and the feedback system. Detect overconfidence, underconfidence, and calibration drift. Generate specific corrections for prompts, self-perf factors, and adaptive confidence thresholds.

## Arguments
- `$ARGUMENTS` — Optional: specific agent ("regime", "trade", "risk", "critic"), "system" for end-to-end, or "all"

## Workflow

### 1. Gather Calibration Data
Load from multiple sources:
- `bot/data/llm/decisions.jsonl` — predicted confidence per decision
- `bot/data/trades.csv` — actual outcomes (win/loss, PnL)
- `bot/data/feedback/confidence_state.json` — adaptive confidence bins
- `bot/data/llm/deep_memory/` — strategy fingerprints (confidence_vs_actual)
- `bot/data/feedback/tuner_state.json` — calibration offset from parameter tuner

Need minimum 30 decisions with resolved outcomes for meaningful analysis.

### 2. Build Calibration Curves

**System-Level Calibration:**
Bin all decisions by confidence and compute actual win rate:
```
SYSTEM CALIBRATION CURVE
━━━━━━━━━━━━━━━━━━━━━━━━
Confidence  Predicted WR  Actual WR   Gap      N Trades   Verdict
50-55%      52.5%         48%         -4.5%    12         OK
55-60%      57.5%         51%         -6.5%    18         Slight overconf
60-65%      62.5%         55%         -7.5%    25         Overconfident ⚠
65-70%      67.5%         64%         -3.5%    30         OK
70-75%      72.5%         70%         -2.5%    22         Well calibrated ✓
75-80%      77.5%         73%         -4.5%    15         OK
80-85%      82.5%         82%         -0.5%    10         Well calibrated ✓
85-90%      87.5%         79%         -8.5%    8          OVERCONFIDENT ⚠
90-100%     95.0%         78%         -17%     5          DANGER ⚠⚠
```

**Per-Agent Calibration:**
For each agent (Regime, Trade, Risk, Critic):
- What confidence does this agent typically output?
- How does the agent's confidence correlate with actual outcomes?
- Is the agent systematically biased? (always high, always low)

### 3. Calibration by Context
Break down calibration errors by:

**By Regime:**
- In "trend": is the system more accurate (tighter calibration)?
- In "range": is the system overconfident?
- In "panic": does confidence drop appropriately?

**By Strategy Agreement:**
- 4/4 agree: calibration at this consensus level
- 3/4 agree: calibration at this consensus level
- 2/4 agree (minimum): calibration at this consensus level
- Is more agreement actually more reliable?

**By Symbol:**
- Per-symbol calibration curve (BTC, ETH, SOL, etc.)
- Some symbols may be inherently harder to predict

**By Time of Day:**
- Calibration during high-volume hours vs low-volume

### 4. Self-Performance Correction Effectiveness
Read `bot/llm/decision_engine.py` — the calibration correction step:
```python
correction = cal * 0.5  # 50% of calibration offset applied
decision.confidence -= correction
```

Evaluate:
- Is the 0.5 multiplier correct? (too aggressive = overcorrection, too soft = undercorrection)
- After correction, is calibration actually better?
- Compute optimal correction factor from data

### 5. Adaptive Confidence Floor Validation
Read `bot/data/feedback/confidence_state.json`:
- Current floor value
- Per-bin EV analysis: is the floor set at the right level?
- Trust bonus components: are they justified?
- Per-strategy floor adjustments: are they helping?
- Per-symbol adjustments: are they helping?
- Per-regime adjustments: are they helping?

Verify: is the bot trading signals that should be skipped (below optimal floor)?

### 6. Regime Agent Accuracy
Specifically for the Regime Agent:
- How often does the classified regime match what actually happened?
- Regime accuracy per symbol
- Regime transitions: does the agent catch shifts in time?
- Penalty effectiveness: does the regime penalty (applied when accuracy <40%) help?

### 7. Calibration Improvement Plan
Based on analysis, generate specific fixes:

**Prompt-Level Fixes:**
- If 90%+ confidence is unreliable: add explicit ceiling guidance to Trade Agent prompt
  - "Confidence above 85% requires: 4/4 strategy agreement + regime confirmation + clean setup"
- If specific regimes are miscalibrated: add regime-specific confidence guidance
- If specific agents are biased: adjust their confidence scale definition

**System-Level Fixes:**
- Optimal self-perf correction multiplier (if different from 0.5)
- Optimal adaptive confidence floor
- Per-context adjustment recommendations

**Feedback Loop Fixes:**
- Adjust confidence bin boundaries if some bins have too few samples
- Adjust trust bonus weights if they're miscalibrated
- Adjust per-strategy/symbol/regime offsets

### 8. Report
```
CONFIDENCE CALIBRATION REPORT — <timestamp>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

OVERALL CALIBRATION ERROR: ±X.X% (target: ±3%)
Decisions analyzed: N

SYSTEM VERDICT:
  50-75% range: Well calibrated ✓
  75-85% range: Slightly overconfident (gap: -X%)
  85-100% range: OVERCONFIDENT (gap: -XX%) ⚠

PER-AGENT CALIBRATION:
  Regime Agent:  ±X.X% (XX% regime accuracy)
  Trade Agent:   ±X.X% (main bias source)
  Risk Agent:    N/A (doesn't output confidence)
  Critic Agent:  ±X.X% (adjustments help/hurt)

CONTEXT BREAKDOWN:
  Best calibrated:  [regime/symbol/time] (±X%)
  Worst calibrated: [regime/symbol/time] (±XX%)

SELF-PERF CORRECTION:
  Current multiplier: 0.5
  Optimal multiplier: X.XX
  Correction effectiveness: XX% of error removed

RECOMMENDED FIXES:
  1. [Specific prompt change] — expected: -X% calibration error
  2. [Correction factor adjustment] — expected: -X% error
  3. [Floor adjustment] — expected: +X% win rate on marginal trades

PROJECTED IMPACT:
  Current system WR: XX%
  After calibration fixes: ~XX% (+X%)
```
