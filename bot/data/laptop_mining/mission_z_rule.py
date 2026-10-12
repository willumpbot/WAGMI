"""Mission Z step 3 -- THE ONE RULE. Fit on TRAIN, score ONCE on holdout.

Follows PREREG_MISSION_Z_DUDS_2026-10-12.md (sealed body sha256
b90c4b526cc5561199680209264da68233273d6ee2c6af8ea35af4fc2385d183, verified).

Sections referenced below are the prereg's. Nothing here deviates silently; every deviation is
printed in the DEVIATIONS block and is forced by what the fetcher could actually retrieve.
"""
import io
import json
import math
import os
import random
import datetime as dt

D = os.path.dirname(os.path.abspath(__file__))
U = dt.timezone.utc
T_ASOF = 1791764404
MATURE_24H = 86400
MATURE_7D = 604800
SPLIT_TS = int(dt.datetime(2026, 9, 28, 0, 0, 0, tzinfo=U).timestamp())   # prereg s3
DECILES = [10, 20, 30, 40, 50, 60, 70, 80, 90]
MIN_KEEP_FRAC = 0.40          # prereg s7
MIN_TRAIN_3X_RECALL = 0.85    # prereg s7
GATE_RECALL = 0.85            # prereg s8
GATE_WILSON_LO = 0.65         # prereg s8
MDE_ICC0 = 31.3               # prereg s5, holdout n=72
MDE_ICC05 = 34.7
PLACEBO_ITERS = 500
BOOT = 2000


def load(name):
    out = []
    for line in io.open(os.path.join(D, name), encoding="utf-8"):
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def day(ts):
    return dt.datetime.fromtimestamp(ts, U).strftime("%Y-%m-%d")


def pct(x):
    return 100.0 * x


def pooled(flags):
    return (sum(flags) / len(flags)) if flags else float("nan")


def eqday(rows, key):
    """Equal-weighted-by-day: each UTC day's rate, then days averaged equally (prereg s9)."""
    d = {}
    for r in rows:
        d.setdefault(r["day"], []).append(1 if r[key] else 0)
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


def corr_ci_t(a, b):
    """Fisher-z CI and t for corr(day size, day rate) -- prereg s9 wants it with uncertainty."""
    r = corr(a, b)
    n = len(a)
    if not (n > 3) or r != r or abs(r) >= 1:
        return r, float("nan"), float("nan"), float("nan")
    z = 0.5 * math.log((1 + r) / (1 - r))
    se = 1.0 / math.sqrt(n - 3)
    lo, hi = math.tanh(z - 1.96 * se), math.tanh(z + 1.96 * se)
    t = r * math.sqrt((n - 2) / (1 - r * r))
    return r, lo, hi, t


def wilson(k, n, z=1.96):
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return p, max(0.0, c - h), min(1.0, c + h)


def block_boot_lift(rows, keepfn, iters=BOOT, seed=11):
    """Day-clustered CI for the LIFT (keep rate minus all rate), pooled and equal-weight-by-day.
    Resamples whole UTC days with replacement (prereg s9.4)."""
    rnd = random.Random(seed)
    d = {}
    for r in rows:
        d.setdefault(r["day"], []).append(r)
    days = sorted(d)
    pl, eq = [], []
    for _ in range(iters):
        pick = [days[rnd.randrange(len(days))] for _ in range(len(days))]
        flat = [r for k in pick for r in d[k]]
        kept = [r for r in flat if keepfn(r)]
        if not kept:
            continue
        pl.append(pooled([r["win"] for r in kept]) - pooled([r["win"] for r in flat]))
        # equal-weight-by-day on the resampled day blocks
        kr, ar = [], []
        for k in pick:
            blk = d[k]
            kb = [r for r in blk if keepfn(r)]
            ar.append(pooled([r["win"] for r in blk]))
            if kb:
                kr.append(pooled([r["win"] for r in kb]))
        if kr:
            eq.append(sum(kr) / len(kr) - sum(ar) / len(ar))
    def q(v):
        if not v:
            return float("nan"), float("nan")
        v = sorted(v)
        return v[int(0.025 * len(v))], v[int(0.975 * len(v)) - 1]
    return q(pl), q(eq)


# ---------------------------------------------------------------- labels (prereg s4)
def build_labels():
    hi = load("syndicate_highs.jsonl")
    pa = {r["call_ts"]: r for r in load("syndicate_paths.jsonl")}
    rows = []
    for r in hi:
        ts = r["call_ts"]
        rec = {"call_ts": ts, "day": day(ts), "skip": r.get("skip")}
        pm, ph = r.get("peak_m"), r.get("peak_h")
        if rec["skip"]:
            rec.update(win=0, win3x=0, win3x7d=0, win3x7d_pub=0, peak24=None, peak7d=None)
        else:
            p24 = max(pm) if pm else max(ph[:25])
            p7 = max(ph) if ph else p24
            rec["peak24"], rec["peak7d"] = p24, p7
            rec["win"] = 1 if p24 >= 1.5 else 0
            rec["win3x"] = 1 if p24 >= 3.0 else 0
            rec["win3x7d"] = 1 if p7 >= 3.0 else 0
            rec["win3x7d_pub"] = 1 if max(p24, p7) >= 3.0 else 0
        rec["mature24"] = ts + MATURE_24H <= T_ASOF
        rec["mature7d"] = ts + MATURE_7D <= T_ASOF
        p = pa.get(ts)
        h1 = (p or {}).get("h1")
        rec["dud"] = None
        if not rec["mature7d"]:
            rec["dud_status"] = "OUTCOME-IMMATURE"
        elif rec["skip"]:
            rec["dud_status"] = "ok"
            rec["dud"] = 1
        elif not h1 or len(h1) < 169:
            rec["dud_status"] = "SOURCE-MISSING"
        else:
            rec["dud_status"] = "ok"
            tail = h1[121:169]
            silent = 1 if all(abs(x - tail[0]) < 1e-12 for x in tail) else 0
            rec["dud"] = 1 if (silent or h1[168] <= 0.20) else 0
        rows.append(rec)
    return rows


# ---------------------------------------------------------------- features (prereg s6a)
# The sealed list is 14. Only 11 are realizable from what the fetcher actually retrieved;
# F7/F9/F11 were never fetched and are SOURCE-MISSING, not zeros. See DEVIATIONS.
FEATS = [
    ("F1  pool_age_min",        "age_proxy_s",           60.0),   # /60 -> minutes
    ("F2  n_premin_bars_60",    "n_min_bars_1h_pre",     1.0),
    ("F3  pre_ret_60m",         "ret_1h_pre",            1.0),
    ("F4* pre_ret_5m",          "ret_5m_pre",            1.0),    # sealed said 15m; only 5m exists
    ("F5  pre_ret_6h",          "ret_6h_pre",            1.0),
    ("F6  pre_rv_60m",          "rv_1h_pre",             1.0),
    ("F8  pre_vol_usd_60m",     "vol_1h_pre",            1.0),
    ("F10 prox_to_pre_high",    "dist_from_6h_high_pre", 1.0),    # = prox - 1, monotone identical
    ("F12 pre_hist_bars_total", "n_hour_bars_7d_pre",    1.0),
    ("F13 us_session",          "_us_session",           1.0),    # clock only
    ("F14 mins_since_prev",     "_mins_since_prev",      1.0),    # clock only
]
MISSING_FEATS = ["F7  pre_maxdd_60m", "F9  vol_accel", "F11 pre_green_frac_60m"]
BINARY = {"_us_session"}


def attach_features(rows):
    pc = {r["call_ts"]: r for r in load("syndicate_precall.jsonl")}
    all_ts = sorted(r["call_ts"] for r in rows)
    prev = {}
    for i, ts in enumerate(all_ts):
        prev[ts] = None if i == 0 else (ts - all_ts[i - 1]) / 60.0
    for r in rows:
        ts = r["call_ts"]
        src = pc.get(ts)
        r["has_precall_row"] = src is not None
        r["precall_status"] = (src or {}).get("status", "no_pool")
        f = {}
        h = dt.datetime.fromtimestamp(ts, U).hour
        f["_us_session"] = 1 if 13 <= h < 21 else 0
        f["_mins_since_prev"] = prev[ts]
        for _, col, div in FEATS:
            if col.startswith("_"):
                continue
            v = (src or {}).get(col)
            f[col] = None if v is None else v / div
        r["f"] = f
    return rows


# ---------------------------------------------------------------- the one rule form (prereg s7)
def candidates(train):
    """Thresholds come from the TRAIN distribution only. Returns the realised candidate list."""
    out = []
    for label, col, _ in FEATS:
        vals = sorted(v for v in (r["f"][col] for r in train) if v is not None)
        if len(vals) < 10:
            continue
        if col in BINARY:
            ths = [1.0]
        else:
            raw = []
            for p in DECILES:
                k = (len(vals) - 1) * p / 100.0
                lo, hi = int(math.floor(k)), int(math.ceil(k))
                raw.append(vals[lo] if lo == hi else vals[lo] + (k - lo) * (vals[hi] - vals[lo]))
            ths = sorted(set(raw))               # grids collapse on ties -> realised < budget
        for t in ths:
            for s in (+1, -1):
                out.append((label, col, s, t))
    return out


def apply_rule(r, col, s, t):
    v = r["f"][col]
    if v is None:
        return None                               # not evaluable -> its own bucket, never a zero
    return 1 if s * v >= s * t else 0


def score(rows, col, s, t):
    ev = [r for r in rows if r["f"][col] is not None]
    if not ev:
        return None
    kept = [r for r in ev if apply_rule(r, col, s, t)]
    if not kept:
        return None
    base = pooled([r["win"] for r in ev])
    kr = pooled([r["win"] for r in kept])
    n3 = sum(r["win3x"] for r in ev)
    k3 = sum(r["win3x"] for r in kept)
    return {
        "n_ev": len(ev), "n_keep": len(kept), "keep_frac": len(kept) / len(ev),
        "base": base, "keep_rate": kr, "lift": kr - base,
        "n3": n3, "k3": k3, "recall3": (k3 / n3) if n3 else float("nan"),
    }


def fit(train, cands):
    """prereg s7: maximise lift subject to 3x-recall >= .85 and keep_frac >= .40.
    Ties -> larger keep fraction."""
    best, feasible = None, 0
    for (label, col, s, t) in cands:
        sc = score(train, col, s, t)
        if sc is None:
            continue
        if sc["keep_frac"] < MIN_KEEP_FRAC:
            continue
        if not (sc["recall3"] >= MIN_TRAIN_3X_RECALL):
            continue
        feasible += 1
        key = (sc["lift"], sc["keep_frac"])
        if best is None or key > (best[1]["lift"], best[1]["keep_frac"]):
            best = ((label, col, s, t), sc)
    return best, feasible


# ---------------------------------------------------------------- placebo (prereg s10)
def placebo(analysis, cands_builder, seed=1234):
    """Day-block permutation of the FEATURE VECTORS. Within-day feature correlation survives;
    every feature-outcome link is destroyed. Full pipeline re-run, one holdout score each."""
    rnd = random.Random(seed)
    rows = sorted(analysis, key=lambda r: r["call_ts"])
    blocks, order = {}, []
    for r in rows:
        if r["day"] not in blocks:
            blocks[r["day"]] = []
            order.append(r["day"])
        blocks[r["day"]].append(r["f"])
    lifts, infeasible = [], 0
    for _ in range(PLACEBO_ITERS):
        perm = order[:]
        rnd.shuffle(perm)
        fseq = [f for d in perm for f in blocks[d]]
        shadow = []
        for i, r in enumerate(rows):
            s = dict(r)
            s["f"] = fseq[i]
            shadow.append(s)
        tr = [r for r in shadow if r["call_ts"] < SPLIT_TS]
        ho = [r for r in shadow if r["call_ts"] >= SPLIT_TS]
        best, _ = fit(tr, cands_builder(tr))
        if best is None:
            infeasible += 1
            lifts.append(0.0)                     # no rule selected == no filter == zero lift
            continue
        (_, col, s_, t) = best[0]
        sc = score(ho, col, s_, t)
        lifts.append(0.0 if sc is None else sc["lift"])
    return lifts, infeasible


def main():
    out = {}
    print("=" * 100)
    print("MISSION Z -- THE ONE RULE.  Scored ONCE on the holdout.")
    print("=" * 100)

    rows = build_labels()
    rep = (sum(r["win"] for r in rows), sum(r["win3x"] for r in rows), len(rows))
    ok = rep[0] == 75 and rep[1] == 26 and rep[2] == 199
    print("\n[0] HARNESS REPLICATION (prereg s4, abort condition)")
    print("    WINNER %d/%d = %.2f%% (published 37.69%%)   WIN3X %d/%d = %.2f%% (published 13.07%%)   %s"
          % (rep[0], rep[2], pct(rep[0] / rep[2]), rep[1], rep[2], pct(rep[1] / rep[2]),
             "MATCH -- proceed" if ok else "MISMATCH -- ABORT"))
    out["replication_ok"] = ok
    if not ok:
        print("    ABORT: a PRIMARY label does not reproduce. Nothing else reported.")
        return

    rows = attach_features(rows)
    analysis = [r for r in rows if r["mature24"] and not r["skip"]]
    analysis.sort(key=lambda r: r["call_ts"])
    train = [r for r in analysis if r["call_ts"] < SPLIT_TS]
    hold = [r for r in analysis if r["call_ts"] >= SPLIT_TS]

    # ---- MDE FIRST, before any verdict (prereg s5)
    print("\n[1] MDE -- STATED BEFORE ANY VERDICT (prereg s5, restated not recomputed)")
    print("    Clustered unit = UTC call-day. 31 days, 199 calls, mean 6.42/day, median 6, max 18.")
    print("    BINDING (single pre-specified test = one score on the holdout, n=%d):" % len(hold))
    print("      ICC 0.00 -> %.1f pp   ICC 0.05 -> %.1f pp   ICC 0.10 -> 37.5 pp   (50/50 split; 30/70 adds ~3.5 pp)"
          % (MDE_ICC0, MDE_ICC05))
    print("    Full-sample descriptive only (n=179): 20.5 / 23.0 / 25.2 / 28.9 pp at ICC 0/.05/.10/.20")
    print("    => This design can only detect a filter moving 37.7%% -> ~69%%. An ordinary filter")
    print("       (37.7%% -> 50%%) is INVISIBLE here. Pre-committed: lift < MDE returns UNDERPOWERED,")
    print("       and the word 'null' is not available for this design.")

    print("\n[2] ANALYSIS SET AND SPLIT (prereg s3, time-ordered, cut 2026-09-28 00:00 UTC)")
    print("    24h-mature with a path: %d   train %d (%d days)   holdout %d (%d days)"
          % (len(analysis), len(train), len(set(r["day"] for r in train)),
             len(hold), len(set(r["day"] for r in hold))))
    print("    train 3x = %d   holdout 3x = %d   <- killer-metric denominators"
          % (sum(r["win3x"] for r in train), sum(r["win3x"] for r in hold)))

    print("\n[3] DEVIATIONS, DISCLOSED (prereg is sealed and is NOT edited)")
    print("    Sealed list is 14 features. Only 11 are realizable from what the fetch actually returned.")
    for m in MISSING_FEATS:
        print("      %-24s SOURCE-MISSING -- never fetched. Not imputed, not replaced." % m)
    print("      F4  pre_ret_15m          no 15m window exists in the file; realised as the 5m return.")
    print("      F1  pool_age_min         pool_created_at was never fetched; realised as age_proxy_s")
    print("                               (call_ts - first pre-call bar), with 15 rows age-censored.")
    print("      F10 prox_to_pre_high     realised as dist_from_6h_high_pre = prox - 1 (monotone identical,")
    print("                               so the threshold grid is unchanged).")
    print("    Longer-lookback columns the fetcher also produced (ret_24h/ret_7d/vol_6h/vol_24h/vol_7d/")
    print("    rv_6h/rv_7d/n_min_bars_6h/pct_of_6h_range) are NOT in the sealed 14 and are NOT used.")
    print("    Budget therefore falls from 236 to 10 continuous x 9 deciles x 2 + 1 binary x 2 = 182.")
    out["missing_features"] = MISSING_FEATS

    # ---- coverage + the no_prehistory bucket, reported as its own bucket (prereg s6a)
    print("\n[4] FEATURE COVERAGE ON THE ANALYSIS SET, and the no_prehistory bucket")
    nop = [r for r in analysis if r["precall_status"] != "ok"]
    evb = [r for r in analysis if r["precall_status"] == "ok"]
    pw, _, _, _ = eqday(nop, "win") if nop else (float("nan"),) * 4
    print("    no_prehistory (valid HTTP, EMPTY pre-call bar list): n=%d  winner %.1f%% pooled / %.1f%% eq-day"
          % (len(nop), pct(pooled([r["win"] for r in nop])), pct(pw)))
    print("    with pre-call history:                               n=%d  winner %.1f%% pooled / %.1f%% eq-day"
          % (len(evb), pct(pooled([r["win"] for r in evb])), pct(eqday(evb, "win")[0])))
    print("    Reported as a labelled bucket, never imputed to 0, and not promoted to a feature.")
    print("    %-24s %6s %6s" % ("feature", "n_trn", "n_hld"))
    for label, col, _ in FEATS:
        print("    %-24s %6d %6d" % (label, sum(1 for r in train if r["f"][col] is not None),
                                     sum(1 for r in hold if r["f"][col] is not None)))

    # ---- FIT on train only
    cands = candidates(train)
    print("\n[5] FIT -- TRAIN ONLY (n=%d). One feature, one threshold, one direction." % len(train))
    print("    Candidates realised: %d (budget 182 after the SOURCE-MISSING features; sealed budget 236)."
          % len(cands))
    ncoll = 0
    ncont = 0
    for _lab, _col, _ in FEATS:
        if _col in BINARY:
            continue
        ncont += 1
        nth = len(set(t2 for (_l, c2, s2, t2) in cands if c2 == _col and s2 == 1))
        if nth < len(DECILES):
            ncoll += 1
    print("    Grids collapse on ties -- %d of %d continuous feature grids lost thresholds to duplicate deciles."
          % (ncoll, ncont))
    sid = 1 - (1 - 0.05) ** (1.0 / max(1, len(cands)))
    print("    Sidak-adjusted alpha for %d tries: %.5f  (nominal 0.05)" % (len(cands), sid))
    print("    Train-side lift is a SELECTION statistic, not evidence (prereg s7).")

    best, feasible = fit(train, cands)
    out["n_candidates"] = len(cands)
    out["n_feasible"] = feasible
    print("    Candidates passing BOTH train constraints (3x-recall>=%.2f, keep_frac>=%.2f): %d of %d"
          % (MIN_TRAIN_3X_RECALL, MIN_KEEP_FRAC, feasible, len(cands)))

    if best is None:
        print("\n    NO CANDIDATE satisfies the sealed train constraints. Verdict: NO RULE SELECTED.")
        out["verdict"] = "NO RULE SELECTED"
        json.dump(out, io.open(os.path.join(D, "mission_z_rule.json"), "w"), indent=1, default=float)
        return

    (label, col, s, t), tsc = best
    arrow = ">=" if s == 1 else "<="
    print("\n    SELECTED RULE:  KEEP iff  %s %s %.6g" % (label, arrow, t))
    teq = eqday([r for r in train if r["f"][col] is not None and apply_rule(r, col, s, t)], "win")[0]
    tbase_eq = eqday([r for r in train if r["f"][col] is not None], "win")[0]
    print("      train: keep %d/%d (%.1f%%)  winner %.1f%% vs base %.1f%%  LIFT %+.1f pp pooled / %+.1f pp eq-day"
          % (tsc["n_keep"], tsc["n_ev"], pct(tsc["keep_frac"]), pct(tsc["keep_rate"]),
             pct(tsc["base"]), pct(tsc["lift"]), pct(teq - tbase_eq)))
    print("      train 3x-recall %d/%d = %.3f" % (tsc["k3"], tsc["n3"], tsc["recall3"]))

    ev_tr = [r for r in train if r["f"][col] is not None]
    _, _, rts, szs = eqday(ev_tr, "win")
    r_, rlo, rhi, rt = corr_ci_t(szs, rts)
    print("      corr(day size, day winner rate) on train evaluable = %+.3f  95%% CI [%+.2f, %+.2f]  t=%+.2f  (%d days)"
          % (r_, rlo, rhi, rt, len(szs)))

    # ---- sign stability (prereg s11)
    print("\n[6] WALK-FORWARD SIGN STABILITY (prereg s11 -- gate; 5 of 6 rules flipped in M3)")
    tss = sorted(r["call_ts"] for r in train)
    med = tss[len(tss) // 2]
    T1 = [r for r in train if r["call_ts"] < med]
    T2 = [r for r in train if r["call_ts"] >= med]
    halves = []
    for nm, h in (("T1", T1), ("T2", T2)):
        sc = score(h, col, s, t)
        evh = [r for r in h if r["f"][col] is not None]
        kh = [r for r in evh if apply_rule(r, col, s, t)]
        e = (eqday(kh, "win")[0] - eqday(evh, "win")[0]) if kh else float("nan")
        halves.append((nm, sc, e))
        if sc is None:
            print("    %s n=%d  NOT EVALUABLE" % (nm, len(h)))
        else:
            print("    %s n_ev=%2d keep=%2d  lift %+.1f pp pooled / %+.1f pp eq-day"
                  % (nm, sc["n_ev"], sc["n_keep"], pct(sc["lift"]), pct(e)))
    l1 = halves[0][1]["lift"] if halves[0][1] else float("nan")
    l2 = halves[1][1]["lift"] if halves[1][1] else float("nan")
    sign_ok = (l1 == l1 and l2 == l2 and (l1 >= 0) == (l2 >= 0))
    print("    sign(T1)=%s  sign(T2)=%s  -> SIGN-STABILITY GATE %s"
          % ("+" if l1 >= 0 else "-", "+" if l2 >= 0 else "-", "PASS" if sign_ok else "FAIL"))
    out["sign_stability"] = {"T1_lift_pp": pct(l1), "T2_lift_pp": pct(l2), "pass": bool(sign_ok)}

    # ---- THE ONE HOLDOUT SCORE
    print("\n[7] HOLDOUT -- SCORED ONCE. No refit, no second look.")
    hsc = score(hold, col, s, t)
    if hsc is None:
        print("    NOT EVALUABLE on the holdout. SOURCE-MISSING.")
        out["verdict"] = "SOURCE-MISSING"
        json.dump(out, io.open(os.path.join(D, "mission_z_rule.json"), "w"), indent=1, default=float)
        return
    ev_ho = [r for r in hold if r["f"][col] is not None]
    k_ho = [r for r in ev_ho if apply_rule(r, col, s, t)]
    heq_k = eqday(k_ho, "win")[0]
    heq_b = eqday(ev_ho, "win")[0]
    heq = heq_k - heq_b
    (plo, phi), (elo, ehi) = block_boot_lift(ev_ho, lambda r: apply_rule(r, col, s, t))
    _, _, hrts, hszs = eqday(ev_ho, "win")
    hr, hrlo, hrhi, hrt = corr_ci_t(hszs, hrts)
    print("    evaluable %d of %d holdout calls   keep %d (%.1f%%)" %
          (hsc["n_ev"], len(hold), hsc["n_keep"], pct(hsc["keep_frac"])))
    print("    winner rate  KEEP %.1f%%   vs evaluable base %.1f%%" % (pct(hsc["keep_rate"]), pct(hsc["base"])))
    print("    HOLDOUT LIFT  %+.1f pp pooled  [%+.1f, %+.1f]   %+.1f pp EQ-WEIGHT-BY-DAY  [%+.1f, %+.1f]"
          % (pct(hsc["lift"]), pct(plo), pct(phi), pct(heq), pct(elo), pct(ehi)))
    print("    corr(day size, day winner rate) holdout = %+.3f  95%% CI [%+.2f, %+.2f]  t=%+.2f  (%d days)"
          % (hr, hrlo, hrhi, hrt, len(hszs)))
    print("    MDE restated: %.1f pp (ICC 0) / %.1f pp (ICC 0.05)." % (MDE_ICC0, MDE_ICC05))
    beats_mde = pct(abs(heq)) >= MDE_ICC0 and heq > 0
    print("    |lift| vs MDE: %.1f pp vs %.1f pp -> %s"
          % (pct(abs(heq)), MDE_ICC0, "exceeds" if beats_mde else "BELOW the detection floor"))
    out["holdout"] = {"n_ev": hsc["n_ev"], "n_keep": hsc["n_keep"], "keep_frac": hsc["keep_frac"],
                      "keep_rate_pct": pct(hsc["keep_rate"]), "base_pct": pct(hsc["base"]),
                      "lift_pooled_pp": pct(hsc["lift"]), "lift_pooled_ci": [pct(plo), pct(phi)],
                      "lift_eqday_pp": pct(heq), "lift_eqday_ci": [pct(elo), pct(ehi)],
                      "corr_day": hr, "corr_ci": [hrlo, hrhi], "corr_t": hrt}

    # ---- THE KILLER METRIC (prereg s8)
    print("\n[8] KILLER METRIC -- share of 3x+ winners the filter THROWS AWAY (prereg s8 GATE)")
    rc, rlo2, rhi2 = wilson(hsc["k3"], hsc["n3"])
    disc = 1 - rc if rc == rc else float("nan")
    print("    holdout runner_recall = %d/%d = %.3f   Wilson 95%% [%.2f, %.2f]"
          % (hsc["k3"], hsc["n3"], rc, rlo2, rhi2))
    print("    => RUNNERS DISCARDED = %d of %d 3x winners = %.1f%%"
          % (hsc["n3"] - hsc["k3"], hsc["n3"], pct(disc)))
    gate_ok = (rc == rc) and rc >= GATE_RECALL and rlo2 >= GATE_WILSON_LO
    print("    gate: recall >= %.2f AND Wilson lower >= %.2f -> %s"
          % (GATE_RECALL, GATE_WILSON_LO, "PASS" if gate_ok else "FAIL"))
    for nm, sel, key in (("full sample, WIN3X_24h", analysis, "win3x"),
                         ("full sample, WIN3X_7D ", analysis, "win3x7d_pub")):
        ev = [r for r in sel if r["f"][col] is not None]
        n3 = sum(r[key] for r in ev)
        k3 = sum(r[key] for r in ev if apply_rule(r, col, s, t))
        p3, a, b = wilson(k3, n3)
        print("    descriptive  %s: recall %d/%d = %.3f  Wilson [%.2f, %.2f]" % (nm, k3, n3, p3, a, b))
    print("    The gate is deliberately asymmetric: at n~10 it can FAIL a rule credibly but can never")
    print("    certify one as runner-safe (Wilson width ~[0.66, 0.94] at recall 0.85).")
    out["runner_recall"] = {"k": hsc["k3"], "n": hsc["n3"], "recall": rc, "wilson": [rlo2, rhi2],
                            "discarded_pct": pct(disc), "gate_pass": bool(gate_ok)}

    # ---- PLACEBO (prereg s10)
    print("\n[9] PLACEBO -- day-block feature permutation, %d iters, full pipeline each (prereg s10)"
          % PLACEBO_ITERS)
    lifts, infeas = placebo(analysis, lambda tr: candidates(tr))
    sl = sorted(lifts)
    p50 = sl[len(sl) // 2]
    p95 = sl[int(0.95 * len(sl))]
    print("    null holdout lift: median %+.1f pp   95th pct %+.1f pp   min %+.1f  max %+.1f"
          % (pct(p50), pct(p95), pct(sl[0]), pct(sl[-1])))
    print("    LEAK CHECK: null median must sit within +/-3 pp of 0 -> %+.1f pp  %s"
          % (pct(p50), "OK" if abs(pct(p50)) <= 3.0 else "LEAK -- NO RESULT MAY BE REPORTED"))
    print("    iterations with no feasible rule: %d of %d (recorded as zero lift)" % (infeas, PLACEBO_ITERS))
    emp_p = sum(1 for v in lifts if v >= hsc["lift"]) / len(lifts)
    print("    real pooled holdout lift %+.1f pp vs null 95th pct %+.1f pp -> empirical p = %.3f"
          % (pct(hsc["lift"]), pct(p95), emp_p))
    print("    This could have come out against the rule, and %s."
          % ("it did" if hsc["lift"] < p95 else "it did not"))
    leak_ok = abs(pct(p50)) <= 3.0
    out["placebo"] = {"null_median_pp": pct(p50), "null_p95_pp": pct(p95),
                      "real_pp": pct(hsc["lift"]), "emp_p": emp_p,
                      "infeasible": infeas, "leak_ok": bool(leak_ok)}

    # ---- 7d dud leg, train-side descriptive only (prereg s3/s12)
    print("\n[10] 7d DUD LEG -- train-side DESCRIPTIVE ONLY, no verdict (prereg s5: n=26 untestable)")
    dud_ev = [r for r in train if r["f"][col] is not None and r["dud"] is not None]
    imm = sum(1 for r in train if r["dud"] is None)
    if dud_ev:
        kd = [r for r in dud_ev if apply_rule(r, col, s, t)]
        print("     train evaluable with a dud label n=%d (OUTCOME-IMMATURE excluded: %d)" % (len(dud_ev), imm))
        print("     dud rate  KEEP %.1f%% pooled / %.1f%% eq-day   vs base %.1f%% pooled / %.1f%% eq-day"
              % (pct(pooled([r["dud"] for r in kd])), pct(eqday(kd, "dud")[0]),
                 pct(pooled([r["dud"] for r in dud_ev])), pct(eqday(dud_ev, "dud")[0])))
    print("     Holdout dud leg (26 calls, 4 days) was declared untestable in the prereg: NO VERDICT.")

    # ---- VERDICT (prereg s12 ordered logic)
    print("\n" + "=" * 100)
    print("[11] VERDICT TABLE (prereg s12, ordered logic)")
    print("=" * 100)
    if not leak_ok:
        verdict = "NOTHING REPORTABLE (placebo leak)"
    elif not gate_ok:
        verdict = "WORTHLESS (kills runners)"
    elif not sign_ok:
        verdict = "NO EDGE (sign flip)"
    elif not beats_mde:
        verdict = "UNDERPOWERED"
    elif hsc["lift"] > p95:
        verdict = "EDGE (provisional, single sample)"
    else:
        verdict = "UNDERPOWERED"
    tbl = [
        ("rule", "KEEP iff %s %s %.6g" % (label, arrow, t)),
        ("candidates tried", "%d realised (sealed budget 236; 182 after SOURCE-MISSING feats); Sidak alpha %.5f"
         % (len(cands), sid)),
        ("train lift", "%+.1f pp pooled / %+.1f pp eq-day, keep %d/%d"
         % (pct(tsc["lift"]), pct(teq - tbase_eq), tsc["n_keep"], tsc["n_ev"])),
        ("corr(day size, day rate)", "%+.3f [%+.2f, %+.2f] t=%+.2f, %d days (holdout)" % (hr, hrlo, hrhi, hrt, len(hszs))),
        ("T1 / T2 half lifts", "%+.1f pp / %+.1f pp -> gate %s" % (pct(l1), pct(l2), "PASS" if sign_ok else "FAIL")),
        ("HOLDOUT LIFT (one score)", "%+.1f pp pooled [%+.1f, %+.1f] / %+.1f pp eq-day [%+.1f, %+.1f]"
         % (pct(hsc["lift"]), pct(plo), pct(phi), pct(heq), pct(elo), pct(ehi))),
        ("MDE", "%.1f pp (ICC 0) / %.1f pp (ICC 0.05)" % (MDE_ICC0, MDE_ICC05)),
        ("runner recall (holdout)", "%d/%d = %.3f Wilson [%.2f, %.2f]; DISCARDS %.1f%% of 3x -> gate %s"
         % (hsc["k3"], hsc["n3"], rc, rlo2, rhi2, pct(disc), "PASS" if gate_ok else "FAIL")),
        ("placebo", "real %+.1f pp vs null p95 %+.1f pp, p=%.3f; null median %+.1f pp (leak check %s)"
         % (pct(hsc["lift"]), pct(p95), emp_p, pct(p50), "OK" if leak_ok else "FAIL")),
        ("7d dud leg", "train-side descriptive only; %d OUTCOME-IMMATURE excluded; holdout n=26 no verdict" % imm),
        ("VERDICT", verdict),
    ]
    for k, v in tbl:
        print("  %-26s | %s" % (k, v))
    out["verdict"] = verdict
    out["rule"] = {"feature": label, "col": col, "direction": s, "threshold": t}
    json.dump(out, io.open(os.path.join(D, "mission_z_rule.json"), "w"), indent=1, default=float)
    print("\nwrote mission_z_rule.json")


if __name__ == "__main__":
    main()
