"""Hourly workers in their OWN Task Scheduler task (WAGMI-Workers), not children of the 15-min cycle: Windows refuses
CREATE_BREAKAWAY_FROM_JOB for the cycle's job, so a child launched near the end of a cycle was killed with it (10-15).
Runs, in order, whatever is due: the 1,200-wallet snapshot (~13 min) and the laptop export (~5-10 min).
"""
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
LOG = HERE.parents[1] / "data" / "hivemind" / "cycle.log"


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%SZ ", time.gmtime()) + "workers: " + msg + "\n")


def main():
    import wallet_miner
    try:
        if wallet_miner.due(3000):
            t = time.time()
            r = wallet_miner.snapshot()
            log(f"wallet_miner {r} in {time.time() - t:.0f}s")
    except Exception as e:
        log(f"wallet_miner failed: {e} {traceback.format_exc()[-300:]}")
    import laptop_sync
    try:
        lock = HERE.parents[1] / "data" / "hivemind" / ".laptop_sync.lock"
        due = (not laptop_sync.STAMP.exists()
               or time.time() - float(laptop_sync.STAMP.read_text() or 0) >= laptop_sync.EVERY_S - 1500)
        if due and not (lock.exists() and time.time() - lock.stat().st_mtime < 45 * 60):
            lock.write_text(str(time.time()))
            try:
                t = time.time()
                r = laptop_sync.run(force=True)   # its own "not due" gate would undo the early window above
                log(f"laptop_sync {r} in {time.time() - t:.0f}s")
            finally:
                lock.unlink(missing_ok=True)
    except Exception as e:
        log(f"laptop_sync failed: {e} {traceback.format_exc()[-300:]}")


if __name__ == "__main__":
    main()
