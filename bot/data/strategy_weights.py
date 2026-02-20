"""
Persistent strategy weight manager.
Tracks per-strategy win/trial counts and computes smoothed accuracy weights
with exponential decay for ensemble weighting.

Weight formula: (wins + 1) / (trials + 2)  (Laplace/additive smoothing)
Decay: before each recompute, multiply counts by alpha (0.9) to downweight old data.
"""

import json
import logging
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
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load strategy weights: {e}")
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
        """Get smoothed weight: (wins+1)/(trials+2) — Laplace prior."""
        self._ensure_entry(name)
        entry = self.data[name]
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
        self.data[strategy]["weight"] = self.get_weight(strategy)
        self._save()

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
