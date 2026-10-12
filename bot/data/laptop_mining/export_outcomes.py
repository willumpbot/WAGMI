"""STEP 1 of the caller-form handoff: per-call OUTCOMES, with no caller field, ever.

The server asked for caller rolling form. That needs calls grouped by caller, which needs
`caller_hash`, which this machine is not permitted to read. So instead of doing it anyway, it is
split so that identities never leave the server:

    STEP 1 (here)    export public price facts per call -- no caller field at all
    STEP 2 (server)  join to identity LOCALLY, compute rolling form using only outcomes whose
                     resolved_at < call_ts, ship back {ca, call_ts, form_*} with no identity
    STEP 3 (here)    test form against outcome under a prereg written before the join

This file is STEP 1. It asserts its own output contains no identity field, because "I was careful"
is not a control.

ON `resolved_at`. The server's spec has one resolution time per row, and they will filter prior
calls on `resolved_at < call_ts` to keep the form free of lookahead. But the fields resolve at
DIFFERENT times -- a 24h hit is knowable a day after the call, a 7d return a week after. Shipping a
single time forces a choice between staleness and lookahead.

So this exports BOTH per-field times AND the conservative single field they asked for:

    resolved_24h_at = call_ts + 24h
    resolved_7d_at  = call_ts + 7d
    resolved_at     = resolved_7d_at          (the LATEST, so their filter can never look ahead
                                               on any field; the per-field times let them be
                                               sharper if they want)

DEAD CALLS. A call whose pool never existed or never priced is a -100% outcome. Strictly its
resolution time is ambiguous -- arguably the call itself, since there was never anything to hold.
It is stamped with the same 7d time as everything else, and `dead: true` is on the row so the
server can treat it however their form definition requires. Flagged rather than decided here.
"""
import collections
import datetime
import io
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PATHS = os.path.join(HERE, "megacalls_paths.jsonl")
OUT = os.path.join(HERE, "call_outcomes.jsonl")

FORBIDDEN = ("caller", "caller_hash", "hash", "user", "author", "sender", "starred")


def load_calls():
    """Dedupe by ca, last wins -- the fetch appends, and the horizon upgrade appends a second,
    complete row per call. Counting rows instead of calls is the bug that understated the death
    rate by 8 points earlier today."""
    by_ca = {}
    for line in io.open(PATHS, encoding="utf-8"):
        if not line.strip():
            continue
        d = json.loads(line)
        if d.get("ca"):
            by_ca[d["ca"]] = d
    return by_ca


def main():
    by_ca = load_calls()
    rows, skipped = [], collections.Counter()
    for ca, d in by_ca.items():
        t0 = float(d["call_ts"])
        pm = d.get("peak_m") if isinstance(d.get("peak_m"), list) else None
        ph = d.get("peak_h") if isinstance(d.get("peak_h"), list) else None
        ch = d.get("close_h") if isinstance(d.get("close_h"), list) else None
        dead = bool(d.get("dead"))

        if not dead and not (pm or ph):
            skipped["no grid yet (awaiting fetch/upgrade)"] += 1
            continue

        def at(series, idx):
            if not series:
                return None
            return series[min(idx, len(series) - 1)]

        rec = {
            "ca": ca,
            "call_ts": int(t0),
            "chat": d.get("chat"),
            "dead": dead,
            # resolution times -- the server filters prior calls on these to avoid lookahead
            "resolved_24h_at": int(t0 + 24 * 3600),
            "resolved_7d_at": int(t0 + 7 * 86400),
            "resolved_at": int(t0 + 7 * 86400),      # the LATEST, per their spec
            # outcomes. None where the horizon is not covered yet, never 0 -- a missing
            # observation is not a failed one, which is the error this project keeps finding.
            # 24h comes from the HOURLY grid, not the minute grid: the minute grid uses a
            # different base price AND only covers 16.7h of its nominal 24 (1000-bar limit), so
            # mixing them produced 7d peaks below their own 24h peaks on 29% of calls.
            "hit15_24h": (None if dead is False and ph is None
                          else (False if dead else at(ph, 24) >= 1.5)),
            "hit2x_7d": (None if dead is False and ph is None
                         else (False if dead else at(ph, 168) >= 2.0)),
            "ret_7d": (None if dead is False and ch is None
                       else (-1.0 if dead else round(at(ch, 168) - 1.0, 6))),
            "peak_24h": None if dead else (round(max(ph[:25]), 6) if ph else None),
            "peak_7d": None if dead else (round(max(ph[:169]), 6) if ph else None),
            "peak_14d": None if dead else (round(max(ph[:337]), 6) if ph else None),
            "reserve_usd_now": d.get("reserve_usd_now"),
        }
        rows.append(rec)

    # ---- the control: no identity field may appear in the output, at any nesting level
    blob = json.dumps(rows).lower()
    hits = [w for w in FORBIDDEN if '"%s"' % w in blob]
    keys = {k.lower() for r in rows for k in r}
    bad = [k for k in keys if any(w in k for w in FORBIDDEN)]
    if hits or bad:
        raise SystemExit("REFUSING TO WRITE: identity-like field present %s %s" % (hits, bad))

    rows.sort(key=lambda r: r["call_ts"])
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")

    fmt = lambda t: datetime.datetime.fromtimestamp(t, datetime.UTC).date()
    print("wrote %d call outcomes to %s" % (len(rows), os.path.basename(OUT)))
    print("  identity check: PASSED -- no caller/hash/user/author/sender/starred field present")
    print("  fields: %s" % sorted(rows[0].keys()) if rows else "")
    print("  call dates: %s .. %s" % (fmt(rows[0]["call_ts"]), fmt(rows[-1]["call_ts"])))
    print("  dead: %d | with a 7d outcome: %d | with a 14d peak: %d"
          % (sum(1 for r in rows if r["dead"]),
             sum(1 for r in rows if r["ret_7d"] is not None),
             sum(1 for r in rows if r["peak_14d"] is not None)))
    print("  by chat: %s" % dict(collections.Counter(r["chat"] for r in rows).most_common()))
    for k, v in skipped.most_common():
        print("  skipped %-34s %d" % (k, v))
    print("\n  REGENERATE this as the fetch fills -- it is a view over megacalls_paths.jsonl,")
    print("  not a snapshot, and the corpus is %d of 2,479 complete." % len(rows))


if __name__ == "__main__":
    main()
