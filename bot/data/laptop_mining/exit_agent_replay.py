"""Does the LLM exit agent add value? Replay its real decisions against what holding would have done.

REAL_LEDGER.md observed that the exit agent closes 105 of 293 positions (36%) at a 22% win rate for
-$721, the largest single line item in the ledger. The server asked for a full red team on that. But
a composition table cannot answer the question, because the agent CHOOSES which positions to close --
so "its closes lose money" may just mean "it closes the losers", which is its job.

This is the counterfactual instead, and it is the owner's own suggested method: take the REAL
decisions with their real timestamps and prices, and vary only ONE thing -- whether the agent acted.

WHY THIS IS A SAFER SIMULATION THAN THE ONES THAT FAILED
My trailing-exit simulation was refuted because it synthesised the whole trade: I invented the entry,
the bracket, the intra-bar ordering and the fills, and three of those conventions were wrong. Here the
entry, side, stop, target, decision time and decision price are all OBSERVED from
exit_decisions.jsonl + position_journal.jsonl. The only counterfactual is "hold instead", evaluated on
real candles. Far fewer degrees of freedom, and the thing it is compared against actually happened.

THE NATURAL EXPERIMENT. The agent emits four actions: close (827), partial (198), hold (177),
tighten_sl (118). It HOLDS 13% of the time, so there is a within-agent comparison group, and it is
not a pure loss-cutter -- only 10% of its stated reasons mention a loss at all; the rest are regime
mismatch, thesis invalidation and dead capital.

WHAT IS MEASURED, per `close` decision at time t:
  acted   = the position is closed at the decision price (observed)
  held    = the position continues on real 1h candles until the FIRST of:
              its own stop (position_sl, observed), its own target (position_tp2, observed),
              or a horizon cap (24h / 48h / 168h reported separately)
  edge    = acted - held, in R units where R = |entry - position_sl| (so coins are comparable)
A positive edge means the agent saved money by closing. A negative edge means it closed a position
that would have recovered.

GUARDS, because this project has nine reversals behind it:
  * R units, so the pre-2026-07-24 USD leverage bug cannot touch the result.
  * SL-vs-TP tie inside one bar resolved as STOP-FIRST (conservative for the HOLD arm, i.e. biased
    AGAINST the agent looking bad -- the direction that makes a negative verdict harder to reach).
  * Both the stop-first and target-first tie conventions reported, because convention choices are
    what killed the trailing finding.
  * Week-clustered CIs with the equal-weighted week mean beside every pooled figure.
  * A placebo: shuffle the decision TIMES within each symbol, preserving count and clustering, and
    confirm the measured edge disappears. Size reported before any verdict.
  * The `hold` decisions replayed the same way as a validation arm -- if the measurement is sound,
    the agent's own holds should look different from its closes.
"""
import json, io, os, csv, math, collections, datetime, warnings
warnings.simplefilter("ignore")
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.join(HERE, "server_exports")
HIST = os.path.join(HERE, "history")
FEE_BPS = 9.0
HORIZONS = (24, 48, 168)
PLACEBO = 300
rng = np.random.default_rng(20261010)


def load1h(sym):
    rows = []
    p = os.path.join(HIST, f"{sym}_1h_fresh.csv")
    if not os.path.exists(p):
        return None
    with io.open(p, encoding="utf-8", errors="replace", newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                rows.append((int(r["t_ms"]) // 1000, float(r["o"]), float(r["h"]),
                             float(r["l"]), float(r["c"])))
            except (TypeError, ValueError):
                continue
    rows.sort()
    return rows


def decisions():
    out = []
    with io.open(os.path.join(EXP, "exit_decisions.jsonl"), encoding="utf-8", errors="replace") as fh:
        for l in fh:
            l = l.strip()
            if not l:
                continue
            try:
                d = json.loads(l)
            except json.JSONDecodeError:
                continue
            try:
                ts = datetime.datetime.fromisoformat(d["ts"]).timestamp()
                e = float(d["position_entry"]); sl = float(d["position_sl"])
            except (TypeError, ValueError, KeyError):
                continue
            if not (e > 0 and sl > 0) or e == sl:
                continue
            tp = d.get("position_tp2")
            try:
                tp = float(tp) if tp is not None else None
            except (TypeError, ValueError):
                tp = None
            out.append({"ts": ts, "sym": d.get("symbol"), "side": d.get("position_side"),
                        "entry": e, "sl": sl, "tp": tp, "action": d.get("exit_action"),
                        "state": d.get("position_state"), "conf": d.get("exit_confidence"),
                        "reason": d.get("reason") or ""})
    # FIX 1: R must use the ORIGINAL stop. position_sl is the CURRENT stop, and after a
    # tighten_sl it sits near entry, so |entry-sl| collapses and every R explodes (observed
    # -14.6R on tighten_sl rows). exit_decisions has no position_id, so identity is
    # (symbol, position_entry) and the original risk is the EARLIEST stop seen for it.
    out.sort(key=lambda x: x["ts"])
    orig = {}
    for d in out:
        k = (d["sym"], round(d["entry"], 8))
        if k not in orig:
            orig[k] = abs(d["entry"] - d["sl"])
    for d in out:
        d["risk0"] = orig[(d["sym"], round(d["entry"], 8))]
        d["pos_key"] = (d["sym"], round(d["entry"], 8))
    return out


CAND = {}


def first_after(c, t):
    lo, hi = 0, len(c)
    while lo < hi:
        mid = (lo + hi) // 2
        if c[mid][0] <= t:
            lo = mid + 1
        else:
            hi = mid
    return lo if lo < len(c) else None


def replay(d, hours, stop_first=True):
    """Return (acted_R, held_R) for one decision, or None if unreplayable."""
    c = CAND.get(d["sym"])
    if not c:
        return None
    i0 = first_after(c, d["ts"])
    if i0 is None or i0 >= len(c) - 2:
        return None
    long_ = (d["side"] or "").upper() == "LONG"
    e, sl, tp = d["entry"], d["sl"], d["tp"]
    risk = d.get("risk0") or abs(e - sl)      # FIX 1: original risk, not the moved stop
    if risk <= 0:
        return None
    sg = 1.0 if long_ else -1.0
    feeR = 2 * (FEE_BPS / 1e4) * e / risk

    # ACTED: closed at the decision price = the open of the first bar at/after the decision
    px_now = c[i0][1]
    acted = sg * (px_now - e) / risk - feeR

    # HELD: continue on real candles to stop / target / horizon
    end = d["ts"] + hours * 3600
    held = None
    k = i0
    while k < len(c) and c[k][0] <= end:
        _, o, h, l, cl = c[k]
        hs = (l <= sl) if long_ else (h >= sl)
        ht = (tp is not None) and ((h >= tp) if long_ else (l <= tp))
        # FIX 3: a stop HIT is not -1R once the stop has moved. With original-risk
        # normalisation it books (sl - entry)/risk0, which for a tightened or
        # breakeven-moved stop is far better than -1. Hardcoding -1.0 penalised the HOLD
        # arm exactly on the positions whose stop had been improved -- biasing the result
        # toward "the agent adds value".
        sl_R = sg * (sl - e) / risk
        if hs and ht:
            held = (sl_R if stop_first else sg * (tp - e) / risk)
            break
        if hs:
            held = sl_R
            break
        if ht:
            held = sg * (tp - e) / risk
            break
        k += 1
    if held is None:
        last = c[min(k, len(c) - 1)][4]
        held = sg * (last - e) / risk
    held -= feeR
    return acted, held


def wk(vals, ts):
    byw = collections.defaultdict(list)
    for v, t in zip(vals, ts):
        ic = datetime.datetime.fromtimestamp(t, datetime.UTC).isocalendar()
        byw[f"{ic[0]}-W{ic[1]:02d}"].append(v)
    mus = np.array([np.mean(x) for x in byw.values()])
    if len(mus) < 6:
        return float("nan"), float("nan"), len(mus)
    se = float(mus.std(ddof=1)) / math.sqrt(len(mus))
    return float(mus.mean()), (float(mus.mean()) / se if se > 0 else float("nan")), len(mus)


def main():
    D = decisions()
    for s in {d["sym"] for d in D}:
        c = load1h(s)
        if c:
            CAND[s] = c
    print(f"{len(D)} replayable decisions, {len(CAND)} symbols with candles")
    print("action mix:", dict(collections.Counter(d["action"] for d in D)))
    print()
    out = {"n_decisions": len(D), "horizons": list(HORIZONS), "results": {}}

    print("=" * 104)
    print("DID THE AGENT'S CLOSE BEAT HOLDING?  edge = acted - held, in R.  positive = the close saved money")
    print("  stop-first tie rule (conservative for the HOLD arm, so it makes the agent look BETTER)")
    print("=" * 104)
    print(f"  {'action':<12}{'horizon':>9}{'n':>7}{'acted R':>10}{'held R':>10}"
          f"{'edge':>10}{'wk edge':>10}{'wk t':>8}  verdict")
    print("-" * 104)
    for act in ("close", "partial", "hold", "tighten_sl"):
        sub = [d for d in D if d["action"] == act]
        for hours in HORIZONS:
            pairs, ts = [], []
            for d in sub:
                r = replay(d, hours, stop_first=True)
                if r:
                    pairs.append(r[0] - r[1]); ts.append(d["ts"])
            if len(pairs) < 40:
                continue
            a = np.mean([replay(d, hours, True)[0] for d in sub if replay(d, hours, True)])
            h = np.mean([replay(d, hours, True)[1] for d in sub if replay(d, hours, True)])
            m, t, nw = wk(pairs, ts)
            v = ("agent ADDS value" if (np.isfinite(t) and m - 1.96 * m / t > 0 and t > 1.96)
                 else "agent DESTROYS value" if (np.isfinite(t) and t < -1.96)
                 else "no measurable effect")
            print(f"  {act:<12}{str(hours)+'h':>9}{len(pairs):>7}{a:>+10.3f}{h:>+10.3f}"
                  f"{np.mean(pairs):>+10.3f}{m:>+10.3f}{t:>8.2f}  {v}")
            out["results"][f"{act}|{hours}h"] = {
                "n": len(pairs), "acted_R": round(float(a), 4), "held_R": round(float(h), 4),
                "edge_pooled": round(float(np.mean(pairs)), 4), "edge_week": round(m, 4),
                "week_t": round(float(t), 2) if np.isfinite(t) else None, "weeks": nw}

    print("\n" + "=" * 104)
    print("CONVENTION CHECK — the same table with the TARGET-first tie rule")
    print("  (the trailing finding died on exactly this kind of choice, so both are reported)")
    print("=" * 104)
    print(f"  {'action':<12}{'horizon':>9}{'n':>7}{'edge stop-first':>18}{'edge target-first':>20}{'sign flips?':>14}")
    print("-" * 104)
    for act in ("close", "hold"):
        sub = [d for d in D if d["action"] == act]
        for hours in HORIZONS:
            e1 = [replay(d, hours, True) for d in sub]
            e2 = [replay(d, hours, False) for d in sub]
            v1 = [x[0] - x[1] for x in e1 if x]
            v2 = [x[0] - x[1] for x in e2 if x]
            if len(v1) < 40:
                continue
            f1, f2 = np.mean(v1), np.mean(v2)
            print(f"  {act:<12}{str(hours)+'h':>9}{len(v1):>7}{f1:>+18.3f}{f2:>+20.3f}"
                  f"{('YES' if (f1 > 0) != (f2 > 0) else 'no'):>14}")
            out["results"].setdefault(f"{act}|{hours}h", {})["edge_target_first"] = round(float(f2), 4)

    print("\n" + "=" * 104)
    print("PLACEBO — shuffle decision TIMES within each symbol (count and clustering kept)")
    print("=" * 104)
    sub = [d for d in D if d["action"] == "close"]
    bysym = collections.defaultdict(list)
    for d in sub:
        bysym[d["sym"]].append(d)
    real_pairs, real_ts = [], []
    for d in sub:
        r = replay(d, 48, True)
        if r:
            real_pairs.append(r[0] - r[1]); real_ts.append(d["ts"])
    real_m, real_t, _ = wk(real_pairs, real_ts)
    poswin = {}
    for d in D:
        k = d["pos_key"]
        if k in poswin:
            poswin[k] = (min(poswin[k][0], d["ts"]), max(poswin[k][1], d["ts"]))
        else:
            poswin[k] = (d["ts"], d["ts"])
    nulls = []
    for _ in range(PLACEBO):
        vals, tss = [], []
        # FIX 2: shuffling to a RANDOM DATE broke the entry<->price link, so `acted` became a
        # huge random number and the placebo returned |t|>1.96 on 100% of draws. Instead jitter
        # the decision time WITHIN the same position's own decision window, which asks the right
        # question: was the agent's TIMING better than an arbitrary moment in the same position?
        for s, ds in bysym.items():
            c = CAND.get(s)
            if not c:
                continue
            for d in ds:
                span = poswin.get(d["pos_key"])
                if not span or span[1] - span[0] < 3600:
                    continue
                d2 = dict(d); d2["ts"] = float(rng.uniform(span[0], span[1]))
                r = replay(d2, 48, True)
                if r:
                    vals.append(r[0] - r[1]); tss.append(d2["ts"])
        if len(vals) > 40:
            m2, t2, _ = wk(vals, tss)
            nulls.append(t2)
    nulls = np.array([x for x in nulls if np.isfinite(x)])
    size = float(np.mean(np.abs(nulls) > 1.96)) if len(nulls) else float("nan")
    print(f"  real close-edge at 48h: {real_m:+.4f} R, week t {real_t:.2f}")
    print(f"  placebo week t: mean {nulls.mean():+.2f}, sd {nulls.std(ddof=1):.2f}, "
          f"|t|>1.96 in {100*size:.1f}% of draws")
    print(f"  => placebo size {size:.3f} against nominal 0.05: "
          f"{'calibrated' if 0.01 <= size <= 0.12 else 'MISCALIBRATED, design void'}")
    print(f"  p(|placebo t| >= |real t|) = {float(np.mean(np.abs(nulls) >= abs(real_t))):.3f}")
    out["placebo"] = {"size": round(size, 3), "real_week_t": round(float(real_t), 2),
                      "p": round(float(np.mean(np.abs(nulls) >= abs(real_t))), 4),
                      "valid": bool(0.01 <= size <= 0.12)}

    with io.open(os.path.join(HERE, "exit_agent_replay.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    print("\nwrote exit_agent_replay.json")


if __name__ == "__main__":
    main()
