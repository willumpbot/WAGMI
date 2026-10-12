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


def _uptime_ping():
    """Append one row per cycle: is the bot alive (heartbeat age) and is its AI healthy. Laptop 10-11 needed an
    uptime record to tell downtime from quiet markets; bot logs rotate weekly so they can't answer it."""
    import json, time
    hb = HERE.parents[1] / "data" / "heartbeat.json"
    # The bot rewrites heartbeat.json every scan; reading mid-write gives partial JSON with no "epoch" (that read as
    # "age = 56 years" and sent two false 'bot down' alerts on 10-11). Retry, and fall back to the ISO timestamp.
    h, age = {}, None
    for _try in range(4):
        try:
            h = json.loads(hb.read_text(encoding="utf-8"))
            ep = h.get("epoch")
            if not ep and h.get("last_alive"):
                from datetime import datetime as _dt
                ep = _dt.fromisoformat(str(h["last_alive"]).replace("Z", "+00:00")).timestamp()
            if ep:
                age = time.time() - float(ep)
                break
        except Exception:
            pass
        time.sleep(1.5)
    alive = age is not None and age < 600
    llm_ok = alive and not bool(h.get("llm_first_degraded"))      # laptop 10-11: Oct 5-7 the bot was UP but its AI was down
    row = {"t": int(time.time()), "hb_age_s": None if age is None else round(age), "pid": h.get("pid"),
           "scans": h.get("scan_count"), "alive": alive, "llm_ok": llm_ok, "can_trade": alive and llm_ok}
    hm = HERE.parents[1] / "data" / "hivemind"
    with open(hm / "uptime.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + chr(10))
    # Alert the owner on his phone (Telegram Saved Messages via tg_listener's outbox) when the bot stops being able
    # to trade, every 6h while it lasts, and once when it recovers. In September the watchdog detected a 3-day crash
    # and nobody saw it.
    st_p = hm / "uptime_alert_state.json"
    try:
        st = json.loads(st_p.read_text(encoding="utf-8"))
    except Exception:
        st = {"bad_since": None, "last_alert": 0}
    now, msg = time.time(), None
    if not row["can_trade"]:
        why = "the bot process is DOWN (no heartbeat for %s min)" % (round(age / 60) if age else "?") if not alive             else "the bot is running but its AI is DEGRADED (likely the Claude login expired: run /login on the PC)"
        if st.get("bad_since") is None:
            st["bad_since"] = now
        # only alert once it has been bad on two checks >= 20 min apart (one bad read is not an outage)
        if now - st["bad_since"] >= 1200 and now - st.get("last_alert", 0) > 6 * 3600:
            msg, st["last_alert"] = "Bot can't trade: " + why + ".", now
    elif st.get("bad_since") is not None:
        if st.get("last_alert"):   # only announce recovery if we actually told him it was down
            msg = "Bot is back to normal after %.1f h." % ((now - st["bad_since"]) / 3600)
        st = {"bad_since": None, "last_alert": 0}
    if msg:
        with open(hm / "tg" / "outbox.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": int(now), "text": msg}) + chr(10))
    st_p.write_text(json.dumps(st), encoding="utf-8")


def main():
    import assemble, desk, chief   # assemble fixes sys.path order (copilot before tools)
    sys.path.remove(str(assemble.BOT / "tools" / "copilot"))
    sys.path.insert(0, str(assemble.BOT / "tools" / "copilot"))
    try:
        _uptime_ping()
    except Exception as e:
        log(f"uptime ping failed: {e}")
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
        for mod, fn in (("scanner", "run"), ("plans", "resolve"), ("tg_track", "run"), ("call_snapshot", "run"), ("candle_archive", "run"), ("depth_all", "run"), ("entry_mom", "run"), ("stop_shadow", "run"), ("ai_plans", "run"), ("history", "build"), ("board_feed", "run"), ("laptop_sync", "run")):
            try:
                res = getattr(__import__(mod), fn)()
                if mod == "scanner":
                    import scan_grader
                    scan_grader.log(res)
                    scan_grader.resolve()
                    import expmove_grade
                    expmove_grade.log(res)
                    expmove_grade.resolve()
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
