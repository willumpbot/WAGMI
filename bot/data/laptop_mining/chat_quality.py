"""PREREG_CHAT_QUALITY_2026-10-12 — do the chats differ in call quality? Runs ONCE.

Gate satisfied: the megacall fetch COMPLETED (live 1924, dead 182 of 2,106) and
call_outcomes.jsonl was regenerated to 2,442 rows before this ran.

SEALED DESIGN, implemented exactly:
  comparison   dtn_hitters vs syndicate, restricted to days BOTH were active
  outcome      hit2x_7d primary; ret_7d continuous secondary
  statistic    difference in outcome rate, EQUAL-WEIGHTED over shared call-days,
               printed beside the pooled difference. The equal-weighted mean GOVERNS.
  CI           day-block bootstrap over shared days, 4,000 reps
  dead         dead rows are outcome FALSE, never dropped; per-chat death rate reported
               separately because it may be the whole story
  secondary    dtn vs dtn_hitters on their shared days, own day count, NOT combined
  EXCLUDED     dtn x syndicate -- zero shared days, permanently (dtn ends 2026-06-21,
               syndicate begins 2026-08-24; they never coexist, so any comparison would be
               a market-regime difference wearing a quality label)

DECISION RULE (all required for SUPPORT): eq-weighted shared-day difference with CI excluding
zero at |z| > 2.24 (Bonferroni over 2 outcomes); pooled and eq-weighted agree in sign; sign
stable across first and second half of shared days; effect exceeds the simulated MDE; survives
the placebo. AGAINST = significantly reversed. UNDERPOWERED = everything else.

PRE-COMMITMENT: if the simulated MDE exceeds 15 percentage points the verdict is UNDERPOWERED
regardless of the point estimate. Recorded expectation: UNDERPOWERED.

PLACEBO: chat-label shuffle WITHIN shared days, 2,000 draws; measured size must be ~5%. If it is
not, the result is "unmeasurable", not "nothing". Shuffling within day preserves day structure so
it tests chat identity rather than which days each chat happened to be active on.

Report order is the prereg's: placebo size -> MDE -> shared-day count -> only then the effect.
"""
import collections
import datetime
import io
import json
import math
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "call_outcomes.jsonl")
BOOT = 4000
PLACEBO = 2000
Z_THRESH = 2.24          # Bonferroni over the 2 outcomes, two-sided 0.05/2
MDE_FLOOR_PP = 15.0      # pre-committed: above this, UNDERPOWERED regardless
rng = np.random.default_rng(20261013)


def day_of(ts):
    """UTC date of a call.

    VOID RUN 1 (disclosed in the result doc): this divided by 1000, but call_outcomes.jsonl
    stores call_ts in SECONDS (10 digits). Every call collapsed into ~20 days of January 1970,
    so BOTH pairs reported "shared days: 1" and the run could compute nothing. The prereg's own
    recorded count -- 14 shared days at 384 rows -- is what caught it: more data cannot reduce
    shared days. No effect was computed, so nothing about the relationship was revealed.

    Now unit-detected AND range-checked, so a future units error halts instead of silently
    producing one shared day.
    """
    ts = int(ts)
    secs = ts / 1000.0 if ts > 1e12 else float(ts)
    d = datetime.datetime.fromtimestamp(secs, datetime.UTC)
    if not (2024 <= d.year <= 2030):
        raise SystemExit("HALT: call_ts %r -> %s, outside the plausible range. Units are wrong."
                         % (ts, d.date()))
    return d.strftime("%Y-%m-%d")


def load():
    rows = []
    for line in io.open(SRC, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        chat, ts = r.get("chat"), r.get("call_ts")
        if not chat or not ts:
            continue
        dead = bool(r.get("dead"))
        h = r.get("hit2x_7d")
        # dead -> outcome FALSE, never dropped. Unresolved and not dead -> excluded.
        if h is None:
            if not dead:
                continue
            h = False
        ret = r.get("ret_7d")
        if ret is None:
            ret = -100.0 if dead else None
        rows.append({"chat": chat, "day": day_of(ts), "hit": 1.0 if h else 0.0,
                     "ret": ret, "dead": dead})
    return rows


def arms(rows, a, b):
    """Per shared day: (rate_a, rate_b, n_a, n_b) for days where BOTH chats called."""
    byday = collections.defaultdict(lambda: {a: [], b: []})
    for r in rows:
        if r["chat"] in (a, b):
            byday[r["day"]][r["chat"]].append(r)
    shared = {d: v for d, v in byday.items() if v[a] and v[b]}
    return dict(sorted(shared.items()))


def eq_and_pooled(shared, a, b, field="hit"):
    """Equal-weighted shared-day mean difference (GOVERNS) and the pooled difference."""
    diffs, na, nb, sa, sb = [], 0, 0, 0.0, 0.0
    for d, v in shared.items():
        va = [x[field] for x in v[a] if x[field] is not None]
        vb = [x[field] for x in v[b] if x[field] is not None]
        if not va or not vb:
            continue
        diffs.append(float(np.mean(va)) - float(np.mean(vb)))
        na += len(va); nb += len(vb)
        sa += float(np.sum(va)); sb += float(np.sum(vb))
    if not diffs:
        return None
    eq = float(np.mean(diffs))
    pooled = (sa / na) - (sb / nb) if na and nb else float("nan")
    return {"eq": eq, "pooled": pooled, "days": len(diffs), "n_a": na, "n_b": nb,
            "diffs": diffs}


def bootstrap_ci(diffs, reps=BOOT):
    """Day-block bootstrap: resample whole shared days."""
    d = np.asarray(diffs, float)
    if len(d) < 2:
        return None
    idx = rng.integers(0, len(d), size=(reps, len(d)))
    means = d[idx].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    se = float(means.std(ddof=1))
    return {"lo": float(lo), "hi": float(hi), "se": se,
            "z": (float(np.mean(d)) / se) if se > 0 else float("nan")}


def placebo_size(shared, a, b, field="hit", draws=PLACEBO):
    """Chat-label shuffle WITHIN shared days. Returns the measured false-positive rate.

    This placebo CAN fail: if the size is not ~5% the test is mis-sized and the result is
    "unmeasurable", not "nothing".
    """
    pool = []
    for d, v in shared.items():
        vals = [x[field] for x in v[a] + v[b] if x[field] is not None]
        pool.append((len(v[a]), vals))
    hits = 0
    for _ in range(draws):
        diffs = []
        for ka, vals in pool:
            if len(vals) < 2 or ka == 0 or ka >= len(vals):
                continue
            p = rng.permutation(vals)
            diffs.append(float(np.mean(p[:ka])) - float(np.mean(p[ka:])))
        if len(diffs) < 2:
            continue
        b2 = bootstrap_ci(diffs, reps=400)
        if b2 and (b2["lo"] > 0 or b2["hi"] < 0):
            hits += 1
    return hits / draws


def mde_sim(shared, a, b, field="hit", draws=600):
    """Smallest injected difference (in rate points) detected >=80% of the time."""
    pool = []
    for d, v in shared.items():
        va = [x[field] for x in v[a] if x[field] is not None]
        vb = [x[field] for x in v[b] if x[field] is not None]
        if va and vb:
            pool.append((va, vb))
    if len(pool) < 2:
        return None
    for delta in (0.02, 0.04, 0.06, 0.08, 0.10, 0.125, 0.15, 0.20, 0.25, 0.30, 0.40):
        det = 0
        for _ in range(draws):
            diffs = []
            for va, vb in pool:
                sa = rng.choice(va, size=len(va), replace=True).mean() + delta
                sb = rng.choice(vb, size=len(vb), replace=True).mean()
                diffs.append(float(sa - sb))
            bb = bootstrap_ci(diffs, reps=300)
            if bb and bb["lo"] > 0:
                det += 1
        if det / draws >= 0.80:
            return delta
    return None


def half_split(shared, a, b, field="hit"):
    days = list(shared.keys())
    mid = len(days) // 2
    out = []
    for half in (days[:mid], days[mid:]):
        sub = {d: shared[d] for d in half}
        r = eq_and_pooled(sub, a, b, field)
        out.append(None if r is None else r["eq"])
    return out


def run_pair(rows, a, b, label, primary=True):
    shared = arms(rows, a, b)
    print("\n" + "=" * 92)
    print("%s  --  %s vs %s" % (label, a, b))
    print("=" * 92)
    if len(shared) < 2:
        print("  shared days: %d -- CANNOT TEST" % len(shared))
        return {"pair": label, "shared_days": len(shared), "verdict": "CANNOT TEST"}
    res = {"pair": label, "shared_days": len(shared)}

    # 1. PLACEBO FIRST -- it can fail, and a failure makes everything below unmeasurable
    size = placebo_size(shared, a, b)
    ok = 0.02 <= size <= 0.09
    print("  1. PLACEBO (chat-label shuffle within shared days, %d draws): size %.3f  [%s]"
          % (PLACEBO, size, "ok" if ok else "MIS-SIZED -> unmeasurable"))
    res["placebo_size"] = round(size, 4); res["placebo_ok"] = bool(ok)

    # 2. MDE
    mde = mde_sim(shared, a, b)
    mde_pp = None if mde is None else 100 * mde
    print("  2. MDE (simulated, 80%% power): %s  [pre-committed floor %.0f pp]"
          % ("none up to 40 pp" if mde_pp is None else "%.1f pp" % mde_pp, MDE_FLOOR_PP))
    res["mde_pp"] = mde_pp

    # 3. counts
    r = eq_and_pooled(shared, a, b, "hit")
    print("  3. shared days %d | calls %s=%d %s=%d" % (r["days"], a, r["n_a"], b, r["n_b"]))
    res.update({"n_a": r["n_a"], "n_b": r["n_b"]})

    # 4. only now, the effect
    bb = bootstrap_ci(r["diffs"])
    halves = half_split(shared, a, b, "hit")
    print("  4. hit2x_7d  EQ-WEIGHTED %+.1f pp (GOVERNS) | pooled %+.1f pp | CI [%+.1f, %+.1f] z %.2f"
          % (100 * r["eq"], 100 * r["pooled"], 100 * bb["lo"], 100 * bb["hi"], bb["z"]))
    print("     halves: %s | %s  (sign-stable: %s)"
          % ("n/a" if halves[0] is None else "%+.1f pp" % (100 * halves[0]),
             "n/a" if halves[1] is None else "%+.1f pp" % (100 * halves[1]),
             "yes" if (halves[0] is not None and halves[1] is not None
                       and halves[0] * halves[1] > 0) else "NO"))
    res.update({"eq_pp": round(100 * r["eq"], 2), "pooled_pp": round(100 * r["pooled"], 2),
                "ci_pp": [round(100 * bb["lo"], 2), round(100 * bb["hi"], 2)],
                "z": round(bb["z"], 2),
                "halves_pp": [None if h is None else round(100 * h, 2) for h in halves]})

    # secondary continuous outcome
    r2 = eq_and_pooled(shared, a, b, "ret")
    if r2:
        b2 = bootstrap_ci(r2["diffs"])
        print("  5. ret_7d (secondary) EQ-WEIGHTED %+.1f%% | pooled %+.1f%% | CI [%+.1f, %+.1f] z %.2f"
              % (100 * r2["eq"] if abs(r2["eq"]) < 10 else r2["eq"],
                 100 * r2["pooled"] if abs(r2["pooled"]) < 10 else r2["pooled"],
                 b2["lo"], b2["hi"], b2["z"]))
        res["ret_eq"] = round(r2["eq"], 3); res["ret_z"] = round(b2["z"], 2)

    # verdict, per the sealed decision rule
    sign_ok = (halves[0] is not None and halves[1] is not None and halves[0] * halves[1] > 0)
    agree = (r["eq"] * r["pooled"]) > 0
    excl = bb["lo"] > 0 or bb["hi"] < 0
    zbig = abs(bb["z"]) > Z_THRESH
    over_mde = (mde_pp is not None) and (abs(100 * r["eq"]) >= mde_pp)
    if not ok:
        v = "UNMEASURABLE (placebo mis-sized at %.3f)" % size
    elif mde_pp is None or mde_pp > MDE_FLOOR_PP:
        v = ("UNDERPOWERED (MDE %s exceeds the %.0f pp pre-committed floor)"
             % ("none up to 40 pp" if mde_pp is None else "%.1f pp" % mde_pp, MDE_FLOOR_PP))
    elif excl and zbig and agree and sign_ok and over_mde and r["eq"] > 0:
        v = "SUPPORT"
    elif excl and zbig and r["eq"] < 0:
        v = "AGAINST (significantly reversed)"
    else:
        v = "UNDERPOWERED"
    print("  ->  VERDICT: %s" % v)
    res["verdict"] = v
    return res


def main():
    rows = load()
    print("PREREG_CHAT_QUALITY_2026-10-12 -- ONE run. Gate: megacall fetch COMPLETE.")
    print("source: call_outcomes.jsonl, %d usable rows" % len(rows))
    byc = collections.Counter(r["chat"] for r in rows)
    print("by chat: %s" % dict(byc))
    print("\ndeath rate per chat (reported separately -- it may be the whole story):")
    for c in sorted(byc):
        sub = [r for r in rows if r["chat"] == c]
        dd = sum(1 for r in sub if r["dead"])
        hr = float(np.mean([r["hit"] for r in sub]))
        print("  %-12s n %4d | dead %4d = %5.1f%% | hit2x_7d %5.1f%%"
              % (c, len(sub), dd, 100 * dd / len(sub), 100 * hr))
    out = {"prereg": "PREREG_CHAT_QUALITY_2026-10-12", "rows": len(rows),
           "by_chat": dict(byc), "results": []}
    out["results"].append(run_pair(rows, "dtn_hitters", "syndicate", "PRIMARY"))
    out["results"].append(run_pair(rows, "dtn", "dtn_hitters", "SECONDARY (own day count)"))
    print("\n" + "=" * 92)
    print("EXCLUDED BY THE PREREG: dtn x syndicate -- zero shared days, permanently.")
    print("dtn ends 2026-06-21, syndicate begins 2026-08-24. They never coexist, so any")
    print("comparison would be a market-regime difference wearing a quality label.")
    print("=" * 92)
    io.open(os.path.join(HERE, "chat_quality.json"), "w", encoding="utf-8").write(
        json.dumps(out, indent=1))
    print("\nwrote chat_quality.json")
    print("RECORDED EXPECTATION was UNDERPOWERED. The equal-weighted shared-day mean governs.")


if __name__ == "__main__":
    main()
