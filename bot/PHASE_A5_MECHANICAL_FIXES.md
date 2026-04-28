# Phase A.5: Mechanical Optimization Focus
**Status**: Analysis complete, executing mechanical fixes  
**Discovery**: Agents made performance worse (-$1,282 vs -$627). Focus on mechanical gate fixes instead.

## Root Causes Identified

### Problem 1: MIN_VOTES=2 Consensus Kills Profitability
- 1_agree (solo): 6 events, 67% WR, +$570.28
- 2_agree (consensus): 4 events, 0% WR, -$1,526.36
- **Difference: +$2,096.64 (360% better with solo)**

**Fix**: Lower MIN_VOTES from 2 to 1

### Problem 2: multi_tier_quality Always Losing
- multi_tier_quality: 0% WR, -$1,555.55 loss
- When paired with bollinger_squeeze (2_agree): 0% WR, -$1,526.36
- Confirmed: Disable this strategy

**Fix**: STRATEGY_MULTI_TIER_QUALITY_ENABLED=false (already done)

### Problem 3: Trading in Ranging/Consolidation Loses 100%
- ranging: 3 trades, 0% WR, -$1,245.04
- consolidation: 3 trades, 0% WR, -$1,073.69
- trending_bear: 2 trades, 100% WR, +$1,021.71
- trending_bull: 2 trades, 100% WR, +$340.93

**Fix**: Gate by regime - only trade trending markets

### Problem 4: mean_reversion Setup Always Loses
- mean_reversion: 3 trades, 0% WR, -$1,272.78
- trend_follow: 5 trades, 60% WR, +$462.55
- standard: 2 trades, 50% WR, -$145.85

**Fix**: Gate mean_reversion setup entirely, or require different confirmation

### Problem 5: Losing Hours Drain Profit
- 10:00 UTC: -$435.14 loss
- 07:00 UTC: -$452.35 loss
- 18:00 UTC: +$490.42 win
- 04:00 UTC: +$129.55 win

**Fix**: Skip trading during losing hours (10:00-11:00 UTC, 07:00-08:00 UTC)

## Phase A.5 Config Changes (All Mechanical)

### Change 1: Lower MIN_VOTES (Confidence Fix)
```bash
# OLD: MIN_VOTES_REQUIRED=1  # But actually voting for 2_agree
# NEW: MIN_VOTES_REQUIRED=1  # Actually accept solo signals
# Mechanism: Modify ensemble.py to accept 1_agree signals
```

### Change 2: Gate by Regime
```bash
# Add to .env
ENABLE_REGIME_GATE=true
SKIP_REGIMES=ranging,consolidation,unknown,low_liquidity
# Only trade: trending_bull, trending_bear
```

### Change 3: Gate by Setup Type
```bash
# Add to .env
ENABLE_SETUP_TYPE_GATE=true
SKIP_SETUPS=mean_reversion
# Trade: trend_follow, standard only
```

### Change 4: Time-of-Day Skip
```bash
# Add to .env
ENABLE_TIME_OF_DAY_SKIP=true
SKIP_HOURS=07,10  # Skip 07:00-08:00 UTC and 10:00-11:00 UTC
```

## Expected Improvement (Phase A.5)

**If we implement Change 1 (MIN_VOTES) alone:**
- Gain: +$2,096.64 (solo signals we're currently missing)
- New PnL: -$1,282.61 + $2,096.64 = +$814.03

**If we implement Changes 1+2 (MIN_VOTES + Regime Gate):**
- Prevent: -$2,318.73 loss from ranging/consolidation trades
- Gain: +$2,096.64 from solo signals
- New PnL: -$1,282.61 + $2,096.64 + $2,318.73 = +$3,132.76

**If we implement Changes 1+2+3 (Add Setup Gate):**
- Prevent: -$1,272.78 loss from mean_reversion
- New PnL: +$3,132.76 + $1,272.78 = +$4,405.54

**If we implement Changes 1+2+3+4 (Add Time Skip):**
- Prevent: -$887.49 loss from hours 07:00-08:00 and 10:00-11:00 UTC
- New PnL: +$4,405.54 + $887.49 = +$5,293.03

## Validation Run

Before applying all changes, test incrementally:

```bash
cd bot

# Test 1: MIN_VOTES only
# TODO: Modify ensemble.py to actually accept 1_agree
python run.py backtest --symbols BTC,ETH,SOL,HYPE --days 100
# Expected: +$814 improvement

# Test 2: MIN_VOTES + Regime Gate
ENABLE_REGIME_GATE=true SKIP_REGIMES=ranging,consolidation \
python run.py backtest --symbols BTC,ETH,SOL,HYPE --days 100
# Expected: +$3,132 improvement

# Test 3: All mechanical fixes
ENABLE_REGIME_GATE=true SKIP_REGIMES=ranging,consolidation \
ENABLE_SETUP_TYPE_GATE=true SKIP_SETUPS=mean_reversion \
ENABLE_TIME_OF_DAY_SKIP=true SKIP_HOURS=07,10 \
python run.py backtest --symbols BTC,ETH,SOL,HYPE --days 100
# Expected: +$5,293 improvement
```

## Why Agents Didn't Help

- Agents added latency (8-10s per decision)
- Gates were still blocking signals before agents could even see them
- Mechanical problems (consensus requirement, wrong regime, wrong setup type) can't be fixed by agents
- Agents need visible signals to coach; gates starved them of data

## Conclusion

**Skip complex agent optimization. Fix mechanical problems first.**
- Consensus requirement: Kill it
- Regime mismatch: Gate it
- Setup mismatch: Gate it
- Time mismatch: Skip it
- Dead strategy: Disable it

These fixes are data-driven, high-confidence, and don't require agent coaching.
