#!/usr/bin/env python
"""WAGMI proof-window tracker — read-only, LLM-FREE.

The measurement backbone was made HONEST on 2026-07-15 (accuracy sweep: real
fees on notional*leverage + entry leg charged, signed funding, realized R:R,
counterfactual de-zeroing, unit fixes; plus regime + reflection self-knowledge
fixes). Paper P&L before this was OPTIMISTIC and self-knowledge was corrupted, so
ONLY closes recorded after the honest-numbers foundation reflect the real system.

This scores the CLEAN honest window from ground-truth sources only (trade_ledger.csv
net_pnl — which now carries real fees+funding), tracks progress toward a decision
threshold, and (with --alert) pings Discord ONCE when enough clean trades exist to
judge edge truthfully. Nothing here trades or gates — pure measurement.

Usage:
  python bot/tools/proof_window.py [cutoff_iso] [--alert]
  default cutoff = honest-numbers foundation 2026-07-15T02:52:00Z
"""
import os
import sys
import csv
import json
import datetime

BOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(BOT, "data", "trade_ledger.csv")
THESIS = os.path.join(BOT, "data", "llm", "thesis_history.jsonl")
KELLY = os.path.join(BOT, "data", "kelly_weights.json")
IC = os.path.join(BOT, "data", "ic_history.json")
OUT = os.path.join(BOT, "..", "coordination", "PROOF_WINDOW.md")
ALERT_MARKER = os.path.join(BOT, "data", ".proof_window_alerted")

# Honest-numbers foundation (accuracy sweep + fees/funding live, pid 23928 restart).
HONEST_CUTOFF_ISO = "2026-07-15T02:52:00+00:00"

# Decision thresholds (trades in the clean window).
MIN_TO_JUDGE = 30      # enough to form a preliminary read
CONFIDENT = 50         # enough for a confident read

_args = [a for a in sys.argv[1:] if a != "--alert"]
DO_ALERT = "--alert" in sys.argv
CUTOFF_ISO = _args[0] if _args else HONEST_CUTOFF_ISO


def _ts(v):
    v = str(v).strip()
    try:
        return float(v) if "T" not in v else datetime.datetime.fromisoformat(
            v.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return 0.0


def _fnum(r, key):
    try:
        return float(r.get(key) or 0)
    except (ValueError, TypeError):
        return 0.0


def _wl(pnls):
    w = sum(1 for p in pnls if p > 0)
    l = sum(1 for p in pnls if p < 0)
    s = sum(pnls)
    wr = w / len(pnls) if pnls else 0.0
    win_avg = sum(p for p in pnls if p > 0) / w if w else 0.0
    loss_avg = sum(p for p in pnls if p < 0) / l if l else 0.0
    pf = (sum(p for p in pnls if p > 0) / abs(sum(p for p in pnls if p < 0))
          if l and sum(p for p in pnls if p < 0) != 0 else float("inf"))
    return w, l, s, wr, win_avg, loss_avg, pf


def _alert_once(n, s, wr):
    """Send a Discord ping the FIRST time the clean window reaches MIN_TO_JUDGE."""
    if os.path.exists(ALERT_MARKER):
        return
    try:
        sys.path.insert(0, os.path.join(BOT, "tools"))
        from discord_notify import send_discord
        send_discord(
            f"Clean honest-numbers window hit **{n} trades** "
            f"(WR {wr*100:.0f}%, net ${s:+.2f}). Enough to judge edge truthfully — "
            f"time to review coordination/PROOF_WINDOW.md.",
            title="WAGMI: proof window ready",
        )
        with open(ALERT_MARKER, "w", encoding="utf-8") as f:
            f.write(datetime.datetime.now(datetime.timezone.utc).isoformat())
    except Exception as e:
        print(f"[proof_window] alert skipped: {e}")


def main():
    cutoff = _ts(CUTOFF_ISO)
    rows = []
    if os.path.exists(LEDGER):
        rows = list(csv.DictReader(open(LEDGER, encoding="utf-8", errors="ignore")))

    post_rows = [r for r in rows if _ts(r.get("timestamp")) >= cutoff]
    pre = [_fnum(r, "net_pnl") for r in rows if _ts(r.get("timestamp")) < cutoff]
    post = [_fnum(r, "net_pnl") for r in post_rows]

    now = datetime.datetime.now(datetime.timezone.utc)
    n = len(post)
    verdict = ("NOT_READY — window still thin" if n < MIN_TO_JUDGE else
               "READY_PRELIMINARY — enough for a first read" if n < CONFIDENT else
               "READY_CONFIDENT — enough to judge edge")

    L = [f"# WAGMI Proof Window — {now.strftime('%Y-%m-%d %H:%M UTC')}",
         f"Clean window = closes on/after the HONEST-NUMBERS foundation {CUTOFF_ISO} "
         f"(real fees+funding, fixed self-knowledge). Source: trade_ledger.csv net_pnl. "
         f"Measurement only.", "",
         f"## Readiness: **{verdict}**",
         f"- clean trades **{n}** / {MIN_TO_JUDGE} to judge "
         f"({max(0, MIN_TO_JUDGE - n)} more needed) / {CONFIDENT} for confidence", ""]

    # EPOCH_FENCE cross-reference (measurement-integrity, Phase 0): this
    # honest-numbers cutoff is a DIFFERENT window than the canonical
    # operational epoch (data/epoch_start.json, the $5k reset baseline) —
    # they measure different things (fees/funding accuracy vs. the reset
    # balance). Surface both so nobody mistakes one for the other.
    try:
        sys.path.insert(0, BOT)
        from data.trade_source import get_run_stats
        _rs = get_run_stats(epoch=True)
        if _rs["epoch_id"] or _rs["epoch_start"]:
            L.append(
                f"_Canonical epoch (operational $5k reset, separate from the "
                f"honest-numbers cutoff above): {_rs['epoch_id'] or _rs['epoch_start']} "
                f"— {_rs['n']} trades, net ${_rs['net']:+.2f}"
                + (f", derived equity ${_rs['derived_equity']:.2f}" if _rs["derived_equity"] is not None else "")
                + "._"
            )
            L.append("")
    except Exception:
        pass

    for label, pnls in (("PRE-foundation (optimistic / contaminated)", pre),
                        ("POST-foundation (CLEAN honest window)", post)):
        if not pnls:
            L.append(f"## {label}: no closes")
            L.append("")
            continue
        w, l, s, wr, wa, la, pf = _wl(pnls)
        L.append(f"## {label}")
        L.append(f"- closes **{len(pnls)}** | W/L **{w}/{l}** | WR **{wr*100:.0f}%** | "
                 f"net **${s:+.2f}** | avg win ${wa:+.2f} / avg loss ${la:+.2f} | PF **{pf:.2f}**")
        L.append("")

    # Honest cost transparency in the clean window (fees + funding now real)
    if post_rows:
        fees = sum(_fnum(r, "fees") for r in post_rows)
        funding = sum(_fnum(r, "funding") for r in post_rows)
        gross = sum(_fnum(r, "gross_pnl") for r in post_rows)
        rr_vals = [_fnum(r, "realized_rr") for r in post_rows if (r.get("realized_rr") or "") not in ("", "0", "0.0")]
        avg_rr = sum(rr_vals) / len(rr_vals) if rr_vals else 0.0
        L.append("## Clean-window honest accounting")
        L.append(f"- gross P&L ${gross:+.2f} | fees ${fees:+.2f} | funding ${funding:+.2f} "
                 f"| net ${gross - abs(fees) + funding:+.2f}")
        L.append(f"- avg realized R:R **{avg_rr:+.2f}** (n={len(rr_vals)} with recorded RR)")
        L.append("")

    # Per symbol_side edge in the clean window
    if post_rows:
        cells = {}
        for r in post_rows:
            k = f"{r.get('symbol','?')}_{r.get('side','?')}"
            cells.setdefault(k, []).append(_fnum(r, "net_pnl"))
        L.append("## Clean-window edge by symbol_side (n>=3)")
        ranked = sorted(((sum(v) / len(v), k, len(v), sum(1 for x in v if x > 0) / len(v))
                         for k, v in cells.items() if len(v) >= 3), reverse=True)
        for avg, k, cnt, wr in ranked:
            L.append(f"- {k}: avg **${avg:+.2f}**/trade, WR {wr*100:.0f}%, n={cnt}")
        if not ranked:
            L.append("- (waiting for n>=3 per cell — window still thin)")
        L.append("")

    # Thesis directional accuracy (clean window)
    if os.path.exists(THESIS):
        graded = []
        for x in open(THESIS, encoding="utf-8"):
            x = x.strip()
            if not x:
                continue
            try:
                t = json.loads(x)
            except (ValueError, TypeError):
                continue
            if t.get("outcome") in ("correct", "incorrect", "partial"):
                graded.append(t)
        gp = [t for t in graded if _ts(t.get("closed_at") or t.get("created_at")) >= cutoff]
        if gp:
            c = sum(1 for t in gp if t.get("outcome") == "correct")
            p = sum(1 for t in gp if t.get("outcome") == "partial")
            L.append("## Thesis directional accuracy (clean window)")
            L.append(f"- graded **{len(gp)}** | correct {c} | partial {p} | "
                     f"incorrect {len(gp)-c-p} | hit-rate **{(c+0.5*p)/len(gp)*100:.0f}%**")
            L.append("")

    # Loop liveness
    def age_h(p):
        return (datetime.datetime.now().timestamp() - os.path.getmtime(p)) / 3600 if os.path.exists(p) else None
    kh, ih = age_h(KELLY), age_h(IC)
    L.append("## Loop liveness")
    if kh is not None:
        L.append(f"- kelly_weights.json updated {kh:.1f}h ago | "
                 f"ic_history.json {(f'{ih:.1f}h ago' if ih is not None else 'absent (rebuilding clean)')} "
                 f"({'FRESH' if kh < 168 else 'STALE'})")
    else:
        L.append("- kelly/ic missing")
    L.append("")
    L.append("**Read:** only the POST-foundation honest window reflects the real system — "
             "pre-foundation P&L was optimistic (understated fees/funding) and self-knowledge "
             "was corrupted. Give it clean closes before judging profitability; the readiness "
             "line above says when there are enough.")

    txt = "\n".join(L)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(txt + "\n")
    print(txt.encode("ascii", "replace").decode("ascii"))

    if DO_ALERT and n >= MIN_TO_JUDGE:
        w, l, s, wr, wa, la, pf = _wl(post)
        _alert_once(n, s, wr)


if __name__ == "__main__":
    main()
