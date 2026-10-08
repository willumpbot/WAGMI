"""Base-rate map: how the CURRENT combination of daily readings behaved next.

For every day in each coin's Hyperliquid daily history, compute the same four
readings the desk shows (using only candles closed by that day):
  structure  UP if EMA20 > EMA50 else DOWN
  stretch    price ABOVE or BELOW its EMA20
  range      LOW / MID / HIGH third of the trailing 20-day high-low range
  driver     BUYERS if +DI > -DI else SELLERS
and record the forward 5- and 10-day returns. lookup() returns the history of
today's combination, pooled across the six coins and for the coin alone.

This is a base rate, not a prediction: overlapping windows mean consecutive
days are not independent, so n_eff ~= n / 5 is reported alongside n.
The table is rebuilt at most once a day (cached under data/hivemind/).
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
HORIZONS = (5, 10)
REBUILD_S = 20 * 3600


def _daily(sym):
    path = CACHE / f"{sym}_1d.json"
    if path.exists() and time.time() - path.stat().st_mtime < REBUILD_S:
        raw = json.loads(path.read_text())
    else:
        body = json.dumps({"type": "candleSnapshot", "req": {
            "coin": sym, "interval": "1d", "startTime": 0, "endTime": int(time.time() * 1000)}}).encode()
        req = urllib.request.Request("https://api.hyperliquid.xyz/info", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = json.loads(r.read())
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(raw))
    df = pd.DataFrame([{"t": int(b["t"]), "o": float(b["o"]), "h": float(b["h"]), "l": float(b["l"]),
                        "c": float(b["c"])} for b in raw]).sort_values("t").reset_index(drop=True)
    return df


def _closed(df):
    """Drop today's still-forming candle."""
    if len(df) and df["t"].iloc[-1] + 86_400_000 > time.time() * 1000:
        return df.iloc[:-1]
    return df


def features(df):
    c, h, l = df["c"], df["h"], df["l"]
    ema20, ema50 = c.ewm(span=20, adjust=False).mean(), c.ewm(span=50, adjust=False).mean()
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    up, dn = h.diff(), -l.diff()
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean().replace(0, np.nan)
    pdi = pd.Series(pdm).ewm(alpha=1 / 14, adjust=False).mean() / atr
    mdi = pd.Series(mdm).ewm(alpha=1 / 14, adjust=False).mean() / atr
    hi20, lo20 = h.rolling(20).max(), l.rolling(20).min()
    pos = (c - lo20) / (hi20 - lo20)
    f = pd.DataFrame({
        "structure": np.where(ema20 > ema50, "UP", "DOWN"),
        "stretch": np.where(c > ema20, "ABOVE", "BELOW"),
        "range": np.where(pos < 1 / 3, "LOW", np.where(pos > 2 / 3, "HIGH", "MID")),
        "driver": np.where(pdi > mdi, "BUYERS", "SELLERS"),
        "atr_pct": tr.rolling(14).mean() / c * 100,
    })
    for hz in HORIZONS:
        f[f"r{hz}"] = (c.shift(-hz) / c - 1) * 100
    f["valid"] = np.arange(len(df)) >= 50   # EMA50 warm-up
    return f


def _key(row):
    return f"{row['structure']}|{row['stretch']}|{row['range']}|{row['driver']}"


def _stats(vals):
    v = np.array([x for x in vals if x == x])
    if len(v) == 0:
        return {"n": 0}
    return {"n": int(len(v)), "n_eff": int(len(v) // 5), "up_pct": round(float((v > 0).mean() * 100), 1),
            "median_pct": round(float(np.median(v)), 2), "p25_pct": round(float(np.percentile(v, 25)), 2),
            "p75_pct": round(float(np.percentile(v, 75)), 2)}


def build():
    table, latest = {}, {}
    for sym in SYMS:
        raw = _daily(sym)
        df = _closed(raw)
        f = features(df)
        f = f[f["valid"]]
        if len(f):
            latest[sym] = {k: f.iloc[-1][k] for k in ("structure", "stretch", "range", "driver")}
            latest[sym]["atr_pct"] = round(float(f.iloc[-1]["atr_pct"]), 2)
            latest[sym]["since"] = pd.to_datetime(df["t"].iloc[50], unit="ms").strftime("%Y-%m-%d")
        for _, row in f.iterrows():
            k = _key(row)
            for hz in HORIZONS:
                v = row[f"r{hz}"]
                if v == v:
                    table.setdefault(k, {}).setdefault(sym, {}).setdefault(hz, []).append(float(v))
    out = {"built": time.time(), "latest": latest, "keys": {}}
    for k, per in table.items():
        out["keys"][k] = {f"{hz}d": {"all": _stats([x for s in per.values() for x in s.get(hz, [])]),
                                     **{s: _stats(per[s].get(hz, [])) for s in per}} for hz in HORIZONS}
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "table.json").write_text(json.dumps(out), encoding="utf-8")
    return out


def _table():
    p = CACHE / "table.json"
    if p.exists() and time.time() - p.stat().st_mtime < REBUILD_S:
        return json.loads(p.read_text(encoding="utf-8"))
    return build()


def live_state(sym):
    """Today's combination using the still-forming daily candle at the current price."""
    path = CACHE / f"{sym}_live.json"
    body = json.dumps({"type": "candleSnapshot", "req": {
        "coin": sym, "interval": "1d", "startTime": int((time.time() - 120 * 86400) * 1000),
        "endTime": int(time.time() * 1000)}}).encode()
    req = urllib.request.Request("https://api.hyperliquid.xyz/info", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = json.loads(r.read())
    df = pd.DataFrame([{"t": int(b["t"]), "o": float(b["o"]), "h": float(b["h"]), "l": float(b["l"]),
                        "c": float(b["c"])} for b in raw]).sort_values("t").reset_index(drop=True)
    f = features(df)
    return {k: f.iloc[-1][k] for k in ("structure", "stretch", "range", "driver")}


def lookup(sym, market=None):
    t = _table()
    cur = t["latest"].get(sym)
    if not cur:
        return {"note": "no history for this coin"}
    try:
        cur = {**cur, **live_state(sym)}   # judge today's tape, not yesterday's close
        basis = "live (today's forming daily candle)"
    except Exception:
        basis = "last daily close (live fetch failed)"
    k = _key(cur)
    rec = t["keys"].get(k, {})
    words = {"UP": "uptrend structure", "DOWN": "downtrend structure", "ABOVE": "above its 20d avg",
             "BELOW": "below its 20d avg", "LOW": "lower third of its 20d range", "MID": "middle of its 20d range",
             "HIGH": "upper third of its 20d range", "BUYERS": "buyers driving", "SELLERS": "sellers driving"}
    return {
        "state": k, "state_words": ", ".join(words[x] for x in k.split("|")),
        "state_basis": basis, "history_since": cur.get("since"),
        "next_5d": rec.get("5d", {}).get("all"), "next_5d_this_coin": rec.get("5d", {}).get(sym),
        "next_10d": rec.get("10d", {}).get("all"), "next_10d_this_coin": rec.get("10d", {}).get(sym),
        "atr_pct_1d": cur.get("atr_pct"),
        "caveat": "base rate from overlapping daily windows (n_eff ~= n/5); describes the past, not a forecast",
    }


if __name__ == "__main__":
    b = build()
    for s in SYMS:
        print(s, json.dumps(lookup(s))[:400])
