"""Project X - funding-flip FADE LENS (separate exploratory add to the m32c fade atlas; does NOT touch
the sealed M32C_FADE_PREREG composite rule). At the +0.5R bar (strictly pre-peak), does funding predict
fade vs run? Circumstances: funding sign, funding WITH/AGAINST the position (position pays carry or
receives), |funding| magnitude, and a fresh funding FLIP (sign changed in the trailing 24h). Candidate
-only: a clean separation -> note for a future SEALED lens, never a live claim here.
funding_oi_history: (symbol, timestamp ISO, funding_rate, ...); starts 2026-06-06 -> moments before
that are dropped. Point-in-time: funding snapshot at/<= the b05 bar time.
"""
import io, os, json, gzip, sqlite3, datetime
import numpy as np
from m30_run import first_true, sidepaths, HOLD, HOR, SPACING, rng
from m13_build import daily, em_pit, atr_pit, K_STOP

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "crunch", "panels.sqlite")
FUND = os.path.join(HERE, "server_exports", "funding_oi_history.jsonl.gz")


def load_funding():
    by = {}
    with gzip.open(FUND, "rt", encoding="utf-8") as f:
        for l in f:
            if not l.strip():
                continue
            r = json.loads(l)
            s = r.get("symbol")
            try:
                ts = datetime.datetime.fromisoformat(r["timestamp"]).timestamp() * 1000.0
            except Exception:
                continue
            fr = r.get("funding_rate")
            if s is None or fr is None:
                continue
            by.setdefault(s, []).append((ts, float(fr)))
    out = {}
    for s, v in by.items():
        v.sort()
        out[s] = (np.array([x[0] for x in v]), np.array([x[1] for x in v]))
    return out


def main():
    print("Funding-flip fade lens (exploratory; does NOT touch the sealed prereg).")
    fund = load_funding()
    print("funding symbols: %d (e.g. %s)" % (len(fund), ",".join(list(fund)[:6])))
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    coins = [r[0] for r in c.execute("SELECT DISTINCT coin FROM candles_1h ORDER BY coin")]
    _cap = os.environ.get("M32C_COINS")
    if _cap:
        coins = coins[:int(_cap)]
    LAB, FSIGN, FAGN, FMAG, FFLIP, COIN, DAY = ([] for _ in range(7))
    done = 0
    for coin in coins:
        if coin not in fund:
            continue
        rows = c.execute("SELECT t,h,l,c FROM candles_1h WHERE coin=? ORDER BY t", (coin,)).fetchall()
        if len(rows) < 1000:
            continue
        a = np.asarray(rows, float)
        b = {"t": a[:, 0], "h": a[:, 1], "l": a[:, 2], "c": a[:, 3]}
        day, uq, dh, dl, dc = daily(b)
        em_d, atr_d = em_pit(dc), atr_pit(dh, dl, dc)
        dix = np.searchsorted(uq, day); em_h, atr_h = em_d[dix], atr_d[dix]
        n = len(b["c"])
        elig = np.flatnonzero(np.isfinite(em_h) & np.isfinite(atr_h) & (atr_h > 0))
        elig = elig[(dix[elig] >= 61) & (elig >= 520) & (elig < n - HOR - 2)]
        if len(elig) < 40:
            continue
        off = int(rng.integers(0, SPACING)); ent, last = [], -10**9
        for e in elig:
            if e >= off and e - last >= SPACING:
                ent.append(e); last = e
        ent = np.asarray(ent); sf = K_STOP * em_h[ent]
        pidx = ent[:, None] + np.arange(1, HOR + 1)[None, :]
        entry = b["c"][ent][:, None]
        Hs, Ls, Cs, Ts = b["h"][pidx], b["l"][pidx], b["c"][pidx], b["t"][pidx]
        fts, frate = fund[coin]
        for side in (1.0, -1.0):
            fav, adv, close = sidepaths(entry, Hs, Ls, Cs, side)
            sfc = sf[:, None]
            b05 = first_true(fav >= 0.5 * sfc)
            cols = np.arange(HOLD)[None, :]
            markR = close / sfc
            b15 = first_true(fav >= 1.5 * sfc)
            fade_bar = first_true((markR <= 0) & (cols > b05[:, None]))
            run = (b15 < fade_bar) & (b15 < HOLD); fade = (fade_bar < HOLD) & (fade_bar <= b15)
            lab = np.where(run, 1, np.where(fade, 0, -1))
            t05 = np.take_along_axis(Ts, np.clip(b05, 0, HOR - 1)[:, None], 1)[:, 0]
            fi = np.searchsorted(fts, t05) - 1           # funding snapshot at/<= b05 time
            ok = (b05 < HOLD) & (lab >= 0) & (fi >= 0)
            fr_now = np.where(fi >= 0, frate[np.clip(fi, 0, len(frate) - 1)], np.nan)
            # fresh flip: sign changed vs ~24h earlier snapshot
            fi24 = np.searchsorted(fts, t05 - 24 * 3600 * 1000.0) - 1
            fr_24 = np.where(fi24 >= 0, frate[np.clip(fi24, 0, len(frate) - 1)], np.nan)
            flip = (np.sign(fr_now) != np.sign(fr_24)) & np.isfinite(fr_24)
            # AGAINST = position pays carry: long pays when funding>0; short pays when funding<0
            against = ((side > 0) & (fr_now > 0)) | ((side < 0) & (fr_now < 0))
            for arr, src in ((LAB, lab), (FSIGN, (fr_now > 0).astype(float)), (FAGN, against.astype(float)),
                             (FMAG, np.abs(fr_now)), (FFLIP, flip.astype(float))):
                arr.append(src[ok])
            COIN.extend([coin] * int(ok.sum())); DAY.extend([int(uq[dix[e]]) for e, m in zip(ent, ok) if m])
        done += 1
    c.close()
    LAB = np.concatenate(LAB); FSIGN = np.concatenate(FSIGN); FAGN = np.concatenate(FAGN)
    FMAG = np.concatenate(FMAG); FFLIP = np.concatenate(FFLIP)
    carr = np.asarray(COIN); dayk = np.asarray(DAY, np.int64)
    isfade = (LAB == 0).astype(float); base = float(isfade.mean())
    print("scored +0.5R moments w/ funding: %d (coins %d) | base P(FADE) %.3f" % (len(LAB), done, base))

    def ci(mask):
        v = isfade[mask]; cc = carr[mask]
        if len(v) < 40:
            return float("nan"), float("nan"), float("nan"), int(len(v)), float("nan")
        u = np.unique(cc); g = {x: v[cc == x] for x in u}
        bo = np.array([np.concatenate([g[p] for p in u[rng.integers(0, len(u), len(u))]]).mean() for _ in range(2000)])
        per = np.array([v[cc == x].mean() for x in u if (cc == x).sum() >= 5])
        return float(v.mean()), float(np.percentile(bo, 2.5)), float(np.percentile(bo, 97.5)), int(len(v)), float((per > base).mean())

    def rep(name, buckets):
        print("\n[%s] base %.3f:" % (name, base))
        for bl, mk in buckets:
            m, lo, hi, nn, _ = ci(mk)
            sig = "" if not np.isfinite(lo) else (" <== higher FADE" if lo > base else " <== runs" if hi < base else "")
            print("   %-18s n=%6d P(FADE)=%.3f [%.3f,%.3f]%s" % (bl, nn, m, lo, hi, sig))
    rep("funding sign at +0.5R", [("funding>0 (longs pay)", FSIGN > 0.5), ("funding<=0 (shorts pay)", FSIGN <= 0.5)])
    rep("funding vs position", [("AGAINST (we pay carry)", FAGN > 0.5), ("WITH (we receive)", FAGN <= 0.5)])
    rep("fresh funding flip (24h)", [("flipped", FFLIP > 0.5), ("no flip", FFLIP <= 0.5)])
    qs = np.nanpercentile(FMAG, [50, 90])
    rep("|funding| magnitude", [("low (<=med)", FMAG <= qs[0]), ("mid", (FMAG > qs[0]) & (FMAG <= qs[1])), ("extreme (top10%)", FMAG > qs[1])])
    print("\nCandidate-only. A clean, confound-controlled separation -> note for a FUTURE sealed lens;")
    print("the frozen fade rule (surge+velocity) is unchanged. No live claim.")


if __name__ == "__main__":
    main()
