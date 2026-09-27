"""Resolve the LLM-exit-agent counterfactual — was cutting the trade worth it?

The Exit Agent (LLM_EXIT_AGENT / LLM_EXIT_HIGH / LLM_EXIT_CRITICAL close reasons)
force-closes positions ahead of their original SL/TP1/TP2 based on a live
thesis-invalidation read. Its P&L impact has never been measured: nothing
compares the REALIZED exit against what would have happened had the position
simply been left to run to its own original stop/targets. That means the
exit agent's net value (alpha protected on losers vs. alpha cut short on
winners) has required manual archaeology instead of being live-measurable.

This mirrors tools/resolve_missed_trades.py's structure and moat rules:
  - reads the authoritative closed-trade ledger (data/trade_ledger.csv),
  - joins each LLM-exit row against its original SL/TP1/TP2 by matching the
    corresponding TRADE_OPENED event in data/trade_events.jsonl (the ledger
    itself carries no reliable position_id -- 5/29 populated in practice --
    so the join is by symbol+side+entry-price+approx-open-time, same
    proximity-matching idea as resolve_missed_trades.py's setup dedupe),
  - reconstructs the forward price path from OHLC candles strictly AFTER the
    actual exit, and applies the SAME TP-first/SL-first logic as the live
    missed-trade resolver (extended with a TP2 leg, since a real position has
    two targets): whichever of SL or TP2 is touched first in the forward
    close series decides the counterfactual fate; TP1 is tracked only as an
    informational way-point, since modeling partial TP1 closes + breakeven-
    ratchet SL movement is out of scope for a pure measurement tool.

Read-only w.r.t. trading -- this is a measurement instrument, not an execution
path. Never touches data/replay/ (sandbox copies). Writes/overwrites
data/llm_exits_resolved.jsonl on every run so readouts stay current.

Run:  python tools/resolve_llm_exits.py [--min-age-hours 1] [--limit N] [--top-n 3]
"""
import argparse
import csv
import json
import os
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

LEDGER = os.path.join("data", "trade_ledger.csv")
EVENTS = os.path.join("data", "trade_events.jsonl")
OUT = os.path.join("data", "llm_exits_resolved.jsonl")

# The 3 close reasons routed through the discretionary LLM exit layer
# (confirmed against core/position_wiring.py ~L850-895 and core/close_types.py
# _FULL_CLOSE registration ~L3883-3893).
LLM_EXIT_REASONS = {"LLM_EXIT_AGENT", "LLM_EXIT_HIGH", "LLM_EXIT_CRITICAL"}

# Dust-floor: rows with fees < $0.5 are near-zero-notional exploration slices
# that don't represent a real economic decision (same floor used elsewhere in
# the project's ledger analysis -- 274 raw rows collapse to 62 real trades).
DUST_FLOOR_FEES = 0.5

# Tolerance for matching a ledger close row back to its TRADE_OPENED event.
_OPEN_TIME_TOL_S = 30 * 60      # 30 minutes
_OPEN_PRICE_TOL_PCT = 0.01      # 1%


def _parse_ts(v):
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        try:
            import datetime as dt
            return dt.datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
        except Exception:
            return None


def _load_ledger_llm_exits():
    """Read data/trade_ledger.csv, keep dust-floor real trades closed by the
    LLM exit agent."""
    if not os.path.exists(LEDGER):
        return []
    rows = []
    with open(LEDGER, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("exit_type") not in LLM_EXIT_REASONS:
                continue
            try:
                fees = float(row.get("fees") or 0)
            except (ValueError, TypeError):
                fees = 0.0
            if fees < DUST_FLOOR_FEES:
                continue
            try:
                entry = float(row["entry_price"])
                exit_px = float(row["exit_price"])
                gross = float(row["gross_pnl"])
                net = float(row["net_pnl"])
                hold_hours = float(row.get("hold_hours") or 0)
                close_ts = _parse_ts(row["timestamp"])
            except (KeyError, ValueError, TypeError):
                continue
            side = str(row.get("side", "")).upper()
            if side not in ("LONG", "SHORT") or close_ts is None:
                continue
            rows.append({
                "trade_id": row.get("trade_id", ""),
                "symbol": str(row.get("symbol", "")).upper(),
                "side": side,
                "exit_type": row.get("exit_type", ""),
                "close_ts": close_ts,
                "hold_hours": hold_hours,
                "entry_price": entry,
                "exit_price": exit_px,
                "gross_pnl": gross,
                "fees": fees,
                "realized_pnl": net,
                "position_id": row.get("position_id", ""),
            })
    return rows


def _load_open_events():
    """Index every TRADE_OPENED event from data/trade_events.jsonl by symbol,
    for proximity-matching the original SL/TP1/TP2 onto each ledger close row.
    trade_events.jsonl carries no position_id (confirmed: 0/150574 rows), so
    this is the only source of original targets."""
    idx = defaultdict(list)
    if not os.path.exists(EVENTS):
        return idx
    with open(EVENTS, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("event") != "TRADE_OPENED":
                continue
            ts = _parse_ts(d.get("timestamp"))
            if ts is None:
                continue
            try:
                entry = float(d.get("entry"))
                sl = float(d.get("sl"))
                tp1 = float(d.get("tp1"))
                tp2 = float(d.get("tp2"))
            except (TypeError, ValueError):
                continue
            side = str(d.get("side", "")).upper()
            if side not in ("LONG", "SHORT"):
                continue
            sym = str(d.get("symbol", "")).upper()
            idx[sym].append({"ts": ts, "side": side, "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2})
    return idx


def _match_open(row, open_idx):
    """Find the TRADE_OPENED event that produced this ledger close row.
    Best match = closest open-time to (close_ts - hold_hours) among same
    symbol+side+entry-price-within-tolerance candidates."""
    approx_open_ts = row["close_ts"] - row["hold_hours"] * 3600
    candidates = open_idx.get(row["symbol"], [])
    best = None
    best_dt = None
    for c in candidates:
        if c["side"] != row["side"]:
            continue
        if c["entry"] <= 0:
            continue
        price_diff_pct = abs(c["entry"] - row["entry_price"]) / c["entry"]
        if price_diff_pct > _OPEN_PRICE_TOL_PCT:
            continue
        dt = abs(c["ts"] - approx_open_ts)
        if dt > _OPEN_TIME_TOL_S:
            continue
        if best is None or dt < best_dt:
            best, best_dt = c, dt
    if best is None:
        return None
    return {
        "sl_orig": best["sl"], "tp1_orig": best["tp1"], "tp2_orig": best["tp2"],
        "match_time_diff_s": round(best_dt, 1),
        "match_entry_diff_pct": round(abs(best["entry"] - row["entry_price"]) / best["entry"] * 100, 4),
    }


def _resolve_cf(row, closes_after):
    """Apply TP-first/SL-first logic (mirrors resolve_missed_trades.py's
    _resolve_row), extended with a TP2 leg: whichever of SL/TP2 is touched
    first in the forward close series decides the counterfactual fate. TP1 is
    tracked as an informational way-point only (no partial-close modeling)."""
    if not closes_after:
        return None
    is_long = row["side"] == "LONG"
    sl, tp1, tp2 = row["sl_orig"], row["tp1_orig"], row["tp2_orig"]
    hit_tp1 = False
    outcome = None
    for p in closes_after:
        if is_long:
            if p <= sl:
                outcome = "SL"; break
            if p >= tp1:
                hit_tp1 = True
            if p >= tp2:
                outcome = "TP2"; break
        else:
            if p >= sl:
                outcome = "SL"; break
            if p <= tp1:
                hit_tp1 = True
            if p <= tp2:
                outcome = "TP2"; break

    cf_status = outcome or "OPEN_AT_HORIZON"
    if outcome == "SL":
        cf_exit_price = sl
    elif outcome == "TP2":
        cf_exit_price = tp2
    else:
        cf_exit_price = closes_after[-1]

    entry = row["entry_price"]
    diff_real = (row["exit_price"] - entry) if is_long else (entry - row["exit_price"])
    diff_cf = (cf_exit_price - entry) if is_long else (entry - cf_exit_price)
    qty_implied = (row["gross_pnl"] / diff_real) if diff_real not in (0, None) else None

    gross_cf = qty_implied * diff_cf if qty_implied is not None else None
    # Approximation: reuse the realized trade's $ fees as the round-trip fee
    # proxy for the counterfactual (same notional/qty; funding drift over the
    # extra hold time is not modeled). Documented simplification, not a
    # full backtest engine.
    net_cf = (gross_cf - row["fees"]) if gross_cf is not None else None
    delta = (net_cf - row["realized_pnl"]) if net_cf is not None else None

    # Floored at 0: standard MFE semantics -- "best favorable move seen after
    # the exit," not a signed drift (a price that only ever worsened relative
    # to the exit has MFE=0, same convention as Position.mfe elsewhere).
    mfe_price = max(0.0, (max(closes_after) - row["exit_price"]) if is_long
                    else (row["exit_price"] - min(closes_after)))
    mfe_dollars = qty_implied * mfe_price if qty_implied is not None else None

    out = dict(row)
    out.update({
        "cf_status": cf_status,
        "would_have_hit_tp1": hit_tp1 or outcome == "TP2",
        "would_have_hit_tp2": outcome == "TP2",
        "would_have_hit_sl": outcome == "SL",
        "cf_exit_price": cf_exit_price,
        "qty_implied": qty_implied,
        "cf_pnl_if_held": net_cf,
        "delta": delta,
        "mfe_after_exit_price": mfe_price,
        "mfe_after_exit_dollars": mfe_dollars,
        "category": "winner_cut" if row["realized_pnl"] > 0 else "loser_cut",
    })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-age-hours", type=float, default=1.0,
                     help="skip closes younger than this (not enough forward data yet)")
    ap.add_argument("--limit", type=int, default=0, help="0 = all")
    ap.add_argument("--top-n", type=int, default=3,
                     help="outliers (by |delta|) to also report ex- in the summary")
    args = ap.parse_args()

    rows = _load_ledger_llm_exits()
    now = time.time()
    cutoff = now - args.min_age_hours * 3600
    rows = [r for r in rows if r["close_ts"] < cutoff]
    if not rows:
        print(f"no LLM-exit dust-floor rows (>= ${DUST_FLOOR_FEES} fees) found in {LEDGER}")
        return
    if args.limit:
        rows = rows[-args.limit:]
    print(f"{len(rows)} LLM-exit rows (dust-floor, aged >= {args.min_age_hours}h) to resolve")

    open_idx = _load_open_events()

    matched, unmatched = [], []
    for r in rows:
        m = _match_open(r, open_idx)
        if m is None:
            unmatched.append(r)
        else:
            r2 = dict(r)
            r2.update(m)
            matched.append(r2)

    print(f"  {len(matched)}/{len(rows)} matched to an original TRADE_OPENED event "
          f"(sl/tp1/tp2 recovered); {len(unmatched)} unmatched (no original targets found)")

    from data.fetcher import DataFetcher
    from trading_config import DEFAULT_SYMBOLS
    fetcher = DataFetcher()
    by_sym = defaultdict(list)
    for r in matched:
        by_sym[r["symbol"]].append(r)

    resolved = []
    no_ohlc = []
    for sym, srows in by_sym.items():
        cg = DEFAULT_SYMBOLS[sym].coingecko_id if sym in DEFAULT_SYMBOLS else sym.lower()
        try:
            d = fetcher.fetch_multi_timeframe(sym, cg, ["1h"])
            df = d.get("1h")
        except Exception as e:
            print(f"  {sym}: fetch failed ({e}) -- skipping {len(srows)}")
            no_ohlc.extend(srows)
            continue
        if df is None or df.empty:
            print(f"  {sym}: no OHLC -- skipping {len(srows)}")
            no_ohlc.extend(srows)
            continue
        times = [t.timestamp() if hasattr(t, "timestamp") else float(t) for t in df["time"]]
        closes = list(df["close"].astype(float))
        for r in srows:
            fwd = [closes[i] for i in range(len(times)) if times[i] > r["close_ts"]]
            rr = _resolve_cf(r, fwd)
            if rr is not None:
                resolved.append(rr)
            else:
                no_ohlc.append(r)

    # Overwrite (derived file) -- regenerate each run so readouts stay accurate.
    with open(OUT, "w", encoding="utf-8") as f:
        for r in resolved:
            f.write(json.dumps(r, default=str) + "\n")
        for r in unmatched:
            f.write(json.dumps(dict(r, cf_status="UNMATCHED_NO_ORIGINAL_TARGETS"), default=str) + "\n")
        for r in no_ohlc:
            f.write(json.dumps(dict(r, cf_status="NO_FORWARD_OHLC"), default=str) + "\n")

    print(f"resolved {len(resolved)} -> {OUT}")
    if not resolved:
        return

    def _summarize(label, subset):
        scored = [r for r in subset if r.get("delta") is not None]
        if not scored:
            print(f"  {label}: n=0")
            return
        total = sum(r["delta"] for r in scored)
        winners = [r for r in scored if r["category"] == "winner_cut"]
        losers = [r for r in scored if r["category"] == "loser_cut"]
        w_delta = sum(r["delta"] for r in winners)
        l_delta = sum(r["delta"] for r in losers)
        print(f"  {label}: n={len(scored)} | NET DELTA (cf - realized) = {total:+.2f}")
        print(f"    winners-cut (n={len(winners)}): alpha left on table = {w_delta:+.2f}")
        print(f"    losers-cut  (n={len(losers)}): would-be P&L delta   = {l_delta:+.2f} "
              f"(negative = losses avoided by cutting early)")

    print(f"\n=== LLM Exit Agent counterfactual summary ===")
    _summarize("ALL", resolved)

    if args.top_n > 0 and len(resolved) > args.top_n:
        scored = [r for r in resolved if r.get("delta") is not None]
        outliers = sorted(scored, key=lambda r: abs(r["delta"]), reverse=True)[:args.top_n]
        outlier_ids = {r["trade_id"] for r in outliers}
        ex_outliers = [r for r in resolved if r["trade_id"] not in outlier_ids]
        print(f"\n  top {args.top_n} outliers by |delta|:")
        for r in outliers:
            print(f"    {r['trade_id']} {r['symbol']} {r['side']} {r['exit_type']} "
                  f"realized={r['realized_pnl']:+.2f} cf={r.get('cf_pnl_if_held'):+.2f} "
                  f"delta={r['delta']:+.2f} status={r['cf_status']}")
        _summarize("EX-OUTLIERS", ex_outliers)

    if unmatched:
        print(f"\n  {len(unmatched)} rows had no original TRADE_OPENED match "
              f"(targets unrecoverable) -- see {OUT} (cf_status=UNMATCHED_NO_ORIGINAL_TARGETS)")
    if no_ohlc:
        print(f"  {len(no_ohlc)} rows had no usable forward OHLC -- see {OUT} "
              f"(cf_status=NO_FORWARD_OHLC)")


if __name__ == "__main__":
    main()
