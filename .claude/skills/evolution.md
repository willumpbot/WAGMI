# /evolution — Strategy Evolution Summary

## Description
Generate a comprehensive strategy evolution report showing what's working, what's degrading, and what to adjust. Combines performance data, regime analysis, and LLM insights.

## Arguments
- `$ARGUMENTS` — Optional: time range ("24h", "7d", "30d") or "full"

## Workflow

### 1. Run Evolution Report
```bash
cd bot && python cli.py --mode evolve
```
Capture the full output.

### 2. Parse Performance Data
Read trade data and compute:

**Overall Metrics (by time window):**
| Period | Trades | Win Rate | Avg R | Sharpe | PnL |
|--------|--------|----------|-------|--------|-----|
| 24h    |        |          |       |        |     |
| 7d     |        |          |       |        |     |
| 30d    |        |          |       |        |     |

**Per-Strategy Performance:**
- Each of 4 strategies: win rate, avg R, PnL contribution
- Strategy weight trajectory (are weights shifting?)
- Which strategy is improving? Which is degrading?

**Per-Regime Performance:**
- Win rate by regime (trend/range/panic/high_vol/low_liq)
- Which regime is the bot best at? Worst at?
- Current regime vs historical performance in this regime

### 3. Edge Attribution
Answer the key questions:
- **WHERE is the edge?** (symbol? regime? strategy? time of day?)
- **HOW is it changing?** (improving, stable, or degrading over 7d/30d?)
- **WHAT should change?** (parameter tweaks, strategy emphasis, regime filters)

### 4. LLM Agent Performance (if multi-agent enabled)
- Read agent decision history from `bot/data/llm/decisions.jsonl`
- Regime Agent accuracy: classified regime vs what actually happened
- Trade Agent accuracy: go/skip/flip decisions vs outcomes
- Critic Agent value: did vetoes save money? did approvals make money?
- Learning Agent utility: are stored lessons being applied?

### 5. Risk Analysis
- Drawdown trajectory: improving or worsening?
- Circuit breaker activations: how often? justified?
- Position sizing efficiency: are we risking too much on low-quality signals?
- Leverage distribution: are we using appropriate leverage?

### 6. Trend Detection
Flag significant changes:
- Win rate shifted >5pp in last 7d vs 30d average
- Average R-multiple changed >0.3R
- Strategy weight changed >10%
- New regime dominance (market shifted from trending to ranging)

### 7. Actionable Report
```
STRATEGY EVOLUTION — <date range>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EDGE MAP:
  Primary edge:   regime_trend in trending markets (+1.8R avg)
  Secondary edge:  monte_carlo at support zones (+1.2R avg)
  Weak spot:       All strategies in 'range' regime (-0.3R avg)

TRAJECTORY:
  ↑ Win rate improving (52% → 58% over 7d)
  → Avg R stable (1.4R → 1.3R, within noise)
  ↓ Drawdown worsening (-3% → -5% over 7d)

TOP 3 ACTIONS:
  1. Reduce position size in 'range' regime (negative EV)
  2. Increase regime_trend weight (outperforming by 2x)
  3. Tighten SL in high_volatility (too many full SL hits)

AGENT INSIGHTS:
  Regime Agent: 78% accurate (good)
  Trade Agent: 62% directionally correct (needs work)
  Critic vetoed 3 trades — 2 would have been losses (valuable)
```
