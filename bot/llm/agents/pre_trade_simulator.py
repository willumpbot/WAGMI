"""
Pre-trade simulation: Imagines scenarios before committing capital.
Uses historical data patterns to estimate probability of different outcomes.
Pure computation — no LLM calls.
"""
import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger("bot.llm.agents.pre_trade_simulator")

# Empirical correlation matrix (from portfolio_intelligence.py)
_CORR = {
    ("BTC", "ETH"): 0.92, ("BTC", "SOL"): 0.85, ("BTC", "HYPE"): 0.63,
    ("BTC", "DOGE"): 0.72, ("BTC", "AVAX"): 0.78, ("BTC", "LINK"): 0.76,
    ("ETH", "SOL"): 0.80, ("ETH", "HYPE"): 0.60, ("ETH", "AVAX"): 0.82,
    ("SOL", "HYPE"): 0.58, ("SOL", "AVAX"): 0.70, ("SOL", "DOGE"): 0.65,
}
_DEFAULT_ATR_PCT = {"BTC": 0.003, "ETH": 0.004, "SOL": 0.005, "HYPE": 0.007}
_WEEKEND_RATIO = 0.55
_SQUEEZE_BASE = 0.08


def _corr(a: str, b: str) -> float:
    a, b = a.upper(), b.upper()
    if a == b: return 1.0
    return _CORR.get((a, b), _CORR.get((b, a), 0.40))


def _sym(raw: str) -> str:
    return raw.split("/")[0].split(":")[0].split("-")[0].upper()


def _positions(portfolio: Dict) -> List[Dict[str, Any]]:
    result = []
    if not portfolio: return result
    items = portfolio.values() if isinstance(portfolio, dict) else portfolio
    for pos in items:
        if hasattr(pos, "symbol"):
            s, sd = _sym(pos.symbol), getattr(pos, "side", "LONG").upper()
            n = abs(float(getattr(pos, "entry", 0)) * float(getattr(pos, "qty", 0)))
            result.append({"symbol": s, "side": sd, "notional": n})
        elif isinstance(pos, dict):
            s = _sym(pos.get("symbol", pos.get("s", "")))
            sd = pos.get("side", "LONG").upper()
            e, q = float(pos.get("entry", pos.get("e", 0))), float(pos.get("qty", pos.get("q", 0)))
            n = float(pos.get("notional", abs(e * q)))
            if s and n > 0: result.append({"symbol": s, "side": sd, "notional": n})
    return result


class PreTradeSimulator:
    """Scenario-based pre-trade imagination engine."""

    def simulate(self, symbol: str, side: str, entry: float, sl: float,
                 tp1: float, leverage: float, current_portfolio: Dict,
                 market_data: Dict) -> Dict[str, Any]:
        """Run pre-trade scenario analysis. Returns scenarios, EV, portfolio impact, recommendation."""
        sym = _sym(symbol)
        is_long = side.upper() in ("BUY", "LONG")
        equity = market_data.get("equity", 1000.0)
        stop_pct = abs(entry - sl) / entry
        tp_pct = abs(tp1 - entry) / entry
        reward = equity * tp_pct * leverage
        # Resolve ATR
        atr_pct = market_data.get("atr_pct", 0.0)
        if atr_pct <= 0:
            atr_pct = (market_data.get("atr", 0.0) / entry) if entry > 0 else 0.0
        if atr_pct <= 0:
            atr_pct = _DEFAULT_ATR_PCT.get(sym, 0.005)
        weekend = market_data.get("is_weekend", False)
        wr = market_data.get("recent_win_rate", 0.50)

        scenarios = [
            self._base(wr, atr_pct, tp_pct, weekend, reward),
            self._btc_adverse(sym, entry, sl, leverage, equity, atr_pct),
            self._liq_magnet(entry, sl, tp1, leverage, equity, atr_pct),
            self._squeeze(is_long, entry, sl, leverage, equity, atr_pct, current_portfolio),
        ]
        # Chop: residual probability
        chop_p = max(0.03, 1.0 - sum(s["probability"] for s in scenarios))
        fee = equity * leverage * 0.0004 * 2
        scenarios.append({"name": "chop", "description": "Sideways chop, time stop, fee loss",
                          "probability": round(chop_p, 2), "estimated_pnl": round(-fee, 2),
                          "time_to_resolution": "6-8h"})
        # Normalize to 1.0
        total = sum(s["probability"] for s in scenarios)
        if total > 0 and abs(total - 1.0) > 0.01:
            for s in scenarios: s["probability"] = round(s["probability"] / total, 2)
            scenarios[0]["probability"] = round(scenarios[0]["probability"] + 1.0 - sum(s["probability"] for s in scenarios), 2)

        ev = sum(s["probability"] * s["estimated_pnl"] for s in scenarios)
        ml = min(s["estimated_pnl"] for s in scenarios)
        impact = self._portfolio_impact(sym, is_long, leverage, equity, current_portfolio)
        rec, reason = self._decide(ev, ml, equity, impact)
        return {"scenarios": scenarios, "expected_value": round(ev, 2), "max_loss": round(ml, 2),
                "portfolio_impact": impact, "recommendation": rec, "reasoning": reason}

    # ── Scenario builders ──────────────────────────────────────────

    def _base(self, wr, atr_pct, tp_pct, weekend, reward):
        hours = tp_pct / (atr_pct * 0.5) if atr_pct > 0 else 8.0
        prob = wr * (1.10 if hours < 2 else 0.85 if hours > 8 else 1.0)
        if weekend: prob *= 0.90
        prob = max(0.10, min(0.65, prob))
        if weekend: hours /= _WEEKEND_RATIO
        return {"name": "base_case", "description": "Normal market, thesis plays out to TP1",
                "probability": round(prob, 2), "estimated_pnl": round(reward, 2),
                "time_to_resolution": self._fmth(max(0.25, min(24.0, hours)))}

    def _btc_adverse(self, sym, entry, sl, lev, equity, atr_pct):
        c = _corr("BTC", sym) if sym != "BTC" else 1.0
        drag = 0.01 * c  # BTC 1% move * correlation
        stop = abs(entry - sl) / entry
        if drag >= stop:
            pnl = -equity * stop * lev
            desc = f"BTC 1% against, {sym} follows {drag:.1%} (corr {c:.2f}). Stop hit."
        else:
            pnl = -equity * drag * lev * 0.7
            desc = f"BTC 1% against, {sym} dips {drag:.1%} (corr {c:.2f}). Partial DD."
        return {"name": "btc_adverse", "description": desc,
                "probability": round(min(0.15 + c * 0.12, 0.30), 2),
                "estimated_pnl": round(pnl, 2), "time_to_resolution": "15-45min"}

    def _liq_magnet(self, entry, sl, tp1, lev, equity, atr_pct):
        stop = abs(entry - sl) / entry
        tp = abs(tp1 - entry) / entry
        tight = stop < atr_pct * 1.5
        prob = 0.12 if tight else 0.06
        desc = f"Tight stop ({stop:.1%}) hunted, reversal to TP" if tight else "Stop hunt past SL then reversal"
        return {"name": "liq_magnet", "description": desc, "probability": round(prob, 2),
                "estimated_pnl": round(equity * tp * lev * 0.8, 2), "time_to_resolution": "1-3h"}

    def _squeeze(self, is_long, entry, sl, lev, equity, atr_pct, portfolio):
        stop = abs(entry - sl) / entry
        pnl = -equity * min(atr_pct * 3.0, stop) * lev
        # Directional bias increases squeeze probability
        pos = _positions(portfolio)
        bias = 0.0
        if pos:
            same = sum(1 for p in pos if (is_long and p["side"] in ("BUY", "LONG")) or
                       (not is_long and p["side"] in ("SELL", "SHORT")))
            bias = same / len(pos)
        prob = min(_SQUEEZE_BASE * (1.0 + bias * 0.5), 0.18)
        kind = "short squeeze" if not is_long else "long squeeze"
        return {"name": "squeeze", "description": f"Violent {kind}, 3x ATR move against",
                "probability": round(prob, 2), "estimated_pnl": round(pnl, 2),
                "time_to_resolution": "5-20min"}

    # ── Portfolio impact ───────────────────────────────────────────

    def _portfolio_impact(self, sym, is_long, leverage, equity, portfolio):
        pos = _positions(portfolio)
        long_pct = short_pct = 0.0
        for p in pos:
            exp = (p["notional"] / equity * 100) if equity > 0 else 0
            if p["side"] in ("BUY", "LONG"): long_pct += exp
            else: short_pct += exp
        proposed = leverage * 100
        if is_long: long_pct += proposed
        else: short_pct += proposed
        # Correlation clustering
        same_dir, mx = 0, 0.0
        for p in pos:
            c = _corr(sym, p["symbol"])
            mx = max(mx, c)
            same = (is_long and p["side"] in ("BUY", "LONG")) or (not is_long and p["side"] in ("SELL", "SHORT"))
            if same and c > 0.7: same_dir += 1
        if same_dir >= 3: cr = "CRITICAL"
        elif same_dir >= 2 or mx > 0.85: cr = "HIGH"
        elif same_dir >= 1: cr = "MODERATE"
        else: cr = "LOW"
        total = long_pct + short_pct + proposed
        return {"post_trade_directional_pct": round(long_pct - short_pct, 0),
                "correlation_risk": cr, "risk_budget_after": round(min(100, total / 5), 0),
                "same_dir_correlated_count": same_dir, "total_exposure_pct": round(total, 0)}

    # ── Decision ───────────────────────────────────────────────────

    def _decide(self, ev, max_loss, equity, impact) -> Tuple[str, str]:
        if ev < 0: return "skip", f"Negative EV (${ev:.2f})"
        if abs(max_loss) > equity * 0.20: return "skip", f"Max loss ${max_loss:.2f} > 20% equity"
        reasons = []
        if impact["correlation_risk"] == "CRITICAL":
            reasons.append(f"CRITICAL corr risk ({impact['same_dir_correlated_count']} same-dir)")
        if impact["risk_budget_after"] > 80:
            reasons.append(f"Risk budget {impact['risk_budget_after']:.0f}% used")
        if abs(impact["post_trade_directional_pct"]) > 300:
            reasons.append(f"Directional tilt {impact['post_trade_directional_pct']:.0f}%")
        if 0 < ev < abs(max_loss) * 0.1:
            reasons.append(f"Marginal EV ${ev:.2f} vs loss ${max_loss:.2f}")
        if reasons: return "reduce_size", ". ".join(reasons)
        r = [f"Positive EV ${ev:.2f}"]
        if impact["correlation_risk"] in ("LOW", "MODERATE"):
            r.append(f"Portfolio risk {impact['correlation_risk']}")
        return "proceed", ". ".join(r)

    # ── Agent formatting ───────────────────────────────────────────

    def format_for_agent(self, sim: Dict) -> str:
        """Format simulation for Trade/Risk/Critic agent context injection."""
        lines = ["PRE-TRADE SIMULATION:"]
        for s in sim.get("scenarios", []):
            p, sign = s["estimated_pnl"], "+" if s["estimated_pnl"] >= 0 else ""
            lines.append(f"  {s['name']} ({s['probability']:.0%}): {sign}${p:.2f} "
                         f"in {s['time_to_resolution']} -- {s['description']}")
        imp = sim.get("portfolio_impact", {})
        lines.append(f"  EV: ${sim.get('expected_value', 0):+.2f} | "
                     f"Max loss: ${sim.get('max_loss', 0):.2f} | "
                     f"Portfolio: {imp.get('post_trade_directional_pct', 0):+.0f}% "
                     f"({imp.get('correlation_risk', '?')})")
        lines.append(f"  -> {sim.get('recommendation', '?').upper()}: {sim.get('reasoning', '')}")
        return "\n".join(lines)

    @staticmethod
    def _fmth(h: float) -> str:
        if h < 0.5: return f"{int(h * 60)}min"
        lo, hi = max(1, int(h * 0.7)), max(int(h * 1.3) + 1, int(h * 1.5))
        return f"{lo}-{hi}h" if lo != hi else f"{lo}h"
