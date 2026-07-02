"""Feedback loop state collector for LLM agents.
Reads all feedback loops and formats them for agent context,
so agents understand the system's current behavioral tendencies."""
import json, logging, os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bot.llm.agents.feedback_state")
_PATHS = {
    "strat": os.path.join("ml_data", "strategy_weights.json"),
    "tuner": os.path.join("data", "feedback", "tuner_state.json"),
    "adapt": os.path.join("data", "feedback", "adaptive_risk_state.json"),
    "conf":  os.path.join("data", "feedback", "confidence_state.json"),
    "ic":    os.path.join("data", "ic_history.json"),
    "kelly": os.path.join("data", "kelly_weights.json"),
    "ev":    os.path.join("data", "ev_calibrator_state.json"),
}

def _load(key: str) -> Optional[Dict]:
    try:
        p = _PATHS[key]
        if os.path.exists(p):
            with open(p) as f: return json.load(f)
    except Exception as e: logger.debug(f"Failed to load {key}: {e}")
    return None


# SHIP S5 (2026-07-02): stale-stats gate (THE_STANDARD v1.3 §3b).
# kelly_weights.json froze 2026-06-06 but kept entering agent prompts as
# current. If mtime is older than STALE_STATS_MAX_AGE_DAYS (default 7),
# exclude from the collected state (inject nothing) and WARN once.
_STALE_WARNED: set = set()


def _stale(key: str) -> bool:
    import time
    try:
        max_age = float(os.environ.get("STALE_STATS_MAX_AGE_DAYS", "7"))
    except (ValueError, TypeError):
        max_age = 7.0
    try:
        age_days = (time.time() - os.path.getmtime(_PATHS[key])) / 86400.0
    except OSError:
        return False
    if age_days > max_age:
        if key not in _STALE_WARNED:
            _STALE_WARNED.add(key)
            logger.warning(
                f"STALE-STATS: {_PATHS[key]} is {age_days:.1f} days old "
                f"(max {max_age:g}) -- EXCLUDED from prompt injection (SHIP S5)")
        return True
    return False

def _wr(outcomes: List, window: int = 10) -> Optional[float]:
    if not outcomes: return None
    r = outcomes[-window:]
    return sum(1 for x in r if x) / len(r)

def _status(weight: float, wr: Optional[float], trials: float) -> str:
    if trials < 1: return "NEW"
    if wr is not None and wr < 0.10 and trials >= 10: return "MUTED"
    if wr is not None and wr < 0.25 and trials >= 10: return "DEMOTING"
    if wr is not None and wr >= 0.60: return "HOT"
    if wr is not None and wr < 0.35: return "COLD"
    return "OK"

def collect_all_feedback_states() -> Dict[str, Any]:
    """Read every feedback loop's current state from disk/memory."""
    r: Dict[str, Any] = {}
    sw = _load("strat") or {}
    strats = {}
    for name, e in sw.items():
        t = e.get("trials", 0)
        w = _wr(e.get("recent_outcomes", []), 10)
        wt = (e.get("wins", 0) + 1) / (t + 2) if t >= 1 else 0.30
        strats[name] = {"weight": round(wt, 2), "recent_wr": round(w, 2) if w is not None else None,
                        "status": _status(wt, w, t), "trials": round(t, 1)}
    r["strategy_weights"] = strats

    # 2. Kelly fractions (SHIP S5: excluded entirely when the file is stale)
    kd = {} if _stale("kelly") else (_load("kelly") or {})
    kf = {}
    for factor, frac in kd.get("weights", {}).items():
        nt = len(kd.get("trades", {}).get(factor, []))
        kf[factor] = {"fraction": round(frac, 3), "at_floor": frac <= 0.151, "n_trades": nt}
    r["kelly_fractions"] = kf

    # 3. Adaptive risk
    ad = _load("adapt")
    ar = {"multiplier": 1.0, "streak": "", "last_5": "", "recent_wr": None, "mode": "NORMAL"}
    if ad:
        oc = ad.get("recent_outcomes", [])
        l5 = oc[-5:] if oc else []
        w5 = sum(1 for x in l5 if x)
        mult = 1.0
        if len(oc) >= 5:
            mult = {0: 0.60, 1: 0.75}.get(w5, 1.15 if w5 >= 4 else 1.05 if w5 >= 3 else 1.0)
        ar = {"multiplier": round(mult, 2), "streak": "".join("W" if x else "L" for x in l5),
              "last_5": f"{w5}W/{len(l5)-w5}L", "recent_wr": round(_wr(oc, 20), 2) if oc else None,
              "mode": "AGGRESSIVE" if mult >= 1.1 else "CONSERVATIVE" if mult <= 0.8 else "NORMAL"}
    r["adaptive_risk"] = ar

    # 4. Tuner
    td = _load("tuner")
    tu = {"trust": 1.0, "calibration_offset": 0, "frozen": False, "confidence_floor": 50}
    if td:
        trust = td.get("trust_score", 1.0)
        co = td.get("calibration_offset", 0)
        tu = {"trust": round(trust, 2), "calibration_offset": round(co, 1),
              "frozen": trust < 0.25, "confidence_floor": td.get("confidence_floor", 50),
              "total_adjustments": td.get("total_adjustments", 0)}
    r["tuner"] = tu

    # 5. IC tracker
    ic = _load("ic") or {}
    ics = {}
    for factor, samples in ic.items():
        n = len(samples) if isinstance(samples, list) else 0
        if n < 10:
            st = f"INSUFFICIENT({n})"
        elif isinstance(samples, list) and len(set(s[0] for s in samples if isinstance(s, (list, tuple)))) <= 1:
            st = "CONSTANT_PREDS"
        else:
            st = f"TRACKING({n})"
        ics[factor] = {"n_samples": n, "status": st}
    r["ic_tracker"] = ics

    # 6. Confidence calibration
    cd = _load("conf")
    cc = {"floor": 65.0, "bins_summary": {}, "overconfidence_detected": False}
    if cd:
        bins, overconf = {}, False
        for b in cd.get("bins", []):
            lo, hi, w, l = b.get("low", 0), b.get("high", 0), b.get("wins", 0), b.get("losses", 0)
            tot = w + l
            if tot > 0:
                wr_val = w / tot
                bins[f"{lo}-{hi}"] = {"wr": round(wr_val, 2), "n": tot}
                if lo >= 80 and wr_val < 0.45 and tot >= 20: overconf = True
        cc = {"floor": cd.get("current_floor", 65.0), "bins_summary": bins,
              "overconfidence_detected": overconf}
    r["confidence_calibration"] = cc

    # 7. EV calibrator
    ed = _load("ev")
    ev = {"mode": "strict", "threshold": 0.0, "override_count": 0, "override_wr": None}
    if ed:
        to, tw = ed.get("total_overrides", 0), ed.get("total_override_wins", 0)
        ev = {"mode": ed.get("mode", "strict"), "threshold": ed.get("ev_threshold", 0.0),
              "override_count": to, "override_wr": round(tw / to, 2) if to > 0 else None}
    r["ev_calibrator"] = ev
    return r

def _detect_deadlock(s: Dict[str, Any]) -> Optional[str]:
    """Detect conservative deadlock: all loops pulling toward trade less/smaller."""
    warns = []
    ar = s.get("adaptive_risk", {})
    if ar.get("multiplier", 1.0) <= 0.75:
        warns.append(f"Adaptive risk at {ar['multiplier']}x (loss streak)")
    tu = s.get("tuner", {})
    if tu.get("frozen"): warns.append(f"Tuner FROZEN (trust={tu['trust']})")
    if tu.get("calibration_offset", 0) < -10:
        warns.append(f"Cal offset {tu['calibration_offset']:+.0f} (subtracts from all confidence)")
    kf = s.get("kelly_fractions", {})
    if kf and all(v.get("at_floor") for v in kf.values()):
        warns.append("ALL Kelly fractions at floor (0.15)")
    return ("CONSERVATIVE DEADLOCK: " + "; ".join(warns)) if len(warns) >= 2 else None

def format_feedback_for_agent(states: Optional[Dict] = None) -> str:
    """Format all feedback states as compact text for agent context (~200 tokens)."""
    if states is None:
        states = collect_all_feedback_states()
    lines = ["FEEDBACK STATE:"]

    # Strategy weights
    sw = states.get("strategy_weights", {})
    if sw:
        parts = []
        for n, i in sorted(sw.items(), key=lambda x: -x[1].get("weight", 0)):
            wr_s = f"{i['recent_wr']:.0%}" if i.get("recent_wr") is not None else "?"
            parts.append(f"{n[:12]}={i['weight']:.2f}({wr_s},{i['status']})")
        lines.append("Weights: " + " ".join(parts))

    # Kelly
    kf = states.get("kelly_fractions", {})
    if kf:
        parts = []
        for n, i in sorted(kf.items()):
            fl = ",FLOOR" if i["at_floor"] else ""
            parts.append(f"{n[:12]}={i['fraction']:.2f}({i['n_trades']}t{fl})")
        lines.append("Kelly: " + " ".join(parts))

    # Adaptive risk
    ar = states.get("adaptive_risk", {})
    if ar:
        lines.append(f"Adaptive: mult={ar.get('multiplier',1.0):.2f}x "
                      f"streak={ar.get('streak','?')}({ar.get('last_5','?')}) -> {ar.get('mode','NORMAL')}")

    # Tuner
    t = states.get("tuner", {})
    if t:
        fr = " FROZEN" if t.get("frozen") else ""
        lines.append(f"Tuner:{fr} trust={t.get('trust',1.0):.2f} "
                      f"cal_offset={t.get('calibration_offset',0):+.0f} floor={t.get('confidence_floor',50)}")

    # IC
    ic = states.get("ic_tracker", {})
    if ic:
        lines.append("IC: " + " ".join(f"{k[:12]}={v['status']}" for k, v in sorted(ic.items())))

    # Confidence
    cc = states.get("confidence_calibration", {})
    if cc:
        oc = " OVERCONFIDENT!" if cc.get("overconfidence_detected") else ""
        lines.append(f"Conf floor: {cc.get('floor', 65):.0f}%{oc}")

    # EV
    ev = states.get("ev_calibrator", {})
    if ev:
        wr_s = f" WR={ev['override_wr']:.0%}" if ev.get("override_wr") is not None else ""
        lines.append(f"EV: mode={ev.get('mode','strict')} thresh={ev.get('threshold',0):.3f} "
                      f"overrides={ev.get('override_count',0)}{wr_s}")

    # Deadlock warning
    warning = _detect_deadlock(states)
    if warning:
        lines.append("")
        lines.append(f"WARNING: {warning}")
        ar_m = ar.get("multiplier", 1.0)
        avg_k = (sum(v["fraction"] for v in kf.values()) / len(kf)) if kf else 0.15
        lines.append(f"Combined sizing: ~{ar_m * avg_k:.1%} of full Kelly. "
                      "Agents should compensate by recommending larger base sizes.")

    return "\n".join(lines)
