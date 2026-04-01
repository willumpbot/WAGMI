#!/usr/bin/env python3
"""
High-Leverage Precision Trading Analysis
=========================================
Core insight: precision entry = tight stop = high leverage at SAME dollar risk.
A 0.5% stop at 20x = same $risk as a 2.5% stop at 4x, but 5x more upside.

Analysis:
1. Minimum viable stop widths by asset (noise floor)
2. Leverage-adjusted returns at different stop widths
3. 5m vs 1h entry precision advantage
4. Maximum safe leverage by setup quality
5. Risk of ruin Monte Carlo at each leverage level
"""

import sys
import os
import time
import numpy as np
import pandas as pd

# Add bot to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.fetcher import DataFetcher

# ──────────────────────────────────────────────────────────────────────
# FETCH DATA
# ──────────────────────────────────────────────────────────────────────

SYMBOLS = {
    "HYPE": "hyperliquid",
    "BTC": "bitcoin",
    "SOL": "solana",
}

def fetch_data():
    """Fetch 500 1h candles and 500 5m candles for each asset."""
    fetcher = DataFetcher()
    data = {}
    for sym, cg_id in SYMBOLS.items():
        print(f"\n[FETCH] {sym} 1h candles...")
        df_1h = fetcher.fetch_ohlcv(sym, cg_id, "1h")
        print(f"  -> got {len(df_1h)} 1h candles")

        print(f"[FETCH] {sym} 5m candles...")
        df_5m = fetcher.fetch_ohlcv(sym, cg_id, "5m")
        print(f"  -> got {len(df_5m)} 5m candles")

        data[sym] = {"1h": df_1h, "5m": df_5m}
    return data


# ──────────────────────────────────────────────────────────────────────
# 1. NOISE FLOOR ANALYSIS: Minimum viable stop widths
# ──────────────────────────────────────────────────────────────────────

def analyze_noise_floor(data):
    """
    For BUY entries: what % does price dip below close? (low - close) / close
    For SELL entries: what % does price spike above close? (high - close) / close

    The median/P75/P90 of these "wicks" is the noise floor.
    Any stop tighter than this gets stopped out by random noise.
    """
    print("\n" + "=" * 80)
    print("1. NOISE FLOOR ANALYSIS — Minimum Viable Stop Widths")
    print("=" * 80)

    results = {}

    for sym, dfs in data.items():
        df = dfs["1h"].copy()
        if df.empty:
            print(f"  {sym}: NO DATA")
            continue

        # BUY noise: how far below close does the candle wick?
        # Use (close - low) / close as the downward wick %
        buy_noise = ((df["close"] - df["low"]) / df["close"]).abs() * 100

        # SELL noise: how far above close does the candle wick?
        sell_noise = ((df["high"] - df["close"]) / df["close"]).abs() * 100

        # Also compute bar-to-bar adverse moves (consecutive candles)
        # This captures multi-candle noise before reverting
        close = df["close"].values
        adverse_buy_1bar = np.array([max(0, (close[i] - min(df["low"].values[i], df["low"].values[i+1])) / close[i])
                                      for i in range(len(close)-1)]) * 100
        adverse_sell_1bar = np.array([max(0, (max(df["high"].values[i], df["high"].values[i+1]) - close[i]) / close[i])
                                       for i in range(len(close)-1)]) * 100

        # ATR% for context
        atr_14 = df["high"].rolling(14).max() - df["low"].rolling(14).min()
        atr_pct = (atr_14 / df["close"] * 100).dropna()

        stats = {
            "buy_noise_median": np.median(buy_noise),
            "buy_noise_p75": np.percentile(buy_noise, 75),
            "buy_noise_p90": np.percentile(buy_noise, 90),
            "buy_noise_p95": np.percentile(buy_noise, 95),
            "sell_noise_median": np.median(sell_noise),
            "sell_noise_p75": np.percentile(sell_noise, 75),
            "sell_noise_p90": np.percentile(sell_noise, 90),
            "sell_noise_p95": np.percentile(sell_noise, 95),
            "2bar_buy_p75": np.percentile(adverse_buy_1bar, 75),
            "2bar_buy_p90": np.percentile(adverse_buy_1bar, 90),
            "2bar_sell_p75": np.percentile(adverse_sell_1bar, 75),
            "2bar_sell_p90": np.percentile(adverse_sell_1bar, 90),
            "avg_atr_pct": atr_pct.mean() if len(atr_pct) > 0 else 0,
        }
        results[sym] = stats

        print(f"\n  {sym} (1h candles, n={len(df)}):")
        print(f"    BUY noise (close-to-low wick):")
        print(f"      Median: {stats['buy_noise_median']:.3f}%")
        print(f"      P75:    {stats['buy_noise_p75']:.3f}%")
        print(f"      P90:    {stats['buy_noise_p90']:.3f}%")
        print(f"      P95:    {stats['buy_noise_p95']:.3f}%")
        print(f"    SELL noise (close-to-high wick):")
        print(f"      Median: {stats['sell_noise_median']:.3f}%")
        print(f"      P75:    {stats['sell_noise_p75']:.3f}%")
        print(f"      P90:    {stats['sell_noise_p90']:.3f}%")
        print(f"      P95:    {stats['sell_noise_p95']:.3f}%")
        print(f"    2-bar adverse move:")
        print(f"      BUY P75/P90: {stats['2bar_buy_p75']:.3f}% / {stats['2bar_buy_p90']:.3f}%")
        print(f"      SELL P75/P90: {stats['2bar_sell_p75']:.3f}% / {stats['2bar_sell_p90']:.3f}%")
        print(f"    Avg 14-bar range: {stats['avg_atr_pct']:.2f}%")

        # Recommendation
        min_sl_buy = stats["buy_noise_p75"]
        min_sl_sell = stats["sell_noise_p75"]
        print(f"    >>> MIN VIABLE SL (P75): BUY={min_sl_buy:.3f}%, SELL={min_sl_sell:.3f}%")
        safe_sl = stats["buy_noise_p90"]
        print(f"    >>> SAFE SL (P90):       {safe_sl:.3f}%")
        max_lev_at_p75 = round(100 / min_sl_buy, 1) if min_sl_buy > 0 else 0
        max_lev_at_p90 = round(100 / safe_sl, 1) if safe_sl > 0 else 0
        print(f"    >>> MAX LEV @ P75 SL: {max_lev_at_p75}x | @ P90 SL: {max_lev_at_p90}x")

    return results


# ──────────────────────────────────────────────────────────────────────
# 2. LEVERAGE-ADJUSTED RETURNS: Simulate at each stop width
# ──────────────────────────────────────────────────────────────────────

def simulate_stop_width_returns(data):
    """
    For each asset, simulate entries at every candle close with stops at:
    0.3%, 0.5%, 0.8%, 1.0%, 1.5%, 2.0%

    Measure: WR (did we get stopped out within 3 candles?),
    net PnL with fixed R:R targets.
    """
    print("\n" + "=" * 80)
    print("2. LEVERAGE-ADJUSTED RETURNS by Stop Width")
    print("=" * 80)

    STOP_WIDTHS = [0.3, 0.5, 0.8, 1.0, 1.5, 2.0]
    HOLDING_BARS = 6  # 6 hours for 1h candles
    RR_TARGET = 1.5   # TP at 1.5x the stop width
    RISK_PER_TRADE = 100  # $100 risk per trade for comparison

    results = {}

    for sym, dfs in data.items():
        df = dfs["1h"].copy()
        if len(df) < HOLDING_BARS + 10:
            print(f"  {sym}: insufficient data")
            continue

        close = df["close"].values
        high = df["high"].values
        low = df["low"].values

        sym_results = {}

        for sw_pct in STOP_WIDTHS:
            sw_frac = sw_pct / 100.0
            tp_frac = sw_frac * RR_TARGET

            wins = 0
            losses = 0
            total_pnl = 0
            trades = 0

            # Simulate BUY entries at each candle
            for i in range(len(close) - HOLDING_BARS - 1):
                entry = close[i]
                sl = entry * (1 - sw_frac)
                tp = entry * (1 + tp_frac)

                hit_tp = False
                hit_sl = False

                for j in range(1, HOLDING_BARS + 1):
                    idx = i + j
                    if idx >= len(close):
                        break
                    # Check SL first (conservative: SL before TP if both hit)
                    if low[idx] <= sl:
                        hit_sl = True
                        break
                    if high[idx] >= tp:
                        hit_tp = True
                        break

                if hit_tp:
                    wins += 1
                    total_pnl += RISK_PER_TRADE * RR_TARGET
                elif hit_sl:
                    losses += 1
                    total_pnl -= RISK_PER_TRADE
                else:
                    # Held to expiry: mark to market
                    exit_price = close[min(i + HOLDING_BARS, len(close) - 1)]
                    pnl_pct = (exit_price - entry) / entry
                    pnl_dollar = (pnl_pct / sw_frac) * RISK_PER_TRADE  # Scale to risk
                    total_pnl += pnl_dollar
                    if pnl_dollar >= 0:
                        wins += 1
                    else:
                        losses += 1

                trades += 1

            wr = wins / trades * 100 if trades > 0 else 0
            avg_pnl = total_pnl / trades if trades > 0 else 0
            max_lev = round(100 / sw_pct, 1) if sw_pct > 0 else 0

            sym_results[sw_pct] = {
                "trades": trades,
                "wins": wins,
                "losses": losses,
                "wr": wr,
                "total_pnl": total_pnl,
                "avg_pnl": avg_pnl,
                "max_leverage": max_lev,
                "pnl_per_1pct_risk": avg_pnl,  # Already $100 risk base
            }

        results[sym] = sym_results

        print(f"\n  {sym} — BUY entries, {RR_TARGET}:1 R:R, {HOLDING_BARS}h hold:")
        print(f"    {'SL%':>6} {'MaxLev':>7} {'Trades':>7} {'WR':>7} {'AvgPnL':>9} {'TotalPnL':>10} {'Edge':>8}")
        print(f"    {'-'*55}")
        for sw_pct in STOP_WIDTHS:
            r = sym_results[sw_pct]
            edge = "+" if r["avg_pnl"] > 0 else "-"
            print(f"    {sw_pct:>5.1f}% {r['max_leverage']:>6.0f}x {r['trades']:>7d} {r['wr']:>6.1f}% ${r['avg_pnl']:>8.2f} ${r['total_pnl']:>9.0f} {edge:>8}")

    return results


# ──────────────────────────────────────────────────────────────────────
# 3. PRECISION ENTRY ADVANTAGE: 5m vs 1h stop width
# ──────────────────────────────────────────────────────────────────────

def analyze_precision_entry(data):
    """
    Compare stop widths needed when using 1h candle structure vs 5m candle structure.

    1h SL: behind the 1h signal candle low (for BUY)
    5m SL: behind the 5m signal candle low (tighter)

    Quantify the leverage advantage.
    """
    print("\n" + "=" * 80)
    print("3. PRECISION ENTRY ADVANTAGE — 5m vs 1h Stop Widths")
    print("=" * 80)

    results = {}

    for sym, dfs in data.items():
        df_1h = dfs["1h"].copy()
        df_5m = dfs["5m"].copy()

        if df_1h.empty or df_5m.empty:
            print(f"  {sym}: insufficient data")
            continue

        # 1h: SL = behind candle low -> distance = (close - low) / close
        sl_1h = ((df_1h["close"] - df_1h["low"]) / df_1h["close"] * 100).values
        # Add a buffer (1 ATR fraction)
        atr_1h = (df_1h["high"] - df_1h["low"]).rolling(14).mean().values
        atr_pct_1h = atr_1h / df_1h["close"].values * 100
        sl_1h_buffered = sl_1h + np.nan_to_num(atr_pct_1h * 0.2, nan=0)  # 20% ATR buffer

        # 5m: SL = behind 5m candle low
        sl_5m = ((df_5m["close"] - df_5m["low"]) / df_5m["close"] * 100).values
        atr_5m = (df_5m["high"] - df_5m["low"]).rolling(14).mean().values
        atr_pct_5m = atr_5m / df_5m["close"].values * 100
        sl_5m_buffered = sl_5m + np.nan_to_num(atr_pct_5m * 0.2, nan=0)

        # Filter out zeros
        sl_1h_b = sl_1h_buffered[sl_1h_buffered > 0]
        sl_5m_b = sl_5m_buffered[sl_5m_buffered > 0]

        if len(sl_1h_b) == 0 or len(sl_5m_b) == 0:
            continue

        stats = {
            "sl_1h_median": np.median(sl_1h_b),
            "sl_1h_p25": np.percentile(sl_1h_b, 25),
            "sl_5m_median": np.median(sl_5m_b),
            "sl_5m_p25": np.percentile(sl_5m_b, 25),
        }

        # Leverage advantage
        lev_1h = 100 / stats["sl_1h_median"] if stats["sl_1h_median"] > 0 else 1
        lev_5m = 100 / stats["sl_5m_median"] if stats["sl_5m_median"] > 0 else 1
        advantage = lev_5m / lev_1h if lev_1h > 0 else 1

        stats["max_lev_1h"] = lev_1h
        stats["max_lev_5m"] = lev_5m
        stats["leverage_advantage"] = advantage

        # Tight 5m: use P25 (best 25% of entries)
        lev_5m_tight = 100 / stats["sl_5m_p25"] if stats["sl_5m_p25"] > 0 else 1
        stats["max_lev_5m_tight"] = lev_5m_tight

        results[sym] = stats

        print(f"\n  {sym}:")
        print(f"    1h entry SL (median): {stats['sl_1h_median']:.3f}% -> max {lev_1h:.0f}x")
        print(f"    5m entry SL (median): {stats['sl_5m_median']:.3f}% -> max {lev_5m:.0f}x")
        print(f"    5m entry SL (P25 tight): {stats['sl_5m_p25']:.3f}% -> max {lev_5m_tight:.0f}x")
        print(f"    >>> PRECISION ADVANTAGE: {advantage:.1f}x more leverage with 5m timing")
        print(f"    >>> AT SAME $RISK: 5m entry = {advantage:.1f}x more profit potential")

    return results


# ──────────────────────────────────────────────────────────────────────
# 4. MAX SAFE LEVERAGE BY SETUP QUALITY
# ──────────────────────────────────────────────────────────────────────

def max_leverage_by_quality(noise_results, precision_results):
    """
    Combine noise floor + precision entry data to recommend max leverage
    by setup quality tier.
    """
    print("\n" + "=" * 80)
    print("4. MAXIMUM SAFE LEVERAGE BY SETUP QUALITY")
    print("=" * 80)

    tiers = {}

    for sym in noise_results:
        noise = noise_results[sym]
        prec = precision_results.get(sym, {})

        # Tier 1: 1 confluence, 1h entry -> stop at noise P90 (safe from noise)
        sl_tier1 = noise["buy_noise_p90"]
        lev_tier1 = min(100 / sl_tier1, 25) if sl_tier1 > 0 else 3

        # Tier 2: 2-3 confluences, 1h entry -> stop at noise P75 (good level)
        sl_tier2 = noise["buy_noise_p75"]
        lev_tier2 = min(100 / sl_tier2, 25) if sl_tier2 > 0 else 5

        # Tier 3: 3 confluences, 5m timed -> stop at 5m median
        sl_tier3 = prec.get("sl_5m_median", sl_tier2 * 0.6)
        lev_tier3 = min(100 / sl_tier3, 25) if sl_tier3 > 0 else 10

        # Tier 4: 5 confluences, 5m timed, volume confirmed, multi-TF
        sl_tier4 = prec.get("sl_5m_p25", sl_tier3 * 0.7)
        lev_tier4 = min(100 / sl_tier4, 25) if sl_tier4 > 0 else 15

        # Apply safety factor (80% of theoretical max)
        safety = 0.80
        tiers[sym] = {
            "tier1": {"confluences": 1, "entry": "1h", "sl_pct": sl_tier1, "max_lev": round(lev_tier1 * safety, 1)},
            "tier2": {"confluences": "2-3", "entry": "1h", "sl_pct": sl_tier2, "max_lev": round(lev_tier2 * safety, 1)},
            "tier3": {"confluences": 3, "entry": "5m", "sl_pct": sl_tier3, "max_lev": round(lev_tier3 * safety, 1)},
            "tier4": {"confluences": "5+", "entry": "5m+vol+MTF", "sl_pct": sl_tier4, "max_lev": round(lev_tier4 * safety, 1)},
        }

        print(f"\n  {sym}:")
        print(f"    {'Tier':>6} {'Confluences':>13} {'Entry':>12} {'SL%':>8} {'MaxLev':>8} {'Note':>20}")
        print(f"    {'-'*70}")
        for name, t in tiers[sym].items():
            note = ""
            if t["max_lev"] > 20:
                note = "CAP AT 20x"
                t["max_lev"] = min(t["max_lev"], 20.0)
            elif t["max_lev"] > 15:
                note = "HIGH RISK"
            print(f"    {name:>6} {str(t['confluences']):>13} {t['entry']:>12} {t['sl_pct']:>7.3f}% {t['max_lev']:>7.1f}x {note:>20}")

    return tiers


# ──────────────────────────────────────────────────────────────────────
# 5. RISK OF RUIN — Monte Carlo Simulation
# ──────────────────────────────────────────────────────────────────────

def risk_of_ruin_mc(observed_wr=0.52, rr_ratio=1.5,
                     leverage_levels=[5, 10, 15, 20, 25],
                     n_sims=1000, n_trades=100,
                     starting_equity=100,
                     risk_per_trade_pct=2.0,
                     ruin_threshold=0.25):
    """
    Monte Carlo risk of ruin at each leverage level.

    Key insight: leverage doesn't change your WR or R:R. It changes how
    much of your equity is at risk per trade.

    At 10x leverage with 2% risk per trade, a loss = 2% equity.
    But the POSITION is 10x larger, so the STOP must be tighter.
    If the stop is too tight for the noise, the REAL WR drops.

    We simulate two scenarios:
    A) "Ideal WR" — leverage doesn't affect WR (perfect entries)
    B) "Realistic WR" — WR degrades as leverage increases (tighter stops = more noise stops)
    """
    print("\n" + "=" * 80)
    print("5. RISK OF RUIN — Monte Carlo (1000 sims x 100 trades)")
    print("=" * 80)
    print(f"    Base WR: {observed_wr*100:.0f}%, R:R: {rr_ratio}:1")
    print(f"    Risk per trade: {risk_per_trade_pct}% of equity")
    print(f"    Ruin = equity drops to {ruin_threshold*100:.0f}% of starting")
    print(f"    Starting equity: ${starting_equity}")

    np.random.seed(42)

    # WR degradation model: tighter stops = more noise stops
    # At 5x: WR stays at observed
    # At 10x: -3% WR (slightly tighter stops)
    # At 15x: -6% WR
    # At 20x: -10% WR
    # At 25x: -15% WR
    wr_degradation = {5: 0, 10: 0.03, 15: 0.06, 20: 0.10, 25: 0.15}

    results = {}

    print(f"\n    {'Lev':>5} {'Scenario':>10} {'EffWR':>7} {'Ruin%':>7} {'MedianEq':>10} {'P10Eq':>9} {'P90Eq':>9} {'MaxDD':>7}")
    print(f"    {'-'*70}")

    for lev in leverage_levels:
        for scenario, wr_adj in [("ideal", 0), ("realistic", wr_degradation.get(lev, 0.15))]:
            effective_wr = observed_wr - wr_adj
            if effective_wr <= 0.3:
                effective_wr = 0.3  # Floor

            ruin_count = 0
            final_equities = []
            max_drawdowns = []

            for sim in range(n_sims):
                equity = starting_equity
                peak = equity
                max_dd = 0
                ruined = False

                for t in range(n_trades):
                    risk_usd = equity * (risk_per_trade_pct / 100.0)

                    if np.random.random() < effective_wr:
                        # Win: gain = risk * R:R
                        equity += risk_usd * rr_ratio
                    else:
                        # Loss: lose risk amount
                        equity -= risk_usd

                    peak = max(peak, equity)
                    dd = (peak - equity) / peak if peak > 0 else 0
                    max_dd = max(max_dd, dd)

                    if equity <= starting_equity * ruin_threshold:
                        ruined = True
                        break

                final_equities.append(equity)
                max_drawdowns.append(max_dd)
                if ruined:
                    ruin_count += 1

            ruin_pct = ruin_count / n_sims * 100
            median_eq = np.median(final_equities)
            p10_eq = np.percentile(final_equities, 10)
            p90_eq = np.percentile(final_equities, 90)
            avg_max_dd = np.mean(max_drawdowns) * 100

            key = f"{lev}x_{scenario}"
            results[key] = {
                "leverage": lev,
                "scenario": scenario,
                "effective_wr": effective_wr,
                "ruin_pct": ruin_pct,
                "median_equity": median_eq,
                "p10_equity": p10_eq,
                "p90_equity": p90_eq,
                "avg_max_dd": avg_max_dd,
            }

            print(f"    {lev:>4}x {scenario:>10} {effective_wr*100:>6.0f}% {ruin_pct:>6.1f}% ${median_eq:>9.0f} ${p10_eq:>8.0f} ${p90_eq:>8.0f} {avg_max_dd:>6.1f}%")

    # ── Sensitivity: What WR do you need at each leverage for <5% ruin?
    print(f"\n  SENSITIVITY: Minimum WR for <5% ruin at each leverage:")
    print(f"    {'Lev':>5} {'MinWR for <5% ruin':>20} {'MinWR for <1% ruin':>20}")

    for lev in leverage_levels:
        for target_ruin, label in [(5, "<5%"), (1, "<1%")]:
            for wr_test in np.arange(0.40, 0.75, 0.01):
                ruin_ct = 0
                for sim in range(500):  # Quick check
                    eq = starting_equity
                    for t in range(n_trades):
                        r = eq * (risk_per_trade_pct / 100.0)
                        if np.random.random() < wr_test:
                            eq += r * rr_ratio
                        else:
                            eq -= r
                        if eq <= starting_equity * ruin_threshold:
                            ruin_ct += 1
                            break

                if ruin_ct / 500 * 100 < target_ruin:
                    if label == "<5%":
                        min_wr_5 = wr_test
                    else:
                        min_wr_1 = wr_test
                    break
            else:
                if label == "<5%":
                    min_wr_5 = 0.75
                else:
                    min_wr_1 = 0.75

        print(f"    {lev:>4}x {min_wr_5*100:>18.0f}% {min_wr_1*100:>18.0f}%")

    return results


# ──────────────────────────────────────────────────────────────────────
# 6. FINAL RECOMMENDATIONS
# ──────────────────────────────────────────────────────────────────────

def generate_recommendations(noise_results, stop_results, precision_results, leverage_tiers, ruin_results):
    """Generate specific recommendations for conviction_sizer.py"""
    print("\n" + "=" * 80)
    print("6. RECOMMENDATIONS FOR CONVICTION SIZER")
    print("=" * 80)

    print("""
  CURRENT SYSTEM:
    1 confluence:  5x  (min)
    2 confluences: 8x
    3 confluences: 10x
    4 confluences: 12x
    5+ confluences: 15x
    Hard cap: 20x

  PROPOSED HIGH-LEVERAGE PRECISION TIERS:

  The key insight: it's not about "higher leverage = more risk."
  It's about: tighter stop (from precision entry) = same $ risk at higher leverage.

  TWO MODES:

  A) CONSERVATIVE (current bot — auto-traded):
     Keep current tiers. The bot doesn't have 5m precision timing.
     Max 5.5x leverage. This is correct for automated execution.

  B) PRECISION SNIPER (manual — 5m timed entries):
     These tiers REQUIRE:
     - 5m candle timing (enter at 5m candle close at support)
     - Volume confirmation (volume > 1.5x avg at level)
     - Multi-TF alignment (1h + 5m agree)

     PROPOSED PRECISION TIERS:
""")

    for sym in leverage_tiers:
        tiers = leverage_tiers[sym]
        print(f"  {sym}:")
        for name, t in tiers.items():
            conf = t["confluences"]
            entry = t["entry"]
            sl = t["sl_pct"]
            lev = t["max_lev"]
            print(f"    {conf} conf, {entry} entry: SL={sl:.2f}%, max {lev:.0f}x")
        print()

    # Risk per trade recommendations
    print("""  RISK PER TRADE (at each leverage):
    5-8x:   2.0% equity  (bread and butter)
    10-12x: 1.5% equity  (reduced for leverage)
    15x:    1.0% equity  (precision required)
    20x:    0.75% equity (only fortress setups)
    25x:    0.5% equity  (max precision, rare)

  CRITICAL RULES:
    1. NEVER use >10x without 5m entry timing
    2. NEVER use >15x without 3+ confluences
    3. NEVER use >20x without 5+ confluences AND volume confirmation
    4. Risk per trade DECREASES as leverage increases
    5. Stop MUST be behind structure (not arbitrary %)
    6. If 2 consecutive stops hit at high leverage, drop to 5x for 3 trades
""")

    # Dollar example
    print("""  DOLLAR EXAMPLE ($100 account, HYPE BUY):

    CONSERVATIVE (1h entry, 1 conf):
      Entry: $40.00, SL: $39.60 (1.0%), TP: $40.60 (1.5%)
      Leverage: 5x, Risk: 2% = $2.00
      Notional: $200, Qty: 5.0 HYPE
      Win: +$3.00, Loss: -$2.00, R:R 1.5:1

    PRECISION (5m entry, 5 conf):
      Entry: $40.00, SL: $39.85 (0.375%), TP: $40.60 (1.5%)
      Leverage: 20x, Risk: 0.75% = $0.75
      Notional: $1,500, Qty: 37.5 HYPE
      Win: +$22.50, Loss: -$5.63, R:R 4.0:1

    SAME DOLLAR RISK ($2.00), but precision entry:
      Entry: $40.00, SL: $39.85 (0.375%), TP: $40.60 (1.5%)
      Leverage: 20x, Risk: 2% = $2.00
      Qty: $2.00 / $0.15 = 13.3 HYPE
      Win: +$8.00, Loss: -$2.00, R:R 4.0:1
      >>> 2.67x MORE PROFIT for the SAME risk
""")

    return True


# ──────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 80)
    print("HIGH-LEVERAGE PRECISION TRADING ANALYSIS")
    print("=" * 80)

    # Fetch data
    print("\n[STEP 0] Fetching market data...")
    data = fetch_data()

    # 1. Noise floor
    print("\n[STEP 1] Analyzing noise floors...")
    noise_results = analyze_noise_floor(data)

    # 2. Stop width returns
    print("\n[STEP 2] Simulating leverage-adjusted returns...")
    stop_results = simulate_stop_width_returns(data)

    # 3. Precision entry advantage
    print("\n[STEP 3] Analyzing 5m vs 1h precision...")
    precision_results = analyze_precision_entry(data)

    # 4. Max leverage by quality
    print("\n[STEP 4] Computing max leverage by setup quality...")
    leverage_tiers = max_leverage_by_quality(noise_results, precision_results)

    # 5. Risk of ruin
    print("\n[STEP 5] Running Monte Carlo risk of ruin...")
    ruin_results = risk_of_ruin_mc()

    # 6. Recommendations
    print("\n[STEP 6] Generating recommendations...")
    generate_recommendations(noise_results, stop_results, precision_results, leverage_tiers, ruin_results)

    print("\n" + "=" * 80)
    print("ANALYSIS COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
