"""
Measurement Integrity Audit — verification script (READ-ONLY).

Recomputes select LLM-facing self-knowledge stats two ways — (a) exactly as
the live code computes them today, and (b) with the two known corruption
patterns forced OFF (no setup-identity dedup, no fixed-horizon resolution) —
to measure how much headroom the existing fixes are actually buying on real
production data. Does not write, mutate, or delete anything.

Usage:
    cd bot && python tools/copilot/measurement_integrity_audit.py
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.dedupe import dedupe_setups  # noqa: E402

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data")


def _load_jsonl(path, limit=None):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, "r") as f:
        for i, line in enumerate(f):
            if limit and i >= limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def audit_counterfactual_learner():
    print("=" * 78)
    print("1. COUNTERFACTUAL LEARNER  (feeds coordinator.py 'missed_opportunities' ->")
    print("   Trade/Regime/Critic agent prompts every decision cycle)")
    print("=" * 78)
    path = os.path.join(DATA, "llm", "counterfactual_resolved.jsonl")
    if not os.path.exists(path):
        print(f"  [SKIP] {path} not found")
        return
    total_lines = sum(1 for _ in open(path, "r"))
    print(f"  Raw resolved-file line count: {total_lines:,}")

    for lookback_days in (7, 14):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
        rows = []
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("created_at", "") < cutoff:
                    continue
                # mirror CounterfactualLearner._is_scored
                pnl = d.get("hypothetical_pnl_pct")
                if pnl is None:
                    continue
                if (pnl == 0.0 and not d.get("would_hit_tp1") and not d.get("would_hit_tp2")
                        and not d.get("would_hit_sl") and d.get("bars_to_resolve", 0) < 48):
                    continue
                rows.append(d)

        n_raw = len(rows)
        if n_raw == 0:
            print(f"  lookback={lookback_days}d: no scored rows in window")
            continue

        wrapped = [
            {"symbol": r.get("symbol", ""), "side": r.get("side", ""),
             "entry_price": r.get("entry_price", 0), "created_at": r.get("created_at", ""),
             "_r": r}
            for r in rows
        ]
        deduped_wrapped = dedupe_setups(wrapped, entry_key="entry_price", ts_key="created_at")
        deduped = [w["_r"] for w in deduped_wrapped]
        n_dedup = len(deduped)

        def wr(rs):
            wins = sum(1 for r in rs if (r.get("hypothetical_pnl_pct") or 0) > 0)
            return wins, (wins / len(rs) if rs else 0.0)

        wins_raw, wr_raw = wr(rows)
        wins_dedup, wr_dedup = wr(deduped)

        print(f"  --- lookback={lookback_days}d ---")
        print(f"  RAW    : n={n_raw:5d}  would_win={wins_raw:5d}  win_rate_of_skips={wr_raw*100:5.1f}%")
        print(f"  DEDUPED: n={n_dedup:5d}  would_win={wins_dedup:5d}  win_rate_of_skips={wr_dedup*100:5.1f}%")
        inflate = (n_raw / n_dedup) if n_dedup else float("inf")
        print(f"  Inflation factor (raw/deduped n): {inflate:.2f}x")
        print(f"  DEDUPE_CF_AGGREGATION env: {os.getenv('DEDUPE_CF_AGGREGATION', '<unset -> defaults true>')}")
        print(f"  -> live get_missed_opportunity_stats() uses the DEDUPED path by default.")


def audit_shadow_ledger():
    print()
    print("=" * 78)
    print("2. SHADOW LEDGER  (feedback/shadow_ledger.py — factor reactivation only,")
    print("   NOT wired into any LLM prompt path found in this audit)")
    print("=" * 78)
    path = os.path.join(DATA, "shadow_ledger.csv")
    if not os.path.exists(path):
        print(f"  [SKIP] {path} not found")
        return
    import csv
    with open(path, "r", newline="") as f:
        rows = list(csv.DictReader(f))
    resolved = [r for r in rows if r.get("resolved") == "true"]
    by_factor = {}
    for r in resolved:
        by_factor.setdefault(r.get("factor", "?"), []).append(r)
    print(f"  Total rows: {len(rows):,}  Resolved: {len(resolved):,}")
    for factor, rs in sorted(by_factor.items(), key=lambda kv: -len(kv[1]))[:10]:
        wins = sum(1 for r in rs if float(r.get("actual_return", 0) or 0) > 0)
        print(f"  factor={factor:20s} n={len(rs):5d} win_rate={wins/len(rs)*100:5.1f}%  "
              f"(raw per-tick count, no dedup -- confirms pseudoreplication risk)")


def audit_thesis_tracker():
    print()
    print("=" * 78)
    print("3. THESIS TRACKER  (feeds coordinator.py 'thesis_accuracy' -> prompts)")
    print("=" * 78)
    path = os.path.join(DATA, "llm", "thesis_history.jsonl")
    rows = _load_jsonl(path)
    if not rows:
        print(f"  [SKIP] {path} not found or empty")
        return
    by_id = {}
    for r in rows:
        by_id.setdefault(r.get("thesis_id"), []).append(r)
    dup_ids = {k: v for k, v in by_id.items() if len(v) > 1}
    closed = [max(v, key=lambda r: r.get("closed_at") or "") if len(v) > 1 else v[0]
              for v in by_id.values()]
    closed = [r for r in closed if r.get("outcome") not in (None, "pending")]
    print(f"  Raw lines: {len(rows):,}  Unique thesis_ids: {len(by_id):,}  "
          f"(dup lines per id are append-on-close updates, expected: {len(dup_ids)} ids appear twice)")
    print(f"  Closed/graded theses (deduped by thesis_id): {len(closed):,}")
    correct = sum(1 for r in closed if r.get("outcome") in ("correct", "partial"))
    if closed:
        print(f"  Overall accuracy: {correct/len(closed)*100:.1f}%  "
              f"(matches ThesisTracker.get_accuracy_stats() methodology: 1 row per thesis_id, "
              f"resolved against that trade's OWN real exit price -- fixed horizon = the trade's actual life)")


if __name__ == "__main__":
    audit_counterfactual_learner()
    audit_shadow_ledger()
    audit_thesis_tracker()
