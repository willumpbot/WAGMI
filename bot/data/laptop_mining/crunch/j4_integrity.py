"""J4 -- integrity checks on every export, written to INTEGRITY.md.

THIS JOB EXISTS BECAUSE BAD DATA HAS ALREADY PRODUCED FALSE ALERTS AND FALSE CONCLUSIONS HERE:
  - uptime.jsonl rows with hb_age_s ~ 1.79e9 were heartbeat.json read mid-write, not downtime.
    They sent the owner two false "bot DOWN" alerts. Any hb_age_s > 1e8 is a READ ERROR.
  - a column that is 100% null reads identically to a column that is 100% zero unless you check
    fill rates, and defaults have been mistaken for measurements in this project before.

So this reports, per export: whether it is present, whether it is GROWING, its fill rates, and
its gaps. It flags regressions rather than interpreting them.
"""
import glob
import subprocess
import gzip
import io
import json
import os
import time

from common import MINING, db, log, record_run

EXP = os.path.join(MINING, "server_exports")
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "INTEGRITY.md")
STATE = os.path.join(HERE, "integrity_state.json")
HB_BAD = 1e8


def read_lines(p, limit=60000):
    try:
        op = gzip.open(p, "rt", encoding="utf-8") if p.endswith(".gz") else io.open(
            p, encoding="utf-8")
        with op as f:
            for i, line in enumerate(f):
                if i >= limit:
                    return
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except ValueError:
                        continue
    except (OSError, EOFError):
        return


def fill_rates(rows):
    keys = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        for k, v in r.items():
            s = keys.setdefault(k, [0, 0])
            s[0] += 1
            if v not in (None, "", [], {}):
                s[1] += 1
    return {k: (100.0 * v[1] / v[0] if v[0] else 0.0, v[0]) for k, v in keys.items()}


def check_uptime():
    p = os.path.join(EXP, "uptime.jsonl")
    if not os.path.exists(p):
        return "`uptime.jsonl` **SOURCE-MISSING** -- not present in the export."
    rows = list(read_lines(p))
    bad = [r for r in rows if isinstance(r.get("hb_age_s"), (int, float))
           and r["hb_age_s"] > HB_BAD]
    dead = [r for r in rows if r.get("alive") is False]
    real_dead = [r for r in dead if not (isinstance(r.get("hb_age_s"), (int, float))
                                         and r["hb_age_s"] > HB_BAD)]
    return ("`uptime.jsonl` %d rows, %d alive:false of which **%d are read errors** "
            "(hb_age_s > 1e8) and %d are real. Read errors must never alert."
            % (len(rows), len(dead), len(bad), len(real_dead)))


def check_ctx_gaps():
    ps = sorted(glob.glob(os.path.join(EXP, "ctx_snapshots", "*.jsonl.gz")))
    if not ps:
        return "`ctx_snapshots/` **SOURCE-MISSING**."
    out = []
    for p in ps[-3:]:
        ts = sorted({int(r["t"]) for r in read_lines(p) if r.get("t")})
        if len(ts) < 2:
            out.append("%s: %d stamps" % (os.path.basename(p)[:10], len(ts)))
            continue
        d = [ts[i + 1] - ts[i] for i in range(len(ts) - 1)]
        med = sorted(d)[len(d) // 2]
        gaps = [x for x in d if x > 3 * med]
        out.append("%s: %d stamps, median cadence %ds, **%d gaps > 3x**"
                   % (os.path.basename(p)[:10], len(ts), med, len(gaps)))
    return "`ctx_snapshots/` " + "; ".join(out)


CADENCE_S = 3600          # the scheduled task is hourly
STALE_AFTER_S = 2.5 * 3600


def check_self_freshness():
    """Is this layer still being run at all?

    THRESHOLD IS PICKED FROM THE CADENCE, not by feel: hourly cadence, so two consecutive
    missed runs (2.5h) is the alarm. One missed run is a reboot or a long j5 sweep and is not
    news; two means the scheduler is not firing.

    The run ledger is the evidence, and the PREVIOUS run is what matters -- this very run is
    about to insert its own row, so a check against `now` would always look fresh.
    """
    try:
        c = db()
        rows = c.execute("SELECT started, job FROM runs ORDER BY started DESC LIMIT 400").fetchall()
        c.close()
    except Exception as e:
        return "**cannot read the run ledger** (%s) -- freshness unknown, which is itself a problem" \
            % str(e)[:80]
    if not rows:
        return "run ledger is **empty** -- no job has ever recorded a run"
    now = time.time()
    # the newest run belonging to an EARLIER wall-clock hour than this one
    this_hour = int(now // CADENCE_S)
    prior = [r[0] for r in rows if int(r[0] // CADENCE_S) < this_hour]
    if not prior:
        return ("only this hour's runs are in the ledger (%d rows) -- too new to judge freshness"
                % len(rows))
    age = now - max(prior)
    verdict = ("🔴 **STALE: the layer has not run for %.1f h** (alarm at %.1f h, which is two "
               "missed hourly runs). Check the scheduled task: "
               "`schtasks /query /tn WAGMI-LaptopCrunch /fo LIST`"
               % (age / 3600.0, STALE_AFTER_S / 3600.0)) if age > STALE_AFTER_S else \
              ("fresh -- previous run was %.1f h ago, inside the %.1f h alarm"
               % (age / 3600.0, STALE_AFTER_S / 3600.0))
    # and what the scheduler itself thinks, which is the only direct evidence
    sched = ""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "$i=Get-ScheduledTaskInfo -TaskName 'WAGMI-LaptopCrunch' -ErrorAction Stop;"
             "$t=Get-ScheduledTask -TaskName 'WAGMI-LaptopCrunch';"
             "'{0}|{1}|{2}|{3}' -f $t.State,$i.LastTaskResult,$i.NextRunTime,$i.NumberOfMissedRuns"],
            capture_output=True, text=True, timeout=30)
        out = (r.stdout or "").strip().splitlines()
        if out and "|" in out[-1]:
            st, res, nxt, miss = (out[-1].split("|") + ["", "", "", ""])[:4]
            bad = res.strip() not in ("0", "267009")      # 0 = ok, 267009 = currently running
            sched = (" Scheduler says: state **%s**, last result **%s**%s, next %s, missed %s."
                     % (st.strip(), res.strip(), " (NOT success)" if bad else "",
                        nxt.strip() or "?", miss.strip() or "?"))
        else:
            sched = " Scheduler **did not answer** -- the task may have been removed."
    except Exception:
        sched = " Could not query the scheduler."
    return verdict + sched


LAST_SYNC = os.path.join(EXP, ".last_sync")
SYNC_STALE_S = 3 * 3600


def measure(p):
    """Size a file by its CONTENT, not its bytes.

    FALSE ALARM I ACTUALLY RAISED: this used compressed byte size, so when the server made its
    gzip headers deterministic (mtime=0) the header bytes changed and j4 reported
    `entry_gate_log` and `floor_decisions_log` as SHRANK -- while the decompressed line counts
    were identical (5,383 = 5,383 and 61 = 61). Compressed size is not content size, which is
    the same shape as the server's own rule that a label is not a provenance.

    So: .gz and .jsonl are measured in ROWS, everything else in bytes, and the unit is recorded
    alongside so a future comparison cannot mix them.
    """
    if os.path.isdir(p):
        tot = 0
        for f in sorted(os.listdir(p)):
            fp = os.path.join(p, f)
            if os.path.isfile(fp):
                tot += measure(fp)[0]
        return tot, "rows+bytes"
    if p.endswith(".gz"):
        try:
            n = 0
            with gzip.open(p, "rt", encoding="utf-8", errors="replace") as f:
                for _ in f:
                    n += 1
            return n, "rows"
        except (OSError, EOFError):
            return -1, "unreadable"
    if p.endswith((".jsonl", ".csv")):
        try:
            n = 0
            with io.open(p, encoding="utf-8", errors="replace") as f:
                for _ in f:
                    n += 1
            return n, "rows"
        except OSError:
            return -1, "unreadable"
    try:
        return os.path.getsize(p), "bytes"
    except OSError:
        return -1, "unreadable"


def check_sync_freshness():
    """Is the server still shipping? Their ask: a failed push only returns a string on their
    side, so the laptop is the only place that would notice the feed stopping."""
    if not os.path.exists(LAST_SYNC):
        return ("`server_exports/.last_sync` **SOURCE-MISSING** -- cannot tell whether the "
                "server is still shipping. That is not the same as the feed being fine.")
    age = time.time() - os.path.getmtime(LAST_SYNC)
    if age > SYNC_STALE_S:
        return ("🔴 **THE SERVER FEED LOOKS STOPPED: `.last_sync` is %.1f h old** (alarm at "
                "%.0f h). Every export below is that stale, whatever its own numbers say."
                % (age / 3600.0, SYNC_STALE_S / 3600.0))
    return "server feed fresh -- `.last_sync` %.1f h old, alarm at %.0f h" % (
        age / 3600.0, SYNC_STALE_S / 3600.0)


def check_outputs_tracked():
    """Can this layer's own reports actually reach git?

    THIS BIT FOR REAL. The repo ignores `bot/data/**` and re-includes the mining deliverables
    with SINGLE-LEVEL negations (`laptop_mining/*.md`). Everything in `laptop_mining/crunch/`
    sits one directory deeper, so it fell straight back through -- and because the runner calls
    `git add` with check=False, it failed silently. STATUS.md, TRACKERS.md and INTEGRITY.md were
    written every hour and never committed; the log said "nothing changed, no commit", which is
    indistinguishable from genuinely nothing changing.

    The .gitignore comment says the same trap bit on 2026-10-08. So it is checked here rather
    than trusted.
    """
    names = ["STATUS.md", "TRACKERS.md", "INTEGRITY.md"]
    bad = []
    for n in names:
        path = os.path.join(HERE, n)
        if not os.path.exists(path):
            continue
        try:
            r = subprocess.run(["git", "check-ignore", "-q", path],
                               cwd=HERE, capture_output=True, text=True, timeout=20)
            if r.returncode == 0:          # exit 0 means git IS ignoring it
                bad.append(n)
        except Exception:
            return "could not ask git whether the outputs are tracked"
    if bad:
        return ("🔴 **%s is git-ignored** -- written every hour and never committed, so the "
                "server cannot see it. Add a negation in .gitignore for "
                "`bot/data/laptop_mining/crunch/`." % ", ".join("`%s`" % b for b in bad))
    return "all three reports are trackable by git, so the hourly commit can carry them"


def main():
    t0 = time.time()
    prev = {}
    if os.path.exists(STATE):
        try:
            prev = json.load(io.open(STATE, encoding="utf-8"))
        except ValueError:
            prev = {}
    cur, regress = {}, []
    lines = ["# Export integrity",
             "",
             "_Written by `crunch/j4_integrity.py` every hour. Reports presence, growth, fill",
             "rates and gaps. Flags regressions; does not interpret them._",
             "",
             "_Updated %s._" % time.strftime("%Y-%m-%d %H:%M"),
             "",
             "## Growth -- is each export still being written?",
             "",
             "| export | size | change since last run |",
             "|---|---|---|"]
    for p in sorted(glob.glob(os.path.join(EXP, "*"))):
        name = os.path.basename(p)
        sz, unit = measure(p)
        cur[name] = {"v": sz, "u": unit}
        o = prev.get(name)
        # old state was a bare int in bytes; a unit change is not a content change
        old = o.get("v") if isinstance(o, dict) else None
        oldu = o.get("u") if isinstance(o, dict) else None
        if old is None:
            ch = "new" if o is None else "unit changed to %s -- not compared" % unit
        elif oldu != unit:
            ch = "unit changed %s to %s -- not compared" % (oldu, unit)
        elif sz > old:
            ch = "+%d %s" % (sz - old, unit)
        elif sz == old:
            ch = "unchanged"
        else:
            ch = "**SHRANK %d %s**" % (old - sz, unit)
            regress.append("%s shrank %d %s" % (name, old - sz, unit))
        lines.append("| `%s` | %d %s | %s |" % (name, sz, unit, ch))
    gone = [k for k in prev if k not in cur]
    for g in gone:
        regress.append("%s DISAPPEARED from the export" % g)
        lines.append("| `%s` | — | **DISAPPEARED** |" % g)

    lines += ["", "## Known failure modes", "", "- " + check_uptime(), "- " + check_ctx_gaps(), ""]

    lines += ["## Fill rates on the ledgers that get reasoned about", ""]
    for f in ("agent_grades_resolved.jsonl", "exit_decisions.jsonl", "chief_calls.jsonl",
              "owner_plans.jsonl", "llm_exits_resolved.jsonl"):
        p = os.path.join(EXP, f)
        if not os.path.exists(p):
            lines.append("- `%s` **SOURCE-MISSING**" % f)
            continue
        fr = fill_rates(list(read_lines(p)))
        if not fr:
            lines.append("- `%s` present but no parseable rows" % f)
            continue
        empty = sorted([k for k, (pc, _n) in fr.items() if pc == 0.0])
        thin = sorted([(k, pc) for k, (pc, _n) in fr.items() if 0 < pc < 50])
        n = max(v[1] for v in fr.values())
        lines.append("- `%s` %d rows, %d columns. %s%s" % (
            f, n, len(fr),
            ("**always-empty: %s**. " % ", ".join("`%s`" % k for k in empty[:8])) if empty
            else "no always-empty columns. ",
            ("under-50%% filled: %s" % ", ".join("`%s` %.0f%%" % (k, pc)
                                                 for k, pc in thin[:8])) if thin else ""))

    lines += ["", "## Is the layer itself still running?", "",
              "_The jobs report what they did. Nothing reported whether the SCHEDULER fired, and a",
              "stopped scheduler leaves a stale STATUS.md that reads exactly like `nothing changed`._",
              ""]
    lines += ["- " + check_self_freshness(), ""]
    lines += ["- " + check_sync_freshness(), ""]
    lines += ["- " + check_outputs_tracked(), ""]

    lines += ["", "## Panel store", ""]
    try:
        conn = db()
        for tbl in ("candles_1h", "candles_5m", "ctx", "funding_hist"):
            try:
                q = conn.execute("SELECT COUNT(*), COUNT(DISTINCT coin), MIN(t), MAX(t) "
                                 "FROM %s" % tbl).fetchone()
            except Exception:
                lines.append("- `%s` not created yet" % tbl)
                continue
            span = (q[3] - q[2]) / 86_400_000.0 if q[2] else 0
            # POOLED SPAN IS A LIE WHEN COINS DIFFER. It ran from the oldest coin's first row
            # to the newest coin's last row and reported "365.0 days" for a funding table where
            # 176 of 178 coins had stopped a year earlier. So recency is now reported per coin.
            try:
                stale = conn.execute(
                    "SELECT COUNT(*) FROM (SELECT coin, MAX(t) m FROM %s GROUP BY coin) "
                    "WHERE m < ?" % tbl,
                    (int((time.time() - 3 * 86_400) * 1000),)).fetchone()[0]
            except Exception:
                stale = None
            tail = ""
            if stale:
                tail = ("  🔴 **%d of %d coins have no row newer than 3 days** -- the span above "
                        "is the POOLED min-to-max and does not mean the table is current"
                        % (stale, q[1]))
            elif stale == 0:
                tail = "  (every coin current within 3 days)"
            lines.append("- `%s` %d rows, %d coins, %.1f days pooled span%s"
                         % (tbl, q[0], q[1], span, tail))
        conn.close()
    except Exception as e:
        lines.append("- panel db unreadable: %s" % str(e)[:120])

    if regress:
        lines = lines[:5] + ["", "## 🔴 REGRESSIONS THIS RUN", ""] + \
            ["- %s" % r for r in regress] + lines[5:]
    else:
        lines += ["", "No regressions this run.", ""]

    io.open(OUT, "w", encoding="utf-8").write("\n".join(lines))
    json.dump(cur, io.open(STATE, "w", encoding="utf-8"), indent=1)
    log("j4", "%d exports checked, %d regressions" % (len(cur), len(regress)))
    record_run("j4_integrity", not regress, len(cur), time.time() - t0,
               "; ".join(regress)[:300])


if __name__ == "__main__":
    from common import standalone
    standalone(main, 'j4')
