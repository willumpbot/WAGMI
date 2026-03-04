# /setup-edge — Setup Type Profitability Analysis

## Description
Discover which setup types (confluence patterns) make money and which lose money. The statistical edge map that tells you: "trend_at_zone wins 72%, solo_regime_trend wins 48% — stop taking solo setups."

## Arguments
- `$ARGUMENTS` — Optional: "summary" (quick overview), "deep" (full breakdown), "by-regime" (edge per regime), "profitable" (only winning setups), "losers" (only losing setups)

## Workflow

### 1. Load Trade History with Setup Classification
- Read `bot/data/trades.csv` for all closed trades
- Read `bot/data/llm/decisions.jsonl` for decision notes containing setup= fields
- Match trades to decisions by symbol + timestamp
- Parse setup_type from decision notes (e.g., "setup=trend_at_zone")
- For trades without setup_type, infer from strategy combination:
  - regime_trend + monte_carlo → trend_at_zone
  - regime_trend + multi_tier → trend_micro_entry
  - monte_carlo + confidence_scorer → zone_validated
  - etc. (see `bot/llm/agents/shared_context.py:_classify_setup()`)

### 2. Edge Analysis Per Setup Type
For each setup type, calculate:

**Win Rate & PnL:**
- Total trades, wins, losses
- Win rate %
- Average win size ($), average loss size ($)
- Expectancy = (WR × avg_win) - ((1-WR) × avg_loss)
- Profit factor = total_wins / total_losses
- Total PnL contribution

**Quality Metrics:**
- Average R-multiple (reward / risk)
- Average hold time (minutes)
- Average funding cost per trade
- Average confluence quality score
- Best regime for this setup
- Worst regime for this setup

### 3. Setup Type Leaderboard
Rank all setup types by expectancy (profit per trade):

```
╔══════════════════════════════════════════════════════════════════╗
║  SETUP TYPE EDGE MAP — Ranked by Expectancy                    ║
╠══════════════════════════════════════════════════════════════════╣
║  #1  trend_at_zone         WR: 72%  Exp: +$18.40  n=45  ★★★  ║
║  #2  full_confluence_trend  WR: 81%  Exp: +$22.10  n=12  ★★★  ║
║  #3  trend_micro_entry     WR: 64%  Exp: +$11.20  n=38  ★★   ║
║  #4  zone_validated        WR: 58%  Exp: +$4.30   n=67  ★    ║
║  #5  validated_scalp       WR: 55%  Exp: +$2.10   n=23  ★    ║
║  ── BREAKEVEN LINE ──────────────────────────────────────────  ║
║  #6  zone_momentum         WR: 49%  Exp: -$1.80   n=31  ✗    ║
║  #7  solo_regime_trend     WR: 44%  Exp: -$5.20   n=52  ✗✗   ║
║  #8  solo_monte_carlo      WR: 41%  Exp: -$8.10   n=28  ✗✗✗  ║
╚══════════════════════════════════════════════════════════════════╝
```

### 4. Regime × Setup Heatmap
Cross-reference setup types with regimes:

| Setup \ Regime | trend | range | high_vol | panic |
|----------------|-------|-------|----------|-------|
| trend_at_zone | +$18 | -$12 | +$3 | n/a |
| zone_validated | -$5 | +$11 | +$2 | n/a |
| solo_regime_trend | +$8 | -$15 | -$9 | n/a |

Highlight: which setup works in which regime.

### 5. Actionable Recommendations

**Size Up (positive edge, high confidence):**
- Setup types with WR > 60% AND n > 20 AND expectancy > $5
- "trend_at_zone in trend regime: size up 1.5x — proven edge"

**Avoid (negative edge):**
- Setup types with WR < 50% AND n > 15
- "solo_regime_trend: AVOID — historically losing, WR=44%"

**Needs More Data (promising but small sample):**
- Setup types with WR > 55% but n < 15
- "full_confluence_trend: looks great (WR=81%) but only 12 trades — monitor"

**Regime-Specific Rules:**
- Setup types that work in one regime but fail in another
- "zone_validated: GREAT in range (WR=68%), TERRIBLE in trend (WR=35%) — only take in range"

### 6. Feed Back Into System
After analysis, suggest:
- Which setup types should get higher confidence from the Trade Agent
- Which should get automatic skip/reduce from the Critic
- Propose hypotheses for the hypothesis tracker based on findings
- Update deep memory with validated setup type win rates

### 7. Output
Present clean report with:
- Leaderboard table (sorted by expectancy)
- Top 3 money-makers with specific conditions
- Top 3 money-losers with recommendation to avoid
- Regime heatmap highlighting best regime for each setup
- Total PnL attribution: how much each setup type contributed
