"""
Automated Go-Live Gate — 5 criteria from quantplan1.docx §9.1.

All 5 gates must pass before transitioning from paper to live trading:
  1. Walk-Forward ratio > 0.7 (averaged across last 3 windows)
  2. Net PnL > 0 in last 30-day paper period
  3. Max drawdown < 15% cumulative
  4. All factor ICs > 0 on 30-day rolling
  5. Sharpe ratio > 1.0 with full fee accounting

Usage:
    from validation.go_live_gate import GoLiveGate
    gate = GoLiveGate(trade_ledger=ledger, ic_tracker=tracker)
    result = gate.evaluate()
    print(gate.format_report(result))
"""

import logging
import math
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bot.validation.go_live_gate")

# Gate thresholds
WF_RATIO_THRESHOLD = 0.7
NET_PNL_THRESHOLD = 0.0
MAX_DD_THRESHOLD = 15.0
IC_THRESHOLD = 0.0
SHARPE_THRESHOLD = 1.0


class GoLiveGate:
    """Evaluates 5 deployment criteria for paper → live transition."""

    def __init__(self, trade_ledger=None, ic_tracker=None, circuit_breaker=None):
        self._ledger = trade_ledger
        self._ic_tracker = ic_tracker
        self._cb = circuit_breaker

    def evaluate(self) -> Dict[str, Any]:
        """Run all 5 gate checks.

        Returns:
            Dict with 'passed' (bool), 'gates' (per-gate results),
            and 'recommendation' (str).
        """
        gates = {
            "walk_forward": self._gate_walk_forward(),
            "net_pnl": self._gate_net_pnl(),
            "max_drawdown": self._gate_max_drawdown(),
            "factor_ics": self._gate_factor_ics(),
            "sharpe_ratio": self._gate_sharpe_ratio(),
        }

        all_passed = all(g.get("passed", False) for g in gates.values())
        insufficient = any(g.get("passed") is None for g in gates.values())

        if all_passed:
            recommendation = "ALL GATES PASSED — system is cleared for live trading."
        elif insufficient:
            recommendation = "INSUFFICIENT DATA — some gates cannot be evaluated yet. Continue paper trading."
        else:
            failed = [name for name, g in gates.items() if not g.get("passed")]
            recommendation = f"BLOCKED — {len(failed)} gate(s) failed: {', '.join(failed)}. Do not go live."

        return {
            "passed": all_passed,
            "gates": gates,
            "recommendation": recommendation,
            "evaluated_at": time.time(),
        }

    # ── Individual gates ──────────────────────────────────────────

    def _gate_walk_forward(self) -> Dict[str, Any]:
        """Gate 1: Walk-Forward ratio > 0.7."""
        try:
            from validation.walk_forward import run_rolling_walk_forward, avg_wf_ratio

            if not self._ledger:
                return {"passed": None, "value": None, "threshold": WF_RATIO_THRESHOLD,
                        "note": "No trade ledger available"}

            trades = self._ledger.get_trades(lookback_days=60)
            if len(trades) < 10:
                return {"passed": None, "value": None, "threshold": WF_RATIO_THRESHOLD,
                        "note": f"Need 10+ trades, have {len(trades)}"}

            results = [{"pnl": self._pf(t.get("net_pnl", "0")),
                        "timestamp": self._pf(t.get("timestamp", "0"))}
                       for t in trades]
            wf_results = run_rolling_walk_forward(results)
            ratio = avg_wf_ratio(wf_results) if wf_results else 0.0

            return {"passed": ratio >= WF_RATIO_THRESHOLD, "value": round(ratio, 3),
                    "threshold": WF_RATIO_THRESHOLD,
                    "windows": len(wf_results) if wf_results else 0}
        except Exception as e:
            return {"passed": None, "value": None, "threshold": WF_RATIO_THRESHOLD,
                    "note": f"Error: {e}"}

    def _gate_net_pnl(self) -> Dict[str, Any]:
        """Gate 2: Net PnL > 0 in last 30 days."""
        if not self._ledger:
            return {"passed": None, "value": None, "threshold": NET_PNL_THRESHOLD,
                    "note": "No trade ledger"}

        trades = self._ledger.get_trades(lookback_days=30)
        if len(trades) < 5:
            return {"passed": None, "value": None, "threshold": NET_PNL_THRESHOLD,
                    "note": f"Need 5+ trades, have {len(trades)}"}

        net_pnl = sum(self._pf(t.get("net_pnl", "0")) for t in trades)
        return {"passed": net_pnl > NET_PNL_THRESHOLD, "value": round(net_pnl, 2),
                "threshold": NET_PNL_THRESHOLD, "trades": len(trades)}

    def _gate_max_drawdown(self) -> Dict[str, Any]:
        """Gate 3: Max drawdown < 15%."""
        if not self._ledger:
            return {"passed": None, "value": None, "threshold": MAX_DD_THRESHOLD,
                    "note": "No trade ledger"}

        trades = self._ledger.get_trades(lookback_days=30)
        if len(trades) < 5:
            return {"passed": None, "value": None, "threshold": MAX_DD_THRESHOLD,
                    "note": f"Need 5+ trades, have {len(trades)}"}

        # Compute max DD from running equity series
        equities = []
        for t in reversed(trades):  # oldest first
            eq = self._pf(t.get("running_equity", "0"))
            if eq > 0:
                equities.append(eq)

        if len(equities) < 2:
            # Fallback: use session DD from circuit breaker
            if self._cb and hasattr(self._cb, 'session_peak_equity') and self._cb.session_peak_equity > 0:
                dd = (self._cb.session_peak_equity - equities[-1] if equities else 0) / self._cb.session_peak_equity * 100
                return {"passed": dd < MAX_DD_THRESHOLD, "value": round(dd, 2),
                        "threshold": MAX_DD_THRESHOLD, "source": "circuit_breaker"}
            return {"passed": None, "value": None, "threshold": MAX_DD_THRESHOLD,
                    "note": "Insufficient equity data"}

        peak = equities[0]
        max_dd_pct = 0.0
        for eq in equities:
            peak = max(peak, eq)
            dd = (peak - eq) / peak * 100 if peak > 0 else 0
            max_dd_pct = max(max_dd_pct, dd)

        return {"passed": max_dd_pct < MAX_DD_THRESHOLD, "value": round(max_dd_pct, 2),
                "threshold": MAX_DD_THRESHOLD}

    def _gate_factor_ics(self) -> Dict[str, Any]:
        """Gate 4: All factor ICs > 0."""
        if not self._ic_tracker:
            return {"passed": None, "details": {}, "threshold": IC_THRESHOLD,
                    "note": "No IC tracker"}

        try:
            report = self._ic_tracker.get_report()
            if not report:
                return {"passed": None, "details": {}, "threshold": IC_THRESHOLD,
                        "note": "No factors tracked yet"}

            details = {}
            all_positive = True
            has_data = False

            for factor, data in report.items():
                ic = data.get("ic")
                if ic is not None:
                    has_data = True
                    details[factor] = round(ic, 4)
                    if ic <= IC_THRESHOLD:
                        all_positive = False
                else:
                    details[factor] = None

            if not has_data:
                return {"passed": None, "details": details, "threshold": IC_THRESHOLD,
                        "note": "Insufficient data for IC computation"}

            return {"passed": all_positive, "details": details, "threshold": IC_THRESHOLD}
        except Exception as e:
            return {"passed": None, "details": {}, "threshold": IC_THRESHOLD,
                    "note": f"Error: {e}"}

    def _gate_sharpe_ratio(self) -> Dict[str, Any]:
        """Gate 5: Sharpe > 1.0 with fee accounting."""
        if not self._ledger:
            return {"passed": None, "value": None, "threshold": SHARPE_THRESHOLD,
                    "note": "No trade ledger"}

        trades = self._ledger.get_trades(lookback_days=30)
        if len(trades) < 10:
            return {"passed": None, "value": None, "threshold": SHARPE_THRESHOLD,
                    "note": f"Need 10+ trades, have {len(trades)}"}

        # Group PnL by day for daily returns
        daily_pnl: Dict[str, float] = {}
        for t in trades:
            ts = self._pf(t.get("timestamp", "0"))
            if ts <= 0:
                continue
            day = str(int(ts // 86400))
            daily_pnl[day] = daily_pnl.get(day, 0) + self._pf(t.get("net_pnl", "0"))

        if len(daily_pnl) < 5:
            return {"passed": None, "value": None, "threshold": SHARPE_THRESHOLD,
                    "note": f"Need 5+ trading days, have {len(daily_pnl)}"}

        returns = list(daily_pnl.values())
        mean_ret = sum(returns) / len(returns)
        variance = sum((r - mean_ret) ** 2 for r in returns) / (len(returns) - 1)
        std_ret = math.sqrt(variance) if variance > 0 else 0

        if std_ret < 1e-10:
            return {"passed": None, "value": None, "threshold": SHARPE_THRESHOLD,
                    "note": "Zero variance in returns"}

        # Annualize: sqrt(365) for crypto (trades every day)
        sharpe = (mean_ret / std_ret) * math.sqrt(365)

        return {"passed": sharpe >= SHARPE_THRESHOLD, "value": round(sharpe, 3),
                "threshold": SHARPE_THRESHOLD, "trading_days": len(daily_pnl)}

    # ── Formatting ────────────────────────────────────────────────

    def format_report(self, result: Dict[str, Any]) -> str:
        """Human-readable gate report."""
        lines = [
            "=" * 60,
            "  GO-LIVE GATE EVALUATION",
            "=" * 60,
        ]

        overall = "PASSED" if result["passed"] else "BLOCKED"
        lines.append(f"  Overall: {overall}")
        lines.append("")

        for name, gate in result.get("gates", {}).items():
            passed = gate.get("passed")
            status = "PASS" if passed else ("N/A" if passed is None else "FAIL")
            value = gate.get("value")
            threshold = gate.get("threshold")
            val_str = f"{value}" if value is not None else "N/A"
            thr_str = f"{threshold}" if threshold is not None else ""

            lines.append(f"  [{status:4s}] {name}: {val_str} (threshold: {thr_str})")
            if "note" in gate:
                lines.append(f"         {gate['note']}")

        lines.append("")
        lines.append(f"  Recommendation: {result.get('recommendation', '')}")
        lines.append("=" * 60)

        return "\n".join(lines)

    @staticmethod
    def _pf(val) -> float:
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0
