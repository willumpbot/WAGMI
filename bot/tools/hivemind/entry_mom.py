"""signed_mom_24h for every bot entry, for the laptop's sealed entry-timing test (PREREG_ENTRY_TIMING_2026-10-11 §3).

signed_mom_24h = (close_at_entry_hour / close_24h_earlier - 1) * 100 * (+1 LONG, -1 SHORT), from HL 1h closes, at the
last CLOSED hourly bar at or before the fill. A trade without 24h of prior bars is written with value null and a reason
(excluded, never defaulted to zero). Read-only sidecar: reads the position journal's OPEN events, touches nothing in the
bot, so the bot never needs a restart for it. Writes data/hivemind/entry_mom.jsonl (one row per position_id).
"""
import json
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import hl  # noqa: E402

BOT = HERE.parents[1]
JOURNAL = BOT / "data" / "position_journal.jsonl"
OUT = BOT / "data" / "hivemind" / "entry_mom.jsonl"
H = 3600_000
MAX_PER_RUN = 60   # the journal holds ~1.6k historic opens; backfill a slice per 15-min cycle


def signed_mom(coin, side, fill_ms):
    """Returns (value, info). Bars are keyed by open time t; a bar is closed once t + 1h <= fill."""
    bars = hl.candles(coin, "1h", fill_ms - 30 * H, fill_ms, ttl=3600) or []
    closed = {int(b["t"]): float(b["c"]) for b in bars if int(b["t"]) + H <= fill_ms}
    if not closed:
        return None, {"reason": "no closed 1h bar before fill"}
    t_now = max(closed)
    t_prev = t_now - 24 * H
    if t_prev not in closed:
        return None, {"reason": "no bar 24h earlier", "bar_t": t_now}
    v = (closed[t_now] / closed[t_prev] - 1) * 100 * (1 if side == "LONG" else -1)
    return round(v, 4), {"bar_t": t_now, "close": closed[t_now], "close_24h": closed[t_prev]}


def run():
    done = set()
    try:
        done = {json.loads(l)["position_id"] for l in OUT.read_text(encoding="utf-8").splitlines() if l.strip()}
    except OSError:
        pass
    todo = []
    for line in JOURNAL.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        side = str((e.get("meta") or {}).get("side") or "").upper()
        if e.get("phase") == "OPEN" and e.get("position_id") not in done and side in ("LONG", "SHORT"):
            todo.append((e, side))
    todo.sort(key=lambda x: x[0]["ts"], reverse=True)   # newest first: live entries never wait behind the backfill
    new = []
    coins = set(hl.post({"type": "allMids"}, ttl=300) or {})
    for e, side in todo[:MAX_PER_RUN]:
        if e["position_id"] in done:
            continue
        if e["symbol"] not in coins:   # test-suite rows (e.g. TEST) leaked into the live journal: mark, never retry
            v, info = None, {"reason": "not an HL perp (test row?)"}
        fill_ms = int(datetime.fromisoformat(e["ts"]).timestamp() * 1000)
        try:
            if e["symbol"] in coins:
                v, info = signed_mom(e["symbol"], side, fill_ms)
        except Exception as ex:   # API hiccup: retry next cycle rather than write a hole
            print("entry_mom", e["symbol"], ex)
            continue
        r = dict({"position_id": e["position_id"], "symbol": e["symbol"], "side": side, "fill_ts": e["ts"],
                  "signed_mom_24h": v, "def": "PREREG_ENTRY_TIMING_2026-10-11 s3"}, **info)
        with open(OUT, "a", encoding="utf-8") as f:
            f.write(json.dumps(r) + chr(10))
        new.append(r)
        done.add(e["position_id"])
    return len(new)


if __name__ == "__main__":
    print(run(), "new rows")
