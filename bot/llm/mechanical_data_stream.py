"""
TIER 4.1c: Mechanical Bot Data Stream

Captures the LIVE market intelligence data the mechanical bot is processing.

The mechanical bot continuously computes:
- Regime analysis (with confidence scores)
- Volatility metrics (ATR, Bollinger bands, IV)
- Multi-timeframe alignment (5m + 1h + 6h agreement)
- Support/resistance levels
- Correlation matrix (BTC vs alts)
- Time-of-day seasonality
- Momentum indicators
- Volume profile

Instead of just using signals, tap the raw data stream.

Use case: LLM makes decisions based on the SAME data the mechanical bot sees.
Not as a downstream filter, but as an additional consumer of real-time market intel.

Data flow:
```
OHLCV Data
    ↓
Market Intel Extraction (Mechanical Bot)
    ├→ Regime classifier
    ├→ Volatility calculator
    ├→ Multi-TF alignment
    ├→ Support/resistance finder
    ├→ Correlation tracker
    └→ [All this data flows here]
        ↓
        ├→ Ensemble Strategy Pipeline (current)
        └→ LLM Data Stream Consumer (new)
             ├→ Semantic memory queries
             ├→ Pattern recognition
             ├→ Correlation-based signal generation
             └→ Synthetic signal synthesis
```

Key insight: We don't wait for mechanical signals to filter.
We analyze the same raw market data independently and generate complementary signals.
"""

import json
import logging
import os
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict, field
from datetime import datetime
import time

logger = logging.getLogger("bot.llm.mechanical_data_stream")


@dataclass
class MarketSnapshot:
    """
    Complete market intelligence snapshot for one symbol at one time.

    Captures everything the mechanical bot calculated.
    """
    symbol: str
    timestamp: float

    # Price & volatility
    current_price: float = 0.0
    price_change_1h_pct: float = 0.0
    price_change_24h_pct: float = 0.0
    atr: float = 0.0  # Average true range
    volatility_percentile: float = 0.0  # 0-100, where is vol in distribution?

    # Regime analysis
    regime: Optional[str] = None
    regime_confidence: float = 0.0
    regime_momentum: Optional[str] = None  # "strengthening" | "weakening" | "neutral"

    # Multi-timeframe alignment
    alignment_5m_1h: float = 0.0  # Agreement between 5m and 1h (-1 to 1)
    alignment_1h_6h: float = 0.0
    alignment_6h_1d: float = 0.0
    overall_alignment: float = 0.0  # Combined score

    # Support/resistance
    support_level: Optional[float] = None
    resistance_level: Optional[float] = None
    distance_to_support_pct: float = 0.0
    distance_to_resistance_pct: float = 0.0

    # Correlation context
    btc_price: Optional[float] = None
    btc_change_1h_pct: float = 0.0
    correlation_with_btc_1h: float = 0.0
    correlation_with_btc_6h: float = 0.0

    # Time-of-day context
    time_of_day: int = 0  # 0-23 hour
    day_of_week: int = 0  # 0-6 (Monday-Sunday)
    trading_session: str = ""  # "asia", "europe", "us"

    # Momentum
    rsi_14: Optional[float] = None
    macd_histogram: Optional[float] = None
    momentum_direction: Optional[str] = None  # "up", "down", "neutral"

    # Volume
    volume_profile: Optional[str] = None  # "increasing", "decreasing", "normal"
    liquidity_rating: float = 0.0  # 0-100


class MechanicalDataStreamCapture:
    """
    Captures the mechanical bot's continuous market data stream.
    """

    def __init__(self, output_dir: str = "data/llm"):
        self.output_dir = output_dir
        self.stream_file = os.path.join(output_dir, "mechanical_data_stream.jsonl")
        os.makedirs(output_dir, exist_ok=True)

        # Recent snapshots in memory
        self.recent_snapshots: Dict[str, List[MarketSnapshot]] = {}  # symbol -> list

    def capture_snapshot(
        self,
        symbol: str,
        current_price: float,
        price_change_1h_pct: float,
        price_change_24h_pct: float,
        atr: float,
        volatility_percentile: float,
        regime: Optional[str],
        regime_confidence: float,
        regime_momentum: Optional[str],
        alignment_5m_1h: float,
        alignment_1h_6h: float,
        alignment_6h_1d: float,
        support_level: Optional[float],
        resistance_level: Optional[float],
        btc_price: Optional[float],
        btc_change_1h_pct: float,
        correlation_with_btc_1h: float,
        correlation_with_btc_6h: float,
        time_of_day: int,
        day_of_week: int,
        trading_session: str,
        rsi_14: Optional[float] = None,
        macd_histogram: Optional[float] = None,
        momentum_direction: Optional[str] = None,
        volume_profile: Optional[str] = None,
        liquidity_rating: float = 0.0,
    ) -> MarketSnapshot:
        """
        Capture a market intelligence snapshot.

        Called once per evaluation cycle for each symbol.
        """
        now = time.time()

        # Calculate derived metrics
        distance_to_support_pct = (
            ((current_price - support_level) / support_level * 100)
            if support_level and support_level > 0
            else 0.0
        )
        distance_to_resistance_pct = (
            ((resistance_level - current_price) / resistance_level * 100)
            if resistance_level and resistance_level > 0
            else 0.0
        )
        overall_alignment = (alignment_5m_1h + alignment_1h_6h + alignment_6h_1d) / 3

        snapshot = MarketSnapshot(
            symbol=symbol,
            timestamp=now,
            current_price=current_price,
            price_change_1h_pct=price_change_1h_pct,
            price_change_24h_pct=price_change_24h_pct,
            atr=atr,
            volatility_percentile=volatility_percentile,
            regime=regime,
            regime_confidence=regime_confidence,
            regime_momentum=regime_momentum,
            alignment_5m_1h=alignment_5m_1h,
            alignment_1h_6h=alignment_1h_6h,
            alignment_6h_1d=alignment_6h_1d,
            overall_alignment=overall_alignment,
            support_level=support_level,
            resistance_level=resistance_level,
            distance_to_support_pct=distance_to_support_pct,
            distance_to_resistance_pct=distance_to_resistance_pct,
            btc_price=btc_price,
            btc_change_1h_pct=btc_change_1h_pct,
            correlation_with_btc_1h=correlation_with_btc_1h,
            correlation_with_btc_6h=correlation_with_btc_6h,
            time_of_day=time_of_day,
            day_of_week=day_of_week,
            trading_session=trading_session,
            rsi_14=rsi_14,
            macd_histogram=macd_histogram,
            momentum_direction=momentum_direction,
            volume_profile=volume_profile,
            liquidity_rating=liquidity_rating,
        )

        # Store in memory
        if symbol not in self.recent_snapshots:
            self.recent_snapshots[symbol] = []
        self.recent_snapshots[symbol].append(snapshot)
        if len(self.recent_snapshots[symbol]) > 288:  # Keep 24h of 5min candles
            self.recent_snapshots[symbol] = self.recent_snapshots[symbol][-288:]

        # Persist
        self._save_snapshot(snapshot)

        return snapshot

    def get_latest_snapshot(self, symbol: str) -> Optional[MarketSnapshot]:
        """Get most recent snapshot for a symbol."""
        if symbol not in self.recent_snapshots or not self.recent_snapshots[symbol]:
            return None
        return self.recent_snapshots[symbol][-1]

    def get_snapshot_history(self, symbol: str, lookback_minutes: int = 60) -> List[MarketSnapshot]:
        """Get historical snapshots for a symbol."""
        if symbol not in self.recent_snapshots:
            return []

        cutoff_time = time.time() - (lookback_minutes * 60)
        return [s for s in self.recent_snapshots[symbol] if s.timestamp >= cutoff_time]

    def get_market_conditions(self, symbol: str) -> Dict[str, Any]:
        """Get summary of current market conditions for symbol."""
        snapshot = self.get_latest_snapshot(symbol)
        if not snapshot:
            return {"status": "no_data"}

        return {
            "symbol": symbol,
            "current_price": snapshot.current_price,
            "regime": snapshot.regime,
            "regime_confidence": f"{snapshot.regime_confidence:.0%}",
            "volatility": f"{snapshot.volatility_percentile:.0f}th percentile",
            "alignment": f"{snapshot.overall_alignment:.2f}",
            "distance_to_support": f"{snapshot.distance_to_support_pct:+.1f}%",
            "distance_to_resistance": f"{snapshot.distance_to_resistance_pct:+.1f}%",
            "btc_correlation_1h": f"{snapshot.correlation_with_btc_1h:.2f}",
            "momentum": snapshot.momentum_direction,
        }

    def identify_high_quality_moments(self, symbol: str) -> List[Dict]:
        """
        Identify snapshots with high-quality conditions (best times to trade).

        High quality: trending regime + high alignment + good support/resistance distance
        """
        history = self.get_snapshot_history(symbol, lookback_minutes=120)
        if not history:
            return []

        quality_moments = []
        for snapshot in history:
            # Score this moment
            quality_score = 0.0

            # Regime quality
            if snapshot.regime and "trend" in snapshot.regime.lower():
                quality_score += snapshot.regime_confidence

            # Multi-TF alignment
            quality_score += abs(snapshot.overall_alignment) * 50

            # Support/resistance distance
            if 5 <= snapshot.distance_to_support_pct <= 15:
                quality_score += 20  # Good risk/reward from support
            if 5 <= snapshot.distance_to_resistance_pct <= 15:
                quality_score += 20  # Good room to resistance

            if quality_score >= 60:
                quality_moments.append({
                    "timestamp": snapshot.timestamp,
                    "quality_score": round(quality_score, 1),
                    "regime": snapshot.regime,
                    "alignment": snapshot.overall_alignment,
                })

        return quality_moments

    def _save_snapshot(self, snapshot: MarketSnapshot) -> None:
        """Persist snapshot to disk."""
        try:
            with open(self.stream_file, "a") as f:
                data = {
                    "symbol": snapshot.symbol,
                    "timestamp": snapshot.timestamp,
                    "current_price": snapshot.current_price,
                    "regime": snapshot.regime,
                    "regime_confidence": snapshot.regime_confidence,
                    "volatility_percentile": snapshot.volatility_percentile,
                    "alignment": snapshot.overall_alignment,
                    "correlation_with_btc_1h": snapshot.correlation_with_btc_1h,
                }
                f.write(json.dumps(data) + "\n")
        except Exception as e:
            logger.error(f"Failed to save snapshot: {e}")


# Global stream capture
_global_capture: Optional[MechanicalDataStreamCapture] = None


def get_mechanical_data_stream_capture() -> MechanicalDataStreamCapture:
    """Get or create global capture."""
    global _global_capture
    if _global_capture is None:
        _global_capture = MechanicalDataStreamCapture()
    return _global_capture
