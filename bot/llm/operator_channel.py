"""
LLM Operator Channel: The bot's voice to you.

When the LLM detects operational anomalies during live trading, this module
formats structured messages and sends them to the operator via Telegram.

The operator channel is the fourth team member in the trading system:
  1. The human operator (you)
  2. The guardrails (circuit breakers, risk limits, feedback loops)
  3. Claude Code (the builder)
  4. The LLM meta-brain (the trader)

This channel lets #4 talk to #1 when something needs human attention.

Detectable issues (6 categories):
  1. Performance: Loss streaks, degrading win rate
  2. LLM Performance: Accuracy drop, overconfidence, poor flips
  3. Cost: Budget approaching limits, model auto-downgrades
  4. Risk: Correlated positions, directional overload
  5. Activity: Too many skips, long inactivity despite signals
  6. Funding: High holding costs bleeding PnL

Dedup: Same category won't re-alert within 30 minutes.
Persistence: Message log saved to data/llm/operator_messages.json.
"""

import json
import logging
import os
import time
from typing import Dict, Any, List, Optional

logger = logging.getLogger("bot.llm.operator_channel")

_OP_DIR = os.path.join("data", "llm")
_OP_PATH = os.path.join(_OP_DIR, "operator_messages.json")
_CHECK_INTERVAL_S = 300  # Check for issues every 5 minutes
_DEDUP_WINDOW_S = 1800   # Same category won't re-alert within 30 min
_MAX_LOG_SIZE = 200


class OperatorChannel:
    """Detects operational anomalies and relays them to the operator."""

    def __init__(self, alert_router=None):
        """
        Args:
            alert_router: AlertRouter instance for sending Telegram/Discord messages.
                         Can be None (messages only logged, not sent).
        """
        self._alerts = alert_router
        self._message_log: List[Dict] = []
        self._last_sent_by_category: Dict[str, float] = {}
        self._last_check: float = 0.0
        self._load_state()

    def check_and_report(self, context: Dict[str, Any]):
        """Called every tick. Checks for anomalies and sends operator messages.

        Args:
            context: Dict with operational metrics:
                - consecutive_losses: int
                - llm_accuracy: float (0-1)
                - llm_decisions_count: int
                - budget_used_pct: float (0-1)
                - correlation_risk: str ("low", "medium", "high")
                - hours_since_last_trade: float
                - signals_generated: int (today)
                - estimated_daily_funding_cost: float (% of equity)
                - flip_success_rate: float (0-1)
                - flip_count: int
                - calibration: float (positive = overconfident)
                - veto_accuracy: float (0-1)
                - streak: str (e.g., "WWLLL")
        """
        now = time.time()
        if now - self._last_check < _CHECK_INTERVAL_S:
            return
        self._last_check = now

        issues = self._detect_issues(context)
        for issue in issues:
            category = issue.get("category", "unknown")

            # Dedup: don't send same category within window
            last_sent = self._last_sent_by_category.get(category, 0)
            if now - last_sent < _DEDUP_WINDOW_S:
                continue

            self._send_to_operator(issue)
            self._last_sent_by_category[category] = now

    def _detect_issues(self, ctx: Dict) -> List[Dict]:
        """Detect operational anomalies worth flagging to the operator."""
        issues = []

        # 1. Loss streak detection
        consecutive = ctx.get("consecutive_losses", 0)
        if consecutive >= 4:
            issues.append({
                "severity": "WARNING",
                "category": "performance",
                "message": (
                    f"Lost {consecutive} trades in a row. "
                    f"Current regime detection may be off."
                ),
                "suggestion": (
                    "Consider pausing for 30min or switching to VETO_ONLY mode"
                ),
                "auto_fixable": False,
            })

        # 2. LLM accuracy degradation
        llm_acc = ctx.get("llm_accuracy", 0.5)
        llm_count = ctx.get("llm_decisions_count", 0)
        if llm_acc < 0.40 and llm_count >= 15:
            issues.append({
                "severity": "ALERT",
                "category": "llm_performance",
                "message": (
                    f"LLM accuracy dropped to {llm_acc:.0%} "
                    f"over last {llm_count} decisions"
                ),
                "suggestion": (
                    "Downgrade to VETO_ONLY mode until accuracy recovers"
                ),
                "auto_fixable": False,
            })

        # 2b. LLM overconfidence
        calibration = ctx.get("calibration", 0.0)
        if calibration > 0.15 and llm_count >= 10:
            issues.append({
                "severity": "INFO",
                "category": "llm_calibration",
                "message": (
                    f"LLM is overconfident by {calibration:.0%} — "
                    f"stated confidence exceeds actual win rate"
                ),
                "suggestion": (
                    "The LLM should self-adjust, but watch for continued overconfidence"
                ),
                "auto_fixable": True,
            })

        # 2c. Flips not working
        flip_sr = ctx.get("flip_success_rate", 0.5)
        flip_count = ctx.get("flip_count", 0)
        if flip_sr < 0.30 and flip_count >= 5:
            issues.append({
                "severity": "WARNING",
                "category": "llm_flips",
                "message": (
                    f"LLM flips succeed only {flip_sr:.0%} of the time "
                    f"({flip_count} flips total)"
                ),
                "suggestion": (
                    "Consider disabling flips (set mode to VETO_ONLY or SIZING)"
                ),
                "auto_fixable": False,
            })

        # 3. Budget warning
        budget_pct = ctx.get("budget_used_pct", 0)
        if budget_pct > 0.80:
            issues.append({
                "severity": "INFO",
                "category": "cost",
                "message": (
                    f"API budget {budget_pct:.0%} used today. "
                    f"Auto-switching to cheaper models for non-critical calls."
                ),
                "suggestion": None,
                "auto_fixable": True,
            })

        # 4. Correlation overload
        corr_risk = ctx.get("correlation_risk", "low")
        if corr_risk == "high":
            issues.append({
                "severity": "WARNING",
                "category": "risk",
                "message": (
                    "Portfolio heavily correlated — multiple same-direction "
                    "positions in correlated assets"
                ),
                "suggestion": (
                    "Reduce exposure or add a hedge position"
                ),
                "auto_fixable": False,
            })

        # 5. Inactivity detection
        hours_since_trade = ctx.get("hours_since_last_trade", 0)
        signals_gen = ctx.get("signals_generated", 0)
        if hours_since_trade > 8 and signals_gen > 10:
            issues.append({
                "severity": "INFO",
                "category": "activity",
                "message": (
                    f"No trades in {hours_since_trade:.0f}h despite "
                    f"{signals_gen} signals generated. "
                    f"Confidence floor may be too high."
                ),
                "suggestion": (
                    "Review feedback floor settings or lower minimum confidence"
                ),
                "auto_fixable": False,
            })

        # 6. Funding cost bleeding
        daily_funding = ctx.get("estimated_daily_funding_cost", 0)
        if daily_funding > 0.5:  # >0.5% of equity per day
            issues.append({
                "severity": "WARNING",
                "category": "funding",
                "message": (
                    f"Paying ~{daily_funding:.2f}%/day in funding "
                    f"on open positions"
                ),
                "suggestion": (
                    "Consider closing high-funding positions or "
                    "switching to shorter holds"
                ),
                "auto_fixable": False,
            })

        # 7. Strong veto accuracy (positive feedback)
        veto_acc = ctx.get("veto_accuracy", 0.5)
        veto_count = ctx.get("veto_count", 0)
        if veto_acc > 0.80 and veto_count >= 10:
            issues.append({
                "severity": "INFO",
                "category": "veto_success",
                "message": (
                    f"LLM veto accuracy is excellent: {veto_acc:.0%} "
                    f"({veto_count} vetoes evaluated). "
                    f"The LLM is successfully filtering out losers."
                ),
                "suggestion": None,
                "auto_fixable": True,
            })

        return issues

    def _send_to_operator(self, issue: Dict):
        """Format and send issue to Telegram/Discord via AlertRouter."""
        severity_markers = {
            "WARNING": "[!! WARNING]",
            "ALERT": "[!!! ALERT]",
            "INFO": "[i INFO]",
        }
        marker = severity_markers.get(issue["severity"], "[INFO]")

        msg_lines = [
            f"{marker} LLM INSIGHT — {issue['category'].upper()}",
            f"{issue['message']}",
        ]
        if issue.get("suggestion"):
            msg_lines.append(f"")
            msg_lines.append(f"Suggestion: {issue['suggestion']}")
        if issue.get("auto_fixable"):
            msg_lines.append("(Auto-handling this)")

        msg = "\n".join(msg_lines)

        # Send via AlertRouter
        if self._alerts:
            try:
                self._alerts.send_market_update(msg)
            except Exception as e:
                logger.warning(f"[OPERATOR] Failed to send alert: {e}")

        # Always log
        self._log_message(issue)

        logger.info(f"[OPERATOR] Sent: {issue['category']} — {issue['message'][:80]}")

    def _log_message(self, issue: Dict):
        """Append to persistent message log."""
        entry = {
            "ts": time.time(),
            "severity": issue.get("severity"),
            "category": issue.get("category"),
            "message": issue.get("message"),
            "suggestion": issue.get("suggestion"),
            "auto_fixable": issue.get("auto_fixable", False),
        }
        self._message_log.append(entry)
        if len(self._message_log) > _MAX_LOG_SIZE:
            self._message_log = self._message_log[-_MAX_LOG_SIZE:]
        self._save_state()

    def get_recent_messages(self, limit: int = 10) -> List[Dict]:
        """Get recent operator messages."""
        return self._message_log[-limit:]

    def _save_state(self):
        """Persist message log."""
        os.makedirs(_OP_DIR, exist_ok=True)
        try:
            with open(_OP_PATH, "w") as f:
                json.dump({
                    "messages": self._message_log[-_MAX_LOG_SIZE:],
                    "last_sent_by_category": self._last_sent_by_category,
                }, f, indent=2)
        except Exception as e:
            logger.warning(f"[OPERATOR] Failed to save state: {e}")

    def _load_state(self):
        """Load message log from disk."""
        if not os.path.exists(_OP_PATH):
            return
        try:
            with open(_OP_PATH, "r") as f:
                state = json.load(f)
            self._message_log = state.get("messages", [])
            self._last_sent_by_category = state.get("last_sent_by_category", {})
            # Convert string timestamps back to float
            self._last_sent_by_category = {
                k: float(v) for k, v in self._last_sent_by_category.items()
            }
        except Exception as e:
            logger.warning(f"[OPERATOR] Failed to load state: {e}")


# Module-level singleton
_channel: Optional[OperatorChannel] = None


def get_operator_channel(alert_router=None) -> OperatorChannel:
    """Get or create the singleton OperatorChannel."""
    global _channel
    if _channel is None:
        _channel = OperatorChannel(alert_router=alert_router)
    elif alert_router is not None and _channel._alerts is None:
        _channel._alerts = alert_router
    return _channel
