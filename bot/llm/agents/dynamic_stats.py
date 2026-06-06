"""
Dynamic stats provider for agent prompts.

Replaces hardcoded historical stats with live rolling calculations
from trades.csv, strategy_weights.json, adaptive_risk_state.json,
confidence_state.json, and kelly_weights.json.

All functions return compact text blocks (<200 tokens each) suitable
for injection into agent enriched context.
"""

import csv
import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple  # Tuple used in get_system_baseline return type

logger = logging.getLogger(__name__)

# ── Data paths ──────────────────────────────────────────────────
_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_ML_DIR = Path(__file__).resolve().parent.parent.parent / "ml_data"

TRADES_CSV = _DATA_DIR / "trades.csv"
ADAPTIVE_RISK = _DATA_DIR / "feedback" / "adaptive_risk_state.json"
CONFIDENCE_STATE = _DATA_DIR / "feedback" / "confidence_state.json"
KELLY_WEIGHTS = _DATA_DIR / "kelly_weights.json"
STRATEGY_WEIGHTS = _ML_DIR / "strategy_weights.json"
STRATEGY_STATS = _ML_DIR / "strategy_stats.json"


def _load_json(path: Path) -> Optional[dict]:
    """Load JSON file, return None on any error."""
    try:
        if path.exists():
            with open(path, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.debug("dynamic_stats: failed to load %s: %s", path, e)
    return None


def _load_recent_trades(max_trades: int = 100) -> List[dict]:
    """Load last N trades from trades.csv."""
    trades = []
    try:
        if not TRADES_CSV.exists():
            return trades
        with open(TRADES_CSV, "r", newline="") as f:
            reader = csv.DictReader(f)
            all_rows = list(reader)
        # Take last max_trades
        for row in all_rows[-max_trades:]:
            try:
                pnl = float(row.get("pnl", 0))
                trades.append({
                    "symbol": row.get("symbol", ""),
                    "side": row.get("side", ""),
                    "pnl": pnl,
                    "won": pnl > 0,
                    "strategy": row.get("strategy", ""),
                    "regime": row.get("regime", ""),
                    "confidence": float(row.get("confidence", 0)),
                    "leverage": float(row.get("leverage", 0)),
                    "fees": float(row.get("fees", 0)),
                    "outcome": row.get("outcome", ""),
                    "timestamp": row.get("timestamp", ""),
                })
            except (ValueError, TypeError):
                continue
    except Exception as e:
        logger.debug("dynamic_stats: failed to load trades: %s", e)
    return trades


def get_system_baseline() -> Tuple[float, float]:
    """Compute live system WR and payoff ratio from recent trades.

    Returns: (win_rate, payoff_ratio)
    Fallback: (0.50, 1.5) if insufficient data
    """
    trades = _load_recent_trades(max_trades=100)
    if len(trades) < 10:
        return (0.50, 1.5)

    wins = sum(1 for t in trades if t["won"])
    wr = wins / len(trades)

    # Compute payoff ratio: avg_win / abs(avg_loss)
    win_pnls = [t["pnl"] for t in trades if t["won"] and t["pnl"] > 0]
    loss_pnls = [abs(t["pnl"]) for t in trades if not t["won"] and t["pnl"] < 0]

    avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 0
    avg_loss = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 1

    payoff_ratio = avg_win / avg_loss if avg_loss > 0 else 1.5

    return (wr, payoff_ratio)


def _wr_label(wr: float, n: int) -> str:
    """Human-readable label for a win rate given sample size.

    Labels are relative to dynamic system baseline, not 50%.
    Baseline = system's actual win rate from recent trades.
    """
    if n < 3:
        return "INSUFFICIENT DATA"
    if n < 10:
        return "LOW SAMPLE"

    baseline_wr, _ = get_system_baseline()

    # STRONG: at least 0.10 above baseline
    if wr >= baseline_wr + 0.10:
        return "STRONG"
    # NORMAL: within 0.10 of baseline
    if wr >= baseline_wr - 0.10:
        return "NORMAL"
    # BELOW AVG: 0.10-0.20 below baseline
    if wr >= baseline_wr - 0.20:
        return "BELOW AVG"
    return "TOXIC"


def get_current_edge_map(max_trades: int = 100) -> str:
    """Compute current WR and PF for each symbol+side from recent trades.

    Returns compact text block for agent injection.
    """
    trades = _load_recent_trades(max_trades)
    if not trades:
        return "CURRENT EDGES: No trade data available yet."

    # Group by symbol+side
    groups: Dict[str, List[dict]] = defaultdict(list)
    for t in trades:
        key = f"{t['symbol']}_{t['side']}"
        groups[key] = groups.get(key, [])
        groups[key].append(t)

    lines = [f"CURRENT EDGES (last {len(trades)} trades):"]
    # Sort by trade count descending
    for key in sorted(groups.keys(), key=lambda k: -len(groups[k])):
        group = groups[key]
        n = len(group)
        wins = sum(1 for t in group if t["won"])
        wr = wins / n if n > 0 else 0
        total_pnl = sum(t["pnl"] for t in group)
        # Profit factor
        gross_wins = sum(t["pnl"] for t in group if t["pnl"] > 0)
        gross_losses = abs(sum(t["pnl"] for t in group if t["pnl"] < 0))
        pf = (gross_wins / gross_losses) if gross_losses > 0 else float("inf") if gross_wins > 0 else 0
        pf_str = f"PF {pf:.2f}" if pf < 100 else "PF INF"

        label = _wr_label(wr, n)
        lines.append(
            f"  {key}: {wr:.0%} WR ({n} trades), {pf_str}, ${total_pnl:+.2f} — {label}"
        )

    # Overall
    total_n = len(trades)
    total_wins = sum(1 for t in trades if t["won"])
    overall_wr = total_wins / total_n if total_n > 0 else 0
    lines.append(f"  OVERALL: {overall_wr:.0%} WR ({total_n} trades)")

    # Add regime-specific edges (symbol+side+regime)
    regime_groups: Dict[str, List[dict]] = defaultdict(list)
    for t in trades:
        regime = t.get("regime", "")
        if regime:
            key = f"{t['symbol']}_{t['side']}_{regime}"
            regime_groups[key].append(t)

    # Show top regime-specific edges (n>=3, sorted by PnL)
    regime_edges = []
    for key, group in regime_groups.items():
        n = len(group)
        if n < 3:
            continue
        wins = sum(1 for t in group if t["won"])
        total_pnl = sum(t["pnl"] for t in group)
        regime_edges.append((key, n, wins / n, total_pnl))

    if regime_edges:
        regime_edges.sort(key=lambda x: -x[3])
        lines.append("  REGIME-SPECIFIC (n>=3):")
        for key, n, wr, pnl in regime_edges[:8]:
            label = _wr_label(wr, n)
            lines.append(f"    {key}: {wr:.0%} WR ({n}), ${pnl:+.2f} — {label}")

    return "\n".join(lines)


def get_current_regime_performance() -> str:
    """Compute WR by regime from recent trades and adaptive_risk_state."""
    trades = _load_recent_trades(100)
    adaptive = _load_json(ADAPTIVE_RISK)

    # From trades.csv
    regime_stats: Dict[str, Dict] = defaultdict(lambda: {"wins": 0, "total": 0, "pnl": 0.0})
    for t in trades:
        regime = t.get("regime", "unknown")
        if not regime:
            regime = "unknown"
        regime_stats[regime]["total"] += 1
        if t["won"]:
            regime_stats[regime]["wins"] += 1
        regime_stats[regime]["pnl"] += t["pnl"]

    # Merge adaptive_risk_state regime_wr if available
    if adaptive and "regime_wr" in adaptive:
        for regime, data in adaptive["regime_wr"].items():
            if regime not in regime_stats:
                regime_stats[regime] = {
                    "wins": data.get("wins", 0),
                    "total": data.get("total", 0),
                    "pnl": 0.0,
                }

    if not regime_stats:
        return "REGIME PERFORMANCE: No data available."

    lines = ["REGIME PERFORMANCE:"]
    for regime in sorted(regime_stats.keys(), key=lambda r: -regime_stats[r]["total"]):
        s = regime_stats[regime]
        n = s["total"]
        wr = s["wins"] / n if n > 0 else 0
        label = _wr_label(wr, n)
        lines.append(f"  {regime}: {wr:.0%} WR ({n} trades), ${s['pnl']:+.2f} — {label}")

    return "\n".join(lines)


def get_current_strategy_performance() -> str:
    """Compute per-strategy WR and status from strategy_stats and strategy_weights."""
    stats = _load_json(STRATEGY_STATS)
    weights = _load_json(STRATEGY_WEIGHTS)

    if not stats and not weights:
        # Fall back to trades.csv
        trades = _load_recent_trades(100)
        if not trades:
            return "STRATEGY PERFORMANCE: No data available."
        strat_groups: Dict[str, List[dict]] = defaultdict(list)
        for t in trades:
            strat_groups[t["strategy"]].append(t)

        lines = ["STRATEGY PERFORMANCE:"]
        for strat in sorted(strat_groups.keys(), key=lambda s: -len(strat_groups[s])):
            group = strat_groups[strat]
            n = len(group)
            wins = sum(1 for t in group if t["won"])
            wr = wins / n if n > 0 else 0
            pnl = sum(t["pnl"] for t in group)
            label = _wr_label(wr, n)
            lines.append(f"  {strat}: {wr:.0%} WR ({n} trades), ${pnl:+.2f} — {label}")
        return "\n".join(lines)

    lines = ["STRATEGY PERFORMANCE:"]

    if stats:
        for strat, data in stats.items():
            wins = data.get("wins", 0)
            losses = data.get("losses", 0)
            n = wins + losses
            wr = wins / n if n > 0 else 0
            pnl = data.get("total_pnl", 0)
            weight = None
            if weights and strat in weights:
                weight = weights[strat].get("weight", None)

            # Recent trend from recent_results
            recent = data.get("recent_results", [])
            recent_n = len(recent)
            recent_wr = sum(recent) / recent_n if recent_n > 0 else 0

            label = _wr_label(wr, n)
            # Hot/cold/muted status
            if recent_n >= 5:
                if recent_wr > wr + 0.10:
                    status = "HOT"
                elif recent_wr < wr - 0.10:
                    status = "COLD"
                else:
                    status = "STABLE"
            else:
                status = "?"

            weight_str = f", wt={weight:.2f}" if weight is not None else ""
            lines.append(
                f"  {strat}: {wr:.0%} WR ({n} trades), ${pnl:+.1f}, "
                f"recent={recent_wr:.0%} ({recent_n}){weight_str} — {label} [{status}]"
            )

    return "\n".join(lines)


def get_current_calibration() -> str:
    """Compute confidence calibration from confidence_state.json.

    Returns calibration drift description for agents.
    """
    conf_state = _load_json(CONFIDENCE_STATE)
    if not conf_state:
        return "CALIBRATION: No calibration data available."

    lines = ["CALIBRATION:"]

    # Calibration errors
    errors = conf_state.get("calibration_errors", [])
    if errors:
        recent_errors = errors[-20:]  # Last 20
        avg_error = sum(recent_errors) / len(recent_errors)
        if avg_error > 0.10:
            lines.append(
                f"  Overconfident: avg calibration error = +{avg_error:.2f}. "
                f"Your high-confidence trades win less than expected. Reduce confidence by ~{abs(avg_error)*100:.0f}%."
            )
        elif avg_error < -0.10:
            lines.append(
                f"  Underconfident: avg calibration error = {avg_error:.2f}. "
                f"Your trades win more than expected. Can increase confidence by ~{abs(avg_error)*100:.0f}%."
            )
        else:
            lines.append(f"  Well-calibrated: avg error = {avg_error:+.2f}. No adjustment needed.")

    # Per-strategy floors
    strat_floors = conf_state.get("strategy_floors", {})
    if strat_floors:
        floor_parts = [f"{s}={v:.0f}" for s, v in strat_floors.items()]
        lines.append(f"  Strategy floors: {', '.join(floor_parts)}")

    # Symbol adjustments
    sym_adj = conf_state.get("symbol_adjustments", {})
    if sym_adj:
        adj_parts = [f"{s}={v:+.1f}" for s, v in sym_adj.items()]
        lines.append(f"  Symbol adjustments: {', '.join(adj_parts)}")

    # Regime adjustments
    reg_adj = conf_state.get("regime_adjustments", {})
    if reg_adj:
        # Only show significant adjustments
        sig = {k: v for k, v in reg_adj.items() if abs(v) > 0.3}
        if sig:
            adj_parts = [f"{k}={v:+.1f}" for k, v in sig.items()]
            lines.append(f"  Regime adjustments: {', '.join(adj_parts)}")

    return "\n".join(lines)


def get_current_kelly() -> str:
    """Compute current Kelly fractions from kelly_weights.json."""
    kelly = _load_json(KELLY_WEIGHTS)
    if not kelly:
        return "KELLY: No Kelly data available."

    lines = ["KELLY FRACTIONS:"]
    trades_data = kelly.get("trades", {})
    for strat, data in trades_data.items():
        trade_list = data if isinstance(data, list) else []
        if not trade_list:
            continue
        n = len(trade_list)
        wins = sum(1 for t in trade_list if t.get("won", False))
        wr = wins / n if n > 0 else 0

        # Compute Kelly: f* = (p*b - q) / b where p=WR, q=1-p, b=avg_win/avg_loss
        win_pcts = [t.get("pnl_pct", 0) for t in trade_list if t.get("won", False)]
        loss_pcts = [abs(t.get("pnl_pct", 0)) for t in trade_list if not t.get("won", False)]
        avg_win = sum(win_pcts) / len(win_pcts) if win_pcts else 0
        avg_loss = sum(loss_pcts) / len(loss_pcts) if loss_pcts else 1
        b = avg_win / avg_loss if avg_loss > 0 else 0
        kelly_f = ((wr * b) - (1 - wr)) / b if b > 0 else 0
        half_kelly = max(kelly_f / 2, 0)

        lines.append(
            f"  {strat}: WR={wr:.0%} ({n} trades), payoff={b:.2f}x, "
            f"full_kelly={kelly_f:.3f}, half_kelly={half_kelly:.3f}"
        )

    return "\n".join(lines)


def get_recent_trade_patterns(max_trades: int = 50) -> str:
    """Extract actionable patterns from recent trades.

    Detects: win/loss streaks, fee drag, regime shifts, time patterns.
    """
    trades = _load_recent_trades(max_trades)
    if len(trades) < 5:
        return "PATTERNS: Insufficient trades for pattern detection."

    lines = ["RECENT PATTERNS:"]

    # Win/loss streak
    streak = 0
    streak_type = None
    for t in reversed(trades):
        if streak_type is None:
            streak_type = t["won"]
            streak = 1
        elif t["won"] == streak_type:
            streak += 1
        else:
            break
    if streak >= 3:
        word = "WIN" if streak_type else "LOSS"
        lines.append(f"  Current {word} streak: {streak} trades. {'Size down after losses.' if not streak_type else 'Do not chase after wins.'}")

    # Fee drag analysis
    total_fees = sum(t["fees"] for t in trades)
    total_pnl = sum(t["pnl"] for t in trades)
    directional_pnl = total_pnl + total_fees  # PnL before fees
    if total_fees > 0 and abs(directional_pnl) > 0:
        fee_ratio = total_fees / abs(directional_pnl) if directional_pnl != 0 else float("inf")
        if fee_ratio > 0.5:
            lines.append(f"  FEE DRAG WARNING: Fees ${total_fees:.2f} are {fee_ratio:.0%} of directional PnL ${directional_pnl:.2f}.")

    # Last big win/loss detection (post-win giveback)
    for i, t in enumerate(reversed(trades)):
        if abs(t["pnl"]) > 20 and i < 3:  # Big trade in last 3
            if t["won"]:
                lines.append(f"  RECENT BIG WIN: {t['symbol']} {t['side']} +${t['pnl']:.2f}. Historical pattern: givebacks follow big wins. Size conservatively.")
            else:
                lines.append(f"  RECENT BIG LOSS: {t['symbol']} {t['side']} ${t['pnl']:.2f}. Avoid revenge trading this setup.")
            break

    if len(lines) == 1:
        lines.append("  No significant patterns detected.")

    return "\n".join(lines)


def get_all_dynamic_stats() -> str:
    """Combine all dynamic stats into one compact block for agent injection.

    Target: ~200-300 tokens total.
    """
    parts = []
    try:
        edge = get_current_edge_map(50)
        if edge:
            parts.append(edge)
    except Exception as e:
        logger.debug("dynamic_stats edge_map error: %s", e)

    try:
        regime = get_current_regime_performance()
        if regime:
            parts.append(regime)
    except Exception as e:
        logger.debug("dynamic_stats regime error: %s", e)

    try:
        strat = get_current_strategy_performance()
        if strat:
            parts.append(strat)
    except Exception as e:
        logger.debug("dynamic_stats strategy error: %s", e)

    try:
        cal = get_current_calibration()
        if cal:
            parts.append(cal)
    except Exception as e:
        logger.debug("dynamic_stats calibration error: %s", e)

    try:
        kelly = get_current_kelly()
        if kelly:
            parts.append(kelly)
    except Exception as e:
        logger.debug("dynamic_stats kelly error: %s", e)

    try:
        patterns = get_recent_trade_patterns(50)
        if patterns:
            parts.append(patterns)
    except Exception as e:
        logger.debug("dynamic_stats patterns error: %s", e)

    if not parts:
        return "DYNAMIC STATS: No data available. All stats will populate after first trades."

    return "\n\n".join(parts)
