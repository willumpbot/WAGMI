# Infrastructure Reshape Plan — 2026-04-29

**Companion to:** `03_web_page_audit.md`
**Scope:** the three competing backends + how the bot writes data + how the frontend reads it.

---

## Current State (the mess)

Three backends exist. Each was built at a different point in the project's life. Nothing was officially deprecated, so all three still run.

### Backend 1 — `bot/api_server.py` (FastAPI, 1,726 lines) ✅ The de facto winner

- **~36 endpoints**, all under `/v1/*` prefix
- Reads directly from bot's local data files: `trades.csv`, `position_state.json`, `decisions.jsonl`, `signal_outcomes.jsonl`, etc.
- No database, no auth, no middleware
- Started by `cd bot && python api_server.py` (port 8000)
- **This is what the frontend mostly hits.** Page audit confirmed this for backtest, results, llm-audit, signals, copy-trade, forensics, thesis.
- Endpoint coverage:
  - Trades: `/v1/trades/history`, `/v1/trades/equity-curve`
  - Strategies: `/v1/strategies`
  - LLM: `/v1/llm/market-view`, `/v1/llm/feed`, `/v1/reasoning/feed`, `/v1/reasoning/pipeline/{id}`
  - Positions/account: `/v1/positions`, `/v1/account`
  - Agents: `/v1/agents/overview`, `/v1/agents/team/calibration`, `/v1/agents/debate/history`, `/v1/agents/{name}/performance`, `/v1/agents/{name}/calibration`, `/v1/agents/health`
  - Signals: `/v1/signals`, `/v1/signals/funnel`, `/v1/signals/funnel/cost`, `/v1/ohlcv`
  - Sniper: `/v1/sniper/recent`
  - Summary: `/v1/summary`
  - Backtest: `/v1/backtest/results`, `/v1/backtest/results/latest`, `/v1/backtest/results/{run_id}`, `/v1/backtest/runs`
  - Forensics: `/v1/forensics/analysis`
  - Copy: `/v1/copy/status`
  - Portfolio: `/v1/portfolio/allocation`
  - Performance: `/v1/performance/metrics`
  - Activity: `/v1/activity/feed`
  - Counterfactuals: `/v1/counterfactuals/resolved`
  - Thesis: `/v1/thesis/list`, `/v1/thesis/{symbol}`, `/v1/thesis/{symbol}/thread`, `/v1/thesis/accuracy`
  - Trade detail: `/v1/trade/{trade_id}/trail`

### Backend 2 — `api/app/` (FastAPI, Postgres, multi-file) ⚠️ The half-built alternative

- Title still `"NunuIRL API"` (not WAGMI — old branding leak)
- Postgres-backed (`Base.metadata.create_all`, retry-on-startup logic)
- Middleware: request-id, metrics, CORS, structured logging
- Has POST ingest endpoints: `/ingest/trade`, `/ingest/position`, `/ingest/pnl`, `/ingest/heartbeat`
- Background signal refresh loop on startup
- Has `auth.py` (mostly empty per earlier inventory — `config.py`, `deps.py`, `main_v2.py` are zero-byte stubs)
- Routes overlap heavily with `bot/api_server.py`: activity feed, agents overview, backtest results, llm feed, summary, trades — same endpoints, different implementations
- Has unique routes: edge (setup-types, regimes, strategies, symbols, summary), copy (subscribe, executions), sniper (queue/approve/reject), strategies CRUD (read.py)
- The `routes/` subdirectory contains only partial v2 migrations (`signals_v2.py`, `strategies_v2.py`, `summary_v2.py`)

### Backend 3 — `bot/dashboard/server.py` (Flask, 9,628 lines) 🪦 Legacy

- Single-file Flask server, ~9.6KLOC
- Older API surface
- Has `_compute_metrics`, `_read_trade_events`, `_get_recent_signals` helpers
- Probably the original dashboard, partially superseded by `bot/api_server.py`
- No evidence the frontend uses it — the page audit didn't surface any Flask-style URLs

---

## The Architectural Question

The intent of `api/app/` was clear: bot writes to Postgres via `/ingest/*`, frontend reads via `/v1/*`. Clean separation. Auth-able. Multi-process-safe.

**What actually happened:** the bot just writes to local files, and `bot/api_server.py` reads files directly. No DB, no ingest. The simpler architecture won by attrition.

So the choice is:

- **(A) Embrace the file-based architecture** — kill `api/app/` and `bot/dashboard/server.py`. Standardize on `bot/api_server.py`. Single backend. Single dev surface. **Fastest, simplest.**
- **(B) Finish migrating to `api/app/`** — bot starts pushing trades via `/ingest/*` to Postgres, frontend reads via `api/app/`. **More work, more rigor, multi-process-safe.** Required if you ever want multiple bots writing to one frontend, or remote read replicas.
- **(C) Keep both** — sigh. This is what's happened. Don't keep doing it.

**Recommendation: (A).** The bot is single-process, the dataset is small (KB to low MB), and the user is one person. File-based is correct for the scale. If you ever ship WAGMI-as-a-product with multiple bots writing to one dashboard, revisit (B). Until then, kill `api/app/` and `bot/dashboard/server.py`.

---

## Reshape Plan

### Step 0 — Inventory before deletion (30 min)

For every endpoint in `api/app/`, confirm whether anything (frontend OR scripts OR docs) references it. Build a kill list. **Don't delete what we need.**

```bash
# In repo root
grep -rn "api/app/" web/ bot/ scripts/ docs/ --include="*.tsx" --include="*.ts" --include="*.py" --include="*.md"
```

### Step 1 — Adopt `bot/api_server.py` as the canonical backend (30 min)

1. Move `bot/api_server.py` → `backend/server.py` (or keep where it is — the path is fine).
2. Update README / CLAUDE.md to say "the API is `bot/api_server.py`. Run with `cd bot && python api_server.py`."
3. Add a docstring at top: list of all 36 endpoints with one-line descriptions.

### Step 2 — Add the missing endpoints `bot/api_server.py` doesn't have but the frontend needs (2–3 hours)

From the page audit, frontend pages call endpoints not currently surveyed:

- `/api/sniper`, `/api/sniper/journal` (`copy-trade.tsx`) — wrong prefix; should be `/v1/sniper/queue` and `/v1/sniper/journal`. Add `/v1/sniper/journal` if missing.
- Pages using `useApi` hook may hit endpoints I didn't catch. Audit `web/hooks/useApi.ts` and `web/src/api.ts` for the canonical endpoint list.

### Step 3 — Migrate any unique-and-needed `api/app/` endpoints to `bot/api_server.py` (4–6 hours)

Endpoints `api/app/` has but `bot/api_server.py` doesn't:

- **Ingest** (`/ingest/trade`, `/ingest/position`, `/ingest/pnl`, `/ingest/heartbeat`) — only matters if you switch to push-based. **Skip for now.**
- **Edge** (`/edge/setup-types`, `/edge/regimes`, `/edge/strategies`, `/edge/symbols`, `/edge/summary`) — useful for "where does our edge live" analytics. **Migrate** as `/v1/edge/*`.
- **Copy** (`/copy/subscribe`, `/copy/subscribers`, `/copy/executions`) — only matters if you ship copy-trading-as-a-service. **Skip until you do.**
- **Sniper** (`/sniper/queue`, `/sniper/history`, `/sniper/stats`, `/sniper/{id}/approve`, `/sniper/{id}/reject`) — useful if you build the `/sniper` page. **Migrate** as `/v1/sniper/queue`, `/v1/sniper/{id}/approve`, etc. POST endpoints needed for approve/reject.
- **Strategies CRUD** (`/strategies/{id}`, `/strategies/{id}/trades`, `/strategies/{id}/positions`, `/strategies/{id}/performance`, `/strategies/{id}/trades.csv`, `/leaderboard`) — useful for the `/strategies/[id]` frontend page. **Migrate** all.

That's ~12 endpoints to port. Plain function definitions reading from files.

### Step 4 — Delete `bot/dashboard/server.py` (1 hour, with verification)

1. `grep -rn "dashboard.server\|dashboard\.server\|port=8080\|dashboard/__main__"` to find any caller.
2. If no caller in active code paths: delete `bot/dashboard/` entirely.
3. Update any docs that say "run the Flask dashboard."

### Step 5 — Delete `api/app/` (1 hour, with verification)

1. `grep -rn "api\.app\|api/app/" web/ bot/ scripts/ --include="*.tsx" --include="*.ts" --include="*.py"` (after Step 3 ports completed).
2. If clean: delete `api/app/`. Keep the directory if any related scripts (like Postgres migrations) need to live somewhere — but the FastAPI app itself goes.
3. Document in `docs/` that ingest / Postgres path was retired in favor of file-based.

### Step 6 — Single-command boot (1 hour)

After cleanup, the entire stack is:

- **Bot:** `cd bot && python run.py paper`
- **API:** `cd bot && python api_server.py`
- **Frontend:** `cd web && npm run dev`

Add a `Makefile` or top-level `start.sh`:

```bash
#!/bin/bash
# Start all services in the background, log to stdout
cd "$(dirname "$0")"
python bot/run.py paper > logs/bot.log 2>&1 &
python bot/api_server.py > logs/api.log 2>&1 &
cd web && npm run dev > ../logs/web.log 2>&1 &
wait
```

### Step 7 — Add Server-Sent Events for live data (4–6 hours)

`bot/api_server.py` adds:

- `/v1/signals/stream` — SSE feed of new signals
- `/v1/decisions/stream` — SSE feed of LLM decisions
- `/v1/positions/stream` — SSE feed of position updates
- `/v1/equity/stream` — SSE feed of equity ticks

Implementation: file-watch on `decisions.jsonl`, `signals.jsonl`, `position_state.json` and emit. ~200 lines total.

Frontend swaps polling for `EventSource` on signals, ai-decisions, dashboard. **The "feels alive" upgrade.**

### Step 8 — Authentication (deferred, but plan now)

When WAGMI ships as a product (per the masterclass page intent), single-user auth is needed. Cleanest path:

- Add `auth_middleware` to `bot/api_server.py` that checks `Authorization: Bearer <token>` header.
- Token stored as env var `WAGMI_API_TOKEN`, set in `.env`.
- Frontend reads token from another env var, sends on every request.
- Public-landing pages stay unauthenticated.

Don't build this until you have a second user. Premature for now.

---

## Data Flow After Reshape

```
┌─────────────────────────────────────────────────┐
│  bot/run.py paper (the trading bot)             │
│  • writes trades.csv, decisions.jsonl,          │
│    position_state.json, signal_outcomes.jsonl,  │
│    counterfactuals/scenarios.json,              │
│    feedback/graduated_rules.json,               │
│    data/llm/teaching/knowledge_base.json        │
└────────────────────┬────────────────────────────┘
                     │ writes files
                     ▼
┌─────────────────────────────────────────────────┐
│  bot/data/ (canonical state on disk)            │
└────────────────────┬────────────────────────────┘
                     │ reads files
                     ▼
┌─────────────────────────────────────────────────┐
│  bot/api_server.py (FastAPI, port 8000)         │
│  • /v1/* GET endpoints                          │
│  • /v1/*/stream SSE endpoints (new)             │
└────────────────────┬────────────────────────────┘
                     │ HTTP / SSE
                     ▼
┌─────────────────────────────────────────────────┐
│  web/ (Next.js, port 3000)                      │
│  • /dashboard, /signals, /decisions,            │
│    /analytics/*, /agents, /strategies,          │
│    /sniper, /backtest, /learn, /masterclass     │
└─────────────────────────────────────────────────┘
```

**One bot. One API. One frontend.** No Postgres. No Flask. No half-built ingest path.

---

## What this enables

1. **Phone-friendly editing.** Smaller files, MDX content, single-backend means small clean diffs to review.
2. **Local-first deployment.** No DB to provision means a fresh machine boots in 5 minutes (`git clone && cd bot && python run.py && python api_server.py && cd ../web && npm run dev`).
3. **Real-time UI.** SSE on file watches gives near-instant updates to the dashboard when the bot acts.
4. **Single source of truth.** Bot writes files; nothing else does. Any mismatch between UI and bot reality is a UI bug, not a sync bug.
5. **Deploy anywhere.** No DB dependency means the entire stack runs on a $5 VPS or a Raspberry Pi.

---

## What this gives up

1. **Multi-bot architecture.** If you want 5 bots writing to one dashboard, you need (B) Postgres path.
2. **Concurrent reads at scale.** File-based concurrent reads are fine up to dozens of clients; if you ever have hundreds of dashboard viewers, revisit.
3. **Auditable history.** Postgres gives you transactional history; file-based gives you append-only logs. Append-only is fine but harder to query.

For where WAGMI is right now (one user, one bot, paper trading), the trades aren't a real concern. Revisit when you start running live with real capital and need durability guarantees.

---

## Sequencing with the page audit

The page audit's Phase 1 (brand + health strip) and Phase 2 (kill duplicates) **can ship before** any backend reshape — they're pure frontend work.

The page audit's Phase 3 (extraction), Phase 4 (MDX), Phase 5 (real-time) **benefit from** but don't strictly require the backend reshape.

**Recommended global sequence:**

1. Page audit Phase 1 (brand + health strip) — phone-friendly, ~2 hours
2. Backend reshape Step 1–2 (adopt + add missing endpoints) — ~3 hours desktop
3. Page audit Phase 2 (kill duplicates) — ~5 hours, mostly desktop
4. Backend reshape Step 3 (port unique endpoints) — ~5 hours desktop
5. Backend reshape Step 4–5 (delete legacy) — ~2 hours, low risk
6. Page audit Phase 3 (extraction) — ~12 hours desktop
7. Backend reshape Step 6 (single-command boot) — ~1 hour
8. Backend reshape Step 7 (SSE) + page audit Phase 5 (real-time) — ~10 hours combined
9. Page audit Phase 4 (MDX) — ~5 hours, can be phone-driven editing
10. Page audit Phase 6 (polish) — ongoing

**Total**: ~50 hours of focused work to take the app from "many duplicate pages, three backends, no live data" to "12 clean pages, one backend, SSE live updates." Spread over a week of focused sessions, this is genuinely doable.

---

*Companion to: `03_web_page_audit.md`. Together these two docs are the full UI reshape plan.*
