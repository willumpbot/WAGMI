# /web-dashboard — Dashboard, API, and Monitoring Stack

## Description
Check, configure, and troubleshoot the web dashboard, REST API, health server, and monitoring infrastructure (Prometheus/Grafana). Ensures all web-facing systems are operational.

## Arguments
- `$ARGUMENTS` — Optional: "dashboard" (SPA + charts), "api" (FastAPI endpoints), "health" (health server), "monitoring" (Prometheus/Grafana), or "full"

## Workflow

### 1. Dashboard Status
Read `bot/dashboard/server.py`:

**Endpoints:**
- `GET /` — HTML dashboard (single-page app with charts)
- `GET /api/dashboard` — Full JSON metrics
- `GET /api/metrics` — Performance metrics
- `GET /api/trades` — Recent trades
- `GET /api/positions` — Open positions

**Check:**
- Is the dashboard server running? (`curl http://localhost:5000/`)
- Are API endpoints returning valid JSON?
- Is data fresh (not stale)?
- Are charts rendering correctly?

**Configuration:**
- Port: 5000 (default, configurable)
- Auto-refresh interval

### 2. REST API Status
Read `api/app/main.py` and route files:

**Endpoints:**
- `GET /health` — API health check
- `GET /v1/signals` — Current market signals
- `POST /v1/signals/run` — Force signal refresh (60s cache bypass)
- `POST /v1/events/trade` — Trade event ingestion
- `GET /metrics` — Prometheus metrics

**Check:**
- API responding? (`curl http://localhost:8000/health`)
- Signals endpoint working? (`curl http://localhost:8000/v1/signals`)
- Database connected? (PostgreSQL via DATABASE_URL)
- Metrics being scraped?

**Configuration:**
- `DATABASE_URL` — PostgreSQL connection
- `NUNUIRL_API_KEY` — API authentication

### 3. Health Server Status
Read `bot/monitoring/health_server.py`:

**Endpoints:**
- `GET /healthz` — Liveness (200 if bot loop running, 503 if stalled)
- `GET /readyz` — Readiness (200 if bot initialized)
- `GET /status` — Full JSON status

**Check:**
```bash
curl http://localhost:8081/healthz
curl http://localhost:8081/readyz
curl http://localhost:8081/status
```

**Verify:**
- Health server is bound and listening
- Heartbeat is being recorded (`bot/data/heartbeat.json`)
- Stall detection threshold is reasonable (default: 10 min)
- Status endpoint returns all expected fields

### 4. Watchdog Status
Read `bot/monitoring/watchdog.py`:

**Monitoring:**
- Main loop stall detection (threshold: `WATCHDOG_STALL_THRESHOLD_S`)
- Error rate monitoring (threshold: `WATCHDOG_ERROR_THRESHOLD`)
- Equity drawdown tracking (threshold: `WATCHDOG_DRAWDOWN_ALERT_PCT`)
- Exchange connectivity monitoring

**Check:**
- Is watchdog thread running?
- Current alert state
- Recent alerts triggered

### 5. Prometheus/Grafana Stack (if using Docker)
Read infrastructure files:

**Prometheus** (`infra/prometheus.yml`):
- Scrape targets: api:8000/metrics, copy-executor:9102/metrics
- Scrape interval: 5s
- Is Prometheus accessible at :9090?

**Alertmanager** (`infra/alertmanager.yml`):
- Webhook receiver: discord-relay:8081/alert
- Is it routing alerts to Discord?

**Grafana** (`infra/docker-compose.yml`):
- Is Grafana accessible at :3000?
- Are dashboards pre-provisioned?
- Data sources connected to Prometheus?

**Discord Relay** (`infra/discord_relay/app.py`):
- Flask endpoint: POST /alert
- Converts Prometheus alerts to Discord embeds

### 6. End-to-End Connectivity Test
Test the full monitoring chain:

```
Bot Loop → Heartbeat → Health Server → /healthz
Bot Error → Watchdog → AlertRouter → Discord/Telegram
API Request → FastAPI → /v1/signals → JSON
Prometheus → Scrape → Alert Rule → Alertmanager → Discord Relay → Discord
```

For each chain:
- Is data flowing?
- Are there bottlenecks or failures?
- What's the latency?

### 7. Security Check
- Health server: is it exposed only internally? (should not be public)
- API: is authentication required for write endpoints?
- Dashboard: is it behind authentication?
- Webhooks: are they using HTTPS?
- No secrets in any API responses

### 8. Report
```
WEB SYSTEMS STATUS — <timestamp>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DASHBOARD (port 5000)
  Status:       [RUNNING/DOWN]
  Last Data:    Xs ago
  Endpoints:    X/X responding

REST API (port 8000)
  Status:       [RUNNING/DOWN]
  Database:     [CONNECTED/ERROR]
  Endpoints:    X/X responding

HEALTH SERVER (port 8081)
  Status:       [RUNNING/DOWN]
  /healthz:     [200/503]
  /readyz:      [200/503]
  Heartbeat:    Xs ago

WATCHDOG
  Status:       [RUNNING/STOPPED]
  Alerts:       N triggered (24h)

PROMETHEUS/GRAFANA
  Prometheus:   [UP/DOWN] (port 9090)
  Grafana:      [UP/DOWN] (port 3000)
  Alertmanager: [UP/DOWN] (port 9093)
  Discord Relay:[UP/DOWN] (port 8081)

ISSUES FOUND: [List or "None"]
```
