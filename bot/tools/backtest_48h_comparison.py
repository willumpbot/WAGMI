#!/usr/bin/env python3
"""
48-Hour Backtest: OLD System vs NEW (Improved) System

Fetches real 1h candles for HYPE, BTC, SOL via the DataFetcher,
then simulates both OLD and NEW system rules on the last 48 hours.

NEW system rules:
  1. Quality scorecard (min 50 to enter, 70+ for full size)
  2. Trend-aware gates (no HYPE BUY below both EMAs unless 85%+ conf)
  3. SOL SELL allowed as solo signal at 60%+
  4. Kelly leverage (3.9x half-Kelly baseline)
  5. Smart exits (12h time stop, BE at +0.5%, trailing at +1.0%)
  6. R:R minimum 1.5

OLD system rules (before fixes):
  1. No scorecard — any signal with confidence >= 55 enters
  2. No trend-aware gate — HYPE BUY fires in full bear alignment
  3. SOL SELL blocked unless 3-agree consensus (never fires solo)
  4. Fixed leverage 5x-25x based on tier (no Kelly)
  5. Fixed TP exits only (no time stop, no BE, no trailing)
  6. R:R minimum 1.0
"""

import os
import sys

# Fix encoding on Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

# Ensure bot/ is on path
BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BOT_DIR not in sys.path:
    sys.path.insert(0, BOT_DIR)

import logging
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("backtest_48h")

# ── Data fetching ──────────────────────────────────────────────────

SYMBOLS = {
    "HYPE": "hyperliquid",
    "BTC": "bitcoin",
    "SOL": "solana",
}

def fetch_data() -> Dict[str, Dict[str, pd.DataFrame]]:
    """Fetch 500 1h candles + 120 6h candles for each symbol."""
    from data.fetcher import DataFetcher
    fetcher = DataFetcher(fresh=True)

    data = {}
    for sym, cg_id in SYMBOLS.items():
        logger.info(f"Fetching {sym}...")
        df_1h = fetcher.fetch_ohlcv(sym, cg_id, "1h")
        df_6h = fetcher.fetch_ohlcv(sym, cg_id, "6h")
        if df_1h is not None and not df_1h.empty:
            logger.info(f"  {sym} 1h: {len(df_1h)} candles, "
                        f"{df_1h['time'].iloc[0]} -> {df_1h['time'].iloc[-1]}")
        else:
            logger.warning(f"  {sym} 1h: NO DATA")
        if df_6h is not None and not df_6h.empty:
            logger.info(f"  {sym} 6h: {len(df_6h)} candles")
        data[sym] = {"1h": df_1h, "6h": df_6h}

    return data


# ── Indicator helpers ──────────────────────────────────────────────

def add_emas(df: pd.DataFrame) -> pd.DataFrame:
    """Add EMA20, EMA50, EMA200, ATR14 to DataFrame."""
    if df is None or df.empty:
        return df
    df = df.copy()
    n = len(df)
    df["EMA20"] = df["close"].ewm(span=20, min_periods=20, adjust=False).mean()
    df["EMA50"] = df["close"].ewm(span=50, min_periods=50, adjust=False).mean()
    df["EMA200"] = df["close"].ewm(span=200, min_periods=min(200, n), adjust=False).mean()
    prev = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev).abs(),
        (df["low"] - prev).abs(),
    ], axis=1).max(axis=1)
    df["ATR14"] = tr.rolling(window=min(14, max(1, n)), min_periods=1).mean()

    # RSI
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0.0).rolling(14, min_periods=14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14, min_periods=14).mean()
    rs = gain / loss.replace(0, 1e-9)
    df["RSI14"] = 100 - (100 / (1 + rs))

    # ADX
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    atr_smooth = tr.rolling(14, min_periods=1).mean()
    plus_di = (plus_dm.rolling(14, min_periods=1).mean() / atr_smooth.replace(0, 1e-9)) * 100
    minus_di = (minus_dm.rolling(14, min_periods=1).mean() / atr_smooth.replace(0, 1e-9)) * 100
    dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-9)) * 100
    df["ADX14"] = dx.rolling(14, min_periods=1).mean()

    return df


def compute_vwap(df: pd.DataFrame, idx: int) -> Optional[float]:
    """Compute session VWAP from 1h data up to idx."""
    if df is None or df.empty or idx < 0:
        return None
    last_dt = df["time"].iloc[idx]
    if pd.isna(last_dt):
        return None
    session_date = pd.to_datetime(last_dt).date()
    mask = df["time"].dt.date == session_date
    mask_idx = mask & (df.index <= idx)
    if not mask_idx.any():
        return None
    part = df.loc[mask_idx]
    tp = (part["high"] + part["low"] + part["close"]) / 3.0
    vol = part["volume"].clip(lower=1e-12)
    vwap = (tp * vol).cumsum() / vol.cumsum()
    return float(vwap.iloc[-1]) if not vwap.empty else None


# ── Signal generation ──────────────────────────────────────────────

@dataclass
class SimSignal:
    """Simulated signal at a point in time."""
    bar_idx: int
    time: datetime
    symbol: str
    side: str
    entry: float
    sl: float
    tp1: float
    tp2: float
    confidence: float
    atr: float
    ema20: float
    ema50: float
    ema200: float
    rsi: float
    adx: float
    vwap: Optional[float]
    regime_score: int  # -2 to +2
    ema_6h_align: bool
    stop_width: float
    rr: float


def generate_signals_at_bar(sym: str, df_1h: pd.DataFrame, df_6h: pd.DataFrame,
                            idx: int) -> Optional[SimSignal]:
    """Generate a signal for a given bar, mimicking multi_tier_quality strategy."""
    if idx < 50:
        return None

    close = float(df_1h["close"].iloc[idx])
    ema20 = float(df_1h["EMA20"].iloc[idx])
    ema50 = float(df_1h["EMA50"].iloc[idx])
    ema200 = float(df_1h["EMA200"].iloc[idx]) if not pd.isna(df_1h["EMA200"].iloc[idx]) else close
    atr = float(df_1h["ATR14"].iloc[idx])
    rsi = float(df_1h["RSI14"].iloc[idx]) if not pd.isna(df_1h["RSI14"].iloc[idx]) else 50.0
    adx = float(df_1h["ADX14"].iloc[idx]) if not pd.isna(df_1h["ADX14"].iloc[idx]) else 25.0

    # Side from EMA20 vs EMA50
    if ema20 > ema50:
        side = "BUY"
    else:
        side = "SELL"

    # 6h regime
    regime_score = 0
    ema_6h_align = False
    if df_6h is not None and "EMA20" in df_6h.columns and "EMA50" in df_6h.columns:
        # Find latest 6h bar before current 1h time
        bar_time = df_1h["time"].iloc[idx]
        mask_6h = df_6h["time"] <= bar_time
        if mask_6h.any():
            last_6h_idx = df_6h.loc[mask_6h].index[-1]
            e20_6h = float(df_6h["EMA20"].iloc[last_6h_idx])
            e50_6h = float(df_6h["EMA50"].iloc[last_6h_idx])
            # 6h side
            side_6h = "above" if e20_6h > e50_6h else "below"
            slope_6h = "up" if e20_6h > df_6h["EMA50"].iloc[max(0, last_6h_idx-4)] else "down"

            # 1h side/slope for regime
            side_1h = "above" if close > ema50 else "below"
            slope_1h = "up" if ema50 > df_1h["EMA50"].iloc[max(0, idx-4)] else "down"

            # Trend score
            for s, sl in [(side_6h, slope_6h), (side_1h, slope_1h)]:
                if s == "above" and sl == "up":
                    regime_score += 1
                elif s == "below" and sl == "down":
                    regime_score -= 1

            # 6h alignment
            if side == "BUY":
                ema_6h_align = e20_6h > e50_6h
            else:
                ema_6h_align = e20_6h < e50_6h

    # Stop placement (ATR-based, K=1.5)
    K = 1.5
    stop = close - K * atr if side == "BUY" else close + K * atr
    stop_width = abs(close - stop)

    # Clamp stops
    lo = 1.0 * atr
    hi = 3.0 * atr
    if stop_width < lo:
        stop = close - lo if side == "BUY" else close + lo
    elif stop_width > hi:
        stop = close - K * atr if side == "BUY" else close + K * atr
    stop_width = abs(close - stop)

    # TPs
    tp1 = close + 2.0 * stop_width if side == "BUY" else close - 2.0 * stop_width
    tp2 = close + 4.0 * stop_width if side == "BUY" else close - 4.0 * stop_width

    # Confidence
    conf = 0
    if abs(regime_score) >= 2:
        conf += 30
    elif regime_score != 0:
        conf += 15

    ema1h_side = "above" if close > ema50 else "below"
    ema_aligned = (ema1h_side == "below" and side == "SELL") or (ema1h_side == "above" and side == "BUY")
    if ema_aligned:
        conf += 20

    vwap = compute_vwap(df_1h, idx)
    vwap_align = vwap and ((close > vwap and side == "BUY") or (close < vwap and side == "SELL"))
    if vwap_align:
        conf += 10

    if atr and stop_width:
        if 1.2 * atr <= stop_width <= 3.0 * atr:
            conf += 15
        elif 0.8 * atr <= stop_width <= 3.5 * atr:
            conf += 8

    # EMA slope bonus
    if idx >= 5:
        e_slice = df_1h["EMA50"].iloc[idx-4:idx+1]
        rising = float(e_slice.iloc[-1]) > float(e_slice.iloc[0])
        if (rising and side == "BUY") or (not rising and side == "SELL"):
            conf += 3

    # RSI adjustment
    if 35 <= rsi <= 65:
        conf += 5
    elif rsi < 30 or rsi > 70:
        conf -= 5

    conf = max(0, min(100, conf))

    rr = abs(close - tp1) / stop_width if stop_width > 0 else 0

    return SimSignal(
        bar_idx=idx,
        time=df_1h["time"].iloc[idx],
        symbol=sym,
        side=side,
        entry=close,
        sl=stop,
        tp1=tp1,
        tp2=tp2,
        confidence=conf,
        atr=atr,
        ema20=ema20,
        ema50=ema50,
        ema200=ema200,
        rsi=rsi,
        adx=adx,
        vwap=vwap,
        regime_score=regime_score,
        ema_6h_align=ema_6h_align,
        stop_width=stop_width,
        rr=rr,
    )


# ── Filter systems ─────────────────────────────────────────────────

def old_system_filter(sig: SimSignal) -> Tuple[bool, str, float]:
    """OLD system filter: loose, no scorecard, no trend gates.
    Returns (passed, reject_reason, leverage)"""

    # ADX filter (was 22 in old too)
    if sig.adx < 22:
        return False, "adx_low", 0

    # RSI extremes
    if sig.side == "BUY" and sig.rsi > 78:
        return False, "rsi_overbought", 0
    if sig.side == "SELL" and sig.rsi < 22:
        return False, "rsi_oversold", 0

    # Confidence floor (old was 55)
    if sig.confidence < 55:
        return False, "low_confidence", 0

    # R:R minimum (old was 1.0)
    if sig.rr < 1.0:
        return False, "low_rr", 0

    # Neutral regime (old system DID have this eventually)
    if abs(sig.regime_score) == 0:
        return False, "neutral_regime", 0

    # 6h misalignment downgrade (old system: simpler, just skip MANUAL tier)
    tier = "REGULAR"
    if sig.confidence >= 75:
        tier = "PRIORITY"
    elif sig.confidence >= 65:
        tier = "REGULAR"
    else:
        tier = "MANUAL"

    if not sig.ema_6h_align and sig.confidence < 80:
        if tier == "PRIORITY":
            tier = "REGULAR"
        elif tier == "REGULAR":
            tier = "MANUAL"
        elif tier == "MANUAL":
            return False, "6h_misalign_reject", 0

    # OLD: No setup-specific filtering (HYPE_SELL still possible!)
    # OLD: SOL_SELL required 3-agree which solo signals never have -> effectively blocked
    setup_key = f"{sig.symbol}_{sig.side}"
    if setup_key == "SOL_SELL":
        # OLD system: SOL SELL blocked (required min_agree=2 AND confidence >= 78)
        # Solo strategies produce 60-75%, so virtually all SOL SELL blocked
        if sig.confidence < 78:
            return False, "sol_sell_blocked_old", 0

    # OLD leverage: fixed tiers
    if tier == "PRIORITY":
        lev = 15.0
    elif tier == "PREMIUM":
        lev = 10.0
    else:
        lev = 5.0

    return True, "passed", lev


def new_system_filter(sig: SimSignal) -> Tuple[bool, str, float, float]:
    """NEW system filter: scorecard, trend gates, Kelly sizing.
    Returns (passed, reject_reason, leverage, size_mult)"""

    setup_key = f"{sig.symbol}_{sig.side}"

    # ADX filter
    if sig.adx < 22:
        return False, "adx_low", 0, 0

    # Squeeze detection
    # (simplified: just check ATR is not too compressed)

    # RSI extremes
    if sig.side == "BUY" and sig.rsi > 78:
        return False, "rsi_overbought", 0, 0
    if sig.side == "SELL" and sig.rsi < 22:
        return False, "rsi_oversold", 0, 0

    # Confidence floor (55)
    if sig.confidence < 55:
        return False, "low_confidence", 0, 0

    # Neutral regime
    if abs(sig.regime_score) == 0:
        return False, "neutral_regime", 0, 0

    # NEW: HYPE_SELL hard block
    if setup_key == "HYPE_SELL":
        return False, "hype_sell_blocked", 0, 0

    # NEW: Trend-aware gate for HYPE_BUY
    if setup_key == "HYPE_BUY":
        if sig.entry < sig.ema20 and sig.entry < sig.ema50:
            # Below both EMAs = bearish
            if sig.confidence < 80:
                return False, "hype_buy_bearish_low_conf", 0, 0
            if sig.ema20 < sig.ema50 and sig.confidence < 85:
                return False, "hype_buy_bear_cross", 0, 0

    # NEW: SOL SELL allowed as solo at 60%+
    if setup_key == "SOL_SELL":
        if sig.confidence < 60:
            return False, "sol_sell_low_conf", 0, 0
        # Otherwise passes! This is the key improvement.

    # R:R minimum (NEW = 1.5)
    if sig.rr < 1.5:
        return False, "low_rr_new", 0, 0

    # 6h alignment gate
    tier = "REGULAR"
    if sig.confidence >= 75:
        tier = "PRIORITY"
    elif sig.confidence >= 65:
        tier = "REGULAR"
    else:
        tier = "MANUAL"

    if not sig.ema_6h_align and sig.confidence < 80:
        if tier == "PRIORITY":
            tier = "REGULAR"
        elif tier == "REGULAR":
            tier = "MANUAL"
        elif tier == "MANUAL":
            return False, "6h_misalign_reject", 0, 0

    # NEW: Quality scorecard simulation
    # Confidence: 25 pts max
    score = 0
    if sig.confidence >= 85:
        score += 25
    elif sig.confidence >= 80:
        score += 20
    elif sig.confidence >= 75:
        score += 15
    elif sig.confidence >= 70:
        score += 8

    # Consensus (we simulate solo = 1, but in real system strategies vote)
    # For this backtest, use 1 agree (solo strategy)
    num_agree = 1
    if num_agree >= 3:
        score += 25
    elif num_agree >= 2:
        score += 15
    # solo = 0 pts

    # Edge trend
    edge_trends = {
        "HYPE_BUY": 0, "HYPE_SELL": 0,
        "SOL_SELL": 15, "SOL_BUY": 10,
        "BTC_BUY": 10, "BTC_SELL": 0,
    }
    score += edge_trends.get(setup_key, 5)

    # Regime quality
    if abs(sig.regime_score) >= 2:
        score += 15
    elif abs(sig.regime_score) == 1:
        score += 10

    # Vol regime
    atr_pct = (sig.atr / sig.entry) * 100 if sig.entry > 0 else 1.0
    if setup_key == "HYPE_BUY":
        if 1.40 <= atr_pct <= 1.69:
            score += 10
        elif 1.15 <= atr_pct <= 1.90:
            score += 5
        else:
            score -= 5
    elif setup_key == "SOL_SELL":
        if 0.80 <= atr_pct <= 0.98:
            score += 10
        elif 0.60 <= atr_pct <= 1.20:
            score += 5
        else:
            score -= 5
    else:
        if 0.50 <= atr_pct <= 2.00:
            score += 5
        else:
            score -= 5

    # Time of day (use the signal's hour)
    hour = sig.time.hour if hasattr(sig.time, 'hour') else pd.to_datetime(sig.time).hour
    if 18 <= hour or hour < 6:
        score += 10
    elif 6 <= hour < 10 or 14 <= hour < 18:
        score += 5

    # Scorecard gate
    if score < 50:
        return False, f"scorecard_{score}", 0, 0

    # Size factor
    size_mult = 1.0 if score >= 70 else 0.5

    # NEW: Kelly leverage (3.9x half-Kelly baseline)
    # Adjust for confidence
    base_kelly = 3.9
    conf_factor = sig.confidence / 80.0  # normalize: 80% = 1.0
    lev = round(base_kelly * min(conf_factor, 1.3), 1)  # cap at 5.1x
    lev = max(2.0, min(lev, 5.0))  # hard bounds

    return True, "passed", lev, size_mult


# ── Trade simulation ───────────────────────────────────────────────

@dataclass
class SimTrade:
    """A simulated trade with full outcome tracking."""
    signal: SimSignal
    system: str  # "OLD" or "NEW"
    leverage: float
    size_mult: float = 1.0

    # Outcomes (filled during simulation)
    exit_price: float = 0.0
    exit_time: Optional[datetime] = None
    exit_reason: str = ""
    bars_held: int = 0
    pnl_pct: float = 0.0  # raw price move %
    pnl_at_2x: float = 0.0
    pnl_at_3_9x: float = 0.0
    pnl_at_5x: float = 0.0
    max_favorable: float = 0.0  # max favorable excursion %
    max_adverse: float = 0.0    # max adverse excursion %
    be_triggered: bool = False
    trailing_triggered: bool = False
    tp1_hit: bool = False
    sl_hit: bool = False
    time_stopped: bool = False


def simulate_trade_old(trade: SimTrade, df_1h: pd.DataFrame) -> SimTrade:
    """OLD system exits: fixed TP1/TP2 or SL. No time stop, no BE, no trailing."""
    sig = trade.signal
    start_idx = sig.bar_idx + 1  # enter at close, track from next bar
    max_bars = min(start_idx + 48, len(df_1h))  # max 48h hold

    for i in range(start_idx, max_bars):
        high = float(df_1h["high"].iloc[i])
        low = float(df_1h["low"].iloc[i])
        close_i = float(df_1h["close"].iloc[i])
        bars_held = i - sig.bar_idx

        # Track excursions
        if sig.side == "BUY":
            fav = (high - sig.entry) / sig.entry * 100
            adv = (sig.entry - low) / sig.entry * 100
        else:
            fav = (sig.entry - low) / sig.entry * 100
            adv = (high - sig.entry) / sig.entry * 100
        trade.max_favorable = max(trade.max_favorable, fav)
        trade.max_adverse = max(trade.max_adverse, adv)

        # Check SL
        if sig.side == "BUY" and low <= sig.sl:
            trade.exit_price = sig.sl
            trade.exit_reason = "SL_HIT"
            trade.sl_hit = True
            trade.exit_time = df_1h["time"].iloc[i]
            trade.bars_held = bars_held
            break
        elif sig.side == "SELL" and high >= sig.sl:
            trade.exit_price = sig.sl
            trade.exit_reason = "SL_HIT"
            trade.sl_hit = True
            trade.exit_time = df_1h["time"].iloc[i]
            trade.bars_held = bars_held
            break

        # Check TP1
        if sig.side == "BUY" and high >= sig.tp1:
            trade.exit_price = sig.tp1
            trade.exit_reason = "TP1_HIT"
            trade.tp1_hit = True
            trade.exit_time = df_1h["time"].iloc[i]
            trade.bars_held = bars_held
            break
        elif sig.side == "SELL" and low <= sig.tp1:
            trade.exit_price = sig.tp1
            trade.exit_reason = "TP1_HIT"
            trade.tp1_hit = True
            trade.exit_time = df_1h["time"].iloc[i]
            trade.bars_held = bars_held
            break
    else:
        # Expired (48h max hold = data end)
        trade.exit_price = float(df_1h["close"].iloc[min(max_bars - 1, len(df_1h) - 1)])
        trade.exit_reason = "EXPIRED"
        trade.exit_time = df_1h["time"].iloc[min(max_bars - 1, len(df_1h) - 1)]
        trade.bars_held = max_bars - sig.bar_idx

    # Calculate PnL
    if sig.side == "BUY":
        trade.pnl_pct = (trade.exit_price - sig.entry) / sig.entry * 100
    else:
        trade.pnl_pct = (sig.entry - trade.exit_price) / sig.entry * 100

    trade.pnl_at_2x = trade.pnl_pct * 2.0
    trade.pnl_at_3_9x = trade.pnl_pct * 3.9
    trade.pnl_at_5x = trade.pnl_pct * 5.0

    return trade


def simulate_trade_new(trade: SimTrade, df_1h: pd.DataFrame) -> SimTrade:
    """NEW system exits: 12h time stop, BE at +0.5%, trailing at +1.0%."""
    sig = trade.signal
    start_idx = sig.bar_idx + 1
    max_bars = min(start_idx + 48, len(df_1h))
    time_stop_bars = 12  # 12h time stop

    be_level = 0.010   # +1.0% -> move stop to breakeven (was 0.5%, too tight for 1h)
    trail_level = 0.015  # +1.5% -> activate trailing stop (was 1.0%)
    trail_distance = 0.008  # trailing distance = 0.8% (was 0.5%)

    current_stop = sig.sl
    trailing_active = False
    be_active = False

    for i in range(start_idx, max_bars):
        high = float(df_1h["high"].iloc[i])
        low = float(df_1h["low"].iloc[i])
        close_i = float(df_1h["close"].iloc[i])
        bars_held = i - sig.bar_idx

        # Track excursions
        if sig.side == "BUY":
            fav = (high - sig.entry) / sig.entry * 100
            adv = (sig.entry - low) / sig.entry * 100
            current_pnl_pct = (high - sig.entry) / sig.entry  # best case this bar
        else:
            fav = (sig.entry - low) / sig.entry * 100
            adv = (high - sig.entry) / sig.entry * 100
            current_pnl_pct = (sig.entry - low) / sig.entry
        trade.max_favorable = max(trade.max_favorable, fav)
        trade.max_adverse = max(trade.max_adverse, adv)

        # Smart exit logic: BE and trailing stop management
        if sig.side == "BUY":
            peak_pnl = (high - sig.entry) / sig.entry
            # BE at +0.5%
            if not be_active and peak_pnl >= be_level:
                current_stop = sig.entry * 1.0001  # tiny profit = breakeven
                be_active = True
                trade.be_triggered = True
            # Trailing at +1.0%
            if not trailing_active and peak_pnl >= trail_level:
                trailing_active = True
                trade.trailing_triggered = True
            if trailing_active:
                new_trail = high * (1 - trail_distance)
                current_stop = max(current_stop, new_trail)
        else:  # SELL
            peak_pnl = (sig.entry - low) / sig.entry
            if not be_active and peak_pnl >= be_level:
                current_stop = sig.entry * 0.9999
                be_active = True
                trade.be_triggered = True
            if not trailing_active and peak_pnl >= trail_level:
                trailing_active = True
                trade.trailing_triggered = True
            if trailing_active:
                new_trail = low * (1 + trail_distance)
                current_stop = min(current_stop, new_trail)

        # Check stop (could be original SL, BE, or trailing)
        if sig.side == "BUY" and low <= current_stop:
            trade.exit_price = current_stop
            if trailing_active:
                trade.exit_reason = "TRAILING_STOP"
            elif be_active:
                trade.exit_reason = "BE_STOP"
            else:
                trade.exit_reason = "SL_HIT"
                trade.sl_hit = True
            trade.exit_time = df_1h["time"].iloc[i]
            trade.bars_held = bars_held
            break
        elif sig.side == "SELL" and high >= current_stop:
            trade.exit_price = current_stop
            if trailing_active:
                trade.exit_reason = "TRAILING_STOP"
            elif be_active:
                trade.exit_reason = "BE_STOP"
            else:
                trade.exit_reason = "SL_HIT"
                trade.sl_hit = True
            trade.exit_time = df_1h["time"].iloc[i]
            trade.bars_held = bars_held
            break

        # Check TP1
        if sig.side == "BUY" and high >= sig.tp1:
            trade.exit_price = sig.tp1
            trade.exit_reason = "TP1_HIT"
            trade.tp1_hit = True
            trade.exit_time = df_1h["time"].iloc[i]
            trade.bars_held = bars_held
            break
        elif sig.side == "SELL" and low <= sig.tp1:
            trade.exit_price = sig.tp1
            trade.exit_reason = "TP1_HIT"
            trade.tp1_hit = True
            trade.exit_time = df_1h["time"].iloc[i]
            trade.bars_held = bars_held
            break

        # 12h time stop
        if bars_held >= time_stop_bars:
            trade.exit_price = close_i
            trade.exit_reason = "TIME_STOP_12H"
            trade.time_stopped = True
            trade.exit_time = df_1h["time"].iloc[i]
            trade.bars_held = bars_held
            break
    else:
        trade.exit_price = float(df_1h["close"].iloc[min(max_bars - 1, len(df_1h) - 1)])
        trade.exit_reason = "EXPIRED"
        trade.exit_time = df_1h["time"].iloc[min(max_bars - 1, len(df_1h) - 1)]
        trade.bars_held = max_bars - sig.bar_idx

    # Calculate PnL
    if sig.side == "BUY":
        trade.pnl_pct = (trade.exit_price - sig.entry) / sig.entry * 100
    else:
        trade.pnl_pct = (sig.entry - trade.exit_price) / sig.entry * 100

    trade.pnl_at_2x = trade.pnl_pct * 2.0 * trade.size_mult
    trade.pnl_at_3_9x = trade.pnl_pct * 3.9 * trade.size_mult
    trade.pnl_at_5x = trade.pnl_pct * 5.0 * trade.size_mult

    return trade


# ── Main backtest loop ─────────────────────────────────────────────

def run_backtest():
    """Run the full 48h comparison backtest."""
    print("=" * 80)
    print("  48-HOUR BACKTEST: OLD SYSTEM vs NEW (IMPROVED) SYSTEM")
    print("=" * 80)
    print()

    # Step 1: Fetch data
    print("[1/4] Fetching market data...")
    all_data = fetch_data()
    print()

    # Step 2: Compute indicators on full dataset
    print("[2/4] Computing indicators...")
    for sym in SYMBOLS:
        if all_data[sym]["1h"] is not None and not all_data[sym]["1h"].empty:
            all_data[sym]["1h"] = add_emas(all_data[sym]["1h"])
            print(f"  {sym} 1h: indicators added ({len(all_data[sym]['1h'])} bars)")
        if all_data[sym]["6h"] is not None and not all_data[sym]["6h"].empty:
            all_data[sym]["6h"] = add_emas(all_data[sym]["6h"])
            print(f"  {sym} 6h: indicators added ({len(all_data[sym]['6h'])} bars)")
    print()

    # Step 3: Generate signals on last 48 bars
    print("[3/4] Generating signals on last 48 hours...")
    old_trades: List[SimTrade] = []
    new_trades: List[SimTrade] = []
    all_signals: List[SimSignal] = []

    for sym in SYMBOLS:
        df_1h = all_data[sym]["1h"]
        df_6h = all_data[sym]["6h"]

        if df_1h is None or df_1h.empty or len(df_1h) < 60:
            print(f"  {sym}: insufficient data, skipping")
            continue

        # Last 48 bars
        start_bar = len(df_1h) - 48
        end_bar = len(df_1h) - 1  # leave last bar for exit check

        print(f"  {sym}: scanning bars {start_bar}-{end_bar} "
              f"({df_1h['time'].iloc[start_bar]} -> {df_1h['time'].iloc[end_bar]})")

        # Track open position to avoid overlapping trades
        old_open_until = -1
        new_open_until = -1

        for idx in range(start_bar, end_bar):
            sig = generate_signals_at_bar(sym, df_1h, df_6h, idx)
            if sig is None:
                continue

            all_signals.append(sig)

            # OLD system
            if idx > old_open_until:
                passed_old, reason_old, lev_old = old_system_filter(sig)
                if passed_old:
                    trade_old = SimTrade(signal=sig, system="OLD", leverage=lev_old)
                    trade_old = simulate_trade_old(trade_old, df_1h)
                    old_trades.append(trade_old)
                    old_open_until = idx + trade_old.bars_held

            # NEW system
            if idx > new_open_until:
                passed_new, reason_new, lev_new, size_mult = new_system_filter(sig)
                if passed_new:
                    trade_new = SimTrade(signal=sig, system="NEW", leverage=lev_new, size_mult=size_mult)
                    trade_new = simulate_trade_new(trade_new, df_1h)
                    new_trades.append(trade_new)
                    new_open_until = idx + trade_new.bars_held

    print(f"\n  Total signals generated: {len(all_signals)}")
    print(f"  OLD system trades: {len(old_trades)}")
    print(f"  NEW system trades: {len(new_trades)}")
    print()

    # Step 4: Report
    print("[4/4] RESULTS")
    print("=" * 80)

    for system_name, trades in [("OLD SYSTEM", old_trades), ("NEW SYSTEM", new_trades)]:
        print(f"\n{'─' * 40}")
        print(f"  {system_name}")
        print(f"{'─' * 40}")

        if not trades:
            print("  No trades taken.")
            continue

        # Per-trade details
        print(f"\n  {'#':>2} {'Symbol':>6} {'Side':>4} {'Entry':>10} {'Exit':>10} {'Reason':>15} "
              f"{'Bars':>4} {'Conf':>4} {'RR':>4} {'Raw%':>7} {'@2x':>7} {'@3.9x':>7} {'@5x':>7} "
              f"{'MFE%':>6} {'MAE%':>6} {'BE':>3} {'Trail':>5}")
        print(f"  {'─' * 130}")

        total_pnl_2x = 0
        total_pnl_3_9x = 0
        total_pnl_5x = 0
        wins = 0
        losses = 0

        for i, t in enumerate(trades):
            sig = t.signal
            is_win = t.pnl_pct > 0
            if is_win:
                wins += 1
            else:
                losses += 1
            total_pnl_2x += t.pnl_at_2x
            total_pnl_3_9x += t.pnl_at_3_9x
            total_pnl_5x += t.pnl_at_5x

            w_mark = "W" if is_win else "L"
            print(f"  {i+1:>2} {sig.symbol:>6} {sig.side:>4} {sig.entry:>10.2f} {t.exit_price:>10.2f} "
                  f"{t.exit_reason:>15} {t.bars_held:>4}h {sig.confidence:>3.0f}% {sig.rr:>4.1f} "
                  f"{t.pnl_pct:>+6.2f}% {t.pnl_at_2x:>+6.2f}% {t.pnl_at_3_9x:>+6.2f}% {t.pnl_at_5x:>+6.2f}% "
                  f"{t.max_favorable:>5.2f}% {t.max_adverse:>5.2f}% "
                  f"{'Y' if t.be_triggered else 'N':>3} {'Y' if t.trailing_triggered else 'N':>5} {w_mark}")

        total = wins + losses
        wr = wins / total * 100 if total > 0 else 0

        print(f"\n  Summary:")
        print(f"    Trades: {total} (W:{wins} L:{losses})")
        print(f"    Win Rate: {wr:.1f}%")
        print(f"    PnL (raw):   {sum(t.pnl_pct for t in trades):>+.2f}%")
        print(f"    PnL @ 2x:    {total_pnl_2x:>+.2f}%")
        print(f"    PnL @ 3.9x:  {total_pnl_3_9x:>+.2f}%")
        print(f"    PnL @ 5x:    {total_pnl_5x:>+.2f}%")

        # Dollar PnL on $100 account
        equity = 100.0
        print(f"\n    On $100 account:")
        print(f"      @ 2x leverage:   ${equity * total_pnl_2x / 100:>+.2f}")
        print(f"      @ 3.9x leverage: ${equity * total_pnl_3_9x / 100:>+.2f}")
        print(f"      @ 5x leverage:   ${equity * total_pnl_5x / 100:>+.2f}")

        # Exit analysis
        exit_reasons = {}
        for t in trades:
            exit_reasons[t.exit_reason] = exit_reasons.get(t.exit_reason, 0) + 1
        print(f"\n    Exit breakdown:")
        for reason, count in sorted(exit_reasons.items(), key=lambda x: -x[1]):
            pnl_this = sum(t.pnl_pct for t in trades if t.exit_reason == reason)
            print(f"      {reason:>15}: {count} trades, {pnl_this:>+.2f}% raw PnL")

        # BE/Trailing stats
        be_count = sum(1 for t in trades if t.be_triggered)
        trail_count = sum(1 for t in trades if t.trailing_triggered)
        print(f"\n    Smart exit stats:")
        print(f"      BE triggered: {be_count}/{total}")
        print(f"      Trailing triggered: {trail_count}/{total}")

    # ── Head-to-head comparison ──
    print(f"\n{'=' * 80}")
    print("  HEAD-TO-HEAD COMPARISON")
    print(f"{'=' * 80}")

    old_total_raw = sum(t.pnl_pct for t in old_trades) if old_trades else 0
    new_total_raw = sum(t.pnl_pct for t in new_trades) if new_trades else 0
    old_total_39 = sum(t.pnl_at_3_9x for t in old_trades) if old_trades else 0
    new_total_39 = sum(t.pnl_at_3_9x for t in new_trades) if new_trades else 0

    print(f"\n  {'Metric':>25} {'OLD':>12} {'NEW':>12} {'Delta':>12}")
    print(f"  {'─' * 61}")
    print(f"  {'Trades taken':>25} {len(old_trades):>12} {len(new_trades):>12} {len(new_trades)-len(old_trades):>+12}")
    print(f"  {'Win rate':>25} {(sum(1 for t in old_trades if t.pnl_pct > 0)/max(len(old_trades),1)*100):>11.1f}% "
          f"{(sum(1 for t in new_trades if t.pnl_pct > 0)/max(len(new_trades),1)*100):>11.1f}% "
          f"{((sum(1 for t in new_trades if t.pnl_pct > 0)/max(len(new_trades),1)*100)-(sum(1 for t in old_trades if t.pnl_pct > 0)/max(len(old_trades),1)*100)):>+11.1f}%")
    print(f"  {'Raw PnL':>25} {old_total_raw:>+11.2f}% {new_total_raw:>+11.2f}% {new_total_raw-old_total_raw:>+11.2f}%")
    print(f"  {'PnL @ 3.9x':>25} {old_total_39:>+11.2f}% {new_total_39:>+11.2f}% {new_total_39-old_total_39:>+11.2f}%")

    old_dollar = 100 * old_total_39 / 100
    new_dollar = 100 * new_total_39 / 100
    print(f"  {'$100 @ 3.9x':>25} ${old_dollar:>+10.2f} ${new_dollar:>+10.2f} ${new_dollar-old_dollar:>+10.2f}")

    # Per-symbol breakdown
    print(f"\n  Per-symbol breakdown (@ 3.9x leverage):")
    for sym in SYMBOLS:
        old_sym = [t for t in old_trades if t.signal.symbol == sym]
        new_sym = [t for t in new_trades if t.signal.symbol == sym]
        old_pnl = sum(t.pnl_at_3_9x for t in old_sym)
        new_pnl = sum(t.pnl_at_3_9x for t in new_sym)
        print(f"    {sym:>6}: OLD {len(old_sym)} trades {old_pnl:>+.2f}% | "
              f"NEW {len(new_sym)} trades {new_pnl:>+.2f}% | "
              f"delta {new_pnl-old_pnl:>+.2f}%")

    # Signal rejection analysis
    print(f"\n  Signal filter analysis (what NEW system blocked vs OLD):")
    for sym in SYMBOLS:
        sym_sigs = [s for s in all_signals if s.symbol == sym]
        for side in ["BUY", "SELL"]:
            side_sigs = [s for s in sym_sigs if s.side == side]
            if not side_sigs:
                continue
            old_pass = 0
            new_pass = 0
            new_rejections = {}
            for s in side_sigs:
                p_old, r_old, _ = old_system_filter(s)
                p_new, r_new, _, _ = new_system_filter(s)
                if p_old:
                    old_pass += 1
                if p_new:
                    new_pass += 1
                else:
                    new_rejections[r_new] = new_rejections.get(r_new, 0) + 1
            print(f"    {sym} {side}: {len(side_sigs)} signals -> OLD passed {old_pass}, NEW passed {new_pass}")
            if new_rejections:
                top_rej = sorted(new_rejections.items(), key=lambda x: -x[1])[:3]
                rej_str = ", ".join(f"{r}({c})" for r, c in top_rej)
                print(f"      Top NEW rejections: {rej_str}")

    print(f"\n{'=' * 80}")
    if new_total_39 > old_total_39:
        diff = new_total_39 - old_total_39
        print(f"  VERDICT: NEW system OUTPERFORMS by {diff:+.2f}% (@ 3.9x) = ${100*diff/100:+.2f} on $100")
    elif new_total_39 < old_total_39:
        diff = old_total_39 - new_total_39
        print(f"  VERDICT: OLD system outperforms by {diff:+.2f}% (@ 3.9x) = ${100*diff/100:+.2f} on $100")
    else:
        print(f"  VERDICT: Systems tied")
    print(f"{'=' * 80}")


if __name__ == "__main__":
    run_backtest()
