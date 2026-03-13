"""
Confidence Calibration Loop

Tracks the relationship between claimed confidence and actual outcomes,
then applies a calibration correction to prevent systematic over/under-confidence.

Problem: LLMs are notoriously overconfident. When the Trade Agent says 85% confidence,
the actual win rate might only be 55%. This creates bad position sizing.

Solution: Build a calibration curve from historical data, then deflate/inflate
confidence values before they reach the ensemble and position sizing.

The calibration is:
1. Bin historical trades by confidence level (50-60, 60-70, 70-80, 80-90, 90-100)
2. For each bin, compute actual win rate
3. Use isotonic regression (or simple mapping) to build a calibration function
4. Apply calibration to new confidence values: raw_conf → calibrated_conf

Storage: bot/data/llm/calibration_curve.json
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("bot.llm.confidence_calibrator")


class ConfidenceCalibrator:
    """
    Calibrates agent confidence against actual outcomes.

    Tracks claimed confidence vs actual win rate, builds a calibration curve,
    and adjusts new confidence values to match observed reliability.
    """

    # Calibration bins: 5-point width for finer resolution.
    # 10-point bins create false precision (everything in 70-80 maps to midpoint 75).
    BINS = [
        (50, 55), (55, 60), (60, 65), (65, 70), (70, 75),
        (75, 80), (80, 85), (85, 90), (90, 95), (95, 100),
    ]

    # Minimum samples per bin before calibration is applied.
    # Raised from 5 to 8 to compensate for thinner bins.
    MIN_SAMPLES_PER_BIN = 8

    # Smoothing: blend calibrated value with raw value (prevents overcorrection)
    # 0.0 = fully raw, 1.0 = fully calibrated
    CALIBRATION_STRENGTH = 0.7

    # Maximum adjustment per calibration step
    MAX_ADJUSTMENT_PCT = 15.0  # Don't shift confidence by more than 15 points

    def __init__(self, data_dir: str = "data/llm"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.curve_file = self.data_dir / "calibration_curve.json"
        self.observations_file = self.data_dir / "calibration_observations.jsonl"

        # In-memory calibration curve
        self._curve: Dict[str, Dict] = {}  # bin_key → {claimed_mid, actual_win_rate, n}
        self._observations: List[Dict] = []
        self._load()

    def _load(self):
        """Load calibration curve and recent observations."""
        if self.curve_file.exists():
            try:
                with open(self.curve_file, "r") as f:
                    self._curve = json.load(f)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Failed to load calibration curve: {e}")
                self._curve = {}

        if self.observations_file.exists():
            try:
                with open(self.observations_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            self._observations.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                logger.warning(f"Failed to load calibration observations: {e}")

    def _save_curve(self):
        """Save the calibration curve."""
        try:
            with open(self.curve_file, "w") as f:
                json.dump(self._curve, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save calibration curve: {e}")

    def _get_bin_key(self, confidence: float) -> str:
        """Get the bin key for a confidence value."""
        for low, high in self.BINS:
            if low <= confidence < high:
                return f"{low}-{high}"
        if confidence >= 100:
            return "90-100"
        return "50-60"

    def record_observation(self, claimed_confidence: float, was_correct: bool,
                            agent: str = "system", symbol: str = "",
                            regime: str = "", pnl_pct: float = 0.0):
        """Record a single confidence → outcome observation."""
        obs = {
            "confidence": claimed_confidence,
            "correct": was_correct,
            "agent": agent,
            "symbol": symbol,
            "regime": regime,
            "pnl_pct": pnl_pct,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._observations.append(obs)

        # Append to file
        try:
            with open(self.observations_file, "a") as f:
                f.write(json.dumps(obs) + "\n")
        except Exception as e:
            logger.error(f"Failed to save calibration observation: {e}")

        # Rebuild curve periodically (every 10 observations)
        if len(self._observations) % 10 == 0:
            self.rebuild_curve()

    def rebuild_curve(self, lookback_days: int = 30):
        """Rebuild the calibration curve from recent observations."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
        recent = [o for o in self._observations if o.get("timestamp", "") >= cutoff]

        if len(recent) < self.MIN_SAMPLES_PER_BIN * 2:
            return  # Not enough data

        # Bin observations
        bins: Dict[str, List[Dict]] = {f"{lo}-{hi}": [] for lo, hi in self.BINS}
        for obs in recent:
            key = self._get_bin_key(obs["confidence"])
            if key in bins:
                bins[key].append(obs)

        # Compute actual win rate per bin
        new_curve = {}
        for bin_key, observations in bins.items():
            if len(observations) < self.MIN_SAMPLES_PER_BIN:
                continue

            correct_count = sum(1 for o in observations if o["correct"])
            total = len(observations)
            actual_wr = correct_count / total

            # Bin midpoint (what the agent "claims")
            parts = bin_key.split("-")
            claimed_mid = (int(parts[0]) + int(parts[1])) / 2.0

            new_curve[bin_key] = {
                "claimed_mid": claimed_mid,
                "actual_win_rate": actual_wr,
                "n": total,
                "correct": correct_count,
                "adjustment": (actual_wr * 100) - claimed_mid,
                "updated": datetime.now(timezone.utc).isoformat(),
            }

        # Apply isotonic regression (pool-adjacent-violators) to ensure
        # monotonically non-decreasing calibration curve. Higher claimed
        # confidence should always map to higher actual win rate.
        if len(new_curve) >= 2:
            sorted_keys = sorted(new_curve.keys(), key=lambda k: int(k.split("-")[0]))
            win_rates = [new_curve[k]["actual_win_rate"] for k in sorted_keys]
            weights = [new_curve[k]["n"] for k in sorted_keys]
            isotonic_wr = self._isotonic_regression(win_rates, weights)
            for i, k in enumerate(sorted_keys):
                new_curve[k]["actual_win_rate_raw"] = new_curve[k]["actual_win_rate"]
                new_curve[k]["actual_win_rate"] = isotonic_wr[i]
                new_curve[k]["adjustment"] = (isotonic_wr[i] * 100) - new_curve[k]["claimed_mid"]

        if new_curve:
            self._curve = new_curve
            self._save_curve()
            logger.info(f"Rebuilt calibration curve from {len(recent)} observations, "
                        f"{len(new_curve)} bins active (isotonic={len(new_curve) >= 2})")

    @staticmethod
    def _isotonic_regression(values, weights=None):
        """Pool-adjacent-violators algorithm for isotonic (monotone non-decreasing) regression.

        Ensures that higher bins always have >= win rate of lower bins.
        Standard calibration technique used in Platt scaling and reliability diagrams.
        """
        n = len(values)
        if n <= 1:
            return list(values)
        if weights is None:
            weights = [1] * n
        # Make mutable copies
        result = list(values)
        w = list(weights)
        i = 0
        while i < n - 1:
            if result[i] > result[i + 1]:
                # Pool adjacent violators: merge i and i+1
                total_w = w[i] + w[i + 1]
                result[i] = (result[i] * w[i] + result[i + 1] * w[i + 1]) / total_w
                result[i + 1] = result[i]
                w[i] = total_w
                w[i + 1] = total_w
                # Check backwards
                while i > 0 and result[i - 1] > result[i]:
                    total_w = w[i - 1] + w[i]
                    result[i - 1] = (result[i - 1] * w[i - 1] + result[i] * w[i]) / total_w
                    result[i] = result[i - 1]
                    w[i - 1] = total_w
                    w[i] = total_w
                    i -= 1
            i += 1
        return result

    def calibrate(self, raw_confidence: float, agent: str = "system") -> float:
        """
        Apply calibration to a raw confidence value.

        Returns the calibrated confidence. If insufficient calibration data,
        returns the raw value unchanged.
        """
        if not self._curve:
            return raw_confidence

        bin_key = self._get_bin_key(raw_confidence)
        bin_data = self._curve.get(bin_key)

        if bin_data is None or bin_data["n"] < self.MIN_SAMPLES_PER_BIN:
            return raw_confidence

        # The actual win rate for this confidence bin
        actual_wr = bin_data["actual_win_rate"]
        calibrated = actual_wr * 100.0  # Convert to 0-100 scale

        # Apply strength blending
        blended = (self.CALIBRATION_STRENGTH * calibrated +
                    (1 - self.CALIBRATION_STRENGTH) * raw_confidence)

        # Cap adjustment
        adjustment = blended - raw_confidence
        if abs(adjustment) > self.MAX_ADJUSTMENT_PCT:
            adjustment = self.MAX_ADJUSTMENT_PCT if adjustment > 0 else -self.MAX_ADJUSTMENT_PCT
            blended = raw_confidence + adjustment

        # Clamp to valid range
        result = max(10.0, min(99.0, blended))

        if abs(result - raw_confidence) > 3.0:
            logger.debug(f"Calibrated confidence: {raw_confidence:.0f}% → {result:.0f}% "
                         f"(bin={bin_key}, actual_wr={actual_wr:.0%}, n={bin_data['n']})")

        return result

    def get_calibration_summary(self) -> Dict[str, Any]:
        """Get a summary of the current calibration state."""
        summary = {
            "total_observations": len(self._observations),
            "bins": {},
            "overall_bias": None,
        }

        total_claimed = 0.0
        total_actual = 0.0
        total_n = 0

        for bin_key, data in self._curve.items():
            summary["bins"][bin_key] = {
                "claimed_mid": data["claimed_mid"],
                "actual_wr": data["actual_win_rate"],
                "n": data["n"],
                "adjustment": data["adjustment"],
                "status": "overconfident" if data["adjustment"] < -5 else
                          "underconfident" if data["adjustment"] > 5 else "calibrated",
            }
            total_claimed += data["claimed_mid"] * data["n"]
            total_actual += data["actual_win_rate"] * 100 * data["n"]
            total_n += data["n"]

        if total_n > 0:
            avg_claimed = total_claimed / total_n
            avg_actual = total_actual / total_n
            summary["overall_bias"] = {
                "avg_claimed": avg_claimed,
                "avg_actual": avg_actual,
                "bias": avg_actual - avg_claimed,
                "direction": "overconfident" if avg_actual < avg_claimed else "underconfident",
            }

        return summary

    def get_prompt_context(self) -> str:
        """Generate context for agent prompts about calibration."""
        summary = self.get_calibration_summary()
        if summary["total_observations"] < 20:
            return ""

        lines = ["CONFIDENCE CALIBRATION:"]
        bias = summary.get("overall_bias")
        if bias:
            if abs(bias["bias"]) > 5:
                lines.append(f"  You are {bias['direction']}: avg claimed={bias['avg_claimed']:.0f}%, "
                             f"actual={bias['avg_actual']:.0f}%")
            else:
                lines.append(f"  Calibration is good: avg claimed={bias['avg_claimed']:.0f}%, "
                             f"actual={bias['avg_actual']:.0f}%")

        for bin_key, data in summary.get("bins", {}).items():
            if data["n"] >= self.MIN_SAMPLES_PER_BIN:
                if data["status"] == "overconfident":
                    lines.append(f"  {bin_key}% confidence → only {data['actual_wr']*100:.0f}% actual "
                                 f"(OVERCONFIDENT, n={data['n']})")
                elif data["status"] == "underconfident":
                    lines.append(f"  {bin_key}% confidence → {data['actual_wr']*100:.0f}% actual "
                                 f"(underconfident, n={data['n']})")

        return "\n".join(lines)
