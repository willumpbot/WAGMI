"""
BT_ADX_SURVIVOR — forward-validate the one missed-EV survivor:
trend-direction continuation entries in confirmed high-ADX trends.

Method:
- 1h candles from Hyperliquid public API for BTC/ETH/SOL/HYPE/XRP.
- ADX(14) Wilder, +DI/-DI, EMA20, ATR(14).
- Entry (long example): trend dir = +DI> -DI; previous close above EMA20,
  current bar low touches EMA20 -> fill at EMA20. Mirror for shorts.
- Stop = 1.5*ATR(14) at entry (1R). Trim 50% at +1R, stop->breakeven,
  trail rest with close - 2*ATR chandelier. Max hold 72 bars.
- Conservative intrabar: stop checked BEFORE target on same bar.
- Treatment: entry bar inside confirmed high-ADX window (ADX>=thr for
  >=3 consecutive bars). Control: all entries regardless of ADX.
- Fees: 0.06%/side (taker+slip) converted to R at trade level.

Outputs aggregate stats per window type, symbol, week; window
concentration; ADX threshold sweep; extended out-of-sample span.
"""
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone

import numpy as np
import pandas as pd

API = "https://api.hyperliquid.xyz/info"
SYMBOLS = ["BTC", "ETH", "SOL", "HYPE", "XRP"]
FEE_PCT_PER_SIDE = 0.06  # taker + slippage, percent of notional


def fetch_candles(coin, start_ms, end_ms):
    body = json.dumps({
        "type": "candleSnapshot",
        "req": {"coin": coin, "interval": "1h",
                "startTime": int(start_ms), "endTime": int(end_ms)},
    }).encode()
    req = urllib.request.Request(API, data=body,
                                 headers={"Content-Type": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
            break
        except Exception as e:
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))
    df = pd.DataFrame(data)
    if df.empty:
        return df
    df = df.rename(columns={"t": "ts", "o": "open", "h": "high",
                            "l": "low", "c": "close", "v": "vol"})
    for c in ["open", "high", "low", "close", "vol"]:
        df[c] = df[c].astype(float)
    df["dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df[["ts", "dt", "open", "high", "low", "close", "vol"]].sort_values("ts").reset_index(drop=True)


def wilder_smooth(s, n):
    return s.ewm(alpha=1.0 / n, adjust=False).mean()


def add_indicators(df, adx_n=14, ema_n=20, atr_n=14):
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    up = h.diff()
    dn = -l.diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    atr_w = wilder_smooth(tr, adx_n)
    pdi = 100 * wilder_smooth(pd.Series(plus_dm, index=df.index), adx_n) / atr_w
    mdi = 100 * wilder_smooth(pd.Series(minus_dm, index=df.index), adx_n) / atr_w
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    adx = wilder_smooth(dx.fillna(0), adx_n)
    df["atr"] = wilder_smooth(tr, atr_n)
    df["ema20"] = c.ewm(span=ema_n, adjust=False).mean()
    df["pdi"], df["mdi"], df["adx"] = pdi, mdi, adx
    return df


def label_windows(df, thr, confirm=3):
    """Contiguous ADX>=thr runs; 'confirmed' from the confirm-th bar of the run."""
    hi = (df["adx"] >= thr).values
    win_id = np.full(len(df), -1)
    confirmed = np.zeros(len(df), bool)
    wid, run = -1, 0
    for i in range(len(df)):
        if hi[i]:
            if run == 0:
                wid += 1
            run += 1
            win_id[i] = wid
            if run >= confirm:
                confirmed[i] = True
        else:
            run = 0
    df["win_id"] = win_id
    df["confirmed_hi_adx"] = confirmed
    return df


def simulate(df, sym, stop_mult=1.5, trail_mult=2.0, max_hold=72,
             eval_start=None, eval_end=None):
    """One position at a time. Returns list of trade dicts (all entries;
    each tagged with in_window at entry)."""
    trades = []
    i = 30  # warmup
    n = len(df)
    while i < n - 1:
        row = df.iloc[i]
        prev = df.iloc[i - 1]
        if eval_start is not None and row["dt"] < eval_start:
            i += 1
            continue
        if eval_end is not None and row["dt"] >= eval_end:
            break
        d = 1 if row["pdi"] > row["mdi"] else -1
        ema = row["ema20"]
        touch = (prev["close"] > prev["ema20"] and row["low"] <= ema) if d == 1 \
            else (prev["close"] < prev["ema20"] and row["high"] >= ema)
        if not touch or np.isnan(row["atr"]) or row["atr"] <= 0:
            i += 1
            continue
        entry = ema
        risk = stop_mult * row["atr"]
        stop = entry - d * risk
        in_window = bool(row["confirmed_hi_adx"])
        adx_at_entry = row["adx"]
        win_id = int(row["win_id"])
        trimmed = False
        pnl_r = 0.0
        size = 1.0
        hi_close = entry
        exit_i = None
        # entry bar itself: conservative — check stop first on the remainder of the bar
        j = i
        while j < n:
            b = df.iloc[j]
            # stop check (conservative: before target)
            hit_stop = (b["low"] <= stop) if d == 1 else (b["high"] >= stop)
            if j == i:
                # on entry bar, only count stop if bar range crosses it (it may,
                # since we fill mid-bar); conservative = allow
                pass
            if hit_stop:
                pnl_r += size * d * (stop - entry) / risk
                exit_i = j
                break
            if not trimmed:
                tgt = entry + d * risk
                hit_tgt = (b["high"] >= tgt) if d == 1 else (b["low"] <= tgt)
                if hit_tgt:
                    pnl_r += 0.5 * 1.0  # +1R on half
                    size = 0.5
                    stop = entry  # breakeven
                    trimmed = True
            # trail update (after trim), using closes
            if trimmed:
                if d == 1:
                    hi_close = max(hi_close, b["close"])
                    stop = max(stop, hi_close - trail_mult * b["atr"])
                else:
                    hi_close = min(hi_close, b["close"])
                    stop = min(stop, hi_close + trail_mult * b["atr"])
            if j - i >= max_hold:
                pnl_r += size * d * (b["close"] - entry) / risk
                exit_i = j
                break
            j += 1
        if exit_i is None:
            exit_i = n - 1
            b = df.iloc[exit_i]
            pnl_r += size * d * (b["close"] - entry) / risk
        # fees: round trip on full notional, in R units
        fee_r = (2 * FEE_PCT_PER_SIDE / 100.0) * entry / risk
        trades.append({
            "symbol": sym, "dt": row["dt"], "dir": d, "entry": entry,
            "risk_pct": 100 * risk / entry, "adx": adx_at_entry,
            "in_window": in_window, "win_id": win_id,
            "pnl_r_gross": pnl_r, "pnl_r_net": pnl_r - fee_r,
            "hold": exit_i - i, "week": row["dt"].strftime("%G-W%V"),
        })
        i = exit_i + 1  # no overlap
    return trades


def agg(tr):
    if len(tr) == 0:
        return dict(n=0, wr=np.nan, exp_g=np.nan, exp_n=np.nan, tot_n=0.0)
    p = np.array([t["pnl_r_net"] for t in tr])
    g = np.array([t["pnl_r_gross"] for t in tr])
    return dict(n=len(tr), wr=100 * (p > 0).mean(), exp_g=g.mean(),
                exp_n=p.mean(), tot_n=p.sum())


def fmt(a):
    if a["n"] == 0:
        return "n=0"
    return (f"n={a['n']:>3}  WR={a['wr']:5.1f}%  expG={a['exp_g']:+.3f}R  "
            f"expNET={a['exp_n']:+.3f}R  totNET={a['tot_n']:+.2f}R")


def main():
    thr = float(sys.argv[1]) if len(sys.argv) > 1 else 25.0
    span = sys.argv[2] if len(sys.argv) > 2 else "primary"  # primary|extended
    now_ms = int(time.time() * 1000)
    if span == "primary":
        eval_start = pd.Timestamp("2026-05-30", tz="UTC")
        fetch_start = pd.Timestamp("2026-05-15", tz="UTC")
    else:
        eval_start = pd.Timestamp("2026-01-01", tz="UTC")
        fetch_start = pd.Timestamp("2025-12-01", tz="UTC")
    eval_end = pd.Timestamp("2026-07-02", tz="UTC")

    all_tr = []
    for sym in SYMBOLS:
        df = fetch_candles(sym, fetch_start.value // 10**6, now_ms)
        if df.empty:
            print(f"!! no candles for {sym}")
            continue
        df = add_indicators(df)
        df = label_windows(df, thr)
        tr = simulate(df, sym, eval_start=eval_start, eval_end=eval_end)
        all_tr.extend(tr)
        print(f"{sym}: {len(df)} bars {df['dt'].iloc[0]:%m-%d}->{df['dt'].iloc[-1]:%m-%d %H:%M}, "
              f"{int((df['adx']>=thr).sum())} hiADX bars, {len(tr)} entries")

    treat = [t for t in all_tr if t["in_window"]]
    ctrl_out = [t for t in all_tr if not t["in_window"]]
    print(f"\n=== ADX thr={thr} span={span} eval {eval_start:%Y-%m-%d}->{eval_end:%Y-%m-%d} ===")
    print("TREATMENT (confirmed hiADX):", fmt(agg(treat)))
    print("ALL entries (control)     :", fmt(agg(all_tr)))
    print("OUT-of-window only        :", fmt(agg(ctrl_out)))

    print("\nPer symbol (treatment | out-of-window):")
    for sym in SYMBOLS:
        print(f"  {sym:4} T: {fmt(agg([t for t in treat if t['symbol']==sym]))}")
        print(f"       O: {fmt(agg([t for t in ctrl_out if t['symbol']==sym]))}")

    print("\nPer week (treatment):")
    for wk in sorted({t["week"] for t in treat}):
        print(f"  {wk}  {fmt(agg([t for t in treat if t['week']==wk]))}")
    print("Per week (out-of-window):")
    for wk in sorted({t["week"] for t in ctrl_out}):
        print(f"  {wk}  {fmt(agg([t for t in ctrl_out if t['week']==wk]))}")

    print("\nPer direction (treatment):")
    for d, lbl in [(1, "LONG"), (-1, "SHORT")]:
        print(f"  {lbl:5} {fmt(agg([t for t in treat if t['dir']==d]))}")

    # window concentration
    from collections import defaultdict
    wpnl = defaultdict(float)
    wn = defaultdict(int)
    for t in treat:
        k = (t["symbol"], t["win_id"])
        wpnl[k] += t["pnl_r_net"]
        wn[k] += 1
    tot = sum(wpnl.values())
    pos = sum(v for v in wpnl.values() if v > 0)
    ranked = sorted(wpnl.items(), key=lambda kv: -kv[1])
    print(f"\nWindow concentration: {len(wpnl)} distinct trend windows, "
          f"total {tot:+.2f}R, positive-window sum {pos:+.2f}R")
    for (k, v) in ranked[:6]:
        first = min(t["dt"] for t in treat if (t["symbol"], t["win_id"]) == k)
        print(f"  {k[0]:4} win#{k[1]:<3} {first:%m-%d %H:%M}  trades={wn[k]}  {v:+.2f}R"
              f"  ({100*v/pos if pos>0 else 0:.0f}% of positive sum)")

    # dump trades for inspection
    out = f"C:/Users/vince/WAGMI/bot/tools/backtests/adx_trades_{span}_thr{int(thr)}.csv"
    pd.DataFrame(all_tr).to_csv(out, index=False)
    print(f"\ntrades -> {out}")


if __name__ == "__main__":
    main()
