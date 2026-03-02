"""
Performance Attribution Engine: "Which decisions actually made money?"

Breaks down PnL into five attribution dimensions:
  1. Strategy contribution   - which strategy drove each trade
  2. LLM decision contribution - did LLM veto/approve add value
  3. Regime contribution     - which market regimes were profitable
  4. Sizing contribution     - did position sizing add/subtract alpha
  5. Timing contribution     - entry/exit timing quality

Data source: SQLite database at ml_data/bot.db (via data.db.get_connection).

Tables used:
  - trades: id, timestamp, symbol, action, side, price, qty, pnl, fee,
            leverage, strategy, metadata
  - signal_outcomes: id, signal_id, timestamp, symbol, strategy, side,
            confidence, entry_price, exit_price, exit_action, pnl, pnl_pct,
            hold_time_s, regime, leverage, win, score
  - performance_daily: date, symbol, strategy, trades, wins, losses,
            gross_pnl, net_pnl, etc.
"""

import json
import logging
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any

from data.db import get_connection

logger = logging.getLogger("bot.attribution")

# Actions that represent position closes (must stay in sync with data.db)
CLOSE_ACTIONS = {
    "SL", "TP1", "TP2", "TRAILING_STOP", "EARLY_EXIT",
    "EMERGENCY", "ROTATE_OUT", "ROTATE_LOSS", "MANUAL_CLOSE",
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Data classes
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dataclass
class SubAttribution:
    """Common attribution metrics for any single slice (strategy, regime, symbol)."""
    total_pnl: float = 0.0
    num_trades: int = 0
    win_rate: float = 0.0
    avg_pnl: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0


@dataclass
class StrategyAttribution(SubAttribution):
    """Attribution slice for a single strategy."""
    strategy: str = ""
    pnl_contribution_pct: float = 0.0  # what % of total PnL this strategy produced
    avg_confidence: float = 0.0
    avg_hold_time_s: float = 0.0


@dataclass
class RegimeAttribution(SubAttribution):
    """Attribution slice for a single market regime."""
    regime: str = ""
    pnl_contribution_pct: float = 0.0
    avg_leverage: float = 1.0


@dataclass
class SymbolAttribution(SubAttribution):
    """Attribution slice for a single trading symbol."""
    symbol: str = ""
    pnl_contribution_pct: float = 0.0
    total_fees: float = 0.0


@dataclass
class AttributionReport:
    """Complete PnL attribution breakdown."""
    period_days: int = 30
    total_pnl: float = 0.0
    total_trades: int = 0
    by_strategy: Dict[str, StrategyAttribution] = field(default_factory=dict)
    by_regime: Dict[str, RegimeAttribution] = field(default_factory=dict)
    by_symbol: Dict[str, SymbolAttribution] = field(default_factory=dict)
    llm_value_add: float = 0.0        # PnL from LLM-approved minus LLM-vetoed-would-have-been
    sizing_alpha: float = 0.0         # extra PnL from sizing vs equal-weight baseline
    timing_score: float = 0.0         # 0-100 composite entry/exit timing quality
    top_contributors: List[str] = field(default_factory=list)
    worst_detractors: List[str] = field(default_factory=list)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _cutoff_iso(days: int) -> str:
    """Return an ISO-8601 timestamp string for *days* ago."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Division that returns *default* when denominator is zero."""
    if denominator == 0:
        return default
    return numerator / denominator


def _approx_sharpe(pnl_list: List[float], annualisation: float = 365.0) -> float:
    """Approximate Sharpe ratio from a list of per-trade PnL values.

    Uses daily-equivalent scaling: assumes trades are roughly daily events.
    Returns 0.0 when there are fewer than 2 data points.
    """
    if len(pnl_list) < 2:
        return 0.0
    mean = sum(pnl_list) / len(pnl_list)
    variance = sum((p - mean) ** 2 for p in pnl_list) / (len(pnl_list) - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0
    if std == 0:
        return 0.0
    return (mean / std) * math.sqrt(annualisation)


def _max_drawdown(pnl_list: List[float]) -> float:
    """Compute the maximum drawdown from a sequence of PnL values.

    Tracks cumulative equity and returns the largest peak-to-trough decline.
    """
    if not pnl_list:
        return 0.0
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnl_list:
        cumulative += pnl
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _parse_metadata(raw: Optional[str]) -> Dict[str, Any]:
    """Safely parse a JSON metadata string into a dict."""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _build_sub_attribution(pnl_list: List[float], wins: int) -> SubAttribution:
    """Populate common SubAttribution fields from raw numbers."""
    n = len(pnl_list)
    return SubAttribution(
        total_pnl=sum(pnl_list),
        num_trades=n,
        win_rate=_safe_div(wins, n),
        avg_pnl=_safe_div(sum(pnl_list), n),
        sharpe_ratio=_approx_sharpe(pnl_list),
        max_drawdown=_max_drawdown(pnl_list),
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Core query helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _fetch_closed_trades(conn: sqlite3.Connection, cutoff: str) -> List[Dict[str, Any]]:
    """Fetch all closed trades since *cutoff* as dicts."""
    placeholders = ",".join("?" for _ in CLOSE_ACTIONS)
    query = (
        f"SELECT * FROM trades WHERE timestamp >= ? AND action IN ({placeholders}) "
        "ORDER BY timestamp"
    )
    params: list = [cutoff] + sorted(CLOSE_ACTIONS)
    try:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("Failed to fetch closed trades: %s", exc)
        return []


def _fetch_signal_outcomes(conn: sqlite3.Connection, cutoff: str) -> List[Dict[str, Any]]:
    """Fetch signal outcomes since *cutoff* as dicts."""
    try:
        rows = conn.execute(
            "SELECT * FROM signal_outcomes WHERE timestamp >= ? ORDER BY timestamp",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("Failed to fetch signal outcomes: %s", exc)
        return []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. Strategy contribution
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_strategy_contribution(days: int = 30) -> Dict[str, Any]:
    """By-strategy PnL, win rates, Sharpe, and drawdown.

    Returns a dict keyed by strategy name, each value containing:
      total_pnl, num_trades, win_rate, avg_pnl, sharpe_ratio,
      max_drawdown, pnl_contribution_pct, avg_confidence, avg_hold_time_s
    """
    cutoff = _cutoff_iso(days)
    conn: Optional[sqlite3.Connection] = None
    try:
        conn = get_connection()
        outcomes = _fetch_signal_outcomes(conn, cutoff)
        if not outcomes:
            logger.info("No signal outcomes in the last %d days for strategy attribution.", days)
            return {}

        buckets: Dict[str, List[Dict]] = {}
        for o in outcomes:
            strat = o.get("strategy") or "unknown"
            buckets.setdefault(strat, []).append(o)

        total_pnl_all = sum(o["pnl"] for o in outcomes)
        result: Dict[str, Any] = {}
        for strat, rows in buckets.items():
            pnl_list = [r["pnl"] for r in rows]
            wins = sum(1 for r in rows if r.get("win"))
            n = len(rows)
            result[strat] = {
                "total_pnl": sum(pnl_list),
                "num_trades": n,
                "win_rate": _safe_div(wins, n),
                "avg_pnl": _safe_div(sum(pnl_list), n),
                "sharpe_ratio": _approx_sharpe(pnl_list),
                "max_drawdown": _max_drawdown(pnl_list),
                "pnl_contribution_pct": _safe_div(sum(pnl_list), abs(total_pnl_all)) * 100
                    if total_pnl_all != 0 else 0.0,
                "avg_confidence": _safe_div(
                    sum(r.get("confidence", 0) for r in rows), n
                ),
                "avg_hold_time_s": _safe_div(
                    sum(r.get("hold_time_s", 0) for r in rows), n
                ),
            }

        return result
    except Exception as exc:
        logger.error("Strategy attribution failed: %s", exc, exc_info=True)
        return {}
    finally:
        if conn:
            conn.close()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. LLM decision contribution
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_llm_attribution(days: int = 30) -> Dict[str, Any]:
    """LLM approve vs veto outcome analysis.

    Reads the ``metadata`` JSON column on the *trades* table, looking for
    the ``llm_action`` field.  Buckets trades into:
      - ``approved``  : LLM let the trade through  (action in proceed/go)
      - ``vetoed``    : LLM blocked the trade       (action = flat)
      - ``no_llm``    : trade taken without LLM     (action empty / no_llm)

    For vetoed trades we use the *counterfactual* PnL stored in the veto
    tracker metadata (``counterfactual_pnl``) when available.

    Returns dict with per-bucket stats plus ``llm_value_add``.
    """
    cutoff = _cutoff_iso(days)
    conn: Optional[sqlite3.Connection] = None
    try:
        conn = get_connection()
        trades = _fetch_closed_trades(conn, cutoff)
        outcomes = _fetch_signal_outcomes(conn, cutoff)

        # Build a mapping of llm_action from trade metadata
        approved: List[float] = []
        vetoed: List[float] = []
        no_llm: List[float] = []
        approved_wins = 0
        vetoed_wins = 0
        no_llm_wins = 0

        # Combine both data sources: trades have metadata with llm_action,
        # signal_outcomes have richer fields but may lack llm_action.
        # Use trades as primary since they carry the metadata blob.
        for t in trades:
            meta = _parse_metadata(t.get("metadata"))
            pnl = t.get("pnl", 0.0)
            llm_action = meta.get("llm_action", "")
            win = pnl > 0

            if llm_action in ("proceed", "go"):
                approved.append(pnl)
                if win:
                    approved_wins += 1
            elif llm_action == "flat":
                vetoed.append(pnl)
                if win:
                    vetoed_wins += 1
            else:
                no_llm.append(pnl)
                if win:
                    no_llm_wins += 1

        # Also scan signal outcomes for richer data (some closed positions
        # may not have metadata on the trades row but do in signal_outcomes)
        _seen_from_trades = len(approved) + len(vetoed) + len(no_llm)
        if not _seen_from_trades and outcomes:
            # Fallback: use signal outcomes alone when trade metadata is absent
            for o in outcomes:
                pnl = o.get("pnl", 0.0)
                win = bool(o.get("win"))
                # signal_outcomes don't carry llm_action directly;
                # treat all as "no_llm" bucket
                no_llm.append(pnl)
                if win:
                    no_llm_wins += 1

        approved_total_pnl = sum(approved)
        vetoed_total_pnl = sum(vetoed)
        no_llm_total_pnl = sum(no_llm)

        # LLM value-add: PnL of approved trades minus the average PnL that
        # would have occurred without LLM filtering.
        # If no_llm bucket has data, use its avg_pnl as baseline.
        # Otherwise, compare approved avg against the overall average.
        all_pnl = approved + vetoed + no_llm
        overall_avg = _safe_div(sum(all_pnl), len(all_pnl))
        approved_avg = _safe_div(approved_total_pnl, len(approved))
        llm_value_add = (approved_avg - overall_avg) * len(approved) if approved else 0.0

        return {
            "approved": {
                "total_pnl": approved_total_pnl,
                "num_trades": len(approved),
                "win_rate": _safe_div(approved_wins, len(approved)),
                "avg_pnl": approved_avg,
                "sharpe_ratio": _approx_sharpe(approved),
                "max_drawdown": _max_drawdown(approved),
            },
            "vetoed": {
                "total_pnl": vetoed_total_pnl,
                "num_trades": len(vetoed),
                "win_rate": _safe_div(vetoed_wins, len(vetoed)),
                "avg_pnl": _safe_div(vetoed_total_pnl, len(vetoed)),
                "sharpe_ratio": _approx_sharpe(vetoed),
                "max_drawdown": _max_drawdown(vetoed),
            },
            "no_llm": {
                "total_pnl": no_llm_total_pnl,
                "num_trades": len(no_llm),
                "win_rate": _safe_div(no_llm_wins, len(no_llm)),
                "avg_pnl": _safe_div(no_llm_total_pnl, len(no_llm)),
                "sharpe_ratio": _approx_sharpe(no_llm),
                "max_drawdown": _max_drawdown(no_llm),
            },
            "llm_value_add": round(llm_value_add, 4),
        }
    except Exception as exc:
        logger.error("LLM attribution failed: %s", exc, exc_info=True)
        return {"approved": {}, "vetoed": {}, "no_llm": {}, "llm_value_add": 0.0}
    finally:
        if conn:
            conn.close()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. Regime contribution
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_regime_attribution(days: int = 30) -> Dict[str, Any]:
    """By-regime performance breakdown.

    Uses the ``regime`` column on ``signal_outcomes``.  Returns dict keyed
    by regime label with sub-attribution metrics plus avg_leverage.
    """
    cutoff = _cutoff_iso(days)
    conn: Optional[sqlite3.Connection] = None
    try:
        conn = get_connection()
        outcomes = _fetch_signal_outcomes(conn, cutoff)
        if not outcomes:
            logger.info("No signal outcomes for regime attribution in the last %d days.", days)
            return {}

        buckets: Dict[str, List[Dict]] = {}
        for o in outcomes:
            regime = o.get("regime") or "unknown"
            buckets.setdefault(regime, []).append(o)

        total_pnl_all = sum(o["pnl"] for o in outcomes)
        result: Dict[str, Any] = {}
        for regime, rows in buckets.items():
            pnl_list = [r["pnl"] for r in rows]
            wins = sum(1 for r in rows if r.get("win"))
            n = len(rows)
            result[regime] = {
                "total_pnl": sum(pnl_list),
                "num_trades": n,
                "win_rate": _safe_div(wins, n),
                "avg_pnl": _safe_div(sum(pnl_list), n),
                "sharpe_ratio": _approx_sharpe(pnl_list),
                "max_drawdown": _max_drawdown(pnl_list),
                "pnl_contribution_pct": _safe_div(sum(pnl_list), abs(total_pnl_all)) * 100
                    if total_pnl_all != 0 else 0.0,
                "avg_leverage": _safe_div(
                    sum(r.get("leverage", 1.0) for r in rows), n
                ),
            }

        return result
    except Exception as exc:
        logger.error("Regime attribution failed: %s", exc, exc_info=True)
        return {}
    finally:
        if conn:
            conn.close()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. Sizing contribution
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_sizing_attribution(days: int = 30) -> Dict[str, Any]:
    """Analyse whether larger positions outperformed smaller ones.

    Methodology:
      - Split trades at the median ``qty`` into "large" and "small" buckets.
      - Compute an *equal-weight baseline* PnL (every trade gets the same
        notional = median qty) and compare against actual PnL.
      - ``sizing_alpha`` = actual_total_pnl - equal_weight_baseline_pnl.
        Positive means the sizing algorithm added value.

    Also provides leverage-bucketed analysis (low / medium / high leverage).
    """
    cutoff = _cutoff_iso(days)
    conn: Optional[sqlite3.Connection] = None
    try:
        conn = get_connection()
        trades = _fetch_closed_trades(conn, cutoff)
        if not trades:
            logger.info("No closed trades for sizing attribution in the last %d days.", days)
            return {"sizing_alpha": 0.0, "by_size_bucket": {}, "by_leverage_bucket": {}}

        # Filter trades that have a qty > 0 (valid sizing data)
        sized = [t for t in trades if t.get("qty", 0) > 0]
        if not sized:
            return {"sizing_alpha": 0.0, "by_size_bucket": {}, "by_leverage_bucket": {}}

        qtys = sorted(t["qty"] for t in sized)
        median_qty = qtys[len(qtys) // 2]

        # Actual PnL
        actual_total = sum(t["pnl"] for t in sized)

        # Equal-weight baseline: rescale each trade's PnL as if qty = median_qty
        equal_weight_total = 0.0
        for t in sized:
            qty = t["qty"]
            pnl = t["pnl"]
            if qty > 0:
                # PnL per unit * median_qty
                equal_weight_total += (pnl / qty) * median_qty
            else:
                equal_weight_total += pnl  # cannot rescale; keep as-is

        sizing_alpha = actual_total - equal_weight_total

        # Size buckets: small vs large
        small_pnl: List[float] = []
        large_pnl: List[float] = []
        small_wins = 0
        large_wins = 0
        for t in sized:
            pnl = t["pnl"]
            win = pnl > 0
            if t["qty"] <= median_qty:
                small_pnl.append(pnl)
                if win:
                    small_wins += 1
            else:
                large_pnl.append(pnl)
                if win:
                    large_wins += 1

        by_size_bucket = {
            "small": {
                "total_pnl": sum(small_pnl),
                "num_trades": len(small_pnl),
                "win_rate": _safe_div(small_wins, len(small_pnl)),
                "avg_pnl": _safe_div(sum(small_pnl), len(small_pnl)),
                "sharpe_ratio": _approx_sharpe(small_pnl),
                "max_drawdown": _max_drawdown(small_pnl),
            },
            "large": {
                "total_pnl": sum(large_pnl),
                "num_trades": len(large_pnl),
                "win_rate": _safe_div(large_wins, len(large_pnl)),
                "avg_pnl": _safe_div(sum(large_pnl), len(large_pnl)),
                "sharpe_ratio": _approx_sharpe(large_pnl),
                "max_drawdown": _max_drawdown(large_pnl),
            },
        }

        # Leverage buckets: low (<=1x), medium (1-3x), high (>3x)
        lev_buckets: Dict[str, Dict[str, Any]] = {
            "low": {"pnl_list": [], "wins": 0},
            "medium": {"pnl_list": [], "wins": 0},
            "high": {"pnl_list": [], "wins": 0},
        }
        for t in sized:
            lev = t.get("leverage", 1.0) or 1.0
            pnl = t["pnl"]
            win = pnl > 0
            if lev <= 1.0:
                bucket = "low"
            elif lev <= 3.0:
                bucket = "medium"
            else:
                bucket = "high"
            lev_buckets[bucket]["pnl_list"].append(pnl)
            if win:
                lev_buckets[bucket]["wins"] += 1

        by_leverage_bucket: Dict[str, Any] = {}
        for label, data in lev_buckets.items():
            plist = data["pnl_list"]
            w = data["wins"]
            by_leverage_bucket[label] = {
                "total_pnl": sum(plist),
                "num_trades": len(plist),
                "win_rate": _safe_div(w, len(plist)),
                "avg_pnl": _safe_div(sum(plist), len(plist)),
                "sharpe_ratio": _approx_sharpe(plist),
                "max_drawdown": _max_drawdown(plist),
            }

        return {
            "sizing_alpha": round(sizing_alpha, 4),
            "actual_total_pnl": round(actual_total, 4),
            "equal_weight_baseline_pnl": round(equal_weight_total, 4),
            "median_qty": median_qty,
            "by_size_bucket": by_size_bucket,
            "by_leverage_bucket": by_leverage_bucket,
        }
    except Exception as exc:
        logger.error("Sizing attribution failed: %s", exc, exc_info=True)
        return {"sizing_alpha": 0.0, "by_size_bucket": {}, "by_leverage_bucket": {}}
    finally:
        if conn:
            conn.close()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. Timing contribution
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_timing_attribution(days: int = 30) -> Dict[str, Any]:
    """Assess entry/exit timing quality.

    Metrics:
      - **entry_efficiency**: For winning trades, how close was the entry
        price to the best possible price during the hold?
        ``(best_possible - entry) / (best_possible - worst_possible)``
        Averaged across all trades; 1.0 = perfect entry, 0.0 = worst.
        Approximated here using pnl_pct since we lack full OHLC bars.
      - **exit_efficiency**: For each trade, ``realized_pnl_pct / max_favorable_pnl_pct``.
        Approximated as: positive pnl_pct trades get score = pnl_pct / (pnl_pct + slippage_est),
        negative trades get penalty.
      - **hold_time_analysis**: Bucketed by short / medium / long hold times.
      - **timing_score**: Composite 0-100 score combining entry + exit + hold analysis.
    """
    cutoff = _cutoff_iso(days)
    conn: Optional[sqlite3.Connection] = None
    try:
        conn = get_connection()
        outcomes = _fetch_signal_outcomes(conn, cutoff)
        if not outcomes:
            logger.info("No signal outcomes for timing attribution in the last %d days.", days)
            return {"timing_score": 0.0, "entry_efficiency": 0.0, "exit_efficiency": 0.0,
                    "by_hold_bucket": {}}

        # --- Entry efficiency approximation ---
        # We approximate entry quality by looking at pnl_pct:
        # - High positive pnl_pct on a winning trade suggests good entry
        # - A win with tiny pnl_pct suggests marginal entry or late entry
        entry_scores: List[float] = []
        exit_scores: List[float] = []

        for o in outcomes:
            pnl_pct = o.get("pnl_pct", 0.0)
            entry_price = o.get("entry_price", 0.0)
            exit_price = o.get("exit_price", 0.0)
            side = o.get("side", "long")
            win = bool(o.get("win"))

            # Entry efficiency: for a long, lower entry is better.
            # Without intra-bar highs/lows, use pnl_pct magnitude as proxy.
            if entry_price > 0 and exit_price > 0:
                # Directional move captured
                if side.lower() in ("long", "buy"):
                    move_pct = ((exit_price - entry_price) / entry_price) * 100
                else:
                    move_pct = ((entry_price - exit_price) / entry_price) * 100

                # Normalize: +5% or more move → perfect score.
                # The idea is that capturing a large % move implies good entry.
                entry_eff = min(1.0, max(0.0, move_pct / 5.0)) if move_pct > 0 else 0.0
                entry_scores.append(entry_eff)

                # Exit efficiency: what fraction of the favorable move was captured?
                # Proxy: if win, score = pnl_pct / (pnl_pct + 0.5) to model
                # diminishing returns; if loss, score = 0.
                if win and pnl_pct > 0:
                    exit_eff = pnl_pct / (pnl_pct + 0.5)
                elif not win and pnl_pct < 0:
                    # Penalise: larger loss → lower score. Map [-10%, 0%] to [0, 0.3]
                    exit_eff = max(0.0, 0.3 + (pnl_pct / 10.0) * 0.3)
                else:
                    exit_eff = 0.3  # breakeven
                exit_scores.append(exit_eff)

        avg_entry_eff = _safe_div(sum(entry_scores), len(entry_scores))
        avg_exit_eff = _safe_div(sum(exit_scores), len(exit_scores))

        # --- Hold-time bucketed analysis ---
        hold_buckets: Dict[str, Dict[str, Any]] = {
            "short": {"pnl_list": [], "wins": 0, "label": "< 5 min"},
            "medium": {"pnl_list": [], "wins": 0, "label": "5 min - 1 hr"},
            "long": {"pnl_list": [], "wins": 0, "label": "> 1 hr"},
        }
        for o in outcomes:
            hold = o.get("hold_time_s", 0.0)
            pnl = o.get("pnl", 0.0)
            win = bool(o.get("win"))
            if hold < 300:
                bucket = "short"
            elif hold < 3600:
                bucket = "medium"
            else:
                bucket = "long"
            hold_buckets[bucket]["pnl_list"].append(pnl)
            if win:
                hold_buckets[bucket]["wins"] += 1

        by_hold_bucket: Dict[str, Any] = {}
        for label, data in hold_buckets.items():
            plist = data["pnl_list"]
            w = data["wins"]
            by_hold_bucket[label] = {
                "description": data["label"],
                "total_pnl": sum(plist),
                "num_trades": len(plist),
                "win_rate": _safe_div(w, len(plist)),
                "avg_pnl": _safe_div(sum(plist), len(plist)),
                "sharpe_ratio": _approx_sharpe(plist),
                "max_drawdown": _max_drawdown(plist),
            }

        # --- Composite timing score (0-100) ---
        # Weighted: 40% entry efficiency, 40% exit efficiency,
        # 20% bonus if medium-hold trades outperform
        medium_wr = by_hold_bucket.get("medium", {}).get("win_rate", 0.5)
        # Scale each component to 0-100
        timing_score = (
            avg_entry_eff * 40.0
            + avg_exit_eff * 40.0
            + medium_wr * 20.0
        )
        timing_score = max(0.0, min(100.0, timing_score))

        return {
            "timing_score": round(timing_score, 2),
            "entry_efficiency": round(avg_entry_eff, 4),
            "exit_efficiency": round(avg_exit_eff, 4),
            "by_hold_bucket": by_hold_bucket,
        }
    except Exception as exc:
        logger.error("Timing attribution failed: %s", exc, exc_info=True)
        return {"timing_score": 0.0, "entry_efficiency": 0.0, "exit_efficiency": 0.0,
                "by_hold_bucket": {}}
    finally:
        if conn:
            conn.close()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Full attribution report
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def compute_attribution(days: int = 30) -> AttributionReport:
    """Compute the full PnL attribution breakdown.

    Orchestrates all five dimensions and assembles them into an
    ``AttributionReport`` with top contributors / worst detractors.
    """
    report = AttributionReport(period_days=days)

    # --- 1. Strategy ---
    strat_raw = get_strategy_contribution(days)
    for name, data in strat_raw.items():
        sa = StrategyAttribution(
            strategy=name,
            total_pnl=data["total_pnl"],
            num_trades=data["num_trades"],
            win_rate=data["win_rate"],
            avg_pnl=data["avg_pnl"],
            sharpe_ratio=data["sharpe_ratio"],
            max_drawdown=data["max_drawdown"],
            pnl_contribution_pct=data.get("pnl_contribution_pct", 0.0),
            avg_confidence=data.get("avg_confidence", 0.0),
            avg_hold_time_s=data.get("avg_hold_time_s", 0.0),
        )
        report.by_strategy[name] = sa

    # --- 2. Regime ---
    regime_raw = get_regime_attribution(days)
    for name, data in regime_raw.items():
        ra = RegimeAttribution(
            regime=name,
            total_pnl=data["total_pnl"],
            num_trades=data["num_trades"],
            win_rate=data["win_rate"],
            avg_pnl=data["avg_pnl"],
            sharpe_ratio=data["sharpe_ratio"],
            max_drawdown=data["max_drawdown"],
            pnl_contribution_pct=data.get("pnl_contribution_pct", 0.0),
            avg_leverage=data.get("avg_leverage", 1.0),
        )
        report.by_regime[name] = ra

    # --- 3. Symbol (derived from signal_outcomes) ---
    cutoff = _cutoff_iso(days)
    conn: Optional[sqlite3.Connection] = None
    try:
        conn = get_connection()
        outcomes = _fetch_signal_outcomes(conn, cutoff)
        trades = _fetch_closed_trades(conn, cutoff)
    except Exception as exc:
        logger.error("Failed to fetch data for full attribution: %s", exc)
        outcomes = []
        trades = []
    finally:
        if conn:
            conn.close()

    # Symbol attribution from signal_outcomes
    sym_buckets: Dict[str, List[Dict]] = {}
    for o in outcomes:
        sym = o.get("symbol") or "UNKNOWN"
        sym_buckets.setdefault(sym, []).append(o)

    total_pnl_all = sum(o["pnl"] for o in outcomes) if outcomes else 0.0

    # Also compute total fees from trades by symbol
    fee_by_symbol: Dict[str, float] = {}
    for t in trades:
        sym = t.get("symbol", "UNKNOWN")
        fee_by_symbol[sym] = fee_by_symbol.get(sym, 0.0) + t.get("fee", 0.0)

    for sym, rows in sym_buckets.items():
        pnl_list = [r["pnl"] for r in rows]
        wins = sum(1 for r in rows if r.get("win"))
        n = len(rows)
        sa = SymbolAttribution(
            symbol=sym,
            total_pnl=sum(pnl_list),
            num_trades=n,
            win_rate=_safe_div(wins, n),
            avg_pnl=_safe_div(sum(pnl_list), n),
            sharpe_ratio=_approx_sharpe(pnl_list),
            max_drawdown=_max_drawdown(pnl_list),
            pnl_contribution_pct=_safe_div(sum(pnl_list), abs(total_pnl_all)) * 100
                if total_pnl_all != 0 else 0.0,
            total_fees=fee_by_symbol.get(sym, 0.0),
        )
        report.by_symbol[sym] = sa

    # --- 4. LLM value add ---
    llm_raw = get_llm_attribution(days)
    report.llm_value_add = llm_raw.get("llm_value_add", 0.0)

    # --- 5. Sizing alpha ---
    sizing_raw = get_sizing_attribution(days)
    report.sizing_alpha = sizing_raw.get("sizing_alpha", 0.0)

    # --- 6. Timing score ---
    timing_raw = get_timing_attribution(days)
    report.timing_score = timing_raw.get("timing_score", 0.0)

    # --- Totals ---
    report.total_pnl = total_pnl_all
    report.total_trades = len(outcomes)

    # --- Top contributors / worst detractors ---
    # Collect all labelled PnL sources and sort
    contributors: List[tuple] = []  # (label, pnl)
    for name, sa in report.by_strategy.items():
        contributors.append((f"strategy:{name}", sa.total_pnl))
    for name, ra in report.by_regime.items():
        contributors.append((f"regime:{name}", ra.total_pnl))
    for name, sa in report.by_symbol.items():
        contributors.append((f"symbol:{name}", sa.total_pnl))

    if report.llm_value_add != 0:
        contributors.append(("llm_filtering", report.llm_value_add))
    if report.sizing_alpha != 0:
        contributors.append(("position_sizing", report.sizing_alpha))

    # Sort descending by PnL
    contributors.sort(key=lambda x: x[1], reverse=True)

    report.top_contributors = [
        f"{label} ({pnl:+.4f})" for label, pnl in contributors if pnl > 0
    ][:10]
    report.worst_detractors = [
        f"{label} ({pnl:+.4f})" for label, pnl in reversed(contributors) if pnl < 0
    ][:10]

    logger.info(
        "Attribution computed: %d trades, PnL %.4f, %d contributors, %d detractors over %dd",
        report.total_trades, report.total_pnl,
        len(report.top_contributors), len(report.worst_detractors), days,
    )

    return report


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Text report formatter
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def format_attribution_report(report: AttributionReport) -> str:
    """Format an AttributionReport into a human-readable text report."""
    lines: List[str] = []
    sep = "-" * 72

    lines.append("=" * 72)
    lines.append("  PERFORMANCE ATTRIBUTION REPORT")
    lines.append(f"  Period: last {report.period_days} days")
    lines.append(f"  Total PnL: {report.total_pnl:+.4f}  |  Trades: {report.total_trades}")
    lines.append("=" * 72)

    # --- Strategy breakdown ---
    lines.append("")
    lines.append("  STRATEGY CONTRIBUTION")
    lines.append(sep)
    if report.by_strategy:
        # Sort by PnL descending
        sorted_strats = sorted(
            report.by_strategy.items(), key=lambda x: x[1].total_pnl, reverse=True
        )
        lines.append(
            f"  {'Strategy':<20} {'PnL':>10} {'Trades':>7} {'WinRate':>8} "
            f"{'AvgPnL':>10} {'Sharpe':>7} {'MaxDD':>10}"
        )
        lines.append("  " + "-" * 70)
        for name, sa in sorted_strats:
            lines.append(
                f"  {name:<20} {sa.total_pnl:>+10.4f} {sa.num_trades:>7} "
                f"{sa.win_rate:>7.1%} {sa.avg_pnl:>+10.4f} "
                f"{sa.sharpe_ratio:>7.2f} {sa.max_drawdown:>10.4f}"
            )
    else:
        lines.append("  No strategy data available.")

    # --- Regime breakdown ---
    lines.append("")
    lines.append("  REGIME CONTRIBUTION")
    lines.append(sep)
    if report.by_regime:
        sorted_regimes = sorted(
            report.by_regime.items(), key=lambda x: x[1].total_pnl, reverse=True
        )
        lines.append(
            f"  {'Regime':<20} {'PnL':>10} {'Trades':>7} {'WinRate':>8} "
            f"{'AvgPnL':>10} {'Sharpe':>7} {'AvgLev':>7}"
        )
        lines.append("  " + "-" * 70)
        for name, ra in sorted_regimes:
            lines.append(
                f"  {name:<20} {ra.total_pnl:>+10.4f} {ra.num_trades:>7} "
                f"{ra.win_rate:>7.1%} {ra.avg_pnl:>+10.4f} "
                f"{ra.sharpe_ratio:>7.2f} {ra.avg_leverage:>7.1f}x"
            )
    else:
        lines.append("  No regime data available.")

    # --- Symbol breakdown ---
    lines.append("")
    lines.append("  SYMBOL CONTRIBUTION")
    lines.append(sep)
    if report.by_symbol:
        sorted_syms = sorted(
            report.by_symbol.items(), key=lambda x: x[1].total_pnl, reverse=True
        )
        lines.append(
            f"  {'Symbol':<20} {'PnL':>10} {'Trades':>7} {'WinRate':>8} "
            f"{'AvgPnL':>10} {'Sharpe':>7} {'Fees':>10}"
        )
        lines.append("  " + "-" * 70)
        for name, sa in sorted_syms:
            lines.append(
                f"  {name:<20} {sa.total_pnl:>+10.4f} {sa.num_trades:>7} "
                f"{sa.win_rate:>7.1%} {sa.avg_pnl:>+10.4f} "
                f"{sa.sharpe_ratio:>7.2f} {sa.total_fees:>10.4f}"
            )
    else:
        lines.append("  No symbol data available.")

    # --- LLM contribution ---
    lines.append("")
    lines.append("  LLM DECISION CONTRIBUTION")
    lines.append(sep)
    lines.append(f"  LLM Value-Add (PnL from filtering): {report.llm_value_add:+.4f}")

    # --- Sizing contribution ---
    lines.append("")
    lines.append("  SIZING CONTRIBUTION")
    lines.append(sep)
    lines.append(f"  Sizing Alpha (actual vs equal-weight): {report.sizing_alpha:+.4f}")

    # --- Timing quality ---
    lines.append("")
    lines.append("  TIMING QUALITY")
    lines.append(sep)
    lines.append(f"  Composite Timing Score: {report.timing_score:.1f} / 100")

    # --- Top contributors / worst detractors ---
    lines.append("")
    lines.append("  TOP CONTRIBUTORS")
    lines.append(sep)
    if report.top_contributors:
        for i, c in enumerate(report.top_contributors, 1):
            lines.append(f"  {i:>3}. {c}")
    else:
        lines.append("  None (no positive PnL sources).")

    lines.append("")
    lines.append("  WORST DETRACTORS")
    lines.append(sep)
    if report.worst_detractors:
        for i, d in enumerate(report.worst_detractors, 1):
            lines.append(f"  {i:>3}. {d}")
    else:
        lines.append("  None (no negative PnL sources).")

    lines.append("")
    lines.append("=" * 72)

    return "\n".join(lines)
