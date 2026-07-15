"""
Strategy 2: Momentum Scorer
Redesigned from the original zone-based confidence scorer.

Core logic:
- ADX + Directional Index for trend strength & direction
- MACD histogram for momentum acceleration
- Bollinger Band / Keltner Channel squeeze for breakout detection
- RSI divergence for reversal detection
- Historical accuracy tracking per (symbol, signal_type) — carried forward
- Uses 1h data only (backtest-compatible: CoinGecko provides 30d of 1h)
"""

import csv
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from pathlib import Path

import pandas as pd
import numpy as np

from .base import BaseStrategy, Signal

logger = logging.getLogger("bot.strategy.momentum_scorer")

# ── LIVING VALUES: shared ledger access (2026-07-15) ─────────────────────
# Read-only, mtime-cached access to the bot's own realized closed-trade
# ledger (data/trade_ledger.csv). Backs every de-hardcoded confidence
# adjustment in this file so each stays self-updating as new trades close,
# per the LIVING VALUES mandate (n>=13, never a frozen snapshot). Never
# writes to the ledger. Mirrors feedback/live_edge.py's cache pattern.
_LEDGER_PATH = Path(__file__).resolve().parent.parent / "data" / "trade_ledger.csv"
_LEDGER_CACHE: Dict[str, Any] = {"mtime": 0.0, "rows": []}
_SIM_ENTRY_PRICES = {100.0, 150.0, 50000.0}  # known synthetic/test entry prices


def _load_ledger_rows() -> List[Dict[str, Any]]:
    """Load+cache data/trade_ledger.csv, refreshing when the file's mtime changes."""
    try:
        mtime = _LEDGER_PATH.stat().st_mtime if _LEDGER_PATH.exists() else 0.0
    except OSError:
        mtime = 0.0
    if mtime and mtime == _LEDGER_CACHE.get("mtime"):
        return _LEDGER_CACHE["rows"]
    rows: List[Dict[str, Any]] = []
    try:
        if _LEDGER_PATH.exists():
            with open(_LEDGER_PATH, newline="", encoding="utf-8", errors="ignore") as f:
                for r in csv.DictReader(f):
                    try:
                        net = float(r.get("net_pnl") or "")
                    except (ValueError, TypeError):
                        continue  # unresolved/malformed row -- not a closed trade
                    try:
                        entry_px = float(r.get("entry_price") or 0)
                    except (ValueError, TypeError):
                        entry_px = 0.0
                    sym = str(r.get("symbol", "")).strip().upper()
                    if not sym or "TEST" in sym or entry_px in _SIM_ENTRY_PRICES:
                        continue
                    r["_net_pnl"] = net
                    r["_symbol"] = sym
                    r["_side"] = str(r.get("side", "")).strip().upper()  # LONG/SHORT
                    try:
                        r["_conf"] = float(r.get("confidence_score") or 0)
                    except (ValueError, TypeError):
                        r["_conf"] = 0.0
                    try:
                        r["_ts"] = float(r.get("timestamp") or 0)
                    except (ValueError, TypeError):
                        r["_ts"] = 0.0
                    rows.append(r)
    except Exception:
        rows = []
    _LEDGER_CACHE["mtime"] = mtime
    _LEDGER_CACHE["rows"] = rows
    return rows


def _closed_trades(symbol: Optional[str] = None, side: Optional[str] = None) -> List[Dict[str, Any]]:
    """Filtered view of the realized ledger. ``side`` is LONG/SHORT."""
    out = _load_ledger_rows()
    if symbol:
        out = [r for r in out if r["_symbol"] == symbol.upper()]
    if side:
        out = [r for r in out if r["_side"] == side.upper()]
    return out


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=max(2, span), adjust=False).mean()


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev).abs(),
        (df["low"] - prev).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=1).mean()


def _adx_di(df: pd.DataFrame, period: int = 14) -> Dict[str, pd.Series]:
    """Compute ADX, +DI, -DI."""
    high, low, close = df["high"], df["low"], df["close"]
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low

    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0), index=df.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0), index=df.index)

    atr_vals = _atr(df, period)
    atr_safe = atr_vals.replace(0, 1e-12)

    plus_di = 100 * _ema(plus_dm, period) / atr_safe
    minus_di = 100 * _ema(minus_dm, period) / atr_safe

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-12)
    adx = _ema(dx, period)

    return {"adx": adx, "plus_di": plus_di, "minus_di": minus_di}


def _macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD line, signal line, histogram."""
    macd_line = _ema(close, fast) - _ema(close, slow)
    signal_line = _ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _bollinger_bands(close: pd.Series, period: int = 20, std_mult: float = 2.0):
    """Bollinger Bands: upper, middle, lower."""
    mid = close.rolling(period, min_periods=1).mean()
    std = close.rolling(period, min_periods=1).std().fillna(0)
    return mid + std_mult * std, mid, mid - std_mult * std


def _keltner_channels(df: pd.DataFrame, period: int = 20, atr_mult: float = 1.5):
    """Keltner Channels: upper, middle, lower."""
    mid = _ema(df["close"], period)
    atr_vals = _atr(df, period)
    return mid + atr_mult * atr_vals, mid, mid - atr_mult * atr_vals


def _mfi_like(df: pd.DataFrame, period: int = 60) -> pd.Series:
    """Money Flow Index approximation (same as regime_trend)."""
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    mf = tp * df["volume"]
    up = (tp > tp.shift(1)).astype(float)
    dn = (tp < tp.shift(1)).astype(float)
    pos = mf.mul(up).rolling(period, min_periods=1).mean()
    neg = mf.mul(dn).rolling(period, min_periods=1).mean().replace(0, 1e-12)
    ratio = pos / neg
    return 100.0 - (100.0 / (1.0 + ratio))


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    roll_up = up.rolling(period, min_periods=1).mean()
    roll_down = down.rolling(period, min_periods=1).mean().replace(0, 1e-12)
    return 100 - (100 / (1 + roll_up / roll_down))


class ConfidenceScorerStrategy(BaseStrategy):
    """
    Multi-factor momentum strategy that combines ADX, MACD, Bollinger squeeze,
    and RSI for signal generation. Tracks historical accuracy per (symbol, signal_type)
    and adjusts confidence based on observed win rates.
    """

    def __init__(self, symbols: Dict[str, Any], data_dir: str = "ml_data", backtest_mode: bool = False):
        super().__init__("confidence_scorer", symbols)
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.signal_log_path = self.data_dir / "confidence_signal_log.json"
        self.signal_log = self._load_signal_log()
        self.backtest_mode = backtest_mode

    def get_required_timeframes(self) -> List[str]:
        return ["1h", "6h"]

    def _load_signal_log(self) -> Dict:
        if self.signal_log_path.exists():
            try:
                with open(self.signal_log_path) as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_signal_log(self):
        try:
            with open(self.signal_log_path, "w") as f:
                json.dump(self.signal_log, f, indent=2, default=str)
        except Exception as e:
            logger.warning(f"Failed to save signal log: {e}")

    def _log_signal(self, symbol: str, action: str, price: float, **flags):
        """Record a signal for later evaluation.

        ``**flags`` (LIVING VALUES 2026-07-15) persists per-signal condition
        flags (exhaustion_fired, htf_contra_fired, etc.) so they can later be
        joined against closed trades in data/trade_ledger.csv to compute live,
        self-updating penalty/adjustment values instead of frozen constants.
        """
        if symbol not in self.signal_log:
            self.signal_log[symbol] = []
        entry = {
            "signal": action,
            "price": price,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "evaluated": False,
        }
        entry.update(flags)
        self.signal_log[symbol].append(entry)
        self.signal_log[symbol] = self.signal_log[symbol][-200:]
        self._save_signal_log()

    def _get_historical_confidence(self, symbol: str, action: str) -> Optional[float]:
        """
        Calculate win rate for this (symbol, action) pair from the bot's own
        realized ledger (data/trade_ledger.csv). Returns None if insufficient
        data (n<13) or in backtest mode.

        LIVING VALUES fix (2026-07-15): this used to source WR from the
        signal-log's synthetic 1h-price-move "success" proxy. Ledger audit
        proved that proxy inverted vs realized PnL -- e.g. HYPE BUY graded
        58% WR (n=157) from the proxy while realized net was -$34.36/tr
        (n=17, worst edge on the book); the proxy also contained zero SELL
        entries, so the bot's best realized edges (ETH/BTC/SOL SHORT,
        +$20.37/+$10.70/+$7.65 per trade) were invisible to this adjustment.
        Now reads real closed-trade outcomes instead, mapping BUY->LONG and
        SELL->SHORT (STRONG_BUY/STRONG_SELL fold into the same bucket as
        their base action).

        In backtest mode, historical WR is disabled to prevent the cold-start death
        spiral: early losses poison WR → confidence drops → fewer trades → worse WR.
        The 7-day backtest showed WR decaying from 35% → 16% within a single run.
        """
        if self.backtest_mode:
            return None  # Prevent cold-start death spiral in backtests
        ledger_side = "LONG" if action.upper().replace("STRONG_", "").endswith("BUY") else "SHORT"
        trades = _closed_trades(symbol=symbol, side=ledger_side)
        n = len(trades)
        if n < 13:  # LIVING VALUES sample gate (was n>=30 against the stale proxy)
            return None
        wins = sum(1 for t in trades if t["_net_pnl"] > 0)
        avg_net = sum(t["_net_pnl"] for t in trades) / n
        wr = wins / n
        # With fewer than 50 samples, WR estimates are noisy — dampen toward 0.5.
        # Progressive dampening: 60% strength at 30 samples, full strength at 50.
        if n < 50:
            dampen_factor = n / 50
            wr = 0.5 + (wr - 0.5) * dampen_factor
        # WR alone can mislead (e.g. XRP SHORT: WR 78.6% but avg net -$0.14/tr) --
        # a net-losing slice can never earn a positive confidence nudge.
        if avg_net < 0:
            wr = min(wr, 0.5)
        return wr

    def evaluate_past_signals(self, symbol: str, current_price: float):
        """Evaluate unresolved signals based on subsequent price movement.

        Signals must be at least 1 hour old before evaluation to give the
        market time to move.  Evaluating on the next 1-minute tick was
        poisoning the historical WR with near-zero-move "failures".

        LIVING VALUES note (2026-07-15): this synthetic 1h-price-move grade
        is DIAGNOSTIC ONLY. It no longer feeds _get_historical_confidence()
        (that now reads realized ledger outcomes -- see there for why: this
        proxy was proven inverted vs realized PnL, e.g. HYPE BUY 58% proxy
        WR vs -$34.36/tr realized). Kept for get_performance_report() /
        get_status() visibility; nothing here may drive a confidence adjustment.
        """
        entries = self.signal_log.get(symbol, [])
        changed = False
        now = datetime.now(timezone.utc)
        for e in entries:
            if e["evaluated"]:
                continue
            # ── Wait at least 1 hour before evaluating ──
            try:
                ts = datetime.fromisoformat(e["timestamp"])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age_minutes = (now - ts).total_seconds() / 60
                if age_minutes < 60:
                    continue  # Too young to evaluate
            except (KeyError, ValueError):
                pass  # Missing/bad timestamp — evaluate anyway

            price_at_signal = e["price"]
            if price_at_signal <= 0:
                continue
            pct_move = (current_price - price_at_signal) / price_at_signal * 100

            success = False
            sig = e["signal"]
            if sig == "STRONG_BUY" and pct_move > 1.0:
                success = True
            elif sig == "BUY" and pct_move > 0.5:
                success = True
            elif sig == "SELL" and pct_move < -0.5:
                success = True
            elif sig == "STRONG_SELL" and pct_move < -1.0:
                success = True

            e["evaluated"] = True
            e["success"] = success
            e["exit_price"] = current_price
            e["pct_move"] = pct_move
            changed = True

        if changed:
            self._save_signal_log()

    def _detect_squeeze(self, df: pd.DataFrame) -> bool:
        """Detect Bollinger Band inside Keltner Channel (volatility squeeze)."""
        bb_upper, _, bb_lower = _bollinger_bands(df["close"])
        kc_upper, _, kc_lower = _keltner_channels(df)

        # Squeeze: BB inside KC (compressed volatility)
        squeeze = (bb_lower.iloc[-1] > kc_lower.iloc[-1]) and (bb_upper.iloc[-1] < kc_upper.iloc[-1])
        return squeeze

    def _detect_rsi_divergence(self, df: pd.DataFrame, rsi_vals: pd.Series, side: str, lookback: int = 10) -> bool:
        """Detect bullish or bearish RSI divergence."""
        if len(df) < lookback + 2:
            return False

        price = df["close"].iloc[-lookback:]
        rsi_window = rsi_vals.iloc[-lookback:]

        if side == "BUY":
            # Bullish divergence: price makes lower low but RSI makes higher low
            price_ll = price.iloc[-1] < price.iloc[:lookback // 2].min()
            rsi_hl = rsi_window.iloc[-1] > rsi_window.iloc[:lookback // 2].min()
            return price_ll and rsi_hl
        else:
            # Bearish divergence: price makes higher high but RSI makes lower high
            price_hh = price.iloc[-1] > price.iloc[:lookback // 2].max()
            rsi_lh = rsi_window.iloc[-1] < rsi_window.iloc[:lookback // 2].max()
            return price_hh and rsi_lh

    # ── LIVING VALUES: live per-side exhaustion penalty (2026-07-15) ────────
    # Seed constants from the ledger audit's log-join (48 exhaustion firings
    # joined to closed paper_trades by symbol+side, ±30min of open) -- used
    # ONLY until this strategy's own signal_log accumulates n>=13 directly
    # joined samples per side (see _exhaustion_join_stats). Both the aggregate
    # and SELL slices are net-profitable, so the old flat -15 ("90d backtest
    # 22% WR") was actively penalizing the bot's best realized edge
    # (ETH/BTC/SOL SELL, best condition = ADX>35 + RSI extreme).
    _EXHAUSTION_SEED = {
        "SELL": {"n": 31, "avg_net": 4.59, "wr": None},
        "BUY": {"n": 17, "avg_net": -0.97, "wr": None},
    }
    _EXHAUSTION_NONFLAGGED_WR = 0.56  # audit: n=217 non-flagged WR 56%
    _EXHAUSTION_FLAGGED_WR = 0.40     # audit: n=48 flagged (aggregate) WR 40%

    def _exhaustion_join_stats(self, side: str) -> Optional[Dict[str, float]]:
        """Join this strategy's own signal_log exhaustion_fired flags (persisted
        at signal time via _log_signal) to closed trades in data/trade_ledger.csv
        by symbol+side within 30 minutes of trade open. Mirrors the ledger
        audit's manual join. Returns None if fewer than 13 direct samples."""
        ledger_side = "SHORT" if side == "SELL" else "LONG"
        pnls: List[float] = []
        for symbol, entries in self.signal_log.items():
            flagged_ts = []
            for e in entries:
                sig = e.get("signal", "")
                if not sig or not e.get("exhaustion_fired"):
                    continue
                is_buy_signal = sig.endswith("BUY")
                if (side == "BUY") != is_buy_signal:
                    continue
                try:
                    ts = datetime.fromisoformat(e["timestamp"])
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    flagged_ts.append(ts.timestamp())
                except (KeyError, ValueError, TypeError):
                    continue
            if not flagged_ts:
                continue
            for row in _closed_trades(symbol=symbol, side=ledger_side):
                if any(abs(row["_ts"] - sts) <= 1800 for sts in flagged_ts):
                    pnls.append(row["_net_pnl"])
        n = len(pnls)
        if n < 13:
            return None
        wins = sum(1 for p in pnls if p > 0)
        return {"n": n, "avg_net": sum(pnls) / n, "wr": wins / n}

    def _get_exhaustion_penalty(self, side: str) -> int:
        """Live per-side momentum-exhaustion penalty. Never exceeds the static
        15 (safety ceiling unchanged). Prefers a direct join from this
        strategy's own accumulating signal_log; falls back to the 2026-07-15
        audit seed while direct samples are still <13; falls back to the
        original static 15 only if no live/seed data exists for the side."""
        try:
            live = self._exhaustion_join_stats(side)
            if live is not None:
                if live["avg_net"] >= 0:
                    return 0
                wr_flagged = live["wr"]
                return int(max(0, min(15, round((self._EXHAUSTION_NONFLAGGED_WR - wr_flagged) * 50))))
            seed = self._EXHAUSTION_SEED.get(side)
            if seed is not None:
                if seed["avg_net"] >= 0:
                    return 0
                wr_flagged = seed["wr"] if seed["wr"] is not None else self._EXHAUSTION_FLAGGED_WR
                return int(max(0, min(15, round((self._EXHAUSTION_NONFLAGGED_WR - wr_flagged) * 50))))
        except Exception as e:
            logger.warning(f"_get_exhaustion_penalty fallback to static 15: {e}")
        return 15  # cold-start fallback, never exceeded

    # ── LIVING VALUES: live per-(symbol,side) HTF-contra penalty (2026-07-15) ──
    def _htf_contra_join_stats(self, symbol: str, side: str) -> Optional[Dict[str, float]]:
        """Join persisted htf_contra_fired flags in this strategy's signal_log
        to closed trades in data/trade_ledger.csv for the same symbol+side
        within 30 minutes of trade open. Returns None if fewer than 13 samples."""
        ledger_side = "SHORT" if side == "SELL" else "LONG"
        entries = self.signal_log.get(symbol, [])
        flagged_ts = []
        for e in entries:
            sig = e.get("signal", "")
            if not sig or not e.get("htf_contra_fired"):
                continue
            if (side == "BUY") != sig.endswith("BUY"):
                continue
            try:
                ts = datetime.fromisoformat(e["timestamp"])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                flagged_ts.append(ts.timestamp())
            except (KeyError, ValueError, TypeError):
                continue
        if not flagged_ts:
            return None
        pnls = [row["_net_pnl"] for row in _closed_trades(symbol=symbol, side=ledger_side)
                if any(abs(row["_ts"] - sts) <= 1800 for sts in flagged_ts)]
        n = len(pnls)
        if n < 13:
            return None
        wins = sum(1 for p in pnls if p > 0)
        return {"n": n, "avg_net": sum(pnls) / n, "wr": wins / n}

    def _side_baseline_stats(self, side: str) -> Optional[Dict[str, float]]:
        """Realized baseline avg net pnl for a side (LONG/SHORT), n>=13."""
        ledger_side = "SHORT" if side == "SELL" else "LONG"
        trades = _closed_trades(side=ledger_side)
        n = len(trades)
        if n < 13:
            return None
        return {"n": n, "avg_net": sum(t["_net_pnl"] for t in trades) / n}

    def _get_htf_contra_penalty(self, symbol: str, side: str, strong: bool) -> int:
        """Live per-(symbol,side) HTF-contra-trend penalty. Ledger audit: SHORT
        avg net +$9.10/tr (n=166, WR57%) vs LONG avg net -$8.17/tr (n=99,
        WR47%) -- this symmetric penalty fired 9,248x and hard-killed 5,834
        signals (3,283 SELLs), penalizing the winning side identically to the
        losing side. Scales with the flagged slice's realized shortfall vs the
        side's own realized baseline; zero if the flagged slice is itself
        net-profitable. Falls back to the original static -12/-8 (n<13)."""
        fallback = 12 if strong else 8
        try:
            slice_stats = self._htf_contra_join_stats(symbol, side)
            if slice_stats is not None:
                if slice_stats["avg_net"] >= 0:
                    return 0
                baseline = self._side_baseline_stats(side)
                if baseline is not None and baseline["avg_net"] > 0:
                    shortfall = baseline["avg_net"] - slice_stats["avg_net"]
                    return int(max(0, min(15, round(shortfall * 0.8))))
                return int(max(0, min(15, fallback)))
        except Exception as e:
            logger.warning(f"_get_htf_contra_penalty fallback to static {fallback}: {e}")
        return fallback

    def _get_strong_confidence_threshold(self) -> float:
        """Live STRONG-tier confidence boundary (LIVING VALUES 2026-07-15).

        Ledger audit (data/trade_ledger.csv, non-TEST, conf>0, n=99): the
        static "normal" tier (conf 65-84) realized n=54 WR39% avg net
        -$1.07/tr, while the static "MARGINAL" tier (conf 30-64) realized
        n=44 WR57% avg net -$0.35/tr -- the static boundaries INVERTED
        realized quality (both n>=13). Promotes a bucket to STRONG only once
        it clears n>=13 with a positive realized edge that beats the bucket
        below it; falls back to the static 85 while every bucket above 65
        stays under n=13 (true today: conf>=85 n=1, conf>=80 n=8).
        """
        try:
            trades = _closed_trades()
            below = [t for t in trades if 30 <= t["_conf"] < 65]
            base_avg = (sum(t["_net_pnl"] for t in below) / len(below)) if len(below) >= 13 else None
            for lo, hi in ((85, 200), (80, 85), (65, 80)):
                bucket = [t for t in trades if lo <= t["_conf"] < hi]
                if len(bucket) < 13:
                    continue
                avg = sum(t["_net_pnl"] for t in bucket) / len(bucket)
                wr = sum(1 for t in bucket if t["_net_pnl"] > 0) / len(bucket)
                if avg > 0 and wr > 0.5 and (base_avg is None or avg > base_avg):
                    return float(lo)
        except Exception as e:
            logger.warning(f"_get_strong_confidence_threshold fallback to static 85: {e}")
        return 85.0  # cold-start fallback -- no bucket above 65 clears n>=13 yet

    def evaluate(self, symbol: str, data: Dict[str, pd.DataFrame]) -> Optional[Signal]:
        df = data.get("1h")
        if df is None or df.empty or len(df) < 50:
            return None

        close = df["close"]
        entry = float(close.iloc[-1])
        if pd.isna(entry):
            return None

        # Evaluate past signals
        self.evaluate_past_signals(symbol, entry)

        # Compute all indicators
        di = _adx_di(df)
        adx = float(di["adx"].iloc[-1])
        plus_di = float(di["plus_di"].iloc[-1])
        minus_di = float(di["minus_di"].iloc[-1])

        macd_line, signal_line, histogram = _macd(close)
        macd_hist = float(histogram.iloc[-1])
        macd_hist_prev = float(histogram.iloc[-2]) if len(histogram) > 1 else 0
        macd_rising = macd_hist > macd_hist_prev

        rsi_vals = _rsi(close)
        rsi_val = float(rsi_vals.iloc[-1])

        atr_val = float(_atr(df).iloc[-1])

        squeeze = self._detect_squeeze(df)

        # --- Scoring system: 4 factors, each 0-25 points ---

        # Factor 1: ADX + DI direction (0-25)
        # ADX < 22 means no/weak trend — skip entirely.
        # ADX 20-22 is the "maybe trending" zone with terrible win rates.
        # Raising from 20→22 eliminates ~30% of weak signals at source.
        adx_score = 0
        di_bullish = plus_di > minus_di
        # Use centralized ADX threshold from config
        try:
            from trading_config import TradingConfig as _TC
            _adx_thresh = _TC().adx_min_trending
        except Exception:
            _adx_thresh = 22.0
        # 2026-06-08: don't drop signal on low ADX. Penalize via adx_score,
        # let downstream + LLM decide. Killing at strategy layer means the
        # LLM never sees the setup even if confluence is exceptional.
        if adx < _adx_thresh:
            adx_score = max(0, int((adx / _adx_thresh) * 8))  # 0-8 for sub-threshold
        elif adx > 35:
            adx_score = 25  # Strong trend
        elif adx > 25:
            adx_score = 20  # Moderate trend
        else:
            adx_score = 12  # Weak trend (ADX 20-25)

        # Factor 2: MACD histogram (0-25)
        macd_score = 0
        if di_bullish:
            if macd_hist > 0 and macd_rising:
                macd_score = 25  # Positive and accelerating
            elif macd_hist > 0:
                macd_score = 15  # Positive but decelerating
            elif macd_rising:
                macd_score = 8   # Negative but improving
        else:
            if macd_hist < 0 and not macd_rising:
                macd_score = 25  # Negative and accelerating down
            elif macd_hist < 0:
                macd_score = 15  # Negative but decelerating
            elif not macd_rising:
                macd_score = 8   # Positive but weakening

        # Factor 3: Squeeze / volatility (0-25)
        # During a squeeze, price is compressed — direction is 50/50 until breakout.
        # Don't trade DURING squeeze; only reward post-breakout (price outside BB).
        squeeze_score = 0
        if squeeze:
            # Check if price has broken out of the squeeze
            bb_upper, _, bb_lower = _bollinger_bands(close)
            price = float(close.iloc[-1])
            if di_bullish and price > float(bb_upper.iloc[-1]):
                squeeze_score = 22  # Bullish breakout from squeeze — strong signal
            elif not di_bullish and price < float(bb_lower.iloc[-1]):
                squeeze_score = 22  # Bearish breakout from squeeze — strong signal
            else:
                squeeze_score = 0  # Still inside squeeze — skip, direction unclear
        else:
            # No squeeze — reward if momentum aligns
            if (di_bullish and macd_hist > 0) or (not di_bullish and macd_hist < 0):
                squeeze_score = 10  # Momentum aligned without squeeze

        # Factor 4: RSI confirmation (0-25)
        # Crypto-calibrated: 25/75 for extremes (not 30/70 — crypto RSI runs hotter)
        rsi_score = 0
        if di_bullish:
            if rsi_val < 25:
                rsi_score = 25  # Oversold + bullish DI = strong reversal setup
            elif rsi_val < 50:
                rsi_score = 15  # Below midline, room to run
            elif rsi_val < 75:
                rsi_score = 10  # In bullish territory but not overbought
            # rsi > 75: overbought, no RSI score
        else:
            if rsi_val > 75:
                rsi_score = 25  # Overbought + bearish DI = strong reversal setup
            elif rsi_val > 50:
                rsi_score = 15  # Above midline, room to fall
            elif rsi_val > 25:
                rsi_score = 10  # In bearish territory but not oversold
            # rsi < 25: oversold, no RSI score

        # RSI divergence bonus
        side = "BUY" if di_bullish else "SELL"
        if self._detect_rsi_divergence(df, rsi_vals, side):
            rsi_score = min(25, rsi_score + 10)

        # Total confidence
        confidence = float(adx_score + macd_score + squeeze_score + rsi_score)

        # Momentum exhaustion penalty: when ADX is very high AND RSI extreme,
        # the move is often extended/overheated. High confidence paradoxically
        # means "everything is maxed = move may be exhausting".
        # LIVING VALUES fix (2026-07-15): the old flat -15 was justified by a
        # "90d backtest: 22% WR" that the ledger audit proved FALSE. Log-joined
        # 41,507 exhaustion firings to closed paper_trades (same symbol+side,
        # ±30min of open): flagged n=48 avg net +$2.62/tr WR40% vs non-flagged
        # n=217 +$2.65/tr WR56% -- both net-profitable. SELL slice n=31 is
        # +$4.59/tr NET POSITIVE, yet this penalty fired on 57% of SELL
        # signals (the bot's best realized edge). Penalty is now computed live
        # per side (see _get_exhaustion_penalty) with the static 15 kept only
        # as a cold-start / no-data fallback -- never exceeded.
        exhaustion_fired = False
        exhaustion_penalty = 0
        if adx > 35 and ((di_bullish and rsi_val > 70) or (not di_bullish and rsi_val < 30)):
            exhaustion_fired = True
            exhaustion_penalty = self._get_exhaustion_penalty(side)
            confidence -= exhaustion_penalty
            logger.info(
                f"[{symbol}] Momentum exhaustion: ADX={adx:.0f} RSI={rsi_val:.0f} "
                f"-> penalty -{exhaustion_penalty}, conf now {confidence:.0f}"
            )

        # 6h regime filter: reject signals that contradict higher-timeframe regime
        htf_contra_fired = False
        htf_penalty = 0
        macd_h_6h = None
        mfi_6h_val = None
        df_6h = data.get("6h")
        if df_6h is None or len(df_6h) < 10:
            logger.warning(f"[{symbol}] confidence_scorer: 6h data unavailable, HTF filter skipped")
            confidence *= 0.85  # Penalize: no HTF confirmation
        if df_6h is not None and len(df_6h) >= 10:
            _, _, hist_6h = _macd(df_6h["close"])
            macd_h_6h = float(hist_6h.iloc[-1])
            mfi_6h_val = 50.0
            if "volume" in df_6h.columns:
                mfi_6h = _mfi_like(df_6h, period=min(60, len(df_6h)))
                mfi_6h_val = float(mfi_6h.iloc[-1])

            # HTF contra-trend: penalize (don't hard-kill) when 6h contradicts 1h.
            # LIVING VALUES fix (2026-07-15): this symmetric penalty fired 9,248x
            # in logs and silently hard-killed 5,834 signals (3,283 SELLs) via
            # the `confidence < 50: return None` below -- removed. Ledger:
            # SHORT avg net +$9.10/tr (n=166, WR57%) vs LONG avg net -$8.17/tr
            # (n=99, WR47%); ETH/BTC/SOL SELL are the only proven edges, yet
            # this penalized SELL identically to LONG and hard-killed 180 SELL
            # signals Jul 11-12 alone -- the exact silent-gate pattern behind
            # the zero-trade week. The LLM-first dispatcher + 6-stage risk
            # gates adjudicate now, not a pre-LLM hardcoded kill. Magnitude is
            # computed live per (symbol,side) -- see _get_htf_contra_penalty --
            # with the original static -12/-8 kept only as an n<13 fallback.
            if di_bullish and (macd_h_6h < 0 and mfi_6h_val < 45):
                htf_contra_fired = True
                htf_penalty = self._get_htf_contra_penalty(symbol, "BUY", strong=mfi_6h_val < 30)
                confidence -= htf_penalty
                logger.info(f"[{symbol}] confidence_scorer BUY penalized -{htf_penalty}: 6h bearish (MACD_h={macd_h_6h:.2f}, MFI={mfi_6h_val:.0f}), conf now {confidence:.0f}")
            if not di_bullish and (macd_h_6h > 0 and mfi_6h_val > 55):
                htf_contra_fired = True
                htf_penalty = self._get_htf_contra_penalty(symbol, "SELL", strong=mfi_6h_val > 70)
                confidence -= htf_penalty
                logger.info(f"[{symbol}] confidence_scorer SELL penalized -{htf_penalty}: 6h bullish (MACD_h={macd_h_6h:.2f}, MFI={mfi_6h_val:.0f}), conf now {confidence:.0f}")

            # 6h confirmation bonus
            htf_aligned = (di_bullish and macd_h_6h > 0) or (not di_bullish and macd_h_6h < 0)
            if htf_aligned:
                confidence += 5

        # Historical accuracy adjustment FIRST so it shapes the tier decision.
        # Forensic 2026-04-14: stated confidence 55-75% was firing with actual
        # WR 30-50%, a 15-25 point calibration gap. Reordering means a bad
        # historical track record reduces the signal to below the raised
        # threshold and the signal never fires.
        # Pre-adjustment action label just to look up historical confidence;
        # STRONG vs non-STRONG is set after the adjustment.
        _pre_action = "BUY" if di_bullish else "SELL"
        hist_conf = self._get_historical_confidence(symbol, _pre_action)
        if hist_conf is not None:
            adjustment = (hist_conf - 0.5) * 20  # -10 to +10
            confidence += adjustment
            logger.info(
                f"[{symbol}] {_pre_action} hist WR={hist_conf:.0%}, "
                f"adj={adjustment:+.1f}, pre-threshold={confidence:.1f}"
            )
        confidence = max(0, min(100, confidence))

        # 2026-06-08: relaxed hard floor from 65 to 30. Low-confidence signals
        # still emit (with diagnostic) so the LLM can review them with full
        # context. Below 30 still dropped to limit noise (unverified floor,
        # no realized trade exists below conf 35 -- ledger doesn't contradict it).
        #
        # LIVING VALUES fix (2026-07-15): dropped the dead static 65 "normal"
        # tier boundary. It was functionally dead (65-84 and 30-64 emitted the
        # identical BUY/SELL action string; the only consumer of the label
        # split, evaluate_past_signals' STRONG-vs-not grading, is diagnostic
        # only per the fix above) while falsely asserting 65-84 as higher
        # quality: ledger showed the OPPOSITE (WR39%/-$1.07 vs WR57%/-$0.35,
        # both n>=13). Deleting it is a pure label-truthfulness fix with zero
        # output-behavior change. STRONG boundary is now live-computed.
        _strong_thresh = self._get_strong_confidence_threshold()
        if confidence >= _strong_thresh:
            action = "STRONG_BUY" if di_bullish else "STRONG_SELL"
        elif confidence >= 30:
            # Below historic floor — emit as MARGINAL for LLM review.
            action = "BUY" if di_bullish else "SELL"
        else:
            return None  # True noise threshold

        # Log signal (persist condition flags for future live joins -- see
        # _exhaustion_join_stats / _htf_contra_join_stats)
        self._log_signal(
            symbol, action, entry,
            exhaustion_fired=exhaustion_fired,
            exhaustion_penalty=exhaustion_penalty,
            htf_contra_fired=htf_contra_fired,
            htf_penalty=htf_penalty,
        )

        # Stop/TP placement: regime-conditional ATR multipliers
        try:
            from trading_config import TradingConfig as _TC, get_regime_sl_tp
            _cfg = _TC()
            _regime = self._current_regime if hasattr(self, '_current_regime') else "unknown"
            K, _tp1_mult, _tp2_mult = get_regime_sl_tp(
                _regime, _cfg.sl_atr_multiplier, 2.0, 4.0
            )
        except Exception:
            K, _tp1_mult, _tp2_mult = 1.5, 2.0, 4.0
        sl = entry - K * atr_val if side == "BUY" else entry + K * atr_val
        stop_width = abs(entry - sl)
        tp1 = entry + _tp1_mult * stop_width if side == "BUY" else entry - _tp1_mult * stop_width
        tp2 = entry + _tp2_mult * stop_width if side == "BUY" else entry - _tp2_mult * stop_width

        rr = abs(entry - tp1) / stop_width if stop_width > 0 else 0
        hist_str = f"hist_WR={hist_conf:.0%}" if hist_conf is not None else "hist_WR=n/a"
        ctx = (
            f"ADX={adx:.0f}({'+DI' if di_bullish else '-DI'}), "
            f"MACD={'rising' if macd_rising else 'falling'}, "
            f"RSI={rsi_val:.0f}, "
            f"{'SQUEEZE ' if squeeze else ''}"
            f"{hist_str}, R:R={rr:.1f}"
        )

        return Signal(
            strategy=self.name,
            symbol=symbol,
            side=side,
            confidence=confidence,
            entry=entry,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            atr=atr_val,
            signal_context=ctx,
            metadata={
                "action": action,
                "adx": adx,
                "plus_di": plus_di,
                "minus_di": minus_di,
                "macd_hist": macd_hist,
                "macd_rising": macd_rising,
                "rsi": rsi_val,
                "squeeze": squeeze,
                "exhaustion_fired": exhaustion_fired,
                "exhaustion_penalty": exhaustion_penalty,
                "htf_contra_fired": htf_contra_fired,
                "htf_penalty": htf_penalty,
                "mfi_6h_val": mfi_6h_val,
                "macd_h_6h": macd_h_6h,
                "historical_confidence": hist_conf,
                "factor_scores": {
                    "adx": adx_score,
                    "macd": macd_score,
                    "squeeze": squeeze_score,
                    "rsi": rsi_score,
                },
                # Regime classification for system-wide regime detector
                "regime": (
                    "trend" if adx > 25 and not squeeze else
                    "range" if adx < 20 else
                    "high_volatility" if squeeze else
                    "unknown"
                ),
            },
        )

    def get_status(self, symbol: str, data: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        df = data.get("1h")
        if df is None or df.empty or len(df) < 50:
            return {"symbol": symbol, "strategy": self.name, "status": "insufficient_data"}

        close = df["close"]
        di = _adx_di(df)
        adx = float(di["adx"].iloc[-1])
        plus_di = float(di["plus_di"].iloc[-1])
        minus_di = float(di["minus_di"].iloc[-1])

        _, _, histogram = _macd(close)
        rsi_vals = _rsi(close)
        squeeze = self._detect_squeeze(df)

        # Historical confidence scores
        conf_scores = {}
        for act in ["STRONG_BUY", "BUY", "SELL", "STRONG_SELL"]:
            hc = self._get_historical_confidence(symbol, act)
            if hc is not None:
                conf_scores[act] = hc

        return {
            "symbol": symbol,
            "strategy": self.name,
            "price": float(close.iloc[-1]),
            "adx": adx,
            "plus_di": plus_di,
            "minus_di": minus_di,
            "macd_hist": float(histogram.iloc[-1]),
            "rsi": float(rsi_vals.iloc[-1]),
            "squeeze": squeeze,
            "di_direction": "bullish" if plus_di > minus_di else "bearish",
            "historical_confidence": conf_scores,
            "total_signals_logged": sum(len(v) for v in self.signal_log.values()),
        }

    def get_performance_report(self) -> Dict[str, Any]:
        """Generate a performance report from signal history."""
        report = {}
        for symbol, entries in self.signal_log.items():
            evaluated = [e for e in entries if e.get("evaluated") and "success" in e]
            if not evaluated:
                continue

            by_type = {}
            for sig_type in ["STRONG_BUY", "BUY", "SELL", "STRONG_SELL"]:
                sigs = [e for e in evaluated if e["signal"] == sig_type]
                if sigs:
                    wins = sum(1 for s in sigs if s["success"])
                    by_type[sig_type] = {
                        "total": len(sigs),
                        "wins": wins,
                        "win_rate": wins / len(sigs),
                    }

            total = len(evaluated)
            total_wins = sum(1 for e in evaluated if e["success"])
            report[symbol] = {
                "total_signals": total,
                "overall_win_rate": total_wins / total if total else 0,
                "by_type": by_type,
            }
        return report
