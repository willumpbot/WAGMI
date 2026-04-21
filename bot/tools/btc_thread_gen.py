"""BTC thread chart generator - clean charts for public/TL posting."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import FancyBboxPatch
import ccxt
import numpy as np
from datetime import datetime, timezone
import os

OUT = "C:/Users/vince/Desktop/btc_thread"
os.makedirs(OUT, exist_ok=True)

plt.rcParams["font.family"] = "DejaVu Sans"
plt.rcParams["axes.facecolor"] = "#0d1117"
plt.rcParams["figure.facecolor"] = "#0d1117"
plt.rcParams["savefig.facecolor"] = "#0d1117"
plt.rcParams["text.color"] = "#e6edf3"
plt.rcParams["axes.labelcolor"] = "#e6edf3"
plt.rcParams["xtick.color"] = "#8b949e"
plt.rcParams["ytick.color"] = "#8b949e"
plt.rcParams["axes.edgecolor"] = "#30363d"
plt.rcParams["grid.color"] = "#21262d"
plt.rcParams["grid.alpha"] = 0.5

ex = ccxt.hyperliquid()
ex.load_markets()
SYM = "BTC/USDC:USDC"

GREEN = "#26a69a"
RED = "#ef5350"
GOLD = "#ffc107"
BLUE = "#42a5f5"
PURPLE = "#ab47bc"
TEXT = "#e6edf3"


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


def candles(ax, times, o, h, l, c, body_width=3, wick_width=0.8):
    for i in range(len(times)):
        color = GREEN if c[i] >= o[i] else RED
        ax.plot([times[i], times[i]], [l[i], h[i]], color=color, linewidth=wick_width)
        ax.plot([times[i], times[i]], [o[i], c[i]], color=color, linewidth=body_width)


price = ex.fetch_ticker(SYM)["last"]
TS = datetime.now(timezone.utc).strftime("%b %d, %Y · %H:%M UTC")

# ============ IMAGE 1: THESIS SUMMARY ============
fig, ax = plt.subplots(figsize=(12, 7))
ax.axis("off")
ax.set_xlim(0, 10)
ax.set_ylim(0, 10)

ax.text(5, 9.3, "BTC — MULTI-TIMEFRAME THESIS", fontsize=26, fontweight="bold",
        ha="center", color=GOLD)
ax.text(5, 8.6, f"${price:,.2f}  ·  {TS}", fontsize=14, ha="center", color="#8b949e")

# Boxes
def box(x, y, w, h, title, lines, color):
    rect = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.15",
                          facecolor="#161b22", edgecolor=color, linewidth=2)
    ax.add_patch(rect)
    ax.text(x + w / 2, y + h - 0.35, title, fontsize=14, fontweight="bold",
            ha="center", color=color)
    for i, line in enumerate(lines):
        ax.text(x + 0.25, y + h - 0.85 - i * 0.38, line, fontsize=11, color=TEXT)

box(0.3, 4.8, 4.6, 3.2, "LONG-TERM (Daily)", [
    "• Trend: UP  ·  slope +4.5%/10d",
    "• RSI(14): 61 — bullish, not overbought",
    "• Price vs EMA20: +3.8%  ·  vs EMA50: +6.8%",
    "• 60-day range: $65,697 — $78,279",
    "• Structural bull thesis: INTACT",
    "• Invalidation: daily close < $71,088",
], GREEN)

box(5.1, 4.8, 4.6, 3.2, "SHORT-TERM (1h / 4h)", [
    "• 1h trend: UP  ·  4h: FLAT / consolidation",
    "• 5m RSI: 78 — overbought intraday",
    "• ATR 1h: 0.52% (compressed vs daily 3.16%)",
    "• Volume: 0.24-0.34x — thin tape",
    "• Range: $74,661 — $76,540 (4 days)",
    "• Action: wait for pullback or volume-break",
], BLUE)

box(0.3, 0.9, 9.4, 3.5, "KEY LEVELS", [
    "★  UPSIDE:  $76,540 → $77,369 → $78,279 (60-day high)  →  breakout targets $82k-$85k",
    "★  ENTRY ZONE (pullback):  $75,730 (1h EMA20)  ·  $75,000 (round + 1h EMA50)",
    "★  CURRENT:  " + f"${price:,.0f}  — RSI overheated intraday, thin weekend volume",
    "★  DOWNSIDE:  $74,661 (4d low / stop)  ·  $73,690 (16d low)  ·  $73,115 (daily EMA20)",
    "★  INVALIDATION:  daily close < $71,088 (daily EMA50) — bull thesis broken",
], GOLD)

plt.tight_layout()
plt.savefig(f"{OUT}/01_thesis_summary.png", dpi=130, bbox_inches="tight")
plt.close()
print("01_thesis_summary.png")


# ============ IMAGE 2: DAILY STRUCTURE ============
times, o, h, l, c, v = get_ohlcv("1d", 60)
e20 = ema(c, 20)
e50 = ema(c, 50)
r = rsi14(c)

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 9), sharex=True,
                                gridspec_kw={"height_ratios": [3, 1]})
fig.suptitle(f"BTC — Daily Structure  ·  60 days  ·  ${price:,.2f}",
             fontsize=17, fontweight="bold", color=GOLD)

candles(ax1, times, o, h, l, c, body_width=5, wick_width=1.2)
ax1.plot(times, e20, label=f"EMA20  ${e20[-1]:,.0f}", color=GOLD, linewidth=2)
ax1.plot(times, e50, label=f"EMA50  ${e50[-1]:,.0f}", color=BLUE, linewidth=2)
ax1.axhline(y=78279, color=RED, linestyle="--", alpha=0.7, linewidth=1.5, label="60d HIGH $78,279")
ax1.axhline(y=65697, color=GREEN, linestyle="--", alpha=0.7, linewidth=1.5, label="60d LOW $65,697")
ax1.axhline(y=71088, color="#ff4444", linestyle=":", alpha=0.6, linewidth=1.5, label="INVALIDATION $71,088")
ax1.axhline(y=price, color="white", linestyle="-", linewidth=1.5, alpha=0.9, label=f"NOW ${price:,.0f}")
ax1.axhspan(82000, 85000, alpha=0.12, color=GREEN)
ax1.text(times[-5], 83500, "BREAKOUT\nTARGET ZONE", fontsize=10, color=GREEN,
         fontweight="bold", ha="center")

ax1.legend(loc="upper left", fontsize=10, framealpha=0.85, facecolor="#161b22",
           edgecolor="#30363d", labelcolor=TEXT)
ax1.set_ylabel("Price $", fontsize=11)
ax1.grid(alpha=0.3)

ax2.plot(times, r, color=PURPLE, linewidth=2)
ax2.axhline(y=70, color=RED, linestyle="--", alpha=0.5)
ax2.axhline(y=30, color=GREEN, linestyle="--", alpha=0.5)
ax2.axhline(y=50, color="#666", linestyle=":", alpha=0.5)
ax2.fill_between(times, 70, 100, color=RED, alpha=0.1)
ax2.fill_between(times, 0, 30, color=GREEN, alpha=0.1)
ax2.set_ylabel("RSI(14)", fontsize=11)
ax2.set_ylim(20, 90)
ax2.grid(alpha=0.3)
ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
plt.xticks(rotation=0)
plt.tight_layout()
plt.savefig(f"{OUT}/02_daily_structure.png", dpi=130, bbox_inches="tight")
plt.close()
print("02_daily_structure.png")


# ============ IMAGE 3: SHORT-TERM ZOOM ============
times, o, h, l, c, v = get_ohlcv("1h", 96)
e20 = ema(c, 20)
e50 = ema(c, 50)
r = rsi14(c)

fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(13, 10), sharex=True,
                                     gridspec_kw={"height_ratios": [4, 1, 1]})
fig.suptitle(f"BTC — Short-term 1h  ·  4 days  ·  ${price:,.2f}",
             fontsize=17, fontweight="bold", color=BLUE)

candles(ax1, times, o, h, l, c)
ax1.plot(times, e20, label=f"EMA20 1h ${e20[-1]:,.0f}", color=GOLD, linewidth=1.8)
ax1.plot(times, e50, label=f"EMA50 1h ${e50[-1]:,.0f}", color=BLUE, linewidth=1.8)
ax1.axhline(y=76540, color=RED, linestyle="--", alpha=0.7, label="Resistance $76,540")
ax1.axhline(y=77369, color=RED, linestyle=":", alpha=0.5, label="Resistance $77,369")
ax1.axhline(y=75942, color="#FF8800", linestyle=":", alpha=0.6, label="Break-up trigger $75,942")
ax1.axhline(y=75000, color=GOLD, linestyle=":", alpha=0.5, label="Round level $75,000")
ax1.axhline(y=74661, color=GREEN, linestyle="--", alpha=0.7, label="Support $74,661")
ax1.axhline(y=73690, color=GREEN, linestyle=":", alpha=0.5, label="Support $73,690")
ax1.axhline(y=price, color="white", linestyle="-", alpha=0.9, linewidth=1.3)

ax1.axhspan(75730, 75000, alpha=0.08, color=GOLD)
ax1.text(times[-10], 75400, "ENTRY\nZONE", fontsize=9, color=GOLD, fontweight="bold", ha="center")
ax1.axhspan(76540, 78279, alpha=0.08, color=GREEN)
ax1.text(times[-10], 77400, "TARGET\nZONE", fontsize=9, color=GREEN, fontweight="bold", ha="center")

ax1.legend(loc="upper left", fontsize=9, framealpha=0.85, facecolor="#161b22",
           edgecolor="#30363d", labelcolor=TEXT, ncol=2)
ax1.set_ylabel("Price $", fontsize=11)
ax1.grid(alpha=0.3)

ax2.bar(times, v, color=[GREEN if c[i] >= o[i] else RED for i in range(len(times))],
        width=0.035, alpha=0.8)
ax2.set_ylabel("Vol", fontsize=10)
ax2.grid(alpha=0.3)

ax3.plot(times, r, color=PURPLE, linewidth=1.8)
ax3.axhline(y=70, color=RED, linestyle="--", alpha=0.5)
ax3.axhline(y=30, color=GREEN, linestyle="--", alpha=0.5)
ax3.axhline(y=50, color="#666", linestyle=":", alpha=0.5)
ax3.fill_between(times, 70, 100, color=RED, alpha=0.1)
ax3.fill_between(times, 0, 30, color=GREEN, alpha=0.1)
ax3.set_ylabel("RSI(14)", fontsize=10)
ax3.set_ylim(20, 90)
ax3.grid(alpha=0.3)

ax3.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %Hh"))
plt.xticks(rotation=30)
plt.tight_layout()
plt.savefig(f"{OUT}/03_shortterm_1h.png", dpi=130, bbox_inches="tight")
plt.close()
print("03_shortterm_1h.png")


# ============ IMAGE 4: SCENARIOS PLAYBOOK ============
fig, ax = plt.subplots(figsize=(13, 9))
fig.suptitle(f"BTC — Scenario Playbook  ·  ${price:,.2f}",
             fontsize=17, fontweight="bold", color=GOLD)

# Pull 1h for visual
times, o, h, l, c, v = get_ohlcv("1h", 72)
candles(ax, times, o, h, l, c, body_width=2.5, wick_width=0.8)

# Project forward 24 hourly points
N = 24
dt = times[-1] - times[-2]
future_times = [times[-1] + dt * i for i in range(1, N + 1)]
full_x = [times[-1]] + future_times  # N+1 points

# Bullish path: N+1 points
bull = np.concatenate([
    np.linspace(c[-1], 76540, 7),
    np.linspace(76540, 78279, 11)[1:],
    np.linspace(78279, 82000, 9)[1:],
])[:N + 1]
ax.plot(full_x, bull, color=GREEN, linewidth=2, linestyle="--", alpha=0.8,
        label="Bull scenario →$82k")

# Base path: N+1 points  — choppy range
base = c[-1] + 200 * np.sin(np.linspace(0, 4 * np.pi, N + 1)) + \
       300 * np.linspace(0, 1, N + 1)
ax.plot(full_x, base, color=GOLD, linewidth=2, linestyle="--", alpha=0.7,
        label="Base: chop $75k-$77k")

# Bear path: N+1 points
bear = np.concatenate([
    np.linspace(c[-1], 74661, 5),
    np.linspace(74661, 73115, 16)[1:],
    np.linspace(73115, 72500, 6)[1:],
])[:N + 1]
ax.plot(full_x, bear, color=RED, linewidth=2, linestyle="--", alpha=0.7,
        label="Bear: break $74,661 → $73,115")

# Key levels
for y, lbl, col in [
    (78279, "60d HIGH $78,279", RED),
    (76540, "Resistance $76,540", RED),
    (75000, "Round $75,000", GOLD),
    (74661, "Support $74,661", GREEN),
    (73115, "Daily EMA20 $73,115", BLUE),
]:
    ax.axhline(y=y, color=col, linestyle=":", alpha=0.5, linewidth=1)
    ax.text(full_x[-1], y, f" {lbl}", fontsize=9, color=col, va="center")

ax.axhline(y=price, color="white", linewidth=1.3, alpha=0.9)

ax.legend(loc="upper left", fontsize=11, framealpha=0.85, facecolor="#161b22",
          edgecolor="#30363d", labelcolor=TEXT)
ax.set_ylabel("Price $", fontsize=11)
ax.grid(alpha=0.3)
ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %Hh"))
plt.xticks(rotation=30)
plt.tight_layout()
plt.savefig(f"{OUT}/04_scenarios.png", dpi=130, bbox_inches="tight")
plt.close()
print("04_scenarios.png")


# ============ IMAGE 5: R:R TABLE VISUAL ============
fig, ax = plt.subplots(figsize=(12, 7))
ax.axis("off")
ax.set_xlim(0, 10)
ax.set_ylim(0, 10)

ax.text(5, 9.3, "BTC LONG — RISK / REWARD", fontsize=24, fontweight="bold",
        ha="center", color=GOLD)
ax.text(5, 8.7, f"Entry planning at ${price:,.2f}", fontsize=13, ha="center", color="#8b949e")

# Table
headers = ["Setup", "Entry", "Stop", "Target 1", "Target 2", "R:R T1", "R:R T2", "Quality"]
col_x = [0.4, 1.8, 3.0, 4.2, 5.4, 6.6, 7.5, 8.5]
for i, hdr in enumerate(headers):
    ax.text(col_x[i], 7.8, hdr, fontsize=11, fontweight="bold", color=GOLD)

rows = [
    ["Swing pullback long", "$75,730", "$74,600", "$76,540", "$78,279", "0.7x", "2.3x", "Best R:R"],
    ["Aggressive pullback",  "$75,000", "$74,300", "$76,540", "$78,279", "2.2x", "4.7x", "Wait for wick"],
    ["Breakout chase",       "$75,942", "$75,400", "$76,540", "$77,369", "1.1x", "2.6x", "Volume required"],
    ["Daily add-on (DCA)",   "$75,000", "$71,088", "$78,279", "$82,000", "0.8x", "1.8x", "Long horizon"],
    ["Re-test invalidation", "$73,115", "$71,088", "$76,000", "$78,279", "1.4x", "2.6x", "Only on flush"],
]
colors = [GREEN, GOLD, BLUE, PURPLE, "#888"]
for j, row in enumerate(rows):
    y = 7.1 - j * 0.85
    for i, val in enumerate(row):
        color = colors[j] if i == 0 else TEXT
        weight = "bold" if i == 0 else "normal"
        ax.text(col_x[i], y, val, fontsize=10, color=color, fontweight=weight)

# Footer note
ax.text(0.4, 1.2, "Rules of engagement:", fontsize=12, fontweight="bold", color=GOLD)
footer = [
    "•  Size with 1-2% account risk max. BTC ATR 1h = 0.52% — tight stops, small slippage.",
    "•  Weekend/Asia volume is 0.24-0.34x normal. Real signal comes at EU/US opens.",
    "•  Daily close below $71,088 = thesis broken. Close longs, reassess.",
    "•  Don't chase 5m RSI > 75 unless you're already in profit + trailing stops engaged.",
]
for i, ln in enumerate(footer):
    ax.text(0.4, 0.7 - i * 0.35, ln, fontsize=10, color=TEXT)

plt.tight_layout()
plt.savefig(f"{OUT}/05_risk_reward.png", dpi=130, bbox_inches="tight")
plt.close()
print("05_risk_reward.png")

print(f"\n=== 5 images in {OUT} ===")
