"""
Confidence Calibration System

Tracks the relationship between claimed confidence and actual outcomes,
then applies a calibration correction to prevent systematic over/under-confidence.

Problem: Backtest shows 90-100% confidence signals are LOSING while 70-79% is
the sweet spot. The confidence scores from the ensemble are not well-calibrated.

Solution:
1. Track actual win rates per confidence band (10-point bands)
2. Per-symbol calibration (BTC at 80% != SOL at 80%)
3. Apply EWMA-weighted calibration curve (recent trades weighted more)
4. Feed calibrated confidence into sizing BEFORE confidence-based sizing
5. Bootstrap from backtest data (backtest_trades_30d.csv)

Storage: bot/data/llm/calibration_curve.json
"""

import csv
import json
import logging
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("bot.llm.confidence_calibrator")


class ConfidenceCalibrator:
    """
    Calibrates ensemble confidence against actual outcomes.

    Tracks claimed confidence vs actual win rate per band and per symbol,
    builds a calibration curve using EWMA, and adjusts new confidence
    values to match observed reliability.
    """

    # Calibration bins (confidence % ranges)
    BINS = [(50, 60), (60, 70), (70, 80), (80, 90), (90, 100)]

    # Minimum samples per bin before calibration is applied
    MIN_SAMPLES_PER_BIN = 5

    # Smoothing: blend calibrated value with raw value (prevents overcorrection)
    # 0.0 = fully raw, 1.0 = fully calibrated
    CALIBRATION_STRENGTH = 0.7

    # Maximum adjustment per calibration step (points)
    MAX_ADJUSTMENT_PCT = 20.0

    # EWMA decay factor: higher = more weight on recent trades
    # 0.95 means each older trade is weighted 0.95x the next newer trade
    EWMA_DECAY = 0.95

    def __init__(self, data_dir: str = "data/llm", calibration_window: int = 50):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.curve_file = self.data_dir / "calibration_curve.json"
        self.observations_file = self.data_dir / "calibration_observations.jsonl"
        self.calibration_window = calibration_window

        # In-memory calibration curves
        # "global" key for system-wide, symbol keys for per-symbol
        self._curve: Dict[str, Dict[str, Dict]] = {}  # scope → bin_key → data
        self._observations: List[Dict] = []
        self._bootstrapped = False
        self._load()

    def _load(self):
        """Load calibration curve and recent observations."""
        if self.curve_file.exists():
            try:
                with open(self.curve_file, "r") as f:
                    data = json.load(f)
                # Handle both old format (flat) and new format (nested by scope)
                if data and isinstance(next(iter(data.values()), None), dict):
                    first_val = next(iter(data.values()))
                    if "claimed_mid" in first_val:
                        # Old flat format — migrate to new nested format
                        self._curve = {"global": data}
                    else:
                        self._curve = data
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

    def _normalize_symbol(self, symbol: str) -> str:
        """Normalize symbol name to base (BTC, SOL, etc.)."""
        if not symbol:
            return ""
        return (symbol.replace("/USDC:USDC", "")
                .replace("/USDT:USDT", "")
                .replace("/USD", "")
                .strip())

    def record_observation(self, claimed_confidence: float, was_correct: bool,
                           agent: str = "system", symbol: str = "",
                           regime: str = "", pnl_pct: float = 0.0):
        """Record a single confidence -> outcome observation."""
        obs = {
            "confidence": claimed_confidence,
            "correct": was_correct,
            "agent": agent,
            "symbol": self._normalize_symbol(symbol),
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

    def bootstrap_from_backtest(self, csv_path: str = "data/backtest_trades_30d.csv"):
        """Pre-seed calibration data from backtest results.

        Reads the backtest CSV and creates observations from historical trades.
        Only runs once (idempotent via _bootstrapped flag).
        """
        if self._bootstrapped:
            return

        csv_file = Path(csv_path)
        if not csv_file.exists():
            logger.info(f"No backtest file at {csv_path}, skipping bootstrap")
            return

        try:
            added = 0
            with open(csv_file, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        confidence = float(row.get("confidence", 0))
                        if confidence < 50:
                            continue

                        outcome = row.get("outcome", "").upper()
                        was_correct = outcome == "WIN"
                        symbol = self._normalize_symbol(row.get("symbol", ""))
                        pnl = float(row.get("pnl", 0))

                        # Add as observation without writing to file (bulk load)
                        obs = {
                            "confidence": confidence,
                            "correct": was_correct,
                            "agent": "backtest",
                            "symbol": symbol,
                            "regime": row.get("llm_regime", ""),
                            "pnl_pct": pnl,
                            "timestamp": "2026-03-01T00:00:00+00:00",  # backtest epoch
                        }
                        self._observations.append(obs)
                        added += 1
                    except (ValueError, KeyError):
                        continue

            if added > 0:
                logger.info(f"Bootstrapped {added} observations from {csv_path}")
                self.rebuild_curve()
                self._bootstrapped = True

        except Exception as e:
            logger.warning(f"Failed to bootstrap from backtest: {e}")

    def _compute_ewma_win_rate(self, observations: List[Dict]) -> float:
        """Compute EWMA-weighted win rate (recent trades weighted more).

        Sorts by timestamp descending, applies exponential decay weights.
        """
        if not observations:
            return 0.5

        # Sort by timestamp, most recent first
        sorted_obs = sorted(observations,
                            key=lambda o: o.get("timestamp", ""),
                            reverse=True)

        # Limit to calibration window
        sorted_obs = sorted_obs[:self.calibration_window]

        numerator = 0.0
        denominator = 0.0
        for i, obs in enumerate(sorted_obs):
            weight = self.EWMA_DECAY ** i
            numerator += weight * (1.0 if obs["correct"] else 0.0)
            denominator += weight

        if denominator == 0:
            return 0.5

        return numerator / denominator

    def rebuild_curve(self, lookback_days: int = 60):
        """Rebuild calibration curves from recent observations.

        Builds both a global curve and per-symbol curves.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
        recent = [o for o in self._observations if o.get("timestamp", "") >= cutoff]

        if len(recent) < self.MIN_SAMPLES_PER_BIN * 2:
            return  # Not enough data

        # Build curves for global and per-symbol scopes
        scopes: Dict[str, List[Dict]] = {"global": recent}

        # Group by symbol
        for obs in recent:
            sym = obs.get("symbol", "")
            if sym:
                scopes.setdefault(sym, []).append(obs)

        new_curves: Dict[str, Dict[str, Dict]] = {}

        for scope, scope_obs in scopes.items():
            # Bin observations
            bins: Dict[str, List[Dict]] = {f"{lo}-{hi}": [] for lo, hi in self.BINS}
            for obs in scope_obs:
                key = self._get_bin_key(obs["confidence"])
                if key in bins:
                    bins[key].append(obs)

            # Compute EWMA win rate per bin
            scope_curve = {}
            for bin_key, bin_obs in bins.items():
                if len(bin_obs) < self.MIN_SAMPLES_PER_BIN:
                    continue

                actual_wr = self._compute_ewma_win_rate(bin_obs)

                parts = bin_key.split("-")
                claimed_mid = (int(parts[0]) + int(parts[1])) / 2.0

                scope_curve[bin_key] = {
                    "claimed_mid": claimed_mid,
                    "actual_win_rate": round(actual_wr, 4),
                    "n": len(bin_obs),
                    "correct": sum(1 for o in bin_obs if o["correct"]),
                    "adjustment": round((actual_wr * 100) - claimed_mid, 2),
                    "updated": datetime.now(timezone.utc).isoformat(),
                }

            if scope_curve:
                new_curves[scope] = scope_curve

        if new_curves:
            self._curve = new_curves
            self._save_curve()
            n_scopes = len(new_curves)
            n_global = len(new_curves.get("global", {}))
            logger.info(
                f"Rebuilt calibration curves: {n_scopes} scopes, "
                f"{n_global} global bins, {len(recent)} observations"
            )

    def calibrate(self, raw_confidence: float, symbol: str = "",
                  agent: str = "system") -> float:
        """Apply calibration to a raw confidence value.

        Uses per-symbol curve if available, falls back to global.
        Returns the calibrated confidence. If insufficient data, returns raw.
        """
        if not self._curve:
            return raw_confidence

        norm_symbol = self._normalize_symbol(symbol)
        bin_key = self._get_bin_key(raw_confidence)

        # Try per-symbol curve first, fall back to global
        bin_data = None
        curve_source = "none"
        if norm_symbol and norm_symbol in self._curve:
            bin_data = self._curve[norm_symbol].get(bin_key)
            if bin_data and bin_data["n"] >= self.MIN_SAMPLES_PER_BIN:
                curve_source = norm_symbol
            else:
                bin_data = None

        if bin_data is None and "global" in self._curve:
            bin_data = self._curve["global"].get(bin_key)
            if bin_data and bin_data["n"] >= self.MIN_SAMPLES_PER_BIN:
                curve_source = "global"
            else:
                bin_data = None

        if bin_data is None:
            return raw_confidence

        # The actual EWMA win rate for this confidence bin
        actual_wr = bin_data["actual_win_rate"]
        calibrated = actual_wr * 100.0  # Convert to 0-100 scale

        # Apply strength blending
        blended = (self.CALIBRATION_STRENGTH * calibrated +
                   (1 - self.CALIBRATION_STRENGTH) * raw_confidence)

        # Cap adjustment
        adjustment = blended - raw_confidence
        if abs(adjustment) > self.MAX_ADJUSTMENT_PCT:
            adjustment = (self.MAX_ADJUSTMENT_PCT if adjustment > 0
                          else -self.MAX_ADJUSTMENT_PCT)
            blended = raw_confidence + adjustment

        # Clamp to valid range
        result = max(10.0, min(99.0, blended))

        if abs(result - raw_confidence) > 2.0:
            logger.debug(
                f"Calibrated confidence: {raw_confidence:.0f}% -> {result:.0f}% "
                f"(bin={bin_key}, wr={actual_wr:.0%}, n={bin_data['n']}, "
                f"source={curve_source})"
            )

        return result

    def get_calibration_summary(self) -> Dict[str, Any]:
        """Get a summary of the current calibration state."""
        summary = {
            "total_observations": len(self._observations),
            "scopes": {},
            "overall_bias": None,
        }

        global_curve = self._curve.get("global", {})

        total_claimed = 0.0
        total_actual = 0.0
        total_n = 0

        # Global bins
        global_bins = {}
        for bin_key, data in global_curve.items():
            global_bins[bin_key] = {
                "claimed_mid": data["claimed_mid"],
                "actual_wr": data["actual_win_rate"],
                "n": data["n"],
                "adjustment": data["adjustment"],
                "status": ("overconfident" if data["adjustment"] < -5 else
                           "underconfident" if data["adjustment"] > 5 else
                           "calibrated"),
            }
            total_claimed += data["claimed_mid"] * data["n"]
            total_actual += data["actual_win_rate"] * 100 * data["n"]
            total_n += data["n"]

        summary["scopes"]["global"] = global_bins

        # Per-symbol summaries
        for scope, curve in self._curve.items():
            if scope == "global":
                continue
            scope_bins = {}
            for bin_key, data in curve.items():
                scope_bins[bin_key] = {
                    "claimed_mid": data["claimed_mid"],
                    "actual_wr": data["actual_win_rate"],
                    "n": data["n"],
                    "adjustment": data["adjustment"],
                }
            summary["scopes"][scope] = scope_bins

        if total_n > 0:
            avg_claimed = total_claimed / total_n
            avg_actual = total_actual / total_n
            summary["overall_bias"] = {
                "avg_claimed": round(avg_claimed, 1),
                "avg_actual": round(avg_actual, 1),
                "bias": round(avg_actual - avg_claimed, 1),
                "direction": ("overconfident" if avg_actual < avg_claimed
                              else "underconfident"),
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
                lines.append(
                    f"  You are {bias['direction']}: avg claimed="
                    f"{bias['avg_claimed']:.0f}%, actual={bias['avg_actual']:.0f}%"
                )
            else:
                lines.append(
                    f"  Calibration is good: avg claimed="
                    f"{bias['avg_claimed']:.0f}%, actual={bias['avg_actual']:.0f}%"
                )

        global_bins = summary.get("scopes", {}).get("global", {})
        for bin_key, data in global_bins.items():
            if data["n"] >= self.MIN_SAMPLES_PER_BIN:
                if data["status"] == "overconfident":
                    lines.append(
                        f"  {bin_key}% confidence -> only "
                        f"{data['actual_wr']*100:.0f}% actual "
                        f"(OVERCONFIDENT, n={data['n']})"
                    )
                elif data["status"] == "underconfident":
                    lines.append(
                        f"  {bin_key}% confidence -> "
                        f"{data['actual_wr']*100:.0f}% actual "
                        f"(underconfident, n={data['n']})"
                    )

        # Per-symbol highlights
        for scope, bins in summary.get("scopes", {}).items():
            if scope == "global":
                continue
            for bin_key, data in bins.items():
                if data["n"] >= self.MIN_SAMPLES_PER_BIN and abs(data["adjustment"]) > 10:
                    direction = "over" if data["adjustment"] < 0 else "under"
                    lines.append(
                        f"  {scope} {bin_key}%: {direction}confident by "
                        f"{abs(data['adjustment']):.0f}pts (n={data['n']})"
                    )

        return "\n".join(lines)
