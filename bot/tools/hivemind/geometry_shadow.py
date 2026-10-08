"""Paired shadow test of the laptop's geometry proposal (bot/data/laptop_mining/GEOMETRY.md).

Every new bot signal (SIGNAL_GENERATED, plus IC-muted drops) is played out twice over 48h on Hyperliquid 1h
candles, at equal dollar risk:
  current   stop = the signal's sl, target = the signal's tp1, marked to the 48h close if neither is hit
  proposal  stop' = 8 x |entry - sl| from entry, target = 1.0R of that wider stop, 48h time stop
Resolution follows GEOMETRY.md: bars starting after the signal; a bar spanning stop and target counts as a
stop; fees of 9 bps round trip are charged in R (fee / stop distance). Results are in R per setup.
Read-only; writes data/hivemind/geometry_shadow*.json. Nothing here changes the bot.
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

BOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
DATA = BOT / "data"
HM = DATA / "hivemind"
STATE = HM / "geometry_shadow_state.json"
OUT = HM / "geometry_shadow.json"
HOLD = 48 * 3600
FEE = 0.0009
STOP_MULT, TP_R = 8.0, 1.0


def _load(p, d):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return d


def _iso(s):
    t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).timestamp()


def _offset_at(path, since):
    off = 0
    with open(path, "rb") as f:
        for raw in f:
            i = raw.find(b'"timestamp": "')
            if i >= 0:
                try:
                    if _iso(raw[i + 14:raw.find(b'"', i + 14)].decode()) >= since:
                        return off
                except Exception:
                    pass
            off += len(raw)
    return off


def ingest(st):
    path = DATA / "trade_events.jsonl"
    size = path.stat().st_size
    off = st.get("off")
    if off is None or off > size:
        since = st.get("backfill_since")
        off = _offset_at(path, since) if since else size   # default: start from now (forward test)
    with open(path, "rb") as f:
        f.seek(off)
        chunk = f.read()
    end = chunk.rfind(b"\n")
    if end >= 0:
        for raw in chunk[:end + 1].splitlines():
            if b"SIGNAL_GENERATED" not in raw and b"ic_muted" not in raw:
                continue
            try:
                r = json.loads(raw)
                e, sl = float(r["entry"]), float(r["sl"])
                tp = float(r.get("tp1") or 0)
                side = 1 if r.get("side") in ("BUY", "LONG") else -1
                if e <= 0 or sl <= 0 or (sl - e) * side >= 0:
                    continue
                t = _iso(r["timestamp"])
                key = f"{r['symbol']}|{side}|{int(t // 3600)}"
                if key in st["seen"]:
                    continue
                st["seen"][key] = 1
                st["pending"].append({"sym": r["symbol"], "ts": t, "side": side, "entry": e, "sl": sl, "tp": tp,
                                      "src": "ic_muted" if b"ic_muted" in raw else "signal"})
            except Exception:
                continue
        off += end + 1
    st["off"] = off


def play(bars, side, entry, stop, target, d):
    fee_r = FEE * entry / d
    for t, o, h, l, c in bars:
        hit_stop = (l <= stop) if side > 0 else (h >= stop)
        hit_tp = target and ((h >= target) if side > 0 else (l <= target))
        if hit_stop:
            return -1.0 - fee_r
        if hit_tp:
            return abs(target - entry) / d - fee_r
    last = bars[-1][4]
    return (last - entry) * side / d - fee_r


def resolve(st):
    import hl
    now = time.time()
    done = []
    for p in list(st["pending"]):
        if now - p["ts"] < HOLD + 3600:
            continue
        try:
            raw = hl.candles(p["sym"], "1h", int(p["ts"] * 1000), int((p["ts"] + HOLD + 3600) * 1000), ttl=3600)
        except Exception:
            continue
        bars = [(int(b["t"]) / 1000, float(b["o"]), float(b["h"]), float(b["l"]), float(b["c"])) for b in raw]
        bars = [b for b in bars if b[0] > p["ts"] and b[0] < p["ts"] + HOLD]
        st["pending"].remove(p)
        if len(bars) < 24:
            continue
        d0 = abs(p["entry"] - p["sl"])
        cur = play(bars, p["side"], p["entry"], p["sl"], p["tp"], d0)
        d1 = STOP_MULT * d0
        stop1 = p["entry"] - p["side"] * d1
        tgt1 = p["entry"] + p["side"] * TP_R * d1
        prop = play(bars, p["side"], p["entry"], stop1, tgt1, d1)
        done.append({**p, "r_current": round(cur, 3), "r_proposal": round(prop, 3)})
    if done:
        with open(HM / "geometry_shadow_results.jsonl", "a", encoding="utf-8") as f:
            for r in done:
                f.write(json.dumps(r) + "\n")
    return len(done)


def scorecard():
    rows = []
    try:
        rows = [json.loads(l) for l in (HM / "geometry_shadow_results.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    except OSError:
        pass
    out = {"updated": datetime.now(timezone.utc).isoformat(timespec="minutes"), "n": len(rows),
           "proposal": f"stop x{STOP_MULT:g}, target {TP_R:g}R, 48h time stop, equal dollar risk"}
    if len(rows) >= 2:
        cur = np.array([r["r_current"] for r in rows])
        prop = np.array([r["r_proposal"] for r in rows])
        diff = prop - cur
        days = np.array([int(r["ts"] // 86400) for r in rows])
        u = np.unique(days)
        g = {d: diff[days == d] for d in u}
        rnd = np.random.default_rng(5)
        boots = sorted(float(np.concatenate([g[d] for d in rnd.choice(u, len(u))]).mean()) for _ in range(1000))
        out.update({"mean_r_current": round(float(cur.mean()), 3), "mean_r_proposal": round(float(prop.mean()), 3),
                    "paired_diff_r": round(float(diff.mean()), 3), "ci95": [round(boots[25], 3), round(boots[974], 3)],
                    "n_days": int(len(u)),
                    "laptop_backtest": "+0.542R paired diff, CI [+0.300, +0.799] out of sample (GEOMETRY.md)"})
        lo, hi = out["ci95"]
        out["verdict"] = ("collecting" if len(rows) < 30 else "confirmed live" if lo > 0 else
                          "contradicted live" if hi < 0 else "inconclusive so far")
    else:
        out["verdict"] = "collecting"
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def main():
    HM.mkdir(parents=True, exist_ok=True)
    st = _load(STATE, {"seen": {}, "pending": []})
    for a in sys.argv:
        if a.startswith("--backfill-since=") and "off" not in st:
            st["backfill_since"] = _iso(a.split("=", 1)[1])
    ingest(st)
    n = resolve(st)
    if len(st["seen"]) > 5000:
        st["seen"] = dict(list(st["seen"].items())[-3000:])
    STATE.write_text(json.dumps(st), encoding="utf-8")
    sc = scorecard()
    return n, len(st["pending"]), sc


if __name__ == "__main__":
    print(main())
