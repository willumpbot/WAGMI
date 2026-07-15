"""
MFE-Aware Exit Intelligence — Data-driven exit decisions based on
Maximum Favorable Excursion (MFE) and Maximum Adverse Excursion (MAE).

Key insight: every symbol has a *typical* move size within a holding window.
If uPnL already exceeds the median MFE, the position has captured more
than most trades ever will — take the gift.  Conversely, if drawdown
exceeds the median MAE after several hours, recovery is unlikely.

MFE/MAE percentile data is computed live from the bot's own realized
closes (paper_trades/trades_*.csv, n>=13 per symbol/side; see MFE_MAE_DATA
below), falling back to a conservative static default when evidence is
thin.

Recommendation hierarchy:
  EXIT_NOW       — close immediately (loser past recovery window)
  TAKE_PROFIT    — close at market (captured > 2x median MFE)
  TIGHTEN_STOP   — move SL to breakeven or better (fading momentum)
  HOLD           — no action needed
"""

import csv
import glob
import logging
import math
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

logger = logging.getLogger("bot.execution.mfe_exit")

# ─── MFE / MAE percentile table (LIVING VALUES, 2026-07-15) ─────────
# Was a static table "sourced from a 2h holding-window study on Hyperliquid
# SHORT positions (March 2026)" -- acted on LIVE with close authority
# (multi_strategy_main.py calls get_exit_recommendation every tick and
# force-closes on TAKE_PROFIT/EXIT_NOW) yet diverged up to ~2x from the
# realized ledger: HYPE mfe_p50 1.43 (n=31 live) vs hardcoded 0.78 meant
# TAKE_PROFIT fired at 2x0.78=1.56% when the realized MEDIAN winner
# excursion alone is 1.43%. SOL mfe_p50 0.72 vs 0.51. ETH mae_p50 0.38 vs
# 0.50 (EXIT_NOW waited too long). XRP (n=28, live-traded) was entirely
# absent and fell to DEFAULT_MFE_MAE (0.40/0.42) vs realized 0.69/0.62,
# causing premature exits on every XRP trade. Also SHORT-only, so longs
# were judged by short percentiles.
#
# Replaced with a live per-SYMBOL and per-SYMBOL_SIDE computation from
# paper_trades/trades_*.csv close rows (mfe_pct/mae_pct columns), reusing
# position_manager._compute_live_setup_time_stops's exact row hygiene
# (skip action=OPEN, skip TEST symbols, skip test-fixture prices
# {100,150,50000}, dedupe on symbol/action/side/price/qty/timestamp) plus
# one extra filter: rows where mfe_pct==mae_pct==0.0 are TP1/
# LLM_EXIT_PARTIAL partial-close legs with no excursion recorded
# (placeholder, not a genuine zero-move trade) and are skipped so they
# don't drag percentiles toward zero. n>=13 required per key (side-
# specific first, then symbol-pooled, then DEFAULT_MFE_MAE) else the
# static DEFAULT_MFE_MAE floor governs. Cached with ledger-mtime+hourly-
# TTL like leverage.py's Kelly-leverage cache.
#
# NOTE: mutated in place (clear()+update(), never reassigned) so existing
# `from execution.mfe_exit import MFE_MAE_DATA` references stay live.
MFE_MAE_DATA: Dict[str, Dict[str, float]] = {}

# Fallback when a symbol/side has no n>=13 live data yet — conservative
# average of the original BTC/ETH study values.
DEFAULT_MFE_MAE = {
    "mfe_p50": 0.40, "mfe_p75": 0.80,
    "mae_p50": 0.42, "mae_p75": 0.80,
}

_MFE_MAE_MIN_N = 13
_MFE_MAE_TTL_S = 3600  # refresh at most hourly, or immediately on ledger mtime change
_MFE_MAE_TEST_PRICES = (100.0, 150.0, 50000.0)
_mfe_mae_cache = {"computed_at": 0.0, "ledger_mtime": 0.0}
_mfe_mae_lock = threading.Lock()


def _normalise_symbol_for_ledger(symbol: str) -> str:
    """Strip exchange suffixes for grouping ledger rows (mirrors
    MFEExitAdvisor._normalise_symbol)."""
    sym = (symbol or "").upper()
    for suffix in ("/USDT:USDT", "/USDT", "-PERP", "-USD", "USDT", "USD"):
        if sym.endswith(suffix):
            sym = sym[: -len(suffix)]
            break
    return sym


def _percentile(sorted_vals: list, pct: float) -> float:
    """Linear-interpolation percentile (numpy default method). Assumes
    sorted_vals is already sorted ascending."""
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    if n == 1:
        return sorted_vals[0]
    k = (n - 1) * pct
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    return sorted_vals[int(f)] * (c - k) + sorted_vals[int(c)] * (k - f)


def _compute_live_mfe_mae() -> Dict[str, Dict[str, float]]:
    """Live per-SYMBOL and per-SYMBOL_SIDE MFE/MAE percentiles from realized
    closes in paper_trades/trades_*.csv. See module-level comment above for
    the row hygiene. Never raises -- returns {} on any failure so
    DEFAULT_MFE_MAE governs everything."""
    try:
        rows_by_key: Dict[tuple, dict] = {}
        for path in glob.glob(os.path.join("paper_trades", "trades_*.csv")):
            try:
                with open(path, newline="") as f:
                    for row in csv.DictReader(f):
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
                        if price in _MFE_MAE_TEST_PRICES:
                            continue
                        dedup_key = (
                            symbol, action, row.get("side"), row.get("price"),
                            row.get("qty"), row.get("timestamp"),
                        )
                        rows_by_key[dedup_key] = row
            except Exception:
                continue  # one bad/partial file shouldn't kill the whole computation

        grouped: Dict[str, Dict[str, list]] = {}
        for row in rows_by_key.values():
            try:
                mfe = float(row.get("mfe_pct") or 0.0)
                mae = float(row.get("mae_pct") or 0.0)
            except (TypeError, ValueError):
                continue
            if mfe == 0.0 and mae == 0.0:
                continue  # partial-close placeholder, no real excursion recorded
            base_sym = _normalise_symbol_for_ledger(row.get("symbol") or "")
            if not base_sym:
                continue
            side_raw = (row.get("side") or "").upper()
            side_label = "BUY" if side_raw in ("LONG", "BUY") else "SELL"
            for key in (base_sym, f"{base_sym}_{side_label}"):
                bucket = grouped.setdefault(key, {"mfe": [], "mae": []})
                bucket["mfe"].append(mfe)
                bucket["mae"].append(mae)

        result: Dict[str, Dict[str, float]] = {}
        for key, vals in grouped.items():
            n = len(vals["mfe"])
            if n < _MFE_MAE_MIN_N:
                continue
            mfes = sorted(vals["mfe"])
            maes = sorted(vals["mae"])
            result[key] = {
                "mfe_p50": round(_percentile(mfes, 0.50), 4),
                "mfe_p75": round(_percentile(mfes, 0.75), 4),
                "mae_p50": round(_percentile(maes, 0.50), 4),
                "mae_p75": round(_percentile(maes, 0.75), 4),
            }
        return result
    except Exception as e:
        logger.warning(f"Live MFE/MAE computation failed, using DEFAULT_MFE_MAE: {e}")
        return {}


def _mfe_mae_ledger_mtime() -> float:
    try:
        mtimes = [
            os.path.getmtime(p)
            for p in glob.glob(os.path.join("paper_trades", "trades_*.csv"))
        ]
        return max(mtimes) if mtimes else 0.0
    except OSError:
        return 0.0


def _ensure_mfe_mae_fresh() -> None:
    """Refresh MFE_MAE_DATA in place at most hourly, or immediately on
    ledger mtime change. Mutates (clear+update) rather than reassigns so
    existing `from execution.mfe_exit import MFE_MAE_DATA` references stay
    live. Never raises -- a failed refresh just keeps the prior cache."""
    now = time.time()
    led_mtime = _mfe_mae_ledger_mtime()
    with _mfe_mae_lock:
        stale = (
            now - _mfe_mae_cache["computed_at"] > _MFE_MAE_TTL_S
            or led_mtime != _mfe_mae_cache["ledger_mtime"]
        )
        if not stale:
            return
        live = _compute_live_mfe_mae()
        MFE_MAE_DATA.clear()
        MFE_MAE_DATA.update(live)
        _mfe_mae_cache["computed_at"] = now
        _mfe_mae_cache["ledger_mtime"] = led_mtime


@dataclass
class ExitRecommendation:
    """Output of the MFE exit advisor."""
    action: str             # HOLD | TAKE_PROFIT | TIGHTEN_STOP | EXIT_NOW
    urgency: str = "low"    # low | medium | high | critical
    reason: str = ""
    upnl_pct: float = 0.0   # current uPnL as % of entry
    mfe_ratio: float = 0.0   # uPnL / median MFE (>1 = above median)
    mae_ratio: float = 0.0   # |drawdown| / median MAE (>1 = deeper than typical)
    hold_hours: float = 0.0


class MFEExitAdvisor:
    """
    Data-driven exit intelligence using MFE/MAE percentile benchmarks.

    Parameters
    ----------
    take_profit_mfe_mult : float
        Take profit when uPnL > this * median MFE.  Default 2.0.
    tighten_mfe_mult : float
        Tighten stop when uPnL > this * median MFE with fading momentum.
        Default 1.5.
    loser_timeout_hours : float
        Exit losing positions older than this.  Default 4.0.
    deep_loss_timeout_hours : float
        Exit positions in deep drawdown (>1x MAE) after this many hours.
        Default 2.0.
    volume_spike_mult : float
        Volume spike threshold for momentum-cascade HOLD override.
        Default 3.0.
    """

    def __init__(
        self,
        take_profit_mfe_mult: float = 2.0,
        tighten_mfe_mult: float = 1.5,
        loser_timeout_hours: float = 4.0,
        deep_loss_timeout_hours: float = 2.0,
        volume_spike_mult: float = 3.0,
    ):
        self.take_profit_mfe_mult = take_profit_mfe_mult
        self.tighten_mfe_mult = tighten_mfe_mult
        self.loser_timeout_hours = loser_timeout_hours
        self.deep_loss_timeout_hours = deep_loss_timeout_hours
        self.volume_spike_mult = volume_spike_mult

    # ─── public API ─────────────────────────────────────────────────

    def evaluate(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        current_price: float,
        open_timestamp: float,
        leverage: float = 1.0,
        current_volume: Optional[float] = None,
        avg_volume: Optional[float] = None,
    ) -> ExitRecommendation:
        """
        Evaluate an open position and return an exit recommendation.

        Parameters
        ----------
        symbol : str
            Trading symbol (e.g. "BTC", "SOL", "HYPE").
        side : str
            "BUY" (long) or "SELL" (short).
        entry_price : float
            Position entry price.
        current_price : float
            Current market price.
        open_timestamp : float
            Unix timestamp when the position was opened.
        leverage : float
            Position leverage (used for logging context, not decision logic).
        current_volume : float, optional
            Current candle volume.
        avg_volume : float, optional
            Average volume over recent candles.

        Returns
        -------
        ExitRecommendation
        """
        # Normalise symbol (strip /USDT, -PERP, etc.)
        sym = self._normalise_symbol(symbol)
        side_label = "BUY" if side.upper() == "BUY" else "SELL"
        _ensure_mfe_mae_fresh()
        data = (
            MFE_MAE_DATA.get(f"{sym}_{side_label}")
            or MFE_MAE_DATA.get(sym)
            or DEFAULT_MFE_MAE
        )

        # Calculate uPnL percentage
        if side.upper() == "BUY":
            upnl_pct = ((current_price - entry_price) / entry_price) * 100
        else:
            upnl_pct = ((entry_price - current_price) / entry_price) * 100

        hold_hours = (time.time() - open_timestamp) / 3600.0

        mfe_p50 = data["mfe_p50"]
        mae_p50 = data["mae_p50"]

        mfe_ratio = upnl_pct / mfe_p50 if mfe_p50 > 0 else 0.0
        mae_ratio = abs(upnl_pct) / mae_p50 if (upnl_pct < 0 and mae_p50 > 0) else 0.0

        base = ExitRecommendation(
            action="HOLD",
            upnl_pct=upnl_pct,
            mfe_ratio=mfe_ratio,
            mae_ratio=mae_ratio,
            hold_hours=hold_hours,
        )

        # ── Rule 1: Volume spike + price in our favor → HOLD (momentum cascade)
        if self._has_volume_spike(current_volume, avg_volume) and upnl_pct > 0:
            base.action = "HOLD"
            base.reason = (
                f"Volume spike ({current_volume:.0f} vs avg {avg_volume:.0f}) "
                f"with positive uPnL — momentum cascade, let it run"
            )
            logger.info(f"[MFE-Exit] {sym} HOLD — {base.reason}")
            return base

        # ── Rule 2: uPnL > 2x median MFE → TAKE_PROFIT
        if upnl_pct > 0 and mfe_ratio >= self.take_profit_mfe_mult:
            base.action = "TAKE_PROFIT"
            base.urgency = "high"
            base.reason = (
                f"uPnL {upnl_pct:.3f}% is {mfe_ratio:.1f}x the median MFE "
                f"({mfe_p50:.2f}%) — captured more than typical, take profit"
            )
            logger.info(f"[MFE-Exit] {sym} TAKE_PROFIT — {base.reason}")
            return base

        # ── Rule 3: uPnL > 1.5x median MFE + fading momentum → TIGHTEN_STOP
        if upnl_pct > 0 and mfe_ratio >= self.tighten_mfe_mult:
            momentum_fading = self._is_momentum_fading(current_volume, avg_volume)
            if momentum_fading:
                base.action = "TIGHTEN_STOP"
                base.urgency = "medium"
                base.reason = (
                    f"uPnL {upnl_pct:.3f}% is {mfe_ratio:.1f}x median MFE "
                    f"and momentum fading — tighten stop to lock gains"
                )
                logger.info(f"[MFE-Exit] {sym} TIGHTEN_STOP — {base.reason}")
                return base

        # ── Rule 4: Open > 2h AND drawdown > 1x median MAE → EXIT_NOW
        if (
            hold_hours >= self.deep_loss_timeout_hours
            and upnl_pct < 0
            and mae_ratio >= 1.0
        ):
            base.action = "EXIT_NOW"
            base.urgency = "critical"
            base.reason = (
                f"Open {hold_hours:.1f}h with drawdown {upnl_pct:.3f}% "
                f"({mae_ratio:.1f}x median MAE {mae_p50:.2f}%) — "
                f"deeper than typical, cut loss"
            )
            logger.info(f"[MFE-Exit] {sym} EXIT_NOW — {base.reason}")
            return base

        # ── Rule 5: Open > 4h AND still losing → EXIT_NOW
        if hold_hours >= self.loser_timeout_hours and upnl_pct < 0:
            base.action = "EXIT_NOW"
            base.urgency = "high"
            base.reason = (
                f"Loser open {hold_hours:.1f}h with uPnL {upnl_pct:.3f}% — "
                f"positions that haven't recovered by {self.loser_timeout_hours}h rarely do"
            )
            logger.info(f"[MFE-Exit] {sym} EXIT_NOW — {base.reason}")
            return base

        # ── Default: HOLD
        base.reason = (
            f"uPnL {upnl_pct:.3f}% after {hold_hours:.1f}h — "
            f"within normal MFE/MAE range, hold"
        )
        logger.debug(f"[MFE-Exit] {sym} HOLD — {base.reason}")
        return base

    # ─── convenience function (module-level wrapper below) ──────────

    def should_take_profit(
        self,
        symbol: str,
        entry_price: float,
        current_price: float,
        side: str,
        leverage: float = 1.0,
        hold_hours: float = 0.0,
    ) -> bool:
        """
        Quick check: should this position take profit now?

        Uses a synthetic open_timestamp derived from hold_hours so the
        full evaluate() logic applies without needing a real timestamp.
        """
        open_ts = time.time() - (hold_hours * 3600)
        rec = self.evaluate(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            current_price=current_price,
            open_timestamp=open_ts,
            leverage=leverage,
        )
        return rec.action in ("TAKE_PROFIT", "EXIT_NOW")

    # ─── helpers ────────────────────────────────────────────────────

    def _has_volume_spike(
        self, current_volume: Optional[float], avg_volume: Optional[float]
    ) -> bool:
        """True if current volume is a significant spike above average."""
        if current_volume is None or avg_volume is None:
            return False
        if avg_volume <= 0:
            return False
        return current_volume >= avg_volume * self.volume_spike_mult

    def _is_momentum_fading(
        self, current_volume: Optional[float], avg_volume: Optional[float]
    ) -> bool:
        """
        Heuristic for fading momentum: volume is below average.
        When volume data is unavailable, assume momentum *could* be fading
        (conservative — better to tighten than miss the exit).
        """
        if current_volume is None or avg_volume is None:
            return True  # conservative: assume fading when no data
        if avg_volume <= 0:
            return True
        return current_volume < avg_volume

    @staticmethod
    def _normalise_symbol(symbol: str) -> str:
        """Strip exchange suffixes: 'BTC/USDT:USDT' → 'BTC', 'SOL-PERP' → 'SOL'."""
        sym = symbol.upper()
        for suffix in ("/USDT:USDT", "/USDT", "-PERP", "-USD", "USDT", "USD"):
            if sym.endswith(suffix):
                sym = sym[: -len(suffix)]
                break
        return sym


# ─── Module-level convenience function ──────────────────────────────

_default_advisor = MFEExitAdvisor()


def should_take_profit(
    symbol: str,
    entry: float,
    current_price: float,
    side: str,
    leverage: float = 1.0,
    hold_hours: float = 0.0,
) -> bool:
    """
    Module-level convenience: should this position take profit?

    Returns True if the MFE advisor recommends TAKE_PROFIT or EXIT_NOW.
    """
    return _default_advisor.should_take_profit(
        symbol=symbol,
        entry_price=entry,
        current_price=current_price,
        side=side,
        leverage=leverage,
        hold_hours=hold_hours,
    )


def get_exit_recommendation(
    symbol: str,
    side: str,
    entry_price: float,
    current_price: float,
    open_timestamp: float,
    leverage: float = 1.0,
    current_volume: Optional[float] = None,
    avg_volume: Optional[float] = None,
) -> ExitRecommendation:
    """Module-level convenience: get full exit recommendation."""
    return _default_advisor.evaluate(
        symbol=symbol,
        side=side,
        entry_price=entry_price,
        current_price=current_price,
        open_timestamp=open_timestamp,
        leverage=leverage,
        current_volume=current_volume,
        avg_volume=avg_volume,
    )
