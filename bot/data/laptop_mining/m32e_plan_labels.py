"""Project X part 6 - the owner's OWN recent plans as labels on the fade map (DESCRIPTIVE, n=7, no
verdict). For each owner plan within candle coverage that reached +0.5R: what did the fade-lean
(fade_tells: clean volume-surge + velocity at +0.5R) call it (FADE_PRONE=quiet=trim vs RUN_LIKELY=
impulsive=give room), and what actually happened (ran to +1.5R, or faded back to <=0)? Shows him his
trades on the map; closes the Project X label loop. source=claude_idea plans flagged (not owner-labels).
"""
import io, json, os, sqlite3
import numpy as np
import fade_tells
from m30_run import first_true, HOLD
from m13_build import daily, atr_pit

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "crunch", "panels.sqlite")


def main():
    rows = [json.loads(l) for l in io.open(os.path.join(HERE, "server_exports", "owner_plans.jsonl"), encoding="utf-8") if l.strip()]
    plans = [r for r in rows if r.get("kind") == "plan" and r.get("entry") and r.get("stop") and r.get("coin")]
    c = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    have = set(x[0] for x in c.execute("SELECT DISTINCT coin FROM candles_1h"))
    out = []
    for p in plans:
        coin = p["coin"]
        if coin not in have:
            continue
        a = np.asarray(c.execute("SELECT t,h,l,c,v FROM candles_1h WHERE coin=? ORDER BY t", (coin,)).fetchall(), float)
        ts = p.get("ts", 0) * 1000.0
        i = int(np.searchsorted(a[:, 0], ts))
        if i < 73 or i + 48 >= len(a):
            continue
        e = float(p["entry"]); s = float(p["stop"])
        side = 1 if str(p.get("side", "")).upper().startswith("L") else -1
        Rfrac = abs(e - s) / e
        fwdH = a[i + 1:i + 49, 1]; fwdL = a[i + 1:i + 49, 2]; fwdC = a[i + 1:i + 49, 3]; fwdV = a[i + 1:i + 49, 4]
        # favorable excursion in R per bar (from entry e)
        fav = ((fwdH - e) / e if side > 0 else (e - fwdL) / e) / Rfrac
        mark = ((fwdC - e) / e if side > 0 else (e - fwdC) / e) / Rfrac
        b05 = int(np.argmax(fav >= 0.5)) if (fav >= 0.5).any() else None
        if b05 is None:
            continue
        # outcome: reached +1.5R (RUN) before fading to <=0 (FADE)?
        after = np.arange(len(fav)) > b05
        hit15 = np.argmax((fav >= 1.5) & after) if ((fav >= 1.5) & after).any() else 10**6
        fade0 = np.argmax((mark <= 0) & after) if ((mark <= 0) & after).any() else 10**6
        outcome = "RAN" if hit15 < fade0 else "FADED" if fade0 < 10**6 else "neither"
        # fade_tells inputs: velocity (bars to +0.5R), clean surge = V[b05-1]/mean(V 72 before entry)
        vel = b05 + 1
        vbase = a[max(i - 72, 0):i, 4].mean()
        vprev = fwdV[b05 - 1] if b05 >= 1 else a[i, 4]
        lean, note = fade_tells.classify(vel, vprev, vbase)
        src = "claude_idea" if str(p.get("setup", "")).lower().startswith("ai") or p.get("source") == "ai" else "owner"
        out.append({"coin": coin, "src": src, "setup": p.get("setup", "")[:14], "peakR": round(float(fav.max()), 2),
                    "vel_bars": int(vel), "fade_lean": lean, "outcome": outcome})
    c.close()
    print("Project X part 6 - owner plans on the fade map (DESCRIPTIVE, n=%d, NO verdict):\n" % len(out))
    print("  %-8s %-11s %-14s peakR vel lean         outcome   lean-vs-outcome" % ("coin", "src", "setup"))
    agree = 0
    for r in out:
        # 'agreed' = RUN_LIKELY & RAN, or FADE_PRONE & FADED
        ok = (r["fade_lean"] == "RUN_LIKELY" and r["outcome"] == "RAN") or (r["fade_lean"] == "FADE_PRONE" and r["outcome"] == "FADED")
        agree += int(ok)
        print("  %-8s %-11s %-14s %4.2f  %3d %-12s %-9s %s"
              % (r["coin"], r["src"], r["setup"], r["peakR"], r["vel_bars"], r["fade_lean"], r["outcome"], "lean-right" if ok else ""))
    print("\n  lean matched outcome on %d/%d (DESCRIPTIVE ONLY, n=%d - far too few to mean anything)." % (agree, len(out), len(out)))
    io.open(os.path.join(HERE, "m32e_result.json"), "w", encoding="utf-8").write(json.dumps({"n": len(out), "agree": agree, "rows": out}, indent=1, default=str))
    print("  wrote m32e_result.json")


if __name__ == "__main__":
    main()
