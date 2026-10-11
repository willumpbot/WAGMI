"""J2 -- forward trackers for the SEALED preregs. Counts only. No peeking, ever.

THE WHOLE POINT OF THIS JOB IS WHAT IT REFUSES TO DO. Each prereg committed to exactly one
interim look at a stated n and a stated alpha. If this job computed the statistic every hour and
wrote it anywhere a human could read it, the alpha spend would be unbounded and the seal would be
worthless -- the look is what costs you, not the decision to act on it.

So this job computes, for each prereg, ONLY:
  - the running n
  - whether n has reached the pre-committed unlock threshold
  - how far away it is
and writes nothing else. The statistic is computed by a human-run script on or after the unlock
date, once.

SECOND RULE, learned the hard way: a MISSING SOURCE IS NOT A COUNT OF ZERO. If the file a prereg
names is absent or unreadable this reports SOURCE-MISSING, never n=0. Reporting zero for an
unreadable file reads as "no progress" when it means "no visibility", and that confusion has
already produced two false conclusions in this project.
"""
import io
import json
import os
import time

from common import MINING, db, log, record_run

EXP = os.path.join(MINING, "server_exports")
SEAL_DAY = "2026-10-11"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "TRACKERS.md")

# (name, prereg file, unlock description, threshold)
PREREGS = [
    ("OI", "PREREG_OI_2026-10-11.md", "n_days >= 106, interim at alpha=0.005", 106),
    ("IDEAS", "PREREG_IDEAS_2026-10-11.md", "n resolved >= 87, interim at alpha=0.005", 87),
    ("ADOPT", "PREREG_ADOPT_2026-10-11.md", "both arms >= 44, interim at alpha=0.005", 44),
]


def days_since_seal():
    import datetime
    y, m, d = (int(x) for x in SEAL_DAY.split("-"))
    return (datetime.date.today() - datetime.date(y, m, d)).days


def count_oi():
    """Coin-days that actually have a 24h OI change, which is the prereg's unit of observation.

    THE BUG THIS REPLACES: it counted `ctx_snapshots/*.jsonl.gz` FILENAMES. The prereg's unit is
    a coin-day carrying `oi_chg = log(oi_t / oi_{t-1d})`, which needs an observation AND one 24
    hours earlier. With the archive spanning 20.6 hours, no coin had a 24h lag and the true n was
    ZERO -- while this reported 1 and would have gone on reporting a number one higher than the
    truth forever, because day one can never have a lag. Counting the files is counting the wrong
    object, and it was wrong in the direction that made the test look closer than it was.
    """
    try:
        c = db()
        rows = c.execute("SELECT coin, t FROM ctx WHERE oi IS NOT NULL").fetchall()
        c.close()
    except Exception as e:
        return None, "SOURCE-UNREADABLE: panel store (%s)" % str(e)[:60]
    if not rows:
        return None, ("SOURCE-MISSING: no ctx rows carry `oi`. The archive may exist without the "
                      "column, which is not the same as zero observations")
    # THE UNIT IS n_days, NOT coin-days. The prereg sizes its MDE as 2.8*SD/sqrt(n_days), so a
    # day on which 178 coins are observed is ONE observation of the clustered quantity, not 178.
    # My first fix counted coin-days and published "n=178, UNLOCKED" for a prereg holding under a
    # day of data -- a worse error than the off-by-one it replaced, because it claimed the look
    # was open. Counting the right object is not enough; it has to be the object the prereg sizes.
    #
    # And a calendar-day pair is not a 24h lag: the archive spans 2 UTC days but only 20.6 hours,
    # so a day-index pair would "qualify" on observations 20 h apart. A real pair needs two
    # observations about 24 h apart, so that is what is required here (+/- 2 h).
    DAY_MS = 86_400_000
    TOL_MS = 2 * 3_600_000
    by_coin = {}
    for coin, t in rows:
        by_coin.setdefault(coin, []).append(int(t))
    qualifying_days = set()
    for coin, ts in by_coin.items():
        ts.sort()
        s = set(ts)
        for t in ts:
            want = t - DAY_MS
            # any earlier observation within tolerance of exactly 24h back
            if any(abs(u - want) <= TOL_MS for u in s if u < t):
                qualifying_days.add(t // DAY_MS)
                break        # one qualifying day per coin is enough to mark the day present
    n_days = len(qualifying_days)
    allt = [t for _c, t in rows]
    span_h = (max(allt) - min(allt)) / 3_600_000.0
    note = ("%d day(s) on which a 24h OI change is computable, from %.1f h of archive over "
            "%d coins. The unit is DAYS, not coin-days: one day is one observation of the "
            "clustered quantity the prereg sizes" % (n_days, span_h, len(by_coin)))
    if n_days == 0:
        note += (" — GENUINE ZERO: the archive is under 24 h deep, so no 24h pair exists yet. "
                 "Not a missing source")
    return n_days, note


def count_ideas():
    """Resolved ideas only. An unresolved idea is not an observation."""
    p = os.path.join(EXP, "ai_plans.json")
    if not os.path.exists(p):
        return None, "SOURCE-MISSING: ai_plans.json absent"
    try:
        d = json.load(io.open(p, encoding="utf-8"))
    except (ValueError, OSError) as e:
        return None, "SOURCE-UNREADABLE: %s" % str(e)[:80]
    items = d if isinstance(d, list) else d.get("plans") or d.get("ideas") or []
    if not isinstance(items, list):
        return None, "SOURCE-SHAPE-UNKNOWN: no list of ideas found"
    # the resolution field is `result`. If NOT ONE idea carries it, that is a schema change,
    # not a count of zero -- the distinction this whole job exists to preserve.
    keys = set()
    for it in items:
        if isinstance(it, dict):
            keys |= set(it)
    if items and "result" not in keys:
        return None, ("SOURCE-SHAPE-CHANGED: %d ideas present but none carries a `result` field; "
                      "this is NOT a count of zero" % len(items))
    # `result` is a DICT -- {"status": "open", "live_r": ...}. Comparing it to the string
    # "open" marks every open idea as resolved, which is what the first version of this did.
    # Resolution is result.status, and an OPEN idea is not an observation.
    OPEN = (None, "", "open", "pending", "live", "filled")

    def resolved(it):
        r = it.get("result") if isinstance(it, dict) else None
        if isinstance(r, dict):
            return str(r.get("status") or "").lower() not in OPEN
        return r not in OPEN

    n = sum(1 for it in items if resolved(it))
    note = "%d of %d ideas resolved" % (n, len(items))
    srv = (d.get("stats") or {}).get("n") if isinstance(d, dict) else None
    if srv is not None and srv != n:
        note += " (server stats.n=%s -- disagrees, worth a look)" % srv
    return n, note


def count_adopt():
    """Two arms: ideas ADOPTED, and ideas SKIPPED. A skip lives on the IDEA side, not the plan side.

    TWO BUGS THIS REPLACES, both of which pinned the test at zero forever:

    1. WRONG SOURCE. It read `owner_plans.jsonl` (5 rows, none carrying the fields). The fields
       landed in `plans.json`, where 3 of 4 plans carry `adopt_mode`.
    2. WRONG DEFINITION OF A SKIP, which was the fatal one. It counted a skip as a *plan row*
       carrying `source_idea_id` with no `adopt_mode` -- but a skipped idea produces NO PLAN ROW
       AT ALL. So the skip arm could only ever be 0, and `min(adopt, 0) = 0` for all time. The
       test was sealed against data that had no route to exist.

    A skip is therefore counted here as: an idea whose entry window has ELAPSED and which no
    admissible plan references. Until the window elapses the idea is still live and is neither
    adopted nor skipped -- counting it either way would be inventing a decision.

    The prereg admits only `source_inferred` false/absent: a link recovered by matching coin and
    side cannot tell adopting an idea from independently reaching the same view.
    """
    pp = os.path.join(EXP, "plans.json")
    ip = os.path.join(EXP, "ai_plans.json")
    if not os.path.exists(pp):
        return None, "SOURCE-MISSING: plans.json absent"
    if not os.path.exists(ip):
        return None, "SOURCE-MISSING: ai_plans.json absent (needed for the skip arm)"
    try:
        pd = json.load(io.open(pp, encoding="utf-8"))
        idd = json.load(io.open(ip, encoding="utf-8"))
    except (ValueError, OSError) as e:
        return None, "SOURCE-UNREADABLE: %s" % str(e)[:80]
    plans = pd if isinstance(pd, list) else (pd.get("plans") or [])
    ideas = idd if isinstance(idd, list) else (idd.get("ideas") or [])
    if not isinstance(plans, list) or not isinstance(ideas, list):
        return None, "SOURCE-SHAPE-UNKNOWN"

    adopt = adjust = inferred = 0
    claimed = set()
    for r in plans:
        if not isinstance(r, dict):
            continue
        mode = str(r.get("adopt_mode") or "").lower()
        if mode not in ("adopt", "adjust"):
            continue
        if r.get("source_inferred") is True:
            inferred += 1
            continue                      # backfilled link: inadmissible, by the prereg
        if r.get("source_idea_id"):
            claimed.add(r["source_idea_id"])
        if mode == "adopt":
            adopt += 1
        else:
            adjust += 1                   # reported separately, never merged into adopted

    now = time.time()
    skip = live = 0
    for it in ideas:
        if not isinstance(it, dict) or not it.get("id"):
            continue
        if it["id"] in claimed:
            continue
        try:
            elapsed = now > float(it.get("ts") or 0) + float(it.get("entry_window_h") or 24) * 3600
        except (TypeError, ValueError):
            elapsed = False
        if elapsed:
            skip += 1
        else:
            live += 1

    note = ("adopt=%d adjust=%d skip=%d (%d ideas still inside their entry window; "
            "%d decisions EXCLUDED as source_inferred)" % (adopt, adjust, skip, live, inferred))
    if adopt == 0 and skip == 0 and inferred:
        note += (" — note this is NOT 'no decisions taken': %d were, and all were backfilled "
                 "links the prereg does not admit" % inferred)
    return min(adopt, skip), note


COUNTERS = {"OI": count_oi, "IDEAS": count_ideas, "ADOPT": count_adopt}


def main():
    t0 = time.time()
    lines = ["# Prereg forward trackers -- COUNTS ONLY, no statistics",
             "",
             "_Written by `crunch/j2_trackers.py`. This file deliberately contains no test",
             "statistic, no p-value and no direction. Each prereg committed to ONE interim look",
             "at a stated n; computing the statistic every hour would spend that alpha silently.",
             "A missing source is reported as SOURCE-MISSING, never as n=0._",
             "",
             "_Updated %s. Seal date %s (%d days ago)._" % (
                 time.strftime("%Y-%m-%d %H:%M"), SEAL_DAY, days_since_seal()),
             "",
             "| prereg | unlock condition | running n | reached? | remaining |",
             "|---|---|---|---|---|"]
    ok = True
    for name, _f, cond, thr in PREREGS:
        n, note = COUNTERS[name]()
        if n is None:
            lines.append("| `%s` | %s | **%s** | — | — |" % (name, cond, note))
            ok = False
            log("j2", "%s: %s" % (name, note))
            continue
        reached = n >= thr
        lines.append("| `%s` | %s | **%d** (%s) | %s | %s |" % (
            name, cond, n, note, "**YES -- look is unlocked**" if reached else "not yet",
            "—" if reached else "%d more" % (thr - n)))
        log("j2", "%s n=%d/%d %s" % (name, n, thr, "UNLOCKED" if reached else ""))
    lines += ["",
              "**Nothing in this table authorises a conclusion.** When a row reads *unlocked*, the",
              "analysis is run once, by hand, against the sealed design -- and its result is",
              "reported whichever way it comes out.", ""]
    io.open(OUT, "w", encoding="utf-8").write("\n".join(lines))
    record_run("j2_trackers", ok, len(PREREGS), time.time() - t0)
    log("j2", "wrote %s" % os.path.basename(OUT))


if __name__ == "__main__":
    from common import standalone
    standalone(main, 'j2')
