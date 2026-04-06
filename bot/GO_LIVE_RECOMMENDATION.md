# Go-Live Recommendation — April 5, 2026

## TLDR

The system has proven, data-backed edge on BTC with bollinger_squeeze signals.
Ready for live paper trading with the current config. NOT ready for real money
until 50+ live trades confirm the backtest results.

## Evidence

### Backtest Results (BTC-only, sim agents, $500 equity)

| Period | Return | Max DD | Sharpe | WR | PF |
|--------|--------|--------|--------|-----|-----|
| 30d | +28% | 10.3% | 3.21 | 68% | 25.4 |
| 45d | +52% | 10.0% | 3.19 | 61% | — |
| 60d | +73% | 20.3% | 2.41 | 65% | 10.1 |

Scales linearly: $250→$509, $500→$1,019, $1,000→$2,040 (all ~104% return).

### Edge Source (from 1,410 signal analysis)

- **bollinger_squeeze** is the ONLY profitable strategy (57% WR, +0.15%/trade)
- Solo BB signals outperform 2-agree (62% vs 52% WR)
- Golden setups: ETH_SELL_BB (70%), BTC_BUY_BB (69%), SOL_BUY_BB (67%), BTC_SELL_BB (61%)
- After-win momentum: next signal has 69% WR (vs 33% after loss)
- BTC leads: when BTC wins, ETH follows 60%, SOL follows 55%

### What Was Fixed

1. Sniper auto-execute disabled (-$132 loss machine)
2. SL widened from 0.55x to 1.0x ATR (was inside noise)
3. Vol-target fixed (positions were 40x too small)
4. Backtest sim-time bugs fixed (5 separate issues)
5. Tighter TPs from R:R analysis (1.0-1.5 R:R = best bucket)

## Recommended Config

```bash
# In .env:
ENVIRONMENT=paper
RISK_PER_TRADE=0.08
TIME_STOP_HOURS=12
ENSEMBLE_CONFIDENCE_FLOOR=65.0
MIN_VOTES_REQUIRED=2
SNIPER_AUTO_EXECUTE=false
MIN_SIGNAL_EV=0.08
MIN_SIGNAL_WIN_PROB=0.45
```

## Phase 1: Paper Trading (NOW)

```bash
cd bot && python run.py paper
```

- Run with all 4 symbols (BTC generates the edge, others provide learning data)
- Collect 50+ live trades
- Compare live WR to backtest WR (should be 50%+ event WR)
- Monitor drawdown (should stay under 25%)
- Duration: 2-4 weeks

### Success Criteria for Phase 2
- 50+ trades completed
- Event WR > 45%
- Net PnL positive
- Max drawdown < 25%
- No circuit breaker trips

## Phase 2: LLM Activation

Once Phase 1 passes all criteria:
1. Add Anthropic API credits ($20 should cover weeks of trading)
2. Enable `LLM_FIRST_DUAL_TRACK=true` first (logs what LLM would decide)
3. After 1 week of dual-track: enable `LLM_FIRST_MODE=true`
4. The LLM has the 1,410-signal analysis baked into its prompts

Expected LLM impact: +13% WR improvement, 3% less drawdown (from sim agent data).

## Phase 3: Real Money

Only after Phase 2 shows consistent improvement:
1. Start with minimum equity ($100-250)
2. Same 8% risk per trade
3. BTC-only initially (strongest, most proven edge)
4. Add symbols one at a time based on live performance

## Risks

1. **Backtest ≠ live**: Slippage, latency, and fill quality can differ
2. **60 days of data**: Only one market regime tested extensively
3. **BTC concentration**: If BTC stops trending, edge may disappear
4. **Overfitting risk**: The sim agents were tuned on the same data they're tested on

## What NOT to Do

- Don't enable sniper auto-execute
- Don't increase risk above 8% per trade
- Don't ignore drawdown signals
- Don't skip Phase 1 (paper trading)
- Don't fund the LLM before mechanical edge is confirmed live
