"""Sniper counterfactual backtest at user's target leverage range.

User asked: "we can take all the data we've collected from our sniper/sim
and compare it to high leverage. it won't be the same since i won't
manually be closing, but it could help us understand."

This replays every sniper signal against actual chart history with
mechanical exits (SL / scalp TP / swing TP / time stop) at user-specified
leverage. The answer tells us what a discipline-only execution of every
SNIPER/PREMIUM alert would have produced at 5x / 10x / 15x / 20x.

Usage:
    python bot/tools/sniper_counterfactual.py
    python bot/tools/sniper_counterfactual.py --tiers SNIPER,PREMIUM --max-hold 8
    python bot/tools/sniper_counterfactual.py --leverages 5,10,15,20 --sample 500

Caveats:
- Mechanical exits only (no manual early-close simulation)
- Fees modeled at 0.08% round-trip (2x taker_fee_bps)
- Uses CCXT 5m OHLCV as the highest-resolution chart data
- Dedupes signals by (symbol, side, tier) within 30-min cooldown to match alert behavior
- Missing chart data = signal skipped from the analysis
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

_BOT_ROOT = Path(__file__).resolve().parent.parent
if str(_BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOT_ROOT))

SIGNALS_PATH = _BOT_ROOT / "data" / "manual" / "sniper_signals.jsonl"
DEDUP_COOLDOWN_S = 1800  # 30 min — matches alert cooldown


@dataclass
class Signal:
    ts: datetime
    symbol: str
    side: str              # "BUY"/"SELL"
    tier: str
    entry: float
    sl: float
    tp_scalp: float
    tp_swing: float
    confidence: float
    regime: str


@dataclass
class Outcome:
    signal: Signal
    leverage: float
    result: str            # "tp_scalp", "tp_swing", "sl", "time_stop", "no_data"
    exit_price: float
    hold_hours: float
    pnl_pct_on_notional: float  # (move_pct) after fees
    pnl_dollars_on_1k_notional: float  # convenience — what $1000 notional would earn


_TEST_STRATEGY_MARKERS = {"a", "b", "c"}


def _load_signals(path: Path, drop_test_markers: bool = True) -> list[Signal]:
    out: list[Signal] = []
    skipped_test = 0
    skipped_bad = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                skipped_bad += 1
                continue
            try:
                strats = d.get("strategies") or []
                # Filter synthetic test entries (smoke tests wrote ['a','b','c'] etc.)
                if drop_test_markers and strats and all(
                    s in _TEST_STRATEGY_MARKERS for s in strats
                ):
                    skipped_test += 1
                    continue
                ts_s = d.get("timestamp", "")
                if ts_s.endswith("Z"):
                    ts_s = ts_s[:-1] + "+00:00"
                ts = datetime.fromisoformat(ts_s)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                out.append(Signal(
                    ts=ts,
                    symbol=d.get("symbol", "?"),
                    side=d.get("side", "BUY").upper(),
                    tier=d.get("tier", "?"),
                    entry=float(d.get("entry", 0)),
                    sl=float(d.get("sl", 0)),
                    tp_scalp=float(d.get("tp_scalp", 0)),
                    tp_swing=float(d.get("tp_swing", 0)),
                    confidence=float(d.get("confidence", 0)),
                    regime=d.get("regime", ""),
                ))
            except Exception:
                skipped_bad += 1
                continue
    if skipped_test:
        print(f"  filtered {skipped_test} synthetic/test signals (strategies=[a,b,c])")
    if skipped_bad:
        print(f"  skipped {skipped_bad} malformed rows")
    return out


def _dedupe(signals: list[Signal]) -> list[Signal]:
    """Drop signals that fired within DEDUP_COOLDOWN_S of a prior same-setup."""
    last_fired: dict[tuple, datetime] = {}
    out: list[Signal] = []
    for s in signals:
        key = (s.symbol, s.side, s.tier)
        prev = last_fired.get(key)
        if prev is None or (s.ts - prev).total_seconds() >= DEDUP_COOLDOWN_S:
            out.append(s)
            last_fired[key] = s.ts
    return out


def _fetch_ohlcv_for_signals(
    signals: list[Signal], window_hours: int = 24, fresh: bool = False,
) -> dict[str, list[tuple[datetime, float, float, float, float]]]:
    """Pull OHLCV (5m) covering each signal's time window, merged per symbol.

    Returns per-symbol list of (ts, open, high, low, close) sorted by ts.
    """
    # Group signals by symbol
    by_sym: dict[str, list[Signal]] = defaultdict(list)
    for s in signals:
        by_sym[s.symbol].append(s)
    if not by_sym:
        return {}

    try:
        from data.fetcher import DataFetcher
    except Exception as e:
        print(f"ERROR: cannot import fetcher: {e}", file=sys.stderr)
        return {}

    try:
        # Determine span needed across all signals
        earliest_all = min(s.ts for sigs in by_sym.values() for s in sigs)
        latest_all = max(s.ts for sigs in by_sym.values() for s in sigs)
        days_needed = max(int((latest_all - earliest_all).days) + 3, 10)
        fetcher = DataFetcher(backtest_mode=True, backtest_days=days_needed, fresh=fresh)
    except Exception as e:
        print(f"ERROR: cannot init fetcher: {e}", file=sys.stderr)
        return {}

    ohlcv: dict[str, list[tuple]] = {}
    for sym, sigs in by_sym.items():
        earliest = min(s.ts for s in sigs)
        latest = max(s.ts for s in sigs) + timedelta(hours=window_hours)
        print(f"[FETCH] {sym}: {len(sigs)} signals {earliest.date()} -> {latest.date()}", flush=True)
        try:
            df = fetcher.fetch_ohlcv(sym, None, "5m")
            if df is None or df.empty:
                print(f"  (no data for {sym})")
                continue
            rows = []
            # DataFrame has RangeIndex; actual timestamp is in "time" column
            for _, row in df.iterrows():
                ts = row["time"]
                if hasattr(ts, "to_pydatetime"):
                    ts = ts.to_pydatetime()
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                rows.append((
                    ts,
                    float(row["open"]), float(row["high"]),
                    float(row["low"]), float(row["close"]),
                ))
            rows.sort(key=lambda x: x[0])
            ohlcv[sym] = rows
            span_hours = (rows[-1][0] - rows[0][0]).total_seconds() / 3600 if len(rows) >= 2 else 0
            print(f"  fetched {len(rows)} 5m bars spanning {span_hours:.1f}h "
                  f"({rows[0][0].date()} -> {rows[-1][0].date()})")
        except Exception as e:
            print(f"  ERROR fetching {sym}: {e}")
    return ohlcv


def _simulate_signal(
    signal: Signal,
    bars: list[tuple],
    leverage: float,
    max_hold_hours: float,
    fee_round_trip_pct: float = 0.0008,
) -> Outcome:
    """Walk forward from signal.ts; return mechanical outcome."""
    is_long = signal.side in ("BUY", "LONG")
    end_time = signal.ts + timedelta(hours=max_hold_hours)

    # Find first bar at or after signal.ts
    relevant = [b for b in bars if signal.ts <= b[0] <= end_time]
    if len(relevant) < 2:
        return Outcome(
            signal=signal, leverage=leverage, result="no_data",
            exit_price=0.0, hold_hours=0.0,
            pnl_pct_on_notional=0.0, pnl_dollars_on_1k_notional=0.0,
        )

    for bar in relevant:
        ts, op, hi, lo, cl = bar
        # Check SL first (conservative: assume SL hits before TP if bar contains both)
        if is_long:
            if lo <= signal.sl:
                move_pct = (signal.sl - signal.entry) / signal.entry
                pnl_pct = move_pct * leverage - fee_round_trip_pct * leverage
                return Outcome(
                    signal=signal, leverage=leverage, result="sl",
                    exit_price=signal.sl,
                    hold_hours=(ts - signal.ts).total_seconds() / 3600,
                    pnl_pct_on_notional=pnl_pct,
                    pnl_dollars_on_1k_notional=1000 * pnl_pct,
                )
            if hi >= signal.tp_scalp:
                # Determine whether scalp or swing — use the higher one that bar reached
                if hi >= signal.tp_swing:
                    move_pct = (signal.tp_swing - signal.entry) / signal.entry
                    pnl_pct = move_pct * leverage - fee_round_trip_pct * leverage
                    return Outcome(
                        signal=signal, leverage=leverage, result="tp_swing",
                        exit_price=signal.tp_swing,
                        hold_hours=(ts - signal.ts).total_seconds() / 3600,
                        pnl_pct_on_notional=pnl_pct,
                        pnl_dollars_on_1k_notional=1000 * pnl_pct,
                    )
                move_pct = (signal.tp_scalp - signal.entry) / signal.entry
                pnl_pct = move_pct * leverage - fee_round_trip_pct * leverage
                return Outcome(
                    signal=signal, leverage=leverage, result="tp_scalp",
                    exit_price=signal.tp_scalp,
                    hold_hours=(ts - signal.ts).total_seconds() / 3600,
                    pnl_pct_on_notional=pnl_pct,
                    pnl_dollars_on_1k_notional=1000 * pnl_pct,
                )
        else:  # SHORT
            if hi >= signal.sl:
                move_pct = (signal.entry - signal.sl) / signal.entry
                pnl_pct = move_pct * leverage - fee_round_trip_pct * leverage
                return Outcome(
                    signal=signal, leverage=leverage, result="sl",
                    exit_price=signal.sl,
                    hold_hours=(ts - signal.ts).total_seconds() / 3600,
                    pnl_pct_on_notional=pnl_pct,
                    pnl_dollars_on_1k_notional=1000 * pnl_pct,
                )
            if lo <= signal.tp_scalp:
                if lo <= signal.tp_swing:
                    move_pct = (signal.entry - signal.tp_swing) / signal.entry
                    pnl_pct = move_pct * leverage - fee_round_trip_pct * leverage
                    return Outcome(
                        signal=signal, leverage=leverage, result="tp_swing",
                        exit_price=signal.tp_swing,
                        hold_hours=(ts - signal.ts).total_seconds() / 3600,
                        pnl_pct_on_notional=pnl_pct,
                        pnl_dollars_on_1k_notional=1000 * pnl_pct,
                    )
                move_pct = (signal.entry - signal.tp_scalp) / signal.entry
                pnl_pct = move_pct * leverage - fee_round_trip_pct * leverage
                return Outcome(
                    signal=signal, leverage=leverage, result="tp_scalp",
                    exit_price=signal.tp_scalp,
                    hold_hours=(ts - signal.ts).total_seconds() / 3600,
                    pnl_pct_on_notional=pnl_pct,
                    pnl_dollars_on_1k_notional=1000 * pnl_pct,
                )

    # Time stop — exit at last bar's close
    last = relevant[-1]
    cl = last[4]
    if is_long:
        move_pct = (cl - signal.entry) / signal.entry
    else:
        move_pct = (signal.entry - cl) / signal.entry
    pnl_pct = move_pct * leverage - fee_round_trip_pct * leverage
    return Outcome(
        signal=signal, leverage=leverage, result="time_stop",
        exit_price=cl,
        hold_hours=(last[0] - signal.ts).total_seconds() / 3600,
        pnl_pct_on_notional=pnl_pct,
        pnl_dollars_on_1k_notional=1000 * pnl_pct,
    )


def _write_summaries(path: str, summaries: list[dict]) -> None:
    """Write summary rows to JSON or CSV depending on the file extension."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.suffix.lower() == ".csv":
        # Pick union of keys across rows, keep a stable column order for scalars
        preferred = [
            "leverage", "group", "label", "total", "no_data", "playable",
            "win_rate_pct", "wins", "losses", "total_pnl_on_1k",
            "avg_pnl_on_1k", "avg_win_on_1k", "avg_loss_on_1k",
            "avg_hold_hours", "compounded_100_final", "max_drawdown_pct",
        ]
        # Flatten `outcomes` dict to a string since CSV is scalar
        rows = []
        for s in summaries:
            row = {k: s.get(k) for k in preferred}
            outcomes_dict = s.get("outcomes", {})
            row["outcomes"] = json.dumps(outcomes_dict, sort_keys=True) if outcomes_dict else ""
            rows.append(row)
        cols = preferred + ["outcomes"]
        with p.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for row in rows:
                w.writerow(row)
    else:
        with p.open("w", encoding="utf-8") as f:
            json.dump({"summaries": summaries}, f, indent=2, default=str)


def _summary_dict(outcomes: list[Outcome], label: str) -> dict:
    """Return structured summary metrics for a list of outcomes.

    Used by both text output (_summarize) and machine-readable --output json/csv.
    """
    total = len(outcomes)
    no_data = sum(1 for o in outcomes if o.result == "no_data")
    playable = [o for o in outcomes if o.result != "no_data"]
    if not playable:
        return {
            "label": label,
            "total": total,
            "no_data": no_data,
            "playable": 0,
            "win_rate_pct": 0.0,
            "wins": 0,
            "losses": 0,
            "outcomes": {},
            "total_pnl_on_1k": 0.0,
            "avg_pnl_on_1k": 0.0,
            "avg_win_on_1k": 0.0,
            "avg_loss_on_1k": 0.0,
            "avg_hold_hours": 0.0,
            "compounded_100_final": 100.0,
            "max_drawdown_pct": 0.0,
        }
    wins = [o for o in playable if o.pnl_pct_on_notional > 0]
    losses = [o for o in playable if o.pnl_pct_on_notional <= 0]
    by_result = Counter(o.result for o in playable)
    total_pnl = sum(o.pnl_dollars_on_1k_notional for o in playable)
    avg_pnl = total_pnl / len(playable)
    wr = 100 * len(wins) / len(playable)
    avg_w = sum(o.pnl_dollars_on_1k_notional for o in wins) / len(wins) if wins else 0
    avg_l = sum(o.pnl_dollars_on_1k_notional for o in losses) / len(losses) if losses else 0
    avg_hold = sum(o.hold_hours for o in playable) / len(playable)

    equity = 100.0
    peak = 100.0
    max_dd = 0.0
    for o in playable:
        dollar_pnl_on_100 = o.pnl_dollars_on_1k_notional * (equity / 1000.0)
        equity += dollar_pnl_on_100
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    return {
        "label": label,
        "total": total,
        "no_data": no_data,
        "playable": len(playable),
        "win_rate_pct": round(wr, 3),
        "wins": len(wins),
        "losses": len(losses),
        "outcomes": dict(by_result),
        "total_pnl_on_1k": round(total_pnl, 2),
        "avg_pnl_on_1k": round(avg_pnl, 2),
        "avg_win_on_1k": round(avg_w, 2),
        "avg_loss_on_1k": round(avg_l, 2),
        "avg_hold_hours": round(avg_hold, 2),
        "compounded_100_final": round(equity, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
    }


def _summarize(outcomes: list[Outcome], label: str) -> dict:
    """Print a summary and return the structured dict."""
    if not outcomes:
        print(f"{label}: (no outcomes)")
        return {"label": label, "total": 0, "playable": 0}
    s = _summary_dict(outcomes, label)
    if s["playable"] == 0:
        print(f"{label}: {s['total']} signals, all missing data")
        return s

    print(f"\n{label}")
    print(f"  Signals: {s['total']}  (playable: {s['playable']}, no_data: {s['no_data']})")
    print(f"  WR: {s['win_rate_pct']:.1f}% ({s['wins']}W/{s['losses']}L)")
    print(f"  Avg hold: {s['avg_hold_hours']:.1f}h")
    print(f"  Outcomes: {s['outcomes']}")
    print(f"  PnL on $1k notional/trade: ${s['total_pnl_on_1k']:+,.2f} total, "
          f"${s['avg_pnl_on_1k']:+.2f}/trade")
    print(f"  Avg win: ${s['avg_win_on_1k']:+.2f}  Avg loss: ${s['avg_loss_on_1k']:+.2f}")
    print(f"  Expectancy/trade: ${s['avg_pnl_on_1k']:+.2f} on $1k notional")
    print(f"  Compounded $100 start (fixed 1000% notional): "
          f"${s['compounded_100_final']:.2f}  (max DD {s['max_drawdown_pct']:.1f}%)")
    return s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiers", default="SNIPER,PREMIUM",
                    help="Comma list of tiers to include")
    ap.add_argument("--sides", default="BUY,SELL",
                    help="Comma list of sides")
    ap.add_argument("--symbols", default="",
                    help="Comma list of symbols (empty = all)")
    ap.add_argument("--leverages", default="5,10,15,20",
                    help="Comma list of leverages to test")
    ap.add_argument("--max-hold", type=float, default=8.0,
                    help="Max hold time in hours before time-stop")
    ap.add_argument("--sample", type=int, default=0,
                    help="Limit to N most-recent signals (0 = all after dedupe)")
    ap.add_argument("--fresh", action="store_true",
                    help="Skip OHLCV disk cache and re-fetch from exchange")
    ap.add_argument("--min-date", default="",
                    help="Drop signals before this date (YYYY-MM-DD)")
    ap.add_argument("--output", default="",
                    help="Write machine-readable summary to this path "
                         "(.json or .csv; format auto-detected from extension)")
    args = ap.parse_args()

    tiers = set(t.strip() for t in args.tiers.split(",") if t.strip())
    sides = set(s.strip() for s in args.sides.split(",") if s.strip())
    symbols = set(s.strip() for s in args.symbols.split(",") if s.strip())
    leverages = [float(x) for x in args.leverages.split(",") if x.strip()]

    print("=" * 78)
    print(f"  SNIPER COUNTERFACTUAL BACKTEST")
    print(f"  tiers={tiers}  sides={sides}  symbols={symbols or 'all'}")
    print(f"  leverages={leverages}  max_hold={args.max_hold}h  sample={args.sample or 'all'}")
    print("=" * 78)

    print(f"\nLoading {SIGNALS_PATH}...")
    all_sigs = _load_signals(SIGNALS_PATH)
    print(f"  total: {len(all_sigs)}")

    min_date = None
    if args.min_date:
        min_date = datetime.fromisoformat(args.min_date).replace(tzinfo=timezone.utc)

    filtered = [
        s for s in all_sigs
        if s.tier in tiers
        and s.side in sides
        and (not symbols or s.symbol in symbols)
        and (min_date is None or s.ts >= min_date)
    ]
    print(f"  after tier/side/symbol/date filter: {len(filtered)}")

    deduped = _dedupe(filtered)
    print(f"  after 30-min dedupe: {len(deduped)}")

    if args.sample:
        deduped = deduped[-args.sample:]
        print(f"  after --sample={args.sample}: {len(deduped)}")

    if not deduped:
        print("No signals match.")
        return 0

    print("\nFetching chart history per symbol (this takes a minute)...")
    ohlcv = _fetch_ohlcv_for_signals(deduped, window_hours=args.max_hold + 4, fresh=args.fresh)

    # Run each leverage scenario, collect all summaries for optional export
    all_summaries: list[dict] = []
    for lev in leverages:
        print(f"\n--- Leverage: {lev}x ---")
        outcomes: list[Outcome] = []
        for sig in deduped:
            bars = ohlcv.get(sig.symbol, [])
            outcomes.append(_simulate_signal(sig, bars, lev, args.max_hold))
        all_summaries.append(
            {"leverage": lev, "group": "ALL", **_summarize(outcomes, f"ALL ({lev}x, {args.max_hold}h max hold)")}
        )

        # Per-tier breakdown
        by_tier: dict[str, list[Outcome]] = defaultdict(list)
        for o in outcomes:
            by_tier[o.signal.tier].append(o)
        for tier, os_ in sorted(by_tier.items(), key=lambda x: -len(x[1])):
            all_summaries.append(
                {"leverage": lev, "group": f"TIER={tier}", **_summarize(os_, f"  TIER={tier} ({lev}x)")}
            )

        # Per-side breakdown
        by_side: dict[str, list[Outcome]] = defaultdict(list)
        for o in outcomes:
            by_side[o.signal.side].append(o)
        for side, os_ in sorted(by_side.items()):
            all_summaries.append(
                {"leverage": lev, "group": f"SIDE={side}", **_summarize(os_, f"  SIDE={side} ({lev}x)")}
            )

    # Machine-readable export
    if args.output:
        _write_summaries(args.output, all_summaries)
        print(f"\n[OUTPUT] Wrote {len(all_summaries)} summary rows to {args.output}")

    print("\n" + "=" * 78)
    print("BACKTEST COMPLETE")
    print("=" * 78)
    print("\nInterpret with care:")
    print("  - These are MECHANICAL outcomes (no manual early close)")
    print("  - Your real manual trading may differ — skill at early exit can raise WR")
    print("  - Fees modeled at 0.08% round-trip; real Hyperliquid may vary")
    print("  - 5m OHLCV is coarse — actual intraday wicks may hit SL sooner than this suggests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
