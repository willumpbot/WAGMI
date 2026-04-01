"""
Cross-Asset Lead-Lag Alert & Boost Module.

Monitors BTC price movements and alerts when decisive moves occur,
predicting follow-through in correlated assets (SOL, ETH).

Empirical correlations (from analysis):
  BTC-ETH: 0.91 correlation, 1.20x beta, moves simultaneously at 1h,
           but BTC leads by 15-30min at sub-hour resolution
  BTC-SOL: 0.87 correlation, 1.16x beta, ~1h lag
  BTC-HYPE: 0.44 correlation, independent (excluded from alerts)

Two systems:
  1. CrossAssetLeadLagMonitor — original alert system (predictions + accuracy tracking)
  2. LeadLagBoostEngine — NEW: real-time confidence boost for aligned strategy signals.
     Tracks BTC 5min rolling momentum, generates time-delayed "lead signals" for
     followers, and provides a get_boost() method for ensemble confidence amplification.
     This is a BOOST system — it never generates standalone trades.

Usage:
  # Alert system (original)
  monitor = CrossAssetLeadLagMonitor()
  result = monitor.check_btc_lead(btc_prices_5m, sol_price, eth_price)
  if result["alert"]:
      print(f"BTC moved {result['btc_move_pct']:.2f}% -> expect SOL {result['expected_sol_move']:.2f}%")

  # Boost system (new)
  engine = LeadLagBoostEngine()
  engine.update_btc_price(84500.0)  # call every ~1min
  engine.update_follower_price("SOL", 135.0)
  boost = engine.get_boost("SOL", "BUY")  # returns 0-12 confidence boost
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# BTC move threshold (%) over the lookback window to trigger an alert
BTC_MOVE_THRESHOLD = 0.3

# Number of 5m candles in a 15-minute window
LOOKBACK_CANDLES = 3

# Beta multipliers (how much the follower amplifies BTC's move)
BETA_SOL = 1.16
BETA_ETH = 1.20

# How long (seconds) to wait before checking if prediction was correct
PREDICTION_EVAL_WINDOW = 3600  # 1 hour

# Minimum number of BTC price points needed to compute a move
MIN_PRICES = 2


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Prediction:
    """A recorded prediction for later evaluation."""

    timestamp: float  # time.time() when prediction was made
    btc_move_pct: float
    expected_sol_move: float
    expected_eth_move: float
    recommended_side: str  # "LONG" or "SHORT"
    sol_price_at_alert: float
    eth_price_at_alert: float
    evaluated: bool = False
    sol_correct: Optional[bool] = None
    eth_correct: Optional[bool] = None


@dataclass
class PredictionStats:
    """Rolling accuracy statistics."""

    total: int = 0
    sol_correct: int = 0
    eth_correct: int = 0

    @property
    def sol_accuracy(self) -> float:
        return self.sol_correct / self.total if self.total > 0 else 0.0

    @property
    def eth_accuracy(self) -> float:
        return self.eth_correct / self.total if self.total > 0 else 0.0


# ---------------------------------------------------------------------------
# Main monitor
# ---------------------------------------------------------------------------

class CrossAssetLeadLagMonitor:
    """Monitors BTC for decisive moves and predicts SOL/ETH follow-through."""

    def __init__(
        self,
        btc_threshold: float = BTC_MOVE_THRESHOLD,
        lookback_candles: int = LOOKBACK_CANDLES,
        beta_sol: float = BETA_SOL,
        beta_eth: float = BETA_ETH,
        eval_window: int = PREDICTION_EVAL_WINDOW,
    ):
        self.btc_threshold = btc_threshold
        self.lookback_candles = lookback_candles
        self.beta_sol = beta_sol
        self.beta_eth = beta_eth
        self.eval_window = eval_window

        # Pending predictions awaiting evaluation
        self._predictions: List[Prediction] = []
        self._stats = PredictionStats()

        # Cooldown: avoid spamming alerts for the same move
        self._last_alert_time: float = 0.0
        self._alert_cooldown: float = 300.0  # 5 minutes between alerts

    def check_btc_lead(
        self,
        btc_prices_5m: List[float],
        sol_price: float,
        eth_price: float,
        current_time: Optional[float] = None,
    ) -> Dict:
        """
        Check if BTC has made a decisive move and predict follower response.

        Args:
            btc_prices_5m: Recent BTC prices at 5-minute intervals (oldest first).
                           Needs at least `lookback_candles + 1` entries for a full
                           15-minute window, but works with as few as 2.
            sol_price: Current SOL price.
            eth_price: Current ETH price.
            current_time: Optional override for time.time() (for testing).

        Returns:
            Dict with keys:
                alert (bool): Whether a decisive BTC move was detected.
                btc_move_pct (float): BTC % change over the lookback window.
                expected_sol_move (float): Predicted SOL % move.
                expected_eth_move (float): Predicted ETH % move.
                recommended_side (str): "LONG", "SHORT", or "NONE".
                prediction_stats (dict): Rolling accuracy of past predictions.
        """
        now = current_time or time.time()

        # Evaluate any pending predictions that are past the evaluation window
        self._evaluate_predictions(sol_price, eth_price, now)

        # Default response (no alert)
        result = {
            "alert": False,
            "btc_move_pct": 0.0,
            "expected_sol_move": 0.0,
            "expected_eth_move": 0.0,
            "recommended_side": "NONE",
            "prediction_stats": {
                "total": self._stats.total,
                "sol_accuracy": self._stats.sol_accuracy,
                "eth_accuracy": self._stats.eth_accuracy,
            },
        }

        # Need at least 2 prices to compute a move
        if len(btc_prices_5m) < MIN_PRICES:
            return result

        # Use only the last lookback_candles+1 prices for the window
        window = btc_prices_5m[-(self.lookback_candles + 1):]
        start_price = window[0]
        end_price = window[-1]

        if start_price <= 0:
            return result

        btc_move_pct = ((end_price - start_price) / start_price) * 100.0
        result["btc_move_pct"] = round(btc_move_pct, 4)

        # Check if move is decisive
        if abs(btc_move_pct) < self.btc_threshold:
            return result

        # Check cooldown
        if (now - self._last_alert_time) < self._alert_cooldown:
            return result

        # Decisive move detected -- compute expected follower moves
        expected_sol = btc_move_pct * self.beta_sol
        expected_eth = btc_move_pct * self.beta_eth
        side = "LONG" if btc_move_pct > 0 else "SHORT"

        result["alert"] = True
        result["expected_sol_move"] = round(expected_sol, 4)
        result["expected_eth_move"] = round(expected_eth, 4)
        result["recommended_side"] = side

        # Record prediction for later evaluation
        self._predictions.append(Prediction(
            timestamp=now,
            btc_move_pct=btc_move_pct,
            expected_sol_move=expected_sol,
            expected_eth_move=expected_eth,
            recommended_side=side,
            sol_price_at_alert=sol_price,
            eth_price_at_alert=eth_price,
        ))

        self._last_alert_time = now

        logger.info(
            "BTC lead-lag alert: BTC %.2f%% -> expect SOL %.2f%%, ETH %.2f%% | side=%s",
            btc_move_pct, expected_sol, expected_eth, side,
        )

        return result

    def _evaluate_predictions(
        self,
        current_sol: float,
        current_eth: float,
        now: float,
    ) -> None:
        """Evaluate pending predictions whose eval window has elapsed."""
        for pred in self._predictions:
            if pred.evaluated:
                continue
            if (now - pred.timestamp) < self.eval_window:
                continue

            # Check if direction was correct
            if pred.sol_price_at_alert > 0:
                sol_actual_pct = ((current_sol - pred.sol_price_at_alert)
                                  / pred.sol_price_at_alert) * 100.0
                # Direction match: both positive or both negative
                pred.sol_correct = (sol_actual_pct * pred.expected_sol_move) > 0
            else:
                pred.sol_correct = False

            if pred.eth_price_at_alert > 0:
                eth_actual_pct = ((current_eth - pred.eth_price_at_alert)
                                  / pred.eth_price_at_alert) * 100.0
                pred.eth_correct = (eth_actual_pct * pred.expected_eth_move) > 0
            else:
                pred.eth_correct = False

            pred.evaluated = True
            self._stats.total += 1
            if pred.sol_correct:
                self._stats.sol_correct += 1
            if pred.eth_correct:
                self._stats.eth_correct += 1

            logger.info(
                "Lead-lag prediction evaluated: SOL %s, ETH %s (total=%d)",
                "correct" if pred.sol_correct else "wrong",
                "correct" if pred.eth_correct else "wrong",
                self._stats.total,
            )

    def get_stats(self) -> Dict:
        """Return current prediction accuracy statistics."""
        return {
            "total_predictions": self._stats.total,
            "sol_accuracy": round(self._stats.sol_accuracy, 3),
            "eth_accuracy": round(self._stats.eth_accuracy, 3),
            "pending_evaluations": sum(
                1 for p in self._predictions if not p.evaluated
            ),
        }

    def reset(self) -> None:
        """Reset all state (useful for testing)."""
        self._predictions.clear()
        self._stats = PredictionStats()
        self._last_alert_time = 0.0


# ---------------------------------------------------------------------------
# Lead-Lag Boost Engine (new: real-time confidence boost for ensemble)
# ---------------------------------------------------------------------------

@dataclass
class _PricePoint:
    """Internal: timestamped price observation."""
    price: float
    timestamp: float  # time.time()


@dataclass
class LeadSignal:
    """A pending lead signal generated by a BTC move, targeting a follower asset.

    The signal becomes active after `active_after` and expires at `expires_at`.
    While active, it provides a confidence boost to aligned strategy signals.
    """
    follower: str          # e.g. "SOL"
    side: str              # "BUY" or "SELL"
    btc_move_pct: float    # BTC move that triggered this signal
    boost: float           # confidence boost to apply (0-12)
    created_at: float      # time.time() when BTC move was detected
    active_after: float    # time.time() when boost becomes active (after min lag)
    expires_at: float      # time.time() when boost expires (after max lag)
    btc_volume_ratio: float  # volume ratio at time of BTC move (1.0 = average)
    correlation_at_creation: float  # real-time correlation when signal was created


class LeadLagBoostEngine:
    """Real-time BTC lead-lag confidence boost engine.

    Tracks BTC 5-minute rolling momentum and generates time-delayed "lead signals"
    for follower assets (SOL, ETH, HYPE). These lead signals boost the confidence
    of aligned strategy signals in the ensemble -- they NEVER generate standalone trades.

    How it works:
    1. BTC prices are fed via update_btc_price() every ~1 minute.
    2. When BTC moves >threshold% in 15 minutes with above-average volume:
       - A LeadSignal is created for each configured follower
       - The signal has a time window (min_lag -> max_lag) during which it's active
    3. get_boost(symbol, side) returns the confidence boost for an aligned signal
    4. Real-time correlation is tracked and decays the boost if correlation weakens
    """

    # Maximum number of price points to retain per symbol
    _MAX_HISTORY = 200

    # Number of 5-min candles for BTC momentum measurement (3 candles = 15 min)
    _MOMENTUM_WINDOW = 3

    # Minimum observations needed before computing momentum
    _MIN_OBSERVATIONS = 2

    # Cooldown between lead signals for the same follower (seconds)
    _SIGNAL_COOLDOWN = 300.0  # 5 minutes

    # Maximum number of active lead signals to keep
    _MAX_LEAD_SIGNALS = 50

    # Rolling window size for real-time correlation tracking
    _CORRELATION_WINDOW = 60  # last 60 price observations

    def __init__(
        self,
        btc_move_threshold: float = 0.3,
        max_boost: float = 12.0,
        min_correlation: float = 0.60,
        correlation_decay: float = 0.98,
        enabled: bool = True,
    ):
        """Initialize the boost engine.

        Args:
            btc_move_threshold: Min BTC % move over 15min to trigger a lead signal.
            max_boost: Maximum confidence boost (capped per-symbol by config).
            min_correlation: Below this real-time correlation, boost is zeroed.
            correlation_decay: Exponential decay factor applied each evaluation
                               if follower doesn't follow BTC direction.
            enabled: Master switch. When False, get_boost() always returns 0.
        """
        self.btc_move_threshold = btc_move_threshold
        self.max_boost = max_boost
        self.min_correlation = min_correlation
        self.correlation_decay = correlation_decay
        self.enabled = enabled

        # Price history: symbol -> deque of _PricePoint
        self._btc_prices: deque = deque(maxlen=self._MAX_HISTORY)
        self._follower_prices: Dict[str, deque] = {}

        # Volume tracking: deque of (timestamp, volume) tuples
        self._btc_volumes: deque = deque(maxlen=self._MAX_HISTORY)

        # Active lead signals
        self._lead_signals: List[LeadSignal] = []

        # Per-follower cooldown tracking
        self._last_signal_time: Dict[str, float] = {}

        # Real-time correlation tracking: symbol -> rolling correlation estimate
        self._realtime_correlation: Dict[str, float] = {}

        # Per-follower return series for correlation calculation
        self._btc_returns: deque = deque(maxlen=self._CORRELATION_WINDOW)
        self._follower_returns: Dict[str, deque] = {}

        # Load per-symbol config from trading_config
        self._symbol_configs: Dict[str, dict] = {}
        try:
            from trading_config import LEAD_LAG_SYMBOL_CONFIG
            self._symbol_configs = LEAD_LAG_SYMBOL_CONFIG
        except ImportError:
            # Fallback defaults
            self._symbol_configs = {
                "SOL": {"lag_minutes": (30, 60), "correlation": 0.87, "beta": 1.16, "boost_cap": 12.0},
                "ETH": {"lag_minutes": (15, 30), "correlation": 0.91, "beta": 1.20, "boost_cap": 10.0},
                "HYPE": {"lag_minutes": (15, 45), "correlation": 0.44, "beta": 1.50, "boost_cap": 5.0},
            }

        # Initialize real-time correlations from historical values
        for sym, cfg in self._symbol_configs.items():
            self._realtime_correlation[sym] = cfg.get("correlation", 0.5)

    # ------------------------------------------------------------------
    # Price feed API
    # ------------------------------------------------------------------

    def update_btc_price(
        self, price: float, volume: float = 0.0, current_time: Optional[float] = None
    ) -> List[LeadSignal]:
        """Feed a new BTC price observation. Call every ~1 minute.

        Args:
            price: Current BTC price.
            volume: Current period volume (0 = not available).
            current_time: Override for time.time() (testing).

        Returns:
            List of new LeadSignal objects created (empty if no decisive move).
        """
        if not self.enabled:
            return []

        now = current_time or time.time()

        # Compute BTC return before appending (for correlation tracking)
        if self._btc_prices:
            prev_price = self._btc_prices[-1].price
            if prev_price > 0:
                btc_ret = (price - prev_price) / prev_price
                self._btc_returns.append(btc_ret)

        self._btc_prices.append(_PricePoint(price=price, timestamp=now))

        if volume > 0:
            self._btc_volumes.append((now, volume))

        # Expire old lead signals
        self._lead_signals = [
            s for s in self._lead_signals if s.expires_at > now
        ]
        # Cap total lead signals
        if len(self._lead_signals) > self._MAX_LEAD_SIGNALS:
            self._lead_signals = self._lead_signals[-self._MAX_LEAD_SIGNALS:]

        # Check for decisive BTC move
        return self._check_btc_momentum(now)

    def update_follower_price(
        self, symbol: str, price: float, current_time: Optional[float] = None
    ) -> None:
        """Feed a new follower asset price observation.

        Args:
            symbol: Asset symbol (e.g. "SOL", "ETH").
            price: Current price.
            current_time: Override for time.time() (testing).
        """
        if not self.enabled:
            return

        now = current_time or time.time()

        # Strip exchange suffixes
        base = symbol.replace("/USDC:USDC", "").replace("/USDT:USDT", "").replace("/USD", "")

        if base not in self._follower_prices:
            self._follower_prices[base] = deque(maxlen=self._MAX_HISTORY)
            self._follower_returns[base] = deque(maxlen=self._CORRELATION_WINDOW)

        # Compute follower return for correlation tracking
        prices = self._follower_prices[base]
        if prices:
            prev_price = prices[-1].price
            if prev_price > 0:
                fret = (price - prev_price) / prev_price
                self._follower_returns[base].append(fret)
                # Update real-time correlation
                self._update_realtime_correlation(base)

        prices.append(_PricePoint(price=price, timestamp=now))

    # ------------------------------------------------------------------
    # Boost API (called by ensemble)
    # ------------------------------------------------------------------

    def get_boost(
        self, symbol: str, side: str, current_time: Optional[float] = None
    ) -> float:
        """Get the confidence boost for a signal on `symbol` in `side` direction.

        This is the main API called by the ensemble. Returns a float 0-max_boost
        representing how much to add to the signal's confidence.

        Returns 0.0 if:
        - Engine is disabled
        - No active lead signal for this symbol in this direction
        - Real-time correlation has decayed below minimum threshold
        - Symbol is not configured for lead-lag

        Args:
            symbol: Asset symbol (e.g. "SOL", "ETH").
            side: Signal direction ("BUY" or "SELL").
            current_time: Override for time.time() (testing).

        Returns:
            Confidence boost to add (0.0 to max_boost).
        """
        if not self.enabled:
            return 0.0

        now = current_time or time.time()

        base = symbol.replace("/USDC:USDC", "").replace("/USDT:USDT", "").replace("/USD", "")
        cfg = self._symbol_configs.get(base)
        if not cfg:
            return 0.0

        # Check real-time correlation
        rt_corr = self._realtime_correlation.get(base, 0.0)
        if rt_corr < self.min_correlation:
            return 0.0

        # Find the best active lead signal for this symbol + side
        best_boost = 0.0
        for sig in self._lead_signals:
            if sig.follower != base:
                continue
            if sig.side != side.upper():
                continue
            # Must be in active window (after min lag, before expiry)
            if now < sig.active_after or now > sig.expires_at:
                continue

            # Time decay: boost weakens as we approach expiry
            total_window = sig.expires_at - sig.active_after
            elapsed = now - sig.active_after
            if total_window > 0:
                time_decay = max(0.0, 1.0 - (elapsed / total_window) * 0.5)
            else:
                time_decay = 1.0

            # Correlation scaling: boost scales with real-time correlation
            corr_scale = rt_corr / cfg.get("correlation", 0.87)
            corr_scale = min(corr_scale, 1.2)  # cap at 120% of base

            effective_boost = sig.boost * time_decay * corr_scale

            # Apply per-symbol cap
            symbol_cap = cfg.get("boost_cap", self.max_boost)
            effective_boost = min(effective_boost, symbol_cap)

            if effective_boost > best_boost:
                best_boost = effective_boost

        if best_boost > 0:
            logger.info(
                "[%s] Lead-lag boost: +%.1f confidence (%s), rt_corr=%.2f",
                base, best_boost, side, rt_corr,
            )

        return round(best_boost, 2)

    def get_active_signals(self, current_time: Optional[float] = None) -> List[Dict]:
        """Return a summary of all active lead signals (for dashboard/logging)."""
        now = current_time or time.time()
        result = []
        for sig in self._lead_signals:
            is_active = sig.active_after <= now <= sig.expires_at
            result.append({
                "follower": sig.follower,
                "side": sig.side,
                "btc_move_pct": round(sig.btc_move_pct, 3),
                "boost": round(sig.boost, 2),
                "active": is_active,
                "time_remaining_s": max(0, int(sig.expires_at - now)),
                "btc_volume_ratio": round(sig.btc_volume_ratio, 2),
                "correlation": round(sig.correlation_at_creation, 3),
            })
        return result

    def get_diagnostics(self) -> Dict:
        """Return engine diagnostic information."""
        return {
            "enabled": self.enabled,
            "btc_price_count": len(self._btc_prices),
            "active_lead_signals": len([
                s for s in self._lead_signals
                if s.active_after <= time.time() <= s.expires_at
            ]),
            "pending_lead_signals": len([
                s for s in self._lead_signals
                if time.time() < s.active_after
            ]),
            "realtime_correlations": {
                k: round(v, 3) for k, v in self._realtime_correlation.items()
            },
            "btc_move_threshold": self.btc_move_threshold,
            "max_boost": self.max_boost,
            "min_correlation": self.min_correlation,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_btc_momentum(self, now: float) -> List[LeadSignal]:
        """Check if BTC has made a decisive move in the last 15 minutes."""
        if len(self._btc_prices) < self._MIN_OBSERVATIONS:
            return []

        # Find price from ~15 minutes ago
        window_start = now - 15 * 60  # 15 minutes
        baseline = None
        for pp in self._btc_prices:
            if pp.timestamp >= window_start:
                baseline = pp
                break

        if baseline is None or baseline.price <= 0:
            return []

        current = self._btc_prices[-1]
        btc_move_pct = ((current.price - baseline.price) / baseline.price) * 100.0

        # Check threshold
        if abs(btc_move_pct) < self.btc_move_threshold:
            return []

        # Compute volume ratio (current vs average)
        volume_ratio = self._compute_volume_ratio(now)

        # Generate lead signals for each follower
        new_signals = []
        for sym, cfg in self._symbol_configs.items():
            # Check cooldown
            last_time = self._last_signal_time.get(sym, 0.0)
            if (now - last_time) < self._SIGNAL_COOLDOWN:
                continue

            lag_min, lag_max = cfg["lag_minutes"]
            corr = self._realtime_correlation.get(sym, cfg.get("correlation", 0.5))

            # Skip if correlation too low
            if corr < self.min_correlation:
                continue

            # Compute boost: scale by |move|, correlation, and volume
            # Base boost = |move%| * correlation * 10, capped by max_boost and symbol cap
            raw_boost = abs(btc_move_pct) * corr * 10.0

            # Volume bonus: above-average volume strengthens the signal
            if volume_ratio > 1.0:
                raw_boost *= min(volume_ratio, 2.0)  # cap at 2x volume bonus

            symbol_cap = cfg.get("boost_cap", self.max_boost)
            boost = min(raw_boost, symbol_cap, self.max_boost)

            side = "BUY" if btc_move_pct > 0 else "SELL"

            lead_sig = LeadSignal(
                follower=sym,
                side=side,
                btc_move_pct=round(btc_move_pct, 4),
                boost=round(boost, 2),
                created_at=now,
                active_after=now + lag_min * 60,  # becomes active after min lag
                expires_at=now + lag_max * 60,     # expires after max lag
                btc_volume_ratio=round(volume_ratio, 2),
                correlation_at_creation=round(corr, 3),
            )
            self._lead_signals.append(lead_sig)
            self._last_signal_time[sym] = now
            new_signals.append(lead_sig)

            logger.info(
                "Lead signal created: BTC %.2f%% -> %s %s (boost=%.1f, "
                "active in %d-%d min, vol_ratio=%.1f, corr=%.2f)",
                btc_move_pct, sym, side, boost, lag_min, lag_max,
                volume_ratio, corr,
            )

        return new_signals

    def _compute_volume_ratio(self, now: float) -> float:
        """Compute current volume relative to recent average.

        Returns ratio > 1.0 if current volume is above average, < 1.0 if below.
        Returns 1.0 if no volume data is available.
        """
        if len(self._btc_volumes) < 3:
            return 1.0

        # Recent volumes (last 15 min)
        recent_cutoff = now - 15 * 60
        recent_vols = [v for t, v in self._btc_volumes if t >= recent_cutoff]

        # Average volumes (full history)
        all_vols = [v for _, v in self._btc_volumes]
        avg_vol = sum(all_vols) / len(all_vols) if all_vols else 1.0

        if avg_vol <= 0 or not recent_vols:
            return 1.0

        recent_avg = sum(recent_vols) / len(recent_vols)
        return recent_avg / avg_vol

    def _update_realtime_correlation(self, symbol: str) -> None:
        """Update real-time rolling correlation between BTC and a follower.

        Uses the last N return observations. If the follower consistently
        diverges from BTC direction, correlation decays.
        """
        btc_rets = list(self._btc_returns)
        foll_rets = list(self._follower_returns.get(symbol, []))

        # Need at least 10 paired observations
        n = min(len(btc_rets), len(foll_rets))
        if n < 10:
            return

        # Use last N paired returns
        btc_r = btc_rets[-n:]
        fol_r = foll_rets[-n:]

        # Compute Pearson correlation
        mean_b = sum(btc_r) / n
        mean_f = sum(fol_r) / n

        cov = sum((b - mean_b) * (f - mean_f) for b, f in zip(btc_r, fol_r)) / n
        var_b = sum((b - mean_b) ** 2 for b in btc_r) / n
        var_f = sum((f - mean_f) ** 2 for f in fol_r) / n

        denom = math.sqrt(var_b * var_f) if var_b > 0 and var_f > 0 else 0
        if denom <= 0:
            return

        new_corr = cov / denom

        # Exponential moving average with the historical prior
        base_corr = self._symbol_configs.get(symbol, {}).get("correlation", 0.5)
        alpha = 0.3  # weight for new observation vs prior
        old_corr = self._realtime_correlation.get(symbol, base_corr)

        # Blend: decay toward new_corr, but with inertia from old estimate
        blended = old_corr * (1 - alpha) + new_corr * alpha

        # Apply decay if correlation is dropping below historical baseline
        if blended < base_corr:
            blended *= self.correlation_decay

        # Clamp to [0, 1]
        self._realtime_correlation[symbol] = max(0.0, min(1.0, blended))

    def reset(self) -> None:
        """Reset all state (useful for testing)."""
        self._btc_prices.clear()
        self._btc_volumes.clear()
        self._btc_returns.clear()
        self._follower_prices.clear()
        self._follower_returns.clear()
        self._lead_signals.clear()
        self._last_signal_time.clear()
        # Re-initialize correlations from config
        for sym, cfg in self._symbol_configs.items():
            self._realtime_correlation[sym] = cfg.get("correlation", 0.5)
