"""RQ13: BTC -> alt lead-lag test at 1-6h horizons.

Data: Hyperliquid 1h candles for all symbols (Binance geo-blocked 451; binance.us too thin
-> stale closes would fabricate lead-lag). HL history depth ~5000 candles: 2025-12-05 -> 2026-07-01.
Tests:
  1. Cross-correlation corr(btc_ret[t], alt_ret[t+k]) k=0..6, and reverse (alt leads BTC).
  2. Event study: BTC 1h move > +1% / < -1% -> signed alt forward returns 1..6h,
     vs unconditional baseline, with t-stats, hit rates, fragility (drop best obs).
  3. Residual after hedging BTC: alt_fwd - beta*btc_fwd (is it alt-specific or just BTC momentum?).
Era split: E1 Dec25-Feb26, E2 Mar-Apr26, E3 May-Jun26.
Regime split: BTC 24h realized vol above/below median; BTC above/below 50h SMA.
Fees: HL taker 0.045%/side -> 0.09% RT + ~0.03% slip = 0.12% hurdle.
"""
import json, math, time, sys
import urllib.request
import numpy as np
import pandas as pd

MS_H = 3600_000
START = int(pd.Timestamp("2025-12-01", tz="UTC").timestamp() * 1000)
END   = int(pd.Timestamp("2026-07-01", tz="UTC").timestamp() * 1000)

def hl_1h(coin):
    rows, start = [], START
    while start < END:
        req = json.dumps({"type": "candleSnapshot",
                          "req": {"coin": coin, "interval": "1h",
                                  "startTime": start, "endTime": END}}).encode()
        r = urllib.request.Request("https://api.hyperliquid.xyz/info", data=req,
                                   headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(r, timeout=30) as resp:
            batch = json.loads(resp.read())
        if not batch:
            break
        rows += batch
        nxt = batch[-1]["t"] + MS_H
        if nxt <= start:
            break
        start = nxt
        time.sleep(0.2)
    df = pd.DataFrame([(b["t"], float(b["c"])) for b in rows], columns=["t", "close"])
    return df.drop_duplicates("t").set_index("t")["close"]

print("fetching...", flush=True)
px = {}
for s in ["BTC", "ETH", "SOL", "XRP", "HYPE"]:
    px[s] = hl_1h(s)
    print(s, len(px[s]), flush=True)

df = pd.DataFrame(px)
df.index = pd.to_datetime(df.index, unit="ms", utc=True)
ret = np.log(df / df.shift(1))

ALTS = ["ETH", "SOL", "XRP", "HYPE"]
ERAS = {"E1_Dec25-Feb26": ("2025-12-05", "2026-03-01"),
        "E2_Mar-Apr26": ("2026-03-01", "2026-05-01"),
        "E3_May-Jun26": ("2026-05-01", "2026-07-01")}

# regimes
rvol = ret["BTC"].rolling(24).std()
sma50 = df["BTC"].rolling(50).mean()
REGIMES = {"hivol": rvol > rvol.median(), "lovol": rvol <= rvol.median(),
           "uptrend": df["BTC"] > sma50, "downtrend": df["BTC"] <= sma50}

def xcorr(sub):
    out = {}
    for a in ALTS:
        out[a] = {f"btc_leads_{k}h": round(sub["BTC"].corr(sub[a].shift(-k)), 4) for k in range(0, 7)}
        out[a]["alt_leads_1h"] = round(sub[a].corr(sub["BTC"].shift(-1)), 4)
    return out

def event_study(sub, thresh=0.01, mask=None):
    """Signed: after BTC moves > +1% go with; < -1% go with (short). Forward alt ret aligned to BTC sign.
    Forward sums computed on contiguous frame BEFORE any mask, so regime masks don't corrupt them."""
    res = {}
    sign = np.sign(sub["BTC"])
    ev = sub["BTC"].abs() > thresh
    if mask is not None:
        ev = ev & mask.reindex(sub.index).fillna(False)
    n_ev = int(ev.sum())
    for a in ALTS:
        row = {"n": n_ev}
        for k in [1, 2, 3, 6]:
            fwd = sub[a].shift(-1).rolling(k).sum().shift(-(k - 1))  # sum t+1..t+k
            sig = (fwd * sign)[ev].dropna()
            if len(sig) < 5:
                row[f"{k}h"] = None
                continue
            m, s, n = sig.mean(), sig.std(), len(sig)
            t = m / (s / math.sqrt(n)) if s > 0 else 0
            hit = (sig > 0).mean()
            # fragility: drop best obs
            frag = sig.drop(sig.idxmax()).mean()
            row[f"{k}h"] = {"mean_bps": round(m * 1e4, 1), "t": round(t, 2), "n": n,
                            "hit": round(hit, 3), "drop_best_bps": round(frag * 1e4, 1)}
        res[a] = row
    return res

def residual_study(sub, thresh=0.01, k=3):
    """After event, alt fwd minus beta*BTC fwd (beta from full sub contemporaneous OLS)."""
    res = {}
    sign = np.sign(sub["BTC"])
    ev = sub["BTC"].abs() > thresh
    btc_fwd = sub["BTC"].shift(-1).rolling(k).sum().shift(-(k - 1))
    for a in ALTS:
        both = pd.concat([sub[a], sub["BTC"]], axis=1).dropna()
        beta = both.iloc[:, 0].cov(both.iloc[:, 1]) / both.iloc[:, 1].var()
        fwd = sub[a].shift(-1).rolling(k).sum().shift(-(k - 1))
        resid = ((fwd - beta * btc_fwd) * sign)[ev].dropna()
        if len(resid) < 5:
            res[a] = None
            continue
        m, s, n = resid.mean(), resid.std(), len(resid)
        t = m / (s / math.sqrt(n)) if s > 0 else 0
        res[a] = {"beta": round(beta, 2), "resid_mean_bps": round(m * 1e4, 1),
                  "t": round(t, 2), "n": n, "hit": round((resid > 0).mean(), 3)}
    return res

out = {"full": {"xcorr": xcorr(ret), "event_1pct": event_study(ret),
                "event_2pct": event_study(ret, 0.02), "residual_3h": residual_study(ret)}}
for name, (a, b) in ERAS.items():
    sub = ret.loc[a:b]
    out[name] = {"xcorr": xcorr(sub), "event_1pct": event_study(sub),
                 "residual_3h": residual_study(sub)}
for name, mask in REGIMES.items():
    out[name] = {"event_1pct": event_study(ret, mask=mask)}

with open(r"C:\Users\vince\WAGMI\bot\tools\research\rq13_results.json", "w") as f:
    json.dump(out, f, indent=1, default=str)
print("done", flush=True)
