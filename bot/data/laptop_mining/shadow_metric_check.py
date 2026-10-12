"""Which outcome metric is unbiased for the stop_shadow design? Simulation only, no data read.

The server flagged it: `PREREG_STOP_SHADOW_2026-10-12` measures arms in "R of the bot's original
risk", and E2 proved that metric is mechanically biased when the treatment IS the stop distance.
The shadow logger's arms are exactly that -- the bot's own stop versus 1.0/1.5/2.0x exp_move.

The prereg is at n=3 with no arm difference read, so this is the only honest moment to change it.

METHOD. Simulate the design under NO EDGE (driftless GBM) at the real parameters taken from the
three live records (bot stop 2.5-3.6% of entry, exp_move ~5.1-5.4%, so the wider arms are genuinely
wider) and measure what each candidate metric reports when there is nothing to find:

    R_orig   P&L / |entry - bot_stop|      <- what the prereg currently says
    abs_ret  P&L / entry                   <- what E2b used, which was ALSO non-zero there
    R_own    P&L / |entry - that arm's own stop|

A metric is usable here only if its no-edge mean sits at ~0. Anything else manufactures a result.
"""
import math
import random
import statistics

HOURLY_VOL = 0.012          # ~1.2%/h, the order of magnitude for NEAR/HYPE-class perps
CAP_H = 96
N_WORLDS = 4000


def path(px, sig, hours, rng):
    out, p = [], px
    for _ in range(hours):
        o = p
        p = o * math.exp(rng.gauss(0.0, sig))
        w1 = o * math.exp(rng.gauss(0.0, sig * 0.7))
        w2 = p * math.exp(rng.gauss(0.0, sig * 0.7))
        out.append((max(o, p, w1, w2), min(o, p, w1, w2), p))
    return out


def run(stop_pct, tp_pct, side, bars):
    """First touch wins; stop wins a tie. Returns P&L as a fraction of entry."""
    stop = 1.0 - side * stop_pct / 100.0
    tp = 1.0 + side * tp_pct / 100.0
    last = 1.0
    for hi, lo, cl in bars:
        hit_s = (lo <= stop) if side > 0 else (hi >= stop)
        hit_t = (hi >= tp) if side > 0 else (lo <= tp)
        if hit_s:
            return side * (stop - 1.0)
        if hit_t:
            return side * (tp - 1.0)
        last = cl
    return side * (last - 1.0)


def main():
    BOT, TP = 3.0, 8.0                      # bot stop 3% of entry, target 8% -- from the live rows
    ARMS = [("bot", BOT), ("1.0x", 5.2), ("1.5x", 7.8), ("2.0x", 10.4)]
    rng = random.Random(20261012)
    acc = {name: {"R_orig": [], "abs": [], "R_own": []} for name, _ in ARMS}

    for _ in range(N_WORLDS):
        side = 1 if rng.random() < 0.5 else -1
        bars = path(1.0, HOURLY_VOL, CAP_H, rng)
        for name, sp in ARMS:
            pnl = run(sp, TP, side, bars)                  # fraction of entry
            acc[name]["abs"].append(pnl * 100.0)           # % of entry
            acc[name]["R_orig"].append(pnl / (BOT / 100.0))
            acc[name]["R_own"].append(pnl / (sp / 100.0))

    print("NO-EDGE SIMULATION of the stop_shadow design -- %d driftless worlds" % N_WORLDS)
    print("bot stop %.1f%% of entry, target %.1f%%, arms at %s\n"
          % (BOT, TP, ", ".join("%s=%.1f%%" % (n, s) for n, s in ARMS)))
    print("%-8s %14s %14s %14s" % ("arm", "R_orig", "abs_ret %", "R_own"))
    for name, _ in ARMS:
        a = acc[name]
        print("%-8s %14.4f %14.4f %14.4f"
              % (name, statistics.fmean(a["R_orig"]), statistics.fmean(a["abs"]),
                 statistics.fmean(a["R_own"])))

    print("\nTHE CONTRAST THAT MATTERS -- each wider arm MINUS the bot arm, under no edge:")
    print("%-8s %14s %14s %14s" % ("arm-bot", "R_orig", "abs_ret %", "R_own"))
    verdict = {}
    for name, _ in ARMS[1:]:
        row = []
        for metric in ("R_orig", "abs", "R_own"):
            d = [x - y for x, y in zip(acc[name][metric], acc["bot"][metric])]
            m = statistics.fmean(d)
            se = statistics.pstdev(d) / (len(d) ** 0.5)
            row.append((m, se))
            verdict.setdefault(metric, []).append(abs(m / (se or 1e-12)))
        print("%-8s %10.4f%s %10.4f%s %10.4f%s"
              % (name,
                 row[0][0], "*" if abs(row[0][0] / (row[0][1] or 1e-12)) > 2 else " ",
                 row[1][0], "*" if abs(row[1][0] / (row[1][1] or 1e-12)) > 2 else " ",
                 row[2][0], "*" if abs(row[2][0] / (row[2][1] or 1e-12)) > 2 else " "))
    print("  * = the no-edge difference is itself significant, i.e. the metric invents a result\n")

    for metric, zs in verdict.items():
        worst = max(zs)
        name = {"R_orig": "R of the bot's original risk (what the prereg says)",
                "abs": "absolute return, % of entry",
                "R_own": "R of each arm's OWN risk"}[metric]
        print("  %-52s worst |z| under no edge: %5.1f  -> %s"
              % (name, worst, "BIASED" if worst > 2 else "usable"))


if __name__ == "__main__":
    main()
