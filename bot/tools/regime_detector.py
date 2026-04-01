"""
Regime Shift Detector — Real-time detection of market regime transitions.

Detects regime TRANSITIONS, not just static regimes. The alpha is in detecting
shifts EARLY — before price fully reflects the new regime.

Key transitions:
  - neutral -> panic (crash incoming — exit longs, tighten stops)
  - panic -> recovering (bounce starting — prepare long entries)
  - trending -> choppy (stop trend strategies, reduce size)
  - choppy -> trending (start trend strategies, increase size)
  - relative strength divergence (BTC panic + HYPE neutral = bullish HYPE)

Tracks regime state over time with a rolling window, measures transition speed,
and outputs actionable alerts with recommended position actions.

Run:
    cd bot && python -m tools.regime_detector              # One-shot scan
    cd bot && python -m tools.regime_detector --loop        # Continuous (every 2 min)
    cd bot && python -m tools.regime_detector --json        # JSON output for piping
"""

import argparse
import json
import logging
import math
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logger = logging.getLogger("bot.tools.regime_detector")

# ── Constants ────────────────────────────────────────────────────────────

REGIME_HISTORY_FILE = os.path.join(
    os.path.dirname(__file__), "..", "data", "regime_history.json"
)
REGIME_PREDICTIONS_FILE = os.path.join(
    os.path.dirname(__file__), "..", "data", "regime_predictions.json"
)
MAX_HISTORY_ENTRIES = 500  # ~40 hours at 5-min intervals

# Canonical regime labels (shared vocabulary from shared_context.py)
REGIMES = [
    "trend_bull",
    "trend_bear",
    "range",
    "panic_oversold",
    "panic_overbought",
    "recovering",
    "high_volatility",
    "low_liquidity",
    "unknown",
]

# Transition severity: how dangerous is each shift?
# Higher = more urgent action needed.
TRANSITION_SEVERITY = {
    # Into panic — URGENT
    ("trend_bull", "panic_oversold"): 5,
    ("range", "panic_oversold"): 4,
    ("recovering", "panic_oversold"): 4,
    ("trend_bear", "panic_overbought"): 4,
    # Out of panic — OPPORTUNITY
    ("panic_oversold", "recovering"): 4,
    ("panic_oversold", "range"): 3,
    ("panic_overbought", "trend_bear"): 3,
    # Trend breaking
    ("trend_bull", "range"): 3,
    ("trend_bull", "high_volatility"): 3,
    ("trend_bear", "range"): 3,
    # Trend forming
    ("range", "trend_bull"): 3,
    ("range", "trend_bear"): 3,
    ("recovering", "trend_bull"): 3,
}

# Default severity for unlisted transitions
DEFAULT_TRANSITION_SEVERITY = 2


# ── Data Classes ─────────────────────────────────────────────────────────

@dataclass
class RegimeReading:
    """Single point-in-time regime classification for one asset."""
    symbol: str
    timestamp: float
    regime: str
    rsi: float
    rsi_delta_1h: float      # RSI change over last hour
    rsi_delta_3h: float      # RSI change over last 3 hours
    price: float
    price_change_1h: float   # % change
    price_change_3h: float
    volume_ratio: float      # vs 20-bar avg
    adx: float
    ema_alignment: str       # "bull", "bear", "neutral"
    atr_ratio: float         # current ATR / 20-bar avg ATR
    confidence: float        # 0-1 how certain we are of this classification

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RegimeTransition:
    """A detected regime shift."""
    symbol: str
    timestamp: float
    from_regime: str
    to_regime: str
    speed: str               # "fast" (<2h), "normal" (2-6h), "slow" (>6h)
    severity: int            # 1-5
    confidence: float
    rsi_velocity: float      # RSI points/hour — higher = faster panic
    price_velocity: float    # %/hour
    recommended_actions: List[str]
    context: str             # human-readable summary

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CrossAssetDivergence:
    """When assets are in different regimes — relative strength signal."""
    timestamp: float
    leader: str              # asset that shifted first
    laggard: str             # asset that hasn't shifted yet
    leader_regime: str
    laggard_regime: str
    signal: str              # "bullish_divergence", "bearish_divergence", "relative_strength"
    recommended_actions: List[str]
    context: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ADXExhaustion:
    """ADX peak detected — trend is dying, reversal likely in 3-6h."""
    symbol: str
    timestamp: float
    adx_peak: float              # the peak ADX value
    adx_current: float           # current ADX (falling)
    candles_since_peak: int      # how many candles ADX has been falling
    reversal_window_hours: Tuple[float, float]  # estimated (min, max) hours to reversal
    current_regime: str
    context: str

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            "adx_peak": self.adx_peak,
            "adx_current": self.adx_current,
            "candles_since_peak": self.candles_since_peak,
            "reversal_window_hours": list(self.reversal_window_hours),
            "current_regime": self.current_regime,
            "context": self.context,
        }


@dataclass
class BTCLeadSignal:
    """BTC regime shifted — HYPE likely follows in ~4h (83% accuracy)."""
    timestamp: float
    btc_from_regime: str
    btc_to_regime: str
    predicted_hype_direction: str   # "bearish" or "bullish"
    countdown_expires: float        # unix timestamp when 4h window ends
    hours_remaining: float
    confidence: float               # 0.83 base
    context: str

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "btc_from_regime": self.btc_from_regime,
            "btc_to_regime": self.btc_to_regime,
            "predicted_hype_direction": self.predicted_hype_direction,
            "countdown_expires": self.countdown_expires,
            "hours_remaining": round(self.hours_remaining, 2),
            "confidence": self.confidence,
            "context": self.context,
        }


@dataclass
class SqueezeSignal:
    """BB squeeze active — big move incoming, size up."""
    symbol: str
    timestamp: float
    bb_width_percentile: float    # 0-100
    sizing_multiplier: float      # 1.3x or 1.5x
    context: str

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            "bb_width_percentile": round(self.bb_width_percentile, 1),
            "sizing_multiplier": self.sizing_multiplier,
            "context": self.context,
        }


@dataclass
class RegimePredictions:
    """Aggregated forward-looking predictions from regime analysis."""
    adx_exhaustions: List[ADXExhaustion]
    btc_lead_signals: List[BTCLeadSignal]
    squeeze_signals: List[SqueezeSignal]

    def to_dict(self) -> dict:
        return {
            "adx_exhaustions": [e.to_dict() for e in self.adx_exhaustions],
            "btc_lead_signals": [s.to_dict() for s in self.btc_lead_signals],
            "squeeze_signals": [s.to_dict() for s in self.squeeze_signals],
        }


@dataclass
class RegimeReport:
    """Full regime analysis output."""
    timestamp: float
    current_regimes: Dict[str, RegimeReading]
    transitions: List[RegimeTransition]
    divergences: List[CrossAssetDivergence]
    predictions: Optional["RegimePredictions"]
    alerts: List[str]
    summary: str

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "current_regimes": {k: v.to_dict() for k, v in self.current_regimes.items()},
            "transitions": [t.to_dict() for t in self.transitions],
            "divergences": [d.to_dict() for d in self.divergences],
            "predictions": self.predictions.to_dict() if self.predictions else None,
            "alerts": self.alerts,
            "summary": self.summary,
        }


# ── Regime Classifier ───────────────────────────────────────────────────

class RegimeClassifier:
    """Classify regime from OHLCV data for a single asset."""

    @staticmethod
    def compute_rsi(series: pd.Series, period: int = 14) -> Optional[pd.Series]:
        if len(series) < period + 1:
            return None
        delta = series.diff()
        gain = delta.where(delta > 0, 0.0).rolling(period, min_periods=period).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(period, min_periods=period).mean()
        rs = gain / loss.replace(0, 1e-9)
        return 100 - (100 / (1 + rs))

    @staticmethod
    def compute_adx(df: pd.DataFrame, period: int = 14) -> Optional[pd.Series]:
        if len(df) < period + 1:
            return None
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        prev_close = df["close"].astype(float).shift(1)
        up_move = high.diff()
        down_move = -low.diff()
        plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
        minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)
        atr_val = tr.rolling(period, min_periods=1).mean()
        plus_di = (plus_dm.rolling(period, min_periods=1).mean() / atr_val.replace(0, 1e-9)) * 100
        minus_di = (minus_dm.rolling(period, min_periods=1).mean() / atr_val.replace(0, 1e-9)) * 100
        dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-9)) * 100
        return dx.rolling(period, min_periods=1).mean()

    @staticmethod
    def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        prev = df["close"].shift(1)
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - prev).abs(),
            (df["low"] - prev).abs(),
        ], axis=1).max(axis=1)
        return tr.rolling(window=min(period, max(1, len(df))), min_periods=1).mean()

    def classify(self, df: pd.DataFrame, symbol: str) -> Optional[RegimeReading]:
        """Classify current regime from 1h OHLCV data."""
        if df is None or df.empty or len(df) < 20:
            return None

        df = df.copy().sort_values("time").reset_index(drop=True)
        close = df["close"].astype(float)
        price = float(close.iloc[-1])

        # RSI
        rsi_series = self.compute_rsi(close)
        if rsi_series is None:
            return None
        rsi = float(rsi_series.iloc[-1])
        if pd.isna(rsi):
            return None

        # RSI velocity: how fast is RSI changing?
        rsi_1h_ago = float(rsi_series.iloc[-2]) if len(rsi_series) >= 2 else rsi
        rsi_3h_ago = float(rsi_series.iloc[-4]) if len(rsi_series) >= 4 else rsi
        rsi_delta_1h = rsi - rsi_1h_ago
        rsi_delta_3h = rsi - rsi_3h_ago

        # Price changes
        price_1h_ago = float(close.iloc[-2]) if len(close) >= 2 else price
        price_3h_ago = float(close.iloc[-4]) if len(close) >= 4 else price
        price_change_1h = (price - price_1h_ago) / price_1h_ago * 100 if price_1h_ago else 0
        price_change_3h = (price - price_3h_ago) / price_3h_ago * 100 if price_3h_ago else 0

        # Volume ratio
        vol = df["volume"].astype(float)
        vol_avg = float(vol.tail(20).mean()) if len(vol) >= 20 else float(vol.mean())
        vol_current = float(vol.iloc[-1])
        volume_ratio = vol_current / vol_avg if vol_avg > 0 else 1.0

        # ADX
        adx_series = self.compute_adx(df)
        adx = float(adx_series.iloc[-1]) if adx_series is not None else 25.0

        # ATR ratio (volatility expansion/compression)
        atr_series = self.compute_atr(df)
        atr_current = float(atr_series.iloc[-1])
        atr_avg = float(atr_series.tail(20).mean()) if len(atr_series) >= 20 else atr_current
        atr_ratio = atr_current / atr_avg if atr_avg > 0 else 1.0

        # EMA alignment
        ema20 = close.ewm(span=20, min_periods=min(20, len(close))).mean()
        ema50 = close.ewm(span=50, min_periods=min(50, len(close))).mean()
        e20 = float(ema20.iloc[-1])
        e50 = float(ema50.iloc[-1])
        if price > e20 > e50:
            ema_alignment = "bull"
        elif price < e20 < e50:
            ema_alignment = "bear"
        else:
            ema_alignment = "neutral"

        # ── Classify regime ──
        regime, confidence = self._classify_from_indicators(
            rsi, rsi_delta_1h, rsi_delta_3h,
            price_change_1h, price_change_3h,
            volume_ratio, adx, atr_ratio, ema_alignment,
        )

        return RegimeReading(
            symbol=symbol,
            timestamp=time.time(),
            regime=regime,
            rsi=round(rsi, 1),
            rsi_delta_1h=round(rsi_delta_1h, 1),
            rsi_delta_3h=round(rsi_delta_3h, 1),
            price=round(price, 4),
            price_change_1h=round(price_change_1h, 2),
            price_change_3h=round(price_change_3h, 2),
            volume_ratio=round(volume_ratio, 2),
            adx=round(adx, 1),
            ema_alignment=ema_alignment,
            atr_ratio=round(atr_ratio, 2),
            confidence=round(confidence, 2),
        )

    def _classify_from_indicators(
        self,
        rsi: float, rsi_d1h: float, rsi_d3h: float,
        pc_1h: float, pc_3h: float,
        vol_ratio: float, adx: float, atr_ratio: float,
        ema_align: str,
    ) -> Tuple[str, float]:
        """Multi-factor regime classification with confidence scoring."""

        scores: Dict[str, float] = {r: 0.0 for r in REGIMES}

        # ── PANIC detection (highest priority) ──
        # Fast RSI drop + large price drop + volume spike
        if rsi < 25:
            scores["panic_oversold"] += 3.0
        elif rsi < 30:
            scores["panic_oversold"] += 2.0
        if rsi > 80:
            scores["panic_overbought"] += 3.0
        elif rsi > 75:
            scores["panic_overbought"] += 2.0

        # Speed of RSI drop amplifies panic signal
        if rsi_d3h < -15:
            scores["panic_oversold"] += 2.5
        elif rsi_d3h < -10:
            scores["panic_oversold"] += 1.5
        if rsi_d3h > 15:
            scores["panic_overbought"] += 2.5
        elif rsi_d3h > 10:
            scores["panic_overbought"] += 1.5

        # Volume spike during panic
        if vol_ratio > 3.0:
            if rsi < 35:
                scores["panic_oversold"] += 1.5
            if rsi > 65:
                scores["panic_overbought"] += 1.5

        # Large price drops
        if pc_3h < -5:
            scores["panic_oversold"] += 2.0
        elif pc_3h < -3:
            scores["panic_oversold"] += 1.0
        if pc_3h > 5:
            scores["panic_overbought"] += 2.0
        elif pc_3h > 3:
            scores["panic_overbought"] += 1.0

        # ── RECOVERING detection ──
        # RSI was low but now rising, price stabilizing
        if 30 <= rsi <= 45 and rsi_d1h > 2:
            scores["recovering"] += 2.5
        if 30 <= rsi <= 45 and rsi_d3h > 5:
            scores["recovering"] += 2.0
        if pc_1h > 0 and pc_3h < -2:
            # Price bouncing after a drop
            scores["recovering"] += 1.5

        # ── TREND detection ──
        if adx > 25 and ema_align == "bull":
            scores["trend_bull"] += 2.5
        elif adx > 20 and ema_align == "bull":
            scores["trend_bull"] += 1.5

        if adx > 25 and ema_align == "bear":
            scores["trend_bear"] += 2.5
        elif adx > 20 and ema_align == "bear":
            scores["trend_bear"] += 1.5

        # Strong directional momentum
        if 50 <= rsi <= 70 and ema_align == "bull":
            scores["trend_bull"] += 1.0
        if 30 <= rsi <= 50 and ema_align == "bear":
            scores["trend_bear"] += 1.0

        # ── RANGE / CHOP detection ──
        if adx < 20:
            scores["range"] += 2.0
        if 40 <= rsi <= 60 and abs(pc_3h) < 1.5:
            scores["range"] += 1.5
        if atr_ratio < 0.7:
            scores["range"] += 1.0  # Volatility compression = range
        if ema_align == "neutral":
            scores["range"] += 1.0

        # ── HIGH VOLATILITY detection ──
        if atr_ratio > 1.8:
            scores["high_volatility"] += 2.5
        elif atr_ratio > 1.4:
            scores["high_volatility"] += 1.5
        if vol_ratio > 2.0 and abs(pc_3h) > 2:
            scores["high_volatility"] += 1.0

        # ── LOW LIQUIDITY detection ──
        if vol_ratio < 0.3:
            scores["low_liquidity"] += 3.0
        elif vol_ratio < 0.5:
            scores["low_liquidity"] += 1.5

        # ── Pick winner ──
        best_regime = max(scores, key=scores.get)
        best_score = scores[best_regime]
        total_score = sum(scores.values())

        # Confidence = how much the winner dominates
        confidence = best_score / total_score if total_score > 0 else 0.3
        confidence = min(0.95, max(0.2, confidence))

        # If nothing scored well, unknown
        if best_score < 1.5:
            return "unknown", 0.3

        return best_regime, confidence


# ── Transition Detector ──────────────────────────────────────────────────

class TransitionDetector:
    """Detect regime transitions from a history of readings."""

    def __init__(self, history: Dict[str, List[dict]]):
        """
        history: {symbol: [RegimeReading.to_dict(), ...]} ordered by timestamp
        """
        self.history = history

    def detect_transitions(self, current: RegimeReading) -> List[RegimeTransition]:
        """Compare current reading against history to find transitions."""
        sym = current.symbol
        hist = self.history.get(sym, [])

        if len(hist) < 2:
            return []

        transitions = []

        # Get the established regime (majority over last N readings)
        prev_regime = self._get_established_regime(hist)
        if prev_regime is None or prev_regime == current.regime:
            return []

        # Transition detected!
        # Measure speed: how long ago was the old regime dominant?
        shift_start = self._find_shift_start(hist, prev_regime, current.regime)
        shift_duration_h = (current.timestamp - shift_start) / 3600 if shift_start else 6.0

        if shift_duration_h < 2:
            speed = "fast"
        elif shift_duration_h < 6:
            speed = "normal"
        else:
            speed = "slow"

        severity = TRANSITION_SEVERITY.get(
            (prev_regime, current.regime),
            DEFAULT_TRANSITION_SEVERITY
        )

        # Fast shifts are more severe
        if speed == "fast":
            severity = min(5, severity + 1)

        # RSI velocity (points per hour)
        rsi_velocity = current.rsi_delta_3h / 3.0 if current.rsi_delta_3h else 0

        # Price velocity (%/hour)
        price_velocity = current.price_change_3h / 3.0 if current.price_change_3h else 0

        # Generate recommended actions
        actions = self._recommend_actions(
            prev_regime, current.regime, speed, current
        )

        context = (
            f"{sym} shifted from {prev_regime} to {current.regime} "
            f"({speed}, {shift_duration_h:.1f}h). "
            f"RSI {current.rsi:.0f} (delta {current.rsi_delta_3h:+.1f}/3h), "
            f"price {current.price_change_3h:+.2f}%/3h, "
            f"vol {current.volume_ratio:.1f}x avg"
        )

        transitions.append(RegimeTransition(
            symbol=sym,
            timestamp=current.timestamp,
            from_regime=prev_regime,
            to_regime=current.regime,
            speed=speed,
            severity=severity,
            confidence=current.confidence,
            rsi_velocity=round(rsi_velocity, 2),
            price_velocity=round(price_velocity, 2),
            recommended_actions=actions,
            context=context,
        ))

        return transitions

    def _get_established_regime(self, hist: List[dict], lookback: int = 6) -> Optional[str]:
        """Get the dominant regime over last N readings."""
        recent = hist[-lookback:] if len(hist) >= lookback else hist
        regime_counts: Dict[str, int] = {}
        for entry in recent:
            r = entry.get("regime", "unknown")
            regime_counts[r] = regime_counts.get(r, 0) + 1

        if not regime_counts:
            return None

        # Need at least 50% agreement for "established"
        best = max(regime_counts, key=regime_counts.get)
        if regime_counts[best] >= len(recent) * 0.5:
            return best
        return None

    def _find_shift_start(
        self, hist: List[dict], old_regime: str, new_regime: str
    ) -> Optional[float]:
        """Find when the regime first started shifting."""
        # Walk backwards to find the last reading that was solidly old_regime
        for entry in reversed(hist):
            if entry.get("regime") == old_regime:
                return entry.get("timestamp", 0)
        return None

    def _recommend_actions(
        self,
        from_regime: str, to_regime: str,
        speed: str, current: RegimeReading,
    ) -> List[str]:
        """Generate actionable recommendations based on transition type."""
        actions = []

        # ── Into panic (crash) ──
        if to_regime == "panic_oversold":
            actions.append("EXIT all longs or tighten stops to breakeven")
            actions.append("HALT new long entries until RSI recovers above 30")
            if speed == "fast":
                actions.append("URGENT: fast crash — consider immediate exit, do NOT average down")
            if current.volume_ratio > 2.0:
                actions.append("High volume capitulation — bounce likely within 1-4h but timing uncertain")
            # Mean reversion data from insight journal
            actions.append("WATCH for RSI recovery to 30-35 zone (64% up probability, +0.43% avg)")

        elif to_regime == "panic_overbought":
            actions.append("EXIT all shorts or tighten stops")
            actions.append("HALT new short entries until RSI drops below 70")

        # ── Out of panic (recovery) ──
        elif from_regime == "panic_oversold" and to_regime in ("recovering", "range", "trend_bull"):
            actions.append("PREPARE long entries — bounce confirmed")
            actions.append("After 3+ red 1h candles, next 6h is 79% up (+1.17% avg)")
            if to_regime == "recovering":
                actions.append("SIZE conservatively — recovery can fail, wait for RSI 35-50")
            if to_regime == "trend_bull":
                actions.append("SIZE normally — trend resuming, full conviction entries")

        # ── Trend breaking ──
        elif from_regime.startswith("trend") and to_regime == "range":
            actions.append("REDUCE position sizes — trend edge gone")
            actions.append("DISABLE trend-following strategies (regime_trend)")
            actions.append("SWITCH to mean-reversion setups only")
            actions.append("TIGHTEN stops on existing positions")

        elif from_regime.startswith("trend") and to_regime == "high_volatility":
            actions.append("TIGHTEN stops — volatility expansion incoming")
            actions.append("REDUCE size by 50% — high vol = wider stops needed")
            if speed == "fast":
                actions.append("URGENT: possible trend reversal, protect profits")

        # ── Trend forming ──
        elif from_regime == "range" and to_regime.startswith("trend"):
            direction = "LONG" if to_regime == "trend_bull" else "SHORT"
            actions.append(f"PREPARE {direction} entries — trend forming")
            actions.append("ENABLE trend-following strategies (regime_trend)")
            actions.append("SIZE normally — ADX rising confirms trend")

        # ── Recovering to trend ──
        elif from_regime == "recovering" and to_regime == "trend_bull":
            actions.append("GO LONG — recovery confirmed, trend resuming")
            actions.append("This is the highest-edge entry: bounce + trend alignment")

        # ── General ──
        if to_regime == "low_liquidity":
            actions.append("HALT all trading — no edge in thin markets")

        if to_regime == "high_volatility" and from_regime not in ("panic_oversold", "panic_overbought"):
            actions.append("WIDEN stops or reduce size — ATR expanding")

        return actions


# ── Cross-Asset Divergence Detector ──────────────────────────────────────

class DivergenceDetector:
    """Detect when assets diverge in regime — relative strength signal."""

    # Known relationships
    RELATIONSHIPS = {
        ("BTC", "HYPE"): {
            "beta": 0.84,
            "lag_hours": 0.25,  # HYPE follows BTC with ~15 min lag
        },
        ("BTC", "SOL"): {
            "beta": 1.2,
            "lag_hours": 0.5,
        },
    }

    def detect_divergences(
        self, regimes: Dict[str, RegimeReading]
    ) -> List[CrossAssetDivergence]:
        """Find regime divergences between correlated assets."""
        divergences = []

        for (leader_sym, laggard_sym), rel in self.RELATIONSHIPS.items():
            leader = regimes.get(leader_sym)
            laggard = regimes.get(laggard_sym)

            if not leader or not laggard:
                continue

            div = self._check_pair(leader, laggard, rel)
            if div:
                divergences.append(div)

        return divergences

    def _check_pair(
        self,
        leader: RegimeReading,
        laggard: RegimeReading,
        relationship: dict,
    ) -> Optional[CrossAssetDivergence]:
        """Check if two assets are in divergent regimes."""

        l_regime = leader.regime
        f_regime = laggard.regime

        # Same regime = no divergence
        if l_regime == f_regime:
            return None

        # Unclassifiable = skip
        if "unknown" in (l_regime, f_regime):
            return None

        actions = []
        signal = ""
        context = ""

        # BTC in panic, alt holding up = RELATIVE STRENGTH (bullish alt)
        if l_regime == "panic_oversold" and f_regime not in ("panic_oversold", "panic_overbought"):
            signal = "relative_strength"
            actions.append(
                f"{laggard.symbol} showing relative strength vs {leader.symbol} panic"
            )
            actions.append(
                f"BULLISH {laggard.symbol} — when {leader.symbol} stabilizes, "
                f"{laggard.symbol} likely rallies harder"
            )
            if f_regime in ("trend_bull", "recovering"):
                actions.append(
                    f"{laggard.symbol} is leading the recovery — consider aggressive long"
                )
            context = (
                f"{leader.symbol} in PANIC (RSI {leader.rsi:.0f}, {leader.price_change_3h:+.1f}%/3h) "
                f"but {laggard.symbol} holds {f_regime} (RSI {laggard.rsi:.0f}, "
                f"{laggard.price_change_3h:+.1f}%/3h). "
                f"Relative strength = bullish {laggard.symbol}."
            )

        # BTC trending, alt lagging = CATCH-UP TRADE
        elif l_regime == "trend_bull" and f_regime in ("range", "recovering"):
            signal = "bullish_divergence"
            actions.append(
                f"{laggard.symbol} lagging {leader.symbol} uptrend — catch-up trade likely"
            )
            actions.append(
                f"PREPARE long {laggard.symbol} — historically follows with "
                f"{relationship.get('lag_hours', 1):.1f}h lag"
            )
            context = (
                f"{leader.symbol} in trend_bull but {laggard.symbol} still in {f_regime}. "
                f"Beta={relationship.get('beta', 1):.2f}, expected follow-through "
                f"within {relationship.get('lag_hours', 1):.1f}h."
            )

        # BTC trending down, alt still up = DANGER
        elif l_regime == "trend_bear" and f_regime in ("trend_bull", "range"):
            signal = "bearish_divergence"
            actions.append(
                f"WARNING: {leader.symbol} turning bearish but {laggard.symbol} hasn't followed"
            )
            actions.append(
                f"TIGHTEN stops on {laggard.symbol} longs — "
                f"{leader.symbol} bear usually drags alts down"
            )
            # From insight journal: "When BTC dumps, alts dump 2-3x harder"
            beta = relationship.get("beta", 1)
            actions.append(
                f"If {leader.symbol} continues down, expect {laggard.symbol} "
                f"to drop {beta:.1f}x harder"
            )
            context = (
                f"{leader.symbol} in trend_bear (RSI {leader.rsi:.0f}) but "
                f"{laggard.symbol} still in {f_regime}. Historical beta={beta:.2f} — "
                f"alt follow-through is likely."
            )

        # Alt panicking but BTC stable = likely alt-specific event
        elif f_regime == "panic_oversold" and l_regime not in ("panic_oversold", "trend_bear"):
            signal = "relative_weakness"
            actions.append(
                f"{laggard.symbol} panic is ISOLATED — not a {leader.symbol}-driven crash"
            )
            actions.append(
                f"Mean reversion more likely since {leader.symbol} is stable"
            )
            actions.append(
                f"WATCH for {laggard.symbol} bounce — {leader.symbol} support makes it safer"
            )
            context = (
                f"{laggard.symbol} in panic (RSI {laggard.rsi:.0f}) but {leader.symbol} stable "
                f"in {l_regime}. Isolated {laggard.symbol} sell-off — "
                f"bounce probability is HIGHER than correlated crash."
            )

        if not signal:
            return None

        return CrossAssetDivergence(
            timestamp=time.time(),
            leader=leader.symbol,
            laggard=laggard.symbol,
            leader_regime=l_regime,
            laggard_regime=f_regime,
            signal=signal,
            recommended_actions=actions,
            context=context,
        )


# ── History Manager ──────────────────────────────────────────────────────

class RegimeHistoryManager:
    """Persist regime readings to disk for transition detection across runs."""

    def __init__(self, path: str = REGIME_HISTORY_FILE):
        self.path = path
        self.data: Dict[str, List[dict]] = self._load()

    def _load(self) -> Dict[str, List[dict]]:
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to load regime history: {e}")
        return {}

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
        except IOError as e:
            logger.warning(f"Failed to save regime history: {e}")

    def add_reading(self, reading: RegimeReading):
        sym = reading.symbol
        if sym not in self.data:
            self.data[sym] = []
        self.data[sym].append(reading.to_dict())
        # Trim to max entries
        if len(self.data[sym]) > MAX_HISTORY_ENTRIES:
            self.data[sym] = self.data[sym][-MAX_HISTORY_ENTRIES:]

    def get_history(self, symbol: str) -> List[dict]:
        return self.data.get(symbol, [])

    def get_all_history(self) -> Dict[str, List[dict]]:
        return self.data


# ── ADX Trajectory Tracker ───────────────────────────────────────────────

class ADXTrajectoryTracker:
    """Track ADX over last 10 candles, detect peaks signaling trend exhaustion.

    Research: ADX peaks 3.6-6.1h before price reversal. When ADX was rising
    and starts falling for 2+ candles, the trend is dying.
    """

    MIN_PEAK_ADX = 25.0          # Only flag peaks above this (meaningful trend)
    MIN_FALLING_CANDLES = 2      # ADX must fall for N+ candles after peak

    def detect_exhaustion(
        self,
        symbol: str,
        adx_series: Optional[pd.Series],
        current_regime: str,
    ) -> Optional[ADXExhaustion]:
        """Check last 10 ADX readings for a peak-then-decline pattern."""
        if adx_series is None or len(adx_series) < 5:
            return None

        # Get last 10 ADX values
        recent = adx_series.tail(10).values
        if len(recent) < 5:
            return None

        # Find peak in the window
        peak_idx = int(np.argmax(recent))
        peak_val = float(recent[peak_idx])

        if peak_val < self.MIN_PEAK_ADX:
            return None

        # Peak must not be at the very end (ADX must be falling after it)
        candles_since_peak = len(recent) - 1 - peak_idx
        if candles_since_peak < self.MIN_FALLING_CANDLES:
            return None

        # Verify ADX is actually falling: each reading after peak should be lower
        post_peak = recent[peak_idx:]
        falling = all(post_peak[i] >= post_peak[i + 1] - 0.5
                      for i in range(len(post_peak) - 1))
        if not falling:
            return None

        current_adx = float(recent[-1])
        drop_pct = (peak_val - current_adx) / peak_val * 100

        # Only flag if ADX has dropped meaningfully (at least 5%)
        if drop_pct < 5:
            return None

        # Reversal window: 3.6-6.1h from peak (research-based)
        # Adjust based on how many candles have passed (1h candles assumed)
        hours_elapsed = candles_since_peak  # 1h candles
        min_hours = max(0.0, 3.6 - hours_elapsed)
        max_hours = max(0.5, 6.1 - hours_elapsed)

        return ADXExhaustion(
            symbol=symbol,
            timestamp=time.time(),
            adx_peak=round(peak_val, 1),
            adx_current=round(current_adx, 1),
            candles_since_peak=candles_since_peak,
            reversal_window_hours=(round(min_hours, 1), round(max_hours, 1)),
            current_regime=current_regime,
            context=(
                f"{symbol} ADX peaked at {peak_val:.1f}, now {current_adx:.1f} "
                f"(falling for {candles_since_peak} candles, -{drop_pct:.0f}%). "
                f"TREND_EXHAUSTION: reversal likely in {min_hours:.1f}-{max_hours:.1f}h. "
                f"Current regime: {current_regime}."
            ),
        )


# ── BTC Lead Predictor ──────────────────────────────────────────────────

class BTCLeadPredictor:
    """When BTC regime shifts, HYPE follows ~4h later (83% accuracy).

    Tracks BTC regime transitions and generates predictive signals for HYPE.
    Active signals are persisted so they survive restarts.
    """

    LEAD_HOURS = 4.0
    BASE_CONFIDENCE = 0.83
    PREDICTIONS_KEY = "btc_lead_signals"

    # Map BTC regime shifts to predicted HYPE direction
    SHIFT_DIRECTION = {
        # BTC turns bearish -> HYPE will follow bearish
        ("trend_bull", "range"): "bearish",
        ("trend_bull", "high_volatility"): "bearish",
        ("trend_bull", "panic_oversold"): "bearish",
        ("range", "trend_bear"): "bearish",
        ("range", "panic_oversold"): "bearish",
        ("recovering", "panic_oversold"): "bearish",
        # BTC turns bullish -> HYPE will follow bullish
        ("trend_bear", "range"): "bullish",
        ("trend_bear", "recovering"): "bullish",
        ("panic_oversold", "recovering"): "bullish",
        ("panic_oversold", "range"): "bullish",
        ("panic_oversold", "trend_bull"): "bullish",
        ("range", "trend_bull"): "bullish",
        ("recovering", "trend_bull"): "bullish",
    }

    def __init__(self):
        self._active_signals: List[Dict] = []
        self._load()

    def _load(self):
        try:
            if os.path.exists(REGIME_PREDICTIONS_FILE):
                with open(REGIME_PREDICTIONS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._active_signals = data.get(self.PREDICTIONS_KEY, [])
        except (json.JSONDecodeError, IOError):
            self._active_signals = []

    def _save(self):
        try:
            data = {}
            if os.path.exists(REGIME_PREDICTIONS_FILE):
                with open(REGIME_PREDICTIONS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            data[self.PREDICTIONS_KEY] = self._active_signals
            os.makedirs(os.path.dirname(REGIME_PREDICTIONS_FILE), exist_ok=True)
            with open(REGIME_PREDICTIONS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except IOError as e:
            logger.warning(f"Failed to save BTC lead predictions: {e}")

    def check_btc_transitions(
        self, transitions: List[RegimeTransition]
    ) -> List[BTCLeadSignal]:
        """Process BTC transitions and generate/update HYPE predictions."""
        now = time.time()
        new_signals: List[BTCLeadSignal] = []

        # Process new BTC transitions
        for t in transitions:
            if t.symbol != "BTC":
                continue

            direction = self.SHIFT_DIRECTION.get((t.from_regime, t.to_regime))
            if direction is None:
                continue

            expires = now + self.LEAD_HOURS * 3600
            signal = BTCLeadSignal(
                timestamp=now,
                btc_from_regime=t.from_regime,
                btc_to_regime=t.to_regime,
                predicted_hype_direction=direction,
                countdown_expires=expires,
                hours_remaining=self.LEAD_HOURS,
                confidence=self.BASE_CONFIDENCE,
                context=(
                    f"BTC shifted {t.from_regime} -> {t.to_regime}. "
                    f"HYPE predicted to follow {direction} within {self.LEAD_HOURS:.0f}h "
                    f"(83% historical accuracy). "
                    f"{'PREPARE HYPE SELL entries at resistance' if direction == 'bearish' else 'PREPARE HYPE BUY entries at support'}."
                ),
            )
            new_signals.append(signal)

            # Persist
            self._active_signals.append(signal.to_dict())

        # Update existing signals (update hours_remaining, expire old ones)
        active = []
        for s in self._active_signals:
            remaining = (s["countdown_expires"] - now) / 3600
            if remaining > 0:
                s["hours_remaining"] = round(remaining, 2)
                active.append(s)
        self._active_signals = active

        if new_signals or self._active_signals:
            self._save()

        # Return all active signals (new + existing unexpired)
        all_signals = list(new_signals)
        for s in self._active_signals:
            # Don't double-count ones we just created
            if s["timestamp"] != now:
                all_signals.append(BTCLeadSignal(**{
                    k: tuple(v) if k == "reversal_window_hours" else v
                    for k, v in s.items()
                }))

        return all_signals


# ── Squeeze Sizer ────────────────────────────────────────────────────────

class SqueezeSizer:
    """BB squeeze detection — size up when volatility is compressed.

    Research: BB squeeze predicts magnitude (not direction).
    When squeezed, a big move is coming. Size up to capture it.
    """

    # BB width percentile thresholds
    SQUEEZE_THRESHOLD_MILD = 20.0    # < 20th percentile = 1.3x
    SQUEEZE_THRESHOLD_EXTREME = 10.0  # < 10th percentile = 1.5x
    MULTIPLIER_MILD = 1.3
    MULTIPLIER_EXTREME = 1.5

    @staticmethod
    def compute_bb_width_percentile(df: pd.DataFrame) -> Optional[float]:
        """Compute current BB width as percentile of recent history."""
        if df is None or len(df) < 50:
            return None

        close = df["close"].astype(float)
        sma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        bb_width = (2 * std20 / sma20.replace(0, 1e-9)) * 100

        # Drop NaN values
        bb_width = bb_width.dropna()
        if len(bb_width) < 20:
            return None

        current = float(bb_width.iloc[-1])

        # Percentile over last 100 candles (or available)
        lookback = bb_width.tail(100).values
        percentile = float(np.sum(lookback < current) / len(lookback) * 100)

        return percentile

    def detect_squeeze(
        self,
        symbol: str,
        df: pd.DataFrame,
    ) -> Optional[SqueezeSignal]:
        """Check if BB squeeze is active for this symbol."""
        pct = self.compute_bb_width_percentile(df)
        if pct is None:
            return None

        if pct >= self.SQUEEZE_THRESHOLD_MILD:
            return None

        if pct < self.SQUEEZE_THRESHOLD_EXTREME:
            multiplier = self.MULTIPLIER_EXTREME
            severity = "EXTREME"
        else:
            multiplier = self.MULTIPLIER_MILD
            severity = "MILD"

        return SqueezeSignal(
            symbol=symbol,
            timestamp=time.time(),
            bb_width_percentile=pct,
            sizing_multiplier=multiplier,
            context=(
                f"{symbol} BB SQUEEZE ({severity}): width at {pct:.0f}th percentile. "
                f"Big move incoming — sizing multiplier {multiplier}x. "
                f"Direction unknown, but magnitude will be above average."
            ),
        )


# ── Main Detector ────────────────────────────────────────────────────────

class RegimeShiftDetector:
    """
    Main entry point: fetch data, classify regimes, detect transitions,
    find cross-asset divergences, and produce actionable alerts.
    """

    SYMBOLS = {
        "BTC": "bitcoin",
        "HYPE": "hyperliquid",
        "SOL": "solana",
    }

    def __init__(self):
        self.classifier = RegimeClassifier()
        self.history_mgr = RegimeHistoryManager()
        self.divergence_detector = DivergenceDetector()
        self.adx_tracker = ADXTrajectoryTracker()
        self.btc_lead_predictor = BTCLeadPredictor()
        self.squeeze_sizer = SqueezeSizer()

    def scan(self) -> RegimeReport:
        """Full regime scan across all tracked assets."""
        from data.fetcher import DataFetcher

        fetcher = DataFetcher()
        now = time.time()

        current_regimes: Dict[str, RegimeReading] = {}
        all_transitions: List[RegimeTransition] = []
        alerts: List[str] = []
        ohlcv_cache: Dict[str, pd.DataFrame] = {}  # Keep DFs for prediction analysis

        # 1. Classify each asset
        for sym, coin_id in self.SYMBOLS.items():
            df = fetcher.fetch_ohlcv(sym, coin_id, "1h")
            if df is None or df.empty:
                alerts.append(f"WARNING: No data for {sym}")
                continue

            df["time"] = pd.to_datetime(df["time"], utc=True)
            df = df.sort_values("time").reset_index(drop=True)
            ohlcv_cache[sym] = df

            reading = self.classifier.classify(df, sym)
            if reading is None:
                alerts.append(f"WARNING: Could not classify regime for {sym}")
                continue

            current_regimes[sym] = reading

            # 2. Detect transitions
            detector = TransitionDetector(self.history_mgr.get_all_history())
            transitions = detector.detect_transitions(reading)
            all_transitions.extend(transitions)

            # 3. Store reading
            self.history_mgr.add_reading(reading)

        # 4. Detect cross-asset divergences
        divergences = self.divergence_detector.detect_divergences(current_regimes)

        # 5. Regime predictions (ADX exhaustion, BTC lead, squeeze sizing)
        predictions = self._compute_predictions(
            current_regimes, all_transitions, ohlcv_cache
        )

        # 6. Generate alerts from transitions
        for t in all_transitions:
            if t.severity >= 4:
                alerts.append(f"CRITICAL: {t.context}")
            elif t.severity >= 3:
                alerts.append(f"WARNING: {t.context}")
            else:
                alerts.append(f"INFO: {t.context}")

        for d in divergences:
            alerts.append(f"DIVERGENCE: {d.context}")

        # Prediction alerts
        if predictions:
            for exh in predictions.adx_exhaustions:
                alerts.append(f"PREDICTION: {exh.context}")
            for sig in predictions.btc_lead_signals:
                alerts.append(f"PREDICTION: {sig.context}")
            for sq in predictions.squeeze_signals:
                alerts.append(f"PREDICTION: {sq.context}")

        # 7. Build summary
        summary = self._build_summary(current_regimes, all_transitions, divergences)

        # 8. Save history
        self.history_mgr.save()

        return RegimeReport(
            timestamp=now,
            current_regimes=current_regimes,
            transitions=all_transitions,
            divergences=divergences,
            predictions=predictions,
            alerts=alerts,
            summary=summary,
        )

    def _compute_predictions(
        self,
        regimes: Dict[str, RegimeReading],
        transitions: List[RegimeTransition],
        ohlcv_cache: Dict[str, pd.DataFrame],
    ) -> RegimePredictions:
        """Run all prediction engines: ADX exhaustion, BTC lead, squeeze."""
        adx_exhaustions: List[ADXExhaustion] = []
        squeeze_signals: List[SqueezeSignal] = []

        for sym, reading in regimes.items():
            df = ohlcv_cache.get(sym)
            if df is None or df.empty:
                continue

            # ADX trajectory: detect trend exhaustion
            adx_series = self.classifier.compute_adx(df)
            if adx_series is not None:
                exh = self.adx_tracker.detect_exhaustion(sym, adx_series, reading.regime)
                if exh:
                    adx_exhaustions.append(exh)
                    logger.info(f"[REGIME-PREDICT] {exh.context}")

            # Squeeze sizing: detect BB compression
            sq = self.squeeze_sizer.detect_squeeze(sym, df)
            if sq:
                squeeze_signals.append(sq)
                logger.info(f"[REGIME-PREDICT] {sq.context}")

        # BTC lead predictor: check BTC transitions for HYPE predictions
        btc_lead_signals = self.btc_lead_predictor.check_btc_transitions(transitions)
        for sig in btc_lead_signals:
            logger.info(f"[REGIME-PREDICT] {sig.context}")

        return RegimePredictions(
            adx_exhaustions=adx_exhaustions,
            btc_lead_signals=btc_lead_signals,
            squeeze_signals=squeeze_signals,
        )

    def _build_summary(
        self,
        regimes: Dict[str, RegimeReading],
        transitions: List[RegimeTransition],
        divergences: List[CrossAssetDivergence],
    ) -> str:
        parts = []

        # Current state
        for sym, r in regimes.items():
            parts.append(
                f"{sym}: {r.regime} (RSI {r.rsi:.0f}, "
                f"{r.price_change_3h:+.1f}%/3h, vol {r.volume_ratio:.1f}x)"
            )

        if transitions:
            parts.append("")
            parts.append("REGIME SHIFTS DETECTED:")
            for t in transitions:
                parts.append(
                    f"  {t.symbol}: {t.from_regime} -> {t.to_regime} "
                    f"({t.speed}, severity {t.severity}/5)"
                )
                for a in t.recommended_actions[:3]:
                    parts.append(f"    -> {a}")

        if divergences:
            parts.append("")
            parts.append("CROSS-ASSET DIVERGENCES:")
            for d in divergences:
                parts.append(f"  {d.signal}: {d.leader} vs {d.laggard}")
                for a in d.recommended_actions[:2]:
                    parts.append(f"    -> {a}")

        if not transitions and not divergences:
            parts.append("")
            parts.append("No regime shifts or divergences detected. Market stable.")

        return "\n".join(parts)


# ── Pretty Printer ───────────────────────────────────────────────────────

def format_report(report: RegimeReport) -> str:
    """Human-readable formatted output."""
    lines = []
    ts = datetime.fromtimestamp(report.timestamp, tz=timezone.utc)

    lines.append(f"\n{'=' * 70}")
    lines.append(f"  REGIME SHIFT DETECTOR — {ts.strftime('%H:%M UTC %Y-%m-%d')}")
    lines.append(f"{'=' * 70}")

    # Current regimes
    lines.append(f"\n  --- CURRENT REGIMES ---")
    for sym, r in report.current_regimes.items():
        regime_display = r.regime.upper().replace("_", " ")
        conf_bar = "#" * int(r.confidence * 10) + "." * (10 - int(r.confidence * 10))
        lines.append(
            f"  {sym:6s} | {regime_display:20s} | RSI {r.rsi:5.1f} "
            f"({r.rsi_delta_3h:+5.1f}/3h) | {r.price_change_3h:+6.2f}%/3h "
            f"| vol {r.volume_ratio:.1f}x | conf [{conf_bar}]"
        )
        lines.append(
            f"         | EMA: {r.ema_alignment:7s} | ADX: {r.adx:5.1f} "
            f"| ATR ratio: {r.atr_ratio:.2f} | price: ${r.price:,.4f}"
        )

    # Transitions
    if report.transitions:
        lines.append(f"\n  {'!' * 50}")
        lines.append(f"  --- REGIME SHIFTS DETECTED ---")
        lines.append(f"  {'!' * 50}")
        for t in report.transitions:
            severity_bar = "!" * t.severity + "." * (5 - t.severity)
            lines.append(
                f"\n  {t.symbol}: {t.from_regime} --> {t.to_regime}"
            )
            lines.append(
                f"    Speed: {t.speed.upper():8s} | Severity: [{severity_bar}] {t.severity}/5 "
                f"| Confidence: {t.confidence:.0%}"
            )
            lines.append(
                f"    RSI velocity: {t.rsi_velocity:+.1f} pts/h | "
                f"Price velocity: {t.price_velocity:+.2f}%/h"
            )
            lines.append(f"    Context: {t.context}")
            lines.append(f"    RECOMMENDED ACTIONS:")
            for i, action in enumerate(t.recommended_actions, 1):
                lines.append(f"      {i}. {action}")

    # Divergences
    if report.divergences:
        lines.append(f"\n  --- CROSS-ASSET DIVERGENCES ---")
        for d in report.divergences:
            lines.append(f"\n  Signal: {d.signal.upper().replace('_', ' ')}")
            lines.append(f"    {d.leader} ({d.leader_regime}) vs {d.laggard} ({d.laggard_regime})")
            lines.append(f"    {d.context}")
            for i, action in enumerate(d.recommended_actions, 1):
                lines.append(f"      {i}. {action}")

    # Predictions
    if report.predictions:
        preds = report.predictions
        if preds.adx_exhaustions or preds.btc_lead_signals or preds.squeeze_signals:
            lines.append(f"\n  --- REGIME PREDICTIONS ---")

            for exh in preds.adx_exhaustions:
                lines.append(
                    f"\n  TREND EXHAUSTION: {exh.symbol}"
                )
                lines.append(
                    f"    ADX peak {exh.adx_peak} -> now {exh.adx_current} "
                    f"(falling {exh.candles_since_peak} candles)"
                )
                lines.append(
                    f"    Reversal window: {exh.reversal_window_hours[0]:.1f}-"
                    f"{exh.reversal_window_hours[1]:.1f}h"
                )

            for sig in preds.btc_lead_signals:
                lines.append(
                    f"\n  BTC LEADS HYPE: {sig.predicted_hype_direction.upper()}"
                )
                lines.append(
                    f"    BTC shifted: {sig.btc_from_regime} -> {sig.btc_to_regime}"
                )
                lines.append(
                    f"    HYPE follow window: {sig.hours_remaining:.1f}h remaining "
                    f"(83% confidence)"
                )

            for sq in preds.squeeze_signals:
                lines.append(
                    f"\n  BB SQUEEZE: {sq.symbol} ({sq.bb_width_percentile:.0f}th pctile)"
                )
                lines.append(
                    f"    Sizing multiplier: {sq.sizing_multiplier}x — big move incoming"
                )

    # Regime history summary (last 6 readings per asset)
    lines.append(f"\n  --- REGIME HISTORY (last 6 readings) ---")
    history_mgr = RegimeHistoryManager()
    for sym in report.current_regimes:
        hist = history_mgr.get_history(sym)
        if hist:
            recent = hist[-6:]
            regime_seq = " -> ".join(
                h.get("regime", "?").replace("_", " ") for h in recent
            )
            lines.append(f"  {sym}: {regime_seq}")
        else:
            lines.append(f"  {sym}: (first reading)")

    # Alerts
    if report.alerts:
        lines.append(f"\n  --- ALERTS ---")
        for alert in report.alerts:
            if alert.startswith("CRITICAL"):
                lines.append(f"  *** {alert} ***")
            elif alert.startswith("WARNING"):
                lines.append(f"  ** {alert} **")
            else:
                lines.append(f"  {alert}")

    lines.append(f"\n{'=' * 70}")
    return "\n".join(lines)


# ── Integration Helpers ──────────────────────────────────────────────────

def get_current_regime(symbol: str = "HYPE") -> Optional[Dict[str, Any]]:
    """Quick API for other tools to get current regime + any active transitions.

    Returns dict with:
        - regime: current regime label
        - confidence: 0-1
        - rsi: current RSI
        - transition: None or {from, to, speed, severity, actions}
        - divergence: None or {signal, context, actions}
        - predictions: {adx_exhaustion, btc_lead, squeeze}
    """
    detector = RegimeShiftDetector()
    report = detector.scan()

    reading = report.current_regimes.get(symbol)
    if not reading:
        return None

    result = {
        "regime": reading.regime,
        "confidence": reading.confidence,
        "rsi": reading.rsi,
        "rsi_delta_3h": reading.rsi_delta_3h,
        "price_change_3h": reading.price_change_3h,
        "ema_alignment": reading.ema_alignment,
        "transition": None,
        "divergence": None,
        "predictions": {
            "adx_exhaustion": None,
            "btc_lead": None,
            "squeeze": None,
        },
    }

    # Find transitions for this symbol
    for t in report.transitions:
        if t.symbol == symbol:
            result["transition"] = {
                "from": t.from_regime,
                "to": t.to_regime,
                "speed": t.speed,
                "severity": t.severity,
                "actions": t.recommended_actions,
            }
            break

    # Find divergences involving this symbol
    for d in report.divergences:
        if symbol in (d.leader, d.laggard):
            result["divergence"] = {
                "signal": d.signal,
                "context": d.context,
                "actions": d.recommended_actions,
            }
            break

    # Populate predictions for this symbol
    if report.predictions:
        for exh in report.predictions.adx_exhaustions:
            if exh.symbol == symbol:
                result["predictions"]["adx_exhaustion"] = exh.to_dict()
                break
        for sig in report.predictions.btc_lead_signals:
            if symbol == "HYPE":  # BTC lead signals are always for HYPE
                result["predictions"]["btc_lead"] = sig.to_dict()
                break
        for sq in report.predictions.squeeze_signals:
            if sq.symbol == symbol:
                result["predictions"]["squeeze"] = sq.to_dict()
                break

    return result


# ── CLI ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Regime Shift Detector")
    parser.add_argument("--loop", action="store_true", help="Continuous monitoring every 2 min")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--interval", type=int, default=120, help="Loop interval in seconds (default: 120)")
    args = parser.parse_args()

    if args.loop:
        print("Starting regime shift monitoring (Ctrl+C to stop)...")
        print(f"Interval: {args.interval}s")
        while True:
            try:
                detector = RegimeShiftDetector()
                report = detector.scan()
                if args.json:
                    print(json.dumps(report.to_dict(), indent=2))
                else:
                    print(format_report(report))

                # Save latest report
                report_path = os.path.join(
                    os.path.dirname(__file__), "..", "data", "manual", "latest_regime_report.json"
                )
                os.makedirs(os.path.dirname(report_path), exist_ok=True)
                with open(report_path, "w", encoding="utf-8") as f:
                    json.dump(report.to_dict(), f, indent=2)

                time.sleep(args.interval)
            except KeyboardInterrupt:
                print("\nStopped.")
                break
            except Exception as e:
                print(f"Error: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(30)
    else:
        detector = RegimeShiftDetector()
        report = detector.scan()
        if args.json:
            print(json.dumps(report.to_dict(), indent=2))
        else:
            print(format_report(report))


if __name__ == "__main__":
    main()
