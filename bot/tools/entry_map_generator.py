#!/usr/bin/env python3
"""
Aggressive Anticipatory Entry Map Generator
Fetches 500 1h candles, computes all technical levels, ranks entries.
"""

import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from data.fetcher import DataFetcher

# ─── Fetch Data ──────────────────────────────────────────────────

COINGECKO_IDS = {
    "HYPE": "hyperliquid",
    "BTC": "bitcoin",
    "SOL": "solana",
}

def fetch_all():
    fetcher = DataFetcher(fresh=True)
    data = {}
    for sym in ["HYPE", "BTC", "SOL"]:
        print(f"Fetching 1h candles for {sym}...")
        cg_id = COINGECKO_IDS[sym]
        df = fetcher.fetch_ohlcv(sym, cg_id, "1h")
        if df is not None and len(df) > 50:
            data[sym] = df
            print(f"  Got {len(df)} candles, last close: {df['close'].iloc[-1]:.4f}")
        else:
            print(f"  FAILED or insufficient data for {sym}")
    return data

# ─── Technical Indicators ────────────────────────────────────────

def compute_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def compute_bb(series, period=20, std_mult=2.0):
    mid = series.rolling(period).mean()
    std = series.rolling(period).std()
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    return upper, mid, lower

def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def compute_atr(df, period=14):
    h, l, c = df['high'], df['low'], df['close'].shift(1)
    tr = pd.concat([h - l, (h - c).abs(), (l - c).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def compute_vwap(df, lookback=24):
    """Approximate session VWAP from last `lookback` candles."""
    recent = df.tail(lookback)
    if 'volume' not in recent.columns or recent['volume'].sum() == 0:
        return recent['close'].mean()
    tp = (recent['high'] + recent['low'] + recent['close']) / 3
    return (tp * recent['volume']).sum() / recent['volume'].sum()

def find_swing_highs_lows(df, lookback_hours=48):
    """Find swing highs and lows in last N hours."""
    recent = df.tail(lookback_hours)
    highs = []
    lows = []
    for i in range(2, len(recent) - 2):
        h = recent['high'].iloc
        l = recent['low'].iloc
        if h[i] > h[i-1] and h[i] > h[i-2] and h[i] > h[i+1] and h[i] > h[i+2]:
            highs.append(h[i])
        if l[i] < l[i-1] and l[i] < l[i-2] and l[i] < l[i+1] and l[i] < l[i+2]:
            lows.append(l[i])
    return sorted(set(highs), reverse=True), sorted(set(lows))

def compute_fibs(swing_high, swing_low):
    """Fibonacci retracement levels from a swing."""
    diff = swing_high - swing_low
    return {
        "fib_236": swing_high - 0.236 * diff,
        "fib_382": swing_high - 0.382 * diff,
        "fib_500": swing_high - 0.500 * diff,
        "fib_618": swing_high - 0.618 * diff,
        "fib_786": swing_high - 0.786 * diff,
    }

# ─── Round Number Levels ─────────────────────────────────────────

ROUND_LEVELS = {
    "HYPE": [35.0, 37.5, 40.0, 42.5, 45.0, 47.5, 50.0, 30.0, 32.5, 27.5, 25.0, 20.0, 22.5],
    "BTC": [60000, 62000, 63000, 64000, 65000, 66000, 67000, 68000, 69000, 70000,
            72000, 75000, 80000, 85000, 87000, 88000, 89000, 90000, 85000, 84000, 83000, 82000],
    "SOL": [70, 75, 80, 85, 90, 95, 100, 105, 110, 115, 120, 125, 130, 135, 140, 145, 150,
            155, 160, 165, 170, 175, 180],
}

# ─── Entry Map Builder ───────────────────────────────────────────

def build_entry_map(sym, df):
    entries = []
    close = df['close'].iloc[-1]
    atr = compute_atr(df).iloc[-1]
    rsi = compute_rsi(df['close']).iloc[-1]
    atr_pct = atr / close * 100

    ema9 = compute_ema(df['close'], 9).iloc[-1]
    ema20 = compute_ema(df['close'], 20).iloc[-1]
    ema50 = compute_ema(df['close'], 50).iloc[-1]

    bb_upper, bb_mid, bb_lower = compute_bb(df['close'])
    bb_u = bb_upper.iloc[-1]
    bb_m = bb_mid.iloc[-1]
    bb_l = bb_lower.iloc[-1]

    vwap = compute_vwap(df, 24)

    last_24h = df.tail(24)
    session_high = last_24h['high'].max()
    session_low = last_24h['low'].min()

    swing_highs, swing_lows = find_swing_highs_lows(df, 48)

    # Recent swing for fibs
    recent_100 = df.tail(100)
    swing_h = recent_100['high'].max()
    swing_l = recent_100['low'].min()
    fibs = compute_fibs(swing_h, swing_l)

    # Collect ALL key levels for dynamic TP targeting
    all_levels = set()
    all_levels.update([bb_u, bb_m, bb_l, vwap, ema9, ema20, ema50])
    all_levels.update([session_high, session_low])
    all_levels.update(swing_highs[:5])
    all_levels.update(swing_lows[:5])
    all_levels.update(fibs.values())
    for rl in ROUND_LEVELS.get(sym, []):
        if abs(rl - close) / close < 0.15:
            all_levels.add(rl)
    all_levels = sorted(all_levels)

    def dist_pct(level):
        return abs(level - close) / close * 100

    def find_tp_target(level, direction):
        """Find the next key level as TP (dynamic, not fixed ATR multiple)."""
        if direction == "BUY":
            # TP = next resistance above entry
            candidates = [l for l in all_levels if l > level + 0.3 * atr]
            if candidates:
                # Pick the one that gives best R:R (at least 2nd level if close)
                for c in candidates:
                    if (c - level) >= 1.5 * atr:
                        return c
                return candidates[0]  # fallback: nearest
            return level + 3 * atr
        else:
            # TP = next support below entry
            candidates = [l for l in reversed(all_levels) if l < level - 0.3 * atr]
            if candidates:
                for c in candidates:
                    if (level - c) >= 1.5 * atr:
                        return c
                return candidates[0]
            return level - 3 * atr

    def count_confluences(level, direction):
        """Count how many independent technical levels cluster near this price."""
        radius = 0.5 * atr  # Within 0.5 ATR = confluence
        count = 0
        level_sources = []
        checks = [
            (bb_l, "BB_Lower"), (bb_u, "BB_Upper"), (bb_m, "BB_Mid"),
            (ema9, "EMA9"), (ema20, "EMA20"), (ema50, "EMA50"),
            (vwap, "VWAP"), (session_high, "24H_High"), (session_low, "24H_Low"),
        ]
        for fk, fv in fibs.items():
            checks.append((fv, fk))
        for rl in ROUND_LEVELS.get(sym, []):
            if abs(rl - close) / close < 0.15:
                checks.append((rl, f"Round_{rl}"))

        for val, name in checks:
            if abs(val - level) <= radius:
                count += 1
                level_sources.append(name)
        return count, level_sources

    def add_entry(level, direction, source, trigger, base_conf_bonus=0):
        d = dist_pct(level)
        if d > 12:  # Skip levels too far away
            return

        confluences, conf_sources = count_confluences(level, direction)

        # Dynamic SL: 0.8x ATR for tight (high confluence), 1.5x for loose
        sl_mult = max(0.6, 1.5 - 0.15 * confluences)
        if direction == "BUY":
            sl = level - sl_mult * atr
        else:
            sl = level + sl_mult * atr

        tp = find_tp_target(level, direction)

        sl_dist = abs(level - sl)
        tp_dist = abs(tp - level)
        rr = tp_dist / sl_dist if sl_dist > 0 else 0

        if rr < 1.2:  # Minimum R:R filter
            return

        sl_pct = sl_dist / level * 100
        # Leverage: tighter stop = more leverage (capped at 20x)
        raw_lev = min(20, max(3, 2.0 / (sl_pct / 100))) if sl_pct > 0 else 5
        leverage = round(min(20, raw_lev))

        # Confidence scoring
        conf = 30 + base_conf_bonus
        conf += confluences * 12  # Each confluence adds 12
        # RSI alignment
        if direction == "BUY" and rsi < 35:
            conf += 15
        elif direction == "BUY" and rsi < 45:
            conf += 8
        elif direction == "SELL" and rsi > 65:
            conf += 15
        elif direction == "SELL" and rsi > 55:
            conf += 8
        # EMA trend alignment
        if direction == "BUY" and ema9 > ema20:
            conf += 5  # Buying in uptrend
        elif direction == "SELL" and ema9 < ema20:
            conf += 5  # Selling in downtrend
        # Proximity bonus (actionable soon)
        if d < 0.5:
            conf += 10
        elif d < 1.0:
            conf += 5
        conf = min(98, conf)

        # Score = R:R * Confidence, with distance penalty
        # Levels >5% away get heavily penalized (not actionable now)
        dist_penalty = 1.0
        if d > 5:
            dist_penalty = 0.3
        elif d > 3:
            dist_penalty = 0.6
        elif d > 2:
            dist_penalty = 0.8
        elif d > 1:
            dist_penalty = 0.9

        score = rr * (conf / 100) * dist_penalty

        entries.append({
            "symbol": sym,
            "level": round(level, 4),
            "direction": direction,
            "source": source,
            "distance_pct": round(d, 2),
            "trigger": trigger,
            "sl": round(sl, 4),
            "tp": round(tp, 4),
            "rr": round(rr, 2),
            "leverage": leverage,
            "confidence": conf,
            "score": round(score, 2),
            "confluences": confluences,
            "confluence_sources": conf_sources,
            "atr": round(atr, 4),
            "current_price": round(close, 4),
            "rsi": round(rsi, 1),
        })

    # ─── BB Bands ─────────────────────────────────────────────
    add_entry(bb_l, "BUY", "BB_Lower", f"Price touches BB lower + RSI<35 (now {rsi:.0f})", 2)
    add_entry(bb_u, "SELL", "BB_Upper", f"Price touches BB upper + RSI>65 (now {rsi:.0f})", 2)
    add_entry(bb_m, "BUY" if close < bb_m else "SELL", "BB_Mid",
              f"Mean reversion to BB mid from {'below' if close < bb_m else 'above'}", 1)

    # ─── EMAs ─────────────────────────────────────────────────
    for name, val in [("EMA9", ema9), ("EMA20", ema20), ("EMA50", ema50)]:
        conf_count = 1
        # EMA confluence check
        if abs(val - vwap) / close < 0.005:
            conf_count += 1
        if close > val:
            add_entry(val, "BUY", name, f"Pullback to {name} support + bounce candle", conf_count)
        else:
            add_entry(val, "SELL", name, f"Rally to {name} resistance + rejection candle", conf_count)

    # ─── VWAP ─────────────────────────────────────────────────
    vwap_conf = 1
    if abs(vwap - ema20) / close < 0.005:
        vwap_conf += 1
    if close > vwap:
        add_entry(vwap, "BUY", "VWAP", f"Pullback to VWAP support (mean reversion)", vwap_conf)
    else:
        add_entry(vwap, "SELL", "VWAP", f"Rally into VWAP resistance", vwap_conf)

    # ─── Session High/Low ────────────────────────────────────
    add_entry(session_low, "BUY", "Session_Low", "Test of 24h low + bullish engulf", 2)
    add_entry(session_high, "SELL", "Session_High", "Test of 24h high + bearish engulf", 2)

    # ─── Swing S/R ───────────────────────────────────────────
    for h in swing_highs[:3]:
        conf_count = 1
        # Check if near other levels
        for fk, fv in fibs.items():
            if abs(h - fv) / close < 0.005:
                conf_count += 1
                break
        add_entry(h, "SELL", "Swing_High", f"Resistance at swing high, watch for rejection", conf_count)
    for l in swing_lows[:3]:
        conf_count = 1
        for fk, fv in fibs.items():
            if abs(l - fv) / close < 0.005:
                conf_count += 1
                break
        add_entry(l, "BUY", "Swing_Low", f"Support at swing low, watch for bounce", conf_count)

    # ─── Round Numbers ───────────────────────────────────────
    for rl in ROUND_LEVELS.get(sym, []):
        if dist_pct(rl) > 15:
            continue
        conf_count = 1
        # Confluence with other levels
        for fk, fv in fibs.items():
            if abs(rl - fv) / close < 0.005:
                conf_count += 1
                break
        if abs(rl - ema50) / close < 0.01:
            conf_count += 1
        direction = "BUY" if rl < close else "SELL"
        add_entry(rl, direction, "Round_Number", f"Psychological level ${rl}", conf_count)

    # ─── Fibonacci ───────────────────────────────────────────
    for fname, fval in fibs.items():
        conf_count = 1
        # Check confluence with EMAs
        for ema_val in [ema9, ema20, ema50]:
            if abs(fval - ema_val) / close < 0.005:
                conf_count += 1
                break
        if abs(fval - vwap) / close < 0.005:
            conf_count += 1
        direction = "BUY" if fval < close else "SELL"
        pct_name = fname.split("_")[1]
        add_entry(fval, direction, f"Fib_{pct_name}",
                  f"Fib {pct_name}% retracement (swing {swing_l:.1f}-{swing_h:.1f})", conf_count)

    return entries

# ─── Main ────────────────────────────────────────────────────────

def main():
    data = fetch_all()
    if not data:
        print("FATAL: No data fetched")
        return

    all_entries = []
    for sym, df in data.items():
        print(f"\n{'='*60}")
        print(f"  {sym} Analysis — {len(df)} candles")
        print(f"{'='*60}")
        print(f"  Current: ${df['close'].iloc[-1]:.4f}")
        print(f"  ATR(14): ${compute_atr(df).iloc[-1]:.4f}")
        print(f"  RSI(14): {compute_rsi(df['close']).iloc[-1]:.1f}")

        entries = build_entry_map(sym, df)
        all_entries.extend(entries)

    # Sort by score (R:R * confidence)
    all_entries.sort(key=lambda x: x['score'], reverse=True)

    # Print table
    print(f"\n{'='*120}")
    print(f"  RANKED ENTRY MAP — ALL ASSETS (sorted by Score = R:R * Confidence)")
    print(f"{'='*120}")
    print(f"{'Rank':>4} {'Sym':>5} {'Dir':>5} {'Level':>12} {'Dist%':>6} {'Source':>14} "
          f"{'SL':>12} {'TP':>12} {'R:R':>5} {'Lev':>4} {'Conf':>5} {'Score':>6} {'RSI':>5}")
    print("-" * 120)

    for i, e in enumerate(all_entries):
        rank = i + 1
        marker = " <<<" if rank <= 3 else ""
        print(f"{rank:>4} {e['symbol']:>5} {e['direction']:>5} "
              f"${e['level']:>11.4f} {e['distance_pct']:>5.1f}% {e['source']:>14} "
              f"${e['sl']:>11.4f} ${e['tp']:>11.4f} {e['rr']:>5.2f} {e['leverage']:>3}x "
              f"{e['confidence']:>4}% {e['score']:>5.2f} {e['rsi']:>5.1f}{marker}")

    # Top 3 active entries
    top3 = all_entries[:3]
    print(f"\n{'='*80}")
    print(f"  TOP 3 ACTIVE ANTICIPATORY ENTRIES")
    print(f"{'='*80}")
    for i, e in enumerate(top3):
        print(f"\n  #{i+1} — {e['symbol']} {e['direction']} @ ${e['level']:.4f}")
        print(f"     Source: {e['source']}")
        print(f"     Trigger: {e['trigger']}")
        print(f"     SL: ${e['sl']:.4f} | TP: ${e['tp']:.4f} | R:R: {e['rr']:.2f}")
        print(f"     Leverage: {e['leverage']}x | Confidence: {e['confidence']}%")
        print(f"     Distance from current (${e['current_price']:.4f}): {e['distance_pct']:.1f}%")
        print(f"     Current RSI: {e['rsi']:.1f}")

    # Save to JSON
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            sym: {
                "price": round(data[sym]['close'].iloc[-1], 4),
                "atr": round(compute_atr(data[sym]).iloc[-1], 4),
                "rsi": round(compute_rsi(data[sym]['close']).iloc[-1], 1),
            } for sym in data
        },
        "top_3_active": top3,
        "all_entries": all_entries,
    }

    out_path = os.path.join(os.path.dirname(__file__), "..", "data", "manual", "entry_map.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nSaved to {os.path.abspath(out_path)}")

if __name__ == "__main__":
    main()
