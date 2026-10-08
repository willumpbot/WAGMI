"""Profile the legacy (pre-server-window) trade_events.jsonl found on the laptop.

Source: C:/Users/vince/WAGMI PROJECT/WAGMI/bot/data/trade_events.jsonl
Spans 2026-03-31 -> 2026-06-06, i.e. ~2 months before the server's grading
window opens (2026-05-30). Fixture filtering follows the signatures the server
documented in bot/data/agent_grades/SCORECARD.md.
"""
import json, collections, io

SRC = "C:/Users/vince/WAGMI PROJECT/WAGMI/bot/data/trade_events.jsonl"
OUT = "C:/Users/vince/WAGMI/bot/data/laptop_mining/legacy_closed_trades.json"

ev = collections.Counter()
closed = []
bad = collections.Counter()


def is_fixture(d):
    """Server-documented fixture signatures (SCORECARD.md method section)."""
    if d.get("strategy") == "test":
        return "strategy=test"
    for k in ("entry", "entry_price"):
        if d.get(k) in (100.0, 50000.0):
            return "canned_entry"
    return None


with io.open(SRC, encoding="utf-8", errors="replace") as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            bad["unparseable"] += 1
            continue
        e = d.get("event", "?")
        ev[e] += 1
        if e != "TRADE_CLOSED":
            continue
        fx = is_fixture(d)
        if fx:
            bad[fx] += 1
            continue
        pnl = d.get("pnl")
        if not isinstance(pnl, (int, float)):
            bad["no_pnl"] += 1
            continue
        closed.append({
            "ts": d.get("timestamp", ""),
            "sym": d.get("symbol"),
            "side": d.get("side"),
            "pnl": float(pnl),
            "strat": d.get("strategy"),
            "regime": d.get("regime"),
            "lev": d.get("leverage"),
            "conf": d.get("confidence"),
            "entry": d.get("entry_price"),
            "exit": d.get("exit_price"),
        })

print("=== event types (top 12) ===")
for k, v in ev.most_common(12):
    print(f"  {v:>8}  {k}")

print(f"\n=== TRADE_CLOSED after fixture filter: {len(closed)} ===")
print("  dropped:", dict(bad))
if not closed:
    raise SystemExit("no usable closed trades")

ts = [c["ts"] for c in closed]
print(f"  span: {min(ts)[:19]}  ->  {max(ts)[:19]}")
tot = sum(c["pnl"] for c in closed)
wins = sum(1 for c in closed if c["pnl"] > 0)
print(f"  net pnl: ${tot:,.2f}   wins {wins}/{len(closed)} = {100*wins/len(closed):.1f}%")

print("\n=== by month ===")
months = collections.defaultdict(list)
for c in closed:
    months[c["ts"][:7]].append(c["pnl"])
for m in sorted(months):
    v = months[m]
    w = sum(1 for x in v if x > 0)
    print(f"  {m}: n={len(v):>5}  net=${sum(v):>12,.2f}  WR={100*w/len(v):>5.1f}%")

print("\n=== by symbol (top 12) ===")
bysym = collections.defaultdict(list)
for c in closed:
    bysym[c["sym"]].append(c["pnl"])
for s, v in sorted(bysym.items(), key=lambda x: -len(x[1]))[:12]:
    w = sum(1 for x in v if x > 0)
    print(f"  {str(s):<7} n={len(v):>5}  net=${sum(v):>12,.2f}  WR={100*w/len(v):>5.1f}%")

print("\n=== by side ===")
byside = collections.defaultdict(list)
for c in closed:
    byside[c["side"]].append(c["pnl"])
for s, v in sorted(byside.items(), key=lambda x: -len(x[1])):
    w = sum(1 for x in v if x > 0)
    print(f"  {str(s):<7} n={len(v):>5}  net=${sum(v):>12,.2f}  WR={100*w/len(v):>5.1f}%")

with io.open(OUT, "w", encoding="utf-8") as fh:
    json.dump(closed, fh, indent=0)
print(f"\nwrote {OUT} ({len(closed)} rows)")
