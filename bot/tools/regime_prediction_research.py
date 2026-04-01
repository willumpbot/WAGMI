"""
Regime Change Prediction Research
==================================
Analyzes leading indicators that predict regime shifts before they happen.
Fetches 500 1h candles for HYPE, BTC, SOL and tests 6 predictors.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd
from data.fetcher import DataFetcher

# ─── Technical Indicator Helpers ─────────────────────────────────────

def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).ewm(span=period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(span=period, adjust=False).mean()
    rs = gain / loss.replace(0, 1e-12)
    return 100.0 - (100.0 / (1.0 + rs))

def compute_bb(close: pd.Series, period: int = 20, std_mult: float = 2.0):
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = sma + std_mult * std
    lower = sma - std_mult * std
    width = (upper - lower) / sma * 100  # as % of price
    return upper, lower, width

def compute_macd(close: pd.Series):
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def compute_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    atr_val = tr.rolling(period, min_periods=1).mean()
    plus_di = (plus_dm.rolling(period, min_periods=1).mean() / atr_val.replace(0, 1e-9)) * 100
    minus_di = (minus_dm.rolling(period, min_periods=1).mean() / atr_val.replace(0, 1e-9)) * 100

    dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-9)) * 100
    adx = dx.rolling(period, min_periods=1).mean()
    return adx

def compute_ema(close: pd.Series, span: int) -> pd.Series:
    return close.ewm(span=span, adjust=False).mean()

def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev).abs(),
        (df["low"] - prev).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=1).mean()

# ─── Regime Classification ──────────────────────────────────────────

def classify_regimes(df: pd.DataFrame) -> pd.Series:
    """
    Simple regime classifier based on EMA slope + ADX + volatility.
    Returns: Series of regime labels for each bar.
    Regimes: bullish_trend, bearish_trend, range, high_vol, transition
    """
    close = df["close"]
    ema20 = compute_ema(close, 20)
    ema50 = compute_ema(close, 50)
    adx = compute_adx(df)
    atr = compute_atr(df)
    atr_pct = atr / close * 100  # ATR as % of price

    # EMA20 slope (rate of change over 5 bars)
    ema20_slope = ema20.pct_change(5) * 100

    regimes = pd.Series("range", index=df.index)

    for i in range(50, len(df)):
        adx_val = adx.iloc[i]
        slope = ema20_slope.iloc[i]
        vol = atr_pct.iloc[i]
        above_ema50 = close.iloc[i] > ema50.iloc[i]

        if vol > atr_pct.rolling(50).mean().iloc[i] * 1.8:
            regimes.iloc[i] = "high_vol"
        elif adx_val > 25 and slope > 0.3 and above_ema50:
            regimes.iloc[i] = "bullish_trend"
        elif adx_val > 25 and slope < -0.3 and not above_ema50:
            regimes.iloc[i] = "bearish_trend"
        elif adx_val < 20:
            regimes.iloc[i] = "range"
        else:
            regimes.iloc[i] = "transition"

    return regimes

def find_regime_shifts(regimes: pd.Series) -> list:
    """Find points where regime changes. Returns list of (index, from_regime, to_regime)."""
    shifts = []
    for i in range(1, len(regimes)):
        if regimes.iloc[i] != regimes.iloc[i-1]:
            # Only count significant shifts (not transition)
            from_r = regimes.iloc[i-1]
            to_r = regimes.iloc[i]
            if from_r != "transition" and to_r != "transition":
                shifts.append((i, from_r, to_r))
    return shifts

# ─── PREDICTOR 1: RSI Divergence ────────────────────────────────────

def analyze_rsi_divergence(df: pd.DataFrame, regimes: pd.Series, shifts: list, symbol: str):
    """When price makes new high but RSI doesn't, how reliably does regime shift follow?"""
    close = df["close"]
    rsi = compute_rsi(close)

    # Find bearish divergences: price higher high, RSI lower high
    lookback = 10  # look back 10 bars for comparison
    divergences = []

    for i in range(lookback + 1, len(df) - 1):
        # Find local price high in last lookback bars
        price_window = close.iloc[i-lookback:i+1]
        rsi_window = rsi.iloc[i-lookback:i+1]

        if close.iloc[i] == price_window.max() and close.iloc[i] > close.iloc[i-lookback]:
            # Price made a new high - check if RSI didn't
            if rsi.iloc[i] < rsi_window.max() * 0.97:  # RSI at least 3% lower
                divergences.append(i)

    # Also find bullish divergences: price lower low, RSI higher low
    bull_divergences = []
    for i in range(lookback + 1, len(df) - 1):
        price_window = close.iloc[i-lookback:i+1]
        rsi_window = rsi.iloc[i-lookback:i+1]

        if close.iloc[i] == price_window.min() and close.iloc[i] < close.iloc[i-lookback]:
            if rsi.iloc[i] > rsi_window.min() * 1.03:
                bull_divergences.append(i)

    # Check: after bearish divergence, does a bearish shift follow within 6h?
    bearish_hits = 0
    bearish_total = 0
    bearish_lags = []

    shift_indices = {s[0]: s for s in shifts}

    for div_idx in divergences:
        bearish_total += 1
        for ahead in range(1, 7):  # look 1-6 bars ahead (1-6 hours)
            check_idx = div_idx + ahead
            if check_idx in shift_indices:
                _, from_r, to_r = shift_indices[check_idx]
                if to_r in ("bearish_trend", "high_vol", "range") and from_r == "bullish_trend":
                    bearish_hits += 1
                    bearish_lags.append(ahead)
                    break

    # Check bullish divergence -> bullish shift
    bullish_hits = 0
    bullish_total = 0
    bullish_lags = []

    for div_idx in bull_divergences:
        bullish_total += 1
        for ahead in range(1, 7):
            check_idx = div_idx + ahead
            if check_idx in shift_indices:
                _, from_r, to_r = shift_indices[check_idx]
                if to_r in ("bullish_trend",) and from_r in ("bearish_trend", "range"):
                    bullish_hits += 1
                    bullish_lags.append(ahead)
                    break

    # Also measure: what happens to price 6h after divergence even without formal regime shift
    price_moves_after_bear_div = []
    for div_idx in divergences:
        if div_idx + 6 < len(df):
            move = (close.iloc[div_idx + 6] - close.iloc[div_idx]) / close.iloc[div_idx] * 100
            price_moves_after_bear_div.append(move)

    price_moves_after_bull_div = []
    for div_idx in bull_divergences:
        if div_idx + 6 < len(df):
            move = (close.iloc[div_idx + 6] - close.iloc[div_idx]) / close.iloc[div_idx] * 100
            price_moves_after_bull_div.append(move)

    print(f"\n{'='*70}")
    print(f"  PREDICTOR 1: RSI Divergence — {symbol}")
    print(f"{'='*70}")
    print(f"  Bearish divergences found: {bearish_total}")
    if bearish_total > 0:
        accuracy = bearish_hits / bearish_total * 100 if bearish_total else 0
        avg_lag = np.mean(bearish_lags) if bearish_lags else 0
        fp_rate = 100 - accuracy
        print(f"  -> Led to regime shift (within 6h): {bearish_hits} ({accuracy:.1f}%)")
        print(f"  -> Average lead time: {avg_lag:.1f} hours")
        print(f"  -> False positive rate: {fp_rate:.1f}%")
        if price_moves_after_bear_div:
            avg_move = np.mean(price_moves_after_bear_div)
            neg_pct = sum(1 for m in price_moves_after_bear_div if m < 0) / len(price_moves_after_bear_div) * 100
            print(f"  -> Avg price move 6h after bearish div: {avg_move:+.2f}%")
            print(f"  -> Price declined in {neg_pct:.0f}% of cases")

    print(f"\n  Bullish divergences found: {bullish_total}")
    if bullish_total > 0:
        accuracy = bullish_hits / bullish_total * 100 if bullish_total else 0
        avg_lag = np.mean(bullish_lags) if bullish_lags else 0
        print(f"  -> Led to regime shift (within 6h): {bullish_hits} ({accuracy:.1f}%)")
        print(f"  -> Average lead time: {avg_lag:.1f} hours")
        if price_moves_after_bull_div:
            avg_move = np.mean(price_moves_after_bull_div)
            pos_pct = sum(1 for m in price_moves_after_bull_div if m > 0) / len(price_moves_after_bull_div) * 100
            print(f"  -> Avg price move 6h after bullish div: {avg_move:+.2f}%")
            print(f"  -> Price rose in {pos_pct:.0f}% of cases")

    return {
        "bearish_divergences": bearish_total,
        "bearish_accuracy": bearish_hits / bearish_total * 100 if bearish_total else 0,
        "bearish_avg_lag": np.mean(bearish_lags) if bearish_lags else 0,
        "bullish_divergences": bullish_total,
        "bullish_accuracy": bullish_hits / bullish_total * 100 if bullish_total else 0,
        "avg_move_after_bear": np.mean(price_moves_after_bear_div) if price_moves_after_bear_div else 0,
        "avg_move_after_bull": np.mean(price_moves_after_bull_div) if price_moves_after_bull_div else 0,
    }

# ─── PREDICTOR 2: Volume Decline in Trend ───────────────────────────

def analyze_volume_decline(df: pd.DataFrame, regimes: pd.Series, shifts: list, symbol: str):
    """When trend continues but volume decreases for 3+ candles, predict reversal."""
    close = df["close"]
    volume = df["volume"]
    vol_ma = volume.rolling(20).mean()

    # Find volume decline streaks during trends
    events = []

    for i in range(25, len(df) - 6):
        regime = regimes.iloc[i]
        if regime not in ("bullish_trend", "bearish_trend"):
            continue

        # Check 3+ consecutive declining volume bars
        declining = True
        streak = 0
        for k in range(3):
            if volume.iloc[i-k] < volume.iloc[i-k-1]:
                streak += 1
            else:
                declining = False
                break

        if declining and streak >= 3:
            # Also check volume is below average
            if volume.iloc[i] < vol_ma.iloc[i] * 0.8:
                events.append((i, regime))

    # Check what happens within 6 hours after
    reversals = 0
    continuation = 0
    lag_to_reversal = []
    price_moves = []

    for idx, regime in events:
        reversed_flag = False
        for ahead in range(1, 7):
            check = idx + ahead
            if check >= len(regimes):
                break
            new_regime = regimes.iloc[check]
            if regime == "bullish_trend" and new_regime in ("bearish_trend", "range", "high_vol"):
                reversals += 1
                lag_to_reversal.append(ahead)
                reversed_flag = True
                break
            elif regime == "bearish_trend" and new_regime in ("bullish_trend", "range"):
                reversals += 1
                lag_to_reversal.append(ahead)
                reversed_flag = True
                break

        if not reversed_flag:
            continuation += 1

        if idx + 6 < len(df):
            move = (close.iloc[idx + 6] - close.iloc[idx]) / close.iloc[idx] * 100
            # For bearish trends, a positive move = reversal
            if regime == "bearish_trend":
                move = -move  # flip so positive = moved against the trend
            price_moves.append(move)

    total = len(events)
    print(f"\n{'='*70}")
    print(f"  PREDICTOR 2: Volume Decline in Trend — {symbol}")
    print(f"{'='*70}")
    print(f"  Volume decline events (3+ bars, during trend): {total}")
    if total > 0:
        rev_pct = reversals / total * 100
        cont_pct = continuation / total * 100
        avg_lag = np.mean(lag_to_reversal) if lag_to_reversal else 0
        print(f"  -> Reversed within 6h: {reversals} ({rev_pct:.1f}%)")
        print(f"  -> Continued trend: {continuation} ({cont_pct:.1f}%)")
        print(f"  -> Average lead time to reversal: {avg_lag:.1f} hours")
        print(f"  -> False positive rate: {cont_pct:.1f}%")
        if price_moves:
            avg_counter = np.mean(price_moves)
            print(f"  -> Avg counter-trend move 6h later: {avg_counter:+.2f}%")

    return {
        "events": total,
        "reversal_rate": reversals / total * 100 if total else 0,
        "avg_lead_time": np.mean(lag_to_reversal) if lag_to_reversal else 0,
        "false_positive_rate": continuation / total * 100 if total else 0,
    }

# ─── PREDICTOR 3: Bollinger Band Width Contraction ──────────────────

def analyze_bb_contraction(df: pd.DataFrame, regimes: pd.Series, shifts: list, symbol: str):
    """BB width drops 20%+ in 5 candles -> predict breakout magnitude."""
    close = df["close"]
    _, _, bb_width = compute_bb(close)

    events = []

    for i in range(25, len(df) - 6):
        if pd.isna(bb_width.iloc[i]) or pd.isna(bb_width.iloc[i-5]):
            continue

        width_change = (bb_width.iloc[i] - bb_width.iloc[i-5]) / bb_width.iloc[i-5] * 100

        if width_change <= -20:  # 20%+ contraction
            events.append((i, width_change))

    # Analyze what follows: next 6h move magnitude + regime shifts
    breakout_moves = []
    regime_shifted = 0
    shift_lags = []

    shift_indices = {s[0]: s for s in shifts}

    for idx, contraction in events:
        # Max absolute move in next 6h
        if idx + 6 < len(df):
            future_prices = close.iloc[idx+1:idx+7]
            max_up = (future_prices.max() - close.iloc[idx]) / close.iloc[idx] * 100
            max_down = (close.iloc[idx] - future_prices.min()) / close.iloc[idx] * 100
            max_move = max(abs(max_up), abs(max_down))
            breakout_moves.append((contraction, max_move, max_up, -max_down))

        # Check regime shift within 6h
        for ahead in range(1, 7):
            check = idx + ahead
            if check in shift_indices:
                regime_shifted += 1
                shift_lags.append(ahead)
                break

    total = len(events)
    print(f"\n{'='*70}")
    print(f"  PREDICTOR 3: BB Width Contraction — {symbol}")
    print(f"{'='*70}")
    print(f"  BB squeeze events (20%+ contraction in 5 bars): {total}")
    if total > 0 and breakout_moves:
        avg_move = np.mean([b[1] for b in breakout_moves])
        max_move = max([b[1] for b in breakout_moves])
        shift_pct = regime_shifted / total * 100
        avg_lag = np.mean(shift_lags) if shift_lags else 0

        # Bin by contraction severity
        mild = [b for b in breakout_moves if b[0] > -30]  # -20 to -30%
        severe = [b for b in breakout_moves if b[0] <= -30]  # > -30%

        print(f"  -> Avg breakout magnitude (6h): {avg_move:.2f}%")
        print(f"  -> Max breakout magnitude: {max_move:.2f}%")
        print(f"  -> Led to regime shift: {regime_shifted} ({shift_pct:.1f}%)")
        print(f"  -> Avg lead time to shift: {avg_lag:.1f} hours")

        if mild:
            print(f"  -> Mild squeeze (-20 to -30%): avg breakout {np.mean([b[1] for b in mild]):.2f}%  (n={len(mild)})")
        if severe:
            print(f"  -> Severe squeeze (>-30%): avg breakout {np.mean([b[1] for b in severe]):.2f}%  (n={len(severe)})")

        # Direction bias
        up_breakouts = sum(1 for b in breakout_moves if b[2] > abs(b[3]))
        print(f"  -> Breakout direction: {up_breakouts}/{total} upward ({up_breakouts/total*100:.0f}%)")

    return {
        "events": total,
        "avg_breakout": np.mean([b[1] for b in breakout_moves]) if breakout_moves else 0,
        "regime_shift_rate": regime_shifted / total * 100 if total else 0,
        "avg_lead_time": np.mean(shift_lags) if shift_lags else 0,
    }

# ─── PREDICTOR 4: Cross-Asset Leading Signals ───────────────────────

def analyze_cross_asset_lead(data: dict, symbol_regimes: dict, symbol: str):
    """Does BTC regime-shift before SOL/HYPE?"""
    btc_regimes = symbol_regimes.get("BTC")
    target_regimes = symbol_regimes.get(symbol)

    if btc_regimes is None or target_regimes is None or symbol == "BTC":
        print(f"\n{'='*70}")
        print(f"  PREDICTOR 4: Cross-Asset Lead — {symbol}")
        print(f"{'='*70}")
        print(f"  (Skipped for BTC — this is the reference asset)")
        return {}

    btc_shifts = find_regime_shifts(btc_regimes)
    target_shifts = find_regime_shifts(target_regimes)

    # For each BTC bearish shift, find if target follows and how many hours later
    lead_lags = []
    btc_leads = 0
    target_leads = 0
    simultaneous = 0

    for btc_idx, btc_from, btc_to in btc_shifts:
        if btc_to not in ("bearish_trend", "range"):
            continue

        # Look for similar shift in target within +/- 12 hours
        best_match = None
        for t_idx, t_from, t_to in target_shifts:
            if t_to in ("bearish_trend", "range") and abs(t_idx - btc_idx) <= 12:
                if best_match is None or abs(t_idx - btc_idx) < abs(best_match - btc_idx):
                    best_match = t_idx

        if best_match is not None:
            lag = best_match - btc_idx  # positive = BTC led
            lead_lags.append(lag)
            if lag > 0:
                btc_leads += 1
            elif lag < 0:
                target_leads += 1
            else:
                simultaneous += 1

    # Same for bullish shifts
    bull_lead_lags = []
    for btc_idx, btc_from, btc_to in btc_shifts:
        if btc_to != "bullish_trend":
            continue

        best_match = None
        for t_idx, t_from, t_to in target_shifts:
            if t_to == "bullish_trend" and abs(t_idx - btc_idx) <= 12:
                if best_match is None or abs(t_idx - btc_idx) < abs(best_match - btc_idx):
                    best_match = t_idx

        if best_match is not None:
            bull_lead_lags.append(best_match - btc_idx)

    total_matched = len(lead_lags)
    print(f"\n{'='*70}")
    print(f"  PREDICTOR 4: Cross-Asset Lead (BTC -> {symbol})")
    print(f"{'='*70}")
    print(f"  BTC bearish shifts: {sum(1 for s in btc_shifts if s[2] in ('bearish_trend','range'))}")
    print(f"  {symbol} bearish shifts: {sum(1 for s in target_shifts if s[2] in ('bearish_trend','range'))}")
    print(f"  Matched pairs (within 12h): {total_matched}")

    if total_matched > 0:
        avg_lag = np.mean(lead_lags)
        print(f"  -> BTC led {symbol}: {btc_leads} times ({btc_leads/total_matched*100:.0f}%)")
        print(f"  -> {symbol} led BTC: {target_leads} times ({target_leads/total_matched*100:.0f}%)")
        print(f"  -> Simultaneous: {simultaneous} ({simultaneous/total_matched*100:.0f}%)")
        print(f"  -> Average lag (positive = BTC leads): {avg_lag:+.1f} hours")
        if lead_lags:
            median_lag = np.median(lead_lags)
            print(f"  -> Median lag: {median_lag:+.1f} hours")

    if bull_lead_lags:
        avg_bull = np.mean(bull_lead_lags)
        print(f"  -> Bullish shifts avg lag: {avg_bull:+.1f} hours")

    return {
        "matched_pairs": total_matched,
        "btc_leads_pct": btc_leads / total_matched * 100 if total_matched else 0,
        "avg_lag_hours": np.mean(lead_lags) if lead_lags else 0,
    }

# ─── PREDICTOR 5: ADX Trajectory ────────────────────────────────────

def analyze_adx_trajectory(df: pd.DataFrame, regimes: pd.Series, shifts: list, symbol: str):
    """ADX rising = trend forming, ADX falling = trend dying. How many bars before reversal?"""
    adx = compute_adx(df)
    close = df["close"]

    # Find ADX peaks (trend dying signal)
    adx_peaks = []
    for i in range(3, len(df) - 1):
        if adx.iloc[i] > 30 and adx.iloc[i] > adx.iloc[i-1] and adx.iloc[i] > adx.iloc[i+1]:  # local max above 30
            adx_peaks.append(i)

    # Find ADX troughs (trend forming signal)
    adx_troughs = []
    for i in range(3, len(df) - 1):
        if adx.iloc[i] < 20 and adx.iloc[i] < adx.iloc[i-1] and adx.iloc[i] < adx.iloc[i+1]:
            adx_troughs.append(i)

    # ADX peak -> how many bars until trend reversal in price?
    peak_to_reversal = []
    peak_shift_hits = 0

    shift_indices_set = set(s[0] for s in shifts)

    for peak_idx in adx_peaks:
        for ahead in range(1, 13):  # look up to 12h
            check = peak_idx + ahead
            if check in shift_indices_set:
                peak_to_reversal.append(ahead)
                peak_shift_hits += 1
                break

    # ADX trough -> how many bars until new trend starts?
    trough_to_trend = []
    trough_hits = 0

    for tr_idx in adx_troughs:
        for ahead in range(1, 13):
            check = tr_idx + ahead
            if check < len(regimes) and regimes.iloc[check] in ("bullish_trend", "bearish_trend"):
                trough_to_trend.append(ahead)
                trough_hits += 1
                break

    # ADX slope as continuous predictor
    adx_slope_5 = adx.diff(5)  # 5-bar ADX change

    # When ADX drops 10+ points in 5 bars, what happens?
    sharp_drops = []
    for i in range(30, len(df) - 6):
        if adx_slope_5.iloc[i] < -10:
            if i + 6 < len(df):
                move = abs((close.iloc[i+6] - close.iloc[i]) / close.iloc[i] * 100)
                sharp_drops.append((i, adx_slope_5.iloc[i], move))

    print(f"\n{'='*70}")
    print(f"  PREDICTOR 5: ADX Trajectory — {symbol}")
    print(f"{'='*70}")
    print(f"  ADX peaks found (>30): {len(adx_peaks)}")
    if adx_peaks:
        accuracy = peak_shift_hits / len(adx_peaks) * 100
        avg_lead = np.mean(peak_to_reversal) if peak_to_reversal else 0
        print(f"  -> Led to regime shift (within 12h): {peak_shift_hits} ({accuracy:.1f}%)")
        print(f"  -> Average lead time: {avg_lead:.1f} hours")
        print(f"  -> False positive rate: {100 - accuracy:.1f}%")

    print(f"\n  ADX troughs found (<20): {len(adx_troughs)}")
    if adx_troughs:
        accuracy = trough_hits / len(adx_troughs) * 100
        avg_lead = np.mean(trough_to_trend) if trough_to_trend else 0
        print(f"  -> New trend started (within 12h): {trough_hits} ({accuracy:.1f}%)")
        print(f"  -> Average lead time to new trend: {avg_lead:.1f} hours")

    if sharp_drops:
        avg_move = np.mean([s[2] for s in sharp_drops])
        print(f"\n  Sharp ADX drops (>10 pts in 5 bars): {len(sharp_drops)}")
        print(f"  -> Avg absolute price move 6h later: {avg_move:.2f}%")

    return {
        "adx_peak_accuracy": peak_shift_hits / len(adx_peaks) * 100 if adx_peaks else 0,
        "adx_peak_lead_time": np.mean(peak_to_reversal) if peak_to_reversal else 0,
        "adx_trough_accuracy": trough_hits / len(adx_troughs) * 100 if adx_troughs else 0,
        "adx_trough_lead_time": np.mean(trough_to_trend) if trough_to_trend else 0,
    }

# ─── PREDICTOR 6: Multi-Indicator Consensus Shift ───────────────────

def analyze_multi_indicator_consensus(df: pd.DataFrame, regimes: pd.Series, shifts: list, symbol: str):
    """When 3+ indicators simultaneously flip, is this a reliable regime change signal?"""
    close = df["close"]
    rsi = compute_rsi(close)
    macd_line, macd_signal, macd_hist = compute_macd(close)
    ema20 = compute_ema(close, 20)
    ema50 = compute_ema(close, 50)
    adx = compute_adx(df)
    _, _, bb_width = compute_bb(close)

    # Track indicator states
    consensus_events = []

    for i in range(52, len(df) - 6):
        # Count bullish flips in this bar
        bullish_flips = 0
        bearish_flips = 0

        # RSI crosses 50
        if rsi.iloc[i-1] < 50 and rsi.iloc[i] >= 50:
            bullish_flips += 1
        if rsi.iloc[i-1] > 50 and rsi.iloc[i] <= 50:
            bearish_flips += 1

        # MACD crosses zero
        if macd_line.iloc[i-1] < 0 and macd_line.iloc[i] >= 0:
            bullish_flips += 1
        if macd_line.iloc[i-1] > 0 and macd_line.iloc[i] <= 0:
            bearish_flips += 1

        # Price crosses EMA20
        if close.iloc[i-1] < ema20.iloc[i-1] and close.iloc[i] >= ema20.iloc[i]:
            bullish_flips += 1
        if close.iloc[i-1] > ema20.iloc[i-1] and close.iloc[i] <= ema20.iloc[i]:
            bearish_flips += 1

        # Price crosses EMA50
        if close.iloc[i-1] < ema50.iloc[i-1] and close.iloc[i] >= ema50.iloc[i]:
            bullish_flips += 1
        if close.iloc[i-1] > ema50.iloc[i-1] and close.iloc[i] <= ema50.iloc[i]:
            bearish_flips += 1

        # MACD histogram sign change
        if macd_hist.iloc[i-1] < 0 and macd_hist.iloc[i] >= 0:
            bullish_flips += 1
        if macd_hist.iloc[i-1] > 0 and macd_hist.iloc[i] <= 0:
            bearish_flips += 1

        if bullish_flips >= 3:
            consensus_events.append((i, "bullish", bullish_flips))
        if bearish_flips >= 3:
            consensus_events.append((i, "bearish", bearish_flips))

    # Analyze outcomes
    correct_shifts = 0
    shift_lags = []
    price_moves = []
    false_positives = 0

    shift_indices = {s[0]: s for s in shifts}

    for idx, direction, n_flips in consensus_events:
        found_shift = False
        for ahead in range(0, 7):  # 0-6h
            check = idx + ahead
            if check in shift_indices:
                _, from_r, to_r = shift_indices[check]
                if direction == "bullish" and to_r == "bullish_trend":
                    correct_shifts += 1
                    shift_lags.append(ahead)
                    found_shift = True
                    break
                elif direction == "bearish" and to_r in ("bearish_trend", "range"):
                    correct_shifts += 1
                    shift_lags.append(ahead)
                    found_shift = True
                    break

        if not found_shift:
            false_positives += 1

        # Price outcome
        if idx + 6 < len(df):
            move = (close.iloc[idx + 6] - close.iloc[idx]) / close.iloc[idx] * 100
            if direction == "bearish":
                move = -move  # positive = moved in predicted direction
            price_moves.append(move)

    total = len(consensus_events)
    print(f"\n{'='*70}")
    print(f"  PREDICTOR 6: Multi-Indicator Consensus — {symbol}")
    print(f"{'='*70}")
    print(f"  Consensus events (3+ indicators flip): {total}")

    bullish_events = sum(1 for e in consensus_events if e[1] == "bullish")
    bearish_events = sum(1 for e in consensus_events if e[1] == "bearish")
    print(f"  -> Bullish consensus: {bullish_events}, Bearish consensus: {bearish_events}")

    if total > 0:
        accuracy = correct_shifts / total * 100
        fp_rate = false_positives / total * 100
        avg_lag = np.mean(shift_lags) if shift_lags else 0
        print(f"  -> Correct regime shift prediction: {correct_shifts} ({accuracy:.1f}%)")
        print(f"  -> False positives: {false_positives} ({fp_rate:.1f}%)")
        print(f"  -> Average lead/lag time: {avg_lag:.1f} hours")

        if price_moves:
            avg_directional = np.mean(price_moves)
            win_rate = sum(1 for m in price_moves if m > 0) / len(price_moves) * 100
            print(f"  -> Avg directional move 6h later: {avg_directional:+.2f}%")
            print(f"  -> Direction correct: {win_rate:.0f}% of the time")

    # Breakdown by strength (3 vs 4 vs 5 flips)
    for n in [3, 4, 5]:
        subset = [e for e in consensus_events if e[2] >= n]
        if subset and len(subset) < total:
            print(f"  -> {n}+ indicators: {len(subset)} events")

    return {
        "events": total,
        "accuracy": correct_shifts / total * 100 if total else 0,
        "false_positive_rate": false_positives / total * 100 if total else 0,
        "avg_lead_time": np.mean(shift_lags) if shift_lags else 0,
        "directional_win_rate": sum(1 for m in price_moves if m > 0) / len(price_moves) * 100 if price_moves else 0,
    }


# ─── MAIN ───────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("  REGIME CHANGE PREDICTION RESEARCH")
    print("  Analyzing 500 1h candles for HYPE, BTC, SOL")
    print("=" * 70)

    fetcher = DataFetcher(fresh=True)

    symbols = {
        "BTC": "bitcoin",
        "SOL": "solana",
        "HYPE": "hyperliquid",
    }

    data = {}
    for sym, coin_id in symbols.items():
        print(f"\nFetching {sym} 1h data (500 candles)...")
        df = fetcher.fetch_ohlcv(sym, coin_id, "1h")
        if df is not None and not df.empty:
            # Take last 500
            df = df.tail(500).reset_index(drop=True)
            data[sym] = df
            print(f"  Got {len(df)} candles for {sym}")
            print(f"  Date range: {df.iloc[0].get('timestamp', 'N/A')} to {df.iloc[-1].get('timestamp', 'N/A')}")
            print(f"  Price range: {df['close'].min():.2f} - {df['close'].max():.2f}")
        else:
            print(f"  FAILED to fetch {sym}")

    if not data:
        print("\nERROR: No data fetched. Exiting.")
        return

    # Classify regimes for each symbol
    symbol_regimes = {}
    all_shifts = {}

    for sym, df in data.items():
        regimes = classify_regimes(df)
        shifts = find_regime_shifts(regimes)
        symbol_regimes[sym] = regimes
        all_shifts[sym] = shifts

        # Print regime summary
        regime_counts = regimes.value_counts()
        print(f"\n  {sym} Regime Distribution:")
        for regime, count in regime_counts.items():
            print(f"    {regime}: {count} bars ({count/len(regimes)*100:.1f}%)")
        print(f"  Total regime shifts: {len(shifts)}")

    # Run all 6 predictors for each symbol
    all_results = {}

    for sym, df in data.items():
        regimes = symbol_regimes[sym]
        shifts = all_shifts[sym]

        results = {}

        # Predictor 1: RSI Divergence
        results["rsi_divergence"] = analyze_rsi_divergence(df, regimes, shifts, sym)

        # Predictor 2: Volume Decline
        results["volume_decline"] = analyze_volume_decline(df, regimes, shifts, sym)

        # Predictor 3: BB Contraction
        results["bb_contraction"] = analyze_bb_contraction(df, regimes, shifts, sym)

        # Predictor 4: Cross-Asset Lead
        results["cross_asset"] = analyze_cross_asset_lead(data, symbol_regimes, sym)

        # Predictor 5: ADX Trajectory
        results["adx_trajectory"] = analyze_adx_trajectory(df, regimes, shifts, sym)

        # Predictor 6: Multi-Indicator Consensus
        results["multi_consensus"] = analyze_multi_indicator_consensus(df, regimes, shifts, sym)

        all_results[sym] = results

    # ─── FINAL RANKING ──────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  FINAL PREDICTOR RANKING (Cross-Symbol Summary)")
    print("=" * 70)

    predictor_scores = {}

    predictors = [
        ("RSI Divergence", lambda r: (
            (r.get("rsi_divergence", {}).get("bearish_accuracy", 0) +
             r.get("rsi_divergence", {}).get("bullish_accuracy", 0)) / 2,
            max(abs(r.get("rsi_divergence", {}).get("avg_move_after_bear", 0)),
                abs(r.get("rsi_divergence", {}).get("avg_move_after_bull", 0))),
        )),
        ("Volume Decline", lambda r: (
            r.get("volume_decline", {}).get("reversal_rate", 0),
            r.get("volume_decline", {}).get("avg_lead_time", 0),
        )),
        ("BB Contraction", lambda r: (
            r.get("bb_contraction", {}).get("regime_shift_rate", 0),
            r.get("bb_contraction", {}).get("avg_breakout", 0),
        )),
        ("ADX Trajectory", lambda r: (
            (r.get("adx_trajectory", {}).get("adx_peak_accuracy", 0) +
             r.get("adx_trajectory", {}).get("adx_trough_accuracy", 0)) / 2,
            (r.get("adx_trajectory", {}).get("adx_peak_lead_time", 0) +
             r.get("adx_trajectory", {}).get("adx_trough_lead_time", 0)) / 2,
        )),
        ("Multi-Indicator", lambda r: (
            r.get("multi_consensus", {}).get("accuracy", 0),
            r.get("multi_consensus", {}).get("directional_win_rate", 0),
        )),
    ]

    for name, scorer in predictors:
        accuracies = []
        secondary = []
        for sym in data.keys():
            if sym in all_results:
                a, s = scorer(all_results[sym])
                accuracies.append(a)
                secondary.append(s)

        avg_accuracy = np.mean(accuracies) if accuracies else 0
        avg_secondary = np.mean(secondary) if secondary else 0
        predictor_scores[name] = (avg_accuracy, avg_secondary)

    # Cross-asset lead (special case - only for non-BTC)
    cross_asset_accs = []
    cross_asset_lags = []
    for sym in ["SOL", "HYPE"]:
        if sym in all_results:
            ca = all_results[sym].get("cross_asset", {})
            if ca.get("btc_leads_pct", 0) > 0:
                cross_asset_accs.append(ca["btc_leads_pct"])
                cross_asset_lags.append(ca.get("avg_lag_hours", 0))

    if cross_asset_accs:
        predictor_scores["Cross-Asset BTC Lead"] = (np.mean(cross_asset_accs), np.mean(cross_asset_lags))

    # Sort by accuracy
    ranked = sorted(predictor_scores.items(), key=lambda x: x[1][0], reverse=True)

    print(f"\n  {'Rank':<6} {'Predictor':<25} {'Accuracy':<15} {'Secondary Metric':<20}")
    print(f"  {'-'*66}")
    for i, (name, (acc, sec)) in enumerate(ranked, 1):
        print(f"  {i:<6} {name:<25} {acc:>8.1f}%      {sec:>8.2f}")

    print(f"\n  RECOMMENDATION:")
    print(f"  Top predictors for integration into anticipatory entry system:")
    for i, (name, (acc, sec)) in enumerate(ranked[:3], 1):
        print(f"  {i}. {name} (accuracy: {acc:.1f}%)")

    print(f"\n  Integration approach:")
    print(f"  - Create a 'regime_prediction_score' (0-100) combining top predictors")
    print(f"  - Feed to Regime Agent as additional context")
    print(f"  - When score > 70, emit early warning to Trade Agent")
    print(f"  - Use cross-asset BTC lead for alt positioning (if BTC lead is confirmed)")


if __name__ == "__main__":
    main()
