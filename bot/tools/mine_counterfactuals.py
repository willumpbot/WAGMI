#!/usr/bin/env python
"""WAGMI counterfactual edge miner — read-only, LLM-FREE, SHADOW.

Activates the counterfactual learning loop on our ACCUMULATED data: turns the
~74k resolved skip-outcomes (bot/data/llm/counterfactual_resolved.jsonl) into
conditional edge stats — which (symbol, side, confidence-band, regime) cells the
LLM SKIPPED that actually paid, so we can see where the brain is leaving money.

Guards baked in from the 2026-07-13 audit: (1) DEDUP by (symbol,side,30-min bucket)
— signals re-fire every ~50s inflating n ~10x; (2) RECENCY window (default 21d)
to avoid the June overdrive-blowup + outage tape; (3) fees subtracted (10.4bps RT);
(4) n>=13 floor per cell. Output is KNOWLEDGE (coordination/CF_EDGES.md), not a gate
change — shadow-first per THE_STANDARD.

Usage: python bot/tools/mine_counterfactuals.py [days] [min_n]
"""
import os
import sys
import json
import datetime
import collections

BOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CF = os.path.join(BOT, "data", "llm", "counterfactual_resolved.jsonl")
DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 21
MIN_N = int(sys.argv[2]) if len(sys.argv) > 2 else 13
FEE_PCT = 0.104  # round-trip fee, %


def _cband(c):
    try:
        c = float(c)
    except Exception:
        return "?"
    if c >= 80:
        return "80+"
    if c >= 70:
        return "70-80"
    if c >= 60:
        return "60-70"
    return "<60"


def main():
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=DAYS)
    seen = set()
    cells = collections.defaultdict(lambda: {"n": 0, "tp1": 0, "pnl": 0.0})
    total = kept = 0
    for line in open(CF, encoding="utf-8", errors="ignore"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if not r.get("resolved"):
            continue
        total += 1
        # recency
        try:
            c = datetime.datetime.fromisoformat(str(r.get("created_at", "")))
            if c < cutoff:
                continue
        except Exception:
            continue
        sym = r.get("symbol", "?")
        side = r.get("side", "?")
        # dedup by 30-min bucket
        bucket = int(c.timestamp() // 1800)
        key = (sym, side, bucket)
        if key in seen:
            continue
        seen.add(key)
        kept += 1
        try:
            pnl = float(r.get("hypothetical_pnl_pct") or 0) - FEE_PCT
        except Exception:
            pnl = -FEE_PCT
        cell = (f"{sym}_{side}", _cband(r.get("confidence")), r.get("regime", "?"))
        cells[cell]["n"] += 1
        cells[cell]["pnl"] += pnl
        if r.get("would_hit_tp1"):
            cells[cell]["tp1"] += 1

    ranked = []
    for (ss, cb, reg), v in cells.items():
        if v["n"] < MIN_N:
            continue
        avg = v["pnl"] / v["n"]
        ranked.append((avg, ss, cb, reg, v["n"], v["tp1"] / v["n"]))
    ranked.sort(reverse=True)

    L = [f"# WAGMI Counterfactual Edges — {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
         f"Resolved CFs scanned: {total:,}; in last {DAYS}d after dedup: {kept:,}. "
         f"Cells with n>={MIN_N}, fees {FEE_PCT}% subtracted. SHADOW knowledge, not a gate.", "",
         "## Skipped setups that PAID (top — brain left money here)"]
    for avg, ss, cb, reg, n, tp in ranked[:15]:
        if avg <= 0:
            break
        L.append(f"- **{ss}** conf {cb} regime {reg}: avg **{avg:+.2f}%**/skip after fees, tp1 {tp*100:.0f}%, n={n}")
    L.append("")
    L.append("## Skips that were CORRECT (worst — the cage earning)")
    for avg, ss, cb, reg, n, tp in ranked[-8:]:
        L.append(f"- {ss} conf {cb} regime {reg}: avg {avg:+.2f}%/skip, tp1 {tp*100:.0f}%, n={n}")
    txt = "\n".join(L)
    with open(os.path.join(BOT, "..", "coordination", "CF_EDGES.md"), "w", encoding="utf-8") as f:
        f.write(txt + "\n")
    # ascii-safe print
    print(txt.encode("ascii", "replace").decode("ascii"))


if __name__ == "__main__":
    main()
