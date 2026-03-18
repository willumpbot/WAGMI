import os
import json
import time
from fastapi import APIRouter, Query
from typing import List, Optional
from .utils_jsonl import tail_jsonl as _tail_jsonl

router = APIRouter(prefix="/v1/llm", tags=["llm"])

# Path to bot's decisions log — configurable via env var.
# Default assumes API runs from project root alongside bot/.
_DECISIONS_PATH = os.environ.get(
    "LLM_DECISIONS_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", "bot", "data", "llm", "decisions.jsonl"),
)


def _extract_symbol(entry: dict) -> Optional[str]:
    """Best-effort symbol extraction from a decision entry."""
    ctx = entry.get("trigger_context", "")
    if ctx:
        parts = ctx.strip().split()
        if parts:
            sym = parts[0].upper().replace("USDT", "").replace("USD", "")
            if 2 <= len(sym) <= 6 and sym.isalpha():
                return sym
    snap = entry.get("snapshot", {})
    if isinstance(snap, dict):
        sym = snap.get("symbol") or snap.get("market", "")
        if sym:
            return str(sym).upper().replace("USDT", "").replace("USD", "")
    return None


def _format_entry(entry: dict) -> dict:
    """Normalize a raw decision entry for API consumers."""
    action = entry.get("action", "unknown")
    confidence = float(entry.get("confidence") or 0)
    regime = entry.get("regime") or "unknown"
    notes = entry.get("notes") or ""
    mode = entry.get("mode", "UNKNOWN")
    trigger = entry.get("trigger_reason", "")
    is_veto = bool(entry.get("is_veto"))
    allowed = entry.get("allowed", True)
    gate_reason = entry.get("gate_reason") or ""
    ts = entry.get("ts", 0)
    symbol = _extract_symbol(entry)
    usage = entry.get("usage") or {}
    model = usage.get("model", "")

    # "would_have_traded" = LLM said proceed AND it wasn't blocked by gate
    would_have_traded = (action in ("proceed", "go")) and allowed

    return {
        "ts": ts,
        "ts_iso": _ts_to_iso(ts),
        "symbol": symbol,
        "action": action,
        "original_action": entry.get("original_action", action),
        "confidence": round(confidence, 3),
        "regime": regime,
        "notes": notes,
        "mode": mode,
        "trigger": trigger,
        "trigger_context": entry.get("trigger_context", ""),
        "is_veto": is_veto,
        "allowed": allowed,
        "gate_reason": gate_reason,
        "would_have_traded": would_have_traded,
        "model": model,
        "size_multiplier": entry.get("size_multiplier"),
    }


def _ts_to_iso(ts) -> Optional[str]:
    try:
        import datetime
        return datetime.datetime.utcfromtimestamp(float(ts)).isoformat() + "Z"
    except Exception:
        return None


@router.get("/feed")
def get_llm_feed(limit: int = Query(default=20, ge=1, le=100)):
    """
    Returns the last N LLM advisory decisions, newest first.
    Use this to show users what the LLM would have traded.
    """
    raw = _tail_jsonl(_DECISIONS_PATH, limit)
    # Filter to real decisions (skip error/validation_failed entries)
    meaningful = [e for e in raw if e.get("action") not in ("api_error", "validation_failed", "sanitization_failed")]
    return {
        "items": [_format_entry(e) for e in meaningful],
        "total": len(meaningful),
        "path": _DECISIONS_PATH,
        "has_data": len(meaningful) > 0,
    }


@router.get("/latest")
def get_latest_decision():
    """Returns the single most recent meaningful LLM decision."""
    raw = _tail_jsonl(_DECISIONS_PATH, 10)
    for entry in raw:
        if entry.get("action") not in ("api_error", "validation_failed", "sanitization_failed"):
            return {"item": _format_entry(entry), "has_data": True}
    return {"item": None, "has_data": False}


@router.get("/market-view")
def get_market_view():
    """
    Aggregated market view: most recent regime, per-symbol LLM stance, and
    a rolling summary of the last hour of decisions.
    """
    raw = _tail_jsonl(_DECISIONS_PATH, 50)
    meaningful = [e for e in raw if e.get("action") not in ("api_error", "validation_failed", "sanitization_failed")]

    if not meaningful:
        return {
            "has_data": False,
            "regime": "unknown",
            "overall_bias": "neutral",
            "per_symbol": {},
            "last_updated": None,
            "summary": "No LLM decisions recorded yet. Start the bot with LLM_MODE=1.",
        }

    # Most recent regime
    current_regime = meaningful[0].get("regime", "unknown")
    latest_ts = meaningful[0].get("ts", 0)

    # Per-symbol: most recent decision per unique symbol
    per_symbol: dict = {}
    for entry in meaningful:
        sym = _extract_symbol(entry)
        if sym and sym not in per_symbol:
            per_symbol[sym] = _format_entry(entry)

    # Overall bias from last 10 decisions
    recent_10 = meaningful[:10]
    proceed_count = sum(1 for e in recent_10 if e.get("action") in ("proceed", "go"))
    flat_count = sum(1 for e in recent_10 if e.get("action") in ("flat", "skip"))
    flip_count = sum(1 for e in recent_10 if e.get("action") == "flip")
    total_10 = len(recent_10) or 1

    if proceed_count / total_10 >= 0.6:
        overall_bias = "bullish"
    elif flat_count / total_10 >= 0.6:
        overall_bias = "neutral"
    elif flip_count / total_10 >= 0.3:
        overall_bias = "volatile"
    else:
        overall_bias = "mixed"

    # Human-readable summary from most recent notes
    recent_notes = [e.get("notes", "") for e in meaningful[:3] if e.get("notes")]
    summary = recent_notes[0] if recent_notes else f"Regime: {current_regime}. {proceed_count}/{total_10} recent decisions were to trade."

    # Average confidence of recent decisions
    confidences = [float(e.get("confidence") or 0) for e in recent_10 if e.get("confidence") is not None]
    avg_confidence = round(sum(confidences) / len(confidences), 3) if confidences else None

    return {
        "has_data": True,
        "regime": current_regime,
        "overall_bias": overall_bias,
        "avg_confidence": avg_confidence,
        "per_symbol": per_symbol,
        "last_updated": _ts_to_iso(latest_ts),
        "summary": summary,
        "decision_counts": {
            "proceed": proceed_count,
            "flat": flat_count,
            "flip": flip_count,
            "total_recent": total_10,
        },
    }
