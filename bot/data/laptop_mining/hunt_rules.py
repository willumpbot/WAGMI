"""Mission 4: hunt falsifiable slice rules from the graded laptop corpus.

Grammar and scoring follow bot/tools/rules_manager.py exactly:
  slice   = {symbol?, side?, agree?, regime?}       agree bucket in {1,2,3+}
  action  = avoid | favor
  metric  = IN-SLICE minus OUT-OF-SLICE mean e_4h (bps, net of fees)
            -- not the in-slice level; a rule must beat the rest of the book
  earn    = signals: n_in >= 30 AND bootstrap CI on the DIFF excludes 0 in the
            rule's direction

Honest out-of-sample: train on 2026-03-16 -> 04-30, test on 05-01 -> 06-05.
A candidate is only promoted if the sign holds in BOTH halves.

Bootstrap resamples (symbol, UTC day) clusters and recomputes both the in- and
out-of-slice means each draw, so the CI is on the difference.
"""
import json, io, os, gzip, collections, random

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "graded_signals.jsonl.gz")
CUTOFF = "2026-05-01"
MIN_IN = 30
random.seed(20261008)

rows = []
with gzip.open(SRC, "rt", encoding="utf-8") as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if r.get("e_4h") is None:
            continue
        a = int(r["num_agree"])
        rs = r.get("regime_score")
        rows.append({
            "day": r["day"], "sym": r["sym"], "side": r["side"],
            "agree": "1" if a <= 1 else ("2" if a == 2 else "3+"),
            # corpus carries a numeric regime_score, not the server's regime
            # label vocabulary -- bucketed, and flagged as a different vocabulary
            "regime": None if rs is None else ("rs_lo" if rs < 0.33 else
                      ("rs_mid" if rs < 0.67 else "rs_hi")),
            "e": r["e_4h"], "first": r.get("first_hit"),
        })

print(f"graded rows with e_4h : {len(rows)}")
train = [r for r in rows if r["day"] < CUTOFF]
test = [r for r in rows if r["day"] >= CUTOFF]
print(f"train (< {CUTOFF})    : {len(train)}  ({min(r['day'] for r in train)} -> {max(r['day'] for r in train)})")
print(f"test  (>= {CUTOFF})   : {len(test)}  ({min(r['day'] for r in test)} -> {max(r['day'] for r in test)})")
print(f"regime_score present  : {sum(1 for r in rows if r['regime'])}/{len(rows)}")


def matches(r, sl):
    for k in ("sym", "side", "agree", "regime"):
        if sl.get(k) is not None and r.get(k) != sl[k]:
            return False
    return True


def diff_stats(rows_, sl, iters=3000):
    ins = [r for r in rows_ if matches(r, sl)]
    out = [r for r in rows_ if not matches(r, sl)]
    if len(ins) < 2 or len(out) < 2:
        return None
    mi = sum(r["e"] for r in ins) / len(ins)
    mo = sum(r["e"] for r in out) / len(out)
    cl = collections.defaultdict(lambda: ([], []))
    for r in rows_:
        b = cl[(r["sym"], r["day"])]
        (b[0] if matches(r, sl) else b[1]).append(r["e"])
    keys = list(cl)
    diffs = []
    if len(keys) >= 3:
        for _ in range(iters):
            a, b = [], []
            for _ in range(len(keys)):
                k = keys[random.randrange(len(keys))]
                a.extend(cl[k][0]); b.extend(cl[k][1])
            if a and b:
                diffs.append(sum(a) / len(a) - sum(b) / len(b))
        diffs.sort()
    lo = diffs[int(0.025 * len(diffs))] if diffs else None
    hi = diffs[int(0.975 * len(diffs))] if diffs else None
    return {"n_in": len(ins), "n_out": len(out),
            "n_eff_in": len({(r["sym"], r["day"]) for r in ins}),
            "mean_in": round(mi, 2), "mean_out": round(mo, 2),
            "diff": round(mi - mo, 2),
            "ci": [round(lo, 2), round(hi, 2)] if lo is not None else None,
            "sl_first_pct": round(100 * sum(1 for r in ins if r["first"] == "sl") / len(ins), 1),
            "tp1_first_pct": round(100 * sum(1 for r in ins if r["first"] == "tp1") / len(ins), 1)}


# candidate slice space
cands = []
syms = sorted({r["sym"] for r in rows})
for s in syms:
    cands.append({"sym": s})
    for sd in ("LONG", "SHORT"):
        cands.append({"sym": s, "side": sd})
for sd in ("LONG", "SHORT"):
    cands.append({"side": sd})
for ag in ("1", "2", "3+"):
    cands.append({"agree": ag})
    for sd in ("LONG", "SHORT"):
        cands.append({"agree": ag, "side": sd})
for rg in ("rs_lo", "rs_mid", "rs_hi"):
    if any(r["regime"] == rg for r in rows):
        cands.append({"regime": rg})
        for sd in ("LONG", "SHORT"):
            cands.append({"regime": rg, "side": sd})

print(f"\ncandidate slices evaluated: {len(cands)}")

results = []
for sl in cands:
    tr = diff_stats(train, sl)
    if not tr or tr["n_in"] < MIN_IN:
        continue
    te = diff_stats(test, sl)
    action = "avoid" if tr["diff"] < 0 else "favor"
    want = -1 if action == "avoid" else 1
    ci_ok = bool(tr["ci"] and ((tr["ci"][1] < 0) if want < 0 else (tr["ci"][0] > 0)))
    oos_ok = bool(te and te["n_in"] >= 13 and
                  ((te["diff"] < 0) if want < 0 else (te["diff"] > 0)))
    results.append({
        "slice": {k: v for k, v in sl.items() if v is not None},
        "action": action, "train": tr, "test": te,
        "train_ci_excludes_0": ci_ok, "oos_sign_holds": oos_ok,
        "status": "CANDIDATE" if (ci_ok and oos_ok) else
                  ("in-sample only" if ci_ok else
                   ("oos only" if oos_ok else "no signal")),
    })

results.sort(key=lambda r: (r["status"] != "CANDIDATE", -abs(r["train"]["diff"])))

print("\n" + "=" * 118)
print("SLICE RULE SCAN — e_4h bps, IN-SLICE minus OUT-OF-SLICE  (train 03-16..04-30 | test 05-01..06-05)")
print("=" * 118)
print(f"{'slice':<30}{'act':<7}{'n_in':>6}{'nEff':>6}{'diff':>9}{'CI95 (train)':>20}"
      f"{'oos n':>7}{'oos diff':>10}  status")
print("-" * 118)
for r in results:
    sl = ",".join(f"{k}={v}" for k, v in r["slice"].items())
    tr, te = r["train"], r["test"]
    ci = f"[{tr['ci'][0]:>7.1f},{tr['ci'][1]:>7.1f}]" if tr["ci"] else " " * 17
    on = te["n_in"] if te else 0
    od = f"{te['diff']:>9.1f}" if te else "      n/a"
    print(f"{sl[:29]:<30}{r['action']:<7}{tr['n_in']:>6}{tr['n_eff_in']:>6}"
          f"{tr['diff']:>9.1f}{ci:>20}{on:>7}{od}  {r['status']}")

promoted = [r for r in results if r["status"] == "CANDIDATE"]
print(f"\nPROMOTED (train CI excludes 0 AND out-of-sample sign holds): {len(promoted)}")
for r in promoted:
    sl = ",".join(f"{k}={v}" for k, v in r["slice"].items())
    print(f"  {r['action']:<6} {sl:<34} train {r['train']['diff']:+.1f} bps "
          f"{r['train']['ci']}  oos {r['test']['diff']:+.1f} bps (n={r['test']['n_in']})")

payload = {
    "generated": "2026-10-08",
    "source": "laptop signal corpus, forward-graded vs Hyperliquid 1h candles",
    "metric": "mean e_4h in-slice minus out-of-slice, bps net of 9 bps fees",
    "grammar": "bot/tools/rules_manager.py (symbol|side|agree|regime; avoid|favor)",
    "train_window": ["2026-03-16", "2026-04-30"],
    "test_window": [CUTOFF, "2026-06-05"],
    "min_n_in": MIN_IN,
    "caveats": [
        "Trade-side corroboration is NOT available: every closed-trade series on this laptop is "
        "corrupt (fixture flooding, fill over-credit). These candidates rest on forward-graded "
        "signals only. The server should cross-check against its own 290-trade ledger before acting.",
        "regime here is a bucketed numeric regime_score, NOT the server's regime label vocabulary. "
        "The bucketing is also badly unbalanced: rs_lo holds 11,410 of 11,574 train rows and "
        "rs_mid is empty, so any rs_lo rule is near-tautological against a 164-row complement. "
        "Treat every regime= slice here as unusable until a real regime label is joined in.",
        "Horizon resolution is coarser than the server's (1h bars, up to 1h boundary drift).",
        "29 slices were scanned. No slice's training CI excluded 0, so nothing was promoted; "
        "multiple-comparison risk is therefore moot, but it also means nothing here is actionable.",
        "IMPORTANT correction to REGRADE.md: BTC's in-slice level (-15.9 bps, CI excluding 0) does "
        "NOT survive the manager's in-minus-out metric. BTC vs non-BTC is -9.8 bps, CI "
        "[-36.7, +15.7]. BTC looks bad because the whole book is bad, not because it is "
        "distinctively worse. Do not ship an avoid-BTC rule on this evidence.",
    ],
    "candidates": results,
    "promoted": [r["slice"] | {"action": r["action"]} for r in promoted],
}
with io.open(os.path.join(HERE, "RULE_CANDIDATES.json"), "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=1)
print("\nwrote RULE_CANDIDATES.json")
