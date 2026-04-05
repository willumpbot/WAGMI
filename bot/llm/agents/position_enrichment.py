"""
Position state enrichment for LLM agents.
Transforms raw position data into rich context including
state machine phase, MFE/MAE tracking, thesis validity signals.
"""
from datetime import datetime, timezone
from typing import Dict, Any


def _pct(a: float, b: float) -> float:
    return (a - b) / b * 100 if b else 0.0


def _fmt_price(price: float) -> str:
    if price >= 10_000: return f"${price/1000:.1f}k"
    if price >= 100: return f"${price:.0f}"
    if price >= 1: return f"${price:.2f}"
    return f"${price:.4f}"


def _extract_thesis(notes: str) -> str:
    if not notes: return "none"
    for line in notes.split("\n"):
        if "THESIS:" in line.upper():
            t = line.split(":", 1)[1].strip()
            return t[:60]
    return notes[:60]


def _health_score(dist_sl: float, hold_h: float, mfe: float,
                  upnl: float, trailing: bool, expected_hold: str) -> int:
    """Composite 0-100: SL distance + time pressure + MFE retention + momentum."""
    # SL distance (0-25): >2% = full
    s1 = min(25, max(0, dist_sl * 12.5))
    # Time pressure (0-25)
    exp_h = {"very_short": 1, "short": 4, "medium": 12, "long": 48}.get(expected_hold, 8)
    tr = hold_h / max(exp_h, 0.1)
    s2 = 25 if tr <= 1 else (25 - (tr - 1) * 15 if tr <= 2 else max(0, 10 - (tr - 2) * 5))
    # MFE retention (0-25)
    s3 = max(0, min(25, (upnl / mfe) * 25)) if mfe > 0 else 12
    # Momentum (0-25)
    s4 = 25 if upnl >= 1 else (15 + upnl * 10 if upnl >= 0 else max(0, 15 + upnl * 7.5))
    return int(min(100, s1 + s2 + s3 + s4 + (5 if trailing else 0)))


def enrich_position(position, current_price: float, current_time=None) -> Dict[str, Any]:
    """Enrich a position with computed metrics for LLM context."""
    if current_time is None:
        current_time = datetime.now(timezone.utc)
    p, entry, is_long = position, position.entry, position.side == "LONG"

    # Timing
    opened = getattr(p, "opened_at", None) or getattr(p, "open_time", current_time)
    if isinstance(opened, str):
        try: opened = datetime.fromisoformat(opened)
        except (ValueError, TypeError): opened = current_time
    if opened.tzinfo is None:
        opened = opened.replace(tzinfo=timezone.utc)
    hold_hours = max(0, (current_time - opened).total_seconds() / 3600)

    # Unrealised P&L
    upnl_pct = _pct(current_price, entry) if is_long else _pct(entry, current_price)
    notional = entry * getattr(p, "qty", 0)
    upnl_dollar = notional * (upnl_pct / 100) if notional else 0

    # MFE / MAE
    highest = max(getattr(p, "highest_price", entry) or entry, current_price)
    lowest = min(getattr(p, "lowest_price", entry) or entry, current_price)
    if is_long:
        mfe_pct, mae_pct = _pct(highest, entry), _pct(entry, lowest)
    else:
        mfe_pct, mae_pct = _pct(entry, lowest), _pct(highest, entry)
    current_vs_mfe = mfe_pct - abs(upnl_pct) if mfe_pct > 0 else 0

    # Risk distances
    sl, tp1, tp2 = (getattr(p, k, 0) or 0 for k in ("sl", "tp1", "tp2"))
    dist_sl = abs(_pct(current_price, sl)) if sl else 99
    dist_tp1 = abs(_pct(tp1, current_price)) if tp1 else 0
    dist_tp2 = abs(_pct(tp2, current_price)) if tp2 else 0

    # Trailing
    trailing_active = getattr(p, "trailing_active", False)
    trail_dist = getattr(p, "trailing_distance", 0) or 0
    peak = getattr(p, "peak_price", 0) or 0
    # Trailing stop level = peak - distance (long) or peak + distance (short)
    if trail_dist and peak:
        trail_stop = (peak - trail_dist) if is_long else (peak + trail_dist)
        trail_dist_pct = abs(_pct(current_price, trail_stop)) if trail_stop else 0
    else:
        trail_stop = 0
        trail_dist_pct = 0

    # Trade profile
    profile = getattr(p, "trade_profile", None)
    entry_reasons = getattr(profile, "entry_reasons", []) if profile else []
    expected_hold = getattr(profile, "expected_holding_time", "medium") if profile else "medium"
    entry_type = getattr(profile, "entry_type", "MEDIUM") if profile else "MEDIUM"

    # Funding
    funding = getattr(p, "funding_costs", 0) or 0
    funding_dir = "receiving" if funding < 0 else ("paying" if funding > 0 else "none")

    # State
    state = getattr(p, "state", "OPEN")
    state_path = getattr(p, "state_path_str", state) if hasattr(p, "state_path_str") else state

    # Health
    health = _health_score(dist_sl, hold_hours, mfe_pct, upnl_pct,
                           trailing_active, expected_hold)

    r = lambda v, n=2: round(v, n)
    return {
        "symbol": p.symbol, "side": p.side, "entry": entry,
        "sl": sl, "tp1": tp1, "tp2": tp2,
        "leverage": getattr(p, "leverage", 1.0) or 1.0,
        "qty": getattr(p, "qty", 0), "entry_type": entry_type,
        "state": state, "state_path": state_path,
        "hold_hours": r(hold_hours, 1), "expected_hold": expected_hold,
        "upnl_pct": r(upnl_pct), "upnl_dollar": r(upnl_dollar),
        "realized_partial": r(getattr(p, "realized_pnl", 0) or 0),
        "tp1_hit": getattr(p, "filled_tp1", False),
        "mfe_pct": r(mfe_pct), "mae_pct": r(mae_pct),
        "current_vs_mfe": r(current_vs_mfe),
        "trailing_active": trailing_active,
        "trail_stop": r(trail_stop, 4), "trail_distance_pct": r(trail_dist_pct),
        "dist_to_sl_pct": r(dist_sl), "dist_to_tp1_pct": r(dist_tp1),
        "dist_to_tp2_pct": r(dist_tp2),
        "funding_total": r(funding, 4), "funding_direction": funding_dir,
        "entry_reasons": entry_reasons,
        "setup_type": getattr(p, "setup_type", "") or "",
        "original_confidence": r(getattr(p, "confidence", 0) or 0, 1),
        "thesis": _extract_thesis(getattr(p, "notes", "") or ""),
        "health": health,
    }


def format_positions_for_agent(positions: Dict, prices: Dict, current_time=None) -> str:
    """Format all open positions as compact text for agent context (~150 tokens/3 pos)."""
    if not positions:
        return "NO OPEN POSITIONS"
    lines = []
    for symbol, pos in positions.items():
        price = prices.get(symbol, getattr(pos, "entry", 0))
        e = enrich_position(pos, price, current_time)
        lev = f"{e['leverage']:.0f}x " if e["leverage"] > 1 else ""
        lines.append(
            f"POS {e['symbol']} {e['side']} {lev}@ {_fmt_price(e['entry'])} "
            f"| {e['state']} | hold={e['hold_hours']:.1f}h "
            f"| uPnL={e['upnl_pct']:+.1f}% "
            f"| MFE={e['mfe_pct']:+.1f}% MAE=-{e['mae_pct']:.1f}%"
        )
        parts = []
        if e["trailing_active"] and e["trail_stop"]:
            parts.append(f"trail={_fmt_price(e['trail_stop'])}({e['trail_distance_pct']:.1f}% away)")
        parts.append(f"SL={_fmt_price(e['sl'])}({e['dist_to_sl_pct']:.1f}%)")
        if not e["tp1_hit"]:
            parts.append(f"TP1={_fmt_price(e['tp1'])}({e['dist_to_tp1_pct']:.1f}%)")
        parts.append(f"TP2={_fmt_price(e['tp2'])}")
        if e["funding_direction"] != "none":
            parts.append(f"funding={e['funding_total']:+.2f}({e['funding_direction']})")
        else:
            parts.append("no funding data")
        lines.append("  " + " | ".join(parts))
        lines.append(f"  health={e['health']}/100 | thesis=\"{e['thesis']}\"")
    return "\n".join(lines)
