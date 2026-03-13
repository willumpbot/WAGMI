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

KELLY_FLOOR = 0.05       # Minimum half-Kelly weight (never fully zero out a factor)
KELLY_CAP = 1.0          # Maximum half-Kelly weight
DEFAULT_LOOKBACK = 30    # Default rolling window for Kelly computation
MIN_TRADES_FOR_KELLY = 5 # Minimum trades before computing Kelly (use prior otherwise)

# ── Initial calibration from backtest data ───────────────────
# These seed the system before live trades accumulate.
BACKTEST_PRIORS: Dict[str, Dict[str, float]] = {
    "confidence_scorer": {"win_rate": 0.71, "payoff_ratio": 2.0},
    "bollinger_squeeze": {"win_rate": 0.60, "payoff_ratio": 1.73},
    "regime_trend": {"win_rate": 0.56, "payoff_ratio": 1.5},
}

# ── Persistence ──────────────────────────────────────────────

_DEFAULT_DATA_DIR = os.path.join("data", "kelly_weights.json")


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

        # Seed weights from backtest priors for factors with no trades
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
                    # Check if we have a backtest prior
                    if factor in BACKTEST_PRIORS:
                        wr = BACKTEST_PRIORS[factor]["win_rate"]
                        pr = BACKTEST_PRIORS[factor]["payoff_ratio"]
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
            # Fall back to backtest priors if available
            if factor in BACKTEST_PRIORS:
                prior = BACKTEST_PRIORS[factor]
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

    # ── Priors ───────────────────────────────────────────────

    def _apply_priors(self) -> None:
        """Seed weights from backtest priors for factors without live data."""
        for factor, prior in BACKTEST_PRIORS.items():
            if factor not in self._weights:
                raw = self._raw_kelly(prior["win_rate"], prior["payoff_ratio"])
                self._weights[factor] = self._clamp_kelly(raw / 2.0)
                logger.debug(
                    "Kelly prior applied: %s WR=%.0f%% PR=%.2f -> weight=%.3f",
                    factor, prior["win_rate"] * 100, prior["payoff_ratio"],
                    self._weights[factor],
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
