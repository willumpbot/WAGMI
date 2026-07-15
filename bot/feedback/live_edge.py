"""Living-values edge computer — LLM-FREE, read-only on the ledger.

The north star (2026-07-14): every value the bot acts on should be computed LIVE
from its own experience, never hardcoded. This replaces the stale hardcoded
SYMBOL_SIDE_RISK_MULTIPLIERS (a 2026-03-30 backtest table, deleted 2026-07-15,
that penalized ETH_SELL — the actual best edge — and under-penalized HYPE_BUY —
the actual worst) with a value computed from the COMPLETE trade_ledger.csv
(net_pnl, the de-biased truth).

Design:
  - PnL-per-trade driven (NOT win-rate — the edge is payoff: ETH_SELL is +$14.90/tr
    at only 30% WR; a WR gate would wrongly penalize it).
  - n>=13 required (the house data-learned standard) else returns None -> caller
    falls back to neutral 1.0 (no pre-decided bias).
  - Cached with mtime + TTL so it stays "living" as trades close, cheaply.
  - Optional recency window (LIVE_EDGE_WINDOW_DAYS, default 0 = all ledger).

Gate: DATA_DRIVEN_SIDE_MULT (default true). Set false to revert to neutral 1.0
(the legacy hardcoded SYMBOL_SIDE_RISK_MULTIPLIERS table has been deleted).
"""
import os
import csv
import time
import datetime
import threading

_BOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LEDGER = os.path.join(_BOT, "data", "trade_ledger.csv")

_MIN_N = 13
_TTL_S = 900          # recompute at most every 15 min
_lock = threading.Lock()
_cache = {"mult": {}, "computed_at": 0.0, "ledger_mtime": 0.0, "meta": {},
          "symbol_mult": {}, "symbol_meta": {}, "breakeven_floor": None}

# Confidence-floor break-even scan (LIVING VALUES: feedback/loop.py's
# effective_floor blend must never gate below the confidence level the
# ledger actually proves profitable). Scans confidence_score thresholds
# and returns the lowest one whose admitted trades are net non-negative
# with enough evidence (n>=_MIN_N), else None (caller keeps its fallback).
_BE_SCAN_LO = 55.0
_BE_SCAN_HI = 85.0
_BE_SCAN_STEP = 2.5

# Synthetic/test entry prices seeded by test fixtures — exclude from live stats.
# Mirrors trading_config._TEST_ENTRY_PRICES / _get_regime_ledger_ev.
_TEST_ENTRY_PRICES = (100.0, 150.0, 50000.0)


def enabled() -> bool:
    return os.getenv("DATA_DRIVEN_SIDE_MULT", "true").strip().lower() in ("1", "true", "yes")


def _norm_side(side: str) -> str:
    return "BUY" if str(side).upper() in ("BUY", "LONG") else "SELL"


def _pnl_to_mult(avg_pnl: float) -> float:
    """Map avg net PnL/trade -> size multiplier. Payoff-driven, bounded.
    +$10/tr -> ~1.5 boost, -$10/tr -> ~0.5 cut, break-even -> ~1.0. Clamp [0.25, 1.5]."""
    m = 1.0 + max(-0.75, min(0.5, avg_pnl / 20.0))
    return round(max(0.25, min(1.5, m)), 3)


def _row_ts(r) -> float:
    t = str(r.get("timestamp", "")).strip()
    try:
        return float(t) if "T" not in t else datetime.datetime.fromisoformat(
            t.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return 0.0


def _recompute():
    """Rebuild the {(symbol,side): mult} and {symbol: mult} maps from the ledger.
    Never raises. The symbol-only map aggregates BOTH sides per symbol.
    Also derives the live break-even confidence floor (see module docstring
    near _BE_SCAN_* for rationale)."""
    mult, meta = {}, {}
    symbol_mult, symbol_meta = {}, {}
    breakeven_floor = None
    try:
        if not os.path.exists(_LEDGER):
            return mult, meta, symbol_mult, symbol_meta, breakeven_floor
        try:
            window_days = float(os.getenv("LIVE_EDGE_WINDOW_DAYS", "0") or 0)
        except (ValueError, TypeError):
            window_days = 0.0
        cutoff = (time.time() - window_days * 86400.0) if window_days > 0 else 0.0
        cells = {}
        symbol_cells = {}
        conf_pnl_rows = []
        with open(_LEDGER, newline="", encoding="utf-8", errors="ignore") as f:
            for r in csv.DictReader(f):
                try:
                    pnl = float(r.get("net_pnl") or 0)
                except (ValueError, TypeError):
                    continue
                if cutoff and _row_ts(r) < cutoff:
                    continue
                sym = str(r.get("symbol", "")).upper()
                if "TEST" in sym or "SIM" in sym:
                    continue
                try:
                    ep = float(r.get("entry_price") or 0)
                except (ValueError, TypeError):
                    ep = 0.0
                if ep in _TEST_ENTRY_PRICES:
                    continue
                try:
                    conf = float(r.get("confidence_score") or 0)
                except (ValueError, TypeError):
                    conf = 0.0
                # NOTE: conf==0 rows are REAL legacy/reconstructed trades (117 of
                # 216 rows, e.g. ETH SHORT @1871 +$1010) — they MUST stay in the
                # mult/symbol_mult cells. TEST/synthetic rows are excluded above
                # by symbol and _TEST_ENTRY_PRICES, mirroring
                # trading_config._get_regime_ledger_ev.
                key = (sym, _norm_side(r.get("side", "")))
                cells.setdefault(key, []).append(pnl)
                symbol_cells.setdefault(sym, []).append(pnl)
                if conf > 0:  # breakeven scan only: skip unscored rows (conf==0); TEST/entry-sim rows are excluded above
                    conf_pnl_rows.append((conf, pnl))
        for key, pnls in cells.items():
            if len(pnls) < _MIN_N:
                continue  # not enough evidence -> caller stays neutral
            avg = sum(pnls) / len(pnls)
            mult[key] = _pnl_to_mult(avg)
            meta[key] = {"n": len(pnls), "avg_pnl": round(avg, 2)}
        for sym, pnls in symbol_cells.items():
            if len(pnls) < _MIN_N:
                continue
            avg = sum(pnls) / len(pnls)
            symbol_mult[sym] = _pnl_to_mult(avg)
            symbol_meta[sym] = {"n": len(pnls), "avg_pnl": round(avg, 2)}
        f_thresh = _BE_SCAN_LO
        while f_thresh <= _BE_SCAN_HI + 1e-9:
            slice_pnls = [p for c, p in conf_pnl_rows if c >= f_thresh]
            n = len(slice_pnls)
            if n >= _MIN_N and (sum(slice_pnls) / n) >= 0:
                breakeven_floor = f_thresh
                break
            f_thresh += _BE_SCAN_STEP
    except Exception:
        return {}, {}, {}, {}, None
    return mult, meta, symbol_mult, symbol_meta, breakeven_floor


def _ensure_fresh():
    now = time.time()
    try:
        led_mtime = os.path.getmtime(_LEDGER) if os.path.exists(_LEDGER) else 0.0
    except OSError:
        led_mtime = 0.0
    with _lock:
        stale = (now - _cache["computed_at"] > _TTL_S) or (led_mtime != _cache["ledger_mtime"])
        if stale:
            mult, meta, symbol_mult, symbol_meta, breakeven_floor = _recompute()
            _cache.update({"mult": mult, "meta": meta,
                           "symbol_mult": symbol_mult, "symbol_meta": symbol_meta,
                           "breakeven_floor": breakeven_floor,
                           "computed_at": now, "ledger_mtime": led_mtime})


def get_side_mult(symbol: str, side: str):
    """Live-computed symbol+side size multiplier from the ledger, or None if n<13.
    Returns None (not 1.0) so the caller can choose its own neutral fallback."""
    base = str(symbol).replace("/USDC:USDC", "").replace("/USDT:USDT", "").replace("/USD", "").upper()
    _ensure_fresh()
    with _lock:
        return _cache["mult"].get((base, _norm_side(side)))


def get_symbol_mult(symbol: str):
    """Live-computed per-symbol (both sides combined) size multiplier from the
    ledger, or None if n<13. Returns None (not 1.0) so the caller picks its own
    neutral fallback. Mirrors get_side_mult but aggregates across BUY+SELL."""
    base = str(symbol).replace("/USDC:USDC", "").replace("/USDT:USDT", "").replace("/USD", "").upper()
    _ensure_fresh()
    with _lock:
        return _cache["symbol_mult"].get(base)


def get_breakeven_confidence_floor():
    """Live-computed confidence floor: the lowest confidence_score threshold
    at which closed ledger trades are net non-negative (n>=13), scanned
    55..85 in steps of 2.5. Returns None if no threshold in that range has
    enough evidence -> caller must keep its own (non-lowering) fallback."""
    _ensure_fresh()
    with _lock:
        return _cache["breakeven_floor"]


def get_report() -> dict:
    """Full {symbol_side: {mult, n, avg_pnl}} for inspection/logging."""
    _ensure_fresh()
    with _lock:
        return {f"{s}_{sd}": {"mult": _cache["mult"][(s, sd)], **_cache["meta"].get((s, sd), {})}
                for (s, sd) in _cache["mult"]}


def get_symbol_report() -> dict:
    """Full {symbol: {mult, n, avg_pnl}} for inspection/logging."""
    _ensure_fresh()
    with _lock:
        return {s: {"mult": _cache["symbol_mult"][s], **_cache["symbol_meta"].get(s, {})}
                for s in _cache["symbol_mult"]}


if __name__ == "__main__":
    import json
    print(json.dumps(get_report(), indent=2))
