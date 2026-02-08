# Mico API - Production Backend

**Crisp, production-grade FastAPI backend** for the NunuIRL trading platform. Website-only, observational signals (no BUY/SELL language).

## Architecture

```
api/
├── app/
│   ├── config.py              # Pydantic Settings (env-first)
│   ├── deps.py                # Dependency injection & lifespan
│   ├── main_v2.py             # FastAPI app entry point
│   ├── models/
│   │   └── dto.py             # Pydantic response models (strict)
│   ├── routes/
│   │   ├── signals_v2.py      # GET /v1/signals
│   │   ├── summary_v2.py      # GET /v1/summary
│   │   └── strategies_v2.py   # GET /v1/strategies, logs, POST
│   └── services/
│       └── signals_v2.py      # Signal engine (fetch, compute, cache)
├── data/
│   ├── trades.json            # Last 100 trades
│   └── strategy_logs/         # Per-strategy JSONL logs
├── requirements.txt
├── Makefile
└── README_BACKEND.md
```

## API Contracts

### GET /v1/signals
**Returns:** Current market signals for BTC, SOL, PUMP

```json
{
  "last_updated": 1730789800,
  "regime": "Neutral",
  "signals": {
    "BTC": {
      "label": "Accumulation",
      "score": 72,
      "market": "BTC",
      "price": 94250.50,
      "sma20": 93000.00,
      "sma50": 92000.00,
      "atr14": 1500.00,
      "rsi14": 58.7,
      "vol_spike": false,
      "atr_pct": 1.59,
      "zones": {
        "deepAccum": 91000.00,
        "accum": 91500.00,
        "distrib": 94500.00,
        "safeDistrib": 95000.00
      },
      "trend": {
        "sma20": "Up",
        "sma50": "Up",
        "rsi14": 58.7
      }
    }
  },
  "errors": []
}
```

### GET /v1/summary
**Returns:** Home page meta + most recent trade

```json
{
  "updatedAt": "2025-11-05T04:16:00Z",
  "regime": "Neutral",
  "status": "ok",
  "errors": 0,
  "mostRecentTrade": {
    "strategyId": "scalp-perp-15m",
    "name": "Scalp Perp (15m)",
    "market": "SOL",
    "action": "ACCUMULATION",
    "price": 182.34,
    "ts": "2025-11-05T04:15:00Z"
  }
}
```

### GET /v1/strategies
**Returns:** All strategies with latest signals

```json
{
  "items": [
    {
      "id": "scalp-perp-15m",
      "name": "Scalp Perp (15m)",
      "description": "15m scalp strategy",
      "category": "perp",
      "status": "Active",
      "markets": ["BTCUSDT", "ETHUSDT"],
      "lastEvaluated": "2025-11-05T04:16:00Z",
      "latestSignal": {
        "label": "Accumulation",
        "score": 72,
        "market": "BTC",
        ...
      }
    }
  ]
}
```

### GET /v1/strategies/{id}/logs?limit=50
**Returns:** Last N logs for strategy

```json
{
  "value": [
    {
      "ts": "2025-11-05T04:16:00Z",
      "event": "strategy_tick",
      "market": "SOL",
      "note": "score 72, label Accumulation",
      "score": 72,
      "details": null
    }
  ],
  "Count": 1
}
```

### POST /v1/strategies/{id}/logs
**Body:**
```json
{
  "event": "strategy_tick",
  "market": "SOL",
  "note": "Optional note",
  "score": 72,
  "details": {}
}
```

### POST /v1/trades
**Body:**
```json
{
  "strategyId": "scalp-perp-15m",
  "name": "Scalp Perp (15m)",
  "market": "SOL",
  "action": "ACCUMULATION",
  "price": 182.34
}
```

## Environment Variables

Create `.env` file:

```bash
# API Configuration
API_CACHE_TTL_SEC=60
API_ORIGINS=http://localhost:3000,https://nunuirl-platform.onrender.com

# CoinGecko
COINGECKO_BASE=https://api.coingecko.com/api/v3
COINGECKO_TIMEOUT_SEC=20

# Signal Engine
DISABLE_SIGNALS=0
SIGNAL_POLL_SECONDS=60

# Data Storage
DATA_DIR=/app/data
MAX_TRADES_KEPT=100
MAX_LOGS_RETURNED=50
```

## Running Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Run with hot reload
uvicorn app.main_v2:app --host 0.0.0.0 --port 8000 --reload

# Or use Makefile
make install
make run
```

**API will be available at:** http://localhost:8000
**Docs:** http://localhost:8000/docs

## Running with Docker

```bash
# Build
docker-compose -f ../infra/docker-compose.yml build api

# Start
docker-compose -f ../infra/docker-compose.yml up -d api

# Logs
docker logs nunuirl_api --tail 50 -f

# Stop
docker-compose -f ../infra/docker-compose.yml down
```

## Testing

```bash
# Run tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=app --cov-report=html

# Specific test
pytest tests/test_signals.py -v
```

## Code Quality

```bash
# Format
black app/ tests/
isort app/ tests/

# Lint
ruff check app/ tests/
mypy app/ --ignore-missing-imports

# All in one
make fmt && make lint
```

## Deployment (Render)

### Web Service Configuration

**Environment:**
- `PORT`: Auto-set by Render
- `API_ORIGINS`: Your frontend URL
- `DATA_DIR`: `/app/data`
- `DISABLE_SIGNALS`: `0`

**Build Command:**
```bash
pip install -r requirements.txt
```

**Start Command:**
```bash
uvicorn app.main_v2:app --host 0.0.0.0 --port $PORT --workers 2
```

**Health Check:**
```
/health
```

## Signal Engine

### How It Works

1. **Polling Loop:** Runs every 60s (configurable)
2. **Fetch:** Gets CoinGecko market_chart data (90 days)
3. **Compute:** Calculates SMA20/50, ATR14, RSI14, vol_spike
4. **Zones:** ATR-based bands (deepAccum, accum, distrib, safeDistrib)
5. **Label:** Assigns Observation/Accumulation/Distribution based on zones
6. **Score:** 0-100 blend of proximity, trend, RSI, volatility
7. **Cache:** Stores in app.state.cache, returns last good on failure

### Labels (Safe, Observational)

- **Aggressive Accumulation:** Price <= deep accumulation zone
- **Accumulation:** Price <= accumulation zone
- **Observation:** Price in neutral zone
- **Distribution:** Price >= distribution zone
- **Aggressive Distribution:** Price >= safe distribution zone

**Never uses BUY/SELL language.**

## Data Persistence

### trades.json
Stores last 100 trades in JSON format:
```json
[
  {
    "strategyId": "...",
    "name": "...",
    "market": "SOL",
    "action": "ACCUMULATION",
    "price": 182.34,
    "ts": "2025-11-05T04:15:00Z"
  }
]
```

### strategy_logs/{id}.jsonl
One JSON object per line (JSONL format):
```jsonl
{"ts":"2025-11-05T04:16:00Z","event":"strategy_tick","market":"SOL","note":"...","score":72}
{"ts":"2025-11-05T04:12:00Z","event":"signal_assessed","market":"SOL","note":"..."}
```

**Benefits:**
- Append-only (fast writes)
- Tail last N lines (fast reads)
- Resilient to corrupt lines (skip and continue)

## CORS Configuration

Allowed origins are configured via `API_ORIGINS` env var:

```python
# Development
API_ORIGINS=http://localhost:3000

# Production
API_ORIGINS=https://nunuirl-platform.onrender.com,https://mico-site.onrender.com
```

**IMPORTANT:** Frontend must set `NEXT_PUBLIC_API_URL` to backend URL.

## Status & Error Handling

### Status Values
- `ok`: All systems operational
- `degraded`: Some errors but functional (returns cached data)
- `paused`: Signals disabled

### Error Strategy
1. **Always return valid JSON** (never 500 HTML)
2. **Degrade gracefully** (use last good cache on upstream failure)
3. **Log errors** but don't expose internals to frontend
4. **Rate limit protection** with backoff on 429

## Performance

- **Cache TTL:** 60s (configurable)
- **aiohttp session:** Persistent connection pool
- **Concurrent limit:** 10 connections max
- **Response time:** <200ms (cached), <2s (cold)
- **Memory:** ~150MB (with pandas)

## Monitoring

### Health Checks
```bash
curl http://localhost:8000/health
```

### Metrics (Future)
- Prometheus `/metrics` endpoint
- Request duration histograms
- Upstream API latency
- Cache hit rate

## Security

- **CORS restricted** to allowed origins
- **No hardcoded secrets** (env only)
- **Input validation** via Pydantic
- **Request size limits** on POST routes
- **No auth required** (website-only, read-mostly)

## Troubleshooting

### Signals not updating
```bash
# Check logs
docker logs nunuirl_api --tail 50

# Verify CoinGecko reachable
curl https://api.coingecko.com/api/v3/ping

# Check cache status
curl http://localhost:8000/v1/summary
```

### CORS errors
1. Verify `API_ORIGINS` includes your frontend URL
2. Check browser Network tab for preflight requests
3. Ensure frontend uses correct API URL

### Data not persisting
```bash
# Check data directory exists
docker exec nunuirl_api ls -la /app/data

# Create manually if needed
docker exec nunuirl_api mkdir -p /app/data/strategy_logs
```

## Next Steps

- [ ] Add pytest test suite
- [ ] Add Prometheus metrics
- [ ] Implement WebSocket for real-time updates
- [ ] Add rate limiting (slowapi)
- [ ] Add structured logging (structlog)
- [ ] Add CI/CD pipeline (GitHub Actions)
- [ ] Add API authentication for POST routes
- [ ] Add request ID tracing

## Support

For issues or questions, see main project README or open a GitHub issue.
