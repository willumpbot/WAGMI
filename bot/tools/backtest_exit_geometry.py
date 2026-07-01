"""
Exit-geometry backtest — owner decision D3 evidence (2026-07-02).

Replays every closed trade in bot/data/trades.csv against Hyperliquid 1h
candles and simulates exit-management variants:

  V0  CURRENT mechanical config (baseline / reproduction check)
      - profit lock: BE at 1.2R, lock 0.3R at 1.8R (MEDIUM, position_manager.py:580-585)
      - trailing ONLY in TRAILING state (post-TP1), distance = 1.5*ATR (env
        TRAILING_STOP_ATR_MULT=1.5), tighten 0.80->0.65
      - post-TP1 floor: progress = peak/(tp2-entry) -> insta-locks 57.5% of peak
  V1  WIRING_AUDIT #4 fix: trailing+floor ratchet active in OPEN state once
      peak >= 0.5R (pre-TP1 profit protection)
  V2  WIRING_AUDIT #5 fix: post-TP1 progress computed FROM TP1
      (progress = (peak-tp1)/(tp2-tp1)); floor no longer insta-locks 57.5% of
      peak at the moment TP1 fills; min floor stays breakeven+fees
  V3  V1 + V2
  V4  ARCHAEOLOGY config: pre-2026-04-20 profit-lock triggers
      (MEDIUM BE at 0.6R, lock 0.3R at 1.0R — commit b937691, raised by 585518d)
  V5  V3 + V4

No bot imports. Standalone. Read-only on live code paths.

Data sources:
  bot/data/trades.csv           — 90 closed trades (2026-06-01 .. 2026-07-01)
  bot/data/trade_events.jsonl   — TRADE_OPENED events carry sl/tp1/tp2/atr/qty
  Hyperliquid /info candleSnapshot (free, public) — 1h candles, cached locally

Known fidelity limits (stated in the report):
  - 1h candle granularity; intra-candle path approximated O->L->H->C (green)
    or O->H->L->C (red). Entry candle skipped (no look-inside before entry).
  - LLM Exit Agent closes, time-stop reviews, and wiring partial closes are
    NOT simulated — V0 is the pure mechanical geometry. Divergence from
    actuals post-Jun-7 measures the LLM-exit layer, not sim error.
  - Funding ignored (funding_oi_history.jsonl has a 536h hole Jun 7-29).
  - Dynamic TP overshoot scaling not simulated (fills assumed at TP1 level);
    speed-based close-pct scaling not simulated (fixed 50%).
"""

import csv
import json
import math
import os
import sys
import time
import urllib.request
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # bot/
TRADES_CSV = ROOT / "data" / "trades.csv"
EVENTS_JSONL = ROOT / "data" / "trade_events.jsonl"
CACHE_DIR = ROOT / "data" / "cache" / "exit_geometry_bt"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

HL_INFO = "https://api.hyperliquid.xyz/info"
TAKER_FEE_BPS = 4                 # position_manager default
FEE_BUFFER_EXTRA = 0.001          # position_manager BE fee buffer extra
MAX_HOLD_HOURS = 72.0             # check_hold_limits: 48h * 1.5 hard force-close
ERA_SPLIT = datetime(2026, 6, 7, tzinfo=timezone.utc)


# ── Variant configs ──────────────────────────────────────────────────────

@dataclass
class VariantCfg:
    name: str
    desc: str
    be_trigger: float = 1.2       # MEDIUM current (SHIP-2026-04-20)
    lock_trigger: float = 1.8
    lock_frac: float = 0.3
    pre_tp1_trail: bool = False   # V1: trailing ratchet in OPEN state
    pre_tp1_activation_r: float = 0.5
    progress_from_tp1: bool = False  # V2: floor progress measured from TP1
    trail_mult: float = 1.5       # live .env TRAILING_STOP_ATR_MULT=1.5
    tighten_start: float = 0.80   # MEDIUM base profile
    tighten_end: float = 0.65
    floor_progress: float = 0.15
    floor_start: float = 0.40
    floor_max: float = 0.70
    tp1_close_pct: float = 0.50


VARIANTS = [
    VariantCfg("V0", "current mechanical config (baseline)"),
    VariantCfg("V1", "pre-TP1 trail at peak>=0.5R (#4 fix)", pre_tp1_trail=True),
    VariantCfg("V2", "post-TP1 progress from TP1 (#5 fix)", progress_from_tp1=True),
    VariantCfg("V3", "V1+V2 combined", pre_tp1_trail=True, progress_from_tp1=True),
    VariantCfg("V4", "archaeology: pre-Apr-20 profit lock (BE 0.6R, lock 1.0R)",
               be_trigger=0.6, lock_trigger=1.0),
    VariantCfg("V5", "V3+V4 hybrid", pre_tp1_trail=True, progress_from_tp1=True,
               be_trigger=0.6, lock_trigger=1.0),
    # ── sensitivity sweep (not owner-decision variants, robustness only) ──
    VariantCfg("S1", "pre-TP1 trail at 0.75R", pre_tp1_trail=True,
               pre_tp1_activation_r=0.75, progress_from_tp1=True),
    VariantCfg("S2", "pre-TP1 trail at 1.0R", pre_tp1_trail=True,
               pre_tp1_activation_r=1.0, progress_from_tp1=True),
    VariantCfg("S3", "archaeology Apr-1 lock (BE 0.3R, lock 0.6R)",
               be_trigger=0.3, lock_trigger=0.6),
    VariantCfg("S4", "V4 + pre-TP1 trail at 0.75R", be_trigger=0.6, lock_trigger=1.0,
               pre_tp1_trail=True, pre_tp1_activation_r=0.75, progress_from_tp1=True),
    VariantCfg("S5", "BE 0.8R, lock 1.2R (mid)", be_trigger=0.8, lock_trigger=1.2),
    VariantCfg("S6", "V4 + pre-TP1 trail at 1.0R", be_trigger=0.6, lock_trigger=1.0,
               pre_tp1_trail=True, pre_tp1_activation_r=1.0, progress_from_tp1=True),
]


# ── Data loading ─────────────────────────────────────────────────────────

def parse_ts(s):
    s = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def load_trades():
    with open(TRADES_CSV, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_open_events():
    opens = []
    with open(EVENTS_JSONL, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or '"TRADE_OPENED"' not in line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("event") == "TRADE_OPENED":
                opens.append(e)
    return opens


def match_open(trade, opens):
    """Match a trades.csv row (timestamp = close time) to its TRADE_OPENED event."""
    sym, side = trade["symbol"], trade["side"]
    entry = float(trade["entry"])
    close_ts = parse_ts(trade["timestamp"])
    best, best_dt = None, None
    for e in opens:
        if e.get("symbol") != sym or e.get("side") != side:
            continue
        try:
            e_entry = float(e.get("entry", 0))
        except (TypeError, ValueError):
            continue
        if entry == 0 or abs(e_entry - entry) / entry > 0.0005:
            continue
        ets = parse_ts(e["timestamp"])
        if ets > close_ts + timedelta(minutes=2):
            continue
        if best is None or ets > best_dt:
            best, best_dt = e, ets
    return best


# ── Candles ──────────────────────────────────────────────────────────────

def fetch_candles(coin, start_ms, end_ms):
    cache = CACHE_DIR / f"{coin}_1h_{start_ms}_{end_ms}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    body = json.dumps({
        "type": "candleSnapshot",
        "req": {"coin": coin, "interval": "1h",
                "startTime": start_ms, "endTime": end_ms},
    }).encode()
    for attempt in range(4):
        try:
            req = urllib.request.Request(
                HL_INFO, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
            out = [{"t": int(c["t"]), "o": float(c["o"]), "h": float(c["h"]),
                    "l": float(c["l"]), "c": float(c["c"])} for c in data]
            cache.write_text(json.dumps(out))
            return out
        except Exception as ex:  # noqa: BLE001
            wait = 2 ** attempt
            print(f"  [{coin}] fetch failed ({ex}), retry in {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"could not fetch candles for {coin}")


# ── Simulation engine (mirrors position_manager.update_price mechanics) ──

@dataclass
class SimResult:
    pnl: float = 0.0
    exit_action: str = ""
    tp1_hit: bool = False
    hold_hours: float = 0.0
    exit_price: float = 0.0


def candle_points(c):
    """Intra-candle path: green O->L->H->C, red O->H->L->C."""
    if c["c"] >= c["o"]:
        return [c["o"], c["l"], c["h"], c["c"]]
    return [c["o"], c["h"], c["l"], c["c"]]


def simulate(trade_row, cfg, candles):
    side = trade_row["side"]              # LONG/SHORT
    is_long = side == "LONG"
    entry = trade_row["entry"]
    sl0 = trade_row["sl"]
    tp1 = trade_row["tp1"]
    tp2 = trade_row["tp2"]
    atr = trade_row["atr"]
    qty = trade_row["qty"]
    lev = trade_row["leverage"]
    open_time = trade_row["open_time"]

    sl_dist = abs(entry - sl0)
    if sl_dist <= 0 or qty <= 0 or atr <= 0:
        return None

    trailing_distance = atr * cfg.trail_mult
    fee_bps = TAKER_FEE_BPS / 10000.0
    fee_buffer = entry * (fee_bps * 2 + FEE_BUFFER_EXTRA)

    state = "OPEN"
    sl = sl0
    pos_qty = qty
    realized = -(entry * qty * fee_bps)   # entry fee
    peak = entry                          # best price since trailing activation
    hi, lo = entry, entry
    tp1_was_hit = False

    open_ms = int(open_time.timestamp() * 1000)
    deadline = open_time + timedelta(hours=MAX_HOLD_HOURS)

    def fav_move(px):
        return (px - entry) if is_long else (entry - px)

    def leg_pnl(px, q):
        return (px - entry) * q * lev if is_long else (entry - px) * q * lev

    def close_all(px, action, when):
        nonlocal realized, pos_qty
        realized += leg_pnl(px, pos_qty) - px * pos_qty * fee_bps
        pos_qty = 0.0
        hh = (when - open_time).total_seconds() / 3600
        return SimResult(realized, action, tp1_was_hit, hh, px)

    def update_trailing(px):
        """Mirror of _update_trailing_stop with variant progress definition."""
        nonlocal peak, sl
        if is_long:
            peak = max(peak, px)
            total_range = tp2 - entry
            peak_move = peak - entry
        else:
            peak = min(peak, px)
            total_range = entry - tp2
            peak_move = entry - peak

        if cfg.progress_from_tp1 and state == "TRAILING":
            tp1_move = abs(tp1 - entry)
            tp2_move = abs(tp2 - entry)
            rng = tp2_move - tp1_move
            progress = (peak_move - tp1_move) / rng if rng > 0 else 0.0
            progress = max(0.0, min(progress, 1.0))
        else:
            progress = min(peak_move / total_range, 1.0) if total_range > 0 else 0.0

        tighten = max(cfg.tighten_start - progress * (cfg.tighten_start - cfg.tighten_end),
                      cfg.tighten_end)
        eff = trailing_distance * tighten
        trailing_sl = (peak - eff) if is_long else (peak + eff)

        floor_sl = None
        if progress > cfg.floor_progress and peak_move > 0:
            lock_pct = min(cfg.floor_start + (progress - cfg.floor_progress) * 0.5,
                           cfg.floor_max)
            floor_sl = (entry + peak_move * lock_pct) if is_long else (entry - peak_move * lock_pct)
        elif peak_move > 0:
            fb = entry * fee_bps * 2
            floor_sl = (entry + fb) if is_long else (entry - fb)

        new_sl = trailing_sl
        if floor_sl is not None:
            new_sl = max(trailing_sl, floor_sl) if is_long else min(trailing_sl, floor_sl)
        # protective-direction only
        if is_long and new_sl > sl:
            sl = new_sl
        elif not is_long and new_sl < sl:
            sl = new_sl

    # iterate candles strictly after entry (no look-inside the entry candle)
    for c in candles:
        c_open = datetime.fromtimestamp(c["t"] / 1000, tz=timezone.utc)
        c_close_t = c_open + timedelta(hours=1)
        if c["t"] < open_ms + 1:          # skip entry candle and earlier
            if c_close_t <= open_time or c["t"] <= open_ms - 3_600_000:
                continue
            continue
        if c_open >= deadline:
            return close_all(candles_close_before(candles, deadline) or c["o"],
                             "HOLD_LIMIT", deadline)

        for px in candle_points(c):
            hi, lo = max(hi, px), min(lo, px)

            # 0a. profit lock (OPEN state)
            if state == "OPEN":
                r_now = fav_move(px) / sl_dist
                if r_now >= cfg.be_trigger:
                    be_sl = (entry + fee_buffer) if is_long else (entry - fee_buffer)
                    if (is_long and sl < be_sl) or (not is_long and sl > be_sl):
                        sl = be_sl
                if r_now >= cfg.lock_trigger:
                    lock_sl = (entry + sl_dist * cfg.lock_frac) if is_long \
                        else (entry - sl_dist * cfg.lock_frac)
                    if (is_long and sl < lock_sl) or (not is_long and sl > lock_sl):
                        sl = lock_sl
                # V1: pre-TP1 trailing ratchet
                if cfg.pre_tp1_trail:
                    peak_r = (fav_move(hi) if is_long else fav_move(lo)) / sl_dist
                    if peak_r >= cfg.pre_tp1_activation_r:
                        update_trailing(px)

            # 0b. SL check
            if (is_long and px <= sl) or (not is_long and px >= sl):
                action = "TRAILING_STOP" if state == "TRAILING" else "SL"
                return close_all(sl, action, c_close_t)

            # 2. TP1 partial
            if state == "OPEN" and ((is_long and px >= tp1) or (not is_long and px <= tp1)):
                tp1_was_hit = True
                close_qty = pos_qty * cfg.tp1_close_pct
                realized += leg_pnl(tp1, close_qty) - tp1 * close_qty * fee_bps
                pos_qty -= close_qty
                # cushion breakeven (position_manager.py:1178-1195)
                if pos_qty > 0 and lev > 0:
                    cushion = realized / (pos_qty * lev)
                    sl = (entry - cushion + fee_buffer) if is_long \
                        else (entry + cushion - fee_buffer)
                peak = tp1
                state = "TRAILING"

            # 3. trailing update
            if state == "TRAILING":
                update_trailing(px)

            # 4. TP2
            if (is_long and px >= tp2) or (not is_long and px <= tp2):
                return close_all(tp2, "TP2", c_close_t)

    # ran out of candle data — mark to last close
    last = candles[-1]["c"] if candles else entry
    when = datetime.fromtimestamp(candles[-1]["t"] / 1000, tz=timezone.utc) if candles else open_time
    return close_all(last, "END_OF_DATA", when)


def candles_close_before(candles, when):
    ms = when.timestamp() * 1000
    px = None
    for c in candles:
        if c["t"] + 3_600_000 <= ms:
            px = c["c"]
        else:
            break
    return px


# ── Metrics ──────────────────────────────────────────────────────────────

def metrics(results):
    """results: list of dicts with pnl, side, era, r_mult."""
    if not results:
        return {}
    pnls = [r["pnl"] for r in results]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    cum, peak_eq, maxdd = 0.0, 0.0, 0.0
    for p in pnls:
        cum += p
        peak_eq = max(peak_eq, cum)
        maxdd = max(maxdd, peak_eq - cum)
    return {
        "n": len(pnls),
        "total": sum(pnls),
        "wr": len(wins) / len(pnls) * 100,
        "avg_win": (sum(wins) / len(wins)) if wins else 0.0,
        "avg_loss": (sum(losses) / len(losses)) if losses else 0.0,
        "max_dd": maxdd,
        "total_r": sum(r["r_mult"] for r in results),
        "avg_r": sum(r["r_mult"] for r in results) / len(results),
    }


def fmt_row(name, m):
    if not m:
        return f"| {name} | - | - | - | - | - | - | - |"
    return (f"| {name} | {m['n']} | ${m['total']:+,.2f} | {m['wr']:.1f}% "
            f"| ${m['avg_win']:,.2f} | ${m['avg_loss']:,.2f} | ${m['max_dd']:,.2f} "
            f"| {m['total_r']:+.2f}R |")


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    trades = load_trades()
    opens = load_open_events()
    print(f"trades.csv rows: {len(trades)}, TRADE_OPENED events: {len(opens)}")

    rows, unmatched = [], []
    for t in trades:
        ev = match_open(t, opens)
        if ev is None:
            unmatched.append(t)
            continue
        try:
            row = {
                "symbol": t["symbol"],
                "side": t["side"],
                "entry": float(t["entry"]),
                "actual_exit": float(t["exit"]),
                "actual_pnl": float(t["pnl"]),
                "sl": float(ev["sl"]),
                "tp1": float(ev["tp1"]),
                "tp2": float(ev["tp2"]),
                "atr": float(ev.get("atr", 0)),
                "qty": float(ev.get("position_size", 0)),
                "leverage": float(ev.get("leverage", 1.0)) or 1.0,
                "open_time": parse_ts(ev["timestamp"]),
                "close_time": parse_ts(t["timestamp"]),
                "state_path": t.get("state_path", ""),
                "outcome": t.get("outcome", ""),
            }
        except (KeyError, TypeError, ValueError) as ex:
            unmatched.append(t)
            print(f"  bad row {t['symbol']} {t['timestamp']}: {ex}", file=sys.stderr)
            continue
        if row["atr"] <= 0 or row["qty"] <= 0 or abs(row["entry"] - row["sl"]) <= 0:
            unmatched.append(t)
            continue
        row["era"] = "pre-Jun7" if row["open_time"] < ERA_SPLIT else "Jun7+"
        row["risk_usd"] = abs(row["entry"] - row["sl"]) * row["qty"] * row["leverage"]
        rows.append(row)
    print(f"matched: {len(rows)}, unmatched/unusable: {len(unmatched)}")

    # candles
    syms = sorted({r["symbol"] for r in rows})
    t_min = min(r["open_time"] for r in rows) - timedelta(hours=2)
    t_max = max(r["close_time"] for r in rows) + timedelta(hours=MAX_HOLD_HOURS + 2)
    t_max = min(t_max, datetime.now(timezone.utc))
    start_ms = int(t_min.timestamp() // 3600 * 3600 * 1000)
    end_ms = int(t_max.timestamp() * 1000)
    candles = {}
    for s in syms:
        candles[s] = fetch_candles(s, start_ms, end_ms)
        print(f"  {s}: {len(candles[s])} candles "
              f"({datetime.fromtimestamp(candles[s][0]['t']/1000, tz=timezone.utc):%m-%d} "
              f".. {datetime.fromtimestamp(candles[s][-1]['t']/1000, tz=timezone.utc):%m-%d})")

    # simulate all variants
    all_results = {}   # variant -> list of result dicts
    per_trade = []     # per-trade detail for reproduction table
    for cfg in VARIANTS:
        vres = []
        for r in rows:
            sim = simulate(r, cfg, candles[r["symbol"]])
            if sim is None:
                continue
            risk = r["risk_usd"] or 1.0
            vres.append({
                "pnl": sim.pnl, "r_mult": sim.pnl / risk, "side": r["side"],
                "era": r["era"], "symbol": r["symbol"],
                "exit_action": sim.exit_action, "tp1": sim.tp1_hit,
                "hold_h": sim.hold_hours,
                "key": (r["symbol"], r["open_time"].isoformat()),
            })
            if cfg.name == "V0":
                per_trade.append({**r, "sim_pnl": sim.pnl,
                                  "sim_action": sim.exit_action, "sim_tp1": sim.tp1_hit})
        all_results[cfg.name] = vres

    # reproduction fidelity (V0 vs actual)
    diffs = [abs(p["sim_pnl"] - p["actual_pnl"]) for p in per_trade]
    sign_agree = sum(1 for p in per_trade
                     if (p["sim_pnl"] > 0) == (p["actual_pnl"] > 0)) / len(per_trade) * 100
    era_a = [p for p in per_trade if p["era"] == "pre-Jun7"]
    era_b = [p for p in per_trade if p["era"] == "Jun7+"]

    def repro(sub):
        if not sub:
            return {}
        return {
            "n": len(sub),
            "actual_total": sum(p["actual_pnl"] for p in sub),
            "sim_total": sum(p["sim_pnl"] for p in sub),
            "mae": sum(abs(p["sim_pnl"] - p["actual_pnl"]) for p in sub) / len(sub),
            "sign_agree": sum(1 for p in sub if (p["sim_pnl"] > 0) == (p["actual_pnl"] > 0))
                          / len(sub) * 100,
        }

    print("\n== Reproduction (V0 vs actual) ==")
    for label, sub in (("ALL", per_trade), ("pre-Jun7", era_a), ("Jun7+", era_b)):
        m = repro(sub)
        print(f"  {label}: n={m['n']} actual=${m['actual_total']:+,.2f} "
              f"sim=${m['sim_total']:+,.2f} MAE=${m['mae']:,.2f} sign-agree={m['sign_agree']:.0f}%")

    # variant tables
    print("\n== Variant totals ==")
    print("| variant | n | total PnL | WR | avg win | avg loss | max DD | sum R |")
    for cfg in VARIANTS:
        print(fmt_row(f"{cfg.name} {cfg.desc}", metrics(all_results[cfg.name])))

    for split_key, split_vals in (("era", ("pre-Jun7", "Jun7+")), ("side", ("LONG", "SHORT"))):
        for val in split_vals:
            print(f"\n== {split_key} = {val} ==")
            print("| variant | n | total PnL | WR | avg win | avg loss | max DD | sum R |")
            for cfg in VARIANTS:
                sub = [x for x in all_results[cfg.name] if x[split_key] == val]
                print(fmt_row(cfg.name, metrics(sub)))

    # dump machine-readable results next to the cache
    out = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "n_trades": len(rows),
        "unmatched": len(unmatched),
        "reproduction": {"all": repro(per_trade), "pre_jun7": repro(era_a),
                         "jun7_plus": repro(era_b)},
        "variants": {},
        "per_trade_v0": [
            {"symbol": p["symbol"], "side": p["side"],
             "open": p["open_time"].isoformat(), "era": p["era"],
             "actual_pnl": round(p["actual_pnl"], 2), "sim_pnl": round(p["sim_pnl"], 2),
             "actual_outcome": p["outcome"], "sim_action": p["sim_action"]}
            for p in per_trade
        ],
    }
    for cfg in VARIANTS:
        res = all_results[cfg.name]
        out["variants"][cfg.name] = {
            "desc": cfg.desc,
            "all": metrics(res),
            "pre_jun7": metrics([x for x in res if x["era"] == "pre-Jun7"]),
            "jun7_plus": metrics([x for x in res if x["era"] == "Jun7+"]),
            "long": metrics([x for x in res if x["side"] == "LONG"]),
            "short": metrics([x for x in res if x["side"] == "SHORT"]),
            "exit_actions": {a: sum(1 for x in res if x["exit_action"] == a)
                             for a in sorted({x["exit_action"] for x in res})},
            "tp1_rate": sum(1 for x in res if x["tp1"]) / len(res) * 100 if res else 0,
        }
    result_path = CACHE_DIR / "results.json"
    result_path.write_text(json.dumps(out, indent=1))
    print(f"\nresults written to {result_path}")


if __name__ == "__main__":
    main()
