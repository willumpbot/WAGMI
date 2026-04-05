# Deep Signal Analysis — 1,410 Signals, 7 Dimensions

## 1. CONFLUENCE: BB Solo > BB+Others

| Pattern | n | WR | Avg Move | VERDICT |
|---------|---|-----|----------|---------|
| **1-agree+BB (solo BB)** | 196 | **62%** | **+0.28%** | **BEST PATTERN** |
| 2-agree+BB | 150 | 52% | +0.02% | Diluted by partner |
| 1-agree_noBB | 687 | 45% | -0.12% | Losing |
| 3-agree+BB | 4 | 25% | -0.59% | Too rare + loses |

**CRITICAL INSIGHT: Solo BB signals (62% WR) outperform 2-agree+BB (52% WR).**
Adding a second strategy to BB actually HURTS performance. The confidence_scorer
"confirmation" is noise that dilutes BB's edge. BB works BEST alone.

This contradicts our entire consensus architecture. The 2-agree requirement
is filtering OUT the best signals (solo BB) and letting in worse ones.

## 2. SEQUENTIAL PATTERNS: Momentum is real

| Symbol | After WIN | After LOSS |
|--------|-----------|------------|
| BTC | **69% WR, +0.23%** | 34% WR, -0.30% |
| ETH | **68% WR, +0.37%** | 35% WR, -0.23% |
| SOL | **69% WR, +0.40%** | 33% WR, -0.41% |
| HYPE | **69% WR, +0.45%** | 25% WR, -0.63% |

**MASSIVE FINDING: After a winning signal, the NEXT signal has ~69% WR.**
After a losing signal, next signal has ~33% WR. This is a 2:1 edge.

Implication: The system should SIZE UP after wins and SIZE DOWN or SKIP after losses.
This is the anti-martingale principle, but the data proves it works with 35 point spread.

## 3. BB STOP WIDTH: Tighter = Better

| Stop Width | n | WR | Avg Move |
|-----------|---|-----|----------|
| <0.5% | 6 | **83%** | +0.10% |
| 0.5-1.0% | 55 | 56% | +0.28% |
| 1.0-1.5% | 115 | 57% | +0.12% |
| >1.5% | 209 | 57% | +0.14% |

BB signals with tighter stops (0.5-1.0%) have the best risk-adjusted return (+0.28%/trade).
The very tight (<0.5%) are too small a sample but 83% WR is notable.

## 4. OPTIMAL HOLD TIME PER SETUP

### ETH_SELL_BB (best setup, 70% WR)
| Horizon | WR | Avg Move |
|---------|-----|----------|
| 1h | 62% | +0.23% |
| 2h | 58% | +0.40% |
| **4h** | **70%** | **+0.81%** |
| **8h** | **70%** | **+1.38%** |
| 12h | 66% | +1.43% |

Peaks at 4-8h. After 8h, WR starts declining (66% at 12h).

### BTC_SELL_BB (61% WR)
| Horizon | WR | Avg Move |
|---------|-----|----------|
| 4h | 61% | +0.24% |
| **8h** | **63%** | **+0.41%** |
| 12h | 54% | +0.21% |

Peaks at 8h. 12h overhold kills the edge.

### BTC_BUY_BB (69% WR)
| Horizon | WR | Avg Move |
|---------|-----|----------|
| 1h | 38% | +0.01% |
| **4h** | **69%** | **+0.06%** |
| **8h** | **69%** | **+0.11%** |
| 12h | 69% | +0.12% |

Needs 4h+ to develop. DON'T cut early.

### SOL_BUY_BB (67% WR)
| Horizon | WR | Avg Move |
|---------|-----|----------|
| **4h** | **67%** | **+0.36%** |
| 8h | 58% | +0.35% |
| 12h | 54% | -0.00% |

Peaks at 4h, decays after. Take profit by 8h.

## 5. MFE/MAE (How far moves actually go in 4h)

| Symbol | Median MFE | p75 MFE | Median MAE | p25 MAE |
|--------|-----------|---------|-----------|---------|
| BTC | +0.46% | +0.92% | -0.48% | -0.90% |
| ETH | +0.60% | +1.26% | -0.50% | -1.10% |
| SOL | +0.69% | +1.27% | -0.63% | -1.23% |
| HYPE | +0.90% | +1.44% | -1.00% | -1.78% |

**Optimal SL/TP from this data:**
- SL should be at p75 MAE (only 25% of trades reach this adverse level)
- TP1 should be at median MFE (reachable 50% of the time)

| Symbol | Optimal SL | Optimal TP1 | R:R |
|--------|-----------|-------------|-----|
| BTC | 0.90% | 0.46% | 0.51:1 |
| ETH | 1.10% | 0.60% | 0.55:1 |
| SOL | 1.23% | 0.69% | 0.56:1 |
| HYPE | 1.78% | 0.90% | 0.51:1 |

Note: R:R < 1.0 is fine when WR > 55% (which BB achieves).

## 6. THE ULTIMATE AGENT FRAMEWORK

Based on ALL findings:

### ENTRY RULES
1. **Primary**: Take BB signals, especially golden setups (ETH_SELL, BTC_BUY, SOL_BUY)
2. **Solo BB > 2-agree**: Don't require consensus for BB (it dilutes the edge)
3. **After a win**: Next signal has 69% WR — take it at full or 1.2x size
4. **After a loss**: Next signal has 33% WR — skip or 0.3x size
5. **high_volatility regime**: Genuine edge (55% WR) — boost size

### EXIT RULES
6. **ETH_SELL_BB**: Hold 4-8h, then tighten. Peak edge at 4h.
7. **BTC_SELL_BB**: Hold 8h max. 12h overhold kills edge.
8. **BTC_BUY_BB**: Needs 4h minimum to develop. Don't cut early.
9. **SOL_BUY_BB**: Take profit by 4-8h. Decays after.

### SKIP RULES
10. **No BB involvement**: Skip or 0.3x size (45% WR, -0.12%/trade)
11. **HYPE_SELL_BB**: Always skip (35% WR, worst setup)
12. **HYPE_BUY_CS**: Always skip (38% WR)
13. **After consecutive losses**: Skip next signal (33% WR)
14. **confidence_scorer solo**: Skip (47% WR, negative EV)
