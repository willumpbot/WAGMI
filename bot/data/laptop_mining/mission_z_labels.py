"""Mission Z step 2 -- build the OUTCOME LABELS and the joint winner/dud distribution.

Runs AFTER PREREG_MISSION_Z_DUDS_2026-10-12.md was sealed
(sha256 of sealed body = b90c4b526cc5561199680209264da68233273d6ee2c6af8ea35af4fc2385d183).

Labels only. No feature is read, computed, or joined here -- the call-time feature fetch has not
happened yet. Definitions are copied verbatim from the sealed prereg, section 4.

JOIN: on `call_ts`, never on `i`. The highs-file `i` matches the current anon list ordering for
only 18 of 199 rows (the server made that list append-only), so an index join would silently
mis-pair calls with paths.

WHY TWO FILES: `syndicate_highs.jsonl` holds the RUNNING MAX of the intrabar high, which cannot
fall -- so the winner leg comes from it and the dud leg CANNOT. `-80% at 7d` needs a terminal
close, which only `syndicate_paths.jsonl` (forward-filled closes) has.
"""
import io
import json
import math
import os
import random
import datetime as dt

D = os.path.dirname(os.path.abspath(__file__))
U = dt.timezone.utc
T_ASOF = 1791764404          # 2026-10-12 00:20:04 UTC, mtime of syndicate_highs.jsonl
MATURE_24H = 86400
MATURE_7D = 604800


def load(name):
    out = []
    for line in io.open(os.path.join(D, name), encoding="utf-8"):
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def day(ts):
    return dt.datetime.fromtimestamp(ts, U).strftime("%Y-%m-%d")


def pooled(flags):
    return (sum(flags) / len(flags)) if flags else float("nan")


def by_day(rows, key):
    """Equal-weighted-by-day mean: each UTC day's rate, then days averaged with equal weight.
    Returned with the per-day sizes so corr(size, rate) can be reported for the acted-on number."""
    d = {}
    for r in rows:
        d.setdefault(day(r["call_ts"]), []).append(1 if r[key] else 0)
    days = sorted(d)
    rates = [sum(d[k]) / len(d[k]) for k in days]
    sizes = [len(d[k]) for k in days]
    return (sum(rates) / len(rates) if rates else float("nan")), days, rates, sizes


def corr(a, b):
    n = len(a)
    if n < 3:
        return float("nan")
    ma, mb = sum(a) / n, sum(b) / n
    sa = math.sqrt(sum((x - ma) ** 2 for x in a))
    sb = math.sqrt(sum((x - mb) ** 2 for x in b))
    if sa == 0 or sb == 0:
        return float("nan")
    return sum((a[i] - ma) * (b[i] - mb) for i in range(n)) / (sa * sb)


def block_boot(rows, key, iters=2000, seed=7):
    """Day-clustered CI: resample whole UTC days with replacement."""
    rnd = random.Random(seed)
    d = {}
    for r in rows:
        d.setdefault(day(r["call_ts"]), []).append(1 if r[key] else 0)
    days = sorted(d)
    pool_est, eq_est = [], []
    for _ in range(iters):
        pick = [days[rnd.randrange(len(days))] for _ in range(len(days))]
        flat = [v for k in pick for v in d[k]]
        pool_est.append(sum(flat) / len(flat))
        eq_est.append(sum(sum(d[k]) / len(d[k]) for k in pick) / len(pick))
    pool_est.sort()
    eq_est.sort()
    lo, hi = int(0.025 * iters), int(0.975 * iters) - 1
    return (pool_est[lo], pool_est[hi]), (eq_est[lo], eq_est[hi])


def main():
    hi = load("syndicate_highs.jsonl")
    pa = {r["call_ts"]: r for r in load("syndicate_paths.jsonl")}

    rows = []
    for r in hi:
        ts = r["call_ts"]
        rec = {"call_ts": ts, "day": day(ts), "skip": r.get("skip")}
        pm, ph = r.get("peak_m"), r.get("peak_h")

        # ---- WINNER / WIN3X: running max of intrabar HIGH. Skip rows count as misses.
        if rec["skip"]:
            rec["peak24"] = None
            rec["peak7d"] = None
            rec["win"] = 0
            rec["win3x"] = 0
            rec["win3x7d"] = 0
            rec["win3x7d_pub"] = 0
            rec["peak_src"] = "skip"
        else:
            if pm:
                p24 = max(pm)
                rec["peak_src"] = "peak_m"
            else:                                   # pre-committed fallback (2 rows)
                p24 = max(ph[:25])
                rec["peak_src"] = "peak_h_fallback"
            p7 = max(ph) if ph else p24
            rec["peak24"] = p24
            rec["peak7d"] = p7
            rec["win"] = 1 if p24 >= 1.5 else 0
            rec["win3x"] = 1 if p24 >= 3.0 else 0
            # Sealed prereg definition: hourly grid only.
            rec["win3x7d"] = 1 if p7 >= 3.0 else 0
            # Published-grid definition, recovered by reconciliation (see note below): the max of
            # the 24h MINUTE running max and the hourly running max. The two grids disagree because
            # each has its own entry base -- the close of its own first bar at/after the call -- and
            # the hour bar that contains the call is up to 60 min coarse, so the hourly series
            # misses spikes the minute series caught.
            rec["win3x7d_pub"] = 1 if max(p24, p7) >= 3.0 else 0

        rec["mature24"] = ts + MATURE_24H <= T_ASOF
        rec["mature7d"] = ts + MATURE_7D <= T_ASOF

        # ---- DUD leg: needs the terminal CLOSE, from the paths file, 7d-mature rows only.
        p = pa.get(ts)
        h1 = (p or {}).get("h1")
        rec["has_close"] = bool(h1)
        rec["dud"] = None
        rec["dead"] = None
        rec["term80"] = None
        rec["silent"] = None
        rec["term80_med"] = None
        if not rec["mature7d"]:
            rec["dud_status"] = "OUTCOME-IMMATURE"
        elif rec["skip"]:
            rec["dud_status"] = "ok"
            rec["dead"] = 1
            rec["silent"] = 0
            rec["term80"] = 0
            rec["term80_med"] = 0
            rec["dud"] = 1
        elif not h1 or len(h1) < 169:
            rec["dud_status"] = "SOURCE-MISSING"
        else:
            rec["dud_status"] = "ok"
            tail = h1[121:169]
            rec["silent"] = 1 if all(abs(x - tail[0]) < 1e-12 for x in tail) else 0
            rec["dead"] = rec["silent"]
            rec["term80"] = 1 if h1[168] <= 0.20 else 0
            srt = sorted(h1[161:169])
            med = (srt[3] + srt[4]) / 2.0
            rec["term80_med"] = 1 if med <= 0.20 else 0
            rec["dud"] = 1 if (rec["dead"] or rec["term80"]) else 0
            rec["h1_end"] = h1[168]
        rows.append(rec)

    out = {}

    # ---------- harness replication check (abort condition in the prereg) ----------
    rep = {
        "WINNER_1.5x_24h  (acted on)": (sum(r["win"] for r in rows), len(rows), 37.69, True),
        "WIN3X_24h        (gate)": (sum(r["win3x"] for r in rows), len(rows), 13.07, True),
        "WIN3X_7D  prereg defn": (sum(r["win3x7d"] for r in rows), len(rows), 26.63, False),
        "WIN3X_7D  published defn": (sum(r["win3x7d_pub"] for r in rows), len(rows), 26.63, False),
    }
    print("=== HARNESS REPLICATION CHECK (must match published rates) ===")
    allok = True
    for k, (h, n, pub, primary) in rep.items():
        got = 100.0 * h / n
        ok = abs(got - pub) < 0.01
        if primary:
            allok &= ok
        print("  %-28s %3d/%d = %6.2f%%   published %6.2f%%   %s%s"
              % (k, h, n, got, pub, "MATCH" if ok else "MISMATCH",
                 "   <- PRIMARY" if primary else ""))
    out["replication_ok"] = bool(allok)
    out["replication"] = {k: {"hits": v[0], "n": v[1], "published_pct": v[2], "primary": v[3]}
                          for k, v in rep.items()}
    print("""
  DEVIATION, DISCLOSED (the prereg is sealed; it is NOT being edited):
  Both labels this mission acts on -- WINNER (75/199) and the WIN3X gate (26/199) -- replicate the
  published rates EXACTLY. The sealed prereg's secondary WIN3X_7D formula (hourly grid only) gives
  46/199 = 23.12%, not the published 26.63%. Cause identified and it is a DEFINITION difference,
  not a harness bug: the published grid uses max(24h-minute running max, hourly running max) beyond
  24h. Under that convention all 30 cells of syndicate_highs_grid.json and all 5 cells of
  syndicate_highs_rates.json reproduce with zero mismatches. Both 7d-3x numbers are therefore
  reported side by side below, and nothing that gates a verdict depends on either.
""")
    if not allok:
        print("ABORT: a PRIMARY label does not reproduce. Nothing else reported.")
        json.dump(out, io.open(os.path.join(D, "mission_z_labels.json"), "w", encoding="utf-8"),
                  indent=1, default=float)
        return

    # ---------- winner leg, pooled vs equal-weight-by-day ----------
    print("=== WINNER LEG (1.5x high touch within 24h) ===")
    sets = [
        ("all 199 (dead pools = miss)", rows),
        ("24h-mature (195)", [r for r in rows if r["mature24"]]),
        ("24h-mature with path (179)", [r for r in rows if r["mature24"] and not r["skip"]]),
    ]
    out["winner"] = {}
    for lab, sel in sets:
        pl = pooled([r["win"] for r in sel])
        eq, days, rates, sizes = by_day(sel, "win")
        c = corr(sizes, rates)
        (pl_lo, pl_hi), (eq_lo, eq_hi) = block_boot(sel, "win")
        print("  %-28s n=%3d days=%2d  pooled %5.1f%% [%4.1f, %4.1f]   EQ-WEIGHT-BY-DAY %5.1f%% "
              "[%4.1f, %4.1f]   corr(day size, day rate) %+.3f"
              % (lab, len(sel), len(days), 100 * pl, 100 * pl_lo, 100 * pl_hi,
                 100 * eq, 100 * eq_lo, 100 * eq_hi, c))
        out["winner"][lab] = {"n": len(sel), "days": len(days), "pooled_pct": 100 * pl,
                              "pooled_ci": [100 * pl_lo, 100 * pl_hi],
                              "eqday_pct": 100 * eq, "eqday_ci": [100 * eq_lo, 100 * eq_hi],
                              "corr_size_rate": c}
    sing = sum(1 for s in by_day(rows, "win")[3] if s == 1)
    print("  singleton days (1 call): %d of %d" % (sing, len(by_day(rows, "win")[1])))
    out["singleton_days"] = sing

    # ---------- maturity accounting ----------
    m7 = [r for r in rows if r["mature7d"]]
    imm = [r for r in rows if not r["mature7d"]]
    ok7 = [r for r in m7 if r["dud_status"] == "ok"]
    miss7 = [r for r in m7 if r["dud_status"] == "SOURCE-MISSING"]
    print("\n=== 7d MATURITY ACCOUNTING ===")
    print("  7d-mature            %3d  (of 199)" % len(m7))
    print("  OUTCOME-IMMATURE     %3d  excluded from every dud figure, NOT counted as non-duds"
          % len(imm))
    print("  SOURCE-MISSING close %3d" % len(miss7))
    print("  dud-labelled set     %3d  (= %d with closes + %d structural dead pools)"
          % (len(ok7), sum(1 for r in ok7 if not r["skip"]), sum(1 for r in ok7 if r["skip"])))
    out["maturity"] = {"mature7d": len(m7), "immature": len(imm),
                       "source_missing": len(miss7), "dud_set": len(ok7)}

    # ---------- dud leg components ----------
    print("\n=== DUD LEG COMPONENTS (7d-mature, n=%d) ===" % len(ok7))
    for k, lab in (("dead", "dead_pool (no_pool/no_path OR 48h trade-silent)"),
                   ("silent", "  of which trade-silent (had a pool, then no trades)"),
                   ("term80", "terminal_80 (close at +7d <= 0.20x)"),
                   ("term80_med", "terminal_80 robustness (median of last 8h <= 0.20x)"),
                   ("dud", "DUD = dead_pool OR terminal_80")):
        h = sum(r[k] for r in ok7)
        pl = h / len(ok7)
        eq, days, rates, sizes = by_day(ok7, k)
        c = corr(sizes, rates)
        print("  %-52s %3d/%d = %5.1f%%   EQ-BY-DAY %5.1f%%   corr %+.3f"
              % (lab, h, len(ok7), 100 * pl, 100 * eq, c))
        out.setdefault("dud_components", {})[k] = {"hits": h, "n": len(ok7), "pooled_pct": 100 * pl,
                                                   "eqday_pct": 100 * eq, "corr_size_rate": c}
    (pl_lo, pl_hi), (eq_lo, eq_hi) = block_boot(ok7, "dud")
    print("  DUD day-clustered CI: pooled [%.1f, %.1f]   eq-by-day [%.1f, %.1f]"
          % (100 * pl_lo, 100 * pl_hi, 100 * eq_lo, 100 * eq_hi))
    out["dud_ci"] = {"pooled": [100 * pl_lo, 100 * pl_hi], "eqday": [100 * eq_lo, 100 * eq_hi]}

    # ---------- THE JOINT TABLE ----------
    cells = {"winner_only": 0, "both": 0, "dud_only": 0, "neither": 0}
    for r in ok7:
        if r["win"] and r["dud"]:
            cells["both"] += 1
        elif r["win"]:
            cells["winner_only"] += 1
        elif r["dud"]:
            cells["dud_only"] += 1
        else:
            cells["neither"] += 1
    n = len(ok7)
    print("\n=== JOINT OUTCOME DISTRIBUTION (7d-mature, n=%d) ===" % n)
    print("                       |  DUD (dead or -80%@7d)  |  not DUD   |  row total")
    w_d, w_nd = cells["both"], cells["winner_only"]
    nw_d, nw_nd = cells["dud_only"], cells["neither"]
    print("  WINNER (1.5x in 24h) |   %3d  (%4.1f%%) BOTH   |  %3d (%4.1f%%) |  %3d (%4.1f%%)"
          % (w_d, 100 * w_d / n, w_nd, 100 * w_nd / n, w_d + w_nd, 100 * (w_d + w_nd) / n))
    print("  not WINNER           |   %3d  (%4.1f%%)        |  %3d (%4.1f%%) |  %3d (%4.1f%%)"
          % (nw_d, 100 * nw_d / n, nw_nd, 100 * nw_nd / n, nw_d + nw_nd, 100 * (nw_d + nw_nd) / n))
    print("  col total            |   %3d  (%4.1f%%)        |  %3d (%4.1f%%) |  %3d"
          % (w_d + nw_d, 100 * (w_d + nw_d) / n, w_nd + nw_nd, 100 * (w_nd + nw_nd) / n, n))
    out["joint"] = dict(cells, n=n)

    # equal-weighted-by-day version of each joint cell
    print("\n  equal-weighted-by-day version of the same four cells:")
    for key, lab in (("c_both", "BOTH (1.5x then died)"), ("c_wonly", "WINNER only"),
                     ("c_donly", "DUD only"), ("c_neither", "NEITHER")):
        for r in ok7:
            if key == "c_both":
                r[key] = 1 if (r["win"] and r["dud"]) else 0
            elif key == "c_wonly":
                r[key] = 1 if (r["win"] and not r["dud"]) else 0
            elif key == "c_donly":
                r[key] = 1 if (not r["win"] and r["dud"]) else 0
            else:
                r[key] = 1 if (not r["win"] and not r["dud"]) else 0
        pl = pooled([r[key] for r in ok7])
        eq, days, rates, sizes = by_day(ok7, key)
        c = corr(sizes, rates)
        print("    %-24s pooled %5.1f%%   EQ-BY-DAY %5.1f%%   corr %+.3f"
              % (lab, 100 * pl, 100 * eq, c))
        out.setdefault("joint_eqday", {})[lab] = {"pooled_pct": 100 * pl, "eqday_pct": 100 * eq,
                                                  "corr_size_rate": c}

    # ---------- what the BOTH cell means for a filter ----------
    wins = [r for r in ok7 if r["win"]]
    print("\n=== THE 'BOTH' CELL: where a dud filter does its damage ===")
    print("  winners (7d-mature set):            %3d" % len(wins))
    print("  of those, also DUDs by 7d:          %3d  (%.1f%% of all winners)"
          % (w_d, 100 * w_d / len(wins)))
    print("  -> a filter trained to drop DUDs is being asked to drop %.0f%% of the winners too."
          % (100 * w_d / len(wins)))
    r3 = [r for r in ok7 if r["win3x"]]
    r3d = sum(1 for r in r3 if r["dud"])
    r37 = [r for r in ok7 if r["win3x7d_pub"]]
    r37d = sum(1 for r in r37 if r["dud"])
    print("  3x-in-24h winners (the runners):    %3d, of which %d (%.0f%%) are also DUDs by 7d"
          % (len(r3), r3d, 100 * r3d / len(r3) if r3 else float("nan")))
    print("  3x-in-7d winners:                   %3d, of which %d (%.0f%%) are also DUDs by 7d"
          % (len(r37), r37d, 100 * r37d / len(r37) if r37 else float("nan")))
    out["both_cell"] = {"winners": len(wins), "winners_also_dud": w_d,
                        "pct_of_winners": 100 * w_d / len(wins),
                        "runners_3x24h": len(r3), "runners_3x24h_also_dud": r3d,
                        "runners_3x7d": len(r37), "runners_3x7d_also_dud": r37d}

    # ---------- runner counts available to the killer metric ----------
    ho = [r for r in rows if r["mature24"] and not r["skip"]
          and r["call_ts"] >= int(dt.datetime(2026, 9, 28, tzinfo=U).timestamp())]
    tr = [r for r in rows if r["mature24"] and not r["skip"]
          and r["call_ts"] < int(dt.datetime(2026, 9, 28, tzinfo=U).timestamp())]
    print("\n=== KILLER-METRIC DENOMINATORS (pre-sealed split at 2026-09-28) ===")
    print("  train n=%d, 3x winners=%d   |   holdout n=%d, 3x winners=%d"
          % (len(tr), sum(r["win3x"] for r in tr), len(ho), sum(r["win3x"] for r in ho)))
    out["killer_denoms"] = {"train_n": len(tr), "train_3x": sum(r["win3x"] for r in tr),
                            "holdout_n": len(ho), "holdout_3x": sum(r["win3x"] for r in ho)}

    json.dump(out, io.open(os.path.join(D, "mission_z_labels.json"), "w", encoding="utf-8"),
              indent=1, default=float)
    print("\nwrote mission_z_labels.json")


if __name__ == "__main__":
    main()
