"""
Learning hooks: trade outcome classification and rolling performance metrics.

Updates after every trade close:
- data/analysis/trade_outcomes.csv  (per-trade outcomes)
- data/analysis/performance.json    (rolling metrics)
"""

import csv
import json
import logging
import os
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("bot.data.learning")

_OUTCOMES_DIR = os.path.join("data", "analysis")
_OUTCOMES_FILE = os.path.join(_OUTCOMES_DIR, "trade_outcomes.csv")
_OUTCOMES_HEADERS = [
    "timestamp", "symbol", "side", "outcome", "pnl", "rr1", "rr2",
    "tp1_hit", "sl_after_tp1", "state_path", "leverage", "confidence",
    "strategy", "entry_reasons",
    "entry_type", "primary_driver", "regime", "volatility_band",
]

_PERF_FILE = os.path.join(_OUTCOMES_DIR, "performance.json")


def _ensure_outcomes_file():
    os.makedirs(_OUTCOMES_DIR, exist_ok=True)
    if not os.path.exists(_OUTCOMES_FILE):
        with open(_OUTCOMES_FILE, "w", newline="") as f:
            csv.writer(f).writerow(_OUTCOMES_HEADERS)


# Rolling window of recent outcomes for metric computation
_recent_outcomes: deque = deque(maxlen=100)


def record_trade_outcome(
    symbol: str,
    side: str,
    outcome: str,
    pnl: float,
    entry: float,
    sl: float,
    tp1: float,
    tp2: float,
    tp1_hit: bool,
    sl_after_tp1: bool,
    state_path: str,
    leverage: float = 1.0,
    confidence: float = 0.0,
    strategy: str = "",
    entry_reasons: Optional[Dict[str, Any]] = None,
    entry_type: str = "",
    primary_driver: str = "",
    regime: str = "",
    volatility_band: str = "",
):
    """Record a trade outcome to CSV and update rolling metrics."""
    _ensure_outcomes_file()

    stop_width = abs(entry - sl) if abs(entry - sl) > 0 else 1e-9
    rr1 = abs(tp1 - entry) / stop_width
    rr2 = abs(tp2 - entry) / stop_width

    ts = datetime.now(timezone.utc).isoformat()
    row = [
        ts, symbol, side, outcome, f"{pnl:.2f}",
        f"{rr1:.2f}", f"{rr2:.2f}",
        str(tp1_hit), str(sl_after_tp1), state_path,
        f"{leverage:.1f}", f"{confidence:.1f}", strategy,
        json.dumps(entry_reasons or {}),
        entry_type, primary_driver, regime, volatility_band,
    ]

    try:
        with open(_OUTCOMES_FILE, "a", newline="") as f:
            csv.writer(f).writerow(row)
    except Exception as e:
        logger.warning(f"Failed to write trade outcome: {e}")

    # Add to rolling window
    _recent_outcomes.append({
        "pnl": pnl, "outcome": outcome, "rr1": rr1,
        "tp1_hit": tp1_hit, "sl_after_tp1": sl_after_tp1,
        "leverage": leverage,
        "entry_type": entry_type,
        "primary_driver": primary_driver,
        "regime": regime,
    })

    # Update rolling performance
    _update_performance()


def _update_performance():
    """Compute and save rolling performance metrics."""
    if not _recent_outcomes:
        return

    outcomes = list(_recent_outcomes)
    n = len(outcomes)

    def _window_stats(window):
        if not window:
            return {"win_rate": 0, "count": 0}
        wins = sum(1 for o in window if o["pnl"] > 0)
        return {
            "win_rate": round(wins / len(window), 3),
            "count": len(window),
        }

    last_20 = outcomes[-20:] if n >= 20 else outcomes
    last_50 = outcomes[-50:] if n >= 50 else outcomes

    tp1_hits = [o for o in outcomes if o["tp1_hit"]]
    tp1_then_sl = [o for o in outcomes if o["sl_after_tp1"]]
    early_exits = [o for o in outcomes if "EARLY_EXIT" in o["outcome"]]
    early_saves = [o for o in early_exits if o["pnl"] > -abs(o.get("rr1", 1)) * 0.5]

    avg_rr = sum(o["rr1"] for o in outcomes) / n if n else 0

    # ── Per-entry_type EV metrics ──
    by_type = {}
    for etype in ("SCALP", "MEDIUM", "TREND", "REGIME"):
        typed = [o for o in outcomes if o.get("entry_type") == etype]
        if typed:
            t_wins = [o for o in typed if o["pnl"] > 0]
            t_losses = [o for o in typed if o["pnl"] <= 0]
            wr = len(t_wins) / len(typed)
            avg_win_r = sum(o["rr1"] for o in t_wins) / len(t_wins) if t_wins else 0
            avg_loss_r = sum(o["rr1"] for o in t_losses) / len(t_losses) if t_losses else 0
            ev = wr * avg_win_r - (1 - wr) * avg_loss_r
            tp1_h = [o for o in typed if o["tp1_hit"]]
            tp1_sl = [o for o in typed if o["sl_after_tp1"]]
            trail_wins = [o for o in typed if "TRAILING" in o["outcome"] and o["pnl"] > 0]
            by_type[etype] = {
                "count": len(typed),
                "win_rate": round(wr, 3),
                "avg_pnl": round(sum(o["pnl"] for o in typed) / len(typed), 2),
                "total_pnl": round(sum(o["pnl"] for o in typed), 2),
                "avg_win_R": round(avg_win_r, 2),
                "avg_loss_R": round(avg_loss_r, 2),
                "EV_per_trade": round(ev, 3),
                "tp1_success_rate": round(len(tp1_h) / len(typed), 3),
                "tp1_to_sl_rate": round(len(tp1_sl) / max(len(tp1_h), 1), 3),
                "trailing_win_rate": round(len(trail_wins) / max(len([o for o in typed if "TRAILING" in o["outcome"]]), 1), 3),
            }

    # ── Per-regime metrics ──
    by_regime = {}
    for reg in ("trending", "ranging", "volatile", "illiquid"):
        reg_outcomes = [o for o in outcomes if o.get("regime") == reg]
        if reg_outcomes:
            rwr = sum(1 for o in reg_outcomes if o["pnl"] > 0) / len(reg_outcomes)
            by_regime[reg] = {
                "count": len(reg_outcomes),
                "win_rate": round(rwr, 3),
                "total_pnl": round(sum(o["pnl"] for o in reg_outcomes), 2),
            }

    # ── Per-strategy metrics ──
    by_strategy = {}
    all_drivers = set(o.get("primary_driver", "") for o in outcomes if o.get("primary_driver"))
    for drv in all_drivers:
        drv_outcomes = [o for o in outcomes if o.get("primary_driver") == drv]
        if drv_outcomes:
            dwr = sum(1 for o in drv_outcomes if o["pnl"] > 0) / len(drv_outcomes)
            by_strategy[drv] = {
                "count": len(drv_outcomes),
                "win_rate": round(dwr, 3),
                "total_pnl": round(sum(o["pnl"] for o in drv_outcomes), 2),
            }

    perf = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "total_trades": n,
        "win_rate_20": _window_stats(last_20)["win_rate"],
        "win_rate_50": _window_stats(last_50)["win_rate"],
        "avg_rr": round(avg_rr, 2),
        "tp1_success_rate": round(len(tp1_hits) / n, 3) if n else 0,
        "tp1_to_sl_rate": round(len(tp1_then_sl) / max(len(tp1_hits), 1), 3),
        "early_exit_count": len(early_exits),
        "early_exit_success_rate": round(len(early_saves) / max(len(early_exits), 1), 3),
        "total_pnl": round(sum(o["pnl"] for o in outcomes), 2),
        "avg_pnl": round(sum(o["pnl"] for o in outcomes) / n, 2) if n else 0,
        "by_entry_type": by_type,
        "by_regime": by_regime,
        "by_strategy": by_strategy,
    }

    try:
        os.makedirs(_OUTCOMES_DIR, exist_ok=True)
        with open(_PERF_FILE, "w") as f:
            json.dump(perf, f, indent=2)
    except Exception as e:
        logger.warning(f"Failed to write performance: {e}")


def get_performance() -> Dict[str, Any]:
    """Read current performance metrics."""
    try:
        if os.path.exists(_PERF_FILE):
            with open(_PERF_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {}
