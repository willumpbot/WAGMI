"""Generate coordination/STATE.md — the single always-current 'state of the brain' page.

Run from bot/: python tools/gen_state.py
Every section is fail-soft: a missing/broken source reports itself rather than killing the page.
"""
import csv
import json
import os
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))          # bot/
COORD = os.path.join(os.path.dirname(ROOT), "coordination")

def _try(fn, fallback):
    try:
        return fn()
    except Exception as e:
        return fallback + f" _(unavailable: {e.__class__.__name__})_"

def health():
    d = json.load(open(os.path.join(ROOT, "data", "heartbeat.json")))
    age_min = (time.time() - d["epoch"]) / 60
    status = "🟢 ALIVE" if age_min < 10 else "🔴 STALE HEARTBEAT"
    return (f"{status} — pid {d['pid']}, uptime {d['uptime_s']/3600:.1f}h, "
            f"scan {d['scan_count']}, errors {d['errors']}, equity ${d['equity']:.2f} "
            f"(heartbeat {age_min:.0f}m old)")

def book():
    p = json.load(open(os.path.join(ROOT, "data", "position_state.json")))
    pos = p.get("positions", {})
    if not pos:
        return "_flat — no open positions_"
    lines = []
    for s, x in pos.items():
        lines.append(f"- **{x['symbol']} {x['side']}** @ {x['entry']} | SL {x['sl']} TP1 {x['tp1']} "
                     f"| conf {round(x.get('confidence', 0), 1)} | opened {x.get('open_time', '')[:16]}")
    return "\n".join(lines)

def recent_trades(n=5):
    rows = list(csv.reader(open(os.path.join(ROOT, "data", "trades.csv"))))
    h = [c.strip() for c in rows[0]]
    idx = {c: i for i, c in enumerate(h)}
    out = ["| time (UTC) | trade | pnl | outcome | conf | entry_type |", "|---|---|---|---|---|---|"]
    for r in rows[1:][-n:]:
        g = lambda c: r[idx[c]] if idx.get(c, -1) < len(r) and c in idx else ""
        out.append(f"| {g('timestamp')[:16].replace('T',' ')} | {g('symbol')} {g('side')} "
                   f"| {g('pnl')} | {g('outcome')} | {g('confidence')} | {g('entry_type') or '?'} |")
    return "\n".join(out)

def holes():
    path = os.path.join(COORD, "HOLES.md")
    txt = open(path, encoding="utf-8", errors="replace").read()
    open_n = txt.count("| OPEN")
    fixed_n = txt.count("FIXED")
    return f"{open_n} open / {fixed_n} fixed — full registry: coordination/HOLES.md"

def decisions():
    path = os.path.join(COORD, "MORNING_BRIEF_2026-07-02.md")
    if os.path.exists(path):
        return "6 owner decisions pending — coordination/MORNING_BRIEF_2026-07-02.md"
    return "_none pending_"

def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    md = f"""# 🧠 STATE OF THE BRAIN — {now}
_Auto-generated every learning-engine pass (bot/tools/gen_state.py). This is the shared page._

## Bot
{_try(health, "health unknown")}

## Open book
{_try(book, "book unknown")}

## Last 5 closes
{_try(lambda: recent_trades(5), "trades unavailable")}

## Knowledge state
- Thesis scoreboard: 54% @24h (shorts 56% / longs 48%; confidence INVERTED — 80+ only trustworthy band). Details: THESIS_GRADES_2026-07-01.md
- Missed-EV verdict: ARTIFACT (week-1 crash shorts). Agent caution is earning. MISSED_EV_LOCKDOWN_2026-07-01.md
- Spine: repaired 2026-07-01 (6 fixes); live verification on new closes in progress. Invariant contract: WIRING_INVARIANTS.md

## Hole registry
{_try(holes, "registry pending")}

## Waiting on owner
{_try(decisions, "_none_")}
"""
    out = os.path.join(COORD, "STATE.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"wrote {out}")

if __name__ == "__main__":
    main()
