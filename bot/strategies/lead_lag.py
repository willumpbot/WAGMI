"""
Strategy 9: Lead-Lag / Relative Strength

Core logic:
- BTC leads alt movements by 15-60 minutes in crypto markets
- When BTC makes a significant move, alts that haven't moved yet will follow
- "Relative strength" = alt that holds up during BTC dip → will outperform on recovery
- "Relative weakness" = alt that drops harder than BTC → more downside ahead

Signal generation:
1. BTC breakout detection (significant move in last 1-4 candles)
2. Check if alt has NOT yet followed (lag detection)
3. If BTC up + alt flat/slightly down → BUY alt (expect catch-up)
4. If BTC down + alt flat/slightly up → SELL alt (expect catch-down)
5. Relative strength scoring: alt_return / btc_return over rolling window

This strategy works because crypto markets are informationally inefficient —
BTC price discovery happens first, then propagates to alts.

Data requirements:
- 1h OHLCV for target symbol AND BTC
- BTC data passed via data dict as "_btc_1h" or extracted from cross-symbol data
"""

import logging
from typing import Optional, Dict, Any, List

import pandas as pd
import numpy as np

from .base import BaseStrategy, Signal

logger = logging.getLogger("bot.strategy.lead_lag")


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev).abs(),
        (df["low"] - prev).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=1).mean()


def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=max(2, span), adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period, min_periods=1).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period, min_periods=1).mean()
    rs = gain / loss.replace(0, 1e-12)
    return 100.0 - (100.0 / (1.0 + rs))


class LeadLagStrategy(BaseStrategy):
    """
    Exploits the BTC → alt lead-lag relationship in crypto markets.

    BTC moves first, alts follow. This strategy detects when BTC has made
    a significant move and the target alt hasn't caught up yet, then
    positions for the expected catch-up move.

    Also uses relative strength analysis: alts that hold up during BTC drops
    are likely to outperform when BTC recovers.
    """

    # BTC move thresholds
    BTC_SIGNIFICANT_MOVE_PCT = 0.015  # 1.5% BTC move = significant
    BTC_STRONG_MOVE_PCT = 0.03       # 3% BTC move = very strong

    # Lag detection: alt hasn't followed if its move is < this fraction of BTC's
    LAG_RATIO_THRESHOLD = 0.3  # Alt moved < 30% of BTC's move = lagging

    # Relative strength window
    RS_LOOKBACK_BARS = 12  # 12h rolling window for relative strength

    # Minimum lag bars: BTC moved, wait at least this many bars for alt catch-up
    MIN_LAG_BARS = 1  # At least 1 bar of observed lag before entering

    def __init__(self, symbols: Dict[str, Any]):
        super().__init__("lead_lag", symbols)

    def get_required_timeframes(self) -> List[str]:
        return ["1h"]

    def _compute_btc_move(self, btc_df: pd.DataFrame, lookback: int = 4) -> Dict[str, float]:
        """Compute BTC's recent move characteristics."""
        close = btc_df["close"].astype(float)
        if len(close) < lookback + 1:
            return {"move_pct": 0.0, "move_bars": 0, "direction": 0}

        # Find the max move over the lookback period
        current = float(close.iloc[-1])
        max_move_pct = 0.0
        best_bars_ago = 0

        for i in range(1, lookback + 1):
            prev = float(close.iloc[-(i + 1)])
            if prev > 0:
                move = (current - prev) / prev
                if abs(move) > abs(max_move_pct):
                    max_move_pct = move
                    best_bars_ago = i

        # Volume surge check
        vol = btc_df["volume"].astype(float)
        vol_avg = float(vol.rolling(20, min_periods=1).mean().iloc[-1])
        vol_recent = float(vol.iloc[-lookback:].mean())
        vol_ratio = vol_recent / max(vol_avg, 1e-12)

        return {
            "move_pct": max_move_pct,
            "move_bars": best_bars_ago,
            "direction": 1 if max_move_pct > 0 else -1 if max_move_pct < 0 else 0,
            "vol_ratio": vol_ratio,
        }

    def _compute_relative_strength(self, alt_df: pd.DataFrame, btc_df: pd.DataFrame,
                                    lookback: int = 12) -> float:
        """
        Compute relative strength of alt vs BTC.
        RS > 1.0 = alt outperforming BTC, RS < 1.0 = alt underperforming.
        """
        alt_close = alt_df["close"].astype(float)
        btc_close = btc_df["close"].astype(float)

        # Align lengths
        min_len = min(len(alt_close), len(btc_close))
        if min_len < lookback + 1:
            return 1.0

        alt_return = float(alt_close.iloc[-1]) / float(alt_close.iloc[-lookback - 1])
        btc_return = float(btc_close.iloc[-1]) / float(btc_close.iloc[-lookback - 1])

        if btc_return <= 0:
            return 1.0

        return alt_return / btc_return

    def evaluate(self, symbol: str, data: Dict[str, pd.DataFrame]) -> Optional[Signal]:
        # Skip BTC — can't lead-lag against itself
        if symbol.upper() == "BTC":
            return None

        df_1h = data.get("1h")
        if df_1h is None or len(df_1h) < 20:
            return None

        # Get BTC data
        btc_df = data.get("_btc_1h")
        if btc_df is None:
            btc_data = data.get("_cross", {})
            btc_df = btc_data.get("BTC", {}).get("1h")
        if btc_df is None or len(btc_df) < 20:
            return None

        close = df_1h["close"].astype(float)
        price = float(close.iloc[-1])
        atr = float(_atr(df_1h).iloc[-1])

        if atr <= 0 or price <= 0:
            return None

        # Step 1: Detect BTC significant move
        btc_move = self._compute_btc_move(btc_df, lookback=4)

        if abs(btc_move["move_pct"]) < self.BTC_SIGNIFICANT_MOVE_PCT:
            return None  # BTC didn't move enough to trigger lead-lag

        # Step 2: Check if alt has lagged (hasn't followed BTC)
        alt_move_pct = 0.0
        lookback = btc_move["move_bars"]
        if lookback > 0 and len(close) > lookback:
            prev_price = float(close.iloc[-(lookback + 1)])
            if prev_price > 0:
                alt_move_pct = (price - prev_price) / prev_price

        # Lag ratio: how much of BTC's move has the alt followed?
        btc_abs = abs(btc_move["move_pct"])
        if btc_abs > 0:
            # Same direction ratio: positive if alt moved with BTC, negative if against
            if btc_move["direction"] > 0:
                lag_ratio = alt_move_pct / btc_abs
            else:
                lag_ratio = -alt_move_pct / btc_abs
        else:
            return None

        # If alt already caught up (lag_ratio > 0.7), no signal
        if lag_ratio > 0.7:
            return None

        # Step 3: Relative strength analysis
        rs = self._compute_relative_strength(df_1h, btc_df, self.RS_LOOKBACK_BARS)

        # Step 4: Determine signal direction
        side = None
        signal_type = None
        confidence = 55.0

        if btc_move["direction"] > 0:
            # BTC went up, alt hasn't followed → BUY alt (catch-up expected)
            side = "BUY"
            signal_type = "catch_up_long"

            # If alt showed relative strength before BTC's move → even more bullish
            if rs > 1.05:
                confidence += 8.0  # Alt was already strong
            elif rs < 0.95:
                confidence -= 5.0  # Alt was weak, might not catch up
        else:
            # BTC went down, alt hasn't followed → SELL alt (catch-down expected)
            side = "SELL"
            signal_type = "catch_down_short"

            # If alt showed relative weakness → more downside expected
            if rs < 0.95:
                confidence += 8.0  # Alt already weak
            elif rs > 1.05:
                confidence -= 5.0  # Alt is strong, might resist

        # Confidence adjustments
        # BTC move magnitude
        if abs(btc_move["move_pct"]) >= self.BTC_STRONG_MOVE_PCT:
            confidence += 10.0  # Strong BTC move = higher conviction
        else:
            confidence += 5.0

        # How much the alt is lagging (bigger gap = bigger catch-up potential)
        if lag_ratio < 0.0:
            confidence += 8.0  # Alt moved AGAINST BTC → strong catch-up expected
        elif lag_ratio < self.LAG_RATIO_THRESHOLD:
            confidence += 5.0

        # BTC volume confirmation
        if btc_move["vol_ratio"] > 1.5:
            confidence += 5.0  # BTC move on high volume = more credible

        # Alt RSI: prefer entries when not overbought/oversold
        rsi = float(_rsi(close).iloc[-1])
        if side == "BUY" and rsi < 40:
            confidence += 5.0  # Oversold alt catching up to bullish BTC
        elif side == "SELL" and rsi > 60:
            confidence += 5.0

        confidence = max(50.0, min(95.0, confidence))

        # TP/SL: target the expected catch-up magnitude
        expected_catch_up = btc_abs * (1.0 - max(0, lag_ratio))
        catch_up_dollar = price * expected_catch_up

        # Use ATR for stop, but catch-up magnitude for targets
        sl_dist = atr * 1.5
        tp1_dist = max(atr * 1.5, catch_up_dollar * 0.7)  # 70% of expected catch-up
        tp2_dist = max(atr * 2.5, catch_up_dollar * 1.2)   # 120% (overshoot)

        if side == "BUY":
            sl = price - sl_dist
            tp1 = price + tp1_dist
            tp2 = price + tp2_dist
        else:
            sl = price + sl_dist
            tp1 = price - tp1_dist
            tp2 = price - tp2_dist

        context_parts = [
            f"Lead-Lag: BTC {btc_move['move_pct']*100:+.2f}% in {btc_move['move_bars']}h",
            f"{symbol} only {alt_move_pct*100:+.2f}% (lag ratio={lag_ratio:.2f})",
            f"Relative strength={rs:.3f}",
            f"Expected catch-up: {expected_catch_up*100:.2f}%",
            f"RSI={rsi:.1f}",
        ]

        sig = Signal(
            strategy="lead_lag",
            symbol=symbol,
            side=side,
            confidence=confidence,
            entry=price,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            atr=atr,
            metadata={
                "btc_move_pct": btc_move["move_pct"],
                "alt_move_pct": alt_move_pct,
                "lag_ratio": lag_ratio,
                "relative_strength": rs,
                "signal_type": signal_type,
                "btc_vol_ratio": btc_move["vol_ratio"],
                "rsi": rsi,
                "regime": (
                    "trend" if abs(btc_move["move_pct"]) > 2 else
                    "high_volatility" if btc_move["vol_ratio"] > 2.0 else
                    "range"
                ),
            },
            signal_context=" | ".join(context_parts),
        )

        if not sig.is_valid:
            return None

        logger.info(f"[{symbol}] Lead-Lag signal: {side} conf={confidence:.0f}% "
                     f"BTC={btc_move['move_pct']*100:+.2f}% alt={alt_move_pct*100:+.2f}% "
                     f"RS={rs:.3f}")
        return sig

    def get_status(self, symbol: str, data: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        btc_df = data.get("_btc_1h")
        if btc_df is None:
            return {"strategy": self.name, "symbol": symbol, "state": "no_btc_data"}

        btc_move = self._compute_btc_move(btc_df, lookback=4)
        rs = 1.0
        df_1h = data.get("1h")
        if df_1h is not None and len(df_1h) >= 15:
            rs = self._compute_relative_strength(df_1h, btc_df, 12)

        return {
            "strategy": self.name,
            "symbol": symbol,
            "btc_move_pct": btc_move["move_pct"],
            "relative_strength": rs,
        }
