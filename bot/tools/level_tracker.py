"""
Level Proximity Tracker — Shows how close price is to pending entry levels.

Snapshot tool (no loop). Shows:
- All pending entries with proximity to current price
- Open positions with live R:R
- Color-coded alerts based on distance

Run: cd bot && python -m tools.level_tracker
"""

import os
import sys
import json
import time
from datetime import datetime, timezone
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.fetcher import DataFetcher

# ─── Paths ────────────────────────────────────────────────────────
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "manual")
PENDING_PATH = os.path.join(DATA_DIR, "pending_entries.json")
SIM_PATH = os.path.join(DATA_DIR, "sim_status.json")

# ─── Symbols (must match alpha_hunter) ────────────────────────────
SYMBOLS = {"HYPE": "hyperliquid", "BTC": "bitcoin", "SOL": "solana", "DOGE": "dogecoin"}

# ─── ANSI colors ──────────────────────────────────────────────────
RESET = "\033[0m"
RED = "\033[91m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
CYAN = "\033[96m"
BOLD = "\033[1m"
DIM = "\033[2m"
WHITE = "\033[97m"
MAGENTA = "\033[95m"


def color_proximity(pct: float) -> str:
    """Color-code based on distance: <1% ALERT, 1-2% WATCH, >2% chill."""
    if pct < 1.0:
        return RED + BOLD
    elif pct < 2.0:
        return YELLOW
    else:
        return GREEN


def proximity_tag(pct: float) -> str:
    """Human-readable tag for proximity."""
    if pct < 0.3:
        return "IMMINENT"
    elif pct < 1.0:
        return "ALERT"
    elif pct < 2.0:
        return "WATCH"
    else:
        return "chill"


def format_price(price: float) -> str:
    """Smart price formatting based on magnitude."""
    if price >= 10000:
        return f"${price:,.0f}"
    elif price >= 100:
        return f"${price:,.2f}"
    elif price >= 1:
        return f"${price:.2f}"
    else:
        return f"${price:.4f}"


def load_pending_entries() -> list:
    """Load pending entries, filtering to active only."""
    if not os.path.exists(PENDING_PATH):
        return []
    try:
        with open(PENDING_PATH, encoding="utf-8") as f:
            data = json.load(f)
        entries = data.get("pending", [])
        # Only active entries (not invalidated/expired/triggered)
        active = [e for e in entries if e.get("status", "pending") in ("pending", "active", "watching")]
        return active
    except (json.JSONDecodeError, KeyError):
        return []


def load_positions() -> tuple:
    """Load open positions and equity from sim."""
    if not os.path.exists(SIM_PATH):
        return [], 100.0
    try:
        with open(SIM_PATH, encoding="utf-8") as f:
            sim = json.load(f)
        return sim.get("open_positions", []), sim.get("current_equity", 100.0)
    except (json.JSONDecodeError, KeyError):
        return [], 100.0


def fetch_current_prices(fetcher: DataFetcher, symbols: set) -> dict:
    """Fetch current prices for all needed symbols."""
    prices = {}
    for sym in symbols:
        coin_id = SYMBOLS.get(sym)
        if not coin_id:
            continue
        try:
            df = fetcher.fetch_ohlcv(sym, coin_id, "5m")
            if df is not None and not df.empty:
                prices[sym] = df["close"].iloc[-1]
        except Exception as e:
            print(f"  {DIM}(could not fetch {sym}: {e}){RESET}")
    return prices


def compute_rr_from_current(current: float, entry: float, sl: float, tp: float, side: str) -> tuple:
    """Compute R:R from current price perspective.

    Returns (risk_pct, reward_pct, rr_ratio).
    """
    if side == "BUY":
        risk = abs(current - sl) / current * 100
        reward = abs(tp - current) / current * 100
    else:  # SELL
        risk = abs(sl - current) / current * 100
        reward = abs(current - tp) / current * 100

    rr = reward / risk if risk > 0 else 0
    return risk, reward, rr


def format_level_line(sym: str, current: float, entry: dict) -> str:
    """Format a single pending entry proximity line."""
    target = entry.get("target_price", 0)
    side = entry.get("side", "BUY")
    sl = entry.get("sl", 0)
    tp = entry.get("tp", 0)
    tp2 = entry.get("tp2", 0)
    setup = entry.get("setup_type", "")
    entry_id = entry.get("entry_id", "")
    confidence = entry.get("confidence", 0)
    leverage = entry.get("leverage", 1)

    # Distance to target entry
    dist = abs(current - target) / current * 100
    direction = "above" if current > target else "below"

    # Color based on proximity
    clr = color_proximity(dist)
    tag = proximity_tag(dist)

    # R:R from the planned entry level
    if sl > 0 and tp > 0:
        if side == "BUY":
            risk_pts = abs(target - sl)
            reward_pts = abs(tp - target)
        else:
            risk_pts = abs(sl - target)
            reward_pts = abs(target - tp)
        rr = reward_pts / risk_pts if risk_pts > 0 else 0
        rr_str = f"R:R {rr:.1f}:1"
    else:
        rr_str = ""

    # Build trigger description
    trigger = entry.get("trigger_conditions", {})
    if isinstance(trigger, dict) and trigger:
        trigger_parts = []
        for k, v in trigger.items():
            trigger_parts.append(f"{k} {v}")
        trigger_str = " | Trigger: " + ", ".join(trigger_parts)
    elif entry.get("reasoning"):
        trigger_str = f" | {entry['reasoning'][:50]}"
    else:
        trigger_str = ""

    # Format the line
    price_str = format_price(current)
    target_str = format_price(target)

    line = (
        f"  {clr}{sym:5s}{RESET}: {WHITE}{price_str}{RESET} | "
        f"Nearest entry: {BOLD}{side} {target_str}{RESET} "
        f"({clr}{dist:.1f}% {direction}{RESET}) "
        f"[{clr}{tag}{RESET}]"
    )
    if rr_str:
        line += f" | {CYAN}{rr_str}{RESET}"
    if trigger_str:
        line += f" {DIM}{trigger_str}{RESET}"

    # Sub-line with details
    details = []
    if confidence:
        details.append(f"Conf: {confidence}")
    if leverage and leverage > 1:
        details.append(f"Lev: {leverage}x")
    if setup:
        details.append(f"Setup: {setup}")
    if entry_id:
        details.append(f"ID: {entry_id}")

    if details:
        line += f"\n         {DIM}{' | '.join(details)}{RESET}"

    return line


def format_position_line(pos: dict, current: float) -> str:
    """Format an open position with live R:R."""
    sym = pos.get("symbol", "???")
    side = pos.get("side", "BUY")
    entry = pos.get("entry", 0)
    sl = pos.get("sl", pos.get("current_sl", 0))
    tp = pos.get("tp_scalp", pos.get("tp1", 0))
    tp2 = pos.get("tp_swing", pos.get("tp2", 0))

    # PnL from entry
    if side == "BUY":
        pnl_pct = (current - entry) / entry * 100
    else:
        pnl_pct = (entry - current) / entry * 100

    pnl_clr = GREEN if pnl_pct > 0 else RED

    # R:R from current price
    risk, reward, rr = compute_rr_from_current(current, entry, sl, tp, side)

    # Distance to SL and TP
    sl_dist = abs(current - sl) / current * 100
    tp_dist = abs(tp - current) / current * 100

    price_str = format_price(current)
    entry_str = format_price(entry)
    sl_str = format_price(sl)
    tp_str = format_price(tp)

    line = (
        f"  {MAGENTA}{sym:5s}{RESET}: {WHITE}{price_str}{RESET} | "
        f"{BOLD}IN POSITION: {side} @ {entry_str}{RESET} "
        f"({pnl_clr}{pnl_pct:+.2f}%{RESET})"
    )
    line += (
        f"\n         SL {sl_str} ({RED}{sl_dist:.1f}% away{RESET}) | "
        f"TP {tp_str} ({GREEN}{tp_dist:.1f}% away{RESET}) | "
        f"Live R:R {CYAN}{rr:.1f}:1{RESET}"
    )

    if tp2 and tp2 > 0:
        tp2_str = format_price(tp2)
        tp2_dist = abs(tp2 - current) / current * 100
        line += f" | TP2 {tp2_str} ({GREEN}{tp2_dist:.1f}%{RESET})"

    return line


def format_idle_symbol(sym: str, current: float) -> str:
    """Format a symbol with no pending entries and no position."""
    price_str = format_price(current)
    return f"  {DIM}{sym:5s}: {price_str} | No pending entries{RESET}"


def run_tracker() -> str:
    """Run the level tracker and return the formatted output.

    Returns the output string (useful for integration with alpha_hunter).
    """
    fetcher = DataFetcher()
    now = datetime.now(timezone.utc)

    # Load data
    pending = load_pending_entries()
    positions, equity = load_positions()

    # Determine all symbols we need prices for
    needed_symbols = set(SYMBOLS.keys())
    for e in pending:
        needed_symbols.add(e.get("symbol", ""))
    for p in positions:
        needed_symbols.add(p.get("symbol", ""))
    needed_symbols.discard("")

    # Fetch prices
    prices = fetch_current_prices(fetcher, needed_symbols)

    if not prices:
        return "  No price data available."

    # Build symbol -> nearest pending entry mapping
    sym_entries = {}
    for e in pending:
        sym = e.get("symbol", "")
        if sym not in sym_entries:
            sym_entries[sym] = []
        sym_entries[sym].append(e)

    # Sort each symbol's entries by proximity
    for sym in sym_entries:
        if sym in prices:
            current = prices[sym]
            sym_entries[sym].sort(
                key=lambda e: abs(current - e.get("target_price", 0))
            )

    # Build position symbol set
    pos_syms = {p.get("symbol", "") for p in positions}

    lines = []
    lines.append("")
    lines.append(f"  {BOLD}{'=' * 55}{RESET}")
    lines.append(f"  {BOLD}  LEVEL TRACKER{RESET} | {now.strftime('%H:%M:%S')} UTC")
    lines.append(f"  {BOLD}{'=' * 55}{RESET}")

    # ── Open Positions Section ──
    if positions:
        lines.append(f"\n  {BOLD}--- OPEN POSITIONS (equity: ${equity:.2f}) ---{RESET}")
        for p in positions:
            sym = p.get("symbol", "")
            if sym in prices:
                lines.append(format_position_line(p, prices[sym]))
            else:
                lines.append(f"  {sym}: no price data")

    # ── Pending Entries Section ──
    active_pending = [e for e in pending if e.get("symbol", "") in prices]
    if active_pending:
        lines.append(f"\n  {BOLD}--- PENDING ENTRIES ({len(active_pending)} active) ---{RESET}")

        # Sort all entries by proximity (closest first)
        all_sorted = []
        for e in active_pending:
            sym = e.get("symbol", "")
            current = prices.get(sym, 0)
            dist = abs(current - e.get("target_price", 0)) / current * 100 if current > 0 else 999
            all_sorted.append((dist, e))
        all_sorted.sort(key=lambda x: x[0])

        for dist, e in all_sorted:
            sym = e.get("symbol", "")
            lines.append(format_level_line(sym, prices[sym], e))
    else:
        lines.append(f"\n  {DIM}--- No pending entries ---{RESET}")

    # ── Idle Symbols (no position, no pending entry) ──
    tracked_syms = set(sym_entries.keys()) | pos_syms
    idle_syms = [s for s in sorted(prices.keys()) if s not in tracked_syms]
    if idle_syms:
        lines.append(f"\n  {DIM}--- IDLE SYMBOLS ---{RESET}")
        for sym in idle_syms:
            lines.append(format_idle_symbol(sym, prices[sym]))

    # ── Proximity Summary ──
    alerts = []
    for e in pending:
        sym = e.get("symbol", "")
        if sym in prices:
            current = prices[sym]
            target = e.get("target_price", 0)
            dist = abs(current - target) / current * 100 if current > 0 else 999
            if dist < 1.0:
                alerts.append((dist, sym, e.get("side", ""), target))

    if alerts:
        alerts.sort()
        lines.append(f"\n  {RED}{BOLD}!!! PROXIMITY ALERTS !!!{RESET}")
        for dist, sym, side, target in alerts:
            lines.append(f"  {RED}{BOLD}  >> {sym} {side} @ {format_price(target)} is {dist:.2f}% away!{RESET}")

    lines.append(f"\n  {BOLD}{'=' * 55}{RESET}")

    output = "\n".join(lines)
    return output


def get_pending_entries_section(prices: Optional[dict] = None) -> str:
    """Generate a PENDING ENTRIES section for integration with alpha_hunter.

    Args:
        prices: dict of {symbol: current_price}. If None, fetches fresh prices.

    Returns:
        Formatted string ready to print in alpha_hunter output.
    """
    pending = load_pending_entries()
    if not pending:
        return ""

    if prices is None:
        fetcher = DataFetcher()
        needed = {e.get("symbol", "") for e in pending}
        needed.discard("")
        prices = fetch_current_prices(fetcher, needed)

    if not prices:
        return ""

    lines = []
    lines.append(f"\n  {BOLD}--- PENDING ENTRIES ---{RESET}")

    # Sort by proximity
    entries_with_dist = []
    for e in pending:
        sym = e.get("symbol", "")
        if sym not in prices:
            continue
        current = prices[sym]
        target = e.get("target_price", 0)
        dist = abs(current - target) / current * 100 if current > 0 else 999
        entries_with_dist.append((dist, sym, current, e))

    if not entries_with_dist:
        return ""

    entries_with_dist.sort(key=lambda x: x[0])

    for dist, sym, current, e in entries_with_dist:
        side = e.get("side", "BUY")
        target = e.get("target_price", 0)
        sl = e.get("sl", 0)
        tp = e.get("tp", 0)
        direction = "above" if current > target else "below"
        clr = color_proximity(dist)
        tag = proximity_tag(dist)

        # R:R
        rr_str = ""
        if sl > 0 and tp > 0:
            if side == "BUY":
                risk_pts = abs(target - sl)
                reward_pts = abs(tp - target)
            else:
                risk_pts = abs(sl - target)
                reward_pts = abs(target - tp)
            rr = reward_pts / risk_pts if risk_pts > 0 else 0
            rr_str = f" | R:R {rr:.1f}:1"

        lines.append(
            f"    {clr}{sym} {side} @ {format_price(target)}{RESET} "
            f"({clr}{dist:.1f}% {direction} [{tag}]{RESET}){rr_str}"
        )

    return "\n".join(lines)


def main():
    output = run_tracker()
    print(output)


if __name__ == "__main__":
    main()
