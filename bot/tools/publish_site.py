#!/usr/bin/env python3
r"""
Publish the bot's fresh data snapshots to the live website.

THE BUG THIS FIXES (found 2026-09-07)
  snapshot_export.py writes fresh JSON every 15 minutes to
      C:\Users\vince\WAGMI\web\public\data\
  ...where it sat UNTRACKED and never went anywhere.

  The site deploys from a separate sparse worktree,
      C:\Users\vince\WAGMI_web_deploy\   (tracks origin/main)
  whose copies of those same JSONs were frozen at 24 July.

  tunnel_manager.trigger_rebuild() pushed EMPTY commits to main, so Vercel
  faithfully rebuilt and re-served 45-day-old data every single time.

  This script closes the gap: it copies the fresh snapshots into the deploy
  worktree, commits them with a real message, and pushes.

SAFETY
  - Pushing is OPT-IN. Without --push this is a dry run that only reports
    what would change. Publishing to a public site should be deliberate.
  - The worktree is reset to origin/main first, exactly as trigger_rebuild
    already does. That reset is confined to WAGMI_web_deploy and never
    touches the main WAGMI checkout or its unpushed branches.
  - If nothing changed, it does nothing rather than making an empty commit.
"""
import argparse
import filecmp
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SRC = Path(r"C:\Users\vince\WAGMI\web\public\data")
DEPLOY = Path(r"C:\Users\vince\WAGMI_web_deploy")
DST = DEPLOY / "web" / "public" / "data"


def git(*args, check=False):
    r = subprocess.run(["git", "-C", str(DEPLOY), *args],
                       capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(args), r.stderr.strip()))
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true",
                    help="actually commit and push to origin/main (default: dry run)")
    args = ap.parse_args()

    if not SRC.is_dir():
        print("ERROR: no snapshot source at %s" % SRC)
        return 2
    if not DEPLOY.is_dir():
        print("ERROR: no deploy worktree at %s" % DEPLOY)
        return 2

    src_files = sorted(SRC.glob("*.json"))
    if not src_files:
        print("ERROR: no snapshots in %s - is WAGMI-Snapshot running?" % SRC)
        return 2

    # Match trigger_rebuild(): start from a clean origin/main.
    git("fetch", "origin", "main")
    r = git("reset", "--hard", "origin/main")
    if r.returncode != 0:
        print("ERROR: could not reset deploy worktree: %s" % r.stderr.strip())
        return 2

    DST.mkdir(parents=True, exist_ok=True)

    changed, added, same = [], [], []
    for f in src_files:
        target = DST / f.name
        if not target.exists():
            added.append(f.name)
        elif filecmp.cmp(f, target, shallow=False):
            same.append(f.name)
            continue
        else:
            changed.append(f.name)
        if args.push:
            shutil.copy2(f, target)

    total = len(changed) + len(added)
    print("Snapshot source : %s" % SRC)
    print("Deploy worktree : %s" % DEPLOY)
    print("  unchanged     : %d" % len(same))
    print("  updated       : %d" % len(changed))
    print("  new           : %d" % len(added))

    if total == 0:
        print("\nNothing to publish - the site already has this data.")
        return 0

    for n in (added + changed)[:12]:
        print("    - %s" % n)
    if total > 12:
        print("    ... and %d more" % (total - 12))

    if not args.push:
        print("\nDRY RUN. Nothing was copied, committed or pushed.")
        print("Re-run with --push to publish these %d file(s) to the live site." % total)
        return 0

    git("add", "web/public/data")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    msg = ("chore(web): publish live data snapshots (%s)\n\n"
           "%d updated, %d new. Fixes snapshots that had been frozen since "
           "2026-07-24 because they were exported to the bot repo (untracked) "
           "rather than the deploy worktree." % (stamp, len(changed), len(added)))
    c = git("commit", "-m", msg)
    if c.returncode != 0 and "nothing to commit" in (c.stdout + c.stderr).lower():
        print("\nNothing staged after all - no commit made.")
        return 0
    if c.returncode != 0:
        print("ERROR committing: %s" % (c.stderr or c.stdout).strip())
        return 1

    p = git("push", "origin", "HEAD:main")
    if p.returncode != 0:
        print("ERROR pushing: %s" % p.stderr.strip()[:400])
        return 1

    print("\nPublished %d file(s) to origin/main. Vercel will rebuild." % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
