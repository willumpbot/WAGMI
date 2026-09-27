#!/usr/bin/env python
"""
WAGMI Co-Pilot LIQUIDATION HYPOTHESIS HARNESS -- liq_hypothesis_harness.py
=============================================================================
PRE-REGISTRATION METHOD LOCK for H3 (liquidation clustering) and H5
(liquidation session-timing) -- see data/copilot/PREREGISTRATION.md.

WHY THIS EXISTS, AND WHY NOW: H3/H5 are pre-registered in PREREGISTRATION.md
to be tested once enough data accrues. This script is written BEFORE that
data is mature so the METHOD is locked in before any result exists -- if the
method were designed after looking at a "promising" cut of the data, any
finding would be an overfit-by-construction, exactly the failure mode this
whole pre-registration ledger (H1-H5) exists to prevent. Running this
script's default (real-data) mode is safe at ANY maturity level because the
gating below makes it structurally incapable of printing a significance
claim before n>=30 independent episodes exist per bucket -- see "STRICT
GATING".

THE PSEUDOREPLICATION LESSON (the reason this file exists as a dedicated
harness and not a one-off script) -- found repeatedly this session: the
Bybit liquidation feed (data/copilot/liquidations/liq_events.jsonl, written
by liq_collector.py) re-logs CORRELATED events. A single large position's
force-liquidation is routinely executed by the exchange as several PARTIAL
FILLS in quick succession, each landing as its own row in the jsonl (the
FARTCOIN caveat in PREREGISTRATION.md: the feed carries no account/order ID,
only individual fill events, so this can never be distinguished after the
fact from several distinct traders being liquidated together). Treating raw
event count as N therefore MASSIVELY overstates independent sample size and
would make any p-value fabricated. The fix, implemented below, is to COLLAPSE
events into independent EPISODES before any statistics are computed:
same-symbol events within a short gap (EPISODE_GAP_SEC, a documented,
tunable parameter) collapse into ONE episode. All gating, all N, and all
reported buckets in this file are in EPISODE units -- raw event counts are
shown only as a diagnostic (collapse ratio), never as a sample size.

CAVEATS carried over verbatim from PREREGISTRATION.md's H3/H5 sections
(reprinted here so this file is self-contained):
  - "a 'cluster' may be one position, not many" -- the feed has no account ID.
    An episode with events all on the SAME side is consistent with either
    (a) one position's partial fills, or (b) several same-side accounts
    liquidated together -- indistinguishable from this feed. An episode with
    events split across BOTH sides (a "mixed_side" episode below) CANNOT be
    one position (a position isn't simultaneously long- and short-
    liquidated), so mixed-side episodes are the only ones this data can
    positively attribute to more than one distinct liquidation. Both counts
    are reported; every finding is read as "liquidation-PRESSURE clustering",
    never as a cross-account cascade claim.
  - H3's success bar (PREREGISTRATION.md): n>=30 per bucket before ANY
    significance readout; below that, "n=X, not yet significant" only.
  - H5's success bar: n>=30 events, a session's share of episodes must beat
    its share of clock-hours by a BOOTSTRAP-significant margin, and the
    comparison point is session_vol_test.py's OHLC-derived finding (US
    session 13-21 UTC, peak ~14-15 UTC, era-stable, 26/27 coins) -- the
    liq-timing read is compared against that, never used to override it.

STRICT GATING (non-negotiable, mirrors resolve_calls.py's SIGNIFICANCE_N
discipline -- see that file's `print_summary()`): every bucket requires
n>=30 INDEPENDENT EPISODES before a p-value/CI/significance verdict is
computed. Below that bar the ONLY thing ever printed for that bucket is
"n=X episodes, UNDERPOWERED - descriptive only, not yet significant". This
is enforced in the COMPUTATION layer (compute_h3/compute_h5 leave
z/p_value/bootstrap fields as None below the bar), not just in printing, so
there is no code path that can accidentally surface a number below n=30.

ADDITIONAL YOUNG-SAMPLE GUARD (beyond the n>=30 mandate, disclosed): a
bucket can numerically clear n>=30 while the ENTIRE collection window is
still very short (a burst of correlated liquidations across a single
volatile week can produce >=30 episodes in days, not the 60-90 days
PREREGISTRATION.md anticipated) -- that is 30 draws from one slice of market
conditions, not 30 draws spread across varied regimes. Any bucket that
clears n>=30 while the total collection span is under MIN_SPAN_DAYS_FOR_TRUST
is still printed with its numbers (the n>=30 gate is not re-litigated) but is
tagged "[YOUNG-SAMPLE, PROVISIONAL]" and must not be read as a resolved
answer. This guard can only ADD caution, never suppress the n>=30 mechanism
or lower the bar.

REFUTE-YOURSELF HOOKS baked in (see main()):
  1. Episode-gap sensitivity sweep -- rebuilds episodes at several gap
     thresholds and shows whether headline counts / rankings move.
  2. Single-symbol-dominance check -- flags when one symbol is carrying most
     of the pooled episode count (a "clustering" or "session" finding that's
     really just BTC or SOL dominating is not a general finding).
  3. Mixed-side vs single-side episode breakdown -- the explicit partial-
     fill/no-account-ID caveat, computed and printed every run, not just
     asserted in prose.

READ-ONLY / STANDALONE: only reads data/copilot/liquidations/liq_events.jsonl.
No imports of llm/, execution/, core/, strategies/. No Discord. No network
calls. Writes nothing (--selftest and the default real-data mode both only
print to stdout).

CLI:
    python tools/copilot/liq_hypothesis_harness.py                # real-data maturity readout (no conclusions drawn)
    python tools/copilot/liq_hypothesis_harness.py --gap-sec 900  # override the episode-dedup gap threshold
    python tools/copilot/liq_hypothesis_harness.py --selftest     # synthetic method-verification suite
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))
DEFAULT_PATH = os.path.join(BOT_DIR, "data", "copilot", "liquidations", "liq_events.jsonl")

# ---------------------------------------------------------------------------
# LOCKED METHOD PARAMETERS -- this is the pre-registration. Changing any of
# these after looking at a real-data result is exactly the p-hacking this
# file exists to prevent. If a change is ever truly warranted, date-stamp it
# here AND in PREREGISTRATION.md, same discipline as resolve_calls.py's
# "FORWARD-EVIDENCE ANCHOR FIX" notes.
# ---------------------------------------------------------------------------
DEFAULT_GAP_SEC = 300              # episode-dedup gap: same-symbol events within this many seconds collapse to ONE episode (5 min)
SIGNIFICANCE_N = 30                # min INDEPENDENT EPISODES per bucket before ANY p-value/CI is computed (mirrors resolve_calls.py)
MIN_SPAN_DAYS_FOR_TRUST = 14       # even at n>=30, tag results YOUNG-SAMPLE if the whole collection window is shorter than this
H3_WINDOWS_MIN: Tuple[int, ...] = (15, 60)   # forward windows tested for "does an episode raise P(another episode)"
GAP_SENSITIVITY_SEC: Tuple[int, ...] = (60, 300, 900, 1800, 3600)  # refute-yourself sweep (1/5/15/30/60 min)
BOOTSTRAP_ITERS = 2000
BOOTSTRAP_SEED = 1337              # fixed seed -> reproducible bootstrap CIs, never re-rolled to chase a result
SINGLE_SYMBOL_DOMINANCE_WARN = 0.50  # flag if one symbol carries more than this share of pooled episodes

# Identical (deliberately) to session_vol_test.py's SESSIONS -- overlapping,
# trading-desk-style windows, NOT a mutually exclusive partition of the day.
SESSIONS: Dict[str, set] = {
    "Asia (00-08 UTC)": set(range(0, 8)),
    "EU (07-15 UTC)": set(range(7, 15)),
    "US (13-21 UTC)": set(range(13, 21)),
    "Off (21-00 UTC)": set(range(21, 24)) | {0},
}
# The OHLC-derived comparison point H5 is tested against (session_vol_test.py,
# era-stable, 26/27 coins) -- reprinted here, NOT recomputed by this file.
OHLC_PEAK_SESSION = "US (13-21 UTC)"
OHLC_PEAK_HOURS: Tuple[int, ...] = (14, 15)


# ---------------------------------------------------------------------------
# Loading (mirrors liq_summary.py's loader style -- standalone, read-only)
# ---------------------------------------------------------------------------

def load_events(path: str) -> List[dict]:
    rows: List[dict] = []
    if not os.path.exists(path):
        return rows
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _parse_dt(ts: str) -> Optional[datetime]:
    if not ts or not isinstance(ts, str):
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def prepare_events(raw_rows: List[dict]) -> List[dict]:
    """Parses timestamps and drops rows missing symbol/side/ts_utc. Returns
    rows sorted by time, each carrying a 'dt' datetime field alongside the
    original fields. Never raises on malformed input -- a bad row is
    silently skipped (same fail-soft posture as liq_summary.py)."""
    out = []
    for r in raw_rows:
        dt = _parse_dt(r.get("ts_utc"))
        if dt is None or not r.get("symbol") or not r.get("side"):
            continue
        row = dict(r)
        row["dt"] = dt
        out.append(row)
    out.sort(key=lambda r: r["dt"])
    return out


# ---------------------------------------------------------------------------
# EPISODE construction -- THE pseudoreplication fix. Primary/conservative key
# is "symbol" (matches PREREGISTRATION.md's cluster definition verbatim:
# "same symbol, within N min"). "symbol_side" is a SECONDARY sensitivity view
# only (see module docstring) -- never used as the official gating N.
# ---------------------------------------------------------------------------

def _finalize_episode(evs: List[dict]) -> dict:
    sides = sorted(set(e.get("side") for e in evs if e.get("side")))
    return {
        "symbol": evs[0]["symbol"],
        "sides": sides,
        "mixed_side": len(sides) > 1,
        "start": evs[0]["dt"],
        "end": evs[-1]["dt"],
        "n_events": len(evs),
        "notional_usd": sum(e.get("notional_usd") or 0.0 for e in evs),
        "venues": sorted(set(e.get("venue", "unknown") for e in evs)),
    }


def build_episodes(events: List[dict], gap_sec: int, key: str = "symbol") -> List[dict]:
    """Collapses `events` into independent episodes. `key`="symbol" is the
    PRIMARY/conservative grouping (matches the pre-registered cluster
    definition); "symbol_side" is a secondary, less-conservative sensitivity
    view that additionally splits by side (a single position's partial fills
    are always same-side, so this view over-splits genuine partial-fill
    bursts that happen to overlap with an opposite-side liquidation in the
    same window -- reported only as a diagnostic range, never as the
    official N). Returns episodes sorted by start time."""
    groups: Dict[object, List[dict]] = defaultdict(list)
    for e in events:
        k = e["symbol"] if key == "symbol" else (e["symbol"], e["side"])
        groups[k].append(e)

    episodes: List[dict] = []
    for _, evs in groups.items():
        evs = sorted(evs, key=lambda e: e["dt"])
        cur: List[dict] = []
        for e in evs:
            if cur and (e["dt"] - cur[-1]["dt"]).total_seconds() > gap_sec:
                episodes.append(_finalize_episode(cur))
                cur = []
            cur.append(e)
        if cur:
            episodes.append(_finalize_episode(cur))

    episodes.sort(key=lambda ep: ep["start"])
    return episodes


def episode_dedup_report(events: List[dict], gap_sec: int) -> dict:
    """Diagnostic stats about the event->episode collapse: collapse ratio,
    per-symbol episode counts, mixed-side fraction (the only positive
    multi-account signal this feed can give -- see module docstring), and
    the conservative-vs-side-aware episode-count band."""
    episodes = build_episodes(events, gap_sec, key="symbol")
    episodes_side = build_episodes(events, gap_sec, key="symbol_side")
    per_symbol = Counter(ep["symbol"] for ep in episodes)
    n_mixed = sum(1 for ep in episodes if ep["mixed_side"])
    top_symbol, top_n = (per_symbol.most_common(1)[0] if per_symbol else (None, 0))
    total_eps = len(episodes)
    dominance_frac = (top_n / total_eps) if total_eps else float("nan")
    return {
        "n_events": len(events),
        "n_episodes_conservative": total_eps,
        "n_episodes_side_aware": len(episodes_side),
        "collapse_ratio": (len(events) / total_eps) if total_eps else float("nan"),
        "per_symbol_episodes": per_symbol,
        "n_mixed_side_episodes": n_mixed,
        "mixed_side_frac": (n_mixed / total_eps) if total_eps else float("nan"),
        "top_symbol": top_symbol,
        "top_symbol_n": top_n,
        "top_symbol_dominance_frac": dominance_frac,
        "dominance_flag": dominance_frac >= SINGLE_SYMBOL_DOMINANCE_WARN if total_eps else False,
        "episodes": episodes,
    }


# ---------------------------------------------------------------------------
# Normal-approximation helpers (no scipy dependency, same posture as
# resolve_calls.py's _normal_cdf/_welch_p_value -- an early-warning number,
# never a publication-grade test).
# ---------------------------------------------------------------------------

def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _one_sample_proportion_p(phat: float, p0: float, n: int) -> Optional[float]:
    """Two-sided p-value for H0: true rate == p0, via normal approximation
    to the binomial (valid once n is reasonably large -- this is only ever
    invoked at n>=SIGNIFICANCE_N by the caller). Returns None on a
    degenerate null (p0 in {0,1})."""
    if n <= 0 or not (0.0 < p0 < 1.0):
        return None
    se = math.sqrt(p0 * (1.0 - p0) / n)
    if se <= 0:
        return None
    z = (phat - p0) / se
    return 2.0 * (1.0 - _normal_cdf(abs(z)))


# ---------------------------------------------------------------------------
# H3 -- CLUSTERING: does an episode raise P(another same-symbol episode)
# within the next W minutes, vs. the unconditional (homogeneous-Poisson)
# base rate over the same collection window?
# ---------------------------------------------------------------------------

def compute_h3(
    episodes: List[dict],
    global_start: datetime,
    global_end: datetime,
    window_min: int,
) -> Dict[str, dict]:
    """Per-symbol clustering test. NEVER pools across symbols (base
    liquidation rates differ by orders of magnitude between e.g. BTC and a
    thin meme -- pooling would conflate them, exactly the kind of averaging
    artifact this harness exists to avoid). z/p_value are left None whenever
    n_eligible < SIGNIFICANCE_N -- this is enforced HERE, in the computation,
    not only in the printer, so no downstream code path can surface a number
    below the bar."""
    total_minutes = (global_end - global_start).total_seconds() / 60.0
    by_symbol: Dict[str, List[dict]] = defaultdict(list)
    for ep in episodes:
        by_symbol[ep["symbol"]].append(ep)

    cutoff = global_end - timedelta(minutes=window_min)
    results: Dict[str, dict] = {}
    for symbol, eps in by_symbol.items():
        eps_sorted = sorted(eps, key=lambda e: e["start"])
        n_total_symbol = len(eps_sorted)
        # Homogeneous-Poisson null rate: episodes/minute over the WHOLE
        # collection window (the collector observes every symbol
        # continuously, so "no data this window" is a valid zero-rate
        # observation, not missing data).
        lam_per_min = (n_total_symbol / total_minutes) if total_minutes > 0 else 0.0
        null_p = 1.0 - math.exp(-lam_per_min * window_min)

        eligible = [e for e in eps_sorted if e["end"] <= cutoff]
        n_elig = len(eligible)
        hits = 0
        for e in eligible:
            window_end = e["end"] + timedelta(minutes=window_min)
            has_followup = any(
                (other is not e) and (e["end"] < other["start"] <= window_end)
                for other in eps_sorted
            )
            hits += int(has_followup)
        emp_rate = (hits / n_elig) if n_elig else float("nan")

        z = None
        p_value = None
        if n_elig >= SIGNIFICANCE_N:
            p_value = _one_sample_proportion_p(emp_rate, null_p, n_elig)
            if p_value is not None:
                se = math.sqrt(null_p * (1.0 - null_p) / n_elig)
                z = (emp_rate - null_p) / se if se > 0 else None

        results[symbol] = {
            "n_total_episodes": n_total_symbol,
            "n_eligible": n_elig,
            "hits": hits,
            "empirical_rate": emp_rate,
            "null_rate_poisson": null_p,
            "lam_per_min": lam_per_min,
            "z": z,
            "p_value": p_value,
        }
    return results


def fmt_h3_line(symbol: str, window_min: int, r: dict, young: bool) -> str:
    n = r["n_eligible"]
    if n < SIGNIFICANCE_N:
        return (
            f"    {symbol:<10s} W={window_min:>2d}m  n={n:<4d} episodes  "
            f"UNDERPOWERED - descriptive only, not yet significant (need n>={SIGNIFICANCE_N})"
        )
    p = r["p_value"]
    p_bit = f"p={p:.4f}" if p is not None else "p unavailable (degenerate null)"
    sig = "p<0.05" if (p is not None and p < 0.05) else "n.s."
    young_bit = "  [YOUNG-SAMPLE, PROVISIONAL]" if young else ""
    return (
        f"    {symbol:<10s} W={window_min:>2d}m  n={n:<4d}  "
        f"empirical={r['empirical_rate'] * 100:5.1f}%  null(Poisson)={r['null_rate_poisson'] * 100:5.1f}%  "
        f"{p_bit} ({sig}){young_bit}"
    )


# ---------------------------------------------------------------------------
# H5 -- SESSION TIMING: do episodes cluster by UTC hour/session, beyond what
# each session's share of clock-hours would predict, bootstrap-significant?
# ---------------------------------------------------------------------------

def compute_h5(
    episodes: List[dict],
    rng: random.Random,
    bootstrap_iters: int = BOOTSTRAP_ITERS,
) -> Tuple[Counter, Dict[str, dict], int]:
    """Returns (hour_counts, per-session results, n_total_episodes). Bootstrap
    resampling is done at the EPISODE level (never the raw-event level) --
    resampling raw events would silently reintroduce the exact
    pseudoreplication this file exists to remove. Session bootstrap fields
    are left None whenever that session's own n < SIGNIFICANCE_N."""
    n_total = len(episodes)
    hour_counts = Counter(ep["start"].hour for ep in episodes)

    session_counts: Dict[str, int] = {name: 0 for name in SESSIONS}
    for ep in episodes:
        h = ep["start"].hour
        for name, hours in SESSIONS.items():
            if h in hours:
                session_counts[name] += 1

    results: Dict[str, dict] = {}
    for name, hours in SESSIONS.items():
        clock_share = len(hours) / 24.0
        n_sess = session_counts[name]
        obs_share = (n_sess / n_total) if n_total else float("nan")

        ci_lo = ci_hi = None
        bootstrap_significant = None
        if n_total >= SIGNIFICANCE_N and n_sess >= SIGNIFICANCE_N:
            boot_shares = []
            for _ in range(bootstrap_iters):
                cnt = 0
                for _i in range(n_total):
                    ep = episodes[rng.randrange(n_total)]
                    if ep["start"].hour in hours:
                        cnt += 1
                boot_shares.append(cnt / n_total)
            boot_shares.sort()
            lo_idx = int(0.025 * len(boot_shares))
            hi_idx = min(int(0.975 * len(boot_shares)), len(boot_shares) - 1)
            ci_lo, ci_hi = boot_shares[lo_idx], boot_shares[hi_idx]
            bootstrap_significant = clock_share < ci_lo

        results[name] = {
            "n": n_sess,
            "obs_share": obs_share,
            "clock_share": clock_share,
            "ci_lo": ci_lo,
            "ci_hi": ci_hi,
            "bootstrap_significant": bootstrap_significant,
        }
    return hour_counts, results, n_total


def fmt_h5_session_line(name: str, r: dict, young: bool) -> str:
    n = r["n"]
    if n < SIGNIFICANCE_N:
        return (
            f"    {name:<18s} n={n:<4d} episodes  "
            f"UNDERPOWERED - descriptive only, not yet significant (need n>={SIGNIFICANCE_N})"
        )
    verdict = "SIG (exceeds clock-hour share)" if r["bootstrap_significant"] else "n.s."
    young_bit = "  [YOUNG-SAMPLE, PROVISIONAL]" if young else ""
    return (
        f"    {name:<18s} n={n:<4d}  obs_share={r['obs_share'] * 100:5.1f}%  "
        f"clock_share={r['clock_share'] * 100:5.1f}%  "
        f"boot_CI=[{r['ci_lo'] * 100:.1f}%,{r['ci_hi'] * 100:.1f}%]  {verdict}{young_bit}"
    )


# ---------------------------------------------------------------------------
# Real-data maturity readout -- draws NO conclusion, ever. Reports current
# episode counts per bucket, distance to n>=30, and gap/dominance/mixed-side
# diagnostics.
# ---------------------------------------------------------------------------

def _print_header(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def run_real_data_readout(path: str, gap_sec: int) -> None:
    print("=" * 78)
    print("WAGMI LIQUIDATION HYPOTHESIS HARNESS -- H3/H5 MATURITY READOUT")
    print("(pre-registered method, data/copilot/PREREGISTRATION.md -- H3/H5)")
    print("=" * 78)
    print(
        "\n*** NO SIGNIFICANCE CONCLUSION IS DRAWN BY THIS RUN. ***\n"
        "This prints descriptive episode counts and, only where the n>=30\n"
        f"independent-EPISODE bar (SIGNIFICANCE_N={SIGNIFICANCE_N}) is already\n"
        "cleared, the mechanically-gated stat -- always re-read the YOUNG-SAMPLE\n"
        "caveat below before treating any such number as an answer."
    )
    print(
        "\nCAVEAT (verbatim from PREREGISTRATION.md): the feed carries no\n"
        "account/order ID. A same-side episode cannot be told apart from one\n"
        "position's partial fills; only MIXED-SIDE episodes are positively\n"
        "attributable to more than one distinct liquidation. Every number\n"
        "below is liquidation-PRESSURE clustering/timing, never a cross-\n"
        "account cascade claim."
    )

    raw_rows = load_events(path)
    print(f"\nfile: {path}")
    print(f"raw rows loaded: {len(raw_rows)}")
    events = prepare_events(raw_rows)
    n_dropped = len(raw_rows) - len(events)
    if n_dropped:
        print(f"(dropped {n_dropped} row(s) with unparsable ts_utc/missing symbol or side)")
    if not events:
        print("\nNo usable events -- nothing to report. This is expected on a fresh/empty collector.")
        return

    global_start, global_end = events[0]["dt"], events[-1]["dt"]
    span_days = (global_end - global_start).total_seconds() / 86400.0
    young = span_days < MIN_SPAN_DAYS_FOR_TRUST
    print(f"collection window: {global_start.isoformat()} .. {global_end.isoformat()}")
    print(f"collection span: {span_days:.2f} days (MIN_SPAN_DAYS_FOR_TRUST={MIN_SPAN_DAYS_FOR_TRUST})")
    if young:
        print(
            f"*** YOUNG SAMPLE: span is {span_days:.2f}d, well under the {MIN_SPAN_DAYS_FOR_TRUST}d bar. ***\n"
            "*** ANY bucket below that clears n>=30 is tagged YOUNG-SAMPLE and must ***\n"
            "*** still be read as provisional, not resolved -- 30 episodes from one ***\n"
            "*** short volatile stretch is not 30 draws across varied market regimes. ***"
        )

    # ---- Episode dedup / pseudoreplication diagnostics ----
    _print_header("PSEUDOREPLICATION DEDUP (event -> episode collapse)")
    dd = episode_dedup_report(events, gap_sec)
    print(f"episode-dedup gap threshold: {gap_sec}s ({gap_sec / 60:.1f} min)")
    print(f"raw events: {dd['n_events']}")
    print(f"independent episodes (CONSERVATIVE, symbol-only grouping -- the official N): {dd['n_episodes_conservative']}")
    print(f"independent episodes (symbol+side, secondary sensitivity view): {dd['n_episodes_side_aware']}")
    print(f"collapse ratio (events per episode, conservative): {dd['collapse_ratio']:.2f}x")
    print(
        f"mixed-side episodes (positively NOT a single position's partial fills): "
        f"{dd['n_mixed_side_episodes']}/{dd['n_episodes_conservative']} "
        f"({dd['mixed_side_frac'] * 100:.1f}%)"
    )
    print(
        f"remaining {100 - dd['mixed_side_frac'] * 100:.1f}% of episodes are single-sided -- "
        "ambiguous between one position's partials and several same-side accounts; "
        "the feed cannot resolve this, per PREREGISTRATION.md."
    )
    print(f"\ntop symbol by episode count: {dd['top_symbol']} ({dd['top_symbol_n']} episodes, "
          f"{dd['top_symbol_dominance_frac'] * 100:.1f}% of all episodes)")
    if dd["dominance_flag"]:
        print(
            f"*** SINGLE-SYMBOL DOMINANCE WARNING: {dd['top_symbol']} alone carries "
            f">= {SINGLE_SYMBOL_DOMINANCE_WARN * 100:.0f}% of all episodes. Any POOLED-looking finding "
            f"is really a {dd['top_symbol']}-specific finding -- read per-symbol only. ***"
        )
    else:
        print(f"(no single symbol clears the {SINGLE_SYMBOL_DOMINANCE_WARN * 100:.0f}% dominance-warning threshold)")
    print("\nepisodes per symbol (conservative):")
    for sym, n in dd["per_symbol_episodes"].most_common():
        gap_to_30 = max(0, SIGNIFICANCE_N - n)
        status = "CLEARS n>=30" if n >= SIGNIFICANCE_N else f"needs {gap_to_30} more"
        print(f"    {sym:<10s} n={n:<5d} {status}")

    episodes = dd["episodes"]

    # ---- H3 clustering ----
    _print_header("H3 -- CLUSTERING (does an episode raise P(another same-symbol episode)?)")
    for window in H3_WINDOWS_MIN:
        print(f"\n-- window = {window} min --")
        h3 = compute_h3(episodes, global_start, global_end, window)
        for sym, r in sorted(h3.items(), key=lambda kv: -kv[1]["n_eligible"]):
            print(fmt_h3_line(sym, window, r, young))

    # ---- H5 session timing ----
    _print_header("H5 -- SESSION TIMING (episode share of hour/session vs. clock-hour share)")
    rng = random.Random(BOOTSTRAP_SEED)
    hour_counts, h5_sessions, n_total_eps = compute_h5(episodes, rng)
    print(f"\ntotal independent episodes (gate for H5): n={n_total_eps} "
          f"({'CLEARS' if n_total_eps >= SIGNIFICANCE_N else 'BELOW'} n>={SIGNIFICANCE_N})")
    print("\nepisode start hour distribution (UTC) -- descriptive, finer than n>=30 usually allows:")
    for h in range(24):
        n = hour_counts.get(h, 0)
        marker = " <-- OHLC peak hour" if h in OHLC_PEAK_HOURS else ""
        print(f"    {h:02d}:00  n={n:<4d}{marker}")
    max_hour = max(range(24), key=lambda h: hour_counts.get(h, 0))
    print(f"\n(descriptive only: busiest single hour bucket so far is {max_hour:02d}:00 UTC with "
          f"n={hour_counts.get(max_hour, 0)} -- {'still below' if hour_counts.get(max_hour, 0) < SIGNIFICANCE_N else 'at/above'} "
          f"n>={SIGNIFICANCE_N}, no per-hour significance is computed by this harness, only per-session below.)")

    print("\nper-session (overlapping, same definition as session_vol_test.py):")
    for name in SESSIONS:
        print(fmt_h5_session_line(name, h5_sessions[name], young))

    top_session = max(h5_sessions.items(), key=lambda kv: kv[1]["obs_share"] if not math.isnan(kv[1]["obs_share"]) else -1)[0]
    print(f"\nOHLC-derived comparison point (session_vol_test.py, NOT recomputed here): "
          f"peak session = {OHLC_PEAK_SESSION}, peak hours = {OHLC_PEAK_HOURS}")
    print(f"current liq-episode busiest session (descriptive, by raw share): {top_session}")
    match_str = "MATCHES" if top_session == OHLC_PEAK_SESSION else "DOES NOT MATCH (contradicts or is inconclusive vs)"
    print(f"-> descriptive read: liq-timing busiest session {match_str} the OHLC vol-peak session. "
          f"NOT a conclusion -- see gating above for which sessions actually cleared n>=30 with a bootstrap verdict.")

    # ---- Refute-yourself hook: gap sensitivity sweep ----
    _print_header("REFUTE-YOURSELF HOOK 1 -- episode-gap sensitivity sweep")
    print("Rebuilding episodes at several gap thresholds; if headline counts/rankings")
    print("swing wildly, treat any single-gap finding as fragile.\n")
    print(f"{'gap':>8}  {'n_episodes':>10}  {'top_symbol(n)':>18}  {'busiest_session':>20}")
    for gap in GAP_SENSITIVITY_SEC:
        eps_g = build_episodes(events, gap, key="symbol")
        persym = Counter(ep["symbol"] for ep in eps_g)
        top_sym, top_n = persym.most_common(1)[0] if persym else ("-", 0)
        _, sess_g, n_g = compute_h5(eps_g, random.Random(BOOTSTRAP_SEED), bootstrap_iters=1)  # 1 iter: just need obs shares here, not CI
        best_sess = max(sess_g.items(), key=lambda kv: kv[1]["obs_share"] if not math.isnan(kv[1]["obs_share"]) else -1)[0] if n_g else "-"
        print(f"{gap:>6}s  {len(eps_g):>10}  {f'{top_sym}({top_n})':>18}  {best_sess:>20}")

    print(
        "\n(Note: the H5 bootstrap CIs/verdicts above always use the LOCKED "
        f"DEFAULT_GAP_SEC={DEFAULT_GAP_SEC}s -- this sweep is a stability diagnostic only, "
        "never used to pick a more favorable gap after the fact.)"
    )

    # ---- When answerable? ----
    _print_header("WHEN WILL H3/H5 BE ANSWERABLE? (rough linear projection, not a promise)")
    days_elapsed = max(span_days, 1e-6)
    print(f"Collection has run {days_elapsed:.2f} days so far. Projections below linearly extrapolate")
    print("each bucket's CURRENT accrual rate -- liquidation activity is bursty, so real")
    print("time-to-n30 could be much shorter (a volatile week) or longer (a calm one).\n")
    for sym, n in dd["per_symbol_episodes"].most_common():
        if n >= SIGNIFICANCE_N:
            print(f"    {sym:<10s} already clears n>={SIGNIFICANCE_N} ({n} episodes)"
                  + ("  [YOUNG-SAMPLE]" if young else ""))
        else:
            rate_per_day = n / days_elapsed
            eta_days = (SIGNIFICANCE_N / rate_per_day) if rate_per_day > 0 else float("inf")
            eta_str = f"~{eta_days:.1f} more day(s)" if math.isfinite(eta_days) else "no data yet to project from"
            print(f"    {sym:<10s} n={n:<4d} -> needs {SIGNIFICANCE_N - n} more episodes, projected ETA {eta_str}")

    print("\n" + "=" * 78)
    print("END OF READOUT -- no H3/H5 significance conclusion has been asserted above.")
    print("=" * 78)


# ---------------------------------------------------------------------------
# SELF-TEST -- synthetic verification. Proves the METHOD (not any real
# finding): (a) episode dedup correctly collapses a partial-fill burst,
# (b) H3 recovers a KNOWN clustering signal and stays quiet on a matched
# no-clustering control, (c) H5 recovers a KNOWN session concentration and
# stays quiet on a uniform control, (d) both refuse to conclude below n=30.
# ---------------------------------------------------------------------------

def _mk_event(symbol: str, side: str, dt: datetime, notional: float = 1000.0, venue: str = "synthetic") -> dict:
    """Raw-style event (ts_utc as an ISO string, like a real jsonl row) so
    synthetic tests exercise the SAME prepare_events() parsing path real
    data goes through, not a shortcut."""
    return {"symbol": symbol, "side": side, "ts_utc": dt.isoformat(), "notional_usd": notional, "venue": venue}


def _burst(symbol: str, side: str, start: datetime, n: int = 3, spacing_sec: float = 2.0) -> List[dict]:
    """A tight burst of n events spacing_sec apart -- simulates one
    liquidation reported as several partial fills."""
    return [_mk_event(symbol, side, start + timedelta(seconds=i * spacing_sec)) for i in range(n)]


def selftest_dedup_collapses_partial_fills() -> bool:
    """A single position's liquidation reported as 50 partial fills 2s apart
    must collapse to exactly ONE episode; a second, later fill outside the
    gap window must start a second episode."""
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    events = _burst("SYNTH_PF", "long", t0, n=50, spacing_sec=2.0)
    # a genuinely separate liquidation 20 minutes later (well past a 5-min gap)
    events += [_mk_event("SYNTH_PF", "long", t0 + timedelta(minutes=20))]
    events = prepare_events(events)
    episodes = build_episodes(events, gap_sec=300, key="symbol")
    ok = (
        len(episodes) == 2
        and episodes[0]["n_events"] == 50
        and episodes[1]["n_events"] == 1
    )
    print(
        f"  [dedup] 50-fill burst + 1 later fill -> episodes={[e['n_events'] for e in episodes]} "
        f"(expected [50, 1]): {'PASS' if ok else 'FAIL'}"
    )
    return ok


def _gen_clustered_symbol(rng: random.Random, symbol: str, n_seeds: int, trigger_prob: float) -> List[dict]:
    """Seeds spaced far apart (independent, low base rate) -- each seed
    triggers a same-symbol follow-up EPISODE ~8 min later with `trigger_prob`.
    A perfect method should find empirical P(followup within 15/60 min) far
    above the Poisson null implied by the seed rate alone.

    NOTE: the follow-up delay (8 min) is deliberately chosen to be LARGER
    than DEFAULT_GAP_SEC (5 min) so the seed and its follow-up remain TWO
    distinct episodes after dedup (a delay equal to/under the dedup gap
    would get merged into one episode by build_episodes, silently erasing
    the very follow-up this generator is trying to plant) while staying
    inside the 15-min H3 forecast window so it's detectable."""
    events: List[dict] = []
    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for _ in range(n_seeds):
        events += _burst(symbol, "long", t, n=rng.randint(1, 3), spacing_sec=2.0)
        if rng.random() < trigger_prob:
            events += _burst(symbol, "long", t + timedelta(minutes=8), n=rng.randint(1, 2), spacing_sec=2.0)
        t += timedelta(minutes=100)  # seeds spaced 100 min apart -> low background rate
    return events


def _gen_poisson_symbol(rng: random.Random, symbol: str, n_episodes: int, mean_gap_min: float) -> List[dict]:
    """A GENUINE homogeneous Poisson process (i.i.d. exponential inter-
    episode gaps) -- the matched negative control for H3's null model.
    IMPORTANT: a deterministic/regular spacing (e.g. jittered-uniform gaps
    all larger than the forecast window) is NOT a valid null control -- it
    would deterministically produce zero follow-ups, which is itself a
    significant deviation from the Poisson null (too REGULAR, not merely
    'unclustered'). Only a true Poisson process is expected to show
    empirical follow-up rates statistically consistent with its own
    theoretical null."""
    events: List[dict] = []
    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for _ in range(n_episodes):
        events += _burst(symbol, "long", t, n=rng.randint(1, 3), spacing_sec=2.0)
        gap_min = rng.expovariate(1.0 / mean_gap_min)
        t += timedelta(minutes=gap_min)
    return events


def selftest_h3_recovers_known_clustering() -> bool:
    rng = random.Random(4242)
    treat_events = _gen_clustered_symbol(rng, "SYNTH_CLUST", n_seeds=150, trigger_prob=0.85)
    ctrl_events = _gen_poisson_symbol(rng, "SYNTH_NOCLUST", n_episodes=220, mean_gap_min=50.0)
    events = prepare_events(treat_events + ctrl_events)
    episodes = build_episodes(events, gap_sec=DEFAULT_GAP_SEC, key="symbol")
    global_start, global_end = events[0]["dt"], events[-1]["dt"]

    h3 = compute_h3(episodes, global_start, global_end, window_min=15)
    treat = h3["SYNTH_CLUST"]
    ctrl = h3["SYNTH_NOCLUST"]

    treat_ok = (
        treat["n_eligible"] >= SIGNIFICANCE_N
        and treat["p_value"] is not None
        and treat["p_value"] < 0.05
        and treat["empirical_rate"] > treat["null_rate_poisson"] + 0.2
    )
    ctrl_ok = (
        ctrl["n_eligible"] >= SIGNIFICANCE_N
        and (ctrl["p_value"] is None or ctrl["p_value"] >= 0.05)
    )
    print(
        f"  [H3 treat] SYNTH_CLUST n={treat['n_eligible']} empirical={treat['empirical_rate']:.3f} "
        f"null={treat['null_rate_poisson']:.3f} p={treat['p_value']}: "
        f"{'PASS (detected clustering, p<0.05)' if treat_ok else 'FAIL'}"
    )
    print(
        f"  [H3 control] SYNTH_NOCLUST n={ctrl['n_eligible']} empirical={ctrl['empirical_rate']:.3f} "
        f"null={ctrl['null_rate_poisson']:.3f} p={ctrl['p_value']}: "
        f"{'PASS (correctly quiet, n.s.)' if ctrl_ok else 'FAIL'}"
    )
    return treat_ok and ctrl_ok


def _gen_session_concentrated_symbol(rng: random.Random, symbol: str, n_episodes: int, concentration: float) -> List[dict]:
    """Episodes spread across many distinct days, with `concentration` share
    of them landing in OHLC_PEAK_HOURS and the remainder spread uniformly
    across the rest of the day -- a known, planted session-timing signal."""
    events: List[dict] = []
    day0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(n_episodes):
        day = day0 + timedelta(days=i)  # one distinct calendar day per episode -> genuine day-to-day spread
        if rng.random() < concentration:
            hour = rng.choice(OHLC_PEAK_HOURS)
        else:
            hour = rng.randrange(24)
        minute = rng.randrange(60)
        t = day.replace(hour=hour, minute=minute)
        events += _burst(symbol, rng.choice(["long", "short"]), t, n=rng.randint(1, 4), spacing_sec=2.0)
    return events


def _gen_uniform_symbol(rng: random.Random, symbol: str, n_episodes: int) -> List[dict]:
    events: List[dict] = []
    day0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(n_episodes):
        day = day0 + timedelta(days=i)
        hour = rng.randrange(24)
        minute = rng.randrange(60)
        t = day.replace(hour=hour, minute=minute)
        events += _burst(symbol, rng.choice(["long", "short"]), t, n=rng.randint(1, 4), spacing_sec=2.0)
    return events


def selftest_h5_recovers_known_session_concentration() -> bool:
    rng = random.Random(777)
    treat_events = _gen_session_concentrated_symbol(rng, "SYNTH_SESSION", n_episodes=150, concentration=0.85)
    ctrl_events = _gen_uniform_symbol(rng, "SYNTH_UNIFORM", n_episodes=150)

    treat_ev = prepare_events(treat_events)
    ctrl_ev = prepare_events(ctrl_events)
    treat_eps = build_episodes(treat_ev, gap_sec=DEFAULT_GAP_SEC, key="symbol")
    ctrl_eps = build_episodes(ctrl_ev, gap_sec=DEFAULT_GAP_SEC, key="symbol")

    rng_boot = random.Random(BOOTSTRAP_SEED)
    _, treat_sessions, n_treat = compute_h5(treat_eps, rng_boot)
    rng_boot2 = random.Random(BOOTSTRAP_SEED)
    _, ctrl_sessions, n_ctrl = compute_h5(ctrl_eps, rng_boot2)

    us = treat_sessions[OHLC_PEAK_SESSION]
    treat_ok = (
        n_treat >= SIGNIFICANCE_N
        and us["n"] >= SIGNIFICANCE_N
        and us["bootstrap_significant"] is True
        and us["obs_share"] > us["clock_share"]
    )
    ctrl_us = ctrl_sessions[OHLC_PEAK_SESSION]
    ctrl_ok = (
        n_ctrl >= SIGNIFICANCE_N
        and (ctrl_us["bootstrap_significant"] is not True)
    )
    print(
        f"  [H5 treat] SYNTH_SESSION {OHLC_PEAK_SESSION}: n={us['n']} obs_share={us['obs_share']:.3f} "
        f"clock_share={us['clock_share']:.3f} sig={us['bootstrap_significant']}: "
        f"{'PASS (detected planted session concentration)' if treat_ok else 'FAIL'}"
    )
    print(
        f"  [H5 control] SYNTH_UNIFORM {OHLC_PEAK_SESSION}: n={ctrl_us['n']} obs_share={ctrl_us['obs_share']:.3f} "
        f"clock_share={ctrl_us['clock_share']:.3f} sig={ctrl_us['bootstrap_significant']}: "
        f"{'PASS (correctly quiet on uniform control)' if ctrl_ok else 'FAIL'}"
    )
    return treat_ok and ctrl_ok


def selftest_gating_refuses_below_n30() -> bool:
    """A thin symbol with only 10 episodes must never produce a p-value/CI,
    regardless of how extreme the (tiny-n) empirical pattern looks."""
    rng = random.Random(99)
    # 10 seeds, ALL triggering a followup -- would look like p~0 "perfect"
    # clustering if the gate were bypassed. Must still refuse.
    events = _gen_clustered_symbol(rng, "SYNTH_THIN", n_seeds=10, trigger_prob=1.0)
    ev = prepare_events(events)
    eps = build_episodes(ev, gap_sec=DEFAULT_GAP_SEC, key="symbol")
    global_start, global_end = ev[0]["dt"], ev[-1]["dt"]
    h3 = compute_h3(eps, global_start, global_end, window_min=15)
    r = h3["SYNTH_THIN"]
    h3_ok = r["n_eligible"] < SIGNIFICANCE_N and r["p_value"] is None and r["z"] is None
    line = fmt_h3_line("SYNTH_THIN", 15, r, young=False)
    line_ok = "UNDERPOWERED" in line and "p=" not in line

    # H5: a symbol with only 10 episodes, all in the peak hour -- must not
    # get a bootstrap verdict either.
    rng2 = random.Random(55)
    day0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    thin_sess_events = []
    for i in range(10):
        day = day0 + timedelta(days=i)
        t = day.replace(hour=14, minute=0)
        thin_sess_events += _burst("SYNTH_THIN_SESSION", "long", t, n=2, spacing_sec=2.0)
    ev2 = prepare_events(thin_sess_events)
    eps2 = build_episodes(ev2, gap_sec=DEFAULT_GAP_SEC, key="symbol")
    _, sessions, n_total = compute_h5(eps2, random.Random(BOOTSTRAP_SEED))
    us = sessions[OHLC_PEAK_SESSION]
    h5_ok = n_total < SIGNIFICANCE_N and us["bootstrap_significant"] is None and us["ci_lo"] is None
    h5_line = fmt_h5_session_line(OHLC_PEAK_SESSION, us, young=False)
    h5_line_ok = "UNDERPOWERED" in h5_line

    ok = h3_ok and line_ok and h5_ok and h5_line_ok
    print(
        f"  [gating] H3 n={r['n_eligible']}<30 all-triggered thin symbol -> "
        f"p_value={r['p_value']}, z={r['z']}, printed line has no p=: {'PASS' if (h3_ok and line_ok) else 'FAIL'}"
    )
    print(
        f"  [gating] H5 n={n_total}<30 all-peak-hour thin symbol -> "
        f"bootstrap_significant={us['bootstrap_significant']}, printed line UNDERPOWERED: "
        f"{'PASS' if (h5_ok and h5_line_ok) else 'FAIL'}"
    )
    return ok


def run_selftest() -> int:
    print("=" * 78)
    print("SELF-TEST -- SYNTHETIC METHOD VERIFICATION (no real data touched)")
    print("=" * 78)
    print(
        "Proves the METHOD, not any live finding: dedup correctly collapses a\n"
        "partial-fill burst, H3/H5 recover PLANTED signals and stay quiet on\n"
        "matched negative controls, and both refuse to compute a p-value/CI\n"
        "below n=30 independent episodes even when the tiny-n pattern looks\n"
        "'perfect'.\n"
    )
    results = []
    print("-- Pseudoreplication dedup --")
    results.append(selftest_dedup_collapses_partial_fills())
    print("\n-- H3 clustering: recovers planted signal + quiet on control --")
    results.append(selftest_h3_recovers_known_clustering())
    print("\n-- H5 session timing: recovers planted signal + quiet on control --")
    results.append(selftest_h5_recovers_known_session_concentration())
    print("\n-- Strict gating: refuses to conclude below n=30 --")
    results.append(selftest_gating_refuses_below_n30())

    n_pass = sum(1 for r in results if r)
    n_total = len(results)
    print("\n" + "=" * 78)
    print(f"SELF-TEST RESULT: {n_pass}/{n_total} checks PASSED")
    print("=" * 78)
    return 0 if n_pass == n_total else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "WAGMI Co-Pilot liquidation hypothesis harness (H3 clustering, H5 session-timing). "
            "Default: real-data maturity readout (no conclusions drawn). --selftest: synthetic "
            "method verification."
        )
    )
    ap.add_argument("--path", type=str, default=DEFAULT_PATH, help="Path to liq_events.jsonl")
    ap.add_argument(
        "--gap-sec", type=int, default=DEFAULT_GAP_SEC,
        help=f"Episode-dedup gap threshold in seconds (default {DEFAULT_GAP_SEC} = {DEFAULT_GAP_SEC/60:.0f} min)",
    )
    ap.add_argument("--selftest", action="store_true", help="Run synthetic method-verification suite and exit")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(run_selftest())
    else:
        run_real_data_readout(args.path, args.gap_sec)


if __name__ == "__main__":
    main()
