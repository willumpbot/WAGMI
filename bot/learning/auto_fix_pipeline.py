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
            recent_trades: List of recent closed trades with gate application info.
                           Each trade should have 'ab_gate_hash' (int 0-99) and 'win' (bool).

        Returns:
            {evaluated: N, reverted: M, promoted: K}
        """
        evaluated = 0
        reverted = 0
        promoted = 0
        revert_threshold = 3.0   # Revert if treatment WR 3pp below control
        promote_threshold = 2.0  # Promote if treatment WR 2pp above control
        min_trades_per_group = 20  # Minimum trades before evaluation

        if not recent_trades:
            self._save_state()
            return {"evaluated": 0, "reverted": 0, "promoted": 0, "skip_reason": "no_trades"}

        # Also sync with graduated_rules.json A/B_ACTIVE rules
        graduated_path = os.path.join(os.path.dirname(self.data_dir), "feedback", "graduated_rules.json")
        graduated_rules = []
        try:
            with open(graduated_path) as f:
                gd = json.load(f)
                graduated_rules = gd.get("rules", [])
        except Exception:
            pass

        active_in_graduated = [r for r in graduated_rules if r.get("status") == "A/B_ACTIVE"]

        fixes_to_evaluate = list(self._state["active_fixes"])
        # Add graduated A/B_ACTIVE rules not already tracked
        tracked_fixes = {f.get("fix") for f in fixes_to_evaluate}
        for gr in active_in_graduated:
            if gr["rule_id"] not in tracked_fixes:
                fixes_to_evaluate.append({
                    "fix": gr["rule_id"],
                    "gate_percentage": gr.get("gate_percentage", 20),
                    "applied_ts": 0,
                    "baseline_wr": gr.get("baseline_wr"),
                    "expected_impact": 0,
                    "confidence": gr.get("confidence", 0),
                    "_graduated_rule": True,
                })

        updated_fixes = []
        graduated_updates = {}

        for fix in fixes_to_evaluate:
            gate_pct = fix.get("gate_percentage", 20)
            fix_id = fix.get("fix", "unknown")

            # Split trades: treatment = ab_gate_hash < gate_pct, control = rest
            treatment = [t for t in recent_trades if t.get("ab_gate_hash", 100) < gate_pct]
            control = [t for t in recent_trades if t.get("ab_gate_hash", 100) >= gate_pct]

            if len(treatment) < min_trades_per_group or len(control) < min_trades_per_group:
                logger.debug(f"[AUTO_FIX] {fix_id}: insufficient data (treatment={len(treatment)}, control={len(control)})")
                updated_fixes.append(fix)
                continue

            evaluated += 1
            treatment_wr = sum(1 for t in treatment if t.get("win")) / len(treatment)
            control_wr = sum(1 for t in control if t.get("win")) / len(control)
            wr_delta = (treatment_wr - control_wr) * 100

            fix["treatment_wr"] = round(treatment_wr, 4)
            fix["control_wr"] = round(control_wr, 4)
            fix["last_evaluated_ts"] = time.time()
            fix["sample_sizes"] = {"treatment": len(treatment), "control": len(control)}

            if fix.get("_graduated_rule"):
                graduated_updates[fix_id] = {
                    "treatment_wr": round(treatment_wr, 4),
                    "baseline_wr": fix.get("baseline_wr") or round(control_wr, 4),
                }

            if wr_delta < -revert_threshold:
                fix["status"] = "REVERTED"
                reverted += 1
                self._state["reverted_total"] += 1
                logger.warning(
                    f"[AUTO_FIX] REVERT {fix_id}: treatment_wr={treatment_wr:.1%} "
                    f"control_wr={control_wr:.1%} delta={wr_delta:+.1f}pp"
                )
                if fix.get("_graduated_rule"):
                    graduated_updates[fix_id]["status"] = "REVERTED"
            elif wr_delta >= promote_threshold:
                fix["status"] = "PROMOTED"
                fix["gate_percentage"] = 100
                promoted += 1
                logger.info(
                    f"[AUTO_FIX] PROMOTE {fix_id}: treatment_wr={treatment_wr:.1%} "
                    f"control_wr={control_wr:.1%} delta={wr_delta:+.1f}pp → 100% gate"
                )
                if fix.get("_graduated_rule"):
                    graduated_updates[fix_id]["status"] = "PROMOTED"
                    graduated_updates[fix_id]["gate_percentage"] = 100
            else:
                logger.info(
                    f"[AUTO_FIX] HOLD {fix_id}: treatment_wr={treatment_wr:.1%} "
                    f"control_wr={control_wr:.1%} delta={wr_delta:+.1f}pp (within ±{revert_threshold}pp)"
                )
                updated_fixes.append(fix)
                continue

            if fix.get("status") not in ("REVERTED",):
                updated_fixes.append(fix)

        self._state["active_fixes"] = updated_fixes
        self._state["ab_tests_active"] = len([f for f in updated_fixes if f.get("status") not in ("REVERTED", "PROMOTED")])

        # Write treatment_wr updates back to graduated_rules.json
        if graduated_updates:
            try:
                with open(graduated_path) as f:
                    gd = json.load(f)
                for rule in gd.get("rules", []):
                    rid = rule["rule_id"]
                    if rid in graduated_updates:
                        rule.update(graduated_updates[rid])
                gd["last_updated"] = datetime.utcnow().isoformat() + "Z"
                with open(graduated_path, "w") as f:
                    json.dump(gd, f, indent=2)
                logger.info(f"[AUTO_FIX] Updated {len(graduated_updates)} graduated rules with treatment_wr")
            except Exception as e:
                logger.warning(f"[AUTO_FIX] Failed to update graduated_rules.json: {e}")

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
