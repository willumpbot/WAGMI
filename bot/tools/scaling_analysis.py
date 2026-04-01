"""
Scaling Entry/Exit Analysis Tool
=================================
Fetches 500 1h candles for HYPE, BTC, SOL and simulates:
1. DCA entries (full vs 50/50 vs 33/33/33)
2. Scale-out exits (full TP1 vs partial+trail vs tiered R)
3. Pyramid into winners
4. Kelly argument for/against scaling
5. SOL SELL specific analysis
"""

import sys
import os
import math
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field

# Add bot dir to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

from data.fetcher import DataFetcher
from trading_config import DEFAULT_SYMBOLS


# ─── Configuration ──────────────────────────────────────────────
ATR_PERIOD = 14
ENTRY_LOOKBACK = 3        # bars to wait for DCA fills
SL_ATR_MULT = 1.5         # stop loss = 1.5 ATR
TP1_ATR_MULT = 1.5        # TP1 = 1.5R  (i.e. 1.5 * SL distance)
TP2_ATR_MULT = 3.0        # TP2 = 3.0R
FEE_BPS = 4               # taker fee in bps (0.04%)
INITIAL_CAPITAL = 1000.0
RISK_PER_TRADE = 0.02     # 2% risk per trade


@dataclass
class TradeResult:
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    sl: float
    tp1: float
    tp2: float
    atr: float
    pnl_pct: float       # net of fees
    r_captured: float     # how many R captured
    method: str           # which scaling method
    bars_held: int
    won: bool


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def detect_signals(df: pd.DataFrame, atr: pd.Series) -> List[dict]:
    """Simple mean-reversion + momentum signals for backtesting scaling methods.

    Uses EMA crossover + RSI for signal generation.
    Returns list of {bar_idx, side, entry, sl, tp1, tp2, atr_val}.
    """
    close = df["close"].values

    # EMA 9/21 crossover
    ema9 = df["close"].ewm(span=9).mean().values
    ema21 = df["close"].ewm(span=21).mean().values

    # RSI 14
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = (100 - 100 / (1 + rs)).values

    atr_vals = atr.values
    signals = []

    cooldown = 0
    for i in range(25, len(df) - 20):  # leave room for trade to play out
        if cooldown > 0:
            cooldown -= 1
            continue
        if np.isnan(atr_vals[i]) or atr_vals[i] <= 0:
            continue

        a = atr_vals[i]

        # BUY: EMA9 crosses above EMA21, RSI < 65
        if ema9[i] > ema21[i] and ema9[i-1] <= ema21[i-1] and rsi[i] < 65:
            entry = close[i]
            sl = entry - SL_ATR_MULT * a
            tp1 = entry + TP1_ATR_MULT * a
            tp2 = entry + TP2_ATR_MULT * a
            signals.append({
                "bar_idx": i, "side": "BUY", "entry": entry,
                "sl": sl, "tp1": tp1, "tp2": tp2, "atr": a
            })
            cooldown = 5

        # SELL: EMA9 crosses below EMA21, RSI > 35
        elif ema9[i] < ema21[i] and ema9[i-1] >= ema21[i-1] and rsi[i] > 35:
            entry = close[i]
            sl = entry + SL_ATR_MULT * a
            tp1 = entry - TP1_ATR_MULT * a
            tp2 = entry - TP2_ATR_MULT * a
            signals.append({
                "bar_idx": i, "side": "SELL", "entry": entry,
                "sl": sl, "tp1": tp1, "tp2": tp2, "atr": a
            })
            cooldown = 5

    return signals


def fee_cost(price: float, size_frac: float) -> float:
    """Fee as fraction of position for a given fill."""
    return price * size_frac * FEE_BPS / 10000.0


# ═══════════════════════════════════════════════════════════════
# SECTION 1: DCA Entry Methods
# ═══════════════════════════════════════════════════════════════

def sim_entry_method_a(sig: dict, df: pd.DataFrame) -> Optional[TradeResult]:
    """Method A: Full size at signal bar (current approach)."""
    idx = sig["bar_idx"]
    entry = sig["entry"]
    sl = sig["sl"]
    tp1 = sig["tp1"]
    side = sig["side"]
    atr = sig["atr"]
    stop_dist = abs(entry - sl)

    # Simulate forward
    fees = 2 * FEE_BPS / 10000.0  # entry + exit fee

    for j in range(1, min(50, len(df) - idx)):
        bar = df.iloc[idx + j]
        high, low, close = bar["high"], bar["low"], bar["close"]

        if side == "BUY":
            if low <= sl:
                pnl_pct = (sl - entry) / entry - fees
                return TradeResult(symbol="", side=side, entry_price=entry, exit_price=sl,
                                   sl=sl, tp1=tp1, tp2=sig["tp2"], atr=atr,
                                   pnl_pct=pnl_pct, r_captured=-1.0, method="A_full",
                                   bars_held=j, won=False)
            if high >= tp1:
                pnl_pct = (tp1 - entry) / entry - fees
                r_cap = (tp1 - entry) / stop_dist
                return TradeResult(symbol="", side=side, entry_price=entry, exit_price=tp1,
                                   sl=sl, tp1=tp1, tp2=sig["tp2"], atr=atr,
                                   pnl_pct=pnl_pct, r_captured=r_cap, method="A_full",
                                   bars_held=j, won=True)
        else:  # SELL
            if high >= sl:
                pnl_pct = (entry - sl) / entry - fees
                return TradeResult(symbol="", side=side, entry_price=entry, exit_price=sl,
                                   sl=sl, tp1=tp1, tp2=sig["tp2"], atr=atr,
                                   pnl_pct=pnl_pct, r_captured=-1.0, method="A_full",
                                   bars_held=j, won=False)
            if low <= tp1:
                pnl_pct = (entry - tp1) / entry - fees
                r_cap = (entry - tp1) / stop_dist
                return TradeResult(symbol="", side=side, entry_price=entry, exit_price=tp1,
                                   sl=sl, tp1=tp1, tp2=sig["tp2"], atr=atr,
                                   pnl_pct=pnl_pct, r_captured=r_cap, method="A_full",
                                   bars_held=j, won=True)

    # Time exit at last bar
    last_close = df.iloc[min(idx + 49, len(df) - 1)]["close"]
    if side == "BUY":
        pnl_pct = (last_close - entry) / entry - fees
        r_cap = (last_close - entry) / stop_dist
    else:
        pnl_pct = (entry - last_close) / entry - fees
        r_cap = (entry - last_close) / stop_dist
    return TradeResult(symbol="", side=side, entry_price=entry, exit_price=last_close,
                       sl=sl, tp1=tp1, tp2=sig["tp2"], atr=atr,
                       pnl_pct=pnl_pct, r_captured=r_cap, method="A_full",
                       bars_held=50, won=pnl_pct > 0)


def sim_entry_method_b(sig: dict, df: pd.DataFrame) -> Optional[TradeResult]:
    """Method B: 50% at level, 50% if price improves 0.5% more."""
    idx = sig["bar_idx"]
    entry1 = sig["entry"]
    sl = sig["sl"]
    tp1 = sig["tp1"]
    side = sig["side"]
    atr = sig["atr"]
    stop_dist = abs(entry1 - sl)

    # DCA level: 0.5% better
    if side == "BUY":
        entry2 = entry1 * 0.995  # buy lower
    else:
        entry2 = entry1 * 1.005  # sell higher

    filled_1 = True   # always fill first tranche
    filled_2 = False
    avg_entry = entry1  # will update if second fills
    total_weight = 0.5  # starts at 50%

    # Check if second tranche fills within ENTRY_LOOKBACK bars
    for j in range(1, ENTRY_LOOKBACK + 1):
        if idx + j >= len(df):
            break
        bar = df.iloc[idx + j]
        if side == "BUY" and bar["low"] <= entry2:
            filled_2 = True
            avg_entry = (entry1 * 0.5 + entry2 * 0.5)
            total_weight = 1.0
            break
        elif side == "SELL" and bar["high"] >= entry2:
            filled_2 = True
            avg_entry = (entry1 * 0.5 + entry2 * 0.5)
            total_weight = 1.0
            break

    if not filled_2:
        avg_entry = entry1
        total_weight = 0.5  # only half size deployed

    # Fee: entry fees for filled tranches + exit fee
    n_fills = 2 if filled_2 else 1
    fees = (n_fills + 1) * FEE_BPS / 10000.0

    # Simulate from entry bar forward (same SL/TP based on original signal)
    for j in range(1, min(50, len(df) - idx)):
        bar = df.iloc[idx + j]
        high, low = bar["high"], bar["low"]

        if side == "BUY":
            if low <= sl:
                pnl_pct = (sl - avg_entry) / avg_entry * total_weight - fees
                return TradeResult(symbol="", side=side, entry_price=avg_entry, exit_price=sl,
                                   sl=sl, tp1=tp1, tp2=sig["tp2"], atr=atr,
                                   pnl_pct=pnl_pct, r_captured=-1.0 * total_weight,
                                   method="B_50_50", bars_held=j, won=False)
            if high >= tp1:
                pnl_pct = (tp1 - avg_entry) / avg_entry * total_weight - fees
                r_cap = (tp1 - avg_entry) / stop_dist * total_weight
                return TradeResult(symbol="", side=side, entry_price=avg_entry, exit_price=tp1,
                                   sl=sl, tp1=tp1, tp2=sig["tp2"], atr=atr,
                                   pnl_pct=pnl_pct, r_captured=r_cap,
                                   method="B_50_50", bars_held=j, won=True)
        else:
            if high >= sl:
                pnl_pct = (avg_entry - sl) / avg_entry * total_weight - fees
                return TradeResult(symbol="", side=side, entry_price=avg_entry, exit_price=sl,
                                   sl=sl, tp1=tp1, tp2=sig["tp2"], atr=atr,
                                   pnl_pct=pnl_pct, r_captured=-1.0 * total_weight,
                                   method="B_50_50", bars_held=j, won=False)
            if low <= tp1:
                pnl_pct = (avg_entry - tp1) / avg_entry * total_weight - fees
                r_cap = (avg_entry - tp1) / stop_dist * total_weight
                return TradeResult(symbol="", side=side, entry_price=avg_entry, exit_price=tp1,
                                   sl=sl, tp1=tp1, tp2=sig["tp2"], atr=atr,
                                   pnl_pct=pnl_pct, r_captured=r_cap,
                                   method="B_50_50", bars_held=j, won=True)

    last_close = df.iloc[min(idx + 49, len(df) - 1)]["close"]
    if side == "BUY":
        pnl_pct = (last_close - avg_entry) / avg_entry * total_weight - fees
        r_cap = (last_close - avg_entry) / stop_dist * total_weight
    else:
        pnl_pct = (avg_entry - last_close) / avg_entry * total_weight - fees
        r_cap = (avg_entry - last_close) / stop_dist * total_weight
    return TradeResult(symbol="", side=side, entry_price=avg_entry, exit_price=last_close,
                       sl=sl, tp1=tp1, tp2=sig["tp2"], atr=atr,
                       pnl_pct=pnl_pct, r_captured=r_cap,
                       method="B_50_50", bars_held=50, won=pnl_pct > 0)


def sim_entry_method_c(sig: dict, df: pd.DataFrame) -> Optional[TradeResult]:
    """Method C: 33% at level, 33% at -0.5%, 33% at -1.0%."""
    idx = sig["bar_idx"]
    entry1 = sig["entry"]
    sl = sig["sl"]
    tp1 = sig["tp1"]
    side = sig["side"]
    atr = sig["atr"]
    stop_dist = abs(entry1 - sl)

    if side == "BUY":
        entry2 = entry1 * 0.995
        entry3 = entry1 * 0.990
    else:
        entry2 = entry1 * 1.005
        entry3 = entry1 * 1.010

    fills = [entry1]  # always fill first

    for j in range(1, ENTRY_LOOKBACK + 1):
        if idx + j >= len(df):
            break
        bar = df.iloc[idx + j]
        if side == "BUY":
            if len(fills) < 2 and bar["low"] <= entry2:
                fills.append(entry2)
            if len(fills) < 3 and bar["low"] <= entry3:
                fills.append(entry3)
        else:
            if len(fills) < 2 and bar["high"] >= entry2:
                fills.append(entry2)
            if len(fills) < 3 and bar["high"] >= entry3:
                fills.append(entry3)

    n_fills = len(fills)
    avg_entry = sum(fills) / n_fills
    total_weight = n_fills / 3.0  # fraction of intended size deployed
    fees = (n_fills + 1) * FEE_BPS / 10000.0

    for j in range(1, min(50, len(df) - idx)):
        bar = df.iloc[idx + j]
        high, low = bar["high"], bar["low"]

        if side == "BUY":
            if low <= sl:
                pnl_pct = (sl - avg_entry) / avg_entry * total_weight - fees
                return TradeResult(symbol="", side=side, entry_price=avg_entry, exit_price=sl,
                                   sl=sl, tp1=tp1, tp2=sig["tp2"], atr=atr,
                                   pnl_pct=pnl_pct, r_captured=-1.0 * total_weight,
                                   method="C_33_33_33", bars_held=j, won=False)
            if high >= tp1:
                pnl_pct = (tp1 - avg_entry) / avg_entry * total_weight - fees
                r_cap = (tp1 - avg_entry) / stop_dist * total_weight
                return TradeResult(symbol="", side=side, entry_price=avg_entry, exit_price=tp1,
                                   sl=sl, tp1=tp1, tp2=sig["tp2"], atr=atr,
                                   pnl_pct=pnl_pct, r_captured=r_cap,
                                   method="C_33_33_33", bars_held=j, won=True)
        else:
            if high >= sl:
                pnl_pct = (avg_entry - sl) / avg_entry * total_weight - fees
                return TradeResult(symbol="", side=side, entry_price=avg_entry, exit_price=sl,
                                   sl=sl, tp1=tp1, tp2=sig["tp2"], atr=atr,
                                   pnl_pct=pnl_pct, r_captured=-1.0 * total_weight,
                                   method="C_33_33_33", bars_held=j, won=False)
            if low <= tp1:
                pnl_pct = (avg_entry - tp1) / avg_entry * total_weight - fees
                r_cap = (avg_entry - tp1) / stop_dist * total_weight
                return TradeResult(symbol="", side=side, entry_price=avg_entry, exit_price=tp1,
                                   sl=sl, tp1=tp1, tp2=sig["tp2"], atr=atr,
                                   pnl_pct=pnl_pct, r_captured=r_cap,
                                   method="C_33_33_33", bars_held=j, won=True)

    last_close = df.iloc[min(idx + 49, len(df) - 1)]["close"]
    if side == "BUY":
        pnl_pct = (last_close - avg_entry) / avg_entry * total_weight - fees
        r_cap = (last_close - avg_entry) / stop_dist * total_weight
    else:
        pnl_pct = (avg_entry - last_close) / avg_entry * total_weight - fees
        r_cap = (avg_entry - last_close) / stop_dist * total_weight
    return TradeResult(symbol="", side=side, entry_price=avg_entry, exit_price=last_close,
                       sl=sl, tp1=tp1, tp2=sig["tp2"], atr=atr,
                       pnl_pct=pnl_pct, r_captured=r_cap,
                       method="C_33_33_33", bars_held=50, won=pnl_pct > 0)


# ═══════════════════════════════════════════════════════════════
# SECTION 2: Scale-Out Exit Methods
# ═══════════════════════════════════════════════════════════════

def sim_exit_method_a(sig: dict, df: pd.DataFrame) -> Optional[TradeResult]:
    """Exit A: Full exit at TP1 (same as entry method A)."""
    return sim_entry_method_a(sig, df)


def sim_exit_method_b(sig: dict, df: pd.DataFrame) -> Optional[TradeResult]:
    """Exit B: 50% at TP1, trail remaining 50% with 1-ATR trailing stop."""
    idx = sig["bar_idx"]
    entry = sig["entry"]
    sl = sig["sl"]
    tp1 = sig["tp1"]
    tp2 = sig["tp2"]
    side = sig["side"]
    atr = sig["atr"]
    stop_dist = abs(entry - sl)
    fees_entry = FEE_BPS / 10000.0

    total_pnl = 0.0
    remaining = 1.0
    trailing_active = False
    trailing_stop = 0.0
    peak = entry

    for j in range(1, min(80, len(df) - idx)):
        bar = df.iloc[idx + j]
        high, low, close = bar["high"], bar["low"], bar["close"]

        if side == "BUY":
            # Check SL first
            if low <= sl and not trailing_active:
                exit_fee = remaining * FEE_BPS / 10000.0
                total_pnl += remaining * (sl - entry) / entry
                total_pnl -= (fees_entry + exit_fee)
                return TradeResult(symbol="", side=side, entry_price=entry, exit_price=sl,
                                   sl=sl, tp1=tp1, tp2=tp2, atr=atr,
                                   pnl_pct=total_pnl, r_captured=total_pnl * entry / stop_dist,
                                   method="B_50_trail", bars_held=j, won=False)

            # TP1 hit: close 50%
            if high >= tp1 and remaining > 0.5:
                pnl_half = 0.5 * (tp1 - entry) / entry
                total_pnl += pnl_half
                remaining = 0.5
                trailing_active = True
                peak = tp1
                sl = entry  # move SL to breakeven for remaining

            if trailing_active:
                if high > peak:
                    peak = high
                trailing_stop = peak - atr  # 1 ATR trailing
                trailing_stop = max(trailing_stop, entry)  # at least breakeven

                if low <= trailing_stop:
                    total_pnl += remaining * (trailing_stop - entry) / entry
                    exit_fee = (1 + (1 if remaining < 1 else 0)) * FEE_BPS / 10000.0
                    total_pnl -= exit_fee
                    r_cap = total_pnl * entry / stop_dist
                    return TradeResult(symbol="", side=side, entry_price=entry,
                                       exit_price=trailing_stop, sl=sl, tp1=tp1, tp2=tp2,
                                       atr=atr, pnl_pct=total_pnl, r_captured=r_cap,
                                       method="B_50_trail", bars_held=j, won=total_pnl > 0)

                if high >= tp2:
                    total_pnl += remaining * (tp2 - entry) / entry
                    exit_fee = 2 * FEE_BPS / 10000.0
                    total_pnl -= exit_fee
                    r_cap = total_pnl * entry / stop_dist
                    return TradeResult(symbol="", side=side, entry_price=entry,
                                       exit_price=tp2, sl=sl, tp1=tp1, tp2=tp2,
                                       atr=atr, pnl_pct=total_pnl, r_captured=r_cap,
                                       method="B_50_trail", bars_held=j, won=True)

        else:  # SELL
            if high >= sl and not trailing_active:
                exit_fee = remaining * FEE_BPS / 10000.0
                total_pnl += remaining * (entry - sl) / entry
                total_pnl -= (fees_entry + exit_fee)
                return TradeResult(symbol="", side=side, entry_price=entry, exit_price=sl,
                                   sl=sl, tp1=tp1, tp2=tp2, atr=atr,
                                   pnl_pct=total_pnl, r_captured=total_pnl * entry / stop_dist,
                                   method="B_50_trail", bars_held=j, won=False)

            if low <= tp1 and remaining > 0.5:
                pnl_half = 0.5 * (entry - tp1) / entry
                total_pnl += pnl_half
                remaining = 0.5
                trailing_active = True
                peak = tp1  # lowest price for short
                sl = entry

            if trailing_active:
                if low < peak:
                    peak = low
                trailing_stop = peak + atr
                trailing_stop = min(trailing_stop, entry)

                if high >= trailing_stop:
                    total_pnl += remaining * (entry - trailing_stop) / entry
                    exit_fee = 2 * FEE_BPS / 10000.0
                    total_pnl -= exit_fee
                    r_cap = total_pnl * entry / stop_dist
                    return TradeResult(symbol="", side=side, entry_price=entry,
                                       exit_price=trailing_stop, sl=sl, tp1=tp1, tp2=tp2,
                                       atr=atr, pnl_pct=total_pnl, r_captured=r_cap,
                                       method="B_50_trail", bars_held=j, won=total_pnl > 0)

                if low <= tp2:
                    total_pnl += remaining * (entry - tp2) / entry
                    exit_fee = 2 * FEE_BPS / 10000.0
                    total_pnl -= exit_fee
                    r_cap = total_pnl * entry / stop_dist
                    return TradeResult(symbol="", side=side, entry_price=entry,
                                       exit_price=tp2, sl=sl, tp1=tp1, tp2=tp2,
                                       atr=atr, pnl_pct=total_pnl, r_captured=r_cap,
                                       method="B_50_trail", bars_held=j, won=True)

    # Time exit
    last_close = df.iloc[min(idx + 79, len(df) - 1)]["close"]
    if side == "BUY":
        total_pnl += remaining * (last_close - entry) / entry
    else:
        total_pnl += remaining * (entry - last_close) / entry
    total_pnl -= 2 * FEE_BPS / 10000.0
    r_cap = total_pnl * entry / stop_dist if stop_dist > 0 else 0
    return TradeResult(symbol="", side=side, entry_price=entry, exit_price=last_close,
                       sl=sl, tp1=tp1, tp2=tp2, atr=atr,
                       pnl_pct=total_pnl, r_captured=r_cap,
                       method="B_50_trail", bars_held=80, won=total_pnl > 0)


def sim_exit_method_c(sig: dict, df: pd.DataFrame) -> Optional[TradeResult]:
    """Exit C: 33% at +0.5R, 33% at +1R, 33% at +2R."""
    idx = sig["bar_idx"]
    entry = sig["entry"]
    sl = sig["sl"]
    side = sig["side"]
    atr = sig["atr"]
    stop_dist = abs(entry - sl)

    # Three TP levels
    if side == "BUY":
        tp_levels = [entry + 0.5 * stop_dist, entry + 1.0 * stop_dist, entry + 2.0 * stop_dist]
    else:
        tp_levels = [entry - 0.5 * stop_dist, entry - 1.0 * stop_dist, entry - 2.0 * stop_dist]

    total_pnl = 0.0
    remaining = 1.0
    tranches_closed = 0
    current_sl = sl

    for j in range(1, min(80, len(df) - idx)):
        bar = df.iloc[idx + j]
        high, low = bar["high"], bar["low"]

        if side == "BUY":
            if low <= current_sl:
                total_pnl += remaining * (current_sl - entry) / entry
                fees = (tranches_closed + 2) * FEE_BPS / 10000.0
                total_pnl -= fees
                return TradeResult(symbol="", side=side, entry_price=entry, exit_price=current_sl,
                                   sl=sl, tp1=tp_levels[1], tp2=tp_levels[2], atr=atr,
                                   pnl_pct=total_pnl, r_captured=total_pnl * entry / stop_dist,
                                   method="C_tiered_R", bars_held=j, won=total_pnl > 0)

            for k in range(tranches_closed, min(3, len(tp_levels))):
                if high >= tp_levels[k]:
                    close_frac = 1.0 / 3.0
                    total_pnl += close_frac * (tp_levels[k] - entry) / entry
                    remaining -= close_frac
                    tranches_closed += 1
                    if tranches_closed == 1:
                        current_sl = entry  # breakeven after first TP
                    elif tranches_closed == 2:
                        current_sl = tp_levels[0]  # lock in 0.5R after second TP

        else:  # SELL
            if high >= current_sl:
                total_pnl += remaining * (entry - current_sl) / entry
                fees = (tranches_closed + 2) * FEE_BPS / 10000.0
                total_pnl -= fees
                return TradeResult(symbol="", side=side, entry_price=entry, exit_price=current_sl,
                                   sl=sl, tp1=tp_levels[1], tp2=tp_levels[2], atr=atr,
                                   pnl_pct=total_pnl, r_captured=total_pnl * entry / stop_dist,
                                   method="C_tiered_R", bars_held=j, won=total_pnl > 0)

            for k in range(tranches_closed, min(3, len(tp_levels))):
                if low <= tp_levels[k]:
                    close_frac = 1.0 / 3.0
                    total_pnl += close_frac * (entry - tp_levels[k]) / entry
                    remaining -= close_frac
                    tranches_closed += 1
                    if tranches_closed == 1:
                        current_sl = entry
                    elif tranches_closed == 2:
                        current_sl = tp_levels[0] if side == "SELL" else tp_levels[0]
                        # For SELL, lock at first TP (which is below entry)
                        current_sl = 2 * entry - tp_levels[0]  # mirror for sell

        if remaining <= 0.01:
            fees = 4 * FEE_BPS / 10000.0  # 1 entry + 3 exits
            total_pnl -= fees
            r_cap = total_pnl * entry / stop_dist
            return TradeResult(symbol="", side=side, entry_price=entry, exit_price=tp_levels[2],
                               sl=sl, tp1=tp_levels[1], tp2=tp_levels[2], atr=atr,
                               pnl_pct=total_pnl, r_captured=r_cap,
                               method="C_tiered_R", bars_held=j, won=True)

    last_close = df.iloc[min(idx + 79, len(df) - 1)]["close"]
    if side == "BUY":
        total_pnl += remaining * (last_close - entry) / entry
    else:
        total_pnl += remaining * (entry - last_close) / entry
    fees = (tranches_closed + 2) * FEE_BPS / 10000.0
    total_pnl -= fees
    r_cap = total_pnl * entry / stop_dist if stop_dist > 0 else 0
    return TradeResult(symbol="", side=side, entry_price=entry, exit_price=last_close,
                       sl=sl, tp1=tp_levels[1] if len(tp_levels) > 1 else 0,
                       tp2=tp_levels[2] if len(tp_levels) > 2 else 0, atr=atr,
                       pnl_pct=total_pnl, r_captured=r_cap,
                       method="C_tiered_R", bars_held=80, won=total_pnl > 0)


# ═══════════════════════════════════════════════════════════════
# SECTION 3: Pyramid into Winners
# ═══════════════════════════════════════════════════════════════

def sim_pyramid(sig: dict, df: pd.DataFrame) -> Tuple[Optional[TradeResult], Optional[TradeResult]]:
    """Compare fixed size vs pyramid (add 50% at +0.5% with SL moved to breakeven).

    Returns (fixed_result, pyramid_result).
    """
    idx = sig["bar_idx"]
    entry = sig["entry"]
    sl = sig["sl"]
    tp1 = sig["tp1"]
    side = sig["side"]
    atr = sig["atr"]
    stop_dist = abs(entry - sl)

    # Fixed size result (reuse method A)
    fixed = sim_entry_method_a(sig, df)

    # Pyramid: start with 1.0 size, add 0.5 at +0.5%
    if side == "BUY":
        add_level = entry * 1.005
    else:
        add_level = entry * 0.995

    size = 1.0
    added = False
    avg_entry = entry
    pyramid_sl = sl

    total_pnl = 0.0

    for j in range(1, min(50, len(df) - idx)):
        bar = df.iloc[idx + j]
        high, low, close = bar["high"], bar["low"], bar["close"]

        if side == "BUY":
            # Check for add
            if not added and high >= add_level:
                added = True
                avg_entry = (entry * 1.0 + add_level * 0.5) / 1.5
                size = 1.5
                pyramid_sl = entry  # breakeven on original

            if low <= pyramid_sl:
                pnl = size * (pyramid_sl - avg_entry) / avg_entry
                fees = (2 if added else 1 + 1) * FEE_BPS / 10000.0
                pnl -= fees
                pyr = TradeResult(symbol="", side=side, entry_price=avg_entry,
                                  exit_price=pyramid_sl, sl=sl, tp1=tp1, tp2=sig["tp2"],
                                  atr=atr, pnl_pct=pnl, r_captured=pnl * avg_entry / stop_dist,
                                  method="pyramid", bars_held=j, won=pnl > 0)
                return fixed, pyr

            if high >= tp1:
                pnl = size * (tp1 - avg_entry) / avg_entry
                fees = (2 if added else 1 + 1) * FEE_BPS / 10000.0
                pnl -= fees
                r_cap = pnl * avg_entry / stop_dist
                pyr = TradeResult(symbol="", side=side, entry_price=avg_entry,
                                  exit_price=tp1, sl=sl, tp1=tp1, tp2=sig["tp2"],
                                  atr=atr, pnl_pct=pnl, r_captured=r_cap,
                                  method="pyramid", bars_held=j, won=True)
                return fixed, pyr

        else:  # SELL
            if not added and low <= add_level:
                added = True
                avg_entry = (entry * 1.0 + add_level * 0.5) / 1.5
                size = 1.5
                pyramid_sl = entry

            if high >= pyramid_sl:
                pnl = size * (avg_entry - pyramid_sl) / avg_entry
                fees = (2 if added else 1 + 1) * FEE_BPS / 10000.0
                pnl -= fees
                pyr = TradeResult(symbol="", side=side, entry_price=avg_entry,
                                  exit_price=pyramid_sl, sl=sl, tp1=tp1, tp2=sig["tp2"],
                                  atr=atr, pnl_pct=pnl, r_captured=pnl * avg_entry / stop_dist,
                                  method="pyramid", bars_held=j, won=pnl > 0)
                return fixed, pyr

            if low <= tp1:
                pnl = size * (avg_entry - tp1) / avg_entry
                fees = (2 if added else 1 + 1) * FEE_BPS / 10000.0
                pnl -= fees
                r_cap = pnl * avg_entry / stop_dist
                pyr = TradeResult(symbol="", side=side, entry_price=avg_entry,
                                  exit_price=tp1, sl=sl, tp1=tp1, tp2=sig["tp2"],
                                  atr=atr, pnl_pct=pnl, r_captured=r_cap,
                                  method="pyramid", bars_held=j, won=True)
                return fixed, pyr

    # Time exit
    last_close = df.iloc[min(idx + 49, len(df) - 1)]["close"]
    if side == "BUY":
        pnl = size * (last_close - avg_entry) / avg_entry
    else:
        pnl = size * (avg_entry - last_close) / avg_entry
    fees = (2 if added else 1 + 1) * FEE_BPS / 10000.0
    pnl -= fees
    pyr = TradeResult(symbol="", side=side, entry_price=avg_entry,
                      exit_price=last_close, sl=sl, tp1=tp1, tp2=sig["tp2"],
                      atr=atr, pnl_pct=pnl, r_captured=pnl * avg_entry / stop_dist,
                      method="pyramid", bars_held=50, won=pnl > 0)
    return fixed, pyr


# ═══════════════════════════════════════════════════════════════
# SECTION 4: Kelly Criterion Analysis
# ═══════════════════════════════════════════════════════════════

def kelly_analysis(results: List[TradeResult]) -> dict:
    """Compute Kelly fraction and scaling implications."""
    if not results:
        return {"kelly_pct": 0, "edge": 0}

    wins = [r for r in results if r.won]
    losses = [r for r in results if not r.won]

    wr = len(wins) / len(results) if results else 0
    avg_win = np.mean([r.pnl_pct for r in wins]) if wins else 0
    avg_loss = abs(np.mean([r.pnl_pct for r in losses])) if losses else 0.01

    # Kelly: f* = (p*b - q) / b  where p=WR, q=1-WR, b=avg_win/avg_loss
    b = avg_win / avg_loss if avg_loss > 0 else 0
    q = 1 - wr
    kelly = (wr * b - q) / b if b > 0 else 0

    # Half-Kelly (practical)
    half_kelly = kelly / 2

    # Expected value per trade
    ev = wr * avg_win - q * avg_loss

    # Sharpe-like ratio
    all_pnl = [r.pnl_pct for r in results]
    sharpe = np.mean(all_pnl) / np.std(all_pnl) if np.std(all_pnl) > 0 else 0

    return {
        "win_rate": wr,
        "avg_win_pct": avg_win,
        "avg_loss_pct": avg_loss,
        "payoff_ratio": b,
        "kelly_pct": kelly * 100,
        "half_kelly_pct": half_kelly * 100,
        "ev_per_trade": ev,
        "sharpe_per_trade": sharpe,
        "n_trades": len(results),
    }


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    import io, sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    print("=" * 80)
    print("SCALING ENTRY/EXIT ANALYSIS")
    print("=" * 80)

    # Fetch data
    fetcher = DataFetcher(fresh=True)
    symbols_data = {}

    for sym, cfg in DEFAULT_SYMBOLS.items():
        print(f"\nFetching 500 1h candles for {sym}...")
        df = fetcher.fetch_ohlcv(sym, cfg.coingecko_id, "1h")
        if df is not None and not df.empty:
            # Take last 500
            df = df.tail(500).reset_index(drop=True)
            symbols_data[sym] = df
            print(f"  Got {len(df)} candles, range: {df['close'].iloc[0]:.2f} -> {df['close'].iloc[-1]:.2f}")
        else:
            print(f"  FAILED to fetch data for {sym}")

    if not symbols_data:
        print("No data fetched. Exiting.")
        return

    # ─── SECTION 1: DCA Entry Comparison ────────────────────
    print("\n" + "=" * 80)
    print("SECTION 1: DCA ENTRY METHODS")
    print("=" * 80)

    for sym, df in symbols_data.items():
        atr = compute_atr(df, ATR_PERIOD)
        signals = detect_signals(df, atr)
        print(f"\n{'─' * 60}")
        print(f"{sym}: {len(signals)} signals detected")
        print(f"{'─' * 60}")

        if not signals:
            continue

        results_a, results_b, results_c = [], [], []

        for sig in signals:
            sig_copy = sig.copy()

            ra = sim_entry_method_a(sig_copy, df)
            rb = sim_entry_method_b(sig_copy, df)
            rc = sim_entry_method_c(sig_copy, df)

            if ra: ra.symbol = sym; results_a.append(ra)
            if rb: rb.symbol = sym; results_b.append(rb)
            if rc: rc.symbol = sym; results_c.append(rc)

        for label, results in [("A: Full @signal", results_a),
                                ("B: 50/50 DCA", results_b),
                                ("C: 33/33/33 DCA", results_c)]:
            if not results:
                continue
            wins = sum(1 for r in results if r.won)
            wr = wins / len(results) * 100
            total_pnl = sum(r.pnl_pct for r in results) * 100
            avg_pnl = np.mean([r.pnl_pct for r in results]) * 100
            avg_r = np.mean([r.r_captured for r in results])
            avg_entry_improvement = 0
            if label.startswith("B") or label.startswith("C"):
                for ra, rx in zip(results_a, results):
                    if ra and rx:
                        avg_entry_improvement += abs(rx.entry_price - ra.entry_price) / ra.entry_price * 100
                avg_entry_improvement /= max(len(results), 1)

            print(f"  {label:20s} | Trades: {len(results):3d} | WR: {wr:5.1f}% | "
                  f"Total PnL: {total_pnl:+7.2f}% | Avg PnL: {avg_pnl:+5.2f}% | "
                  f"Avg R: {avg_r:+5.2f}")
            if avg_entry_improvement > 0:
                print(f"  {'':20s} | Avg entry improvement: {avg_entry_improvement:.3f}%")

    # ─── SECTION 2: Scale-Out Exit Comparison ────────────────
    print("\n" + "=" * 80)
    print("SECTION 2: SCALE-OUT EXIT METHODS")
    print("=" * 80)

    for sym, df in symbols_data.items():
        atr = compute_atr(df, ATR_PERIOD)
        signals = detect_signals(df, atr)
        print(f"\n{'─' * 60}")
        print(f"{sym}: {len(signals)} signals")
        print(f"{'─' * 60}")

        if not signals:
            continue

        results_ea, results_eb, results_ec = [], [], []

        for sig in signals:
            ra = sim_exit_method_a(sig, df)
            rb = sim_exit_method_b(sig, df)
            rc = sim_exit_method_c(sig, df)

            if ra: ra.symbol = sym; results_ea.append(ra)
            if rb: rb.symbol = sym; results_eb.append(rb)
            if rc: rc.symbol = sym; results_ec.append(rc)

        for label, results in [("A: Full @TP1", results_ea),
                                ("B: 50% TP1 + trail", results_eb),
                                ("C: Tiered 0.5/1/2R", results_ec)]:
            if not results:
                continue
            wins = sum(1 for r in results if r.won)
            wr = wins / len(results) * 100
            total_pnl = sum(r.pnl_pct for r in results) * 100
            avg_pnl = np.mean([r.pnl_pct for r in results]) * 100
            avg_r = np.mean([r.r_captured for r in results])
            max_drawdown = min(r.pnl_pct for r in results) * 100

            print(f"  {label:22s} | Trades: {len(results):3d} | WR: {wr:5.1f}% | "
                  f"Total PnL: {total_pnl:+7.2f}% | Avg R: {avg_r:+5.2f} | "
                  f"Worst: {max_drawdown:+6.2f}%")

    # ─── SECTION 3: Pyramid into Winners ─────────────────────
    print("\n" + "=" * 80)
    print("SECTION 3: PYRAMID INTO WINNERS")
    print("=" * 80)

    for sym, df in symbols_data.items():
        atr = compute_atr(df, ATR_PERIOD)
        signals = detect_signals(df, atr)
        print(f"\n{'─' * 60}")
        print(f"{sym}: {len(signals)} signals")
        print(f"{'─' * 60}")

        if not signals:
            continue

        fixed_results = []
        pyramid_results = []

        for sig in signals:
            fixed, pyr = sim_pyramid(sig, df)
            if fixed: fixed.symbol = sym; fixed_results.append(fixed)
            if pyr: pyr.symbol = sym; pyramid_results.append(pyr)

        for label, results in [("Fixed size", fixed_results), ("Pyramid +50%", pyramid_results)]:
            if not results:
                continue
            wins = sum(1 for r in results if r.won)
            wr = wins / len(results) * 100
            total_pnl = sum(r.pnl_pct for r in results) * 100
            avg_pnl = np.mean([r.pnl_pct for r in results]) * 100
            avg_r = np.mean([r.r_captured for r in results])

            print(f"  {label:16s} | Trades: {len(results):3d} | WR: {wr:5.1f}% | "
                  f"Total PnL: {total_pnl:+7.2f}% | Avg PnL: {avg_pnl:+5.2f}% | "
                  f"Avg R: {avg_r:+5.2f}")

    # ─── SECTION 4: Kelly Analysis ────────────────────────────
    print("\n" + "=" * 80)
    print("SECTION 4: KELLY CRITERION ANALYSIS")
    print("=" * 80)

    # Aggregate all method A results
    all_a = []
    all_b_entry = []
    all_c_entry = []
    all_b_exit = []
    all_c_exit = []
    all_pyramid = []

    for sym, df in symbols_data.items():
        atr = compute_atr(df, ATR_PERIOD)
        signals = detect_signals(df, atr)
        for sig in signals:
            ra = sim_entry_method_a(sig, df)
            rb = sim_entry_method_b(sig, df)
            rc = sim_entry_method_c(sig, df)
            eb = sim_exit_method_b(sig, df)
            ec = sim_exit_method_c(sig, df)
            _, pyr = sim_pyramid(sig, df)

            if ra: ra.symbol = sym; all_a.append(ra)
            if rb: rb.symbol = sym; all_b_entry.append(rb)
            if rc: rc.symbol = sym; all_c_entry.append(rc)
            if eb: eb.symbol = sym; all_b_exit.append(eb)
            if ec: ec.symbol = sym; all_c_exit.append(ec)
            if pyr: pyr.symbol = sym; all_pyramid.append(pyr)

    for label, results in [
        ("Baseline (full entry, full exit @TP1)", all_a),
        ("DCA 50/50 entry", all_b_entry),
        ("DCA 33/33/33 entry", all_c_entry),
        ("50% TP1 + trail exit", all_b_exit),
        ("Tiered 0.5/1/2R exit", all_c_exit),
        ("Pyramid +50% winners", all_pyramid),
    ]:
        k = kelly_analysis(results)
        print(f"\n  {label}")
        print(f"    Trades: {k['n_trades']} | WR: {k['win_rate']*100:.1f}% | "
              f"Payoff: {k['payoff_ratio']:.2f} | EV/trade: {k['ev_per_trade']*100:+.3f}%")
        print(f"    Kelly: {k['kelly_pct']:+.1f}% | Half-Kelly: {k['half_kelly_pct']:+.1f}% | "
              f"Sharpe/trade: {k['sharpe_per_trade']:.3f}")

    # ─── SECTION 5: SOL SELL Specific ─────────────────────────
    print("\n" + "=" * 80)
    print("SECTION 5: SOL SELL ANALYSIS (1.5R TARGET)")
    print("=" * 80)

    if "SOL" in symbols_data:
        df = symbols_data["SOL"]
        atr = compute_atr(df, ATR_PERIOD)
        signals = detect_signals(df, atr)
        sell_signals = [s for s in signals if s["side"] == "SELL"]

        print(f"\n  SOL SELL signals: {len(sell_signals)}")

        if sell_signals:
            methods = {
                "A: Full entry, full exit": [],
                "B: 50/50 DCA entry": [],
                "C: 33/33/33 DCA entry": [],
                "B: 50% TP1 + trail exit": [],
                "C: Tiered R exit": [],
                "Pyramid +50%": [],
            }

            for sig in sell_signals:
                ra = sim_entry_method_a(sig, df)
                rb = sim_entry_method_b(sig, df)
                rc = sim_entry_method_c(sig, df)
                eb = sim_exit_method_b(sig, df)
                ec = sim_exit_method_c(sig, df)
                _, pyr = sim_pyramid(sig, df)

                if ra: methods["A: Full entry, full exit"].append(ra)
                if rb: methods["B: 50/50 DCA entry"].append(rb)
                if rc: methods["C: 33/33/33 DCA entry"].append(rc)
                if eb: methods["B: 50% TP1 + trail exit"].append(eb)
                if ec: methods["C: Tiered R exit"].append(ec)
                if pyr: methods["Pyramid +50%"].append(pyr)

            print(f"\n  {'Method':<30s} | {'Trades':>6s} | {'WR':>6s} | {'Total PnL':>10s} | {'Avg R':>7s} | {'Kelly%':>7s}")
            print(f"  {'─'*30} | {'─'*6} | {'─'*6} | {'─'*10} | {'─'*7} | {'─'*7}")

            for label, results in methods.items():
                if not results:
                    continue
                wins = sum(1 for r in results if r.won)
                wr = wins / len(results) * 100
                total_pnl = sum(r.pnl_pct for r in results) * 100
                avg_r = np.mean([r.r_captured for r in results])
                k = kelly_analysis(results)

                print(f"  {label:<30s} | {len(results):6d} | {wr:5.1f}% | {total_pnl:+9.2f}% | {avg_r:+6.2f} | {k['kelly_pct']:+6.1f}%")

    # ─── FINAL RECOMMENDATION ────────────────────────────────
    print("\n" + "=" * 80)
    print("SUMMARY & RECOMMENDATION")
    print("=" * 80)

    # Compare total PnL across methods
    baseline_pnl = sum(r.pnl_pct for r in all_a) * 100 if all_a else 0
    dca50_pnl = sum(r.pnl_pct for r in all_b_entry) * 100 if all_b_entry else 0
    dca33_pnl = sum(r.pnl_pct for r in all_c_entry) * 100 if all_c_entry else 0
    trail_pnl = sum(r.pnl_pct for r in all_b_exit) * 100 if all_b_exit else 0
    tiered_pnl = sum(r.pnl_pct for r in all_c_exit) * 100 if all_c_exit else 0
    pyramid_pnl = sum(r.pnl_pct for r in all_pyramid) * 100 if all_pyramid else 0

    results_summary = [
        ("Baseline (current)", baseline_pnl),
        ("DCA 50/50 entry", dca50_pnl),
        ("DCA 33/33/33 entry", dca33_pnl),
        ("50% TP1 + trail", trail_pnl),
        ("Tiered R exit", tiered_pnl),
        ("Pyramid +50%", pyramid_pnl),
    ]

    results_summary.sort(key=lambda x: x[1], reverse=True)

    print(f"\n  Overall PnL ranking (all symbols combined):")
    for i, (label, pnl) in enumerate(results_summary, 1):
        delta = pnl - baseline_pnl
        marker = " <-- CURRENT" if "Baseline" in label else ""
        print(f"    {i}. {label:<25s}: {pnl:+8.2f}%  (vs baseline: {delta:+7.2f}%){marker}")

    # DCA fill rates
    print(f"\n  DCA Fill Rate Analysis:")
    for sym, df in symbols_data.items():
        atr = compute_atr(df, ATR_PERIOD)
        signals = detect_signals(df, atr)

        fill_2 = 0
        fill_3 = 0
        total = len(signals)

        for sig in signals:
            idx = sig["bar_idx"]
            entry1 = sig["entry"]
            side = sig["side"]

            if side == "BUY":
                lvl2 = entry1 * 0.995
                lvl3 = entry1 * 0.990
            else:
                lvl2 = entry1 * 1.005
                lvl3 = entry1 * 1.010

            for j in range(1, ENTRY_LOOKBACK + 1):
                if idx + j >= len(df):
                    break
                bar = df.iloc[idx + j]
                if side == "BUY":
                    if bar["low"] <= lvl2: fill_2 += 1
                    if bar["low"] <= lvl3: fill_3 += 1
                else:
                    if bar["high"] >= lvl2: fill_2 += 1
                    if bar["high"] >= lvl3: fill_3 += 1
                if fill_2 > 0 and fill_3 > 0:
                    break

        if total > 0:
            print(f"    {sym}: 2nd tranche fills {fill_2}/{total} ({fill_2/total*100:.0f}%), "
                  f"3rd tranche fills {fill_3}/{total} ({fill_3/total*100:.0f}%)")


if __name__ == "__main__":
    main()
