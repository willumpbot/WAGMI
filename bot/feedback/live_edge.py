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


def defabricate_sol_veto_enabled() -> bool:
    """RIP-OUT PHASE 1 gate (default OFF -> zero live behavior change on deploy).

    When true, callers (manual/sniper_filter.py, llm/quant_brain.py,
    core/position_wiring.py) replace their fabricated SOL_BUY RSI<20 hard
    veto (a frozen, never-corroborated "0% up at 6h" backtest stat) with the
    living-values gate in `living_veto_decision()` below. When false (default),
    those callers keep firing the fabricated veto exactly as before."""
    return os.getenv("DEFABRICATE_SOL_VETO", "false").strip().lower() in ("1", "true", "yes")


def defabricate_sniper_sizing_enabled() -> bool:
    """RIP-OUT PHASE 1 gate #2+#3 (default OFF -> zero live behavior change on deploy).

    When true:
      - execution/sizing_optimizer.py replaces its fabricated per-setup
        _DEFAULT_PRIORS table (e.g. HYPE_BUY prior (0.52, 1.34) vs an audited
        live WR of ~22-23%) and the fabricated 1.15x dip_mult leverage boost
        with living per-(symbol,side) win-rate/payoff computed from the trade
        ledger (n>=13; below that, the single documented neutral prior
        _DEFAULT_PRIOR, never a fabricated per-setup value).
      - manual/sniper_filter.py replaces its fabricated positive_ev_setups
        "elite" grade table with `living_setup_grade()` below (n>=13 required
        to be graded A/B "proven +EV"; below that, "unproven" -- never a
        fabricated WR/grade).
      - manual/signal_scorer.py's dip-buy score bonus is only awarded when
        the underlying (symbol, side) is living-graded A/B, not unconditionally.
    When false (default), all three keep using the fabricated tables exactly
    as before. Both states always shadow-log the counterfactual
    ("[DEFAB-SNIPER-SIZE]" / "[DEFAB-SNIPER-LABEL]") once the flag machinery
    is invoked, so the delta is measurable before the flag is trusted."""
    return os.getenv("DEFABRICATE_SNIPER_SIZING", "false").strip().lower() in ("1", "true", "yes")


def split_setup_key(setup: str):
    """"SYMBOL_BUY"/"SYMBOL_SELL" -> (symbol, side), or (None, None) if unparseable.

    Shared helper so sizing_optimizer / sniper_filter / signal_scorer all
    parse manual-sniper "setup" keys (e.g. "HYPE_BUY") the same way when
    looking up living per-(symbol,side) evidence."""
    s = str(setup or "").upper()
    if s.endswith("_BUY"):
        return s[:-4], "BUY"
    if s.endswith("_SELL"):
        return s[:-5], "SELL"
    return None, None


def _norm_side(side: str) -> str:
    return "BUY" if str(side).upper() in ("BUY", "LONG") else "SELL"


def _pnl_to_mult(avg_pnl: float) -> float:
    """Map avg net PnL/trade -> size multiplier. Payoff-driven, bounded.
    +$10/tr -> ~1.5 boost, -$10/tr -> ~0.5 cut, break-even -> ~1.0. Clamp [0.25, 1.5]."""
    m = 1.0 + max(-0.75, min(0.5, avg_pnl / 20.0))
    return round(max(0.25, min(1.5, m)), 3)


def _win_rate_payoff(pnls) -> dict:
    """{win_rate, payoff_ratio} from a list of net PnL values. Mirrors
    feedback/kelly_engine.py's _win_rate_and_payoff (per-factor axis) but
    applied to live_edge's per-(symbol,side) axis -- reuses the same
    all-wins/all-losses degenerate-case handling (payoff capped at 3.0)."""
    if not pnls:
        return {"win_rate": 0.0, "payoff_ratio": 0.0}
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    win_rate = len(wins) / len(pnls)
    if not losses:
        return {"win_rate": win_rate, "payoff_ratio": 3.0 if wins else 0.0}
    if not wins:
        return {"win_rate": win_rate, "payoff_ratio": 0.0}
    avg_win = sum(wins) / len(wins)
    avg_loss = sum(abs(p) for p in losses) / len(losses)
    payoff_ratio = (avg_win / avg_loss) if avg_loss > 1e-9 else 3.0
    return {"win_rate": round(win_rate, 4), "payoff_ratio": round(payoff_ratio, 3)}


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
            meta[key] = {"n": len(pnls), "avg_pnl": round(avg, 2),
                         **_win_rate_payoff(pnls)}
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


def get_side_stats(symbol: str, side: str):
    """Raw {n, avg_pnl} live evidence behind get_side_mult(), or None if n<13.

    Callers that need to reason about the underlying evidence (e.g. a veto
    decision, not just a size multiplier) should use this instead of trying
    to invert get_side_mult()'s clamped/rounded output."""
    base = str(symbol).replace("/USDC:USDC", "").replace("/USDT:USDT", "").replace("/USD", "").upper()
    _ensure_fresh()
    with _lock:
        return _cache["meta"].get((base, _norm_side(side)))


def get_side_wr_payoff(symbol: str, side: str):
    """Live per-(symbol,side) {n, avg_pnl, win_rate, payoff_ratio}, or None if n<13.

    RIP-OUT PHASE 1 (#2 sizing): backs execution/sizing_optimizer.py's Kelly
    fraction, replacing the fabricated _DEFAULT_PRIORS table. Built on the
    same n>=13 ledger evidence as get_side_stats()/get_side_mult() -- just
    surfaces win_rate/payoff_ratio (needed by the Kelly formula) instead of
    the PnL-per-trade size multiplier."""
    return get_side_stats(symbol, side)


def living_setup_grade(symbol: str, side: str) -> dict:
    """Data-driven replacement for the fabricated positive_ev_setups grade
    table (manual/sniper_filter.py) and the fabricated setup_scores /
    dip-buy bonus (manual/signal_scorer.py).

    RIP-OUT PHASE 1 (#3 labels): a setup is only graded "proven +EV" (A/B)
    if the ledger has n>=13 closed (symbol,side) trades AND the average net
    PnL/trade is positive. Insufficient evidence (n<13) is always "unproven"
    (neutral) -- never a fabricated grade/WR.

    Returns:
        {"grade": "A"|"B"|"F"|"unproven", "n": int, "win_rate": float|None,
         "avg_pnl": float|None, "reason": str}
        reason is one of:
          - "insufficient_evidence"      (n<13 -> grade="unproven")
          - "live_positive_ev_strong"    (n>=13, avg_pnl>0, WR>=45% -> grade="A")
          - "live_positive_ev_marginal"  (n>=13, avg_pnl>0, WR<45%  -> grade="B")
          - "live_negative_ev"           (n>=13, avg_pnl<=0        -> grade="F")
    """
    stats = get_side_wr_payoff(symbol, side)
    if stats is None:
        return {"grade": "unproven", "n": 0, "win_rate": None, "avg_pnl": None,
                "reason": "insufficient_evidence"}
    n = stats.get("n", 0)
    wr = stats.get("win_rate", 0.0)
    avg = stats.get("avg_pnl", 0.0)
    if avg > 0 and wr >= 0.45:
        return {"grade": "A", "n": n, "win_rate": wr, "avg_pnl": avg,
                "reason": "live_positive_ev_strong"}
    if avg > 0:
        return {"grade": "B", "n": n, "win_rate": wr, "avg_pnl": avg,
                "reason": "live_positive_ev_marginal"}
    return {"grade": "F", "n": n, "win_rate": wr, "avg_pnl": avg,
            "reason": "live_negative_ev"}


def living_veto_decision(symbol: str, side: str) -> dict:
    """Data-driven replacement for a fabricated hard veto on (symbol, side).

    This is the RIP-OUT PHASE 1 rule: a hard veto is only "living" (justified
    by the bot's own experience) if the ledger has n>=13 closed trades for
    this (symbol, side) AND the average net PnL/trade is clearly negative.
    Insufficient evidence (n<13) or a neutral/positive average must NEVER
    veto — that would just be re-fabricating the block under a new name.

    Returns:
        {"veto": bool, "n": int, "avg_pnl": float|None, "reason": str}
        reason is one of:
          - "insufficient_evidence" (n<13 -> veto=False, epsilon-preserving)
          - "toxic_confirmed"       (n>=13, avg_pnl<0 -> veto=True)
          - "neutral_or_positive"   (n>=13, avg_pnl>=0 -> veto=False)
    """
    stats = get_side_stats(symbol, side)
    if stats is None:
        return {"veto": False, "n": 0, "avg_pnl": None, "reason": "insufficient_evidence"}
    n = stats.get("n", 0)
    avg = stats.get("avg_pnl", 0.0)
    if avg < 0:
        return {"veto": True, "n": n, "avg_pnl": avg, "reason": "toxic_confirmed"}
    return {"veto": False, "n": n, "avg_pnl": avg, "reason": "neutral_or_positive"}


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
