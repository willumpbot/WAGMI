"""
Production-quality routes for swing-perp-16h strategy.
Provides clean read-only endpoints for frontend consumption.
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
from .utils import append_jsonl, tail_jsonl, write_state, read_state

router = APIRouter(tags=["summary"])

# Data directories structure
DATA_DIR = Path(__file__).parent.parent / "data"
LOGS_DIR = DATA_DIR / "strategy_logs"
TRADES_DIR = DATA_DIR / "strategy_trades"
STATE_DIR = DATA_DIR / "strategy_state"
ROUNDTRIPS_DIR = DATA_DIR / "strategy_roundtrips"

# Ensure directories exist
for d in [LOGS_DIR, TRADES_DIR, STATE_DIR, ROUNDTRIPS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Canonical strategy ID
STRATEGY_ID = "swing-perp-16h"

# Optional alias mapping
ALIASES = {
    "swing-atr": "swing-perp-16h",
}

def resolve_strategy_id(sid: str) -> str:
    """Resolve aliases to canonical ID"""
    return ALIASES.get(sid, sid)


def get_state_file(strategy_id: str) -> Path:
    """Get path to state file for strategy"""
    return STATE_DIR / f"{strategy_id}.json"


def get_logs_file(strategy_id: str) -> Path:
    """Get path to logs JSONL file for strategy"""
    return LOGS_DIR / f"{strategy_id}.jsonl"


def get_trades_file(strategy_id: str) -> Path:
    """Get path to trades JSONL file for strategy"""
    return TRADES_DIR / f"{strategy_id}.jsonl"


def get_roundtrips_file(strategy_id: str) -> Path:
    """Get path to roundtrips JSONL file for strategy"""
    return ROUNDTRIPS_DIR / f"{strategy_id}.jsonl"


def clamp_score(score: Any) -> int:
    """Clamp score to 0-100 range"""
    try:
        val = int(score)
        return max(0, min(100, val))
    except Exception:
        return 0


def format_price(price: Any) -> float:
    """Format price to 2 decimal places"""
    try:
        return round(float(price), 2)
    except Exception:
        return 0.0


def compute_position_from_trades(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute current position from trade history"""
    qty = 0.0
    total_cost = 0.0
    symbol = "BTCUSDT"
    side = "FLAT"
    
    for t in reversed(trades):  # Process oldest first
        trade_side = t.get("side", "")
        trade_qty = float(t.get("qty", 0))
        fill_px = float(t.get("fill_px", 0))
        
        if trade_side == "OPEN_LONG":
            qty += trade_qty
            total_cost += trade_qty * fill_px
        elif trade_side == "CLOSE_LONG":
            qty -= trade_qty
            if qty <= 0:
                qty = 0
                total_cost = 0
        elif trade_side == "OPEN_SHORT":
            qty -= trade_qty
            total_cost += trade_qty * fill_px
        elif trade_side == "CLOSE_SHORT":
            qty += trade_qty
            if qty >= 0:
                qty = 0
                total_cost = 0
        
        if t.get("symbol"):
            symbol = t["symbol"]
    
    if qty > 0.001:
        side = "LONG"
    elif qty < -0.001:
        side = "SHORT"
    else:
        side = "FLAT"
        qty = 0.0
    
    avg_entry = (total_cost / abs(qty)) if qty != 0 else 0.0
    
    return {
        "symbol": symbol,
        "side": side,
        "qty": round(qty, 8),
        "avg_entry": format_price(avg_entry),
        "mark": 0.0,
        "upnl": 0.0
    }


@router.get("/v1/version")
async def get_version():
    """
    GET /v1/version - Returns build info for frontend display.
    Shows git commit SHA and build timestamp.
    """
    import subprocess
    from datetime import datetime, timezone
    
    # Get git commit SHA (short 7 chars)
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short=7", "HEAD"],
            cwd=Path(__file__).parent.parent.parent,
            text=True
        ).strip()
    except Exception:
        sha = "unknown"
    
    # Build timestamp (ISO 8601)
    built_at = datetime.now(timezone.utc).isoformat()
    
    return {
        "sha": sha,
        "built_at": built_at,
        "strategy_id": STRATEGY_ID,
        "version": "1.0.0"
    }


@router.get("/v1/summary")
async def get_summary():
    """
    Get home page summary: updated time, regime, status, errors, most recent trade.
    Returns graceful empty state if no data yet.
    """
    # Get state for canonical strategy
    state = read_state(get_state_file(STRATEGY_ID))
    
    last_updated = state.get("lastEvaluated")
    regime = state.get("latestSignal", {}).get("label", "Observation")
    status = state.get("status", "Active")
    
    # Get most recent trade from state
    most_recent_trade = state.get("lastTrade")
    
    # updatedAt must be epoch seconds per contract
    def iso_to_epoch(iso_val: Optional[str]) -> Optional[int]:
        if not iso_val:
            return None
        try:
            dt = datetime.fromisoformat(iso_val.replace("Z", "+00:00"))
            return int(dt.timestamp())
        except Exception:
            return None
    
    return {
        "updatedAt": last_updated,  # Return ISO string for frontend display
        "regime": regime,
        "status": "degraded" if status == "Error" else "ok",
        "errors": 1 if status == "Error" else 0,
        "mostRecentTrade": most_recent_trade,
    }
@router.get("/v1/strategies/swing-perp-16h")
async def get_strategy_summary():
    """
    GET /v1/strategies/swing-perp-16h
    Returns comprehensive strategy summary for header/at-a-glance display.
    Never crashes - returns graceful defaults if no data.
    """
    state = read_state(get_state_file(STRATEGY_ID))
    
    # Extract components with safe defaults
    latest_signal = state.get("latestSignal")
    position = state.get("position", {
        "symbol": "BTCUSDT",
        "side": "FLAT",
        "qty": 0.0,
        "avg_entry": 0.0,
        "mark": 0.0,
        "upnl": 0.0
    })
    last_trade = state.get("lastTrade")
    last_evaluated = state.get("lastEvaluated", datetime.now(timezone.utc).isoformat())
    status = state.get("status", "Active")
    
    # Build open_position in the shape the frontend expects (null if FLAT)
    pos_side = (position.get("side") or "FLAT").upper()
    open_position = None
    if pos_side not in ("FLAT", "", "NONE"):
        open_position = {
            "side": pos_side,
            "size": position.get("qty", 0.0),
            "avg_entry": position.get("avg_entry", 0.0),
            "unrealized_pnl": position.get("upnl", 0.0),
            "unrealized_pnl_pct": 0.0,
            "updated_at": last_evaluated,
        }

    return {
        "id": STRATEGY_ID,
        "name": "Swing Perp (16h)",
        "markets": ["BTC", "SOL", "HYPE"],
        "status": status,
        "lastHeartbeat": last_evaluated,
        "lastTradeAt": (last_trade or {}).get("ts") if last_trade else None,
        "pnl_realized": (last_trade or {}).get("pnl") if last_trade else None,
        "open_position": open_position,
        # keep legacy fields for other consumers
        "lastEvaluated": last_evaluated,
        "latestSignal": latest_signal,
        "position": position,
        "lastTrade": last_trade,
    }


# Alias routes for backward compatibility
@router.get("/v1/strategies")
async def get_single_strategy():
    """
    Legacy route - returns array of strategies for homepage.
    Frontend expects array or {items: []} format.
    """
    strategy = await get_strategy_summary()
    # Return as array for frontend compatibility
    return [strategy]


@router.get("/v1/strategy")
async def get_single_strategy_card():
    """Legacy route - redirects to canonical strategy"""
    return await get_strategy_summary()


@router.get("/v1/strategies/swing-perp-16h/logs")
async def get_strategy_logs_canonical(limit: int = Query(50, description="Max logs to return")):
    """
    GET /v1/strategies/swing-perp-16h/logs?limit=50
    Returns recent evaluation/decision events from JSONL file.
    Returns empty array if no logs yet.
    """
    logs = tail_jsonl(get_logs_file(STRATEGY_ID), limit)
    # Normalize: ensure level becomes "info" if not present
    for log in logs:
        if "level" not in log:
            log["level"] = "info"
    return logs


@router.get("/v1/strategies/{strategy_id}/logs")
async def get_strategy_logs_generic(strategy_id: str, limit: int = Query(50)):
    """
    GET /v1/strategies/{strategy_id}/logs?limit=50
    Generic endpoint with alias resolution.
    """
    resolved_id = resolve_strategy_id(strategy_id)
    logs = tail_jsonl(get_logs_file(resolved_id), limit)
    for log in logs:
        if "level" not in log:
            log["level"] = "info"
    return logs


@router.post("/v1/strategies/swing-perp-16h/logs")
async def post_strategy_log_canonical(log: Dict[str, Any]):
    """
    POST /v1/strategies/swing-perp-16h/logs
    Called by bot after each evaluation/decision. Appends to JSONL.
    Body: {"event": "evaluation", "market": "BTCUSDT", "note": "...", "score": 71}
    """
    # Add timestamp if not present
    if "ts" not in log:
        log["ts"] = datetime.now(timezone.utc).isoformat()
    
    # Clamp score to 0-100
    if "score" in log:
        log["score"] = clamp_score(log["score"])
    
    # Append to JSONL
    append_jsonl(get_logs_file(STRATEGY_ID), log)
    
    # Update lastEvaluated in state file
    state_file = get_state_file(STRATEGY_ID)
    state = read_state(state_file)
    state["lastEvaluated"] = log["ts"]
    
    # If this is an evaluation event, update latestSignal
    if log.get("event") == "evaluation" and "score" in log:
        state["latestSignal"] = {
            "label": log.get("label", "Observation"),
            "score": log["score"],
            "market": log.get("market", "BTCUSDT"),
            "price": format_price(log.get("price", 0)),
            "trend": log.get("trend", {"sma20": "Up", "sma50": "Up", "rsi14": 50.0}),
            "zones": log.get("zones", {"deepAccum": 0.0, "accum": 0.0, "distrib": 0.0, "safeDistrib": 0.0})
        }
    
    write_state(state_file, state)
    
    return {"ok": True}


@router.post("/v1/strategies/{strategy_id}/logs")
async def post_strategy_log_generic(strategy_id: str, log: Dict[str, Any]):
    """Generic POST endpoint with alias resolution"""
    resolved_id = resolve_strategy_id(strategy_id)
    
    if "ts" not in log:
        log["ts"] = datetime.now(timezone.utc).isoformat()
    
    if "score" in log:
        log["score"] = clamp_score(log["score"])
    
    append_jsonl(get_logs_file(resolved_id), log)
    
    state_file = get_state_file(resolved_id)
    state = read_state(state_file)
    state["lastEvaluated"] = log["ts"]
    write_state(state_file, state)
    
    return {"ok": True}


@router.get("/v1/strategies/swing-perp-16h/trades")
async def get_strategy_trades_canonical(limit: int = Query(20, description="Max trades to return")):
    """
    GET /v1/strategies/swing-perp-16h/trades?limit=20
    Returns fills/executions (not paired round-trips).
    Shape: [{ts, order_id, side, symbol, fill_px, qty, status}]
    """
    trades = tail_jsonl(get_trades_file(STRATEGY_ID), limit)
    return trades


@router.get("/v1/strategies/{strategy_id}/trades")
async def get_strategy_trades_generic(strategy_id: str, limit: int = Query(20)):
    """Generic trades endpoint with alias resolution"""
    resolved_id = resolve_strategy_id(strategy_id)
    trades = tail_jsonl(get_trades_file(resolved_id), limit)
    return trades


@router.post("/v1/strategies/swing-perp-16h/trades")
async def post_strategy_trade_canonical(trade: Dict[str, Any]):
    """
    POST /v1/strategies/swing-perp-16h/trades
    Called by bot on fills. Appends to JSONL and updates lastTrade/position.
    Body: {"order_id": "abc123", "side": "OPEN_LONG", "symbol": "BTCUSDT", 
           "fill_px": 94200.00, "qty": 0.015, "status": "filled", "ts": "..."}
    """
    # Add timestamp if not present
    if "ts" not in trade:
        trade["ts"] = datetime.now(timezone.utc).isoformat()
    
    # Normalize price
    if "fill_px" in trade:
        trade["fill_px"] = format_price(trade["fill_px"])
    
    # Append to trades JSONL
    append_jsonl(get_trades_file(STRATEGY_ID), trade)
    
    # Update state file
    state_file = get_state_file(STRATEGY_ID)
    state = read_state(state_file)
    
    # Update lastTrade
    state["lastTrade"] = {
        "ts": trade["ts"],
        "side": trade.get("side", "UNKNOWN"),
        "symbol": trade.get("symbol", "BTCUSDT"),
        "fill_px": trade.get("fill_px", 0.0),
        "qty": trade.get("qty", 0.0),
        "order_id": trade.get("order_id", ""),
        "status": trade.get("status", "filled")
    }
    
    # Recompute position from all trades
    all_trades = tail_jsonl(get_trades_file(STRATEGY_ID), 1000)  # Get enough history
    state["position"] = compute_position_from_trades(all_trades)
    
    write_state(state_file, state)
    
    return {"ok": True}


@router.post("/v1/strategies/{strategy_id}/trades")
async def post_strategy_trade_generic(strategy_id: str, trade: Dict[str, Any]):
    """Generic POST trades endpoint with alias resolution"""
    resolved_id = resolve_strategy_id(strategy_id)
    
    if "ts" not in trade:
        trade["ts"] = datetime.now(timezone.utc).isoformat()
    
    if "fill_px" in trade:
        trade["fill_px"] = format_price(trade["fill_px"])
    
    append_jsonl(get_trades_file(resolved_id), trade)
    
    state_file = get_state_file(resolved_id)
    state = read_state(state_file)
    state["lastTrade"] = {
        "ts": trade["ts"],
        "side": trade.get("side", "UNKNOWN"),
        "symbol": trade.get("symbol", "BTCUSDT"),
        "fill_px": trade.get("fill_px", 0.0),
        "qty": trade.get("qty", 0.0),
        "order_id": trade.get("order_id", ""),
        "status": trade.get("status", "filled")
    }
    
    all_trades = tail_jsonl(get_trades_file(resolved_id), 1000)
    state["position"] = compute_position_from_trades(all_trades)
    
    write_state(state_file, state)
    
    return {"ok": True}


@router.get("/v1/strategies/swing-perp-16h/roundtrips")
async def get_strategy_roundtrips(limit: int = Query(10, description="Max roundtrips to return")):
    """
    GET /v1/strategies/swing-perp-16h/roundtrips?limit=10
    Returns paired entry/exit trades with PnL.
    Shape: [{entry_ts, exit_ts, side, symbol, entry_px, exit_px, qty, pnl_quote, hold_hours}]
    """
    # Get all trades to pair
    trades = tail_jsonl(get_trades_file(STRATEGY_ID), 1000)
    
    # Build roundtrips by pairing OPEN/CLOSE trades
    trips = []
    stack = []
    
    for t in reversed(trades):  # Process oldest first
        side = t.get("side", "")
        if side.startswith("OPEN_"):
            stack.append(t)
        elif side.startswith("CLOSE_") and stack:
            entry = stack.pop(0)
            entry_ts_dt = datetime.fromisoformat(entry["ts"].replace("Z", "+00:00"))
            exit_ts_dt = datetime.fromisoformat(t["ts"].replace("Z", "+00:00"))
            hold_hours = (exit_ts_dt - entry_ts_dt).total_seconds() / 3600.0
            
            entry_side = entry["side"].split("_")[1]  # LONG or SHORT
            entry_px = float(entry.get("fill_px", 0))
            exit_px = float(t.get("fill_px", 0))
            qty = float(t.get("qty", 0))
            
            # PnL calculation
            if entry_side == "LONG":
                pnl_quote = (exit_px - entry_px) * qty
            else:  # SHORT
                pnl_quote = (entry_px - exit_px) * qty
            
            trips.append({
                "entry_ts": entry["ts"],
                "exit_ts": t["ts"],
                "side": entry_side,
                "symbol": t.get("symbol", "BTCUSDT"),
                "entry_px": format_price(entry_px),
                "exit_px": format_price(exit_px),
                "qty": qty,
                "pnl_quote": round(pnl_quote, 2),
                "hold_hours": round(hold_hours, 1)
            })
    
    # Return last N
    return trips[-limit:]


@router.get("/v1/strategies/{strategy_id}/roundtrips")
async def get_strategy_roundtrips_generic(strategy_id: str, limit: int = Query(10)):
    """Generic roundtrips endpoint with alias resolution"""
    resolved_id = resolve_strategy_id(strategy_id)
    trades = tail_jsonl(get_trades_file(resolved_id), 1000)
    
    trips = []
    stack = []
    
    for t in reversed(trades):
        side = t.get("side", "")
        if side.startswith("OPEN_"):
            stack.append(t)
        elif side.startswith("CLOSE_") and stack:
            entry = stack.pop(0)
            entry_ts_dt = datetime.fromisoformat(entry["ts"].replace("Z", "+00:00"))
            exit_ts_dt = datetime.fromisoformat(t["ts"].replace("Z", "+00:00"))
            hold_hours = (exit_ts_dt - entry_ts_dt).total_seconds() / 3600.0
            
            entry_side = entry["side"].split("_")[1]
            entry_px = float(entry.get("fill_px", 0))
            exit_px = float(t.get("fill_px", 0))
            qty = float(t.get("qty", 0))
            
            if entry_side == "LONG":
                pnl_quote = (exit_px - entry_px) * qty
            else:
                pnl_quote = (entry_px - exit_px) * qty
            
            trips.append({
                "entry_ts": entry["ts"],
                "exit_ts": t["ts"],
                "side": entry_side,
                "symbol": t.get("symbol", "BTCUSDT"),
                "entry_px": format_price(entry_px),
                "exit_px": format_price(exit_px),
                "qty": qty,
                "pnl_quote": round(pnl_quote, 2),
                "hold_hours": round(hold_hours, 1)
            })
    
    return trips[-limit:]


@router.get("/v1/strategies/swing-perp-16h/kpis")
async def get_strategy_kpis_canonical(window: str = Query("7d", description="Time window: 7d, 24h, 30d")):
    """
    GET /v1/strategies/swing-perp-16h/kpis?window=7d
    Returns aggregated KPIs over time window.
    Shape: {alertsIssued, avgScore, riskSuppressedCount, medianTimeBetweenEvals}
    """
    # Parse window
    now = datetime.now(timezone.utc)
    if window.endswith("d"):
        delta = timedelta(days=int(window[:-1]))
    elif window.endswith("h"):
        delta = timedelta(hours=int(window[:-1]))
    else:
        delta = timedelta(days=7)  # Default
    
    cutoff = now - delta
    
    # Read logs from file
    logs = tail_jsonl(get_logs_file(STRATEGY_ID), 10000)  # Get enough history
    
    # Filter by time window
    filtered = []
    for log in logs:
        try:
            ts = datetime.fromisoformat(log.get("ts", "").replace("Z", "+00:00"))
            if ts >= cutoff:
                filtered.append(log)
        except Exception:
            continue
    
    # Compute KPIs
    alerts_issued = sum(1 for log in filtered if log.get("event") in ("signal_long", "signal_short"))
    
    scores = [log.get("score", 0) for log in filtered if isinstance(log.get("score"), (int, float))]
    avg_score = int(sum(scores) / len(scores)) if scores else 0
    
    risk_suppressed = sum(1 for log in filtered if "blocked" in log.get("note", "").lower())
    
    # Median time between evaluations (minutes)
    eval_times = []
    for log in filtered:
        if log.get("event") == "evaluation":
            try:
                eval_times.append(datetime.fromisoformat(log.get("ts", "").replace("Z", "+00:00")))
            except Exception:
                continue
    
    eval_times.sort()
    gaps = [(eval_times[i] - eval_times[i-1]).total_seconds() / 60.0 for i in range(1, len(eval_times))]
    gaps.sort()
    median_gap = gaps[len(gaps) // 2] if gaps else 0
    
    return {
        "window": window,
        "alertsIssued": alerts_issued,
        "avgScore": avg_score,
        "riskSuppressedCount": risk_suppressed,
        "medianTimeBetweenEvalsMin": round(median_gap, 1)
    }


@router.get("/v1/strategies/{strategy_id}/kpis")
async def get_strategy_kpis_generic(strategy_id: str, window: str = Query("7d")):
    """Generic KPIs endpoint with alias resolution"""
    resolved_id = resolve_strategy_id(strategy_id)
    
    if resolved_id != STRATEGY_ID:
        # Redirect to canonical
        return await get_strategy_kpis_canonical(window)
    
    return await get_strategy_kpis_canonical(window)
