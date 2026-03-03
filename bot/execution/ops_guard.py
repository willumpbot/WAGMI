"""
Operations Guard: Throttles, kill switch, and rate limiting.

Provides hard operational limits that protect against runaway trading:
- Max trades per hour
- Max position size as % of equity
- Max total exposure
- Emergency kill switch (halts all execution immediately)
- Trade rate limiter (sliding window)

These are HARD LIMITS that cannot be overridden by LLM or strategies.
"""

import logging
import os
import time
import threading
from typing import Dict, Any, Optional

logger = logging.getLogger("bot.execution.ops_guard")


def _env_float(key: str, default: float) -> float:
    return float(os.getenv(key, str(default)))


def _env_int(key: str, default: int) -> int:
    return int(os.getenv(key, str(default)))


def _env_bool(key: str, default: bool) -> bool:
    return os.getenv(key, str(default)).lower() in ("1", "true", "yes")


class OpsGuard:
    """Operational safety limits - hard throttles that protect capital."""

    def __init__(self):
        # Rate limiting
        self.max_trades_per_hour: int = _env_int("MAX_TRADES_PER_HOUR", 10)
        self.max_trades_per_day: int = _env_int("MAX_TRADES_PER_DAY", 50)

        # Position sizing limits
        self.max_single_position_pct: float = _env_float("MAX_SINGLE_POSITION_PCT", 5.0)  # 500% of equity (notional with leverage)
        self.max_total_exposure_pct: float = _env_float("MAX_TOTAL_EXPOSURE_PCT", 10.0)  # 1000% of equity (aggregate notional)

        # Kill switch
        self._killed = False
        self._kill_reason = ""
        self._kill_file = os.getenv("KILL_SWITCH_FILE", "data/.kill_switch")

        # Trade timestamps for rate limiting
        self._trade_times: list = []
        self._lock = threading.Lock()

        # Check for persistent kill switch on startup
        if os.path.exists(self._kill_file):
            self._killed = True
            try:
                with open(self._kill_file, "r") as f:
                    self._kill_reason = f.read().strip() or "Kill switch file found on startup"
            except Exception:
                self._kill_reason = "Kill switch file found on startup"
            logger.warning(f"[OPS] Kill switch active on startup: {self._kill_reason}")

    # ── Kill Switch ─────────────────────────────────────────

    @property
    def is_killed(self) -> bool:
        return self._killed

    @property
    def kill_reason(self) -> str:
        return self._kill_reason

    def kill(self, reason: str = "Manual kill") -> None:
        """Activate kill switch. Halts all execution immediately."""
        self._killed = True
        self._kill_reason = reason
        # Persist to file so it survives restarts
        try:
            os.makedirs(os.path.dirname(self._kill_file), exist_ok=True)
            with open(self._kill_file, "w") as f:
                f.write(f"{reason}\n{time.time()}")
        except Exception:
            pass
        logger.warning(f"[OPS] KILL SWITCH ACTIVATED: {reason}")

    def unkill(self) -> None:
        """Deactivate kill switch."""
        self._killed = False
        self._kill_reason = ""
        try:
            if os.path.exists(self._kill_file):
                os.remove(self._kill_file)
        except Exception:
            pass
        logger.info("[OPS] Kill switch deactivated")

    # ── Rate Limiting ───────────────────────────────────────

    def record_trade(self) -> None:
        """Record a trade execution for rate limiting."""
        with self._lock:
            self._trade_times.append(time.time())
            # Keep only last 24h
            cutoff = time.time() - 86400
            self._trade_times = [t for t in self._trade_times if t > cutoff]

    def trades_last_hour(self) -> int:
        cutoff = time.time() - 3600
        with self._lock:
            return sum(1 for t in self._trade_times if t > cutoff)

    def trades_last_day(self) -> int:
        cutoff = time.time() - 86400
        with self._lock:
            return sum(1 for t in self._trade_times if t > cutoff)

    # ── Pre-Execution Check ─────────────────────────────────

    def can_execute(
        self,
        position_size_usd: float = 0.0,
        equity: float = 10000.0,
        total_exposure_usd: float = 0.0,
    ) -> Dict[str, Any]:
        """Check if a trade execution is allowed.

        Returns:
            {"allowed": bool, "reason": str}
        """
        # Kill switch
        if self._killed:
            return {"allowed": False, "reason": f"Kill switch: {self._kill_reason}"}

        # Hourly rate limit
        hourly = self.trades_last_hour()
        if hourly >= self.max_trades_per_hour:
            return {"allowed": False, "reason": f"Rate limit: {hourly}/{self.max_trades_per_hour} trades/hour"}

        # Daily rate limit
        daily = self.trades_last_day()
        if daily >= self.max_trades_per_day:
            return {"allowed": False, "reason": f"Rate limit: {daily}/{self.max_trades_per_day} trades/day"}

        # Single position size check
        if equity > 0 and position_size_usd > 0:
            pos_pct = position_size_usd / equity
            if pos_pct > self.max_single_position_pct:
                return {
                    "allowed": False,
                    "reason": f"Position size {pos_pct:.1%} > max {self.max_single_position_pct:.1%}",
                }

        # Total exposure check
        if equity > 0 and total_exposure_usd > 0:
            exp_pct = (total_exposure_usd + position_size_usd) / equity
            if exp_pct > self.max_total_exposure_pct:
                return {
                    "allowed": False,
                    "reason": f"Total exposure {exp_pct:.1%} > max {self.max_total_exposure_pct:.1%}",
                }

        return {"allowed": True, "reason": "OK"}

    def format_status(self) -> str:
        """Format ops guard status for display."""
        lines = ["*Ops Guard:*"]
        lines.append(f"  Kill switch: {'ACTIVE' if self._killed else 'OFF'}")
        if self._killed:
            lines.append(f"  Reason: {self._kill_reason}")
        lines.append(f"  Trades/hour: {self.trades_last_hour()}/{self.max_trades_per_hour}")
        lines.append(f"  Trades/day: {self.trades_last_day()}/{self.max_trades_per_day}")
        lines.append(f"  Max pos size: {self.max_single_position_pct:.0%}")
        lines.append(f"  Max exposure: {self.max_total_exposure_pct:.0%}")
        return "\n".join(lines)
