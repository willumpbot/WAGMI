# Exit Optimization Analysis

**Date:** 2026-06-02  
**Author:** laptop-claude  
**Source data:** `bot/data/trades.csv` (228 trades, old bot pre-2026-04-23)

---

## Key Finding: SL Rate is the Core Problem, Not Exit Timing

228 old-bot trades:
- **83.3% hit SL (190 trades)** — avg loss $29.27/trade
- **16.7% hit TP1 then trail (38 trades)** — avg profit $48.60/trade
- **TIME_STOP not used** in old bot (state_path only shows IDLE→OPEN→CLOSED)

The problem is ENTRY QUALITY, not exit timing. A 83% SL rate means the edge was on the wrong side consistently.

---

## Entry Quality Breakdown (by strategy consensus)

| Num Agree | Trades | WR | PnL |
|-----------|--------|-----|-----|
| 0 (solo) | 59 | 31% | -$1,240 |
| 1 (solo) | 116 | 20% | -$2,608 |
| 2 (consensus) | 48 | **44%** | **+$190** |
| 3 (strong consensus) | 5 | 0% | -$57 |

**Critical:** 2-strategy consensus is the ONLY profitable bucket. Solo signals are money-losing on average. The current LLM bot's BOOST/PENALIZE rules for num_agree are validated here.

Note: n=5 for 3-agree is too small to draw conclusions (likely data-quality issue with old bot).

---

## Regime Performance

| Regime | Side | Trades | WR | Avg PnL |
|--------|------|--------|-----|---------|
| trending | LONG | 22 | 41% | -$0.32 |
| trending | SHORT | 5 | **80%** | +$6.49 |
| illiquid | LONG | 57 | 19% | -$29.59 |
| illiquid | SHORT | 53 | 28% | -$3.39 |
| ranging | LONG | 17 | 18% | -$3.03 |
| ranging | SHORT | 15 | 13% | -$38.89 |

**Critical:** Only "trending" regime has positive expected value. Illiquid and ranging regimes are net-negative. The current bot's regime awareness is validated — avoiding illiquid/ranging entries is essential.

---

## Exit Type PnL Contribution

| Exit Type | Trades | Avg PnL | Total PnL |
|-----------|--------|---------|-----------|
| TP1 hit | 38 | +$48.60 | +$1,847 |
| TP2 hit | 4 | +$44.57 | +$178 |
| SL hit | 190 | -$29.27 | -$5,562 |
| Trailing hit | 34 | +$49.07 | +$1,668 |

TP1 + Trailing = all profitable exits. SL = the loss engine.

**Exit timing is NOT the priority.** The priority is blocking bad entries (improving WR from 27% to 50%+). With LLM filtering and HYPE alpha (85-88% WR in US session), we're addressing this.

---

## TIME_STOP Analysis (LLM Bot Context)

The LLM bot (current) has TIME_STOP at 12h base. We've already improved this session:
- Changed max_extension from 4h to 8h for score≥75 positions (in `position_manager.py`)

From the brief: "BTC #4 time-stopped at 5h with +$77 when TP1 was just minutes away."
This implies TIME_STOP fired too early when TP1 was close. **Recommendation: check proximity to TP1 before firing TIME_STOP.**

### Proposed Enhancement: TP1-Proximity Check

Before firing TIME_STOP, check:
1. Is price within 0.3% of TP1? → extend 1 additional hour
2. Is unrealized PnL > 50% of TP1 profit? → extend by 30 min

This would have saved BTC #4 (TP1 just minutes away). Low implementation risk — just adds a condition to `position_manager.py:_check_time_stop()`.

---

## Recommendations

### Immediate (low risk)
1. ✅ Doubled TIME_STOP max extension (done this session, 4h→8h for score≥75)
2. **Add TP1-proximity check** before TIME_STOP fires — prevents leaving $75+ on table

### Medium term  
3. **Vol-adaptive trailing**: tighten trail in low ATR (<0.5%), loosen in high ATR (>2%)
4. **Regime-adaptive TIME_STOP**: shorter in range/illiquid (exit when thesis is wrong), longer in trending
5. **Win trail vs loss trail**: if unrealized PnL > 2x risk, use tighter trail; if PnL < 1x risk, standard trail

### Data gap
- No TIME_STOP records in old bot data (wasn't used)
- LLM bot has had some TIME_STOP exits per desktop brief
- Need desktop's new `bot/data/trades.csv` for TIME_STOP analysis
