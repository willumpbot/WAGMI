# Setup Edge by Regime
*Generated: 2026-05-30 | Source: historical/old-bot-pre-2026-04-23/trades.csv | 228 trades*

---

## Regime Performance Overview

| Regime | Trades | Win Rate | PnL | Avg PnL/Trade | Verdict |
|---|---|---|---|---|---|
| trending | 27 | **48.1%** | +$25.41 | +$0.94 | ✅ Trade here |
| (no regime tagged) | 59 | 30.5% | -$1,239.60 | -$21.01 | ⚠️ Borderline |
| illiquid | 110 | 23.6% | -$1,865.95 | -$16.96 | ❌ High caution |
| ranging | 32 | 15.6% | -$634.85 | -$19.84 | ❌ Avoid |

---

## TRENDING Regime — Trade Here

**27 trades, 48.1% WR, +$25.41 total**

### What Works in Trending

| Setup | Trades | Win Rate | PnL |
|---|---|---|---|
| ETH LONG + ensemble | 7 | 57% | +$13.89 |
| SOL LONG + ensemble | 4 | 25% | +$5.97 |
| BTC LONG + ensemble | 4 | 50% | -$10.05 |
| HYPE LONG + ensemble | 7 | 29% | -$16.85 |

**Profitable sub-setups:**
- ETH LONG trending: consistent winner (57% WR, positive PnL)
- Following the trend direction (LONG in trending) works better than counter-trend

**Avoid in trending:**
- HYPE LONG in trending: 29% WR, consistent loser
- BTC LONG in trending: breakeven but not worth it

### Trading Rules for Trending Regime
1. ETH/SOL LONG is the primary play
2. Avoid HYPE LONG (29% WR even in trending)
3. BTC LONG is borderline — LLM should require high conviction (>70 confidence)
4. SHORT setups in trending regime: low sample size, inconclusive

---

## ILLIQUID Regime — High Caution

**110 trades (largest bucket), 23.6% WR, -$1,865.95**

The majority of all trading happened in illiquid regime. The majority of all losses happened here too.

### What Works in Illiquid (the hidden gems)

| Setup | Trades | Win Rate | PnL | Notes |
|---|---|---|---|---|
| ETH SHORT + ensemble | 6 | **83%** | +$568.63 | Best setup in entire dataset |
| BTC SHORT + ensemble | 6 | 50% | +$176.79 | Real edge |
| SOL SHORT + ensemble | 7 | 57% | +$19.15 | Marginal but positive |

**ETH SHORT in illiquid regime is the highest-alpha setup in the entire 8-month dataset.** 83% WR, $94 average win, only 6 samples (all from May 7 cluster). The new bot should treat this as a confirmed shadow EDGE.

### What Destroys Value in Illiquid

| Setup | Trades | Win Rate | PnL |
|---|---|---|---|
| ETH SHORT + omniscient | 12 | 17% | -$895.53 |
| ETH LONG + ensemble | 13 | 15% | -$1,114.05 |
| SOL LONG + ensemble | 14 | 36% | -$325.03 |
| HYPE LONG + ensemble | 16 | 6% | -$60.50 |
| BTC LONG + ensemble | 12 | 25% | -$168.44 |

**LONG positions in illiquid regime** are consistently losing. Illiquid = directional uncertainty. Going LONG in directional uncertainty = fade the move.

### Trading Rules for Illiquid Regime
1. **ETH SHORT = highest-priority target** (83% WR confirmed)
2. BTC SHORT = secondary opportunity (50% WR, worthwhile)
3. All LONG positions = avoid unless exceptional LLM conviction
4. Never use omniscient_integrated here (17% WR vs ensemble's 83%)

---

## RANGING Regime — Avoid

**32 trades, 15.6% WR, -$634.85**

This is a systematic loser across all setups.

| Setup | Trades | Win Rate | PnL |
|---|---|---|---|
| BTC SHORT + omniscient | 5 | 0% | -$8.45 |
| ETH SHORT + omniscient | 7 | 14% | -$564.42 |
| ETH LONG + ensemble | 4 | 25% | -$5.18 |
| HYPE LONG + ensemble | 8 | 12% | -$30.11 |
| SOL LONG + ensemble | 4 | 25% | -$15.15 |

No setup is profitable in ranging regime. This makes intuitive sense: ranging = oscillation, no sustained directional momentum, stops get hit at support/resistance edges.

### Trading Rules for Ranging Regime
- **Skip all signals.** There is no profitable setup in ranging regime in 8 months of data.
- If the LLM wants to trade in ranging, require >80 confidence AND trailing exit configured.
- The paper trading report had `ranging_regime_penalize_v1` gate=50% — should be 100% skip or LLM-only with very high bar.

---

## NO REGIME TAG — Borderline

**59 trades, 30.5% WR, -$1,239.60**

These are trades where the regime classification was empty/missing. Mixed bag — contains both the ETH SHORT 100% WR cluster and many losses.

### Breakdown
- ETH SHORT + ensemble (no regime): 3 trades, **100% WR**, +$310.40 — the May 7 cluster subset
- ETH LONG + ensemble (no regime): 7 trades, 14% WR, -$540.48 — consistent loser
- SOL LONG + ensemble (no regime): 7 trades, 14% WR, -$336.10 — consistent loser

The "no regime" bucket is being dragged down by LONG positions. If regime is unknown, the default should be SHORT bias or flat.

---

## Regime-Based Decision Matrix for New Bot

```
REGIME          RECOMMENDATION          EXAMPLES THAT WORK
trending    →   ETH/SOL LONG OK        ETH LONG trending: 57% WR
                HIGH bar for HYPE      HYPE LONG trending: only 29% WR

illiquid    →   ETH SHORT FIRST        ETH SHORT illiquid: 83% WR  
                BTC SHORT SECOND       BTC SHORT illiquid: 50% WR
                ALL LONGS: LLM veto    ETH LONG illiquid: 15% WR

ranging     →   FLAT. Full stop.       No profitable setup found.
                LLM must override      Require confidence >80 to override.

unknown     →   SHORT bias or flat     ETH SHORT: worked. ETH LONG: 14% WR.
                Avoid LONG default     
```
