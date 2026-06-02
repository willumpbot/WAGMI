"""
Counter-Factual Learning — Track What Would Have Happened

For every trade the system SKIPS (filtered by ensemble, vetoed by Critic,
rejected by risk gates), track what would have happened if the trade was taken.

This prevents the system from becoming too conservative after anti-spam tightening.
If we're consistently skipping trades that would have been profitable, that's a sign
our filters are too tight.

Tracks:
- Skipped trade entry price, TP1, TP2, SL
- Forward price action after skip (did it hit TP1? TP2? SL?)
- Reason for skip (which filter rejected it)
- Running PnL of "would-have-been" trades

This data feeds back to:
1. Learning Agent: "You skipped 5 winning trades this week"
2. Parameter tuner: loosening gates that block too many winners
3. Confidence calibration: adjusting filters that are miscalibrated

Storage:
- Pending (unresolved): bot/data/llm/counterfactual_pending.jsonl
- Resolved: bot/data/llm/counterfactual_resolved.jsonl
- Legacy (read-only): bot/data/llm/counterfactual_log.jsonl
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bot.llm.counterfactual")


class CounterfactualRecord:
    """A single skipped trade tracked for counterfactual analysis."""

    def __init__(self, symbol: str, side: str, entry_price: float,
                 sl: float, tp1: float, tp2: float, confidence: float,
                 skip_reason: str, strategy: str = "",
                 regime: str = "", metadata: Optional[Dict] = None):
        self.record_id = f"cf_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{id(self) % 10000}"
        self.symbol = symbol
        self.side = side
        self.entry_price = entry_price
        self.sl = sl
        self.tp1 = tp1
        self.tp2 = tp2
        self.confidence = confidence
        self.skip_reason = skip_reason
        self.strategy = strategy
        self.regime = regime
        self.metadata = metadata or {}
        self.created_at = datetime.now(timezone.utc).isoformat()

        # Outcome fields (filled when resolved)
        self.resolved = False
        self.would_hit_tp1 = False
        self.would_hit_tp2 = False
        self.would_hit_sl = False
        self.max_favorable_price: Optional[float] = None
        self.max_adverse_price: Optional[float] = None
        self.hypothetical_pnl_pct: Optional[float] = None
        self.resolved_at: Optional[str] = None
        self.bars_to_resolve: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "symbol": self.symbol,
            "side": self.side,
            "entry_price": self.entry_price,
            "sl": self.sl,
            "tp1": self.tp1,
            "tp2": self.tp2,
            "confidence": self.confidence,
            "skip_reason": self.skip_reason,
            "strategy": self.strategy,
            "regime": self.regime,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "resolved": self.resolved,
            "would_hit_tp1": self.would_hit_tp1,
            "would_hit_tp2": self.would_hit_tp2,
            "would_hit_sl": self.would_hit_sl,
            "max_favorable_price": self.max_favorable_price,
            "max_adverse_price": self.max_adverse_price,
            "hypothetical_pnl_pct": self.hypothetical_pnl_pct,
            "resolved_at": self.resolved_at,
            "bars_to_resolve": self.bars_to_resolve,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CounterfactualRecord":
        rec = cls(
            symbol=d["symbol"],
            side=d["side"],
            entry_price=d["entry_price"],
            sl=d["sl"],
            tp1=d["tp1"],
            tp2=d["tp2"],
            confidence=d["confidence"],
            skip_reason=d["skip_reason"],
            strategy=d.get("strategy", ""),
            regime=d.get("regime", ""),
            metadata=d.get("metadata", {}),
        )
        rec.record_id = d.get("record_id", rec.record_id)
        rec.created_at = d.get("created_at", rec.created_at)
        rec.resolved = d.get("resolved", False)
        rec.would_hit_tp1 = d.get("would_hit_tp1", False)
        rec.would_hit_tp2 = d.get("would_hit_tp2", False)
        rec.would_hit_sl = d.get("would_hit_sl", False)
        rec.max_favorable_price = d.get("max_favorable_price")
        rec.max_adverse_price = d.get("max_adverse_price")
        rec.hypothetical_pnl_pct = d.get("hypothetical_pnl_pct")
        rec.resolved_at = d.get("resolved_at")
        rec.bars_to_resolve = d.get("bars_to_resolve", 0)
        return rec


class CounterfactualLearner:
    """
    Tracks skipped trades and computes what would have happened.

    Architecture:
    - Pending records stored in counterfactual_pending.jsonl (small, rewritten on compact)
    - Resolved records appended to counterfactual_resolved.jsonl (append-only)
    - Recent resolved records kept in memory for stats (last N days only)
    - Periodic compaction prevents file bloat

    Provides aggregate stats:
    - How many skipped trades would have been winners?
    - Which skip reasons produce the most missed winners?
    - What's the total hypothetical PnL we left on the table?
    - Which filters need loosening vs tightening?
    """

    # Max bars to track a counterfactual before giving up
    MAX_TRACKING_BARS = 48  # 48h max for 1h candles

    # Max pending counterfactuals to track simultaneously
    MAX_PENDING = 2000

    # How many days of resolved records to keep in memory for stats
    RESOLVED_MEMORY_DAYS = 14

    # Compact pending file every N resolutions
    COMPACT_EVERY = 100

    def __init__(self, data_dir: str = "data/llm"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # New split files
        self.pending_file = self.data_dir / "counterfactual_pending.jsonl"
        self.resolved_file = self.data_dir / "counterfactual_resolved.jsonl"

        # Legacy file (read-only for migration)
        self.legacy_file = self.data_dir / "counterfactual_log.jsonl"

        self._pending: Dict[str, CounterfactualRecord] = {}
        self._resolved_recent: List[CounterfactualRecord] = []  # Only recent N days
        self._resolved_count: int = 0  # Total count including on-disk
        self._resolutions_since_compact: int = 0

        # Track last price update per symbol to avoid double-counting ticks
        # as "bars". We only increment bars_to_resolve when the high/low
        # actually changes (new candle data, not same tick repeated).
        self._last_price_update: Dict[str, tuple] = {}  # symbol -> (high, low)

        self._load()

    def _load(self):
        """Load pending records and recent resolved records.

        Strategy:
        1. If new pending file exists, load from it (fast, small)
        2. If not, migrate from legacy file (one-time, loads only pending)
        3. Load recent resolved records for stats (last N days only)
        """
        loaded_pending = False

        # 1. Try new pending file first
        if self.pending_file.exists():
            try:
                with open(self.pending_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            d = json.loads(line)
                            rec = CounterfactualRecord.from_dict(d)
                            if not rec.resolved:
                                self._pending[rec.record_id] = rec
                        except (json.JSONDecodeError, KeyError):
                            continue
                loaded_pending = True
                logger.info(f"Loaded {len(self._pending)} pending counterfactuals from pending file")
            except Exception as e:
                logger.warning(f"Failed to load pending file: {e}")

        # 2. If no pending file, migrate from legacy
        if not loaded_pending and self.legacy_file.exists():
            self._migrate_from_legacy()

        # 3. Load recent resolved for stats
        self._load_recent_resolved()

    def _migrate_from_legacy(self):
        """One-time migration from legacy counterfactual_log.jsonl.

        Only loads the LAST occurrence of each record_id (deduplication)
        and only keeps pending (unresolved) records.
        """
        logger.info("Migrating from legacy counterfactual_log.jsonl...")
        seen_ids: Dict[str, Dict] = {}  # record_id -> latest dict
        line_count = 0

        try:
            with open(self.legacy_file, "r") as f:
                for line in f:
                    line_count += 1
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        rid = d.get("record_id", "")
                        if rid:
                            seen_ids[rid] = d  # Keep latest version
                    except (json.JSONDecodeError, KeyError):
                        continue

            # Split into pending and resolved
            pending_records = []
            resolved_records = []
            for rid, d in seen_ids.items():
                if d.get("resolved"):
                    resolved_records.append(d)
                else:
                    pending_records.append(d)
                    try:
                        rec = CounterfactualRecord.from_dict(d)
                        self._pending[rec.record_id] = rec
                    except (KeyError, TypeError):
                        continue

            # Write deduplicated pending file
            with open(self.pending_file, "w") as f:
                for d in pending_records:
                    f.write(json.dumps(d) + "\n")

            # Write deduplicated resolved file
            with open(self.resolved_file, "w") as f:
                for d in resolved_records:
                    f.write(json.dumps(d) + "\n")

            logger.info(
                f"Migration complete: {line_count} lines -> "
                f"{len(seen_ids)} unique records "
                f"({len(pending_records)} pending, {len(resolved_records)} resolved)"
            )

            # Rename legacy file so migration doesn't repeat
            backup = self.legacy_file.with_suffix(".jsonl.bak")
            try:
                if backup.exists():
                    backup.unlink()
                self.legacy_file.rename(backup)
                logger.info(f"Legacy file renamed to {backup.name}")
            except Exception as e:
                logger.warning(f"Could not rename legacy file: {e}")

        except Exception as e:
            logger.warning(f"Legacy migration failed: {e}")

    def _load_recent_resolved(self):
        """Load resolved records from the last N days for in-memory stats."""
        if not self.resolved_file.exists():
            return

        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.RESOLVED_MEMORY_DAYS)).isoformat()
        total = 0

        try:
            with open(self.resolved_file, "r") as f:
                for line in f:
                    total += 1
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        created = d.get("created_at", "")
                        if created >= cutoff:
                            rec = CounterfactualRecord.from_dict(d)
                            self._resolved_recent.append(rec)
                    except (json.JSONDecodeError, KeyError):
                        continue

            self._resolved_count = total
            logger.info(
                f"Loaded {len(self._resolved_recent)} recent resolved "
                f"(of {total} total) counterfactuals"
            )
        except Exception as e:
            logger.warning(f"Failed to load resolved counterfactuals: {e}")

    def _save_pending_record(self, record: CounterfactualRecord):
        """Append a NEW pending record to the pending file."""
        try:
            with open(self.pending_file, "a") as f:
                f.write(json.dumps(record.to_dict()) + "\n")
        except Exception as e:
            logger.error(f"Failed to save pending counterfactual: {e}")

    def _save_resolved_record(self, record: CounterfactualRecord):
        """Append a resolved record to the resolved file."""
        try:
            with open(self.resolved_file, "a") as f:
                f.write(json.dumps(record.to_dict()) + "\n")
        except Exception as e:
            logger.error(f"Failed to save resolved counterfactual: {e}")

    def _compact_pending_file(self):
        """Rewrite pending file with only current pending records.

        Called periodically to remove records that have been resolved.
        """
        try:
            with open(self.pending_file, "w") as f:
                for rec in self._pending.values():
                    f.write(json.dumps(rec.to_dict()) + "\n")
            self._resolutions_since_compact = 0
            logger.debug(f"Compacted pending file: {len(self._pending)} records")
        except Exception as e:
            logger.warning(f"Pending file compaction failed: {e}")

    def record_skip(self, symbol: str, side: str, entry_price: float,
                     sl: float, tp1: float, tp2: float, confidence: float,
                     skip_reason: str, strategy: str = "",
                     regime: str = "", metadata: Optional[Dict] = None) -> str:
        """Record a skipped trade for counterfactual tracking."""
        # Evict oldest pending if at capacity
        if len(self._pending) >= self.MAX_PENDING:
            oldest_key = min(self._pending, key=lambda k: self._pending[k].created_at)
            old = self._pending.pop(oldest_key)
            old.resolved = True
            old.resolved_at = datetime.now(timezone.utc).isoformat()
            old.hypothetical_pnl_pct = 0.0
            self._resolved_recent.append(old)
            self._save_resolved_record(old)
            self._resolved_count += 1

        rec = CounterfactualRecord(
            symbol=symbol, side=side, entry_price=entry_price,
            sl=sl, tp1=tp1, tp2=tp2, confidence=confidence,
            skip_reason=skip_reason, strategy=strategy,
            regime=regime, metadata=metadata,
        )
        self._pending[rec.record_id] = rec
        self._save_pending_record(rec)
        return rec.record_id

    def update_with_price(self, symbol: str, high: float, low: float, close: float):
        """
        Update all pending counterfactuals for a symbol with new price data.

        Called on every scan tick (~15-45s), but bars_to_resolve only increments
        when the OHLC data actually changes (i.e., a new candle arrived).
        This prevents the 48-bar timeout from triggering in 48 ticks (~20 min)
        instead of the intended 48 hours.
        """
        # Detect new candle: high/low changed from last update
        last = self._last_price_update.get(symbol)
        is_new_candle = (last is None or last != (high, low))
        self._last_price_update[symbol] = (high, low)

        to_resolve = []

        for record_id, rec in self._pending.items():
            if rec.symbol != symbol:
                continue

            # Only count as a new bar if candle data actually changed
            if is_new_candle:
                rec.bars_to_resolve += 1

            # Track max favorable/adverse excursion
            if rec.side == "BUY":
                if rec.max_favorable_price is None or high > rec.max_favorable_price:
                    rec.max_favorable_price = high
                if rec.max_adverse_price is None or low < rec.max_adverse_price:
                    rec.max_adverse_price = low

                # Check if TP1/TP2/SL would have been hit
                if high >= rec.tp1:
                    rec.would_hit_tp1 = True
                if high >= rec.tp2:
                    rec.would_hit_tp2 = True
                if low <= rec.sl:
                    rec.would_hit_sl = True
            else:  # SELL
                if rec.max_favorable_price is None or low < rec.max_favorable_price:
                    rec.max_favorable_price = low
                if rec.max_adverse_price is None or high > rec.max_adverse_price:
                    rec.max_adverse_price = high

                if low <= rec.tp1:
                    rec.would_hit_tp1 = True
                if low <= rec.tp2:
                    rec.would_hit_tp2 = True
                if high >= rec.sl:
                    rec.would_hit_sl = True

            # Resolve conditions: SL hit, TP2 hit, or max tracking bars
            if rec.would_hit_sl or rec.would_hit_tp2 or rec.bars_to_resolve >= self.MAX_TRACKING_BARS:
                # Calculate hypothetical PnL
                if rec.would_hit_sl and not rec.would_hit_tp1:
                    # SL hit first (loss)
                    loss_pct = abs(rec.entry_price - rec.sl) / rec.entry_price * 100
                    rec.hypothetical_pnl_pct = -loss_pct
                elif rec.would_hit_tp2:
                    # Full TP2 (big win)
                    gain_pct = abs(rec.tp2 - rec.entry_price) / rec.entry_price * 100
                    rec.hypothetical_pnl_pct = gain_pct
                elif rec.would_hit_tp1:
                    # TP1 but not TP2 (partial win)
                    gain_pct = abs(rec.tp1 - rec.entry_price) / rec.entry_price * 100
                    rec.hypothetical_pnl_pct = gain_pct * 0.65  # ~65% partial close
                else:
                    # Timed out, use close price
                    if rec.side == "BUY":
                        rec.hypothetical_pnl_pct = (close - rec.entry_price) / rec.entry_price * 100
                    else:
                        rec.hypothetical_pnl_pct = (rec.entry_price - close) / rec.entry_price * 100

                rec.resolved = True
                rec.resolved_at = datetime.now(timezone.utc).isoformat()
                to_resolve.append(record_id)

        # Move resolved records
        for rid in to_resolve:
            rec = self._pending.pop(rid)
            self._resolved_recent.append(rec)
            self._resolved_count += 1
            self._save_resolved_record(rec)
            # Convert resolved counterfactuals with strong evidence into KB entries
            # so future agents are aware of specific filter biases
            try:
                self._maybe_write_kb_entry(rec)
            except Exception:
                pass
            # Wire graduated-rule veto outcomes back for accuracy tracking.
            # Without this, veto rules accumulate times_applied but times_correct stays
            # at 0 forever (no trade → no trade_close → record_outcome never fires).
            if "graduated_rule_veto" in (rec.skip_reason or ""):
                try:
                    from llm.graduated_rules import get_graduated_rules_engine
                    _won = (rec.hypothetical_pnl_pct or 0) > 0
                    try:
                        _cf_hr = datetime.fromisoformat(rec.created_at).hour
                    except Exception:
                        _cf_hr = -1
                    get_graduated_rules_engine().record_outcome(
                        symbol=rec.symbol, regime=rec.regime,
                        side=rec.side, won=_won, hour_utc=_cf_hr,
                    )
                    logger.debug(
                        f"[CF→RULES] Veto outcome wired: {rec.symbol} {rec.side} "
                        f"won={_won} pnl={rec.hypothetical_pnl_pct:.1f}%"
                    )
                except Exception:
                    pass

        # Periodic compaction of pending file
        if to_resolve:
            self._resolutions_since_compact += len(to_resolve)
            if self._resolutions_since_compact >= self.COMPACT_EVERY:
                self._compact_pending_file()

        # Prune old resolved records from memory
        if len(self._resolved_recent) > 10000:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=self.RESOLVED_MEMORY_DAYS)).isoformat()
            self._resolved_recent = [r for r in self._resolved_recent if r.created_at >= cutoff]

    def _maybe_write_kb_entry(self, rec: "CounterfactualRecord") -> None:
        """Write a KB entry when a resolved counterfactual reveals a clear filter bias.

        Conditions for writing:
        - Filter incorrectly blocked a winning trade (hypothetical_pnl_pct > 2%)
          → writes a CAUTION entry about the over-restrictive filter
        - Filter correctly blocked a losing trade (hypothetical_pnl_pct < -2%)
          → writes an EDGE entry confirming the filter works
        Only writes when confidence is high enough (pnl abs > 2%).
        """
        pnl = rec.hypothetical_pnl_pct or 0
        if abs(pnl) < 2.0:
            return  # Not a strong enough signal

        import json as _json, os as _os, time as _time
        _kb_path = _os.path.join("data", "llm", "teaching", "knowledge_base.json")
        try:
            _os.makedirs(_os.path.dirname(_kb_path), exist_ok=True)
            if _os.path.exists(_kb_path):
                with open(_kb_path, "r") as _f:
                    _kb = _json.load(_f)
            else:
                _kb = {"entries": []}

            _sym = getattr(rec, "symbol", "")
            _side = getattr(rec, "side", "")
            _reason = getattr(rec, "skip_reason", "unknown_filter")
            _regime = getattr(rec, "regime", "")

            if pnl > 2.0:
                # Filter was WRONG — blocked a winner
                _content = (
                    f"[FILTER_MISS] {_reason} blocked a winning {_side} trade on {_sym}"
                    + (f" in {_regime}" if _regime else "")
                    + f" (hypothetical +{pnl:.1f}%). Consider relaxing this filter."
                )
                _cat = "execution"
                _conf = min(0.75, 0.50 + abs(pnl) / 100)
            else:
                # Filter was CORRECT — blocked a loser
                _content = (
                    f"[FILTER_CORRECT] {_reason} correctly blocked a losing {_side} trade on {_sym}"
                    + (f" in {_regime}" if _regime else "")
                    + f" (hypothetical {pnl:.1f}%). Filter is working."
                )
                _cat = "risk"
                _conf = min(0.80, 0.55 + abs(pnl) / 100)

            # Deduplicate by content prefix
            _prefix = _content[:80]
            for _e in _kb.get("entries", []):
                if str(_e.get("content", "")).startswith(_prefix[:60]):
                    return

            _kb.setdefault("entries", []).append({
                "knowledge_type": "counterfactual_evidence",
                "content": _content,
                "confidence": round(_conf, 3),
                "evidence_count": 1,
                "category": _cat,
                "tags": [_reason, _sym, _side],
                "source": "counterfactual_resolution",
                "created_at": _time.time(),
                "last_validated": _time.time(),
                "validation_count": 1,
                "invalidation_count": 0,
            })

            with open(_kb_path, "w") as _f:
                _json.dump(_kb, _f, indent=2, default=str)

        except Exception as _e:
            pass  # KB write failure is non-critical

    def get_missed_opportunity_stats(self, lookback_days: int = 14) -> Dict[str, Any]:
        """Compute statistics on missed trading opportunities."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
        recent = [r for r in self._resolved_recent if r.created_at >= cutoff]

        if not recent:
            return {"total_skips": 0, "sufficient_data": False}

        winners = [r for r in recent if (r.hypothetical_pnl_pct or 0) > 0]
        losers = [r for r in recent if (r.hypothetical_pnl_pct or 0) <= 0]

        total_hypo_pnl = sum(r.hypothetical_pnl_pct or 0 for r in recent)
        avg_hypo_pnl = total_hypo_pnl / len(recent) if recent else 0

        # By skip reason
        by_reason: Dict[str, Dict] = {}
        for r in recent:
            reason = r.skip_reason
            if reason not in by_reason:
                by_reason[reason] = {"total": 0, "would_win": 0, "would_lose": 0,
                                      "total_pnl": 0.0}
            by_reason[reason]["total"] += 1
            if (r.hypothetical_pnl_pct or 0) > 0:
                by_reason[reason]["would_win"] += 1
            else:
                by_reason[reason]["would_lose"] += 1
            by_reason[reason]["total_pnl"] += (r.hypothetical_pnl_pct or 0)

        for k, v in by_reason.items():
            v["skip_accuracy"] = v["would_lose"] / v["total"] if v["total"] > 0 else 0
            v["avg_pnl"] = v["total_pnl"] / v["total"] if v["total"] > 0 else 0

        # Identify filters that are too aggressive (blocking winners)
        problem_filters = {k: v for k, v in by_reason.items()
                           if v["total"] >= 5 and v["skip_accuracy"] < 0.5}

        return {
            "total_skips": len(recent),
            "sufficient_data": True,
            "would_win": len(winners),
            "would_lose": len(losers),
            "win_rate_of_skips": len(winners) / len(recent) if recent else 0,
            "total_hypothetical_pnl": total_hypo_pnl,
            "avg_hypothetical_pnl": avg_hypo_pnl,
            "by_skip_reason": by_reason,
            "problem_filters": problem_filters,
            "pending_count": len(self._pending),
            "total_resolved": self._resolved_count,
        }

    def get_filter_tuning_recommendations(self) -> Dict[str, Any]:
        """Generate actionable filter tuning recommendations from counterfactual data.

        Returns a dict with:
        - filters_too_tight: filters blocking >50% would-be winners (should loosen)
        - filters_effective: filters correctly blocking >60% losers (keep)
        - confidence_curve: win rate by confidence bucket for optimal floor calibration
        - symbol_side_edge: which symbol+side combos have edge even when filtered
        """
        stats = self.get_missed_opportunity_stats(lookback_days=7)
        if not stats.get("sufficient_data"):
            return {"sufficient_data": False}

        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        recent = [r for r in self._resolved_recent if r.created_at >= cutoff]

        if len(recent) < 20:
            return {"sufficient_data": False, "reason": f"Only {len(recent)} resolved records"}

        # 1. Filter effectiveness
        filters_too_tight = {}
        filters_effective = {}
        for reason, data in stats.get("by_skip_reason", {}).items():
            if data["total"] < 5:
                continue
            accuracy = data["skip_accuracy"]
            if accuracy < 0.5:
                filters_too_tight[reason] = {
                    "count": data["total"],
                    "would_win_pct": round((1 - accuracy) * 100, 1),
                    "avg_missed_pnl": round(data["avg_pnl"], 3),
                    "action": "LOOSEN" if accuracy < 0.4 else "REVIEW",
                }
            elif accuracy >= 0.6:
                filters_effective[reason] = {
                    "count": data["total"],
                    "correct_rejection_pct": round(accuracy * 100, 1),
                    "action": "KEEP",
                }

        # 2. Confidence curve: win rate by bucket
        conf_buckets: Dict[str, Dict] = {}
        for r in recent:
            conf = r.confidence
            if conf < 50:
                bucket = "<50"
            elif conf < 55:
                bucket = "50-55"
            elif conf < 60:
                bucket = "55-60"
            elif conf < 63:
                bucket = "60-63"
            elif conf < 65:
                bucket = "63-65"
            elif conf < 68:
                bucket = "65-68"
            elif conf < 72:
                bucket = "68-72"
            else:
                bucket = "72+"

            if bucket not in conf_buckets:
                conf_buckets[bucket] = {"total": 0, "wins": 0, "pnl_sum": 0.0}
            conf_buckets[bucket]["total"] += 1
            if (r.hypothetical_pnl_pct or 0) > 0:
                conf_buckets[bucket]["wins"] += 1
            conf_buckets[bucket]["pnl_sum"] += (r.hypothetical_pnl_pct or 0)

        confidence_curve = {}
        for bucket, data in conf_buckets.items():
            if data["total"] >= 3:
                confidence_curve[bucket] = {
                    "count": data["total"],
                    "win_rate": round(data["wins"] / data["total"] * 100, 1),
                    "avg_pnl": round(data["pnl_sum"] / data["total"], 3),
                }

        # 3. Symbol + side edge
        sym_side: Dict[str, Dict] = {}
        for r in recent:
            key = f"{r.symbol}_{r.side}"
            if key not in sym_side:
                sym_side[key] = {"total": 0, "wins": 0, "pnl_sum": 0.0}
            sym_side[key]["total"] += 1
            if (r.hypothetical_pnl_pct or 0) > 0:
                sym_side[key]["wins"] += 1
            sym_side[key]["pnl_sum"] += (r.hypothetical_pnl_pct or 0)

        symbol_side_edge = {}
        for key, data in sym_side.items():
            if data["total"] >= 5:
                wr = data["wins"] / data["total"]
                symbol_side_edge[key] = {
                    "count": data["total"],
                    "win_rate": round(wr * 100, 1),
                    "avg_pnl": round(data["pnl_sum"] / data["total"], 3),
                    "has_edge": data["pnl_sum"] > 0,  # PnL-based edge, not WR (system is 35% WR)
                }

        return {
            "sufficient_data": True,
            "total_resolved_7d": len(recent),
            "overall_skip_wr": round(stats.get("win_rate_of_skips", 0) * 100, 1),
            "filters_too_tight": filters_too_tight,
            "filters_effective": filters_effective,
            "confidence_curve": confidence_curve,
            "symbol_side_edge": symbol_side_edge,
            "recommendation_summary": self._build_recommendation_summary(
                filters_too_tight, filters_effective, confidence_curve, symbol_side_edge
            ),
        }

    def _build_recommendation_summary(self, too_tight, effective, conf_curve, sym_edge) -> str:
        """Build a human-readable recommendation summary."""
        lines = []

        if too_tight:
            lines.append("FILTERS TO LOOSEN (blocking too many winners):")
            for filt, data in sorted(too_tight.items(), key=lambda x: -x[1]["count"]):
                lines.append(
                    f"  - {filt}: {data['count']} blocked, "
                    f"{data['would_win_pct']:.0f}% would have won "
                    f"(avg PnL={data['avg_missed_pnl']:+.3f}%) -> {data['action']}"
                )

        if effective:
            lines.append("EFFECTIVE FILTERS (correctly blocking losers):")
            for filt, data in sorted(effective.items(), key=lambda x: -x[1]["count"]):
                lines.append(
                    f"  - {filt}: {data['count']} blocked, "
                    f"{data['correct_rejection_pct']:.0f}% correctly rejected -> KEEP"
                )

        # Find optimal confidence floor from curve
        if conf_curve:
            positive_buckets = {k: v for k, v in conf_curve.items() if v["avg_pnl"] > 0}
            if positive_buckets:
                lowest_profitable = min(positive_buckets.keys())
                lines.append(f"OPTIMAL CONFIDENCE FLOOR: signals above {lowest_profitable} have positive avg PnL")

        # Symbol-side edges
        edge_setups = {k: v for k, v in sym_edge.items() if v.get("has_edge")}
        if edge_setups:
            lines.append("SETUPS WITH EDGE (even when filtered):")
            for setup, data in sorted(edge_setups.items(), key=lambda x: -x[1]["win_rate"]):
                lines.append(
                    f"  - {setup}: WR={data['win_rate']:.0f}% "
                    f"avg_PnL={data['avg_pnl']:+.3f}% ({data['count']} samples)"
                )

        return "\n".join(lines) if lines else "Insufficient data for recommendations"

    def get_prompt_context(self, lookback_days: int = 7) -> str:
        """Generate context for agent prompts about missed opportunities."""
        stats = self.get_missed_opportunity_stats(lookback_days)
        if not stats.get("sufficient_data") or stats["total_skips"] < 10:
            return ""

        lines = [f"COUNTERFACTUAL ANALYSIS ({stats['total_skips']} skipped trades, {lookback_days}d):"]
        lines.append(f"  Of trades we skipped: {stats['would_win']} would have won, "
                     f"{stats['would_lose']} would have lost")
        lines.append(f"  Skip accuracy: {(1-stats['win_rate_of_skips'])*100:.0f}% correctly skipped")
        lines.append(f"  Hypothetical PnL left on table: {stats['total_hypothetical_pnl']:+.2f}%")
        lines.append(f"  Pending resolution: {stats['pending_count']} | Total resolved: {stats['total_resolved']}")

        if stats.get("problem_filters"):
            lines.append("  FILTERS BLOCKING TOO MANY WINNERS:")
            for filt, data in stats["problem_filters"].items():
                lines.append(f"    - {filt}: blocked {data['total']} trades, "
                             f"{data['would_win']} would have won "
                             f"(avg PnL={data['avg_pnl']:+.2f}%)")

        return "\n".join(lines)

    def get_status(self) -> Dict[str, Any]:
        """Get current counterfactual learner status for health checks."""
        return {
            "pending": len(self._pending),
            "resolved_in_memory": len(self._resolved_recent),
            "total_resolved": self._resolved_count,
            "max_pending": self.MAX_PENDING,
            "pending_by_symbol": self._count_by_symbol(self._pending),
        }

    def _count_by_symbol(self, records: Dict[str, CounterfactualRecord]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for rec in records.values():
            counts[rec.symbol] = counts.get(rec.symbol, 0) + 1
        return counts
