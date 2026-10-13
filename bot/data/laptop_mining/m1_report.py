"""M1 aggregation — ranked exit table. EXPLORATORY: nothing here may reach a card above HYPOTHESIS.

GOVERNING STATISTIC: the COIN-clustered equal-weighted mean of (measured - no-edge control), in bps
of notional net of fees. Coins dominate this panel (178 of them, one entry sample each), so the coin
is the clustering unit the mission's ground rules require, and the equal-weighted figure is printed
beside the pooled one because pooling has caused a sign flip in this project more often than any
other single defect.

WHY THE SUBTRACTION IS NOT OPTIONAL: the no-edge control (a martingale bootstrap of each coin's own
bar shapes) lands between -0.075R and +0.040R of -fee depending on the RULE. That spread is discrete-
bar geometry, not edge. A table of raw measured numbers would rank stop/target geometry and call it
exit skill -- which is exactly how E2 died earlier tonight.

Reported per (K, rule): diff (governing), measured, control, a coin-block bootstrap CI on the diff,
ORIG17 vs NEW156 for built-in replication, plus P(stop), MAE in R, fee drag and mean hold.
"""
import collections
import glob
import io
import json
import math
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CKPT = os.path.join(HERE, "m1_checkpoints")
BOOT = 4000
rng = np.random.default_rng(20261013)
ORIG17 = {"ARB", "AVAX", "BTC", "DOGE", "ENA", "ETH", "HYPE", "LINK", "NEAR",
          "PUMP", "SOL", "SUI", "UNI", "VVV", "WLD", "XRP", "ZEC"}


def load():
    real, ctrl = collections.defaultdict(dict), collections.defaultdict(dict)
    for p in glob.glob(os.path.join(CKPT, "*.json")):
        try:
            rows = json.load(io.open(p, encoding="utf-8"))
        except ValueError:
            continue
        for r in rows:
            d = ctrl if r.get("synthetic") else real
            d[(r["K"], r["rule"])][r["coin"]] = r
    return real, ctrl


def coin_boot(vals, reps=BOOT):
    v = np.asarray(vals, float)
    v = v[np.isfinite(v)]
    if len(v) < 3:
        return None
    idx = rng.integers(0, len(v), size=(reps, len(v)))
    means = v[idx].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    se = float(means.std(ddof=1))
    return {"mean": float(v.mean()), "lo": float(lo), "hi": float(hi), "se": se,
            "z": float(v.mean() / se) if se > 0 else float("nan"), "n": len(v)}


def main():
    real, ctrl = load()
    if not real:
        raise SystemExit("no checkpoints -- run m1_exit_library.py first")
    Ks = sorted({k for k, _ in real})
    rules = sorted({r for _, r in real}, key=lambda s: (s.split("_")[0], s))
    print("M1 EXIT-POLICY LIBRARY -- coin-clustered diff vs a no-edge control, bps net of fees")
    print("EXPLORATORY. The diff GOVERNS; measured alone would rank geometry, not exits.\n")
    out = []
    for K in Ks:
        rows = []
        for rule in rules:
            rr, cc = real.get((K, rule), {}), ctrl.get((K, rule), {})
            coins = sorted(set(rr) & set(cc))
            if len(coins) < 20:
                continue
            diff = [rr[c]["mean_bps"] - cc[c]["mean_bps"] for c in coins]
            b = coin_boot(diff)
            if b is None:
                continue
            o17 = [rr[c]["mean_bps"] - cc[c]["mean_bps"] for c in coins if c in ORIG17]
            n156 = [rr[c]["mean_bps"] - cc[c]["mean_bps"] for c in coins if c not in ORIG17]
            rows.append({
                "K": K, "rule": rule, "coins": len(coins),
                "diff_bps": b["mean"], "lo": b["lo"], "hi": b["hi"], "z": b["z"],
                "measured_bps": float(np.mean([rr[c]["mean_bps"] for c in coins])),
                "control_bps": float(np.mean([cc[c]["mean_bps"] for c in coins])),
                "pooled_diff": float(np.mean(diff)),
                "orig17": float(np.mean(o17)) if o17 else float("nan"),
                "new156": float(np.mean(n156)) if n156 else float("nan"),
                "p_stop": float(np.mean([rr[c]["p_stop"] for c in coins])),
                "mae_R": float(np.mean([rr[c]["mae_R"] for c in coins])),
                "fee": float(np.mean([rr[c]["fee_bps"] for c in coins])),
                "held": float(np.mean([rr[c]["bars_held"] for c in coins])),
                "r_bps": float(np.mean([rr[c]["r_bps"] for c in coins])),
            })
        rows.sort(key=lambda d: -d["diff_bps"])
        print("=" * 108)
        print("K = %.1f   (1R = %.0f bps on average)" % (K, rows[0]["r_bps"] if rows else 0))
        print("=" * 108)
        print("  %-17s %9s %9s %9s %16s %6s %8s %8s %6s %6s"
              % ("rule", "DIFF", "measured", "no-edge", "CI95", "z", "ORIG17", "NEW156",
                 "pstop", "hold"))
        for d in rows:
            print("  %-17s %+9.1f %+9.1f %+9.1f  [%+6.1f,%+6.1f] %6.2f %+8.1f %+8.1f %6.2f %6.0f"
                  % (d["rule"], d["diff_bps"], d["measured_bps"], d["control_bps"],
                     d["lo"], d["hi"], d["z"], d["orig17"], d["new156"], d["p_stop"], d["held"]))
        out.extend(rows)
    io.open(os.path.join(HERE, "m1_exit_table.json"), "w", encoding="utf-8").write(
        json.dumps(out, indent=1))
    print("\nwrote m1_exit_table.json")
    # best few by diff with a CI excluding zero AND agreeing across the coin split
    good = [d for d in out if d["lo"] > 0 and d["orig17"] > 0 and d["new156"] > 0]
    good.sort(key=lambda d: -d["z"])
    print("\nCANDIDATES (CI excludes zero AND positive on BOTH coin groups) -- top 8 by z:")
    if not good:
        print("  none. No exit rule beats its own no-edge control on this panel.")
    for d in good[:8]:
        print("  K%.1f %-17s diff %+7.1f bps  z %5.2f  ORIG17 %+7.1f  NEW156 %+7.1f"
              % (d["K"], d["rule"], d["diff_bps"], d["z"], d["orig17"], d["new156"]))
    print("\nREMINDER: 1h bars are a coarse referee for tight stops. Nothing at K=1.0 is believable")
    print("until the 5m referee check (72 coins, ~21 days) measures the disagreement rate.")


if __name__ == "__main__":
    main()
