"""Thesis Accountability Tracker.

Every time live_analyst publishes a thesis, we log a compact record.
Later (N hours after), the grader resolves: did the call play out?

Why this matters: backward-looking win rate is a poor measure because
markets drift. But a LIVE forward-graded record of "we said X, Y happened"
is the cleanest measure of whether our REASONING has edge.

Files:
    bot/data/thesis_log.jsonl    — append-only log of every published thesis
    bot/data/thesis_grades.jsonl — append-only log of resolved grades

Usage:
    # Record a thesis (auto-called from live_analyst.py)
    python -m tools.thesis_tracker log --symbol BTC --thesis-path web/public/thesis/btc/thesis.json

    # Grade stale theses (call periodically or at morning digest)
    python -m tools.thesis_tracker grade

    # Summary
    python -m tools.thesis_tracker summary
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent  # bot/
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

LOG_PATH = DATA / "thesis_log.jsonl"
GRADES_PATH = DATA / "thesis_grades.jsonl"

logger = logging.getLogger("thesis_tracker")


def _jsonl_append(path: Path, row: Dict[str, Any]) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


def _jsonl_read_all(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    return rows


def log_thesis(thesis: Dict[str, Any]) -> Optional[str]:
    """Extract the compact record from a full thesis.json and append to log.
    Returns the record's id (ts + symbol)."""
    committee = thesis.get("committee", {}) or {}
    trade = committee.get("trade", {}) or {}
    critic = committee.get("critic", {}) or {}
    regime = committee.get("regime", {}) or {}
    factors = thesis.get("factors", {}) or {}

    record = {
        "id": f"{thesis.get('symbol','?')}_{thesis.get('updated_at','')}",
        "symbol": thesis.get("symbol"),
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "price_at_thesis": thesis.get("price"),
        "regime": regime.get("regime_label"),
        "regime_narrative": (regime.get("narrative") or "")[:400],
        "trade_action": trade.get("action"),
        "trade_confidence": trade.get("confidence"),
        "trade_narrative": (trade.get("narrative") or "")[:400],
        "entry_low": trade.get("entry_low"),
        "entry_high": trade.get("entry_high"),
        "stop": trade.get("stop"),
        "target1": trade.get("target1"),
        "target2": trade.get("target2"),
        "rr_t1": trade.get("rr_t1"),
        "rr_t2": trade.get("rr_t2"),
        "critic_vote": critic.get("vote"),
        "critic_narrative": (critic.get("narrative") or "")[:400],
        "conviction_count": factors.get("conviction_count"),
        "mode": committee.get("mode"),
    }
    _jsonl_append(LOG_PATH, record)
    return record["id"]


def log_from_path(thesis_json_path: str) -> Optional[str]:
    """Log a thesis given a path to its JSON file."""
    path = Path(thesis_json_path)
    if not path.exists():
        logger.warning(f"thesis not found: {path}")
        return None
    try:
        thesis = json.loads(path.read_text(encoding="utf-8"))
        return log_thesis(thesis)
    except Exception as e:
        logger.exception(f"log_from_path failed: {e}")
        return None


def grade_theses(min_age_hours: float = 1.0, max_age_hours: float = 48.0) -> List[Dict[str, Any]]:
    """Resolve graded outcomes for theses logged between min/max hours ago.
    Compares against live CCXT price. Returns list of grade records."""
    try:
        import ccxt
        ex = ccxt.hyperliquid()
        ex.load_markets()
    except Exception as e:
        logger.error(f"CCXT init failed: {e}")
        return []

    logs = _jsonl_read_all(LOG_PATH)
    graded_ids = {g.get("id") for g in _jsonl_read_all(GRADES_PATH)}
    now = datetime.now(timezone.utc)
    new_grades = []

    for rec in logs:
        rid = rec.get("id")
        if not rid or rid in graded_ids:
            continue
        try:
            logged = datetime.fromisoformat(
                rec.get("logged_at", "").replace("Z", "+00:00")
            )
            age_h = (now - logged).total_seconds() / 3600
            if age_h < min_age_hours or age_h > max_age_hours:
                continue
        except Exception:
            continue

        sym = rec.get("symbol")
        if not sym:
            continue

        try:
            t = ex.fetch_ticker(f"{sym}/USDC:USDC")
            price_now = float(t["last"])
        except Exception as e:
            logger.warning(f"[{sym}] ticker fetch failed: {e}")
            continue

        entry_lo = rec.get("entry_low")
        entry_hi = rec.get("entry_high")
        stop = rec.get("stop")
        t1 = rec.get("target1")
        t2 = rec.get("target2")
        p0 = rec.get("price_at_thesis")
        action = rec.get("trade_action")

        # Direction correctness (did price move in the thesis direction?)
        direction_correct = None
        if p0 and price_now:
            moved_up = price_now > p0
            if action == "go_long":
                direction_correct = moved_up
            elif action == "go_short":
                direction_correct = not moved_up
            # "wait" has no direction claim — skip grading direction

        # Target/stop hits
        tp1_hit = None
        stop_hit = None
        if action == "go_long" and t1 and stop:
            tp1_hit = price_now >= t1
            stop_hit = price_now <= stop
        elif action == "go_short" and t1 and stop:
            tp1_hit = price_now <= t1
            stop_hit = price_now >= stop

        # Move in R-multiple
        r_move = None
        if p0 and stop and action in ("go_long", "go_short"):
            risk_dist = abs(p0 - stop)
            if action == "go_long":
                r_move = (price_now - p0) / max(risk_dist, 1e-9)
            else:
                r_move = (p0 - price_now) / max(risk_dist, 1e-9)

        grade = {
            "id": rid,
            "symbol": sym,
            "graded_at": now.isoformat(),
            "age_hours": round(age_h, 2),
            "price_at_thesis": p0,
            "price_now": price_now,
            "action": action,
            "direction_correct": direction_correct,
            "tp1_hit": tp1_hit,
            "stop_hit": stop_hit,
            "r_move": round(r_move, 2) if r_move is not None else None,
            "conviction_count": rec.get("conviction_count"),
            "critic_vote": rec.get("critic_vote"),
        }
        _jsonl_append(GRADES_PATH, grade)
        new_grades.append(grade)
        logger.info(f"[{sym}] graded: action={action} dir={direction_correct} "
                    f"r={grade['r_move']} age={age_h:.1f}h")
    return new_grades


def summary(days: float = 7.0) -> Dict[str, Any]:
    """Accuracy summary over the last N days of grades."""
    grades = _jsonl_read_all(GRADES_PATH)
    if not grades:
        return {"total": 0, "msg": "No graded theses yet."}

    # Only grades with direction_correct known (i.e. action was go_long or go_short)
    actionable = [g for g in grades if g.get("direction_correct") is not None]
    if not actionable:
        return {"total": 0, "msg": "No actionable theses graded yet (all were 'wait')."}

    correct = sum(1 for g in actionable if g.get("direction_correct"))
    tp1_hits = sum(1 for g in actionable if g.get("tp1_hit"))
    stop_hits = sum(1 for g in actionable if g.get("stop_hit"))

    by_symbol: Dict[str, Dict[str, int]] = {}
    for g in actionable:
        s = g.get("symbol", "?")
        by_symbol.setdefault(s, {"n": 0, "correct": 0, "r_sum": 0.0})
        by_symbol[s]["n"] += 1
        if g.get("direction_correct"):
            by_symbol[s]["correct"] += 1
        r = g.get("r_move")
        if r is not None:
            by_symbol[s]["r_sum"] += r

    return {
        "total": len(actionable),
        "direction_accuracy": round(correct / len(actionable) * 100, 1),
        "tp1_hit_rate": round(tp1_hits / len(actionable) * 100, 1),
        "stop_hit_rate": round(stop_hits / len(actionable) * 100, 1),
        "mean_r_move": round(
            sum(g.get("r_move", 0) or 0 for g in actionable) / len(actionable), 2
        ),
        "by_symbol": {
            s: {
                "n": v["n"],
                "dir_acc_pct": round(v["correct"] / v["n"] * 100, 1),
                "mean_r": round(v["r_sum"] / v["n"], 2),
            }
            for s, v in by_symbol.items()
        },
    }


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    p_log = sub.add_parser("log", help="Log a thesis from file")
    p_log.add_argument("--thesis-path", required=True)
    sub.add_parser("grade", help="Grade stale theses")
    sub.add_parser("summary", help="Print accuracy summary")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.cmd == "log":
        rid = log_from_path(args.thesis_path)
        print(f"Logged: {rid}")
    elif args.cmd == "grade":
        new_grades = grade_theses()
        print(f"Graded {len(new_grades)} new theses")
        for g in new_grades[-10:]:
            print(f"  {g['symbol']:5} action={g['action']:8} dir={g['direction_correct']} "
                  f"r={g['r_move']} age={g['age_hours']}h")
    elif args.cmd == "summary":
        s = summary()
        print(json.dumps(s, indent=2))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
