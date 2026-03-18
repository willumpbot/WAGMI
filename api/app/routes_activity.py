"""Activity feed API — merged view of LLM decisions and missed trades."""
import os
import json
import datetime
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Query

from .utils_jsonl import tail_jsonl

router = APIRouter(prefix="/v1/activity", tags=["activity"])

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_DECISIONS_PATH = os.environ.get(
    "LLM_DECISIONS_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", "bot", "data", "llm", "decisions.jsonl"),
)
_MISSED_TRADES_PATH = os.environ.get(
    "MISSED_TRADES_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", "bot", "data", "missed_trades.jsonl"),
)

# ---------------------------------------------------------------------------
# System-event actions to skip (not useful to traders)
# ---------------------------------------------------------------------------
_SKIP_ACTIONS = {
    "api_error",
    "validation_failed",
    "sanitization_failed",
    "multi_agent_decision",
    "ensemble_vote",
}

# ---------------------------------------------------------------------------
# Badge definitions
# ---------------------------------------------------------------------------
_BADGES: Dict[str, Dict[str, str]] = {
    "llm_would_trade":   {"badge": "WOULD TRADE", "color": "#16a34a"},
    "llm_veto":          {"badge": "AI VETO",     "color": "#dc2626"},
    "llm_skip":          {"badge": "SKIP",         "color": "#6b7280"},
    "llm_flip":          {"badge": "FLIP",         "color": "#7c3aed"},
    "llm_regime":        {"badge": "REGIME",       "color": "#2563eb"},
    "signal_blocked":    {"badge": "BLOCKED",      "color": "#ea580c"},
    "signal_blocked_miss": {"badge": "MISSED",     "color": "#b91c1c"},
}

# ---------------------------------------------------------------------------
# Scalp insight templates
# ---------------------------------------------------------------------------
_REGIME_TIPS: Dict[str, str] = {
    "trend":             "Scalp in trend direction only. Buy dips, don't fade moves.",
    "range":             "Fade extremes — buy near support, sell near resistance.",
    "panic":             "High risk. Very small size, no overnight holds.",
    "high_volatility":   "Wide spreads, fast moves. Tight SL, take profits quickly.",
    "low_liquidity":     "Thin market. Reduce size, expect slippage.",
    "news_dislocation":  "News-driven move. Wait for dust to settle before scalping.",
}


def _fmt_price(val) -> Optional[str]:
    """Format a price value as $X.XX, or None if value is missing/invalid."""
    try:
        return f"${float(val):.2f}"
    except (TypeError, ValueError):
        return None


def _make_scalp_insight(
    event_type: str,
    entry_data: dict,
    regime: Optional[str],
    symbol: Optional[str],
) -> str:
    """Generate a 1-2 sentence scalp insight for a given activity event."""
    side = entry_data.get("side", "")
    confidence = entry_data.get("confidence")
    conf_str = f"{int(round(float(confidence)))}%" if confidence is not None else "?"
    notes = entry_data.get("notes") or ""
    gate = entry_data.get("gate") or "unknown"
    reason = entry_data.get("reason") or ""

    entry_price = _fmt_price(entry_data.get("entry"))
    sl_price = _fmt_price(entry_data.get("sl"))
    tp1_raw = entry_data.get("tp1")
    tp1_price = _fmt_price(tp1_raw)

    regime_tip = _REGIME_TIPS.get(regime or "", "Wait for a clearer setup.")

    if event_type == "llm_would_trade":
        # tp_scalp = entry + (tp1 - entry) * 0.4
        tp_scalp_str: Optional[str] = None
        try:
            e_val = float(entry_data.get("entry"))
            t_val = float(tp1_raw)
            tp_scalp_str = _fmt_price(e_val + (t_val - e_val) * 0.4)
        except (TypeError, ValueError):
            pass
        side_str = side.lower() if side else "here"
        parts = [f"Bot would {side_str} here ({conf_str} confidence)."]
        if entry_price and sl_price and tp_scalp_str:
            parts.append(f"Quick scalp: entry ~{entry_price}, SL {sl_price}, TP {tp_scalp_str} (40% of TP1 distance).")
        return " ".join(parts)

    elif event_type == "llm_veto":
        notes_short = notes[:60] if notes else "uncertain setup"
        side_str = side.lower() if side else "this"
        return f"AI said no. Avoid {side_str} here — {notes_short}. Wait for setup to change."

    elif event_type == "llm_skip":
        return f"{regime_tip} Bot waiting for better conditions."

    elif event_type == "llm_flip":
        new_dir = side.lower() if side else "new direction"
        return f"Direction reversed to {new_dir}. Scalp: small size, confirm with 2-3 candles, tight SL."

    elif event_type == "llm_regime":
        regime_str = regime or "unknown"
        tip = _REGIME_TIPS.get(regime_str, "Adjust your strategy.")
        return f"Market entered {regime_str} mode. {tip}"

    elif event_type == "signal_blocked":
        side_str = side if side else "a"
        tp1_str = tp1_price or "—"
        entry_str = entry_price or "—"
        sl_str = sl_price or "—"
        return (
            f"Bot had a {side_str} setup — {gate} gate blocked it. "
            f"Levels: entry {entry_str}, SL {sl_str}, TP1 {tp1_str}. Trade it if you agree."
        )

    elif event_type == "signal_blocked_miss":
        side_str = side if side else "this"
        hit_tp = entry_data.get("hit_tp") or "TP"
        entry_str = entry_price or "—"
        sl_str = sl_price or "—"
        return (
            f"This {side_str} setup would have hit {hit_tp}. "
            f"{gate} blocked the bot. Next similar setup: entry near {entry_str}, SL {sl_str}."
        )

    return "No insight available."


# ---------------------------------------------------------------------------
# Symbol extraction (mirrors routes_llm.py logic)
# ---------------------------------------------------------------------------
def _extract_symbol(entry: dict) -> Optional[str]:
    ctx = entry.get("trigger_context", "")
    if ctx:
        parts = ctx.strip().split()
        if parts:
            sym = parts[0].upper().replace("USDT", "").replace("USD", "").replace("PERP", "")
            if 2 <= len(sym) <= 6 and sym.isalpha():
                return sym
    snap = entry.get("snapshot", {})
    if isinstance(snap, dict):
        sym = snap.get("symbol") or snap.get("market", "")
        if sym:
            cleaned = str(sym).upper().replace("USDT", "").replace("USD", "").replace("PERP", "")
            if 2 <= len(cleaned) <= 6 and cleaned.isalpha():
                return cleaned
    return None


def _ts_to_iso(ts) -> Optional[str]:
    try:
        return datetime.datetime.utcfromtimestamp(float(ts)).isoformat() + "Z"
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Decision entry → ActivityEvent
# ---------------------------------------------------------------------------
def _decision_to_event(entry: dict, prev_regime: Optional[str]) -> Optional[dict]:
    """Convert a decisions.jsonl entry to an ActivityEvent dict.

    Returns None if the entry should be skipped.
    Returns a tuple (event_dict, new_regime) where new_regime may differ.
    """
    action = entry.get("action", "unknown")
    if action in _SKIP_ACTIONS:
        return None

    is_veto = bool(entry.get("is_veto"))
    regime = entry.get("regime") or "unknown"
    confidence = entry.get("confidence")
    notes = entry.get("notes") or ""
    mode = entry.get("mode", "UNKNOWN")
    ts = entry.get("ts", 0)
    symbol = _extract_symbol(entry)

    # Determine event type
    if is_veto:
        event_type = "llm_veto"
    elif action in ("proceed", "go"):
        event_type = "llm_would_trade"
    elif action == "flip":
        event_type = "llm_flip"
    elif action in ("flat", "skip"):
        if prev_regime is not None and regime != prev_regime:
            event_type = "llm_regime"
        else:
            event_type = "llm_skip"
    elif prev_regime is not None and regime != prev_regime:
        event_type = "llm_regime"
    else:
        event_type = "llm_skip"

    # Also emit regime event when regime changes on any action type
    # (handled by checking prev_regime above for non-veto, non-proceed)

    # Extract trade-level fields
    snap = entry.get("snapshot", {}) or {}
    side = entry.get("side") or (snap.get("side") if isinstance(snap, dict) else None) or ""
    entry_price = entry.get("entry") or (snap.get("entry") if isinstance(snap, dict) else None)
    sl = entry.get("sl") or (snap.get("sl") if isinstance(snap, dict) else None)
    tp1 = entry.get("tp1") or (snap.get("tp1") if isinstance(snap, dict) else None)
    tp2 = entry.get("tp2") or (snap.get("tp2") if isinstance(snap, dict) else None)

    # Build title
    sym_label = symbol or "?"
    direction = side.upper() if side else ""
    if event_type == "llm_would_trade":
        title = f"{sym_label} — LLM would trade {direction}" if direction else f"{sym_label} — LLM would trade"
    elif event_type == "llm_veto":
        title = f"{sym_label} — AI VETO"
    elif event_type == "llm_skip":
        title = f"{sym_label} — LLM skip"
    elif event_type == "llm_flip":
        title = f"{sym_label} — Direction flip to {direction}" if direction else f"{sym_label} — Direction flip"
    elif event_type == "llm_regime":
        title = f"Regime change → {regime}"
    else:
        title = f"{sym_label} — {event_type}"

    # Build detail line
    conf_part = f"{int(round(float(confidence)))}% confidence" if confidence is not None else ""
    regime_part = f"Regime: {regime}"
    mode_part = mode
    detail_parts = [p for p in [conf_part, regime_part, mode_part] if p]
    detail = " • ".join(detail_parts)

    # entry_data for insight generation
    entry_data = {
        "side": side,
        "entry": entry_price,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "confidence": confidence,
        "notes": notes,
    }

    scalp_insight = _make_scalp_insight(event_type, entry_data, regime, symbol)
    badge_info = _BADGES.get(event_type, {"badge": event_type.upper(), "color": "#6b7280"})

    return {
        "ts": float(ts) if ts else 0.0,
        "ts_iso": _ts_to_iso(ts),
        "event_type": event_type,
        "symbol": symbol,
        "title": title,
        "detail": detail,
        "scalp_insight": scalp_insight,
        "badge": badge_info["badge"],
        "badge_color": badge_info["color"],
        "data": {
            "entry": entry_price,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "confidence": confidence,
            "regime": regime,
            "side": side,
            "notes": notes,
            "mode": mode,
            "action": action,
            "is_veto": is_veto,
        },
    }


# ---------------------------------------------------------------------------
# Missed trades entry → ActivityEvent
# ---------------------------------------------------------------------------
def _missed_trade_to_event(entry: dict) -> Optional[dict]:
    """Convert a missed_trades.jsonl entry to an ActivityEvent dict."""
    try:
        ts_raw = entry.get("ts") or entry.get("timestamp") or ""
        if ts_raw:
            ts = datetime.datetime.fromisoformat(str(ts_raw).rstrip("Z")).timestamp()
        else:
            ts = 0.0
    except Exception:
        ts = 0.0

    counterfactual = entry.get("counterfactual", {}) or {}
    if_traded = counterfactual.get("if_traded")

    if if_traded is True:
        event_type = "signal_blocked_miss"
    else:
        event_type = "signal_blocked"

    symbol = entry.get("symbol") or entry.get("asset")
    if symbol:
        symbol = str(symbol).upper().replace("USDT", "").replace("USD", "").replace("PERP", "")
        if not (2 <= len(symbol) <= 6 and symbol.isalpha()):
            symbol = None

    side = entry.get("side") or entry.get("direction") or ""
    entry_price = entry.get("entry") or entry.get("entry_price")
    sl = entry.get("sl") or entry.get("stop_loss")
    tp1 = entry.get("tp1") or entry.get("take_profit")
    tp2 = entry.get("tp2")
    gate = entry.get("gate") or entry.get("blocked_by") or "unknown"
    reason = entry.get("reason") or ""
    hit_tp = counterfactual.get("hit_tp") or counterfactual.get("result") or "TP"

    sym_label = symbol or "?"
    direction = side.upper() if side else ""
    if event_type == "signal_blocked_miss":
        title = f"{sym_label} — Missed {direction} setup" if direction else f"{sym_label} — Missed setup"
    else:
        title = f"{sym_label} — Blocked {direction} setup" if direction else f"{sym_label} — Blocked setup"

    detail_parts = [p for p in [f"Gate: {gate}", f"Side: {direction}" if direction else ""] if p]
    detail = " • ".join(detail_parts)

    entry_data = {
        "side": side,
        "entry": entry_price,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "gate": gate,
        "reason": reason,
        "hit_tp": hit_tp,
    }
    scalp_insight = _make_scalp_insight(event_type, entry_data, None, symbol)
    badge_info = _BADGES[event_type]

    return {
        "ts": ts,
        "ts_iso": _ts_to_iso(ts) if ts else None,
        "event_type": event_type,
        "symbol": symbol,
        "title": title,
        "detail": detail,
        "scalp_insight": scalp_insight,
        "badge": badge_info["badge"],
        "badge_color": badge_info["color"],
        "data": {
            "entry": entry_price,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "side": side,
            "gate": gate,
            "reason": reason,
            "if_traded": if_traded,
            "hit_tp": hit_tp,
        },
    }


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------
@router.get("/feed")
def get_activity_feed(limit: int = Query(default=30, ge=1, le=200)):
    """
    Returns the last N merged activity events from LLM decisions and missed trades,
    sorted newest first.
    """
    # --- Read decisions ---
    # Read a generous batch so we have enough after filtering
    raw_decisions = tail_jsonl(_DECISIONS_PATH, limit * 3)

    decision_events: List[dict] = []
    prev_regime: Optional[str] = None

    # raw_decisions is newest-first; iterate newest-first to detect regime changes
    # (compare each entry's regime to the one we saw most recently = the one before it)
    # We need oldest-first for regime tracking, then reverse at the end.
    for entry in reversed(raw_decisions):
        event = _decision_to_event(entry, prev_regime)
        if event is not None:
            decision_events.append(event)
        # Update prev_regime regardless (even for skipped entries)
        regime_now = entry.get("regime") or "unknown"
        if regime_now and regime_now != "unknown":
            prev_regime = regime_now

    # decision_events is now oldest-first; reverse to newest-first
    decision_events.reverse()

    # --- Read missed trades ---
    raw_missed = tail_jsonl(_MISSED_TRADES_PATH, limit * 2)
    missed_events: List[dict] = []
    for entry in raw_missed:
        event = _missed_trade_to_event(entry)
        if event is not None:
            missed_events.append(event)

    # --- Merge and sort ---
    all_events = decision_events + missed_events
    all_events.sort(key=lambda e: e["ts"], reverse=True)
    all_events = all_events[:limit]

    return {
        "items": all_events,
        "has_data": len(all_events) > 0,
        "sources": {
            "decisions": len(decision_events),
            "missed_trades": len(missed_events),
        },
    }
