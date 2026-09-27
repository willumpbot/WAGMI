"""
session_vol_test.py -- RISK-CONTEXT test (NOT an edge hunt).

Question: does crypto volatility / adverse-move risk cluster by UTC hour or
trading session (Asia/EU/US/off)? If it does AND it's stable across eras and
consistent across coins, the co-pilot briefing can honestly say "the tape is
typically most violent in the X session." If it's weak or era-unstable, we
surface nothing.

READ-ONLY. Standalone. No live-co-pilot imports, no Discord, no writes to
any live/shadow state. Run manually:

    python tools/copilot/session_vol_test.py

Data sources:
  - data/longtail/ohlc/*_1h.csv   (25 alts, hourly OHLCV, ~200d)
  - data/cache/BTC_1h_420d.csv, data/cache/SOL_1h_420d.csv
  - data/copilot/liquidations/liq_events.jsonl  (live collector, ~n=12,
    DIRECTIONAL PEEK ONLY -- explicitly underpowered, not a conclusion)

DATA HONESTY NOTE: the alt CSVs (longtail) and the BTC/SOL cache CSVs do
NOT share an end date -- alts run through ~2026-07-31 (last backfill), BTC/
SOL cache tops out ~2026-07-14 (~17d gap; same cache ceiling noted in
corr_stress_test.py). Session/hour buckets are computed per-symbol from
each symbol's own local timestamps, so this doesn't bias the hour-of-day
read within a symbol, but BTC/SOL reflect ~2.5 fewer recent weeks than the
alts when eyeballing them side by side. Disclosed, not hidden.

This is about VOLATILITY TIMING (how violent is the tape when), not
directional return. We deliberately do NOT build or report a time-of-day
*return* edge. If one falls out incidentally, it gets the same
refute-yourself treatment before it's allowed anywhere near a conclusion --
in practice here we just note it and set it aside.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]  # bot/
LONGTAIL_DIR = BASE / "data" / "longtail" / "ohlc"
CACHE_DIR = BASE / "data" / "cache"
LIQ_PATH = BASE / "data" / "copilot" / "liquidations" / "liq_events.jsonl"

TAIL_THRESH = 0.01  # |1h return| > 1.0% counted as a "tail move" for freq table

SESSIONS = {
    "Asia (00-08 UTC)": set(range(0, 8)),
    "EU (07-15 UTC)": set(range(7, 15)),
    "US (13-21 UTC)": set(range(13, 21)),
    "Off (21-00 UTC)": set(range(21, 24)) | {0},  # NB overlaps Asia's hour 0 by design (see note)
}
# Note: session buckets are the classic overlapping definition requested
# (Asia/EU/US/off), not a mutually-exclusive partition of the day -- that's
# intentional (real sessions overlap), but it means Asia+Off share hour 0.
# We call this out in the summary so it isn't misread as a clean partition.


def _iter_alt_files():
    for p in sorted(LONGTAIL_DIR.glob("*_1h.csv")):
        yield p.stem.replace("_1h", ""), p


def load_ohlc_generic(path: Path) -> list[dict]:
    """Load either the longtail schema (open_time_ms,dt_utc_iso,o,h,l,c,v)
    or the cache schema (open,high,low,close,volume,time) into a common
    list of dicts: dt (str iso), hour (int UTC), dow (int 0=Mon), o,h,l,c."""
    import csv
    from datetime import datetime, timezone

    rows = []
    with open(path, "r", newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        is_longtail = "dt_utc_iso" in fields
        for r in reader:
            try:
                if is_longtail:
                    dt_raw = r["dt_utc_iso"]
                    o, h, l, c = float(r["o"]), float(r["h"]), float(r["l"]), float(r["c"])
                else:
                    dt_raw = r["time"]
                    o, h, l, c = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
                dt_raw = dt_raw.strip()
                # normalize "+00:00" / "Z" / plain space-separated forms
                dt_norm = dt_raw.replace("Z", "+00:00")
                dt = datetime.fromisoformat(dt_norm)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                dt = dt.astimezone(timezone.utc)
                if o <= 0 or c <= 0 or h <= 0 or l <= 0:
                    continue
                rows.append(
                    {
                        "dt": dt,
                        "hour": dt.hour,
                        "dow": dt.weekday(),  # 0=Mon .. 6=Sun
                        "o": o,
                        "h": h,
                        "l": l,
                        "c": c,
                    }
                )
            except (KeyError, ValueError):
                continue
    rows.sort(key=lambda r: r["dt"])
    return rows


def compute_bars(rows: list[dict]) -> list[dict]:
    """Attach per-bar |close-to-close return| and intrabar range (h-l)/o."""
    out = []
    prev_close = None
    for r in rows:
        ret = None
        if prev_close is not None and prev_close > 0:
            ret = (r["c"] - prev_close) / prev_close
        rng = (r["h"] - r["l"]) / r["o"] if r["o"] > 0 else None
        out.append({**r, "ret": ret, "range": rng})
        prev_close = r["c"]
    return out


def load_all_symbols() -> dict[str, list[dict]]:
    data = {}
    for sym, path in _iter_alt_files():
        rows = load_ohlc_generic(path)
        if len(rows) < 100:
            continue
        data[sym] = compute_bars(rows)
    for sym, fname in [("BTC", "BTC_1h_420d.csv"), ("SOL", "SOL_1h_420d.csv")]:
        p = CACHE_DIR / fname
        if p.exists():
            rows = load_ohlc_generic(p)
            if len(rows) >= 100:
                data[sym] = compute_bars(rows)
    return data


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else float("nan")


def hourly_profile(all_bars: list[dict]) -> dict[int, dict]:
    """Pooled across all coins: per-UTC-hour avg |ret|, avg range, n, tail freq."""
    buckets = {h: {"abs_ret": [], "range": [], "tail": 0, "n": 0} for h in range(24)}
    for b in all_bars:
        if b["ret"] is None:
            continue
        h = b["hour"]
        buckets[h]["abs_ret"].append(abs(b["ret"]))
        if b["range"] is not None:
            buckets[h]["range"].append(b["range"])
        buckets[h]["n"] += 1
        if abs(b["ret"]) > TAIL_THRESH:
            buckets[h]["tail"] += 1
    out = {}
    for h, d in buckets.items():
        n = d["n"]
        out[h] = {
            "n": n,
            "mean_abs_ret": mean(d["abs_ret"]),
            "mean_range": mean(d["range"]),
            "tail_freq": (d["tail"] / n) if n else float("nan"),
        }
    return out


def session_bucket_stats(all_bars: list[dict]) -> dict[str, dict]:
    out = {}
    for name, hours in SESSIONS.items():
        abs_rets = [abs(b["ret"]) for b in all_bars if b["ret"] is not None and b["hour"] in hours]
        ranges = [b["range"] for b in all_bars if b["range"] is not None and b["hour"] in hours]
        tails = sum(1 for r in abs_rets if r > TAIL_THRESH)
        n = len(abs_rets)
        out[name] = {
            "n": n,
            "mean_abs_ret": mean(abs_rets),
            "mean_range": mean(ranges),
            "tail_freq": (tails / n) if n else float("nan"),
        }
    return out


def dow_stats(all_bars: list[dict]) -> dict[str, dict]:
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    weekday_bars = [b for b in all_bars if b["dow"] <= 4 and b["ret"] is not None]
    weekend_bars = [b for b in all_bars if b["dow"] >= 5 and b["ret"] is not None]
    out = {
        "weekday": {
            "n": len(weekday_bars),
            "mean_abs_ret": mean([abs(b["ret"]) for b in weekday_bars]),
        },
        "weekend": {
            "n": len(weekend_bars),
            "mean_abs_ret": mean([abs(b["ret"]) for b in weekend_bars]),
        },
    }
    per_dow = {}
    for i, nm in enumerate(names):
        bars = [b for b in all_bars if b["dow"] == i and b["ret"] is not None]
        per_dow[nm] = {"n": len(bars), "mean_abs_ret": mean([abs(b["ret"]) for b in bars])}
    out["per_dow"] = per_dow
    return out


def split_era(bars: list[dict]) -> tuple[list[dict], list[dict]]:
    if not bars:
        return [], []
    mid = len(bars) // 2
    return bars[:mid], bars[mid:]


def rank_hours(profile: dict[int, dict]) -> list[int]:
    return sorted(profile.keys(), key=lambda h: profile[h]["mean_abs_ret"], reverse=True)


def spearman(a: list[int], b: list[int]) -> float:
    """Spearman rank correlation between two hour-rank orderings (0-23),
    comparing the RANK POSITION each hour occupies in each ordering."""
    n = len(a)
    rank_a = {h: i for i, h in enumerate(a)}
    rank_b = {h: i for i, h in enumerate(b)}
    d2 = sum((rank_a[h] - rank_b[h]) ** 2 for h in range(24))
    if n <= 1:
        return float("nan")
    return 1 - (6 * d2) / (n * (n ** 2 - 1))


def fmt_pct(x, dp=3):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/a"
    return f"{x*100:.{dp}f}%"


def print_hourly_table(profile: dict[int, dict], title: str):
    print(f"\n-- {title} --")
    print(f"{'UTC hr':>6} {'n':>6} {'mean|ret|':>10} {'mean range':>11} {'tail freq (>1%)':>16}")
    for h in range(24):
        d = profile[h]
        print(f"{h:>6} {d['n']:>6} {fmt_pct(d['mean_abs_ret']):>10} {fmt_pct(d['mean_range']):>11} {fmt_pct(d['tail_freq']):>16}")


def print_session_table(sess: dict[str, dict], title: str):
    print(f"\n-- {title} --")
    print(f"{'session':>20} {'n':>7} {'mean|ret|':>10} {'mean range':>11} {'tail freq (>1%)':>16}")
    for name, d in sess.items():
        print(f"{name:>20} {d['n']:>7} {fmt_pct(d['mean_abs_ret']):>10} {fmt_pct(d['mean_range']):>11} {fmt_pct(d['tail_freq']):>16}")


def load_liq_events() -> list[dict]:
    if not LIQ_PATH.exists():
        return []
    out = []
    from datetime import datetime

    with open(LIQ_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                ts = d.get("ts_utc")
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                out.append({"dt": dt, "hour": dt.hour, "dow": dt.weekday(), "raw": d})
            except (json.JSONDecodeError, ValueError, AttributeError):
                continue
    return out


def which_session(hour: int) -> list[str]:
    return [name for name, hours in SESSIONS.items() if hour in hours]


def main():
    print("=" * 78)
    print("SESSION VOLATILITY / RISK-TIMING TEST  (read-only, standalone)")
    print("=" * 78)

    data = load_all_symbols()
    if not data:
        print("No OHLC data loaded -- aborting.")
        return
    coins = sorted(data.keys())
    print(f"\nLoaded {len(coins)} symbols: {', '.join(coins)}")
    for sym in coins:
        bars = data[sym]
        rets = [b for b in bars if b["ret"] is not None]
        if rets:
            span_days = (bars[-1]["dt"] - bars[0]["dt"]).days
            print(f"  {sym:10s} n_bars={len(bars):5d}  span~{span_days}d  "
                  f"{bars[0]['dt'].date()} -> {bars[-1]['dt'].date()}")

    all_bars = [b for bars in data.values() for b in bars]
    print(f"\nTotal pooled bars (all coins, all time): {len(all_bars)}")

    # ---- Test 1: intraday hourly profile, pooled ----
    profile = hourly_profile(all_bars)
    print_hourly_table(profile, "TEST 1: Pooled intraday UTC-hour vol profile (ALL coins, full sample)")

    ranked = rank_hours(profile)
    top_h, bot_h = ranked[0], ranked[-1]
    top_v, bot_v = profile[top_h]["mean_abs_ret"], profile[bot_h]["mean_abs_ret"]
    ratio_hr = top_v / bot_v if bot_v else float("nan")
    print(f"\nMost-volatile hour: {top_h:02d}:00 UTC (mean|ret|={fmt_pct(top_v)})")
    print(f"Least-volatile hour: {bot_h:02d}:00 UTC (mean|ret|={fmt_pct(bot_v)})")
    print(f"Peak/trough hour ratio: {ratio_hr:.2f}x")

    # ---- Test 2: session buckets ----
    sess = session_bucket_stats(all_bars)
    print_session_table(sess, "TEST 2: Session buckets, pooled (ALL coins, full sample)")
    sess_ranked = sorted(sess.items(), key=lambda kv: kv[1]["mean_abs_ret"], reverse=True)
    top_sess, bot_sess = sess_ranked[0], sess_ranked[-1]
    sess_ratio = top_sess[1]["mean_abs_ret"] / bot_sess[1]["mean_abs_ret"] if bot_sess[1]["mean_abs_ret"] else float("nan")
    print(f"\nMost-violent session: {top_sess[0]} (mean|ret|={fmt_pct(top_sess[1]['mean_abs_ret'])}, "
          f"tail_freq={fmt_pct(top_sess[1]['tail_freq'])})")
    print(f"Least-violent session: {bot_sess[0]} (mean|ret|={fmt_pct(bot_sess[1]['mean_abs_ret'])}, "
          f"tail_freq={fmt_pct(bot_sess[1]['tail_freq'])})")
    print(f"Session peak/trough ratio: {sess_ratio:.2f}x")
    print("NOTE: session buckets overlap by definition (Asia/EU share 07-08, EU/US share")
    print("13-14, US/Off share 21, Off/Asia share 00) -- these are trading-desk session")
    print("windows, not a mutually-exclusive partition of the day.")

    # ---- Test 3: day of week ----
    dow = dow_stats(all_bars)
    print("\n-- TEST 3: Day-of-week, pooled (ALL coins, full sample) --")
    print(f"{'weekday':>10} n={dow['weekday']['n']:>6}  mean|ret|={fmt_pct(dow['weekday']['mean_abs_ret'])}")
    print(f"{'weekend':>10} n={dow['weekend']['n']:>6}  mean|ret|={fmt_pct(dow['weekend']['mean_abs_ret'])}")
    wd, we = dow["weekday"]["mean_abs_ret"], dow["weekend"]["mean_abs_ret"]
    dow_ratio = wd / we if we else float("nan")
    print(f"weekday/weekend ratio: {dow_ratio:.2f}x")
    print("Per-DOW breakdown:")
    for nm, d in dow["per_dow"].items():
        print(f"  {nm}: n={d['n']:>6}  mean|ret|={fmt_pct(d['mean_abs_ret'])}")

    # ---- Test 4: era stability (first half vs second half of sample) ----
    print("\n" + "=" * 78)
    print("TEST 4: ERA STABILITY -- the crux")
    print("=" * 78)

    # Era split: split each coin's own series at its midpoint (calendar-
    # aligned per coin), then pool, so era1/era2 are genuinely "first half of
    # history" vs "second half" per-coin rather than an artifact of how the
    # symbols happen to be concatenated.
    era1_bars, era2_bars = [], []
    for sym, bars in data.items():
        rets = [b for b in bars if b["ret"] is not None]
        e1, e2 = split_era(rets)
        era1_bars.extend(e1)
        era2_bars.extend(e2)

    profile_e1 = hourly_profile(era1_bars)
    profile_e2 = hourly_profile(era2_bars)
    if era1_bars:
        print(f"\nEra 1 (first half, per-coin): n={len(era1_bars)}, "
              f"{min(b['dt'] for b in era1_bars).date()} -> {max(b['dt'] for b in era1_bars).date()}")
    if era2_bars:
        print(f"Era 2 (second half, per-coin): n={len(era2_bars)}, "
              f"{min(b['dt'] for b in era2_bars).date()} -> {max(b['dt'] for b in era2_bars).date()}")

    print_hourly_table(profile_e1, "Era 1 hourly profile")
    print_hourly_table(profile_e2, "Era 2 hourly profile")

    rank_e1 = rank_hours(profile_e1)
    rank_e2 = rank_hours(profile_e2)
    rho = spearman(rank_e1, rank_e2)
    print(f"\nSpearman rank-correlation of hourly vol ranking, era1 vs era2: {rho:.3f}")
    print(f"Era 1 top-3 hours: {rank_e1[:3]}   Era 2 top-3 hours: {rank_e2[:3]}")
    print(f"Era 1 bottom-3 hours: {rank_e1[-3:]}   Era 2 bottom-3 hours: {rank_e2[-3:]}")

    sess_e1 = session_bucket_stats(era1_bars)
    sess_e2 = session_bucket_stats(era2_bars)
    print("\nSession ranking by era:")
    for era_name, sd in [("Era1", sess_e1), ("Era2", sess_e2)]:
        ranked_s = sorted(sd.items(), key=lambda kv: kv[1]["mean_abs_ret"], reverse=True)
        print(f"  {era_name}: " + " > ".join(f"{n}({fmt_pct(d['mean_abs_ret'])})" for n, d in ranked_s))

    top_sess_e1 = max(sess_e1.items(), key=lambda kv: kv[1]["mean_abs_ret"])[0]
    top_sess_e2 = max(sess_e2.items(), key=lambda kv: kv[1]["mean_abs_ret"])[0]
    sess_stable = top_sess_e1 == top_sess_e2
    print(f"\nTop session Era1={top_sess_e1!r} vs Era2={top_sess_e2!r} -> "
          f"{'STABLE' if sess_stable else 'UNSTABLE (peak moved)'}")

    # ---- Cross-coin consistency: does each coin individually agree on the top session? ----
    print("\n-- Cross-coin consistency: top session per coin (full sample) --")
    per_coin_top_session = {}
    for sym, bars in data.items():
        rets = [b for b in bars if b["ret"] is not None]
        if len(rets) < 100:
            continue
        s = session_bucket_stats(rets)
        top = max(s.items(), key=lambda kv: kv[1]["mean_abs_ret"])[0]
        per_coin_top_session[sym] = top
        print(f"  {sym:10s} -> top session: {top}  (mean|ret|={fmt_pct(s[top]['mean_abs_ret'])})")

    from collections import Counter

    vote_counts = Counter(per_coin_top_session.values())
    n_coins_voted = len(per_coin_top_session)
    print(f"\nVote tally across {n_coins_voted} coins: {dict(vote_counts)}")
    majority_sess, majority_n = vote_counts.most_common(1)[0]
    majority_frac = majority_n / n_coins_voted if n_coins_voted else float("nan")
    print(f"Majority session '{majority_sess}' wins in {majority_n}/{n_coins_voted} coins "
          f"({fmt_pct(majority_frac, 1)})")

    # BTC/SOL specifically vs thin memes
    print("\nBTC/SOL vs thin memes (kBONK/kPEPE/kSHIB/FARTCOIN/PENGU/PUMP) top session:")
    majors = {k: v for k, v in per_coin_top_session.items() if k in ("BTC", "SOL")}
    memes = {k: v for k, v in per_coin_top_session.items()
             if k in ("kBONK", "kPEPE", "kSHIB", "FARTCOIN", "PENGU", "PUMP")}
    print(f"  Majors: {majors}")
    print(f"  Memes:  {memes}")

    # ---- Test 5: liquidation timing peek (underpowered) ----
    print("\n" + "=" * 78)
    print("TEST 5: LIQUIDATION-TIMING PEEK -- UNDERPOWERED, n is tiny, NOT EVIDENCE")
    print("=" * 78)
    liq = load_liq_events()
    print(f"\nLoaded {len(liq)} liquidation events from {LIQ_PATH}")
    if liq:
        hour_counts = Counter(e["hour"] for e in liq)
        print("Liq events by UTC hour:")
        for h in sorted(hour_counts):
            print(f"  {h:02d}:00 UTC -> {hour_counts[h]} event(s)")
        sess_counts = Counter()
        for e in liq:
            for s in which_session(e["hour"]):
                sess_counts[s] += 1
        print("\nLiq events by session (note: an event in an overlap hour counts in both sessions):")
        for s, n in sess_counts.most_common():
            print(f"  {s}: {n}")
        print(f"\n*** n={len(liq)} liquidation events is FAR too small to draw any conclusion. ***")
        print("*** This is a directional peek only -- revisit once the collector has 60-90d ***")
        print("*** of data (expect on the order of thousands of events by then). ***")
    else:
        print("No liquidation events found / file missing -- skipping peek.")

    # ---- Final verdict ----
    print("\n" + "=" * 78)
    print("VERDICT")
    print("=" * 78)
    print(f"1. Pooled hourly peak/trough ratio: {ratio_hr:.2f}x "
          f"(hour {top_h:02d}:00 vs {bot_h:02d}:00 UTC)")
    print(f"2. Pooled session peak/trough ratio: {sess_ratio:.2f}x "
          f"({top_sess[0]} vs {bot_sess[0]})")
    print(f"3. Era stability (Spearman rho of hourly ranks, era1 vs era2): {rho:.3f}")
    print(f"   Top session stable across eras: {sess_stable}")
    print(f"4. Cross-coin agreement on top session: {majority_n}/{n_coins_voted} "
          f"({fmt_pct(majority_frac, 1)}) agree on '{majority_sess}'")
    print(f"5. Liquidation peek: n={len(liq)}, underpowered, directional only")

    STABILITY_RHO_THRESH = 0.5
    RATIO_THRESH = 1.3
    MAJORITY_FRAC_THRESH = 0.6

    surfaced = (
        not math.isnan(rho)
        and rho >= STABILITY_RHO_THRESH
        and sess_stable
        and sess_ratio >= RATIO_THRESH
        and majority_frac >= MAJORITY_FRAC_THRESH
    )
    print()
    if surfaced:
        print(f"=> SURFACE: stable, cross-coin-consistent pattern found. Session-level ratio "
              f"{sess_ratio:.2f}x, era-stable (rho={rho:.2f}), {fmt_pct(majority_frac,0)} of coins agree.")
        print(f'   Suggested one-line briefing note: "Tape typically most violent in the '
              f'{top_sess[0]} session, ~{sess_ratio:.1f}x calmer hours -- size/attention accordingly."')
    else:
        reasons = []
        if math.isnan(rho) or rho < STABILITY_RHO_THRESH:
            reasons.append(f"hourly ranking not stable across eras (rho={rho:.2f} < {STABILITY_RHO_THRESH})")
        if not sess_stable:
            reasons.append("top session moved between eras")
        if sess_ratio < RATIO_THRESH:
            reasons.append(f"session ratio too weak ({sess_ratio:.2f}x < {RATIO_THRESH}x)")
        if majority_frac < MAJORITY_FRAC_THRESH:
            reasons.append(f"cross-coin agreement too weak ({fmt_pct(majority_frac,0)} < {fmt_pct(MAJORITY_FRAC_THRESH,0)})")
        print("=> DO NOT SURFACE to the briefing. Reasons: " + "; ".join(reasons))
        print("   Pattern is either too weak or too unstable/coin-dependent to state as fact.")


if __name__ == "__main__":
    main()
