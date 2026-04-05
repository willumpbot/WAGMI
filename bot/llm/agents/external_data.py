"""
External data provider for the LLM agent network.
Reads from data collectors (funding/OI, liquidation, shadow MR) and
formats for agent context injection.

Data sources:
  - data/funding_oi_history.jsonl  (from tools/funding_oi_collector.py)
  - data/liquidation_levels.jsonl  (from tools/liquidation_tracker.py)
  - data/shadow_mr_signals.jsonl   (from tools/shadow_mr_tracker.py)
"""

import json
import os
import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("bot.llm.agents.external_data")

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")

FUNDING_FILE = os.path.join(DATA_DIR, "funding_oi_history.jsonl")
LIQ_FILE = os.path.join(DATA_DIR, "liquidation_levels.jsonl")
SHADOW_MR_FILE = os.path.join(DATA_DIR, "shadow_mr_signals.jsonl")

# Default symbols tracked by the collectors
DEFAULT_SYMBOLS = ["BTC", "ETH", "SOL", "HYPE"]


# ── Helpers ──────────────────────────────────────────────────────────

def _read_jsonl_tail(filepath: str, max_lines: int = 500) -> List[dict]:
    """Read the last N lines of a JSONL file. Returns empty list if missing."""
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, "r") as f:
            lines = f.readlines()
        tail = lines[-max_lines:] if len(lines) > max_lines else lines
        records = []
        for line in tail:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records
    except Exception as e:
        logger.warning(f"Failed to read {filepath}: {e}")
        return []


def _parse_ts(ts_str: str) -> Optional[datetime]:
    """Parse ISO-ish timestamp string to datetime."""
    if not ts_str:
        return None
    try:
        # Handle both "2026-04-03T12:00:00" and "2026-04-03T12:00:00+00:00"
        ts_str = ts_str.replace("Z", "+00:00")
        if "+" not in ts_str and ts_str.count("-") <= 2:
            # Naive timestamp — assume UTC
            return datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return None


def _age_hours(ts_str: str) -> float:
    """How many hours ago was this timestamp? Returns inf on parse failure."""
    dt = _parse_ts(ts_str)
    if not dt:
        return float("inf")
    delta = datetime.now(timezone.utc) - dt
    return delta.total_seconds() / 3600


def _fmt_usd(val: float) -> str:
    """Format USD value compactly: $1.9B, $298M, $12.3K."""
    if val >= 1e9:
        return f"${val/1e9:.1f}B"
    if val >= 1e6:
        return f"${val/1e6:.0f}M"
    if val >= 1e3:
        return f"${val/1e3:.1f}K"
    return f"${val:.0f}"


# ── Funding & OI ─────────────────────────────────────────────────────

def get_latest_funding_oi(symbols: List[str] = None) -> Dict[str, Dict]:
    """Get the most recent funding rate and OI data for each symbol.

    Returns dict keyed by symbol (e.g. "BTC") with fields:
      funding_rate, open_interest, premium, oi_volume_ratio, volume_24h, price, timestamp
    """
    symbols = symbols or DEFAULT_SYMBOLS
    records = _read_jsonl_tail(FUNDING_FILE, max_lines=200)
    if not records:
        return {}

    latest: Dict[str, Dict] = {}
    for r in records:
        sym = r.get("symbol", "")
        if symbols and sym not in symbols:
            continue
        # Keep overwriting — last record wins (file is chronological)
        latest[sym] = r

    # Filter out stale data (>2 hours old)
    result = {}
    for sym, r in latest.items():
        ts = r.get("timestamp", "")
        if _age_hours(ts) > 2:
            logger.debug(f"Skipping stale funding data for {sym}: {ts}")
            continue
        result[sym] = r
    return result


def get_funding_trend(symbol: str, hours: int = 8) -> Dict:
    """Get funding rate trend over the last N hours.

    Returns:
      avg_rate: average funding rate over the period
      direction: "rising" | "falling" | "stable"
      extreme_count: number of readings with |rate| > 0.0001
      annualized_pct: annualized rate as percentage
      samples: number of data points used
    """
    records = _read_jsonl_tail(FUNDING_FILE, max_lines=500)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    sym_records = []
    for r in records:
        if r.get("symbol") != symbol:
            continue
        dt = _parse_ts(r.get("timestamp", ""))
        if dt and dt >= cutoff:
            sym_records.append(r)

    if len(sym_records) < 2:
        return {"avg_rate": 0, "direction": "unknown", "extreme_count": 0,
                "annualized_pct": 0, "samples": len(sym_records)}

    rates = [r.get("funding_rate", 0) for r in sym_records]
    avg_rate = sum(rates) / len(rates)
    extreme_count = sum(1 for r in rates if abs(r) > 0.0001)

    # Direction: compare first half average to second half
    mid = len(rates) // 2
    first_half = sum(rates[:mid]) / max(mid, 1)
    second_half = sum(rates[mid:]) / max(len(rates) - mid, 1)
    diff = second_half - first_half

    if abs(diff) < 1e-6:
        direction = "stable"
    elif diff > 0:
        direction = "rising"
    else:
        direction = "falling"

    annualized_pct = avg_rate * 24 * 365 * 100

    return {
        "avg_rate": avg_rate,
        "direction": direction,
        "extreme_count": extreme_count,
        "annualized_pct": round(annualized_pct, 1),
        "samples": len(sym_records),
    }


def get_oi_trend(symbol: str, hours: int = 4) -> Dict:
    """Get OI change trend — is money flowing in or out?

    Returns:
      direction: "rising" | "falling" | "stable"
      change_pct: percentage change over period
      latest_oi: most recent OI value
      magnitude: "strong" | "moderate" | "flat"
    """
    records = _read_jsonl_tail(FUNDING_FILE, max_lines=300)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    sym_records = []
    for r in records:
        if r.get("symbol") != symbol:
            continue
        dt = _parse_ts(r.get("timestamp", ""))
        if dt and dt >= cutoff:
            sym_records.append(r)

    if len(sym_records) < 2:
        return {"direction": "unknown", "change_pct": 0, "latest_oi": 0, "magnitude": "flat"}

    first_oi = sym_records[0].get("open_interest", 0)
    last_oi = sym_records[-1].get("open_interest", 0)

    if first_oi <= 0:
        change_pct = 0
    else:
        change_pct = (last_oi - first_oi) / first_oi * 100

    if change_pct > 3:
        direction, magnitude = "rising", "strong"
    elif change_pct > 1:
        direction, magnitude = "rising", "moderate"
    elif change_pct < -3:
        direction, magnitude = "falling", "strong"
    elif change_pct < -1:
        direction, magnitude = "falling", "moderate"
    else:
        direction, magnitude = "stable", "flat"

    return {
        "direction": direction,
        "change_pct": round(change_pct, 2),
        "latest_oi": last_oi,
        "magnitude": magnitude,
    }


# ── Liquidation Levels ───────────────────────────────────────────────

def get_liquidation_levels(symbol: str) -> Dict:
    """Get nearest liquidation clusters for a symbol.

    Returns:
      nearest_long_liq: {price, dist_pct, lev, weight}
      nearest_short_liq: {price, dist_pct, lev, weight}
      oi_trend: str
      bias: str
      drift: str or None
      magnetic: bool
      price: current price
      timestamp: when recorded
    """
    records = _read_jsonl_tail(LIQ_FILE, max_lines=200)
    if not records:
        return {}

    # Find latest record for this symbol
    latest = None
    for r in records:
        if r.get("sym") == symbol:
            latest = r

    if not latest:
        return {}

    # Skip stale data (>15 min for liq data)
    ts = latest.get("ts", "")
    if _age_hours(ts) > 0.5:  # 30 min staleness for liq levels
        logger.debug(f"Skipping stale liq data for {symbol}: {ts}")
        return {}

    return {
        "nearest_long_liq": latest.get("nearest_long", {}),
        "nearest_short_liq": latest.get("nearest_short", {}),
        "oi_trend": latest.get("oi_trend", ""),
        "bias": latest.get("bias", ""),
        "drift": latest.get("drift"),
        "magnetic": latest.get("magnetic", False),
        "price": latest.get("price", 0),
        "timestamp": ts,
    }


# ── Shadow Mean-Reversion ────────────────────────────────────────────

def get_shadow_mr_signals(hours: int = 24) -> List[Dict]:
    """Get recent shadow mean-reversion signals and their outcomes.

    Returns list of dicts with:
      signal, short_sym, price, rsi, consec_bars, timestamp, outcomes
    Only returns signals from the last N hours.
    """
    records = _read_jsonl_tail(SHADOW_MR_FILE, max_lines=200)
    if not records:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    recent = []
    for r in records:
        dt = _parse_ts(r.get("timestamp", ""))
        if dt and dt >= cutoff:
            recent.append({
                "signal": r.get("signal", ""),
                "short_sym": r.get("short_sym", ""),
                "price": r.get("price", 0),
                "rsi": r.get("rsi", 50),
                "consec_bars": r.get("consec_bars", 0),
                "timestamp": r.get("timestamp", ""),
                "outcomes": r.get("outcomes", {}),
            })
    return recent


def _mr_summary_stats(signals: List[Dict]) -> Dict:
    """Compute win rate and avg PnL from shadow MR signals."""
    wins, losses, total_pnl = 0, 0, 0
    for s in signals:
        outcomes = s.get("outcomes", {})
        # Use 2h outcome as the primary metric
        for h_key in ("2h", "1h", "4h"):
            o = outcomes.get(h_key)
            if o and "pnl_pct" in o:
                pnl = o["pnl_pct"]
                total_pnl += pnl
                if pnl > 0:
                    wins += 1
                else:
                    losses += 1
                break  # only count once per signal
    total = wins + losses
    return {
        "total_signals": len(signals),
        "resolved": total,
        "win_rate": round(wins / total * 100, 0) if total > 0 else 0,
        "avg_pnl_pct": round(total_pnl / total, 3) if total > 0 else 0,
    }


# ── Main Formatter ───────────────────────────────────────────────────

def format_for_agent(symbols: List[str] = None) -> str:
    """Format all external data as compact text for agent context.

    Target: ~200 tokens covering all symbols.
    Returns empty string if no data available.

    Example output:
    FUNDING: BTC=-0.001%/h(shorts_paid) ETH=+0.001%/h(longs_paid) SOL=-0.0005%/h
    OI: BTC=$1.9B(flat) ETH=$1.1B(rising+2.3%) HYPE=$763M(falling-4.1%) HYPE_OI/VOL=6.8x(CROWDED)
    LIQ: BTC long_liq=$64.2k(3.8%dn) short_liq=$69.5k(3.9%up) | SOL long_liq=$76.2(4.8%dn)
    MR_SHADOW: 2 signals (BTC_BUY@RSI28 +0.3%@2h, SOL_SELL@RSI74 pending)
    """
    symbols = symbols or DEFAULT_SYMBOLS
    parts = []

    # ── Funding line ──
    latest = get_latest_funding_oi(symbols)
    if latest:
        funding_parts = []
        for sym in symbols:
            data = latest.get(sym)
            if not data:
                continue
            fr = data.get("funding_rate", 0)
            payer = "longs_pay" if fr > 0 else "shorts_pay" if fr < 0 else "neutral"
            funding_parts.append(f"{sym}={fr:+.5f}/h({payer})")
        if funding_parts:
            parts.append("FUNDING: " + " ".join(funding_parts))

    # ── OI line ──
    if latest:
        oi_parts = []
        for sym in symbols:
            data = latest.get(sym)
            if not data:
                continue
            oi = data.get("open_interest", 0)
            oi_trend = get_oi_trend(sym, hours=4)
            direction = oi_trend.get("direction", "?")
            change = oi_trend.get("change_pct", 0)
            oi_str = _fmt_usd(oi)

            suffix = f"{direction}"
            if abs(change) >= 1:
                suffix += f"{change:+.1f}%"
            oi_parts.append(f"{sym}={oi_str}({suffix})")

            # Flag crowded OI/Volume ratio
            oi_vol = data.get("oi_volume_ratio", 0)
            if oi_vol > 5:
                oi_parts.append(f"{sym}_OI/VOL={oi_vol:.1f}x(CROWDED)")
        if oi_parts:
            parts.append("OI: " + " ".join(oi_parts))

    # ── Liquidation line ──
    liq_parts = []
    for sym in symbols:
        liq = get_liquidation_levels(sym)
        if not liq:
            continue
        nl = liq.get("nearest_long_liq", {})
        ns = liq.get("nearest_short_liq", {})
        if not nl and not ns:
            continue
        sym_parts = [sym]
        if nl:
            sym_parts.append(f"L-liq=${nl.get('price', 0):,.0f}({nl.get('dist_pct', 0):.1f}%dn)")
        if ns:
            sym_parts.append(f"S-liq=${ns.get('price', 0):,.0f}({ns.get('dist_pct', 0):.1f}%up)")
        if liq.get("drift"):
            sym_parts.append(f"DRIFT:{liq['drift']}")
        if liq.get("magnetic"):
            sym_parts.append("MAGNETIC!")
        liq_parts.append(" ".join(sym_parts))
    if liq_parts:
        parts.append("LIQ: " + " | ".join(liq_parts))

    # ── Shadow MR line ──
    mr_signals = get_shadow_mr_signals(hours=24)
    if mr_signals:
        stats = _mr_summary_stats(mr_signals)
        active = [s for s in mr_signals if not s.get("outcomes")]
        resolved = [s for s in mr_signals if s.get("outcomes")]

        signal_strs = []
        # Show most recent signals (up to 4)
        for s in mr_signals[-4:]:
            tag = f"{s['short_sym']}_{s['signal']}@RSI{s['rsi']:.0f}"
            outcomes = s.get("outcomes", {})
            # Show best available outcome
            for h_key in ("2h", "1h", "4h"):
                o = outcomes.get(h_key)
                if o and "pnl_pct" in o:
                    tag += f" {o['pnl_pct']:+.2f}%@{h_key}"
                    break
            else:
                if not outcomes:
                    tag += " pending"
            signal_strs.append(tag)

        wr_str = f" WR={stats['win_rate']:.0f}%" if stats["resolved"] > 0 else ""
        parts.append(f"MR_SHADOW: {stats['total_signals']} signals{wr_str} ({', '.join(signal_strs)})")
    else:
        parts.append("MR_SHADOW: 0 signals (no extremes)")

    if not parts:
        return ""

    return "\n".join(parts)


def get_external_data_for_snapshot(symbols: List[str] = None) -> Dict:
    """Get structured external data suitable for snapshot injection.

    Returns a dict that can be merged into the LLM snapshot:
      ext_funding: {sym: {rate, oi, premium, oi_vol_ratio}} per symbol
      ext_liq: {sym: {long_liq, short_liq, drift, magnetic}} per symbol
      ext_mr: {total, win_rate, active_signals: [...]}
      ext_summary: compact text string (the format_for_agent output)
    """
    symbols = symbols or DEFAULT_SYMBOLS
    result = {}

    # Funding data
    latest = get_latest_funding_oi(symbols)
    if latest:
        ext_funding = {}
        for sym, data in latest.items():
            ext_funding[sym] = {
                "rate": data.get("funding_rate", 0),
                "oi": data.get("open_interest", 0),
                "premium": data.get("premium", 0),
                "oi_vol": data.get("oi_volume_ratio", 0),
                "vol_24h": data.get("volume_24h", 0),
                "price": data.get("price", 0),
            }
        result["ext_funding"] = ext_funding

    # Liquidation data
    ext_liq = {}
    for sym in symbols:
        liq = get_liquidation_levels(sym)
        if liq:
            ext_liq[sym] = {
                "long_liq": liq.get("nearest_long_liq", {}),
                "short_liq": liq.get("nearest_short_liq", {}),
                "drift": liq.get("drift"),
                "magnetic": liq.get("magnetic", False),
                "bias": liq.get("bias", ""),
            }
    if ext_liq:
        result["ext_liq"] = ext_liq

    # Shadow MR signals
    mr_signals = get_shadow_mr_signals(hours=24)
    if mr_signals:
        stats = _mr_summary_stats(mr_signals)
        result["ext_mr"] = {
            "total": stats["total_signals"],
            "win_rate": stats["win_rate"],
            "avg_pnl": stats["avg_pnl_pct"],
            "active": [
                {"sym": s["short_sym"], "side": s["signal"], "rsi": s["rsi"],
                 "price": s["price"]}
                for s in mr_signals if not s.get("outcomes")
            ][-5:],  # Last 5 active signals
        }

    # Compact text summary
    summary = format_for_agent(symbols)
    if summary:
        result["ext_summary"] = summary

    return result
