"""
Agent performance tracking and self-evaluation.
Measures accuracy, calibration, and value-add per agent.
Enables the network to self-improve by identifying weak links.
"""

import json
import os
import logging
import math
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

logger = logging.getLogger("bot.llm.agents.agent_performance")

DATA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "llm", "agent_performance.json"
)

# Actions that count as "approve" vs "reject"
APPROVE_ACTIONS = {"go", "proceed", "long", "short", "buy", "sell", "hold", "approve"}
REJECT_ACTIONS = {"skip", "flat", "veto", "reject", "close", "no_trade"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentPerformanceTracker:
    """Tracks per-agent decision quality over time."""

    def __init__(self):
        self.data = self._load()

    # ── Persistence ──────────────────────────────────────────────

    def _load(self) -> Dict:
        try:
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, "r") as f:
                    return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("agent_performance load failed: %s — starting fresh", e)
        return {"decisions": [], "outcomes": [], "version": 1}

    def _save(self):
        try:
            os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
            with open(DATA_FILE, "w") as f:
                json.dump(self.data, f, indent=1)
        except IOError as e:
            logger.error("agent_performance save failed: %s", e)

    # ── Recording ────────────────────────────────────────────────

    def record_decision(
        self,
        agent_name: str,
        symbol: str,
        action: str,
        confidence: float,
        context: Dict = None,
    ):
        """Record an agent's decision for later evaluation against outcome."""
        rec = {
            "agent": agent_name.lower(),
            "symbol": symbol,
            "action": action.lower(),
            "confidence": round(confidence, 3),
            "ts": _now_iso(),
            "matched": False,  # set True once matched to outcome
        }
        if context:
            # Store lightweight context (regime, side, sizing)
            for key in ("regime", "side", "recommended_size", "veto_reason",
                        "counter_thesis", "sizing_pct"):
                if key in context:
                    rec[key] = context[key]
        self.data["decisions"].append(rec)
        # Keep last 500 decisions to bound file size
        if len(self.data["decisions"]) > 500:
            self.data["decisions"] = self.data["decisions"][-500:]
        self._save()

    def record_outcome(
        self,
        symbol: str,
        pnl: float,
        entry_time: str,
        exit_time: str,
        mfe_pct: float = 0.0,
        mae_pct: float = 0.0,
        side: str = "",
    ):
        """Record trade outcome and match to all agent decisions near entry_time."""
        outcome = {
            "symbol": symbol,
            "pnl": round(pnl, 4),
            "side": side.lower(),
            "entry_time": entry_time,
            "exit_time": exit_time,
            "mfe_pct": round(mfe_pct, 4),
            "mae_pct": round(mae_pct, 4),
            "ts": _now_iso(),
            "win": pnl > 0,
        }
        self.data["outcomes"].append(outcome)

        # Match unmatched decisions to this outcome (same symbol, within 5 min)
        matched = 0
        for dec in self.data["decisions"]:
            if dec["matched"] or dec["symbol"] != symbol:
                continue
            # Simple time proximity match
            try:
                dec_t = datetime.fromisoformat(dec["ts"])
                entry_t = datetime.fromisoformat(entry_time)
                delta = abs((dec_t - entry_t).total_seconds())
                if delta < 300:  # within 5 minutes
                    dec["matched"] = True
                    dec["outcome_pnl"] = pnl
                    dec["outcome_win"] = pnl > 0
                    dec["outcome_mfe"] = mfe_pct
                    matched += 1
            except (ValueError, TypeError):
                continue

        # Keep last 300 outcomes
        if len(self.data["outcomes"]) > 300:
            self.data["outcomes"] = self.data["outcomes"][-300:]
        self._save()
        logger.info("Recorded outcome %s pnl=%.2f%%, matched %d decisions",
                     symbol, pnl, matched)

    # ── Analysis ─────────────────────────────────────────────────

    def _matched_decisions(self, agent_name: str = None) -> List[Dict]:
        """Get decisions that have been matched to outcomes."""
        decs = [d for d in self.data["decisions"] if d.get("matched")]
        if agent_name:
            decs = [d for d in decs if d["agent"] == agent_name.lower()]
        return decs

    def get_agent_stats(self, agent_name: str) -> Dict:
        """Get accuracy, calibration, value-add for one agent."""
        decs = self._matched_decisions(agent_name)
        if not decs:
            return {"n": 0, "status": "no_data"}

        approved = [d for d in decs if d["action"] in APPROVE_ACTIONS]
        rejected = [d for d in decs if d["action"] in REJECT_ACTIONS]

        # Accuracy: approve+win or reject+loss = correct
        correct = 0
        for d in decs:
            is_approve = d["action"] in APPROVE_ACTIONS
            won = d.get("outcome_win", False)
            if (is_approve and won) or (not is_approve and not won):
                correct += 1
        accuracy = correct / len(decs) if decs else 0

        # Average confidence and actual win rate
        avg_conf = sum(d["confidence"] for d in decs) / len(decs) if decs else 0
        actual_wr = sum(1 for d in decs if d.get("outcome_win")) / len(decs) if decs else 0
        cal_drift = avg_conf - actual_wr

        # Approved trade stats
        app_wins = sum(1 for d in approved if d.get("outcome_win"))
        app_avg_pnl = (sum(d.get("outcome_pnl", 0) for d in approved) / len(approved)
                       if approved else 0)

        # Rejected trade stats (counterfactual)
        rej_would_win = sum(1 for d in rejected if d.get("outcome_win"))
        rej_avg_pnl = (sum(d.get("outcome_pnl", 0) for d in rejected) / len(rejected)
                       if rejected else 0)

        return {
            "n": len(decs),
            "accuracy": round(accuracy, 3),
            "avg_confidence": round(avg_conf, 3),
            "actual_win_rate": round(actual_wr, 3),
            "calibration_drift": round(cal_drift, 3),
            "approved": {"n": len(approved), "wins": app_wins,
                         "avg_pnl": round(app_avg_pnl, 3)},
            "rejected": {"n": len(rejected), "would_have_won": rej_would_win,
                         "avg_pnl": round(rej_avg_pnl, 3)},
        }

    def get_calibration_curve(self, agent_name: str, bins: int = 5) -> List[Tuple]:
        """Return (predicted_confidence, actual_win_rate, n) per bin."""
        decs = self._matched_decisions(agent_name)
        if not decs:
            return []

        # Bin by confidence
        bin_width = 1.0 / bins
        buckets = defaultdict(list)
        for d in decs:
            conf = min(d["confidence"], 0.999)
            bucket = int(conf / bin_width)
            buckets[bucket].append(d)

        curve = []
        for b in range(bins):
            items = buckets.get(b, [])
            if not items:
                continue
            avg_conf = sum(d["confidence"] for d in items) / len(items)
            win_rate = sum(1 for d in items if d.get("outcome_win")) / len(items)
            curve.append((round(avg_conf, 3), round(win_rate, 3), len(items)))
        return curve

    def get_value_add(self, agent_name: str) -> Dict:
        """Compare approved vs rejected trade outcomes."""
        decs = self._matched_decisions(agent_name)
        if not decs:
            return {"status": "no_data"}

        approved = [d for d in decs if d["action"] in APPROVE_ACTIONS]
        rejected = [d for d in decs if d["action"] in REJECT_ACTIONS]

        app_pnl = sum(d.get("outcome_pnl", 0) for d in approved)
        rej_pnl = sum(d.get("outcome_pnl", 0) for d in rejected)

        # Positive = agent is adding value (approved > rejected)
        value = app_pnl - rej_pnl if (approved and rejected) else 0
        destroying = len(rejected) > 0 and rej_pnl > app_pnl

        return {
            "approved_total_pnl": round(app_pnl, 3),
            "rejected_total_pnl": round(rej_pnl, 3),
            "value_added_pnl": round(value, 3),
            "destroying_value": destroying,
            "n_approved": len(approved),
            "n_rejected": len(rejected),
        }

    def get_veto_stats(self) -> Dict:
        """Critic-specific: veto rate, accuracy, PnL impact."""
        decs = self._matched_decisions("critic")
        if not decs:
            return {"status": "no_data"}

        vetoes = [d for d in decs if d["action"] in REJECT_ACTIONS]
        approvals = [d for d in decs if d["action"] in APPROVE_ACTIONS]
        veto_rate = len(vetoes) / len(decs) if decs else 0

        # Correct veto = vetoed and trade would have lost
        correct_vetoes = sum(1 for d in vetoes if not d.get("outcome_win"))
        veto_accuracy = correct_vetoes / len(vetoes) if vetoes else 0

        pnl_saved = sum(abs(d.get("outcome_pnl", 0)) for d in vetoes
                        if not d.get("outcome_win"))
        pnl_missed = sum(d.get("outcome_pnl", 0) for d in vetoes
                         if d.get("outcome_win"))

        return {
            "veto_rate": round(veto_rate, 3),
            "veto_accuracy": round(veto_accuracy, 3),
            "n_vetoes": len(vetoes),
            "n_approvals": len(approvals),
            "pnl_saved": round(pnl_saved, 3),
            "pnl_missed": round(pnl_missed, 3),
            "net_veto_value": round(pnl_saved - pnl_missed, 3),
        }

    def get_sizing_stats(self) -> Dict:
        """Risk Agent specific: sizing accuracy vs optimal."""
        decs = self._matched_decisions("risk")
        if not decs:
            return {"status": "no_data"}

        pairs = []
        for d in decs:
            rec_size = d.get("sizing_pct") or d.get("recommended_size")
            mfe = d.get("outcome_mfe", 0)
            if rec_size is not None and mfe != 0:
                # Optimal size approximation: proportional to MFE
                # (higher MFE = could have sized bigger)
                pairs.append((float(rec_size), mfe))

        if not pairs:
            return {"status": "no_sizing_data", "n": len(decs)}

        # Correlation between recommended size and realized MFE
        n = len(pairs)
        sx = sum(p[0] for p in pairs)
        sy = sum(p[1] for p in pairs)
        sxx = sum(p[0] ** 2 for p in pairs)
        syy = sum(p[1] ** 2 for p in pairs)
        sxy = sum(p[0] * p[1] for p in pairs)

        denom = math.sqrt((n * sxx - sx**2) * (n * syy - sy**2))
        corr = (n * sxy - sx * sy) / denom if denom > 0 else 0

        # Did we undersize winners?
        winners = [p for p in pairs if p[1] > 0]
        losers = [p for p in pairs if p[1] <= 0]
        avg_win_size = sum(p[0] for p in winners) / len(winners) if winners else 0
        avg_loss_size = sum(p[0] for p in losers) / len(losers) if losers else 0

        return {
            "n_with_sizing": n,
            "size_mfe_correlation": round(corr, 3),
            "avg_winner_size": round(avg_win_size, 3),
            "avg_loser_size": round(avg_loss_size, 3),
            "undersizing_winners": avg_win_size < avg_loss_size,
        }

    # ── Prompt injection ─────────────────────────────────────────

    def format_for_agent(self, agent_name: str) -> str:
        """Format this agent's own performance stats for prompt injection."""
        stats = self.get_agent_stats(agent_name)
        if stats.get("status") == "no_data":
            return ""

        n = stats["n"]
        acc = stats["accuracy"]
        drift = stats["calibration_drift"]
        app = stats["approved"]
        rej = stats["rejected"]

        lines = [
            f"YOUR PERFORMANCE ({n} decisions): {acc:.0%} accuracy, "
            f"calibration drift {drift:+.0%}"
        ]

        if app["n"]:
            wr = app["wins"] / app["n"] if app["n"] else 0
            lines.append(
                f"Approved: {app['n']} trades, {wr:.0%} WR, avg {app['avg_pnl']:+.2f}%"
            )
        if rej["n"]:
            lines.append(
                f"Rejected: {rej['n']} signals, {rej['would_have_won']} would have won "
                f"(avg PnL {rej['avg_pnl']:+.2f}%)"
            )

        # Calibration advice
        if abs(drift) > 0.05 and n >= 10:
            direction = "reduce" if drift > 0 else "increase"
            lines.append(
                f"CALIBRATION: {direction} confidence estimates by ~{abs(drift):.0%}"
            )

        # Special sections
        if agent_name.lower() == "critic":
            vs = self.get_veto_stats()
            if vs.get("n_vetoes", 0) > 0:
                lines.append(
                    f"VETO: {vs['veto_accuracy']:.0%} accurate, "
                    f"saved {vs['pnl_saved']:+.2f}%, missed {vs['pnl_missed']:+.2f}%, "
                    f"net {vs['net_veto_value']:+.2f}%"
                )
                if vs["veto_accuracy"] < 0.5 and vs["n_vetoes"] >= 5:
                    lines.append("WARNING: Veto accuracy below 50% — approve more trades")

        if agent_name.lower() == "risk":
            ss = self.get_sizing_stats()
            if ss.get("n_with_sizing", 0) > 0:
                lines.append(
                    f"SIZING: corr={ss['size_mfe_correlation']:.2f} with optimal"
                )
                if ss.get("undersizing_winners"):
                    lines.append("WARNING: Undersizing winners vs losers — size up on conviction")

        return "\n".join(lines)

    def format_network_summary(self) -> str:
        """Format the whole network's performance for the Overseer agent."""
        agents = set(d["agent"] for d in self.data["decisions"])
        if not agents:
            return "NETWORK HEALTH: No agent decisions recorded yet."

        lines = ["NETWORK HEALTH:"]
        for agent in sorted(agents):
            stats = self.get_agent_stats(agent)
            if stats.get("status") == "no_data":
                continue
            n = stats["n"]
            acc = stats["accuracy"]
            drift = stats["calibration_drift"]
            tag = ""
            if abs(drift) > 0.10:
                tag = " — MISCALIBRATED"
            va = self.get_value_add(agent)
            if va.get("destroying_value"):
                tag = " — DESTROYING VALUE"
            lines.append(
                f"  {agent.capitalize()}: {acc:.0%} accuracy (n={n}), "
                f"drift {drift:+.0%}{tag}"
            )

        # Critic veto summary
        vs = self.get_veto_stats()
        if vs.get("n_vetoes", 0) > 0:
            lines.append(
                f"  Critic vetoes: {vs['n_vetoes']}, {vs['veto_accuracy']:.0%} accurate, "
                f"net PnL {vs['net_veto_value']:+.2f}%"
            )

        return "\n".join(lines)


# ── Module-level singleton ───────────────────────────────────────

_tracker: Optional[AgentPerformanceTracker] = None


def get_tracker() -> AgentPerformanceTracker:
    """Get or create the singleton tracker."""
    global _tracker
    if _tracker is None:
        _tracker = AgentPerformanceTracker()
    return _tracker
