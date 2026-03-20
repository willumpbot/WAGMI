from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from html import escape
from fastapi.middleware.cors import CORSMiddleware
import time
import aiohttp
import asyncio
from datetime import datetime, timezone
from config import COINS, CACHE_TTL_SEC, DISABLE_SIGNALS, API_ORIGINS
from indicators import build_signals_snapshot, fetch_df, _regime_from_indicators, compute_indicators, fetch_errors

app = FastAPI(title="MICO Signals")

app.add_middleware(
    CORSMiddleware,
    allow_origins=API_ORIGINS,
    allow_methods=["GET"],
    allow_headers=["*"],
)


class Cache:
    ts = 0
    data = None
    status = "ok"  # ok | degraded | paused
    errors = 0
    regime = "Neutral"
    history = {}  # {market: [log_entry1, log_entry2, ...]} - last 10 per market


cache = Cache()


async def refresh_signals_task():
    """Background task that refreshes signals every 60 seconds and appends to history."""
    await asyncio.sleep(5)  # initial delay
    while True:
        try:
            if not DISABLE_SIGNALS:
                # Fetch BTC once, derive regime from it, then reuse df in snapshot
                btc_df = await fetch_df(app.state.session, "bitcoin", days=60)
                regime = _regime_from_indicators(compute_indicators(btc_df))
                signals = await build_signals_snapshot(app.state.session, COINS, regime, _btc_df=btc_df)
                now = int(time.time())
                if signals:  # only overwrite cache if we actually got data
                    cache.ts = now
                    cache.data = signals
                    cache.regime = regime
                    cache.status = "ok"
                    cache.errors = 0
                
                # Append to history for each market
                iso_ts = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
                for market, signal in signals.items():
                    log_entry = {
                        "ts": iso_ts,
                        "event": "evaluation",
                        "market": market,
                        "note": f"score {signal.get('score', 0)} • label {signal.get('label', 'Observation')} • price ${signal.get('price', 0):.2f}",
                        "score": signal.get("score", 0),
                        "label": signal.get("label", "Observation"),
                        "price": signal.get("price", 0),
                        "level": "info",
                        "details": {
                            "sma20": signal.get("sma20", 0),
                            "sma50": signal.get("sma50", 0),
                            "rsi14": signal.get("rsi14", 50),
                            "atr14": signal.get("atr14", 0),
                            "vol_spike": signal.get("vol_spike", False),
                            "zones": signal.get("zones", {}),
                        }
                    }
                    if market not in cache.history:
                        cache.history[market] = []
                    # Add new entry at the end
                    cache.history[market].append(log_entry)
                    # Keep only last 10
                    if len(cache.history[market]) > 10:
                        cache.history[market] = cache.history[market][-10:]
        except Exception:
            cache.errors += 1
            cache.status = "degraded"
        
        await asyncio.sleep(180)  # refresh every 3 minutes (fetch cycle takes ~35s)


@app.on_event("startup")
async def startup():
    app.state.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))
    # Start background refresh task
    asyncio.create_task(refresh_signals_task())


@app.on_event("shutdown")
async def shutdown():
    await app.state.session.close()


@app.get("/v1/signals")
async def signals():
    now = time.time()
    status = "paused" if DISABLE_SIGNALS else (cache.status or "loading")
    return {
        "last_updated": cache.ts or int(now),
        "regime": cache.regime,
        "signals": cache.data or {},
        "status": status,
    }


@app.get("/v1/summary")
async def summary():
    now = time.time()
    return {
        "updatedAt": cache.ts or int(now),
        "regime": cache.regime,
        "status": cache.status or "loading",
        "errors": cache.errors,
    }


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "cache_age": int(time.time() - cache.ts) if cache.ts else None}


@app.get("/v1/debug")
async def debug():
    return {
        "cache_ts": cache.ts,
        "cache_age_sec": int(time.time() - cache.ts) if cache.ts else None,
        "cache_status": cache.status,
        "cache_errors": cache.errors,
        "coins_loaded": list((cache.data or {}).keys()),
        "fetch_errors": fetch_errors,
    }


def _get_signals_from_cache() -> tuple:
        """Helper to read current signals/regime from cache."""
        now = time.time()
        sig = cache.data or {}
        reg = cache.regime
        ts = cache.ts or int(now)
        return ts, reg, sig


def _guidance_text(label: str, regime: str, risk: str) -> str:
    """Human-friendly guidance based on label, regime, and asset risk."""
    label = (label or "Observation").strip()
    regime = (regime or "Neutral").strip()
    risk_note = {
        "low": "(lower volatility)",
        "medium": "(moderate volatility)",
        "high": "(high volatility)"
    }.get(risk, "")

    base = "Observation: No clear edge. Stand by and wait for better alignment."
    if label == "Aggressive Accumulation":
        base = "Deep Accumulation: Price is below the lower band (SMA20 - k2·ATR). DCA/scale-in zone for longs; avoid shorts unless plan requires."
    elif label == "Accumulation":
        base = "Accumulation: Price near lower band (SMA20 - k1·ATR). Favor buying dips; wait for momentum reclaim above SMA20 for adds."
    elif label == "Distribution":
        base = "Distribution: Price near upper band (SMA20 + k1·ATR). Take profits on longs; avoid fresh longs; wait for pullbacks."
    elif label == "Aggressive Distribution":
        base = "Aggressive Distribution: Overextended above upper band (SMA20 + k2·ATR). Trim/hedge; only short if plan allows and risk controlled."

    regime_note = {
        "Risk-ON": "Backdrop supportive; continuation more likely.",
        "Neutral": "Mixed backdrop; manage size and confirmation.",
        "Risk-OFF": "Caution: de-risk, smaller size, tighter risk."
    }.get(regime, "")

    risk_tail = {
        "low": "",
        "medium": " Size moderately.",
        "high": " Use smaller size and wider stops."
    }.get(risk, "")

    parts = [base]
    if regime_note:
        parts.append(regime_note)
    if risk_note or risk_tail:
        parts.append(f"Asset risk: {risk} {risk_note}.{risk_tail}")
    return " ".join(p for p in parts if p)


@app.get("/view", response_class=HTMLResponse)
async def view_home():
    """Simple HTML dashboard listing all signals with links to logs."""
    # Ensure cache is warm
    await signals()
    ts, regime, sigs = _get_signals_from_cache()
    # Human-readable local time for header
    try:
        local_ts = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
        human_ts = local_ts.strftime("%I:%M:%S %p").lstrip("0")
    except Exception:
        human_ts = str(ts)
    rows = []
    for m, s in sigs.items():
        risk = COINS.get(m, {}).get("risk", "medium")
        guidance = _guidance_text(str(s.get('label','')), regime, risk)
        rows.append(
            f"<tr><td>{escape(m)}</td><td>{escape(str(s.get('label','')))}</td><td>{s.get('score',0)}</td>"
            f"<td>{s.get('price',0):.6f}</td><td>{s.get('sma20',0):.6f}</td><td>{s.get('sma50',0):.6f}</td>"
            f"<td>{s.get('rsi14',0):.1f}</td><td style='max-width:480px'>{escape(guidance)}</td>"
            f"<td><a href='/view/strategies/signals-{m.lower()}'>logs</a></td></tr>"
        )
    table = """
    <table border='1' cellspacing='0' cellpadding='6'>
      <thead><tr><th>Market</th><th>Label</th><th>Score</th><th>Price</th><th>SMA20</th><th>SMA50</th><th>RSI14</th><th>Guidance</th><th>Logs</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    """.replace("{rows}", "\n".join(rows))
    html = f"""
    <html><head><title>MICO Signals</title><meta charset='utf-8' /></head>
    <body style='font-family:Arial, sans-serif; padding:16px;'>
      <h2>MICO Signals</h2>
            <div>Updated: {human_ts} • Regime: {escape(regime)} • Status: {escape(cache.status)}</div>
      <div style='margin:12px 0;'>This is a minimal HTML view served by the API.</div>
      {table}
    </body></html>
    """
    return HTMLResponse(content=html)


@app.get("/", response_class=HTMLResponse)
async def root():
        """Serve the minimal signals table as the main page."""
        return await view_home()


@app.get("/view/strategies/{strategy_id}", response_class=HTMLResponse)
async def view_strategy(strategy_id: str):
    """Simple HTML page showing current log row for a strategy."""
    # Ensure cache is warm
    await signals()
    ts, regime, sigs = _get_signals_from_cache()
    try:
        local_ts = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
        human_ts = local_ts.strftime("%I:%M:%S %p").lstrip("0")
    except Exception:
        human_ts = str(ts)
    market = strategy_id.replace("signals-", "").upper()
    s = sigs.get(market, {})
    price = s.get("price", 0)
    label = s.get("label", "Observation")
    score = s.get("score", 0)
    zones = s.get("zones", {})
    risk = COINS.get(market, {}).get("risk", "medium")
    guidance = _guidance_text(label, regime, risk)
    html = f"""
    <html><head><title>{escape(market)} Logs</title><meta charset='utf-8' /></head>
    <body style='font-family:Arial, sans-serif; padding:16px;'>
      <a href='/view'>&larr; Back</a>
      <h2>{escape(market)} Signals</h2>
            <div>Updated: {human_ts} • Regime: {escape(regime)} • Status: {escape(cache.status)}</div>
      <h3 style='margin-top:16px;'>Current Evaluation</h3>
      <ul>
        <li>Label: <strong>{escape(str(label))}</strong></li>
        <li>Score: <strong>{score}</strong></li>
        <li>Price: <strong>{price:.6f}</strong></li>
        <li>Zones: deepAccum={zones.get('deepAccum',0):.6f} | accum={zones.get('accum',0):.6f} | distrib={zones.get('distrib',0):.6f} | safeDistrib={zones.get('safeDistrib',0):.6f}</li>
      </ul>
      <h3>What this means</h3>
      <p style='max-width:720px;'>{escape(guidance)}</p>
      <div><a href='/v1/strategies/{escape(strategy_id)}/logs'>View JSON logs</a></div>
    </body></html>
    """
    return HTMLResponse(content=html)


@app.get("/v1/strategies")
async def strategies():
    """Frontend compatibility endpoint - returns strategies array"""
    now = time.time()
    signals = cache.data or {}
    regime = cache.regime

    # Convert signals to strategies array format
    strategies_list = []
    for market, signal in signals.items():
        strategies_list.append({
            "id": f"signals-{market.lower()}",
            "name": f"{market} Signals",
            "markets": [market],
            "status": "Active",
            "lastEvaluated": cache.ts or int(now),
            "latestSignal": {
                "label": signal.get("label", "Observation"),
                "score": signal.get("score", 0),
                "market": market,
                "ts": cache.ts or int(now),
            },
        })
    
    return strategies_list


@app.get("/v1/strategy")
async def strategy_legacy():
    """Legacy endpoint - returns first strategy for backward compatibility"""
    strategies_list = await strategies()
    if strategies_list:
        return strategies_list[0]
    return {"id": "unknown", "name": "No strategies", "status": "Waiting"}


@app.get("/v1/strategies/{strategy_id}")
async def strategy_detail(strategy_id: str):
    """Get single strategy details"""
    now = time.time()
    signals = cache.data or {}

    # Extract market from strategy_id (e.g., "signals-btc" -> "BTC")
    market = strategy_id.replace("signals-", "").upper()
    signal = signals.get(market, {})
    
    from datetime import datetime, timezone
    timestamp_iso = datetime.fromtimestamp(cache.ts or now, tz=timezone.utc).isoformat() if cache.ts else datetime.now(timezone.utc).isoformat()
    
    return {
        "id": strategy_id,
        "name": f"{market} Signals",
        "status": "Active",
        "lastEvaluated": timestamp_iso,
        "latestSignal": {
            "label": signal.get("label", "Observation"),
            "score": signal.get("score", 0),
            "market": market,
            "price": signal.get("price", 0),
            "trend": {
                "sma20": "Up" if signal.get("price", 0) > signal.get("sma20", 0) else "Down",
                "sma50": "Up" if signal.get("price", 0) > signal.get("sma50", 0) else "Down",
                "rsi14": signal.get("rsi14", 50.0),
            },
            "zones": signal.get("zones", {
                "deepAccum": 0,
                "accum": 0,
                "distrib": 0,
                "safeDistrib": 0,
            }),
        },
    }


@app.get("/v1/strategies/{strategy_id}/logs")
async def strategy_logs(strategy_id: str, limit: int = 50):
    """Get strategy evaluation logs - returns history (newest first)"""
    market = strategy_id.replace("signals-", "").upper()
    
    # Return history if available, otherwise return current reading from cache
    if market in cache.history and cache.history[market]:
        return list(reversed(cache.history[market][-limit:]))

    now = time.time()
    signal = (cache.data or {}).get(market, {})
    timestamp_iso = datetime.fromtimestamp(cache.ts or now, tz=timezone.utc).isoformat() if cache.ts else datetime.now(timezone.utc).isoformat()
    
    log_entry = {
        "ts": timestamp_iso,
        "event": "evaluation",
        "market": market,
        "note": f"score {signal.get('score', 0)} • label {signal.get('label', 'Observation')} • price ${signal.get('price', 0):.2f}",
        "score": signal.get("score", 0),
        "label": signal.get("label", "Observation"),
        "price": signal.get("price", 0),
        "level": "info",
        "details": {
            "sma20": signal.get("sma20", 0),
            "sma50": signal.get("sma50", 0),
            "rsi14": signal.get("rsi14", 50),
            "atr14": signal.get("atr14", 0),
            "vol_spike": signal.get("vol_spike", False),
            "zones": signal.get("zones", {}),
        }
    }
    
    return [log_entry]
