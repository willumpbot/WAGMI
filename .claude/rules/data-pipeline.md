# Data Pipeline Rules

## Architecture
- `bot/data/fetcher.py` — Multi-exchange OHLCV data fetching via CCXT
- `bot/data/fetchers/` — Per-exchange fetcher implementations
- `bot/data/db.py` — SQLite persistence layer
- `bot/data/migrations.py` — Schema migrations
- `bot/data/strategy_weights.py` — Rolling strategy performance weights

## Data Requirements by Strategy
| Strategy | Timeframes Needed | Data Source |
|---|---|---|
| regime_trend | 1h, 6h | CCXT (Hyperliquid) |
| monte_carlo_zones | daily | CCXT |
| multi_tier_quality | 5m, 1h | CCXT |
| confidence_scorer | varies | CCXT |

## Rules
- NEVER assume all timeframes are available — strategies must handle missing data
- Data freshness: if last candle is >5 minutes old, flag as stale
- Exchange API calls MUST have retry logic (exponential backoff)
- NEVER store API keys in code or data files
- SQLite migrations must be backwards-compatible
- Strategy weights should decay exponentially (recent trades weighted more)
- `decisions.jsonl` is append-only — never truncate in production
- Memory files (`llm_memory.json`, `deep_memory/`) are critical — handle write errors gracefully
