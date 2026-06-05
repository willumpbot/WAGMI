# Edge Finder — Historical Archive Analysis
*Generated: 2026-05-30 | Source: historical/old-bot-pre-2026-04-23/ | 228 trades, 2026-03-25 → 2026-05-11*

---

## Overall Performance

| Metric | Value |
|---|---|
| Total Trades | 228 |
| Win Rate | 27.2% (62W / 166L) |
| Gross PnL | -$3,714.99 |
| Total Fees | -$875.19 |
| Net PnL | **-$4,590.18** |
| Date Range | 2026-03-25 → 2026-05-11 (47 days) |

---

## Where the Money Was Made

### By Outcome
| Outcome | Count | PnL | Notes |
|---|---|---|---|
| TRAILING_WIN | 34 | **+$1,668.49** | Only category that made money |
| CLEAN_WIN | 25 | +$308.30 | Small wins |
| CLEAN_LOSS | 169 | -$5,691.78 | The drain |

**Key insight:** Without trailing stops, total PnL would be -$6,258. The trailing exit mechanism is the only alpha the old bot had.

---

## By Symbol

| Symbol | Trades | PnL | Win Rate |
|---|---|---|---|
| BTC | 55 | -$58.81 | 18.2% |
| ETH | 64 | **-$2,909.47** | 32.8% |
| HYPE | 46 | -$122.64 | 21.7% |
| SOL | 63 | -$624.07 | 33.3% |

**ETH is both the worst loser AND the best winner** — the April 26-27 omniscient disaster dragged ETH down, but May 7 ETH SHORT cluster produced the top 6 winning trades.

---

## By Strategy

| Strategy | Trades | PnL | Win Rate | Verdict |
|---|---|---|---|---|
| sniper_premium | 23 | +$48.05 | 34.8% | Only profitable strategy |
| ensemble | 157 | -$1,529.89 | 32.5% | Acceptable but underwater |
| omniscient_integrated | 47 | **-$2,155.16** | **6.4%** | CATASTROPHIC — eliminated |
| sniper_standard | 1 | -$77.99 | 0% | Insufficient sample |

**`omniscient_integrated` was the portfolio killer.** 47 trades, nearly all losses, all concentrated in April 26-27. This strategy does not belong in the new bot.

---

## By Regime

| Regime | Trades | PnL | Win Rate |
|---|---|---|---|
| trending | 27 | +$25.41 | **48.1%** |
| (no regime) | 59 | -$1,239.60 | 30.5% |
| illiquid | 110 | -$1,865.95 | 23.6% |
| ranging | 32 | -$634.85 | 15.6% |

**trending regime = only regime with positive PnL.** Illiquid was the highest-volume regime but 23.6% WR. Ranging was the worst.

---

## Symbol + Strategy + Regime Edge Map (min 3 samples)

*Ranked by avg PnL per trade*

| Setup | Trades | Win Rate | Avg PnL | Total PnL |
|---|---|---|---|---|
| ETH SHORT + ensemble + (no regime) | 3 | **100%** | +$103.47 | +$310.40 |
| ETH SHORT + ensemble + illiquid | 6 | **83%** | +$94.77 | +$568.63 |
| BTC SHORT + ensemble + illiquid | 6 | 50% | +$29.46 | +$176.79 |
| HYPE LONG + ensemble + (no regime) | 5 | 80% | +$3.77 | +$18.86 |
| SOL SHORT + ensemble + illiquid | 7 | 57% | +$2.74 | +$19.15 |
| SOL SHORT + sniper_premium + (no regime) | 23 | 35% | +$2.09 | +$48.05 |
| ETH LONG + ensemble + trending | 7 | 57% | +$1.98 | +$13.89 |
| SOL LONG + ensemble + trending | 4 | 25% | +$1.49 | +$5.97 |
| — BELOW ZERO — | | | | |
| HYPE SHORT + ensemble + illiquid | 3 | 33% | -$0.31 | -$0.93 |
| BTC SHORT + omniscient + ranging | 5 | 0% | -$1.69 | -$8.45 |
| HYPE LONG + ensemble + trending | 7 | 29% | -$2.41 | -$16.85 |
| BTC SHORT + omniscient + illiquid | 19 | **0%** | -$2.51 | -$47.65 |
| HYPE LONG + ensemble + ranging | 8 | 12% | -$3.76 | -$30.11 |
| HYPE LONG + ensemble + illiquid | 16 | 6% | -$3.78 | -$60.50 |
| SOL LONG + ensemble + ranging | 4 | 25% | -$3.79 | -$15.15 |
| BTC LONG + ensemble + illiquid | 12 | 25% | -$14.04 | -$168.44 |
| SOL LONG + ensemble + illiquid | 14 | 36% | -$23.22 | -$325.03 |
| SOL LONG + ensemble + (no regime) | 7 | 14% | -$48.01 | -$336.10 |
| ETH SHORT + omniscient + illiquid | 12 | 17% | -$74.63 | -$895.53 |
| ETH LONG + ensemble + (no regime) | 7 | 14% | -$77.21 | -$540.48 |
| ETH SHORT + omniscient + ranging | 7 | 14% | -$80.63 | -$564.42 |
| ETH LONG + ensemble + illiquid | 13 | 15% | -$85.70 | **-$1,114.05** |

---

## By Side

| Side | Trades | PnL | Win Rate |
|---|---|---|---|
| SHORT | 109 | -$1,017.96 | 30.3% |
| LONG | 119 | -$2,697.03 | 24.4% |

SHORTs outperform LONGs significantly. The period covered a bear-trending market.

---

## Recommendations for New Bot

1. **Never run `omniscient_integrated`** — 6.4% WR over 47 trades is not noise, it's structural failure
2. **ETH SHORT in illiquid regime** is a real shadow EDGE (83% WR, 6 trades, $568.63) — desktop-claude has confirmed keeping shadow edges
3. **Trending regime only** for new positions when LLM is uncertain
4. **Ranging regime = avoid** (15.6% WR, consistent loser)
5. **Trailing stop logic is the alpha** — preserve it, optimize it, don't simplify it
