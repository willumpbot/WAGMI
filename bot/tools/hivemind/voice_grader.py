"""Voice grader: every hivemind voice earns (or loses) trust on forward outcomes.

Two sources, kept separate and both reported:
  history  price-derived voices (structure, stretch, driver, momentum_7d, rsi) reconstructed on CLOSED daily
           candles since 2020 for the six coins; forward 5-day return after each reading. Gives every
           such voice a prior before the live log has data. Block bootstrap over non-overlapping 5-day blocks.
  live     data/hivemind/voice_log.jsonl (one row per voice per 15-min cycle). Each voice's first reading
           per coin per UTC day is graded at +1d and +5d with Hyperliquid 1h prices.

Edge = reading x forward return (bps), net of 9 bps fees, so +1 is right when price rose.
Trust: earned (CI low > 0, n_eff >= 30), promising (mean > 0), backwards (CI high < 0), unproven.
Live grades replace history grades once the live n_eff reaches 30.
Writes data/hivemind/voice_grades.json, which tools/hivemind/voices.py reads.
"""
import json
import random
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

BOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
HM = BOT / "data" / "hivemind"
LOG = HM / "voice_log.jsonl"
OUT = HM / "voice_grades.json"
FEE = 9.0
H5 = 5 * 86400


def _ci(vals, block=1, n_boot=1000):
    v = np.array(vals, dtype=float)
    if len(v) < 10:
        return None
    rng = random.Random(3)
    blocks = [v[i:i + block] for i in range(0, len(v), block)]
    means = sorted(float(np.mean(np.concatenate([rng.choice(blocks) for _ in blocks]))) for _ in range(n_boot))
    return [round(means[int(0.025 * n_boot)], 1), round(means[int(0.975 * n_boot)], 1)]


def _trust(mean, ci, n_eff):
    if ci and n_eff >= 30 and ci[0] > 0:
        return "earned"
    if ci and ci[1] < 0:
        return "backwards"
    if mean is not None and mean > FEE:   # must at least clear one round of trading costs
        return "promising"
    return "unproven"


def history_grades():
    import basemap
    import pandas as pd
    per = defaultdict(list)   # voice -> [(sym, day, edge_bps)]
    # Edge is measured against the period's own drift: 2020-26 had always-long at ~+100 bps/5d, so raw
    # reading x return credits any long-leaning voice with the bull market. Demean by the cross-coin mean
    # of all 5-day returns in the same calendar half before multiplying by the reading.
    for sym in basemap.SYMS:
        df = basemap._closed(basemap._daily(sym))
        f = basemap.features(df)
        c = df["c"]
        r5 = (c.shift(-5) / c - 1) * 1e4
        mom = (c / c.shift(7) - 1) * 100
        delta = c.diff()
        gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
        rsi = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
        for i in range(50, len(df) - 5):
            ret = r5.iloc[i]
            if ret != ret:
                continue
            reads = {
                "structure": 1 if f["structure"].iloc[i] == "UP" else -1,
                "stretch": 1 if f["stretch"].iloc[i] == "ABOVE" else -1,
                "driver": 1 if f["driver"].iloc[i] == "BUYERS" else -1,
                "momentum_7d": 1 if mom.iloc[i] > 5 else -1 if mom.iloc[i] < -5 else 0,
                "rsi": 1 if rsi.iloc[i] < 30 else -1 if rsi.iloc[i] > 70 else 0,
            }
            day = int(df["t"].iloc[i] // 86_400_000)
            for k, r in reads.items():
                if r:
                    per[k].append((sym, day, r, ret))
    RECENT = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() // 86400)
    allrows = [x for rows in per.values() for x in rows]
    drift_old = float(np.mean([x[3] for x in allrows if x[1] < RECENT] or [0]))
    drift_new = float(np.mean([x[3] for x in allrows if x[1] >= RECENT] or [0]))

    def stats(rows):
        vals = np.array([r * (ret - (drift_new if day >= RECENT else drift_old)) for _, day, r, ret in rows])
        days = np.array([day for _, day, _, _ in rows])
        if len(vals) < 10:
            return None
        blk = days // 5
        u = np.unique(blk)
        g = {b: vals[blk == b] for b in u}
        rnd = np.random.default_rng(1)
        means = sorted(float(np.concatenate([g[b] for b in rnd.choice(u, len(u))]).mean()) for _ in range(800))
        return {"n": int(len(vals)), "n_eff": int(len(u)), "mean_bps_5d": round(float(vals.mean()), 1),
                "ci95": [round(means[20], 1), round(means[779], 1)]}

    out = {}
    for k, rows in per.items():
        full, recent = stats(rows), stats([x for x in rows if x[1] >= RECENT])
        tr = _trust(recent["mean_bps_5d"], recent["ci95"], recent["n_eff"]) if recent else "unproven"
        if full and full["ci95"][0] > 0 and tr != "earned":
            tr = "promising" if recent and recent["mean_bps_5d"] > 0 else "unproven"
        out[k] = {"source": "history", **(recent or {}), "full_period": full, "trust": tr,
                  "note": ("vs the period's own drift (always-long was ~+100 bps/5d); trust from 2024+ only; "
                           "clustered by 5-day calendar block across coins; before fees")}
    return out


def _hl_1h(sym, start):
    body = json.dumps({"type": "candleSnapshot", "req": {"coin": sym, "interval": "1h",
                                                          "startTime": int(start * 1000), "endTime": int(time.time() * 1000)}}).encode()
    req = urllib.request.Request("https://api.hyperliquid.xyz/info", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return sorted((int(b["t"]) / 1000, float(b["o"])) for b in json.loads(r.read()))


def live_grades():
    if not LOG.exists():
        return {}
    first = {}
    for ln in LOG.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(ln)
        except Exception:
            continue
        if not r.get("r"):
            continue
        day = datetime.fromtimestamp(r["ts"], timezone.utc).strftime("%Y-%m-%d")
        first.setdefault((r["voice"], r["sym"], day), r)
    now = time.time()
    due = [r for r in first.values() if now - r["ts"] >= H5 + 3600]
    if not due:
        return {"_pending": len(first)}
    prices = {}
    for sym in {r["sym"] for r in due}:
        try:
            prices[sym] = _hl_1h(sym, min(r["ts"] for r in due if r["sym"] == sym))
        except Exception:
            prices[sym] = []
    per = defaultdict(list)
    for r in due:
        bars = prices.get(r["sym"]) or []
        nxt = next((o for t, o in bars if t >= r["ts"] + H5), None)
        if nxt:
            per[r["voice"]].append(r["r"] * (nxt / r["px"] - 1) * 1e4 - FEE)
    out = {}
    for k, vals in per.items():
        mean = float(np.mean(vals))
        ci = _ci(vals)
        out[k] = {"source": "live", "n": len(vals), "n_eff": len(vals), "mean_bps_5d": round(mean, 1), "ci95": ci,
                  "trust": _trust(mean, ci, len(vals))}
    out["_pending"] = len(first) - len(due)
    return out


def tf4h_grades():
    import tf4h
    out = {}
    for k, v in tf4h.history().items():
        out[k] = {"source": "history", "n": v["n"], "n_eff": v["n_eff"], "mean_bps_5d": v["mean_bps_1d"],
                  "ci95": v["ci95"], "horizon": "1d",
                  "trust": _trust(v["mean_bps_1d"], v["ci95"], v["n_eff"]),
                  "note": f"closed 4h bars since {v['since']}, next-1-day vs drift, before fees"}
    return out


def main():
    hist = history_grades()
    try:
        hist.update(tf4h_grades())
    except Exception as e:
        print("4h grading failed:", e)
    live = live_grades()
    voices = {}
    for k in set(hist) | {k for k in live if not k.startswith("_")}:
        h, l = hist.get(k), live.get(k)
        use = l if (l and l.get("n_eff", 0) >= 30) else h or l
        voices[k] = {**(use or {}), "history": h, "live": l}
    OUT.write_text(json.dumps({"updated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
                               "voices": voices, "live_pending": live.get("_pending", 0)}, indent=1), encoding="utf-8")
    return voices


if __name__ == "__main__":
    for k, v in sorted(main().items()):
        print(f"{k:13s} {v.get('trust'):10s} {v.get('source')}: n={v.get('n')} mean={v.get('mean_bps_5d')}bps CI={v.get('ci95')}")
