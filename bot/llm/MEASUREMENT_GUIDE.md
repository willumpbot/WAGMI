# TIER 2.5: Measurement Sprint Guide

## Purpose
Validate that LLM improvements (TIER 1-2) actually make money.

**Decision Point**: After 5-7 days of measurement, we decide:
- ✅ **KEEP LLM**: If net ROI > 20% (profit exceeds cost)
- ⚠️ **UNCERTAIN**: If net ROI 5-20% (gray zone, needs more data)
- ❌ **DISABLE LLM**: If net ROI < 5% (cost not justified)

---

## Key Metrics

### Cost Metrics
```
Cost per decision = Total API cost / Total LLM decisions

Example:
- 100 decisions/day
- $0.007/decision = $0.70/day
- At 100 profitable trades/week = $4.90/week cost
```

### Profit Metrics
```
Net ROI = (LLM PnL - LLM Cost) / LLM Cost

Example:
- LLM PnL: $100/week
- LLM Cost: $4.90/week
- Net ROI: (100 - 4.90) / 4.90 = 1,939% ✅ KEEP

vs.

- LLM PnL: $4.50/week
- LLM Cost: $4.90/week
- Net ROI: (4.50 - 4.90) / 4.90 = -8% ❌ DISABLE
```

### Comparison Metrics
```
LLM vs Baseline = LLM PnL - Mechanical-only PnL

Example:
- LLM trades: $100 PnL, 50% win rate
- Baseline trades: $80 PnL, 48% win rate
- LLM added value: +$20 (25% improvement)
- Cost: $4.90
- Net benefit: $15.10 ✅
```

---

## How to Run Measurement

### Phase 1: Gather Baseline (Day 1-3)
1. Disable all LLM improvements: set env var `LLM_ENABLED=false`
2. Run mechanical trading system only
3. Record all trade outcomes in baseline metrics
4. Target: 20-30 trades minimum for statistical validity

### Phase 2: Run with LLM (Day 4-5)
1. Enable LLM improvements: set `LLM_ENABLED=true`
2. Run with all TIER 1-2 features
3. Record all trade outcomes and LLM costs
4. Target: 20-30 trades minimum

### Phase 3: Analyze (Day 6)
1. Call `get_measurement_sprint().get_summary_report()`
2. Compare LLM vs Baseline
3. Calculate net ROI
4. Make recommendation

---

## Expected Outcomes

### Optimistic Scenario (KEEP LLM)
```
Mechanical only:    $80 PnL, 48% WR
LLM improves:       $110 PnL, 52% WR (+37% better!)
LLM cost:           $5 (0.07% of profit)
Net benefit:        $25 ✅

Recommendation: KEEP - LLM adds clear value
```

### Marginal Scenario (UNCERTAIN)
```
Mechanical only:    $80 PnL, 48% WR
LLM improves:       $90 PnL, 50% WR (+12.5% better)
LLM cost:           $8 (8% of profit)
Net benefit:        $2 ⚠️

Recommendation: UNCERTAIN - Run longer test
```

### Pessimistic Scenario (DISABLE)
```
Mechanical only:    $80 PnL, 48% WR
LLM decreases:      $75 PnL, 46% WR (-6% worse!)
LLM cost:           $5 (extra loss)
Net loss:           -$10 ❌

Recommendation: DISABLE - Mechanical system alone is better
```

---

## How to Integrate Measurement

### 1. Import the sprint
```python
from llm.measurement_sprint import get_measurement_sprint

sprint = get_measurement_sprint()
```

### 2. Start a cycle
```python
sprint.start_cycle(period="1d")
```

### 3. Record LLM costs
```python
# After each LLM decision
api_cost_usd = 0.007  # Or actual cost
api_calls = {"regime": 1, "trade": 1, "critic": 1}
sprint.record_llm_decision(api_cost_usd, api_calls)
```

### 4. Record trade outcomes
```python
# After trade closes
pnl = 25.50  # Profit or loss
is_win = pnl > 0

# If LLM gated this signal:
sprint.record_llm_trade(pnl, is_win)

# If mechanical-only (baseline):
sprint.record_baseline_trade(pnl, is_win)
```

### 5. End cycle and get results
```python
cycle = sprint.end_cycle()
print(f"Recommendation: {cycle.recommendation}")
print(f"ROI: {cycle.net_roi_pct:.0f}%")
print(f"Reasoning: {cycle.reasoning}")

# Get summary across all cycles
summary = sprint.get_summary_report()
print(summary)
```

---

## Decision Matrix

| Metric | KEEP ✅ | UNCERTAIN ⚠️ | DISABLE ❌ |
|--------|---------|-------------|-----------|
| Net ROI | > 20% | 5-20% | < 5% |
| LLM vs Baseline | +15% | +5-15% | -5% or worse |
| Confidence | 2+ cycles positive | Mixed | 2+ cycles negative |
| Action | Deploy TIER 3 | Extend test | Disable LLM fully |

---

## Key Insights to Look For

### Red Flags (Disable)
- 🚩 Slippage eating >50% of expected profit
- 🚩 Confidence calibration off (70% signals win <60% of time)
- 🚩 LLM decisions underperforming mechanical system
- 🚩 Agent debate adding cost without improving decisions
- 🚩 Async agents timing out (parallel adds latency?)

### Green Flags (Keep)
- ✅ Slippage < 10% of profit
- ✅ Confidence well-calibrated (70% signals win ~70% of time)
- ✅ LLM filtering improves win rate by 2-5%
- ✅ Setup profitability (TIER 1.1) actually working
- ✅ Regime-specific floors (TIER 1.2) reducing false signals

---

## Frequently Asked Questions

### Q: How many trades do I need for validity?
**A:** Minimum 20-30 trades per phase. Below 10 trades, margin of error too high.

### Q: What if results are mixed (keep/uncertain)?
**A:** Run longer test (7-10 days). Mixed results suggest small effect size. Need more data for statistical confidence.

### Q: What if mechanical system is already at 95% win rate?
**A:** LLM can't improve much. Focus on: (1) position sizing optimization, (2) slippage reduction, (3) throughput gains from async.

### Q: What if LLM costs are $1/day but profit is $0.50/day?
**A:** Disable immediately. Cost > profit = losing money. Unless there's strategic reason to keep testing.

### Q: Can I run both LLM and mechanical in parallel to compare?
**A:** Yes! Send same signal to both pipelines:
1. One path: LLM gating + execution
2. Other path: Mechanical only + execution
Compare outcomes at end of day.

---

## Success Criteria

**We declare LLM system successful if:**
1. ✅ At least 2 consecutive cycles show positive ROI
2. ✅ LLM adds > +10% to baseline profitability
3. ✅ Slippage analysis shows execution quality acceptable (<20% of profit)
4. ✅ Confidence calibration is accurate (prediction matches outcome)
5. ✅ Cost per profitable decision < 0.5% of profit

**Example success**:
- 100 profitable trades/week
- Baseline profit: $500
- LLM cost: $5
- LLM adds: +$60 (12% improvement)
- Net benefit: +$55 ✅ SUCCESS

---

## What Happens After Measurement?

### If KEEP ✅
- Deploy TIER 3 (Semantic Memory, Correlation tracking)
- Continue optimization work
- Measure quarterly to ensure sustained ROI

### If UNCERTAIN ⚠️
- Run extended measurement (10-14 days)
- Identify bottlenecks via execution quality metrics
- Try targeted fixes (e.g., improve regime floor calibration)
- Re-measure

### If DISABLE ❌
- Fully disable LLM system
- Revert to pure mechanical trading
- Focus all effort on mechanical system optimization
- Revisit LLM after mechanical system at mature state (95%+ performance)

---

## Metrics to Track in Decision Log

For each decision, log:
```json
{
  "timestamp": "2026-03-20T10:30:00Z",
  "symbol": "SOL",
  "llm_decision": "go",
  "llm_confidence": 0.72,
  "regime": "trend",
  "llm_cost": 0.007,
  "actual_outcome": "WIN",
  "pnl": 25.50,
  "is_llm_gated": true
}
```

This enables later analysis:
- Accuracy per regime
- Accuracy per confidence level
- Cost per profitable decision
- Which agent outputs drove decision
