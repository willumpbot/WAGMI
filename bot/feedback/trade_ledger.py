"""
Trade Attribution Ledger — Foundation for all rolling analytics.

Every closed trade logs full attribution data (regime, agreement level,
contributing factors, Kelly weight, compound sizing, etc.) into an
append-only CSV.  Provides filtered lookups and rolling breakdowns
used by the daily report and other analytics modules.

Usage:
    from feedback.trade_ledger import TradeLedger
    ledger = TradeLedger("data")
    ledger.record_trade({...})
    recent = ledger.get_trades(lookback_days=7)
"""

import csv
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bot.feedback.trade_ledger")

# ── Schema ────────────────────────────────────────────────────────
LEDGER_COLUMNS = [
    "trade_id",
    "timestamp",
    "symbol",
    "side",
    "regime_1h",
    "regime_4h",
    "agreement_level",
    "contributing_factors",
    "confidence_score",
    "kelly_weight_applied",
    "compound_size_multiplier",
    "leverage",
    "hold_hours",
    "exit_type",
    "entry_price",
    "exit_price",
    "gross_pnl",
    "fees",
    "funding",
    "net_pnl",
    "running_equity",
    "session_dd_pct",
]


class TradeLedger:
    """Append-only trade attribution ledger backed by CSV.

    Thread-safe — all reads and writes are protected by a Lock.
    Loads existing data on init and keeps an in-memory cache so that
    lookups do not require re-reading the file each time.
    """

    def __init__(self, data_dir: str = "data"):
        self._csv_path = os.path.join(data_dir, "trade_ledger.csv")
        self._lock = threading.Lock()
        self._trades: List[Dict[str, str]] = []
        self._load_existing()

    # ── Persistence ───────────────────────────────────────────────

    def _load_existing(self) -> None:
        """Load existing ledger rows into memory on startup."""
        if not os.path.exists(self._csv_path):
            return
        try:
            with open(self._csv_path, "r", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    self._trades.append(row)
            logger.info(
                f"[LEDGER] Loaded {len(self._trades)} existing trades "
                f"from {self._csv_path}"
            )
        except (OSError, csv.Error) as e:
            logger.warning(f"[LEDGER] Could not load existing ledger: {e}")

    def _ensure_header(self) -> None:
        """Write CSV header if the file does not yet exist."""
        if os.path.exists(self._csv_path):
            return
        os.makedirs(os.path.dirname(self._csv_path) or ".", exist_ok=True)
        try:
            with open(self._csv_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=LEDGER_COLUMNS)
                writer.writeheader()
        except OSError as e:
            logger.error(f"[LEDGER] Could not create ledger file: {e}")

    # ── Write ─────────────────────────────────────────────────────

    def record_trade(self, trade_data: dict) -> None:
        """Append a closed trade to the ledger CSV.

        Missing columns are filled with empty strings.  A ``trade_id``
        is auto-generated if not supplied.  ``timestamp`` defaults to
        the current UTC epoch if absent.

        Args:
            trade_data: Dict whose keys should match LEDGER_COLUMNS.
        """
        with self._lock:
            row: Dict[str, str] = {}
            for col in LEDGER_COLUMNS:
                val = trade_data.get(col, "")
                row[col] = str(val) if val is not None else ""

            # Defaults
            if not row["trade_id"]:
                row["trade_id"] = uuid.uuid4().hex[:12]
            if not row["timestamp"]:
                row["timestamp"] = str(time.time())

            self._ensure_header()
            try:
                with open(self._csv_path, "a", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=LEDGER_COLUMNS)
                    writer.writerow(row)
                self._trades.append(row)
                logger.info(
                    f"[LEDGER] Recorded trade {row['trade_id']} "
                    f"{row['symbol']} {row['side']} net_pnl={row['net_pnl']}"
                )
            except OSError as e:
                logger.error(f"[LEDGER] Failed to write trade: {e}")

    # ── Read helpers ──────────────────────────────────────────────

    def get_trades(self, lookback_days: int = 30) -> List[Dict[str, str]]:
        """Return trades within the lookback window.

        Args:
            lookback_days: Number of days to look back from now.

        Returns:
            List of trade dicts (newest first).
        """
        cutoff = time.time() - (lookback_days * 86400)
        with self._lock:
            result = [
                t for t in self._trades
                if self._parse_ts(t.get("timestamp", "")) >= cutoff
            ]
        return sorted(result, key=lambda t: self._parse_ts(t.get("timestamp", "")), reverse=True)

    def get_trades_by_factor(
        self, factor: str, lookback_days: int = 30
    ) -> List[Dict[str, str]]:
        """Return trades where *contributing_factors* contains *factor*.

        Args:
            factor: Strategy or factor name to filter on.
            lookback_days: Number of days to look back.

        Returns:
            Filtered list of trade dicts.
        """
        trades = self.get_trades(lookback_days)
        return [
            t for t in trades
            if factor.lower() in t.get("contributing_factors", "").lower()
        ]

    def get_trades_by_regime(
        self, regime: str, lookback_days: int = 30
    ) -> List[Dict[str, str]]:
        """Return trades matching the given 1h regime.

        Args:
            regime: Regime name (e.g. ``trend``, ``range``, ``panic``).
            lookback_days: Number of days to look back.

        Returns:
            Filtered list of trade dicts.
        """
        trades = self.get_trades(lookback_days)
        return [
            t for t in trades
            if t.get("regime_1h", "").lower() == regime.lower()
        ]

    # ── Breakdowns ────────────────────────────────────────────────

    def get_agreement_breakdown(
        self, lookback_days: int = 7
    ) -> Dict[str, Dict[str, Any]]:
        """Win-rate breakdown by strategy agreement level.

        Returns a dict keyed by agreement level string (e.g. ``"2"``,
        ``"3"``, ``"4"``) with sub-keys ``trades``, ``wins``,
        ``win_rate``, ``total_pnl``.
        """
        trades = self.get_trades(lookback_days)
        buckets: Dict[str, Dict[str, Any]] = {}

        for t in trades:
            level = t.get("agreement_level", "unknown")
            if not level:
                level = "unknown"
            if level not in buckets:
                buckets[level] = {"trades": 0, "wins": 0, "total_pnl": 0.0}
            pnl = self._parse_float(t.get("net_pnl", "0"))
            buckets[level]["trades"] += 1
            buckets[level]["total_pnl"] += pnl
            if pnl > 0:
                buckets[level]["wins"] += 1

        # Compute win rates
        for level, data in buckets.items():
            n = data["trades"]
            data["win_rate"] = round(data["wins"] / n * 100, 1) if n > 0 else 0.0
            data["total_pnl"] = round(data["total_pnl"], 2)

        return buckets

    def get_regime_breakdown(
        self, lookback_days: int = 7
    ) -> Dict[str, Dict[str, Any]]:
        """Win-rate breakdown by 1h regime.

        Returns a dict keyed by regime name with sub-keys ``trades``,
        ``wins``, ``win_rate``, ``total_pnl``.
        """
        trades = self.get_trades(lookback_days)
        buckets: Dict[str, Dict[str, Any]] = {}

        for t in trades:
            regime = t.get("regime_1h", "unknown")
            if not regime:
                regime = "unknown"
            if regime not in buckets:
                buckets[regime] = {"trades": 0, "wins": 0, "total_pnl": 0.0}
            pnl = self._parse_float(t.get("net_pnl", "0"))
            buckets[regime]["trades"] += 1
            buckets[regime]["total_pnl"] += pnl
            if pnl > 0:
                buckets[regime]["wins"] += 1

        for regime, data in buckets.items():
            n = data["trades"]
            data["win_rate"] = round(data["wins"] / n * 100, 1) if n > 0 else 0.0
            data["total_pnl"] = round(data["total_pnl"], 2)

        return buckets

    # ── Utilities ─────────────────────────────────────────────────

    @staticmethod
    def _parse_ts(val: str) -> float:
        """Parse a timestamp string to epoch float."""
        if not val:
            return 0.0
        try:
            return float(val)
        except ValueError:
            try:
                dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
                return dt.timestamp()
            except (ValueError, TypeError):
                return 0.0

    @staticmethod
    def _parse_float(val: str) -> float:
        """Safely parse a float from string."""
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0
