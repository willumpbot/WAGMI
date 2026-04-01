"""
Live Edge Monitor — Continuous market intelligence without LLM costs.

Checks current market conditions against our proven edge patterns and reports:
1. Current position status and expected outcome
2. Upcoming opportunities based on BTC lead-lag
3. Strategy signal readiness (what's about to fire?)
4. Regime assessment and time-of-day edge
5. Sim performance tracking

Run:
    cd bot && python -m tools.live_edge_monitor          # One-shot scan
    cd bot && python -m tools.live_edge_monitor --loop    # Continuous (every 5 min)
"""
import json
import os
import sys
import time
import argparse
import numpy as np
import pandas as pd
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def scan_market():
    """Full market scan with edge assessment."""
    from data.fetcher import DataFetcher

    fetcher = DataFetcher()
    lines = []
    now = datetime.now(timezone.utc)
    hour = now.hour

    lines.append(f"\n{'=' * 60}")
    lines.append(f"  LIVE EDGE MONITOR — {now.strftime('%H:%M UTC %Y-%m-%d')}")
    is_prime = hour >= 18 or hour < 6
    lines.append(f"  Session: {'PRIME HOURS (18-06 UTC)' if is_prime else 'WEAK HOURS (06-18 UTC)'}")
    lines.append(f"{'=' * 60}")

    # ── Current prices and momentum ──
    symbols = {"HYPE": "hyperliquid", "BTC": "bitcoin", "SOL": "solana"}
    prices = {}
    momentum = {}

    for sym, coin_id in symbols.items():
        df = fetcher.fetch_ohlcv(sym, coin_id, "1h")
        if df is None or df.empty:
            continue
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.sort_values("time").reset_index(drop=True)

        price = df["close"].iloc[-1]
        prices[sym] = price
        sma20 = df["close"].tail(20).mean()
        ret_1h = (df["close"].iloc[-1] - df["close"].iloc[-2]) / df["close"].iloc[-2] * 100
        ret_3h = (df["close"].iloc[-1] - df["close"].iloc[-4]) / df["close"].iloc[-4] * 100

        # RSI
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        rsi = (100 - (100 / (1 + rs))).iloc[-1]

        trend = "UP" if price > sma20 else "DOWN"
        momentum[sym] = {"ret_1h": ret_1h, "ret_3h": ret_3h, "rsi": rsi, "trend": trend}

        lines.append(f"\n  {sym}: ${price:.4f}  {ret_1h:+.2f}% 1h  {ret_3h:+.2f}% 3h  RSI={rsi:.0f}  {trend}")

    # ── BTC Lead-Lag Signal ──
    btc_ret = momentum.get("BTC", {}).get("ret_1h", 0)
    lines.append(f"\n  --- BTC LEAD-LAG ---")
    if abs(btc_ret) >= 0.8:
        direction = "UP" if btc_ret > 0 else "DOWN"
        lines.append(f"  ** BTC moved {btc_ret:+.2f}% — HYPE likely follows {direction} (77% accuracy) **")
        lines.append(f"  ** This is a SWING entry trigger (2.5% SL, 3.75% TP, 6x) **")
    elif abs(btc_ret) >= 0.5:
        direction = "UP" if btc_ret > 0 else "DOWN"
        lines.append(f"  BTC moved {btc_ret:+.2f}% — HYPE {direction} signal (73% accuracy, weaker)")
    else:
        lines.append(f"  BTC moved {btc_ret:+.2f}% — No lead-lag signal (need >0.5%)")

    # ── Entry Quality Assessment ──
    lines.append(f"\n  --- ENTRY QUALITY ---")
    hype_data = momentum.get("HYPE", {})
    if hype_data:
        score = 0
        reasons = []
        if hype_data["trend"] == "UP":
            score += 1
            reasons.append("above SMA20")
        rsi = hype_data["rsi"]
        if 35 <= rsi <= 65:
            score += 1
            reasons.append(f"RSI={rsi:.0f} in sweet spot")
        elif rsi > 65:
            reasons.append(f"RSI={rsi:.0f} getting overbought")
        if is_prime:
            score += 1
            reasons.append("prime hours")
        if btc_ret > 0.3:
            score += 1
            reasons.append("BTC positive")

        quality = "HIGH" if score >= 3 else "MEDIUM" if score >= 2 else "LOW"
        lines.append(f"  HYPE_BUY quality: {quality} ({score}/4 conditions)")
        lines.append(f"  Conditions: {', '.join(reasons)}")

    # ── Sim Status ──
    sim_path = os.path.join("data", "manual", "sim_status.json")
    if os.path.exists(sim_path):
        with open(sim_path, encoding="utf-8") as f:
            sim = json.load(f)
        lines.append(f"\n  --- SIM STATUS ---")
        lines.append(f"  Equity: ${sim.get('current_equity', 100):.2f} ({sim.get('total_trades', 0)} trades, "
                     f"{sim.get('wins', 0)}W/{sim.get('losses', 0)}L)")

        for p in sim.get("open_positions", []):
            entry = p.get("entry", 0)
            current = prices.get(p.get("symbol", ""), 0)
            if entry and current:
                pnl_pct = (current - entry) / entry * 100 if p.get("side") == "BUY" else (entry - current) / entry * 100
                sl = p.get("sl", 0)
                tp = p.get("tp_scalp", 0)
                sl_dist = abs(current - sl) / current * 100 if sl else 0
                tp_dist = abs(tp - current) / current * 100 if tp else 0
                status = "WINNING" if pnl_pct > 0 else "LOSING"
                lines.append(f"  Open: {p['symbol']} {p.get('side','')} @ ${entry:.2f} "
                            f"now ${current:.2f} ({pnl_pct:+.1f}%) {status}")
                lines.append(f"    SL ${sl:.2f} ({sl_dist:.1f}% away) | TP ${tp:.2f} ({tp_dist:.1f}% away)")

    # ── Mean Reversion Intelligence ──
    hype_df_for_streak = None
    try:
        hype_df_raw = fetcher.fetch_ohlcv("HYPE", "hyperliquid", "1h")
        if hype_df_raw is not None and len(hype_df_raw) > 5:
            hype_df_for_streak = hype_df_raw
            red_streak = 0
            for i in range(len(hype_df_raw) - 1, max(len(hype_df_raw) - 10, -1), -1):
                row = hype_df_raw.iloc[i]
                if row["close"] < row["open"]:
                    red_streak += 1
                else:
                    break
            if red_streak >= 3:
                lines.append(f"\n  --- MEAN REVERSION ---")
                lines.append(f"  ** {red_streak} consecutive red 1h candles **")
                lines.append(f"  Data: 79% bounce in 6h (avg +1.17%) after 3+ red candles")
                lines.append(f"  Favors HOLD on existing longs, potential entry on bounce confirmation")
    except Exception:
        pass

    # ── BTC Risk Levels (for open HYPE positions) ──
    open_positions = []
    if os.path.exists(sim_path):
        with open(sim_path, encoding="utf-8") as f2:
            sim2 = json.load(f2)
        open_positions = sim2.get("open_positions", [])
    hype_longs = [p for p in open_positions if p.get("symbol") == "HYPE" and p.get("side") == "BUY"]
    if hype_longs and "BTC" in prices:
        sl = hype_longs[0].get("sl", 0)
        hype_price = prices.get("HYPE", 0)
        btc_price = prices.get("BTC", 0)
        if sl and hype_price and btc_price:
            # Beta: HYPE moves 0.84x per 1% BTC
            hype_pct_to_sl = (sl - hype_price) / hype_price * 100
            btc_pct_to_trigger = hype_pct_to_sl / 0.84
            btc_danger = btc_price * (1 + btc_pct_to_trigger / 100)
            lines.append(f"\n  --- BTC DANGER LEVEL ---")
            lines.append(f"  BTC < ${btc_danger:,.0f} ({btc_pct_to_trigger:+.1f}%) could push HYPE to SL")
            lines.append(f"  BTC currently ${btc_price:,.0f} — {abs(btc_pct_to_trigger):.1f}% buffer")

    # ── What to Watch ──
    lines.append(f"\n  --- WATCH FOR ---")
    if abs(btc_ret) >= 0.5:
        lines.append(f"  - HYPE follow-through in next 1-3 hours")
    else:
        lines.append(f"  - BTC breakout (>0.5% hourly move) for HYPE entry trigger")

    hype_rsi = momentum.get("HYPE", {}).get("rsi", 50)
    if hype_rsi < 35:
        lines.append(f"  - HYPE oversold (RSI {hype_rsi:.0f}) — bounce possible but WR is only 50%")
    elif hype_rsi > 65:
        lines.append(f"  - HYPE getting hot (RSI {hype_rsi:.0f}) — be cautious on new longs")

    sol_rsi = momentum.get("SOL", {}).get("rsi", 50)
    if sol_rsi > 65:
        lines.append(f"  - SOL overbought (RSI {sol_rsi:.0f}) — but SOL_SELL edge is marginal")

    lines.append(f"{'=' * 60}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true", help="Continuous monitoring every 5 min")
    args = parser.parse_args()

    if args.loop:
        print("Starting continuous monitoring (Ctrl+C to stop)...")
        while True:
            try:
                output = scan_market()
                print(output)
                # Save latest scan
                with open(os.path.join("data", "manual", "latest_scan.txt"), "w", encoding="utf-8") as f:
                    f.write(output)
                time.sleep(300)  # 5 minutes
            except KeyboardInterrupt:
                print("\nStopped.")
                break
            except Exception as e:
                print(f"Error: {e}")
                time.sleep(60)
    else:
        print(scan_market())


if __name__ == "__main__":
    main()
