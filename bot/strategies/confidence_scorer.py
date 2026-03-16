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

import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from pathlib import Path

import pandas as pd
import numpy as np

from .base import BaseStrategy, Signal

logger = logging.getLogger("bot.strategy.momentum_scorer")


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

    def _log_signal(self, symbol: str, action: str, price: float):
        """Record a signal for later evaluation."""
        if symbol not in self.signal_log:
            self.signal_log[symbol] = []
        self.signal_log[symbol].append({
            "signal": action,
            "price": price,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "evaluated": False,
        })
        self.signal_log[symbol] = self.signal_log[symbol][-200:]
        self._save_signal_log()

    def _get_historical_confidence(self, symbol: str, action: str) -> Optional[float]:
        """
        Calculate win rate for this (symbol, action) pair from historical data.
        Returns None if insufficient data or in backtest mode.

        In backtest mode, historical WR is disabled to prevent the cold-start death
        spiral: early losses poison WR → confidence drops → fewer trades → worse WR.
        The 7-day backtest showed WR decaying from 35% → 16% within a single run.
        """
        if self.backtest_mode:
            return None  # Prevent cold-start death spiral in backtests
        entries = self.signal_log.get(symbol, [])
        evaluated = [e for e in entries if e.get("evaluated") and e["signal"] == action and "success" in e]
        if len(evaluated) < 5:
            return None
        wins = sum(1 for e in evaluated if e["success"])
        wr = wins / len(evaluated)
        # With fewer than 20 samples, WR estimates are noisy — dampen toward 0.5.
        # With 20+ samples, return raw WR for single-pass calibration (no double-dampening).
        if len(evaluated) < 20:
            wr = 0.5 + (wr - 0.5) * 0.5
        return wr

    def evaluate_past_signals(self, symbol: str, current_price: float):
        """Evaluate unresolved signals based on subsequent price movement."""
        entries = self.signal_log.get(symbol, [])
        changed = False
        for e in entries:
            if e["evaluated"]:
                continue
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
        if adx < _adx_thresh:
            return None  # No/weak trend = no trade
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

        # 6h regime filter: reject signals that contradict higher-timeframe regime
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
            # Hard reject was killing ALL buys in sustained downtrends — zero trades.
            # Now symmetric: both BUY and SELL get sized down, not eliminated.
            # Strong HTF divergence (both MACD + MFI) = moderate penalty.
            # Softened from -15/-20: harsh penalties killed signals where 1h had strong edge.
            if di_bullish and (macd_h_6h < 0 and mfi_6h_val < 45):
                htf_penalty = 12 if mfi_6h_val < 30 else 8
                confidence -= htf_penalty
                logger.info(f"[{symbol}] confidence_scorer BUY penalized -{htf_penalty}: 6h bearish (MACD_h={macd_h_6h:.2f}, MFI={mfi_6h_val:.0f}), conf now {confidence:.0f}")
                if confidence < 50:
                    return None
            if not di_bullish and (macd_h_6h > 0 and mfi_6h_val > 55):
                htf_penalty = 12 if mfi_6h_val > 70 else 8
                confidence -= htf_penalty
                logger.info(f"[{symbol}] confidence_scorer SELL penalized -{htf_penalty}: 6h bullish (MACD_h={macd_h_6h:.2f}, MFI={mfi_6h_val:.0f}), conf now {confidence:.0f}")
                if confidence < 50:
                    return None

            # 6h confirmation bonus
            htf_aligned = (di_bullish and macd_h_6h > 0) or (not di_bullish and macd_h_6h < 0)
            if htf_aligned:
                confidence += 5

        # Classify signal strength
        if confidence >= 75:
            action = "STRONG_BUY" if di_bullish else "STRONG_SELL"
        elif confidence >= 55:
            action = "BUY" if di_bullish else "SELL"
        else:
            return None  # Not enough momentum factors agree

        # Historical accuracy adjustment (key differentiator)
        hist_conf = self._get_historical_confidence(symbol, action)
        if hist_conf is not None:
            adjustment = (hist_conf - 0.5) * 30  # -15 to +15
            confidence += adjustment
            logger.info(
                f"[{symbol}] {action} hist WR={hist_conf:.0%}, "
                f"adj={adjustment:+.1f}, final={confidence:.1f}"
            )

        # Penalize terrible historical WR
        if hist_conf is not None and hist_conf < 0.15:
            confidence -= 15
            logger.info(f"[{symbol}] {action} WR {hist_conf:.0%} too low, -15 penalty")

        confidence = max(0, min(100, confidence))

        # Log signal
        self._log_signal(symbol, action, entry)

        if confidence < 55:
            return None

        # Stop/TP placement: regime-conditional ATR multipliers (per-symbol atr_mult_sl if set)
        try:
            from trading_config import TradingConfig as _TC, get_regime_sl_tp, get_symbol_param
            _cfg = _TC()
            _regime = self._current_regime if hasattr(self, '_current_regime') else "unknown"
            _base_sl = get_symbol_param(symbol, "atr_mult_sl", _cfg) or _cfg.sl_atr_multiplier
            K, _tp1_mult, _tp2_mult = get_regime_sl_tp(
                _regime, _base_sl, 2.0, 4.0
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
