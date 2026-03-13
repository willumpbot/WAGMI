"""
Persistent strategy weight manager.
Tracks per-strategy win/trial counts and computes smoothed accuracy weights
with exponential decay for ensemble weighting.

Weight formula: (wins + 1) / (trials + 2)  (Laplace/additive smoothing)
Decay: before each recompute, multiply counts by alpha (0.9) to downweight old data.
Age-weighted mode: when timestamped outcomes exist, uses 14-day half-life
exponential decay so recent trades matter more than old ones.
"""

import json
import logging
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger("bot.weights")


class StrategyWeightManager:
    """Manages persistent strategy accuracy weights for ensemble weighting."""

    def __init__(self, path: str = "ml_data/strategy_weights.json", decay_alpha: float = 0.9):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.decay_alpha = decay_alpha
        self.data: Dict[str, Dict[str, Any]] = self._load()
        self._last_recompute_date: str = ""

    def _load(self) -> Dict[str, Dict[str, Any]]:
        if self.path.exists():
            try:
                with open(self.path) as f:
                    data = json.load(f)
                if data:
                    weights_summary = {
                        name: round((entry.get("wins", 0) + 1) / (entry.get("trials", 0) + 2), 3)
                        for name, entry in data.items()
                    }
                    logger.info(
                        f"[WEIGHTS] Loaded persisted weights from {self.path}: {weights_summary}"
                    )
                else:
                    logger.info(f"[WEIGHTS] Weight file exists but empty, starting fresh")
                return data
            except Exception as e:
                logger.warning(f"Failed to load strategy weights: {e}")
        else:
            logger.info(f"[WEIGHTS] No persisted weights at {self.path}, starting fresh")
        return {}

    def _save(self):
        try:
            with open(self.path, "w") as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save strategy weights: {e}")

    def _ensure_entry(self, name: str):
        if name not in self.data:
            self.data[name] = {"wins": 0.0, "trials": 0.0, "weight": 0.5}

    def get_weight(self, name: str) -> float:
        """Get smoothed weight with age-weighted decay.

        When timestamped outcomes exist, uses 14-day half-life exponential
        decay so recent trades matter more than old ones. Falls back to
        simple Laplace (wins+1)/(trials+2) when no timestamps available.
        """
        self._ensure_entry(name)
        entry = self.data[name]
        ts_outcomes = entry.get("timestamped_outcomes")
        if ts_outcomes and len(ts_outcomes) >= 3:
            now = time.time()
            half_life = 14 * 86400  # 14-day half-life
            decay_wins = 0.0
            decay_total = 0.0
            for o in ts_outcomes:
                age = now - o.get("ts", now)
                weight = math.exp(-0.693 * age / half_life)
                decay_total += weight
                if o.get("win"):
                    decay_wins += weight
            return (decay_wins + 1) / (decay_total + 2)
        return (entry["wins"] + 1) / (entry["trials"] + 2)

    def get_all_weights(self) -> Dict[str, float]:
        """Get weights for all tracked strategies."""
        return {name: self.get_weight(name) for name in self.data}

    def record_outcome(self, strategy: str, win: bool):
        """Record a single trade outcome for a strategy."""
        self._ensure_entry(strategy)
        self.data[strategy]["trials"] += 1
        if win:
            self.data[strategy]["wins"] += 1
        # Track recent outcomes for rolling weight calculation
        if "recent_outcomes" not in self.data[strategy]:
            self.data[strategy]["recent_outcomes"] = []
        self.data[strategy]["recent_outcomes"].append(1 if win else 0)
        # Keep last 20 outcomes
        if len(self.data[strategy]["recent_outcomes"]) > 20:
            self.data[strategy]["recent_outcomes"] = self.data[strategy]["recent_outcomes"][-20:]
        # Timestamped outcomes for age-weighted Laplace smoothing
        if "timestamped_outcomes" not in self.data[strategy]:
            self.data[strategy]["timestamped_outcomes"] = []
        self.data[strategy]["timestamped_outcomes"].append({
            "win": win, "ts": time.time()
        })
        # Keep last 200 timestamped outcomes
        if len(self.data[strategy]["timestamped_outcomes"]) > 200:
            self.data[strategy]["timestamped_outcomes"] = \
                self.data[strategy]["timestamped_outcomes"][-200:]
        self.data[strategy]["weight"] = self.get_weight(strategy)
        self._save()

    def get_rolling_weights(self, window: int = 10) -> Dict[str, float]:
        """Get strategy weights scaled by rolling win rate.

        Formula: weight = base_weight * max(0.1, rolling_wr / 0.5)
        Hot strategies (>50% WR) get boosted, cold strategies get quieted.
        Hard floor: strategies with <35% WR over 20+ recent trades are muted to 0.1.

        Args:
            window: Number of recent outcomes to consider.
        Returns:
            Dict of strategy name -> dynamic weight.
        """
        dynamic = {}
        for name, entry in self.data.items():
            base = self.get_weight(name)
            # Use recent outcomes if available
            recent = entry.get("recent_outcomes", [])
            if len(recent) >= 3:
                rolling_wr = sum(recent[-window:]) / len(recent[-window:])
            else:
                rolling_wr = base  # Fall back to smoothed weight

            # Hard mute: only if BOTH recent AND long-term are poor.
            # Prevents a good strategy from being killed by a short losing streak
            # during a regime change. Decay can erode historical counts, so we
            # check the Laplace-smoothed long-term weight as a second confirmation.
            long_term_weight = self.get_weight(name)
            # Recovery acceleration: if last 5 trades are all wins, boost weight faster
            last_5 = recent[-5:] if len(recent) >= 5 else []
            recovering = len(last_5) == 5 and sum(last_5) == 5

            if len(recent) >= 15 and rolling_wr < 0.30 and long_term_weight < 0.35:
                # Hard mute floor raised from 0.05 to 0.20 — strategy always gets a voice
                mute_weight = 0.30 if recovering else 0.20
                dynamic[name] = mute_weight
                logger.warning(
                    f"[WEIGHTS] {name} MUTED: recent_WR={rolling_wr:.1%}, "
                    f"long_term={long_term_weight:.2f}"
                    + (" (recovering: 5 consecutive wins)" if recovering else "")
                )
                continue
            if len(recent) >= 15 and rolling_wr < 0.30:
                # Recent is bad but long-term is decent — demote, don't mute
                dynamic[name] = 0.25 if recovering else 0.15
                logger.info(
                    f"[WEIGHTS] {name} SOFT-DEMOTED: recent_WR={rolling_wr:.1%} but "
                    f"long_term={long_term_weight:.2f} — possible regime change"
                )
                continue
            if len(recent) >= 20 and rolling_wr < 0.35 and long_term_weight < 0.40:
                dynamic[name] = 0.20 if recovering else 0.15
                logger.info(
                    f"[WEIGHTS] {name} DEMOTED: recent_WR={rolling_wr:.1%}, "
                    f"long_term={long_term_weight:.2f}"
                )
                continue

            # Scale: 50% WR = 1.0x, 80% = 1.6x, 20% = 0.4x (floored at 0.2)
            # Recovery boost: 2x scale when last 5 are all wins
            scale = max(0.2, rolling_wr / 0.5)
            if recovering:
                scale = min(scale * 1.5, 2.0)
            dynamic[name] = round(base * scale, 4)
        return dynamic

    def apply_decay(self):
        """Apply exponential decay to historical counts.
        This downweights old data so recent performance matters more."""
        for name in self.data:
            self.data[name]["wins"] *= self.decay_alpha
            self.data[name]["trials"] *= self.decay_alpha
        logger.info(f"Applied decay (alpha={self.decay_alpha}) to strategy weights")

    def recompute_from_db(self):
        """Recompute weights from trades table. Call once per day.
        Applies decay first, then ingests recent closed trades."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._last_recompute_date == today:
            return  # already recomputed today

        self.apply_decay()

        try:
            from data.db import get_recent_trades
            trades = get_recent_trades(limit=200)
            ingested = 0
            for trade in trades:
                action = trade.get("action", "")
                # Only count full closes (TP1 is partial — don't double-count)
                if action in ("SL", "TP2", "TRAILING_STOP"):
                    strategy = trade.get("strategy", "")
                    if not strategy:
                        continue
                    # Prefer total_pnl from metadata (includes TP1 partial)
                    pnl = trade.get("pnl", 0)
                    meta = trade.get("metadata")
                    if meta:
                        try:
                            import json
                            md = json.loads(meta) if isinstance(meta, str) else meta
                            pnl = md.get("total_pnl", pnl)
                        except Exception:
                            pass
                    win = pnl > 0
                    self._ensure_entry(strategy)
                    self.data[strategy]["trials"] += 1
                    if win:
                        self.data[strategy]["wins"] += 1
                    ingested += 1

            # Recompute weights
            for name in self.data:
                self.data[name]["weight"] = self.get_weight(name)

            self._save()
            self._last_recompute_date = today
            logger.info(
                f"Recomputed strategy weights from {ingested} trades: "
                f"{self.get_all_weights()}"
            )
        except Exception as e:
            logger.warning(f"Failed to recompute weights from DB: {e}")

    def get_report(self) -> Dict[str, Any]:
        """Get a summary report of strategy weights."""
        report = {}
        for name, entry in self.data.items():
            report[name] = {
                "wins": round(entry["wins"], 1),
                "trials": round(entry["trials"], 1),
                "weight": round(self.get_weight(name), 3),
            }
        return report
