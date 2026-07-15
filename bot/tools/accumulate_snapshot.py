#!/usr/bin/env python
"""WAGMI accumulation instrument — read-only, LLM-FREE.

Now that the inputs are honest (toxicity audit 2026-07-13), the data the bot
produces is trustworthy to learn from. This appends ONE clean metrics record per
run to data/reports/accumulation_log.jsonl — a growing self-knowledge time-series:
is the bot trading the found edge, are the learning loops filling, are the shipped
behavioral fixes behaving? Run daily (Task Scheduler WAGMI-Accumulate) or ad hoc.

Revert: schtasks /delete /tn WAGMI-Accumulate /f + delete this file.
"""
import os
import csv
import json
import datetime
import statistics

BOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BOT, "data")


def _rj(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _today_trades(today):
    n = w = l = 0
    pnl = 0.0
    try:
        with open(os.path.join(DATA, "trades.csv"), newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if not str(r.get("timestamp", "")).startswith(today):
                    continue
                n += 1
                p = 0.0
                try:
                    p = float(r.get("pnl") or 0)
                except Exception:
                    pass
                pnl += p
                if p > 0:
                    w += 1
                elif p < 0:
                    l += 1
    except Exception:
        pass
    return {"n": n, "w": w, "l": l, "pnl": round(pnl, 2)}


def _thesis_progress():
    """How many theses are graded vs pending — F-1 should make this start growing."""
    graded = pending = 0
    try:
        with open(os.path.join(DATA, "llm", "thesis_history.jsonl"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line).get("outcome", "pending")
                except Exception:
                    continue
                if o and o != "pending":
                    graded += 1
                else:
                    pending += 1
    except Exception:
        pass
    return {"graded": graded, "pending": pending}


def _cf_resolution_hours(now, sample=1500):
    """Median wall-clock resolution of recent counterfactuals — should be ~16h
    now (C-F1), not the buggy ~8h. Confirms the resolver fix is live."""
    hrs = []
    try:
        path = os.path.join(DATA, "llm", "counterfactual_resolved.jsonl")
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 900_000))  # tail only
            tail = f.read().decode("utf-8", "ignore").splitlines()
        for line in tail[-sample:]:
            try:
                r = json.loads(line)
                c = datetime.datetime.fromisoformat(str(r.get("created_at", "")))
                z = datetime.datetime.fromisoformat(str(r.get("resolved_at", "")))
                h = (z - c).total_seconds() / 3600.0
                if 0 <= h < 200:
                    hrs.append(h)
            except Exception:
                continue
    except Exception:
        pass
    return round(statistics.median(hrs), 1) if hrs else None


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    hb = _rj(os.path.join(DATA, "heartbeat.json"))
    costs = _rj(os.path.join(DATA, "llm", "agent_costs.json"))
    cb = _rj(os.path.join(DATA, "circuit_breaker_state.json"))

    rec = {
        "ts": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "equity": hb.get("equity"),
        "positions": hb.get("positions"),
        "llm_degraded": hb.get("llm_first_degraded"),
        "trades_today": _today_trades(now.strftime("%Y-%m-%d")),
        "thesis": _thesis_progress(),
        "cf_median_resolve_h": _cf_resolution_hours(now),
        "llm_calls_today": costs.get("today_calls"),
        "cb_tripped": cb.get("tripped"),
        "consec_losses": cb.get("consecutive_losses"),
    }
    reports = os.path.join(DATA, "reports")
    os.makedirs(reports, exist_ok=True)
    with open(os.path.join(reports, "accumulation_log.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps(rec, indent=2))


if __name__ == "__main__":
    main()
