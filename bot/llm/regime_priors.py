"""
Regime-keyed empirical-Bayes win-probability priors.

Motivation (2026-06-23 edge-map audit, n=101 ledger):
- "Pooled SHORT is +EV" is an illusion: the short edge lives ENTIRELY in
  trending_bear (+$1226). SHORT in neutral is ~breakeven; SHORT in
  range/consolidation is -EV. LONG is -EV in every regime including bull.
- The legacy prior in quant_brain.py is keyed by symbol_side ONLY, with no
  regime dimension, so a bear-regime short edge leaks into a bull regime.
- The legacy system baseline is contaminated: 71 of 101 ledger closes are
  LLM_EXIT_AGENT exits that are 0/71 by construction. Pooling them drags the
  baseline win-rate to ~0.19 when the true MECHANICAL-exit win-rate is ~0.63.

This module computes, from MECHANICAL-exit trades only, a recency-weighted,
shrunk win-probability keyed by (symbol, side, regime_bucket). It is gated
behind the USE_REGIME_PRIORS env flag (default FALSE) so live behavior is
unchanged until validated.

Design target (all parameters match the audit spec):
    KEY        = symbol . side . regime_bucket
    regime_bucket collapses regime_1h into {bull, bear, neutral}
                 (label contains 'bull' -> bull, 'bear' -> bear, else neutral)
    DATA       = mechanical-exit trades only
                 (exit_type in {SL, TP2, TRAILING_STOP, TIME_STOP};
                  exclude LLM_EXIT_AGENT)
    RECENCY    = weight each trade 0.5 ** (age_days / 21)
    SHRINKAGE  = shrunk_wp = (cell_wins + k*prior) / (cell_n + k), k=5,
                 where prior is the per-(side, regime_bucket) default
                 (NOT the global pooled value), so a SHORT in bull is pulled
                 toward the SHORT.bull default rather than the bear-driven
                 pooled value.

The win/sum counts are recency-weighted (fractional), so `cell_wins` and
`cell_n` below are weighted sums, not integer counts.
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger("bot.llm.regime_priors")

# Mechanical exit types — deterministic, rule-based closes whose outcome is a
# faithful test of entry edge. LLM_EXIT_AGENT (and any other non-mechanical
# discretionary close) is EXCLUDED because those closes are 0/71 by
# construction and contaminate any win-rate computed over them.
MECHANICAL_EXIT_TYPES = frozenset({"SL", "TP2", "TRAILING_STOP", "TIME_STOP"})

# Empirical-Bayes shrinkage strength (pseudo-count toward the per-cell prior).
SHRINKAGE_K = 5.0

# Recency half-life in days for the 0.5 ** (age_days / HALF_LIFE) weighting.
RECENCY_HALF_LIFE_DAYS = 21.0

# Minimum (recency-weighted) sample mass before a cell is trusted enough to
# override the legacy pooled logic. Below this, the caller should fall back.
COLD_CELL_THRESHOLD = 1.0

# Per-(side, regime_bucket) default win-probabilities. These are the priors the
# cell shrinks TOWARD. They encode the audit's directional finding without
# being a single global pooled number: SHORT has real edge only in bear,
# ~breakeven in neutral, weak in bull; LONG is weak everywhere.
# Sides accepted in both BUY/SELL and LONG/SHORT vocab (see _norm_side).
_SIDE_REGIME_DEFAULTS: Dict[Tuple[str, str], float] = {
    ("SHORT", "bear"):    0.60,
    ("SHORT", "neutral"): 0.50,
    ("SHORT", "bull"):    0.40,
    ("LONG", "bull"):     0.45,
    ("LONG", "neutral"):  0.38,
    ("LONG", "bear"):     0.32,
}

# Last-resort default when a (side, regime_bucket) pair is unknown.
_FALLBACK_DEFAULT = 0.40


def flag_enabled() -> bool:
    """True iff USE_REGIME_PRIORS is set to a truthy value (default FALSE)."""
    return os.getenv("USE_REGIME_PRIORS", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


def regime_bucket(regime_label: Optional[str]) -> str:
    """Collapse a fine-grained regime_1h label into {bull, bear, neutral}.

    'trending_bull' -> bull, 'trending_bear' -> bear, everything else
    (range, consolidation, high_volatility, unknown, ...) -> neutral.
    """
    label = (regime_label or "").lower()
    if "bull" in label:
        return "bull"
    if "bear" in label:
        return "bear"
    return "neutral"


def _norm_side(side: Optional[str]) -> str:
    """Normalize side vocab. Ledger uses LONG/SHORT; signals use BUY/SELL."""
    s = (side or "").strip().upper()
    if s in ("BUY", "LONG"):
        return "LONG"
    if s in ("SELL", "SHORT"):
        return "SHORT"
    return s


def side_regime_default(side: str, bucket: str) -> float:
    """Per-(side, regime_bucket) default win-prob — the shrinkage target."""
    return _SIDE_REGIME_DEFAULTS.get((_norm_side(side), bucket), _FALLBACK_DEFAULT)


def is_mechanical(exit_type: Optional[str]) -> bool:
    """True iff this exit_type counts as a mechanical (non-LLM) close."""
    return (exit_type or "").strip().upper() in MECHANICAL_EXIT_TYPES


def _won(trade: Dict[str, Any]) -> bool:
    """A trade won iff its realized net pnl is strictly positive."""
    for key in ("net_pnl", "pnl", "gross_pnl", "realized_pnl"):
        if key in trade and trade[key] not in (None, ""):
            try:
                return float(trade[key]) > 0.0
            except (ValueError, TypeError):
                continue
    return False


def _parse_ts(value: Any) -> Optional[float]:
    """Parse a timestamp into a unix epoch float. Accepts epoch or ISO-8601."""
    if value in (None, ""):
        return None
    # Numeric / numeric-string epoch
    try:
        return float(value)
    except (ValueError, TypeError):
        pass
    # ISO-8601
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def _recency_weight(trade_ts: Optional[float], now_ts: float) -> float:
    """0.5 ** (age_days / HALF_LIFE). Missing/future ts -> weight 1.0."""
    if trade_ts is None:
        return 1.0
    age_days = max(0.0, (now_ts - trade_ts) / 86400.0)
    return 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)


def mechanical_trades(trades: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter to mechanical-exit trades only (excludes LLM_EXIT_AGENT etc.)."""
    return [t for t in trades if is_mechanical(t.get("exit_type"))]


def pooled_mechanical_win_rate(
    trades: Iterable[Dict[str, Any]],
) -> Tuple[float, int]:
    """Unweighted pooled win-rate over mechanical-exit trades only.

    Returns (win_rate, n). This is the de-contaminated system baseline:
    LLM_EXIT_AGENT closes (0/71 by construction) are excluded.
    """
    mech = mechanical_trades(trades)
    n = len(mech)
    if n == 0:
        return (0.0, 0)
    wins = sum(1 for t in mech if _won(t))
    return (wins / n, n)


class RegimePriorTable:
    """Recency-weighted, shrunk win-prob keyed by (symbol, side, regime_bucket).

    Built from MECHANICAL-exit trades only. Each cell shrinks toward its
    per-(side, regime_bucket) default, so cold or noisy cells inherit the
    directional prior rather than the global pooled value.
    """

    def __init__(self, now_ts: Optional[float] = None):
        import time as _t
        self._now = now_ts if now_ts is not None else _t.time()
        # key -> [weighted_wins, weighted_n]
        self._cells: Dict[str, List[float]] = defaultdict(lambda: [0.0, 0.0])

    @staticmethod
    def cell_key(symbol: str, side: str, bucket: str) -> str:
        return f"{(symbol or '').upper()}.{_norm_side(side)}.{bucket}"

    def fit(self, trades: Iterable[Dict[str, Any]]) -> "RegimePriorTable":
        """Accumulate recency-weighted win/total mass per cell.

        Only mechanical-exit trades contribute. Each trade's contribution is
        weighted by 0.5 ** (age_days / 21).
        """
        for t in trades:
            if not is_mechanical(t.get("exit_type")):
                continue
            symbol = t.get("symbol", "")
            side = t.get("side", "")
            bucket = regime_bucket(t.get("regime_1h", t.get("regime", "")))
            key = self.cell_key(symbol, side, bucket)
            w = _recency_weight(_parse_ts(t.get("timestamp")), self._now)
            self._cells[key][1] += w
            if _won(t):
                self._cells[key][0] += w
        return self

    def cell_mass(self, symbol: str, side: str, bucket: str) -> Tuple[float, float]:
        """Return (weighted_wins, weighted_n) for a cell."""
        key = self.cell_key(symbol, side, bucket)
        wins, n = self._cells.get(key, [0.0, 0.0])
        return (wins, n)

    def win_prob(
        self,
        symbol: str,
        side: str,
        regime_label: str,
        k: float = SHRINKAGE_K,
    ) -> float:
        """Shrunk win-prob for (symbol, side, regime_bucket(regime_label)).

            shrunk_wp = (cell_wins + k*prior) / (cell_n + k)

        where prior = per-(side, regime_bucket) default. With an empty cell
        this returns exactly the per-cell default (full shrinkage).
        """
        bucket = regime_bucket(regime_label)
        prior = side_regime_default(side, bucket)
        wins, n = self.cell_mass(symbol, side, bucket)
        return (wins + k * prior) / (n + k)

    def is_cold(
        self,
        symbol: str,
        side: str,
        regime_label: str,
        threshold: float = COLD_CELL_THRESHOLD,
    ) -> bool:
        """True iff the cell has less weighted mass than `threshold`.

        Cold cells should fall back to the legacy pooled logic rather than
        trusting a near-empty regime cell.
        """
        bucket = regime_bucket(regime_label)
        _, n = self.cell_mass(symbol, side, bucket)
        return n < threshold


def build_table_from_ledger(
    data_dir: Optional[str] = None,
    now_ts: Optional[float] = None,
) -> Optional[RegimePriorTable]:
    """Build a RegimePriorTable from data/trade_ledger.csv.

    Returns None if the ledger is unavailable. Best-effort: never raises.
    """
    import csv
    try:
        if data_dir is None:
            data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
        path = os.path.join(data_dir, "trade_ledger.csv")
        if not os.path.exists(path):
            return None
        with open(path, "r", newline="") as f:
            rows = list(csv.DictReader(f))
        return RegimePriorTable(now_ts=now_ts).fit(rows)
    except Exception as e:
        logger.debug("regime_priors: could not build table from ledger: %s", e)
        return None
