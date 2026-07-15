"""
Rolling Kelly Weight System: Per-factor half-Kelly computation from trade history.

Computes optimal position sizing weights per factor (strategy/signal source)
using the Kelly criterion applied to rolling trade outcomes. Uses half-Kelly
for conservative sizing, with floor/cap to prevent degenerate allocations.

Formula:
  f* = WR - (1 - WR) / payoff_ratio
  half_kelly = f* / 2
  Floored at 0.05, capped at 1.0

Persists weights to bot/data/kelly_weights.json. Thread-safe via Lock.
"""

import csv
import json
import logging
import math
import os
import threading
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bot.feedback.kelly_engine")

# ── Constants ────────────────────────────────────────────────

KELLY_FLOOR = 0.15        # Minimum half-Kelly weight — 0.05 was producing micro-positions
KELLY_CAP = 1.0           # Maximum half-Kelly weight
DEFAULT_LOOKBACK = 30     # Default rolling window for Kelly computation
MIN_TRADES_FOR_KELLY = 13 # House living-values standard: n>=13 before trusting a stat

# ── Ledger-derived priors (replaces stale hardcoded BACKTEST_PRIORS) ──
# When a factor has fewer than MIN_TRADES_FOR_KELLY in-session trades,
# weight is recomputed live from data/trade_ledger.csv (ground truth)
# instead of falling back to a frozen snapshot. See _ledger_prior() and
# _load_ledger_factor_trades() below. Below n=13 on the ledger too, the
# neutral KELLY_FLOOR is used — never a stale value.
LEDGER_PATH = os.path.join("data", "trade_ledger.csv")
_TEST_ENTRY_PRICES = {100.0, 150.0, 50000.0}  # sim/test entry prices to exclude

# ── Persistence ──────────────────────────────────────────────

_DEFAULT_DATA_DIR = os.path.join("data", "kelly_weights.json")


def _load_ledger_factor_trades(ledger_path: str = LEDGER_PATH) -> Dict[str, List[Dict[str, Any]]]:
    """Load per-factor trade outcomes from the live trade ledger (ground truth).

    Excludes TEST-symbol rows and sim/test entry prices (100, 150, 50000)
    per the house pollution filter. Explodes comma-separated
    contributing_factors so each factor gets its own won/pnl_pct record.
    """
    trades_by_factor: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    if not os.path.exists(ledger_path):
        return trades_by_factor
    try:
        with open(ledger_path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    symbol = (row.get("symbol") or "").upper()
                    entry_price = float(row.get("entry_price") or 0)
                    net_pnl = float(row["net_pnl"])
                    equity = float(row["running_equity"])
                    factors_s = (row.get("contributing_factors") or "").strip()
                except (KeyError, ValueError, TypeError):
                    continue
                if "TEST" in symbol or entry_price in _TEST_ENTRY_PRICES:
                    continue
                if not factors_s or equity <= 0:
                    continue
                won = net_pnl > 0
                pnl_pct = net_pnl / equity * 100.0
                for factor in factors_s.split(","):
                    factor = factor.strip()
                    if factor:
                        trades_by_factor[factor].append({"won": won, "pnl_pct": pnl_pct})
    except (IOError, csv.Error) as e:
        logger.warning("Failed to read ledger %s for Kelly priors: %s", ledger_path, e)
    return trades_by_factor


class KellyEngine:
    """
    Rolling Kelly weight system for per-factor position sizing.

    Records trade outcomes per factor, computes half-Kelly weights from
    rolling win rate and payoff ratio, and persists results to disk.
    """

    def __init__(self, data_path: str = None):
        self._data_path = data_path or _DEFAULT_DATA_DIR
        self._lock = threading.Lock()

        # Per-factor trade history: {factor: [{won: bool, pnl_pct: float, ts: float}, ...]}
        self._trades: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

        # Cached weights: {factor: float}
        self._weights: Dict[str, float] = {}

        self._load()

        # Seed weights from a live ledger recompute for factors with no trades
        self._apply_priors()

    # ── Public API ───────────────────────────────────────────

    def record_trade(self, factor: str, won: bool, pnl_pct: float) -> None:
        """Record a trade outcome for a given factor.

        Args:
            factor: Strategy/signal source name (e.g. 'confidence_scorer').
            won: Whether the trade was profitable.
            pnl_pct: Realized PnL as a percentage (e.g. 2.5 for +2.5%).
        """
        with self._lock:
            self._trades[factor].append({
                "won": won,
                "pnl_pct": pnl_pct,
                "ts": time.time(),
            })
            # Recompute weight for this factor
            self._weights[factor] = self._compute_kelly_weight_locked(factor)
            self._save()
            logger.info(
                "Kelly trade recorded: factor=%s won=%s pnl=%.2f%% -> weight=%.3f",
                factor, won, pnl_pct, self._weights[factor],
            )

    def compute_kelly_weight(self, factor: str, lookback: int = DEFAULT_LOOKBACK) -> float:
        """Compute half-Kelly weight for a factor from rolling trade history.

        Args:
            factor: Strategy/signal source name.
            lookback: Number of recent trades to consider.

        Returns:
            Half-Kelly weight floored at KELLY_FLOOR, capped at KELLY_CAP.
        """
        with self._lock:
            return self._compute_kelly_weight_locked(factor, lookback)

    def get_all_weights(self) -> Dict[str, float]:
        """Return all current factor Kelly weights.

        Returns:
            Dict mapping factor name to half-Kelly weight.
        """
        with self._lock:
            return dict(self._weights)

    def get_weights_per_factor(self) -> Dict[str, float]:
        """Return {factor: kelly_weight} for daily report compatibility."""
        return self.get_all_weights()

    def get_report(self) -> Dict[str, Any]:
        """Generate a full Kelly report with per-factor diagnostics.

        Returns:
            Dict with factor weights, win rates, payoff ratios, and sample counts.
        """
        with self._lock:
            report: Dict[str, Any] = {"factors": {}, "generated_at": time.time()}

            all_factors = set(list(self._trades.keys()) + list(self._weights.keys()))
            for factor in sorted(all_factors):
                trades = self._trades.get(factor, [])[-DEFAULT_LOOKBACK:]
                n = len(trades)
                if n == 0:
                    wr, pr = 0.0, 0.0
                    # Live recompute from the ledger (n>=13) — never a stale snapshot
                    prior = self._ledger_prior(factor)
                    if prior is not None:
                        wr = prior["win_rate"]
                        pr = prior["payoff_ratio"]
                else:
                    wr, pr = self._win_rate_and_payoff(trades)

                raw_kelly = self._raw_kelly(wr, pr)
                half_kelly = self._clamp_kelly(raw_kelly / 2.0)

                report["factors"][factor] = {
                    "weight": self._weights.get(factor, half_kelly),
                    "win_rate": round(wr, 4),
                    "payoff_ratio": round(pr, 4),
                    "raw_kelly": round(raw_kelly, 4),
                    "half_kelly": round(half_kelly, 4),
                    "sample_count": n,
                    "source": "live" if n >= MIN_TRADES_FOR_KELLY else "prior",
                }

            return report

    # ── Internal computation ─────────────────────────────────

    def _compute_kelly_weight_locked(
        self, factor: str, lookback: int = DEFAULT_LOOKBACK
    ) -> float:
        """Compute half-Kelly weight (must hold self._lock)."""
        trades = self._trades.get(factor, [])[-lookback:]

        if len(trades) < MIN_TRADES_FOR_KELLY:
            # Fall back to a live recompute from the trade ledger (n>=13),
            # never a stale hardcoded snapshot. Below that, neutral floor.
            prior = self._ledger_prior(factor)
            if prior is not None:
                raw = self._raw_kelly(prior["win_rate"], prior["payoff_ratio"])
                return self._clamp_kelly(raw / 2.0)
            return KELLY_FLOOR

        wr, pr = self._win_rate_and_payoff(trades)
        raw = self._raw_kelly(wr, pr)
        return self._clamp_kelly(raw / 2.0)

    @staticmethod
    def _win_rate_and_payoff(trades: List[Dict[str, Any]]) -> tuple:
        """Compute win rate and payoff ratio from a list of trade records.

        Returns:
            (win_rate, payoff_ratio) tuple. Payoff ratio is avg_win / avg_loss.
            Returns (0.0, 0.0) if insufficient data.
        """
        if not trades:
            return 0.0, 0.0

        wins = [t for t in trades if t["won"]]
        losses = [t for t in trades if not t["won"]]

        total = len(trades)
        win_rate = len(wins) / total

        # All wins: payoff ratio is technically infinite, use large cap
        if not losses:
            avg_win = sum(abs(t["pnl_pct"]) for t in wins) / len(wins) if wins else 0.0
            # Return high payoff to yield a strong Kelly, capped by KELLY_CAP downstream
            return win_rate, max(avg_win, 3.0)

        # All losses: payoff ratio is 0
        if not wins:
            return win_rate, 0.0

        avg_win = sum(abs(t["pnl_pct"]) for t in wins) / len(wins)
        avg_loss = sum(abs(t["pnl_pct"]) for t in losses) / len(losses)

        if avg_loss < 1e-10:
            # Losses are negligible, treat as high payoff
            return win_rate, max(avg_win, 3.0)

        payoff_ratio = avg_win / avg_loss
        return win_rate, payoff_ratio

    @staticmethod
    def _raw_kelly(win_rate: float, payoff_ratio: float) -> float:
        """Compute raw Kelly fraction: f* = WR - (1-WR) / payoff_ratio.

        Returns 0.0 if payoff_ratio is zero or negative f*.
        """
        if payoff_ratio <= 0:
            return 0.0
        f_star = win_rate - (1.0 - win_rate) / payoff_ratio
        return max(0.0, f_star)

    @staticmethod
    def _clamp_kelly(half_kelly: float) -> float:
        """Clamp half-Kelly to [KELLY_FLOOR, KELLY_CAP]."""
        return max(KELLY_FLOOR, min(KELLY_CAP, half_kelly))

    def _ledger_prior(self, factor: str) -> Optional[Dict[str, float]]:
        """Live win_rate/payoff_ratio for a factor, recomputed from the ledger.

        Requires n>=MIN_TRADES_FOR_KELLY ledger trades (house standard).
        Returns None below that threshold — callers must fall back to
        KELLY_FLOOR rather than any hardcoded snapshot.
        """
        ledger_trades = _load_ledger_factor_trades().get(factor, [])
        if len(ledger_trades) < MIN_TRADES_FOR_KELLY:
            return None
        wr, pr = self._win_rate_and_payoff(ledger_trades)
        return {"win_rate": wr, "payoff_ratio": pr, "n": len(ledger_trades)}

    # ── Priors ───────────────────────────────────────────────

    def _apply_priors(self) -> None:
        """Seed weights for factors with no in-session trades yet, from a
        live recompute of the trade ledger (n>=MIN_TRADES_FOR_KELLY) —
        never a stale hardcoded snapshot."""
        for factor, ledger_trades in _load_ledger_factor_trades().items():
            if factor in self._weights or len(ledger_trades) < MIN_TRADES_FOR_KELLY:
                continue
            wr, pr = self._win_rate_and_payoff(ledger_trades)
            raw = self._raw_kelly(wr, pr)
            self._weights[factor] = self._clamp_kelly(raw / 2.0)
            logger.debug(
                "Kelly ledger prior applied: %s n=%d WR=%.0f%% PR=%.2f -> weight=%.3f",
                factor, len(ledger_trades), wr * 100, pr, self._weights[factor],
            )

    # ── Persistence ──────────────────────────────────────────

    def _load(self) -> None:
        """Load persisted trade history and weights from disk."""
        if not os.path.exists(self._data_path):
            return
        try:
            with open(self._data_path, "r") as f:
                data = json.load(f)
            self._trades = defaultdict(list, data.get("trades", {}))
            self._weights = data.get("weights", {})
            logger.info(
                "Kelly state loaded: %d factors, %d total trades",
                len(self._weights),
                sum(len(v) for v in self._trades.values()),
            )
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("Failed to load Kelly state from %s: %s", self._data_path, e)

    def _save(self) -> None:
        """Persist current trade history and weights to disk."""
        try:
            os.makedirs(os.path.dirname(self._data_path) or ".", exist_ok=True)
            data = {
                "trades": dict(self._trades),
                "weights": self._weights,
                "updated_at": time.time(),
            }
            with open(self._data_path, "w") as f:
                json.dump(data, f, indent=2)
        except IOError as e:
            logger.error("Failed to save Kelly state to %s: %s", self._data_path, e)
