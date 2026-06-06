# Trade Profitability Analysis — 2026-06-06
**Dataset:** 231 executed trades (2026-03-25 to 2026-05-07)

---

## Executive Summary

**CRITICAL FINDINGS:**
1. **omniscient_integrated is a pure killer**: 0% WR on 45 trades, -$1,534 PnL
2. **confidence_scorer is the only profit center**: 42.6% WR, +$338 PnL
3. **ETH is radioactive**: -$2,842 total loss (both LONG and SHORT)
4. **Trending regime is where the money is**: 50% WR with confidence_scorer at 69.2%

---

## Strategy Performance

### Win Rates (Primary Driver)
| Strategy | WR | Count | Total PnL | Avg PnL |
|----------|-----|-------|-----------|---------|
| confidence_scorer | 42.6% | 61 | +$338.20 | +$5.54 ✅ |
| bollinger_squeeze | 31.8% | 22 | -$54.08 | -$2.46 |
| regime_trend | 30.0% | 10 | -$34.88 | -$3.49 |
| multi_tier_quality | 17.6% | 17 | -$8.26 | -$0.49 |
| trend_breakout | 28.6% | 14 | -$1,024.86 | -$73.20 ❌ |
| **omniscient_integrated** | **0.0%** | **45** | **-$1,534.44** | **-$34.10** | ❌❌❌ |
| funding_rate | 0.0% | 1 | -$1.88 | -$1.88 |
| probability_engine | 0.0% | 1 | -$0.48 | -$0.48 |

**Key Insight:** Only confidence_scorer is profitable. omniscient_integrated and trend_breakout are major loss drivers.

---

## Regime Performance

### Win Rates by Regime
| Regime | WR | Count | Total PnL | Avg PnL |
|--------|-----|-------|-----------|---------|
| **trending** | **50.0%** | 28 | +$92.86 | +$3.32 ✅ |
| illiquid | 22.5% | 111 | -$1,778.69 | -$16.02 ❌ |
| unknown | 30.0% | 60 | -$1,303.58 | -$21.73 ❌ |
| ranging | 12.5% | 32 | -$634.85 | -$19.84 ❌ |

**Key Insight:** ONLY trending regime is profitable. illiquid/ranging/unknown are loss zones.

---

## Regime × Strategy Matrix (PnL)

### TRENDING (Best Regime)
| Strategy | WR | Count | PnL |
|----------|-----|-------|-----|
| confidence_scorer | **69.2%** | 13 | **+$118.29** ✅ |
| multi_tier_quality | 20.0% | 5 | -$16.80 |
| **Result:** confidence_scorer in trending = gold mine (69% WR) |

### ILLIQUID (Loss Zone)
| Strategy | WR | Count | PnL |
|----------|-----|-------|-----|
| omniscient_integrated | 0.0% | 33 | -$961.57 ❌ |
| confidence_scorer | 38.5% | 39 | +$209.83 ✅ |
| multi_tier_quality | 22.2% | 9 | +$34.26 |
| **Result:** omniscient_integrated is a killer; confidence_scorer salvages it |

### RANGING (Loss Zone)
| Strategy | WR | Count | PnL |
|----------|-----|-------|-----|
| omniscient_integrated | 0.0% | 12 | -$572.87 ❌ |
| confidence_scorer | 22.2% | 9 | +$10.08 |
| multi_tier_quality | 0.0% | 3 | -$25.72 |

---

## Symbol Performance

### Win Rates by Symbol
| Symbol | WR | Count | Total PnL | Avg PnL |
|--------|-----|-------|-----------|---------|
| **BTC** | **19.6%** | 56 | **+$28.45** | +$0.51 ✅ |
| **SOL** | **32.8%** | 64 | **-$688.05** | -$10.75 |
| HYPE | 21.7% | 46 | -$122.64 | -$2.67 |
| **ETH** | **12.1%** | **65** | **-$2,842.02** | **-$43.72** ❌❌❌ |

**Critical:** ETH is a consistent loser (-$2,842), both LONG and SHORT.

### Symbol × Side Breakdown
| Setup | PnL | WR | Count |
|-------|-----|-----|-------|
| **BTC SHORT** | **+$224.37** | **16.7%** | 36 ✅ |
| BTC LONG | -$195.92 | 25.0% | 20 |
| SOL SHORT | -$17.74 | 37.1% | 35 |
| SOL LONG | -$670.31 | 27.6% | 29 |
| **ETH LONG** | **-$1,723.81** | **25.0%** | 32 ❌ |
| **ETH SHORT** | **-$1,118.21** | **33.3%** | 33 ❌ |
| HYPE LONG | -$106.99 | 21.1% | 38 |
| HYPE SHORT | -$15.65 | 25.0% | 8 |

**Key Insight:** Only BTC SHORT is profitable.

---

## Confidence Calibration

**Confidence in actual outcomes:**
- Avg confidence in **WINS**: 61.2%
- Avg confidence in **LOSSES**: 55.3%
- **Problem:** Poor differentiation (only 5.9% gap)
- **Implication:** Confidence scoring needs recalibration

---

## Immediate Actions

### 🔴 CRITICAL (Do Now)
1. **Remove/disable omniscient_integrated** — 0% WR, -$1,534 killer
   - 45 consecutive losses across 3 regimes
   - Specific impact: -$961 in illiquid, -$572 in ranging
   
2. **Reduce ETH trading or add symbol-level guard**
   - Both LONG and SHORT lose money consistently
   - -$2,842 total = 36% of all losses
   - This is not unlucky — pattern is consistent

### 🟡 HIGH PRIORITY (Next)
3. **Boost confidence_scorer weight** in ensemble
   - Only profitable primary driver
   - 69.2% WR in trending + confidence_scorer combo
   - Currently underweighted vs killers like omniscient_integrated

4. **Reduce trend_breakout weight**
   - 28.6% WR, -$1,024 PnL
   - Concentrated losses, not random

5. **Recalibrate confidence scoring**
   - Gap between win/loss confidence too small (5.9%)
   - Need wider separation for better filtering

### 🟢 MEDIUM PRIORITY
6. **Focus on trending regime detection**
   - This is where 50% WR is possible
   - Current regime detection probably too conservative
   - Other regimes (illiquid/ranging) are loss zones

7. **Monitor BTC SHORT as core trade**
   - Only consistently profitable setup (+$224)
   - Currently 16.7% WR but only 36 trades
   - Increase focus in trending BTC environments

---

## Data Quality Notes

- **Timeframe:** 231 trades over 6 weeks (2026-03-25 to 2026-05-07)
- **Coverage:** 4 symbols × 2 sides × 8 strategies (partial)
- **Completeness:** Primary_driver field populated for all trades
- **Regime field:** Some unknown values, but main categories clear
- **Confidence field:** Present for all, but calibration issues noted

---

## Hypothesis for Next Investigation

**Why is omniscient_integrated 100% wrong?**
- Possibly an older/deprecated strategy still in rotation
- Or a feature vector that's orthogonal to market reality
- Or correlation drift since training data

**Why is ETH so toxic?**
- Specific to this exchange/pair?
- Timeframe selection issue (5m signals in 6h markets)?
- Leverage/sizing problems on this symbol?
- Regulatory/news bias?

**Why is confidence_scorer the only winner?**
- Simpler signal = less overfitting?
- Better ensemble in its own right?
- Naturally hedge against other strategies?
