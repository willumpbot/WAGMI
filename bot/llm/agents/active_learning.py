"""
Active Learning Engine: Makes the trading brain smarter over time.

After every trade and every 30 minutes, this engine:
1. DIAGNOSES — What's working? What's failing? Why?
2. HYPOTHESIZES — What change would improve performance?
3. VALIDATES — Test the hypothesis against recent data
4. APPLIES — If validated, update the system
5. MONITORS — Track whether the change actually helped

This is the system's ability to THINK ABOUT ITS OWN THINKING.
"""

import csv
import json
import math
import os
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

logger = logging.getLogger("bot.llm.agents.active_learning")

DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "llm", "active_learning.json")
TRADES_CSV = os.path.join(os.path.dirname(__file__), "..", "..", "data", "trades.csv")

# Hypothesis lifecycle: proposed -> testing -> validated -> applied -> monitoring -> retired/rejected
VALID_STATUSES = {"proposed", "testing", "validated", "applied", "monitoring", "retired", "rejected"}
MIN_TRADES_FOR_VALIDATION = 5
MIN_TRADES_FOR_DIAGNOSIS = 3
MONITORING_WINDOW_TRADES = 10
MAX_HYPOTHESES = 50


class ActiveLearningEngine:
    """Meta-learning engine that continuously improves the trading brain."""

    def __init__(self):
        self.state = self._load_state()
        self.last_cycle_time = 0
        self.cycle_interval = 1800  # 30 minutes

    # ── Persistence ──────────────────────────────────────────

    def _load_state(self) -> Dict:
        try:
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, "r") as f:
                    return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("active_learning load failed: %s — starting fresh", e)
        return {
            "hypotheses": [],
            "applied_changes": [],
            "diagnosis_history": [],
            "cycle_count": 0,
            "version": 1,
        }

    def _save_state(self):
        try:
            os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
            with open(DATA_FILE, "w") as f:
                json.dump(self.state, f, indent=1, default=str)
        except IOError as e:
            logger.error("active_learning save failed: %s", e)

    def _next_hyp_id(self) -> str:
        n = len(self.state["hypotheses"]) + 1
        return f"hyp_{n:03d}"

    # ══════════════════════════════════════════════════════════
    # TRADE DATA LOADING
    # ══════════════════════════════════════════════════════════

    def _load_trades(self, max_rows: int = 200) -> List[Dict]:
        """Load recent trades from CSV."""
        trades = []
        try:
            if not os.path.exists(TRADES_CSV):
                return []
            with open(TRADES_CSV, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        row["pnl"] = float(row.get("pnl", 0))
                        row["fees"] = float(row.get("fees", 0))
                        row["leverage"] = float(row.get("leverage", 1))
                        row["confidence"] = float(row.get("confidence", 0))
                        row["entry"] = float(row.get("entry", 0))
                        row["exit"] = float(row.get("exit", 0))
                        row["win"] = row["pnl"] > 0
                        trades.append(row)
                    except (ValueError, KeyError):
                        continue
            return trades[-max_rows:]
        except Exception as e:
            logger.warning("Failed to load trades: %s", e)
            return []

    # ══════════════════════════════════════════════════════════
    # STEP 1: DIAGNOSE — What's happening?
    # ══════════════════════════════════════════════════════════

    def diagnose(self, recent_trades: List[Dict], agent_stats: Dict,
                 feedback_states: Dict, rejection_stats: Dict) -> Dict:
        """Analyze system performance and identify weaknesses."""
        if not recent_trades:
            recent_trades = self._load_trades()
        if len(recent_trades) < MIN_TRADES_FOR_DIAGNOSIS:
            return {"overall_health": "insufficient_data", "strengths": [],
                    "weaknesses": [], "root_causes": [], "urgency": "low", "metrics": {}}

        metrics = {}
        strengths = []
        weaknesses = []
        root_causes = []

        # -- Win rate trends --
        last_10 = recent_trades[-10:]
        last_20 = recent_trades[-20:] if len(recent_trades) >= 20 else recent_trades
        wr_10 = sum(1 for t in last_10 if t.get("win")) / len(last_10) if last_10 else 0
        wr_20 = sum(1 for t in last_20 if t.get("win")) / len(last_20) if last_20 else 0
        metrics["wr_last_10"] = round(wr_10, 3)
        metrics["wr_last_20"] = round(wr_20, 3)

        if len(recent_trades) >= 20:
            first_half = recent_trades[:len(recent_trades) // 2]
            second_half = recent_trades[len(recent_trades) // 2:]
            wr_first = sum(1 for t in first_half if t.get("win")) / len(first_half)
            wr_second = sum(1 for t in second_half if t.get("win")) / len(second_half)
            if wr_second > wr_first + 0.05:
                metrics["wr_trend"] = "improving"
                strengths.append(f"WR improving: {wr_first:.0%} -> {wr_second:.0%}")
            elif wr_second < wr_first - 0.05:
                metrics["wr_trend"] = "declining"
                weaknesses.append(f"WR declining: {wr_first:.0%} -> {wr_second:.0%}")
                root_causes.append("recent_trades_underperforming")
            else:
                metrics["wr_trend"] = "stable"
        else:
            metrics["wr_trend"] = "insufficient"

        # -- PnL trend --
        pnls = [t["pnl"] for t in recent_trades]
        avg_pnl_10 = sum(p for p in pnls[-10:]) / min(10, len(pnls)) if pnls else 0
        avg_pnl_all = sum(pnls) / len(pnls) if pnls else 0
        metrics["avg_pnl_last_10"] = round(avg_pnl_10, 2)
        metrics["avg_pnl_all"] = round(avg_pnl_all, 2)
        if avg_pnl_10 < 0 and avg_pnl_all >= 0:
            weaknesses.append(f"Recent PnL negative ({avg_pnl_10:.2f}) vs overall positive")
            metrics["avg_pnl_trend"] = "declining"
        elif avg_pnl_10 > avg_pnl_all * 1.2:
            metrics["avg_pnl_trend"] = "improving"
        else:
            metrics["avg_pnl_trend"] = "stable"

        # -- Per-regime performance --
        by_regime = defaultdict(list)
        for t in recent_trades:
            regime = t.get("regime", "unknown")
            by_regime[regime].append(t)

        regime_wr = {}
        for regime, trades in by_regime.items():
            wr = sum(1 for t in trades if t.get("win")) / len(trades)
            regime_wr[regime] = (wr, len(trades))
        metrics["regime_performance"] = {r: {"wr": round(wr, 3), "n": n}
                                          for r, (wr, n) in regime_wr.items()}

        if regime_wr:
            best_regime = max(regime_wr, key=lambda r: regime_wr[r][0])
            worst_regime = min(regime_wr, key=lambda r: regime_wr[r][0])
            metrics["best_regime"] = best_regime
            metrics["worst_regime"] = worst_regime
            worst_wr, worst_n = regime_wr[worst_regime]
            if worst_wr < 0.30 and worst_n >= 3:
                weaknesses.append(f"{worst_regime} regime: {worst_wr:.0%} WR over {worst_n} trades")
                root_causes.append(f"poor_{worst_regime}_regime_performance")

        # -- Per-symbol performance --
        by_symbol = defaultdict(list)
        for t in recent_trades:
            by_symbol[t.get("symbol", "?")].append(t)

        symbol_wr = {}
        for sym, trades in by_symbol.items():
            wr = sum(1 for t in trades if t.get("win")) / len(trades)
            symbol_wr[sym] = (wr, len(trades))
        if symbol_wr:
            best_sym = max(symbol_wr, key=lambda s: symbol_wr[s][0])
            worst_sym = min(symbol_wr, key=lambda s: symbol_wr[s][0])
            metrics["best_symbol"] = best_sym
            metrics["worst_symbol"] = worst_sym
            worst_s_wr, worst_s_n = symbol_wr[worst_sym]
            if worst_s_wr < 0.25 and worst_s_n >= 3:
                weaknesses.append(f"{worst_sym}: {worst_s_wr:.0%} WR over {worst_s_n} trades")
                root_causes.append(f"{worst_sym}_consistent_loser")

        # -- Per-side performance --
        by_side = defaultdict(list)
        for t in recent_trades:
            by_side[t.get("side", "?").upper()].append(t)
        for side, trades in by_side.items():
            wr = sum(1 for t in trades if t.get("win")) / len(trades)
            n = len(trades)
            if wr < 0.25 and n >= 3:
                weaknesses.append(f"{side} trades: {wr:.0%} WR ({n} trades)")
                root_causes.append(f"{side.lower()}_directional_weakness")

        # -- Time-of-day analysis --
        by_hour = defaultdict(list)
        for t in recent_trades:
            try:
                ts = t.get("timestamp", "")
                if ts:
                    hour = datetime.fromisoformat(ts).hour
                    by_hour[hour].append(t)
            except (ValueError, TypeError):
                pass

        if by_hour:
            hour_wr = {}
            for h, trades in by_hour.items():
                if len(trades) >= 2:
                    hour_wr[h] = sum(1 for t in trades if t.get("win")) / len(trades)
            if hour_wr:
                best_h = max(hour_wr, key=hour_wr.get)
                worst_h = min(hour_wr, key=hour_wr.get)
                metrics["best_hour"] = best_h
                metrics["worst_hour"] = worst_h
                if hour_wr[worst_h] < 0.20 and len(by_hour[worst_h]) >= 3:
                    weaknesses.append(f"Hour {worst_h}: {hour_wr[worst_h]:.0%} WR")

        # -- Exit efficiency (MFE capture) --
        exit_ratios = []
        for t in recent_trades:
            if t.get("win") and t.get("entry") and t.get("exit"):
                entry, exit_p = t["entry"], t["exit"]
                pnl_pct = abs(exit_p - entry) / entry if entry else 0
                # Compare to potential (rough proxy: 2x actual move for MFE)
                exit_ratios.append(min(pnl_pct * 100, 100))
        if exit_ratios:
            avg_exit_eff = sum(exit_ratios) / len(exit_ratios)
            metrics["exit_efficiency"] = round(avg_exit_eff, 1)

        # -- Sizing effectiveness (do bigger positions win more?) --
        high_lev = [t for t in recent_trades if t.get("leverage", 0) >= 3]
        low_lev = [t for t in recent_trades if t.get("leverage", 0) < 3]
        if high_lev and low_lev:
            high_wr = sum(1 for t in high_lev if t.get("win")) / len(high_lev)
            low_wr = sum(1 for t in low_lev if t.get("win")) / len(low_lev)
            metrics["sizing_correlation"] = round(high_wr - low_wr, 3)
            if high_wr < low_wr - 0.15:
                weaknesses.append(f"High-leverage trades underperform: {high_wr:.0%} vs {low_wr:.0%}")
                root_causes.append("overleveraging_losers")

        # -- Agent stats integration --
        if agent_stats:
            agent_weakest = None
            worst_acc = 1.0
            for agent, stats in agent_stats.items():
                if isinstance(stats, dict) and stats.get("n", 0) >= 5:
                    acc = stats.get("accuracy", 0.5)
                    if acc < worst_acc:
                        worst_acc = acc
                        agent_weakest = agent
                    if stats.get("destroying_value"):
                        weaknesses.append(f"{agent} agent destroying value")
                        root_causes.append(f"{agent}_agent_negative_contribution")
            if agent_weakest and worst_acc < 0.45:
                metrics["agent_weakest"] = agent_weakest
                weaknesses.append(f"{agent_weakest} agent accuracy: {worst_acc:.0%}")

        # -- Gate/rejection analysis --
        if rejection_stats and isinstance(rejection_stats, dict):
            for gate, count in rejection_stats.items():
                if isinstance(count, (int, float)) and count > 10:
                    metrics.setdefault("gate_rejections", {})[gate] = count
            if metrics.get("gate_rejections"):
                top_gate = max(metrics["gate_rejections"], key=metrics["gate_rejections"].get)
                metrics["gate_most_blocking"] = top_gate
                weaknesses.append(f"Gate '{top_gate}' blocking {metrics['gate_rejections'][top_gate]} signals")

        # -- Consecutive loss detection --
        streak = 0
        max_streak = 0
        for t in recent_trades:
            if not t.get("win"):
                streak += 1
                max_streak = max(max_streak, streak)
            else:
                streak = 0
        if max_streak >= 4:
            weaknesses.append(f"Max loss streak: {max_streak} consecutive")
            root_causes.append("loss_streak_regime_mismatch")

        # -- Determine overall health --
        if len(weaknesses) >= 4 or wr_10 < 0.25:
            health = "critical"
            urgency = "high"
        elif len(weaknesses) >= 2 or wr_10 < 0.40:
            health = "degrading"
            urgency = "medium"
        else:
            health = "healthy"
            urgency = "low"

        # -- Log positive findings --
        if wr_10 >= 0.60:
            strengths.append(f"Strong recent WR: {wr_10:.0%}")
        for sym, (wr, n) in symbol_wr.items():
            if wr >= 0.70 and n >= 3:
                strengths.append(f"{sym}: {wr:.0%} WR ({n} trades)")
        for regime, (wr, n) in regime_wr.items():
            if wr >= 0.65 and n >= 3:
                strengths.append(f"{regime} regime: {wr:.0%} WR")

        diagnosis = {
            "overall_health": health,
            "strengths": strengths[:5],
            "weaknesses": weaknesses[:5],
            "root_causes": root_causes[:5],
            "urgency": urgency,
            "metrics": metrics,
            "n_trades": len(recent_trades),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Keep last 20 diagnoses
        self.state["diagnosis_history"].append(diagnosis)
        self.state["diagnosis_history"] = self.state["diagnosis_history"][-20:]

        return diagnosis

    # ══════════════════════════════════════════════════════════
    # STEP 2: HYPOTHESIZE — What would fix it?
    # ══════════════════════════════════════════════════════════

    def generate_hypotheses(self, diagnosis: Dict) -> List[Dict]:
        """Generate improvement hypotheses from the diagnosis."""
        hypotheses = []
        weaknesses = diagnosis.get("weaknesses", [])
        root_causes = diagnosis.get("root_causes", [])
        metrics = diagnosis.get("metrics", {})

        # Avoid duplicating existing active hypotheses
        active_statements = {h["weakness"] for h in self.state["hypotheses"]
                            if h.get("status") not in ("rejected", "retired")}

        for weakness in weaknesses:
            if weakness in active_statements:
                continue

            hyp = self._weakness_to_hypothesis(weakness, root_causes, metrics)
            if hyp:
                hyp["id"] = self._next_hyp_id()
                hyp["created_at"] = datetime.now(timezone.utc).isoformat()
                hyp["status"] = "proposed"
                hyp["pre_metrics"] = {
                    "wr_10": metrics.get("wr_last_10", 0),
                    "avg_pnl": metrics.get("avg_pnl_last_10", 0),
                }
                hypotheses.append(hyp)

        # Prune old hypotheses if over limit
        active = [h for h in self.state["hypotheses"]
                  if h.get("status") not in ("rejected", "retired")]
        if len(active) + len(hypotheses) > MAX_HYPOTHESES:
            # Retire lowest-priority old ones
            proposed = [h for h in active if h["status"] == "proposed"]
            proposed.sort(key=lambda h: h.get("priority_score", 0))
            for h in proposed[:len(active) + len(hypotheses) - MAX_HYPOTHESES]:
                h["status"] = "retired"

        return hypotheses

    def _weakness_to_hypothesis(self, weakness: str, root_causes: List[str],
                                metrics: Dict) -> Optional[Dict]:
        """Map a specific weakness to a testable hypothesis."""
        w = weakness.lower()

        # Pattern: Poor regime performance
        if "regime" in w and "wr" in w:
            regime = metrics.get("worst_regime", "unknown")
            return {
                "weakness": weakness,
                "hypothesis": f"Reduce position size by 50% in {regime} regime",
                "expected_improvement": f"Cut losses in {regime} regime",
                "test_method": f"Next {MIN_TRADES_FOR_VALIDATION} trades in {regime}: compare PnL",
                "risk": "Miss profitable trades in that regime",
                "confidence": 0.6,
                "priority": "high",
                "priority_score": 8,
                "change_type": "parameter_change",
                "parameter": {"target": "regime_sizing", "regime": regime, "multiplier": 0.5},
                "rollback_info": f"Set {regime} regime sizing multiplier back to 1.0",
            }

        # Pattern: Symbol consistently losing
        for cause in root_causes:
            if "_consistent_loser" in cause:
                sym = cause.replace("_consistent_loser", "")
                return {
                    "weakness": weakness,
                    "hypothesis": f"Add cooldown for {sym}: skip next signal after a loss",
                    "expected_improvement": f"Reduce {sym} loss streaks",
                    "test_method": f"Next {MIN_TRADES_FOR_VALIDATION} {sym} trades: compare WR",
                    "risk": "Miss recovery trades",
                    "confidence": 0.5,
                    "priority": "medium",
                    "priority_score": 6,
                    "change_type": "prompt_addition",
                    "parameter": {"target": "trade_agent", "symbol": sym,
                                  "rule": f"After a {sym} loss, require higher confluence (3+ agree) for re-entry"},
                    "rollback_info": f"Remove {sym} cooldown rule from trade agent",
                }

        # Pattern: Directional weakness
        if "trades:" in w and "wr" in w:
            side = "SHORT" if "short" in w else "LONG" if "long" in w else None
            if side:
                return {
                    "weakness": weakness,
                    "hypothesis": f"Require extra confluence for {side} entries (3+ strategies)",
                    "expected_improvement": f"Filter out weak {side} setups",
                    "test_method": f"Next {MIN_TRADES_FOR_VALIDATION} {side} trades: compare WR",
                    "risk": f"Fewer {side} trades overall",
                    "confidence": 0.55,
                    "priority": "high",
                    "priority_score": 7,
                    "change_type": "prompt_addition",
                    "parameter": {"target": "trade_agent", "side": side,
                                  "rule": f"{side} trades underperforming — require stronger confluence"},
                    "rollback_info": f"Remove {side} confluence requirement",
                }

        # Pattern: High-leverage underperformance
        if "high-leverage" in w and "underperform" in w:
            return {
                "weakness": weakness,
                "hypothesis": "Cap leverage at 3x until WR improves above 50%",
                "expected_improvement": "Reduce oversized losses",
                "test_method": f"Next {MIN_TRADES_FOR_VALIDATION} trades: compare avg loss size",
                "risk": "Smaller wins too",
                "confidence": 0.7,
                "priority": "high",
                "priority_score": 9,
                "change_type": "parameter_change",
                "parameter": {"target": "max_leverage", "value": 3.0},
                "rollback_info": "Restore max leverage to previous value",
            }

        # Pattern: WR declining
        if "wr declining" in w:
            return {
                "weakness": weakness,
                "hypothesis": "Raise minimum confidence threshold by 5 points",
                "expected_improvement": "Filter out lower-quality signals",
                "test_method": f"Next {MIN_TRADES_FOR_VALIDATION} trades: compare WR",
                "risk": "Fewer trades overall",
                "confidence": 0.5,
                "priority": "medium",
                "priority_score": 5,
                "change_type": "parameter_change",
                "parameter": {"target": "min_confidence", "delta": 5},
                "rollback_info": "Lower min confidence threshold by 5",
            }

        # Pattern: Loss streak
        if "loss streak" in w:
            return {
                "weakness": weakness,
                "hypothesis": "After 3 consecutive losses, halve position size for next 2 trades",
                "expected_improvement": "Limit drawdown during losing streaks",
                "test_method": "Compare drawdown in streak periods",
                "risk": "Smaller recovery trades",
                "confidence": 0.65,
                "priority": "high",
                "priority_score": 8,
                "change_type": "prompt_addition",
                "parameter": {"target": "risk_agent",
                              "rule": "After 3+ consecutive losses, reduce sizing by 50% for next 2 trades"},
                "rollback_info": "Remove streak-based sizing reduction",
            }

        # Pattern: Agent destroying value
        if "agent" in w and ("destroying" in w or "accuracy" in w):
            agent = metrics.get("agent_weakest", "unknown")
            return {
                "weakness": weakness,
                "hypothesis": f"Reduce {agent} agent influence weight until accuracy improves",
                "expected_improvement": f"Less bad advice from {agent}",
                "test_method": f"Track {agent} accuracy over next {MIN_TRADES_FOR_VALIDATION} decisions",
                "risk": "Lose whatever value agent was adding",
                "confidence": 0.55,
                "priority": "medium",
                "priority_score": 6,
                "change_type": "weight_adjustment",
                "parameter": {"target": f"agent_{agent}_weight", "multiplier": 0.5},
                "rollback_info": f"Restore {agent} agent weight to 1.0",
            }

        # Pattern: Gate blocking too much
        if "gate" in w and "blocking" in w:
            gate = metrics.get("gate_most_blocking", "unknown")
            return {
                "weakness": weakness,
                "hypothesis": f"Loosen '{gate}' gate threshold by 20%",
                "expected_improvement": "Allow more signals through for evaluation",
                "test_method": f"Compare rejection rate and WR after loosening",
                "risk": "May allow bad signals through",
                "confidence": 0.45,
                "priority": "medium",
                "priority_score": 5,
                "change_type": "gate_modification",
                "parameter": {"target": gate, "adjustment": 0.20},
                "rollback_info": f"Tighten '{gate}' gate threshold back by 20%",
            }

        # Generic fallback
        return {
            "weakness": weakness,
            "hypothesis": f"Investigate and address: {weakness}",
            "expected_improvement": "Reduce identified weakness",
            "test_method": f"Monitor over next {MIN_TRADES_FOR_VALIDATION} trades",
            "risk": "Unknown",
            "confidence": 0.3,
            "priority": "low",
            "priority_score": 2,
            "change_type": "investigation",
            "parameter": {},
            "rollback_info": "N/A",
        }

    # ══════════════════════════════════════════════════════════
    # STEP 3: VALIDATE — Test the hypothesis
    # ══════════════════════════════════════════════════════════

    def validate_hypothesis(self, hypothesis: Dict, trade_outcomes: List[Dict]) -> Dict:
        """Test a hypothesis against recent trade data using simple A/B comparison."""
        hyp_id = hypothesis.get("id", "?")
        applied_at = hypothesis.get("testing_started_at", hypothesis.get("created_at", ""))

        # Split trades into before/after the hypothesis was proposed
        before, after = [], []
        for t in trade_outcomes:
            ts = t.get("timestamp", "")
            if ts and applied_at and ts < applied_at:
                before.append(t)
            else:
                after.append(t)

        if len(after) < MIN_TRADES_FOR_VALIDATION:
            return {
                "hypothesis_id": hyp_id,
                "validation_trades": len(after),
                "result": "inconclusive",
                "actual_improvement": "insufficient data",
                "statistical_significance": 0.0,
                "recommendation": "continue_testing",
            }

        # Compare win rates
        wr_before = (sum(1 for t in before if t.get("win")) / len(before)) if before else 0.5
        wr_after = sum(1 for t in after if t.get("win")) / len(after)
        wr_delta = wr_after - wr_before

        # Compare avg PnL
        pnl_before = (sum(t["pnl"] for t in before) / len(before)) if before else 0
        pnl_after = sum(t["pnl"] for t in after) / len(after)

        # Simple significance: binomial test approximation
        # Under null hypothesis WR = wr_before, how likely is wr_after?
        n = len(after)
        wins = sum(1 for t in after if t.get("win"))
        p0 = max(wr_before, 0.1)  # avoid division by zero
        # Z-score approximation
        expected = n * p0
        std = math.sqrt(n * p0 * (1 - p0)) if p0 < 1 else 1
        z_score = (wins - expected) / std if std > 0 else 0
        significance = min(abs(z_score) / 2.0, 1.0)  # Rough 0-1 scale

        if wr_delta > 0.05 and significance > 0.4:
            result = "confirmed"
            recommendation = "apply"
        elif wr_delta < -0.10:
            result = "rejected"
            recommendation = "reject"
        elif len(after) >= MIN_TRADES_FOR_VALIDATION * 2:
            # Enough data but no clear signal
            result = "inconclusive"
            recommendation = "reject"
        else:
            result = "inconclusive"
            recommendation = "continue_testing"

        return {
            "hypothesis_id": hyp_id,
            "validation_trades": n,
            "result": result,
            "wr_before": round(wr_before, 3),
            "wr_after": round(wr_after, 3),
            "wr_delta": round(wr_delta, 3),
            "pnl_before": round(pnl_before, 2),
            "pnl_after": round(pnl_after, 2),
            "statistical_significance": round(significance, 3),
            "recommendation": recommendation,
        }

    # ══════════════════════════════════════════════════════════
    # STEP 4: APPLY — Make the change
    # ══════════════════════════════════════════════════════════

    def apply_hypothesis(self, hypothesis: Dict) -> Dict:
        """Apply a validated hypothesis to the system."""
        change_type = hypothesis.get("change_type", "unknown")
        param = hypothesis.get("parameter", {})
        details = ""
        applied = False

        try:
            if change_type == "prompt_addition":
                applied = self._apply_prompt_injection(param)
                details = f"Injected rule into {param.get('target', '?')} agent"

            elif change_type == "parameter_change":
                applied = self._apply_parameter_change(param)
                details = f"Changed {param.get('target', '?')}"

            elif change_type == "weight_adjustment":
                applied = self._apply_weight_adjustment(param)
                details = f"Adjusted weight for {param.get('target', '?')}"

            elif change_type == "gate_modification":
                # Gate changes are advisory — store for overseer
                applied = True
                details = f"Flagged gate '{param.get('target')}' for threshold review"

            else:
                details = f"Investigation item stored: {hypothesis.get('hypothesis', '?')}"
                applied = True
        except Exception as e:
            logger.error("Failed to apply hypothesis %s: %s", hypothesis.get("id"), e)
            details = f"Error: {e}"

        result = {
            "applied": applied,
            "change_type": change_type,
            "details": details,
            "rollback_info": hypothesis.get("rollback_info", ""),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if applied:
            self.state["applied_changes"].append(result)
            self.state["applied_changes"] = self.state["applied_changes"][-30:]
        return result

    def _apply_prompt_injection(self, param: Dict) -> bool:
        """Inject a learned rule into an agent's prompt via network learning."""
        try:
            from llm.agents.network_learning import NetworkLearningLoop
            nll = NetworkLearningLoop()
            lesson = {
                "lesson": param.get("rule", ""),
                "category": "active_learning",
                "strength": "strong",
                "applies_to": {
                    "symbol": param.get("symbol", ""),
                    "side": param.get("side", ""),
                },
            }
            nll.process_lesson(lesson)
            return True
        except Exception as e:
            logger.warning("Prompt injection failed: %s", e)
            return False

    def _apply_parameter_change(self, param: Dict) -> bool:
        """Store parameter change recommendation (advisory, not direct mutation)."""
        # We store the recommendation; the overseer/operator decides to apply
        target = param.get("target", "")
        self.state.setdefault("parameter_recommendations", [])
        self.state["parameter_recommendations"].append({
            "target": target,
            "param": param,
            "ts": time.time(),
        })
        self.state["parameter_recommendations"] = self.state["parameter_recommendations"][-20:]
        return True

    def _apply_weight_adjustment(self, param: Dict) -> bool:
        """Store weight adjustment recommendation."""
        self.state.setdefault("weight_recommendations", [])
        self.state["weight_recommendations"].append({
            "target": param.get("target", ""),
            "multiplier": param.get("multiplier", 1.0),
            "ts": time.time(),
        })
        self.state["weight_recommendations"] = self.state["weight_recommendations"][-20:]
        return True

    # ══════════════════════════════════════════════════════════
    # STEP 5: MONITOR — Did it help?
    # ══════════════════════════════════════════════════════════

    def monitor_applied_changes(self, trade_outcomes: List[Dict]) -> List[Dict]:
        """Check if applied changes are working."""
        results = []
        for h in self.state["hypotheses"]:
            if h.get("status") not in ("applied", "monitoring"):
                continue

            h["status"] = "monitoring"
            applied_at = h.get("applied_at", "")
            pre = h.get("pre_metrics", {})
            pre_wr = pre.get("wr_10", 0.5)

            # Get trades since application
            post_trades = [t for t in trade_outcomes
                           if t.get("timestamp", "") > applied_at] if applied_at else []

            if len(post_trades) < MIN_TRADES_FOR_VALIDATION:
                results.append({
                    "hypothesis_id": h["id"],
                    "status": "monitoring",
                    "message": f"Waiting for data ({len(post_trades)}/{MIN_TRADES_FOR_VALIDATION})",
                    "alert": False,
                })
                continue

            post_wr = sum(1 for t in post_trades if t.get("win")) / len(post_trades)
            post_pnl = sum(t["pnl"] for t in post_trades) / len(post_trades)
            delta = post_wr - pre_wr

            if delta < -0.15:
                # Change is hurting — flag for rollback
                h["status"] = "rejected"
                results.append({
                    "hypothesis_id": h["id"],
                    "status": "rollback_needed",
                    "message": f"HURTING: WR dropped {pre_wr:.0%} -> {post_wr:.0%}",
                    "rollback_info": h.get("rollback_info", ""),
                    "alert": True,
                })
            elif delta > 0.05:
                h["status"] = "retired"  # Success — graduated
                results.append({
                    "hypothesis_id": h["id"],
                    "status": "confirmed_helpful",
                    "message": f"HELPING: WR {pre_wr:.0%} -> {post_wr:.0%}",
                    "alert": False,
                })
            else:
                results.append({
                    "hypothesis_id": h["id"],
                    "status": "neutral",
                    "message": f"Neutral: WR {pre_wr:.0%} -> {post_wr:.0%} ({len(post_trades)} trades)",
                    "alert": False,
                })
                # If enough trades and still neutral, retire
                if len(post_trades) >= MONITORING_WINDOW_TRADES:
                    h["status"] = "retired"

        return results

    # ══════════════════════════════════════════════════════════
    # MAIN CYCLE
    # ══════════════════════════════════════════════════════════

    def run_cycle(self, recent_trades: List[Dict] = None, agent_stats: Dict = None,
                  feedback_states: Dict = None, rejection_stats: Dict = None) -> Dict:
        """Run one complete learning cycle."""
        self.last_cycle_time = time.time()
        self.state["cycle_count"] = self.state.get("cycle_count", 0) + 1

        if not recent_trades:
            recent_trades = self._load_trades()

        # Step 1: Diagnose
        diagnosis = self.diagnose(recent_trades, agent_stats or {}, feedback_states or {}, rejection_stats or {})

        # Step 2: Generate hypotheses (only if weaknesses found)
        new_hypotheses = []
        if diagnosis.get("weaknesses"):
            new_hypotheses = self.generate_hypotheses(diagnosis)
            for h in new_hypotheses:
                self.state["hypotheses"].append(h)

        # Step 3: Promote proposed -> testing, validate testing hypotheses
        validations = []
        for h in self.state["hypotheses"]:
            if h["status"] == "proposed":
                h["status"] = "testing"
                h["testing_started_at"] = datetime.now(timezone.utc).isoformat()
            elif h["status"] == "testing":
                v = self.validate_hypothesis(h, recent_trades)
                validations.append(v)
                if v["recommendation"] == "apply":
                    h["status"] = "validated"
                elif v["recommendation"] == "reject":
                    h["status"] = "rejected"

        # Step 4: Apply validated hypotheses
        applications = []
        for h in self.state["hypotheses"]:
            if h["status"] == "validated":
                result = self.apply_hypothesis(h)
                applications.append(result)
                if result["applied"]:
                    h["status"] = "applied"
                    h["applied_at"] = datetime.now(timezone.utc).isoformat()

        # Step 5: Monitor applied changes
        monitoring = self.monitor_applied_changes(recent_trades)

        self._save_state()

        summary = {
            "cycle": self.state["cycle_count"],
            "diagnosis_health": diagnosis.get("overall_health", "unknown"),
            "weaknesses_found": len(diagnosis.get("weaknesses", [])),
            "new_hypotheses": len(new_hypotheses),
            "validations": len(validations),
            "applications": len(applications),
            "monitoring_alerts": [m for m in monitoring if m.get("alert")],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        logger.info("[ACTIVE-LEARN] Cycle %d: health=%s, +%d hyp, %d validated, %d applied",
                     summary["cycle"], summary["diagnosis_health"],
                     summary["new_hypotheses"], summary["validations"], summary["applications"])
        return summary

    def should_run(self) -> bool:
        """Check if enough time has passed for a periodic cycle."""
        return (time.time() - self.last_cycle_time) >= self.cycle_interval

    # ══════════════════════════════════════════════════════════
    # FORMATTING FOR OTHER AGENTS
    # ══════════════════════════════════════════════════════════

    def format_for_overseer(self) -> str:
        """Format learning state for Overseer agent."""
        lines = ["ACTIVE LEARNING:"]

        # Latest diagnosis
        history = self.state.get("diagnosis_history", [])
        if history:
            last = history[-1]
            lines.append(f"  Health: {last.get('overall_health', '?').upper()}"
                         f" (WR10={last.get('metrics', {}).get('wr_last_10', '?')})")
            if last.get("weaknesses"):
                lines.append(f"  Weaknesses: {', '.join(last['weaknesses'][:3])}")
            if last.get("strengths"):
                lines.append(f"  Strengths: {', '.join(last['strengths'][:3])}")

        # Hypothesis summary
        hyps = self.state.get("hypotheses", [])
        by_status = defaultdict(int)
        for h in hyps:
            by_status[h.get("status", "?")] += 1
        if by_status:
            parts = [f"{count} {status}" for status, count in by_status.items()]
            lines.append(f"  Hypotheses: {', '.join(parts)}")

        # Applied changes status
        applied = [h for h in hyps if h.get("status") in ("applied", "monitoring")]
        for h in applied[:3]:
            lines.append(f"  Applied: {h.get('hypothesis', '?')[:60]} [{h['status']}]")

        # Monitoring alerts
        alerts = [h for h in hyps if h.get("status") == "rejected"
                  and h.get("applied_at")]  # Was applied then rejected = rollback needed
        for h in alerts[:2]:
            lines.append(f"  ROLLBACK: {h.get('hypothesis', '?')[:50]} — "
                         f"{h.get('rollback_info', '?')}")

        return "\n".join(lines) if len(lines) > 1 else "ACTIVE LEARNING: No data yet"

    def format_for_agents(self) -> str:
        """Format current learning insights for all agents."""
        lines = ["SYSTEM INSIGHTS (active learning):"]

        # Collect confirmed-helpful insights
        helpful = [h for h in self.state.get("hypotheses", [])
                   if h.get("status") == "retired" and h.get("applied_at")]
        for h in helpful[-5:]:
            lines.append(f"  * {h.get('hypothesis', '?')[:80]} [CONFIRMED]")

        # Current applied experiments
        active = [h for h in self.state.get("hypotheses", [])
                  if h.get("status") in ("applied", "monitoring")]
        for h in active[:3]:
            lines.append(f"  * TESTING: {h.get('hypothesis', '?')[:70]}")

        # Latest diagnosis highlights
        history = self.state.get("diagnosis_history", [])
        if history:
            last = history[-1]
            metrics = last.get("metrics", {})
            if metrics.get("best_regime"):
                best_r = metrics["best_regime"]
                r_perf = metrics.get("regime_performance", {}).get(best_r, {})
                lines.append(f"  * Best regime: {best_r} ({r_perf.get('wr', '?')} WR)")
            if metrics.get("worst_regime"):
                worst_r = metrics["worst_regime"]
                r_perf = metrics.get("regime_performance", {}).get(worst_r, {})
                lines.append(f"  * Worst regime: {worst_r} ({r_perf.get('wr', '?')} WR) — caution")
            if metrics.get("best_symbol"):
                lines.append(f"  * Best symbol: {metrics['best_symbol']}")
            if metrics.get("worst_symbol"):
                lines.append(f"  * Worst symbol: {metrics['worst_symbol']} — reduce exposure")

        return "\n".join(lines) if len(lines) > 1 else "SYSTEM INSIGHTS: Collecting data..."

    def get_status_summary(self) -> Dict:
        """Get a structured summary for dashboards/APIs."""
        hyps = self.state.get("hypotheses", [])
        return {
            "cycle_count": self.state.get("cycle_count", 0),
            "total_hypotheses": len(hyps),
            "by_status": dict(defaultdict(int, {
                s: sum(1 for h in hyps if h.get("status") == s)
                for s in VALID_STATUSES
            })),
            "last_diagnosis": (self.state["diagnosis_history"][-1]
                               if self.state.get("diagnosis_history") else None),
            "applied_changes": len(self.state.get("applied_changes", [])),
            "last_cycle": self.last_cycle_time,
        }


# ── Module-level singleton ──────────────────────────────────

_instance: Optional[ActiveLearningEngine] = None


def get_active_learning_engine() -> ActiveLearningEngine:
    """Get or create the singleton ActiveLearningEngine."""
    global _instance
    if _instance is None:
        _instance = ActiveLearningEngine()
    return _instance
