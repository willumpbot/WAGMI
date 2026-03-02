"""
Trade Autopsy: periodic structured analysis of recent closed trades.

Runs after every 5 trades and generates a compact report that gets injected
into the LLM snapshot as 'autopsy'. This replaces ad-hoc observations with
data-driven analysis the LLM can act on immediately.

No LLM calls — purely statistical/deterministic.
"""

import logging
import time
from collections import defaultdict
from typing import Dict, Any, List

logger = logging.getLogger("bot.llm.trade_autopsy")

_last_autopsy_trade_count: int = 0
_AUTOPSY_INTERVAL_TRADES = 5
_cached_autopsy: str = ""
_cached_at: float = 0.0
_CACHE_TTL = 300  # 5 minutes


def should_run_autopsy(current_trade_count: int) -> bool:
    """Check if we should generate a new autopsy."""
    global _last_autopsy_trade_count
    return (current_trade_count - _last_autopsy_trade_count) >= _AUTOPSY_INTERVAL_TRADES


def generate_autopsy(trades: List[Dict[str, Any]] = None) -> str:
    """Generate a structured autopsy of recent trades.

    Args:
        trades: List of recent trade dicts with keys:
            symbol, side, outcome (WIN/LOSS), pnl, regime, strategy,
            confidence, hold_time_s, exit_action

    Returns compact analysis string or empty string.
    """
    global _last_autopsy_trade_count, _cached_autopsy, _cached_at

    if trades is None:
        # Try to pull from deep memory
        try:
            from llm.deep_memory import get_deep_memory
            dm = get_deep_memory()
            if hasattr(dm, 'trade_dna') and hasattr(dm.trade_dna, '_trades'):
                trades = dm.trade_dna._trades[-20:]
            elif hasattr(dm, 'trade_dna') and hasattr(dm.trade_dna, 'get_recent'):
                trades = dm.trade_dna.get_recent(20)
            else:
                trades = []
        except Exception:
            trades = []

    if len(trades) < 3:
        return ""

    # Analyze last 5 trades specifically
    recent = trades[-5:] if len(trades) >= 5 else trades

    wins = sum(1 for t in recent if _is_win(t))
    losses = len(recent) - wins
    total_pnl = sum(t.get("pnl", 0) for t in recent)

    # Regime breakdown
    regime_results = defaultdict(lambda: {"w": 0, "l": 0})
    for t in recent:
        r = t.get("regime", "unknown") or "unknown"
        if _is_win(t):
            regime_results[r]["w"] += 1
        else:
            regime_results[r]["l"] += 1

    # Symbol breakdown
    symbol_results = defaultdict(lambda: {"w": 0, "l": 0, "pnl": 0})
    for t in recent:
        s = t.get("symbol", "?")
        symbol_results[s]["pnl"] += t.get("pnl", 0)
        if _is_win(t):
            symbol_results[s]["w"] += 1
        else:
            symbol_results[s]["l"] += 1

    # Build compact report
    parts = []
    parts.append(f"LAST {len(recent)}: {wins}W/{losses}L ${total_pnl:+.0f}")

    # Regime insights (only regimes with 2+ trades)
    for r, counts in regime_results.items():
        total = counts["w"] + counts["l"]
        if total >= 2:
            wr = counts["w"] / total
            parts.append(f"{r}: {wr:.0%}WR({total})")

    # Worst performing symbol
    if symbol_results:
        worst = min(symbol_results.items(), key=lambda x: x[1]["pnl"])
        if worst[1]["pnl"] < -1:
            parts.append(f"WEAK: {worst[0]} ${worst[1]['pnl']:+.0f}")

        # Best performing symbol
        best = max(symbol_results.items(), key=lambda x: x[1]["pnl"])
        if best[1]["pnl"] > 1:
            parts.append(f"HOT: {best[0]} ${best[1]['pnl']:+.0f}")

    # Loss pattern detection
    loss_exits = [t.get("exit_action", "") or t.get("exit_reason", "")
                  for t in recent if not _is_win(t)]
    sl_count = sum(1 for e in loss_exits if "SL" in str(e).upper() or "STOP" in str(e).upper())
    if sl_count >= 2:
        parts.append("PATTERN: repeated SL hits—tighten entry or widen stops")

    # Quick losses pattern (< 5 min holds that lost)
    quick_losses = sum(
        1 for t in recent
        if not _is_win(t) and t.get("hold_time_s", 9999) < 300
    )
    if quick_losses >= 2:
        parts.append("PATTERN: quick exits—entries too aggressive")

    # Win rate trend (compare last 5 vs previous 5 if available)
    if len(trades) >= 10:
        prev_5 = trades[-10:-5]
        prev_wins = sum(1 for t in prev_5 if _is_win(t))
        if wins > prev_wins + 1:
            parts.append("IMPROVING")
        elif wins < prev_wins - 1:
            parts.append("DECLINING")

    autopsy = " | ".join(parts)
    _cached_autopsy = autopsy
    _cached_at = time.time()
    _last_autopsy_trade_count += len(recent)

    logger.info(f"[AUTOPSY] {autopsy[:120]}")
    return autopsy


def get_cached_autopsy() -> str:
    """Get the most recent autopsy report. Returns empty if stale."""
    if _cached_autopsy and (time.time() - _cached_at) < _CACHE_TTL:
        return _cached_autopsy
    return _cached_autopsy  # Return even if stale — better than nothing


def _is_win(trade: Dict) -> bool:
    """Determine if a trade was a win."""
    outcome = trade.get("outcome", "")
    if outcome:
        return outcome.upper() in ("WIN", "BREAKEVEN")
    return trade.get("pnl", 0) > 0
