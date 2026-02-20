"""
Self-improving ML system.
Learns from every trade outcome AND market observations to adjust confidence.

Key improvements over v1:
- Learns from EVERY tick (not just closed trades) via market snapshots
- Tracks per-symbol and per-strategy performance separately
- Volatility-adjusted confidence (high vol = less confident)
- Momentum features (price change %, volume surge)
- Rolling win rate per strategy feeds back into ensemble weights
- Saves model + stats after every retrain for crash recovery
"""

import json
import logging
import os
import time
import numpy as np
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

logger = logging.getLogger("bot.ml")


@dataclass
class TradeOutcome:
    """Records everything about a completed trade for ML training."""
    symbol: str
    strategy: str
    side: str
    confidence: float
    regime_score: float = 0.0
    vwap_aligned: bool = False
    ema_aligned: bool = False
    stop_width_ratio: float = 0.0
    hour_of_day: int = 0
    day_of_week: int = 0
    leverage: float = 1.0

    # Market context at signal time
    price_change_1h_pct: float = 0.0
    price_change_24h_pct: float = 0.0
    volume_ratio: float = 1.0  # current vol / avg vol
    volatility: float = 0.0    # ATR / price as percentage
    num_strategies_agree: int = 1

    # Outcome
    win: bool = False
    pnl: float = 0.0
    hold_time_s: float = 0.0
    exit_action: str = ""

    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class MarketSnapshot:
    """Lightweight observation recorded every tick for faster learning."""
    symbol: str
    price: float
    price_change_1h_pct: float = 0.0
    price_change_24h_pct: float = 0.0
    volume_ratio: float = 1.0
    volatility: float = 0.0
    regime_score: float = 0.0
    ensemble_direction: str = ""  # "BUY", "SELL", or "" (no signal)
    ensemble_confidence: float = 0.0
    # Where price went in next N minutes (filled in later)
    future_return_5m: Optional[float] = None
    future_return_15m: Optional[float] = None
    future_return_1h: Optional[float] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SignalLearner:
    """
    ML model that learns from trade outcomes AND market observations.

    Two learning modes:
    1. Trade learning: logistic regression on closed trades (existing)
    2. Market learning: tracks which conditions led to price moves (new)
       - Builds a rolling picture of "when strategies say BUY, does price go up?"
       - Tracks per-strategy accuracy over recent windows
    """

    def __init__(
        self,
        data_dir: str = "ml_data",
        min_samples: int = 20,
        retrain_interval: int = 10,
        adjustment_weight: float = 0.4,
    ):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.outcomes_path = self.data_dir / "trade_outcomes.json"
        self.model_path = self.data_dir / "model_weights.json"
        self.stats_path = self.data_dir / "strategy_stats.json"
        self.snapshots_path = self.data_dir / "market_snapshots.json"

        self.min_samples = min_samples
        self.retrain_interval = retrain_interval
        self.adjustment_weight = adjustment_weight

        self.outcomes: List[TradeOutcome] = self._load_outcomes()
        self.snapshots: List[MarketSnapshot] = self._load_snapshots()
        self.weights: Optional[np.ndarray] = None
        self.bias: float = 0.0
        self._samples_since_train = 0

        # Snapshot-based direction models (learn from market observations, not trades)
        self.snapshot_weights: Optional[np.ndarray] = None  # 1h model
        self.snapshot_bias: float = 0.0
        self.fast_weights: Optional[np.ndarray] = None      # 5m model (quick feedback)
        self.fast_bias: float = 0.0
        self._snapshots_since_train = 0

        # Per-strategy rolling performance
        self.strategy_stats: Dict[str, Dict] = self._load_strategy_stats()

        self._load_model()

    # ─── Persistence ─────────────────────────────────────────────────

    def _load_outcomes(self) -> List[TradeOutcome]:
        if self.outcomes_path.exists():
            try:
                with open(self.outcomes_path) as f:
                    data = json.load(f)
                loaded = []
                for d in data:
                    # Handle fields that may not exist in old data
                    for key in ["price_change_1h_pct", "price_change_24h_pct",
                                "volume_ratio", "volatility", "num_strategies_agree"]:
                        d.setdefault(key, 0.0 if key != "num_strategies_agree" else 1)
                    loaded.append(TradeOutcome(**d))
                return loaded
            except Exception as e:
                logger.warning(f"Failed to load outcomes: {e}")
                # Auto-recover: rename corrupted file so we start fresh
                corrupt = self.outcomes_path.with_suffix(".json.corrupt")
                try:
                    self.outcomes_path.rename(corrupt)
                    logger.warning(f"Renamed corrupted outcomes to {corrupt}")
                except Exception:
                    pass
        return []

    def _save_outcomes(self):
        try:
            with open(self.outcomes_path, "w") as f:
                json.dump([asdict(o) for o in self.outcomes[-500:]], f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save outcomes: {e}")

    def _load_snapshots(self) -> List[MarketSnapshot]:
        if self.snapshots_path.exists():
            try:
                with open(self.snapshots_path) as f:
                    data = json.load(f)
                loaded = []
                for d in data[-2000:]:
                    # Handle old snapshots missing new fields
                    d.setdefault("price_change_24h_pct", 0.0)
                    d.setdefault("regime_score", 0.0)
                    d.setdefault("ensemble_direction", "")
                    d.setdefault("ensemble_confidence", 0.0)
                    loaded.append(MarketSnapshot(**d))
                return loaded
            except Exception as e:
                logger.warning(f"Failed to load snapshots: {e}")
                corrupt = self.snapshots_path.with_suffix(".json.corrupt")
                try:
                    self.snapshots_path.rename(corrupt)
                    logger.warning(f"Renamed corrupted snapshots to {corrupt}")
                except Exception:
                    pass
        return []

    def _save_snapshots(self):
        try:
            # Keep last 2000 snapshots
            with open(self.snapshots_path, "w") as f:
                json.dump([asdict(s) for s in self.snapshots[-2000:]], f)
        except Exception as e:
            logger.warning(f"Failed to save snapshots: {e}")

    def _load_model(self):
        if self.model_path.exists():
            try:
                with open(self.model_path) as f:
                    data = json.load(f)
                # New format with trade_model/snapshot_model keys
                if "trade_model" in data:
                    tm = data["trade_model"]
                    self.weights = np.array(tm["weights"])
                    self.bias = tm["bias"]
                elif "weights" in data:
                    # Old format - backwards compatible
                    self.weights = np.array(data["weights"])
                    self.bias = data["bias"]

                if "snapshot_model" in data:
                    sm = data["snapshot_model"]
                    self.snapshot_weights = np.array(sm["weights"])
                    self.snapshot_bias = sm["bias"]

                if "fast_model" in data:
                    fm = data["fast_model"]
                    self.fast_weights = np.array(fm["weights"])
                    self.fast_bias = fm["bias"]

                n_trade = len(self.weights) if self.weights is not None else 0
                n_snap = len(self.snapshot_weights) if self.snapshot_weights is not None else 0
                n_fast = len(self.fast_weights) if self.fast_weights is not None else 0
                logger.info(f"Loaded ML models: trade={n_trade}f, snapshot={n_snap}f, fast={n_fast}f")
            except Exception as e:
                logger.warning(f"Failed to load ML model: {e}")

    def _save_model(self):
        try:
            data = {"trained_at": datetime.now(timezone.utc).isoformat()}
            if self.weights is not None:
                data["trade_model"] = {
                    "weights": self.weights.tolist(),
                    "bias": self.bias,
                    "feature_names": self._feature_names(),
                }
            if self.snapshot_weights is not None:
                data["snapshot_model"] = {
                    "weights": self.snapshot_weights.tolist(),
                    "bias": self.snapshot_bias,
                    "feature_names": self._snapshot_feature_names(),
                }
            if self.fast_weights is not None:
                data["fast_model"] = {
                    "weights": self.fast_weights.tolist(),
                    "bias": self.fast_bias,
                    "feature_names": self._snapshot_feature_names(),
                }
            data["num_trade_samples"] = len(self.outcomes)
            data["num_snapshot_samples"] = len(self.snapshots)
            with open(self.model_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save model: {e}")

    def _load_strategy_stats(self) -> Dict[str, Dict]:
        if self.stats_path.exists():
            try:
                with open(self.stats_path) as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_strategy_stats(self):
        try:
            with open(self.stats_path, "w") as f:
                json.dump(self.strategy_stats, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save strategy stats: {e}")

    # ─── Feature engineering ─────────────────────────────────────────

    def _feature_names(self) -> List[str]:
        return [
            "confidence", "regime_score", "vwap_aligned", "ema_aligned",
            "stop_width_ratio", "hour_sin", "hour_cos", "day_sin", "day_cos",
            "leverage", "is_buy", "price_change_1h", "price_change_24h",
            "volume_ratio", "volatility", "num_agree",
        ]

    def _featurize(self, outcome: TradeOutcome) -> np.ndarray:
        """Convert a trade outcome into a feature vector with cyclical time encoding."""
        hour_rad = 2 * np.pi * outcome.hour_of_day / 24.0
        day_rad = 2 * np.pi * outcome.day_of_week / 7.0

        return np.array([
            outcome.confidence / 100.0,
            outcome.regime_score / 4.0,
            1.0 if outcome.vwap_aligned else 0.0,
            1.0 if outcome.ema_aligned else 0.0,
            min(outcome.stop_width_ratio, 3.0) / 3.0,
            np.sin(hour_rad),      # cyclical hour encoding
            np.cos(hour_rad),
            np.sin(day_rad),       # cyclical day encoding
            np.cos(day_rad),
            outcome.leverage / 25.0,
            1.0 if outcome.side == "BUY" else 0.0,
            np.clip(outcome.price_change_1h_pct / 5.0, -1, 1),   # normalize
            np.clip(outcome.price_change_24h_pct / 10.0, -1, 1),
            np.clip(outcome.volume_ratio / 3.0, 0, 1),
            np.clip(outcome.volatility / 5.0, 0, 1),
            outcome.num_strategies_agree / 4.0,
        ], dtype=np.float64)

    # ─── Snapshot feature engineering ─────────────────────────────────

    def _snapshot_feature_names(self) -> List[str]:
        return [
            "price_change_1h", "price_change_24h", "volume_ratio",
            "volatility", "hour_sin", "hour_cos",
            "regime_score", "ensemble_buy", "ensemble_confidence",
        ]

    def _featurize_snapshot(self, snap: MarketSnapshot) -> np.ndarray:
        """Convert a market snapshot into a feature vector for direction prediction."""
        try:
            ts = datetime.fromisoformat(snap.timestamp)
            hour = ts.hour
        except Exception:
            hour = 12
        hour_rad = 2 * np.pi * hour / 24.0

        return np.array([
            np.clip(snap.price_change_1h_pct / 5.0, -1, 1),
            np.clip(snap.price_change_24h_pct / 10.0, -1, 1),
            np.clip(snap.volume_ratio / 3.0, 0, 1),
            np.clip(snap.volatility / 5.0, 0, 1),
            np.sin(hour_rad),
            np.cos(hour_rad),
            snap.regime_score / 4.0,  # regime: -2 to +2 → -0.5 to +0.5
            1.0 if snap.ensemble_direction == "BUY" else (-1.0 if snap.ensemble_direction == "SELL" else 0.0),
            snap.ensemble_confidence / 100.0,
        ], dtype=np.float64)

    # ─── Recording ───────────────────────────────────────────────────

    def record_outcome(self, outcome: TradeOutcome):
        """Record a completed trade outcome."""
        self.outcomes.append(outcome)
        self._save_outcomes()
        self._samples_since_train += 1

        # Update per-strategy stats
        strat = outcome.strategy
        if strat not in self.strategy_stats:
            self.strategy_stats[strat] = {
                "wins": 0, "losses": 0, "total_pnl": 0.0,
                "recent_results": [],  # last 20 results
            }
        stats = self.strategy_stats[strat]
        stats["wins" if outcome.win else "losses"] += 1
        stats["total_pnl"] += outcome.pnl
        stats["recent_results"].append(1 if outcome.win else 0)
        stats["recent_results"] = stats["recent_results"][-20:]
        self._save_strategy_stats()

        logger.info(
            f"ML recorded: {outcome.symbol} {outcome.side} "
            f"conf={outcome.confidence:.0f}% {'WIN' if outcome.win else 'LOSS'} "
            f"pnl={outcome.pnl:.2f} (total samples: {len(self.outcomes)})"
        )

        # Auto-retrain
        if (
            len(self.outcomes) >= self.min_samples
            and self._samples_since_train >= self.retrain_interval
        ):
            self.train()

    def record_snapshot(self, snapshot: MarketSnapshot):
        """Record a market observation for passive learning."""
        self.snapshots.append(snapshot)

        # Trim in memory to prevent unbounded growth
        if len(self.snapshots) > 2500:
            self.snapshots = self.snapshots[-2000:]

        # Backfill future returns on older snapshots
        self._backfill_returns(snapshot.symbol, snapshot.price)

        # Save periodically (every 50 snapshots)
        if len(self.snapshots) % 50 == 0:
            self._save_snapshots()

        # Auto-train models when enough filled observations exist
        self._snapshots_since_train += 1

        # Fast 5m model: trains early, updates often (every 20 snapshots = ~10 min)
        if self._snapshots_since_train % 20 == 0:
            filled_5m = sum(1 for s in self.snapshots if s.future_return_5m is not None)
            if filled_5m >= 20:
                self._train_fast_model()

        # 1h direction model: trains less frequently (every 100 snapshots)
        if self._snapshots_since_train >= 100:
            filled = sum(1 for s in self.snapshots if s.future_return_1h is not None)
            if filled >= 30:
                self.train_from_snapshots()
                self._snapshots_since_train = 0

    def _backfill_returns(self, symbol: str, current_price: float):
        """Fill in future returns for past snapshots of same symbol."""
        now = time.time()
        for snap in reversed(self.snapshots[-200:]):
            if snap.symbol != symbol:
                continue
            # Only break when ALL return windows are filled
            if snap.future_return_1h is not None:
                break  # fully filled, everything older is too

            snap_time = datetime.fromisoformat(snap.timestamp).timestamp()
            age_min = (now - snap_time) / 60.0
            ret = (current_price - snap.price) / snap.price * 100.0

            if age_min >= 5 and snap.future_return_5m is None:
                snap.future_return_5m = ret
            if age_min >= 15 and snap.future_return_15m is None:
                snap.future_return_15m = ret
            if age_min >= 60 and snap.future_return_1h is None:
                snap.future_return_1h = ret

    # ─── Training ────────────────────────────────────────────────────

    def train(self):
        """Train logistic regression on all recorded outcomes."""
        if len(self.outcomes) < self.min_samples:
            logger.info(f"Need {self.min_samples} samples, have {len(self.outcomes)}")
            return

        X = np.array([self._featurize(o) for o in self.outcomes])
        y = np.array([1.0 if o.win else 0.0 for o in self.outcomes])

        n_features = X.shape[1]
        if self.weights is None or len(self.weights) != n_features:
            self.weights = np.zeros(n_features)
            self.bias = 0.0

        # Mini-batch gradient descent with momentum
        lr = 0.01
        momentum = 0.9
        v_w = np.zeros_like(self.weights)
        v_b = 0.0

        # More epochs for small datasets, fewer for large
        epochs = max(50, min(300, 3000 // len(self.outcomes)))

        for _ in range(epochs):
            z = X @ self.weights + self.bias
            pred = 1.0 / (1.0 + np.exp(-np.clip(z, -500, 500)))
            error = pred - y

            # L2 regularization to prevent overfitting
            reg = 0.001
            grad_w = (X.T @ error) / len(y) + reg * self.weights
            grad_b = error.mean()

            v_w = momentum * v_w - lr * grad_w
            v_b = momentum * v_b - lr * grad_b
            self.weights += v_w
            self.bias += v_b

        self._samples_since_train = 0
        self._save_model()

        # Log accuracy
        z = X @ self.weights + self.bias
        pred_prob = 1.0 / (1.0 + np.exp(-np.clip(z, -500, 500)))
        pred = pred_prob > 0.5
        accuracy = (pred == y).mean()
        baseline = max(y.mean(), 1 - y.mean())

        logger.info(
            f"ML trained on {len(self.outcomes)} samples | "
            f"Accuracy: {accuracy:.1%} | Baseline: {baseline:.1%} | "
            f"Improvement: {accuracy - baseline:+.1%}"
        )

        # Log feature importances
        feature_names = self._feature_names()
        importances = sorted(
            zip(feature_names, self.weights),
            key=lambda x: abs(x[1]), reverse=True
        )
        top5 = ", ".join(f"{n}={w:+.3f}" for n, w in importances[:5])
        logger.info(f"Top features: {top5}")

    # ─── Snapshot-based training ─────────────────────────────────────

    def train_from_snapshots(self):
        """Train a direction model from market snapshots with filled future returns.
        This gives learning data from hour 1, without waiting for trades to close."""
        filled = [s for s in self.snapshots if s.future_return_1h is not None]
        if len(filled) < 30:
            return

        X = np.array([self._featurize_snapshot(s) for s in filled])
        y = np.array([1.0 if s.future_return_1h > 0 else 0.0 for s in filled])

        n_features = X.shape[1]
        if self.snapshot_weights is None or len(self.snapshot_weights) != n_features:
            self.snapshot_weights = np.zeros(n_features)
            self.snapshot_bias = 0.0

        # Gradient descent with momentum (same approach as trade model)
        lr = 0.01
        momentum = 0.9
        v_w = np.zeros_like(self.snapshot_weights)
        v_b = 0.0
        epochs = max(50, min(200, 2000 // len(filled)))

        for _ in range(epochs):
            z = X @ self.snapshot_weights + self.snapshot_bias
            pred = 1.0 / (1.0 + np.exp(-np.clip(z, -500, 500)))
            error = pred - y

            reg = 0.001
            grad_w = (X.T @ error) / len(y) + reg * self.snapshot_weights
            grad_b = error.mean()

            v_w = momentum * v_w - lr * grad_w
            v_b = momentum * v_b - lr * grad_b
            self.snapshot_weights += v_w
            self.snapshot_bias += v_b

        self._save_model()

        # Log accuracy
        z = X @ self.snapshot_weights + self.snapshot_bias
        pred_prob = 1.0 / (1.0 + np.exp(-np.clip(z, -500, 500)))
        pred_labels = pred_prob > 0.5
        accuracy = (pred_labels == y).mean()
        baseline = max(y.mean(), 1 - y.mean())

        # Log feature importances for snapshot model
        feature_names = self._snapshot_feature_names()
        importances = sorted(
            zip(feature_names, self.snapshot_weights),
            key=lambda x: abs(x[1]), reverse=True
        )
        top = ", ".join(f"{n}={w:+.3f}" for n, w in importances[:4])

        logger.info(
            f"Snapshot model trained on {len(filled)} observations | "
            f"Direction accuracy: {accuracy:.1%} (baseline {baseline:.1%}) | "
            f"Top: {top}"
        )

    def _train_fast_model(self):
        """Train a fast 5-minute direction model for quick feedback.
        Starts learning ~10 min after boot instead of 60+ min for the 1h model."""
        filled = [s for s in self.snapshots if s.future_return_5m is not None]
        if len(filled) < 20:
            return

        X = np.array([self._featurize_snapshot(s) for s in filled])
        y = np.array([1.0 if s.future_return_5m > 0 else 0.0 for s in filled])

        n_features = X.shape[1]
        if self.fast_weights is None or len(self.fast_weights) != n_features:
            self.fast_weights = np.zeros(n_features)
            self.fast_bias = 0.0

        lr = 0.01
        momentum = 0.9
        v_w = np.zeros_like(self.fast_weights)
        v_b = 0.0
        epochs = max(30, min(150, 1000 // len(filled)))

        for _ in range(epochs):
            z = X @ self.fast_weights + self.fast_bias
            pred = 1.0 / (1.0 + np.exp(-np.clip(z, -500, 500)))
            error = pred - y
            reg = 0.001
            grad_w = (X.T @ error) / len(y) + reg * self.fast_weights
            grad_b = error.mean()
            v_w = momentum * v_w - lr * grad_w
            v_b = momentum * v_b - lr * grad_b
            self.fast_weights += v_w
            self.fast_bias += v_b

        self._save_model()

        z = X @ self.fast_weights + self.fast_bias
        pred_prob = 1.0 / (1.0 + np.exp(-np.clip(z, -500, 500)))
        accuracy = ((pred_prob > 0.5) == y).mean()
        baseline = max(y.mean(), 1 - y.mean())

        logger.info(
            f"Fast 5m model trained on {len(filled)} samples | "
            f"Accuracy: {accuracy:.1%} (baseline {baseline:.1%})"
        )

    def predict_direction(
        self,
        price_change_1h_pct: float = 0.0,
        price_change_24h_pct: float = 0.0,
        volume_ratio: float = 1.0,
        volatility: float = 0.0,
        regime_score: float = 0.0,
        ensemble_direction: str = "",
        ensemble_confidence: float = 0.0,
    ) -> Optional[float]:
        """Predict probability of upward price movement from market conditions.
        Returns float between 0 and 1, or None if no model available."""
        if self.snapshot_weights is None:
            return None

        snap = MarketSnapshot(
            symbol="", price=0,
            price_change_1h_pct=price_change_1h_pct,
            price_change_24h_pct=price_change_24h_pct,
            volume_ratio=volume_ratio,
            volatility=volatility,
            regime_score=regime_score,
            ensemble_direction=ensemble_direction,
            ensemble_confidence=ensemble_confidence,
        )
        x = self._featurize_snapshot(snap)
        if len(self.snapshot_weights) != len(x):
            return None

        z = float(x @ self.snapshot_weights + self.snapshot_bias)
        return float(1.0 / (1.0 + np.exp(-np.clip(z, -500, 500))))

    def _predict_fast(
        self,
        price_change_1h_pct: float = 0.0,
        price_change_24h_pct: float = 0.0,
        volume_ratio: float = 1.0,
        volatility: float = 0.0,
    ) -> Optional[float]:
        """Quick 5m direction prediction. Available ~10 min after boot."""
        if self.fast_weights is None:
            return None
        snap = MarketSnapshot(
            symbol="", price=0,
            price_change_1h_pct=price_change_1h_pct,
            price_change_24h_pct=price_change_24h_pct,
            volume_ratio=volume_ratio,
            volatility=volatility,
        )
        x = self._featurize_snapshot(snap)
        if len(self.fast_weights) != len(x):
            return None
        z = float(x @ self.fast_weights + self.fast_bias)
        return float(1.0 / (1.0 + np.exp(-np.clip(z, -500, 500))))

    # ─── Prediction ──────────────────────────────────────────────────

    def predict_win_probability(
        self,
        confidence: float,
        regime_score: float = 0,
        vwap_aligned: bool = False,
        ema_aligned: bool = False,
        stop_width_ratio: float = 1.5,
        leverage: float = 1.0,
        side: str = "BUY",
        price_change_1h_pct: float = 0.0,
        price_change_24h_pct: float = 0.0,
        volume_ratio: float = 1.0,
        volatility: float = 0.0,
        num_strategies_agree: int = 1,
    ) -> Optional[float]:
        """Predict win probability for a signal."""
        if self.weights is None:
            return None

        now = datetime.now(timezone.utc)
        dummy = TradeOutcome(
            symbol="", strategy="", side=side,
            confidence=confidence,
            regime_score=regime_score,
            vwap_aligned=vwap_aligned,
            ema_aligned=ema_aligned,
            stop_width_ratio=stop_width_ratio,
            hour_of_day=now.hour,
            day_of_week=now.weekday(),
            leverage=leverage,
            price_change_1h_pct=price_change_1h_pct,
            price_change_24h_pct=price_change_24h_pct,
            volume_ratio=volume_ratio,
            volatility=volatility,
            num_strategies_agree=num_strategies_agree,
        )
        x = self._featurize(dummy)

        # Handle feature count mismatch (model was trained with different features)
        if len(self.weights) != len(x):
            logger.warning(f"ML feature mismatch: model has {len(self.weights)} weights, input has {len(x)} features. Retraining needed.")
            return None

        z = float(x @ self.weights + self.bias)
        return float(1.0 / (1.0 + np.exp(-np.clip(z, -500, 500))))

    def adjust_confidence(
        self,
        original_confidence: float,
        regime_score: float = 0,
        vwap_aligned: bool = False,
        ema_aligned: bool = False,
        stop_width_ratio: float = 1.5,
        leverage: float = 1.0,
        side: str = "BUY",
        price_change_1h_pct: float = 0.0,
        price_change_24h_pct: float = 0.0,
        volume_ratio: float = 1.0,
        volatility: float = 0.0,
        num_strategies_agree: int = 1,
    ) -> float:
        """Adjust signal confidence by blending trade model + snapshot direction model."""
        # Trade model: predict win probability from signal features
        win_prob = self.predict_win_probability(
            original_confidence, regime_score, vwap_aligned,
            ema_aligned, stop_width_ratio, leverage, side,
            price_change_1h_pct, price_change_24h_pct,
            volume_ratio, volatility, num_strategies_agree,
        )

        # Snapshot model: predict market direction from conditions
        direction_prob = self.predict_direction(
            price_change_1h_pct, price_change_24h_pct,
            volume_ratio, volatility,
        )
        # For SELL signals, invert (we want prob of price moving in our favor)
        if direction_prob is not None and side == "SELL":
            direction_prob = 1.0 - direction_prob

        # Fast 5m model as fallback when 1h model isn't ready
        fast_prob = self._predict_fast(
            price_change_1h_pct, price_change_24h_pct,
            volume_ratio, volatility,
        )
        if fast_prob is not None and side == "SELL":
            fast_prob = 1.0 - fast_prob

        # Blend available models (trade > 1h snapshot > 5m fast)
        if win_prob is not None and direction_prob is not None:
            combined = win_prob * 0.6 + direction_prob * 0.4
            source = f"trade={win_prob:.1%}+snap={direction_prob:.1%}"
        elif win_prob is not None:
            combined = win_prob
            source = f"trade={win_prob:.1%}"
        elif direction_prob is not None:
            combined = direction_prob
            source = f"snap={direction_prob:.1%}"
        elif fast_prob is not None:
            combined = fast_prob
            source = f"fast5m={fast_prob:.1%}"
        else:
            return original_confidence

        ml_confidence = combined * 100.0
        adjusted = (
            original_confidence * (1 - self.adjustment_weight)
            + ml_confidence * self.adjustment_weight
        )
        adjusted = max(0, min(100, adjusted))

        if abs(adjusted - original_confidence) > 2:
            logger.info(
                f"ML adjustment: {original_confidence:.0f}% -> {adjusted:.0f}% "
                f"({source})"
            )

        return adjusted

    # ─── Strategy performance tracking ───────────────────────────────

    def get_strategy_win_rate(self, strategy_name: str, window: int = 20) -> Optional[float]:
        """Get rolling win rate for a strategy over last N trades."""
        stats = self.strategy_stats.get(strategy_name)
        if not stats or not stats.get("recent_results"):
            return None
        recent = stats["recent_results"][-window:]
        if len(recent) < 3:
            return None
        return sum(recent) / len(recent)

    def get_strategy_weights(self) -> Dict[str, float]:
        """Get recommended ensemble weights based on observed performance."""
        weights = {}
        for strat, stats in self.strategy_stats.items():
            recent = stats.get("recent_results", [])
            if len(recent) >= 5:
                wr = sum(recent[-10:]) / len(recent[-10:])
                # Weight = 0.5 + win_rate, clamped to [0.2, 2.0]
                weights[strat] = max(0.2, min(2.0, 0.5 + wr))
            else:
                weights[strat] = 1.0
        return weights

    # ─── Reporting ───────────────────────────────────────────────────

    def get_performance_report(self) -> Dict[str, Any]:
        """Generate performance report from all recorded outcomes."""
        if not self.outcomes:
            return {"total_trades": 0, "status": "no data"}

        total = len(self.outcomes)
        wins = sum(1 for o in self.outcomes if o.win)
        total_pnl = sum(o.pnl for o in self.outcomes)

        by_strategy = {}
        for o in self.outcomes:
            if o.strategy not in by_strategy:
                by_strategy[o.strategy] = {"wins": 0, "losses": 0, "pnl": 0.0}
            s = by_strategy[o.strategy]
            if o.win:
                s["wins"] += 1
            else:
                s["losses"] += 1
            s["pnl"] += o.pnl

        by_symbol = {}
        for o in self.outcomes:
            if o.symbol not in by_symbol:
                by_symbol[o.symbol] = {"wins": 0, "losses": 0, "pnl": 0.0}
            s = by_symbol[o.symbol]
            if o.win:
                s["wins"] += 1
            else:
                s["losses"] += 1
            s["pnl"] += o.pnl

        # Snapshot learning stats
        filled = sum(1 for s in self.snapshots if s.future_return_1h is not None)

        return {
            "total_trades": total,
            "wins": wins,
            "losses": total - wins,
            "win_rate": wins / total if total else 0,
            "total_pnl": total_pnl,
            "trade_model_trained": self.weights is not None,
            "trade_model_features": len(self.weights) if self.weights is not None else 0,
            "snapshot_model_trained": self.snapshot_weights is not None,
            "snapshot_model_features": len(self.snapshot_weights) if self.snapshot_weights is not None else 0,
            "market_snapshots": len(self.snapshots),
            "snapshots_with_returns": filled,
            "by_strategy": by_strategy,
            "by_symbol": by_symbol,
            "strategy_weights": self.get_strategy_weights(),
        }
