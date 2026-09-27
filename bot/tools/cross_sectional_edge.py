#!/usr/bin/env python
"""Cross-sectional edge scorer — makes the regime-confounded skip pool usable.

THE PROBLEM
  data/missed_trades_resolved.jsonl holds 765 resolved counterfactuals: setups
  the bot flagged and then skipped, scored against what price actually did. It
  is 3.5x the size of the real trade ledger and no learning input reads it.

  It cannot be read naively. Over its window (2026-07-15 -> 2026-09-14) BTC ran
  64,493 -> 77,317 and 97% of all rows had price UP 8h later, so raw outcomes
  say BUY wins 100% of days and SELL loses 100% of days. That is not edge, it is
  beta. n=765 observations of ONE regime is closer to n=1. Feeding it to a gate
  teaches "always buy" — the exact lesson that cost -$796 on longs when the
  regime turned.

THE FIX: MEASURE AGAINST THE FIELD, NOT AGAINST ZERO
  At any instant the scanner looks at every symbol at once. So ask a question the
  rally cannot answer for us:

      Of the symbols available RIGHT NOW, did the one the bot picked, in the
      direction it picked, beat the average symbol over the same window?

  Formally, for each time bucket t with k>=MIN_SYMBOLS symbols observed:
      move[s]    = (price_after_H[s] - entry[s]) / entry[s]      (raw, unsigned)
      field[t]   = mean over symbols in bucket t of move[s]      (the common factor)
      excess[s]  = move[s] - field[t]                            (beta removed)
      score[s]   = (+1 if BUY else -1) * excess[s]

  The market factor is subtracted by construction, so a 20% rally contributes
  nothing. A positive mean score means genuine symbol/direction selection skill.
  A zero mean means the calls carry no cross-sectional information — which is a
  real, publishable-to-yourself finding, not a failure.

STATISTICS
  Rows inside one time bucket share a market draw, so the naive t-stat overstates
  significance. We report a bucket-CLUSTERED t-stat (each bucket contributes one
  mean) alongside it, and treat the clustered one as the honest number.

Read-only. Touches no trading path. Run:
    python bot/tools/cross_sectional_edge.py [--horizon 8h] [--min-symbols 3]
"""
import os
import sys
import json
import math
import argparse
import datetime
from collections import defaultdict

BOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BOT, "data", "missed_trades_resolved.jsonl")

HORIZON_FIELD = {"1h": "price_after_1h", "4h": "price_after_4h", "8h": "price_after_8h"}


def _load():
    rows = []
    try:
        with open(SRC, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        continue
    except OSError:
        return []
    return rows


def _bucket(ts_raw, minutes):
    """Floor a timestamp to a bucket so simultaneous scans group together."""
    try:
        t = datetime.datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    epoch = t.timestamp()
    return int(epoch // (minutes * 60))


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _tstat(xs):
    """One-sample t against 0. Returns (mean, t, n)."""
    n = len(xs)
    if n < 2:
        return (_mean(xs), 0.0, n)
    m = _mean(xs)
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    se = math.sqrt(var / n)
    return (m, (m / se) if se > 0 else 0.0, n)


def build_scores(rows, horizon, bucket_minutes, min_symbols):
    """Return (per_row_scores, per_bucket_means, diagnostics)."""
    field = HORIZON_FIELD[horizon]
    buckets = defaultdict(list)
    for r in rows:
        px_after = r.get(field)
        entry = r.get("entry_price")
        sym = r.get("symbol")
        side = str(r.get("side") or "").upper()
        b = _bucket(r.get("timestamp"), bucket_minutes)
        if px_after is None or not entry or not sym or b is None:
            continue
        if side not in ("BUY", "SELL", "LONG", "SHORT"):
            continue
        try:
            move = (float(px_after) - float(entry)) / float(entry)
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        buckets[b].append({"sym": sym, "side": side, "move": move, "row": r})

    scores, bucket_means = [], []
    used_buckets = dropped_buckets = 0
    for b, items in buckets.items():
        if len({i["sym"] for i in items}) < min_symbols:
            dropped_buckets += 1
            continue
        used_buckets += 1
        # The field: one observation per SYMBOL so a symbol logged twice in the
        # same bucket cannot tilt the benchmark it is being measured against.
        per_sym = defaultdict(list)
        for i in items:
            per_sym[i["sym"]].append(i["move"])
        field_mean = _mean([_mean(v) for v in per_sym.values()])
        this_bucket = []
        for i in items:
            direction = 1.0 if i["side"] in ("BUY", "LONG") else -1.0
            score = direction * (i["move"] - field_mean)
            rec = {"score": score, "bucket": b, "sym": i["sym"],
                   "side": i["side"], "row": i["row"]}
            scores.append(rec)
            this_bucket.append(score)
        bucket_means.append(_mean(this_bucket))

    return scores, bucket_means, {"used_buckets": used_buckets,
                                  "dropped_buckets": dropped_buckets}


def _report_slice(label, vals):
    m, t, n = _tstat(vals)
    hit = sum(1 for v in vals if v > 0) / n * 100 if n else 0.0
    print(f"   {label:>22}  n={n:>4}  mean={m*100:+6.3f}%  hit={hit:5.1f}%  t={t:+5.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", choices=sorted(HORIZON_FIELD), default="8h")
    ap.add_argument("--bucket-minutes", type=int, default=60)
    ap.add_argument("--min-symbols", type=int, default=3)
    args = ap.parse_args()

    rows = _load()
    if not rows:
        print(f"no rows at {SRC}")
        return 1

    scores, bucket_means, diag = build_scores(
        rows, args.horizon, args.bucket_minutes, args.min_symbols)
    if not scores:
        print("no scorable rows (need >= %d distinct symbols per bucket)" % args.min_symbols)
        return 1

    vals = [s["score"] for s in scores]
    m, t_naive, n = _tstat(vals)
    mb, t_clustered, nb = _tstat(bucket_means)

    print(f"CROSS-SECTIONAL EDGE  horizon={args.horizon}  "
          f"bucket={args.bucket_minutes}m  min_symbols={args.min_symbols}")
    print(f"source: {len(rows)} resolved rows -> {n} scorable in "
          f"{diag['used_buckets']} buckets ({diag['dropped_buckets']} too thin)")
    print()
    print("THE NUMBER (market factor removed):")
    print(f"   mean excess per call : {m*100:+.3f}%")
    print(f"   naive t              : {t_naive:+.2f}  (overstated - rows share buckets)")
    print(f"   CLUSTERED t          : {t_clustered:+.2f}  over {nb} independent buckets  <-- honest")
    print(f"   hit rate             : {sum(1 for v in vals if v>0)/n*100:.1f}%  (50% = no skill)")
    print()

    print("BY SIDE:")
    for side_set, label in ((("BUY", "LONG"), "long calls"), (("SELL", "SHORT"), "short calls")):
        _report_slice(label, [s["score"] for s in scores if s["side"] in side_set])
    print()

    print("BY CONFLUENCE (num_agree):")
    by_agree = defaultdict(list)
    for s in scores:
        by_agree[s["row"].get("num_agree")].append(s["score"])
    for k in sorted(by_agree, key=lambda x: (x is None, x)):
        _report_slice(f"num_agree={k}", by_agree[k])
    print()

    print("BY SYMBOL:")
    by_sym = defaultdict(list)
    for s in scores:
        by_sym[s["sym"]].append(s["score"])
    for k in sorted(by_sym, key=lambda x: -len(by_sym[x])):
        _report_slice(k, by_sym[k])
    print()

    verdict = ("SKILL" if abs(t_clustered) >= 2.0 and mb > 0 else
               "ANTI-SKILL" if abs(t_clustered) >= 2.0 and mb < 0 else
               "NO DETECTABLE EDGE")
    print(f"VERDICT: {verdict}")
    if verdict == "NO DETECTABLE EDGE":
        print("  The calls carry no cross-sectional information at this horizon.")
        print("  That is a finding, not a bug: it says the skip pool cannot be")
        print("  mined for entry alpha, and the ledger stays the only evidence.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
