"""
Growth Report — Periodic comprehensive learning & intelligence reports.

Generates structured reports combining data from ALL growth subsystems:
- Recommendation engine outcomes
- Hypothesis lifecycle progress
- Parameter change audit trail
- Veto accuracy tracking
- Self-improvement proposal outcomes
- Knowledge base growth

Reports are:
1. Injected into the LLM prompt (compact version) for self-awareness
2. Sent to Telegram (detailed version) for user visibility
3. Persisted to disk for historical analysis

Usage:
    reporter = get_growth_reporter()
    report = reporter.generate_report()
    telegram_msg = reporter.format_telegram()
    llm_context = reporter.format_for_llm_prompt()
"""

import json
import logging
import os
import time
from typing import Dict, Any, Optional

logger = logging.getLogger("bot.llm.growth.report")

_DATA_DIR = os.path.join("data", "llm", "growth")
_REPORTS_FILE = "growth_reports.json"


def _ensure_dir():
    os.makedirs(_DATA_DIR, exist_ok=True)


class GrowthReporter:
    """Generates comprehensive growth intelligence reports."""

    def __init__(self, data_dir: str = None):
        self._data_dir = data_dir or _DATA_DIR
        self._reports: list = []
        self._last_report_time: float = 0
        self._report_interval_s: float = 3600  # 1 hour between reports
        self._loaded = False

    def _ensure_loaded(self):
        if self._loaded:
            return
        self._loaded = True
        _ensure_dir()
        path = os.path.join(self._data_dir, _REPORTS_FILE)
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = json.load(f)
                self._reports = data.get("reports", [])[-50:]
                self._last_report_time = data.get("last_report_time", 0)
            except (json.JSONDecodeError, IOError):
                pass

    def _save(self):
        _ensure_dir()
        path = os.path.join(self._data_dir, _REPORTS_FILE)
        try:
            with open(path, "w") as f:
                json.dump({
                    "reports": self._reports[-50:],
                    "last_report_time": self._last_report_time,
                }, f, indent=2, default=str)
        except IOError as e:
            logger.warning(f"[GROWTH-REPORT] Failed to save: {e}")

    def should_generate(self) -> bool:
        """Check if it's time for a new report."""
        self._ensure_loaded()
        return (time.time() - self._last_report_time) >= self._report_interval_s

    def generate_report(self) -> Dict[str, Any]:
        """Generate a comprehensive growth intelligence report.

        Safely imports and queries each subsystem — any subsystem failure
        is isolated and doesn't crash the report.
        """
        self._ensure_loaded()
        report = {
            "timestamp": time.time(),
            "sections": {},
        }

        # Recommendation engine
        try:
            from llm.growth.recommendation_engine import get_recommendation_engine
            rec_engine = get_recommendation_engine()
            rec_stats = rec_engine.get_stats()
            pending = rec_engine.get_pending(limit=5)
            report["sections"]["recommendations"] = {
                "stats": rec_stats,
                "pending_count": len(pending),
                "top_pending": [
                    {"title": r.title, "confidence": r.confidence, "source": r.source}
                    for r in pending[:3]
                ],
            }
        except Exception as e:
            report["sections"]["recommendations"] = {"error": str(e)}

        # Hypothesis tracker
        try:
            from llm.growth.hypothesis_tracker import get_hypothesis_tracker
            tracker = get_hypothesis_tracker()
            hypo_stats = tracker.get_stats()
            active = tracker.get_active()
            graduated = tracker.check_graduation()
            report["sections"]["hypotheses"] = {
                "stats": hypo_stats,
                "active_count": len(active),
                "newly_graduated": [
                    {"statement": h.statement[:80], "stage": h.stage}
                    for h in graduated
                ],
            }
        except Exception as e:
            report["sections"]["hypotheses"] = {"error": str(e)}

        # Explainability (parameter changes)
        try:
            from llm.growth.explainability import get_explainer
            explainer = get_explainer()
            recent_changes = explainer.get_recent_changes(limit=5)
            effectiveness = explainer.get_change_effectiveness()
            report["sections"]["parameter_changes"] = {
                "recent_count": len(recent_changes),
                "effectiveness": effectiveness,
                "recent": [
                    {
                        "parameter": c.parameter,
                        "change": f"{c.old_value} -> {c.new_value}",
                        "impact": c.impact_was_positive,
                    }
                    for c in recent_changes[:5]
                ],
            }
        except Exception as e:
            report["sections"]["parameter_changes"] = {"error": str(e)}

        # Veto feedback
        try:
            from llm.growth.veto_feedback import get_veto_tracker
            veto_tracker = get_veto_tracker()
            veto_stats = veto_tracker.get_stats()
            report["sections"]["veto_feedback"] = {
                "accuracy": veto_stats.get("accuracy", 0),
                "total_vetoes": veto_stats.get("total_vetoes", 0),
                "resolved": veto_stats.get("resolved", 0),
                "pnl_saved": veto_stats.get("total_pnl_saved", 0),
            }
        except Exception as e:
            report["sections"]["veto_feedback"] = {"error": str(e)}

        # Self-improvement
        try:
            from llm.growth.self_improvement import get_self_improvement_engine
            imp_engine = get_self_improvement_engine()
            imp_stats = imp_engine.get_stats()
            report["sections"]["self_improvement"] = {
                "stats": imp_stats,
                "auto_applicable": len(imp_engine.get_auto_applicable()),
                "pending_review": len(imp_engine.get_pending_review()),
            }
        except Exception as e:
            report["sections"]["self_improvement"] = {"error": str(e)}

        # Self-teaching (curriculum)
        try:
            from llm.self_teaching import get_teaching_engine
            teaching = get_teaching_engine()
            curriculum = teaching.get_curriculum_report()
            knowledge = teaching.knowledge.get_stats()
            report["sections"]["curriculum"] = {
                "level": curriculum["curriculum"]["level"],
                "level_name": curriculum["curriculum"]["level_name"],
                "hours_at_level": curriculum["curriculum"]["hours_at_level"],
                "total_hours": curriculum["curriculum"]["total_hours"],
                "trades_analyzed": curriculum["curriculum"]["trades_analyzed"],
                "knowledge_entries": knowledge["total_entries"],
                "knowledge_by_type": knowledge["by_type"],
            }
        except Exception as e:
            report["sections"]["curriculum"] = {"error": str(e)}

        # Store report
        self._reports.append(report)
        self._last_report_time = time.time()
        self._save()

        logger.info(
            f"[GROWTH-REPORT] Generated report with "
            f"{len(report['sections'])} sections"
        )
        return report

    def format_telegram(self) -> str:
        """Format the latest report for Telegram."""
        self._ensure_loaded()
        if not self._reports:
            return "No growth reports generated yet."

        report = self._reports[-1]
        sections = report.get("sections", {})
        lines = ["*Growth Intelligence Report*\n"]

        # Curriculum
        curr = sections.get("curriculum", {})
        if "error" not in curr:
            level = curr.get("level", 1)
            name = curr.get("level_name", "UNKNOWN")
            hours = curr.get("total_hours", 0)
            trades = curr.get("trades_analyzed", 0)
            knowledge = curr.get("knowledge_entries", 0)
            lines.append(
                f"*Curriculum*: Level {level} ({name})\n"
                f"  Runtime: {hours:.0f}h | Trades: {trades} | Knowledge: {knowledge}"
            )

        # Hypotheses
        hypo = sections.get("hypotheses", {})
        if "error" not in hypo:
            stats = hypo.get("stats", {})
            active = hypo.get("active_count", 0)
            by_stage = stats.get("by_stage", {})
            lines.append(
                f"\n*Hypotheses*: {active} active | "
                f"Validated: {by_stage.get('validated', 0)} | "
                f"Invalidated: {by_stage.get('invalidated', 0)}"
            )
            for grad in hypo.get("newly_graduated", [])[:3]:
                lines.append(f"  NEW: {grad['statement'][:60]} -> {grad['stage']}")

        # Veto accuracy
        veto = sections.get("veto_feedback", {})
        if "error" not in veto and veto.get("total_vetoes", 0) > 0:
            lines.append(
                f"\n*Veto Accuracy*: {veto.get('accuracy', 0):.0%} "
                f"({veto.get('resolved', 0)} resolved) | "
                f"Saved: ~{veto.get('pnl_saved', 0):.1f}%"
            )

        # Self-improvement
        imp = sections.get("self_improvement", {})
        if "error" not in imp:
            auto = imp.get("auto_applicable", 0)
            pending = imp.get("pending_review", 0)
            if auto + pending > 0:
                lines.append(
                    f"\n*Proposals*: {auto} auto-applicable | {pending} pending review"
                )

        # Recommendations
        rec = sections.get("recommendations", {})
        if "error" not in rec:
            pending = rec.get("pending_count", 0)
            if pending > 0:
                lines.append(f"\n*Recommendations*: {pending} pending")
                for r in rec.get("top_pending", [])[:3]:
                    lines.append(
                        f"  - {r['title'][:60]} "
                        f"(conf={r['confidence']:.0%}, from {r['source']})"
                    )

        # Parameter changes
        params = sections.get("parameter_changes", {})
        if "error" not in params and params.get("recent_count", 0) > 0:
            lines.append(f"\n*Param Changes*: {params['recent_count']} recent")

        return "\n".join(lines)

    def format_for_llm_prompt(self) -> str:
        """Format a compact growth summary for LLM prompt injection.

        This gives the LLM self-awareness of its own learning progress.
        """
        self._ensure_loaded()

        parts = []

        # Curriculum status
        try:
            from llm.self_teaching import get_teaching_engine
            teaching = get_teaching_engine()
            c = teaching.curriculum
            parts.append(
                f"LEARNING STATUS: Level {c.current_level} "
                f"({c.hours_at_level:.0f}h at level, "
                f"{c.trades_analyzed} trades analyzed, "
                f"{c.hypotheses_validated} hypotheses validated)"
            )
        except Exception:
            pass

        # Active hypotheses
        try:
            from llm.growth.hypothesis_tracker import get_hypothesis_tracker
            tracker = get_hypothesis_tracker()
            prompt_str = tracker.format_for_llm_prompt()
            if prompt_str:
                parts.append(prompt_str)
        except Exception:
            pass

        # Recent recommendations
        try:
            from llm.growth.recommendation_engine import get_recommendation_engine
            rec_engine = get_recommendation_engine()
            rec_str = rec_engine.format_for_llm_prompt()
            if rec_str:
                parts.append(rec_str)
        except Exception:
            pass

        # Parameter changes
        try:
            from llm.growth.explainability import get_explainer
            explainer = get_explainer()
            exp_str = explainer.format_for_llm_prompt()
            if exp_str:
                parts.append(exp_str)
        except Exception:
            pass

        # Self-improvement outcomes
        try:
            from llm.growth.self_improvement import get_self_improvement_engine
            imp_engine = get_self_improvement_engine()
            imp_str = imp_engine.format_for_llm_prompt()
            if imp_str:
                parts.append(imp_str)
        except Exception:
            pass

        # Veto feedback
        try:
            from llm.growth.veto_feedback import get_veto_tracker
            veto_tracker = get_veto_tracker()
            feedback = veto_tracker.get_memory_feedback()
            if feedback:
                parts.append(f"VETO PERFORMANCE: {feedback}")
        except Exception:
            pass

        return "\n".join(parts)

    def get_latest_report(self) -> Optional[Dict[str, Any]]:
        """Get the most recent report."""
        self._ensure_loaded()
        return self._reports[-1] if self._reports else None


# ── Singleton ─────────────────────────────────────────────

_reporter: Optional[GrowthReporter] = None


def get_growth_reporter() -> GrowthReporter:
    """Get the singleton GrowthReporter."""
    global _reporter
    if _reporter is None:
        _reporter = GrowthReporter()
    return _reporter
