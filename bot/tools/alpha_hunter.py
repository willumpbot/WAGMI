"""
Alpha Hunter — Continuous multi-angle signal scanner with quant intelligence.

Runs as a loop, scanning all symbols across all angles:
- Strategy signals (ensemble + solo)
- Mean reversion setups (red streaks, RSI extremes)
- Vol compression / breakout detection
- BTC lead-lag
- Relative strength analysis
- Position management (SL/TP tracking)

Outputs actionable signals with full agent pipeline simulation.
"""
import os
import sys
import json
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.fetcher import DataFetcher
import pandas as pd
import numpy as np

# ─── Config ──────────────────────────────────────────────────────
SYMBOLS = {"HYPE": "hyperliquid", "BTC": "bitcoin", "SOL": "solana", "DOGE": "dogecoin"}
SCAN_INTERVAL = 120  # seconds between scans
SIM_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "manual", "sim_status.json")

# Proven edge data
EDGE_DATA = {
    "HYPE_BUY": {"wr": 0.58, "pf": 1.61, "grade": "A+"},
    "SOL_SELL": {"wr": 0.47, "pf": 0.82, "grade": "B"},
    "BTC_BUY":  {"wr": 0.56, "pf": 1.40, "grade": "B+"},
}
TOXIC_SETUPS = {"HYPE_SELL", "BTC_SELL", "SOL_BUY", "DOGE_BUY", "DOGE_SELL"}


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add all indicators to a dataframe."""
    close = df["close"]
    df["ema20"] = close.ewm(span=20).mean()
    df["ema50"] = close.ewm(span=50).mean()

    # RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss_s = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss_s.replace(0, 1e-12)
    df["rsi"] = 100 - (100 / (1 + rs))

    # ATR
    prev = close.shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev).abs(),
        (df["low"] - prev).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14, min_periods=1).mean()

    # Bollinger Bands
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    df["bb_upper"] = sma20 + 2 * std20
    df["bb_lower"] = sma20 - 2 * std20
    df["bb_width"] = (2 * std20 / sma20) * 100
    df["bb_width_avg"] = df["bb_width"].rolling(20).mean()

    # Red streak
    df["red"] = df["close"] < df["open"]
    return df


def count_red_streak(df: pd.DataFrame) -> int:
    streak = 0
    for i in range(len(df) - 1, max(len(df) - 15, -1), -1):
        if df.iloc[i]["close"] < df.iloc[i]["open"]:
            streak += 1
        else:
            break
    return streak


def get_sim_positions():
    """Load current sim positions."""
    if not os.path.exists(SIM_PATH):
        return [], 100.0
    with open(SIM_PATH, encoding="utf-8") as f:
        sim = json.load(f)
    return sim.get("open_positions", []), sim.get("current_equity", 100.0)


def regime_agent(sym: str, df: pd.DataFrame) -> dict:
    """Rule-based regime classification."""
    rsi = df["rsi"].iloc[-1]
    ema20 = df["ema20"].iloc[-1]
    ema50 = df["ema50"].iloc[-1]
    c = df["close"].iloc[-1]
    red_streak = count_red_streak(df)
    bb_squeeze = df["bb_width"].iloc[-1] < df["bb_width_avg"].iloc[-1] * 0.75

    regime = "neutral"
    if rsi < 20:
        regime = "panic_oversold"
    elif rsi < 30:
        regime = "oversold"
    elif rsi < 40:
        regime = "recovering"
    elif rsi > 80:
        regime = "overbought"
    elif rsi > 70:
        regime = "hot"

    trend = "bull" if ema20 > ema50 else "bear"
    price_pos = "above_ema" if c > ema20 else "below_ema"

    return {
        "regime": regime, "trend": trend, "price_pos": price_pos,
        "rsi": rsi, "red_streak": red_streak, "bb_squeeze": bb_squeeze,
    }


def trade_agent(sym: str, regime: dict, df: pd.DataFrame) -> dict:
    """Rule-based trade thesis."""
    rsi = regime["rsi"]
    red_streak = regime["red_streak"]
    setup = f"{sym}_BUY"
    edge = EDGE_DATA.get(setup, {})
    c = df["close"].iloc[-1]
    atr = df["atr"].iloc[-1]

    opportunities = []

    # Mean reversion (our best alpha)
    if red_streak >= 3 and rsi >= 28 and rsi <= 45:
        bounce_prob = min(0.79 + (red_streak - 3) * 0.03, 0.90)
        opportunities.append({
            "type": "mean_reversion",
            "sym": sym, "side": "BUY",
            "thesis": f"{red_streak} red candles, RSI {rsi:.0f} — {bounce_prob:.0%} bounce probability",
            "strength": bounce_prob,
            "entry": c,
            "sl": c - 2.0 * atr,
            "tp1": df["ema20"].iloc[-1],  # Bounce to EMA20
            "tp2": c + 2.5 * atr,
        })

    # Extreme oversold bounce (RSI < 20)
    if rsi < 20 and regime["regime"] == "panic_oversold":
        opportunities.append({
            "type": "extreme_oversold",
            "sym": sym, "side": "BUY",
            "thesis": f"RSI {rsi:.0f} is extreme — massive snap-back likely",
            "strength": 0.70,
            "entry": c,
            "sl": c - 2.5 * atr,
            "tp1": df["ema20"].iloc[-1],
            "tp2": c + 3.0 * atr,
        })

    # Vol squeeze breakout
    if regime["bb_squeeze"]:
        direction = "BUY" if regime["trend"] == "bull" else "SELL"
        opportunities.append({
            "type": "vol_squeeze",
            "sym": sym, "side": direction,
            "thesis": f"BB squeeze detected — breakout {direction} expected",
            "strength": 0.65,
            "entry": c,
            "sl": c - 1.5 * atr if direction == "BUY" else c + 1.5 * atr,
            "tp1": c + 2.0 * atr if direction == "BUY" else c - 2.0 * atr,
            "tp2": c + 3.0 * atr if direction == "BUY" else c - 3.0 * atr,
        })

    return {"opportunities": opportunities}


def critic_agent(opportunities: list, positions: list) -> list:
    """Rule-based veto logic."""
    approved = []
    for opp in opportunities:
        setup_key = f"{opp['sym']}_{opp['side']}"

        # Toxic setup veto
        if setup_key in TOXIC_SETUPS:
            continue

        # RSI extreme veto for buys when still crashing
        if opp["side"] == "BUY" and opp.get("strength", 0) < 0.50:
            continue

        # Already have position in same symbol
        same_sym = [p for p in positions if p.get("symbol") == opp["sym"]]
        if same_sym:
            continue  # Don't stack

        # R:R floor
        sl_pct = abs(opp["entry"] - opp["sl"]) / opp["entry"]
        tp_pct = abs(opp["tp1"] - opp["entry"]) / opp["entry"]
        if sl_pct > 0 and tp_pct / sl_pct < 1.2:
            continue  # R:R too thin

        approved.append(opp)

    return approved


def format_opportunity(opp: dict) -> str:
    """Format an opportunity for display."""
    sl_pct = abs(opp["entry"] - opp["sl"]) / opp["entry"] * 100
    tp_pct = abs(opp["tp1"] - opp["entry"]) / opp["entry"] * 100
    rr = tp_pct / sl_pct if sl_pct > 0 else 0

    lines = [
        f"  ** {opp['type'].upper()} | {opp['sym']} {opp['side']} **",
        f"     Thesis: {opp['thesis']}",
        f"     Strength: {opp['strength']:.0%}",
        f"     Entry: ${opp['entry']:.4f}  SL: ${opp['sl']:.4f} ({sl_pct:.1f}%)  TP: ${opp['tp1']:.4f} ({tp_pct:.1f}%)",
        f"     R:R = {rr:.1f}:1",
    ]
    return "\n".join(lines)


def format_position(pos: dict, current_price: float) -> str:
    """Format position status."""
    entry = pos.get("entry", 0)
    sl = pos.get("sl", 0)
    tp = pos.get("tp_scalp", pos.get("tp1", 0))
    pnl_pct = (current_price - entry) / entry * 100 if pos.get("side") == "BUY" else (entry - current_price) / entry * 100
    sl_dist = abs(current_price - sl) / current_price * 100
    tp_dist = abs(tp - current_price) / current_price * 100
    status = "WINNING" if pnl_pct > 0 else "LOSING"

    return (
        f"  {pos['symbol']} {pos['side']} @ ${entry:.4f} | now ${current_price:.4f} ({pnl_pct:+.2f}%) {status}\n"
        f"    SL ${sl:.4f} ({sl_dist:.1f}% away) | TP ${tp:.4f} ({tp_dist:.1f}% away)"
    )


def run_scan(fetcher: DataFetcher) -> None:
    """Single scan cycle."""
    now = datetime.now(timezone.utc)
    session = "PRIME" if (now.hour >= 18 or now.hour < 6) else "WEAK"

    print(f"\n{'=' * 65}")
    print(f"  ALPHA HUNTER | {now.strftime('%H:%M:%S')} UTC | {session} SESSION")
    print(f"{'=' * 65}")

    # Load positions
    positions, equity = get_sim_positions()

    # Collect all data
    market_data = {}
    for sym, coin_id in SYMBOLS.items():
        df = fetcher.fetch_ohlcv(sym, coin_id, "1h")
        if df is not None and not df.empty:
            df = compute_indicators(df)
            market_data[sym] = df

    if not market_data:
        print("  No market data available")
        return

    # Relative strength analysis
    returns = {}
    for sym, df in market_data.items():
        ret_3h = (df["close"].iloc[-1] - df["close"].iloc[-4]) / df["close"].iloc[-4] * 100 if len(df) > 3 else 0
        returns[sym] = ret_3h

    btc_ret = returns.get("BTC", 0)
    print(f"\n  RELATIVE STRENGTH (3h):")
    for sym in sorted(returns, key=lambda x: returns[x], reverse=True):
        alpha = returns[sym] - btc_ret if sym != "BTC" else 0
        tag = f" (alpha: {alpha:+.2f}%)" if sym != "BTC" else ""
        print(f"    {sym}: {returns[sym]:+.2f}%{tag}")

    # Run agents per symbol
    all_opportunities = []
    for sym, df in market_data.items():
        regime = regime_agent(sym, df)
        c = df["close"].iloc[-1]
        rsi = regime["rsi"]

        # Compact status line
        tags = []
        if regime["red_streak"] >= 3:
            tags.append(f"{regime['red_streak']}R")
        if regime["bb_squeeze"]:
            tags.append("SQZ")
        if rsi < 20:
            tags.append("EXTREME_OS")
        elif rsi < 35:
            tags.append("OS")
        elif rsi > 75:
            tags.append("OB")
        tag_str = " [" + " ".join(tags) + "]" if tags else ""

        print(f"\n  {sym}: ${c:.4f} | RSI={rsi:.0f} | {regime['regime']} | {regime['trend']}{tag_str}")

        # Trade agent
        trades = trade_agent(sym, regime, df)
        all_opportunities.extend(trades["opportunities"])

    # Critic veto
    approved = critic_agent(all_opportunities, positions)

    # Display positions
    if positions:
        print(f"\n  --- OPEN POSITIONS (equity: ${equity:.2f}) ---")
        for p in positions:
            sym = p.get("symbol", "")
            if sym in market_data:
                cp = market_data[sym]["close"].iloc[-1]
                print(format_position(p, cp))

                # BTC danger level for HYPE longs
                if sym == "HYPE" and p.get("side") == "BUY" and "BTC" in market_data:
                    sl = p.get("sl", 0)
                    hype_pct_to_sl = (sl - cp) / cp * 100
                    btc_price = market_data["BTC"]["close"].iloc[-1]
                    btc_danger = btc_price * (1 + hype_pct_to_sl / 0.84 / 100)
                    btc_buffer = (btc_price - btc_danger) / btc_price * 100
                    print(f"    BTC danger: <${btc_danger:,.0f} ({btc_buffer:.1f}% buffer)")

    # Display opportunities
    if approved:
        print(f"\n  --- OPPORTUNITIES ({len(approved)} approved) ---")
        for opp in approved:
            print(format_opportunity(opp))
    else:
        raw_count = len(all_opportunities)
        if raw_count > 0:
            print(f"\n  --- No opportunities (Critic vetoed {raw_count} raw signals) ---")
        else:
            print(f"\n  --- No opportunities detected ---")

    # Pending entries proximity
    try:
        from tools.level_tracker import get_pending_entries_section
        current_prices = {sym: df["close"].iloc[-1] for sym, df in market_data.items()}
        pending_section = get_pending_entries_section(prices=current_prices)
        if pending_section:
            print(pending_section)
    except Exception as e:
        pass  # Don't break alpha_hunter if level_tracker has issues

    # BTC lead-lag
    if "BTC" in market_data:
        btc_1h = returns.get("BTC", 0)
        if abs(btc_1h) > 0.5:
            direction = "UP" if btc_1h > 0 else "DOWN"
            print(f"\n  BTC LEAD-LAG: BTC moved {btc_1h:+.2f}% -> expect alts {direction} (73% accuracy)")

    print(f"\n{'=' * 65}")


def main():
    fetcher = DataFetcher()

    # Single scan or loop
    if "--loop" in sys.argv:
        print(f"Starting alpha hunter loop (every {SCAN_INTERVAL}s)")
        while True:
            try:
                run_scan(fetcher)
                time.sleep(SCAN_INTERVAL)
            except KeyboardInterrupt:
                print("\nAlpha hunter stopped.")
                break
            except Exception as e:
                print(f"  Error: {e}")
                time.sleep(30)
    else:
        run_scan(fetcher)


if __name__ == "__main__":
    main()
