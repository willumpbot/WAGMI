"""
Portfolio-level analytics — extracted from multi_strategy_main.py.

Provides portfolio-wide metrics computation:
- Total portfolio leverage
- Estimated daily funding costs
- Cross-position correlation
- Portfolio risk assessment

Usage:
    analytics = PortfolioAnalytics(config)
    metrics = analytics.compute(positions, prices, equity)
"""

import logging
import math
from typing import Dict, Any, List, Optional

logger = logging.getLogger("bot.core.portfolio_analytics")


class PortfolioAnalytics:
    """Compute portfolio-level metrics from open positions."""

    def __init__(self, max_portfolio_risk_pct: float = 5.0):
        self.max_portfolio_risk_pct = max_portfolio_risk_pct

    def compute_portfolio_leverage(
        self, positions: Dict[str, Any], equity: float
    ) -> float:
        """Calculate total portfolio leverage (sum of all position notionals / equity)."""
        if equity <= 0:
            return 0.0

        total_notional = 0.0
        for sym, pos in positions.items():
            if hasattr(pos, "state") and pos.state == "CLOSED":
                continue
            entry = getattr(pos, "entry", 0)
            qty = getattr(pos, "qty", 0)
            leverage = getattr(pos, "leverage", 1)
            total_notional += abs(entry * qty * leverage)

        return total_notional / equity if equity > 0 else 0.0

    def compute_estimated_daily_funding(
        self,
        positions: Dict[str, Any],
        funding_rates: Dict[str, float],
    ) -> float:
        """Estimate daily funding cost across all open positions.

        Funding is charged every 8h on Hyperliquid (3x per day).
        Returns negative for cost, positive for income.
        """
        daily_cost = 0.0
        for sym, pos in positions.items():
            if hasattr(pos, "state") and pos.state == "CLOSED":
                continue
            rate = funding_rates.get(sym, 0.0)
            if rate == 0:
                continue
            notional = abs(getattr(pos, "entry", 0) * getattr(pos, "qty", 0))
            side_mult = 1 if getattr(pos, "side", "LONG") == "LONG" else -1
            # Funding: longs pay when rate > 0, shorts receive
            daily_cost -= notional * rate * 3 * side_mult

        return daily_cost

    def compute_portfolio_correlation(
        self, positions: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Assess cross-position directional correlation.

        If all positions are the same direction (all long or all short),
        portfolio is highly correlated — a single market move wipes everything.
        """
        if not positions:
            return {"correlation": 0.0, "risk_level": "none"}

        sides = []
        for pos in positions.values():
            if hasattr(pos, "state") and pos.state == "CLOSED":
                continue
            sides.append(getattr(pos, "side", "LONG"))

        if not sides:
            return {"correlation": 0.0, "risk_level": "none"}

        long_count = sum(1 for s in sides if s in ("LONG", "BUY"))
        short_count = sum(1 for s in sides if s in ("SHORT", "SELL"))
        total = long_count + short_count

        if total == 0:
            return {"correlation": 0.0, "risk_level": "none"}

        # Correlation: 1.0 = all same direction, 0.0 = perfectly balanced
        majority = max(long_count, short_count)
        correlation = majority / total

        if correlation >= 0.9:
            risk_level = "high"
        elif correlation >= 0.7:
            risk_level = "medium"
        else:
            risk_level = "low"

        return {
            "correlation": round(correlation, 2),
            "risk_level": risk_level,
            "long_count": long_count,
            "short_count": short_count,
        }

    def compute_full_metrics(
        self,
        positions: Dict[str, Any],
        equity: float,
        funding_rates: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """Compute all portfolio metrics in one call."""
        funding_rates = funding_rates or {}
        portfolio_lev = self.compute_portfolio_leverage(positions, equity)
        daily_funding = self.compute_estimated_daily_funding(positions, funding_rates)
        correlation = self.compute_portfolio_correlation(positions)

        # Portfolio risk assessment
        active_count = sum(
            1 for p in positions.values()
            if hasattr(p, "state") and p.state != "CLOSED"
        )

        total_risk_pct = 0.0
        for pos in positions.values():
            if hasattr(pos, "state") and pos.state == "CLOSED":
                continue
            stop_dist = abs(getattr(pos, "entry", 0) - getattr(pos, "sl", 0))
            qty = getattr(pos, "qty", 0)
            risk_usd = stop_dist * qty
            if equity > 0:
                total_risk_pct += (risk_usd / equity) * 100

        risk_ok = total_risk_pct <= self.max_portfolio_risk_pct

        return {
            "portfolio_leverage": round(portfolio_lev, 2),
            "active_positions": active_count,
            "daily_funding_est": round(daily_funding, 2),
            "correlation": correlation,
            "total_risk_pct": round(total_risk_pct, 2),
            "max_risk_pct": self.max_portfolio_risk_pct,
            "risk_ok": risk_ok,
        }
