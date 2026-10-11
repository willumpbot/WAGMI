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

from common import MINING, log, record_run

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
    """n_days accrues with calendar days of ctx_snapshots after the seal."""
    p = os.path.join(EXP, "ctx_snapshots")
    if not os.path.isdir(p):
        return None, "SOURCE-MISSING: ctx_snapshots/ absent"
    days = {f[:10] for f in os.listdir(p) if f.endswith(".jsonl.gz")}
    after = sorted(d for d in days if d >= SEAL_DAY)
    return len(after), "%d snapshot days on or after the seal" % len(after)


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
    """Two arms, keyed on `adopt_mode` (went live 2026-10-11 in 602291cb).

    The prereg admits ONLY rows where `source_inferred` is absent or false -- a link recovered
    by matching coin and side cannot tell adopting an idea apart from independently reaching the
    same view, so backfilled links are excluded by design.

    Note on the zero: `adopt_mode` only appears on a row once a decision is actually taken, so a
    ledger with rows and no `adopt_mode` anywhere is a GENUINE zero, not a schema gap. Said
    explicitly because this job`s other counters treat a missing field as loss of visibility.
    """
    p = os.path.join(EXP, "owner_plans.jsonl")
    if not os.path.exists(p):
        return None, "SOURCE-MISSING: owner_plans.jsonl absent"
    a = adj = b = rows = inferred = 0
    try:
        for line in io.open(p, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            rows += 1
            if r.get("source_inferred") is True:
                inferred += 1
                continue
            mode = str(r.get("adopt_mode") or "").lower()
            if mode == "adopt":
                a += 1
            elif mode == "adjust":
                adj += 1          # reported separately, never merged into adopted
            elif r.get("source_idea_id") and not mode:
                b += 1            # an idea was on the table and was not taken
    except OSError as e:
        return None, "SOURCE-UNREADABLE: %s" % str(e)[:80]
    note = ("adopt=%d adjust=%d skip=%d over %d plan rows (%d excluded as source_inferred)"
            % (a, adj, b, rows, inferred))
    if a == 0 and b == 0:
        note += " — genuine zero: adopt_mode populates only when a decision is taken"
    return min(a, b), note


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
    main()
