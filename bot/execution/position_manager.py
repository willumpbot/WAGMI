"""
Position manager with state machine, progressive trailing stop, and dynamic TP1.

State machine: IDLE -> OPEN -> TP1_HIT -> TRAILING -> CLOSED
                        |                              |
                        +-- CLOSED (SL, EARLY_EXIT) ---+

Exit behavior is driven by TradeProfile (entry_type + regime + volatility):
- SCALP:  tight SL/TP, high TP1%, tight trailing, very short hold
- MEDIUM: balanced SL/TP, medium TP1%, medium trailing
- TREND:  wide SL/TP, low TP1%, loose trailing, let winners run
- REGIME: conservative defaults

Flow:
1. Open position (IDLE -> OPEN) with TradeProfile attached
2. Monitor price each tick
3. Early exit check (OPEN -> CLOSED if momentum reverses hard)
4. If TP1 hit: partial close (% from profile), SL -> breakeven
5. Trailing stop tightens per profile curve (tight/medium/loose)
6. Profit lock floor per profile (varies by entry_type)
7. If TP2 hit or trailing stop triggered (TRAILING -> CLOSED)
"""

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, List, Any

from execution.position_state import (
    IDLE, OPEN, TP1_HIT, TRAILING, CLOSED, transition,
)
from execution.precision import round_price, round_qty
from execution.trade_profile import TradeProfile, ExitParams, MEDIUM, _BASE_PROFILES


def _env_float(name: str, default: float) -> float:
    """Read a float from environment, fall back to default."""
    val = os.environ.get(name)
    if val is not None:
        try:
            return float(val)
        except (ValueError, TypeError):
            pass
    return default


def _env_bool(name: str, default: bool) -> bool:
    """Read a bool from environment, fall back to default."""
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")

# Mechanical bot instrumentation (TIER 4)
try:
    from llm.mechanical_bot_instrumentation import get_mechanical_bot_instrumentation
    _MECHANICAL_BOT_INSTRUMENTATION_AVAILABLE = True
except ImportError:
    _MECHANICAL_BOT_INSTRUMENTATION_AVAILABLE = False

logger = logging.getLogger("bot.execution.positions")


def _get_tel():
    """Lazy import to avoid circular dependency."""
    try:
        from core.structured_logging import get_trade_event_logger
        return get_trade_event_logger()
    except Exception:
        return None


@dataclass
class Position:
    """Represents a trading position with full lifecycle state tracking."""
    symbol: str
    side: str               # "LONG" or "SHORT"
    entry: float
    qty: float
    sl: float               # current stop loss (may move with trailing)
    tp1: float
    tp2: float
    leverage: float = 1.0
    mode: str = "spot"      # "spot" or "leverage"
    strategy: str = ""
    confidence: float = 0.0

    # Position identity (Phase 0.3b, measurement-integrity): a stable,
    # unique id assigned once at OPEN and carried through the position's
    # entire lifecycle (persisted state, close event, ledger row, journal).
    # Replaces fragile value-tuple dedup (symbol, entry, exit, pnl), which
    # false-positives on a genuine second identical trade and
    # false-negatives on re-fires. See core/position_journal.py.
    position_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    atr: float = 0.0            # ATR at entry (for progressive trailing)
    tp1_close_pct: float = 0.5  # fraction to close at TP1 (matches MEDIUM profile default)

    # State machine
    state: str = IDLE
    state_path: List[str] = field(default_factory=lambda: [IDLE])
    original_qty: float = 0.0
    original_sl: float = 0.0

    # Timestamp tracking
    opened_at: Optional[Any] = None  # datetime when position opened

    # Entry reasons: WHY we opened this position (for EV analysis)
    entry_reasons: Dict[str, Any] = field(default_factory=dict)

    # Trade profile: drives exit behavior (TP1%, trailing, floors)
    trade_profile: Optional[TradeProfile] = None

    # Trailing stop
    trailing_distance: float = 0.0  # absolute distance from peak
    peak_price: float = 0.0         # best price since TP1

    # MFE/MAE tracking (max favorable / adverse excursion from entry)
    highest_price: float = 0.0      # highest price seen during position lifetime
    lowest_price: float = 0.0       # lowest price seen during position lifetime

    # Timestamps
    open_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    close_time: Optional[datetime] = None

    # PnL tracking
    realized_pnl: float = 0.0
    fees_paid: float = 0.0
    funding_costs: float = 0.0  # Cumulative funding payments (positive = cost paid)

    # Outcome classification (set on close)
    outcome: str = ""  # CLEAN_WIN, CLEAN_LOSS, TP1_ONLY, TP1_THEN_SL, etc.

    # Wallet attribution (dual-wallet system)
    wallet_id: str = ""      # "A", "B", or "" (single-wallet mode)

    # LLM context: thesis and setup type for exit intelligence
    notes: str = ""          # LLM decision notes (THESIS:..., OUTLOOK:..., etc.)
    setup_type: str = ""     # Classified setup (trend_at_zone, zone_validated, etc.)

    def __post_init__(self):
        # Backward-compat: any construction path that explicitly passes a
        # falsy position_id (e.g. an old persisted dict with no key, loaded
        # via execution/auto_recovery.py::_dict_to_position before this
        # field existed) still gets a fresh, valid id rather than silently
        # carrying "" forward.
        if not self.position_id:
            self.position_id = uuid.uuid4().hex
        if self.original_qty == 0:
            self.original_qty = self.qty
        if self.original_sl == 0:
            self.original_sl = self.sl
        if self.peak_price == 0:
            self.peak_price = self.entry
        if self.highest_price == 0:
            self.highest_price = self.entry
        if self.lowest_price == 0:
            self.lowest_price = self.entry

    # ── Derived properties (backward compat) ──
    @property
    def status(self) -> str:
        return "closed" if self.state == CLOSED else "open"

    @property
    def filled_tp1(self) -> bool:
        return self.state in (TP1_HIT, TRAILING, CLOSED) and TP1_HIT in self.state_path

    @property
    def trailing_active(self) -> bool:
        return self.state == TRAILING

    @property
    def state_path_str(self) -> str:
        return "->".join(self.state_path)

    @property
    def mfe(self) -> float:
        """Max favorable excursion: best unrealized profit during position."""
        if self.side == "LONG":
            return self.highest_price - self.entry
        return self.entry - self.lowest_price

    @property
    def mae(self) -> float:
        """Max adverse excursion: worst unrealized loss during position."""
        if self.side == "LONG":
            return self.entry - self.lowest_price
        return self.highest_price - self.entry

    def _transition(self, target: str, reason: str = "") -> str:
        """Transition to a new state, updating state_path."""
        new = transition(self.symbol, self.state, target, reason)
        if new != self.state:
            self.state = new
            self.state_path.append(new)
        return new


@dataclass
class TradeEvent:
    """Record of a trade action (open, partial close, full close)."""
    symbol: str
    action: str         # "OPEN", "TP1", "TP2", "SL", "TRAILING_STOP", "EARLY_EXIT", etc.
    side: str
    price: float
    qty: float
    pnl: float = 0.0
    fee: float = 0.0
    leverage: float = 1.0
    strategy: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Phase 0.4-A (T-TAX prereq): the originating Position's stable id (see
    # Position.position_id, :98/:147-152), so downstream close-pipeline
    # consumers can key events without falling back to (symbol, timestamp)
    # heuristics. Populated at all 4 construction sites from `pos.position_id`.
    # Defaults to "" only for events built without a live Position in scope
    # (none currently exist, but keep the default safe for future/test code).
    position_id: str = ""
    # TRADE_SUMMARY_PER_POSITION_FIX (2026-07-20): True only for the event that
    # terminates a position's lifecycle (created inside _close_position(), which
    # runs pos._transition(CLOSED, ...) — regardless of the `action`/reason
    # string, so "SL", "TP2", "TP1_FULL", "TIME_STOP", "LLM_EXIT_AGENT",
    # "CIRCUIT_BREAKER", a new reason added tomorrow, etc. are ALL covered
    # automatically with no whitelist to maintain). False for OPEN and for
    # partial/leg events (_partial_close_tp1's "TP1" leg, partial_close()'s
    # "PARTIAL_CLOSE"/"LLM_EXIT_PARTIAL" legs) — those don't end the position,
    # so they must never be counted as their own win/loss in get_trade_summary().
    is_position_close: bool = False


class PositionManager:
    """
    Manages all open positions with state-machine lifecycle.

    Bot-only mode: only manages positions it opened.
    One active position per symbol enforced.
    """

    def __init__(
        self,
        # 4.5 = Hyperliquid Tier-0 taker rate; matches TradingConfig.taker_fee_bps'
        # canonical default. Production always passes config.taker_fee_bps explicitly
        # (see multi_strategy_main.py) -- this default only fires for direct/test
        # construction without an explicit rate.
        taker_fee_bps: float = 4.5,
        enable_trailing: bool = True,
        trailing_atr_mult: float = 1.5,
        time_stop_hours: int = 12,
        hold_time_rules=None,  # Optional HoldTimeRuleManager for blocking early exits
        # Safe-by-default: True ONLY for the real live/paper trading engine
        # (multi_strategy_main.py's self.pos_mgr / wallet A / wallet B).
        # Gates whether this instance's closes are allowed to mutate the
        # shared, on-disk momentum_state.json (see _record_momentum_outcome
        # below). Backtest, replay, scenario_sim, and all test constructions
        # intentionally leave this at the default False so a fabricated/
        # simulated close can never flip the book-level after-loss
        # multiplier or a symbol's win/loss streak for real trading.
        is_live: bool = False,
    ):
        self.positions: Dict[str, Position] = {}
        self.trade_log: List[TradeEvent] = []
        self.taker_fee_bps = taker_fee_bps
        self.enable_trailing = enable_trailing
        self.trailing_atr_mult = trailing_atr_mult
        self._time_stop_hours = time_stop_hours
        self.hold_time_rules = hold_time_rules  # Optional HoldTimeRuleManager
        self.is_live = is_live
        # LIVING VALUES (2026-07-15): the frozen "2,172-signal analysis" table
        # was contradicted by the realized ledger (BTC_BUY claimed 69% WR /
        # 8h-optimal but realized 35% WR / -$2.25/tr with all >2h buckets
        # negative; ETH_SELL's biggest realized wins land in 8-12h, not the
        # 4-8h the table pressured it into; XRP_*/HYPE_SELL were omitted and
        # fell back to a *longer* 12h default than the tabulated setups).
        # Replaced with a live per-SYMBOL_SIDE computation from
        # paper_trades/trades_*.csv (see _compute_live_setup_time_stops).
        # n<13 setups simply aren't in this dict and fall back to
        # self._time_stop_hours (12h) at the lookup site.
        self._setup_time_stops = self._compute_live_setup_time_stops()
        self._setup_time_stops_refreshed_at = datetime.now(timezone.utc)
        # Post-close cooldown: prevent tilt re-entry after losses only
        self._last_close_time: Dict[str, datetime] = {}  # symbol -> close time
        self._last_close_won: Dict[str, bool] = {}  # symbol -> was it a win?
        self._reentry_cooldown_minutes: int = 10  # 10 min cooldown after losses only
        # Position backup directory for crash recovery
        self._backup_dir = Path("data") / "position_backups"
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        # FUNDING_ACCRUAL_CADENCE_FIX (2026-07-20): accrue_funding() used to
        # hardcode scan_interval_s=30.0 regardless of the CALLER's real
        # cadence (multi_strategy_main.py calls it once per symbol per scan
        # cycle, whose actual wall-clock length varies with adaptive scan
        # interval + per-symbol LLM pipeline time — minutes, not 30s, under
        # slow-scan/low-power operation). Reported funding was ~60-200x too
        # small as a result. Fixed by measuring REAL elapsed wall-clock time
        # between consecutive accrue_funding() calls per symbol instead of
        # assuming a constant. Keyed per-symbol so overlapping/rotated
        # positions on different symbols don't share a clock.
        self._last_funding_accrual_ts: Dict[str, datetime] = {}
        # FEE_ACCOUNTING_FIX visibility (2026-07-20): the notional-methodology
        # fix itself stays gated off-by-default (rewriting realized_pnl/fees_paid
        # feeds circuit breakers + Kelly/EV sizing + learning aggregates, so it
        # needs a reviewed backtest before flipping). This flag only makes the
        # KNOWN understatement visible in logs instead of silent -- fires once
        # per process, on the first leveraged position's fee charge, so it
        # doesn't spam every scan cycle.
        self._fee_accounting_warned = False

    def _compute_live_setup_time_stops(self) -> Dict[str, float]:
        """Live per-SYMBOL_SIDE time stops derived from realized closes.

        Reads paper_trades/trades_*.csv, dedupes rows (excludes OPEN rows,
        TEST symbols, and price in {100,150,50000} test-fixture artifacts),
        groups net pnl (pnl-fee) by SYMBOL_SIDE and hold-hour bucket
        [0-2,2-4,4-6,6-8,8-12,12+], and for each setup with n>=13 closed
        trades sets time_stop_hours to the upper edge of the last bucket
        whose cumulative expectancy is still positive, clamped to [4,12]h.
        Setups with n<13 are simply omitted (caller falls back to
        self._time_stop_hours). Never raises — returns {} on any failure so
        the static self._time_stop_hours default takes over.
        """
        buckets = [(0.0, 2.0), (2.0, 4.0), (4.0, 6.0), (6.0, 8.0), (8.0, 12.0), (12.0, 999.0)]
        _test_prices = (100.0, 150.0, 50000.0)
        result: Dict[str, float] = {}
        try:
            import csv as _csv
            import glob as _glob

            rows_by_key: Dict[tuple, dict] = {}
            for path in _glob.glob(os.path.join("paper_trades", "trades_*.csv")):
                try:
                    with open(path, newline="") as f:
                        for row in _csv.DictReader(f):
                            action = (row.get("action") or "").upper()
                            if action == "OPEN":
                                continue
                            symbol = (row.get("symbol") or "").upper()
                            if not symbol or "TEST" in symbol:
                                continue
                            try:
                                price = float(row.get("price") or 0)
                            except (TypeError, ValueError):
                                continue
                            if price in _test_prices:
                                continue
                            dedup_key = (
                                symbol, action, row.get("side"), row.get("price"),
                                row.get("qty"), row.get("timestamp"),
                            )
                            rows_by_key[dedup_key] = row
                except Exception:
                    continue  # one bad/partial file shouldn't kill the whole computation

            grouped: Dict[str, Dict[int, List[float]]] = {}
            for row in rows_by_key.values():
                symbol = (row.get("symbol") or "").upper()
                base_sym = symbol.replace("/USDC:USDC", "").replace("/USDT:USDT", "").split("/")[0]
                side_raw = (row.get("side") or "").upper()
                side_label = "BUY" if side_raw in ("LONG", "BUY") else "SELL"
                key = f"{base_sym}_{side_label}"
                try:
                    hold_h = float(row.get("hold_time_s") or 0) / 3600.0
                    net = float(row.get("pnl") or 0) - float(row.get("fee") or 0)
                except (TypeError, ValueError):
                    continue
                bucket_idx = len(buckets) - 1
                for i, (lo, hi) in enumerate(buckets):
                    if lo <= hold_h < hi:
                        bucket_idx = i
                        break
                grouped.setdefault(key, {}).setdefault(bucket_idx, []).append(net)

            for key, bucket_map in grouped.items():
                n = sum(len(v) for v in bucket_map.values())
                if n < 13:
                    continue
                cumulative = 0.0
                last_positive_hi = None
                for i, (lo, hi) in enumerate(buckets):
                    cumulative += sum(bucket_map.get(i, []))
                    if cumulative > 0:
                        last_positive_hi = hi
                if last_positive_hi is not None:
                    result[key] = max(4.0, min(12.0, float(last_positive_hi)))
        except Exception as e:
            logger.warning(f"Live setup-time-stop computation failed, using static default: {e}")
            return {}
        return result

    def _maybe_refresh_setup_time_stops(self) -> None:
        """Refresh live per-setup time stops at most once per day (avoids
        re-reading the whole paper_trades/ ledger on every tick)."""
        now = datetime.now(timezone.utc)
        last = getattr(self, "_setup_time_stops_refreshed_at", None)
        if last is not None and (now - last).total_seconds() < 86400:
            return
        try:
            live = self._compute_live_setup_time_stops()
            self._setup_time_stops = live  # {} is valid -- means "no n>=13 setups yet"
        except Exception as e:
            logger.debug(f"Setup time-stop refresh skipped: {e}")
        finally:
            self._setup_time_stops_refreshed_at = now

    def _pnl_lev(self, leverage: float) -> float:
        # PNL_LEVERAGE_FIX (default off): coordinator sizes qty as FULL
        # base-currency exposure (qty = risk$/stop_width, "do NOT multiply by
        # leverage"), so realized/unrealized pnl and funding notional must NOT
        # re-apply leverage. Default off preserves current (leverage-inflated)
        # behavior; correct base semantics needs PNL_LEVERAGE_FIX=true AND
        # FEE_ACCOUNTING_FIX=false (paired). Flip only after a reviewed replay.
        if os.getenv("PNL_LEVERAGE_FIX", "false").lower() in ("1", "true", "yes"):
            return 1.0
        return leverage

    def _fee(self, price: float, qty: float, leverage: float = 1.0) -> float:
        # FEE_ACCOUNTING_FIX (default off): charge fees on true notional
        # (price*qty*leverage) to match pnl = move*qty*leverage (L1216/1467/1710)
        # and funding notional = entry*qty*leverage (accrue_funding L334).
        if os.getenv("FEE_ACCOUNTING_FIX", "false").lower() in ("1", "true", "yes"):
            return price * qty * max(leverage, 1.0) * (self.taker_fee_bps / 10000.0)
        if leverage > 1.0 and not self._fee_accounting_warned:
            self._fee_accounting_warned = True
            logger.warning(
                "FEE_ACCOUNTING_FIX=false: leveraged-position fees understated "
                "~%.1fx vs true notional (charging on price*qty, not "
                "price*qty*leverage). Corrected-and-ready behind the flag; "
                "flip requires a reviewed replay backtest first.", leverage,
            )
        return price * qty * (self.taker_fee_bps / 10000.0)

    def _backup_position(self, pos: 'Position') -> None:
        """Persist position SL/TP to disk for crash recovery."""
        # Test-pollution guard (2026-07-02): pytest opening synthetic positions
        # was writing junk crash-backups into the production dir (e.g. ETH SHORT
        # @3000 test fixture found in data/position_backups/). Tests that set
        # pm._backup_dir to a tmp path are unaffected.
        if os.getenv("PYTEST_CURRENT_TEST") and self._backup_dir == Path("data") / "position_backups":
            return
        try:
            backup_file = self._backup_dir / f"{pos.symbol.replace('/', '_')}.json"
            backup_data = {
                "symbol": pos.symbol,
                "side": pos.side,
                "entry": pos.entry,
                "qty": pos.qty,
                "sl": pos.sl,
                "tp1": pos.tp1,
                "tp2": pos.tp2,
                "original_sl": pos.sl,
                "original_tp1": pos.tp1,
                "original_tp2": pos.tp2,
                "leverage": pos.leverage,
                "strategy": pos.strategy,
                "confidence": pos.confidence,
                "opened_at": pos.opened_at.isoformat() if pos.opened_at else None,
            }
            with open(backup_file, 'w') as f:
                json.dump(backup_data, f, indent=2)
            logger.debug(f"[{pos.symbol}] Position backup saved")
        except Exception as e:
            logger.warning(f"[{pos.symbol}] Position backup failed: {e}")

    def _remove_backup(self, symbol: str) -> None:
        """Remove position backup after successful close."""
        # Mirror of the _backup_position pytest guard: a test closing e.g. "SOL"
        # must never delete the real crash-backup of a live open SOL position.
        if os.getenv("PYTEST_CURRENT_TEST") and self._backup_dir == Path("data") / "position_backups":
            return
        try:
            backup_file = self._backup_dir / f"{symbol.replace('/', '_')}.json"
            if backup_file.exists():
                backup_file.unlink()
                logger.debug(f"[{symbol}] Position backup removed")
        except Exception as e:
            logger.warning(f"[{symbol}] Failed to remove position backup: {e}")

    def recover_from_backups(self) -> int:
        """Recover position data from disk backups after crash.

        Returns number of positions recovered.
        """
        recovered = 0
        for backup_file in self._backup_dir.glob("*.json"):
            try:
                with open(backup_file) as f:
                    data = json.load(f)
                symbol = data.get("symbol", "")
                if symbol and symbol not in self.positions:
                    logger.info(
                        f"[{symbol}] Found crash backup: "
                        f"SL={data.get('original_sl')} TP1={data.get('original_tp1')} "
                        f"TP2={data.get('original_tp2')}"
                    )
                    recovered += 1
                    # Note: actual position reconstruction requires exchange reconciliation.
                    # This backup provides the original SL/TP values that would otherwise be lost.
            except Exception as e:
                logger.warning(f"Failed to read position backup {backup_file}: {e}")
        if recovered > 0:
            logger.warning(f"Found {recovered} position backup(s) from previous session")
        return recovered

    def accrue_funding(self, symbol: str, funding_rate: float, interval_hours: float = 8.0) -> None:
        """Accumulate funding cost on an open position.

        In paper trading, funding isn't deducted automatically like on exchange.
        Call this every tick to track the real cost of holding.

        Args:
            symbol: Position symbol
            funding_rate: Funding rate per interval (e.g., 0.0001 = 0.01% per 8h)
            interval_hours: Funding interval in hours (default 8h for Hyperliquid)
        """
        if symbol not in self.positions:
            return
        pos = self.positions[symbol]
        if pos.state == CLOSED or pos.qty <= 0:
            return
        # Funding cost per call: rate * notional * (elapsed_time / interval).
        # FUNDING_ACCRUAL_CADENCE_FIX (2026-07-20): the original code hardcoded
        # scan_interval_s=30.0 regardless of the CALLER's real cadence
        # (multi_strategy_main.py calls this once per symbol per scan cycle,
        # whose actual wall-clock length varies with the adaptive scan
        # interval + per-symbol LLM pipeline time — minutes, not 30s, under
        # slow-scan/low-power operation). That silently understated funding
        # ~60-200x. Fixed accrual LIVE-measures the real elapsed time between
        # consecutive calls per symbol instead of assuming a constant.
        #
        # This changes pos.funding_costs, which feeds realized_pnl at final
        # close (-> the per-symbol daily loss-limit circuit breaker in
        # multi_strategy_main.py) and all downstream learning/reporting —
        # same category of change as FEE_ACCOUNTING_FIX above. Gated
        # off-by-default for the same reason: flip FUNDING_ACCRUAL_CADENCE_FIX=true
        # deliberately once validated, don't let it silently change realized
        # PnL / circuit-breaker timing for a running paper/live session.
        if os.getenv("FUNDING_ACCRUAL_CADENCE_FIX", "false").lower() in ("1", "true", "yes"):
            now = getattr(self, "_sim_now", None) or datetime.now(timezone.utc)
            last = self._last_funding_accrual_ts.get(symbol)
            self._last_funding_accrual_ts[symbol] = now
            if last is None:
                # First call since this position opened (or since process
                # restart, which resets this in-memory dict): no prior
                # timestamp to measure real elapsed time against. Skip this
                # tick rather than guess a duration — the next call has a
                # valid baseline. Self-corrects within one cycle; never
                # fabricates a duration.
                return
            elapsed_s = (now - last).total_seconds()
            if elapsed_s <= 0:
                return
            fraction_of_interval = elapsed_s / (interval_hours * 3600)
        else:
            # Legacy behavior (default, unchanged): hardcoded 30s-per-call
            # approximation. Known to be ~60-200x understated under
            # slow-scan/low-power cadence; kept as-is until the flag above
            # is deliberately enabled.
            scan_interval_s = 30.0
            fraction_of_interval = scan_interval_s / (interval_hours * 3600)
        notional = pos.entry * pos.qty * self._pnl_lev(pos.leverage)
        if os.getenv("FUNDING_SIGNED_ACCRUAL", "false").lower() in ("1", "true", "yes"):
            # Signed carry (2026-07-14 funding_asymmetric fix): LONG pays when
            # rate > 0, SHORT pays when rate < 0; negative accrual = funding
            # EARNED (credit). Matches funding_timer.should_close_before_funding
            # sign logic. Default OFF; revert by unsetting the flag.
            signed_rate = funding_rate if pos.side == "LONG" else -funding_rate
            pos.funding_costs += signed_rate * notional * fraction_of_interval
        else:
            cost = abs(funding_rate) * notional * fraction_of_interval
            if cost > 0:
                pos.funding_costs += cost

    def has_open_position(self, symbol: str) -> bool:
        """Check if there is an open (non-CLOSED) position for this symbol."""
        existing = self.positions.get(symbol)
        return existing is not None and existing.state != CLOSED

    def open_position(
        self,
        symbol: str,
        side: str,
        entry: float,
        qty: float,
        sl: float,
        tp1: float,
        tp2: float,
        atr: float = 0.0,
        leverage: float = 1.0,
        mode: str = "spot",
        strategy: str = "",
        confidence: float = 0.0,
        tp1_close_pct: float = 0.5,  # Match MEDIUM profile default
        entry_reasons: Optional[Dict[str, Any]] = None,
        trade_profile: Optional[TradeProfile] = None,
        notes: str = "",
        setup_type: str = "",
    ) -> Optional[Position]:
        """Open a new position. Enforces one position per symbol.

        Returns None if a position already exists for this symbol (any direction).
        This is the last line of defense against duplicate position opens.
        """
        # Don't open if already have a position in this symbol
        existing = self.positions.get(symbol)
        if existing and existing.state != CLOSED:
            logger.warning(
                f"[{symbol}] DUPLICATE BLOCKED in PositionManager: "
                f"already have {existing.side} position in state {existing.state} "
                f"(entry={existing.entry}, qty={existing.qty}, leverage={existing.leverage}x). "
                f"Attempted new {side} entry at {entry} with {leverage}x leverage."
            )
            return None

        # Post-close cooldown: only after losses (prevent tilt re-entry)
        # Winners can re-enter immediately — the thesis was right, re-entry is valid
        last_close = self._last_close_time.get(symbol)
        if last_close is not None and not self._last_close_won.get(symbol, True):
            _now = getattr(self, '_sim_now', None) or datetime.now(timezone.utc)
            elapsed = (_now - last_close).total_seconds() / 60.0
            if elapsed < self._reentry_cooldown_minutes:
                logger.warning(
                    f"[{symbol}] COOLDOWN BLOCKED: only {elapsed:.0f}m since last LOSS "
                    f"(need {self._reentry_cooldown_minutes}m). Skipping {side} entry."
                )
                return None

        # HARD SAFETY: Never open a position without a stop loss.
        # Sniper trades with sl=0 caused -$330 in catastrophic losses (4 trades, no SL).
        if sl <= 0 or abs(entry - sl) / max(entry, 1) < 0.001:
            logger.error(
                f"[{symbol}] REJECTED: No valid stop loss (sl={sl}, entry={entry}). "
                f"Every trade MUST have a stop loss. This is non-negotiable."
            )
            return None

        # FUNDING_ACCRUAL_CADENCE_FIX: defensive reset — if a stale accrual
        # timestamp survived from a prior position on this symbol (e.g. a
        # close path other than _close_position), don't let the first
        # accrue_funding() call on this NEW position measure elapsed time
        # against a flat/no-position gap. Belt-and-suspenders alongside the
        # pop() in _close_position.
        self._last_funding_accrual_ts.pop(symbol, None)

        # Apply precision rounding
        entry = round_price(symbol, entry)
        sl = round_price(symbol, sl)
        tp1 = round_price(symbol, tp1)
        tp2 = round_price(symbol, tp2)
        qty = round_qty(symbol, qty)
        if qty <= 0:
            logger.warning(f"[{symbol}] Qty rounds to 0, skipping")
            return None

        # Profile-driven trailing distance: SCALP=tight, TREND=loose
        # Fallback: when ATR=0, use profile-aware % of entry instead of flat 1%.
        _style_fallback_pct = {"tight": 0.006, "medium": 0.01, "loose": 0.015}
        _fb_style = trade_profile.exit_params.trailing_style if trade_profile else "medium"
        _trail_fallback = entry * _style_fallback_pct.get(_fb_style, 0.01) if entry > 0 else abs(entry - sl)
        if trade_profile:
            # Use profile's trailing style to scale the ATR multiplier
            style_mult = {
                "tight": 0.8, "medium": 1.0, "loose": 1.5, "none": 1.0,
            }.get(trade_profile.exit_params.trailing_style, 1.0)
            trailing_distance = atr * self.trailing_atr_mult * style_mult if atr > 0 else _trail_fallback
            # Profile overrides tp1_close_pct
            tp1_close_pct = trade_profile.exit_params.tp1_close_pct
        else:
            trailing_distance = atr * self.trailing_atr_mult if atr > 0 else _trail_fallback

        # Belt-and-suspenders (rank-2 fix): some entry paths (LLM-first, recovery) put the
        # confidence only inside entry_reasons and leave the confidence= arg at its 0.0 default,
        # which left pos.confidence=0.0 -> trades.csv confidence column was 81/85 zeros. Derive
        # it from entry_reasons so every downstream pos.confidence reader sees the real value.
        if (not confidence or confidence <= 0) and isinstance(entry_reasons, dict):
            _er_conf = entry_reasons.get("confidence") or (entry_reasons.get("llm_confidence") or 0) * 100
            if _er_conf:
                confidence = float(_er_conf)

        pos = Position(
            symbol=symbol,
            side=side,
            entry=entry,
            qty=qty,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            leverage=leverage,
            mode=mode,
            strategy=strategy,
            confidence=confidence,
            atr=atr,
            tp1_close_pct=tp1_close_pct,
            trailing_distance=trailing_distance,
            entry_reasons=entry_reasons or {},
            trade_profile=trade_profile,
            notes=notes,
            setup_type=setup_type,
        )

        # State: IDLE -> OPEN
        pos._transition(OPEN, f"OPEN {side} @ {entry}")

        # Persist SL/TP to disk BEFORE adding to in-memory tracking
        self._backup_position(pos)

        self.positions[symbol] = pos

        # Write-ahead journal (Phase 0.3b): record OPEN synchronously so a
        # crash immediately after this point still leaves evidence that
        # this position existed, even if position_state.json itself never
        # made it to disk. Journaling is a safety net, not a gate -- never
        # let a journal failure block or crash a real open.
        try:
            from core.position_journal import journal_open
            journal_open(pos.position_id, {"side": side, "entry": entry, "qty": qty}, symbol=symbol)
        except Exception:
            logger.debug(f"[{symbol}] [POSITION-JOURNAL] journal_open failed (non-fatal)", exc_info=True)

        fee = self._fee(entry, qty, leverage)
        pos.fees_paid += fee

        event = TradeEvent(
            symbol=symbol,
            action="OPEN",
            side=side,
            price=entry,
            qty=qty,
            fee=fee,
            leverage=leverage,
            strategy=strategy,
            position_id=pos.position_id,
            metadata={
                "entry_reasons": entry_reasons or {},
                "confidence": confidence,
            },
        )
        self.trade_log.append(event)

        # ── TIER 4: Mechanical Bot Instrumentation (Position Opening Hook) ──
        # Record position opening with all context
        if _MECHANICAL_BOT_INSTRUMENTATION_AVAILABLE:
            try:
                instr = get_mechanical_bot_instrumentation()
                instr.on_position_opened(
                    symbol=symbol,
                    side=side,
                    entry_price=entry,
                    qty=qty,
                    sl=sl,
                    tp1=tp1,
                    tp2=tp2,
                    leverage=leverage,
                    confidence=confidence,
                    strategy=strategy,
                    entry_reasons=entry_reasons or {},
                    notes=notes,
                    setup_type=setup_type,
                )
            except Exception as e:
                logger.debug(f"[{symbol}] Mechanical bot instrumentation error (position opening): {e}")

        entry_type = trade_profile.entry_type if trade_profile else "UNKNOWN"
        logger.info(
            f"[{symbol}] OPEN {side} @ {entry} qty={qty} "
            f"SL={sl} TP1={tp1} TP2={tp2} "
            f"leverage={leverage}x tp1_close={tp1_close_pct:.0%} "
            f"type={entry_type}"
        )

        # Log TRADE_OPENED event
        try:
            tel = _get_tel()
            if tel is not None:
                tel.log(
                    "TRADE_OPENED",
                    symbol,
                    side=side,
                    entry=entry,
                    sl=sl,
                    tp1=tp1,
                    tp2=tp2,
                    leverage=leverage,
                    position_size=qty,
                    strategy=strategy,
                    confidence=confidence,
                    atr=atr,
                    regime=(entry_reasons or {}).get("regime", ""),
                    entry_type=entry_type,
                )
        except Exception:
            pass

        return pos

    def update_price(
        self, symbol: str, current_price: float, df_5m=None, sim_now: datetime = None
    ) -> List[TradeEvent]:
        """
        Process a price update for a position.
        Checks SL, early exit, TP1, trailing stop, TP2 in order.
        SL is checked first to prevent early exit from closing at a worse price.
        df_5m: optional 5m DataFrame for momentum-based early exit.
        sim_now: simulated current time (for backtest; uses datetime.now(UTC) if None).
        """
        if symbol not in self.positions:
            return []

        pos = self.positions[symbol]
        if pos.state == CLOSED:
            return []

        # Store sim_now for internal methods (time stop, TP1 speed calc)
        self._sim_now = sim_now

        events = []
        is_long = pos.side == "LONG"

        # Track MFE/MAE (max favorable/adverse excursion from entry)
        if current_price > pos.highest_price:
            pos.highest_price = current_price
        if current_price < pos.lowest_price:
            pos.lowest_price = current_price

        # 0a. PROFIT LOCK: move SL toward breakeven once we're up enough.
        # Never ride a winner back to a loser. We can always re-enter.
        #
        # Finding 22 trail audit (2026-04-16): old 0.3R trigger was firing
        # on market noise — at ~0.3% profit on a 1% stop, within normal
        # intraday wiggle. 58 historical trades closed within ±0.5% of
        # entry with no TP1 hit = -$47.77 of noise losses from this.
        #
        # Profile-aware thresholds (SHIP S1 2026-07-02 — exit-geometry backtest):
        #   SCALP:  0.8R -> BE, 1.2R -> lock 0.3R
        #   MEDIUM: 0.3R -> BE, 0.6R -> lock 0.3R  (env: PROFIT_LOCK_BE_R/LOCK_R)
        #   TREND:  1.5R -> BE, 2.0R -> lock 0.4R
        if pos.state == OPEN:
            sl_dist = abs(pos.entry - pos.original_sl)
            if sl_dist > 0:
                if is_long:
                    unrealized_r = (current_price - pos.entry) / sl_dist
                else:
                    unrealized_r = (pos.entry - current_price) / sl_dist

                # Determine profile-aware thresholds
                _entry_type = ""
                _prof = getattr(pos, "trade_profile", None)
                if _prof is not None:
                    _entry_type = getattr(_prof, "entry_type", "") or ""
                # SHIP-2026-04-20: raised thresholds + fee buffer on BE move.
                # Reversal study: 25% reversal at 0.5R, 6.7% at 1.5R. Old 0.6R
                # MEDIUM trigger sat in reversal zone; BE clamp at exact entry
                # (zero buffer) was hit by microstructure wicks. 5 independent
                # studies converged on this change.
                if _entry_type == "SCALP":
                    _be_trigger, _lock_trigger, _lock_frac = 0.8, 1.2, 0.3
                elif _entry_type == "TREND":
                    _be_trigger, _lock_trigger, _lock_frac = 1.5, 2.0, 0.4
                else:  # MEDIUM default (and unknown)
                    # SHIP S1 (2026-07-02): restore the Apr-1 "bread-and-butter"
                    # ratchet. EXIT_GEOMETRY_BACKTEST_2026-07-02 variant S3:
                    # BE 0.3R / lock 0.3R at 0.6R = +$1,589 vs -$344 at the
                    # live 1.2R/1.8R (n=90, 70% WR, max DD $570). Every variant
                    # with protection <=0.6R was strongly positive; every one
                    # >=0.8R negative. The 04-20 raise to 1.2/1.8 left a
                    # 0-1.19R unprotected dead zone (WIRING_AUDIT #4).
                    # Flag-revertible: PROFIT_LOCK_BE_R=1.2 PROFIT_LOCK_LOCK_R=1.8
                    # restores the previous behavior without a code change.
                    _be_trigger = _env_float("PROFIT_LOCK_BE_R", 0.3)
                    _lock_trigger = _env_float("PROFIT_LOCK_LOCK_R", 0.6)
                    _lock_frac = 0.3

                _sl_before_lock = pos.sl

                # Breakeven trigger — fee buffer escapes microstructure noise
                if unrealized_r >= _be_trigger:
                    fee_buffer = pos.entry * (self.taker_fee_bps * 2 / 10000.0 + 0.001)
                    be_sl = (pos.entry + fee_buffer) if is_long else (pos.entry - fee_buffer)
                    if is_long and pos.sl < be_sl:
                        pos.sl = be_sl
                        logger.info(
                            f"[{symbol}] PROFIT LOCK ({_entry_type or 'MEDIUM'}): "
                            f"{unrealized_r:.2f}R >= {_be_trigger:.1f}R trigger -> "
                            f"SL moved to breakeven+buffer {be_sl:.4f}"
                        )
                    elif not is_long and pos.sl > be_sl:
                        pos.sl = be_sl
                        logger.info(
                            f"[{symbol}] PROFIT LOCK ({_entry_type or 'MEDIUM'}): "
                            f"{unrealized_r:.2f}R >= {_be_trigger:.1f}R trigger -> "
                            f"SL moved to breakeven+buffer {be_sl:.4f}"
                        )

                # ── MFE TELEMETRY (data only — LLM decides) ──
                # Per principle "everything should provide data and opportunity to our
                # LLMs to make the most accurate decision" — we COMPUTE the profit-lock
                # signals here but DO NOT mechanically act on them. The values are
                # surfaced to the Exit Agent via position metadata so the LLM sees
                # them in its prompt context and can decide whether to tighten_sl,
                # partial_close, hold, or full_close based on the full picture
                # (regime, momentum, alpha-ops, thesis validity, etc).
                _atr = getattr(pos, "atr", 0) or 0
                _atr_pct = (_atr / pos.entry) if pos.entry > 0 else 0
                if is_long:
                    _mfe_pct_now = (current_price - pos.entry) / pos.entry
                    _peak_mfe_pct = max(0, (pos.highest_price - pos.entry) / pos.entry) if pos.highest_price else 0
                else:
                    _mfe_pct_now = (pos.entry - current_price) / pos.entry
                    _peak_mfe_pct = max(0, (pos.entry - pos.lowest_price) / pos.entry) if pos.lowest_price else 0
                _retrace_pct = ((_peak_mfe_pct - _mfe_pct_now) / _peak_mfe_pct) if _peak_mfe_pct > 0 else 0
                _fee_pct = (self.taker_fee_bps * 2 / 10000.0) + 0.001

                # Stash on position for the Exit Agent prompt-builder to read.
                # Naming: clear so the agent prompt can reference these.
                pos.mfe_pct_current = round(_mfe_pct_now, 5)
                pos.mfe_pct_peak = round(_peak_mfe_pct, 5)
                pos.mfe_retrace_pct = round(_retrace_pct, 3)
                pos.atr_pct = round(_atr_pct, 5)
                pos.fee_pct = round(_fee_pct, 5)

                # ── SHADOW-SL: dead-thesis time stop (SHADOW MODE ONLY, data
                # collection is unconditional so we start gathering evidence
                # now) ──
                # Validated design (needs_more_data recommendation): IF pos is
                # still OPEN (pre-TP1) AND held >= SL_DISCIPLINE_MIN_HOLD_H AND
                # peak MFE since entry never reached SL_DISCIPLINE_MFE_FLOOR_PCT
                # AND current unrealized pnl is negative -> this rule WOULD
                # close the position. We only LOG that (once per position, via
                # a guard attr, to avoid tick-spam) — this NEVER mutates pos.sl
                # or closes the position. SL_DISCIPLINE_ENFORCE is a NEW env
                # flag (default false) reserved to gate a real enforcement
                # path in a future change; no such enforcement path exists in
                # this codebase yet, so flipping the flag today has zero
                # effect on trading behavior — enforcement remains impossible
                # until a human both flips it AND ships enforcement code after
                # reviewing shadow output below.
                _sl_enforce = _env_bool("SL_DISCIPLINE_ENFORCE", False)
                if not getattr(pos, "_shadow_sl_logged", False):
                    _sl_min_hold_h = _env_float("SL_DISCIPLINE_MIN_HOLD_H", 3.0)
                    _sl_mfe_floor_pct = _env_float("SL_DISCIPLINE_MFE_FLOOR_PCT", 0.35)
                    _sl_now = sim_now or getattr(self, '_sim_now', None) or datetime.now(timezone.utc)
                    _sl_hold_hours = (_sl_now - pos.open_time).total_seconds() / 3600
                    _sl_unrealized_pnl = (
                        (current_price - pos.entry) * pos.qty if is_long
                        else (pos.entry - current_price) * pos.qty
                    )
                    _sl_would_exit = (
                        _sl_hold_hours >= _sl_min_hold_h
                        and (_peak_mfe_pct * 100) < _sl_mfe_floor_pct
                        and _sl_unrealized_pnl < 0
                    )
                    if _sl_would_exit:
                        pos._shadow_sl_logged = True
                        logger.info(
                            f"[SHADOW-SL] {symbol} side={pos.side} "
                            f"hold_h={_sl_hold_hours:.2f} "
                            f"mfe_pct_peak={_peak_mfe_pct * 100:.3f} "
                            f"mae_pct={round(pos.mae / pos.entry * 100, 4) if pos.entry else 0:.3f} "
                            f"unrealized_pnl={_sl_unrealized_pnl:.4f} "
                            f"entry={pos.entry:.6g} current_price={current_price:.6g} "
                            f"would_exit=true reason=dead_thesis_time_stop "
                            f"enforce_flag={_sl_enforce} (enforcement not implemented; log-only)"
                        )
                # Suggested-but-not-applied breakeven SL the LLM can pick up if it wants.
                pos.suggested_be_sl = round(
                    (pos.entry + pos.entry * _fee_pct) if is_long else (pos.entry - pos.entry * _fee_pct),
                    8
                )

                # Lock-in trigger (above breakeven)
                if unrealized_r >= _lock_trigger:
                    if is_long:
                        lock_sl = pos.entry + sl_dist * _lock_frac
                        if pos.sl < lock_sl:
                            pos.sl = lock_sl
                            logger.info(
                                f"[{symbol}] PROFIT LOCK {_lock_frac:.1f}R "
                                f"({_entry_type or 'MEDIUM'}): SL -> {lock_sl}"
                            )
                    else:
                        lock_sl = pos.entry - sl_dist * _lock_frac
                        if pos.sl > lock_sl:
                            pos.sl = lock_sl
                            logger.info(
                                f"[{symbol}] PROFIT LOCK {_lock_frac:.1f}R "
                                f"({_entry_type or 'MEDIUM'}): SL -> {lock_sl}"
                            )

                # SHADOW-S1 validation (telemetry only, no behavior): whenever
                # the ratchet moves SL, log what the pre-ship 1.2R/1.8R config
                # would have done, so the first post-ship closes can be
                # old-vs-new compared straight from the log.
                if pos.sl != _sl_before_lock and _entry_type not in ("SCALP", "TREND"):
                    _old_be, _old_lock = 1.2, 1.8
                    if unrealized_r >= _old_lock:
                        _old_wb = (pos.entry + sl_dist * 0.3) if is_long else (pos.entry - sl_dist * 0.3)
                        _old_desc = f"{_old_wb:.6g}"
                    elif unrealized_r >= _old_be:
                        _fb = pos.entry * (self.taker_fee_bps * 2 / 10000.0 + 0.001)
                        _old_wb = (pos.entry + _fb) if is_long else (pos.entry - _fb)
                        _old_desc = f"{_old_wb:.6g}"
                    else:
                        _old_desc = f"unprotected({_sl_before_lock:.6g})"
                    logger.info(
                        f"[{symbol}] SHADOW-S1: r={unrealized_r:.2f} "
                        f"new_sl={pos.sl:.6g} old_1.2/1.8_would_be={_old_desc}"
                    )

        # 0b. Check stop loss — on flash crashes, SL must fire before early exit
        sl_hit = (current_price <= pos.sl) if is_long else (current_price >= pos.sl)
        if sl_hit:
            action = "TRAILING_STOP" if pos.state == TRAILING else "SL"
            event = self._close_position(pos, current_price, action)
            events.append(event)
            return events

        # 1a. Smart time stop: assess position health before closing.
        # Original logic: hard 8h cutoff. Problem: closes profitable trades approaching TP1.
        # New logic: check macro position health. Healthy positions get extensions (up to 12h max).
        # Sick positions (losing momentum, wrong direction) close at base time stop.
        if pos.state == OPEN:
            _now = sim_now or getattr(self, '_sim_now', None) or datetime.now(timezone.utc)
            hold_hours = (_now - pos.open_time).total_seconds() / 3600

            # Live per-SYMBOL_SIDE time stop (LIVING VALUES 2026-07-15 --
            # see _compute_live_setup_time_stops). No longer gated to BB-driver
            # setups only: that gate omitted XRP_*/HYPE_SELL and left them on
            # a longer 12h default than the tabulated BB setups got.
            self._maybe_refresh_setup_time_stops()
            _base_sym = symbol.replace("/USDC:USDC", "").replace("/USDT:USDT", "").split("/")[0]
            _side_label = "BUY" if is_long else "SELL"
            _setup_key = f"{_base_sym}_{_side_label}"
            time_stop_hours = self._setup_time_stops.get(
                _setup_key, getattr(self, '_time_stop_hours', 12)
            )

            if hold_hours >= time_stop_hours:
                # Assess position health before closing
                _health = self._assess_position_health(pos, current_price, df_5m)
                # Very healthy positions (score≥75) get double extension (8h vs 4h).
                # BTC SHORT #4 was closed at +$105 real PnL before hitting TP1 because
                # 12h + 4h = 16h max wasn't enough for a trending_bear move. At 20h max,
                # TP1 would have been reachable. Extension only applies if score ≥75 and
                # MFE retention is high (position isn't giving back gains).
                _health_score = _health.get("score", 0)
                _max_extension = 8.0 if _health_score >= 75 else 4.0
                _extension = _health.get("extension_hours", 0)
                _extended_stop = time_stop_hours + min(_extension, _max_extension)

                if hold_hours >= _extended_stop:
                    # TP1-proximity guard: if price is within 0.5% of TP1, extend 1h.
                    # Prevents closing 5 minutes before TP1 (BTC #4 incident: +$77 left
                    # on the table when TP1 was just minutes away at 16h).
                    _tp1 = getattr(pos, 'tp1', 0)
                    _is_long = pos.side == "LONG"
                    _tp1_dist_pct = 0.0
                    if _tp1 > 0 and current_price > 0:
                        if _is_long:
                            _tp1_dist_pct = (_tp1 - current_price) / current_price
                        else:
                            _tp1_dist_pct = (current_price - _tp1) / current_price
                    _tp1_very_close = 0 < _tp1_dist_pct < 0.005  # within 0.5%
                    if _tp1_very_close and pos.state not in ("TP1_HIT", "TRAILING"):
                        _extended_stop += 1.0
                        logger.info(
                            f"[{symbol}] TIME STOP DEFERRED 1h: TP1 within "
                            f"{_tp1_dist_pct*100:.2f}% ({current_price:.2f} -> {_tp1:.2f})"
                        )
                    if hold_hours < _extended_stop:
                        pass  # deferred — TP1 proximity extended stop, skip close this tick
                    else:
                        _reason = _health.get("reason", "time_expired")
                        # 2026-06-07: instead of mechanical close at TIME_STOP, flag the
                        # position for urgent Exit Agent review. The LLM sees current data
                        # (regime, momentum, OI/funding, alpha ops) and decides whether to
                        # close/tighten/hold. Mechanical close cost ~$20 on the BTC LONG
                        # winner this morning (cut at +$4, would have run to +$25).
                        # HARD safety: check_hold_limits() at 1.5x max_hold_hours still
                        # force-closes regardless — Exit Agent isn't allowed to hold forever.
                        if not getattr(pos, "_time_stop_review_requested", False):
                            pos._time_stop_review_requested = True
                            pos._time_stop_age_h = hold_hours
                            logger.info(
                                f"[{symbol}] TIME STOP -> EXIT AGENT REVIEW: held {hold_hours:.1f}h "
                                f">= {_extended_stop:.1f}h (base={time_stop_hours}h + ext={min(_extension, _max_extension):.1f}h) "
                                f"reason={_reason} health={_health_score:.0f}% — deferring close decision to LLM"
                            )
                        # Do NOT mechanically close here. Exit Agent (via
                        # position_wiring._check_llm_exit_suggestions) will see the
                        # _time_stop_review_requested flag and act. Hard fallback at
                        # 1.5x time_stop in check_hold_limits().
                else:
                    # Position is healthy — log extension and continue
                    if not hasattr(pos, '_extension_logged'):
                        logger.info(
                            f"[{symbol}] TIME STOP EXTENDED: {hold_hours:.1f}h held, "
                            f"extending to {_extended_stop:.1f}h (health={_health_score:.0f}% "
                            f"tp1_progress={_health.get('tp1_progress', 0):.0f}%)"
                        )
                        pos._extension_logged = True

        # 1a2. Data-driven 1h assessment: mechanical breakeven-tighten REMOVED
        # (LIVING VALUES 2026-07-15). This branch never fired live (0 '1H
        # ASSESSMENT' log lines, 0 SCALP entries ever across May30-Jul15
        # logs) yet held frozen 67%/56% WR premises. Ledger economics
        # contradict the acted-on conclusion: trades held >=1.5h with
        # mae>=0.1% (losing-at-1h proxy) are net +$77.63 (n=131, +$0.59/tr);
        # held >=3h with drawdown are net +$498.98 (n=92, +$5.42/tr); 84% of
        # that cohort touched >=+0.05% above entry, so a breakeven tighten
        # would have forfeited the recoveries that make the cohort
        # net-positive (the 2026-04-16 audit already conceded this is
        # survivor bias costing ~$87/30d). The tighten action is replaced
        # with a review flag so the live Exit Agent (the same
        # position_wiring._check_llm_exit_suggestions path that already
        # supersedes mechanical TIME_STOP closes above) adjudicates
        # losing-at-1h positions with live context instead of a mechanical
        # SL move. A mechanical tighten may only be reinstated once gated on
        # a live ledger computation of P(net-positive recovery | mae>=0.1%
        # at 1h, entry_type) and EV(hold) from paper_trades/*.csv with
        # n>=13 for that entry_type slice; n<13 must fall back to doing
        # nothing (no tighten), never to a guessed static number.
        if pos.state == OPEN:
            _now_1h = sim_now or getattr(self, '_sim_now', None) or datetime.now(timezone.utc)
            _hold_h = (_now_1h - pos.open_time).total_seconds() / 3600
            if 0.9 <= _hold_h <= 1.5:  # ~1h mark (window to avoid checking every tick)
                _pnl_pct = (current_price - pos.entry) / pos.entry if is_long else (pos.entry - current_price) / pos.entry
                if _pnl_pct < -0.001 and not getattr(pos, "_one_hour_loser_review_requested", False):
                    pos._one_hour_loser_review_requested = True
                    pos._one_hour_loser_pnl_pct = _pnl_pct
                    logger.info(
                        f"[{symbol}] 1H ASSESSMENT: losing ({_pnl_pct:.2%}) -> "
                        f"flagged for Exit Agent review (mechanical breakeven "
                        f"tighten removed, ledger-contradicted)"
                    )

        # 1b. Early exit telemetry: when mechanical conditions detect momentum
        # accelerating toward SL, publish to position for Exit Agent review rather
        # than auto-close. Backtests showed many "early exit" closes were trades
        # that would have gone green if held. Exit Agent reasons regime-aware
        # from this signal + full context instead of mechanical auto-close.
        #
        # LIVING VALUES (2026-07-15): the MECHANICAL_EARLY_EXIT_ENABLED
        # flag-gated auto-close branch was DELETED, not just left off-by-
        # default. Ledger check: 0 of 216 realized closes are EARLY_EXIT --
        # the mechanical path never fired, so the static per-regime
        # _EARLY_EXIT_THRESHOLDS table has zero realized sample backing it.
        # Deleting (rather than leaving the flag defaulted false) means a
        # future flag flip can no longer resurrect it. The live LLM Exit
        # Agent (coordinator.get_exit_intelligence via
        # core/position_wiring.py) remains the sole close authority for this
        # signal; _check_early_exit()'s advisory flag below is unchanged.
        if pos.state == OPEN and df_5m is not None:
            early = self._check_early_exit(pos, current_price, df_5m)
            if early:
                pos._early_exit_review_requested = True

        # 2. Check TP1 (dynamic partial close -> TP1_HIT -> TRAILING)
        if pos.state == OPEN:
            tp1_hit = (current_price >= pos.tp1) if is_long else (current_price <= pos.tp1)
            if tp1_hit:
                event = self._partial_close_tp1(pos, current_price)
                events.append(event)

        # 3. Update trailing stop (if in TRAILING state)
        if pos.state == TRAILING and self.enable_trailing:
            self._update_trailing_stop(pos, current_price)

        # 4. Check TP2 (full close)
        tp2_hit = (current_price >= pos.tp2) if is_long else (current_price <= pos.tp2)
        if tp2_hit and pos.state != CLOSED:
            event = self._close_position(pos, current_price, "TP2")
            events.append(event)

        # Log POSITION_UPDATE periodically (every ~60 ticks) when position is still open
        if pos.state != CLOSED and not events:
            _update_counter = getattr(pos, '_tel_update_counter', 0) + 1
            pos._tel_update_counter = _update_counter
            if _update_counter % 60 == 0:
                try:
                    tel = _get_tel()
                    if tel is not None:
                        if is_long:
                            _unrealized = (current_price - pos.entry) * pos.qty * self._pnl_lev(pos.leverage)
                        else:
                            _unrealized = (pos.entry - current_price) * pos.qty * self._pnl_lev(pos.leverage)
                        tel.log(
                            "POSITION_UPDATE",
                            symbol,
                            side=pos.side,
                            current_price=current_price,
                            unrealized_pnl=round(_unrealized, 2),
                            trailing_stop=pos.sl,
                            entry_price=pos.entry,
                            state=pos.state,
                            strategy=pos.strategy,
                        )
                except Exception:
                    pass

        return events

    def _assess_position_health(self, pos, current_price: float, df_5m=None) -> dict:
        """Assess macro health of a position to decide whether to extend time stop.

        Returns dict with:
            score: 0-100 health score (higher = healthier)
            extension_hours: recommended extension (0 = close now, up to 4h)
            reason: human-readable explanation
            tp1_progress: % of distance from entry to TP1 covered

        Health factors (each 0-25 points, total 0-100):
            1. TP1 progress — how close to TP1 vs SL (approaching TP1 = healthy)
            2. Profit direction — is position profitable? (in profit = healthy)
            3. Momentum — are recent candles moving in our direction? (tailwind = healthy)
            4. MFE retention — current price vs peak price (holding gains = healthy)
        """
        is_long = pos.side == "LONG"
        entry = pos.entry
        sl = pos.original_sl
        tp1 = pos.tp1

        # Calculate distances
        entry_to_tp1 = abs(tp1 - entry)
        entry_to_sl = abs(entry - sl)
        total_range = entry_to_tp1 + entry_to_sl

        if total_range == 0:
            return {"score": 0, "extension_hours": 0, "reason": "zero_range", "tp1_progress": 0}

        # Factor 1: TP1 progress (0-25 points)
        # How much of the entry->TP1 distance have we covered?
        if is_long:
            tp1_progress = max(0, (current_price - entry) / entry_to_tp1) if entry_to_tp1 > 0 else 0
        else:
            tp1_progress = max(0, (entry - current_price) / entry_to_tp1) if entry_to_tp1 > 0 else 0
        tp1_progress_pct = min(tp1_progress * 100, 100)
        tp1_score = min(25, tp1_progress * 25)  # 100% progress = 25 points

        # Factor 2: Profit direction (0-25 points)
        if is_long:
            pnl_pct = (current_price - entry) / entry * 100
        else:
            pnl_pct = (entry - current_price) / entry * 100
        if pnl_pct > 2.0:
            profit_score = 25  # Strongly profitable
        elif pnl_pct > 1.0:
            profit_score = 20
        elif pnl_pct > 0:
            profit_score = 15  # In profit
        elif pnl_pct > -1.0:
            profit_score = 5   # Small loss
        else:
            profit_score = 0   # Losing

        # Factor 3: Momentum (0-25 points) — uses 5m data if available
        momentum_score = 12  # Default neutral if no data
        if df_5m is not None and len(df_5m) >= 10:
            try:
                c = df_5m["close"].astype(float)
                last5 = c.iloc[-5:].values
                # Are we making higher lows (LONG) or lower highs (SHORT)?
                if is_long:
                    trending_up = last5[-1] > last5[0]  # Net positive over 25min
                    ema5 = float(c.ewm(span=5, adjust=False).mean().iloc[-1])
                    ema13 = float(c.ewm(span=13, adjust=False).mean().iloc[-1])
                    ema_bullish = ema5 > ema13
                else:
                    trending_up = last5[-1] < last5[0]
                    ema5 = float(c.ewm(span=5, adjust=False).mean().iloc[-1])
                    ema13 = float(c.ewm(span=13, adjust=False).mean().iloc[-1])
                    ema_bullish = ema5 < ema13

                if trending_up and ema_bullish:
                    momentum_score = 25  # Strong tailwind
                elif trending_up or ema_bullish:
                    momentum_score = 18  # Partial tailwind
                else:
                    momentum_score = 5   # Headwind
            except Exception:
                momentum_score = 12

        # Factor 4: MFE retention (0-25 points) — holding gains vs giving them back
        if is_long:
            peak = pos.highest_price
            mfe = (peak - entry) / entry * 100 if entry > 0 else 0
            current_gain = (current_price - entry) / entry * 100
        else:
            peak = pos.lowest_price
            mfe = (entry - peak) / entry * 100 if entry > 0 else 0
            current_gain = (entry - current_price) / entry * 100

        if mfe > 0:
            retention = current_gain / mfe if mfe > 0 else 0  # What % of peak gain we still have
        else:
            retention = 0

        if retention > 0.8:
            mfe_score = 25  # Holding 80%+ of peak gains
        elif retention > 0.5:
            mfe_score = 18  # Holding 50%+ of gains
        elif retention > 0.2:
            mfe_score = 10  # Gave back a lot but still positive
        else:
            mfe_score = 0   # Lost most/all gains

        # Total health score
        total_score = tp1_score + profit_score + momentum_score + mfe_score

        # Determine extension based on score
        if total_score >= 75:
            extension = 4.0  # Very healthy — extend maximum (8h -> 12h)
            reason = "very_healthy"
        elif total_score >= 60:
            extension = 3.0  # Healthy — extend 3h (8h -> 11h)
            reason = "healthy"
        elif total_score >= 45:
            extension = 1.5  # Mixed — small extension (8h -> 9.5h)
            reason = "mixed"
        elif total_score >= 30:
            extension = 0.5  # Weak — tiny extension (8h -> 8.5h)
            reason = "weak"
        else:
            extension = 0.0  # Unhealthy — close at base time stop
            reason = "unhealthy"

        logger.debug(
            f"[{pos.symbol}] Position health: score={total_score:.0f}/100 "
            f"(tp1={tp1_score:.0f} profit={profit_score:.0f} momentum={momentum_score:.0f} "
            f"mfe={mfe_score:.0f}) ext={extension:.1f}h tp1_progress={tp1_progress_pct:.0f}%"
        )

        return {
            "score": total_score,
            "extension_hours": extension,
            "reason": reason,
            "tp1_progress": tp1_progress_pct,
            "pnl_pct": pnl_pct,
            "retention": retention,
        }

    # Regime-adaptive early exit thresholds:
    # High-vol/range: cut losers earlier (price reverses fast)
    # Trending: let trades breathe longer (trend may resume)
    #
    # LIVING VALUES (2026-07-15) status: this table is now signal-only (see
    # the deleted MECHANICAL_EARLY_EXIT_ENABLED branch above -- it can never
    # directly close a position again), so it no longer meets the "acted-on
    # value" bar for a mandatory live conversion. It is flagged here because
    # it still SHAPES the advisory _early_exit_review_requested flag the
    # Exit Agent sees: trending_bull gets the loosest static gate (0.70
    # sl_progress / 3 conditions) despite being the worst realized regime
    # slice (-$29.46/trade, n=9) vs trending_bear's best (+$81.70/trade,
    # n=15). A live per-regime sl_progress trigger (e.g. MAE-depth beyond
    # which <35% of a regime's trades recovered to green, n>=13) was NOT
    # implemented here: paper_trades/trades_*.csv (which has mae_pct) does
    # not log regime, and the events that do log regime (trade_events.jsonl
    # TRADE_CLOSED, exit_closes.jsonl) don't log mae -- there is no single
    # ledger file position_manager.py can read to join regime+MAE per trade
    # without guessing a fragile cross-file match. Per the "don't guess on
    # live trading code" rule, this is left as the static n<13-style
    # fallback until a ledger file carries both fields together.
    _EARLY_EXIT_THRESHOLDS = {
        "high_volatility": {"sl_progress": 0.40, "conditions": 1},
        "panic":           {"sl_progress": 0.35, "conditions": 1},
        "range":           {"sl_progress": 0.45, "conditions": 2},
        "consolidation":   {"sl_progress": 0.50, "conditions": 2},
        "trending_bull":   {"sl_progress": 0.70, "conditions": 3},
        "trending_bear":   {"sl_progress": 0.70, "conditions": 3},
        "trend":           {"sl_progress": 0.70, "conditions": 3},
    }
    _DEFAULT_EARLY_EXIT = {"sl_progress": 0.65, "conditions": 3}

    def _check_early_exit(self, pos: Position, price: float, df_5m) -> bool:
        """
        Detect momentum reversal heading toward SL and cut early.
        Regime-adaptive: high-vol/range cut faster (1-2 conditions at 35-45%),
        trending lets trades breathe (3 conditions at 70%).

        Respects dynamic hold-time rules: blocks early exit if trade hasn't held long enough.
        """
        if df_5m is None or df_5m.empty or len(df_5m) < 15:
            return False

        # Check hold-time rules: block early exit if held less than regime minimum
        if self.hold_time_rules and pos.opened_at:
            try:
                from datetime import datetime, timezone
                hold_hours = (datetime.now(timezone.utc) - pos.opened_at).total_seconds() / 3600.0
                regime = (pos.entry_reasons or {}).get("regime", "unknown")
                if self.hold_time_rules.should_block_early_exit(regime, hold_hours):
                    return False
            except Exception:
                pass  # If hold-time check fails, allow early exit to proceed

        try:
            is_long = pos.side == "LONG"
            stop_dist = abs(pos.entry - pos.original_sl)
            if stop_dist == 0:
                return False

            if is_long:
                sl_progress = (pos.entry - price) / stop_dist
            else:
                sl_progress = (price - pos.entry) / stop_dist

            # If price already past SL (progress > 1.0), let the SL check handle it
            if sl_progress > 1.0:
                return False

            # Regime-adaptive thresholds
            _regime = (pos.entry_reasons or {}).get("regime", "unknown")
            _thresholds = self._EARLY_EXIT_THRESHOLDS.get(_regime, self._DEFAULT_EARLY_EXIT)
            _min_progress = _thresholds["sl_progress"]
            _min_conditions = _thresholds["conditions"]

            if sl_progress < _min_progress:
                return False

            # Count how many exit conditions are met
            _conditions_met = 0

            c = df_5m["close"].astype(float)
            last3 = c.iloc[-3:].values

            # Condition 1: 3 candles accelerating against position
            if is_long:
                accelerating = last3[2] < last3[1] < last3[0]
            else:
                accelerating = last3[2] > last3[1] > last3[0]
            if accelerating:
                _conditions_met += 1

            # Condition 2: EMA5 crossed against EMA13
            ema5 = float(c.ewm(span=5, adjust=False).mean().iloc[-1])
            ema13 = float(c.ewm(span=13, adjust=False).mean().iloc[-1])
            _ema_cross = (is_long and ema5 < ema13) or (not is_long and ema5 > ema13)
            if _ema_cross:
                _conditions_met += 1

            # Condition 3: SL progress is extreme (>80%)
            if sl_progress >= 0.80:
                _conditions_met += 1

            if _conditions_met >= _min_conditions:
                logger.info(
                    f"[{pos.symbol}] EARLY EXIT ({_regime}): {sl_progress:.0%} toward SL, "
                    f"{_conditions_met}/{_min_conditions} conditions met"
                )
                return True

        except Exception as e:
            logger.debug(f"[{pos.symbol}] Early exit check error: {e}")

        return False

    def _compute_live_tp1_runner_scaler(self) -> float:
        """Live runner-performance scaler for TP1 partial-close sizing.

        Pairs each action=TP1 row in paper_trades/trades_*.csv with the next
        exit row for the same symbol+side (the runner leg -- one active
        position per symbol is enforced, so a TP1 row is followed by exactly
        one subsequent close for that symbol+side), excluding TEST symbols
        and price in {100,150,50000} test-fixture artifacts.

        If n>=13 pairs: realized runner legs net-positive with win rate
        >=60% -> return 0.85 (scale toward keeping more runner; caller
        floors at 0.25). Realized runner legs net-negative -> return 1.10
        (scale toward taking more; caller caps at 0.90). Otherwise (mixed,
        inconclusive) -> 1.0 (no scaling). n<13 -> 1.0 (neutral; do NOT
        fall back to a guessed static boost). Never raises.
        """
        try:
            import csv as _csv
            import glob as _glob

            _test_prices = (100.0, 150.0, 50000.0)
            rows_by_key: Dict[tuple, dict] = {}
            for path in _glob.glob(os.path.join("paper_trades", "trades_*.csv")):
                try:
                    with open(path, newline="") as f:
                        for row in _csv.DictReader(f):
                            action = (row.get("action") or "").upper()
                            if action == "OPEN":
                                continue
                            symbol = (row.get("symbol") or "").upper()
                            if not symbol or "TEST" in symbol:
                                continue
                            try:
                                price = float(row.get("price") or 0)
                            except (TypeError, ValueError):
                                continue
                            if price in _test_prices:
                                continue
                            dedup_key = (
                                symbol, action, row.get("side"), row.get("price"),
                                row.get("qty"), row.get("timestamp"),
                            )
                            rows_by_key[dedup_key] = row
                except Exception:
                    continue

            by_symbol_side: Dict[tuple, list] = {}
            for row in rows_by_key.values():
                k = ((row.get("symbol") or "").upper(), (row.get("side") or "").upper())
                by_symbol_side.setdefault(k, []).append(row)

            runner_pnls: List[float] = []
            for rows in by_symbol_side.values():
                rows.sort(key=lambda r: r.get("timestamp") or "")
                pending_tp1 = False
                for row in rows:
                    action = (row.get("action") or "").upper()
                    if action == "TP1":
                        pending_tp1 = True
                        continue
                    if pending_tp1:
                        try:
                            net = float(row.get("pnl") or 0) - float(row.get("fee") or 0)
                        except (TypeError, ValueError):
                            pending_tp1 = False
                            continue
                        runner_pnls.append(net)
                        pending_tp1 = False

            n = len(runner_pnls)
            if n < 13:
                return 1.0
            wins = sum(1 for p in runner_pnls if p > 0)
            win_rate = wins / n
            net_total = sum(runner_pnls)
            if net_total >= 0 and win_rate >= 0.60:
                return 0.85  # ledger says: keep more runner
            if net_total < 0:
                return 1.10  # ledger says: take more (caller caps at 0.90)
            return 1.0
        except Exception as e:
            logger.debug(f"Live TP1 runner-scaler computation failed, using neutral 1.0: {e}")
            return 1.0

    def _partial_close_tp1(self, pos: Position, price: float) -> TradeEvent:
        """Close tp1_close_pct at TP1, move SL above breakeven, activate trailing."""
        # State: OPEN -> TP1_HIT -> TRAILING
        pos._transition(TP1_HIT, f"TP1 @ {price}")

        # Dynamic TP scaling: adjust close % using a live runner-performance
        # scaler (LIVING VALUES 2026-07-15). Previously three frozen
        # multipliers (overshoot>0.5 -> x1.20 cap 0.90; fast(<30min) -> x0.85;
        # slow-grind(>4h, non-trend) -> x1.10 cap 0.85) guessed a direction
        # per condition. The ledger contradicts two of the three: across all
        # paper_trades/trades_*.csv, TP1->runner leg pairs are 30/30
        # net-positive (avg +$30.42) -- runners have never lost after TP1
        # (breakeven-SL protected) -- yet the only branch that actually fired
        # live (x1.10 slow-grind, 2 hits: SOL 2026-06-25, HYPE 2026-07-03)
        # shrank two runners that both finished green. Per-branch time
        # slices are unverifiable from the ledger (TP1 rows historically
        # logged hold_time_s=0 -- fixed below), so a single ledger-derived
        # scaler now replaces all three conditional branches.
        _now_for_speed = getattr(self, '_sim_now', None) or datetime.now(timezone.utc)
        time_to_tp1_s = (_now_for_speed - pos.open_time).total_seconds()
        dynamic_close_pct = pos.tp1_close_pct
        if os.getenv("DYNAMIC_TP_SCALING", "true").lower() in ("1", "true", "yes"):
            # Only apply scaling if position was open > 60s (avoids test artifacts)
            if time_to_tp1_s > 60:
                _runner_scaler = self._compute_live_tp1_runner_scaler()
                if _runner_scaler != 1.0:
                    dynamic_close_pct = min(max(dynamic_close_pct * _runner_scaler, 0.25), 0.90)

            if dynamic_close_pct != pos.tp1_close_pct:
                logger.info(
                    f"[{pos.symbol}] Dynamic TP: close_pct "
                    f"{pos.tp1_close_pct:.0%} -> {dynamic_close_pct:.0%}"
                )

        close_qty = round_qty(pos.symbol, pos.qty * dynamic_close_pct)
        # Guard: if close_qty rounds to full qty, keep minimum remainder for trailing
        remaining_after = round_qty(pos.symbol, pos.qty - close_qty)
        if remaining_after <= 0 and pos.qty > close_qty:
            # Rounding ate everything — reduce close_qty to preserve minimum remainder
            close_qty = round_qty(pos.symbol, pos.qty * 0.90)  # Close 90% max
        if close_qty <= 0 or close_qty >= pos.qty:
            # Degenerate case: close everything as a full TP1 close
            return self._close_position(pos, price, "TP1_FULL")
        fee = self._fee(price, close_qty, pos.leverage)
        pos.fees_paid += fee

        if pos.side == "LONG":
            pnl = (price - pos.entry) * close_qty * self._pnl_lev(pos.leverage)
        else:
            pnl = (pos.entry - price) * close_qty * self._pnl_lev(pos.leverage)

        # Proportionally allocate funding costs to TP1 partial close
        # (prevents dumping all funding onto final close, distorting per-leg PnL)
        funding_share = pos.funding_costs * (close_qty / pos.qty) if pos.qty > 0 else 0.0
        # PNL_SEMANTICS_FIX (2026-07-20): capture this leg's own NET
        # contribution (fee + funding deducted) as a named value so the
        # trade_events.jsonl TP_HIT record below can log it directly instead
        # of the raw gross `pnl` local. See tel.log() call further down.
        tp1_net_leg_pnl = pnl - fee - funding_share
        pos.realized_pnl += tp1_net_leg_pnl
        pos.funding_costs -= funding_share  # Reduce remaining balance for final close
        pos.qty = round_qty(pos.symbol, pos.qty - close_qty)

        # Move SL to breakeven accounting for locked-in TP1 profit.
        # The remaining position has a cost basis adjusted by the profit already banked.
        # This prevents premature SL hits by giving the remaining qty more room.
        # Formula: breakeven = entry - (locked_pnl / (remaining_qty * leverage)) for LONG
        remaining_qty = pos.qty
        fee_buffer = pos.entry * (self.taker_fee_bps * 2 / 10000.0 + 0.001)
        if remaining_qty > 0 and pos.leverage > 0:
            # How much room does the locked-in profit give us?
            profit_cushion = pos.realized_pnl / (remaining_qty * self._pnl_lev(pos.leverage))
            if pos.side == "LONG":
                # Entry - cushion = adjusted breakeven (lower = more room)
                be_price = pos.entry - profit_cushion + fee_buffer
                pos.sl = round_price(pos.symbol, be_price)
            else:
                be_price = pos.entry + profit_cushion - fee_buffer
                pos.sl = round_price(pos.symbol, be_price)
        else:
            # Fallback to simple breakeven
            if pos.side == "LONG":
                pos.sl = round_price(pos.symbol, pos.entry + fee_buffer)
            else:
                pos.sl = round_price(pos.symbol, pos.entry - fee_buffer)

        pos.peak_price = price

        # TP1_HIT -> TRAILING
        pos._transition(TRAILING, "trailing activated")

        # ── TIER 4: Mechanical Bot Instrumentation (State Change Hook: TP1_HIT) ──
        if _MECHANICAL_BOT_INSTRUMENTATION_AVAILABLE:
            try:
                instr = get_mechanical_bot_instrumentation()
                instr.on_position_state_change(
                    symbol=pos.symbol,
                    from_state=TP1_HIT,
                    to_state=TRAILING,
                    trigger="TP1_HIT",
                    price=price,
                    context={
                        'partial_close_qty': close_qty,
                        'partial_close_pct': dynamic_close_pct,
                        'realized_pnl': pnl,
                        'new_sl': pos.sl,
                        'remaining_qty': pos.qty,
                    }
                )
            except Exception as e:
                logger.debug(f"[{pos.symbol}] Mechanical bot instrumentation error (state change): {e}")

        logger.info(
            f"[{pos.symbol}] TP1 @ {price} | Closed {close_qty} ({dynamic_close_pct:.0%}) | "
            f"PnL={pnl:.2f} | SL->BE+={pos.sl} | Trailing ON"
        )

        event = TradeEvent(
            symbol=pos.symbol,
            action="TP1",
            side=pos.side,
            price=price,
            qty=close_qty,
            pnl=pnl,
            fee=fee,
            leverage=pos.leverage,
            strategy=pos.strategy,
            position_id=pos.position_id,
            metadata={
                "remaining_qty": pos.qty,
                "new_sl": pos.sl,
                "tp1_close_pct": dynamic_close_pct,
                "funding_share": funding_share,  # funding allocated to this partial leg
                "entry_reasons": pos.entry_reasons,
                "num_agree": (pos.entry_reasons or {}).get("num_agree", 0),
                "strategies_agree": (pos.entry_reasons or {}).get("strategies_agree", []),
                "entry": pos.entry,
                "sl": pos.original_sl,
                "tp1": pos.tp1,
                "tp2": pos.tp2,
                "confidence": pos.confidence,
                # Measurement-bug fix (LIVING VALUES 2026-07-15): this used to
                # be absent, so downstream readers (multi_strategy_main.py's
                # event.metadata.get("hold_time_s", 0)) always logged 0 for
                # TP1 rows, making TP1->runner time-to-TP1 slices unverifiable
                # from the ledger. Now populated with actual elapsed seconds
                # from pos.open_time to this TP1 fill.
                "hold_time_s": time_to_tp1_s,
            },
        )
        self.trade_log.append(event)

        # Log TP_HIT event
        try:
            tel = _get_tel()
            if tel is not None:
                _hold_s = ((getattr(self, '_sim_now', None) or datetime.now(timezone.utc)) - pos.open_time).total_seconds()
                tel.log(
                    "TP_HIT",
                    pos.symbol,
                    side=pos.side,
                    exit_price=price,
                    entry_price=pos.entry,
                    # PNL_SEMANTICS_FIX (2026-07-20): was the GROSS leg pnl
                    # (no fee/funding deducted). Now the NET leg contribution,
                    # matching the units of the final-close event's `pnl`
                    # field below -- so summing `pnl` across a position's
                    # TP_HIT + terminal-close events equals the true total
                    # net trade pnl with zero overlap and zero unit mixing.
                    pnl=tp1_net_leg_pnl,
                    # Cumulative net pnl-to-date for this position (== what
                    # the OLD code mistakenly put in `pnl` on the final-close
                    # event). Consumers that want a running/"total so far"
                    # figure (e.g. Telegram alerts) should read this field,
                    # not `pnl`.
                    total_pnl=pos.realized_pnl,
                    fee=fee,
                    funding=funding_share,
                    hold_time=_hold_s,
                    partial_close_pct=dynamic_close_pct,
                    remaining_qty=pos.qty,
                    strategy=pos.strategy,
                )
        except Exception:
            pass

        return event

    def _update_trailing_stop(self, pos: Position, current_price: float):
        """
        Progressive trailing stop with profit lock floor.
        Tighten curve and floor are driven by TradeProfile when available:
        - SCALP:  fast tightening (0.80->0.50), early floor (20%)
        - MEDIUM: standard (0.67->0.33), floor at 30%
        - TREND:  slow tightening (0.50->0.25), late floor (35%)
        """
        is_long = pos.side == "LONG"

        if is_long:
            if current_price > pos.peak_price:
                pos.peak_price = current_price
        else:
            if current_price < pos.peak_price:
                pos.peak_price = current_price

        if is_long:
            total_range = pos.tp2 - pos.entry
            peak_move = pos.peak_price - pos.entry
        else:
            total_range = pos.entry - pos.tp2
            peak_move = pos.entry - pos.peak_price

        # SHIP S1/V2 (2026-07-02, WIRING_AUDIT #5 fix): post-TP1 progress is
        # measured FROM TP1, not from entry. The old entry-based formula
        # insta-locked ~57.5% of peak the moment TP1 filled (progress jumped
        # straight to the tp1/tp2 ratio), contradicting the cushion-BE set at
        # TP1. Exit backtest V2: ~free (-$9 total, +0.5R). This function only
        # runs in TRAILING state (post-TP1), so TP1-based progress is valid.
        _old_progress = min(peak_move / total_range, 1.0) if total_range > 0 else 0.0
        if is_long:
            _tp1_move = pos.tp1 - pos.entry
        else:
            _tp1_move = pos.entry - pos.tp1
        _post_tp1_range = total_range - _tp1_move
        if _post_tp1_range > 0 and _tp1_move > 0:
            progress = max(0.0, min((peak_move - _tp1_move) / _post_tp1_range, 1.0))
        else:
            progress = _old_progress

        # Profile-driven tighten curve (falls back to MEDIUM defaults)
        ep = pos.trade_profile.exit_params if pos.trade_profile else _BASE_PROFILES[MEDIUM]
        tighten_start = ep.trailing_tighten_start
        tighten_end = ep.trailing_tighten_end
        tighten_range = tighten_start - tighten_end
        tighten_factor = max(tighten_start - progress * tighten_range, tighten_end)
        effective_distance = pos.trailing_distance * tighten_factor

        if is_long:
            trailing_sl = pos.peak_price - effective_distance
        else:
            trailing_sl = pos.peak_price + effective_distance

        # Profile-driven profit lock floor
        floor_start = ep.floor_progress_start
        floor_lock_start = ep.floor_lock_start
        floor_lock_max = ep.floor_lock_max

        floor_sl = None
        if progress > floor_start and peak_move > 0:
            lock_pct = min(
                floor_lock_start + (progress - floor_start) * 0.5,
                floor_lock_max,
            )
            if is_long:
                floor_sl = pos.entry + peak_move * lock_pct
            else:
                floor_sl = pos.entry - peak_move * lock_pct
        elif peak_move > 0:
            # Minimum post-TP1 floor: guarantee at least breakeven + fees.
            # Without this, a sharp reversal after TP1 can erase the entire gain.
            fee_buffer = pos.entry * self.taker_fee_bps * 2 / 10000.0
            if is_long:
                floor_sl = pos.entry + fee_buffer
            else:
                floor_sl = pos.entry - fee_buffer

        new_sl = trailing_sl
        if floor_sl is not None:
            if is_long:
                new_sl = max(trailing_sl, floor_sl)
            else:
                new_sl = min(trailing_sl, floor_sl)

        new_sl = round_price(pos.symbol, new_sl)

        # Only move SL in the protective direction
        # (SHADOW-S1: old_prog is what the pre-ship entry-based progress would
        # have been — telemetry for old-vs-new comparison on the first closes.)
        if is_long and new_sl > pos.sl:
            old_sl = pos.sl
            pos.sl = new_sl
            logger.info(
                f"[{pos.symbol}] Trail SL: {old_sl} -> {new_sl} "
                f"(peak={pos.peak_price} prog={progress:.0%} "
                f"shadow_old_prog={_old_progress:.0%})"
            )
        elif not is_long and new_sl < pos.sl:
            old_sl = pos.sl
            pos.sl = new_sl
            logger.info(
                f"[{pos.symbol}] Trail SL: {old_sl} -> {new_sl} "
                f"(peak={pos.peak_price} prog={progress:.0%} "
                f"shadow_old_prog={_old_progress:.0%})"
            )

    def _classify_outcome(self, pos: Position, action: str) -> str:
        """Classify the trade outcome for learning hooks."""
        tp1_was_hit = TP1_HIT in pos.state_path
        win = pos.realized_pnl > 0

        if action == "TP2":
            return "CLEAN_WIN"
        elif action == "EARLY_EXIT":
            return "EARLY_EXIT_SAVE" if pos.realized_pnl > -(abs(pos.entry - pos.original_sl) * pos.original_qty * self._pnl_lev(pos.leverage) * 0.25) else "EARLY_EXIT_FAIL"
        elif action == "TRAILING_STOP":
            return "TRAILING_WIN" if win else "TRAILING_FAIL"
        elif action in ("ROTATE_PROFIT", "ROTATE_LOSS_AVOIDANCE"):
            return "ROTATION_WIN" if win else "ROTATION_LOSS_AVOIDANCE"
        elif action == "SL":
            if tp1_was_hit:
                return "TP1_THEN_SL"
            # Trailing SL can move above entry on strong moves without TP1_HIT
            # having fired. A closed-at-profit SL trigger is a win, not a loss.
            return "CLEAN_WIN" if win else "CLEAN_LOSS"
        elif tp1_was_hit and not win:
            return "TP1_ONLY"
        else:
            return "CLEAN_LOSS" if not win else "CLEAN_WIN"

    def _close_position(self, pos: Position, price: float, action: str) -> TradeEvent:
        """Fully close a position with state transition."""
        # Write-ahead journal (Phase 0.3b): record intent-to-close BEFORE
        # any booking (ledger row / equity credit) happens, so a crash
        # between this point and the ledger write is detectable on restart
        # via core.position_journal.startup_reconcile(). Journaling is a
        # safety net, not a gate -- never let a journal failure block or
        # crash a real close.
        try:
            from core.position_journal import journal_closing
            journal_closing(
                pos.position_id,
                {"action": action, "price": price},
                symbol=pos.symbol,
            )
        except Exception:
            logger.debug(
                f"[{pos.symbol}] [POSITION-JOURNAL] journal_closing failed (non-fatal)",
                exc_info=True,
            )

        # FUNDING_ACCRUAL_CADENCE_FIX: drop the per-symbol accrual clock so a
        # future reopen on this symbol starts with no prior timestamp (see
        # accrue_funding) instead of measuring elapsed time against a stale
        # baseline left over from this now-closed position.
        self._last_funding_accrual_ts.pop(pos.symbol, None)
        qty = pos.qty
        fee = self._fee(price, qty, pos.leverage)
        pos.fees_paid += fee
        # FEE_ACCOUNTING_FIX: the entry-leg fee (booked to fees_paid at open) was
        # never deducted from realized_pnl nor charged to equity (equity only sees
        # exit-event fees via update_equity(event.pnl - event.fee)). Book it into
        # the final-close fee so realized_pnl and equity carry the full round trip.
        if os.getenv("FEE_ACCOUNTING_FIX", "false").lower() in ("1", "true", "yes"):
            fee += self._fee(pos.entry, pos.original_qty, pos.leverage)

        if pos.side == "LONG":
            pnl = (price - pos.entry) * qty * self._pnl_lev(pos.leverage)
        else:
            pnl = (pos.entry - price) * qty * self._pnl_lev(pos.leverage)

        # Deduct accumulated funding costs at final close
        # PNL_SEMANTICS_FIX (2026-07-20): capture this (final) leg's own NET
        # contribution before mutating pos.realized_pnl, so the
        # trade_events.jsonl close event below can log the LEG's net pnl
        # instead of the whole-position cumulative total. Without this, a
        # position that had an earlier TP1 partial double-counts that TP1
        # leg's profit when its events are summed (TP1 leg logged once at
        # TP1 time, then again folded into this event's old
        # pnl=pos.realized_pnl). For a position with no prior TP1 leg, this
        # value is numerically identical to pos.realized_pnl (unchanged
        # behavior for single-leg trades).
        final_leg_net_pnl = pnl - fee - pos.funding_costs
        pos.realized_pnl += final_leg_net_pnl
        pos.qty = 0
        # Use simulated time in backtest mode, real time in live
        pos.close_time = getattr(self, '_sim_now', None) or datetime.now(timezone.utc)

        # Classify outcome before closing state
        pos.outcome = self._classify_outcome(pos, action)

        # State -> CLOSED
        pos._transition(CLOSED, f"{action} @ {price}")
        # Record close time and win/loss for cooldown enforcement
        self._last_close_time[pos.symbol] = pos.close_time
        self._last_close_won[pos.symbol] = pos.realized_pnl > 0

        # Record outcome for momentum tracker (win/loss streak sizing).
        # Gated on self.is_live: only the real live/paper trading engine's
        # PositionManager may mutate the shared momentum_state.json (book-
        # level _global_last_win + per-symbol streaks). Backtest/replay/
        # scenario_sim PositionManagers default is_live=False and are never
        # recorded here, so a fabricated/simulated close cannot halve the
        # next REAL trade's size via get_after_loss_multiplier() or fake a
        # win/streak on a symbol. (momentum_tracker.record_outcome() also
        # independently filters TEST/SIM-named symbols as defense in depth.)
        if self.is_live:
            try:
                from execution.momentum_tracker import get_momentum_tracker
                get_momentum_tracker().record_outcome(pos.symbol, pos.realized_pnl > 0)
            except Exception:
                pass

        # Neuroplasticity: strengthen/weaken setup edges, detect surprises
        try:
            from llm.neuroplasticity import run_neuroplasticity_cycle
            _er = pos.entry_reasons or {}
            run_neuroplasticity_cycle({
                "symbol": pos.symbol,
                "side": "BUY" if pos.side == "LONG" else "SELL",
                "strategy": _er.get("primary_driver", ""),
                "strategies_agree": _er.get("strategies_agree", []),
                "pnl": pos.realized_pnl,
                "entry": pos.entry,
                # PNL_UNIT_FIX (2026-07-14): qty lets neuroplasticity compute a real
                # return-on-margin % instead of dollars-divided-by-price (M12 pattern).
                "qty": getattr(pos, "original_qty", 0.0) or getattr(pos, "qty", 0.0),
                "regime": _er.get("regime", "unknown"),
                "outcome": pos.outcome,
            })
        except Exception:
            pass

        # ── TIER 4: Mechanical Bot Instrumentation (Position Closing Hook) ──
        if _MECHANICAL_BOT_INSTRUMENTATION_AVAILABLE:
            try:
                instr = get_mechanical_bot_instrumentation()
                instr.on_position_closed(
                    symbol=pos.symbol,
                    side=pos.side,
                    exit_price=price,
                    exit_action=action,  # "SL", "TP1", "TP2", "TRAILING", "EARLY_EXIT", etc.
                    exit_qty=qty,
                    entry_price=pos.entry,
                    pnl=pos.realized_pnl,
                    total_fees=pos.fees_paid,
                    funding_costs=pos.funding_costs,
                    outcome=pos.outcome,
                    hold_duration_seconds=(pos.close_time - pos.open_time).total_seconds(),
                    entry_reasons=pos.entry_reasons or {},
                    notes=pos.notes,
                    setup_type=pos.setup_type,
                )
            except Exception as e:
                logger.debug(f"[{pos.symbol}] Mechanical bot instrumentation error (position closing): {e}")

        logger.info(
            f"[{pos.symbol}] {action} @ {price} | PnL={pnl:.2f} | "
            f"Total={pos.realized_pnl:.2f} | Fees={pos.fees_paid:.2f} | "
            f"Funding={pos.funding_costs:.2f} | "
            f"Outcome={pos.outcome} | Path={pos.state_path_str}"
        )

        profile_data = pos.trade_profile.to_dict() if pos.trade_profile else {}

        event = TradeEvent(
            symbol=pos.symbol,
            action=action,
            side=pos.side,
            price=price,
            qty=qty,
            pnl=pnl,
            fee=fee,
            leverage=pos.leverage,
            strategy=pos.strategy,
            position_id=pos.position_id,
            # TRADE_SUMMARY_PER_POSITION_FIX: this is the ONE event per position
            # that reaches _close_position (whatever `action` string triggered
            # it) — get_trade_summary() uses this flag, not an action whitelist,
            # to count positions and classify win/loss.
            is_position_close=True,
            metadata={
                "total_pnl": pos.realized_pnl,
                "total_fees": pos.fees_paid,
                "funding_costs": pos.funding_costs,
                "hold_time_s": (pos.close_time - pos.open_time).total_seconds(),
                "peak_price": pos.peak_price,
                "outcome": pos.outcome,
                "state_path": pos.state_path_str,
                "entry_reasons": pos.entry_reasons,
                "num_agree": (pos.entry_reasons or {}).get("num_agree", 0),
                "strategies_agree": (pos.entry_reasons or {}).get("strategies_agree", []),
                "entry_type": profile_data.get("entry_type", "UNKNOWN"),
                "primary_driver": profile_data.get("primary_driver", ""),
                "regime": (pos.entry_reasons or {}).get("regime", "") or profile_data.get("regime", ""),
                "volatility_band": profile_data.get("volatility_band", ""),
                "trade_profile": profile_data,
                # Position context for CSV analysis
                "entry": pos.entry,
                "sl": pos.original_sl,
                "tp1": pos.tp1,
                "tp2": pos.tp2,
                "confidence": pos.confidence,
                # MFE/MAE tracking — critical for exit optimization
                "mfe": round(pos.mfe, 6),
                "mae": round(pos.mae, 6),
                "mfe_pct": round(pos.mfe / pos.entry * 100, 4) if pos.entry else 0,
                "mae_pct": round(pos.mae / pos.entry * 100, 4) if pos.entry else 0,
                "highest_price": pos.highest_price,
                "lowest_price": pos.lowest_price,
            },
        )
        # ── EXIT-REGRET STAMP (additive, measurement-only — 2026-06-23) ──
        # Every full close flows through here (SL/TP/TRAILING/EARLY_EXIT/force_close/
        # LLM_EXIT_AGENT/rotation/HOLD_LIMIT). Stamp a decision_id and append ONE line
        # to exit_closes.jsonl so analytics/exit_regret.py can score +1h/+2h/+4h recovery.
        # PURELY MEASUREMENT: never alters execution. Fully guarded.
        try:
            import uuid as _uuid
            _decision_id = _uuid.uuid4().hex
            event.metadata["decision_id"] = _decision_id  # correlate close <-> regret score
            _regret_dir = os.path.join("data", "logs")
            os.makedirs(_regret_dir, exist_ok=True)
            _regret_row = {
                "decision_id": _decision_id,
                "ts": (pos.close_time or datetime.now(timezone.utc)).isoformat(),
                "symbol": pos.symbol,
                "side": pos.side,                       # "LONG" / "SHORT"
                "exit_type": action,                    # "SL","TP2","TRAILING_STOP","EARLY_EXIT","LLM_EXIT_AGENT",...
                "entry": pos.entry,
                "exit_price": price,
                "qty": qty,
                "leverage": pos.leverage,
                "pnl": pos.realized_pnl,
                "regime": (pos.entry_reasons or {}).get("regime", "") or "unknown",
                "strategy": pos.strategy,
                "mfe_pct": round(pos.mfe / pos.entry * 100, 4) if pos.entry else 0.0,
                "hold_time_s": (pos.close_time - pos.open_time).total_seconds() if pos.close_time and pos.open_time else 0.0,
            }
            # Skip the real-file write under pytest so synthetic test closes never pollute
            # production exit_closes.jsonl (decision_id stamping above still happens for tests).
            if not os.getenv("PYTEST_CURRENT_TEST"):
                with open(os.path.join(_regret_dir, "exit_closes.jsonl"), "a") as _rf:
                    _rf.write(json.dumps(_regret_row) + "\n")
        except Exception as _regret_err:
            logger.debug(f"[EXIT-REGRET] stamp failed (non-fatal): {_regret_err}")

        self.trade_log.append(event)

        # Log structured trade event (SL_HIT, TP_HIT, or TRADE_CLOSED)
        try:
            tel = _get_tel()
            if tel is not None:
                _hold_s = (pos.close_time - pos.open_time).total_seconds()
                # Map action to event type
                if action in ("SL", "TRAILING_STOP"):
                    _event_type = "SL_HIT"
                elif action in ("TP2", "TP1_FULL"):
                    _event_type = "TP_HIT"
                else:
                    _event_type = "TRADE_CLOSED"
                tel.log(
                    _event_type,
                    pos.symbol,
                    side=pos.side,
                    exit_price=price,
                    entry_price=pos.entry,
                    # PNL_SEMANTICS_FIX (2026-07-20): was pos.realized_pnl
                    # (whole-position cumulative NET, which already includes
                    # any earlier TP1 leg's contribution -- double-counted
                    # when summed alongside that TP1 leg's own TP_HIT event).
                    # Now this leg's own net contribution only, matching the
                    # TP_HIT partial's `pnl` units above. For single-leg
                    # trades (no TP1) this is numerically identical to the
                    # old value.
                    pnl=final_leg_net_pnl,
                    # True whole-position cumulative net pnl as of this
                    # (final) event -- for consumers that want the trade's
                    # grand total rather than a per-leg delta (e.g. Telegram
                    # close alerts, see alerts/telegram_alert_bridge.py).
                    total_pnl=pos.realized_pnl,
                    fee=fee,
                    funding=pos.funding_costs,
                    hold_time=_hold_s,
                    exit_reason=action,
                    leverage=pos.leverage,
                    strategy=pos.strategy,
                    outcome=pos.outcome,
                    confidence=pos.confidence,
                    regime=(pos.entry_reasons or {}).get("regime", ""),
                )
        except Exception:
            pass

        # Remove backup after successful close
        self._remove_backup(pos.symbol)

        # SHIP-2026-04-19: persist state on every close to prevent ghost-position bug
        # where auto_recovery resurrects already-closed positions (COOLDOWN_BYPASS_RCA_2026_04_17.md).
        # Previously only persisted every 5 ticks, so a crash between close and next tick
        # left disk state showing OPEN; on restart, the closed position got resurrected.
        try:
            from execution.auto_recovery import save_position_state
            save_position_state(self)
        except Exception:
            logger.exception("[SAVE-ON-CLOSE] non-fatal state persistence failure")

        return event

    def force_close(self, symbol: str, price: float, reason: str = "EMERGENCY") -> Optional[TradeEvent]:
        """Force close a position (circuit breaker, liquidation avoidance, etc.)."""
        pos = self.positions.get(symbol)
        if not pos or pos.state == CLOSED:
            return None
        return self._close_position(pos, price, reason)

    def partial_close(
        self, symbol: str, pct: float, price: float,
        action: str = "PARTIAL_CLOSE", qty: Optional[float] = None,
    ) -> Optional[TradeEvent]:
        """Book the accounting for a partial close and return its TradeEvent.

        Extracted from the TP1 accounting path (2026-07-01 wiring audit #2):
        LLM/heuristic partial closes previously did only `pos.qty -= close_qty`,
        so the banked leg PnL never reached fees, realized_pnl, equity,
        trade logs, or learning — a PnL black hole that also inverted
        win/loss labels (partial profit + SL on remainder recorded pure loss).

        Pure accounting: fee, leg PnL, proportional funding allocation, qty
        reduction, TradeEvent. Does NOT touch SL/TP/state (exit geometry
        unchanged). Caller owns exchange submission and must stamp
        event.metadata["_exchange_submitted"] before injecting the event
        into the main event loop (equity + log_trade flow from there).

        qty: exact quantity already submitted to the exchange (overrides pct
        for the booked amount so books match the fill).
        """
        pos = self.positions.get(symbol)
        if not pos or pos.state == CLOSED or pos.qty <= 0:
            return None
        close_qty = qty if (qty is not None and qty > 0) else pos.qty * pct
        close_qty = round_qty(symbol, min(close_qty, pos.qty))
        # A "partial" must never zero the position — keep a minimum remainder
        # (mirrors the _partial_close_tp1 rounding guard).
        remaining_after = round_qty(symbol, pos.qty - close_qty)
        if remaining_after <= 0:
            close_qty = round_qty(symbol, pos.qty * 0.90)
        if close_qty <= 0 or close_qty >= pos.qty:
            return None

        fee = self._fee(price, close_qty, pos.leverage)
        pos.fees_paid += fee

        if pos.side == "LONG":
            pnl = (price - pos.entry) * close_qty * self._pnl_lev(pos.leverage)
        else:
            pnl = (pos.entry - price) * close_qty * self._pnl_lev(pos.leverage)

        # Proportionally allocate funding costs to this leg
        # (mirrors _partial_close_tp1 — prevents dumping all funding onto
        # the final close and distorting per-leg PnL)
        funding_share = pos.funding_costs * (close_qty / pos.qty) if pos.qty > 0 else 0.0
        pos.realized_pnl += (pnl - fee - funding_share)
        pos.funding_costs -= funding_share
        pos.qty = round_qty(symbol, pos.qty - close_qty)

        logger.info(
            f"[{symbol}] {action} @ {price} | Closed {close_qty} ({pct:.0%}) | "
            f"PnL={pnl:.2f} | Fee={fee:.2f} | Remaining={pos.qty}"
        )

        event = TradeEvent(
            symbol=symbol,
            action=action,
            side=pos.side,
            price=price,
            qty=close_qty,
            pnl=pnl,
            fee=fee,
            leverage=pos.leverage,
            strategy=pos.strategy,
            position_id=pos.position_id,
            metadata={
                "remaining_qty": pos.qty,
                "partial_pct": pct,
                "entry": pos.entry,
                "sl": pos.original_sl,
                "tp1": pos.tp1,
                "tp2": pos.tp2,
                "confidence": pos.confidence,
                "entry_reasons": pos.entry_reasons,
                # DAILY_SUMMARY_FIX (2026-07-20): mirrors the TP1 partial-close
                # path's metadata — without this, a consumer summing
                # pnl - fee - funding_share per leg (e.g. _send_daily_summary's
                # 24h window) silently treats this leg's funding as 0.
                "funding_share": funding_share,
            },
        )
        self.trade_log.append(event)
        return event

    # Profile-specific max hold hours: prevents stale positions from lingering
    _PROFILE_MAX_HOLD_HOURS = {
        "SCALP": 4,
        "MEDIUM": 12,
        "TREND": 36,
        "REGIME": 48,
    }

    def check_hold_limits(
        self, symbol: str, price: float, max_hold_hours: float = 48, action: str = "tighten_sl"
    ) -> Optional[TradeEvent]:
        """Check if a position has exceeded its max hold time.

        At max_hold_hours: tighten SL to breakeven (or force close if action='force_close').
        At 1.5x max_hold_hours: force close regardless.

        Uses profile-specific hold limits if a trade profile is attached.
        Returns TradeEvent if position was force-closed, None otherwise.
        """
        pos = self.positions.get(symbol)
        if not pos or pos.state == CLOSED:
            return None

        if pos.open_time is None:
            return None

        # Use profile-specific hold limit (always apply, use min of config and profile)
        if pos.trade_profile:
            entry_type = pos.trade_profile.entry_type
            profile_max = self._PROFILE_MAX_HOLD_HOURS.get(entry_type)
            if profile_max is not None:
                max_hold_hours = min(max_hold_hours, profile_max)

        now = getattr(self, '_sim_now', None) or datetime.now(timezone.utc)
        if isinstance(pos.open_time, datetime):
            age_hours = (now - pos.open_time).total_seconds() / 3600
        else:
            age_hours = (now.timestamp() - pos.open_time) / 3600

        force_close_hours = max_hold_hours * 1.5

        if age_hours >= force_close_hours:
            # Hard limit: force close
            logger.warning(
                f"[HOLD_LIMIT] {symbol} {pos.side} open {age_hours:.1f}h "
                f">= {force_close_hours:.0f}h hard limit — FORCE CLOSING"
            )
            return self.force_close(symbol, price, reason="HOLD_LIMIT")

        if age_hours >= max_hold_hours:
            if action == "force_close":
                logger.warning(
                    f"[HOLD_LIMIT] {symbol} {pos.side} open {age_hours:.1f}h "
                    f">= {max_hold_hours:.0f}h — FORCE CLOSING (action=force_close)"
                )
                return self.force_close(symbol, price, reason="HOLD_LIMIT")

            # Default: tighten SL to breakeven + fee buffer (SHIP-2026-04-20)
            fee_buffer = pos.entry * (self.taker_fee_bps * 2 / 10000.0 + 0.001)
            if pos.side == "LONG" and pos.sl < pos.entry + fee_buffer:
                old_sl = pos.sl
                pos.sl = pos.entry + fee_buffer
                logger.info(
                    f"[HOLD_LIMIT] {symbol} LONG open {age_hours:.1f}h "
                    f">= {max_hold_hours:.0f}h — SL tightened {old_sl:.4f} -> {pos.sl:.4f} (BE+buffer)"
                )
            elif pos.side == "SHORT" and pos.sl > pos.entry - fee_buffer:
                old_sl = pos.sl
                pos.sl = pos.entry - fee_buffer
                logger.info(
                    f"[HOLD_LIMIT] {symbol} SHORT open {age_hours:.1f}h "
                    f">= {max_hold_hours:.0f}h — SL tightened {old_sl:.4f} -> {pos.sl:.4f} (BE+buffer)"
                )

        return None

    def get_open_positions(self) -> Dict[str, Position]:
        return {s: p for s, p in self.positions.items() if p.state != CLOSED}

    def get_open_count(self) -> int:
        return sum(1 for p in self.positions.values() if p.state != CLOSED)

    def get_total_open_notional(self) -> float:
        """Sum of all open position notional values (qty * entry * leverage)."""
        total = 0.0
        for pos in self.positions.values():
            if pos.state != CLOSED:
                total += pos.qty * pos.entry * pos.leverage
        return total

    def check_portfolio_notional_cap(
        self, new_notional: float, equity: float, max_portfolio_leverage: float = 5.0,
    ) -> bool:
        """Check if adding a new position would exceed aggregate portfolio leverage cap.

        Returns True if the new position is allowed, False if it would breach the cap.
        """
        current_notional = self.get_total_open_notional()
        cap = equity * max_portfolio_leverage
        if current_notional + new_notional > cap:
            logger.warning(
                f"[PORTFOLIO-CAP] Rejected: current_notional=${current_notional:.0f} + "
                f"new=${new_notional:.0f} > cap=${cap:.0f} "
                f"(equity=${equity:.0f} * {max_portfolio_leverage}x)"
            )
            return False
        return True

    def get_total_unrealized_pnl(self, prices: Dict[str, float]) -> float:
        total = 0.0
        for symbol, pos in self.positions.items():
            if pos.state == CLOSED or symbol not in prices:
                continue
            price = prices[symbol]
            if pos.side == "LONG":
                total += (price - pos.entry) * pos.qty * self._pnl_lev(pos.leverage)
            else:
                total += (pos.entry - price) * pos.qty * self._pnl_lev(pos.leverage)
        return total

    def get_trade_summary(self) -> Dict[str, Any]:
        """Summary of all trades taken.

        TRADE_SUMMARY_PER_POSITION_FIX (2026-07-20):
        1. win_rate/wins/losses/total_trades are now PER POSITION, not per
           closing leg. Previously `closed` mixed partial TP1 legs in with
           full closes and classified each leg independently off its own
           gross e.pnl, so a TP1-partial-profit-then-breakeven-stop position
           counted as "1 win + 1 loss" (2 "trades") instead of one net
           position. Each is_position_close=True event's
           metadata["total_pnl"] already holds pos.realized_pnl — the FULL
           position's cumulative net-of-fees-and-funding PnL across every
           leg — so that (not the leg's own gross e.pnl) is what now decides
           win/loss and total_trades/win_rate. Bonus fix: this also switches
           win/loss classification from gross to net PnL, so a leg that was
           gross-positive but fee-negative can no longer be mislabeled a win.
        2. The old `closed` list was a hardcoded action-string whitelist that
           silently dropped every close whose reason wasn't on it —
           concretely TP1_FULL, TIME_STOP, LLM_EXIT_AGENT and
           LLM_EXIT_PARTIAL (all added to the codebase after this whitelist
           was written) never contributed to any stat below. Replaced with
           the is_position_close flag, set at the one call site
           (_close_position) that actually ends a position's lifecycle
           regardless of the reason string passed in — so no future exit
           reason can silently fall out of these numbers again the same way.
        3. Dollar aggregates (total_pnl/total_fees/net_pnl/profit_factor)
           stay leg-summed across ALL closing events (position closes +
           partial legs) exactly as before — each leg's own event.pnl/fee
           together already equal the position's full round-trip economics —
           just computed over the now-complete event set instead of the
           whitelist.
        4. `window` flags that every number here is scoped to self.trade_log,
           which lives only in this process's memory and is empty again
           after every restart — never an all-time record.
        """
        position_closes = [e for e in self.trade_log if e.is_position_close]
        # Partial/leg events: TP1 (from _partial_close_tp1), PARTIAL_CLOSE /
        # LLM_EXIT_PARTIAL (from partial_close()). Never OPEN, never a
        # position-terminal close.
        legs = [e for e in self.trade_log if not e.is_position_close and e.action != "OPEN"]
        all_closes = position_closes + legs
        opens = [e for e in self.trade_log if e.action == "OPEN"]
        if not position_closes:
            return {
                "total_trades": 0, "positions_opened": len(opens), "close_events": 0,
                "best_trade": None, "worst_trade": None,
                "window": "since_process_start",
            }

        def _position_pnl(e: "TradeEvent") -> float:
            # metadata["total_pnl"] = pos.realized_pnl at terminal close: the
            # position's full net PnL across every leg. Fall back to the raw
            # event pnl only for synthetic/mocked events with no metadata
            # (e.g. unit tests constructing bare TradeEvent/MagicMock rows).
            return (e.metadata or {}).get("total_pnl", e.pnl)

        wins = [e for e in position_closes if _position_pnl(e) > 0]
        losses = [e for e in position_closes if _position_pnl(e) <= 0]

        # DAILY_SUMMARY_GROSS_TO_NET_FIX (2026-07-20): best/worst trade, keyed
        # off the same position-level, fee/funding-netted _position_pnl() used
        # for wins/losses above (not raw per-leg e.pnl) — consistent with the
        # rest of this already-rewritten method.
        best_trade = None
        worst_trade = None
        for e in position_closes:
            p = _position_pnl(e)
            if best_trade is None or p > best_trade["pnl"]:
                best_trade = {"symbol": e.symbol, "pnl": p}
            if worst_trade is None or p < worst_trade["pnl"]:
                worst_trade = {"symbol": e.symbol, "pnl": p}

        total_pnl = sum(e.pnl for e in all_closes)
        # Include entry fees (OPEN events) + every leg's exit fee for accurate total
        total_fees = sum(e.fee for e in all_closes) + sum(e.fee for e in opens)

        gross_wins = sum(e.pnl for e in all_closes if e.pnl > 0)
        gross_losses = abs(sum(e.pnl for e in all_closes if e.pnl <= 0))
        profit_factor = round(gross_wins / gross_losses, 2) if gross_losses > 0 else 99.0

        by_action: Dict[str, int] = {}
        for e in all_closes:
            by_action[e.action] = by_action.get(e.action, 0) + 1

        return {
            "positions_opened": len(opens),
            "close_events": len(all_closes),
            "positions_closed": len(position_closes),
            # backwards-compat key name, but the VALUE is now a true position
            # count (was a leg count) — see fix note above.
            "total_trades": len(position_closes),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(position_closes) if position_closes else 0,
            "total_pnl": total_pnl,
            "gross_pnl": total_pnl,
            "total_fees": total_fees,
            "net_pnl": total_pnl - total_fees,
            "profit_factor": profit_factor,
            "avg_win": sum(_position_pnl(e) for e in wins) / len(wins) if wins else 0,
            "avg_loss": sum(_position_pnl(e) for e in losses) / len(losses) if losses else 0,
            "best_trade": best_trade,
            "worst_trade": worst_trade,
            # Partial legs (TP1 / PARTIAL_CLOSE / LLM_EXIT_PARTIAL) are folded
            # into their parent position's win/loss + avg_win/avg_loss above,
            # not counted as separate trades. Exposed here so a consumer can
            # see how many exist without having to re-derive them.
            "legs_total": len(legs),
            "by_action": by_action,
            "window": "since_process_start",
        }
