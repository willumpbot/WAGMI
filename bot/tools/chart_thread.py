"""Chart + thread generator for any Hyperliquid symbol.

Usage:
    python tools/chart_thread.py BTC
    python tools/chart_thread.py ETH --out ~/Desktop/eth_thread
    python tools/chart_thread.py HYPE --mode simple
    python tools/chart_thread.py SOL --mode thread --theme dark

Modes:
    thread  — 5-image dark-themed thread set (default)
    simple  — 3-image quick-analysis set (light theme)

Output: PNGs written to --out (defaults to ~/Desktop/{symbol}_thread/ or {symbol}_charts/).
"""
import argparse
import os
import sys
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import FancyBboxPatch
import ccxt
import numpy as np


def ema(arr, n):
    alpha = 2 / (n + 1)
    out = [arr[0]]
    for v in arr[1:]:
        out.append(alpha * v + (1 - alpha) * out[-1])
    return np.array(out)


def rsi14(closes):
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    out = np.full(len(closes), 50.0)
    for i in range(14, len(closes)):
        g = np.mean(gains[i - 14:i])
        l = np.mean(losses[i - 14:i])
        out[i] = 100 - 100 / (1 + g / max(l, 1e-9))
    return out


def candles(ax, times, o, h, l, c, body=3, wick=0.8, green="#26a69a", red="#ef5350"):
    for i in range(len(times)):
        color = green if c[i] >= o[i] else red
        ax.plot([times[i], times[i]], [l[i], h[i]], color=color, linewidth=wick)
        ax.plot([times[i], times[i]], [o[i], c[i]], color=color, linewidth=body)


def fetch(ex, sym, tf, limit):
    c = ex.fetch_ohlcv(sym, tf, limit=limit)
    return (
        [datetime.fromtimestamp(x[0] / 1000, tz=timezone.utc) for x in c],
        np.array([x[1] for x in c]),
        np.array([x[2] for x in c]),
        np.array([x[3] for x in c]),
        np.array([x[4] for x in c]),
        np.array([x[5] for x in c]),
    )


def auto_levels(times, o, h, l, c, tf):
    """Derive resistance/support/EMA levels from actual data."""
    hi20 = float(np.max(h[-20:]))
    lo20 = float(np.min(l[-20:]))
    hi_full = float(np.max(h))
    lo_full = float(np.min(l))
    e20 = float(ema(c, 20)[-1])
    e50 = float(ema(c, min(50, len(c) // 2))[-1])
    return {
        "hi20": hi20, "lo20": lo20,
        "hi_full": hi_full, "lo_full": lo_full,
        "ema20": e20, "ema50": e50,
    }


def apply_dark_theme():
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "axes.facecolor": "#0d1117",
        "figure.facecolor": "#0d1117",
        "savefig.facecolor": "#0d1117",
        "text.color": "#e6edf3",
        "axes.labelcolor": "#e6edf3",
        "xtick.color": "#8b949e",
        "ytick.color": "#8b949e",
        "axes.edgecolor": "#30363d",
        "grid.color": "#21262d",
        "grid.alpha": 0.5,
    })


def reset_theme():
    plt.rcdefaults()


def gen_thread(symbol, out_dir):
    apply_dark_theme()
    GREEN, RED, GOLD, BLUE, PURPLE, TEXT = "#26a69a", "#ef5350", "#ffc107", "#42a5f5", "#ab47bc", "#e6edf3"

    ex = ccxt.hyperliquid()
    ex.load_markets()
    sym = f"{symbol}/USDC:USDC"
    price = ex.fetch_ticker(sym)["last"]
    ts = datetime.now(timezone.utc).strftime("%b %d, %Y · %H:%M UTC")

    # Pull daily for long-term levels
    times_d, _, h_d, l_d, c_d, _ = fetch(ex, sym, "1d", 60)
    L_d = auto_levels(times_d, _, h_d, l_d, c_d, "1d")
    # Pull 4h
    times_4, _, h_4, l_4, c_4, _ = fetch(ex, sym, "4h", 100)
    L_4 = auto_levels(times_4, _, h_4, l_4, c_4, "4h")
    # Pull 1h
    times_1, o_1, h_1, l_1, c_1, v_1 = fetch(ex, sym, "1h", 96)
    L_1 = auto_levels(times_1, o_1, h_1, l_1, c_1, "1h")

    # Derived dynamic levels
    resistance = L_1["hi20"]
    support = L_1["lo20"]
    ema20_1h = L_1["ema20"]
    ema50_1h = L_1["ema50"]
    daily_ema20 = L_d["ema20"]
    daily_ema50 = L_d["ema50"]
    hi_60d = L_d["hi_full"]
    lo_60d = L_d["lo_full"]

    # ---- 01 thesis summary ----
    fig, ax = plt.subplots(figsize=(12, 7))
    ax.axis("off")
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.text(5, 9.3, f"{symbol} — MULTI-TIMEFRAME THESIS", fontsize=26, fontweight="bold", ha="center", color=GOLD)
    ax.text(5, 8.6, f"${price:,.2f}  ·  {ts}", fontsize=14, ha="center", color="#8b949e")

    e20d = ema(c_d, 20)
    daily_slope = (e20d[-1] - e20d[-10]) / e20d[-10] * 100
    rsi_d = rsi14(c_d)[-1]
    rsi_1 = rsi14(c_1)[-1]
    atr_1h = float(np.mean(np.maximum(h_1[1:] - l_1[1:], np.maximum(
        np.abs(h_1[1:] - c_1[:-1]), np.abs(l_1[1:] - c_1[:-1])))[-14:]))
    atr_d = float(np.mean(np.maximum(h_d[1:] - l_d[1:], np.maximum(
        np.abs(h_d[1:] - c_d[:-1]), np.abs(l_d[1:] - c_d[:-1])))[-14:]))
    trend_d = "UP" if daily_ema20 > daily_ema50 and daily_slope > 0.2 else ("DOWN" if daily_ema20 < daily_ema50 and daily_slope < -0.2 else "FLAT")

    def box(x, y, w, hh, title, lines, color):
        ax.add_patch(FancyBboxPatch((x, y), w, hh, boxstyle="round,pad=0.15",
                                     facecolor="#161b22", edgecolor=color, linewidth=2))
        ax.text(x + w / 2, y + hh - 0.35, title, fontsize=14, fontweight="bold", ha="center", color=color)
        for i, line in enumerate(lines):
            ax.text(x + 0.25, y + hh - 0.85 - i * 0.38, line, fontsize=11, color=TEXT)

    box(0.3, 4.8, 4.6, 3.2, "LONG-TERM (Daily)", [
        f"• Trend: {trend_d}  ·  slope {daily_slope:+.2f}%/10d",
        f"• RSI(14): {rsi_d:.0f}",
        f"• Price vs EMA20: {(price-daily_ema20)/daily_ema20*100:+.2f}%  ·  vs EMA50: {(price-daily_ema50)/daily_ema50*100:+.2f}%",
        f"• 60-day range: ${lo_60d:,.0f} — ${hi_60d:,.0f}",
        f"• Daily ATR: {atr_d/price*100:.2f}%",
        f"• Invalidation: daily close < ${daily_ema50:,.0f}",
    ], GREEN)
    box(5.1, 4.8, 4.6, 3.2, "SHORT-TERM (1h)", [
        f"• 1h EMA20: ${ema20_1h:,.0f}  ·  EMA50: ${ema50_1h:,.0f}",
        f"• 1h RSI: {rsi_1:.0f}",
        f"• 1h ATR: {atr_1h/price*100:.2f}%",
        f"• Range last 20h: ${support:,.0f} — ${resistance:,.0f}",
        f"• Distance to resistance: {(resistance-price)/price*100:+.2f}%",
        f"• Distance to support: {(support-price)/price*100:+.2f}%",
    ], BLUE)
    box(0.3, 0.9, 9.4, 3.5, "KEY LEVELS", [
        f"★  UPSIDE:  ${resistance:,.0f} → ${hi_60d:,.0f} (60-day high)",
        f"★  ENTRY ZONE (pullback):  ${ema20_1h:,.0f} (1h EMA20)  ·  ${ema50_1h:,.0f} (1h EMA50)",
        f"★  CURRENT:  ${price:,.0f}",
        f"★  DOWNSIDE:  ${support:,.0f} (20h low / stop)  ·  ${daily_ema20:,.0f} (daily EMA20)",
        f"★  INVALIDATION:  daily close < ${daily_ema50:,.0f} (daily EMA50)",
    ], GOLD)
    plt.tight_layout()
    plt.savefig(f"{out_dir}/01_thesis_summary.png", dpi=130, bbox_inches="tight")
    plt.close()
    print(f"  01_thesis_summary.png")

    # ---- 02 daily structure ----
    e20 = ema(c_d, 20)
    e50 = ema(c_d, min(50, len(c_d) // 2))
    r = rsi14(c_d)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 9), sharex=True,
                                    gridspec_kw={"height_ratios": [3, 1]})
    fig.suptitle(f"{symbol} — Daily Structure  ·  60 days  ·  ${price:,.2f}",
                 fontsize=17, fontweight="bold", color=GOLD)
    candles(ax1, times_d, _, h_d, l_d, c_d, body=5, wick=1.2)
    ax1.plot(times_d, e20, label=f"EMA20  ${e20[-1]:,.0f}", color=GOLD, linewidth=2)
    ax1.plot(times_d, e50, label=f"EMA50  ${e50[-1]:,.0f}", color=BLUE, linewidth=2)
    ax1.axhline(y=hi_60d, color=RED, linestyle="--", alpha=0.7, label=f"60d HIGH ${hi_60d:,.0f}")
    ax1.axhline(y=lo_60d, color=GREEN, linestyle="--", alpha=0.7, label=f"60d LOW ${lo_60d:,.0f}")
    ax1.axhline(y=daily_ema50, color="#ff4444", linestyle=":", alpha=0.6, label=f"INVALIDATION ${daily_ema50:,.0f}")
    ax1.axhline(y=price, color="white", linewidth=1.5, alpha=0.9, label=f"NOW ${price:,.0f}")
    ax1.legend(loc="upper left", fontsize=10, framealpha=0.85, facecolor="#161b22", edgecolor="#30363d", labelcolor=TEXT)
    ax1.set_ylabel("Price $", fontsize=11)
    ax1.grid(alpha=0.3)
    ax2.plot(times_d, r, color=PURPLE, linewidth=2)
    ax2.axhline(y=70, color=RED, linestyle="--", alpha=0.5)
    ax2.axhline(y=30, color=GREEN, linestyle="--", alpha=0.5)
    ax2.fill_between(times_d, 70, 100, color=RED, alpha=0.1)
    ax2.fill_between(times_d, 0, 30, color=GREEN, alpha=0.1)
    ax2.set_ylabel("RSI(14)", fontsize=11)
    ax2.set_ylim(20, 90)
    ax2.grid(alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    plt.tight_layout()
    plt.savefig(f"{out_dir}/02_daily_structure.png", dpi=130, bbox_inches="tight")
    plt.close()
    print(f"  02_daily_structure.png")

    # ---- 03 short-term 1h ----
    e20s = ema(c_1, 20)
    e50s = ema(c_1, 50)
    rs = rsi14(c_1)
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(13, 10), sharex=True,
                                         gridspec_kw={"height_ratios": [4, 1, 1]})
    fig.suptitle(f"{symbol} — Short-term 1h  ·  4 days  ·  ${price:,.2f}",
                 fontsize=17, fontweight="bold", color=BLUE)
    candles(ax1, times_1, o_1, h_1, l_1, c_1)
    ax1.plot(times_1, e20s, label=f"EMA20 1h ${e20s[-1]:,.0f}", color=GOLD, linewidth=1.8)
    ax1.plot(times_1, e50s, label=f"EMA50 1h ${e50s[-1]:,.0f}", color=BLUE, linewidth=1.8)
    ax1.axhline(y=resistance, color=RED, linestyle="--", alpha=0.7, label=f"Resistance ${resistance:,.0f}")
    ax1.axhline(y=support, color=GREEN, linestyle="--", alpha=0.7, label=f"Support ${support:,.0f}")
    ax1.axhline(y=price, color="white", linewidth=1.3, alpha=0.9)
    ax1.legend(loc="upper left", fontsize=9, framealpha=0.85, facecolor="#161b22", edgecolor="#30363d", labelcolor=TEXT, ncol=2)
    ax1.set_ylabel("Price $", fontsize=11)
    ax1.grid(alpha=0.3)
    ax2.bar(times_1, v_1, color=[GREEN if c_1[i] >= o_1[i] else RED for i in range(len(times_1))], width=0.035, alpha=0.8)
    ax2.set_ylabel("Vol", fontsize=10)
    ax2.grid(alpha=0.3)
    ax3.plot(times_1, rs, color=PURPLE, linewidth=1.8)
    ax3.axhline(y=70, color=RED, linestyle="--", alpha=0.5)
    ax3.axhline(y=30, color=GREEN, linestyle="--", alpha=0.5)
    ax3.fill_between(times_1, 70, 100, color=RED, alpha=0.1)
    ax3.fill_between(times_1, 0, 30, color=GREEN, alpha=0.1)
    ax3.set_ylabel("RSI(14)", fontsize=10)
    ax3.set_ylim(20, 90)
    ax3.grid(alpha=0.3)
    ax3.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %Hh"))
    plt.xticks(rotation=30)
    plt.tight_layout()
    plt.savefig(f"{out_dir}/03_shortterm_1h.png", dpi=130, bbox_inches="tight")
    plt.close()
    print(f"  03_shortterm_1h.png")

    # ---- 04 scenarios ----
    fig, ax = plt.subplots(figsize=(13, 9))
    fig.suptitle(f"{symbol} — Scenario Playbook  ·  ${price:,.2f}",
                 fontsize=17, fontweight="bold", color=GOLD)
    candles(ax, times_1, o_1, h_1, l_1, c_1, body=2.5, wick=0.8)
    N = 24
    dt = times_1[-1] - times_1[-2]
    future = [times_1[-1] + dt * i for i in range(1, N + 1)]
    full_x = [times_1[-1]] + future
    bull_top = hi_60d * 1.04
    bull = np.concatenate([
        np.linspace(c_1[-1], resistance, 7),
        np.linspace(resistance, hi_60d, 11)[1:],
        np.linspace(hi_60d, bull_top, 9)[1:],
    ])[:N + 1]
    base = c_1[-1] + (resistance - c_1[-1]) * 0.3 * np.sin(np.linspace(0, 4 * np.pi, N + 1)) + \
           (resistance - c_1[-1]) * 0.1 * np.linspace(0, 1, N + 1)
    bear = np.concatenate([
        np.linspace(c_1[-1], support, 5),
        np.linspace(support, daily_ema20, 16)[1:],
        np.linspace(daily_ema20, daily_ema20 * 0.99, 6)[1:],
    ])[:N + 1]
    ax.plot(full_x, bull, color=GREEN, linewidth=2, linestyle="--", alpha=0.8, label=f"Bull → ${bull_top:,.0f}")
    ax.plot(full_x, base, color=GOLD, linewidth=2, linestyle="--", alpha=0.7, label="Base: chop")
    ax.plot(full_x, bear, color=RED, linewidth=2, linestyle="--", alpha=0.7, label=f"Bear: break ${support:,.0f}")
    for y, lbl, col in [
        (hi_60d, f"60d HIGH ${hi_60d:,.0f}", RED),
        (resistance, f"Resistance ${resistance:,.0f}", RED),
        (support, f"Support ${support:,.0f}", GREEN),
        (daily_ema20, f"Daily EMA20 ${daily_ema20:,.0f}", BLUE),
    ]:
        ax.axhline(y=y, color=col, linestyle=":", alpha=0.5, linewidth=1)
        ax.text(full_x[-1], y, f"  {lbl}", fontsize=9, color=col, va="center")
    ax.axhline(y=price, color="white", linewidth=1.3, alpha=0.9)
    ax.legend(loc="upper left", fontsize=11, framealpha=0.85, facecolor="#161b22", edgecolor="#30363d", labelcolor=TEXT)
    ax.set_ylabel("Price $", fontsize=11)
    ax.grid(alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %Hh"))
    plt.xticks(rotation=30)
    plt.tight_layout()
    plt.savefig(f"{out_dir}/04_scenarios.png", dpi=130, bbox_inches="tight")
    plt.close()
    print(f"  04_scenarios.png")

    # ---- 05 R/R table ----
    fig, ax = plt.subplots(figsize=(12, 7))
    ax.axis("off")
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.text(5, 9.3, f"{symbol} LONG — RISK / REWARD", fontsize=24, fontweight="bold", ha="center", color=GOLD)
    ax.text(5, 8.7, f"Entry planning at ${price:,.2f}", fontsize=13, ha="center", color="#8b949e")

    def rr(entry, stop, target):
        return (target - entry) / max(abs(entry - stop), 1e-9)

    plans = [
        ("Swing pullback", ema20_1h, support * 0.999, resistance, hi_60d, GREEN),
        ("Aggressive pullback", ema50_1h, support * 0.998, resistance, hi_60d, GOLD),
        ("Breakout chase", resistance * 1.001, resistance * 0.993, hi_60d, hi_60d * 1.03, BLUE),
        ("DCA add", ema50_1h, daily_ema50, hi_60d, hi_60d * 1.05, PURPLE),
    ]
    headers = ["Setup", "Entry", "Stop", "Target 1", "Target 2", "R:R T1", "R:R T2"]
    col_x = [0.4, 2.0, 3.2, 4.5, 5.8, 7.1, 8.1]
    for i, hdr in enumerate(headers):
        ax.text(col_x[i], 7.8, hdr, fontsize=11, fontweight="bold", color=GOLD)
    for j, (name, e, s, t1, t2, col) in enumerate(plans):
        y = 7.1 - j * 0.85
        row = [name, f"${e:,.0f}", f"${s:,.0f}", f"${t1:,.0f}", f"${t2:,.0f}", f"{rr(e, s, t1):.1f}x", f"{rr(e, s, t2):.1f}x"]
        for i, val in enumerate(row):
            color = col if i == 0 else TEXT
            weight = "bold" if i == 0 else "normal"
            ax.text(col_x[i], y, val, fontsize=10, color=color, fontweight=weight)
    ax.text(0.4, 1.8, "Rules of engagement:", fontsize=12, fontweight="bold", color=GOLD)
    footer = [
        "•  1-2% account risk max.",
        f"•  {symbol} ATR 1h = {atr_1h/price*100:.2f}% — tight stops, respect slippage",
        f"•  Daily close < ${daily_ema50:,.0f} = thesis broken",
        "•  Don't chase 5m RSI > 75 without trailing stops",
    ]
    for i, ln in enumerate(footer):
        ax.text(0.4, 1.3 - i * 0.3, ln, fontsize=10, color=TEXT)
    plt.tight_layout()
    plt.savefig(f"{out_dir}/05_risk_reward.png", dpi=130, bbox_inches="tight")
    plt.close()
    print(f"  05_risk_reward.png")
    reset_theme()


def gen_simple(symbol, out_dir):
    """Light-theme 3-image version."""
    reset_theme()
    ex = ccxt.hyperliquid()
    ex.load_markets()
    sym = f"{symbol}/USDC:USDC"
    price = ex.fetch_ticker(sym)["last"]
    # 1h
    t, o, h, l, c, v = fetch(ex, sym, "1h", 96)
    e20, e50, r = ema(c, 20), ema(c, 50), rsi14(c)
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 10), sharex=True,
                                         gridspec_kw={"height_ratios": [3, 1, 1]})
    fig.suptitle(f"{symbol} — 1h, 4 days — live ${price:,.2f}", fontsize=14, fontweight="bold")
    candles(ax1, t, o, h, l, c, green="green", red="red")
    ax1.plot(t, e20, label="EMA20", color="orange", linewidth=1.5)
    ax1.plot(t, e50, label="EMA50", color="blue", linewidth=1.5)
    ax1.axhline(y=price, color="black", linewidth=1, label=f"NOW ${price:,.0f}")
    ax1.legend(loc="upper left", fontsize=9)
    ax1.grid(alpha=0.3)
    ax2.bar(t, v, width=0.03)
    ax3.plot(t, r, color="purple")
    ax3.axhline(y=70, color="red", linestyle="--", alpha=0.5)
    ax3.axhline(y=30, color="green", linestyle="--", alpha=0.5)
    ax3.set_ylim(20, 90)
    ax3.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    plt.xticks(rotation=30)
    plt.tight_layout()
    plt.savefig(f"{out_dir}/shortterm_1h.png", dpi=110, bbox_inches="tight")
    plt.close()
    print(f"  shortterm_1h.png")


def main():
    ap = argparse.ArgumentParser(description="Generate crypto charts + thread content for any Hyperliquid symbol.")
    ap.add_argument("symbol", help="Symbol (e.g. BTC, ETH, SOL, HYPE)")
    ap.add_argument("--mode", choices=["thread", "simple"], default="thread")
    ap.add_argument("--out", default=None, help="Output dir (default: ~/Desktop/{symbol}_{mode}/)")
    args = ap.parse_args()
    symbol = args.symbol.upper()
    default_out = os.path.expanduser(f"~/Desktop/{symbol.lower()}_{args.mode}")
    out_dir = args.out or default_out
    os.makedirs(out_dir, exist_ok=True)
    print(f"Generating {args.mode} charts for {symbol} -> {out_dir}")
    if args.mode == "thread":
        gen_thread(symbol, out_dir)
    else:
        gen_simple(symbol, out_dir)
    print(f"\nDone. Open: {out_dir}")


if __name__ == "__main__":
    sys.exit(main())
