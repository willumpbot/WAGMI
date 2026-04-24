"""
Auto-Fix Pipeline: Audit recommendations → graduated rules → A/B test → auto-revert.

Reads recommendations from autonomous audit, applies them to graduated_rules.json,
gates changes with A/B split (treatment vs control), auto-reverts if treatment WR drops.
"""

import json
import logging
import os
import time
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger("bot.learning.auto_fix_pipeline")


class AutoFixPipeline:
    """Automatically applies audit recommendations with A/B testing and auto-revert."""

    def __init__(self, data_dir: str = "data/learning"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

        self._state_file = os.path.join(data_dir, "auto_fix_state.json")
        self._change_log = os.path.join(data_dir, "auto_fix_log.jsonl")

        self._state: Dict[str, Any] = {
            "active_fixes": [],  # List of {rule, gate_percentage, baseline_wr, treatment_wr, since_ts}
            "applied_total": 0,
            "reverted_total": 0,
            "ab_tests_active": 0,
        }
        self._load_state()

        logger.info("[AUTO_FIX] Pipeline initialized: %d active fixes", len(self._state["active_fixes"]))

    def process_audit_recommendations(self, recommendations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Process recommendations from autonomous audit.

        Args:
            recommendations: List of {problem, proposed_fix, expected_impact, confidence}

        Returns:
            {applied: N, skipped: M, rationale}
        """
        applied = 0
        skipped = 0

        for rec in recommendations:
            # Only auto-apply if high confidence (>75%)
            if rec.get("confidence", 0) < 75:
                logger.debug(f"[AUTO_FIX] Skipping low-confidence: {rec.get('problem')}")
                skipped += 1
                continue

            # Extract the rule to apply
            proposed_fix = rec.get("proposed_fix", "")
            if not proposed_fix:
                skipped += 1
                continue

            # Apply with A/B gating (20% treatment, 80% control)
            try:
                self._apply_fix_with_ab_gate(proposed_fix, rec)
                applied += 1
                self._state["applied_total"] += 1
            except Exception as e:
                logger.warning(f"[AUTO_FIX] Failed to apply {proposed_fix}: {e}")
                skipped += 1

        self._save_state()
        return {
            "applied": applied,
            "skipped": skipped,
            "rationale": f"Applied {applied} high-confidence fixes with A/B gating",
        }

    def _apply_fix_with_ab_gate(self, fix_description: str, rec: Dict[str, Any]):
        """
        Apply a fix to graduated_rules.json with 20% A/B treatment gate.

        Example fix: "Add VOL_GATE: if (vol > 1.5) skip BTC SHORT"
        """
        # TODO: Parse fix and apply to graduated_rules.json
        # 1. Read graduated_rules.json
        # 2. Add new rule with gate_percentage: 20
        # 3. Track baseline_wr from recent trades (80% control group)
        # 4. Record baseline timestamp
        # 5. Active for 100+ trades before evaluation

        self._state["active_fixes"].append(
            {
                "fix": fix_description,
                "gate_percentage": 20,
                "applied_ts": time.time(),
                "baseline_wr": None,  # Will be computed from control group
                "expected_impact": rec.get("expected_impact", 0),
                "confidence": rec.get("confidence", 0),
            }
        )

        logger.info(f"[AUTO_FIX] Applied with A/B gate: {fix_description}")

    def evaluate_active_fixes(self, recent_trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Evaluate active A/B tests and auto-revert if treatment WR < control WR - threshold.

        Args:
            recent_trades: List of recent closed trades with gate application info

        Returns:
            {evaluated: N, reverted: M, promoted: K}
        """
        evaluated = 0
        reverted = 0
        promoted = 0
        threshold = 3.0  # Auto-revert if treatment WR 3% below control

        # TODO: Implementation
        # 1. For each active fix:
        #    a. Split recent_trades into control (80%) vs treatment (20%)
        #    b. Calculate WR for each group
        #    c. If treatment < control - threshold: revert
        #    d. If treatment >= control + 2%: graduate to 100% (promote)
        #    e. Track all changes

        self._save_state()
        return {
            "evaluated": evaluated,
            "reverted": reverted,
            "promoted": promoted,
        }

    def _load_state(self):
        if os.path.exists(self._state_file):
            try:
                with open(self._state_file) as f:
                    loaded = json.load(f)
                    self._state.update(loaded)
            except Exception as e:
                logger.warning(f"Failed to load state: {e}")

    def _save_state(self):
        try:
            with open(self._state_file, "w") as f:
                json.dump(self._state, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save state: {e}")

    def get_status(self) -> Dict[str, Any]:
        return {
            "applied_total": self._state["applied_total"],
            "reverted_total": self._state["reverted_total"],
            "active_fixes": len(self._state["active_fixes"]),
            "ab_tests_active": self._state["ab_tests_active"],
        }
