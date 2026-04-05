"""
Post-Trade Reflection Engine: Automated quant analysis after every trade.

Runs after every position close. Analyzes entry quality, re-entry patterns,
move exhaustion, and price drift. Logs structured observations with compact
codes for downstream learning.

No LLM calls — pure deterministic analysis on trade data and recent history.

Observation Codes:
    RE1 = re-entry same symbol/direction within 2hrs
    RE2 = entering higher/worse than last close (chasing)
    RE3 = 3+ consecutive same-direction on same symbol
    MEX = move exhaustion (>70% daily ATR consumed in this direction)
    RRD = R:R degraded vs first entry of sequence (<1.5:1)
    WPL = win prob below 50% at entry
    CBR = circuit breaker recently tripped before this entry
    PDR = price drifting against position at close (bounce/reversal)
    TPG = TP1 was reached during lifetime but trailed back (gave back profit)
    SLT = stop too tight (MAE < 50% of stop distance, wick killed it)
    SLW = stop too wide (held losing position >4hrs without improvement)
    BIG = big winner (>3R), marks the trade that others re-enter after
    SEQ = part of a re-entry sequence (links to original BIG trade)
    EXH = entered after >3% same-direction move already happened today
    DRF = entry price drifting away from optimal (worse than prior entries)
"""

import json
import logging
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger("bot.llm.reflection")

_REFLECTION_DIR = os.path.join("data", "reflections")
_REFLECTION_FILE = os.path.join(_REFLECTION_DIR, "trade_reflections.jsonl")
_SEQUENCE_FILE = os.path.join(_REFLECTION_DIR, "active_sequences.json")
_EXHAUSTION_FILE = os.path.join(_REFLECTION_DIR, "move_exhaustion.json")
_SUMMARY_FILE = os.path.join(_REFLECTION_DIR, "periodic_summaries.jsonl")


def _ensure_dir():
    os.makedirs(_REFLECTION_DIR, exist_ok=True)


# ── Observation Code Definitions ─────────────────────────────────────

CODES = {
    "RE1": "re-entry same symbol/direction within 2hrs",
    "RE2": "entering worse price than last close (chasing)",
    "RE3": "3+ consecutive same-direction on same symbol",
    "MEX": "move exhaustion (>70% daily ATR consumed)",
    "RRD": "R:R degraded (<1.5:1)",
    "WPL": "win prob below 50% at entry",
    "CBR": "circuit breaker recently tripped",
    "PDR": "price drifting against position (reversal)",
    "TPG": "TP was reachable but position trailed back",
    "SLT": "stop too tight (wick killed it, MAE < 50% SL dist)",
    "SLW": "stop too wide (held loser >4hrs)",
    "BIG": "big winner (>3R profit)",
    "SEQ": "part of a re-entry sequence after a big winner",
    "EXH": "entered after >3% move already happened",
    "DRF": "entry price worse than prior entries in sequence",
}


@dataclass
class TradeReflection:
    """Structured reflection on a single closed trade."""
    timestamp: str
    symbol: str
    side: str
    entry: float
    exit_price: float
    pnl: float
    hold_time_s: float
    leverage: float
    confidence: float
    regime: str
    exit_action: str
    # Computed analysis
    codes: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    sequence_id: str = ""          # Links re-entries to original trade
    sequence_position: int = 0     # 0=original, 1=first re-entry, etc.
    r_multiple: float = 0.0        # PnL in R multiples
    mfe_pct: float = 0.0           # Max favorable excursion %
    mae_pct: float = 0.0           # Max adverse excursion %
    mfe_capture_pct: float = 0.0   # How much of MFE was captured
    daily_move_pct: float = 0.0    # How much the symbol moved today
    atr_consumed_pct: float = 0.0  # % of daily ATR consumed before entry
    entry_vs_last_close: float = 0.0  # Price diff vs last close on same symbol
    reentry_count: int = 0         # How many times we've entered this symbol today
    win_prob_at_entry: float = 0.0
    ev_at_entry: float = 0.0
    rr_at_entry: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def summary(self) -> str:
        """Compact one-line summary with codes."""
        tag = "W" if self.pnl > 0 else "L"
        codes_str = ",".join(self.codes) if self.codes else "CLEAN"
        return (
            f"[{tag}] {self.symbol} {self.side} ${self.pnl:+.2f} "
            f"({self.r_multiple:+.1f}R) {codes_str} "
            f"seq={self.sequence_position} hold={self.hold_time_s/60:.0f}m"
        )


class ReentryTracker:
    """Tracks same-symbol same-direction entry sequences.

    Detects when the bot is chasing — re-entering the same trade
    after a winner, often at worse prices with degrading edge.
    """

    def __init__(self):
        # symbol -> list of recent entries (last 24hrs)
        self._entries: Dict[str, List[Dict]] = defaultdict(list)
        # symbol -> active sequence info
        self._sequences: Dict[str, Dict] = {}
        self._load_state()

    def _load_state(self):
        _ensure_dir()
        try:
            if os.path.exists(_SEQUENCE_FILE):
                with open(_SEQUENCE_FILE) as f:
                    data = json.load(f)
                self._sequences = data.get("sequences", {})
                self._entries = defaultdict(list, {
                    k: v for k, v in data.get("entries", {}).items()
                })
        except Exception as e:
            logger.debug(f"[REFLECT] Sequence state load: {e}")

    def _save_state(self):
        _ensure_dir()
        try:
            with open(_SEQUENCE_FILE, "w") as f:
                json.dump({
                    "sequences": self._sequences,
                    "entries": dict(self._entries),
                    "updated": datetime.now(timezone.utc).isoformat(),
                }, f, indent=2)
        except Exception as e:
            logger.warning(f"[REFLECT] Sequence state save failed: {e}")

    def record_entry(self, symbol: str, side: str, entry_price: float,
                     confidence: float, regime: str, timestamp: str = "") -> Dict[str, Any]:
        """Record a new entry and return re-entry analysis."""
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        entry_record = {
            "timestamp": ts,
            "side": side,
            "price": entry_price,
            "confidence": confidence,
            "regime": regime,
        }

        # Prune entries older than 24hrs
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        self._entries[symbol] = [
            e for e in self._entries[symbol] if e["timestamp"] > cutoff
        ]

        # Analyze re-entry pattern
        same_dir = [e for e in self._entries[symbol] if e["side"] == side]
        reentry_count = len(same_dir)

        analysis = {
            "reentry_count": reentry_count,
            "is_reentry": reentry_count > 0,
            "codes": [],
            "notes": [],
        }

        if reentry_count > 0:
            last = same_dir[-1]
            time_since = ts  # Will compute properly with datetime

            # RE1: re-entry within 2 hours
            try:
                last_dt = datetime.fromisoformat(last["timestamp"])
                now_dt = datetime.fromisoformat(ts) if ts else datetime.now(timezone.utc)
                hours_since = (now_dt - last_dt).total_seconds() / 3600
                if hours_since < 2:
                    analysis["codes"].append("RE1")
                    analysis["notes"].append(
                        f"Re-entry {hours_since:.1f}hrs after last {side} on {symbol}"
                    )
            except (ValueError, TypeError):
                pass

            # RE2: entering at worse price than last entry
            if side == "SELL" and entry_price > last["price"]:
                analysis["codes"].append("RE2")
                drift_pct = (entry_price - last["price"]) / last["price"] * 100
                analysis["notes"].append(
                    f"Shorting {drift_pct:+.2f}% higher than last entry (chasing)"
                )
            elif side == "BUY" and entry_price < last["price"]:
                analysis["codes"].append("RE2")
                drift_pct = (entry_price - last["price"]) / last["price"] * 100
                analysis["notes"].append(
                    f"Longing {drift_pct:+.2f}% lower than last entry (chasing)"
                )

            # RE3: 3+ consecutive same-direction
            if reentry_count >= 2:
                analysis["codes"].append("RE3")
                analysis["notes"].append(
                    f"{reentry_count + 1} consecutive {side} entries on {symbol}"
                )

            # DRF: entry drifting away from optimal
            all_prices = [e["price"] for e in same_dir]
            if side == "SELL":
                best_entry = max(all_prices)
                if entry_price < best_entry * 0.99:
                    analysis["codes"].append("DRF")
                    analysis["notes"].append(
                        f"Entry ${entry_price:.2f} vs best ${best_entry:.2f} "
                        f"({(entry_price/best_entry - 1)*100:+.1f}%)"
                    )
            else:
                best_entry = min(all_prices)
                if entry_price > best_entry * 1.01:
                    analysis["codes"].append("DRF")

        # Record this entry
        self._entries[symbol].append(entry_record)

        # Update sequence tracking
        seq_key = f"{symbol}_{side}"
        if seq_key not in self._sequences or reentry_count == 0:
            self._sequences[seq_key] = {
                "start_time": ts,
                "first_entry": entry_price,
                "entry_count": 1,
                "cumulative_pnl": 0.0,
                "best_pnl": 0.0,
            }
        else:
            self._sequences[seq_key]["entry_count"] += 1

        analysis["sequence_position"] = self._sequences[seq_key]["entry_count"] - 1
        analysis["sequence_id"] = seq_key

        self._save_state()
        return analysis

    def record_close(self, symbol: str, side: str, pnl: float,
                     is_big_winner: bool = False) -> None:
        """Record a close and update sequence stats."""
        seq_key = f"{symbol}_{side}"
        if seq_key in self._sequences:
            self._sequences[seq_key]["cumulative_pnl"] += pnl
            if pnl > self._sequences[seq_key]["best_pnl"]:
                self._sequences[seq_key]["best_pnl"] = pnl

        # If big winner, mark sequence for tracking
        if is_big_winner and seq_key in self._sequences:
            self._sequences[seq_key]["big_winner_at"] = datetime.now(timezone.utc).isoformat()
            self._sequences[seq_key]["big_winner_pnl"] = pnl

        self._save_state()

    def get_sequence_stats(self, symbol: str, side: str) -> Dict[str, Any]:
        """Get current sequence statistics."""
        seq_key = f"{symbol}_{side}"
        return self._sequences.get(seq_key, {})

    def reset_sequence(self, symbol: str, side: str) -> None:
        """Reset sequence (e.g., when direction changes)."""
        seq_key = f"{symbol}_{side}"
        if seq_key in self._sequences:
            del self._sequences[seq_key]
        self._save_state()


class MoveExhaustionDetector:
    """Tracks how much of the daily range has been consumed per symbol.

    After a big directional move, continuation probability drops.
    This detector measures ATR consumption and flags exhaustion.
    """

    def __init__(self):
        # symbol -> daily price tracking
        self._daily_prices: Dict[str, List[Dict]] = defaultdict(list)
        self._daily_high: Dict[str, float] = {}
        self._daily_low: Dict[str, float] = {}
        self._load_state()

    def _load_state(self):
        _ensure_dir()
        try:
            if os.path.exists(_EXHAUSTION_FILE):
                with open(_EXHAUSTION_FILE) as f:
                    data = json.load(f)
                self._daily_high = data.get("daily_high", {})
                self._daily_low = data.get("daily_low", {})
        except Exception:
            pass

    def _save_state(self):
        _ensure_dir()
        try:
            with open(_EXHAUSTION_FILE, "w") as f:
                json.dump({
                    "daily_high": self._daily_high,
                    "daily_low": self._daily_low,
                    "updated": datetime.now(timezone.utc).isoformat(),
                }, f, indent=2)
        except Exception:
            pass

    def update_price(self, symbol: str, price: float) -> None:
        """Update daily price tracking."""
        if symbol not in self._daily_high or price > self._daily_high[symbol]:
            self._daily_high[symbol] = price
        if symbol not in self._daily_low or price < self._daily_low[symbol]:
            self._daily_low[symbol] = price
        self._save_state()

    def get_daily_range_pct(self, symbol: str) -> float:
        """Get the daily range as a % of the midpoint."""
        high = self._daily_high.get(symbol, 0)
        low = self._daily_low.get(symbol, 0)
        if high <= 0 or low <= 0:
            return 0.0
        mid = (high + low) / 2
        return (high - low) / mid * 100

    def get_move_from_open(self, symbol: str, current_price: float,
                           side: str) -> float:
        """Get how much the price has already moved in the trade direction.

        Returns percentage. Positive = already moved in your favor (exhaustion risk).
        """
        high = self._daily_high.get(symbol, current_price)
        low = self._daily_low.get(symbol, current_price)
        daily_open_approx = (high + low) / 2  # Approximation

        if side == "SELL":
            # For shorts, move from open downward is favorable
            return (daily_open_approx - current_price) / daily_open_approx * 100
        else:
            return (current_price - daily_open_approx) / daily_open_approx * 100

    def check_exhaustion(self, symbol: str, current_price: float,
                         side: str, atr: float = 0) -> Dict[str, Any]:
        """Check if the move is exhausted.

        Returns analysis dict with codes and metrics.
        """
        analysis = {"codes": [], "notes": [], "atr_consumed_pct": 0.0}

        daily_range = self.get_daily_range_pct(symbol)
        move_pct = self.get_move_from_open(symbol, current_price, side)

        # ATR consumption: if daily range > 70% of typical ATR, exhaustion risk
        if atr > 0 and current_price > 0:
            atr_pct = atr / current_price * 100
            if daily_range > 0 and atr_pct > 0:
                consumed = daily_range / atr_pct
                analysis["atr_consumed_pct"] = round(consumed * 100, 1)
                if consumed > 0.7:
                    analysis["codes"].append("MEX")
                    analysis["notes"].append(
                        f"Daily range {daily_range:.1f}% = {consumed*100:.0f}% of ATR "
                        f"consumed. Continuation unlikely."
                    )

        # EXH: price already moved >3% in trade direction
        if move_pct > 3.0:
            analysis["codes"].append("EXH")
            analysis["notes"].append(
                f"{symbol} already moved {move_pct:.1f}% in {side} direction today"
            )

        return analysis

    def reset_daily(self) -> None:
        """Reset daily tracking (call at UTC midnight)."""
        self._daily_high.clear()
        self._daily_low.clear()
        self._save_state()


class ReflectionEngine:
    """Main reflection engine. Runs after every trade close.

    Combines re-entry tracking, move exhaustion detection, and
    trade quality analysis into structured observations.
    """

    def __init__(self):
        self.reentry_tracker = ReentryTracker()
        self.exhaustion_detector = MoveExhaustionDetector()
        self._trade_count = 0
        self._session_reflections: List[TradeReflection] = []
        _ensure_dir()
        logger.info("[REFLECT] Reflection engine initialized")

    def on_entry(self, symbol: str, side: str, entry_price: float,
                 confidence: float, regime: str, atr: float = 0,
                 win_prob: float = 0, ev: float = 0,
                 timestamp: str = "") -> Dict[str, Any]:
        """Called when a new position opens. Returns entry analysis with codes.

        This analysis is logged but does NOT block trades (we need data first).
        """
        ts = timestamp or datetime.now(timezone.utc).isoformat()

        # Update price tracking
        self.exhaustion_detector.update_price(symbol, entry_price)

        # Re-entry analysis
        reentry = self.reentry_tracker.record_entry(
            symbol, side, entry_price, confidence, regime, ts
        )

        # Move exhaustion analysis
        exhaustion = self.exhaustion_detector.check_exhaustion(
            symbol, entry_price, side, atr
        )

        # Win prob check
        codes = reentry["codes"] + exhaustion["codes"]
        notes = reentry["notes"] + exhaustion["notes"]

        if win_prob > 0 and win_prob < 0.50:
            codes.append("WPL")
            notes.append(f"Win probability {win_prob:.1%} below 50% threshold")

        # Log entry analysis
        if codes:
            logger.info(
                f"[REFLECT] ENTRY {symbol} {side} @ ${entry_price:.2f} | "
                f"codes=[{','.join(codes)}] | "
                f"reentry#{reentry['sequence_position']} conf={confidence:.0f}%"
            )
            for note in notes:
                logger.info(f"[REFLECT]   -> {note}")
        else:
            logger.info(
                f"[REFLECT] ENTRY {symbol} {side} @ ${entry_price:.2f} | "
                f"CLEAN entry | conf={confidence:.0f}% regime={regime}"
            )

        return {
            "codes": codes,
            "notes": notes,
            "reentry_count": reentry["reentry_count"],
            "sequence_position": reentry["sequence_position"],
            "sequence_id": reentry.get("sequence_id", ""),
            "atr_consumed_pct": exhaustion.get("atr_consumed_pct", 0),
        }

    def on_close(self, symbol: str, side: str, entry_price: float,
                 exit_price: float, pnl: float, hold_time_s: float,
                 leverage: float, confidence: float, regime: str,
                 exit_action: str, sl_price: float = 0, tp1_price: float = 0,
                 peak_price: float = 0, lowest_price: float = 0,
                 win_prob: float = 0, ev: float = 0, rr: float = 0,
                 entry_reasons: Dict = None, atr: float = 0) -> TradeReflection:
        """Called after every position close. Generates full reflection."""

        entry_reasons = entry_reasons or {}
        self._trade_count += 1

        # Update price tracking
        self.exhaustion_detector.update_price(symbol, exit_price)

        # ── Compute analysis metrics ──
        # R multiple
        sl_dist = abs(entry_price - sl_price) if sl_price > 0 else 0
        risk_amount = sl_dist * leverage if sl_dist > 0 else abs(pnl)
        r_multiple = pnl / risk_amount if risk_amount > 0 else 0

        # MFE/MAE
        if side == "SELL":
            mfe_pct = (entry_price - lowest_price) / entry_price * 100 if lowest_price > 0 and entry_price > 0 else 0
            mae_pct = (peak_price - entry_price) / entry_price * 100 if peak_price > 0 and entry_price > 0 else 0
        else:
            mfe_pct = (peak_price - entry_price) / entry_price * 100 if peak_price > 0 and entry_price > 0 else 0
            mae_pct = (entry_price - lowest_price) / entry_price * 100 if lowest_price > 0 and entry_price > 0 else 0

        # MFE capture
        mfe_capture_pct = 0
        if mfe_pct > 0:
            actual_capture = abs(exit_price - entry_price) / entry_price * 100
            if side == "SELL":
                actual_capture = (entry_price - exit_price) / entry_price * 100
            mfe_capture_pct = (actual_capture / mfe_pct * 100) if mfe_pct > 0 else 0

        # ── Generate observation codes ──
        codes = []
        notes = []

        # BIG winner detection (>3R)
        is_big_winner = r_multiple > 3.0
        if is_big_winner:
            codes.append("BIG")
            notes.append(f"Big winner: {r_multiple:.1f}R (${pnl:+.2f})")

        # SEQ: part of a re-entry sequence
        seq_stats = self.reentry_tracker.get_sequence_stats(symbol, side)
        seq_pos = seq_stats.get("entry_count", 1) - 1
        if seq_pos > 0:
            codes.append("SEQ")
            cum_pnl = seq_stats.get("cumulative_pnl", 0)
            notes.append(
                f"Re-entry #{seq_pos} in sequence. Cumulative: ${cum_pnl + pnl:+.2f}"
            )

        # RRD: R:R degraded
        if rr > 0 and rr < 1.5:
            codes.append("RRD")
            notes.append(f"R:R only {rr:.1f}:1 at entry (below 1.5 threshold)")

        # PDR: price drifting against position (reversal/bounce)
        if pnl < 0:
            if side == "SELL" and exit_price > entry_price:
                drift_pct = (exit_price - entry_price) / entry_price * 100
                codes.append("PDR")
                notes.append(f"Bounce: price rose {drift_pct:.1f}% against short")
            elif side == "BUY" and exit_price < entry_price:
                drift_pct = (entry_price - exit_price) / entry_price * 100
                codes.append("PDR")
                notes.append(f"Drop: price fell {drift_pct:.1f}% against long")

        # TPG: TP was reachable but trailed back
        if mfe_pct > 0 and pnl <= 0:
            if tp1_price > 0:
                if side == "SELL" and lowest_price <= tp1_price:
                    codes.append("TPG")
                    notes.append(
                        f"Price reached TP1 zone (low=${lowest_price:.2f}, "
                        f"TP1=${tp1_price:.2f}) but reversed"
                    )
                elif side == "BUY" and peak_price >= tp1_price:
                    codes.append("TPG")
                    notes.append(
                        f"Price reached TP1 zone (high=${peak_price:.2f}, "
                        f"TP1=${tp1_price:.2f}) but reversed"
                    )

        # SLT: stop too tight (MAE was small relative to SL distance)
        if pnl < 0 and sl_dist > 0 and hold_time_s < 300:
            codes.append("SLT")
            notes.append(
                f"Stopped out in {hold_time_s/60:.0f}min — possible wick/noise"
            )

        # SLW: stop too wide (held loser >4hrs without improvement)
        if pnl < 0 and hold_time_s > 14400 and mfe_pct < 0.5:
            codes.append("SLW")
            notes.append(
                f"Held loser {hold_time_s/3600:.1f}hrs, MFE only {mfe_pct:.1f}% — "
                f"thesis was wrong, should have exited earlier"
            )

        # WPL: win prob was low
        if win_prob > 0 and win_prob < 0.50:
            codes.append("WPL")

        # ── Build reflection ──
        reflection = TradeReflection(
            timestamp=datetime.now(timezone.utc).isoformat(),
            symbol=symbol,
            side=side,
            entry=entry_price,
            exit_price=exit_price,
            pnl=pnl,
            hold_time_s=hold_time_s,
            leverage=leverage,
            confidence=confidence,
            regime=regime,
            exit_action=exit_action,
            codes=codes,
            notes=notes,
            sequence_id=f"{symbol}_{side}",
            sequence_position=seq_pos,
            r_multiple=round(r_multiple, 2),
            mfe_pct=round(mfe_pct, 2),
            mae_pct=round(mae_pct, 2),
            mfe_capture_pct=round(mfe_capture_pct, 1),
            daily_move_pct=round(
                self.exhaustion_detector.get_move_from_open(symbol, exit_price, side), 2
            ),
            atr_consumed_pct=0,  # Set by entry analysis
            reentry_count=seq_pos,
            win_prob_at_entry=round(win_prob, 4),
            ev_at_entry=round(ev, 4),
            rr_at_entry=round(rr, 2),
        )

        # Update sequence tracking
        self.reentry_tracker.record_close(symbol, side, pnl, is_big_winner)

        # Log reflection
        logger.info(f"[REFLECT] CLOSE {reflection.summary()}")
        for note in notes:
            logger.info(f"[REFLECT]   -> {note}")

        # Persist to JSONL
        self._save_reflection(reflection)

        # Track for periodic summary
        self._session_reflections.append(reflection)

        # Periodic self-assessment every 10 trades
        if self._trade_count % 10 == 0:
            self._generate_periodic_summary()

        return reflection

    def on_price_update(self, symbol: str, price: float) -> None:
        """Update price tracking for move exhaustion (call on each scan)."""
        self.exhaustion_detector.update_price(symbol, price)

    def _save_reflection(self, reflection: TradeReflection) -> None:
        """Append reflection to JSONL file."""
        _ensure_dir()
        try:
            with open(_REFLECTION_FILE, "a") as f:
                f.write(json.dumps(reflection.to_dict()) + "\n")
        except Exception as e:
            logger.warning(f"[REFLECT] Save failed: {e}")

    def _generate_periodic_summary(self) -> None:
        """Generate a summary of recent reflections (every 10 trades)."""
        recent = self._session_reflections[-10:]
        if not recent:
            return

        # Code frequency
        code_freq = defaultdict(int)
        for r in recent:
            for c in r.codes:
                code_freq[c] += 1

        # Win rate by code presence
        code_wr = defaultdict(lambda: {"wins": 0, "total": 0})
        for r in recent:
            for c in r.codes:
                code_wr[c]["total"] += 1
                if r.pnl > 0:
                    code_wr[c]["wins"] += 1

        # Sequence analysis
        seq_pnls = defaultdict(float)
        for r in recent:
            if r.sequence_id:
                seq_pnls[r.sequence_id] += r.pnl

        wins = sum(1 for r in recent if r.pnl > 0)
        losses = sum(1 for r in recent if r.pnl <= 0)
        net_pnl = sum(r.pnl for r in recent)
        avg_r = sum(r.r_multiple for r in recent) / len(recent) if recent else 0
        avg_mfe_capture = sum(r.mfe_capture_pct for r in recent) / len(recent) if recent else 0

        summary = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trade_count": self._trade_count,
            "window": len(recent),
            "wins": wins,
            "losses": losses,
            "net_pnl": round(net_pnl, 2),
            "avg_r_multiple": round(avg_r, 2),
            "avg_mfe_capture_pct": round(avg_mfe_capture, 1),
            "code_frequency": dict(code_freq),
            "code_win_rates": {
                k: round(v["wins"] / v["total"] * 100, 0) if v["total"] > 0 else 0
                for k, v in code_wr.items()
            },
            "sequence_net_pnls": {k: round(v, 2) for k, v in seq_pnls.items()},
            "observations": [],
        }

        # Generate observations
        for code, freq in sorted(code_freq.items(), key=lambda x: -x[1]):
            wr = code_wr[code]
            wr_pct = wr["wins"] / wr["total"] * 100 if wr["total"] > 0 else 0
            if wr_pct < 40 and freq >= 2:
                summary["observations"].append(
                    f"WARNING: {code} ({CODES.get(code, '?')}) appeared {freq}x "
                    f"with {wr_pct:.0f}% WR — likely losing pattern"
                )
            elif wr_pct > 70 and freq >= 2:
                summary["observations"].append(
                    f"EDGE: {code} appeared {freq}x with {wr_pct:.0f}% WR — "
                    f"working pattern"
                )

        # Log summary
        logger.info(
            f"[REFLECT] === PERIODIC SUMMARY (last {len(recent)} trades) === "
            f"{wins}W/{losses}L PnL=${net_pnl:+.2f} avgR={avg_r:+.2f} "
            f"MFE_capture={avg_mfe_capture:.0f}%"
        )
        for obs in summary["observations"]:
            logger.info(f"[REFLECT]   {obs}")

        # Persist
        _ensure_dir()
        try:
            with open(_SUMMARY_FILE, "a") as f:
                f.write(json.dumps(summary) + "\n")
        except Exception as e:
            logger.warning(f"[REFLECT] Summary save failed: {e}")

    def get_summary_for_agents(self, symbols: List[str] = None) -> Optional[str]:
        """Get compact reflection summary for LLM agent context.

        Returns a string like:
        'REFLECTION: SOL exhaustion=72%(HIGH) reentry#2 | BTC exhaustion=30%(LOW) CLEAN'
        Or None if no data.
        """
        try:
            parts = []

            # Get exhaustion data for tracked symbols
            tracked = symbols or list(self.exhaustion_detector._daily_high.keys())
            for sym in tracked[:5]:  # Cap at 5 symbols
                high = self.exhaustion_detector._daily_high.get(sym, 0)
                low = self.exhaustion_detector._daily_low.get(sym, 0)
                if high <= 0 or low <= 0:
                    continue
                range_pct = self.exhaustion_detector.get_daily_range_pct(sym)
                level = "HIGH" if range_pct > 4.0 else "MED" if range_pct > 2.0 else "LOW"

                # Re-entry sequences
                seq_info = ""
                for side in ["BUY", "SELL"]:
                    seq = self.reentry_tracker.get_sequence_stats(sym, side)
                    count = seq.get("entry_count", 0)
                    if count > 1:
                        cum = seq.get("cumulative_pnl", 0)
                        seq_info += f" reentry#{count}({side[:1]})=${cum:+.1f}"

                parts.append(f"{sym} range={range_pct:.1f}%({level}){seq_info}")

            # Recent session quality
            if self._session_reflections:
                recent = self._session_reflections[-10:]
                wins = sum(1 for r in recent if r.pnl > 0)
                losses = len(recent) - wins
                codes = []
                for r in recent:
                    codes.extend(r.codes)
                # Most frequent warning codes
                if codes:
                    from collections import Counter
                    top_codes = Counter(codes).most_common(3)
                    code_str = " ".join(f"{c}={n}" for c, n in top_codes)
                    parts.append(f"last{len(recent)}: {wins}W/{losses}L codes=[{code_str}]")

            if not parts:
                return None
            return "REFLECTION: " + " | ".join(parts)
        except Exception as e:
            logger.debug(f"Reflection summary failed: {e}")
            return None

    def get_entry_quality_score(self, symbol: str, side: str,
                                entry_price: float, confidence: float,
                                regime: str, atr: float = 0,
                                win_prob: float = 0) -> Dict[str, Any]:
        """Score an entry BEFORE opening. Returns quality assessment.

        Does NOT block trades — returns advisory score and codes.
        Can be used downstream to adjust sizing.
        """
        # Check re-entry status
        same_dir = [
            e for e in self.reentry_tracker._entries.get(symbol, [])
            if e["side"] == side
        ]
        reentry_count = len(same_dir)

        # Check exhaustion
        exhaustion = self.exhaustion_detector.check_exhaustion(
            symbol, entry_price, side, atr
        )

        codes = exhaustion["codes"][:]
        quality = 100  # Start at 100, deduct for issues

        if reentry_count >= 3:
            quality -= 30
            codes.append("RE3")
        elif reentry_count >= 1:
            quality -= 10
            codes.append("RE1")

        if same_dir:
            last_price = same_dir[-1]["price"]
            if (side == "SELL" and entry_price > last_price) or \
               (side == "BUY" and entry_price < last_price):
                quality -= 20
                codes.append("RE2")

        if win_prob > 0 and win_prob < 0.50:
            quality -= 25
            codes.append("WPL")

        if "MEX" in codes:
            quality -= 20
        if "EXH" in codes:
            quality -= 15

        return {
            "quality_score": max(0, quality),
            "codes": codes,
            "reentry_count": reentry_count,
            "advisory": "STRONG" if quality >= 80 else "CAUTION" if quality >= 50 else "WEAK",
        }
