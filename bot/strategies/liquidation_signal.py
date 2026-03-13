"""
Liquidation Heatmap Proximity Signal — Estimates where leveraged liquidations cluster
and generates signals when price approaches dense liquidation zones.

Edge basis: Retail traders cluster at predictable leverage levels (3x, 5x, 10x, 20x).
Price tends to gravitate toward dense liquidation zones ("magnet effect") because
market makers hunt liquidity. When cascading liquidations trigger, they create
momentum that can be traded.

Logic:
- Track swing highs/lows over a configurable lookback window (default 72h)
- For each swing point, estimate where leveraged positions would get liquidated:
  - Long liquidation: entry * (1 - 1/leverage) — longs opened at swing lows liquidate below
  - Short liquidation: entry * (1 + 1/leverage) — shorts opened at swing highs liquidate above
- Cluster overlapping liquidation levels into density zones
- Signal when price approaches a dense cluster within proximity threshold

Signal direction:
- Price approaching liquidation cluster ABOVE → expect short squeeze → BUY
- Price approaching liquidation cluster BELOW → expect liquidation cascade → SELL

Data: 1h candles via CCXT (Hyperliquid). No order book data needed.
"""

import logging
import os
from typing import Optional, Dict, Any, List, Tuple

import pandas as pd

from .base import BaseStrategy, Signal

logger = logging.getLogger("bot.strategy.liquidation_signal")

# Common leverage levels used by retail traders
LEVERAGE_LEVELS = [3, 5, 10, 20]

# Configurable via environment
LOOKBACK_HOURS = int(os.environ.get("LIQUIDATION_LOOKBACK_HOURS", "72"))
PROXIMITY_PCT = float(os.environ.get("LIQUIDATION_PROXIMITY_PCT", "1.5"))

# Minimum candles required for meaningful swing detection
MIN_CANDLES = 72

# Swing detection: a swing high/low must stand out by this many candles on each side
SWING_ORDER = 5

# Cluster bandwidth: liquidation levels within this % of each other form a cluster
CLUSTER_BAND_PCT = 0.5

# Minimum liquidation levels in a cluster to consider it "dense"
MIN_CLUSTER_DENSITY = 3


class LiquidationSignalStrategy(BaseStrategy):
    """Liquidation heatmap proximity strategy.

    Estimates where leveraged positions would get liquidated based on
    recent swing highs/lows and common retail leverage levels. Generates
    signals when price approaches dense liquidation clusters.
    """

    def __init__(self, symbols=None):
        super().__init__(name="liquidation_signal", symbols=symbols or {})

    def get_required_timeframes(self) -> List[str]:
        return ["1h"]

    def get_status(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Get current liquidation heatmap assessment."""
        df = data.get("1h") if isinstance(data, dict) else None
        if df is None or len(df) < MIN_CANDLES:
            return {
                "strategy": self.name,
                "symbol": symbol,
                "status": "insufficient_data",
                "candles": len(df) if df is not None else 0,
                "required": MIN_CANDLES,
            }

        close = df["close"].iloc[-1]
        swings = self._find_swings(df)
        liq_levels = self._estimate_liquidation_levels(swings)
        clusters = self._cluster_levels(liq_levels, close)
        nearest = self._find_nearest_cluster(clusters, close)

        return {
            "strategy": self.name,
            "symbol": symbol,
            "status": "active",
            "current_price": close,
            "swing_count": len(swings),
            "liquidation_levels": len(liq_levels),
            "clusters": len(clusters),
            "nearest_cluster": nearest,
        }

    def evaluate(
        self, symbol: str, data: Dict[str, Any], **kwargs
    ) -> Optional[Signal]:
        """Evaluate liquidation heatmap proximity signal.

        Expects data dict with '1h' DataFrame containing OHLCV candles.
        Returns Signal when price is near a dense liquidation cluster.
        """
        df = data.get("1h") if isinstance(data, dict) else None
        if df is None or len(df) < MIN_CANDLES:
            return None

        close = df["close"].iloc[-1]
        if close <= 0:
            return None

        atr = self._compute_atr(df)
        if atr <= 0:
            return None

        # Step 1: Find swing highs and lows
        swings = self._find_swings(df)
        if not swings:
            return None

        # Step 2: Estimate liquidation levels from swing points
        liq_levels = self._estimate_liquidation_levels(swings)
        if not liq_levels:
            return None

        # Step 3: Cluster nearby liquidation levels
        clusters = self._cluster_levels(liq_levels, close)
        if not clusters:
            return None

        # Step 4: Find the nearest dense cluster and check proximity
        signal_info = self._evaluate_proximity(clusters, close, atr)
        if signal_info is None:
            return None

        side, confidence, cluster_center, cluster_density = signal_info

        # Step 5: Construct entry/SL/TP
        entry = close

        if side == "BUY":
            # Short squeeze expected — price moving up through liquidation zone
            sl = entry - atr * 2.0
            tp1 = cluster_center + atr * 0.5  # Just beyond the cluster
            tp2 = cluster_center + atr * 1.5  # Extended squeeze target
        else:
            # Liquidation cascade expected — price moving down through zone
            sl = entry + atr * 2.0
            tp1 = cluster_center - atr * 0.5
            tp2 = cluster_center - atr * 1.5

        signal = Signal(
            strategy=self.name,
            symbol=symbol,
            side=side,
            confidence=confidence,
            entry=entry,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            atr=atr,
            metadata={
                "signal_type": "liquidation_heatmap",
                "cluster_center": round(cluster_center, 2),
                "cluster_density": cluster_density,
                "proximity_pct": round(
                    abs(close - cluster_center) / close * 100, 3
                ),
                "swing_count": len(swings),
                "total_liq_levels": len(liq_levels),
                "cluster_count": len(clusters),
                "lookback_hours": LOOKBACK_HOURS,
            },
            signal_context=(
                f"Price within {PROXIMITY_PCT}% of dense liquidation cluster "
                f"({cluster_density} levels near {cluster_center:.2f}). "
                f"{'Short squeeze' if side == 'BUY' else 'Cascade'} expected."
            ),
        )

        if not signal.is_valid:
            logger.debug(
                "Liquidation signal for %s rejected by validation (side=%s, "
                "entry=%.2f, sl=%.2f, tp1=%.2f)",
                symbol, side, entry, sl, tp1,
            )
            return None

        logger.info(
            "Liquidation signal: %s %s @ %.2f | cluster=%.2f density=%d "
            "proximity=%.3f%% conf=%.1f",
            side, symbol, entry, cluster_center, cluster_density,
            abs(close - cluster_center) / close * 100, confidence,
        )
        return signal

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_swings(self, df: pd.DataFrame) -> List[Tuple[str, float]]:
        """Find swing highs and lows in recent price action.

        Returns list of (type, price) tuples where type is 'high' or 'low'.
        Only considers the most recent LOOKBACK_HOURS candles.
        """
        # Use only the lookback window
        lookback = min(LOOKBACK_HOURS, len(df))
        df_window = df.iloc[-lookback:]

        if len(df_window) < SWING_ORDER * 2 + 1:
            return []

        highs = df_window["high"].values
        lows = df_window["low"].values
        swings: List[Tuple[str, float]] = []

        for i in range(SWING_ORDER, len(df_window) - SWING_ORDER):
            # Swing high: higher than SWING_ORDER candles on each side
            is_swing_high = True
            for j in range(1, SWING_ORDER + 1):
                if highs[i] <= highs[i - j] or highs[i] <= highs[i + j]:
                    is_swing_high = False
                    break
            if is_swing_high:
                swings.append(("high", float(highs[i])))

            # Swing low: lower than SWING_ORDER candles on each side
            is_swing_low = True
            for j in range(1, SWING_ORDER + 1):
                if lows[i] >= lows[i - j] or lows[i] >= lows[i + j]:
                    is_swing_low = False
                    break
            if is_swing_low:
                swings.append(("low", float(lows[i])))

        return swings

    def _estimate_liquidation_levels(
        self, swings: List[Tuple[str, float]]
    ) -> List[Tuple[float, str]]:
        """Estimate liquidation prices for common leverage levels.

        For each swing point:
        - Swing low (assumed long entry): liquidation = entry * (1 - 1/leverage)
        - Swing high (assumed short entry): liquidation = entry * (1 + 1/leverage)

        Returns list of (liquidation_price, side_liquidated) tuples.
        'long_liq' = longs get liquidated (price dropped), 'short_liq' = shorts get liquidated.
        """
        levels: List[Tuple[float, str]] = []

        for swing_type, price in swings:
            for lev in LEVERAGE_LEVELS:
                if swing_type == "low":
                    # Longs opened at swing low — liquidated below
                    liq_price = price * (1.0 - 1.0 / lev)
                    levels.append((liq_price, "long_liq"))
                else:
                    # Shorts opened at swing high — liquidated above
                    liq_price = price * (1.0 + 1.0 / lev)
                    levels.append((liq_price, "short_liq"))

        return levels

    def _cluster_levels(
        self, levels: List[Tuple[float, str]], current_price: float
    ) -> List[Dict[str, Any]]:
        """Group nearby liquidation levels into clusters.

        Uses a simple sorted-sweep: levels within CLUSTER_BAND_PCT of each
        other are grouped together. Only returns clusters with at least
        MIN_CLUSTER_DENSITY levels.
        """
        if not levels:
            return []

        # Sort by price
        sorted_levels = sorted(levels, key=lambda x: x[0])

        clusters: List[Dict[str, Any]] = []
        cluster_start = 0

        while cluster_start < len(sorted_levels):
            base_price = sorted_levels[cluster_start][0]
            if base_price <= 0:
                cluster_start += 1
                continue

            band_upper = base_price * (1.0 + CLUSTER_BAND_PCT / 100.0)
            cluster_end = cluster_start

            # Expand cluster to include all levels within band
            while (
                cluster_end < len(sorted_levels)
                and sorted_levels[cluster_end][0] <= band_upper
            ):
                cluster_end += 1

            cluster_members = sorted_levels[cluster_start:cluster_end]
            density = len(cluster_members)

            if density >= MIN_CLUSTER_DENSITY:
                prices = [m[0] for m in cluster_members]
                sides = [m[1] for m in cluster_members]
                long_liq_count = sides.count("long_liq")
                short_liq_count = sides.count("short_liq")

                center = sum(prices) / len(prices)
                clusters.append({
                    "center": center,
                    "density": density,
                    "long_liq_count": long_liq_count,
                    "short_liq_count": short_liq_count,
                    "dominant_side": (
                        "long_liq" if long_liq_count >= short_liq_count
                        else "short_liq"
                    ),
                    "distance_pct": abs(current_price - center) / current_price * 100,
                })

            cluster_start = cluster_end

        return clusters

    def _find_nearest_cluster(
        self, clusters: List[Dict[str, Any]], current_price: float
    ) -> Optional[Dict[str, Any]]:
        """Find the nearest cluster to current price."""
        if not clusters:
            return None
        return min(clusters, key=lambda c: abs(c["center"] - current_price))

    def _evaluate_proximity(
        self,
        clusters: List[Dict[str, Any]],
        current_price: float,
        atr: float,
    ) -> Optional[Tuple[str, float, float, int]]:
        """Check if price is near a dense liquidation cluster.

        Returns (side, confidence, cluster_center, cluster_density) or None.
        """
        nearest = self._find_nearest_cluster(clusters, current_price)
        if nearest is None:
            return None

        distance_pct = nearest["distance_pct"]
        if distance_pct > PROXIMITY_PCT:
            return None

        cluster_center = nearest["center"]
        density = nearest["density"]

        # Determine signal direction based on cluster position
        if cluster_center > current_price:
            # Liquidation cluster is ABOVE — these are short liquidations
            # Price moving up toward short liquidation zone → short squeeze → BUY
            side = "BUY"
        else:
            # Liquidation cluster is BELOW — these are long liquidations
            # Price moving down toward long liquidation zone → cascade → SELL
            side = "SELL"

        # Confidence: 55-75 based on cluster density and proximity
        # Higher density = more confidence (more liquidations = bigger move)
        # Closer proximity = more confidence (about to trigger)
        density_score = min(1.0, (density - MIN_CLUSTER_DENSITY) / 8.0)
        proximity_score = 1.0 - (distance_pct / PROXIMITY_PCT)

        confidence = 55.0 + density_score * 10.0 + proximity_score * 10.0
        confidence = min(75.0, max(55.0, confidence))

        return side, confidence, cluster_center, density

    def _compute_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """Compute ATR from DataFrame."""
        if len(df) < period + 1:
            return 0.0

        try:
            high = df["high"].values
            low = df["low"].values
            close = df["close"].values

            tr_values = []
            for i in range(1, len(df)):
                tr = max(
                    high[i] - low[i],
                    abs(high[i] - close[i - 1]),
                    abs(low[i] - close[i - 1]),
                )
                tr_values.append(tr)

            if len(tr_values) < period:
                return sum(tr_values) / len(tr_values) if tr_values else 0.0

            return sum(tr_values[-period:]) / period
        except Exception:
            return 0.0
