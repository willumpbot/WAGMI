"""
Rolling Correlation Gate: Prevents correlated positions from creating concentrated risk.

Maintains a rolling window of price data per symbol, computes Pearson correlation
of log returns between pairs, and gates new position sizing based on correlation
clustering with existing open positions.

Size multiplier output:
  1.0 — No significant correlation, full size allowed
  0.5 — High correlation cluster detected, reduce size
  0.0 — Cluster exposure limit exceeded, skip position

All math uses stdlib only (no numpy). Thread-safe via Lock.
Price history stored in-memory with bounded deques.
"""

import logging
import math
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger("bot.execution.correlation_gate")

# ── Constants ────────────────────────────────────────────────

CORR_WINDOW = 30         # Number of periods for correlation computation
HIGH_CORR = 0.80         # Threshold for "highly correlated" treatment
CLUSTER_LIMIT = 1.5      # Max cluster exposure as multiple of risk_per_trade
PRICE_HISTORY_LEN = 200  # Max price observations stored per symbol
MIN_OBSERVATIONS = 10    # Minimum shared observations to compute correlation


class CorrelationGate:
    """
    Rolling correlation gate for portfolio concentration risk.

    Feeds streaming price data, computes pairwise Pearson correlations of
    log returns, and returns a sizing multiplier when evaluating whether a
    new position should be added alongside existing positions.
    """

    def __init__(
        self,
        corr_window: int = CORR_WINDOW,
        high_corr: float = HIGH_CORR,
        cluster_limit: float = CLUSTER_LIMIT,
    ):
        self._corr_window = corr_window
        self._high_corr = high_corr
        self._cluster_limit = cluster_limit
        self._lock = threading.Lock()

        # Per-symbol price history: {symbol: deque of (timestamp, price)}
        self._prices: Dict[str, Deque[Tuple[float, float]]] = {}

        # Cached correlation matrix: {(sym_a, sym_b): correlation}
        self._corr_cache: Dict[Tuple[str, str], float] = {}
        self._cache_ts: float = 0.0
        self._cache_ttl: float = 60.0  # Refresh cache every 60 seconds

    # ── Public API ───────────────────────────────────────────

    def update_prices(self, symbol: str, price: float, timestamp: float) -> None:
        """Feed a new price observation for a symbol.

        Args:
            symbol: Trading pair (e.g. 'BTC/USDT').
            price: Current price.
            timestamp: Unix timestamp of the observation.
        """
        if price <= 0:
            return

        with self._lock:
            if symbol not in self._prices:
                self._prices[symbol] = deque(maxlen=PRICE_HISTORY_LEN)
            self._prices[symbol].append((timestamp, price))
            # Invalidate cache on new data
            self._cache_ts = 0.0

    def compute_correlation(
        self, sym_a: str, sym_b: str, window: int = None
    ) -> float:
        """Compute Pearson correlation of log returns between two symbols.

        Args:
            sym_a: First symbol.
            sym_b: Second symbol.
            window: Number of recent periods to use (default: CORR_WINDOW).

        Returns:
            Pearson correlation coefficient in [-1.0, 1.0].
            Returns 0.0 if insufficient data.
        """
        if sym_a == sym_b:
            return 1.0

        window = window or self._corr_window

        with self._lock:
            return self._compute_correlation_locked(sym_a, sym_b, window)

    def check_correlation_budget(
        self,
        new_symbol: str,
        new_side: str,
        open_positions: List[Dict[str, Any]],
    ) -> float:
        """Check correlation budget and return a sizing multiplier.

        Evaluates how correlated the new_symbol is with existing open positions
        and returns a multiplier to scale position size accordingly.

        Args:
            new_symbol: Symbol of the proposed new position.
            new_side: Side of the proposed position ('BUY' or 'SELL', or 'long'/'short').
            open_positions: List of dicts with at least {'symbol': str, 'side': str}.
                           Side can be 'BUY'/'SELL' or 'long'/'short'.

        Returns:
            1.0 — Full size (no correlation concern)
            0.5 — Cluster detected, reduce size
            0.0 — Cluster limit exceeded, skip position
        """
        if not open_positions:
            return 1.0

        new_dir = self._side_to_direction(new_side)

        with self._lock:
            self._refresh_cache_if_stale()

            # Compute effective directional correlation with each open position
            cluster_exposure = 0.0
            cluster_count = 0

            for pos in open_positions:
                pos_symbol = pos.get("symbol", "")
                pos_side = pos.get("side", "")

                if not pos_symbol or pos_symbol == new_symbol:
                    continue

                pos_dir = self._side_to_direction(pos_side)
                corr = self._compute_correlation_locked(
                    new_symbol, pos_symbol, self._corr_window
                )

                # Effective correlation accounts for direction:
                # Same direction + high correlation = concentrated risk
                # Opposite direction + high correlation = hedged
                effective_corr = corr * new_dir * pos_dir

                if effective_corr >= self._high_corr:
                    cluster_exposure += effective_corr
                    cluster_count += 1
                    logger.info(
                        "Correlation cluster: %s (%s) <-> %s (%s) corr=%.3f eff=%.3f",
                        new_symbol, new_side, pos_symbol, pos_side,
                        corr, effective_corr,
                    )

            if cluster_count == 0:
                return 1.0

            # Check against cluster limit
            if cluster_exposure >= self._cluster_limit:
                logger.warning(
                    "Correlation budget EXCEEDED for %s: cluster_exposure=%.2f >= limit=%.1f — SKIP",
                    new_symbol, cluster_exposure, self._cluster_limit,
                )
                return 0.0

            # Partial reduction: scale between 0.5 and 1.0 based on exposure
            logger.info(
                "Correlation cluster detected for %s: %d correlated positions, "
                "cluster_exposure=%.2f — reducing size to 0.5x",
                new_symbol, cluster_count, cluster_exposure,
            )
            return 0.5

    def get_correlation_matrix(self) -> Dict[str, Any]:
        """Return the current pairwise correlation matrix.

        Returns:
            Dict with 'symbols', 'matrix' (nested dict), and 'timestamp'.
        """
        with self._lock:
            self._refresh_cache_if_stale()
            symbols = sorted(self._prices.keys())
            matrix: Dict[str, Dict[str, float]] = {}

            for sym_a in symbols:
                matrix[sym_a] = {}
                for sym_b in symbols:
                    if sym_a == sym_b:
                        matrix[sym_a][sym_b] = 1.0
                    else:
                        key = self._cache_key(sym_a, sym_b)
                        matrix[sym_a][sym_b] = round(
                            self._corr_cache.get(key, 0.0), 4
                        )

            return {
                "symbols": symbols,
                "matrix": matrix,
                "timestamp": time.time(),
                "window": self._corr_window,
            }

    # ── Internal computation ─────────────────────────────────

    def _compute_correlation_locked(
        self, sym_a: str, sym_b: str, window: int
    ) -> float:
        """Compute Pearson correlation of log returns (must hold self._lock)."""
        prices_a = self._prices.get(sym_a)
        prices_b = self._prices.get(sym_b)

        if not prices_a or not prices_b:
            return 0.0

        # Get log returns for each symbol
        returns_a = self._log_returns(prices_a, window + 1)
        returns_b = self._log_returns(prices_b, window + 1)

        if len(returns_a) < MIN_OBSERVATIONS or len(returns_b) < MIN_OBSERVATIONS:
            return 0.0

        # Align to the shorter series (most recent observations)
        n = min(len(returns_a), len(returns_b))
        returns_a = returns_a[-n:]
        returns_b = returns_b[-n:]

        return _pearson_correlation(returns_a, returns_b)

    def _refresh_cache_if_stale(self) -> None:
        """Rebuild correlation cache if stale (must hold self._lock)."""
        now = time.time()
        if now - self._cache_ts < self._cache_ttl:
            return

        symbols = list(self._prices.keys())
        for i, sym_a in enumerate(symbols):
            for j in range(i + 1, len(symbols)):
                sym_b = symbols[j]
                corr = self._compute_correlation_locked(
                    sym_a, sym_b, self._corr_window
                )
                key = self._cache_key(sym_a, sym_b)
                self._corr_cache[key] = corr

        self._cache_ts = now

    @staticmethod
    def _cache_key(sym_a: str, sym_b: str) -> Tuple[str, str]:
        """Canonical cache key (sorted to avoid duplicates)."""
        return (min(sym_a, sym_b), max(sym_a, sym_b))

    @staticmethod
    def _log_returns(
        prices: Deque[Tuple[float, float]], max_periods: int
    ) -> List[float]:
        """Compute log returns from a price deque.

        Args:
            prices: Deque of (timestamp, price) tuples.
            max_periods: Maximum number of price points to consider.

        Returns:
            List of log(p[i] / p[i-1]) values.
        """
        # Take the most recent max_periods prices
        recent = list(prices)[-max_periods:]
        returns = []
        for i in range(1, len(recent)):
            p_prev = recent[i - 1][1]
            p_curr = recent[i][1]
            if p_prev > 0 and p_curr > 0:
                returns.append(math.log(p_curr / p_prev))
        return returns

    @staticmethod
    def _side_to_direction(side: str) -> float:
        """Convert side string to directional multiplier.

        Returns +1.0 for long/buy, -1.0 for short/sell.
        """
        s = side.strip().upper()
        if s in ("BUY", "LONG"):
            return 1.0
        elif s in ("SELL", "SHORT"):
            return -1.0
        return 1.0  # Default to long if ambiguous


# ── Standalone math helpers (stdlib only) ────────────────────

def _mean(xs: List[float]) -> float:
    """Arithmetic mean."""
    if not xs:
        return 0.0
    return sum(xs) / len(xs)


def _pearson_correlation(xs: List[float], ys: List[float]) -> float:
    """Pearson correlation coefficient between two equal-length series.

    Returns 0.0 if fewer than MIN_OBSERVATIONS points or zero variance.
    """
    n = min(len(xs), len(ys))
    if n < MIN_OBSERVATIONS:
        return 0.0

    xs = xs[:n]
    ys = ys[:n]

    mx = _mean(xs)
    my = _mean(ys)

    # Compute covariance and standard deviations in a single pass
    cov = 0.0
    var_x = 0.0
    var_y = 0.0
    for i in range(n):
        dx = xs[i] - mx
        dy = ys[i] - my
        cov += dx * dy
        var_x += dx * dx
        var_y += dy * dy

    sx = math.sqrt(var_x / n)
    sy = math.sqrt(var_y / n)

    if sx < 1e-15 or sy < 1e-15:
        return 0.0

    r = (cov / n) / (sx * sy)
    return max(-1.0, min(1.0, r))
