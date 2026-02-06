"""
Self-improving ML system.
Learns from every trade outcome and adjusts signal confidence over time.

Features tracked per trade:
- Strategy that generated the signal
- Original confidence score
- Regime/trend alignment
- VWAP alignment
- EMA alignment
- ATR stop width ratio
- Hour of day, day of week
- Symbol
- Leverage used
- Win/loss outcome
- PnL

After collecting enough samples (default 20), trains a logistic regression
model to predict win probability. Uses predictions to adjust confidence
scores on new signals.
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
    # Signal features
    symbol: str
    strategy: str
    side: str
    confidence: float
    regime_score: float = 0.0
    vwap_aligned: bool = False
    ema_aligned: bool = False
    stop_width_ratio: float = 0.0  # stop_width / ATR
    hour_of_day: int = 0
    day_of_week: int = 0
    leverage: float = 1.0

    # Outcome
    win: bool = False
    pnl: float = 0.0
    hold_time_s: float = 0.0
    exit_action: str = ""  # "TP1", "TP2", "SL", "TRAILING_STOP"

    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SignalLearner:
    """
    ML model that learns from trade outcomes to improve signal confidence.

    Training flow:
    1. Record outcomes from every closed trade
    2. After min_samples trades, train logistic regression
    3. For new signals, predict win probability and adjust confidence
    4. Retrain every retrain_interval new trades
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

        self.min_samples = min_samples
        self.retrain_interval = retrain_interval
        self.adjustment_weight = adjustment_weight

        self.outcomes: List[TradeOutcome] = self._load_outcomes()
        self.weights: Optional[np.ndarray] = None
        self.bias: float = 0.0
        self._samples_since_train = 0

        self._load_model()

    def _load_outcomes(self) -> List[TradeOutcome]:
        if self.outcomes_path.exists():
            try:
                with open(self.outcomes_path) as f:
                    data = json.load(f)
                return [TradeOutcome(**d) for d in data]
            except Exception as e:
                logger.warning(f"Failed to load outcomes: {e}")
        return []

    def _save_outcomes(self):
        try:
            with open(self.outcomes_path, "w") as f:
                json.dump([asdict(o) for o in self.outcomes], f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save outcomes: {e}")

    def _load_model(self):
        if self.model_path.exists():
            try:
                with open(self.model_path) as f:
                    data = json.load(f)
                self.weights = np.array(data["weights"])
                self.bias = data["bias"]
                logger.info(f"Loaded ML model with {len(self.weights)} features")
            except Exception:
                pass

    def _save_model(self):
        if self.weights is not None:
            try:
                with open(self.model_path, "w") as f:
                    json.dump({
                        "weights": self.weights.tolist(),
                        "bias": self.bias,
                        "trained_at": datetime.now(timezone.utc).isoformat(),
                        "num_samples": len(self.outcomes),
                    }, f, indent=2)
            except Exception as e:
                logger.warning(f"Failed to save model: {e}")

    def _featurize(self, outcome: TradeOutcome) -> np.ndarray:
        """Convert a trade outcome into a feature vector."""
        return np.array([
            outcome.confidence / 100.0,
            outcome.regime_score / 4.0,  # normalize to ~[-1, 1]
            1.0 if outcome.vwap_aligned else 0.0,
            1.0 if outcome.ema_aligned else 0.0,
            min(outcome.stop_width_ratio, 3.0) / 3.0,  # normalize
            outcome.hour_of_day / 24.0,
            outcome.day_of_week / 7.0,
            outcome.leverage / 25.0,  # normalize
            1.0 if outcome.side == "BUY" else 0.0,
        ], dtype=np.float64)

    def record_outcome(self, outcome: TradeOutcome):
        """Record a completed trade outcome."""
        self.outcomes.append(outcome)
        self._save_outcomes()
        self._samples_since_train += 1

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

    def train(self):
        """Train logistic regression on all recorded outcomes."""
        if len(self.outcomes) < self.min_samples:
            logger.info(f"Need {self.min_samples} samples, have {len(self.outcomes)}")
            return

        X = np.array([self._featurize(o) for o in self.outcomes])
        y = np.array([1.0 if o.win else 0.0 for o in self.outcomes])

        # Simple online logistic regression via gradient descent
        n_features = X.shape[1]
        if self.weights is None:
            self.weights = np.zeros(n_features)
            self.bias = 0.0

        lr = 0.01
        for _ in range(100):  # epochs
            z = X @ self.weights + self.bias
            pred = 1.0 / (1.0 + np.exp(-np.clip(z, -500, 500)))  # sigmoid
            error = pred - y
            grad_w = (X.T @ error) / len(y)
            grad_b = error.mean()
            self.weights -= lr * grad_w
            self.bias -= lr * grad_b

        self._samples_since_train = 0
        self._save_model()

        # Log accuracy
        z = X @ self.weights + self.bias
        pred = (1.0 / (1.0 + np.exp(-np.clip(z, -500, 500)))) > 0.5
        accuracy = (pred == y).mean()
        baseline = max(y.mean(), 1 - y.mean())
        logger.info(
            f"ML trained on {len(self.outcomes)} samples | "
            f"Accuracy: {accuracy:.1%} | Baseline: {baseline:.1%} | "
            f"Improvement: {accuracy - baseline:+.1%}"
        )

    def predict_win_probability(
        self,
        confidence: float,
        regime_score: float = 0,
        vwap_aligned: bool = False,
        ema_aligned: bool = False,
        stop_width_ratio: float = 1.5,
        leverage: float = 1.0,
        side: str = "BUY",
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
        )
        x = self._featurize(dummy)
        z = float(x @ self.weights + self.bias)
        return 1.0 / (1.0 + np.exp(-np.clip(z, -500, 500)))

    def adjust_confidence(
        self,
        original_confidence: float,
        regime_score: float = 0,
        vwap_aligned: bool = False,
        ema_aligned: bool = False,
        stop_width_ratio: float = 1.5,
        leverage: float = 1.0,
        side: str = "BUY",
    ) -> float:
        """
        Adjust signal confidence based on ML prediction.
        Blends original confidence with ML win probability prediction.
        """
        win_prob = self.predict_win_probability(
            original_confidence, regime_score, vwap_aligned,
            ema_aligned, stop_width_ratio, leverage, side,
        )
        if win_prob is None:
            return original_confidence

        ml_confidence = win_prob * 100.0
        adjusted = (
            original_confidence * (1 - self.adjustment_weight)
            + ml_confidence * self.adjustment_weight
        )
        adjusted = max(0, min(100, adjusted))

        if abs(adjusted - original_confidence) > 2:
            logger.info(
                f"ML adjustment: {original_confidence:.0f}% -> {adjusted:.0f}% "
                f"(win_prob={win_prob:.1%})"
            )

        return adjusted

    def get_performance_report(self) -> Dict[str, Any]:
        """Generate performance report from all recorded outcomes."""
        if not self.outcomes:
            return {"total_trades": 0, "status": "no data"}

        total = len(self.outcomes)
        wins = sum(1 for o in self.outcomes if o.win)
        total_pnl = sum(o.pnl for o in self.outcomes)

        # By strategy
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

        # By symbol
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

        return {
            "total_trades": total,
            "wins": wins,
            "losses": total - wins,
            "win_rate": wins / total if total else 0,
            "total_pnl": total_pnl,
            "model_trained": self.weights is not None,
            "by_strategy": by_strategy,
            "by_symbol": by_symbol,
        }
