"""PREREG_CALLER_FORM_2026-10-12 (sha 4c9a5f26 = sealed 60e17310 + Amendments 1 and 2). Runs ONCE.

Gate: megacall fetch COMPLETE (~06:40), server step 2 re-run on the 2,442-row corpus, and the opaque
caller_cluster key shipped. All three deferrals are closed; none was a choice of mine and no
form x outcome quantity was seen before this ran.

SEALED DESIGN + AMENDMENT 2:
  predictor    form_hit2x_7d, continuous, on form_n_known_7d >= 3
  population   HUMAN-POSTED ONLY for the primary (bot rows carry null form, so the bot subset is
               empty by construction -- reported, not hidden)
  outcome      hit2x_7d from call_outcomes.jsonl, joined on (ca, call_ts). Same horizon as the
               form, so like predicts like.
  statistic    outcome-rate difference, ABOVE-median vs BELOW-median form
  clustering   AMENDMENT 2: the CALLER is PRIMARY (caller-block bootstrap, 4,000 reps, resampling
               whole clusters). The call-day figure is reported BESIDE it. On disagreement the
               CALLER-clustered CI GOVERNS, because the hypothesis is caller-level and the
               concentration makes day-clustering anti-conservative.
  dead         dead rows are outcome FALSE, never dropped
  threshold    |z| > 2.24 (Bonferroni over the 2 horizons)
  MDE          by simulation. UNDERPOWERED if it exceeds 15 pp REGARDLESS of the point estimate.
  robustness   sign-stable across halves split at the median call-day; leave-top-caller-out and
               leave-top-3-out (Amendment 2 C4 -- with the mass this concentrated, this is the
               decisive check, not a footnote)
  effective n  distinct clusters AND Kish effective n must be reported. Quoting 1,528 as the
               sample size is PROHIBITED by Amendment 2.

PLACEBOS, and one is unavailable:
  1 form-shuffle within call-day cells, 2,000 draws -- size must be ~5% or the result is
    "unmeasurable", not "nothing".
  2 TIME-REVERSAL -- recompute each call's form from SUBSEQUENT outcomes. NOT RUNNABLE HERE: that
    needs a server-side identity join I do not have and did not request in time. Declared as a
    deviation under section 9. PRE-COMMITTED CONSEQUENCE, stated before the numbers: if the result
    comes out POSITIVE AND POWERED, this script HALTS without claiming SUPPORT and the reversed-form
    join is requested, because SUPPORT requires all three placebos. If the result is UNDERPOWERED the
    missing placebo cannot change the verdict.
  3 chat-only -- replace form with the caller's chat. If chat alone reproduces the effect, this is a
    chat-quality finding mislabelled as caller skill.

Recorded expectation (section 8 + Amendment 2 E): UNDERPOWERED with a small positive, held MORE
strongly after seeing Kish effective n ~7.5 -- and the leave-one-out check will probably BE the result.

Report order: placebo size -> MDE -> counts and effective n -> only then any effect.
"""
import collections
import datetime
import io
import json
import math
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FORM = os.path.join(HERE, "server_exports", "call_caller_form_anon.NEW.jsonl")
OUT = os.path.join(HERE, "call_outcomes.jsonl")
MIN_KNOWN = 3
BOOT = 4000
PLACEBO = 2000
Z_THRESH = 2.24
MDE_FLOOR_PP = 15.0
rng = np.random.default_rng(20261013)


def day_of(ts):
    ts = int(ts)
    secs = ts / 1000.0 if ts > 1e12 else float(ts)
    d = datetime.datetime.fromtimestamp(secs, datetime.UTC)
    if not (2024 <= d.year <= 2030):
        raise SystemExit("HALT: call_ts %r -> %s. Units wrong." % (ts, d.date()))
    return d.strftime("%Y-%m-%d")


def load():
    out = {}
    for line in io.open(OUT, encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        out[(r.get("ca"), r.get("call_ts"))] = r
    rows = []
    for line in io.open(FORM, encoding="utf-8"):
        if not line.strip():
            continue
        f = json.loads(line)
        if (f.get("form_n_known_7d") or 0) < MIN_KNOWN:
            continue
        o = out.get((f.get("ca"), f.get("call_ts")))
        if o is None:
            continue
        form = f.get("form_hit2x_7d")
        cl = f.get("caller_cluster")
        if form is None or cl is None:
            continue
        h = o.get("hit2x_7d")
        dead = bool(o.get("dead"))
        if h is None:
            if not dead:
                continue
            h = False
        rows.append({"form": float(form), "hit": 1.0 if h else 0.0,
                     "cluster": int(cl), "day": day_of(f["call_ts"]),
                     "chat": f.get("chat"), "bot": bool(f.get("caller_is_bot")),
                     "n_prior": f.get("form_n_prior_calls") or 0})
    return rows


def split_diff(rows, field="form"):
    """Above-median minus below-median outcome rate. Pooled."""
    med = float(np.median([r[field] for r in rows]))
    hi = [r["hit"] for r in rows if r[field] > med]
    lo = [r["hit"] for r in rows if r[field] <= med]
    if not hi or not lo:
        return None
    return float(np.mean(hi)) - float(np.mean(lo)), med, len(hi), len(lo)


def eq_mean_by(rows, key, field="form"):
    """Equal-weighted mean of the within-group above/below difference."""
    g = collections.defaultdict(list)
    for r in rows:
        g[r[key]].append(r)
    diffs = []
    for k, sub in g.items():
        d = split_diff(sub, field)
        if d is not None:
            diffs.append(d[0])
    return (float(np.mean(diffs)), len(diffs), diffs) if diffs else (None, 0, [])


def block_boot(rows, key, field="form", reps=BOOT):
    """Resample whole blocks (clusters or days), recompute the pooled above/below difference."""
    g = collections.defaultdict(list)
    for r in rows:
        g[r[key]].append(r)
    keys = list(g)
    if len(keys) < 2:
        return None
    est = []
    for _ in range(reps):
        pick = rng.integers(0, len(keys), size=len(keys))
        samp = [x for i in pick for x in g[keys[i]]]
        d = split_diff(samp, field)
        if d is not None:
            est.append(d[0])
    if len(est) < 50:
        return None
    est = np.asarray(est)
    lo, hi = np.percentile(est, [2.5, 97.5])
    se = float(est.std(ddof=1))
    base = split_diff(rows, field)[0]
    return {"lo": float(lo), "hi": float(hi), "se": se, "blocks": len(keys),
            "z": (base / se) if se > 0 else float("nan")}


def kish(counts):
    n = sum(counts)
    return (n * n) / sum(c * c for c in counts) if counts else 0.0


def placebo_shuffle(rows, draws=PLACEBO):
    """Form-shuffle WITHIN call-day cells. Measured size must be ~5%; it CAN fail."""
    byday = collections.defaultdict(list)
    for r in rows:
        byday[r["day"]].append(r)
    hits = 0
    for _ in range(draws):
        perm = []
        for d, sub in byday.items():
            forms = rng.permutation([x["form"] for x in sub])
            perm.extend({"form": float(f), "hit": x["hit"], "cluster": x["cluster"],
                         "day": d} for f, x in zip(forms, sub))
        b = block_boot(perm, "cluster", reps=200)
        if b and (b["lo"] > 0 or b["hi"] < 0):
            hits += 1
    return hits / draws


def mde_sim(rows, draws=400):
    """Smallest injected lift in the above-median arm detected >=80% of the time."""
    for delta in (0.02, 0.05, 0.08, 0.10, 0.125, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50):
        det = 0
        for _ in range(draws):
            med = float(np.median([r["form"] for r in rows]))
            samp = []
            for r in rows:
                h = r["hit"]
                if r["form"] > med and rng.random() < delta:
                    h = 1.0
                samp.append({"form": r["form"], "hit": h, "cluster": r["cluster"], "day": r["day"]})
            b = block_boot(samp, "cluster", reps=150)
            if b and b["lo"] > 0:
                det += 1
        if det / draws >= 0.80:
            return delta
    return None


def main():
    rows = load()
    human = [r for r in rows if not r["bot"]]
    bots = [r for r in rows if r["bot"]]
    cl = collections.Counter(r["cluster"] for r in human)
    print("PREREG_CALLER_FORM 4c9a5f26 -- ONE run. Gate: fetch complete + step 2 + caller_cluster.")
    print("joined rows at form_n_known_7d >= %d: %d (human %d, bot %d)"
          % (MIN_KNOWN, len(rows), len(human), len(bots)))
    print("\n--- 1. PLACEBO (form-shuffle within call-day cells, %d draws) ---" % PLACEBO)
    size = placebo_shuffle(human)
    ok = 0.02 <= size <= 0.09
    print("  size %.3f  [%s]" % (size, "ok" if ok else "MIS-SIZED -> unmeasurable"))

    print("\n--- 2. MDE (simulated, caller-clustered, 80%% power) ---")
    mde = mde_sim(human)
    mde_pp = None if mde is None else 100 * mde
    print("  %s   [pre-committed floor %.0f pp]"
          % ("none up to 50 pp" if mde_pp is None else "%.1f pp" % mde_pp, MDE_FLOOR_PP))

    print("\n--- 3. COUNTS AND EFFECTIVE SAMPLE (Amendment 2: never quote the raw row count) ---")
    k = kish(list(cl.values()))
    print("  raw eligible human rows : %d   <-- PROHIBITED as 'the sample size'" % len(human))
    print("  distinct caller clusters: %d" % len(cl))
    print("  Kish effective n        : %.1f" % k)
    print("  largest cluster         : %d rows (%.0f%% of eligible)"
          % (cl.most_common(1)[0][1], 100 * cl.most_common(1)[0][1] / len(human)))
    print("  top 3 clusters          : %s" % [n for _, n in cl.most_common(3)])
    print("  call-days               : %d" % len({r["day"] for r in human}))

    print("\n--- 4. THE EFFECT (above-median minus below-median form, on hit2x_7d) ---")
    pooled, med, nhi, nlo = split_diff(human)
    eq_day, nday, _ = eq_mean_by(human, "day")
    eq_cl, ncl, _ = eq_mean_by(human, "cluster")
    bc = block_boot(human, "cluster")
    bd = block_boot(human, "day")
    print("  median form %.3f | above %d rows / below %d rows" % (med, nhi, nlo))
    print("  pooled                     %+.1f pp" % (100 * pooled))
    print("  eq-weighted over days      %+.1f pp  (%d days)" % (100 * eq_day, nday))
    print("  eq-weighted over callers   %+.1f pp  (%d clusters)" % (100 * eq_cl, ncl))
    if bc:
        print("  CALLER-clustered CI (GOVERNS) [%+.1f, %+.1f] z %.2f  (%d blocks)"
              % (100 * bc["lo"], 100 * bc["hi"], bc["z"], bc["blocks"]))
    if bd:
        print("  day-clustered CI (secondary)  [%+.1f, %+.1f] z %.2f  (%d blocks)"
              % (100 * bd["lo"], 100 * bd["hi"], bd["z"], bd["blocks"]))

    print("\n--- 5. LEAVE-TOP-CALLER-OUT (Amendment 2 C4 -- the decisive check) ---")
    loo = {}
    for drop in (1, 3):
        bad = {c for c, _ in cl.most_common(drop)}
        sub = [r for r in human if r["cluster"] not in bad]
        d = split_diff(sub)
        b = block_boot(sub, "cluster")
        loo[drop] = None if d is None else (100 * d[0], b["z"] if b else None, len(sub))
        print("  drop top %d: %s  (%d rows left)"
              % (drop,
                 "n/a" if d is None else "%+.1f pp, z %s" % (
                     100 * d[0], "n/a" if not b else "%.2f" % b["z"]),
                 len(sub)))

    print("\n--- 6. SIGN STABILITY (halves split at the median call-day) ---")
    days = sorted({r["day"] for r in human})
    mid = days[len(days) // 2]
    h1 = [r for r in human if r["day"] < mid]
    h2 = [r for r in human if r["day"] >= mid]
    s = []
    for nm, sub in (("first", h1), ("second", h2)):
        d = split_diff(sub)
        s.append(None if d is None else d[0])
        print("  %-6s %s" % (nm, "n/a" if d is None else "%+.1f pp (%d rows)" % (100 * d[0], len(sub))))
    stable = (s[0] is not None and s[1] is not None and s[0] * s[1] > 0)
    print("  sign-stable: %s" % ("yes" if stable else "NO"))

    print("\n--- 7. CHAT-ONLY PLACEBO (is this a chat effect wearing a caller label?) ---")
    chat_rate = {c: float(np.mean([r["hit"] for r in human if r["chat"] == c]))
                 for c in {r["chat"] for r in human}}
    proxy = [{"form": chat_rate[r["chat"]], "hit": r["hit"], "cluster": r["cluster"],
              "day": r["day"]} for r in human]
    cp = split_diff(proxy)
    cb = block_boot(proxy, "cluster")
    print("  chat-rate proxy: %s  z %s"
          % ("n/a" if cp is None else "%+.1f pp" % (100 * cp[0]),
             "n/a" if not cb else "%.2f" % cb["z"]))

    print("\n--- 8. VERDICT ---")
    excl = bool(bc and (bc["lo"] > 0 or bc["hi"] < 0))
    zbig = bool(bc and abs(bc["z"]) > Z_THRESH)
    powered = (mde_pp is not None) and (abs(100 * pooled) >= mde_pp)
    if not ok:
        v = "UNMEASURABLE (placebo mis-sized at %.3f)" % size
    elif mde_pp is None or mde_pp > MDE_FLOOR_PP:
        v = ("UNDERPOWERED -- MDE %s exceeds the %.0f pp pre-committed floor. Kish effective n %.1f."
             % ("none up to 50 pp" if mde_pp is None else "%.1f pp" % mde_pp, MDE_FLOOR_PP, k))
    elif excl and zbig and powered and pooled > 0 and stable:
        v = ("POSITIVE AND POWERED -- but SUPPORT is NOT claimed: the time-reversal placebo could not "
             "be run here (needs a server-side reversed-form join). HALTING per the pre-committed rule.")
    elif excl and zbig and pooled < 0:
        v = "AGAINST (significantly negative)"
    else:
        v = "UNDERPOWERED"
    print("  %s" % v)
    res = {"prereg": "PREREG_CALLER_FORM 4c9a5f26", "rows_human": len(human),
           "clusters": len(cl), "kish_n": round(k, 2), "call_days": len({r["day"] for r in human}),
           "placebo_size": round(size, 4), "placebo_ok": bool(ok), "mde_pp": mde_pp,
           "pooled_pp": round(100 * pooled, 2), "eq_day_pp": round(100 * eq_day, 2),
           "eq_caller_pp": round(100 * eq_cl, 2),
           "caller_ci_pp": None if not bc else [round(100 * bc["lo"], 2), round(100 * bc["hi"], 2)],
           "caller_z": None if not bc else round(bc["z"], 2),
           "day_ci_pp": None if not bd else [round(100 * bd["lo"], 2), round(100 * bd["hi"], 2)],
           "day_z": None if not bd else round(bd["z"], 2),
           "leave_out": {str(k2): v2 for k2, v2 in loo.items()},
           "sign_stable": bool(stable), "chat_proxy_pp": None if cp is None else round(100 * cp[0], 2),
           "bot_rows": len(bots), "verdict": v,
           "deviation": "time-reversal placebo NOT run: requires a server-side reversed-form join"}
    io.open(os.path.join(HERE, "caller_form.json"), "w", encoding="utf-8").write(
        json.dumps(res, indent=1))
    print("\nwrote caller_form.json")
    print("RECORDED EXPECTATION: UNDERPOWERED with a small positive; the leave-one-out check would")
    print("probably BE the result. Amendment 2 prohibits quoting %d as the sample size." % len(human))


if __name__ == "__main__":
    main()
