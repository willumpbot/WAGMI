"""Append-only export of the bot's LIVE r16 confidence-floor decisions for the research laptop.

WHAT r16 IS (read from code, 2026-10-13)
  llm/risk_gating.py gate_decision() Rule 2: a non-flat LLMDecision whose confidence is below
  living_conf_floor.base_floor(0.60) (P90 of the last <=500 / <=14d gate confidences, clamped
  [0.30, 0.60], legacy 0.60 while n<30) is rejected "confidence_too_low (X < Y)". gate_decision()
  is called from ONE place: llm/decision_engine.get_trading_decision(), which is reached from
    (a) core/llm_integration._run_llm_metabrain()  - event triggers (lead-lag, cross-market
        divergence, position closed, ...). A PASS here is only logged, fed to regime_detector,
        written to LLM memory and cached. IT DOES NOT OPEN A POSITION.
    (b) core/llm_integration._llm_veto_check()      - mechanical-path PRE_TRADE veto. Not reached
        while LLM_FIRST_MODE=true (entries go through multi_strategy_main._process_symbol_llm_first
        -> coordinator.get_entry_decision, which never calls gate_decision). A gate REJECT on this
        path returns None from the veto check = "proceed" (gated: is not a fail-closed marker).
  So since the living floor went live, every r16 decision is a metabrain advisory call. "pass" rows
  are NOT trades; the trade_link resolution is a same-symbol PROXIMITY join (co-occurring
  LLM-first trade), never a causal one. The fwd counterfactual is computed for passes AND rejects
  alike so the laptop can test whether the floor sorts decisions at all.

SOURCES
  data/llm/decisions.jsonl  - one audit record per gate call (keys: ts, action, confidence,
                              allowed, gate_reason, trigger_reason, trigger_context, notes,
                              memory_update, snapshot{m:[{s,p,...}]}). Primary source.
  logs/bot_*.log[.1]        - JSON lines: [LIVING-FLOOR] floor=..., [LLM-GATE] ALLOWED/REJECTED,
                              "[<trace>][LLM] PROCEED|No decision: gated: ..." -> trace_id + 2dp floor.
  data/trade_ledger.csv     - closed trades (timestamp = CLOSE time; entry = close - hold_hours).
  data/candles_5m/<COIN>.jsonl archive + HL 5m (last ~17d) + HL 1h (tools/hivemind/hl.py).

START DATE
  FLOOR_START = 2026-09-13T17:42:00Z, the first "[LIVING-FLOOR] floor=" line in the bot logs.
  Earlier gate records used the hardcoded 0.60 and are not exported.

FILES (both append-only; never rewritten, never truncated)
  server_exports/conf_floor_decisions.jsonl    one row per gate decision, immutable facts known at
                                               decision time. key: decision_id ("cfd_<ts %.6f>").
  server_exports/conf_floor_resolutions.jsonl  outcome rows appended LATER, keyed by
                                               (decision_id, kind). Each (decision_id, kind) is
                                               written exactly once, only when FINAL:
      kind="fwd_v1"        forward counterfactual from HL candles, written once ts+24h has closed.
      kind="trade_link_v1" same-symbol ledger trade opened in [ts-30m, ts+2h]; written when a match
                           exists in the (closed-trade) ledger, or as no-match after ts+72h.
  The laptop joins resolutions onto decisions by decision_id. If a method changes, bump the kind
  suffix (_v2) and append new rows; never edit old ones.

IDEMPOTENT: every run re-reads the existing keys from both files and only appends new keys.
Safe hourly. RAM: all files streamed line by line; only gate records (~1k) are held in memory.

Run:  python tools/hivemind/conf_floor_export.py        (from bot/)
"""
import csv
import datetime as dt
import glob
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hl  # noqa: E402

BOT = Path(__file__).resolve().parents[2]
DECISIONS = BOT / "data" / "llm" / "decisions.jsonl"
LEDGER = BOT / "data" / "trade_ledger.csv"
LOGS = BOT / "logs"
C5 = BOT / "data" / "candles_5m"
EXP = BOT / "data" / "laptop_mining" / "server_exports"
OUT = EXP / "conf_floor_decisions.jsonl"
RES = EXP / "conf_floor_resolutions.jsonl"

UTC = dt.timezone.utc
FLOOR_START = dt.datetime(2026, 9, 13, 17, 42, 0, tzinfo=UTC).timestamp()
SCHEMA = "conf_floor_v1"

# living_conf_floor.py constants (mirrored for the replay; verified against the 2dp log value)
MIN_N, FLOOR_MIN, LEGACY, MAX_OBS, MAX_AGE_S, PCTL = 30, 0.30, 0.60, 500, 14 * 86400, 90.0

HORIZONS_H = (1, 4, 24)
FEE_RT_BPS = 9.0                     # assumed taker round trip used for the *_net_bps fields
LINK_BEFORE_S, LINK_AFTER_S = 1800, 7200
LINK_FINAL_S = 72 * 3600
KNOWN = {"BTC", "ETH", "SOL", "HYPE", "XRP", "NEAR", "FARTCOIN", "POPCAT", "DOGE", "SUI", "AVAX"}

RE_THESIS = re.compile(r"THESIS:\s*([^|]*)")
RE_SYM_DIR = re.compile(r"\b([A-Z]{2,10})\b[^|]{0,40}?\b(long|short|buy|sell|longs|shorts)\b", re.I)
RE_TARGET = re.compile(r"(?:toward|towards|to|targets?|reclaim(?:s|ing)?)\s*~?\s*\$\s*([\d,]+(?:\.\d+)?)", re.I)
RE_MEM = re.compile(r"\b([A-Z]{2,10})[ _](LONG|SHORT|BUY|SELL)\b")
RE_PRETRADE = re.compile(r"PRE_TRADE veto check:\s*(\w+)\s+([A-Z]{2,10})\s+@")
RE_FOLLOWER = re.compile(r"'follower':\s*'([A-Z]{2,10})'.*?'expected_follower_move':\s*(-?[\d.]+)")
RE_GATE = re.compile(r"\[LLM-GATE\] (ALLOWED|REJECTED): (\w+) conf=([\d.]+) regime=(\S+)(?: reason=(.*))?")
RE_FLOOR = re.compile(r"\[LIVING-FLOOR\] floor=([\d.]+) \(P(\d+) of n=(\d+) live confidences, raw=([\d.]+)")
RE_TRACE = re.compile(r"^\[([0-9a-f]{6,})\]\[LLM\] (PROCEED|FLIP|FLAT|GO|No decision: gated)")
RE_REJ_FLOOR = re.compile(r"\(([\d.]+) < ([\d.]+)\)")


def iso(ts):
    return dt.datetime.fromtimestamp(ts, UTC).isoformat(timespec="seconds")


def did(ts):
    return f"cfd_{ts:.6f}"


def read_keys(path, fields):
    keys = set()
    if not path.exists():
        return keys
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            keys.add(tuple(r.get(k) for k in fields))
    return keys


def append(path, rows):
    if not rows:
        return
    EXP.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")


# ── 1. gate records from decisions.jsonl ──────────────────────────────────────

def gate_records():
    """All non-flat gate records (incl. pre-START ones, needed to replay the floor window)."""
    out = []
    with open(DECISIONS, encoding="utf-8", errors="replace") as f:
        for line in f:
            if '"gate_reason"' not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("action") == "flat" or d.get("confidence") is None:
                continue
            out.append(d)
    out.sort(key=lambda d: d["ts"])
    return out


def replay_floor(recs):
    """Recompute base_floor() at each gate call from the confidences the gate recorded.

    record() runs before base_floor() in gate_decision, so the current confidence is in the window.
    The persisted store survives restarts, so the window is simply every prior gate record.
    """
    window, res = [], {}
    for d in recs:
        ts = d["ts"]
        c = float(d["confidence"])
        if 0.0 <= c <= 1.0:
            window.append((ts, c))
        window = [o for o in window if ts - o[0] <= MAX_AGE_S][-MAX_OBS:]
        vals = sorted(c for _, c in window)
        if len(vals) < MIN_N:
            res[ts] = (LEGACY, None, len(vals))
            continue
        raw = vals[min(max(int(round(PCTL / 100.0 * (len(vals) - 1))), 0), len(vals) - 1)]
        res[ts] = (min(LEGACY, max(FLOOR_MIN, raw)), raw, len(vals))
    return res


# ── 2. log enrichment (trace_id, logged 2dp floor) ────────────────────────────

def _log_ts(s):
    try:
        return dt.datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None


def log_events(t0, t1):
    """Stream bot logs overlapping [t0, t1]; keep only floor/gate/trace lines in that window."""
    ev = []
    for p in sorted(glob.glob(str(LOGS / "bot_*.log*"))):
        m = re.search(r"bot_(\d{8})\.log", p)
        if not m:
            continue
        start = dt.datetime.strptime(m.group(1), "%Y%m%d").replace(tzinfo=UTC).timestamp()
        if start > t1 + 86400 or os.path.getmtime(p) < t0 - 3600:
            continue
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                if "LIVING-FLOOR] floor" not in line and "LLM-GATE" not in line and "][LLM] " not in line:
                    continue
                try:
                    j = json.loads(line)
                except ValueError:
                    continue
                ts = _log_ts(j.get("ts", ""))
                if ts is None or ts < t0 - 120 or ts > t1 + 120:
                    continue
                msg = j.get("msg", "")
                g = RE_GATE.search(msg)
                if g:
                    ev.append((ts, "gate", g.groups()))
                    continue
                fl = RE_FLOOR.search(msg)
                if fl:
                    ev.append((ts, "floor", fl.groups()))
                    continue
                tr = RE_TRACE.search(msg)
                if tr:
                    ev.append((ts, "trace", tr.groups()))
    ev.sort(key=lambda e: e[0])
    # de-dup (the same line can sit in both bot_X.log and its rotated .1)
    out, seen = [], set()
    for e in ev:
        k = (round(e[0], 6), e[1])
        if k not in seen:
            seen.add(k)
            out.append(e)
    return out


def match_log(d, ev, ev_ts):
    """Find this decision's [LLM-GATE] line (written ms before the audit record)."""
    import bisect
    ts = d["ts"]
    conf2 = f"{float(d['confidence']):.2f}"
    i = bisect.bisect_left(ev_ts, ts - 5)
    gate_i = None
    while i < len(ev) and ev[i][0] <= ts + 2:
        if ev[i][1] == "gate" and ev[i][2][2] == conf2 and \
                (ev[i][2][0] == "ALLOWED") == bool(d.get("allowed")) and \
                (gate_i is None or abs(ev[i][0] - ts) < abs(ev[gate_i][0] - ts)):
            gate_i = i
        i += 1
    if gate_i is None:
        return {}
    gts = ev[gate_i][0]
    out = {"log_gate_ts": round(gts, 6)}
    j = gate_i - 1
    while j >= 0 and gts - ev[j][0] <= 5:
        if ev[j][1] == "floor":
            fl, p, n, raw = ev[j][2]
            out.update(log_floor_2dp=float(fl), log_floor_n=int(n), log_floor_raw_2dp=float(raw))
            break
        j -= 1
    j = gate_i + 1
    while j < len(ev) and ev[j][0] - gts <= 5:
        if ev[j][1] == "trace":
            out["trace_id"] = ev[j][2][0]
            break
        j += 1
    return out


# ── 3. symbol / side inference ────────────────────────────────────────────────

def snapshot_prices(d):
    px = {}
    for m in ((d.get("snapshot") or {}).get("m") or []):
        try:
            px[m["s"]] = float(m["p"])
        except (KeyError, TypeError, ValueError):
            pass
    return px


def infer(d, px):
    """(symbol, side, source, thesis_target, trigger_symbol, trigger_side)."""
    tc = d.get("trigger_context") or ""
    notes = d.get("notes") or ""
    mem = d.get("memory_update") or ""
    known = KNOWN | set(px)

    trig_sym = trig_side = None
    f = RE_FOLLOWER.search(tc)
    if f:
        trig_sym = f.group(1)
        trig_side = "LONG" if float(f.group(2)) > 0 else "SHORT"

    p = RE_PRETRADE.search(tc)
    if p and p.group(2) in known:
        side = "LONG" if p.group(1).upper() in ("LONG", "BUY") else "SHORT"
        return p.group(2), side, "pre_trade_trigger", None, trig_sym, trig_side

    sym = side = src = target = None
    t = RE_THESIS.search(notes)
    thesis = t.group(1) if t else ""
    if thesis:
        first = re.search(r"\b([A-Z]{2,10})\b", thesis)
        if first and first.group(1) in known:
            sym = first.group(1)
        sd = RE_SYM_DIR.search(thesis)
        if sd and sd.group(1) in known and (sym is None or sd.group(1) == sym):
            sym = sd.group(1)
            side = "LONG" if sd.group(2).lower() in ("long", "buy", "longs") else "SHORT"
            src = "thesis_direction_word"
        tg = RE_TARGET.search(thesis)
        if tg and sym and px.get(sym):
            try:
                v = float(tg.group(1).replace(",", ""))
                if 0.8 * px[sym] <= v <= 1.2 * px[sym] and v != px[sym]:
                    target = v
            except ValueError:
                pass
        if sym and side is None and target is not None:
            side = "LONG" if target > px[sym] else "SHORT"
            src = "thesis_target_vs_price"
    if sym and side is None:
        for mm in RE_MEM.finditer(mem):
            if mm.group(1) == sym:
                side = "LONG" if mm.group(2) in ("LONG", "BUY") else "SHORT"
                src = "memory_update"
                break
    if sym is None:
        mm = RE_MEM.search(mem)
        if mm and mm.group(1) in known:
            sym = mm.group(1)
            side = "LONG" if mm.group(2) in ("LONG", "BUY") else "SHORT"
            src = "memory_update"
    if sym and side is None:
        src = "thesis_symbol_only"
    if sym is None and trig_sym:
        sym, side, src = trig_sym, trig_side, "trigger_follower"
    return sym, side, src, target, trig_sym, trig_side


# ── 4. build decision rows ────────────────────────────────────────────────────

def build_rows(new, floors, ev):
    ev_ts = [e[0] for e in ev]
    rows = []
    for d in new:
        ts = d["ts"]
        conf = float(d["confidence"])
        reason = d.get("gate_reason") or ""
        rule = reason.split(" (")[0]
        px = snapshot_prices(d)
        sym, side, src, target, trig_sym, trig_side = infer(d, px)
        lg = match_log(d, ev, ev_ts)
        rf, rraw, rn = floors.get(ts, (None, None, None))
        rej = RE_REJ_FLOOR.search(reason) if rule.endswith("confidence_too_low") else None
        reason_floor = float(rej.group(2)) if rej else None
        logged = lg.get("log_floor_2dp", reason_floor)
        replay_ok = (logged is not None and rf is not None and abs(round(rf, 2) - logged) < 0.0051)
        if replay_ok:
            floor, fsrc = rf, "replay_exact_matches_log"
        elif logged is not None:
            floor, fsrc = logged, "log_2dp"
        else:
            floor, fsrc = rf, "replay_unverified"
        allowed = bool(d.get("allowed"))
        rows.append({
            "schema": SCHEMA,
            "decision_id": did(ts),
            "ts": round(ts, 6),
            "ts_iso": iso(ts),
            "trace_id": lg.get("trace_id"),
            "log_matched": "log_gate_ts" in lg,
            "path": "pre_trade_veto" if d.get("trigger_reason") in ("pre_trade_veto", "pre-trade validation")
                    else "metabrain_advisory",
            "action": d.get("action"),
            "original_action": d.get("original_action"),
            "llm_confidence": conf,
            "floor": floor,
            "floor_source": fsrc,
            "floor_replay": rf,
            "floor_replay_raw": rraw,
            "floor_replay_n": rn,
            "floor_log_2dp": logged,
            "conf_minus_floor": round(conf - floor, 5) if floor is not None else None,
            "outcome": "pass" if allowed else "reject",
            "reject_rule": None if allowed else rule,
            "gate_reason": reason,
            "symbol": sym,
            "side": side,
            "symbol_side_source": src,
            "trigger_symbol": trig_sym,
            "trigger_side": trig_side,
            "trigger_reason": d.get("trigger_reason"),
            "regime": d.get("regime"),
            "size_multiplier": d.get("size_multiplier"),
            "mode": d.get("mode"),
            "snapshot_price": px.get(sym) if sym else None,
            "thesis_target": target,
            "thesis": (RE_THESIS.search(d.get("notes") or "") or [None, None])[1],
        })
    return rows


# ── 5. candles + forward counterfactual ───────────────────────────────────────

_BARS = {}


def bars(coin, iv, t0_ms, t1_ms):
    key = (coin, iv)
    if key not in _BARS:
        got = {}
        if iv == "5m":
            p = C5 / f"{coin}.jsonl"
            if p.exists():
                with open(p, encoding="utf-8") as f:
                    for line in f:
                        try:
                            b = json.loads(line)
                        except ValueError:
                            continue
                        if t0_ms - 3600_000 <= b["t"] <= t1_ms + 3600_000:
                            got[b["t"]] = (b["t"], float(b["o"]), float(b["h"]), float(b["l"]), float(b["c"]))
            start = max(t0_ms - 3600_000, int(time.time() * 1000) - 17 * 86400_000)
        else:
            start = t0_ms - 4 * 3600_000
        try:
            for b in hl.candles(coin, iv, start, None, ttl=3600) or []:
                got.setdefault(b["t"], (b["t"], float(b["o"]), float(b["h"]), float(b["l"]), float(b["c"])))
        except Exception:
            pass
        _BARS[key] = sorted(got.values())
    return _BARS[key]


def fwd(row, now):
    ts, sym, side = row["ts"], row["symbol"], row["side"]
    base = {"decision_id": row["decision_id"], "kind": "fwd_v1", "resolved_at": iso(now),
            "symbol": sym, "side": side}
    if not sym:
        return dict(base, method="unresolvable_no_symbol")
    ms = int(ts * 1000)
    hmax = max(HORIZONS_H) * 3600_000
    for iv, step in (("5m", 300_000), ("1h", 3600_000)):
        bs = [b for b in bars(sym, iv, ms - step, ms + hmax) if ms - 2 * step <= b[0] <= ms + hmax]
        prior = [b for b in bs if b[0] + step <= ms]
        after = [b for b in bs if b[0] + step > ms]
        need = hmax // step
        if not prior or len(after) < 0.95 * need:
            continue
        entry = prior[-1][4]
        sign = {"LONG": 1, "SHORT": -1}.get(side)
        out = dict(base, method=f"fwd_return_hl_{iv}", entry_px=entry,
                   entry_px_rule=f"close of last {iv} bar closed at/before decision ts",
                   fee_rt_bps_assumed=FEE_RT_BPS)
        for h in HORIZONS_H:
            end = ms + h * 3600_000
            win = [b for b in after if b[0] + step <= end]
            if not win:
                continue
            raw = (win[-1][4] / entry - 1) * 1e4
            hi = max(b[2] for b in win)
            lo = min(b[3] for b in win)
            out[f"ret_{h}h_raw_bps"] = round(raw, 2)
            if sign:
                out[f"ret_{h}h_bps"] = round(sign * raw, 2)
                out[f"ret_{h}h_net_bps"] = round(sign * raw - FEE_RT_BPS, 2)
                fav, adv = (hi, lo) if sign > 0 else (lo, hi)
                out[f"mfe_{h}h_bps"] = round(sign * (fav / entry - 1) * 1e4, 2)
                out[f"mae_{h}h_bps"] = round(sign * (adv / entry - 1) * 1e4, 2)
                tgt = row.get("thesis_target")
                if tgt and h in (4, 24) and (tgt - entry) * sign > 0:
                    out[f"thesis_target_hit_{h}h"] = bool(hi >= tgt if sign > 0 else lo <= tgt)
        if not sign:
            out["note"] = "side unknown: only raw (unsigned) returns"
        return out
    return None  # candles not (yet) available -> retry next run


# ── 6. trade-ledger proximity link ────────────────────────────────────────────

def load_ledger():
    out = []
    if not LEDGER.exists():
        return out
    with open(LEDGER, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            try:
                close_ts = float(r["timestamp"])
                hold = float(r.get("hold_hours") or 0)
                entry, exitp = float(r["entry_price"]), float(r["exit_price"])
                gross, fees, net = float(r["gross_pnl"]), float(r.get("fees") or 0), float(r["net_pnl"])
            except (KeyError, TypeError, ValueError):
                continue
            sign = 1 if r.get("side") == "LONG" else -1
            move = sign * (exitp / entry - 1) if entry else 0.0
            notional = gross / move if abs(move) > 1e-9 and gross else None
            out.append({
                "trade_id": r.get("trade_id"), "position_id": r.get("position_id") or None,
                "symbol": r.get("symbol"), "side": r.get("side"),
                "entry_ts": close_ts - hold * 3600, "close_ts": close_ts, "hold_hours": hold,
                "entry_price": entry, "exit_price": exitp, "exit_type": r.get("exit_type"),
                "net_pnl": net, "fees": fees, "gross_bps": round(move * 1e4, 2),
                "notional_est": round(notional, 2) if notional and notional > 0 else None,
                "net_bps": round(net / notional * 1e4, 2) if notional and notional > 0 else None,
                "realized_rr": float(r["realized_rr"]) if r.get("realized_rr") not in (None, "") else None,
            })
    return out


def link(row, ledger, now):
    ts, sym = row["ts"], row["symbol"]
    base = {"decision_id": row["decision_id"], "kind": "trade_link_v1", "resolved_at": iso(now),
            "method": "proximity_same_symbol_entry_in[-30m,+2h]_NOT_causal"}
    if not sym:
        return dict(base, matched=False, note="no symbol") if now - ts > LINK_FINAL_S else None
    cands = [t for t in ledger if t["symbol"] == sym and ts - LINK_BEFORE_S <= t["entry_ts"] <= ts + LINK_AFTER_S]
    if not cands:
        return dict(base, matched=False, n_candidates=0) if now - ts > LINK_FINAL_S else None
    cands.sort(key=lambda t: abs(t["entry_ts"] - ts))
    t = cands[0]
    return dict(base, matched=True, n_candidates=len(cands), same_side=(t["side"] == row["side"]),
                entry_delta_min=round((t["entry_ts"] - ts) / 60, 1),
                **{k: v for k, v in t.items() if k != "symbol"})


# ── main ──────────────────────────────────────────────────────────────────────

def run():
    now = time.time()
    have = {k[0] for k in read_keys(OUT, ("decision_id",))}
    recs = gate_records()
    floors = replay_floor(recs)
    new = [d for d in recs if d["ts"] >= FLOOR_START and did(d["ts"]) not in have]
    rows = []
    if new:
        ev = log_events(new[0]["ts"], new[-1]["ts"])
        rows = build_rows(new, floors, ev)
        append(OUT, rows)

    # resolutions over ALL exported decisions
    done = read_keys(RES, ("decision_id", "kind"))
    ledger = load_ledger()
    res = []
    with open(OUT, encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            i = row["decision_id"]
            if (i, "fwd_v1") not in done and now - row["ts"] > max(HORIZONS_H) * 3600 + 600:
                r = fwd(row, now)
                if r:
                    res.append(r)
            if (i, "trade_link_v1") not in done:
                r = link(row, ledger, now)
                if r:
                    res.append(r)
    append(RES, res)
    return {"new_decisions": len(rows),
            "new_pass": sum(r["outcome"] == "pass" for r in rows),
            "new_reject": sum(r["outcome"] == "reject" for r in rows),
            "new_resolutions": len(res)}


if __name__ == "__main__":
    print(json.dumps(run()))
