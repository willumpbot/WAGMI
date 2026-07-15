"""
Momentum Tracker: tracks win/loss streaks per symbol for sizing adjustments.

Sizing multipliers are LIVE-computed per streak bucket from this bot's own
closed trades (data/trade_ledger.csv), not hardcoded. A bucket needs n>=13
realized closes AND its own realized avg net_pnl to support the direction
of the move before it can shift risk_mult away from neutral 1.0x.

Historical note: an earlier static table (2:1.3, 1:1.15, -1:0.6, -2:0.35)
cited a 2,172-*signal*-level WR spread (75% after 2 wins vs 29% after 2
losses) and stayed live in production despite this bot's own realized
*trade* studies contradicting the win-boost side: sizing_optimizer.py
removed its win-streak bonus (autocorrelation=0.090, near random: post-WIN
55.2% WR vs post-LOSS 46.2%), and RQ16_20 (see get_after_loss_multiplier)
measured post-loss 20.0% (n=65) vs post-win 45.8% (n=24) -- supporting
loss-side cuts but not after-win upsizing. The values below (1.3/1.15/
0.6/0.35) are now only a CEILING a bucket may reach once the live ledger
proves it earns that move; otherwise the multiplier is neutral 1.0x.
"""

import csv
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Optional, Any

logger = logging.getLogger("bot.execution.momentum_tracker")

# ── LIVE PER-STREAK-BUCKET SIZING MULTIPLIER (LIVING VALUES, 2026-07-15) ────
# Ceilings are the ORIGINAL evidence-cited bounds -- a bucket only reaches
# its ceiling once the live ledger shows the bucket itself earns it (see
# _compute_live_streak_mults). Mirrors execution/leverage.py's
# _ensure_kelly_lev_fresh mtime+TTL cache pattern and sim-row exclusion.
_STREAK_MULT_CEILING = {
    2: 1.3,    # After 2+ consecutive wins, IF the bucket is proven profitable
    1: 1.15,   # After 1 win, IF the bucket is proven profitable
    0: 1.0,    # No streak: always baseline
    -1: 0.6,   # After 1 loss, IF the bucket is proven a drag
    -2: 0.35,  # After 2+ losses, IF the bucket is proven a drag
}
_STREAK_MULT_MIN_N = 13
_STREAK_MULT_TTL_S = 3600  # refresh at most hourly, or immediately on ledger mtime change
_LEDGER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "trade_ledger.csv")
_streak_mult_cache = {"mults": {}, "stats": {}, "post_outcome": {}, "computed_at": 0.0, "ledger_mtime": 0.0}
_streak_mult_lock = threading.Lock()


def _read_ledger_closes():
    """Yield (symbol, timestamp, net_pnl) for closed trades, excluding TEST/SIM
    symbols AND the June replay-sim pollution batch. Reuses the exact same
    exclusion as execution/leverage.py:_read_ledger_rows (_is_sim_pollution_row)."""
    from execution.leverage import _is_sim_pollution_row
    path = os.path.normpath(_LEDGER_PATH)
    if not os.path.exists(path):
        return
    with open(path, newline="", encoding="utf-8", errors="ignore") as f:
        for row in csv.DictReader(f):
            sym = (row.get("symbol") or "").strip().upper()
            if not sym or "TEST" in sym or "SIM" in sym:
                continue
            if _is_sim_pollution_row(row):
                continue
            try:
                ts = float(row.get("timestamp") or "")
                pnl = float(row.get("net_pnl") or "")
            except (ValueError, TypeError):
                continue
            yield sym, ts, pnl


def _compute_live_streak_mults():
    """Rebuild {bucket: multiplier} and {bucket: {n, avg_net_pnl}} by replaying
    each symbol's streak sequence chronologically (same update rule as
    record_outcome) and pooling each close's realized net_pnl under the PRIOR
    streak bucket it was sized under. Never raises."""
    stats: Dict[int, Dict[str, float]] = {b: {"n": 0, "avg_net_pnl": 0.0} for b in _STREAK_MULT_CEILING}
    try:
        by_symbol: Dict[str, list] = {}
        for sym, ts, pnl in _read_ledger_closes():
            by_symbol.setdefault(sym, []).append((ts, pnl))
        bucket_pnls: Dict[int, list] = {b: [] for b in _STREAK_MULT_CEILING}
        for sym, closes in by_symbol.items():
            closes.sort(key=lambda x: x[0])
            streak = 0
            for _ts, pnl in closes:
                bucket = 2 if streak >= 2 else (-2 if streak <= -2 else streak)
                bucket_pnls[bucket].append(pnl)
                if pnl > 0:
                    streak = max(1, streak + 1) if streak >= 0 else 1
                else:
                    streak = min(-1, streak - 1) if streak <= 0 else -1
        for bucket, pnls in bucket_pnls.items():
            n = len(pnls)
            avg = (sum(pnls) / n) if n else 0.0
            stats[bucket] = {"n": n, "avg_net_pnl": round(avg, 4)}
    except Exception as e:
        logger.debug(f"momentum_tracker: live streak mult recompute failed: {e}")

    mults: Dict[int, float] = {}
    for bucket, ceiling in _STREAK_MULT_CEILING.items():
        n = stats[bucket]["n"]
        avg = stats[bucket]["avg_net_pnl"]
        if bucket == 0:
            mults[bucket] = 1.0
        elif bucket > 0:
            # Boost must be earned: size up only if the bucket is itself profitable.
            mults[bucket] = ceiling if (n >= _STREAK_MULT_MIN_N and avg > 0) else 1.0
        else:
            # Cut only if the bucket is itself a realized drag.
            mults[bucket] = ceiling if (n >= _STREAK_MULT_MIN_N and avg < 0) else 1.0
    return mults, stats


def _compute_live_post_outcome_wr():
    """Book-level post-win/post-loss next-close WR, re-derived live from the
    ledger on the same schedule as the streak-bucket table -- replaces the
    static 20.0%/45.8% (RQ16_20) citation with a self-updating measurement.
    Diagnostic only; does not change get_after_loss_multiplier's env-tunable
    behavior. Never raises."""
    try:
        closes = sorted(_read_ledger_closes(), key=lambda x: x[1])
        prev_won: Optional[bool] = None
        post_win, post_loss = [], []
        for _sym, _ts, pnl in closes:
            won = pnl > 0
            if prev_won is True:
                post_win.append(won)
            elif prev_won is False:
                post_loss.append(won)
            prev_won = won
        n_pw, n_pl = len(post_win), len(post_loss)
        return {
            "post_win_wr": round(sum(post_win) / n_pw, 3) if n_pw else 0.0,
            "post_win_n": n_pw,
            "post_loss_wr": round(sum(post_loss) / n_pl, 3) if n_pl else 0.0,
            "post_loss_n": n_pl,
        }
    except Exception as e:
        logger.debug(f"momentum_tracker: live post-outcome WR recompute failed: {e}")
        return {"post_win_wr": 0.0, "post_win_n": 0, "post_loss_wr": 0.0, "post_loss_n": 0}


def _ensure_streak_mult_fresh() -> None:
    path = os.path.normpath(_LEDGER_PATH)
    now = time.time()
    try:
        led_mtime = os.path.getmtime(path) if os.path.exists(path) else 0.0
    except OSError:
        led_mtime = 0.0
    with _streak_mult_lock:
        stale = (now - _streak_mult_cache["computed_at"] > _STREAK_MULT_TTL_S) or (led_mtime != _streak_mult_cache["ledger_mtime"])
        if stale:
            mults, stats = _compute_live_streak_mults()
            post_outcome = _compute_live_post_outcome_wr()
            _streak_mult_cache.update({
                "mults": mults, "stats": stats, "post_outcome": post_outcome,
                "computed_at": now, "ledger_mtime": led_mtime,
            })


class MomentumTracker:
    """Tracks win/loss momentum per symbol for data-driven sizing."""

    def __init__(self, state_path: str = "data/momentum_state.json"):
        self._state_path = state_path
        # streak > 0 = consecutive wins, < 0 = consecutive losses
        self._streaks: Dict[str, int] = {}
        self._last_outcome: Dict[str, bool] = {}
        # GLOBAL (book-level) outcome of the most recent close across ALL
        # symbols. RQ16_20_RISK_MATH Part A: WR after a loss = 20.0% (n=65)
        # vs after a win = 45.8% (n=24), runs-test clustering p=0.012
        # (survives era-split p=0.024). None = no close recorded yet.
        self._global_last_win: Optional[bool] = None
        self._load_state()

    def _load_state(self):
        try:
            # Don't load state if file doesn't exist or in test environments
            import sys
            if "pytest" in sys.modules:
                return
            if os.path.exists(self._state_path):
                with open(self._state_path) as f:
                    state = json.load(f)
                self._streaks = state.get("streaks", {})
                self._last_outcome = {k: v for k, v in state.get("last_outcome", {}).items()}
                self._global_last_win = state.get("global_last_win")
        except Exception as e:
            logger.debug(f"Momentum state load error: {e}")

    def _save_state(self):
        try:
            os.makedirs(os.path.dirname(self._state_path) or ".", exist_ok=True)
            with open(self._state_path, "w") as f:
                json.dump({
                    "streaks": self._streaks,
                    "last_outcome": self._last_outcome,
                    "global_last_win": self._global_last_win,
                    "updated": datetime.now(timezone.utc).isoformat(),
                }, f)
        except Exception as e:
            logger.debug(f"Momentum state save error: {e}")

    def record_outcome(self, symbol: str, won: bool):
        """Record a trade outcome for streak tracking."""
        sym = symbol.replace("/USDC:USDC", "").replace("/USDT:USDT", "")
        current = self._streaks.get(sym, 0)

        if won:
            self._streaks[sym] = max(1, current + 1) if current >= 0 else 1
        else:
            self._streaks[sym] = min(-1, current - 1) if current <= 0 else -1

        self._last_outcome[sym] = won
        self._global_last_win = won  # book-level: last close across ALL symbols
        self._save_state()

        logger.info(
            f"[MOMENTUM] {sym}: {'WIN' if won else 'LOSS'} -> "
            f"streak={self._streaks[sym]:+d} "
            f"-> size_mult={self.get_multiplier(symbol):.2f}x"
        )

    def get_multiplier(self, symbol: str) -> float:
        """Get sizing multiplier based on current streak.

        LIVE-computed per streak bucket from data/trade_ledger.csv (n>=13,
        boost/cut only applied when the bucket's own realized avg net_pnl
        supports it -- see _compute_live_streak_mults). Bounded by the same
        0.35x-1.3x ceilings as the original table; defaults to neutral 1.0x
        for any bucket without live proof.
        """
        sym = symbol.replace("/USDC:USDC", "").replace("/USDT:USDT", "")
        streak = self._streaks.get(sym, 0)
        bucket = 2 if streak >= 2 else (-2 if streak <= -2 else streak)

        _ensure_streak_mult_fresh()
        with _streak_mult_lock:
            return _streak_mult_cache["mults"].get(bucket, 1.0)

    def get_streak_bucket_stats(self) -> Dict[str, Any]:
        """Diagnostics for the live per-streak-bucket multiplier decision
        (mirrors execution/leverage.py:live_symbol_kelly_lev_meta)."""
        _ensure_streak_mult_fresh()
        with _streak_mult_lock:
            return {
                "mults": dict(_streak_mult_cache["mults"]),
                "stats": dict(_streak_mult_cache["stats"]),
            }

    def get_streak(self, symbol: str) -> int:
        """Get current streak for a symbol. Positive = wins, negative = losses."""
        sym = symbol.replace("/USDC:USDC", "").replace("/USDT:USDT", "")
        return self._streaks.get(sym, 0)

    def get_after_loss_multiplier(self) -> float:
        """Book-level after-loss de-sizing multiplier (RQ16_20 Part A).

        Evidence (original citation): next-trade WR after a realized LOSS
        was 20.0% (n=65) vs 45.8% after a win (n=24); loss clustering
        runs-test p=0.012 (p=0.024 inside Jun7+ alone). These stats are now
        re-derived live on the same schedule as the streak-bucket table --
        call get_after_loss_stats_live() for the current numbers. Window =
        1 trade: the multiplier applies until the NEXT close updates the
        global last-outcome. Stacks multiplicatively with the per-symbol
        momentum ladder.

        Env: AFTER_LOSS_RISK_MULT (default 0.5). Set to 1.0 to disable.
        """
        if self._global_last_win is not False:  # None (no data) or True (won)
            return 1.0
        try:
            mult = float(os.getenv("AFTER_LOSS_RISK_MULT", "0.5"))
        except (TypeError, ValueError):
            mult = 0.5
        # De-sizing only: never allow this knob to size UP after a loss.
        return max(0.1, min(1.0, mult))

    def get_after_loss_stats_live(self) -> Dict[str, Any]:
        """Live-recomputed post-win/post-loss next-close WR (RQ16_20),
        refreshed on the same mtime+TTL schedule as the streak-bucket table.
        Diagnostic only -- get_after_loss_multiplier's returned value stays
        env-tunable (AFTER_LOSS_RISK_MULT) and gated on self._global_last_win,
        unchanged."""
        _ensure_streak_mult_fresh()
        with _streak_mult_lock:
            return dict(_streak_mult_cache["post_outcome"])

    def should_skip(self, symbol: str) -> bool:
        """Should we skip this symbol due to extreme losing streak?

        After 3+ consecutive losses: 29% WR is below breakeven for any R:R.
        Disabled by MOMENTUM_SKIP_ENABLED=false env var for testing.
        """
        if os.getenv("MOMENTUM_SKIP_ENABLED", "true").lower() not in ("1", "true", "yes"):
            return False
        return self.get_streak(symbol) <= -3

    def get_all_streaks(self) -> Dict[str, int]:
        """Get all symbol streaks for monitoring."""
        return dict(self._streaks)


# Module-level singleton
_tracker: Optional[MomentumTracker] = None


def get_momentum_tracker() -> MomentumTracker:
    global _tracker
    if _tracker is None:
        _tracker = MomentumTracker()
    return _tracker


def reset_momentum_tracker():
    """Reset singleton (for testing)."""
    global _tracker
    _tracker = None
