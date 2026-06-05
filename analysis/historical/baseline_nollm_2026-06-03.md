# Baseline Non-LLM Backtest Results — 2026-06-03

## Context

Ran 4 parallel backtests without LLM filtering to establish raw strategy baseline.
All jobs used `--raw` (circuit breakers disabled) but no `--llm`.

**Important finding:** `--start-date` for pre-cache dates is a no-op. The CCXT fetcher
anchors `since_ms = time.time() - limit * tf_ms`, always returning the most recent N candles.
All 4 jobs ran on the cached Apr 2026 crash window (2026-03-20 to 2026-04-05).

---

## Results

| Job | Data Window | Trades | WR | Net PnL |
|-----|-------------|--------|----|---------|
| BTC:15:2025-10-15 | 2026-03-20 → 2026-04-05 | 2 | 0% | -$1,862 |
| BTC:15:2026-01-15 | 2026-03-20 → 2026-04-05 | 2 | 0% | -$1,862 |
| BTC:15:2026-03-15 | 2026-03-20 → 2026-04-05 | 3 | 0% | -$2,950 |
| ETH:15:2026-03-15 | 2026-03-20 → 2026-04-05 | 1 | 0% | -$647  |

Oct and Jan are identical (same cached data, same start_idx=warmup).

---

## Key Findings

### 1. Raw strategies lose money in crash window
0% WR across all 4 runs on the Apr 2026 crash window. Regime: trending_bear + ranging.
This validates that LLM filtering provides real value — the paper trading +$450 in same period
came from the LLM vetoing/sizing adjustments.

### 2. Confidence floor is blocking winners (critical)
From BTC Mar 2026 log:
- 41 signals missed, all blocked by `confidence_floor` (floor set at 66-71%)
- Gate accuracy: **35.7%** — only 35.7% of rejections were correct saves
- Net gate value: **-30.6%** — gates HURT more than they helped
- "LOOSEN — blocking too many winners"

The top missed: BTC BUY at 65-68% confidence → +3.77% to +5.88% gains blocked.

**Action item:** In trending_bear + ranging regimes on BTC, the confidence floor is set
too high. The raw signals at 65-68% confidence would have been winners. The adaptive
confidence floor needs more data to calibrate.

### 3. Few signals in crash window
Only 2-3 trades over 15 days. The ensemble (min_votes required) is highly selective.
With confidence_floor rejecting 38+ more, the bot is extremely conservative in crash conditions.

### 4. Only regime_trend strategy firing
Only `regime_trend` produced signals (2 regime types: trending_bear, ranging).
Other strategies (bollinger_squeeze, multi_tier_quality) not triggering.

---

## Bug: --start-date doesn't fetch historical data
`run.py backtest --start-date 2025-10-15` correctly marks which candles to skip in the loop
but the CCXT fetcher always fetches the most recent `limit` candles.

**Fix needed (future):** When `start_date` is provided, calculate:
```python
since_ms = int(pd.Timestamp(start_date).value / 1e6)  # start_date in ms
limit = int((days + warmup_days) * tf_candles_per_day)  # cover full window
```
This would enable true historical backtests on different market regimes.

---

## What This Means for LLM Backtests

When LLM quota resets, run on the cached Apr 2026 window to see LLM vs non-LLM delta.
Expected: LLM should achieve positive PnL by vetoing the 0% WR raw signals and sizing
down in crash conditions.

LLM backtest command (quota reset ~22:30 UTC):
```
python scripts/parallel_backtest.py \
  --jobs "BTC:15:2026-03-15" "ETH:15:2026-03-15" \
  --budget 4.0 --llm --raw
```
