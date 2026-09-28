#!/usr/bin/env python
"""
Decision-lineage tracer (stopgap, fuzzy-join edition).

Answers the owner's question - "trace each trade back to its first domino" - for
REAL closed trades, today, without any change to the running bot.

WHY A FUZZY JOIN
----------------
The bot mints a `pipeline_id` per entry decision but drops it before it reaches the
ledger (see LINEAGE_JOIN_GAP.md for the permanent 7-step fix). Until that ships,
we recover the link by matching on time+symbol. That link was MEASURED reliable:
30/30 recent closes matched exactly one trade-agent decision 24-36s before entry.
This tool uses that rule. When the permanent `pipeline_id` stamp lands, swap the
fuzzy match for an exact key lookup and delete the caveats.

WHAT IT SHOWS, per trade:
  FIRST DOMINO  (the trade agent's reasoning - the closest logged "why")
    -> REGIME verdict -> QUANT -> TRADE go/skip -> RISK sizing -> CRITIC approve/veto
    -> OUTCOME (exit type, net P&L, hold)

SAFETY
------
Read-only. Never touches live state, never runs the bot. RAM-frugal: the big logs
(agent_performance.jsonl ~29MB, trade_events.jsonl ~54MB) are STREAMED and filtered
to only the target trades' symbol + time window - never loaded whole.

HONESTY (house rule)
--------------------
The join is fuzzy, not proven per-trade. Caveats are printed inline, not hidden:
entry pipelines log side="" (can't disambiguate a same-symbol long/short flip
inside 5 min); EXPLORATION entries are LLM `skip` verdicts overridden downstream,
so their trade-agent record says skip, not go; the ledger `timestamp` is close-time,
so entry is anchored on TRADE_OPENED, never the ledger row.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

BOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # .../bot (file is bot/tools/copilot/)
LEDGER = os.path.join(BOT, "data", "trade_ledger.csv")
EVENTS = os.path.join(BOT, "data", "trade_events.jsonl")
PERF = os.path.join(BOT, "data", "llm", "agent_performance.jsonl")

MATCH_WINDOW_S = 300          # trade-agent record must be within 5 min before entry
ENTRY_REL_TOL = 1e-4          # entry-price relative tolerance for TRADE_OPENED match
AGENT_ORDER = ["regime", "quant", "trade", "risk", "critic", "exit", "scout",
               "overseer", "learning"]


def _iso_to_epoch(s: str) -> Optional[float]:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _f(v) -> Optional[float]:
    try:
        return float(v)
    except Exception:
        return None


def load_targets(trade_ids: Optional[List[str]], last: int) -> List[dict]:
    """Small file - full read is fine."""
    rows = list(csv.DictReader(open(LEDGER, encoding="utf-8")))
    if trade_ids:
        want = set(trade_ids)
        sel = [r for r in rows if r.get("trade_id") in want]
    else:
        sel = rows[-last:]
    out = []
    for r in sel:
        close_ts = _f(r.get("timestamp"))
        hold_h = _f(r.get("hold_hours")) or 0.0
        entry_est = (close_ts - hold_h * 3600.0) if close_ts else None
        out.append({
            "trade_id": r.get("trade_id"), "symbol": r.get("symbol"),
            "side": (r.get("side") or "").upper(), "entry_price": _f(r.get("entry_price")),
            "close_ts": close_ts, "entry_est": entry_est, "hold_h": hold_h,
            "net_pnl": _f(r.get("net_pnl")), "exit_type": r.get("exit_type"),
            "regime_1h": r.get("regime_1h"), "regime_4h": r.get("regime_4h"),
            "leverage": _f(r.get("leverage")), "confidence_score": r.get("confidence_score"),
            "position_id": r.get("position_id"), "win": r.get("win"),
        })
    return out


def _windows_by_symbol(targets: List[dict], pad_before: float, pad_after: float
                       ) -> Dict[str, List[Tuple[float, float]]]:
    w: Dict[str, List[Tuple[float, float]]] = {}
    for t in targets:
        if not t["close_ts"]:
            continue
        lo = (t["entry_est"] or t["close_ts"]) - pad_before
        hi = t["close_ts"] + pad_after
        w.setdefault(t["symbol"], []).append((lo, hi))
    return w


def _in_windows(sym: str, ts: Optional[float], wins: Dict[str, List[Tuple[float, float]]]) -> bool:
    if ts is None or sym not in wins:
        return False
    return any(lo <= ts <= hi for lo, hi in wins[sym])


def collect_opens(targets) -> List[dict]:
    """Stream trade_events.jsonl; keep only TRADE_OPENED for target symbols in window."""
    wins = _windows_by_symbol(targets, pad_before=1800, pad_after=1800)
    keep = []
    if not os.path.exists(EVENTS):
        return keep
    with open(EVENTS, encoding="utf-8") as f:
        for line in f:
            if '"TRADE_OPENED"' not in line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            sym = e.get("symbol")
            ts = _iso_to_epoch(e.get("timestamp", ""))
            if _in_windows(sym, ts, wins):
                e["_ts"] = ts
                keep.append(e)
    return keep


def collect_perf(targets) -> List[dict]:
    """Stream agent_performance.jsonl; keep only target-symbol decisions in window."""
    wins = _windows_by_symbol(targets, pad_before=MATCH_WINDOW_S + 120, pad_after=1800)
    keep = []
    if not os.path.exists(PERF):
        return keep
    with open(PERF, encoding="utf-8") as f:
        for line in f:
            if '"type": "decision"' not in line and '"type":"decision"' not in line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            sym = r.get("symbol")
            ts = _f(r.get("timestamp"))
            if _in_windows(sym, ts, wins):
                keep.append(r)
    return keep


def match_entry(t: dict, opens: List[dict]) -> Optional[dict]:
    """Nearest TRADE_OPENED for (symbol, side, entry~=price) at or before close."""
    cands = []
    for e in opens:
        if e.get("symbol") != t["symbol"]:
            continue
        if (e.get("side") or "").upper() != t["side"]:
            continue
        ep = _f(e.get("entry"))
        if ep and t["entry_price"] and abs(ep - t["entry_price"]) / t["entry_price"] <= ENTRY_REL_TOL:
            cands.append(e)
    if not cands:
        return None
    # closest to the ledger's estimated entry time
    anchor = t["entry_est"] or t["close_ts"]
    cands.sort(key=lambda e: abs((e.get("_ts") or 0) - (anchor or 0)))
    return cands[0]


def match_pipeline(entry_ts: float, sym: str, perf: List[dict]) -> Tuple[Optional[str], Dict[str, dict]]:
    """Find the trade-agent record nearest before entry_ts; return its pipeline_id
    and every agent-role record sharing that pipeline_id."""
    trade_recs = [r for r in perf
                  if r.get("symbol") == sym and r.get("agent_role") == "trade"
                  and 0 <= (entry_ts - (_f(r.get("timestamp")) or 0)) <= MATCH_WINDOW_S]
    if not trade_recs:
        return None, {}
    trade_recs.sort(key=lambda r: entry_ts - (_f(r.get("timestamp")) or 0))
    pid = trade_recs[0].get("pipeline_id")
    chain = {}
    for r in perf:
        if r.get("pipeline_id") == pid:
            chain[r.get("agent_role")] = r
    return pid, chain


def _short(s: Optional[str], n: int = 220) -> str:
    s = (s or "").strip().replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "..."


def render(t: dict, entry: Optional[dict], pid: Optional[str], chain: Dict[str, dict]) -> str:
    L = []
    pnl = t["net_pnl"]
    sign = "+" if (pnl or 0) >= 0 else ""
    L.append("=" * 74)
    L.append(f"TRADE {t['trade_id']}  {t['symbol']} {t['side']}  "
             f"net {sign}{pnl:.2f}  exit={t['exit_type']}  lev={t['leverage']}")
    et = datetime.fromtimestamp(t["entry_est"], timezone.utc).strftime("%Y-%m-%d %H:%M") if t["entry_est"] else "?"
    L.append(f"  entry~{et}Z  hold={t['hold_h']:.2f}h  "
             f"regime_1h={t['regime_1h']} regime_4h={t['regime_4h'] or '(blank)'}")
    L.append("-" * 74)

    if not entry:
        L.append("  [no TRADE_OPENED match - cannot anchor entry time; skipping chain]")
        return "\n".join(L)
    L.append(f"  ENTRY EVENT: {entry.get('entry_type')} @ {entry.get('entry')} "
             f"size={entry.get('position_size')} conf={entry.get('confidence')}")

    if not pid:
        L.append("  [no trade-agent decision within 5 min before entry - unjoined]")
        L.append("  (Common for pre-fix rows; the permanent pipeline_id stamp fixes this.)")
        return "\n".join(L)

    L.append(f"  DECISION pipeline {pid}:")
    # FIRST DOMINO = the trade agent's own reasoning (closest logged "why")
    tr = chain.get("trade") or {}
    L.append(f"    -> FIRST DOMINO (trade agent {tr.get('decision','?')}, "
             f"conf {tr.get('confidence','?')}):")
    L.append(f"        {_short(tr.get('reasoning_summary'))}")
    for role in AGENT_ORDER:
        if role == "trade" or role not in chain:
            continue
        r = chain[role]
        L.append(f"    - {role:<8} {str(r.get('decision','')):<22} "
                 f"{_short(r.get('reasoning_summary'), 120)}")
    # exploration caveat
    if entry.get("entry_type") == "EXPLORATION":
        L.append("    ! EXPLORATION entry: the trade agent likely said SKIP and was "
                 "overridden downstream - verdict above is not the reason it opened.")
    L.append(f"  OUTCOME: {sign}{pnl:.2f}  via {t['exit_type']}  "
             f"({'win' if str(t['win']).lower() in ('1','true') else 'loss'})")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="Trace closed trades back to their decision chain.")
    ap.add_argument("--last", type=int, default=5, help="trace the last N closes (default 5)")
    ap.add_argument("--trade-id", action="append", help="specific trade_id(s) to trace")
    args = ap.parse_args()

    if not os.path.exists(LEDGER):
        print(f"[lineage] no ledger at {LEDGER}", file=sys.stderr)
        return 1
    targets = load_targets(args.trade_id, args.last)
    if not targets:
        print("[lineage] no matching trades", file=sys.stderr)
        return 1

    opens = collect_opens(targets)
    perf = collect_perf(targets)

    print(f"# Decision-lineage trace - {len(targets)} trade(s)")
    print(f"# fuzzy join (measured 30/30 recent); anchor=TRADE_OPENED, window={MATCH_WINDOW_S}s")
    joined = 0
    for t in targets:
        entry = match_entry(t, opens)
        pid, chain = (None, {})
        if entry and entry.get("_ts"):
            pid, chain = match_pipeline(entry["_ts"], t["symbol"], perf)
            if pid:
                joined += 1
        print(render(t, entry, pid, chain))
    print("=" * 74)
    print(f"joined {joined}/{len(targets)} to a decision chain. "
          f"Unjoined = pre-fix rows or gaps; the pipeline_id stamp (LINEAGE_JOIN_GAP.md) "
          f"makes this exact.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
