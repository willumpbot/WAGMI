"""The hourly runner. Pulls the server branch, runs every job, commits results to the laptop
branch, pushes. No Claude tokens anywhere in this path.

SAFETY, in order of how badly it would hurt to get wrong:
  1. It REFUSES to run if the repo is not on the laptop branch. The desktop owns live ops and its
     own branch; two machines writing one branch is how you lose a day.
  2. It commits ONLY the crunch outputs and research artifacts -- never the panel store (a
     multi-hundred-MB sqlite file), never anything under server_exports/ (the server owns that).
  3. A single job failing does not stop the others, and the failure is recorded in the run ledger
     and surfaced in STATUS.md rather than swallowed.
  4. Nothing here touches the bot, the terminal, or any live process.

Usage:
  python crunch_all.py            # all jobs
  python crunch_all.py j1 j4      # named jobs only
  python crunch_all.py --no-git   # run jobs, do not pull/commit/push
"""
import importlib
import io
import os
import sys
import time
import traceback

from common import HERE, assert_laptop_branch, db, git, init_schema, log

JOBS = ["j1_panels", "j5_backfill", "j2_trackers", "j4_integrity"]
STATUS = os.path.join(HERE, "STATUS.md")

# committed by the runner; the panel store and the server`s own exports are excluded
COMMIT_PATHS = [
    "bot/data/laptop_mining/crunch/TRACKERS.md",
    "bot/data/laptop_mining/crunch/INTEGRITY.md",
    "bot/data/laptop_mining/crunch/STATUS.md",
    "bot/data/laptop_mining/crunch/integrity_state.json",
]


def write_status(results, started):
    lines = ["# Crunch layer status",
             "",
             "_Written by `crunch/crunch_all.py`. This is the unattended layer: it runs hourly,",
             "costs no Claude tokens, and its job is to make sure that when a human does look,",
             "the data is already joined and the integrity is already checked._",
             "",
             "_Last run %s, took %.0fs._" % (time.strftime("%Y-%m-%d %H:%M"),
                                             time.time() - started),
             "",
             "| job | result | rows | secs | note |",
             "|---|---|---|---|---|"]
    for name, ok, rows, secs, note in results:
        lines.append("| `%s` | %s | %s | %.0f | %s |" % (
            name, "ok" if ok else "**FAILED**", rows if rows is not None else "—", secs,
            (note or "")[:160].replace("|", "/")))
    bad = [r for r in results if not r[1]]
    lines += [""]
    if bad:
        lines += ["## 🔴 %d job(s) failed this run" % len(bad), ""]
        lines += ["- `%s`: %s" % (r[0], (r[4] or "")[:300]) for r in bad] + [""]
    else:
        lines += ["All jobs succeeded.", ""]
    lines += ["## What each job does", "",
              "- **j1_panels** — folds `server_exports/` (ctx snapshots, 5m candles) and the 1h",
              "  CSV panel into `crunch/panels.sqlite`, keyed `(coin, t)` so it is idempotent.",
              "  The laptop is the long-term archive: the server keeps 30 days and Hyperliquid",
              "  deletes 5m candles after ~17 days.",
              "- **j5_backfill** — keeps 1h candles and funding history current for every live",
              "  perp, throttled 0.8s/call because an unthrottled sweep hit HTTP 429 after 37",
              "  coins. First run paginates back ~2.3 years; later runs only fetch forward.",
              "- **j2_trackers** — running n for each sealed prereg and nothing else. No",
              "  statistic is computed before its unlock date; the look is what spends the alpha.",
              "- **j4_integrity** — presence, growth, fill rates and gaps per export. Treats",
              "  `hb_age_s > 1e8` as a read error, which is what caused two false DOWN alerts.",
              "",
              "## Not built yet, deliberately", "",
              "- **j3_replications** — out-of-sample recomputation of the live `funding_hot`",
              "  stop-exceedance rule, scan-flag outcomes and chief Brier. **Blocked on the",
              "  exact live definitions**: writing a replication against a guessed definition",
              "  produces numbers that look like replications and are not. That is an ask for",
              "  the server, not something to approximate here.",
              ""]
    io.open(STATUS, "w", encoding="utf-8").write("\n".join(lines))


def main():
    started = time.time()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    use_git = "--no-git" not in sys.argv
    jobs = [j for j in JOBS if not args or any(a in j for a in args)]

    branch = assert_laptop_branch()
    log("run", "branch %s, jobs: %s" % (branch, ", ".join(jobs)))

    if use_git:
        try:
            git("fetch", "origin", "desktop-overdrive-2026-05-30", check=False)
            log("run", "fetched the server branch")
        except Exception as e:
            log("run", "fetch failed (continuing): %s" % str(e)[:120])

    init_schema()
    results = []
    sys.path.insert(0, HERE)
    for name in jobs:
        t0 = time.time()
        try:
            m = importlib.import_module(name)
            importlib.reload(m)
            m.main()
            conn = db()
            row = conn.execute("SELECT ok, rows, note FROM runs WHERE job LIKE ? "
                               "ORDER BY started DESC LIMIT 1",
                               (name.split("_")[0] + "%",)).fetchone()
            conn.close()
            results.append((name, bool(row[0]) if row else True,
                            row[1] if row else None, time.time() - t0,
                            row[2] if row else ""))
        except Exception:
            tb = traceback.format_exc().strip().splitlines()[-1]
            log("run", "%s FAILED: %s" % (name, tb))
            results.append((name, False, None, time.time() - t0, tb))

    write_status(results, started)

    if use_git:
        try:
            assert_laptop_branch()
            existing = [p for p in COMMIT_PATHS
                        if os.path.exists(os.path.join(
                            os.path.dirname(os.path.dirname(os.path.dirname(
                                os.path.dirname(HERE)))), p))]
            if existing:
                git("add", *existing, check=False)
                if git("diff", "--cached", "--name-only", check=False):
                    ok = sum(1 for r in results if r[1])
                    git("commit", "-q", "-m",
                        "crunch: hourly run, %d/%d jobs ok" % (ok, len(results)),
                        check=False)
                    git("push", "-q", "origin", "HEAD:" + branch, check=False)
                    log("run", "committed and pushed")
                else:
                    log("run", "nothing changed, no commit")
        except Exception as e:
            log("run", "git step failed: %s" % str(e)[:200])

    bad = [r[0] for r in results if not r[1]]
    log("run", "done in %.0fs. %s" % (time.time() - started,
                                      "FAILED: " + ", ".join(bad) if bad else "all ok"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
