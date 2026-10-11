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

JOBS = ["j1_panels", "j5_backfill", "j2_trackers", "j4_integrity", "j3_replications"]
STATUS = os.path.join(HERE, "STATUS.md")

# committed by the runner; the panel store and the server`s own exports are excluded
COMMIT_PATHS = [
    "bot/data/laptop_mining/crunch/TRACKERS.md",
    "bot/data/laptop_mining/crunch/INTEGRITY.md",
    "bot/data/laptop_mining/crunch/REPLICATIONS.md",
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
              "- **j3_replications** — recomputes the live scan-flag conditions from",
              "  `server_exports/scanner.py` and the chief Brier on days the original tests",
              "  never saw, and appends each measurement with its n, its equal-weighted",
              "  day-block mean and its MDE. **It writes no verdicts** — a human reads",
              "  `REPLICATIONS.md` on the date stated in it. Unblocked 2026-10-11 when the real",
              "  definitions arrived; what is still missing is reported as SOURCE-MISSING per",
              "  metric rather than as a zero.",
              ""]
    io.open(STATUS, "w", encoding="utf-8").write("\n".join(lines))


SERVER_BRANCH = "origin/desktop-overdrive-2026-05-30"
EXPORTS = "bot/data/laptop_mining/server_exports"


def checkout_server_exports():
    """Bring the server's exports into the working tree, because the jobs read FILES.

    The server owns this directory; the laptop only consumes it. So this is a one-way
    overwrite from the server branch and never a merge -- a local edit here would be a
    laptop pretending to be the server, which is exactly what must not happen.

    Returns the number of paths checked out, so the runner can log a real number rather
    than claiming success.
    """
    names = git("ls-tree", "-r", "--name-only", SERVER_BRANCH, "--", EXPORTS, check=False)
    paths = [p for p in (names or "").splitlines() if p.strip()]
    if not paths:
        log("run", "WARNING: the server branch lists no files under %s" % EXPORTS)
        return 0
    # one checkout for the whole tree; cheap and atomic enough for our purposes
    git("checkout", SERVER_BRANCH, "--", EXPORTS, check=False)
    return len(paths)


LOCK = os.path.join(HERE, "crunch.lock")
STALE_LOCK_S = 3 * 3600


def acquire_lock():
    """Refuse to run twice at once.

    OBSERVED, not hypothetical: the 13:10 scheduled run started j5 while a manual j5 was still
    sweeping the perp universe, so two processes were hitting the same rate-limited API. That is
    the same shape as the duplicate-poster collision that jammed Instagram in Jul 2026, and the
    standing rule here is one process at a time.

    O_EXCL makes the create-or-fail atomic, so two runners starting in the same second cannot
    both win. A lock older than STALE_LOCK_S is treated as a crashed run and broken.
    """
    if os.path.exists(LOCK):
        age = time.time() - os.path.getmtime(LOCK)
        if age < STALE_LOCK_S:
            try:
                who = io.open(LOCK, encoding="utf-8").read().strip()
            except OSError:
                who = "unknown"
            log("run", "ANOTHER RUN IS ACTIVE (%s, %.0fs old) -- exiting without doing anything"
                % (who, age))
            return False
        log("run", "breaking stale lock (%.0fs old, limit %ds)" % (age, STALE_LOCK_S))
        try:
            os.unlink(LOCK)
        except OSError:
            pass
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        log("run", "lost the race for the lock -- exiting")
        return False
    with os.fdopen(fd, "w") as f:
        f.write("pid %d started %s" % (os.getpid(), time.strftime("%Y-%m-%d %H:%M:%S")))
    return True


def release_lock():
    try:
        os.unlink(LOCK)
    except OSError:
        pass


def main():
    started = time.time()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    use_git = "--no-git" not in sys.argv
    jobs = [j for j in JOBS if not args or any(a in j for a in args)]

    if not acquire_lock():
        return 0

    try:
        return _run(started, args, use_git, jobs)
    finally:
        release_lock()


def _run(started, args, use_git, jobs):
    branch = assert_laptop_branch()
    log("run", "branch %s, jobs: %s" % (branch, ", ".join(jobs)))

    if use_git:
        try:
            git("fetch", "origin", "desktop-overdrive-2026-05-30", check=False)
            # FETCHING IS NOT ENOUGH, and assuming it was cost a real claim. `fetch` updates the
            # remote ref and leaves the WORKING TREE alone, so every job that reads
            # server_exports/ was reading whatever had last been copied there by hand. Measured
            # at the time this was found: the local scanner.py was 188 lines with ZERO
            # momentum_small while the server's was 202, and chief.py was absent entirely --
            # so j3_replications was built against a pre-10-11 definition and I told the server
            # it had been built against theirs.
            n = checkout_server_exports()
            log("run", "fetched the server branch and checked out %d export path(s)" % n)
        except Exception as e:
            log("run", "fetch/checkout failed (continuing): %s" % str(e)[:160])

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
