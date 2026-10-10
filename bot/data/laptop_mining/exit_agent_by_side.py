"""Side-cut of the exit-agent replay.

My EXIT_AGENT_REPLAY.md verdict -- "+0.037R, a wash, the agent is not the leak" --
was POOLED ACROSS SIDES. LONG_SIDE.md then found the long side loses $795 while the
short side makes $605, with the exit agent closing 40.2% of longs for -$494 (the
single largest line item in the ledger) against 33.0% of shorts for -$227.

A pooled neutral result is exactly what a +X on one side and a -X on the other looks
like. This re-runs the SAME verified replay, split by side, with power stated first.

Reuses exit_agent_replay.replay/wk/decisions so the arithmetic (including the three
bug fixes: original-stop R, non-hardcoded stop booking, within-window placebo) is
identical to the pooled run.
"""
import collections
import numpy as np
import exit_agent_replay as E

D = E.decisions()
for s in {d["sym"] for d in D}:
    c = E.load1h(s)
    if c:
        E.CAND[s] = c

print("EXIT AGENT, SPLIT BY SIDE  (edge = acted - held, in R. positive = closing helped)")
print("  same replay, same tie rule (stop-first, which flatters the agent), same fixes")
print()
sides = collections.Counter((d.get("side") or "?").upper() for d in D)
print("  decision mix by side:", dict(sides))
print()
hdr = ("%-10s %-7s %6s %9s %9s %9s %9s %7s %9s  %s"
       % ("action", "side", "n", "acted R", "held R", "edge", "wk edge", "wk t", "MDE(80%)", "verdict"))
print(hdr)
print("-" * len(hdr))

rows = {}
for act in ("close", "hold", "partial", "tighten_sl"):
    for side in ("LONG", "SHORT"):
        sub = [d for d in D if d["action"] == act
               and (d.get("side") or "").upper() == side]
        for hours in (48,):
            res = [(E.replay(d, hours, True), d["ts"]) for d in sub]
            res = [(r, t) for (r, t) in res if r]
            if len(res) < 25:
                print("  %-10s %-7s %6d   -- too few to report (floor 25) --"
                      % (act, side, len(res)))
                continue
            pairs = [r[0] - r[1] for (r, t) in res]
            ts = [t for (r, t) in res]
            a = np.mean([r[0] for (r, t) in res])
            h = np.mean([r[1] for (r, t) in res])
            m, t, nw = E.wk(pairs, ts)
            sd = np.std(pairs, ddof=1)
            mde = 2.8 * sd / np.sqrt(len(pairs))     # 80% power, two-sided 0.05
            v = ("agent ADDS value" if (np.isfinite(t) and t > 1.96)
                 else "agent DESTROYS value" if (np.isfinite(t) and t < -1.96)
                 else "no measurable effect")
            if abs(np.mean(pairs)) < mde:
                v += " (below MDE)"
            print("  %-10s %-7s %6d %+9.3f %+9.3f %+9.3f %+9.3f %7.2f %9.3f  %s"
                  % (act, side, len(pairs), a, h, np.mean(pairs), m, t, mde, v))
            rows[(act, side)] = (np.mean(pairs), m, t, mde, len(pairs))

print()
print("THE QUESTION THAT MATTERS: is the LONG close edge different from the SHORT one?")
for act in ("close",):
    if (act, "LONG") in rows and (act, "SHORT") in rows:
        subL = [d for d in D if d["action"] == act and (d.get("side") or "").upper() == "LONG"]
        subS = [d for d in D if d["action"] == act and (d.get("side") or "").upper() == "SHORT"]
        pL = [r[0] - r[1] for r in (E.replay(d, 48, True) for d in subL) if r]
        pS = [r[0] - r[1] for r in (E.replay(d, 48, True) for d in subS) if r]
        d_ = np.mean(pL) - np.mean(pS)
        se = np.sqrt(np.var(pL, ddof=1) / len(pL) + np.var(pS, ddof=1) / len(pS))
        print("  LONG edge %+.3fR (n=%d)   SHORT edge %+.3fR (n=%d)"
              % (np.mean(pL), len(pL), np.mean(pS), len(pS)))
        print("  difference %+.3fR, naive t = %.2f -> %s"
              % (d_, d_ / se, "THEY DIFFER" if abs(d_ / se) > 1.96
                 else "not distinguishable -- the pooled wash was NOT hiding a side split"))
        print("  (naive t here; the week-clustered t per side is in the table above)")
