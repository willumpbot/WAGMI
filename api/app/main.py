import os
import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .db import Base, engine
from .logging_setup import init_logging
from .middleware_request_id import request_id_middleware
from . import models
from .routes_ingest import router as ingest_router
from .routes_read import router as read_router
from .routes_metrics import router as metrics_router
from .routes_copy import router as copy_router
from .middleware import metrics_middleware
from .services.signals import state as signals_state, loop_runner, refresh_signals

app = FastAPI(title="NunuIRL API", version="0.1.0")

# initialize structured logging
init_logging()

# register request-id middleware early so downstream logs can use it
app.middleware("http")(request_id_middleware)

# register metrics middleware early
app.middleware("http")(metrics_middleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Wait for Postgres to be ready before creating tables to avoid startup races.
# Try a few times with a short backoff; if it still fails, allow the app to start
# so healthchecks and other services can report, but log the error.
import time
from sqlalchemy.exc import OperationalError

max_retries = 12
for attempt in range(1, max_retries + 1):
    try:
        Base.metadata.create_all(bind=engine)
        break
    except OperationalError as e:
        if attempt == max_retries:
            # Last attempt: log and continue so the app can start; DB may become ready later
            print(f"Database not ready after {max_retries} attempts: {e}")
            break
        print(f"Database not ready (attempt {attempt}/{max_retries}): {e}")
        time.sleep(2)

@app.on_event("startup")
async def start_signal_loop():
    """Start the background signal refresh loop on startup."""
    asyncio.create_task(loop_runner())

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/v1/signals")
async def get_signals():
    """Get current market signals with zones, labels, and scores."""
    return signals_state

@app.post("/v1/signals/run")
async def force_refresh_signals():
    """Force an immediate refresh of signals (bypasses 60s cache)."""
    await refresh_signals()
    return signals_state

@app.get("/v1/signals/debug")
async def debug_signals():
    """Return signal state including errors — for diagnosing fetch failures."""
    return {
        "last_updated": signals_state.get("last_updated"),
        "coins_loaded": list(signals_state.get("signals", {}).keys()),
        "errors": signals_state.get("errors", []),
    }

@app.post("/seed")
def seed_database():
    """One-time endpoint to seed strategies. Safe to call multiple times."""
    from .db import SessionLocal
    from .models import Strategy
    
    db = SessionLocal()
    try:
        items = [
            {"id": "swing-perp-16h", "name": "Swing Perp (16h regime)", "description": "1h signals, 16h regime filter", "category": "perp", "status": "live", "markets": ["BTCUSDT", "ETHUSDT", "SOLUSDT"]},
            {"id": "mtf-btc-1h-6h-16h", "name": "MTF BTC (1h/6h/16h)", "description": "1h signals with 6h+16h regimes", "category": "perp", "status": "live", "markets": ["BTCUSDT"]},
            {"id": "mtf-eth-1h-6h-16h", "name": "MTF ETH (1h/6h/16h)", "description": "1h signals with 6h+16h regimes", "category": "perp", "status": "live", "markets": ["ETHUSDT"]},
            {"id": "scalp-perp-15m", "name": "Scalp Perp (15m)", "description": "15m scalp strategy", "category": "perp", "status": "live", "markets": ["BTCUSDT", "ETHUSDT"]},
        ]
        
        added = 0
        for x in items:
            if not db.get(Strategy, x["id"]):
                db.add(Strategy(id=x["id"], name=x["name"], description=x["description"], category=x["category"], status=x["status"], markets=x.get("markets", [])))
                added += 1
        
        db.commit()
        return {"ok": True, "added": added, "message": f"Seeded {added} strategies"}
    finally:
        db.close()

# Routers (order matters: specific routes before generic)
from .routes_summary import router as summary_router
from .routes_llm import router as llm_router
from .routes_activity import router as activity_router
from .routes_trades import router as trades_router
from .routes_backtest import router as backtest_router
from .routes_sniper import router as sniper_router
from .routes_agents import router as agents_router
app.include_router(summary_router)  # Must come first for /v1/strategies/swing-perp-16h
app.include_router(ingest_router)
app.include_router(read_router)
app.include_router(metrics_router)
app.include_router(copy_router)
app.include_router(llm_router)
app.include_router(activity_router)
app.include_router(trades_router)
app.include_router(backtest_router)
app.include_router(sniper_router)
app.include_router(agents_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)