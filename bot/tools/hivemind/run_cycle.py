"""One hivemind cycle for Task Scheduler: assemble every voice, then rebuild the desk.

  pythonw tools/hivemind/run_cycle.py            # every 15 min
  pythonw tools/hivemind/run_cycle.py --chief    # every 4h: also the Opus chief read + grading
"""
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
LOG = HERE.parents[1] / "data" / "hivemind" / "cycle.log"


def log(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z {msg}\n")


def main():
    import assemble, desk, chief   # assemble fixes sys.path order (copilot before tools)
    sys.path.remove(str(assemble.BOT / "tools" / "copilot"))
    sys.path.insert(0, str(assemble.BOT / "tools" / "copilot"))
    try:
        if "--chief" in sys.argv:
            import voice_grader
            voice_grader.main()   # refresh per-voice trust before the voices are assembled
        try:
            import whales
            whales.snapshot()
        except Exception as e:
            log(f"whales failed: {e}")
        assemble.assemble()
        if "--chief" in sys.argv:
            out = chief.run_chief()
            log("chief: " + ", ".join(f"{s} {c.get('lean')}{c.get('conviction')}" for s, c in out.get("coins", {}).items()))
        chief.resolve()
        chief.resolve(chief.OWNER_CALLS, chief.OWNER_CARD)
        try:
            import geometry_shadow
            geometry_shadow.main()
        except Exception as e:
            log(f"geometry shadow failed: {e}")
        try:
            import phone_link
            phone_link.main()
        except Exception as e:
            log(f"phone link failed: {e}")
        try:
            import journal
            journal.main()
        except Exception as e:
            log(f"journal failed: {e}")
        for mod, fn in (("scanner", "run"), ("plans", "resolve"), ("tg_track", "run")):
            try:
                res = getattr(__import__(mod), fn)()
                if mod == "scanner":
                    import scan_grader
                    scan_grader.log(res)
                    scan_grader.resolve()
            except Exception as e:
                log(f"{mod} failed: {e}")
        try:
            import decisions
            decisions.build()
        except Exception as e:
            log(f"decisions failed: {e}")
        desk.build()
        desk.build_terminal()
        log("cycle ok" + (" (+chief)" if "--chief" in sys.argv else ""))
    except Exception:
        log("cycle FAILED: " + traceback.format_exc().replace("\n", " | ")[-800:])
        raise


if __name__ == "__main__":
    main()
