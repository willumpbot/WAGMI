"""Shadow stops on 5-minute bars for every LIVE bot entry: would a wider stop have done better? (laptop X2 -> reply 93)

The real-trade stop test was underpowered by construction AND 1h bars cannot referee a 1.66% stop (22% of real stop-
outs came back as winners on 1h). HL keeps 5m bars only ~17 days, so the only way to get a 5m answer is to record it
live. For each live TRADE_OPENED (journal-confirmed, price-sane) this walks HL 5m bars from the fill and resolves, per
arm, which comes first: the stop or the bot's own TP2, else the price at the 96h cap. Arms: the bot's actual stop, and
stops at 1.0x / 1.5x / 2.0x the expected daily move (volforecast, from daily closes before the entry). Everything is
in R of the bot's ORIGINAL risk |entry - sl|, so arms are comparable; fees are left to the analysis. Stop and target
in the same 5m bar resolve as the stop (pessimistic). Measurement only - never touches the bot.
Writes data/hivemind/stop_shadow.json (one record per position; open ones re-walked each cycle).
"""
import json
import time
from datetime import datetime
from pathlib import Path

import hl
import volforecast

BOT = Path(__file__).resolve().parents[2]
EVENTS = BOT / "data" / "trade_events.jsonl"
JOURNAL = BOT / "data" / "position_journal.jsonl"
OUT = BOT / "data" / "hivemind" / "stop_shadow.json"
START = datetime.fromisoformat("2026-10-09T00:00:00+00:00").timestamp()   # 5m history reaches back ~17 days
CAP_S = 96 * 3600
KS = (1.0, 1.5, 2.0)
D = 86400_000


def _opens():
    """Live TRADE_OPENED events since START that the position journal confirms (test fixtures excluded)."""
    jopen = {}
    for l in JOURNAL.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(l)
        except ValueError:
            continue
        if e.get("phase") == "OPEN":
            jopen[e["position_id"]] = e
    out = []
    with open(EVENTS, encoding="utf-8") as f:
        for l in f:
            if '"TRADE_OPENED"' not in l:
                continue
            e = json.loads(l)
            ts = datetime.fromisoformat(e["timestamp"]).timestamp()
            pid = e.get("position_id")
            if ts < START or pid not in jopen or not e.get("sl") or not e.get("tp2"):
                continue
            out.append(dict(e, ts=ts))
    return out


def _exp_move(coin, ts):
    bars = hl.candles(coin, "1d", (ts - 60 * 86400) * 1000, ts * 1000, ttl=3600) or []
    closes = [float(b["c"]) for b in bars if int(b["t"]) + D <= ts * 1000]
    fc = volforecast.forecast(closes) or {}
    return fc.get("next_day_move_pct")


def _walk(side, entry, stop, tp, bars, end_ts):
    """First of stop / tp on 5m bars (stop wins ties). Returns (exit_price, how, at) or None if still open."""
    sg = 1 if side == "LONG" else -1
    last = None
    for b in bars:
        t, hi, lo, c = int(b["t"]) / 1000, float(b["h"]), float(b["l"]), float(b["c"])
        if t > end_ts:
            break
        if (sg > 0 and lo <= stop) or (sg < 0 and hi >= stop):
            return stop, "stop", t
        if (sg > 0 and hi >= tp) or (sg < 0 and lo <= tp):
            return tp, "tp2", t
        last = (c, t)
    if last and time.time() >= end_ts:
        return last[0], "cap96h", last[1]
    return None


def run():
    try:
        st = json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        st = {}
    try:
        live_px = hl.post({"type": "allMids"}, ttl=60) or {}
    except Exception:
        live_px = {}
    for e in _opens():
        pid, coin, side = e["position_id"], e["symbol"], str(e["side"]).upper()
        r = st.get(pid)
        if r and r.get("done"):
            continue
        entry, sl, tp = float(e["entry"]), float(e["sl"]), float(e["tp2"])
        if coin in live_px and abs(entry / float(live_px[coin]) - 1) > 0.5:
            continue   # not this market's price: a fixture, never a live trade
        risk = abs(entry - sl)
        if risk <= 0:
            continue
        if not r:
            em = _exp_move(coin, e["ts"])
            sg = 1 if side == "LONG" else -1
            arms = {"bot": sl}
            if em:
                for k in KS:
                    arms[f"{k}x"] = entry * (1 - sg * k * em / 100)
            r = st[pid] = {"coin": coin, "side": side, "entry": entry, "fill_ts": e["ts"], "tp2": tp, "risk": risk,
                           "exp_move_pct": em, "bot_stop_pct": round(risk / entry * 100, 3),
                           "arms": {a: {"stop": s} for a, s in arms.items()}}
        end = r["fill_ts"] + CAP_S
        try:
            bars = sorted(hl.candles(coin, "5m", r["fill_ts"] * 1000, min(end, time.time()) * 1000, ttl=300) or [],
                          key=lambda b: b["t"])
        except Exception:
            continue
        bars = [b for b in bars if int(b["t"]) / 1000 >= r["fill_ts"] - 300]
        sg = 1 if side == "LONG" else -1
        for a, arm in r["arms"].items():
            if "how" in arm:
                continue
            res = _walk(side, entry, arm["stop"], tp, bars, end)
            if res:
                px, how, at = res
                arm.update(exit=px, how=how, at=at, r=round(sg * (px - entry) / risk, 3))
        r["done"] = all("how" in a for a in r["arms"].values())
        r["checked"] = time.time()
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(st), encoding="utf-8")
    tmp.replace(OUT)
    return len(st)


if __name__ == "__main__":
    n = run()
    print(n, "positions")
    for pid, r in json.loads(OUT.read_text(encoding="utf-8")).items():
        print(r["coin"], r["side"], r["bot_stop_pct"], r["exp_move_pct"], {a: (x.get("how"), x.get("r")) for a, x in r["arms"].items()})
