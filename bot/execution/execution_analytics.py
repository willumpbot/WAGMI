"""
Execution Analytics — Fill quality tracking and slippage analysis.

Records every order fill with expected vs actual prices, computes slippage
in basis points, and provides aggregated summaries by symbol, hour-of-day,
and market regime.

Usage:
    from execution.execution_analytics import ExecutionAnalytics
    ea = ExecutionAnalytics()
    ea.record_fill(trade_id="abc", symbol="BTC", side="long",
                   expected_price=95000, actual_fill=95019,
                   notional=5000, regime="trending_bull")
    print(ea.get_slippage_summary())
"""

import csv
import json
import logging
import os
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("bot.execution.execution_analytics")

ANALYTICS_COLUMNS = [
    "trade_id",
    "timestamp",
    "symbol",
    "side",
    "expected_price",
    "actual_fill",
    "notional",
    "slippage_bps",
    "latency_ms",
    "is_maker",
    "regime",
    "hour_of_day",
]


class ExecutionAnalytics:
    """Append-only execution fill analytics backed by CSV.

    Thread-safe. Loads existing records on init for summary computation.
    """

    def __init__(self, data_dir: str = "data"):
        self._csv_path = os.path.join(data_dir, "execution_analytics.csv")
        self._lock = threading.Lock()
        self._records: List[Dict[str, str]] = []
        self._load_existing()

    def _load_existing(self) -> None:
        if not os.path.exists(self._csv_path):
            return
        try:
            with open(self._csv_path, "r", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    self._records.append(row)
            logger.info(f"[EXEC-ANALYTICS] Loaded {len(self._records)} fill records")
        except (OSError, csv.Error) as e:
            logger.warning(f"[EXEC-ANALYTICS] Could not load existing data: {e}")

    def _ensure_header(self) -> None:
        if os.path.exists(self._csv_path):
            return
        os.makedirs(os.path.dirname(self._csv_path) or ".", exist_ok=True)
        try:
            with open(self._csv_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=ANALYTICS_COLUMNS)
                writer.writeheader()
        except OSError as e:
            logger.error(f"[EXEC-ANALYTICS] Could not create file: {e}")

    def record_fill(
        self,
        trade_id: str,
        symbol: str,
        side: str,
        expected_price: float,
        actual_fill: float,
        notional: float,
        regime: str = "unknown",
        is_maker: bool = False,
        signal_time: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Record a fill event with slippage computation.

        Args:
            trade_id: Unique trade identifier.
            symbol: Trading pair (e.g. 'BTC').
            side: 'long'/'short' or 'BUY'/'SELL'.
            expected_price: Mid/snapshot price at signal time.
            actual_fill: Confirmed fill price from exchange.
            notional: Position notional in USD.
            regime: Current market regime.
            is_maker: True if limit order filled as maker.
            signal_time: Unix timestamp of signal generation (for latency).

        Returns:
            Dict with computed fill metrics.
        """
        now = time.time()

        # Compute slippage in basis points
        if expected_price > 0:
            slippage_bps = (actual_fill - expected_price) / expected_price * 10_000
            # Invert for shorts (paying more on entry is bad for longs, less is bad for shorts)
            if side.upper() in ("SELL", "SHORT"):
                slippage_bps = -slippage_bps
        else:
            slippage_bps = 0.0

        # Latency
        latency_ms = (now - signal_time) * 1000 if signal_time else 0.0

        hour_of_day = datetime.now(timezone.utc).hour

        row = {
            "trade_id": trade_id,
            "timestamp": str(now),
            "symbol": symbol,
            "side": side,
            "expected_price": str(round(expected_price, 6)),
            "actual_fill": str(round(actual_fill, 6)),
            "notional": str(round(notional, 2)),
            "slippage_bps": str(round(slippage_bps, 4)),
            "latency_ms": str(round(latency_ms, 1)),
            "is_maker": str(is_maker).lower(),
            "regime": regime,
            "hour_of_day": str(hour_of_day),
        }

        with self._lock:
            self._records.append(row)
            self._ensure_header()
            try:
                with open(self._csv_path, "a", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=ANALYTICS_COLUMNS)
                    writer.writerow(row)
            except OSError as e:
                logger.error(f"[EXEC-ANALYTICS] Failed to write row: {e}")

        logger.debug(
            f"[EXEC-ANALYTICS] {symbol} {side}: expected={expected_price:.2f} "
            f"actual={actual_fill:.2f} slippage={slippage_bps:.2f}bps"
        )

        return {
            "trade_id": trade_id,
            "symbol": symbol,
            "slippage_bps": round(slippage_bps, 4),
            "latency_ms": round(latency_ms, 1),
        }

    def get_slippage_summary(self, lookback_days: int = 30) -> Dict[str, Any]:
        """Get aggregated slippage statistics.

        Args:
            lookback_days: Only include records from the last N days.

        Returns:
            Dict with overall_mean_bps, by_symbol, by_hour, by_regime,
            maker_rate, total_fills.
        """
        cutoff = time.time() - (lookback_days * 86400)

        with self._lock:
            recent = [
                r for r in self._records
                if self._pf(r.get("timestamp", "0")) >= cutoff
            ]

        if not recent:
            return {
                "overall_mean_bps": 0.0,
                "overall_stdev_bps": 0.0,
                "by_symbol": {},
                "by_hour": {},
                "by_regime": {},
                "maker_rate": 0.0,
                "total_fills": 0,
            }

        all_slippage = [self._pf(r.get("slippage_bps", "0")) for r in recent]

        by_symbol: Dict[str, List[float]] = defaultdict(list)
        by_hour: Dict[int, List[float]] = defaultdict(list)
        by_regime: Dict[str, List[float]] = defaultdict(list)
        maker_count = 0

        for r in recent:
            slip = self._pf(r.get("slippage_bps", "0"))
            by_symbol[r.get("symbol", "")].append(slip)
            by_hour[int(self._pf(r.get("hour_of_day", "0")))].append(slip)
            by_regime[r.get("regime", "unknown")].append(slip)
            if r.get("is_maker", "false") == "true":
                maker_count += 1

        mean_bps = sum(all_slippage) / len(all_slippage)
        if len(all_slippage) > 1:
            variance = sum((s - mean_bps) ** 2 for s in all_slippage) / (len(all_slippage) - 1)
            stdev_bps = variance ** 0.5
        else:
            stdev_bps = 0.0

        return {
            "overall_mean_bps": round(mean_bps, 4),
            "overall_stdev_bps": round(stdev_bps, 4),
            "by_symbol": {s: round(sum(v) / len(v), 4) for s, v in by_symbol.items()},
            "by_hour": {h: round(sum(v) / len(v), 4) for h, v in by_hour.items()},
            "by_regime": {r: round(sum(v) / len(v), 4) for r, v in by_regime.items()},
            "maker_rate": round(maker_count / len(recent), 4),
            "total_fills": len(recent),
        }

    def worst_slippage_hours(self, top_n: int = 3) -> List[Tuple[int, float]]:
        """Returns the N hours-of-day with worst average slippage."""
        by_hour: Dict[int, List[float]] = defaultdict(list)

        with self._lock:
            for r in self._records:
                by_hour[int(self._pf(r.get("hour_of_day", "0")))].append(
                    self._pf(r.get("slippage_bps", "0"))
                )

        if not by_hour:
            return []

        return sorted(
            [(h, sum(v) / len(v)) for h, v in by_hour.items()],
            key=lambda x: x[1],
            reverse=True,
        )[:top_n]

    @staticmethod
    def _pf(val: str) -> float:
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0
