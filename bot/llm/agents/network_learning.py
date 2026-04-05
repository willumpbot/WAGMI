"""
Network Learning: Translates Learning Agent insights into actionable
improvements for other agents in the network.

Feedback channels:
1. Prompt injections — lessons injected into each agent's context
2. Confidence calibration — systematic over/under-confidence correction
3. Regime patterns — regime transition intelligence for Regime/Scout
4. Risk constraints — hard rules from repeated failures for Risk Agent
5. Edge decay detection — alerts for the Overseer when edges disappear

Persisted to data/llm/network_learning.json between restarts.
"""

import json
import logging
import os
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bot.llm.agents.network_learning")

DATA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "llm", "network_learning.json"
)
MAX_LESSONS = 200
MAX_INJECTIONS_PER_AGENT = 10
MAX_RISK_CONSTRAINTS = 20


class NetworkLearningLoop:
    """Routes Learning Agent outputs to improve future agent decisions."""

    def __init__(self, path: str = DATA_PATH):
        self._path = path
        self._state: Dict[str, Any] = {}
        self._loaded = False

    # ── Persistence ──────────────────────────────────────────

    def _ensure_loaded(self):
        if self._loaded:
            return
        self._loaded = True
        try:
            if os.path.exists(self._path):
                with open(self._path, "r") as f:
                    self._state = json.load(f)
        except Exception as e:
            logger.warning(f"[NET-LEARN] Load failed: {e}")
            self._state = {}
        # Ensure structure
        self._state.setdefault("lessons", [])
        self._state.setdefault("prompt_injections", {})
        self._state.setdefault("calibration", {"predicted": [], "actual": []})
        self._state.setdefault("risk_constraints", [])
        self._state.setdefault("regime_patterns", [])
        self._state.setdefault("edge_tracking", {})
        self._state.setdefault("stats", {"total_processed": 0, "last_updated": 0})

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w") as f:
                json.dump(self._state, f, indent=2, default=str)
        except Exception as e:
            logger.warning(f"[NET-LEARN] Save failed: {e}")

    # ── Main Entry Point ─────────────────────────────────────

    def process_lesson(self, lesson: Dict[str, Any], trade_data: Dict[str, Any] = None):
        """Process a Learning Agent output and route to the right agents.

        Args:
            lesson: Parsed Learning Agent output (lesson, category, strength,
                    applies_to, hypothesis, thesis_correct, etc.)
            trade_data: The closed trade that triggered this lesson.
        """
        self._ensure_loaded()
        trade_data = trade_data or {}

        lesson_text = lesson.get("lesson", "")
        category = lesson.get("category", "")
        strength = lesson.get("strength", "weak")
        applies_to = lesson.get("applies_to", {}) or {}
        symbol = applies_to.get("symbol") or trade_data.get("symbol", "")
        regime = applies_to.get("regime") or trade_data.get("regime", "")
        side = applies_to.get("side") or trade_data.get("side", "")
        outcome = trade_data.get("outcome", "")
        leverage = trade_data.get("leverage", 0)
        confidence = trade_data.get("confidence", 0)

        if not lesson_text:
            return

        # Store the lesson
        entry = {
            "ts": time.time(),
            "lesson": lesson_text[:300],
            "category": category,
            "strength": strength,
            "symbol": symbol,
            "regime": regime,
            "side": side,
            "outcome": outcome,
        }
        self._state["lessons"].append(entry)
        self._state["lessons"] = self._state["lessons"][-MAX_LESSONS:]
        self._state["stats"]["total_processed"] += 1
        self._state["stats"]["last_updated"] = time.time()

        # Route to channels based on category and strength
        self._route_prompt_injection(lesson_text, category, strength, symbol,
                                     regime, side, outcome, trade_data)
        self._route_calibration(lesson, trade_data)
        self._route_regime_pattern(lesson_text, category, regime, trade_data)
        self._route_risk_constraint(lesson_text, category, strength,
                                    symbol, leverage, outcome)
        self._track_edge(symbol, side, regime, outcome, trade_data)

        self._save()
        logger.info(f"[NET-LEARN] Processed: [{category}] {lesson_text[:60]}...")

    # ── Channel 1: Prompt Injections ─────────────────────────

    def _route_prompt_injection(self, lesson: str, category: str, strength: str,
                                symbol: str, regime: str, side: str, outcome: str,
                                trade_data: Dict):
        """Convert strong lessons into prompt injections for relevant agents."""
        if strength not in ("strong", "critical"):
            return

        injections = self._state["prompt_injections"]

        # Pattern losses / regime mismatches -> Trade Agent
        if category in ("pattern_loss", "regime_mismatch", "setup_failure"):
            agent = "trade"
            rule = f"{symbol} {side} in {regime} regime: {outcome}. {lesson[:120]}"
            injections.setdefault(agent, [])
            injections[agent].append({"rule": rule, "ts": time.time()})
            injections[agent] = injections[agent][-MAX_INJECTIONS_PER_AGENT:]

        # Risk failures -> Risk Agent
        if category in ("overleveraged", "sizing_error", "funding_cost"):
            agent = "risk"
            rule = lesson[:150]
            injections.setdefault(agent, [])
            injections[agent].append({"rule": rule, "ts": time.time()})
            injections[agent] = injections[agent][-MAX_INJECTIONS_PER_AGENT:]

        # Regime lessons -> Regime Agent
        if category in ("regime_mismatch", "regime_transition"):
            agent = "regime"
            rule = lesson[:150]
            injections.setdefault(agent, [])
            injections[agent].append({"rule": rule, "ts": time.time()})
            injections[agent] = injections[agent][-MAX_INJECTIONS_PER_AGENT:]

        # All strong lessons -> Critic Agent (for better veto decisions)
        agent = "critic"
        rule = f"[{category}] {lesson[:120]}"
        injections.setdefault(agent, [])
        injections[agent].append({"rule": rule, "ts": time.time()})
        injections[agent] = injections[agent][-MAX_INJECTIONS_PER_AGENT:]

    # ── Channel 2: Confidence Calibration ────────────────────

    def _route_calibration(self, lesson: Dict, trade_data: Dict):
        """Track predicted vs actual confidence for calibration adjustment."""
        thesis_correct = lesson.get("thesis_correct")
        predicted_conf = trade_data.get("confidence", 0)
        if thesis_correct is None or not predicted_conf:
            return

        cal = self._state["calibration"]
        cal["predicted"].append(float(predicted_conf))
        cal["actual"].append(1.0 if thesis_correct else 0.0)
        # Keep last 100 data points
        cal["predicted"] = cal["predicted"][-100:]
        cal["actual"] = cal["actual"][-100:]

    def get_calibration_adjustment(self) -> float:
        """Return confidence adjustment based on calibration tracking.

        Positive = we're underconfident (raise confidence).
        Negative = we're overconfident (lower confidence).
        Returns 0.0 if insufficient data.
        """
        self._ensure_loaded()
        cal = self._state.get("calibration", {})
        predicted = cal.get("predicted", [])
        actual = cal.get("actual", [])

        if len(predicted) < 10:
            return 0.0

        avg_predicted = sum(predicted) / len(predicted)
        avg_actual = sum(actual) / len(actual)
        # Scale: predicted is 0-100, actual is 0-1
        avg_predicted_norm = avg_predicted / 100.0 if avg_predicted > 1 else avg_predicted
        gap = avg_actual - avg_predicted_norm
        # Cap adjustment to +/- 15%
        return max(-0.15, min(0.15, gap))

    # ── Channel 3: Regime Patterns ───────────────────────────

    def _route_regime_pattern(self, lesson: str, category: str, regime: str,
                              trade_data: Dict):
        """Capture regime transition and performance patterns."""
        if category not in ("regime_mismatch", "regime_transition", "timing"):
            return

        patterns = self._state["regime_patterns"]
        patterns.append({
            "ts": time.time(),
            "regime": regime,
            "lesson": lesson[:200],
            "outcome": trade_data.get("outcome", ""),
        })
        self._state["regime_patterns"] = patterns[-50:]

    # ── Channel 4: Risk Constraints ──────────────────────────

    def _route_risk_constraint(self, lesson: str, category: str, strength: str,
                               symbol: str, leverage: float, outcome: str):
        """Generate hard risk constraints from repeated failures."""
        if outcome != "LOSS" or strength not in ("strong", "critical"):
            return

        constraints = self._state["risk_constraints"]

        # High leverage losses -> cap
        if leverage and leverage >= 10 and category in ("overleveraged", "sizing_error"):
            rule = f"Max {int(leverage * 0.6)}x leverage on {symbol or 'all'}"
            if not any(r["rule"] == rule for r in constraints):
                constraints.append({"rule": rule, "ts": time.time(), "source": lesson[:80]})

        # Regime-specific losses
        if category == "regime_mismatch":
            rule = lesson[:150]
            if not any(rule in r["rule"] for r in constraints):
                constraints.append({"rule": rule, "ts": time.time(), "source": "regime_loss"})

        self._state["risk_constraints"] = constraints[-MAX_RISK_CONSTRAINTS:]

    # ── Channel 5: Edge Decay Detection ──────────────────────

    def _track_edge(self, symbol: str, side: str, regime: str, outcome: str,
                    trade_data: Dict):
        """Track win rates per setup to detect edge decay."""
        if not symbol or not outcome:
            return

        edges = self._state["edge_tracking"]
        key = f"{symbol}_{side}_{regime}"
        if key not in edges:
            edges[key] = {"wins": 0, "total": 0, "recent_wins": 0, "recent_total": 0}

        e = edges[key]
        win = 1 if outcome == "WIN" else 0
        e["wins"] += win
        e["total"] += 1
        # Recent = last 10 trades (sliding window approximation)
        e["recent_wins"] = int(e["recent_wins"] * 0.9 + win)
        e["recent_total"] = int(e["recent_total"] * 0.9 + 1)

    def get_decaying_edges(self) -> List[Dict]:
        """Find setups where edge is disappearing."""
        self._ensure_loaded()
        decaying = []
        for key, e in self._state.get("edge_tracking", {}).items():
            if e["total"] < 8:
                continue
            overall_wr = e["wins"] / max(1, e["total"])
            recent_wr = e["recent_wins"] / max(1, e["recent_total"])
            if overall_wr >= 0.55 and recent_wr < 0.40:
                decaying.append({
                    "setup": key,
                    "overall_wr": round(overall_wr, 2),
                    "recent_wr": round(recent_wr, 2),
                    "total_trades": e["total"],
                })
        return decaying

    # ── Agent Interface Methods ──────────────────────────────

    def get_prompt_injection(self, agent_name: str) -> str:
        """Get accumulated lessons for a specific agent's prompt context.

        Returns a compact string to inject into the agent's input data.
        """
        self._ensure_loaded()
        injections = self._state.get("prompt_injections", {}).get(agent_name, [])
        if not injections:
            return ""

        # Sort by recency, take most recent
        recent = sorted(injections, key=lambda x: x.get("ts", 0), reverse=True)[:7]
        lines = [f"- {r['rule']}" for r in recent]
        return "LESSONS LEARNED (from past trades):\n" + "\n".join(lines)

    def get_risk_constraints(self) -> List[str]:
        """Return hard rules from Learning Agent for Risk Agent."""
        self._ensure_loaded()
        constraints = self._state.get("risk_constraints", [])
        # Return most recent, deduplicated
        seen = set()
        result = []
        for c in reversed(constraints):
            rule = c["rule"]
            if rule not in seen:
                seen.add(rule)
                result.append(rule)
        return result[:10]

    def get_regime_intelligence(self) -> str:
        """Regime patterns for Regime and Scout agents."""
        self._ensure_loaded()
        patterns = self._state.get("regime_patterns", [])
        if not patterns:
            return ""
        recent = patterns[-5:]
        lines = [f"- [{p['regime']}] {p['lesson'][:100]}" for p in recent]
        return "REGIME LESSONS:\n" + "\n".join(lines)

    def format_for_overseer(self) -> str:
        """Summary of all network learning for Overseer review."""
        self._ensure_loaded()
        parts = []
        stats = self._state.get("stats", {})
        parts.append(f"Lessons processed: {stats.get('total_processed', 0)}")

        # Calibration
        adj = self.get_calibration_adjustment()
        if adj != 0:
            direction = "overconfident" if adj < 0 else "underconfident"
            parts.append(f"Calibration: {direction} by {abs(adj):.1%}")

        # Risk constraints
        constraints = self.get_risk_constraints()
        if constraints:
            parts.append(f"Active risk constraints ({len(constraints)}): " +
                         "; ".join(constraints[:3]))

        # Edge decay
        decaying = self.get_decaying_edges()
        if decaying:
            decay_strs = [f"{d['setup']} ({d['overall_wr']:.0%}->{d['recent_wr']:.0%})"
                          for d in decaying]
            parts.append(f"EDGE DECAY ALERT: {', '.join(decay_strs)}")

        # Injection counts
        inj = self._state.get("prompt_injections", {})
        if inj:
            counts = {k: len(v) for k, v in inj.items() if v}
            if counts:
                parts.append(f"Prompt injections: {counts}")

        return "NETWORK LEARNING:\n" + "\n".join(parts) if parts else ""


# ── Singleton ────────────────────────────────────────────

_instance: Optional[NetworkLearningLoop] = None


def get_network_learning() -> NetworkLearningLoop:
    global _instance
    if _instance is None:
        _instance = NetworkLearningLoop()
    return _instance
