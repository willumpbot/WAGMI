"""
Shadow Ledger — Tracks predictions from disabled/dormant strategies.

Records what disabled strategies WOULD HAVE predicted, then matches
actual returns when the trade window closes.  After 50+ shadow trades,
the factor_tester can evaluate if the strategy should be reactivated.

Usage:
    ledger = ShadowLedger("data")
    ledger.record_shadow_signal("lead_lag", "BTC", "BUY", 72.0, 65000.0)
    ledger.resolve_shadows("BTC", 66000.0)
    stats = ledger.get_factor_stats("lead_lag")
    candidates = ledger.get_reactivation_candidates()
"""

import csv
import logging
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bot.feedback.shadow_ledger")

SHADOW_COLUMNS = [
    "id",
    "timestamp",
    "factor",
    "symbol",
    "predicted_side",
    "confidence",
    "entry_price",
    "exit_price",
    "actual_return",
    "resolved",
    "resolve_timestamp",
]


class ShadowLedger:
    """Append-only shadow trade ledger backed by CSV.

    Thread-safe — all reads and writes are protected by a Lock.
    Loads existing data on init and keeps an in-memory cache.
    """

    def __init__(self, data_dir: str = "data"):
        self._csv_path = os.path.join(data_dir, "shadow_ledger.csv")
        self._lock = threading.Lock()
        self._rows: List[Dict[str, str]] = []
        self._load_existing()

    # ── Persistence ───────────────────────────────────────────────

    def _load_existing(self) -> None:
        if not os.path.exists(self._csv_path):
            return
        try:
            with open(self._csv_path, "r", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    self._rows.append(row)
            logger.info(
                f"[SHADOW] Loaded {len(self._rows)} shadow records "
                f"from {self._csv_path}"
            )
        except (OSError, csv.Error) as e:
            logger.warning(f"[SHADOW] Could not load existing ledger: {e}")

    def _ensure_header(self) -> None:
        if os.path.exists(self._csv_path):
            return
        os.makedirs(os.path.dirname(self._csv_path) or ".", exist_ok=True)
        try:
            with open(self._csv_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=SHADOW_COLUMNS)
                writer.writeheader()
        except OSError as e:
            logger.error(f"[SHADOW] Could not create file: {e}")

    def _write_row(self, row: Dict[str, str]) -> None:
        """Append a single row to CSV. Must hold lock."""
        self._ensure_header()
        try:
            with open(self._csv_path, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=SHADOW_COLUMNS)
                writer.writerow(row)
        except OSError as e:
            logger.error(f"[SHADOW] Failed to write row: {e}")

    def _rewrite_csv(self) -> None:
        """Rewrite entire CSV from in-memory cache (for resolving). Must hold lock."""
        try:
            os.makedirs(os.path.dirname(self._csv_path) or ".", exist_ok=True)
            with open(self._csv_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=SHADOW_COLUMNS)
                writer.writeheader()
                for row in self._rows:
                    writer.writerow(row)
        except OSError as e:
            logger.error(f"[SHADOW] Failed to rewrite CSV: {e}")

    # ── Write ─────────────────────────────────────────────────────

    def record_shadow_signal(
        self,
        factor: str,
        symbol: str,
        side: str,
        confidence: float,
        entry_price: float,
        timestamp: Optional[float] = None,
    ) -> None:
        """Record what a disabled strategy predicted."""
        with self._lock:
            row = {
                "id": uuid.uuid4().hex[:12],
                "timestamp": str(timestamp or time.time()),
                "factor": factor,
                "symbol": symbol,
                "predicted_side": side,
                "confidence": str(round(confidence, 2)),
                "entry_price": str(round(entry_price, 6)),
                "exit_price": "",
                "actual_return": "",
                "resolved": "false",
                "resolve_timestamp": "",
            }
            self._rows.append(row)
            self._write_row(row)
            logger.debug(
                f"[SHADOW] Recorded: {factor} {side} {symbol} "
                f"@ {entry_price} conf={confidence:.1f}"
            )

    def resolve_shadows(
        self, symbol: str, exit_price: float, max_age_hours: float = 8.0
    ) -> int:
        """Resolve pending shadow signals for a symbol.

        Matches exit_price against entry_price to compute actual_return.
        Only resolves shadows within max_age_hours.

        Returns:
            Number of shadows resolved.
        """
        resolved_count = 0
        now = time.time()
        cutoff = now - (max_age_hours * 3600)

        with self._lock:
            for row in self._rows:
                if row.get("resolved") == "true":
                    continue
                if row.get("symbol") != symbol:
                    continue

                ts = self._parse_float(row.get("timestamp", "0"))
                if ts < cutoff:
                    # Too old — mark as expired
                    row["resolved"] = "expired"
                    row["resolve_timestamp"] = str(now)
                    continue

                entry = self._parse_float(row.get("entry_price", "0"))
                if entry <= 0:
                    continue

                # Compute return based on predicted direction
                side = row.get("predicted_side", "").upper()
                if side == "BUY":
                    actual_return = (exit_price - entry) / entry
                elif side == "SELL":
                    actual_return = (entry - exit_price) / entry
                else:
                    continue

                row["exit_price"] = str(round(exit_price, 6))
                row["actual_return"] = str(round(actual_return, 6))
                row["resolved"] = "true"
                row["resolve_timestamp"] = str(now)
                resolved_count += 1

            if resolved_count > 0:
                self._rewrite_csv()
                logger.info(
                    f"[SHADOW] Resolved {resolved_count} shadows for {symbol} "
                    f"@ {exit_price}"
                )

        return resolved_count

    # ── Read helpers ──────────────────────────────────────────────

    def get_factor_stats(
        self, factor: str, lookback_days: int = 30
    ) -> Dict[str, Any]:
        """Get shadow trade statistics for a factor.

        Returns:
            Dict with count, win_rate, avg_return, ic_estimate.
        """
        cutoff = time.time() - (lookback_days * 86400)

        with self._lock:
            resolved = [
                r for r in self._rows
                if r.get("factor") == factor
                and r.get("resolved") == "true"
                and self._parse_float(r.get("timestamp", "0")) >= cutoff
            ]

        if not resolved:
            return {"count": 0, "win_rate": 0.0, "avg_return": 0.0, "ic_estimate": 0.0}

        returns = [self._parse_float(r.get("actual_return", "0")) for r in resolved]
        wins = sum(1 for ret in returns if ret > 0)

        return {
            "count": len(resolved),
            "win_rate": round(wins / len(resolved), 4) if resolved else 0.0,
            "avg_return": round(sum(returns) / len(returns), 6) if returns else 0.0,
            "ic_estimate": round(
                sum(1 if r > 0 else -1 for r in returns) / len(returns), 4
            ) if returns else 0.0,
        }

    def get_reactivation_candidates(
        self, min_trades: int = 50, min_wr: float = 0.55
    ) -> List[Dict[str, Any]]:
        """Return factors with enough shadow trades and positive edge."""
        with self._lock:
            factors = set(r.get("factor", "") for r in self._rows if r.get("factor"))

        candidates = []
        for factor in factors:
            stats = self.get_factor_stats(factor)
            if stats["count"] >= min_trades and stats["win_rate"] >= min_wr:
                candidates.append({"factor": factor, **stats})

        return sorted(candidates, key=lambda x: x["win_rate"], reverse=True)

    @staticmethod
    def _parse_float(val: str) -> float:
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0
