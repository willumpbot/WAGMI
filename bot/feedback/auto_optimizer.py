"""
AutoOptimizer: Autonomous self-review and optimization orchestrator.

Triggers automated evolution reports, parameter optimization, and optional
Haiku LLM interpretation on three conditions:
  1. Scheduled — at least 2x daily, adaptive frequency
  2. Trade-count — after N trades since last review
  3. Alert-driven — performance degradation detection

All parameter changes flow through existing ParameterTuner (trust-gated, bounded).
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bot.feedback.auto_optimizer")

# Adaptive interval bounds (seconds)
_MIN_INTERVAL_S = 6 * 3600    # 6 hours (degrading performance)
_MAX_INTERVAL_S = 18 * 3600   # 18 hours (rising performance)
_DEFAULT_INTERVAL_S = 12 * 3600  # 12 hours

# Minimum gap between ANY two reviews to prevent thrashing
_COOLDOWN_S = 3600  # 1 hour


class AutoOptimizer:
    """Autonomous self-review and optimization loop.

    Monitors trading performance and triggers review pipelines that
    call EvolutionTracker, ParameterTuner, and optionally a Haiku LLM
    for interpretation. Reviews are triggered by schedule, trade count,
    or performance degradation alerts.
    """

    def __init__(
        self,
        evolution_tracker,          # EvolutionTracker instance
        tuner,                      # ParameterTuner instance
        data_dir: str = "data/feedback",
        llm_client=None,            # Optional: bot/llm/client.py for Haiku calls
        min_interval_h: float = 12.0,
        trades_per_review: int = 15,
        degradation_threshold: float = 15.0,
        consec_loss_alert: int = 4,
        llm_review_enabled: bool = True,
    ):
        self._evolution = evolution_tracker
        self._tuner = tuner
        self._data_dir = data_dir
        self._llm_client = llm_client
        self._trades_per_review = trades_per_review
        self._degradation_threshold = degradation_threshold
        self._consec_loss_alert = consec_loss_alert
        self._llm_review_enabled = llm_review_enabled

        # Feedback loop reference (set externally if needed)
        self._feedback_loop = None

        os.makedirs(data_dir, exist_ok=True)

        # ── Persistent state ──────────────────────────────────────
        self._state: Dict[str, Any] = {
            "last_scheduled_review_ts": 0.0,
            "last_trade_count_review": 0,
            "total_trades": 0,
            "total_reviews": 0,
            "review_history": [],          # max 50 entries
            "adaptive_interval_s": min_interval_h * 3600,
            "performance_baseline": {
                "win_rate": 50.0,          # EMA baseline
                "avg_pnl": 0.0,
            },
            "consecutive_losses": 0,
        }

        self._state_path = os.path.join(data_dir, "auto_optimizer_state.json")
        self._log_path = os.path.join(data_dir, "auto_optimizer_log.jsonl")
        self._last_review_ts = 0.0  # tracks ANY review (for cooldown)

        self._load_state()

        logger.info(
            "[AUTO-OPT] Initialized: interval=%.1fh, trades_per_review=%d, "
            "degradation_threshold=%.1f%%, llm_review=%s",
            self._state["adaptive_interval_s"] / 3600,
            self._trades_per_review,
            self._degradation_threshold,
            self._llm_review_enabled,
        )

    # ── Public: wire up FeedbackLoop ──────────────────────────────

    def set_feedback_loop(self, feedback_loop):
        """Attach a FeedbackLoop instance for get_report() calls."""
        self._feedback_loop = feedback_loop

    # ── Public: main tick ─────────────────────────────────────────

    def tick(self, trade_count: int, recent_win_rate: float, recent_avg_pnl: float):
        """Called every main loop iteration. Checks all three trigger conditions.

        Args:
            trade_count: Total closed trades since bot start.
            recent_win_rate: Rolling win rate (0-100).
            recent_avg_pnl: Rolling average PnL per trade.
        """
        trigger = self._should_trigger(trade_count, recent_win_rate)
        if trigger is None:
            return

        # Cooldown guard: no two reviews within 1 hour
        now = time.time()
        if now - self._last_review_ts < _COOLDOWN_S:
            logger.debug(
                "[AUTO-OPT] Trigger '%s' suppressed by cooldown (%.0f min remaining)",
                trigger,
                (_COOLDOWN_S - (now - self._last_review_ts)) / 60,
            )
            return

        logger.info("[AUTO-OPT] Triggered: %s", trigger)
        try:
            result = self._run_review(trigger)
            self._log_review(result)
            self._update_adaptive_interval(recent_win_rate)
            self._last_review_ts = time.time()
        except Exception as e:
            logger.error("[AUTO-OPT] Review failed: %s", e, exc_info=True)

    def record_trade(self, pnl: float, win: bool):
        """Called after each trade close. Updates counters and rolling stats.

        Args:
            pnl: Realized PnL of the closed trade.
            win: Whether the trade was profitable.
        """
        self._state["total_trades"] += 1

        # Track consecutive losses
        if win:
            self._state["consecutive_losses"] = 0
        else:
            self._state["consecutive_losses"] += 1

        # Update performance baseline via exponential moving average
        alpha = 0.1
        baseline = self._state["performance_baseline"]
        current_wr = 100.0 if win else 0.0
        baseline["win_rate"] = baseline["win_rate"] * (1 - alpha) + current_wr * alpha
        baseline["avg_pnl"] = baseline["avg_pnl"] * (1 - alpha) + pnl * alpha

        self._save_state()

    # ── Trigger logic ─────────────────────────────────────────────

    def _should_trigger(self, trade_count: int, recent_win_rate: float) -> Optional[str]:
        """Check if any trigger condition is met. Returns trigger reason or None."""
        now = time.time()

        # 1. Scheduled trigger: adaptive interval elapsed
        elapsed = now - self._state["last_scheduled_review_ts"]
        interval = self._state["adaptive_interval_s"]
        if elapsed >= interval:
            return f"scheduled (interval {interval / 3600:.1f}h elapsed)"

        # 2. Trade-count trigger: N trades since last review
        trades_since = self._state["total_trades"] - self._state["last_trade_count_review"]
        if trades_since >= self._trades_per_review:
            return f"trade_count ({trades_since} trades since last review)"

        # 3. Alert-driven: win rate drop from baseline
        baseline_wr = self._state["performance_baseline"]["win_rate"]
        if baseline_wr > 0 and recent_win_rate < (baseline_wr - self._degradation_threshold):
            return (
                f"alert_degradation (WR {recent_win_rate:.1f}% vs "
                f"baseline {baseline_wr:.1f}%, drop >{self._degradation_threshold:.0f}%)"
            )

        # 4. Alert-driven: consecutive loss streak
        if self._state["consecutive_losses"] >= self._consec_loss_alert:
            return f"alert_consec_losses ({self._state['consecutive_losses']} consecutive losses)"

        return None

    # ── Review pipeline ───────────────────────────────────────────

    def _run_review(self, trigger_reason: str) -> Dict:
        """Execute the full review pipeline.

        Steps:
          1. Generate evolution report
          2. Apply lessons to tuner
          3. Gather feedback loop report (if available)
          4. Optional Haiku LLM review
          5. Update state

        Returns:
            Review result dict with trigger, timestamp, report summary,
            lessons applied, and optional LLM insights.
        """
        now = time.time()
        result: Dict[str, Any] = {
            "trigger": trigger_reason,
            "ts": now,
            "iso": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        }

        # Step 1: Generate evolution report
        try:
            report = self._evolution.generate_report()
            result["total_trades"] = report.total_trades
            result["total_decisions"] = report.total_decisions
            result["lessons_count"] = len(report.lessons)

            # Extract win rate summary from trajectory
            for w in report.win_rate_trajectory:
                if w.window_label == "7d" and w.total_trades > 0:
                    result["wr_7d"] = round(w.win_rate, 1)
                    result["pnl_7d"] = round(w.total_pnl, 2)
                elif w.window_label == "all" and w.total_trades > 0:
                    result["wr_all"] = round(w.win_rate, 1)
                    result["pnl_all"] = round(w.total_pnl, 2)
        except Exception as e:
            logger.warning("[AUTO-OPT] Evolution report failed: %s", e)
            report = None
            result["evolution_error"] = str(e)

        # Step 2: Apply lessons to tuner
        lessons_applied = 0
        if report is not None:
            try:
                lessons_applied = self._evolution.apply_lessons_to_tuner(report, self._tuner)
            except Exception as e:
                logger.warning("[AUTO-OPT] apply_lessons_to_tuner failed: %s", e)
        result["lessons_applied"] = lessons_applied

        # Step 3: Gather feedback loop report
        feedback_report: Dict[str, Any] = {}
        if self._feedback_loop is not None:
            try:
                feedback_report = self._feedback_loop.get_report()
            except Exception as e:
                logger.warning("[AUTO-OPT] FeedbackLoop.get_report() failed: %s", e)
        result["feedback_report_available"] = bool(feedback_report)

        # Step 4: Optional Haiku LLM review
        llm_insights = None
        if self._llm_review_enabled and self._llm_client is not None and report is not None:
            try:
                summary = self._build_compact_summary(report, feedback_report)
                llm_insights = self._haiku_review(summary)
            except Exception as e:
                logger.warning("[AUTO-OPT] Haiku review failed: %s", e)
        result["llm_insights"] = llm_insights

        # Step 5: Update state
        self._state["last_scheduled_review_ts"] = now
        self._state["last_trade_count_review"] = self._state["total_trades"]
        self._state["total_reviews"] += 1

        # Append to review history (cap at 50)
        history_entry = {
            "ts": now,
            "trigger": trigger_reason,
            "lessons_applied": lessons_applied,
            "wr_7d": result.get("wr_7d"),
            "llm_urgency": (llm_insights or {}).get("urgency"),
        }
        self._state["review_history"].append(history_entry)
        if len(self._state["review_history"]) > 50:
            self._state["review_history"] = self._state["review_history"][-50:]

        self._save_state()

        logger.info(
            "[AUTO-OPT] Review #%d complete: trigger=%s, lessons=%d, llm=%s",
            self._state["total_reviews"],
            trigger_reason,
            lessons_applied,
            "yes" if llm_insights else "no",
        )

        return result

    # ── Haiku LLM review ──────────────────────────────────────────

    def _haiku_review(self, summary: str) -> Optional[Dict]:
        """Send compact summary to Haiku for interpretation.

        Args:
            summary: Token-efficient performance summary string.

        Returns:
            Parsed JSON dict with insights, urgency, and actions,
            or None on failure.
        """
        if self._llm_client is None:
            return None

        prompt = (
            "You review a crypto trading bot. Given this performance summary, provide:\n"
            "1. Top 2-3 actionable insights\n"
            "2. Urgency level (low/medium/high)\n"
            "3. Parameter suggestions\n"
            "Respond JSON only: "
            '{"insights":["..."],"urgency":"low","actions":["..."]}\n\n'
            f"Summary:\n{summary}"
        )

        try:
            response_text, usage = self._llm_client.call(
                prompt=prompt,
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
            )

            if response_text is None:
                logger.warning("[AUTO-OPT] Haiku returned None response")
                return None

            # Strip markdown fences if present
            text = response_text.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                # Remove first and last lines (fences)
                lines = [l for l in lines if not l.strip().startswith("```")]
                text = "\n".join(lines).strip()

            parsed = json.loads(text)

            # Validate expected structure
            if not isinstance(parsed, dict):
                logger.warning("[AUTO-OPT] Haiku response is not a dict: %s", type(parsed))
                return None

            # Ensure required keys with defaults
            result = {
                "insights": parsed.get("insights", []),
                "urgency": parsed.get("urgency", "low"),
                "actions": parsed.get("actions", []),
            }

            # Validate urgency value
            if result["urgency"] not in ("low", "medium", "high"):
                result["urgency"] = "low"

            logger.info(
                "[AUTO-OPT] Haiku review: urgency=%s, insights=%d, actions=%d",
                result["urgency"],
                len(result["insights"]),
                len(result["actions"]),
            )
            return result

        except json.JSONDecodeError as e:
            logger.warning("[AUTO-OPT] Haiku response parse failed: %s", e)
            return None
        except Exception as e:
            logger.warning("[AUTO-OPT] Haiku call error: %s", e)
            return None

    def _build_compact_summary(self, report, feedback_report: Dict) -> str:
        """Build a token-efficient summary for Haiku.

        Keeps total under ~400 tokens to leave room for Haiku's 300-token response.

        Args:
            report: EvolutionReport from generate_report().
            feedback_report: Dict from FeedbackLoop.get_report().

        Returns:
            Compact multi-line summary string.
        """
        lines = []

        # Win rate trajectory (compact)
        for w in report.win_rate_trajectory:
            if w.total_trades > 0 and w.window_label in ("24h", "7d", "all"):
                lines.append(
                    f"{w.window_label}: {w.total_trades}t, WR={w.win_rate:.0f}%, "
                    f"PnL=${w.total_pnl:+.2f}, avg=${w.avg_pnl:+.2f}"
                )

        # Top edge dimensions (max 3)
        if report.edge_by_regime:
            top_regimes = [
                f"{e.key}:{e.win_rate:.0f}%({e.trades}t)"
                for e in report.edge_by_regime[:3]
                if e.trades >= 3
            ]
            if top_regimes:
                lines.append(f"Regimes: {', '.join(top_regimes)}")

        if report.edge_by_strategy:
            top_strats = [
                f"{e.key}:{e.win_rate:.0f}%({e.trades}t)"
                for e in report.edge_by_strategy[:3]
                if e.trades >= 3
            ]
            if top_strats:
                lines.append(f"Strategies: {', '.join(top_strats)}")

        # Top lessons (max 3)
        for lesson in report.lessons[:3]:
            lines.append(f"[{lesson.category}] {lesson.message}")

        # Tuner state from feedback report
        tuner_data = feedback_report.get("tuner", {})
        if tuner_data:
            lines.append(
                f"Tuner: trust={tuner_data.get('trust_score', '?')}, "
                f"floor={tuner_data.get('confidence_floor', '?')}%"
            )

        # Consecutive losses
        consec = self._state.get("consecutive_losses", 0)
        if consec >= 2:
            lines.append(f"Consec losses: {consec}")

        return "\n".join(lines) if lines else "No data available."

    # ── Adaptive interval ─────────────────────────────────────────

    def _update_adaptive_interval(self, recent_win_rate: float):
        """Adjust review frequency based on performance.

        Mapping:
          - Degrading (WR drop >10% from baseline): 6h
          - Slightly off (WR drop 5-10%):            9h
          - Stable (within 5% of baseline):          12h
          - Rising (WR above baseline by >5%):       18h

        Args:
            recent_win_rate: Current rolling win rate (0-100).
        """
        baseline_wr = self._state["performance_baseline"]["win_rate"]
        delta = recent_win_rate - baseline_wr

        if delta < -10:
            new_interval = _MIN_INTERVAL_S          # 6h — degrading
        elif delta < -5:
            new_interval = 9 * 3600                 # 9h — slightly off
        elif delta <= 5:
            new_interval = _DEFAULT_INTERVAL_S      # 12h — stable
        else:
            new_interval = _MAX_INTERVAL_S          # 18h — rising

        old_interval = self._state["adaptive_interval_s"]
        self._state["adaptive_interval_s"] = new_interval

        if old_interval != new_interval:
            logger.info(
                "[AUTO-OPT] Adaptive interval: %.1fh -> %.1fh (WR delta %+.1f%%)",
                old_interval / 3600,
                new_interval / 3600,
                delta,
            )

    # ── Logging ───────────────────────────────────────────────────

    def _log_review(self, review_result: Dict):
        """Append review to JSONL log file."""
        try:
            with open(self._log_path, "a") as f:
                f.write(json.dumps(review_result, default=str) + "\n")
        except OSError as e:
            logger.warning("[AUTO-OPT] Failed to write log: %s", e)

    # ── State persistence ─────────────────────────────────────────

    def _save_state(self):
        """Persist optimizer state to JSON file."""
        try:
            tmp_path = self._state_path + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(self._state, f, indent=2)
            os.replace(tmp_path, self._state_path)
        except OSError as e:
            logger.warning("[AUTO-OPT] Failed to save state: %s", e)

    def _load_state(self):
        """Load optimizer state from JSON file."""
        if not os.path.exists(self._state_path):
            return
        try:
            with open(self._state_path, "r") as f:
                saved = json.load(f)

            # Merge saved state into defaults (handles schema additions gracefully)
            for key in self._state:
                if key in saved:
                    self._state[key] = saved[key]

            # Restore last_review_ts from the most recent review history entry
            history = self._state.get("review_history", [])
            if history:
                self._last_review_ts = history[-1].get("ts", 0.0)

            logger.info(
                "[AUTO-OPT] Loaded state: %d reviews, %d trades, interval=%.1fh, "
                "baseline_wr=%.1f%%",
                self._state["total_reviews"],
                self._state["total_trades"],
                self._state["adaptive_interval_s"] / 3600,
                self._state["performance_baseline"]["win_rate"],
            )
        except (OSError, json.JSONDecodeError, KeyError) as e:
            logger.warning("[AUTO-OPT] Failed to load state, using defaults: %s", e)

    # ── Status reporting ──────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Get current optimizer status for reporting."""
        now = time.time()
        interval = self._state["adaptive_interval_s"]
        elapsed = now - self._state["last_scheduled_review_ts"]
        next_scheduled_in = max(0, interval - elapsed)

        trades_since = self._state["total_trades"] - self._state["last_trade_count_review"]
        trades_until_review = max(0, self._trades_per_review - trades_since)

        return {
            "total_reviews": self._state["total_reviews"],
            "total_trades": self._state["total_trades"],
            "adaptive_interval_h": round(interval / 3600, 1),
            "next_scheduled_in_h": round(next_scheduled_in / 3600, 2),
            "trades_until_review": trades_until_review,
            "consecutive_losses": self._state["consecutive_losses"],
            "performance_baseline": {
                "win_rate": round(self._state["performance_baseline"]["win_rate"], 1),
                "avg_pnl": round(self._state["performance_baseline"]["avg_pnl"], 4),
            },
            "llm_review_enabled": self._llm_review_enabled,
            "last_review": (
                self._state["review_history"][-1]
                if self._state["review_history"]
                else None
            ),
        }
