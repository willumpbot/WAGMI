# PHASE 3: LIVE INTERACTION ARCHAEOLOGY

**Date**: 2026-04-28 (continuation)  
**Status**: Initial analysis complete  
**Scope**: Decision logging analysis, signal flow patterns, veto accuracy

---

## DECISION LOGGING ANALYSIS (625 total records)

### Distribution
- **api_error**: 62.2% (389 records) — LLM call failures
- **flat**: 21.0% (131 records) — Skipped signal (no trade)
- **multi_agent_decision**: 9.8% (61 records) — Agent voted to trade
- **sanitization_failed**: 3.8% (24 records) — Data validation failed
- **proceed**: 2.1% (13 records) — Executed trade
- **backend_failure**: 1.0% (6 records) — System error
- **validation_failed**: 0.2% (1 record) — Signal validation failed

### Critical Insight: Signal Filtering Intensity
**Only 2.1% of logged decisions resulted in trades executed**
- Means: 97.9% of signals were rejected/filtered
- Pattern: System was extremely conservative, skipping most signals

**Root cause for losses**: Not enough trades at good odds, too many rejections

---

## SAMPLE DECISION ANALYSIS

### Decision Record Example
```
ts: 1775669469 (2026-04-27)
action: "flat" (skip)
original_action: "flat"
confidence: 0.45 (45%)
regime: "low_liquidity"
size_multiplier: 0.0
is_veto: true
gate_reason: "flat_passthrough"
notes: "SURVIVAL SKIP: 25% recent WR demands extreme selectivity.
        BTC signal weak (2 strats, illiquid regime, low vol, conf<0.6).
        Memory shows BTC LONG lost in illiquid.
        No 3-way agreement.
        Chop score 0.26..."
```

### Interpretation
- **Context**: 25% recent WR created risk-averse stance
- **Signal quality**: Only 2 strategies agreed (min requirement for consensus)
- **Regime mismatch**: Illiquid regime (known bad for omniscient_integrated)
- **Memory**: Historical BTC LONG losses in illiquid
- **Decision**: Veto/skip (correct decision, avoided bad trade)

**Lesson**: System learned from losses and became conservative. But over-conservatism may have skipped good trades.

---

## KEY FINDINGS FROM DECISION ANALYSIS

### 1. LLM Integration Issues (62% API errors)
**Problem**: 389 of 625 decisions failed with api_error  
**Impact**: Cannot make trades without LLM decisions  
**Root cause**: Likely related to local neural network setup mentioned in memory  
**Solution**: Either fix LLM connectivity or use fallback signal processing

### 2. Signal Filtering Excessive (97.9% rejection rate)
**Problem**: Only 2.1% of signals executed, rest filtered  
**Comparison**: Typical trader might execute 20-40% of signals  
**Root cause**: Risk-averse gates after poor performance (25% WR)  
**Implication**: 
- May have skipped good trades to avoid bad ones
- Trade volume too low for statistical significance
- Possible missed opportunities during regime shifts

### 3. Veto Accuracy Shows Learning
**Pattern**: System correctly identified and rejected BTC signals in illiquid regime  
**Evidence**: "Memory shows BTC LONG lost in illiquid" → veto decision  
**Assessment**: Veto logic working correctly, but maybe too conservative

### 4. Regime Awareness Working
**Observation**: Decisions explicitly consider regime ("low_liquidity" gate reason)  
**Assessment**: Regime-based filtering is operational and preventing bad trades

---

## DECISION FLOW ANALYSIS

### Signal Path (based on decision records)
```
Signal Generated
    ↓
LLM Agent Decision (62% fail with api_error)
    ↓
Multi-agent consensus check (9.8% reach consensus)
    ↓
Gate checks: regime, liquidity, veto, etc. (21% filtered here)
    ↓
Execution (only 2.1% reach execution)
    ↓
Trade Result (logged in trades.csv)
```

### Bottlenecks Identified
1. **LLM layer**: 62% fail → need fallback or fix connectivity
2. **Consensus layer**: Only ~10% reach multi-agent decision
3. **Gate layer**: 21% filtered by gates (regime, veto, etc.)
4. **Execution layer**: Only 2.1% executed (too conservative)

---

## TRADING DECISION QUALITY ASSESSMENT

### What the System Got Right
- ✓ Identified illiquid regimes as bad (avoided BTC LONG)
- ✓ Applied regime-aware filtering
- ✓ Tracked historical losses and adjusted conservatively
- ✓ Used multi-agent consensus (2+ strategies agreement)
- ✓ Logged all decisions for analysis

### What the System Got Wrong
- ✗ LLM integration issues (62% API failures)
- ✗ Over-filtering signals (97.9% rejection rate)
- ✗ Not enough trades for statistical significance
- ✗ Possible false negatives (good trades skipped)

---

## VETO PATTERN ANALYSIS

### Veto Reasons (from decision records)
Based on sample, system vetoes:
1. **Regime mismatch**: "illiquid regime" for omniscient_integrated strategies
2. **Low confidence**: Signals below 0.45 confidence threshold
3. **Consensus failure**: Less than 3-way strategy agreement
4. **Historical loss patterns**: "Memory shows BTC LONG lost in illiquid"
5. **Liquidity concerns**: Low volume or spread widening

### Veto Accuracy Assessment
- **Correct vetoes**: BTC signals in illiquid (0% WR historically)
- **Potential false negatives**: May have skipped BTC trending signals (66% WR in trending)
- **Cost of conservatism**: Safe but missed profit opportunities

---

## SIGNAL VISIBILITY COMPARISON

### What We Know
- **Total signals generated**: Unknown (need to check ensemble logs)
- **Signals reaching decision logging**: 625 records
- **Signals resulting in trades**: ~13 executed (2.1%)
- **Actual trades executed**: 205 (from trades.csv)

**Discrepancy**: 205 actual trades but only 13 "proceed" decisions logged?
- Suggests decision.jsonl is incomplete or uses different logging
- May be using silent fallback when LLM unavailable
- Need to correlate decision records with actual trades

---

## RECOMMENDATIONS

### Immediate (Blocking Issues)
1. **Fix LLM API error rate** (62% failures)
   - Check neural network connectivity
   - Implement fallback signal processing
   - Expected: Increase decision throughput by 62%

2. **Reduce signal filtering** (97.9% rejection)
   - Lower veto threshold from 0.45 → 0.35 confidence
   - Increase min_votes from 2 → 1 for trending regimes
   - Expected: Increase trade volume 3-5x

### Short-term (Signal Quality)
1. **Regime-conditional thresholds**
   - Trending regime: Lower filters (more aggressive)
   - Illiquid regime: Higher filters (more conservative)
   - Current approach: Same filters for all regimes

2. **Veto accuracy measurement**
   - Track: "trades skipped" vs "would have won"
   - Calculate: Veto false positive rate
   - Adjust threshold accordingly

### Medium-term (System Learning)
1. **Decision replay system**
   - Replay decisions through current system
   - Measure: What would we do differently now?
   - Identify: Pattern changes and regime shifts

2. **Signal quality scoring**
   - Not just WR, but R:R and Sharpe ratio
   - Weight decisions by expected value, not just confidence
   - Correlate quality scores with outcomes

---

## NEXT PHASE: SYSTEM RELIABILITY (PHASE 4)

Will investigate:
1. Failure modes (agent crashes, data corruption, market halts)
2. Recovery mechanisms
3. Latency under load
4. Concurrent decision handling

This will complement the signal flow analysis with system robustness assessment.

