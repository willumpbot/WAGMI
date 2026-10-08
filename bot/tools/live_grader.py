"""Live agent grader: forward-grade every LLM agent decision as it matures.

Runs every 15 min (Task Scheduler, pythonw). Each run:
  1. tails new lines of data/llm/agent_performance.jsonl and new SIGNAL_GENERATED
     rows of data/trade_events.jsonl from stored byte offsets;
  2. groups agent records into pipelines (one decision round) and attaches the
     proposed side from the nearest preceding signal (<=15 min), else from text;
  3. once a decision is >= 12h old, prices it with Hyperliquid 5m candles
     (no lookahead: p0 = close of the last bar that ENDED at/before the decision)
     and appends it to data/agent_grades/live/resolved.jsonl in the same row
     schema as the 2026-10-07 historical study (data/agent_grades/build_dataset.py);
  4. rebuilds data/agent_grades/live/live_scorecard.json from resolved rows.

Read-only on bot data; writes only under data/agent_grades/live/. Stdlib only,
streams files, peak RAM a few MB. Safe to run any time; idempotent per offset.

Grading rules mirror data/agent_grades/grade.py (edge = side-signed 4h return
minus 9 bps fees; dedupe by symbol/side/decision/hour):
  trade   go vs skip            -> did the agent's GO picks beat its SKIPs?
  risk    take vs block         -> within trade-GO rounds
  critic  approve vs challenge  -> within trade-GO rounds
  exit    hold vs full_close    -> position-side return AFTER the decision (gross)
"""
import collections
import json
import os
import random
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BOT = Path(__file__).resolve().parent.parent
DATA = BOT / "data"
LIVE = DATA / "agent_grades" / "live"
STATE = LIVE / "state.json"
PENDING = LIVE / "pending.json"
RESOLVED = LIVE / "resolved.jsonl"
SCORECARD = LIVE / "live_scorecard.json"
HIST = DATA / "agent_grades" / "scorecard.json"

SYMS = {"BTC", "ETH", "SOL", "HYPE", "XRP", "NEAR"}
FEE = 9.0
HORIZONS = {"1h": 3600, "4h": 4 * 3600, "12h": 12 * 3600}
RESOLVE_AFTER = 12 * 3600 + 600   # 12h horizon + one bar of slack
FINALIZE_AFTER = 900              # a pipeline's records arrive within ~5 min
SIGNAL_MATCH = 900
SIGNAL_KEEP = 3 * 3600
BAR = 300
SIDE_RE = re.compile(r"\b(BUY|SELL|LONG|SHORT)\b")


def _log(msg):
    print(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z {msg}", flush=True)


def _load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj), encoding="utf-8")
    os.replace(tmp, path)


def _iso(s):
    t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.timestamp()


def _tail(path, offset):
    """Yield complete new lines after byte offset; return the new offset via list."""
    lines, new_off = [], offset
    try:
        size = path.stat().st_size
    except OSError:
        return lines, offset
    if size < offset:          # file rotated/truncated: restart from the top
        offset = 0
    with open(path, "rb") as f:
        f.seek(offset)
        chunk = f.read()
    end = chunk.rfind(b"\n")
    if end < 0:
        return lines, offset
    new_off = offset + end + 1
    for raw in chunk[: end + 1].splitlines():
        try:
            lines.append(raw.decode("utf-8"))
        except UnicodeDecodeError:
            continue
    return lines, new_off


def _text_side(txt, sym):
    m = re.search(re.escape(sym) + r"[ ._]?(BUY|SELL|LONG|SHORT)\b", txt)
    if m:
        g = m.group(1)
    else:
        c = collections.Counter(SIDE_RE.findall(txt[:300]))
        if not c:
            return None
        g = c.most_common(1)[0][0]
    return "LONG" if g in ("BUY", "LONG") else "SHORT"


# ── ingest ────────────────────────────────────────────────────────────

def ingest(state, pending):
    # signals first so a pipeline finalized this run can see them
    lines, state["ev_off"] = _tail(DATA / "trade_events.jsonl", state.get("ev_off", 0))
    sigs = state.setdefault("signals", [])
    for ln in lines:
        if "ic_muted" in ln and "SIGNAL_FILTERED" in ln:
            try:
                r = json.loads(ln)
                if r.get("symbol") in SYMS and r.get("entry"):
                    side = "LONG" if r.get("side") in ("BUY", "LONG") else "SHORT"
                    t = _iso(r["timestamp"])
                    pending.setdefault("dropped", []).append({
                        "kind": "dropped", "gate": "ic_muted", "ts": t, "sym": r["symbol"], "prop_side": side,
                        "strategies": r.get("strategy"), "sig": [t, r["symbol"], side, r.get("entry"), r.get("sl"),
                                                                 r.get("tp1"), r.get("num_agree"), r.get("confidence"),
                                                                 r.get("regime")],
                        "feat": decision_context(r["symbol"], side, t)})
            except Exception:
                pass
            continue
        if "SIGNAL_GENERATED" not in ln:
            continue
        try:
            r = json.loads(ln)
            if r.get("symbol") not in SYMS or not r.get("entry"):
                continue
            side = "LONG" if r.get("side") in ("BUY", "LONG") else "SHORT"
            sigs.append([_iso(r["timestamp"]), r["symbol"], side, r.get("entry"),
                         r.get("sl"), r.get("tp1"), r.get("num_agree"), r.get("confidence"),
                         r.get("regime")])
        except Exception:
            continue
    now = time.time()
    state["signals"] = [s for s in sigs if now - s[0] < SIGNAL_KEEP]

    lines, state["ap_off"] = _tail(DATA / "llm" / "agent_performance.jsonl", state.get("ap_off", 0))
    open_pipes = pending.setdefault("open", {})
    exits = pending.setdefault("exits", [])
    for ln in lines:
        try:
            r = json.loads(ln)
        except Exception:
            continue
        if r.get("type") != "decision":
            continue
        txt = str(r.get("reasoning_summary") or "")[:500]
        lat = r.get("latency_ms") or 0
        fallback = txt.startswith("technical_fallback") or "critic_fallback" in txt
        if lat < 1000 and not fallback:
            continue  # test-fixture signature (see agent_grades/SCORECARD.md caveats)
        slim = {"ts": r.get("timestamp"), "sym": r.get("symbol"), "side": r.get("side"),
                "dec": r.get("decision"), "conf": r.get("confidence"), "model": r.get("model_used"),
                "txt": txt, "fallback": fallback, "ctx": r.get("ctx")}
        role = r.get("agent_role")
        if role in ("trade", "critic", "risk", "quant", "regime"):
            open_pipes.setdefault(r.get("pipeline_id"), {})[role] = slim
        elif role == "exit" and slim["sym"] in SYMS:
            exits.append({"pid": r.get("pipeline_id"), **slim})

    # finalize pipelines whose records have all arrived
    ready = pending.setdefault("ready", [])
    for pid in list(open_pipes):
        m = open_pipes[pid]
        t0 = max(x["ts"] for x in m.values())
        if now - t0 < FINALIZE_AFTER:
            continue
        del open_pipes[pid]
        sym = next(iter(m.values()))["sym"]
        if sym not in SYMS:
            continue
        ctx = next((x["ctx"] for x in m.values() if x.get("ctx")), None)
        if ctx and ctx.get("trigger") != "llm_first_entry":
            # Event round: the agents looked at every market and `sym` is just
            # the first one in the snapshot. Not gradeable against one price.
            continue
        sg = None
        for s in reversed(state["signals"]):
            if s[1] == sym and 0 <= t0 - s[0] <= SIGNAL_MATCH:
                sg = s
                break
        txts = " ".join(m.get(k, {}).get("txt", "") for k in ("trade", "critic", "risk"))
        tside = _text_side(txts, sym)
        exact = (ctx or {}).get("signal") or {}
        exact_side = {"BUY": "LONG", "LONG": "LONG", "SELL": "SHORT", "SHORT": "SHORT"}.get(
            str(exact.get("side", "")).upper())
        if exact_side:
            sg = [t0, sym, exact_side, exact.get("entry"), exact.get("sl"), exact.get("tp1"),
                  sg[6] if sg else None, exact.get("confidence"), sg[8] if sg and len(sg) > 8 else None]
        row = {"kind": "pipeline", "pid": pid, "ts": t0, "sym": sym,
               "prop_side": sg[2] if sg else tside,
               "side_src": "exact" if exact_side else ("signal" if sg else ("text" if tside else None)),
               "round": "entry" if ctx else "unknown",
               "sig": sg}
        for role, x in m.items():
            row[role] = {"dec": x["dec"], "conf": x["conf"], "model": x["model"], "fallback": x["fallback"]}
        if row["prop_side"]:
            try:
                row["feat"] = decision_context(sym, row["prop_side"], t0)
            except Exception:
                pass
        ready.append(row)


# ── decision-time context (data/data_waves/DATA_WAVES.md) ────────────

def _tail_rows(path, max_bytes, parse):
    out = []
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - max_bytes))
            f.readline()
            for raw in f:
                try:
                    r = parse(json.loads(raw))
                    if r:
                        out.append(r)
                except Exception:
                    continue
    except OSError:
        pass
    return out


_CTX_CACHE = {}


def _context_sources():
    """Recent depth and funding rows per traded symbol: {sym: [(ts, value), ...]}."""
    if _CTX_CACHE:
        return _CTX_CACHE
    depth = collections.defaultdict(list)
    for sym, ts, v in _tail_rows(DATA / "market_depth_history.jsonl", 6_000_000, lambda r: (
            (r["symbol"], _iso(r["ts"]), r["l2"]["imbalance_1pct"]) if r.get("symbol") in SYMS else None)):
        depth[sym].append((ts, v))
    fund = collections.defaultdict(list)
    for sym, ts, v in _tail_rows(DATA / "funding_oi_history.jsonl", 3_000_000, lambda r: (
            (r["symbol"], _iso(r["timestamp"]), r["funding_rate"]) if r.get("symbol") in SYMS
            and r.get("funding_rate") is not None else None)):
        fund[sym].append((ts, v))
    _CTX_CACHE.update({"depth": depth, "fund": fund})
    return _CTX_CACHE


def _asof(series, t0, max_age):
    best = None
    for ts, v in series:
        if ts <= t0 and t0 - ts <= max_age and (best is None or ts > best[0]):
            best = (ts, v)
    return None if best is None else best[1]


def decision_context(sym, side, t0):
    """Bucketed features known AT decision time t0 (as-of joins, no lookahead)."""
    sgn = 1 if side == "LONG" else -1
    h = datetime.fromtimestamp(t0, timezone.utc).hour
    ctx = {"session": "asia" if h < 8 else "eu" if h < 13 else "us" if h < 20 else "late"}
    src = _context_sources()
    imb = _asof(src["depth"].get(sym, []), t0, 3600)
    if imb is not None:
        a = sgn * float(imb)
        ctx["book"] = "supports" if a > 0.1 else "against" if a < -0.1 else "balanced"
    f = _asof(src["fund"].get(sym, []), t0, 7200)
    if f is not None:
        f = float(f)
        pays = (side == "LONG" and f > 1.3125e-5) or (side == "SHORT" and f < 0)
        paid = (side == "LONG" and f < 0) or (side == "SHORT" and f > 1.3125e-5)
        ctx["funding"] = "side_pays" if pays else "side_paid" if paid else "neutral"
    return ctx


def btc_trend_context(side, t0):
    """BTC 4h move relative to side, from closed 5m bars ending at/before t0."""
    try:
        bars = candles("BTC", t0 - 5 * 3600)
    except Exception:
        return None
    done = [b for b in bars if b[0] + BAR <= t0]
    then = [b for b in done if b[0] + BAR <= t0 - 4 * 3600]
    if not done or not then:
        return None
    ret = done[-1][4] / then[-1][4] - 1
    a = ret if side == "LONG" else -ret
    return "with" if a > 0.005 else "against" if a < -0.005 else "flat"


# ── pricing ───────────────────────────────────────────────────────────

_CANDLES = {}


def candles(sym, start):
    """5m bars [start_s, o, h, l, c] from `start` to now, cached per run."""
    have = _CANDLES.get(sym)
    if have and have[0] <= start:
        return have[1]
    body = json.dumps({"type": "candleSnapshot", "req": {
        "coin": sym, "interval": "5m",
        "startTime": int((start - 3600) * 1000), "endTime": int(time.time() * 1000)}}).encode()
    req = urllib.request.Request("https://api.hyperliquid.xyz/info", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = json.loads(resp.read())
    bars = sorted([int(b["t"]) / 1000, float(b["o"]), float(b["h"]), float(b["l"]), float(b["c"])] for b in raw)
    _CANDLES[sym] = (start, bars)
    return bars


def forward(sym, t0):
    bars = candles(sym, t0)
    before = [b for b in bars if b[0] + BAR <= t0]
    if not before or t0 - (before[-1][0] + BAR) > 1800:
        return None
    p0 = before[-1][4]
    out = {"p0": p0}
    for name, h in HORIZONS.items():
        nxt = next((b for b in bars if b[0] >= t0 + h), None)
        out["r" + name] = None if nxt is None else round((nxt[1] / p0 - 1) * 1e4, 2)
    path = [b for b in bars if t0 <= b[0] < t0 + HORIZONS["12h"]]
    if path:
        out["up12"] = round((max(b[2] for b in path) / p0 - 1) * 1e4, 1)
        out["dn12"] = round((1 - min(b[3] for b in path) / p0) * 1e4, 1)
    return out, path


def sltp(path, side, sl, tp):
    try:
        sl, tp = float(sl), float(tp)
    except Exception:
        return None
    for b in path:
        hit_sl = b[3] <= sl if side == "LONG" else b[2] >= sl
        hit_tp = b[2] >= tp if side == "LONG" else b[3] <= tp
        if hit_sl:
            return "SL"   # same-bar ties count as SL (conservative, as in the study)
        if hit_tp:
            return "TP"
    return "NONE"


def resolve(pending):
    now = time.time()
    due_pipes = [r for r in pending.get("ready", []) if now - r["ts"] >= RESOLVE_AFTER]
    due_exits = [r for r in pending.get("exits", []) if now - r["ts"] >= RESOLVE_AFTER]
    due_drops = [r for r in pending.get("dropped", []) if now - r["ts"] >= RESOLVE_AFTER]
    due_pipes = due_pipes + due_drops
    if not due_pipes and not due_exits:
        return 0
    done = 0
    with open(RESOLVED, "a", encoding="utf-8") as fo:
        for r in due_pipes:
            try:
                f = forward(r["sym"], r["ts"])
            except Exception as e:
                _log(f"price fetch failed {r['sym']}: {e}")
                continue   # stays pending; retried next run
            (pending["dropped"] if r.get("kind") == "dropped" else pending["ready"]).remove(r)
            if f is None:
                continue
            fw, path = f
            sg = r.pop("sig", None)
            row = {**r, **fw}
            if row.get("prop_side"):
                bt = btc_trend_context(row["prop_side"], row["ts"])
                if bt:
                    row.setdefault("feat", {})["btc4h"] = bt
            if sg:
                row["sltp"] = sltp(path, sg[2], sg[4], sg[5])
                row["sig_agree"], row["sig_conf"] = sg[6], sg[7]
                row["sig_regime"] = sg[8] if len(sg) > 8 else None
            fo.write(json.dumps(row) + "\n")
            done += 1
        for r in due_exits:
            try:
                f = forward(r["sym"], r["ts"])
            except Exception as e:
                _log(f"price fetch failed {r['sym']}: {e}")
                continue
            pending["exits"].remove(r)
            if f is None:
                continue
            fo.write(json.dumps({"kind": "exit", "pid": r["pid"], "ts": r["ts"], "sym": r["sym"],
                                 "pos_side": r["side"], "dec": r["dec"], "model": r["model"],
                                 "conf": r["conf"], **f[0]}) + "\n")
            done += 1
    return done


# ── scorecard ─────────────────────────────────────────────────────────

def _sgn(side):
    return 1 if side in ("LONG", "BUY") else -1


def _risk_take(dec):
    dec = dec or ""
    try:
        sz = float(dec.split("size=")[1].split(",")[0])
    except Exception:
        return None
    ov = dec.split("override=")[1] if "override=" in dec else None
    return sz > 0 and ov != "skip"


def _dedupe(rows, key):
    seen, out = set(), []
    for r in rows:
        k = key(r)
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def _summ(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return {"n": 0}
    return {"n": len(vals), "mean_bps": round(sum(vals) / len(vals), 1),
            "hit": round(sum(v > 0 for v in vals) / len(vals), 3)}


def _diff(a, b, n_boot=1000):
    a = [v for v in a if v is not None]
    b = [v for v in b if v is not None]
    if len(a) < 2 or len(b) < 2:
        return {"nA": len(a), "nB": len(b)}
    d = sum(a) / len(a) - sum(b) / len(b)
    rnd = random.Random(7)
    boots = sorted(
        sum(rnd.choice(a) for _ in a) / len(a) - sum(rnd.choice(b) for _ in b) / len(b)
        for _ in range(n_boot))
    return {"nA": len(a), "nB": len(b), "diff_bps": round(d, 1),
            "ci95": [round(boots[int(0.025 * n_boot)], 1), round(boots[int(0.975 * n_boot)], 1)]}


def _verdict(d, n_needed=100):
    if "diff_bps" not in d:
        return "collecting"
    n = min(d["nA"], d["nB"])
    lo, hi = d["ci95"]
    if n < 30:
        return "collecting"
    if lo > 0:
        return "earning" if n >= n_needed else "promising"
    if hi < 0:
        return "backwards"
    return "no edge yet"


def build_scorecard():
    rows = []
    try:
        with open(RESOLVED, encoding="utf-8") as f:
            for ln in f:
                try:
                    rows.append(json.loads(ln))
                except Exception:
                    continue
    except FileNotFoundError:
        pass
    pipes = [r for r in rows if r["kind"] == "pipeline" and r.get("prop_side") and r.get("r4h") is not None]
    for r in pipes:
        r["e"] = _sgn(r["prop_side"]) * r["r4h"] - FEE
    hour = lambda r: int(r["ts"] // 3600)

    def tdec(r):
        d = (r.get("trade") or {}).get("dec")
        return "go" if d == "go" else ("skip" if d in ("skip", "flat") else None)

    T = _dedupe([r for r in pipes if tdec(r)], lambda r: (r["sym"], r["prop_side"], tdec(r), hour(r)))
    trade = _diff([r["e"] for r in T if tdec(r) == "go"], [r["e"] for r in T if tdec(r) == "skip"])

    G = [r for r in pipes if tdec(r) == "go"]
    Rk = [r for r in G if "risk" in r and _risk_take(r["risk"]["dec"]) is not None]
    Rk = _dedupe(Rk, lambda r: (r["sym"], r["prop_side"], _risk_take(r["risk"]["dec"]), hour(r)))
    risk = _diff([r["e"] for r in Rk if _risk_take(r["risk"]["dec"])],
                 [r["e"] for r in Rk if not _risk_take(r["risk"]["dec"])])

    Ck = [r for r in G if "critic" in r and not r["critic"].get("fallback")]
    Ck = _dedupe(Ck, lambda r: (r["sym"], r["prop_side"], r["critic"]["dec"], hour(r)))
    critic = _diff([r["e"] for r in Ck if r["critic"]["dec"] == "approve"],
                   [r["e"] for r in Ck if r["critic"]["dec"] in ("challenge", "veto", "reject")])

    # Confidence bar (llm/living_conf_floor.py): the gate passes roughly the top
    # 10% of confidences. Within trade-GO rounds, compare those above a trailing
    # P90 cut (computed only from earlier GO rounds) against the rest.
    Gs = sorted([r for r in G if (r.get("trade") or {}).get("conf") is not None], key=lambda r: r["ts"])
    above, below, hist_conf = [], [], []
    for r in Gs:
        c = float(r["trade"]["conf"])
        if len(hist_conf) >= 30:
            cut = sorted(hist_conf[-200:])[int(0.9 * (len(hist_conf[-200:]) - 1))]
            (above if c >= cut else below).append(r["e"])
        hist_conf.append(c)
    floor = _diff(above, below)

    X = [r for r in rows if r["kind"] == "exit" and r.get("r4h") is not None and r.get("pos_side")]
    X = _dedupe(X, lambda r: (r["sym"], r["pos_side"], r["dec"], hour(r)))
    xv = lambda r: _sgn(r["pos_side"]) * r["r4h"]
    exit_ = _diff([xv(r) for r in X if r["dec"] == "hold"], [xv(r) for r in X if r["dec"] == "full_close"])

    D = [r for r in rows if r["kind"] == "dropped" and r.get("r4h") is not None]
    D = _dedupe(D, lambda r: (r["sym"], r["prop_side"], hour(r)))
    dropped = _summ([_sgn(r["prop_side"]) * r["r4h"] - FEE for r in D])
    base = _dedupe(pipes, lambda r: (r["sym"], r["prop_side"], hour(r)))
    hist = _load(HIST, {})

    def hist_line(path):
        cur = hist
        for k in path:
            cur = cur.get(k, {}) if isinstance(cur, dict) else {}
        return cur.get("diff_bps") if isinstance(cur, dict) else None

    agents = {
        "trade":  {"question": "Did its GO picks beat its SKIPs?", **trade, "verdict": _verdict(trade),
                   "historical_diff_bps": hist_line(["trade", "go_minus_skip"])},
        "risk":   {"question": "On GO rounds, did what it let through beat what it blocked?", **risk,
                   "verdict": _verdict(risk),
                   "historical_diff_bps": hist_line(["risk", "within_trade_go_take_minus_block"])},
        "critic": {"question": "On GO rounds, did its approvals beat its challenges?", **critic,
                   "verdict": _verdict(critic)},
        "confidence bar": {"question": "On GO rounds, did the top-10% confidence calls (what the bar lets through) beat the rest?",
                           **floor, "verdict": _verdict(floor),
                           # 10-07 study rows, same trailing-P90 method: +11.0 bps, CI [-13.9, +32.9], n 136 vs 744
                           "historical_diff_bps": 11.0},
        "exit":   {"question": "After it said HOLD, did the position do better than after FULL CLOSE? (gross)",
                   **exit_, "verdict": _verdict(exit_)},
    }
    sc = {
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "horizon": "4h", "fee_bps": FEE,
        "since": datetime.fromtimestamp(min((r["ts"] for r in rows), default=time.time()), timezone.utc)
                 .isoformat(timespec="seconds"),
        "resolved_rows": len(rows),
        "baseline_take_every_signal": _summ([r["e"] for r in base]),
        "ic_muted_drops": {**dropped, "question": "Signals the IC gate silently dropped: what would taking them have made? "
                           "Negative = the gate is right to drop them."},
        "agents": agents,
        "models_seen": dict(collections.Counter(
            (r.get("trade") or {}).get("model") for r in pipes if r.get("trade"))),
    }
    _save(SCORECARD, sc)
    return sc


START_TS = datetime(2026, 10, 7, 18, 11, tzinfo=timezone.utc).timestamp()


def _offset_at(path, since, ts_of):
    """Byte offset of the first line whose timestamp is >= since."""
    off = 0
    with open(path, "rb") as f:
        for raw in f:
            try:
                ts = ts_of(json.loads(raw))
                if ts is not None and float(ts) >= since:
                    return off
            except Exception:
                pass
            off += len(raw)
    return off


PROGRESS = LIVE / "progress.json"
HIST_ROWS = DATA / "agent_grades" / "graded_decisions.jsonl"
HIST_WEEKLY_CACHE = LIVE / "hist_weekly.json"


def _week(ts):
    d = datetime.fromtimestamp(ts, timezone.utc)
    return d.strftime("%G-W%V")


def _weekly_pick_quality(path):
    """Per ISO week: mean edge of the trade agent's GO picks minus its SKIPs (bps, 4h, net)."""
    agg = collections.defaultdict(lambda: {"go": [], "skip": []})
    seen = set()
    try:
        f = open(path, encoding="utf-8")
    except FileNotFoundError:
        return {}
    with f:
        for ln in f:
            try:
                r = json.loads(ln)
            except Exception:
                continue
            if r.get("kind") != "pipeline" or not r.get("prop_side") or r.get("r4h") is None:
                continue
            d = (r.get("trade") or {}).get("dec")
            d = "go" if d == "go" else ("skip" if d in ("skip", "flat") else None)
            if not d:
                continue
            key = (r["sym"], r["prop_side"], d, int(r["ts"] // 3600))
            if key in seen:
                continue
            seen.add(key)
            e = _sgn(r["prop_side"]) * r["r4h"] - FEE
            agg[_week(r["ts"])][d].append(e)
    out = {}
    for wk, v in agg.items():
        g, s = v["go"], v["skip"]
        out[wk] = {"n_go": len(g), "n_skip": len(s),
                   "go_minus_skip": round(sum(g) / len(g) - sum(s) / len(s), 1) if len(g) >= 5 and len(s) >= 5 else None}
    return out


def build_progress():
    """Weekly series for the dashboard's 'how it's improving' charts."""
    hist = _load(HIST_WEEKLY_CACHE, None)
    try:
        mtime = HIST_ROWS.stat().st_mtime
    except OSError:
        mtime = 0
    if not hist or hist.get("mtime") != mtime:
        hist = {"mtime": mtime, "weeks": _weekly_pick_quality(HIST_ROWS)}
        _save(HIST_WEEKLY_CACHE, hist)
    weeks = dict(hist["weeks"])
    weeks.update(_weekly_pick_quality(RESOLVED))   # live rows win for overlapping weeks

    pnl = []
    try:
        import csv
        with open(DATA / "trade_ledger.csv", encoding="utf-8") as f:
            rows = sorted((float(r["timestamp"]), float(r["net_pnl"] or 0)) for r in csv.DictReader(f)
                          if r.get("timestamp"))
        cum = 0.0
        for ts, p in rows:
            cum += p
            pnl.append([round(ts), round(cum, 2)])
    except Exception:
        pass
    _save(PROGRESS, {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "pick_quality_weekly": dict(sorted(weeks.items())),
                     "cum_pnl": pnl})


def main():
    LIVE.mkdir(parents=True, exist_ok=True)
    state = _load(STATE, {})
    pending = _load(PENDING, {})
    if "ap_off" not in state:
        # First run: history up to 10-05 is graded by the 10-07 study; start the
        # live record at the 10-07 power-up restart (Opus trade/critic) by default.
        since = START_TS
        for a in sys.argv:
            if a.startswith("--since="):
                since = float(a.split("=", 1)[1])
        state["ap_off"] = _offset_at(DATA / "llm" / "agent_performance.jsonl", since,
                                     lambda r: r.get("timestamp"))
        state["ev_off"] = _offset_at(DATA / "trade_events.jsonl", since - SIGNAL_KEEP,
                                     lambda r: _iso(r["timestamp"]))
        _log(f"first run: starting at {datetime.fromtimestamp(since, timezone.utc):%Y-%m-%d %H:%M}Z")
    ingest(state, pending)
    n = resolve(pending)
    _save(PENDING, pending)
    _save(STATE, state)
    sc = build_scorecard()
    try:
        build_progress()
    except Exception as e:
        _log(f"progress build failed: {e}")
    _log(f"resolved {n}; pending {len(pending.get('ready', []))} pipelines + "
         f"{len(pending.get('exits', []))} exits; open {len(pending.get('open', {}))}; "
         f"total graded {sc['resolved_rows']}")


if __name__ == "__main__":
    if "--rebuild-scorecard" in sys.argv:
        print(json.dumps(build_scorecard(), indent=1))
    else:
        main()
