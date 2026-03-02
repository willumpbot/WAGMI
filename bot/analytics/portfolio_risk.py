"""
Portfolio Risk Engine: Correlation matrix, dynamic position limits,
portfolio risk budgeting, and volatility forecasting.

Wave 3 portfolio-level alpha:
- Correlation matrix (Pearson on log returns) to detect clustered risk
- EWMA volatility forecasting (RiskMetrics lambda=0.94)
- Risk budget allocation across positions
- Cascade detection (BTC dump -> alt follow-through)
- Rebalance suggestions when correlation spikes

All math uses stdlib only (no numpy/scipy). Thread-safe via Lock.
Price history kept in memory with periodic JSON persistence.
"""

import json
import logging
import math
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("bot.portfolio_risk")

# ── Constants ────────────────────────────────────────────────

EWMA_LAMBDA = 0.94  # RiskMetrics standard decay factor
ANNUALIZATION_FACTOR = math.sqrt(365 * 24)  # Hourly data -> annualized
TRADING_HOURS_PER_DAY = 24  # Crypto trades 24/7
DAILY_ANNUALIZATION = math.sqrt(365)

# Vol regime thresholds (annualized %)
VOL_REGIME_LOW = 15.0
VOL_REGIME_NORMAL = 40.0
VOL_REGIME_HIGH = 80.0

# Default vol half-life assumptions (hours) by regime
VOL_HALF_LIFE = {
    "low": 168.0,       # 1 week to mean-revert from low vol
    "normal": 72.0,     # 3 days
    "high": 48.0,       # 2 days
    "extreme": 24.0,    # 1 day — extreme vol reverts fastest
}

# Major crypto leaders for cascade detection
CASCADE_LEADERS = ["BTC", "ETH"]


# ── Data Classes ─────────────────────────────────────────────

@dataclass
class CorrelationMatrix:
    """Pairwise correlation matrix for a set of symbols."""
    symbols: List[str]
    matrix: List[List[float]]  # NxN correlation matrix
    timestamp: float
    lookback_hours: int

    def get_correlation(self, sym_a: str, sym_b: str) -> float:
        """Get pairwise correlation between two symbols.
        Returns 0.0 if either symbol is not in the matrix."""
        if sym_a == sym_b:
            return 1.0
        try:
            i = self.symbols.index(sym_a)
            j = self.symbols.index(sym_b)
            return self.matrix[i][j]
        except (ValueError, IndexError):
            return 0.0

    def get_cluster_risk(self, positions: Dict[str, str]) -> float:
        """Compute aggregate correlation risk for current portfolio.

        positions: {symbol: side} where side is "long" or "short".

        Returns a risk score 0-1 where:
          0.0 = perfectly uncorrelated / hedged portfolio
          1.0 = all positions maximally correlated in same direction

        Two longs with +0.9 correlation = high risk.
        A long and a short with +0.9 correlation = hedged (low risk).
        """
        syms = [s for s in positions if s in self.symbols]
        n = len(syms)
        if n <= 1:
            return 0.0

        # Build direction vector: +1 for long, -1 for short
        directions = []
        for sym in syms:
            side = positions[sym].lower()
            directions.append(1.0 if side == "long" else -1.0)

        # Compute average directional correlation
        # For each pair, effective_corr = corr * dir_i * dir_j
        # If both long and highly correlated -> positive (risky)
        # If long/short and highly correlated -> negative (hedged)
        total_corr = 0.0
        pair_count = 0
        for i in range(n):
            for j in range(i + 1, n):
                corr = self.get_correlation(syms[i], syms[j])
                effective = corr * directions[i] * directions[j]
                total_corr += effective
                pair_count += 1

        if pair_count == 0:
            return 0.0

        avg_corr = total_corr / pair_count
        # Clamp to [0, 1] — negative means hedged, treat as 0 risk
        return max(0.0, min(1.0, avg_corr))


@dataclass
class VolatilityForecast:
    """Volatility forecast for a single symbol."""
    symbol: str
    current_vol: float       # Current realized volatility (annualized %)
    forecast_vol: float      # Predicted next-period volatility (annualized %)
    vol_regime: str          # "low", "normal", "high", "extreme"
    confidence: float        # 0-1 confidence in forecast
    half_life_hours: float   # How long until vol mean-reverts


@dataclass
class RiskBudget:
    """Portfolio risk budget allocation."""
    total_risk_pct: float                   # Total portfolio risk as % of equity
    per_position_risk: Dict[str, float]     # symbol -> risk allocation %
    remaining_budget: float                 # How much risk budget is available (%)
    utilization: float                      # 0-1, how much of budget is used
    concentration_warning: str              # "" or warning message


# ── Helper Math (stdlib only) ────────────────────────────────

def _mean(xs: List[float]) -> float:
    """Arithmetic mean."""
    if not xs:
        return 0.0
    return sum(xs) / len(xs)


def _variance(xs: List[float], mean_val: float = None) -> float:
    """Population variance."""
    if len(xs) < 2:
        return 0.0
    if mean_val is None:
        mean_val = _mean(xs)
    return sum((x - mean_val) ** 2 for x in xs) / len(xs)


def _std(xs: List[float]) -> float:
    """Population standard deviation."""
    return _variance(xs) ** 0.5


def _covariance(xs: List[float], ys: List[float]) -> float:
    """Population covariance between two series of equal length."""
    n = min(len(xs), len(ys))
    if n < 2:
        return 0.0
    mx = _mean(xs[:n])
    my = _mean(ys[:n])
    return sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / n


def _pearson_correlation(xs: List[float], ys: List[float]) -> float:
    """Pearson correlation coefficient between two series."""
    n = min(len(xs), len(ys))
    if n < 5:
        return 0.0
    xs = xs[:n]
    ys = ys[:n]
    sx = _std(xs)
    sy = _std(ys)
    if sx < 1e-15 or sy < 1e-15:
        return 0.0
    cov = _covariance(xs, ys)
    return max(-1.0, min(1.0, cov / (sx * sy)))


def _log_returns(prices: List[Tuple[float, float]]) -> List[float]:
    """Compute log returns from a list of (timestamp, price) tuples.
    Returns list of log(p[i] / p[i-1])."""
    returns = []
    for i in range(1, len(prices)):
        p_prev = prices[i - 1][1]
        p_curr = prices[i][1]
        if p_prev > 0 and p_curr > 0:
            returns.append(math.log(p_curr / p_prev))
    return returns


def _ewma_variance(returns: List[float], lam: float = EWMA_LAMBDA) -> float:
    """Exponentially weighted moving average variance.
    Uses RiskMetrics approach: sigma^2_t = lambda * sigma^2_{t-1} + (1-lambda) * r^2_{t-1}
    """
    if len(returns) < 2:
        return 0.0
    # Initialize with simple variance of first few returns
    init_n = min(10, len(returns))
    var = _variance(returns[:init_n])
    if var < 1e-20:
        var = 1e-10  # Floor to avoid zero

    for r in returns[init_n:]:
        var = lam * var + (1 - lam) * r * r
    return var


def _classify_vol_regime(annualized_vol: float) -> str:
    """Classify volatility into a regime bucket."""
    if annualized_vol < VOL_REGIME_LOW:
        return "low"
    elif annualized_vol < VOL_REGIME_NORMAL:
        return "normal"
    elif annualized_vol < VOL_REGIME_HIGH:
        return "high"
    else:
        return "extreme"


# ── Portfolio Risk Engine ────────────────────────────────────

class PortfolioRiskEngine:
    """Portfolio-level risk management: correlation, volatility, risk budgets.

    Thread-safe. All math in stdlib (no numpy/scipy).
    Price history lives in memory with periodic JSON persistence.
    """

    def __init__(self, data_dir: str = "data/portfolio_risk"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

        self._lock = threading.Lock()

        # Price history: symbol -> [(timestamp, price)]
        self._price_history: Dict[str, List[Tuple[float, float]]] = {}
        self._max_history = 500  # Keep last 500 price points per symbol

        # Cached results
        self._correlation_cache: Optional[CorrelationMatrix] = None
        self._vol_forecasts: Dict[str, VolatilityForecast] = {}
        self._last_persist_time: float = 0.0
        self._persist_interval: float = 300.0  # Persist every 5 minutes

        # File paths
        self._price_file = os.path.join(data_dir, "price_history.json")
        self._corr_file = os.path.join(data_dir, "correlation_cache.json")
        self._vol_file = os.path.join(data_dir, "volatility_forecasts.json")

        self._load_state()
        logger.info(
            "[PORTFOLIO-RISK] Initialized with %d symbols tracked",
            len(self._price_history),
        )

    # ── Price Recording ──────────────────────────────────────

    def record_price(self, symbol: str, price: float,
                     timestamp: float = None):
        """Record a price observation for correlation computation."""
        if price <= 0:
            return
        if timestamp is None:
            timestamp = time.time()

        with self._lock:
            if symbol not in self._price_history:
                self._price_history[symbol] = []

            history = self._price_history[symbol]
            # Avoid duplicate timestamps (within 1 second)
            if history and abs(history[-1][0] - timestamp) < 1.0:
                return
            history.append((timestamp, price))

            # Trim to max history
            if len(history) > self._max_history:
                self._price_history[symbol] = history[-self._max_history:]

    # ── Correlation Matrix ───────────────────────────────────

    def compute_correlation_matrix(
        self,
        symbols: List[str] = None,
        lookback_hours: int = 168,
    ) -> CorrelationMatrix:
        """Compute pairwise correlation matrix from recent price data.

        Uses log returns for proper financial correlation.
        Only includes symbols with sufficient overlapping data.

        Args:
            symbols: List of symbols to include (None = all tracked).
            lookback_hours: How far back to look (default 168 = 1 week).

        Returns:
            CorrelationMatrix with NxN correlation values.
        """
        now = time.time()
        cutoff = now - lookback_hours * 3600

        with self._lock:
            if symbols is None:
                symbols = sorted(self._price_history.keys())

            # Filter to symbols with enough data
            valid_symbols = []
            symbol_returns: Dict[str, List[float]] = {}
            for sym in symbols:
                hist = self._price_history.get(sym, [])
                # Filter to lookback window
                recent = [(t, p) for t, p in hist if t >= cutoff]
                if len(recent) < 10:
                    continue
                rets = _log_returns(recent)
                if len(rets) >= 5:
                    valid_symbols.append(sym)
                    symbol_returns[sym] = rets

        n = len(valid_symbols)
        if n == 0:
            matrix = CorrelationMatrix(
                symbols=[], matrix=[], timestamp=now,
                lookback_hours=lookback_hours,
            )
            self._correlation_cache = matrix
            return matrix

        # Build NxN correlation matrix
        corr_matrix: List[List[float]] = []
        for i in range(n):
            row = []
            for j in range(n):
                if i == j:
                    row.append(1.0)
                elif j < i:
                    # Already computed — symmetric
                    row.append(corr_matrix[j][i])
                else:
                    # Align returns by using last min(len_a, len_b) values
                    rets_a = symbol_returns[valid_symbols[i]]
                    rets_b = symbol_returns[valid_symbols[j]]
                    min_len = min(len(rets_a), len(rets_b))
                    corr = _pearson_correlation(
                        rets_a[-min_len:], rets_b[-min_len:]
                    )
                    row.append(round(corr, 4))
            corr_matrix.append(row)

        matrix = CorrelationMatrix(
            symbols=valid_symbols,
            matrix=corr_matrix,
            timestamp=now,
            lookback_hours=lookback_hours,
        )
        self._correlation_cache = matrix
        self._persist_correlation(matrix)
        return matrix

    # ── Volatility Forecasting ───────────────────────────────

    def forecast_volatility(self, symbol: str) -> VolatilityForecast:
        """Simple EWMA volatility forecast (exponentially weighted).

        This is a lightweight alternative to GARCH that works well in
        practice. Uses RiskMetrics lambda=0.94.

        Vol regime classification:
            <15% annualized  = "low"
            15-40%           = "normal"
            40-80%           = "high"
            >80%             = "extreme"
        """
        with self._lock:
            hist = self._price_history.get(symbol, [])

        if len(hist) < 10:
            forecast = VolatilityForecast(
                symbol=symbol,
                current_vol=0.0,
                forecast_vol=0.0,
                vol_regime="normal",
                confidence=0.0,
                half_life_hours=72.0,
            )
            self._vol_forecasts[symbol] = forecast
            return forecast

        returns = _log_returns(hist)
        if len(returns) < 5:
            forecast = VolatilityForecast(
                symbol=symbol,
                current_vol=0.0,
                forecast_vol=0.0,
                vol_regime="normal",
                confidence=0.0,
                half_life_hours=72.0,
            )
            self._vol_forecasts[symbol] = forecast
            return forecast

        # Estimate sampling frequency from timestamps
        time_diffs = [
            hist[i][0] - hist[i - 1][0]
            for i in range(1, len(hist))
            if hist[i][0] > hist[i - 1][0]
        ]
        if time_diffs:
            avg_interval_hours = _mean(time_diffs) / 3600.0
        else:
            avg_interval_hours = 1.0  # Default to hourly
        avg_interval_hours = max(avg_interval_hours, 0.01)  # Floor

        # Periods per year for annualization
        periods_per_year = (365 * 24) / avg_interval_hours

        # Current realized vol (simple std of recent returns, annualized)
        recent_n = min(50, len(returns))
        recent_returns = returns[-recent_n:]
        realized_std = _std(recent_returns)
        current_vol = realized_std * math.sqrt(periods_per_year) * 100  # -> %

        # EWMA forecast variance
        ewma_var = _ewma_variance(returns, lam=EWMA_LAMBDA)
        forecast_std = ewma_var ** 0.5
        forecast_vol = forecast_std * math.sqrt(periods_per_year) * 100  # -> %

        # Classify regime
        vol_regime = _classify_vol_regime(forecast_vol)

        # Confidence based on amount of data
        data_confidence = min(1.0, len(returns) / 100.0)
        # Reduce confidence in extreme regimes (harder to predict)
        regime_penalty = 1.0 if vol_regime in ("low", "normal") else 0.8
        confidence = round(data_confidence * regime_penalty, 2)

        half_life = VOL_HALF_LIFE.get(vol_regime, 72.0)

        forecast = VolatilityForecast(
            symbol=symbol,
            current_vol=round(current_vol, 2),
            forecast_vol=round(forecast_vol, 2),
            vol_regime=vol_regime,
            confidence=confidence,
            half_life_hours=half_life,
        )

        self._vol_forecasts[symbol] = forecast
        return forecast

    # ── Risk Budgeting ───────────────────────────────────────

    def compute_risk_budget(
        self,
        equity: float,
        open_positions: Dict[str, Any],
        max_portfolio_risk_pct: float = 5.0,
    ) -> RiskBudget:
        """Compute current portfolio risk utilization and remaining budget.

        Risk per position = (notional / equity) * daily_vol * corr_adjustment
        Total risk = sum of per-position risk

        Args:
            equity: Current account equity in USD.
            open_positions: {symbol: {"side": str, "size_usd": float, ...}}
            max_portfolio_risk_pct: Maximum allowed portfolio risk %.

        Returns:
            RiskBudget with utilization and remaining budget.
        """
        if equity <= 0 or not open_positions:
            return RiskBudget(
                total_risk_pct=0.0,
                per_position_risk={},
                remaining_budget=max_portfolio_risk_pct,
                utilization=0.0,
                concentration_warning="",
            )

        # Get correlation matrix if available
        corr_matrix = self._correlation_cache
        if corr_matrix is None:
            corr_matrix = self.compute_correlation_matrix()

        # Build positions map for cluster risk
        position_sides = {}
        for sym, pos_data in open_positions.items():
            side = pos_data.get("side", "long") if isinstance(pos_data, dict) else "long"
            position_sides[sym] = side

        cluster_risk = corr_matrix.get_cluster_risk(position_sides)
        # Correlation adjustment: 1.0 (uncorrelated) to 1.5 (highly correlated)
        corr_adjustment = 1.0 + cluster_risk * 0.5

        per_position_risk: Dict[str, float] = {}
        total_risk = 0.0
        max_single_risk = 0.0
        max_risk_symbol = ""

        for sym, pos_data in open_positions.items():
            if isinstance(pos_data, dict):
                notional = abs(pos_data.get("size_usd", 0.0))
            else:
                notional = 0.0

            # Get vol forecast for daily vol estimate
            vol_forecast = self._vol_forecasts.get(sym)
            if vol_forecast is None:
                vol_forecast = self.forecast_volatility(sym)

            # Convert annualized vol to daily vol
            daily_vol_pct = vol_forecast.forecast_vol / DAILY_ANNUALIZATION
            if daily_vol_pct < 0.1:
                daily_vol_pct = 2.0  # Default 2% daily vol if no data

            # Position risk = (notional / equity) * daily_vol% * sqrt(corr_factor)
            leverage_ratio = notional / equity if equity > 0 else 0
            pos_risk = leverage_ratio * daily_vol_pct * math.sqrt(corr_adjustment)
            pos_risk = round(pos_risk, 4)
            per_position_risk[sym] = pos_risk
            total_risk += pos_risk

            if pos_risk > max_single_risk:
                max_single_risk = pos_risk
                max_risk_symbol = sym

        total_risk = round(total_risk, 4)
        remaining = max(0.0, max_portfolio_risk_pct - total_risk)
        utilization = min(1.0, total_risk / max_portfolio_risk_pct) if max_portfolio_risk_pct > 0 else 1.0

        # Concentration warning
        concentration_warning = ""
        if len(per_position_risk) >= 2 and max_single_risk > 0:
            concentration = max_single_risk / total_risk if total_risk > 0 else 0
            if concentration > 0.6:
                concentration_warning = (
                    f"High concentration: {max_risk_symbol} accounts for "
                    f"{concentration * 100:.0f}% of portfolio risk"
                )
        if cluster_risk > 0.7:
            corr_warn = (
                f"High correlation risk ({cluster_risk:.2f}): "
                f"positions are heavily correlated in same direction"
            )
            if concentration_warning:
                concentration_warning += "; " + corr_warn
            else:
                concentration_warning = corr_warn

        return RiskBudget(
            total_risk_pct=total_risk,
            per_position_risk=per_position_risk,
            remaining_budget=round(remaining, 4),
            utilization=round(utilization, 4),
            concentration_warning=concentration_warning,
        )

    # ── Dynamic Position Limits ──────────────────────────────

    def get_position_limit(
        self,
        symbol: str,
        side: str,
        open_positions: Dict[str, Any],
        equity: float,
    ) -> Dict:
        """Dynamic position limit based on correlation and risk budget.

        Considers:
        1. Current vol regime for the symbol
        2. Correlation with existing positions
        3. Remaining risk budget

        Returns:
            {"max_qty_pct": float, "reason": str, "risk_level": str}
            max_qty_pct: max position size as % of equity (0-100)
        """
        # Base position limit (% of equity)
        base_limit = 20.0  # 20% of equity as default max

        # 1. Volatility adjustment
        vol_forecast = self._vol_forecasts.get(symbol)
        if vol_forecast is None:
            vol_forecast = self.forecast_volatility(symbol)

        vol_multiplier = 1.0
        reason_parts = []
        if vol_forecast.vol_regime == "extreme":
            vol_multiplier = 0.25
            reason_parts.append("extreme vol -> 25% of base limit")
        elif vol_forecast.vol_regime == "high":
            vol_multiplier = 0.5
            reason_parts.append("high vol -> 50% of base limit")
        elif vol_forecast.vol_regime == "low":
            vol_multiplier = 1.25
            reason_parts.append("low vol -> 125% of base limit")

        # 2. Correlation adjustment
        corr_penalty = 1.0
        if open_positions and self._correlation_cache:
            # Check how correlated this symbol is with existing positions
            max_corr = 0.0
            for existing_sym, pos_data in open_positions.items():
                existing_side = pos_data.get("side", "long") if isinstance(pos_data, dict) else "long"
                corr = self._correlation_cache.get_correlation(symbol, existing_sym)
                # Same direction + high correlation = reduce limit
                same_direction = (side.lower() == existing_side.lower())
                if same_direction:
                    effective_corr = corr
                else:
                    effective_corr = -corr  # Opposite direction reduces risk
                max_corr = max(max_corr, effective_corr)

            if max_corr > 0.8:
                corr_penalty = 0.4
                reason_parts.append(f"high corr ({max_corr:.2f}) -> 40% limit")
            elif max_corr > 0.6:
                corr_penalty = 0.6
                reason_parts.append(f"moderate corr ({max_corr:.2f}) -> 60% limit")
            elif max_corr > 0.4:
                corr_penalty = 0.8
                reason_parts.append(f"mild corr ({max_corr:.2f}) -> 80% limit")

        # 3. Risk budget adjustment
        budget_multiplier = 1.0
        if equity > 0 and open_positions:
            budget = self.compute_risk_budget(equity, open_positions)
            if budget.utilization > 0.9:
                budget_multiplier = 0.25
                reason_parts.append("risk budget >90% used -> 25% limit")
            elif budget.utilization > 0.7:
                budget_multiplier = 0.5
                reason_parts.append("risk budget >70% used -> 50% limit")
            elif budget.utilization > 0.5:
                budget_multiplier = 0.75
                reason_parts.append("risk budget >50% used -> 75% limit")

        # Combine
        final_limit = base_limit * vol_multiplier * corr_penalty * budget_multiplier
        final_limit = round(max(1.0, min(base_limit, final_limit)), 2)

        # Risk level classification
        if final_limit <= 5.0:
            risk_level = "high"
        elif final_limit <= 10.0:
            risk_level = "elevated"
        elif final_limit <= 15.0:
            risk_level = "moderate"
        else:
            risk_level = "low"

        reason = "; ".join(reason_parts) if reason_parts else "standard limits"

        return {
            "max_qty_pct": final_limit,
            "reason": reason,
            "risk_level": risk_level,
        }

    # ── Cascade Detection ────────────────────────────────────

    def detect_cascade_signals(
        self,
        price_changes: Dict[str, float],
        threshold_pct: float = 2.0,
    ) -> List[Dict]:
        """Detect cross-symbol cascade patterns.

        When a leader (BTC/ETH) moves sharply and a correlated alt
        hasn't moved yet, signal a potential cascade.

        Args:
            price_changes: {symbol: pct_change} — recent % price changes.
            threshold_pct: Minimum leader move to trigger cascade detection.

        Returns:
            List of cascade signals:
            [{"leader": str, "follower": str, "leader_move_pct": float,
              "follower_move_pct": float, "expected_direction": str,
              "correlation": float, "urgency": str}]
        """
        signals = []
        corr_matrix = self._correlation_cache
        if corr_matrix is None:
            return signals

        # Find leaders that moved sharply
        leaders_moving = {}
        for leader in CASCADE_LEADERS:
            change = price_changes.get(leader, 0.0)
            if abs(change) >= threshold_pct:
                leaders_moving[leader] = change

        if not leaders_moving:
            return signals

        # Check alts that haven't moved proportionally
        for leader, leader_change in leaders_moving.items():
            leader_direction = "down" if leader_change < 0 else "up"

            for sym, sym_change in price_changes.items():
                if sym in CASCADE_LEADERS:
                    continue  # Skip other leaders

                corr = corr_matrix.get_correlation(leader, sym)
                if abs(corr) < 0.3:
                    continue  # Not correlated enough

                # Expected move = leader_change * correlation
                expected_move = leader_change * corr
                actual_move = sym_change

                # Gap = how much the follower hasn't caught up
                gap = abs(expected_move) - abs(actual_move)
                if gap <= threshold_pct * 0.3:
                    continue  # Already moved, no cascade opportunity

                # Expected direction for follower
                if corr > 0:
                    expected_direction = leader_direction
                else:
                    expected_direction = "up" if leader_direction == "down" else "down"

                # Urgency based on gap size and correlation strength
                if gap > threshold_pct and abs(corr) > 0.7:
                    urgency = "high"
                elif gap > threshold_pct * 0.5 and abs(corr) > 0.5:
                    urgency = "medium"
                else:
                    urgency = "low"

                signals.append({
                    "leader": leader,
                    "follower": sym,
                    "leader_move_pct": round(leader_change, 2),
                    "follower_move_pct": round(sym_change, 2),
                    "expected_direction": expected_direction,
                    "correlation": round(corr, 3),
                    "gap_pct": round(gap, 2),
                    "urgency": urgency,
                })

        # Sort by urgency (high first) then by gap
        urgency_order = {"high": 0, "medium": 1, "low": 2}
        signals.sort(key=lambda s: (urgency_order.get(s["urgency"], 3), -s["gap_pct"]))

        if signals:
            logger.info(
                "[CASCADE] Detected %d cascade signals from %s",
                len(signals),
                list(leaders_moving.keys()),
            )

        return signals

    # ── Rebalance Suggestions ────────────────────────────────

    def get_rebalance_suggestions(
        self,
        open_positions: Dict[str, Any],
        equity: float,
    ) -> List[Dict]:
        """Suggest portfolio rebalancing when correlation spikes.

        Returns list of suggestions:
        [{"action": "reduce"|"close", "symbol": str, "reason": str,
          "priority": str, "current_risk_pct": float}]
        """
        suggestions = []
        if not open_positions or equity <= 0:
            return suggestions

        budget = self.compute_risk_budget(equity, open_positions)

        # 1. Concentration-based suggestions
        if budget.concentration_warning:
            # Find most concentrated position
            if budget.per_position_risk:
                worst_sym = max(
                    budget.per_position_risk,
                    key=lambda s: budget.per_position_risk[s],
                )
                worst_risk = budget.per_position_risk[worst_sym]
                suggestions.append({
                    "action": "reduce",
                    "symbol": worst_sym,
                    "reason": budget.concentration_warning,
                    "priority": "high",
                    "current_risk_pct": round(worst_risk, 2),
                })

        # 2. Over-budget suggestions
        if budget.utilization > 0.9:
            # Suggest reducing highest-risk positions until under budget
            sorted_positions = sorted(
                budget.per_position_risk.items(),
                key=lambda x: x[1],
                reverse=True,
            )
            for sym, risk_pct in sorted_positions:
                if budget.utilization <= 0.7:
                    break
                action = "close" if budget.utilization > 1.0 else "reduce"
                suggestions.append({
                    "action": action,
                    "symbol": sym,
                    "reason": (
                        f"Portfolio risk budget {budget.utilization * 100:.0f}% "
                        f"utilized, position risk: {risk_pct:.2f}%"
                    ),
                    "priority": "high" if action == "close" else "medium",
                    "current_risk_pct": round(risk_pct, 2),
                })

        # 3. High-correlation pair suggestions
        corr_matrix = self._correlation_cache
        if corr_matrix and len(open_positions) >= 2:
            pos_list = list(open_positions.keys())
            for i in range(len(pos_list)):
                for j in range(i + 1, len(pos_list)):
                    sym_a, sym_b = pos_list[i], pos_list[j]
                    corr = corr_matrix.get_correlation(sym_a, sym_b)

                    side_a = open_positions[sym_a].get("side", "long") if isinstance(open_positions[sym_a], dict) else "long"
                    side_b = open_positions[sym_b].get("side", "long") if isinstance(open_positions[sym_b], dict) else "long"

                    same_dir = side_a.lower() == side_b.lower()

                    if corr > 0.8 and same_dir:
                        # High positive corr, same direction -> redundant risk
                        # Suggest reducing the smaller position
                        size_a = abs(open_positions[sym_a].get("size_usd", 0)) if isinstance(open_positions[sym_a], dict) else 0
                        size_b = abs(open_positions[sym_b].get("size_usd", 0)) if isinstance(open_positions[sym_b], dict) else 0
                        reduce_sym = sym_b if size_b <= size_a else sym_a

                        # Avoid duplicate suggestions
                        already_suggested = any(
                            s["symbol"] == reduce_sym for s in suggestions
                        )
                        if not already_suggested:
                            suggestions.append({
                                "action": "reduce",
                                "symbol": reduce_sym,
                                "reason": (
                                    f"Corr({sym_a},{sym_b})={corr:.2f}, "
                                    f"both {side_a} -> redundant risk"
                                ),
                                "priority": "medium",
                                "current_risk_pct": round(
                                    budget.per_position_risk.get(reduce_sym, 0), 2
                                ),
                            })

        # Deduplicate by symbol, keep highest priority
        seen = {}
        priority_rank = {"high": 0, "medium": 1, "low": 2}
        for s in suggestions:
            sym = s["symbol"]
            if sym not in seen or priority_rank.get(s["priority"], 3) < priority_rank.get(seen[sym]["priority"], 3):
                seen[sym] = s
        suggestions = sorted(
            seen.values(),
            key=lambda s: priority_rank.get(s["priority"], 3),
        )

        return suggestions

    # ── Risk Report ──────────────────────────────────────────

    def get_portfolio_risk_report(self) -> str:
        """Format a comprehensive portfolio risk report."""
        lines = ["=== Portfolio Risk Report ===", ""]

        # Tracked symbols
        with self._lock:
            symbols = sorted(self._price_history.keys())
            data_points = {
                sym: len(self._price_history[sym])
                for sym in symbols
            }

        lines.append(f"Tracked symbols: {len(symbols)}")
        for sym in symbols:
            lines.append(f"  {sym}: {data_points[sym]} price points")
        lines.append("")

        # Volatility forecasts
        lines.append("--- Volatility Forecasts ---")
        if self._vol_forecasts:
            for sym in sorted(self._vol_forecasts.keys()):
                vf = self._vol_forecasts[sym]
                lines.append(
                    f"  {sym}: current={vf.current_vol:.1f}% "
                    f"forecast={vf.forecast_vol:.1f}% "
                    f"regime={vf.vol_regime} "
                    f"conf={vf.confidence:.0%} "
                    f"half_life={vf.half_life_hours:.0f}h"
                )
        else:
            lines.append("  No forecasts computed yet")
        lines.append("")

        # Correlation matrix
        lines.append("--- Correlation Matrix ---")
        if self._correlation_cache and self._correlation_cache.symbols:
            cm = self._correlation_cache
            age_min = (time.time() - cm.timestamp) / 60
            lines.append(
                f"  Lookback: {cm.lookback_hours}h | "
                f"Age: {age_min:.0f}min | "
                f"Symbols: {len(cm.symbols)}"
            )

            # Header row
            max_sym_len = max(len(s) for s in cm.symbols) if cm.symbols else 5
            header = " " * (max_sym_len + 2)
            for sym in cm.symbols:
                header += f"{sym:>8s}"
            lines.append(f"  {header}")

            # Data rows
            for i, sym in enumerate(cm.symbols):
                row = f"  {sym:>{max_sym_len}s}  "
                for j in range(len(cm.symbols)):
                    val = cm.matrix[i][j]
                    row += f"{val:>8.3f}"
                lines.append(row)

            # Highlight high correlations
            high_corrs = []
            for i in range(len(cm.symbols)):
                for j in range(i + 1, len(cm.symbols)):
                    c = cm.matrix[i][j]
                    if abs(c) > 0.7:
                        high_corrs.append(
                            (cm.symbols[i], cm.symbols[j], c)
                        )
            if high_corrs:
                lines.append("")
                lines.append("  High correlations (|r| > 0.7):")
                for sa, sb, c in high_corrs:
                    lines.append(f"    {sa} <-> {sb}: {c:.3f}")
        else:
            lines.append("  No correlation matrix computed yet")

        lines.append("")
        lines.append("=== End Report ===")
        return "\n".join(lines)

    # ── Periodic Tick ────────────────────────────────────────

    def tick(
        self,
        prices: Dict[str, float],
        open_positions: Dict[str, Any] = None,
        equity: float = 0,
    ):
        """Periodic update: record prices, update forecasts.

        Call this on each bot tick (e.g., every few minutes).

        Args:
            prices: {symbol: current_price}
            open_positions: {symbol: {"side": str, "size_usd": float}}
            equity: Current account equity.
        """
        now = time.time()

        # Record all prices
        for sym, price in prices.items():
            self.record_price(sym, price, now)

        # Update vol forecasts for traded symbols
        symbols_to_forecast = set(prices.keys())
        if open_positions:
            symbols_to_forecast |= set(open_positions.keys())

        for sym in symbols_to_forecast:
            try:
                self.forecast_volatility(sym)
            except Exception as e:
                logger.warning("[PORTFOLIO-RISK] Vol forecast failed for %s: %s", sym, e)

        # Recompute correlation matrix if we have enough symbols
        if len(self._price_history) >= 2:
            try:
                self.compute_correlation_matrix()
            except Exception as e:
                logger.warning("[PORTFOLIO-RISK] Correlation computation failed: %s", e)

        # Periodic persistence
        if now - self._last_persist_time > self._persist_interval:
            self._persist_state()
            self._last_persist_time = now

    # ── Persistence ──────────────────────────────────────────

    def _persist_state(self):
        """Persist price history and cached results to JSON files."""
        with self._lock:
            self._persist_price_history()
            self._persist_vol_forecasts()

    def _persist_price_history(self):
        """Save price history to JSON."""
        try:
            serializable = {}
            for sym, hist in self._price_history.items():
                # Only persist last 200 to keep file size reasonable
                recent = hist[-200:]
                serializable[sym] = [[t, p] for t, p in recent]

            with open(self._price_file, "w") as f:
                json.dump(serializable, f)
            logger.debug("[PORTFOLIO-RISK] Persisted price history for %d symbols", len(serializable))
        except Exception as e:
            logger.warning("[PORTFOLIO-RISK] Failed to persist price history: %s", e)

    def _persist_correlation(self, matrix: CorrelationMatrix):
        """Save correlation matrix to JSON cache."""
        try:
            data = {
                "symbols": matrix.symbols,
                "matrix": matrix.matrix,
                "timestamp": matrix.timestamp,
                "lookback_hours": matrix.lookback_hours,
            }
            with open(self._corr_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning("[PORTFOLIO-RISK] Failed to persist correlation: %s", e)

    def _persist_vol_forecasts(self):
        """Save volatility forecasts to JSON cache."""
        try:
            data = {}
            for sym, vf in self._vol_forecasts.items():
                data[sym] = {
                    "symbol": vf.symbol,
                    "current_vol": vf.current_vol,
                    "forecast_vol": vf.forecast_vol,
                    "vol_regime": vf.vol_regime,
                    "confidence": vf.confidence,
                    "half_life_hours": vf.half_life_hours,
                }
            with open(self._vol_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning("[PORTFOLIO-RISK] Failed to persist vol forecasts: %s", e)

    def _load_state(self):
        """Load persisted state from JSON files."""
        self._load_price_history()
        self._load_correlation_cache()
        self._load_vol_forecasts()

    def _load_price_history(self):
        """Load price history from JSON."""
        if not os.path.exists(self._price_file):
            return
        try:
            with open(self._price_file) as f:
                raw = json.load(f)
            for sym, entries in raw.items():
                self._price_history[sym] = [
                    (float(t), float(p)) for t, p in entries
                ]
            logger.info(
                "[PORTFOLIO-RISK] Loaded price history for %d symbols",
                len(self._price_history),
            )
        except Exception as e:
            logger.warning("[PORTFOLIO-RISK] Failed to load price history: %s", e)

    def _load_correlation_cache(self):
        """Load cached correlation matrix from JSON."""
        if not os.path.exists(self._corr_file):
            return
        try:
            with open(self._corr_file) as f:
                data = json.load(f)
            self._correlation_cache = CorrelationMatrix(
                symbols=data["symbols"],
                matrix=data["matrix"],
                timestamp=data["timestamp"],
                lookback_hours=data["lookback_hours"],
            )
            age_hours = (time.time() - self._correlation_cache.timestamp) / 3600
            logger.info(
                "[PORTFOLIO-RISK] Loaded correlation cache (age: %.1fh)",
                age_hours,
            )
        except Exception as e:
            logger.warning("[PORTFOLIO-RISK] Failed to load correlation cache: %s", e)

    def _load_vol_forecasts(self):
        """Load cached volatility forecasts from JSON."""
        if not os.path.exists(self._vol_file):
            return
        try:
            with open(self._vol_file) as f:
                data = json.load(f)
            for sym, vf_data in data.items():
                self._vol_forecasts[sym] = VolatilityForecast(**vf_data)
            logger.info(
                "[PORTFOLIO-RISK] Loaded %d vol forecasts",
                len(self._vol_forecasts),
            )
        except Exception as e:
            logger.warning("[PORTFOLIO-RISK] Failed to load vol forecasts: %s", e)


# ── Singleton ────────────────────────────────────────────────

_engine: Optional[PortfolioRiskEngine] = None
_engine_lock = threading.Lock()


def get_portfolio_risk_engine() -> PortfolioRiskEngine:
    """Singleton accessor for the portfolio risk engine."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = PortfolioRiskEngine()
    return _engine
