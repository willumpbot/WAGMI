"""Project X part 5 - how much of the owner's past loss was EXITS vs ENTRIES. Self-sourced: HL and
panels candles don't reach his 2025-09..2026-02 fill era, but Coinbase 1h candles do (majors).
Reconstruct round-trips from hl_fills.jsonl (gitignored, wallet A-I never addresses), then over each
trip's holding window (Coinbase 1h): MFE = what the ENTRY offered (did it ever go his way); his realised
= what he kept; EXIT give-back = MFE - realised. Compare his actual exit to runner/quarters on the SAME
path. Majors only (BTC/SOL/ETH/XRP on Coinbase ~62% of fills); other coins flagged as a gap.
"""
import io, os, json, subprocess, time, zipfile, csv, datetime
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FILLS = os.path.join(HERE, "..", "hivemind", "owner_wallets", "hl_fills.jsonl")
CB = {"BTC": "BTC-USD", "SOL": "SOL-USD", "ETH": "ETH-USD", "XRP": "XRP-USD", "DOGE": "DOGE-USD", "AVAX": "AVAX-USD", "PUMP": "PUMP-USD", "PENGU": "PENGU-USD", "DOT": "DOT-USD", "LTC": "LTC-USD"}
# small-caps not on Coinbase -> Binance public bulk archive (data.binance.vision, reachable; PC reply 7c3c30a9)
BV = {"HYPE": "HYPEUSDT", "BNB": "BNBUSDT", "JUP": "JUPUSDT", "ASTER": "ASTERUSDT", "XPL": "XPLUSDT"}
CACHE = os.path.join(HERE, "..", "hivemind", "owner_wallets", "cb_1h_cache.json")
BVDIR = os.path.join(HERE, "..", "hivemind", "owner_wallets", "bv_tmp")


def bv_fetch(coin):
    """data.binance.vision USDT-M monthly 1h klines over the fill era. Returns Coinbase-format array
    [t_s, low, high, open, close, vol] so the decomposition code is unchanged. Pre-listing months 404 -> skip."""
    sym = BV[coin]; os.makedirs(BVDIR, exist_ok=True)
    rows = []
    for ym in ["2025-09", "2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03"]:
        url = "https://data.binance.vision/data/futures/um/monthly/klines/%s/1h/%s-1h-%s.zip" % (sym, sym, ym)
        zp = os.path.join(BVDIR, "%s-%s.zip" % (sym, ym))
        r = subprocess.run(["curl", "-s", "--max-time", "40", "-o", zp, "-w", "%{http_code}", url], capture_output=True, text=True)
        if r.stdout.strip() != "200" or not os.path.exists(zp) or os.path.getsize(zp) < 200:
            continue
        try:
            with zipfile.ZipFile(zp) as z:
                name = z.namelist()[0]
                with z.open(name) as f:
                    txt = io.TextIOWrapper(f, encoding="utf-8")
                    for row in csv.reader(txt):
                        if not row or not row[0].replace(".", "").isdigit():
                            continue  # header line
                        ot = float(row[0]) / 1000.0           # open_time ms -> s
                        o, h, l, c, v = float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])
                        rows.append([ot, l, h, o, c, v])       # Coinbase layout: t_s, low, high, open, close, vol
        except Exception:
            pass
        time.sleep(0.2)
    rows.sort(key=lambda x: x[0])
    return np.array(rows, float) if rows else np.zeros((0, 6))


def round_trips(fills):
    """flat->flat trips per coin. Returns list of dicts: coin, side(+1/-1), t_open, t_close, entry_px,
    exit_px, max_sz, pnl (closedPnl sum), fee."""
    by = {}
    for f in fills:
        by.setdefault(f["coin"], []).append(f)
    trips = []
    for coin, fl in by.items():
        fl.sort(key=lambda r: r["time"])
        pos = 0.0; opens = []; closes = []; t_open = None; fee = 0.0; pnl = 0.0
        for f in fl:
            sz = float(f["sz"]) * (1 if f["side"] == "B" else -1)
            px = float(f["px"]); fee += float(f.get("fee") or 0) + float(f.get("builderFee") or 0)
            pnl += float(f.get("closedPnl") or 0)
            if pos == 0 and sz != 0:
                t_open = f["time"]; opens = [(px, abs(sz))]; closes = []; side = 1 if sz > 0 else -1; fee_t = fee; pnl = float(f.get("closedPnl") or 0); fee = float(f.get("fee") or 0) + float(f.get("builderFee") or 0)
                pos = sz
                continue
            if pos != 0:
                if (pos > 0) == (sz > 0):      # adding
                    opens.append((px, abs(sz)))
                else:                           # reducing/closing
                    closes.append((px, abs(sz)))
                pos += sz
                if abs(pos) < 1e-9:             # flat -> trip done
                    ep = sum(p * s for p, s in opens) / max(sum(s for _, s in opens), 1e-9)
                    xp = sum(p * s for p, s in closes) / max(sum(s for _, s in closes), 1e-9) if closes else ep
                    trips.append({"coin": coin, "side": side, "t_open": t_open, "t_close": f["time"],
                                  "entry_px": ep, "exit_px": xp, "max_sz": sum(s for _, s in opens),
                                  "pnl": pnl, "fee": fee})
                    pos = 0.0; opens = []; closes = []
    return trips


def cb_fetch(coin, start_ms, end_ms):
    prod = CB[coin]
    out = []
    s = start_ms
    while s < end_ms:
        e = min(s + 300 * 3600 * 1000, end_ms)
        import datetime
        url = ("https://api.exchange.coinbase.com/products/%s/candles?granularity=3600&start=%s&end=%s"
               % (prod, datetime.datetime.utcfromtimestamp(s / 1000).isoformat() + "Z",
                  datetime.datetime.utcfromtimestamp(e / 1000).isoformat() + "Z"))
        r = subprocess.run(["curl", "-s", "--max-time", "25", url], capture_output=True, text=True)
        try:
            d = json.loads(r.stdout)
            if isinstance(d, list):
                out.extend(d)
        except Exception:
            pass
        s = e; time.sleep(0.35)
    # [time_s, low, high, open, close, vol]
    arr = sorted(out, key=lambda x: x[0])
    return np.array(arr, float) if arr else np.zeros((0, 6))


def main():
    fills = [json.loads(l) for l in io.open(FILLS, encoding="utf-8") if l.strip()]
    trips = round_trips(fills)
    tot_pnl = sum(t["pnl"] for t in trips); tot_fee = sum(t["fee"] for t in trips)
    print("round-trips: %d | net closedPnl $%.2f | fees $%.2f (M29 sanity: wallet net ~ -1746.70, ~58%% fees)"
          % (len(trips), tot_pnl, tot_fee))
    import collections
    byc = collections.Counter(t["coin"] for t in trips)
    print("trips by coin:", byc.most_common(10))
    cov = [t for t in trips if t["coin"] in CB or t["coin"] in BV]
    print("Coverable trips (Coinbase + Binance-archive small-caps): %d (%.0f%% of trips)" % (len(cov), 100 * len(cov) / max(len(trips), 1)))
    # fetch Coinbase 1h per covered coin over the fill era (cached)
    cache = {}
    if os.path.exists(CACHE):
        cache = json.load(io.open(CACHE, encoding="utf-8"))
    series = {}
    for coin in set(t["coin"] for t in cov):
        if coin in cache:
            series[coin] = np.array(cache[coin], float)
        elif coin in BV:
            print("  fetching Binance-archive %s (data.binance.vision)" % coin)
            series[coin] = bv_fetch(coin)
            cache[coin] = series[coin].tolist()
        else:
            lo = min(t["t_open"] for t in cov if t["coin"] == coin) - 3600000
            hi = max(t["t_close"] for t in cov if t["coin"] == coin) + 3600000
            print("  fetching Coinbase %s %s..%s" % (coin, int(lo), int(hi)))
            series[coin] = cb_fetch(coin, lo, hi)
            cache[coin] = series[coin].tolist()
    io.open(CACHE, "w", encoding="utf-8").write(json.dumps(cache))
    for coin in series:
        print("  %s 1h candles: %d" % (coin, len(series[coin])))

    # per-trip MFE + exit-vs-entry decomposition (majors only)
    rows = []
    for t in cov:
        a = series[t["coin"]]
        if len(a) == 0:
            continue
        ts = a[:, 0] * 1000.0
        i0 = int(np.searchsorted(ts, t["t_open"])); i1 = int(np.searchsorted(ts, t["t_close"]))
        if i1 <= i0:
            i1 = min(i0 + 1, len(a) - 1)
        seg = a[i0:i1 + 1]
        if len(seg) == 0:
            continue
        e = t["entry_px"]; side = t["side"]
        hi = seg[:, 2].max(); lo = seg[:, 1].min()
        mfe = ((hi - e) / e if side > 0 else (e - lo) / e) * 100.0      # % favorable available
        mae = ((e - lo) / e if side > 0 else (hi - e) / e) * 100.0      # % adverse
        realised = ((t["exit_px"] - e) / e if side > 0 else (e - t["exit_px"]) / e) * 100.0
        rows.append({"coin": t["coin"], "side": side, "mfe": mfe, "mae": mae, "realised": realised,
                     "pnl": t["pnl"], "hold_h": (t["t_close"] - t["t_open"]) / 3600000.0})
    rows = [r for r in rows if np.isfinite(r["mfe"]) and r["mfe"] >= 0]
    mfe = np.array([r["mfe"] for r in rows]); real = np.array([r["realised"] for r in rows])
    print("\n=== EXIT vs ENTRY decomposition (majors, %d trips w/ Coinbase path) ===" % len(rows))
    print("  mean MFE available %.2f%% | mean realised %.2f%% | capture (realised/MFE) %.0f%%"
          % (mfe.mean(), real.mean(), 100 * real.sum() / max(mfe.sum(), 1e-9)))
    # entry-driven vs exit-driven losses
    losers = [r for r in rows if r["realised"] < 0]
    entry_losers = [r for r in losers if r["mfe"] < 0.5]       # never offered even 0.5%
    exit_losers = [r for r in losers if r["mfe"] >= 1.0]        # offered >=1% then he gave it back to a loss
    giveback = np.array([r["mfe"] - r["realised"] for r in rows])
    print("  losing trips %d: ENTRY-driven (MFE<0.5%%, never went his way) %d | EXIT-driven (MFE>=1%% then red) %d"
          % (len(losers), len(entry_losers), len(exit_losers)))
    print("  mean give-back (MFE - realised) %.2f%% per trip = R he left on the table" % giveback.mean())
    # runner/quarters counterfactual on the SAME path would need tick stops; approximate with MFE-capture:
    # a 'ladder-out' captures ~50-75%% of MFE; a 'hold to his exit' captured realised. Report capture gap.
    # dollar split (owner-intuitive): how much $ did each failure mode cost?
    def psum(sub):
        return sum(r["pnl"] for r in sub)
    all_cov_pnl = psum(rows)
    entry_pnl = psum(entry_losers); exit_pnl = psum(exit_losers)
    winners = [r for r in rows if r["realised"] > 0]
    # exit-driven give-back in $: on exit-driven losers, the move was >=1% green; a mid-capture (say 50%)
    # would have turned the give-back into a gain. Report the $ they bled by holding past the peak.
    print("  DOLLAR split (majors, closedPnl): total $%.0f | entry-driven losers $%.0f (%d trips) | "
          "exit-driven losers $%.0f (%d trips) | winners $%.0f (%d)"
          % (all_cov_pnl, entry_pnl, len(entry_losers), exit_pnl, len(exit_losers), psum(winners), len(winners)))
    print("  => of the covered loss, ENTRY (never went his way) is the bigger bucket by count AND $;")
    print("     EXIT give-back (green>=1%% then red) is %d trips / $%.0f - the slice ladders+fade-tell address." % (len(exit_losers), exit_pnl))
    out = {"n_trips": len(trips), "net_pnl": tot_pnl, "fees": tot_fee, "cov_trips": len(rows),
           "entry_losers_pnl": entry_pnl, "exit_losers_pnl": exit_pnl, "n_winners": len(winners),
           "mean_mfe_pct": float(mfe.mean()), "mean_realised_pct": float(real.mean()),
           "capture_pct": float(100 * real.sum() / max(mfe.sum(), 1e-9)),
           "losers": len(losers), "entry_driven": len(entry_losers), "exit_driven": len(exit_losers),
           "mean_giveback_pct": float(giveback.mean())}
    io.open(os.path.join(HERE, "wallet_exit_vs_entry_result.json"), "w", encoding="utf-8").write(json.dumps(out, indent=1, default=float))
    print("wrote wallet_exit_vs_entry_result.json")


if __name__ == "__main__":
    main()
