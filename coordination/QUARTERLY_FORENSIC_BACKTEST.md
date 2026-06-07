# Quarterly Forensic Backtest Framework
**Maximum data extraction: Every decision, every feature, every trade analyzed microscopically**

---

## Philosophy
Leave no stone unturned. For each quarter:
1. **Every trade walkthrough** - full agent decision chain
2. **Every agent decision** - why approve/skip and accuracy
3. **Every regime transition** - when did market change
4. **Every feature used** - confidence, regime, volatility, momentum, etc
5. **Every failure mode** - what made agents wrong

---

## Per-Quarter Analysis Structure

### SECTION 1: TRADE-BY-TRADE WALKTHROUGHS
**For EVERY trade that fired (both executed and skipped)**

```
TRADE #1: BTC SHORT 2023-01-15 09:30 UTC
Status: EXECUTED | +$342.50

MARKET CONDITIONS AT ENTRY:
- Price: $42,100
- 1h trend: Down (EMA: 42,300 > 41,900) 
- 6h trend: Down (ADX=38, strong)
- Daily trend: Down (lower lows)
- Volatility: ATR=0.8%, moderately elevated
- Regime classification: trending_bear
- Funding rate: -0.015% (shorts paying, crowded longs)
- OI trend: Increasing (+2.1% 24h)
- Volume: 120% of 20-day average
- Recent action: Support broken at $42,300, rejected 3x
- Confluence: Volume spike + support break + funding negative

RAW SIGNAL (Mechanical):
- Strategy firing: regime_trend + bollinger_squeeze + confidence_scorer (3/4)
- Confidence: 87%
- Entry: $42,100 | SL: $42,600 | TP1: $41,500 | TP2: $40,500
- R:R: 1:2.4 (favorable)

AGENT DECISION CHAIN:

[1] REGIME AGENT ANALYSIS
    Input: 1h/6h/daily candles, ADX=38, EMA slopes, funding rate
    Internal reasoning:
      - "ADX 38 = strong trend (threshold is 25)"
      - "All timeframes aligned down = confluence"
      - "Funding -0.015% = shorts paying, indicates overcrowded longs"
      - "Volume spike = participation"
    Decision: "trending_bear" (high confidence, 0.95)
    Assessment: CORRECT ✓

[2] TRADE AGENT ANALYSIS
    Input: Signal (87% conf), regime (trending_bear), 3/4 strategies agree
    Internal reasoning:
      - "Regime favors shorts: trending_bear = established downtrend"
      - "Multiple strategies agree (3 of 4): high conviction"
      - "87% confidence above 80% threshold"
      - "Support broken = impulsive move, not pullback"
      - "R:R 1:2.4 favorable for risk/reward sizing"
    Approval decision: GO
    Confidence: 0.91
    Thesis: "BTC short into broken support with negative funding and strong ADX confirmation. Expect $1,000+ move."
    Assessment: CORRECT ✓

[3] RISK AGENT ANALYSIS
    Input: Approved signal, volatility=0.8%, equity=$50K, no open positions
    Calculation:
      - Risk per trade: 1% = $500
      - Stop width: $42,600 - $42,100 = $500 (1 ATR exactly)
      - Position size: $500 / $500 = 1.0 BTC
      - Leverage: 2.0x (trending_bear regime warrants this)
      - Portfolio check: 1 position open, max=8, OK
    Decision: 2.0x leverage, 1.0 BTC, SL=$42,600, TP1=$41,500, TP2=$40,500
    Kelly sizing: 2.0x correct (high edge + strong regime)
    Assessment: CORRECT ✓

[4] CRITIC AGENT ANALYSIS
    Input: Full trade proposal (entry/SL/TP, 2.0x leverage, thesis)
    Stress testing:
      - "Can I falsify this thesis?" 
        → "If price holds $42,300, thesis broken"
        → "If OI turns contrarian, thesis broken"
        → "Both have clear exit points"
      - "Is risk/reward reasonable?"
        → "Risking $500 to make $1,200+ = 2.4:1 ratio, excellent"
      - "Is leverage appropriate?"
        → "2.0x in trending_bear with strong ADX = justified"
      - "Any red flags?"
        → "None. All systems aligned."
    Decision: APPROVE
    Concern level: Low (0.1)
    Assessment: CORRECT ✓

EXECUTION & FILL:
- Order type: Market short
- Filled at: $42,098 (2 tick slippage)
- Slippage cost: -$200 (acceptable)
- Final entry: $42,098

RESULT:
- Exit type: Trailing stop (trailed down)
- Entry: $42,098
- Exit: $41,756 (at TP1)
- Gross: $342 (1.0 BTC × $342 move)
- Fees: -$38 (entry $12 + exit $26)
- Net: +$304.50
- Return on risk: 61% (risked $500, made $304)

POST-TRADE ANALYSIS:
- Did agents make the right call? YES
  - Regime detection: Correct (it was trending_bear)
  - Trade approval: Correct (2.4:1 R:R, strong confluence)
  - Sizing: Correct (2.0x leverage justified)
  - Exit timing: Good (closed near TP1, not held too long)
  
- What did agents miss? Nothing major
  - Could have held for TP2 (+$2,402 instead of +$304)
  - But trailing stop is safer, prevents reversals
  
- Confidence calibration: 87% signal, 61% actual return = miscalibrated
  - Signal was more bullish than realized
  - But better to be conservative on sizing
  
- Learning: Trending_bear + broken support + negative funding = highest-conviction setup
  - Validate this triple confluence in future

---

[REPEAT above for ALL other trades this quarter...]
```

### SECTION 2: AGENT ACCURACY MATRIX

```
AGENT PERFORMANCE ANALYSIS Q1 2023

[A] REGIME AGENT
Total predictions: 247
Accuracy: 94.3% (232 correct, 15 wrong)

Breakdown:
- trending_bear: 89 predictions, 98% accuracy (87/89 correct)
  → Only misses on edge cases (sudden reversals)
- trending_bull: 76 predictions, 92% accuracy (70/76 correct)
  → Underestimates bull momentum sometimes
- consolidation: 58 predictions, 81% accuracy (47/58 correct)
  → Often calls consolidation too early (before breakout)
- high_volatility: 24 predictions, 79% accuracy (19/24 correct)
  → Struggles with whipsaw regimes

Top error: Called consolidation on 2023-02-15, missed 3-day rally
Recommendation: Raise consolidation threshold (require 2+ hours chop, not just 1)

---

[B] TRADE AGENT
Total decisions: 247 signals
Approvals: 106 (43%)
Skips: 141 (57%)

Approval accuracy:
- Approved trades that won: 89 (84%)
- Approved trades that lost: 17 (16%)
- Overall approval W/R: 84%

Skip accuracy:
- Skipped trades that WOULD have lost: 127 (90%)
- Skipped trades that WOULD have won: 14 (10%)
- Overall skip accuracy: 90%

Combined: 84% + 90% = excellent filtering

Top miss: Skipped ETH SHORT 2023-03-08 (would have been +$1,247, 89% conf)
Why skipped: "Consolidation regime, wait for confirmation"
Lesson: Consolidation + 89% confidence should override regime doubt

---

[C] RISK AGENT
Total position sizings: 106 executed trades
Leverage assignments:
- 1.0-1.5x: 34 trades (32%), avg WR=71%
- 1.5-2.0x: 48 trades (45%), avg WR=87%
- 2.0-2.5x: 18 trades (17%), avg WR=92%

Kelly accuracy: 95% (97/106 sizing correct)
- Undersized: 6 trades (risked too little, left $3,200 on table)
- Oversized: 3 trades (risked too much, hit SL on 2)

Recommendation: Increase leverage caps in trending regimes from 2.0x to 2.5x
Potential additional return: +$3,200 for quarter (+2.4%)

---

[D] CRITIC AGENT
Total veto opportunities: 106 approved trades
Vetoes issued: 12 (11%)
Veto accuracy: 92% (11/12 correct)
- Correct vetoes (prevented losses): 11 trades, avg -$187 each = +$2,057 saved
- False veto (prevented wins): 1 trade, -$342 missed

Veto precision: 91% (true positive rate)
Veto recall: 89% (caught 11 of 12 bad trades)

Top false veto: 2023-01-27 SOL SHORT
- Thesis: "High volatility, wait for confirmation"
- Reality: Trade would have won +$487
- Lesson: Don't veto high-conf signals just for high volatility

---

Overall agent team score: 91% decision accuracy
(89% regime + 84% trade approval + 95% sizing + 92% veto = ensemble effect)
```

### SECTION 3: FEATURE IMPORTANCE ANALYSIS

```
WHICH FEATURES MATTERED MOST FOR WINNING TRADES?

Feature extraction from winning trades (N=89):

1. REGIME (most important)
   - trending_bear: 56 trades, 87% WR
   - trending_bull: 23 trades, 74% WR
   - consolidation: 8 trades, 41% WR
   - Impact: Regime accounted for 34% of W/R variance

2. CONFIDENCE SCORE (second)
   - 85%+ conf: 67 trades, 89% WR
   - 75-85% conf: 18 trades, 72% WR
   - 65-75% conf: 4 trades, 50% WR
   - Impact: Each 10% confidence = +2% WR

3. STRATEGY AGREEMENT (third)
   - 3+ strategies: 78 trades, 87% WR
   - 2 strategies: 11 trades, 64% WR
   - 1 strategy: 0 trades (all rejected)
   - Impact: Multi-strategy consensus = +23% WR

4. VOLATILITY (fourth)
   - ATR 0.5-1.0%: 45 trades, 84% WR (trending, lower vol)
   - ATR 1.0-1.5%: 32 trades, 82% WR (sweet spot)
   - ATR 1.5-2.0%: 10 trades, 76% WR (high vol, harder to trade)
   - ATR 2.0%+: 2 trades, 50% WR (too volatile)
   - Impact: Moderate volatility (1.0-1.5% ATR) = optimal

5. FUNDING RATE (fifth)
   - Negative funding (shorts paying): 67 trades, 88% WR
   - Neutral funding: 15 trades, 73% WR
   - Positive funding (longs paying): 7 trades, 57% WR
   - Impact: Funding alignment = +15% WR

6. VOLUME CONFIRMATION (sixth)
   - 120%+ of average: 71 trades, 85% WR
   - 100-120% of average: 16 trades, 75% WR
   - <100% of average: 2 trades, 50% WR
   - Impact: Volume spike = +10% WR

FEATURE HIERARCHY FOR NEXT ITERATION:
1. Regime (PRIMARY)
2. Confidence (PRIMARY)
3. Strategy agreement (PRIMARY)
4. Volatility (SECONDARY)
5. Funding rate (SECONDARY)
6. Volume (TERTIARY)

Recommendation: Focus optimization on top 3 features.
Current system gets these right 91% of the time.
Remaining 9% could improve by refining lower features.
```

### SECTION 4: FAILURE MODE ANALYSIS

```
WHICH TRADES LOST AND WHY? (Detailed for each loss)

LOSS #1: HYPE BUY 2023-01-23
- Entry: $68.50 (89% confidence)
- SL: $67.80
- Exit: SL hit, -$0.70
- Why approved: "High confidence, momentum on 5m"
- Why it failed: 5m momentum was noise, 1h trend was DOWN
- Root cause: Trade Agent overweighted 5m signal, didn't validate against 1h
- Prevention: Require multi-timeframe agreement (5m + 1h + 6h)

LOSS #2: SOL BUY 2023-02-08
- Entry: $32.40 (76% confidence)
- SL: $31.95
- Exit: SL hit, -$0.45
- Why approved: "Consolidation breakout, volume spike"
- Why it failed: False breakout, volume was institutional selling, not buying
- Root cause: Volume signal doesn't distinguish direction (up vs down volume)
- Prevention: Add directional volume analysis (buy volume vs sell volume)

LOSS #3: ETH BUY 2023-03-12
- Entry: $2,240 (71% confidence)
- SL: $2,180
- Exit: SL hit, -$60
- Why approved: "Oversold RSI (30), bounce expected"
- Why it failed: RSI hit 30 but no bounce came, continued down to $2,100
- Root cause: RSI oversold doesn't guarantee bounce (need confluence)
- Prevention: Require RSI + support level + funding alignment for entry

---

[REPEAT for all 17 losing trades...]

KEY PATTERN: 94% of losses were from:
1. Single-timeframe signals (5m without 1h confirmation) = 8 losses
2. Broken confluence (volume signal was false) = 5 losses
3. Regime confusion (consolidation vs breakout) = 3 losses
4. Mechanical signal without LLM confirmation = 1 loss

PREVENTION: Agents already catch 90% of these.
Remaining 10% requires tighter thresholds on lower-confidence signals.
```

### SECTION 5: REGIME TRANSITION ANALYSIS

```
HOW DID THE SYSTEM PERFORM AS REGIMES CHANGED?

Q1 2023 Regime Timeline:
- Jan 1-7: consolidation (low vol, choppy)
- Jan 8-15: trending_bear (flash crash, -$5,400)
- Jan 16-31: recovery/range
- Feb 1-14: trending_bull (rally, bot missing half the upside)
- Feb 15-28: consolidation again
- Mar 1-15: trending_bear (strong shorting opportunity)
- Mar 16-31: choppy/high_volatility

TRANSITION ACCURACY:
- Regime shift detection lag: 2-4 hours average
- False positive regime changes: 3 in quarter
- Missed regime changes: 0

PERFORMANCE DURING TRANSITIONS:
- Trades at regime boundaries: 12
- Win rate during boundaries: 58% (vs 64% overall)
- Average loss during boundaries: -$89 (vs -$67 overall)

LESSON: System has a 2-4 hour detection lag when regimes change.
Should tighten regime detection thresholds or add early-warning signals.

OPPORTUNITY: If we catch regime changes 1 hour earlier:
- Avoid 3-4 boundary trades per quarter
- +0.5% improvement in overall W/R (62% → 62.5% equivalent)
```

### SECTION 6: CONFIDENCE CALIBRATION AUDIT

```
IS AGENT CONFIDENCE ACTUALLY ACCURATE?

Confidence reported vs actual win rate:

Confidence 85-90%: 67 signals approved
- Actual W/R: 89%
- Calibration: PERFECT (conf reported 87%, actual 89%)

Confidence 75-84%: 28 signals approved
- Actual W/R: 76%
- Calibration: GOOD (conf reported 80%, actual 76%, -4% error)

Confidence 65-74%: 8 signals approved
- Actual W/R: 62%
- Calibration: POOR (conf reported 70%, actual 62%, -8% error)

Confidence 55-64%: 3 signals approved
- Actual W/R: 33%
- Calibration: VERY POOR (conf reported 59%, actual 33%, -26% error)

FINDING: Confidence is well-calibrated above 75%.
Below 75%, confidence overestimates actual accuracy.

RECOMMENDATION:
- Keep minimum confidence at 80% for automated execution
- Trades at 65-75% need manual review
- Trades below 65% should be rejected entirely

This alone would improve W/R by ~3% (skipping worst-calibrated signals).
```

### SECTION 7: LEVERAGE SIZING ACCURACY

```
DID WE SIZE POSITIONS CORRECTLY?

For winning trades (N=89):
- Avg leverage assigned: 1.87x
- Avg actual return: 1.4% of account
- Expected return (Kelly): 1.3% of account
- Accuracy: 108% (slightly overlevered but profitable)

For losing trades (N=17):
- Avg leverage assigned: 1.64x
- Avg actual loss: -0.8% of account
- Expected loss (Kelly): -0.6% of account
- Accuracy: 133% (overlevered into losses)

INSIGHT: Risk Agent sized winners and losers similarly (1.87x vs 1.64x).
This is CORRECT (we don't know which way it will go).
But when trades go bad, the leverage amplifies the loss.

OPPORTUNITY:
- Current Kelly formula: (W% × AvgWin) - (L% × AvgLoss) × 0.25 (safety factor)
- Could tighten to 0.15 safety factor on low-confidence trades
- This would reduce average loss from -0.8% to -0.5% on losing trades
- Trade-off: Would also reduce winning trades from 1.4% to 1.0%
- Net effect: Better risk management, worth it

RECOMMENDATION: Conditional Kelly sizing based on confidence:
- 85%+ conf: Full Kelly × 0.25 safety factor (current)
- 75-84% conf: Kelly × 0.15 safety factor (tighter)
- <75% conf: Kelly × 0.10 safety factor (very tight)
```

---

## Output: Final Quarterly Report

For EACH quarter, deliver:
1. **Trade Ledger** — all trades with walkthroughs
2. **Agent Accuracy Report** — scores for all 4 agents
3. **Feature Importance** — what mattered most
4. **Failure Mode Analysis** — why losses happened
5. **Regime Analysis** — performance by market condition
6. **Confidence Calibration** — is agent confidence accurate
7. **Leverage Audit** — sizing appropriateness
8. **Key Findings** — top 3 insights per quarter
9. **Recommendations** — specific optimizations

---

## Automation: Quarterly Backtest Workflow

```bash
for quarter in 2023_Q1 2023_Q2 ... 2026_Q2; do
  echo "Running forensic backtest: $quarter"
  
  # 1. Run backtest
  python run.py backtest \
    --symbols BTC ETH SOL HYPE \
    --start-date $quarter_start \
    --end-date $quarter_end \
    --llm --budget 50 \
    --output backtest_$quarter.json
  
  # 2. Extract all trades with full decision chains
  python scripts/extract_trade_walkthroughs.py backtest_$quarter.json
  
  # 3. Generate forensic analysis
  python scripts/generate_forensic_report.py backtest_$quarter.json > forensic_$quarter.md
  
  # 4. Produce summary metrics
  python scripts/generate_metrics.py backtest_$quarter.json > metrics_$quarter.json
  
  echo "Complete: forensic_$quarter.md, metrics_$quarter.json"
done

# 5. Synthesize all quarters
python scripts/synthesize_all_quarters.py > FULL_FORENSIC_REPORT_2023_2026.md
```

---

## Time Estimate

Per quarter:
- Backtest run: 1.5 hours
- Forensic analysis generation: 30 min
- Manual review of key findings: 1 hour
- **Total per quarter: 3 hours**

14 quarters × 3 hours = **42 hours of work**
- Sequential: 2 weeks at 3h/day
- Parallel (4 concurrent): 3.5 days

**Deliverable: 50-100 page forensic audit covering every decision**
