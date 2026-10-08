"""Freeze what happened AFTER each Telegram call, so callers can be graded honestly.

The server's `tg_listener.py` already logs every call to data/hivemind/tg/calls.jsonl
with the price at the call instant -- which is the right design and covers skipped
calls, so there is a control group. Two things are still missing, and both are
fatal to a fair grading if left:

1. NO FOLLOW-UP PRICES. Grading later means re-fetching history, but tokens that
   RUG GET DELISTED from DexScreener. The worst calls would silently disappear
   from the sample -- survivorship bias rebuilding itself inside our own data.
   Snapshotting at fixed offsets freezes the outcome while it is still visible.

2. NO MEASURE OF THE FIRST-MINUTE TAX. Rick bot's peak is measured from the call
   price. The owner's P&L starts at their fill. If a call runs 40% in 90 seconds
   because 200 people read the same message, the caller is genuinely good and the
   trade is still unprofitable for the owner. The +1m and +5m snapshots measure
   that gap per group without needing wallet access.

Run this on a short cron (every 2-5 min). It is idempotent: each (call, offset)
pair is written at most once, so re-runs are safe and cheap.

    python call_tracker.py            # one pass over due snapshots
    python call_tracker.py --report   # grade callers on what is captured so far
"""
import json, io, os, sys, time, math, urllib.request, urllib.parse, collections

HERE = os.path.dirname(os.path.abspath(__file__))
BOT = os.path.dirname(os.path.dirname(HERE))            # .../WAGMI/bot
TG = os.path.join(BOT, "data", "hivemind", "tg")
CALLS = os.path.join(TG, "calls.jsonl")
TRACK = os.path.join(TG, "call_prices.jsonl")
DS = "https://api.dexscreener.com/latest/dex/tokens/"
UA = {"User-Agent": "wagmi-research/1.0"}

# offsets in seconds. The first two measure the entry tax; the rest the outcome.
OFFSETS = [("1m", 60), ("5m", 300), ("15m", 900), ("1h", 3600),
           ("6h", 21600), ("24h", 86400), ("72h", 259200), ("7d", 604800)]
MAX_LATE = 0.5          # skip a snapshot if we are more than 50% of the offset late


def get(url, tries=2):
    for k in range(tries):
        try:
            return json.loads(urllib.request.urlopen(
                urllib.request.Request(url, headers=UA), timeout=20).read())
        except Exception as e:
            if k == tries - 1:
                return {"__err__": str(e)}
            time.sleep(1.0)
    return {"__err__": "unreachable"}


GT = "https://api.geckoterminal.com/api/v2"
NETMAP = {"ethereum": "eth", "solana": "solana", "base": "base", "bsc": "bsc",
          "arbitrum": "arbitrum", "polygon": "polygon_pos", "avalanche": "avax"}


def price_now(ca):
    """Deepest LIVE pair's price for a contract address, plus liquidity and pool id."""
    d = get(DS + urllib.parse.quote(ca))
    if "__err__" in d:
        return None, None, None, None, d["__err__"]
    best = None
    for p in (d.get("pairs") or []):
        try:
            liq = float(((p.get("liquidity") or {}).get("usd") or 0) or 0)
            px = float(p.get("priceUsd") or 0)
        except (TypeError, ValueError):
            continue
        if px <= 0:
            continue
        if best is None or liq > best[1]:
            best = (px, liq, p.get("chainId"), p.get("pairAddress"))
    if best is None:
        # no live pair: the token is gone. That IS the outcome, not an error.
        return 0.0, 0.0, None, None, "no_live_pair"
    return best[0], best[1], best[2], best[3], None


def high_water(chain, pool, since_ts):
    """Highest price TOUCHED since the call.

    A ladder rung fills the moment price trades through it, so point-in-time
    snapshots are the wrong measurement -- a call can touch 3x between two
    snapshots and be back under 1x by the time we look. This pulls minute and
    hourly candle HIGHS and returns the running maximum since the call, which is
    what decides how many rungs filled.
    """
    net = NETMAP.get(chain, chain)
    if not net or not pool:
        return None
    best = None
    for tf, limit in (("minute?aggregate=15&limit=300", None), ("hour?limit=300", None)):
        d = get(f"{GT}/networks/{net}/pools/{pool}/ohlcv/{tf}")
        if "__err__" in d:
            continue
        for r in (((d.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []):
            try:
                t, hi = int(r[0]), float(r[2])
            except (IndexError, TypeError, ValueError):
                continue
            if t >= since_ts - 60 and hi > 0:
                best = hi if best is None else max(best, hi)
        if best is not None:
            break
    return best


def load_jsonl(p):
    out = []
    if not os.path.exists(p):
        return out
    with io.open(p, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    return out


def track():
    calls = load_jsonl(CALLS)
    if not calls:
        print(f"no calls yet at {CALLS}")
        print("This script is ready; it will start working as soon as tg_listener logs a call.")
        return
    done = {(r.get("ca"), r.get("offset")) for r in load_jsonl(TRACK)}
    now = time.time()
    written = skipped = 0
    for c in calls:
        ca, ts = c.get("ca"), c.get("ts")
        if not ca or not isinstance(ts, (int, float)):
            continue
        for name, off in OFFSETS:
            if (ca, name) in done:
                continue
            due = ts + off
            if now < due:
                continue                      # not yet
            if now - due > MAX_LATE * off:
                # too late for this offset to mean what it says; record the miss
                with io.open(TRACK, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"ca": ca, "offset": name, "ts": ts,
                                         "missed": True, "late_s": round(now - due)}) + "\n")
                done.add((ca, name))
                skipped += 1
                continue
            px, liq, chain, pool, err = price_now(ca)
            hw = high_water(chain, pool, ts) if (chain and pool) else None
            p0 = c.get("price_usd")
            try:
                p0 = float(p0)
            except (TypeError, ValueError):
                p0 = None
            rec = {"ca": ca, "offset": name, "ts": ts, "snap_ts": now,
                   "price_usd": px, "liq": liq, "err": err,
                   "chat": c.get("chat"), "sender": c.get("sender"),
                   "p0": p0,
                   "mult": (px / p0 if (p0 and p0 > 0 and px is not None) else None),
                   # high-water multiple: what a LADDER would actually have filled.
                   # A rung fills the moment price trades through it, so a spot
                   # snapshot is the wrong measurement -- a call can touch 3x
                   # between two snapshots and be back under 1x when we look.
                   "peak_mult": (hw / p0 if (p0 and p0 > 0 and hw) else None)}
            with io.open(TRACK, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            done.add((ca, name))
            written += 1
            time.sleep(0.25)
    print(f"calls {len(calls)}   snapshots written {written}   missed-window {skipped}")


def report():
    snaps = load_jsonl(TRACK)
    if not snaps:
        print("no snapshots yet -- run track() on a cron first")
        return
    ok = [s for s in snaps if not s.get("missed") and s.get("mult") is not None]
    print(f"snapshots: {len(snaps)}   usable: {len(ok)}")
    if not ok:
        return

    def med(xs):
        xs = sorted(xs)
        return xs[len(xs) // 2] if xs else float("nan")

    print("\n=== THE FIRST-MINUTE TAX (price vs the call price) ===")
    print(f"  {'offset':<8}{'n':>6}{'median x':>11}{'mean x':>10}{'% >1x':>8}{'% dead':>8}")
    for name, _ in OFFSETS:
        v = [s["mult"] for s in ok if s["offset"] == name]
        if not v:
            continue
        dead = sum(1 for x in v if x == 0)
        print(f"  {name:<8}{len(v):>6}{med(v):>11.3f}{sum(v)/len(v):>10.3f}"
              f"{100*sum(1 for x in v if x > 1)/len(v):>7.0f}%{100*dead/len(v):>7.0f}%")

    print("\n=== BY CALLER (24h multiple; needs n>=10 to mean anything) ===")
    by = collections.defaultdict(list)
    for s in ok:
        if s["offset"] == "24h":
            by[(s.get("chat"), s.get("sender"))].append(s["mult"])
    rows = [(k, v) for k, v in by.items() if len(v) >= 10]
    if not rows:
        print("  not enough per-caller 24h snapshots yet")
    else:
        print(f"  {'chat / sender':<40}{'n':>5}{'median':>9}{'mean':>9}{'% >1x':>8}{'% dead':>8}")
        for (chat, snd), v in sorted(rows, key=lambda x: -med(x[1])):
            dead = sum(1 for x in v if x == 0)
            print(f"  {str(chat)[:22]+' / '+str(snd)[:15]:<40}{len(v):>5}{med(v):>9.3f}"
                  f"{sum(v)/len(v):>9.3f}{100*sum(1 for x in v if x>1)/len(v):>7.0f}%"
                  f"{100*dead/len(v):>7.0f}%")
    print("\n=== LADDER VIEW: P(peak >= k) per caller ===")
    print("  This is the number that decides how many rungs fill. For a ladder the TAIL is")
    print("  the point, so this is reported alongside the median rather than instead of it.")
    RUNGS = [1.5, 2.0, 3.0, 5.0, 10.0]
    byp = collections.defaultdict(list)
    for s_ in ok:
        if s_.get("peak_mult"):
            byp[(s_.get("chat"), s_.get("sender"))].append(s_["peak_mult"])
    rows2 = [(k, v) for k, v in byp.items() if len(v) >= 10]
    if not rows2:
        print("  not enough per-caller peak data yet (need >=10 calls with a high-water mark)")
    else:
        print("  " + "caller".ljust(34) + "n".rjust(4)
              + "".join(f"P>={r}x".rjust(9) for r in RUNGS))
        for (chat, snd), v in sorted(
                rows2, key=lambda x: -sum(1 for y in x[1] if y >= 2) / len(x[1])):
            cells = "".join(f"{100*sum(1 for y in v if y >= r)/len(v):>8.0f}%" for r in RUNGS)
            print(f"  {(str(chat)[:18] + ' / ' + str(snd)[:12]):<34}{len(v):>4}{cells}")
        print("\n  A 25%-per-rung ladder at 1.5/2/3/5 earns roughly")
        print("  0.25*(1.5*P>=1.5 + 2*P>=2 + 3*P>=3 + 5*P>=5), plus whatever the remainder does.")

    print("\n  MEDIAN vs MEAN: for a SINGLE all-or-nothing exit use the median -- one 50x you")
    print("  did not hold does not pay rent. For a LADDER the mean and the tail ARE the point,")
    print("  because the ladder is the mechanism that harvests them. Read both.")


if __name__ == "__main__":
    if "--report" in sys.argv:
        report()
    else:
        track()
        print()
        report()
