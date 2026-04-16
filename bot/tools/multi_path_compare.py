"""Multi-Path Performance Aggregator.

Reads every tracking stream the bot maintains and produces a unified
"which path would have been most profitable" report. Pure read-only —
does not modify any trading state.

Streams read:
  - data/trades.csv               - live executed trades (ensemble + sniper)
  - data/shadow_ledger.csv        - disabled-strategy shadow signals
  - data/manual/sniper_signals.jsonl    - every sniper alert fired
  - data/manual/sniper_rejections.jsonl - rejected signals + reason
  - data/manual/anticipatory_history.jsonl - pre-staged entries
  - data/manual/pa_sim_trades.jsonl - price-action sim trades
  - data/manual/sim_trades.jsonl   - sniper sim trades
  - data/manual/trade_journal.jsonl - user's manual trades
  - data/llm/counterfactual_resolved.jsonl - "would this have won" resolutions

Usage:
    python bot/tools/multi_path_compare.py                  # 30-day report
    python bot/tools/multi_path_compare.py --days 7         # last 7 days
    python bot/tools/multi_path_compare.py --all            # full history
    python bot/tools/multi_path_compare.py --focus ensemble # one stream deep dive
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

DATA_DIR = Path("data")
MANUAL_DIR = DATA_DIR / "manual"
LLM_DIR = DATA_DIR / "llm"


def _parse_ts(ts_str: str) -> datetime | None:
    """Parse an ISO timestamp, tolerant of trailing Z or missing tz."""
    if not ts_str:
        return None
    try:
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


@dataclass
class PathStats:
    name: str
    n: int = 0
    wins: int = 0
    losses: int = 0
    pnl: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    win_rate: float = 0.0
    rr: float = 0.0
    note: str = ""

    def summary(self) -> str:
        return (
            f"{self.name:28s}  n={self.n:5d}  WR={self.win_rate*100:5.1f}%  "
            f"avgW=${self.avg_win:+6.2f}  avgL=${self.avg_loss:+6.2f}  "
            f"R:R={self.rr:4.2f}  net=${self.pnl:+9.2f}  {self.note}"
        )


def _compute_stats(name: str, pnls: list[float], note: str = "") -> PathStats:
    wins_list = [p for p in pnls if p > 0]
    losses_list = [p for p in pnls if p <= 0]
    n = len(pnls)
    avg_w = sum(wins_list) / len(wins_list) if wins_list else 0.0
    avg_l = sum(losses_list) / len(losses_list) if losses_list else 0.0
    rr = -avg_w / avg_l if avg_l < 0 else 0.0
    wr = len(wins_list) / n if n else 0.0
    return PathStats(
        name=name, n=n,
        wins=len(wins_list), losses=len(losses_list),
        pnl=sum(pnls),
        avg_win=avg_w, avg_loss=avg_l,
        win_rate=wr, rr=rr,
        note=note,
    )


def load_live_trades(cutoff: datetime | None) -> list[dict]:
    """Load trades.csv and filter by cutoff."""
    out = []
    path = DATA_DIR / "trades.csv"
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            try:
                ts = _parse_ts(r.get("timestamp", ""))
                if cutoff and ts and ts < cutoff:
                    continue
                r["_pnl"] = float(r.get("pnl", 0) or 0)
                r["_ts"] = ts
                out.append(r)
            except (ValueError, TypeError):
                continue
    return out


def load_jsonl(path: Path, cutoff: datetime | None, ts_field: str = "timestamp") -> list[dict]:
    out = []
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = _parse_ts(d.get(ts_field, "") or d.get("opened_at", "") or d.get("created_at", "") or d.get("resolved_at", ""))
            if cutoff and ts and ts < cutoff:
                continue
            d["_ts"] = ts
            out.append(d)
    return out


def load_shadow_ledger(cutoff: datetime | None) -> list[dict]:
    out = []
    path = DATA_DIR / "shadow_ledger.csv"
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            try:
                # shadow_ledger uses unix epoch timestamps
                ts_val = r.get("timestamp", "")
                ts = None
                if ts_val:
                    try:
                        ts = datetime.fromtimestamp(float(ts_val), tz=timezone.utc)
                    except (ValueError, TypeError):
                        ts = _parse_ts(ts_val)
                if cutoff and ts and ts < cutoff:
                    continue
                r["_ts"] = ts
                try:
                    r["_actual_return"] = float(r.get("actual_return", "") or 0)
                except (ValueError, TypeError):
                    r["_actual_return"] = 0.0
                out.append(r)
            except Exception:
                continue
    return out


def analyze(days: int | None, focus: str | None) -> None:
    cutoff = None
    if days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    window_label = f"last {days} days" if days else "all history"
    print(f"\n{'=' * 82}")
    print(f"  MULTI-PATH COMPARISON — {window_label}")
    print(f"  cutoff: {cutoff.isoformat() if cutoff else 'none'}")
    print('=' * 82)

    all_stats: list[PathStats] = []

    # ── 1. Live trades (trades.csv) — split by strategy ──
    live = load_live_trades(cutoff)
    ensemble = [r for r in live if r.get("strategy") == "ensemble"]
    sniper = [r for r in live if r.get("strategy") == "sniper_premium"]
    all_stats.append(_compute_stats(
        "1. LIVE ensemble",
        [r["_pnl"] for r in ensemble],
        f"({len(ensemble)} executed trades)",
    ))
    all_stats.append(_compute_stats(
        "2. LIVE sniper_premium",
        [r["_pnl"] for r in sniper],
        f"(executed before SNIPER_AUTO_EXECUTE=false)",
    ))

    # ── 3. Sniper sim (paper trades from sniper alerts) ──
    sim = load_jsonl(MANUAL_DIR / "sim_trades.jsonl", cutoff, ts_field="opened_at")
    # Dedupe by trade_id (file has dupes)
    sim_seen = {}
    for t in sim:
        sim_seen[t.get("trade_id", "?")] = t
    sim = list(sim_seen.values())
    sim_closed = [t for t in sim if t.get("exit_price") is not None]
    all_stats.append(_compute_stats(
        "3. SNIPER sim (paper)",
        [float(t.get("pnl_usd", 0) or 0) for t in sim_closed],
        f"({len(sim_closed)} closed of {len(sim)} unique)",
    ))

    # ── 4. PA sim (price-action simulator) ──
    pa_sim = load_jsonl(MANUAL_DIR / "pa_sim_trades.jsonl", cutoff, ts_field="opened_at")
    pa_seen = {}
    for t in pa_sim:
        pa_seen[t.get("trade_id", "?")] = t
    pa_sim = list(pa_seen.values())
    pa_closed = [t for t in pa_sim if t.get("exit_price") is not None or t.get("result") is not None]
    all_stats.append(_compute_stats(
        "4. PA sim (price-action)",
        [float(t.get("pnl_usd", 0) or 0) for t in pa_closed],
        f"({len(pa_closed)} closed)",
    ))

    # ── 5. Trade journal (user's manual trades) ──
    journal = load_jsonl(MANUAL_DIR / "trade_journal.jsonl", cutoff, ts_field="entry_time")
    journal_closed = [t for t in journal if t.get("status") == "CLOSED" or t.get("exit_price") is not None]
    all_stats.append(_compute_stats(
        "5. USER journal (manual)",
        [float(t.get("pnl", 0) or 0) for t in journal_closed],
        f"({len(journal_closed)} closed — log more!)" if len(journal_closed) < 5 else f"({len(journal_closed)} closed)",
    ))

    # ── 6. Shadow ledger (disabled-strategy shadow signals) ──
    shadow = load_shadow_ledger(cutoff)
    shadow_resolved = [r for r in shadow if r.get("resolved") == "true" or r.get("resolved") == "True"]
    # Actual return here is a percentage of entry
    shadow_returns = [r["_actual_return"] for r in shadow_resolved if r["_actual_return"] != 0]
    all_stats.append(_compute_stats(
        "6. SHADOW ledger (% ret)",
        shadow_returns,
        f"({len(shadow_resolved)} resolved, returns in %)",
    ))

    # ── 7. Sniper signals (raw alert stream) ──
    sniper_sigs = load_jsonl(MANUAL_DIR / "sniper_signals.jsonl", cutoff)
    by_tier = Counter(s.get("tier", "UNKNOWN") for s in sniper_sigs)
    all_stats.append(PathStats(
        name="7. SNIPER alerts",
        n=len(sniper_sigs),
        note=f"by tier: {dict(by_tier.most_common(5))}",
    ))

    # ── 8. Sniper rejections (what got killed and why) ──
    rejs = load_jsonl(MANUAL_DIR / "sniper_rejections.jsonl", cutoff)
    by_reason = Counter(r.get("reason", "unknown") for r in rejs)
    all_stats.append(PathStats(
        name="8. SNIPER rejections",
        n=len(rejs),
        note=f"top reasons: {dict(by_reason.most_common(3))}",
    ))

    # ── 9. Anticipatory history ──
    ant = load_jsonl(MANUAL_DIR / "anticipatory_history.jsonl", cutoff, ts_field="resolved_at")
    ant_by_outcome = Counter(a.get("outcome", "unknown") for a in ant)
    all_stats.append(PathStats(
        name="9. ANTICIPATORY",
        n=len(ant),
        note=f"outcomes: {dict(ant_by_outcome.most_common())}",
    ))

    # ── 10. Counterfactuals — the killer metric ──
    cf_path = LLM_DIR / "counterfactual_resolved.jsonl"
    cf_hits = 0
    cf_misses = 0
    cf_sample = 0
    cf_skip_reasons = Counter()
    if cf_path.exists():
        with cf_path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = _parse_ts(d.get("created_at", ""))
                if cutoff and ts and ts < cutoff:
                    continue
                if not d.get("resolved"):
                    continue
                cf_sample += 1
                if d.get("would_hit_tp1"):
                    cf_hits += 1
                elif d.get("would_hit_sl"):
                    cf_misses += 1
                cf_skip_reasons[d.get("skip_reason", "unknown")] += 1
    cf_rate = cf_hits / cf_sample if cf_sample else 0
    note = f"would-have-won rate: {cf_rate*100:.1f}% ({cf_hits} hit TP1, {cf_misses} hit SL, {cf_sample - cf_hits - cf_misses} indeterminate)"
    all_stats.append(PathStats(
        name="10. COUNTERFACTUALS (skipped signals)",
        n=cf_sample,
        note=note,
    ))

    # ── Print master table ──
    print("\nPer-path summary:\n")
    for s in all_stats:
        if s.n > 0 or s.pnl != 0:
            if s.pnl != 0 or s.wins > 0:
                print(f"  {s.summary()}")
            else:
                print(f"  {s.name:28s}  n={s.n:5d}  {s.note}")
        else:
            print(f"  {s.name:28s}  (no data)")

    # ── Top rejection reasons (most-killed signals) ──
    if by_reason and not focus:
        print(f"\nTop sniper rejection reasons (what we're killing most):")
        for reason, count in by_reason.most_common(10):
            print(f"  {count:6d}  {reason}")

    # ── Counterfactual skip reasons ──
    if cf_skip_reasons and not focus:
        print(f"\nTop counterfactual skip reasons (why we said no):")
        for reason, count in cf_skip_reasons.most_common(10):
            print(f"  {count:6d}  {reason}")

    # ── Focus mode: deep-dive one stream ──
    if focus:
        print(f"\n=== FOCUS: {focus} ===\n")
        if focus == "ensemble":
            _focus_ensemble(ensemble)
        elif focus == "sniper":
            _focus_sniper(sniper, sim_closed)
        elif focus == "counterfactuals":
            _focus_counterfactuals(cf_path, cutoff)
        else:
            print(f"Unknown focus: {focus}")

    # ── Bottom-line summary ──
    print("\n" + "=" * 82)
    print("  INTERPRETATION")
    print("=" * 82)
    if any(s.pnl != 0 for s in all_stats[:5]):
        top_profit = max(all_stats[:5], key=lambda s: s.pnl)
        top_volume = max(all_stats[:5], key=lambda s: s.n)
        print(f"  Most profitable path: {top_profit.name} (net ${top_profit.pnl:+.2f})")
        print(f"  Highest-volume path:  {top_volume.name} ({top_volume.n} trades)")
    if cf_sample > 20:
        print(
            f"  Counterfactual read:  "
            f"{cf_rate*100:.0f}% of REJECTED signals would have hit TP1. "
            f"{'Alpha is being left on the table.' if cf_rate > 0.5 else 'Rejections are working.'}"
        )
    print()


def _focus_ensemble(trades: list[dict]) -> None:
    by_sym = defaultdict(lambda: {"n": 0, "w": 0, "pnl": 0.0})
    by_driver = defaultdict(lambda: {"n": 0, "w": 0, "pnl": 0.0})
    by_side = defaultdict(lambda: {"n": 0, "w": 0, "pnl": 0.0})
    for t in trades:
        pnl = t["_pnl"]
        sym = t.get("symbol", "?")
        drv = t.get("primary_driver", "") or "(empty)"
        side = t.get("side", "?")
        for bucket, key in ((by_sym, sym), (by_driver, drv), (by_side, side)):
            bucket[key]["n"] += 1
            bucket[key]["pnl"] += pnl
            if pnl > 0:
                bucket[key]["w"] += 1

    print("  By symbol:")
    for k, v in sorted(by_sym.items(), key=lambda x: -x[1]["pnl"]):
        wr = 100 * v["w"] / v["n"] if v["n"] else 0
        print(f"    {k:6s} n={v['n']:3d}  WR={wr:5.1f}%  net=${v['pnl']:+8.2f}")
    print("\n  By side:")
    for k, v in sorted(by_side.items()):
        wr = 100 * v["w"] / v["n"] if v["n"] else 0
        print(f"    {k:6s} n={v['n']:3d}  WR={wr:5.1f}%  net=${v['pnl']:+8.2f}")
    print("\n  By driver:")
    for k, v in sorted(by_driver.items(), key=lambda x: -x[1]["pnl"]):
        wr = 100 * v["w"] / v["n"] if v["n"] else 0
        print(f"    {k:25s} n={v['n']:3d}  WR={wr:5.1f}%  net=${v['pnl']:+8.2f}")


def _focus_sniper(live_sniper: list[dict], sim_sniper: list[dict]) -> None:
    print(f"  Live sniper trades: {len(live_sniper)}")
    if live_sniper:
        by_k = defaultdict(lambda: {"n": 0, "w": 0, "pnl": 0.0})
        for t in live_sniper:
            k = f"{t.get('symbol','?')} {t.get('side','?')}"
            by_k[k]["n"] += 1
            by_k[k]["pnl"] += t["_pnl"]
            if t["_pnl"] > 0:
                by_k[k]["w"] += 1
        for k, v in sorted(by_k.items(), key=lambda x: -x[1]["pnl"]):
            wr = 100 * v["w"] / v["n"] if v["n"] else 0
            print(f"    {k:12s} n={v['n']:3d}  WR={wr:5.1f}%  net=${v['pnl']:+7.2f}")

    print(f"\n  Sim sniper trades: {len(sim_sniper)}")
    if sim_sniper:
        by_k = defaultdict(lambda: {"n": 0, "w": 0, "pnl": 0.0})
        for t in sim_sniper:
            k = f"{t.get('symbol','?')} {t.get('side','?')}"
            by_k[k]["n"] += 1
            by_k[k]["pnl"] += float(t.get("pnl_usd", 0) or 0)
            if float(t.get("pnl_usd", 0) or 0) > 0:
                by_k[k]["w"] += 1
        for k, v in sorted(by_k.items(), key=lambda x: -x[1]["pnl"]):
            wr = 100 * v["w"] / v["n"] if v["n"] else 0
            print(f"    {k:12s} n={v['n']:3d}  WR={wr:5.1f}%  net=${v['pnl']:+7.2f}")


def _focus_counterfactuals(cf_path: Path, cutoff: datetime | None) -> None:
    if not cf_path.exists():
        print("  (no counterfactual log)")
        return
    by_reason = defaultdict(lambda: {"n": 0, "would_win": 0, "would_lose": 0})
    with cf_path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = _parse_ts(d.get("created_at", ""))
            if cutoff and ts and ts < cutoff:
                continue
            if not d.get("resolved"):
                continue
            reason = d.get("skip_reason", "unknown")
            by_reason[reason]["n"] += 1
            if d.get("would_hit_tp1"):
                by_reason[reason]["would_win"] += 1
            elif d.get("would_hit_sl"):
                by_reason[reason]["would_lose"] += 1

    print("  Per skip-reason: would-have-won rate")
    print("  (reasons with >20 samples sorted by would-win %)")
    filtered = [(r, v) for r, v in by_reason.items() if v["n"] >= 20]
    filtered.sort(key=lambda x: -(x[1]["would_win"] / max(1, x[1]["n"])))
    for reason, v in filtered[:15]:
        n = v["n"]
        w_rate = 100 * v["would_win"] / n if n else 0
        l_rate = 100 * v["would_lose"] / n if n else 0
        print(f"    {reason:35s} n={n:5d}  TP1={w_rate:5.1f}%  SL={l_rate:5.1f}%")


def main() -> int:
    parser = argparse.ArgumentParser(description="Multi-path performance aggregator")
    parser.add_argument("--days", type=int, default=30, help="Days of history (default 30)")
    parser.add_argument("--all", action="store_true", help="Use full history (overrides --days)")
    parser.add_argument("--focus", choices=["ensemble", "sniper", "counterfactuals"], help="Deep dive one stream")
    args = parser.parse_args()

    days = None if args.all else args.days
    analyze(days=days, focus=args.focus)
    return 0


if __name__ == "__main__":
    sys.exit(main())
