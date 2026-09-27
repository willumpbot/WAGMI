#!/usr/bin/env python
"""
REFUTE-H3: is the liquidation-clustering result anything more than
"volatility is clustered in time"?

WHY THIS EXISTS
---------------
`liq_hypothesis_harness.py` tests H3 against a HOMOGENEOUS-POISSON null: it
compares P(another same-symbol episode within W minutes | one just ended)
against the symbol's average episode rate over the WHOLE 56-day collection
window. Every symbol rejects that null at p=0.0000.

That null was never plausible. Liquidations happen during volatile moments,
and volatility clustering is the most heavily replicated fact in financial
econometrics. Rejecting a flat-rate null therefore tells us almost nothing:
a bursty point process rejects it by construction. The harness is honest
enough to print "NO SIGNIFICANCE CONCLUSION IS DRAWN BY THIS RUN" -- this
script is the test that decides whether there is a conclusion to draw.

WHAT WOULD MAKE H3 REAL
-----------------------
Self-excitation ABOVE ambient burstiness. That is the Hawkes-style question:
given that we are already inside a busy stretch for this symbol, does an
episode SPECIFICALLY raise the odds of another one in the next W minutes,
beyond the locally-elevated ambient rate?

So we replace the flat null with a LOCAL (inhomogeneous-Poisson) null:
estimate each trigger's ambient rate from a +/-H hour neighbourhood with the
test zone itself carved out, and ask whether observed follow-ups still beat
it. Excess here is genuine short-horizon self-excitation. No excess means H3
is a restatement of "volatility clusters" and is not tradeable.

TWO ARTIFACTS THIS ALSO KILLS
-----------------------------
1. PARTIAL-FILL CHOP. The feed cannot resolve accounts (91.9% of episodes are
   single-sided, per the pre-registration's own caveat). One large cascade
   reported as partials spanning more than GAP seconds is split into several
   "independent" episodes minutes apart -- which manufactures exactly the
   clustering H3 reports. We therefore sweep the episode gap; a real effect
   must survive at gap=3600s, where intra-cascade chop is collapsed away.
2. TRIGGER DEPENDENCE. Overlapping trigger windows share follow-ups, which
   understates variance. We re-run on a thinned, non-overlapping trigger set
   (triggers >= 2W apart) as a stricter check.

Read-only. Touches no live state and no locked constant.
"""

from __future__ import annotations

import bisect
import math
import os
import sys
from collections import defaultdict
from datetime import timedelta
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from liq_hypothesis_harness import (  # noqa: E402
    DEFAULT_GAP_SEC,
    SIGNIFICANCE_N,
    build_episodes,
    load_events,
    prepare_events,
    _normal_cdf,
)

GAP_SWEEP = [300, 900, 1800, 3600]     # 300 = the locked pre-registered default
WINDOWS = [15, 60]                     # minutes, as pre-registered
AMBIENT_HOURS = [2.0, 6.0, 24.0]       # local-rate neighbourhood half-widths


def _two_sided_p_from_z(z: float) -> float:
    return 2.0 * (1.0 - _normal_cdf(abs(z)))


def local_null_test(
    episodes: List[dict],
    window_min: int,
    ambient_h: float,
    thin: bool = False,
) -> Dict[str, dict]:
    """Per-symbol: observed follow-up count vs a LOCAL-rate expectation.

    For each trigger episode ending at t, ambient rate is estimated from
    same-symbol episodes starting in [t - H, t + H], with the test zone
    (t, t + W] and the trigger itself excluded from both numerator and
    denominator. Expected hits = sum(p_i); variance = sum(p_i(1-p_i))
    (Poisson-binomial). Never reports a p-value below SIGNIFICANCE_N
    triggers, mirroring the harness's discipline.
    """
    by_symbol: Dict[str, List[dict]] = defaultdict(list)
    for ep in episodes:
        by_symbol[ep["symbol"]].append(ep)

    W = float(window_min) * 60.0          # seconds
    H = float(ambient_h) * 3600.0         # seconds
    out: Dict[str, dict] = {}

    for symbol, eps in by_symbol.items():
        eps = sorted(eps, key=lambda e: e["start"])
        if len(eps) < 2:
            continue
        # work in epoch seconds so the hot loops can use bisect
        starts = [e["start"].timestamp() for e in eps]
        ends = [e["end"].timestamp() for e in eps]
        span_start, span_end = starts[0], starts[-1]

        # trigger indices (self-exclusion is by INDEX, never by timestamp
        # equality -- two episodes can share a start second)
        trig_idx: List[int] = []
        last_used_end = None
        for i, e_end in enumerate(ends):
            # need a full W of observable future inside the collection span
            if e_end + W > span_end:
                continue
            if thin and last_used_end is not None and e_end - last_used_end < 2 * W:
                continue
            trig_idx.append(i)
            last_used_end = e_end

        hits = 0
        exp_sum = 0.0
        var_sum = 0.0
        n_used = 0
        for i in trig_idx:
            t = ends[i]
            zone_hi = t + W
            # observed follow-up: any OTHER episode starting in (t, t+W]
            lo_z = bisect.bisect_right(starts, t)
            hi_z = bisect.bisect_right(starts, zone_hi)
            zone_n = hi_z - lo_z
            if lo_z <= i < hi_z:
                zone_n -= 1          # don't count the trigger itself
            hit = zone_n > 0

            # ambient: +/-H neighbourhood, clipped to the span, test zone carved out
            lo = max(t - H, span_start)
            hi = min(t + H, span_end)
            amb_minutes = (hi - lo) / 60.0 - window_min
            if amb_minutes <= 0:
                continue
            lo_a = bisect.bisect_left(starts, lo)
            hi_a = bisect.bisect_right(starts, hi)
            amb_count = (hi_a - lo_a) - zone_n
            if lo_a <= i < hi_a and not (lo_z <= i < hi_z):
                amb_count -= 1       # trigger sits in the neighbourhood, not the zone
            if amb_count < 0:
                amb_count = 0
            lam = amb_count / amb_minutes
            p_i = 1.0 - math.exp(-lam * window_min)
            if not (0.0 < p_i < 1.0):
                continue
            hits += int(hit)
            exp_sum += p_i
            var_sum += p_i * (1.0 - p_i)
            n_used += 1

        z: Optional[float] = None
        p: Optional[float] = None
        if n_used >= SIGNIFICANCE_N and var_sum > 0:
            z = (hits - exp_sum) / math.sqrt(var_sum)
            p = _two_sided_p_from_z(z)

        out[symbol] = {
            "n_triggers": n_used,
            "hits": hits,
            "emp_rate": (hits / n_used) if n_used else float("nan"),
            "exp_rate": (exp_sum / n_used) if n_used else float("nan"),
            "z": z,
            "p_value": p,
        }
    return out


def chop_diagnostic(episodes: List[dict], gap_sec: int) -> str:
    """If episodes are really one cascade split by the gap rule, inter-episode
    gaps pile up JUST above the threshold. A near-threshold spike is the
    signature of chop, not of independent events."""
    by_symbol: Dict[str, List[dict]] = defaultdict(list)
    for ep in episodes:
        by_symbol[ep["symbol"]].append(ep)
    buckets = defaultdict(int)
    total = 0
    for _, eps in by_symbol.items():
        eps = sorted(eps, key=lambda e: e["start"])
        for a, b in zip(eps, eps[1:]):
            d = (b["start"] - a["end"]).total_seconds()
            if d < 0:
                continue
            total += 1
            if d <= gap_sec * 2:
                buckets["<=2x gap"] += 1
            elif d <= gap_sec * 6:
                buckets["2-6x gap"] += 1
            elif d <= 3600:
                buckets["<=1h"] += 1
            elif d <= 86400:
                buckets["<=1d"] += 1
            else:
                buckets[">1d"] += 1
    if not total:
        return "    (no gaps)"
    order = ["<=2x gap", "2-6x gap", "<=1h", "<=1d", ">1d"]
    return "    " + "  ".join(
        f"{k}={100.0 * buckets[k] / total:.1f}%" for k in order if k in buckets
    )


def main() -> None:
    path = os.path.join("data", "copilot", "liquidations", "liq_events.jsonl")
    events = prepare_events(load_events(path))
    print("=" * 78)
    print("REFUTE-H3 -- does liquidation clustering survive a LOCAL-RATE null?")
    print("=" * 78)
    print("usable events: %d" % len(events))
    print(
        "\nThe pre-registered H3 rejects a FLAT (homogeneous-Poisson) null at "
        "p=0.0000\nfor every symbol. A bursty process does that by construction. "
        "Below, the\nnull is the LOCAL ambient rate instead -- excess over it is "
        "real\nself-excitation; no excess means H3 restates 'volatility clusters'."
    )

    for gap in GAP_SWEEP:
        eps = build_episodes(events, gap_sec=gap, key="symbol")
        tag = " (LOCKED pre-registered default)" if gap == DEFAULT_GAP_SEC else ""
        print("\n" + "=" * 78)
        print("GAP = %ds%s   episodes=%d" % (gap, tag, len(eps)))
        print("=" * 78)
        print("  inter-episode gap distribution (chop check):")
        print(chop_diagnostic(eps, gap))
        for W in WINDOWS:
            # A follow-up test is only meaningful when the window EXCEEDS the
            # episode gap. At W <= gap the episode rule itself forbids a
            # same-symbol follow-up inside the window, so the empirical rate is
            # identically 0% -- arithmetic, not evidence. Skip loudly rather
            # than print a row that reads like a refutation.
            if W * 60 <= gap:
                print("\n  W=%dm  -> SKIPPED: W <= gap (%ds). Two same-symbol "
                      "episodes cannot be\n     closer than the gap, so this "
                      "cell is 0%% by construction and carries\n     no "
                      "information about clustering." % (W, gap))
                continue
            for H in AMBIENT_HOURS:
                res = local_null_test(eps, W, H)
                rows = [
                    (s, r)
                    for s, r in res.items()
                    if r["n_triggers"] >= SIGNIFICANCE_N and r["p_value"] is not None
                ]
                if not rows:
                    print("\n  W=%dm  ambient=+/-%sh  -> no symbol clears n>=%d triggers"
                          % (W, H, SIGNIFICANCE_N))
                    continue
                rows.sort(key=lambda kv: -kv[1]["n_triggers"])
                sig_up = sum(
                    1 for _, r in rows if r["p_value"] < 0.05 and r["z"] and r["z"] > 0
                )
                sig_dn = sum(
                    1 for _, r in rows if r["p_value"] < 0.05 and r["z"] and r["z"] < 0
                )
                print("\n  W=%dm  ambient=+/-%sh   [%d/%d symbols SIG-ABOVE local null, "
                      "%d SIG-BELOW]" % (W, H, sig_up, len(rows), sig_dn))
                for s, r in rows:
                    if r["p_value"] < 0.05 and r["z"] > 0:
                        verdict = "EXCESS (p<0.05)"
                    elif r["p_value"] < 0.05:
                        verdict = "BELOW local null (p<0.05)"
                    else:
                        verdict = "n.s. -- no excess over ambient"
                    print(
                        "    %-10s n=%-5d emp=%5.1f%%  local_null=%5.1f%%  "
                        "z=%+6.2f  p=%.4f  %s"
                        % (s, r["n_triggers"], r["emp_rate"] * 100,
                           r["exp_rate"] * 100, r["z"], r["p_value"], verdict)
                    )

    # stricter: thinned, non-overlapping triggers at the locked gap
    print("\n" + "=" * 78)
    print("STRICTER -- thinned NON-OVERLAPPING triggers (>=2W apart), locked gap")
    print("=" * 78)
    eps = build_episodes(events, gap_sec=DEFAULT_GAP_SEC, key="symbol")
    for W in WINDOWS:
        res = local_null_test(eps, W, 6.0, thin=True)
        rows = [(s, r) for s, r in res.items()
                if r["n_triggers"] >= SIGNIFICANCE_N and r["p_value"] is not None]
        rows.sort(key=lambda kv: -kv[1]["n_triggers"])
        sig_up = sum(1 for _, r in rows if r["p_value"] < 0.05 and r["z"] > 0)
        print("\n  W=%dm  ambient=+/-6h  thinned   [%d/%d SIG-ABOVE local null]"
              % (W, sig_up, len(rows)))
        for s, r in rows:
            print("    %-10s n=%-5d emp=%5.1f%%  local_null=%5.1f%%  z=%+6.2f  p=%.4f"
                  % (s, r["n_triggers"], r["emp_rate"] * 100, r["exp_rate"] * 100,
                     r["z"], r["p_value"]))

    print("\n" + "=" * 78)
    print("CAVEAT: overlapping trigger windows share follow-ups, so the "
          "un-thinned\nvariance is optimistic -- the thinned block is the one "
          "to trust. This\nscript asserts no verdict; it reports whether the "
          "excess survives.")
    print("=" * 78)


if __name__ == "__main__":
    main()
