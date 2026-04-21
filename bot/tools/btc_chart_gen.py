"""One-shot BTC chart generator. Saves PNGs to Desktop/btc_charts/."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import ccxt
import numpy as np
from datetime import datetime, timezone
import os

OUT = "C:/Users/vince/Desktop/btc_charts"
os.makedirs(OUT, exist_ok=True)
ex = ccxt.hyperliquid()
ex.load_markets()
SYM = "BTC/USDC:USDC"


def get_ohlcv(tf, limit):
    c = ex.fetch_ohlcv(SYM, tf, limit=limit)
    return (
        [datetime.fromtimestamp(x[0] / 1000, tz=timezone.utc) for x in c],
        np.array([x[1] for x in c]),
        np.array([x[2] for x in c]),
        np.array([x[3] for x in c]),
        np.array([x[4] for x in c]),
        np.array([x[5] for x in c]),
    )


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


price = ex.fetch_ticker(SYM)["last"]

# ============ CHART 1: SHORT-TERM (1h, 4 days) ============
times, o, h, l, c, v = get_ohlcv("1h", 96)
e20 = ema(c, 20)
e50 = ema(c, 50)
r = rsi14(c)

fig, (ax1, ax2, ax3) = plt.subplots(
    3, 1, figsize=(14, 10), sharex=True,
    gridspec_kw={"height_ratios": [3, 1, 1]},
)
fig.suptitle(f"BTC — SHORT-TERM (1h, last 4 days) — live ${price:,.2f}",
             fontsize=14, fontweight="bold")

for i in range(len(times)):
    color = "green" if c[i] >= o[i] else "red"
    ax1.plot([times[i], times[i]], [l[i], h[i]], color=color, linewidth=0.8)
    ax1.plot([times[i], times[i]], [o[i], c[i]], color=color, linewidth=3)

ax1.plot(times, e20, label="EMA20", color="orange", linewidth=1.5)
ax1.plot(times, e50, label="EMA50", color="blue", linewidth=1.5)
ax1.axhline(y=76540, color="red", linestyle="--", alpha=0.6, label="Resistance $76,540 (4d high)")
ax1.axhline(y=75942, color="#FF8800", linestyle=":", alpha=0.6, label="Scalp trigger $75,942")
ax1.axhline(y=75730, color="gold", linestyle=":", alpha=0.6, label="EMA20 pullback $75,730")
ax1.axhline(y=74661, color="green", linestyle="--", alpha=0.6, label="Support $74,661 (4d low)")
ax1.axhline(y=price, color="black", linestyle="-", alpha=0.8, linewidth=1, label=f"NOW ${price:,.0f}")
ax1.legend(loc="upper left", fontsize=9)
ax1.set_ylabel("Price $")
ax1.grid(alpha=0.3)

ax2.bar(times, v, color=["green" if c[i] >= o[i] else "red" for i in range(len(times))], width=0.03)
ax2.set_ylabel("Vol")
ax2.grid(alpha=0.3)

ax3.plot(times, r, color="purple", linewidth=1.5)
ax3.axhline(y=70, color="red", linestyle="--", alpha=0.5)
ax3.axhline(y=30, color="green", linestyle="--", alpha=0.5)
ax3.axhline(y=50, color="gray", linestyle=":", alpha=0.5)
ax3.fill_between(times, 70, 100, color="red", alpha=0.08)
ax3.fill_between(times, 0, 30, color="green", alpha=0.08)
ax3.set_ylabel("RSI(14)")
ax3.set_ylim(20, 90)
ax3.grid(alpha=0.3)

ax3.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
plt.xticks(rotation=30)
plt.tight_layout()
plt.savefig(f"{OUT}/1_shortterm_1h.png", dpi=110, bbox_inches="tight")
plt.close()
print("Saved: 1_shortterm_1h.png")

# ============ CHART 2: LONG-TERM (daily, 60 days) ============
times, o, h, l, c, v = get_ohlcv("1d", 60)
e20 = ema(c, 20)
e50 = ema(c, 50)
r = rsi14(c)

fig, (ax1, ax2) = plt.subplots(
    2, 1, figsize=(14, 9), sharex=True,
    gridspec_kw={"height_ratios": [3, 1]},
)
fig.suptitle(f"BTC — LONG-TERM (daily, 60 days) — live ${price:,.2f}",
             fontsize=14, fontweight="bold")

for i in range(len(times)):
    color = "green" if c[i] >= o[i] else "red"
    ax1.plot([times[i], times[i]], [l[i], h[i]], color=color, linewidth=1.0)
    ax1.plot([times[i], times[i]], [o[i], c[i]], color=color, linewidth=5)

ax1.plot(times, e20, label=f"EMA20 (${e20[-1]:,.0f})", color="orange", linewidth=2)
ax1.plot(times, e50, label=f"EMA50 (${e50[-1]:,.0f})", color="blue", linewidth=2)
ax1.axhline(y=78279, color="red", linestyle="--", alpha=0.6, label="60d HIGH $78,279")
ax1.axhline(y=65697, color="green", linestyle="--", alpha=0.6, label="60d LOW $65,697")
ax1.axhline(y=71088, color="darkred", linestyle=":", alpha=0.5, label="Invalidation $71,088 (EMA50)")
ax1.axhline(y=73115, color="orange", linestyle=":", alpha=0.5, label="Daily bull floor $73,115 (EMA20)")
ax1.axhline(y=price, color="black", linestyle="-", linewidth=1.2, label=f"NOW ${price:,.0f}")
ax1.axhspan(82000, 85000, alpha=0.1, color="green", label="Breakout target zone")
ax1.legend(loc="upper left", fontsize=9)
ax1.set_ylabel("Price $")
ax1.grid(alpha=0.3)

ax2.plot(times, r, color="purple", linewidth=1.8)
ax2.axhline(y=70, color="red", linestyle="--", alpha=0.5)
ax2.axhline(y=30, color="green", linestyle="--", alpha=0.5)
ax2.axhline(y=50, color="gray", linestyle=":", alpha=0.5)
ax2.fill_between(times, 70, 100, color="red", alpha=0.08)
ax2.fill_between(times, 0, 30, color="green", alpha=0.08)
ax2.set_ylabel("RSI(14) daily")
ax2.set_ylim(20, 90)
ax2.grid(alpha=0.3)

ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
plt.xticks(rotation=30)
plt.tight_layout()
plt.savefig(f"{OUT}/2_longterm_daily.png", dpi=110, bbox_inches="tight")
plt.close()
print("Saved: 2_longterm_daily.png")

# ============ CHART 3: LEVELS MAP ============
fig, ax = plt.subplots(figsize=(11, 8))
levels = [
    (85000, "Breakout target", "green", "-"),
    (82000, "Stretch target", "green", "--"),
    (78279, "60d HIGH", "red", "-"),
    (77369, "16d high", "red", "--"),
    (76540, "4d high (swing target)", "orange", "-"),
    (75942, "Scalp trigger ABOVE", "blue", ":"),
    (price, f"NOW ${price:,.0f}", "black", "-"),
    (75730, "Pullback long @EMA20 1h", "gold", ":"),
    (75000, "Round + EMA50 1h", "gold", "--"),
    (74661, "4d LOW (stop)", "red", "-"),
    (73690, "16d low", "red", "--"),
    (73115, "Daily EMA20 (bull floor)", "orange", "-"),
    (71088, "Daily EMA50 (invalidation)", "darkred", "-"),
    (65697, "60d LOW", "purple", "--"),
]
levels.sort(key=lambda x: -x[0])
ymin = min(lv[0] for lv in levels) - 1000
ymax = max(lv[0] for lv in levels) + 1000

for y, label, color, style in levels:
    ax.axhline(y=y, color=color, linestyle=style, linewidth=1.5, alpha=0.8)
    ax.text(
        1.01, y, f"  ${y:,.0f}  {label}",
        transform=ax.get_yaxis_transform(), va="center", fontsize=10, color=color,
        fontweight="bold" if y in (price, 74661, 76540) else "normal",
    )

ax.axhspan(82000, 85000, alpha=0.1, color="green")
ax.axhspan(76540, 78279, alpha=0.06, color="green")
ax.axhspan(74661, 75730, alpha=0.08, color="gold")
ax.axhspan(65697, 73115, alpha=0.06, color="red")

ax.annotate(
    "SCALP: break $75,942\nwith volume",
    xy=(0.02, 75942), xytext=(0.02, 77500),
    fontsize=10, color="blue",
    arrowprops=dict(arrowstyle="->", color="blue"),
)
ax.annotate(
    "SWING LONG\npullback to $75,730\nstop $74,600",
    xy=(0.35, 75730), xytext=(0.35, 73800),
    fontsize=10, color="darkgoldenrod",
    arrowprops=dict(arrowstyle="->", color="darkgoldenrod"),
)

ax.set_ylim(ymin, ymax)
ax.set_xlim(0, 1)
ax.get_xaxis().set_visible(False)
ax.set_title(
    f"BTC — Key Levels Map — live ${price:,.2f}\n"
    f"(green = bullish zones, red = bearish zones, gold = long entry zone)",
    fontsize=13, fontweight="bold",
)
ax.grid(alpha=0.2, axis="y")
plt.tight_layout()
plt.savefig(f"{OUT}/3_levels_map.png", dpi=110, bbox_inches="tight")
plt.close()
print("Saved: 3_levels_map.png")
print(f"\n=== All 3 charts in {OUT} ===")
