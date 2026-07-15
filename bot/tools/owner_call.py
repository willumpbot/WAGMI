#!/usr/bin/env python
"""Owner-call logger + corroboration — capture the owner's own trade calls (posted
to Twitter / made by hand) so we can corroborate them against the bot's signals
later: where human intuition AND the systematic bot agree is a high-conviction entry.

  add:         python tools/owner_call.py add BTC SHORT "crowded longs unwind" [entry]
  corroborate: python tools/owner_call.py corroborate [hours]   (join calls -> bot signals)

Calls are appended to data/owner_calls.jsonl with a UTC timestamp and the bot's
last-known price for the symbol. Nothing here touches trading — pure record + join.
"""
import os
import sys
import json
import datetime

BOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALLS = os.path.join(BOT, "data", "owner_calls.jsonl")


def _last_price(symbol):
    try:
        hb = json.load(open(os.path.join(BOT, "data", "heartbeat.json")))
        # heartbeat has no per-symbol price; best-effort from market_depth tail
    except Exception:
        pass
    try:
        path = os.path.join(BOT, "data", "market_depth_history.jsonl")
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 200_000))
            for line in reversed(f.read().decode("utf-8", "ignore").splitlines()):
                try:
                    r = json.loads(line)
                    if r.get("symbol") == symbol:
                        return (r.get("l2") or {}).get("mid")
                except Exception:
                    continue
    except Exception:
        pass
    return None


def add(symbol, side, thesis, entry=None):
    symbol = symbol.upper()
    side = side.upper()
    rec = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "symbol": symbol,
        "side": side,
        "thesis": thesis,
        "entry": float(entry) if entry else _last_price(symbol),
        "source": "owner",
    }
    with open(CALLS, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    print(f"logged: {symbol} {side} @ {rec['entry']} — {thesis}")


def corroborate(hours=12):
    if not os.path.exists(CALLS):
        print("no owner calls yet — log one with: owner_call.py add SYMBOL SIDE \"thesis\"")
        return
    calls = [json.loads(x) for x in open(CALLS, encoding="utf-8") if x.strip()]
    import glob
    logs = sorted(glob.glob(os.path.join(BOT, "logs", "bot_2026*.log")))[-3:]
    # index recent bot signals: symbol -> list of (ts, side, conf)
    sigs = []
    for lg in logs:
        for line in open(lg, encoding="utf-8", errors="ignore"):
            if "SIGNAL_GENERATED" not in line:
                continue
            try:
                d = json.loads(line).get("data", {})
                sigs.append((d.get("timestamp", ""), d.get("symbol"), d.get("side"), d.get("confidence")))
            except Exception:
                continue
    print(f"Owner calls: {len(calls)} | bot signals indexed: {len(sigs)}\n")
    for c in calls[-20:]:
        # side vocab: owner LONG/SHORT vs bot BUY/SELL
        want = "BUY" if c["side"] in ("LONG", "BUY") else "SELL"
        agree = [s for s in sigs if s[1] == c["symbol"] and s[2] == want]
        opp = [s for s in sigs if s[1] == c["symbol"] and s[2] != want]
        verdict = "AGREE (bot also signalled this side)" if agree else (
            "CONFLICT (bot signalled the other side)" if opp else "no bot signal on this symbol")
        best = max((float(s[3] or 0) for s in agree), default=0)
        print(f"{c['ts'][:16]} {c['symbol']} {c['side']}: {verdict}"
              + (f" [bot conf up to {best:.0f}%]" if agree else ""))


def main():
    if len(sys.argv) < 2:
        print(__doc__); return
    cmd = sys.argv[1]
    if cmd == "add" and len(sys.argv) >= 4:
        add(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "",
            sys.argv[5] if len(sys.argv) > 5 else None)
    elif cmd == "corroborate":
        corroborate(int(sys.argv[2]) if len(sys.argv) > 2 else 12)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
