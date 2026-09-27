#!/usr/bin/env python
"""
WAGMI Co-Pilot H6 NEAR-MISS REVERSION FORWARD TRACKER -- nearmiss_reversion_tracker.py
=============================================================================
Forward-validates H6 (see data/copilot/PREREGISTRATION.md) -- the ONE
near-miss the confluence/mean-reversion campaign produced:
`tools/copilot/meanrev_rule_test.py`'s `drop2d_fixed10pct` rule (buy after a
2-day trailing drop <= -10%, hold 2 days, unlevered, net of per-liquidity
cost) was positive in EVERY in-sample cut (train +1.03%/ep p=0.0018, test
+1.26%/ep p=0.053-0.062, both eras, survives excluding the Feb-2026 crash,
9-11% max single-coin share) but MISSED the pre-registered p<0.05 test-fold
bar. Per this project's discipline (do not lower the bar), it is
UNCONFIRMED, not an edge -- see MEANREV_RULE_TEST_RESULTS.md section 3.

WHY THIS EXISTS: the same overfit-ceiling problem H1-H5 exist to solve
applies here -- the 13-14mo/25-coin historical corpus that produced this
near-miss is SPENT (re-mining it again would just be another cut of the
same exhausted history). This tracker manufactures genuinely NEW, unmined
forward evidence going forward, exactly like `resolve_calls.py` does for
H1/H2 and `liq_hypothesis_harness.py`/`oi_hypothesis_harness.py` do for
H3-H5 -- so H6's eventual verdict comes from calendar time, not another
backtest re-run.

THE RULE (unchanged from the backtest spec -- see PREREGISTRATION.md H6):
for coin X, on the day its trailing 2-day return `c[t]/c[t-2]-1 <= -10%`,
BUY at that day's SETTLED close, HOLD EXACTLY 2 DAYS, SELL at the close 2
days later. Unlevered 1x spot. Net of a round-trip cost keyed to the
symbol's own liquidity bucket (liquid 12.5bps / mid 32.5bps / thin 75bps
RT midpoints -- identical `LIQUIDITY_COST_BPS_RT` assumption as
`confluence_harness.py`; unknown-liquidity symbols default to thin/75bps,
never the cheapest).

ANCHORING -- LEARNED FROM resolve_calls.py, NOT REIMPLEMENTED: this file
reuses `resolve_calls.py`'s `_fetch_daily_closes()` (candle-OPEN-date-keyed
lookup) and its "mature once now >= anchor + horizon + 1 day" maturity
rule DIRECTLY (`import resolve_calls as rc`), rather than re-deriving the
close-to-close date math from scratch. `resolve_calls.py`'s own module
docstring documents the 2026-08-01 bug this avoided (an earlier version
anchored on wall-clock `ts_utc` and used candle CLOSE time instead of OPEN
date, silently inflating every horizon) -- importing the same helper means
that bug structurally cannot be reintroduced here.

UNIVERSE: the 25 longtail alts (`confluence_harness._KNOWN_LONGTAIL`) --
narrower than the in-sample test's 30-symbol universe (which also included
5 majors whose local OHLC cache is stale, frozen 2026-07-13) because this
tracker only watches symbols with a clean LIVE daily feed via
`data/fetchers/hl_native.py` (HLNative), never the stale cache.

NO BACKFILL, PERIOD: trigger DETECTION and RESOLUTION are ALWAYS live
HLNative fetches -- the static `data/longtail/ohlc/*_1d.csv` snapshot (the
now-spent in-sample corpus, frozen through 2026-07-31) is read for exactly
ONE purpose, `get_liquidity_buckets()`: classifying each symbol's typical
liquidity TERCILE for the cost model, a slow-moving, roughly-stable
per-symbol characteristic -- never a source of a trigger or an outcome. A
row's `logged_ts_utc` is always "now" at detection time; only rows logged
on/after the H6 pre-registration date (`PREREGISTRATION_DATE` below) ever
count toward the forward sample (`compute_forward_readout()` enforces this
filter even though, by construction, no other kind of row can exist in this
file).

GATING (identical shape to H1-H5, enforced in the COMPUTE layer, not just
the printer -- see `compute_forward_readout()`): n >= SIGNIFICANCE_N=30
independent post-registration triggers (independence enforced at the
LOGGING layer -- see DEDUP below) before ANY p-value is computed. Below
that bar, only "n=X, UNCONFIRMED near-miss, not yet significant /
forward-accruing" is ever printed -- never a mean, a p-value, or a verdict.
Even at n>=30, "confirmed" additionally requires p<0.05, mean net > 0, AND
no single symbol supplying >=50% of the sample (`SINGLE_SYMBOL_DOMINANCE_
WARN`, the same threshold `confluence_harness.py` uses) -- matching all
three legs of PREREGISTRATION.md's H6 success bar, not just the p-value.

DEDUP / INDEPENDENCE (pseudoreplication guard): a symbol already inside an
open 2-day hold window cannot manufacture a second, overlapping "trigger" --
mirrors `confluence_harness.py`'s own `dedup_gap_days=N` episode-collapse
rule (`_dedup_trigger_indices`: keep a new trigger only if it is MORE than
the gap away from the last kept one). `should_start_new_episode()` below
implements the identical rule for the live daily case: a new episode for a
symbol is only logged if the candidate trigger date is more than 2 days
after that symbol's last logged trigger date.

READ-ONLY / STANDALONE, same constraints as every tools/copilot/*.py module:
never imports live-bot packages (llm/, execution/, core/, strategies/),
never touches live/.env/data/replay. Writes to exactly ONE file this tool
owns: data/copilot/nearmiss_reversion_log.jsonl. No Discord.

CLI:
    python tools/copilot/nearmiss_reversion_tracker.py             # detect + resolve + readout
    python tools/copilot/nearmiss_reversion_tracker.py --quiet     # detect + resolve only
    python tools/copilot/nearmiss_reversion_tracker.py --selftest  # synthetic method-verification suite
"""
from __future__ import annotations

import argparse
import hashlib
import math
import os
import statistics
import sys
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)
BOT_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))
DATA_DIR = os.path.join(BOT_DIR, "data", "copilot")
LOG_PATH = os.path.join(DATA_DIR, "nearmiss_reversion_log.jsonl")

import confluence_harness as ch  # noqa: E402  -- cost model + liquidity-bucket classification + universe list
import resolve_calls as rc  # noqa: E402  -- HL client + date-keyed candle fetch + JSONL I/O (reused, not reimplemented)

# ---------------------------------------------------------------------------
# LOCKED RULE PARAMETERS -- exactly the drop2d_fixed10pct spec from
# meanrev_rule_test.py / MEANREV_RULE_TEST_RESULTS.md. Never tuned after
# looking at forward results (same discipline as every other harness here).
# ---------------------------------------------------------------------------
N_DAYS = 2                    # trailing-return window AND hold horizon (both "2" in "2-day drop, hold 2 days")
DROP_THRESHOLD = -0.10        # trailing N_DAYS-day return <= -10% triggers
DEDUP_MIN_GAP_DAYS = N_DAYS   # a symbol's next episode must start > this many days after its last trigger date

LONGTAIL_UNIVERSE: List[str] = list(ch._KNOWN_LONGTAIL)  # the 25 longtail alts -- see module docstring "UNIVERSE"

PREREGISTRATION_DATE = "2026-08-05"  # H6 added to PREREGISTRATION.md this date -- see there for the full pre-registration
SIGNIFICANCE_N = 30                   # min INDEPENDENT post-registration triggers before ANY p-value is computed
SINGLE_SYMBOL_DOMINANCE_WARN = 0.50   # mirrors confluence_harness.py's own dominance-flag threshold

DETECT_LOOKBACK_DAYS = 14     # candle-fetch window for detection (need trigger_date AND trigger_date-N_DAYS in range)
CANDLE_FETCH_BUFFER_DAYS = 2  # pad the fetch window past "now" so a just-matured exit candle is included (matches resolve_calls.py)


# ---------------------------------------------------------------------------
# Row identity
# ---------------------------------------------------------------------------

def _row_id(symbol: str, trigger_date_iso: str) -> str:
    """Stable id = hash of (symbol, trigger_date) -- a symbol can only have
    ONE logged episode per trigger date by construction, so this doubles as
    the dedup key against re-detection on a re-run the same day."""
    key = f"{symbol}|{trigger_date_iso}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Pure rule logic (no I/O -- directly selftest-able with synthetic data)
# ---------------------------------------------------------------------------

def trailing_return(entry_close: float, prior_close: float) -> Optional[float]:
    if prior_close is None or prior_close <= 0 or entry_close is None:
        return None
    return entry_close / prior_close - 1.0


def is_trigger(ret_n: Optional[float]) -> bool:
    return ret_n is not None and ret_n <= DROP_THRESHOLD


def should_start_new_episode(last_trigger_date: Optional[date], candidate_date: date) -> bool:
    """True iff `candidate_date` is eligible to start a NEW independent
    episode for a symbol whose last logged trigger was `last_trigger_date`
    (None = no prior trigger -- always eligible). Mirrors
    confluence_harness._dedup_trigger_indices: a new episode is kept only if
    it is STRICTLY MORE than DEDUP_MIN_GAP_DAYS after the last kept one."""
    if last_trigger_date is None:
        return True
    return (candidate_date - last_trigger_date).days > DEDUP_MIN_GAP_DAYS


def find_trigger_for_symbol(
    symbol: str,
    closes: Dict[date, float],
    today_utc: date,
    last_trigger_date: Optional[date],
    liquidity_buckets: Dict[str, Optional[str]],
    now_iso: str,
) -> Optional[dict]:
    """Pure (given `closes`, a date-keyed close dict): returns a new ledger
    row dict if `symbol` is in the trigger state as of the last SETTLED
    (fully closed) daily candle, and is eligible to start a new episode
    (dedup) -- else None. `closes` must be produced by
    `resolve_calls._fetch_daily_closes()` (candle-OPEN-date keys) so the
    entry-time-safe / no-lookahead convention matches the rest of the
    project exactly."""
    settled_dates = [d for d in closes if d < today_utc]
    if not settled_dates:
        return None
    settled_date = max(settled_dates)
    prior_date = settled_date - timedelta(days=N_DAYS)
    if prior_date not in closes:
        return None  # insufficient trailing history this run -- retry next run, never guess
    entry_price = closes[settled_date]
    prior_price = closes[prior_date]
    ret_n = trailing_return(entry_price, prior_price)
    if not is_trigger(ret_n):
        return None
    if not should_start_new_episode(last_trigger_date, settled_date):
        return None  # still inside a prior episode's hold window -- pseudoreplication guard
    bucket = liquidity_buckets.get(symbol)
    cost_bps = ch._cost_bps_for_bucket(bucket)
    return {
        "id": _row_id(symbol, settled_date.isoformat()),
        "symbol": symbol,
        "trigger_date": settled_date.isoformat(),
        "entry_price": entry_price,
        "ret_2d_pct_at_trigger": round(ret_n * 100.0, 4),
        "liquidity_bucket": bucket,
        "cost_bps_rt": cost_bps,
        "logged_ts_utc": now_iso,
        "preregistration_date": PREREGISTRATION_DATE,
        "resolved": False,
        "exit_date": None,
        "exit_price": None,
        "fwd_2d_gross_pct": None,
        "fwd_2d_net_pct": None,
        "schema": 1,
    }


def net_of_cost(gross_pct: float, cost_bps: float) -> float:
    return gross_pct - cost_bps / 100.0


def resolve_row(row: dict, closes: Dict[date, float], now: datetime) -> bool:
    """Pure (given `closes`): mutates `row` in place and returns True iff it
    was newly resolved THIS call. Mirrors resolve_calls.py's maturity rule
    EXACTLY (`now < anchor_dt + timedelta(days=horizon+1)` => not mature) --
    the trigger date IS the entry candle's open date (entry = that candle's
    close), so the horizon+1 day buffer accounts for the exit candle
    (trigger_date + N_DAYS) needing to have itself fully closed, not merely
    opened, before its close price is real."""
    if row.get("resolved"):
        return False
    trig_date = date.fromisoformat(row["trigger_date"])
    anchor_dt = datetime.combine(trig_date, time.min, tzinfo=timezone.utc)
    if now < anchor_dt + timedelta(days=N_DAYS + 1):
        return False  # exit candle not settled yet
    target_date = trig_date + timedelta(days=N_DAYS)
    exit_price = closes.get(target_date)
    if exit_price is None or exit_price <= 0:
        return False  # mature by clock but a data gap this run -- retry next run, never guess/interpolate
    entry_price = row["entry_price"]
    gross_pct = (exit_price / entry_price - 1.0) * 100.0
    net_pct = net_of_cost(gross_pct, row["cost_bps_rt"])
    row["resolved"] = True
    row["exit_date"] = target_date.isoformat()
    row["exit_price"] = exit_price
    row["fwd_2d_gross_pct"] = round(gross_pct, 4)
    row["fwd_2d_net_pct"] = round(net_pct, 4)
    return True


# ---------------------------------------------------------------------------
# Liquidity-bucket classification (cost-model input ONLY -- see module
# docstring "NO BACKFILL, PERIOD"). Static, cached once per process.
# ---------------------------------------------------------------------------
_LIQ_BUCKET_CACHE: Optional[Dict[str, Optional[str]]] = None


def get_liquidity_buckets() -> Dict[str, Optional[str]]:
    global _LIQ_BUCKET_CACHE
    if _LIQ_BUCKET_CACHE is not None:
        return _LIQ_BUCKET_CACHE
    try:
        store = ch.DataStore(universe=list(LONGTAIL_UNIVERSE), timeframe="1d",
                              include_funding_oi=False, include_liq_flag=False)
        out: Dict[str, Optional[str]] = {}
        for sym in LONGTAIL_UNIVERSE:
            df = store.get(sym)
            if df is None or "liquidity_bucket" not in df.columns:
                continue
            nn = df["liquidity_bucket"].dropna()
            if len(nn):
                out[sym] = nn.iloc[-1]
        _LIQ_BUCKET_CACHE = out
    except Exception as e:  # fail soft -- every symbol falls back to the thin/most-conservative default cost
        print(f"[nearmiss_reversion_tracker] liquidity-bucket classification failed ({e}) -- "
              f"all symbols use the thin/most-conservative cost default this run", file=sys.stderr)
        _LIQ_BUCKET_CACHE = {}
    return _LIQ_BUCKET_CACHE


# ---------------------------------------------------------------------------
# I/O layer -- live HLNative fetches, grouped per symbol (same shape as
# resolve_calls.resolve_ledger()).
# ---------------------------------------------------------------------------

def detect_new_triggers(now: datetime, client, existing_rows: List[dict]) -> List[dict]:
    today_utc = now.date()
    last_trigger_by_symbol: Dict[str, date] = {}
    existing_ids = set()
    for r in existing_rows:
        existing_ids.add(r.get("id"))
        try:
            d = date.fromisoformat(r["trigger_date"])
        except (KeyError, ValueError, TypeError):
            continue
        prev = last_trigger_by_symbol.get(r["symbol"])
        if prev is None or d > prev:
            last_trigger_by_symbol[r["symbol"]] = d

    liquidity_buckets = get_liquidity_buckets()
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    start_ms = int((now - timedelta(days=DETECT_LOOKBACK_DAYS)).timestamp() * 1000)
    end_ms = int(now.timestamp() * 1000) + CANDLE_FETCH_BUFFER_DAYS * 86400 * 1000

    new_rows: List[dict] = []
    for symbol in LONGTAIL_UNIVERSE:
        closes = rc._fetch_daily_closes(client, symbol, start_ms, end_ms)
        if not closes:
            print(f"[nearmiss_reversion_tracker] no candle data for {symbol} this run -- skipping detection",
                  file=sys.stderr)
            continue
        row = find_trigger_for_symbol(
            symbol, closes, today_utc, last_trigger_by_symbol.get(symbol), liquidity_buckets, now_iso
        )
        if row is not None and row["id"] not in existing_ids:
            new_rows.append(row)
    return new_rows


def resolve_pending(now: datetime, client, all_rows: List[dict]) -> int:
    pending_by_symbol: Dict[str, List[dict]] = {}
    for r in all_rows:
        if not r.get("resolved"):
            pending_by_symbol.setdefault(r["symbol"], []).append(r)

    n_resolved = 0
    end_ms = int(now.timestamp() * 1000) + CANDLE_FETCH_BUFFER_DAYS * 86400 * 1000
    for symbol, rows in pending_by_symbol.items():
        min_trig = min(date.fromisoformat(r["trigger_date"]) for r in rows)
        start_ms = int(datetime.combine(min_trig, time.min, tzinfo=timezone.utc).timestamp() * 1000)
        closes = rc._fetch_daily_closes(client, symbol, start_ms, end_ms)
        if not closes:
            print(f"[nearmiss_reversion_tracker] no candle data for {symbol} this run -- skipping resolution",
                  file=sys.stderr)
            continue
        for r in rows:
            if resolve_row(r, closes, now):
                n_resolved += 1
    return n_resolved


# ---------------------------------------------------------------------------
# Forward readout -- STRICT gate lives HERE (compute layer), mirrors
# resolve_calls.py / liq_hypothesis_harness.py / oi_hypothesis_harness.py.
# ---------------------------------------------------------------------------

def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _one_sample_p_value(vals: List[float]) -> Optional[float]:
    """Two-sided p-value (normal-approximation one-sample t-test, no scipy
    dependency -- same early-warning-only convention as resolve_calls.py's
    _welch_p_value) that the sample mean differs from 0. Returns None if
    n<2 or the sample has zero variance."""
    n = len(vals)
    if n < 2:
        return None
    mean = statistics.mean(vals)
    sd = statistics.stdev(vals)
    if sd == 0:
        return None
    t = mean / (sd / math.sqrt(n))
    return 2.0 * (1.0 - _normal_cdf(abs(t)))


def compute_forward_readout(all_rows: List[dict]) -> dict:
    """THE gate. Only rows that are resolved, have a non-null
    fwd_2d_net_pct, AND were logged on/after PREREGISTRATION_DATE count.
    Below SIGNIFICANCE_N, `p`/`mean_net_pct`/`confirmed` are left at their
    None/False defaults -- callers (print_summary) must not compute or
    print a verdict themselves; this function is the single source of
    truth for whether H6 is confirmed."""
    forward_rows = [
        r for r in all_rows
        if r.get("resolved")
        and r.get("fwd_2d_net_pct") is not None
        and str(r.get("logged_ts_utc") or "")[:10] >= PREREGISTRATION_DATE
    ]
    n = len(forward_rows)
    by_symbol = Counter(r["symbol"] for r in forward_rows)
    max_share = (max(by_symbol.values()) / n) if n else 0.0
    dominance_flag = max_share >= SINGLE_SYMBOL_DOMINANCE_WARN

    result = {
        "n": n, "dominance_flag": dominance_flag, "max_symbol_share": max_share,
        "p": None, "mean_net_pct": None, "confirmed": False,
    }
    if n < SIGNIFICANCE_N:
        return result

    vals = [r["fwd_2d_net_pct"] for r in forward_rows]
    mean_net = statistics.mean(vals)
    p = _one_sample_p_value(vals)
    result["mean_net_pct"] = mean_net
    result["p"] = p
    result["confirmed"] = bool(p is not None and p < 0.05 and mean_net > 0 and not dominance_flag)
    return result


def print_summary(all_rows: List[dict]) -> None:
    n_total = len(all_rows)
    n_resolved = sum(1 for r in all_rows if r.get("resolved"))
    n_pending = n_total - n_resolved
    print("\n=== H6 NEAR-MISS REVERSION TRACKER -- maturity readout ===")
    print(f"total triggers on file: {n_total}  (resolved={n_resolved}, pending={n_pending})")
    by_symbol = Counter(r["symbol"] for r in all_rows)
    if by_symbol:
        top = ", ".join(f"{s}:{c}" for s, c in sorted(by_symbol.items(), key=lambda kv: -kv[1])[:10])
        print(f"per-symbol trigger counts (top 10): {top}")

    readout = compute_forward_readout(all_rows)
    n = readout["n"]
    if n < SIGNIFICANCE_N:
        print(
            f"n={n}, UNCONFIRMED near-miss, not yet significant / forward-accruing "
            f"(need n>={SIGNIFICANCE_N} independent post-registration ({PREREGISTRATION_DATE}) triggers "
            f"before ANY p-value/verdict is attempted -- see data/copilot/PREREGISTRATION.md H6). "
            f"No mean, p-value, or verdict is computed below this bar."
        )
        return

    mean_net = readout["mean_net_pct"]
    p = readout["p"]
    dom = readout["dominance_flag"]
    p_bit = f"p={p:.3f}" if p is not None else "p unavailable (degenerate variance)"
    print(
        f"n={n} resolved forward triggers; mean net fwd-2d = {mean_net:+.2f}%; {p_bit}; "
        f"max single-symbol share={readout['max_symbol_share']:.0%} "
        f"({'*** DOMINANCE FLAG -- >=50% from one symbol ***' if dom else 'no dominance'})."
    )
    if readout["confirmed"]:
        print(
            "*** H6 CONFIRMED on forward data (n>=30, p<0.05, mean net >0, no dominance). Still: this is a "
            "normal-approximation early-warning p-value -- redo with scipy.stats.ttest_1samp before any actual "
            "go/no-go use, per the same discipline as H1/H2's resolve_calls.py. ***"
        )
    else:
        print("NOT confirmed -- at least one of {p<0.05, mean net >0, no dominance} fails. Early read only.")


# ---------------------------------------------------------------------------
# Selftest (synthetic data only, no network)
# ---------------------------------------------------------------------------

def _d(s: str) -> date:
    return date.fromisoformat(s)


def selftest_planted_trigger_and_exact_resolution() -> bool:
    # t-2 = 2026-08-01 close=120, t (trigger day, settled) = 2026-08-03 close=100
    # -> ret_2d = 100/120 - 1 = -16.667% <= -10% => trigger.
    closes = {
        _d("2026-08-01"): 120.0,
        _d("2026-08-02"): 110.0,
        _d("2026-08-03"): 100.0,
    }
    today_utc = _d("2026-08-04")  # 08-03 is settled (strictly before today)
    row = find_trigger_for_symbol("TEST", closes, today_utc, None, {}, "2026-08-05T00:00:00Z")
    expected_ret = (100.0 / 120.0 - 1.0) * 100.0
    ok1 = (
        row is not None
        and row["trigger_date"] == "2026-08-03"
        and row["entry_price"] == 100.0
        and abs(row["ret_2d_pct_at_trigger"] - round(expected_ret, 4)) < 1e-6
        and row["cost_bps_rt"] == 75.0  # unknown bucket ({}) -> thin/most-conservative default
    )

    # Exit target = trigger_date + 2 days = 2026-08-05, close=90.0 -> gross = -10.0% exactly, net = -10.75%.
    closes_full = dict(closes)
    closes_full[_d("2026-08-04")] = 95.0
    closes_full[_d("2026-08-05")] = 90.0

    row_copy = dict(row) if row else {}
    now_immature = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)  # exit candle (08-05) not yet closed
    resolved_immature = resolve_row(row_copy, closes_full, now_immature) if row else False
    ok2 = row is not None and resolved_immature is False and row_copy.get("resolved") is False

    now_mature = datetime(2026, 8, 6, 1, 0, tzinfo=timezone.utc)  # past 08-03 + 3 days = 08-06 00:00 UTC
    resolved_now = resolve_row(row_copy, closes_full, now_mature) if row else False
    ok3 = (
        row is not None
        and resolved_now is True
        and row_copy.get("resolved") is True
        and row_copy.get("exit_date") == "2026-08-05"
        and row_copy.get("exit_price") == 90.0
        and abs(row_copy.get("fwd_2d_gross_pct", 0) - (-10.0)) < 1e-6
        and abs(row_copy.get("fwd_2d_net_pct", 0) - (-10.75)) < 1e-6
    )
    ok = ok1 and ok2 and ok3
    print(
        f"  [selftest] planted trigger detected + exact 2d close-to-close resolution: {'PASS' if ok else 'FAIL'}"
        f" (trigger_ret={row.get('ret_2d_pct_at_trigger') if row else None}, "
        f"immature_resolved={resolved_immature}, mature_gross={row_copy.get('fwd_2d_gross_pct')}, "
        f"mature_net={row_copy.get('fwd_2d_net_pct')})"
    )
    return ok


def selftest_dedup_within_hold_window() -> bool:
    ok_block_1d = should_start_new_episode(_d("2026-08-03"), _d("2026-08-04")) is False   # 1-day gap: blocked
    ok_block_2d = should_start_new_episode(_d("2026-08-03"), _d("2026-08-05")) is False   # 2-day gap: still blocked (boundary)
    ok_allow_3d = should_start_new_episode(_d("2026-08-03"), _d("2026-08-06")) is True    # 3-day gap: new episode allowed
    ok_first_ever = should_start_new_episode(None, _d("2026-08-01")) is True              # no prior trigger: always allowed
    ok = ok_block_1d and ok_block_2d and ok_allow_3d and ok_first_ever
    print(f"  [selftest] dedup collapses re-triggers within the {N_DAYS}-day hold window into one episode: "
          f"{'PASS' if ok else 'FAIL'}")
    return ok


def selftest_gating_refuses_below_n30() -> bool:
    rows = []
    for i in range(15):  # deliberately n=15 < SIGNIFICANCE_N=30, even with a suspiciously clean positive pattern
        rows.append({
            "symbol": f"SYM{i % 3}",
            "resolved": True,
            "logged_ts_utc": "2026-08-06T00:00:00Z",
            "fwd_2d_net_pct": 1.0 + (i % 5) * 0.1,
        })
    readout = compute_forward_readout(rows)
    ok = readout["n"] == 15 and readout["p"] is None and readout["mean_net_pct"] is None and readout["confirmed"] is False
    print(f"  [selftest] gating refuses to compute p-value/mean/verdict below n=30 "
          f"(n=15, all positive): {'PASS' if ok else 'FAIL'} (readout={readout})")
    return ok


def selftest_preregistration_date_filter() -> bool:
    # A row logged BEFORE the pre-registration date must never count, even if
    # perfectly formed and resolved -- defends against any future backfill attempt.
    rows = [{
        "symbol": "PREDATE", "resolved": True,
        "logged_ts_utc": "2026-08-01T00:00:00Z",  # before PREREGISTRATION_DATE
        "fwd_2d_net_pct": 5.0,
    }]
    readout = compute_forward_readout(rows)
    ok = readout["n"] == 0
    print(f"  [selftest] pre-registration-date filter excludes a pre-dated row: {'PASS' if ok else 'FAIL'}")
    return ok


def run_selftest() -> bool:
    print("=== H6 near-miss reversion tracker -- selftest (synthetic data only, no network) ===")
    checks = [
        selftest_planted_trigger_and_exact_resolution(),
        selftest_dedup_within_hold_window(),
        selftest_gating_refuses_below_n30(),
        selftest_preregistration_date_filter(),
    ]
    n_pass = sum(checks)
    print(f"\n{n_pass}/{len(checks)} checks passed.")
    return n_pass == len(checks)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="WAGMI Co-Pilot H6 near-miss reversion forward tracker -- detects/resolves the "
                     "drop2d_fixed10pct near-miss on LIVE forward data only (read-only, no backfill, gated)."
    )
    ap.add_argument("--quiet", action="store_true", help="Detect + resolve only; skip the readout print")
    ap.add_argument("--selftest", action="store_true", help="Run synthetic method-verification suite and exit")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(0 if run_selftest() else 1)

    now = datetime.now(timezone.utc)
    client = rc._get_hl_client()
    existing_rows = rc._load_jsonl(LOG_PATH)
    new_rows = detect_new_triggers(now, client, existing_rows)
    all_rows = existing_rows + new_rows
    n_resolved = resolve_pending(now, client, all_rows)
    if new_rows or n_resolved:
        rc._write_jsonl(LOG_PATH, all_rows)

    print(
        f"[nearmiss_reversion_tracker] {len(new_rows)} new trigger(s) logged, {n_resolved} row(s) resolved this run "
        f"(total triggers on file: {len(all_rows)})."
    )
    if not args.quiet:
        print_summary(all_rows)


if __name__ == "__main__":
    main()
