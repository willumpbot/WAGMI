"""
Sniper Signal Live Simulator.

Paper-trades every manual sniper signal in real-time, tracking a simulated
$100 account as if the user were executing every signal. READ-ONLY on
market data — never places real trades.

Simulated positions are opened at signal entry price and monitored each
scan cycle. Closes happen when:
  1. Price hits tp_scalp (primary target — conservative, take the quick win)
  2. Price hits sl (stop loss)
  3. 12 hours elapse without hitting either level (time stop — close at market)
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

logger = logging.getLogger("bot.manual.simulator")

# ── Paths ──────────────────────────────────────────────────────────────
_DATA_DIR = os.path.join("data", "manual")
_TRADES_PATH = os.path.join(_DATA_DIR, "sim_trades.jsonl")
_STATUS_PATH = os.path.join(_DATA_DIR, "sim_status.json")

# ── Constants ──────────────────────────────────────────────────────────
STARTING_EQUITY = 100.0
# NOTE: Early time-stop DISABLED based on backtest validation.
# Data shows: all losers hit SL within 5 bars naturally. Slow resolvers
# (21+ bars) have 100% WR. A time stop only kills slow winners.
# The correct rule: if trade survives 5+ bars, HOLD — it's a slow winner.
EARLY_TIME_STOP_HOURS = 999.0   # Effectively disabled
EARLY_TIME_STOP_S = EARLY_TIME_STOP_HOURS * 3600
TIME_STOP_HOURS = 24.0          # Extended from 12h — slow winners need time
TIME_STOP_S = TIME_STOP_HOURS * 3600


@dataclass
class SimPosition:
    """A simulated open position."""
    trade_id: str
    symbol: str
    side: str           # BUY or SELL
    tier: str           # SNIPER / PREMIUM / STANDARD
    entry: float
    sl: float
    tp_scalp: float
    tp_swing: float
    leverage: float
    risk_pct: float
    position_size_usd: float
    qty: float
    risk_amount: float
    pnl_scalp: float
    loss_amount: float
    equity_at_open: float
    opened_at: float    # unix timestamp
    opened_at_iso: str
    confidence: float
    num_agree: int
    regime: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SimTrade:
    """A completed simulated trade."""
    trade_id: str
    symbol: str
    side: str
    tier: str
    entry: float
    exit_price: float
    sl: float
    tp_scalp: float
    leverage: float
    position_size_usd: float
    qty: float
    risk_amount: float
    equity_at_open: float
    equity_at_close: float
    pnl_usd: float
    pnl_pct: float       # % of equity
    result: str           # WIN / LOSS / TIME_STOP
    exit_reason: str      # tp_scalp / sl / time_stop
    hold_time_s: float
    hold_time_hours: float
    opened_at: str
    closed_at: str
    confidence: float
    num_agree: int
    regime: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SniperSimulator:
    """
    Live simulator for sniper signals.

    Hooks into ManualSniperFilter output, simulates execution at signal
    entry price, and tracks a virtual $100 compounding account.
    """

    def __init__(self, starting_equity: float = STARTING_EQUITY):
        os.makedirs(_DATA_DIR, exist_ok=True)

        self._starting_equity = starting_equity
        self._equity = starting_equity
        self._open_positions: List[SimPosition] = []
        self._closed_trades: List[SimTrade] = []
        self._trade_counter = 0

        # Stats
        self._wins = 0
        self._losses = 0
        self._gross_profit = 0.0
        self._gross_loss = 0.0
        self._max_equity = starting_equity
        self._min_equity = starting_equity
        self._max_drawdown = 0.0
        self._current_streak = 0   # positive = wins, negative = losses
        self._best_trade_pnl = 0.0
        self._worst_trade_pnl = 0.0
        self._time_stop_count = 0
        self._time_stop_pnl = 0.0
        self._early_time_stop_count = 0
        self._early_time_stop_pnl = 0.0
        self._equity_curve: List[Dict[str, Any]] = [
            {"timestamp": datetime.now(timezone.utc).isoformat(), "equity": starting_equity}
        ]
        self._daily_pnl: Dict[str, float] = {}   # "YYYY-MM-DD" -> pnl
        self._by_symbol: Dict[str, Dict[str, Any]] = {}
        self._by_tier: Dict[str, Dict[str, Any]] = {}

        self._started_at = datetime.now(timezone.utc).isoformat()

        # Load prior state if it exists
        self._load_state()

        logger.info(
            f"[SIM] Initialized — equity=${self._equity:.2f}, "
            f"open={len(self._open_positions)}, closed={len(self._closed_trades)}"
        )

    # ── Public API ─────────────────────────────────────────────────────

    def on_signal(self, sniper_signal) -> Optional[SimPosition]:
        """
        Called when a SniperSignal passes all filters.
        Opens a simulated position at the signal's entry price.
        """
        # Circuit breaker: stop trading if equity too low
        if self._equity <= self._starting_equity * 0.10:
            logger.warning(
                f"[SIM] CIRCUIT BREAKER: Equity ${self._equity:.2f} is below 10% of "
                f"starting equity ${self._starting_equity:.2f}. Halting new trades."
            )
            return None

        # Avoid duplicate positions on same symbol+side
        for pos in self._open_positions:
            if pos.symbol == sniper_signal.symbol and pos.side == sniper_signal.side:
                logger.debug(f"[SIM] Already have {pos.side} on {pos.symbol}, skipping")
                return None

        self._trade_counter += 1
        trade_id = f"SIM-{self._trade_counter:04d}"
        now = time.time()

        # Recalculate sizing based on current sim equity (compound)
        risk_pct = sniper_signal.risk_pct
        risk_amount = self._equity * risk_pct
        if sniper_signal.entry <= 0:
            logger.warning(f"[SIM] Zero/negative entry price, skipping")
            return None
        stop_width_pct = abs(sniper_signal.entry - sniper_signal.sl) / sniper_signal.entry
        if stop_width_pct <= 0:
            stop_width_pct = 0.01

        position_size_usd = risk_amount / stop_width_pct
        margin_required = position_size_usd / sniper_signal.leverage if sniper_signal.leverage > 0 else position_size_usd

        # Cap margin at 95% of equity
        if margin_required > self._equity * 0.95:
            scale = (self._equity * 0.95) / margin_required
            position_size_usd *= scale
            risk_amount *= scale

        qty = position_size_usd / sniper_signal.entry if sniper_signal.entry > 0 else 0

        # Scalp TP expected P&L
        scalp_move_pct = abs(sniper_signal.tp_scalp - sniper_signal.entry) / sniper_signal.entry
        pnl_scalp = position_size_usd * scalp_move_pct

        pos = SimPosition(
            trade_id=trade_id,
            symbol=sniper_signal.symbol,
            side=sniper_signal.side,
            tier=sniper_signal.tier,
            entry=sniper_signal.entry,
            sl=sniper_signal.sl,
            tp_scalp=sniper_signal.tp_scalp,
            tp_swing=sniper_signal.tp_swing,
            leverage=sniper_signal.leverage,
            risk_pct=risk_pct,
            position_size_usd=round(position_size_usd, 2),
            qty=round(qty, 6),
            risk_amount=round(risk_amount, 2),
            pnl_scalp=round(pnl_scalp, 2),
            loss_amount=round(risk_amount, 2),
            equity_at_open=round(self._equity, 2),
            opened_at=now,
            opened_at_iso=datetime.now(timezone.utc).isoformat(),
            confidence=sniper_signal.confidence,
            num_agree=sniper_signal.num_agree,
            regime=sniper_signal.regime,
        )

        self._open_positions.append(pos)
        logger.info(
            f"[SIM] OPENED {trade_id} | {pos.symbol} {pos.side} @ ${pos.entry:.4f} | "
            f"size=${pos.position_size_usd:.2f} risk=${pos.risk_amount:.2f} | "
            f"equity=${self._equity:.2f}"
        )
        self._save_status()
        return pos

    def check_positions(self, current_prices: Dict[str, float]) -> List[SimTrade]:
        """
        Called every scan cycle. Checks all open sim positions against
        current market prices. Returns list of trades closed this cycle.
        """
        # Always save status periodically (even with no position changes)
        # This ensures the dashboard always has fresh data
        if self._open_positions:
            self._save_status()

        if not self._open_positions:
            return []

        closed_this_cycle: List[SimTrade] = []
        now = time.time()
        remaining: List[SimPosition] = []

        for pos in self._open_positions:
            price = current_prices.get(pos.symbol)
            if price is None:
                remaining.append(pos)
                continue

            exit_reason = None
            exit_price = price

            # Check time stops (3h early exit for stale positions, 12h hard stop)
            elapsed_s = now - pos.opened_at
            if elapsed_s >= TIME_STOP_S:
                exit_reason = "time_stop"
                exit_price = price
            elif elapsed_s >= EARLY_TIME_STOP_S:
                # 3h time-stop: fast-resolving trades (1-3 bars) have 91% WR,
                # medium-hold trades (4-8 bars) have 0% WR.
                # If it hasn't hit TP or SL in 3h, it's going nowhere.
                exit_reason = "time_stop_3h"
                exit_price = price

            # Check SL / TP
            if exit_reason is None:
                if pos.side == "BUY":
                    if price <= pos.sl:
                        exit_reason = "sl"
                        exit_price = pos.sl
                    elif price >= pos.tp_scalp:
                        exit_reason = "tp_scalp"
                        exit_price = pos.tp_scalp
                else:  # SELL
                    if price >= pos.sl:
                        exit_reason = "sl"
                        exit_price = pos.sl
                    elif price <= pos.tp_scalp:
                        exit_reason = "tp_scalp"
                        exit_price = pos.tp_scalp

            if exit_reason:
                trade = self._close_position(pos, exit_price, exit_reason, now)
                closed_this_cycle.append(trade)
            else:
                remaining.append(pos)

        self._open_positions = remaining

        # Save status on any change or periodically (every call if positions open)
        if closed_this_cycle or self._open_positions:
            self._save_status()

        return closed_this_cycle

    def get_status(self) -> Dict[str, Any]:
        """Return full simulator status dict."""
        total = self._wins + self._losses
        win_rate = (self._wins / total * 100) if total > 0 else 0.0
        profit_factor = (
            (self._gross_profit / abs(self._gross_loss))
            if self._gross_loss != 0 else float('inf') if self._gross_profit > 0 else 0.0
        )

        # Daily P&L for today
        today_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        daily_pnl = self._daily_pnl.get(today_key, 0.0)

        # Weekly P&L (last 7 days)
        import datetime as dt_mod
        today = dt_mod.date.today()
        weekly_pnl = 0.0
        for i in range(7):
            d = today - dt_mod.timedelta(days=i)
            weekly_pnl += self._daily_pnl.get(d.isoformat(), 0.0)

        # Days elapsed
        try:
            started = datetime.fromisoformat(self._started_at)
            days_elapsed = max(1, (datetime.now(timezone.utc) - started).days)
        except Exception:
            days_elapsed = 1

        return {
            "current_equity": round(self._equity, 2),
            "starting_equity": self._starting_equity,
            "total_trades": total,
            "wins": self._wins,
            "losses": self._losses,
            "win_rate": round(win_rate, 1),
            "profit_factor": round(profit_factor, 2) if profit_factor != float('inf') else 999.0,
            "best_trade": round(self._best_trade_pnl, 2),
            "worst_trade": round(self._worst_trade_pnl, 2),
            "max_drawdown": round(self._max_drawdown, 2),
            "current_streak": self._current_streak,
            "time_stop_count": self._time_stop_count,
            "time_stop_pnl": round(self._time_stop_pnl, 2),
            "early_time_stop_count": self._early_time_stop_count,
            "early_time_stop_pnl": round(self._early_time_stop_pnl, 2),
            "daily_pnl": round(daily_pnl, 2),
            "weekly_pnl": round(weekly_pnl, 2),
            "equity_curve": self._equity_curve[-200:],  # Keep last 200 points
            "by_symbol": self._by_symbol,
            "by_tier": self._by_tier,
            "open_positions": [p.to_dict() for p in self._open_positions],
            "started_at": self._started_at,
            "days_elapsed": days_elapsed,
            "growth_pct": round((self._equity / self._starting_equity - 1) * 100, 1),
        }

    # ── Internal ───────────────────────────────────────────────────────

    def _close_position(
        self, pos: SimPosition, exit_price: float, exit_reason: str, now: float
    ) -> SimTrade:
        """Close a simulated position and update all stats."""
        # Calculate P&L
        if pos.side == "BUY":
            price_change_pct = (exit_price - pos.entry) / pos.entry
        else:
            price_change_pct = (pos.entry - exit_price) / pos.entry

        pnl_usd = pos.position_size_usd * price_change_pct
        pnl_pct = (pnl_usd / pos.equity_at_open * 100) if pos.equity_at_open > 0 else 0
        hold_time_s = now - pos.opened_at
        hold_time_hours = hold_time_s / 3600

        # Determine result
        if exit_reason == "tp_scalp":
            result = "WIN"
        elif exit_reason == "sl":
            result = "LOSS"
        else:  # time_stop or time_stop_3h
            result = "WIN" if pnl_usd > 0 else "LOSS"

        # Update equity
        self._equity += pnl_usd
        equity_at_close = self._equity

        trade = SimTrade(
            trade_id=pos.trade_id,
            symbol=pos.symbol,
            side=pos.side,
            tier=pos.tier,
            entry=pos.entry,
            exit_price=round(exit_price, 6),
            sl=pos.sl,
            tp_scalp=pos.tp_scalp,
            leverage=pos.leverage,
            position_size_usd=pos.position_size_usd,
            qty=pos.qty,
            risk_amount=pos.risk_amount,
            equity_at_open=pos.equity_at_open,
            equity_at_close=round(equity_at_close, 2),
            pnl_usd=round(pnl_usd, 2),
            pnl_pct=round(pnl_pct, 1),
            result=result,
            exit_reason=exit_reason,
            hold_time_s=round(hold_time_s, 1),
            hold_time_hours=round(hold_time_hours, 2),
            opened_at=pos.opened_at_iso,
            closed_at=datetime.now(timezone.utc).isoformat(),
            confidence=pos.confidence,
            num_agree=pos.num_agree,
            regime=pos.regime,
        )

        self._closed_trades.append(trade)

        # ── Update stats ──
        if result == "WIN":
            self._wins += 1
            self._gross_profit += pnl_usd
            self._current_streak = max(0, self._current_streak) + 1
        else:
            self._losses += 1
            self._gross_loss += pnl_usd  # pnl_usd is negative
            self._current_streak = min(0, self._current_streak) - 1

        if pnl_usd > self._best_trade_pnl:
            self._best_trade_pnl = pnl_usd
        if pnl_usd < self._worst_trade_pnl:
            self._worst_trade_pnl = pnl_usd

        # Track time-stop stats separately
        if exit_reason == "time_stop_3h":
            self._early_time_stop_count += 1
            self._early_time_stop_pnl += pnl_usd
        elif exit_reason == "time_stop":
            self._time_stop_count += 1
            self._time_stop_pnl += pnl_usd

        # Drawdown tracking
        if self._equity > self._max_equity:
            self._max_equity = self._equity
        drawdown = (self._max_equity - self._equity) / self._max_equity * 100
        if drawdown > self._max_drawdown:
            self._max_drawdown = drawdown

        # Equity curve
        self._equity_curve.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "equity": round(self._equity, 2),
        })

        # Daily P&L
        today_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._daily_pnl[today_key] = self._daily_pnl.get(today_key, 0.0) + pnl_usd

        # By-symbol stats
        sym_stats = self._by_symbol.setdefault(pos.symbol, {
            "trades": 0, "wins": 0, "losses": 0, "pnl": 0.0, "wr": 0.0
        })
        sym_stats["trades"] += 1
        if result == "WIN":
            sym_stats["wins"] += 1
        else:
            sym_stats["losses"] += 1
        sym_stats["pnl"] = round(sym_stats["pnl"] + pnl_usd, 2)
        sym_stats["wr"] = round(sym_stats["wins"] / sym_stats["trades"] * 100, 1)

        # By-tier stats
        tier_stats = self._by_tier.setdefault(pos.tier, {
            "trades": 0, "wins": 0, "losses": 0, "pnl": 0.0, "wr": 0.0
        })
        tier_stats["trades"] += 1
        if result == "WIN":
            tier_stats["wins"] += 1
        else:
            tier_stats["losses"] += 1
        tier_stats["pnl"] = round(tier_stats["pnl"] + pnl_usd, 2)
        tier_stats["wr"] = round(tier_stats["wins"] / tier_stats["trades"] * 100, 1)

        # Log trade
        self._log_trade(trade)

        logger.info(
            f"[SIM] CLOSED {trade.trade_id} | {trade.symbol} {trade.side} | "
            f"{trade.exit_reason} @ ${trade.exit_price:.4f} | "
            f"P&L=${trade.pnl_usd:+.2f} ({trade.pnl_pct:+.1f}%) | "
            f"hold={trade.hold_time_hours:.1f}h | "
            f"equity=${self._equity:.2f}"
        )

        return trade

    def _log_trade(self, trade: SimTrade) -> None:
        """Append closed trade to JSONL log with flush for durability."""
        try:
            with open(_TRADES_PATH, "a") as f:
                f.write(json.dumps(trade.to_dict()) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except Exception as e:
            logger.warning(f"[SIM] Failed to log trade: {e}")

    def _save_status(self) -> None:
        """Write current status to JSON file."""
        try:
            status = self.get_status()
            tmp_path = _STATUS_PATH + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(status, f, indent=2)
            # Atomic rename
            os.replace(tmp_path, _STATUS_PATH)
        except Exception as e:
            logger.warning(f"[SIM] Failed to save status: {e}")

    def _load_state(self) -> None:
        """Load prior state from sim_status.json and sim_trades.jsonl.

        Handles corrupted files gracefully by falling back to fresh state.
        """
        # Load status for equity and stats
        if os.path.exists(_STATUS_PATH):
            try:
                with open(_STATUS_PATH, "r") as f:
                    content = f.read().strip()
                if not content:
                    logger.warning("[SIM] Empty status file, starting fresh")
                    return
                data = json.loads(content)
                self._equity = data.get("current_equity", self._starting_equity)
                self._wins = data.get("wins", 0)
                self._losses = data.get("losses", 0)
                self._max_drawdown = data.get("max_drawdown", 0.0)
                self._current_streak = data.get("current_streak", 0)
                self._best_trade_pnl = data.get("best_trade", 0.0)
                self._worst_trade_pnl = data.get("worst_trade", 0.0)
                self._equity_curve = data.get("equity_curve", self._equity_curve)
                self._by_symbol = data.get("by_symbol", {})
                self._by_tier = data.get("by_tier", {})
                self._started_at = data.get("started_at", self._started_at)
                self._max_equity = max(self._equity, self._starting_equity)

                # Restore daily_pnl (stored indirectly — recompute from trades)
                # Restore open positions
                open_pos = data.get("open_positions", [])
                for p in open_pos:
                    try:
                        self._open_positions.append(SimPosition(**p))
                        # Extract counter from trade_id to avoid collisions
                        tid = p.get("trade_id", "SIM-0000")
                        try:
                            num = int(tid.split("-")[1])
                            self._trade_counter = max(self._trade_counter, num)
                        except (IndexError, ValueError):
                            self._trade_counter += 1
                    except Exception:
                        pass

                # Recompute gross profit/loss from trade log
                self._recompute_gross_from_log()

                logger.info(
                    f"[SIM] Loaded state — equity=${self._equity:.2f}, "
                    f"W={self._wins} L={self._losses}, open={len(self._open_positions)}"
                )
            except Exception as e:
                logger.warning(f"[SIM] Failed to load status, starting fresh: {e}")

    def _recompute_gross_from_log(self) -> None:
        """Recompute gross_profit and gross_loss from trade log."""
        if not os.path.exists(_TRADES_PATH):
            return
        try:
            with open(_TRADES_PATH, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        t = json.loads(line)
                        pnl = t.get("pnl_usd", 0)
                        if pnl > 0:
                            self._gross_profit += pnl
                        else:
                            self._gross_loss += pnl

                        # Restore daily PnL
                        closed_at = t.get("closed_at", "")
                        if closed_at:
                            day_key = closed_at[:10]
                            self._daily_pnl[day_key] = self._daily_pnl.get(day_key, 0.0) + pnl

                        self._trade_counter = max(
                            self._trade_counter,
                            int(t.get("trade_id", "SIM-0000").split("-")[1])
                        )
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"[SIM] Error recomputing gross from log: {e}")
