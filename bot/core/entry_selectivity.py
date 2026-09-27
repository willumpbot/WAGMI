"""ENTRY SELECTIVITY gates — LLM-FREE, read-only, LIVING-VALUE.

North star (2026-07-14 LIVING VALUES mandate): every value the bot acts on is
computed LIVE from its own experience, never hardcoded. This module enforces
three entry filters whose thresholds are all derived from the bot's own closed
trades (n>=13), cached with a ledger-mtime/TTL exactly like feedback/live_edge.py.

Why (adversarially-verified finding, 2026-07-27): on corrected data the bot
already LOGS these three risk-flags ("skip") but then trades anyway. Each is a
proven drain that is flagged-but-not-enforced:
  a. SOLO / low-confluence (num_agree < 2): the biggest lever.
  b. LOSS-STREAK entries (entered deep in a consecutive-loss run).
  c. NEGATIVE-EV entries (net-of-fee EV at entry < 0).
A "skip solo OR streak>=N* OR neg-EV, KEEP exploration" filter flips the epoch
from a loss to a large gain (kept trades' win-rate >> skipped trades').

Exploration is EXEMPT (owner mandate): those are tiny-sized edge-data probes
that net ~+$4.83 and must never be blocked.

GATE: env ENTRY_SELECTIVITY with three modes (default "off"):
  - "off"    : never blocks, no file reads — BYTE-EQUIVALENT to prior behavior.
  - "shadow" : computes + returns would-block reasons, but block is always False.
  - "true"   : blocks (block=True) when a non-exploration entry trips a gate.

FAIL-OPEN: any exception -> block=False (never break the entry path).

Thresholds (NEVER hardcoded):
  a. CONFLUENCE/SOLO — active only when the rolling solo bucket (num_agree<2) over
     REAL trades in data/trades.csv has n>=13 AND its win-rate is BELOW the
     fee-adjusted breakeven WR implied by the bucket's realized payoff (avg R:R).
     Because trades.csv `pnl` is already NET of fees + de-leveraged, the payoff
     (avg_win/avg_loss) and thus breakeven = 1/(1+payoff) are inherently
     fee-adjusted. num_agree per historical trade comes from the entry_reasons
     JSON (`num_agree`, else len(strategies_agree)); the ledger agreement_level
     column is POLLUTED (defaults to 1) and is NOT used.
  b. LOSS-STREAK — N* is derived from data/trade_ledger.csv close order: the
     smallest consecutive-loss count k such that the EXACT streak==k cohort is
     net-negative AND the streak>=k cohort is net-negative, with n>=13 evidence.
     (See _recompute_streak for why the exact-bucket guard is required — a naive
     "smallest k whose >=k cohort is negative" degenerates to k=1 on a globally
     losing epoch and would wrongly block the profitable low-streak entries.)
  c. NEG-EV — block when ev_per_dollar is not None and < 0. Zero is the natural
     net-of-fee breakeven; no derived threshold needed.

Dust: when learning_input_floor_enabled() is true, ledger/trades rows with
recorded fees < DUST_FEE_FLOOR are treated as NON-EVIDENCE (mirrors
feedback/live_edge.py). When false (default), dust rows count as before.
"""
import os
import csv
import json
import time
import threading

# Shared dust floor + gate with every other ledger-reading learning input.
# The canonical definitions live in feedback/live_edge.py (LEARNING_INPUT_FLOOR
# feature). That feature is not yet merged onto every base branch, so we import
# it when present and otherwise fall back to a byte-identical local shim (same
# 0.5 fee floor, same LEARNING_INPUT_FLOOR env var). When the feature is present
# we use ITS symbols, so the two never drift.
try:
    from feedback.live_edge import (  # type: ignore
        DUST_FEE_FLOOR, learning_input_floor_enabled,
    )
except ImportError:  # pragma: no cover - depends on live_edge version on branch
    DUST_FEE_FLOOR = 0.5

    def learning_input_floor_enabled() -> bool:
        return os.getenv("LEARNING_INPUT_FLOOR", "false").strip().lower() in (
            "1", "true", "yes")

_BOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LEDGER = os.path.join(_BOT, "data", "trade_ledger.csv")
_TRADES = os.path.join(_BOT, "data", "trades.csv")

_MIN_N = 13           # house data-learned evidence standard
_TTL_S = 900          # recompute at most every 15 min

_lock = threading.Lock()
_cache = {
    "computed_at": 0.0,
    "ledger_mtime": 0.0,
    "trades_mtime": 0.0,
    "solo": None,      # {"active": bool, "n": int, "wr": float, "breakeven_wr": float, ...}
    "streak": None,    # {"n_star": int|None, "n": int, "mean_ev": float, ...}
    "long": None,      # {"drain": bool, "n": int, "wr": float, "breakeven_wr": float, ...}
}


def mode() -> str:
    """Current ENTRY_SELECTIVITY mode: 'off' (default), 'shadow', or 'true'.
    Anything unrecognized -> 'off' (fail-safe: never blocks)."""
    m = os.getenv("ENTRY_SELECTIVITY", "off").strip().lower()
    return m if m in ("off", "shadow", "true") else "off"


def long_regime_veto_enabled() -> bool:
    """LONG_REGIME_VETO (default off): veto LONG entries when the side-level long
    bucket is a proven DRAIN (real-trade WR below fee-adjusted breakeven, n>=13)
    UNLESS the regime is a confirmed uptrend (see _uptrend_regimes). Owner call
    2026-07-27: 'veto longs except strong uptrends' (mirror of the short tailwind).
    Living: the drain determination is data-derived; the uptrend carve-out lets
    the bot keep gathering uptrend-long data instead of blindly blocking."""
    return os.getenv("LONG_REGIME_VETO", "false").strip().lower() in ("1", "true", "yes")


def _uptrend_regimes():
    """Regime classes where LONG entries are ALLOWED even when longs are a
    side-level drain. Data-derived-refinable via UPTREND_REGIMES env (comma list);
    default {'trending_bull'} -- the bot's clearest confirmed-uptrend signal."""
    raw = os.getenv("UPTREND_REGIMES", "trending_bull")
    return {r.strip().lower() for r in raw.split(",") if r.strip()}


def entry_selectivity_negev_mode() -> str:
    """Per-sub-gate mode for the NEG-EV leg: 'off', 'shadow' (DEFAULT), or 'true'.
    Split out from the main ENTRY_SELECTIVITY flag because predicted_ev is currently
    NOISE-GRADE on live data (2026-07-27 swarm: corr(ev,win)~-0.17; the neg-EV cohort
    is actually 59% WR vs 37% pos-EV; ensemble labels win_prob IC~0). Hard-blocking on
    an inverted metric can veto GOOD trades, so this leg SHADOWS by default (records the
    reason for observability but never blocks) while the proven solo/streak/long legs
    keep enforcing under ENTRY_SELECTIVITY=true. Flip to 'true' only after an IC monitor
    proves EV calibrated (corr>0, n>=13 per cohort)."""
    m = os.getenv("ENTRY_SELECTIVITY_NEGEV", "shadow").strip().lower()
    return m if m in ("off", "shadow", "true") else "shadow"


def blocked_go_probe_enabled() -> bool:
    """BLOCKED_GO_PROBE (default off): take a small random fraction of gate-BLOCKED
    entries as TINY exploration probes instead of dropping them entirely.

    Why (2026-09-12): the gates above are correct — solo entries really are a
    proven drain (n=32, WR 18.8% vs 57% fee-adjusted breakeven, net -$549) and
    longs outside an uptrend really are 9% WR. But "correct" and "complete" are
    different things. From 2026-07-29 to 2026-09-12 EVERY entry the LLM-FIRST
    path proposed was blocked, so the bot took zero trades for 45 days, and
    therefore learned nothing new: the gates are computed from a ledger that the
    gates themselves stopped growing. An evidence-driven bot that blocks its way
    into silence can never discover that a blocked class has turned around.

    This re-opens the measurement loop at a size where being wrong is cheap:
    probes are taken at BLOCKED_GO_PROBE_SIZE_MULT of normal size (default the
    same 0.1x as EXPLORATION_RISK_MULT), tagged entry_type=EXPLORATION so every
    learning input treats them as probes rather than as edge evidence, and are
    still subject to the circuit breaker, notional caps, OpsGuard and position
    limits. Full-size entries in a blocked class stay blocked.

    OFF by default; BLOCKED_GO_PROBE=false restores exact prior behaviour."""
    return os.getenv("BLOCKED_GO_PROBE", "false").strip().lower() in ("1", "true", "yes")


def blocked_go_probe_rate() -> float:
    """Fraction of blocked entries taken as probes. Default 0.15, hard-capped at
    0.5 so this can never become a way to quietly re-open a drain wholesale."""
    try:
        r = float(os.getenv("BLOCKED_GO_PROBE_RATE", "0.15"))
    except (TypeError, ValueError):
        return 0.15
    return min(0.5, max(0.0, r))


def blocked_go_probe_size_mult() -> float:
    """Size multiplier for a probe. Defaults to EXPLORATION_RISK_MULT (0.1x) so
    probes are the same tiny size as every other exploration entry. Capped at 1x."""
    raw = os.getenv("BLOCKED_GO_PROBE_SIZE_MULT") or os.getenv("EXPLORATION_RISK_MULT", "0.1")
    try:
        m = float(raw)
    except (TypeError, ValueError):
        return 0.1
    return min(1.0, max(0.01, m))


def loss_streak_gate_enabled() -> bool:
    """ENTRY_SELECTIVITY_STREAK (default OFF). Owner 2026-07-29: "there should be
    no loss gate." The loss-streak leg is a hardcoded block that deadlocked the bot
    (a 3-scratch-loss streak from the size-collapse blocked ALL entries, incl. strong
    shorts, for ~22h) -- exactly the pre-decided directional block the mandate rejects.
    OFF by default = removed. Reversible to 'true' only if data ever justifies it."""
    return os.getenv("ENTRY_SELECTIVITY_STREAK", "false").strip().lower() in ("1", "true", "yes")


def trend_direction_gate_mode() -> str:
    """TREND_DIRECTION_GATE (default 'shadow'). Data-driven (2026-07-30 swarms, entry-
    time-safe): SHORTS entered WITHOUT real downside momentum (sym_d24h > T_down)
    mean-revert and drain — shallow-dip shorts 20% WR/-$186 vs deep-downtrend shorts
    (d24h<=-3%) 50% WR. Keyed to the ACTUAL price move, not the polluted regime label
    (the 'trend-fighting' hypothesis was refuted — a look-ahead artifact). Modes
    off/shadow(default)/true; shadow measures the drain live before enforcing."""
    m = os.getenv("TREND_DIRECTION_GATE", "shadow").strip().lower()
    return m if m in ("off", "shadow", "true") else "shadow"


def trend_gate_t_down() -> float:
    """Downside-momentum threshold for the short leg: a SHORT with sym_d24h above this
    has 'no tailwind' and tends to mean-revert. Default -3.0% = the ledger bucket
    boundary where short avg-net flips sign (d24h<=-3%: 50% WR n=12; (-3%,-1%]: 20%
    WR n=10). Env TREND_GATE_T_DOWN override. TODO: promote to a living-value recompute
    of the sign-flip boundary once live n accrues."""
    try:
        return float(os.getenv("TREND_GATE_T_DOWN", "-3.0"))
    except (ValueError, TypeError):
        return -3.0


# ─────────────────────────── living-value computation ───────────────────────

def _row_fees(r) -> float:
    try:
        return float(r.get("fees") or 0)
    except (ValueError, TypeError):
        return 0.0


def _num_agree_from_reasons(er: dict):
    """num_agree per historical trade from the entry_reasons JSON. Prefers the
    explicit `num_agree`, else len(strategies_agree). Returns int or None."""
    n = er.get("num_agree")
    if n is None:
        sa = er.get("strategies_agree")
        if isinstance(sa, list):
            n = len(sa)
    try:
        return int(n) if n is not None else None
    except (ValueError, TypeError):
        return None


def _is_exploration_row(row: dict, er: dict) -> bool:
    """A historical trade is exploration iff entry_type == EXPLORATION (matches
    the live _exploration_entry flag, which also tags entry_type EXPLORATION)."""
    et = (str(row.get("entry_type") or "") or str(er.get("entry_type") or "")).upper()
    return et == "EXPLORATION"


def _win_payoff(pnls):
    """{wr, payoff} from a list of NET pnl values. payoff = avg_win/avg_loss
    (capped at 3.0 for degenerate all-win / no-loss buckets). Mirrors
    feedback/live_edge._win_rate_payoff so the two agree on breakeven math."""
    if not pnls:
        return 0.0, 0.0
    wins = [p for p in pnls if p > 0]
    losses = [abs(p) for p in pnls if p <= 0]
    wr = len(wins) / len(pnls)
    if not losses:
        return wr, (3.0 if wins else 0.0)
    if not wins:
        return wr, 0.0
    avg_win = sum(wins) / len(wins)
    avg_loss = sum(losses) / len(losses)
    payoff = (avg_win / avg_loss) if avg_loss > 1e-9 else 3.0
    return wr, payoff


def _recompute_solo():
    """CONFLUENCE/SOLO gate state from data/trades.csv.

    Buckets NET pnl of every non-exploration trade whose num_agree < 2 (dust
    excluded only when learning_input_floor_enabled()). The gate is ACTIVE when
    that bucket has n>=13 AND its win-rate is below the fee-adjusted breakeven
    win-rate 1/(1+payoff) implied by its own realized payoff. Never raises."""
    try:
        if not os.path.exists(_TRADES):
            return None
        dust_on = learning_input_floor_enabled()
        solo_pnls = []
        with open(_TRADES, newline="", encoding="utf-8", errors="ignore") as f:
            for r in csv.DictReader(f):
                try:
                    er = json.loads(r.get("entry_reasons") or "{}")
                except (ValueError, TypeError):
                    er = {}
                if not isinstance(er, dict):
                    er = {}
                if _is_exploration_row(r, er):
                    continue  # exploration is exempt — never evidence for this gate
                if dust_on and _row_fees(r) < DUST_FEE_FLOOR:
                    continue
                na = _num_agree_from_reasons(er)
                if na is None or na >= 2:
                    continue
                try:
                    solo_pnls.append(float(r.get("pnl") or 0))
                except (ValueError, TypeError):
                    continue
        n = len(solo_pnls)
        if n < _MIN_N:
            return {"active": False, "n": n, "wr": None, "breakeven_wr": None,
                    "net": round(sum(solo_pnls), 2), "reason": "insufficient_evidence"}
        wr, payoff = _win_payoff(solo_pnls)
        breakeven_wr = 1.0 / (1.0 + payoff) if payoff > 0 else 1.0
        active = wr < breakeven_wr
        return {"active": bool(active), "n": n, "wr": round(wr, 4),
                "payoff": round(payoff, 3), "breakeven_wr": round(breakeven_wr, 4),
                "net": round(sum(solo_pnls), 2),
                "reason": "solo_below_breakeven" if active else "solo_at_or_above_breakeven"}
    except Exception:
        return None


def _recompute_streak():
    """LOSS-STREAK N* from data/trade_ledger.csv close order.

    Builds the consecutive-loss streak ACTIVE AT ENTRY for each closed trade
    (count of losing closes immediately preceding it; reset on any net win).
    N* = the smallest k such that:
        - the EXACT streak==k cohort is net-negative (the marginal entry at that
          streak level is itself a loser), AND
        - the streak>=k cohort is net-negative with n>=13 evidence.

    The exact-bucket guard is essential: on a globally-losing epoch the naive
    "smallest k whose >=k cohort is negative" collapses to k=1 (blocking after a
    single loss and destroying the profitable streak==1/streak==2 entries). The
    guard walks up from k=1 and only fixes the threshold once the marginal
    streak level is itself unprofitable — self-adjusting as the ledger evolves.
    Returns {"n_star": int|None, ...}. Never raises."""
    try:
        if not os.path.exists(_LEDGER):
            return None
        dust_on = learning_input_floor_enabled()
        seq = []  # (streak_at_entry, net_pnl) in close order
        streak = 0
        with open(_LEDGER, newline="", encoding="utf-8", errors="ignore") as f:
            for r in csv.DictReader(f):
                try:
                    net = float(r.get("net_pnl") or 0)
                except (ValueError, TypeError):
                    continue
                if dust_on and _row_fees(r) < DUST_FEE_FLOOR:
                    # Dust is non-evidence, but it still advances the win/loss
                    # streak state so the streak-at-entry stays continuous.
                    seq.append((streak, None))
                else:
                    seq.append((streak, net))
                if net > 0:
                    streak = 0
                else:
                    streak += 1
        # Evidence-bearing (streak, net) pairs only.
        pairs = [(s, n) for s, n in seq if n is not None]
        if not pairs:
            return {"n_star": None, "reason": "no_evidence"}
        max_streak = max(s for s, _ in pairs)
        n_star = None
        meta = {}
        for k in range(1, max_streak + 1):
            exact = [n for s, n in pairs if s == k]
            cohort = [n for s, n in pairs if s >= k]
            if not exact or len(cohort) < _MIN_N:
                continue
            if (sum(exact) / len(exact)) < 0 and (sum(cohort) / len(cohort)) < 0:
                n_star = k
                meta = {"cohort_n": len(cohort),
                        "cohort_mean_ev": round(sum(cohort) / len(cohort), 3),
                        "cohort_net": round(sum(cohort), 2),
                        "exact_n": len(exact),
                        "exact_mean_ev": round(sum(exact) / len(exact), 3)}
                break
        return {"n_star": n_star, "reason": ("streak_threshold_found" if n_star
                                             else "no_negative_streak_cohort"), **meta}
    except Exception:
        return None


def _recompute_long():
    """LONG-side drain state from data/trade_ledger.csv (real trades; dust
    excluded when learning_input_floor_enabled()). 'drain' is True when the LONG
    bucket has n>=13 AND its win-rate is below the fee-adjusted breakeven implied
    by its own realized payoff -- same math as the solo gate. When drain, LONG
    entries are vetoed OUTSIDE _uptrend_regimes(). Never raises."""
    try:
        if not os.path.exists(_LEDGER):
            return None
        dust_on = learning_input_floor_enabled()
        pnls = []
        with open(_LEDGER, newline="", encoding="utf-8", errors="ignore") as f:
            for r in csv.DictReader(f):
                if str(r.get("side") or "").strip().upper() not in ("LONG", "BUY"):
                    continue
                sym = str(r.get("symbol") or "").upper()
                if "TEST" in sym or "SIM" in sym:
                    continue
                if dust_on and _row_fees(r) < DUST_FEE_FLOOR:
                    continue
                try:
                    pnls.append(float(r.get("net_pnl") or 0))
                except (ValueError, TypeError):
                    continue
        n = len(pnls)
        if n < _MIN_N:
            return {"drain": False, "n": n, "wr": None, "reason": "insufficient_evidence"}
        wr, payoff = _win_payoff(pnls)
        breakeven_wr = 1.0 / (1.0 + payoff) if payoff > 0 else 1.0
        drain = wr < breakeven_wr
        return {"drain": bool(drain), "n": n, "wr": round(wr, 4),
                "breakeven_wr": round(breakeven_wr, 4), "net": round(sum(pnls), 2),
                "reason": "long_below_breakeven" if drain else "long_at_or_above_breakeven"}
    except Exception:
        return None


def _ensure_fresh():
    """Recompute cached gate state when either source file changes or TTL lapses.
    Mirrors feedback/live_edge._ensure_fresh (mtime + TTL). Never raises."""
    now = time.time()
    try:
        led_m = os.path.getmtime(_LEDGER) if os.path.exists(_LEDGER) else 0.0
    except OSError:
        led_m = 0.0
    try:
        tr_m = os.path.getmtime(_TRADES) if os.path.exists(_TRADES) else 0.0
    except OSError:
        tr_m = 0.0
    with _lock:
        stale = (now - _cache["computed_at"] > _TTL_S
                 or led_m != _cache["ledger_mtime"]
                 or tr_m != _cache["trades_mtime"])
        if stale:
            _cache["solo"] = _recompute_solo()
            _cache["streak"] = _recompute_streak()
            _cache["long"] = _recompute_long()
            _cache["computed_at"] = now
            _cache["ledger_mtime"] = led_m
            _cache["trades_mtime"] = tr_m


def get_solo_gate() -> dict:
    """Live CONFLUENCE/SOLO gate state (or {} if unavailable)."""
    _ensure_fresh()
    with _lock:
        return dict(_cache["solo"] or {})


def get_streak_threshold():
    """Live LOSS-STREAK N* (int) or None if no negative streak cohort has n>=13."""
    _ensure_fresh()
    with _lock:
        s = _cache["streak"] or {}
        return s.get("n_star")


def get_report() -> dict:
    """Full living-value state for inspection/logging."""
    _ensure_fresh()
    with _lock:
        return {"mode": mode(), "solo": dict(_cache["solo"] or {}),
                "streak": dict(_cache["streak"] or {})}


# ───────────────────────────── the entry gate ───────────────────────────────

def evaluate_entry(*, num_agree, ev_per_dollar, loss_streak, is_exploration,
                   symbol=None, side=None, regime=None, sym_d24h=None):
    """Decide whether to BLOCK a would-be entry.

    Args (all keyword-only):
        num_agree: strategy-agreement count for this signal (int or None).
        ev_per_dollar: net-of-fee expected value per $ at entry (float or None).
        loss_streak: current consecutive-loss count active at entry (int or None).
        is_exploration: True if this is an exploration probe (ALWAYS exempt).
        symbol/side/regime: optional, for logging context only.

    Returns:
        (block: bool, reasons: list[str], mode: str)

    Contract:
        - mode "off"  -> always (False, [], "off"), no file reads (byte-equiv).
        - exploration -> always block=False, reasons=["exploration-exempt"].
        - FAIL-OPEN   -> any exception returns block=False (never breaks entry).
        - "shadow"    -> reasons computed, block always False (would-block only).
        - "true"      -> block=True when a non-exploration entry trips any gate.
    """
    m = "off"
    try:
        m = mode()
        if m == "off":
            return False, [], "off"

        if is_exploration:
            # Owner mandate: exploration probes are tiny-sized edge-data and are
            # NEVER blocked, regardless of gates.
            return False, ["exploration-exempt"], m

        _ensure_fresh()
        with _lock:
            solo = _cache["solo"] or {}
            streak = _cache["streak"] or {}
            long_st = _cache["long"] or {}

        reasons = []

        # a. CONFLUENCE / SOLO
        try:
            na = int(num_agree) if num_agree is not None else None
        except (ValueError, TypeError):
            na = None
        if na is not None and na < 2 and solo.get("active"):
            reasons.append(
                "solo_below_breakeven(num_agree=%s wr=%.1f%%<be=%.1f%% n=%s)" % (
                    na, 100.0 * (solo.get("wr") or 0.0),
                    100.0 * (solo.get("breakeven_wr") or 0.0), solo.get("n")))

        # b. LOSS-STREAK (owner 2026-07-29: "there should be no loss gate" -> default OFF).
        # REMOVED by default: on the size-collapsed book a 3-scratch-loss streak (fee
        # noise, not real drawdown) deadlocked ALL entries incl. strong num_agree=3
        # shorts for ~22h. No hardcoded loss block -- trust the LLM + data-learned
        # vetoes. Reversible via ENTRY_SELECTIVITY_STREAK=true if ever data-justified.
        if loss_streak_gate_enabled():
            n_star = streak.get("n_star")
            try:
                ls = int(loss_streak) if loss_streak is not None else None
            except (ValueError, TypeError):
                ls = None
            if n_star is not None and ls is not None and ls >= n_star:
                reasons.append("loss_streak>=N*(streak=%s N*=%s ev=%s)" % (
                    ls, n_star, streak.get("cohort_mean_ev")))

        # c. NEG-EV (per-sub-gate mode ENTRY_SELECTIVITY_NEGEV, default "shadow").
        # predicted_ev is currently noise-grade/inverted on live data, so this leg
        # SHADOWS by default (records the reason for observability but does NOT block)
        # while the proven solo/streak/long legs stay enforcing. Flip to "true" only
        # after an IC monitor proves EV calibrated.
        negev_mode = entry_selectivity_negev_mode()
        if negev_mode != "off" and ev_per_dollar is not None:
            try:
                ev = float(ev_per_dollar)
                if ev < 0:
                    if negev_mode == "true":
                        reasons.append("neg_ev(ev_per_dollar=%.4f)" % ev)
                    else:  # shadow: observability-only, excluded from would_block
                        reasons.append("neg_ev_shadow(ev_per_dollar=%.4f)" % ev)
            except (ValueError, TypeError):
                pass

        # d. LONG-REGIME (owner 2026-07-27: "veto longs except strong uptrends").
        # Longs are a side-level drain (real WR < breakeven, n>=13); veto them
        # UNLESS the regime is a confirmed uptrend. Data-derived + reversible.
        if long_regime_veto_enabled():
            _is_long = str(side or "").strip().upper() in ("LONG", "BUY")
            if _is_long and long_st.get("drain"):
                if str(regime or "").strip().lower() not in _uptrend_regimes():
                    reasons.append(
                        "long_drain_non_uptrend(regime=%s wr=%.1f%% n=%s allowed=%s)" % (
                            regime, 100.0 * (long_st.get("wr") or 0.0),
                            long_st.get("n"), sorted(_uptrend_regimes())))

        # e. TREND-DIRECTION (data-driven, 2026-07-30 swarms): SHORTS entered WITHOUT
        # real downside momentum (sym_d24h > T_down) mean-revert and drain — shallow-dip
        # shorts 20% WR/-$186 vs deep-downtrend shorts (d24h<=-3%) 50% WR. Keyed to the
        # ACTUAL price move, not the polluted regime label. Own flag TREND_DIRECTION_GATE
        # (default shadow); flip to true once live n>=13 confirms the drain.
        if trend_direction_gate_mode() != "off" and sym_d24h is not None:
            _is_short = str(side or "").strip().upper() in ("SHORT", "SELL")
            if _is_short:
                try:
                    _d = float(sym_d24h)
                    _t_down = trend_gate_t_down()
                    if _d > _t_down:
                        _sfx = "" if trend_direction_gate_mode() == "true" else "_shadow"
                        reasons.append("short_no_tailwind%s(sym_d24h=%+.1f%%>T=%.1f%%)" % (
                            _sfx, _d, _t_down))
                except (ValueError, TypeError):
                    pass

        # *_shadow reasons are observability-only and never contribute to a block.
        would_block = any("_shadow(" not in r for r in reasons)
        if m == "shadow":
            return False, reasons, "shadow"
        # m == "true"
        return would_block, reasons, "true"
    except Exception:
        # FAIL-OPEN: never break the entry path on a gate error.
        return False, [], m


if __name__ == "__main__":
    print(json.dumps(get_report(), indent=2))
