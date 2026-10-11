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
             "| export | bytes | change since last run |",
             "|---|---|---|"]
    for p in sorted(glob.glob(os.path.join(EXP, "*"))):
        if os.path.isdir(p):
            sz = sum(os.path.getsize(os.path.join(p, f)) for f in os.listdir(p)
                     if os.path.isfile(os.path.join(p, f)))
        else:
            sz = os.path.getsize(p)
        name = os.path.basename(p)
        cur[name] = sz
        old = prev.get(name)
        if old is None:
            ch = "new"
        elif sz > old:
            ch = "+%d" % (sz - old)
        elif sz == old:
            ch = "unchanged"
        else:
            ch = "**SHRANK %d**" % (old - sz)
            regress.append("%s shrank %d bytes" % (name, old - sz))
        lines.append("| `%s` | %d | %s |" % (name, sz, ch))
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
            lines.append("- `%s` %d rows, %d coins, %.1f days" % (tbl, q[0], q[1], span))
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
    main()
