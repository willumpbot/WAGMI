"""Resolve the missed-trades (skip) backlog from OHLC — the dead skip-learning loop.

feedback/missed_trade_tracker.py records every gated/skipped signal to
data/missed_trades.jsonl with entry/SL/TP1, but its compute_counterfactuals()
resolver is NEVER called live (and its pending queue is in-memory, lost on
restart), so `would_have_won` / `price_after_*` are None on all rows. The bot
therefore cannot SEE whether its skips were smart. (Confirmed 2026-07-30: the
17h no-trade window's skips were 68% vindicated / ~+18.7R saved — invisible to
the bot.)

This resolves the backlog: for each unresolved row old enough to have an 8h
outcome, reconstruct the forward price path from OHLC (candles AFTER entry) and
apply the SAME TP1-first/SL-first logic as the live tracker, writing outcomes to
data/missed_trades_resolved.jsonl. Read-only w.r.t. trading; measurement + a
learning input (gate value = losses-avoided − alpha-missed).

Run:  python tools/resolve_missed_trades.py [--min-age-hours 8] [--limit N]
"""
import argparse
import json
import os
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SRC = os.path.join("data", "missed_trades.jsonl")
OUT = os.path.join("data", "missed_trades_resolved.jsonl")


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


def _dedupe_setups(rows):
    """Collapse duplicate re-logs of the SAME setup. The scanner re-records each
    skipped signal every scan cycle while the move plays out (~30 rows/setup, max
    91) — counting them all inflates every gate-value readout ~30x (verified
    2026-07-30). Same setup = same symbol+side, entry within 0.4%, timestamp within
    3h. Keep the EARLIEST row per cluster (closest to the real decision)."""
    srt = sorted(rows, key=lambda r: _parse_ts(r.get("timestamp")) or 0)
    clusters = []
    out = []
    for r in srt:
        sym = str(r.get("symbol", "")).upper()
        side = str(r.get("side", "")).upper()
        try:
            entry = float(r.get("entry_price"))
        except (ValueError, TypeError):
            continue
        ts = _parse_ts(r.get("timestamp")) or 0
        matched = False
        for c in clusters:
            if (c["sym"] == sym and c["side"] == side
                    and ts - c["ts"] <= 3 * 3600
                    and c["entry"] > 0 and abs(entry - c["entry"]) / c["entry"] <= 0.004):
                matched = True
                break
        if not matched:
            clusters.append({"sym": sym, "side": side, "entry": entry, "ts": ts})
            out.append(r)
    return out


def _resolve_row(row, closes_after):
    """Apply the live tracker's TP1-first/SL-first logic to a forward close series
    (closes strictly AFTER entry). Mutates + returns the row dict."""
    is_long = str(row.get("side", "")).upper() in ("BUY", "LONG")
    entry = float(row["entry_price"]); sl = float(row["sl_price"]); tp1 = float(row["tp1_price"])
    if not closes_after:
        return None
    row["price_after_1h"] = closes_after[0] if len(closes_after) >= 1 else None
    row["price_after_4h"] = closes_after[3] if len(closes_after) >= 4 else None
    row["price_after_8h"] = closes_after[7] if len(closes_after) >= 8 else None
    row["price_max_favorable"] = (max if is_long else min)(closes_after)
    row["price_max_adverse"] = (min if is_long else max)(closes_after)
    won = None
    for p in closes_after:
        if is_long:
            if p >= tp1:
                won = True; break
            if p <= sl:
                won = False; break
        else:
            if p <= tp1:
                won = True; break
            if p >= sl:
                won = False; break
    row["would_have_hit_tp1"] = any((p >= tp1) if is_long else (p <= tp1) for p in closes_after)
    row["would_have_hit_sl"] = any((p <= sl) if is_long else (p >= sl) for p in closes_after)
    row["would_have_won"] = won
    if won is True:
        row["missed_pnl_estimate"] = ((tp1 - entry) if is_long else (entry - tp1)) / entry * 100
    elif won is False:
        row["missed_pnl_estimate"] = ((sl - entry) if is_long else (entry - sl)) / entry * 100
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-age-hours", type=float, default=8.0)
    ap.add_argument("--limit", type=int, default=0, help="0 = all")
    args = ap.parse_args()

    if not os.path.exists(SRC):
        print(f"no {SRC}"); return
    rows = [json.loads(l) for l in open(SRC, encoding="utf-8") if l.strip()]
    now = time.time()
    cutoff = now - args.min_age_hours * 3600
    # unresolved + old enough + has the entry/SL/TP1 we need
    todo = [r for r in rows
            if r.get("would_have_won") is None
            and all(r.get(k) for k in ("entry_price", "sl_price", "tp1_price", "symbol"))
            and (_parse_ts(r.get("timestamp")) or 0) < cutoff]
    n_raw = len(todo)
    todo = _dedupe_setups(todo)  # collapse ~30x scanner re-logs -> distinct setups
    if args.limit:
        todo = todo[-args.limit:]
    print(f"{len(rows)} total rows | {n_raw} unresolved+aged | {len(todo)} DISTINCT setups (deduped)")
    if not todo:
        return

    from data.fetcher import DataFetcher
    from trading_config import DEFAULT_SYMBOLS
    fetcher = DataFetcher()
    by_sym = defaultdict(list)
    for r in todo:
        by_sym[str(r["symbol"]).upper()].append(r)

    resolved = []
    for sym, srows in by_sym.items():
        cg = DEFAULT_SYMBOLS[sym].coingecko_id if sym in DEFAULT_SYMBOLS else sym.lower()
        try:
            d = fetcher.fetch_multi_timeframe(sym, cg, ["1h"])
            df = d.get("1h")
        except Exception as e:
            print(f"  {sym}: fetch failed ({e}) — skipping {len(srows)}"); continue
        if df is None or df.empty:
            print(f"  {sym}: no OHLC — skipping {len(srows)}"); continue
        times = [t.timestamp() if hasattr(t, "timestamp") else float(t) for t in df["time"]]
        closes = list(df["close"].astype(float))
        for r in srows:
            ets = _parse_ts(r.get("timestamp"))
            if ets is None:
                continue
            # forward closes: candles that closed AFTER entry (next 8h)
            fwd = [closes[i] for i in range(len(times)) if times[i] > ets][:8]
            rr = _resolve_row(dict(r), fwd)
            if rr is not None:
                resolved.append(rr)

    # Overwrite (derived file) — regenerate deduped each run so readouts stay accurate.
    with open(OUT, "w", encoding="utf-8") as f:
        for r in resolved:
            f.write(json.dumps(r, default=str) + "\n")

    # summary — the skip-vindication the bot was blind to
    scored = [r for r in resolved if r.get("would_have_won") is not None]
    won = [r for r in scored if r["would_have_won"]]
    lost = [r for r in scored if not r["would_have_won"]]
    saved = sum(abs(r.get("missed_pnl_estimate") or 0) for r in lost)   # losses avoided
    missed = sum(abs(r.get("missed_pnl_estimate") or 0) for r in won)   # alpha missed
    print(f"resolved {len(scored)} -> {OUT}")
    print(f"  skips VINDICATED (would've lost): {len(lost)}/{len(scored)} = {100*len(lost)/max(1,len(scored)):.0f}%")
    print(f"  losses AVOIDED: +{saved:.1f}% | alpha MISSED: -{missed:.1f}% | NET GATE VALUE: {saved-missed:+.1f}%")


if __name__ == "__main__":
    main()
