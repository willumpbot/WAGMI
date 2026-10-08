"""4-hour layer: the same structure / stretch / driver readings on 4h candles, for swing entry timing.

live(sym)    current 4h readings (uses the still-forming 4h bar at the current price)
history()    every closed 4h bar since Hyperliquid's 4h history starts (~2.3 years, i.e. the recent regime),
             each reading's next-1-day (6 bars) return measured against the period's own drift.
"""
import json
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

BOT = Path(__file__).resolve().parents[2]
CACHE = BOT / "data" / "hivemind" / "basemap"
SYMS = ["BTC", "ETH", "SOL", "HYPE", "XRP", "NEAR"]


def _fetch(sym, start_ms):
    import hl
    raw = hl.candles(sym, "4h", start_ms)
    return pd.DataFrame([{"t": int(b["t"]), "h": float(b["h"]), "l": float(b["l"]), "c": float(b["c"])}
                         for b in raw]).sort_values("t").reset_index(drop=True)


def _hist_df(sym):
    p = CACHE / f"{sym}_4h.json"
    if p.exists() and time.time() - p.stat().st_mtime < 20 * 3600:
        return pd.read_json(p)
    df = _fetch(sym, 0)
    CACHE.mkdir(parents=True, exist_ok=True)
    df.to_json(p)
    return df


def feats(df):
    c, h, l = df["c"], df["h"], df["l"]
    e20, e50 = c.ewm(span=20, adjust=False).mean(), c.ewm(span=50, adjust=False).mean()
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    up, dn = h.diff(), -l.diff()
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean().replace(0, np.nan)
    pdi = pd.Series(np.where((up > dn) & (up > 0), up, 0.0)).ewm(alpha=1 / 14, adjust=False).mean() / atr
    mdi = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0)).ewm(alpha=1 / 14, adjust=False).mean() / atr
    return pd.DataFrame({"structure_4h": np.where(e20 > e50, 1, -1), "stretch_4h": np.where(c > e20, 1, -1),
                         "driver_4h": np.where(pdi > mdi, 1, -1), "pdi": pdi, "mdi": mdi})


def live(sym):
    df = _fetch(sym, (int(time.time() // 86400) - 45) * 86_400_000)
    f = feats(df).iloc[-1]
    return {"structure_4h": int(f["structure_4h"]), "stretch_4h": int(f["stretch_4h"]),
            "driver_4h": int(f["driver_4h"]), "pdi": round(float(f["pdi"]) * 100, 0), "mdi": round(float(f["mdi"]) * 100, 0)}


def history(fwd_bars=6):
    rows = []
    for sym in SYMS:
        df = _hist_df(sym)
        df = df[df["t"] + 4 * 3600 * 1000 <= time.time() * 1000].reset_index(drop=True)   # closed bars only
        f = feats(df)
        ret = (df["c"].shift(-fwd_bars) / df["c"] - 1) * 1e4
        day = (df["t"] // 86_400_000).astype(int)
        for i in range(50, len(df) - fwd_bars):
            for k in ("structure_4h", "stretch_4h", "driver_4h"):
                rows.append((k, int(day.iloc[i]), int(f[k].iloc[i]), float(ret.iloc[i])))
    out = {}
    drift = float(np.mean([r[3] for r in rows]))
    for k in ("structure_4h", "stretch_4h", "driver_4h"):
        sub = [(d, r * (x - drift)) for kk, d, r, x in rows if kk == k]
        vals = np.array([v for _, v in sub])
        days = np.array([d for d, _ in sub])
        u = np.unique(days)
        g = {b: vals[days == b] for b in u}
        rnd = np.random.default_rng(2)
        means = sorted(float(np.concatenate([g[b] for b in rnd.choice(u, len(u))]).mean()) for _ in range(600))
        out[k] = {"n": int(len(vals)), "n_eff": int(len(u)), "mean_bps_1d": round(float(vals.mean()), 1),
                  "ci95": [round(means[15], 1), round(means[584], 1)],
                  "since": pd.to_datetime(min(days), unit="D").strftime("%Y-%m-%d")}
    return out


if __name__ == "__main__":
    print(json.dumps(history(), indent=1))
    print(live("SOL"))
