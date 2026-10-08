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

from core.provenance import gate_live_write

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
    "snapshot_entry",
    "exit_price",
    "gross_pnl",
    "fees",
    "funding",
    "net_pnl",
    "running_equity",
    "session_dd_pct",
    "ab_gate_hash",  # 0-99 stable hash for A/B split (hash of trade_id % 100)
    # RR_ZERO_FIX (2026-07-14): these were passed by the close handler in
    # multi_strategy_main.py since inception but silently dropped because
    # record_trade() only keeps keys present in this schema.
    "predicted_ev",   # ev_per_dollar from entry_reasons at open
    "realized_rr",    # net_pnl / (original stop width * original qty * leverage)
    "win",            # 1 if net_pnl > 0 else 0
    # EPOCH_FENCE (measurement-integrity, Phase 0, 2026-07-20): identifies
    # which canonical epoch (data/epoch_start.json / data/epoch.py) this row
    # belongs to. Blank on rows written before this column existed — those
    # are fenced by timestamp instead (see data/trade_source.get_run_stats).
    "epoch_id",
    # POSITION_IDENTITY (measurement-integrity, Phase 0.3b, 2026-07-21):
    # the position_id assigned at open (execution/position_manager.py::
    # Position.position_id) -- a stable per-position identity used by
    # core/position_journal.py's exactly-once crash recovery (LEDGER IS
    # TRUTH: a position_id present here is never re-booked). Appended at
    # the END of the schema so existing column positions/readers are
    # unchanged; blank on rows written before this column existed.
    "position_id",
    # MEASUREMENT-FLOOR (LEDGER_FIELD_COMPLETION, 2026-07-27): numeric
    # funding-rate / open-interest / premium snapshot captured at position
    # OPEN (from bot/data/funding_oi_history.jsonl via
    # core/funding_oi_snapshot.latest_funding_oi, threaded through
    # Position.entry_reasons). Distinct from the existing signed ``funding``
    # column, which is realized funding P&L over the hold -- these are the
    # raw entry-time derivatives readings the funding/OI-confirmation
    # instruments need. Appended at the END so existing column positions/
    # readers are unchanged; blank on rows written before these existed or
    # when the feed was unavailable at entry (fail-neutral).
    "funding_rate_entry",
    "open_interest_entry",
    "premium_entry",
    # LINEAGE (2026-10-08, LINEAGE_JOIN_GAP.md S5): the multi-agent round that
    # opened the trade (joins to agent_performance.jsonl pipeline_id) and the
    # thesis it graded. Appended at the END; blank on older rows.
    "pipeline_id",
    "thesis_id",
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

    def _migrate_schema_if_needed(self) -> None:
        """Additive header migration: pad old rows when LEDGER_COLUMNS grows.

        Without this, appending wider rows under the old narrower header makes
        the CSV ragged and breaks pandas readers. One-time .bak copy + atomic
        os.replace so the migration is fully reversible (restore the .bak).
        """
        try:
            with open(self._csv_path, "r", newline="") as f:
                header = next(csv.reader(f), None)
            if header is None or header == LEDGER_COLUMNS:
                return
            if not set(header).issubset(LEDGER_COLUMNS):
                logger.warning(
                    f"[LEDGER] Existing header has unknown columns "
                    f"{set(header) - set(LEDGER_COLUMNS)}; skipping migration"
                )
                return
            bak = self._csv_path + ".pre_migration.bak"
            if not os.path.exists(bak):
                with open(self._csv_path, "rb") as src, open(bak, "wb") as dst:
                    dst.write(src.read())
            with open(self._csv_path, "r", newline="") as f:
                rows = list(csv.DictReader(f))
            tmp = self._csv_path + ".tmp"
            with open(tmp, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=LEDGER_COLUMNS)
                writer.writeheader()
                for r in rows:
                    writer.writerow({c: (r.get(c) or "") for c in LEDGER_COLUMNS})
            os.replace(tmp, self._csv_path)
            logger.info(
                f"[LEDGER] Schema migrated, added: "
                f"{[c for c in LEDGER_COLUMNS if c not in header]}"
            )
        except (OSError, csv.Error) as e:
            logger.warning(f"[LEDGER] Schema migration failed: {e}")

    def _ensure_header(self) -> None:
        """Write CSV header if the file does not yet exist."""
        if os.path.exists(self._csv_path):
            self._migrate_schema_if_needed()
            return
        os.makedirs(os.path.dirname(self._csv_path) or ".", exist_ok=True)
        try:
            with open(self._csv_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=LEDGER_COLUMNS)
                writer.writeheader()
        except OSError as e:
            logger.error(f"[LEDGER] Could not create ledger file: {e}")

    # ── Write ─────────────────────────────────────────────────────

    def record_trade(
        self,
        trade_data: dict,
        *,
        source: Optional[str] = None,
        position_id: Optional[str] = None,
    ) -> None:
        """Append a closed trade to the ledger CSV.

        Missing columns are filled with empty strings.  A ``trade_id``
        is auto-generated if not supplied.  ``timestamp`` defaults to
        the current UTC epoch if absent.

        Gated by core.provenance.gate_live_write(): a call whose provenance
        resolves to a simulated source (backtest/test/sim) raises
        PollutionError instead of writing -- this is the canonical ledger
        every dashboard, the Learning Agent, and Kelly/IC sizing read as
        ground truth, so it gets the same write-time pollution gate Phase
        0.2 put on data/learning.py's record_trade_outcome(). Real live/
        paper calls (the default when `source` is not given) are
        unaffected -- see core/provenance.py for the full incident writeup.

        Args:
            trade_data: Dict whose keys should match LEDGER_COLUMNS. May
                already contain a "position_id" key (preferred).
            source: Optional explicit provenance (e.g. "backtest") -- see
                core.provenance.resolve_source() for the resolution order
                when omitted.
            position_id: Optional convenience override (Phase 0.3b) for
                callers that don't build the "position_id" key into
                trade_data directly. Ignored if trade_data already supplies
                a non-empty "position_id".
        """
        # Gate the ACTUAL resolved write target (self._csv_path, which
        # tests legitimately redirect via TradeLedger(data_dir=tmp_path)),
        # not a separately-computed canonical path -- mirrors
        # data/learning.py::record_trade_outcome's Phase 0.2 gating so
        # monkeypatch/tmp_path-redirected tests still pass.
        gate_live_write(os.path.abspath(self._csv_path), source=source)

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
            # POSITION_IDENTITY: prefer an explicit trade_data["position_id"]
            # (already handled by the loop above); fall back to the
            # position_id= convenience kwarg if the dict didn't supply one.
            if not row["position_id"] and position_id:
                row["position_id"] = str(position_id)

            # EPOCH_FENCE: auto-stamp the active epoch when the caller didn't
            # supply one explicitly, so every new row is self-identifying
            # without every record_trade() call site needing to know about
            # epochs. Fail-soft: leaves "" if data/epoch.py can't resolve one.
            if not row.get("epoch_id"):
                try:
                    from data.epoch import epoch_id as _active_epoch_id
                    row["epoch_id"] = _active_epoch_id()
                except Exception as e:
                    logger.debug(f"[LEDGER] epoch stamp skipped: {e}")

            # Stable A/B bucket (0-99) derived from trade_id — reproducible per trade
            if not row["ab_gate_hash"]:
                row["ab_gate_hash"] = str(int(row["trade_id"], 16) % 100 if all(c in "0123456789abcdef" for c in row["trade_id"]) else hash(row["trade_id"]) % 100)

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
