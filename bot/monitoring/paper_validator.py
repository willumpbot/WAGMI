"""
Paper trading hourly checkpoint monitor.

Runs every ~1 hour during paper trading to validate:
- Signal generation rate (is the bot actually evaluating?)
- Gate rejection breakdown (is any gate blocking everything?)
- Win rate / drawdown thresholds
- Circuit breaker state
- Regime distribution (is the bot stuck in one regime?)

Sends a Telegram/Discord summary via AlertRouter on each checkpoint.
Sends additional WARNING alerts if any threshold is breached.
"""

import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bot.monitoring.paper_validator")

# Thresholds for warnings
_MIN_WIN_RATE = 0.40          # Warn if WR < 40% over 10+ closed trades
_MAX_DRAWDOWN_PCT = 10.0      # Warn if session DD > 10%
_MIN_SIGNALS_PER_HOUR = 1.0   # Warn if < 1 signal/h (data feed issue?)
_MAX_GATE_DOMINANCE = 0.80    # Warn if one gate blocks > 80% of rejections
_HIGH_CONF_GATE_ALERT = 5     # Warn if gate blocks 5+ high-conf signals in 1h


class PaperValidator:
    """Hourly health checkpoint for paper trading sessions.

    Usage:
        validator = PaperValidator(risk_mgr=risk_mgr, pos_mgr=pos_mgr,
                                   alert_router=alerts)
        # In main loop, every hour:
        validator.run_checkpoint()
    """

    def __init__(self, risk_mgr=None, pos_mgr=None, alert_router=None,
                 start_equity: float = 0.0):
        self._risk_mgr = risk_mgr
        self._pos_mgr = pos_mgr
        self._alert_router = alert_router
        self._start_time = time.time()
        self._start_equity = start_equity
        self._checkpoint_count = 0

    def run_checkpoint(self) -> Dict[str, Any]:
        """Run the hourly checkpoint. Returns metrics dict."""
        self._checkpoint_count += 1
        try:
            metrics = self._compute_metrics()
            warnings = self._check_thresholds(metrics)
            self._send_report(metrics, warnings)
            return {"status": "warn" if warnings else "ok",
                    "metrics": metrics, "warnings": warnings}
        except Exception as e:
            logger.warning(f"[PAPER-VALIDATOR] Checkpoint failed: {e}")
            return {"status": "error", "error": str(e)}

    # ── Metrics collection ────────────────────────────────────────

    def _compute_metrics(self) -> Dict[str, Any]:
        from data import db

        uptime_s = time.time() - self._start_time
        uptime_h = uptime_s / 3600

        # Closed trades in last 24h for win rate
        trades_24h = self._get_closed_trades(hours=24)
        wins_24h = [t for t in trades_24h if t.get("pnl", 0) > 0]
        net_pnl_24h = sum(t.get("pnl", 0) - t.get("fee", 0) for t in trades_24h)
        win_rate = len(wins_24h) / len(trades_24h) if trades_24h else None

        # Signals in last 1h
        signals_1h = self._get_signals(hours=1)
        signals_per_hour = len(signals_1h) / max(uptime_h, 1.0)

        # Gate rejection summary (last 1h)
        rejection_summary = db.get_rejection_summary(hours=1)
        total_rejections = sum(v["count"] for v in rejection_summary.values())
        high_conf_rejections = sum(v["high_conf"] for v in rejection_summary.values())

        # Dominant gate
        dominant_gate = ""
        dominant_pct = 0.0
        if total_rejections > 0:
            for gate, stats in sorted(rejection_summary.items(),
                                      key=lambda x: x[1]["count"], reverse=True):
                dominant_pct = stats["count"] / total_rejections
                dominant_gate = gate
                break

        # Session drawdown
        max_dd_pct = self._compute_session_drawdown()

        # Circuit breaker state
        cb_active = False
        cb_reason = ""
        if self._risk_mgr:
            try:
                cb = getattr(self._risk_mgr, "circuit_breaker", None)
                if cb:
                    cb_active = getattr(cb, "is_active", False)
                    cb_reason = getattr(cb, "trigger_reason", "")
            except Exception:
                pass

        # Open positions
        open_positions = 0
        if self._pos_mgr:
            try:
                open_positions = len(self._pos_mgr.get_open_positions())
            except Exception:
                pass

        # Regime distribution (last 1h from signals metadata)
        regime_dist = self._compute_regime_distribution(signals_1h)

        return {
            "uptime_h": round(uptime_h, 1),
            "checkpoint": self._checkpoint_count,
            "trades_24h": len(trades_24h),
            "wins_24h": len(wins_24h),
            "win_rate": round(win_rate, 3) if win_rate is not None else None,
            "net_pnl_24h": round(net_pnl_24h, 2),
            "signals_1h": len(signals_1h),
            "signals_per_hour": round(signals_per_hour, 1),
            "total_rejections_1h": total_rejections,
            "high_conf_rejections_1h": high_conf_rejections,
            "dominant_gate": dominant_gate,
            "dominant_gate_pct": round(dominant_pct, 2),
            "rejection_by_gate": rejection_summary,
            "max_drawdown_pct": round(max_dd_pct, 2),
            "cb_active": cb_active,
            "cb_reason": cb_reason,
            "open_positions": open_positions,
            "regime_dist": regime_dist,
        }

    def _get_closed_trades(self, hours: int = 24) -> List[Dict]:
        try:
            from data import db
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
            conn = db.get_connection()
            _CLOSE_ACTIONS = ("SL", "TP1", "TP2", "TRAILING_STOP", "EARLY_EXIT",
                              "EMERGENCY", "ROTATE_OUT", "ROTATE_LOSS", "MANUAL_CLOSE")
            placeholders = ",".join("?" * len(_CLOSE_ACTIONS))
            rows = conn.execute(
                f"SELECT * FROM trades WHERE timestamp >= ? AND action IN ({placeholders})",
                [cutoff] + list(_CLOSE_ACTIONS)
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def _get_signals(self, hours: int = 1) -> List[Dict]:
        try:
            from data import db
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
            conn = db.get_connection()
            rows = conn.execute(
                "SELECT * FROM signals WHERE timestamp >= ?", (cutoff,)
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def _compute_session_drawdown(self) -> float:
        """Compute max drawdown since session start."""
        try:
            from data import db
            snapshots = db.get_equity_curve(days=7)
            if not snapshots:
                return 0.0
            # Filter to this session (since _start_time)
            start_ts = datetime.fromtimestamp(self._start_time, tz=timezone.utc).isoformat()
            session_snaps = [s for s in snapshots if s["timestamp"] >= start_ts]
            if not session_snaps:
                return 0.0
            equities = [s["equity"] for s in session_snaps]
            peak = equities[0]
            max_dd = 0.0
            for eq in equities:
                if eq > peak:
                    peak = eq
                elif peak > 0:
                    dd = (peak - eq) / peak * 100
                    max_dd = max(max_dd, dd)
            return max_dd
        except Exception:
            return 0.0

    def _compute_regime_distribution(self, signals: List[Dict]) -> Dict[str, int]:
        """Count regime occurrences from signal metadata."""
        dist: Dict[str, int] = {}
        for sig in signals:
            try:
                import json
                meta = json.loads(sig.get("metadata") or "{}")
                regime = meta.get("regime", "unknown")
                dist[regime] = dist.get(regime, 0) + 1
            except Exception:
                pass
        return dist

    # ── Threshold checks ─────────────────────────────────────────

    def _check_thresholds(self, metrics: Dict[str, Any]) -> List[str]:
        warnings = []

        wr = metrics.get("win_rate")
        if wr is not None and metrics["trades_24h"] >= 10 and wr < _MIN_WIN_RATE:
            warnings.append(
                f"Win rate {wr:.0%} below {_MIN_WIN_RATE:.0%} "
                f"over {metrics['trades_24h']} trades"
            )

        if metrics["max_drawdown_pct"] > _MAX_DRAWDOWN_PCT:
            warnings.append(
                f"Session drawdown {metrics['max_drawdown_pct']:.1f}% "
                f"exceeds {_MAX_DRAWDOWN_PCT:.0f}% threshold"
            )

        if (metrics["uptime_h"] >= 2.0
                and metrics["signals_per_hour"] < _MIN_SIGNALS_PER_HOUR):
            warnings.append(
                f"Only {metrics['signals_per_hour']:.1f} signals/h "
                f"— possible data feed issue"
            )

        if (metrics["dominant_gate_pct"] > _MAX_GATE_DOMINANCE
                and metrics["total_rejections_1h"] >= 5):
            warnings.append(
                f"Gate '{metrics['dominant_gate']}' blocking "
                f"{metrics['dominant_gate_pct']:.0%} of all rejections "
                f"({metrics['total_rejections_1h']} total)"
            )

        if metrics["high_conf_rejections_1h"] >= _HIGH_CONF_GATE_ALERT:
            warnings.append(
                f"{metrics['high_conf_rejections_1h']} high-confidence signals "
                f"rejected in last hour — gates may be too restrictive"
            )

        if metrics["cb_active"]:
            warnings.append(
                f"Circuit breaker ACTIVE: {metrics['cb_reason'] or 'unknown reason'}"
            )

        return warnings

    # ── Reporting ─────────────────────────────────────────────────

    def _send_report(self, metrics: Dict[str, Any], warnings: List[str]):
        msg = self._format_report(metrics, warnings)
        if self._alert_router:
            try:
                self._alert_router.send_market_update(msg)
            except Exception as e:
                logger.warning(f"[PAPER-VALIDATOR] Failed to send alert: {e}")
        else:
            logger.info(f"[PAPER-VALIDATOR] Checkpoint:\n{msg}")

    def _format_report(self, m: Dict[str, Any], warnings: List[str]) -> str:
        # Win rate display
        if m["win_rate"] is not None:
            wr_str = f"{m['win_rate']:.0%}"
        else:
            wr_str = "N/A (no trades)"

        # PnL display
        pnl_sign = "+" if m["net_pnl_24h"] >= 0 else ""
        pnl_str = f"{pnl_sign}${m['net_pnl_24h']:.2f}"

        # CB status
        cb_str = "ACTIVE ⚠️" if m["cb_active"] else "OK"

        # Regime distribution (top 3)
        regime_parts = []
        for r, cnt in sorted(m["regime_dist"].items(),
                              key=lambda x: x[1], reverse=True)[:3]:
            regime_parts.append(f"{r}:{cnt}")
        regime_str = " ".join(regime_parts) if regime_parts else "no data"

        # Gate rejection breakdown
        gate_parts = []
        for gate, stats in sorted(m["rejection_by_gate"].items(),
                                   key=lambda x: x[1]["count"], reverse=True)[:4]:
            gate_parts.append(f"{gate}:{stats['count']}")
        gate_str = " | ".join(gate_parts) if gate_parts else "none"

        lines = [
            f"[PAPER CHECKPOINT #{m['checkpoint']} | {m['uptime_h']:.1f}h]",
            f"Trades(24h): {m['trades_24h']} | WR: {wr_str} | PnL: {pnl_str}",
            f"Signals/h: {m['signals_per_hour']:.1f} | Rejected(1h): {m['total_rejections_1h']}",
            f"DD: {m['max_drawdown_pct']:.1f}% | CB: {cb_str} | Positions: {m['open_positions']}",
            f"Regimes(1h): {regime_str}",
        ]
        if gate_str != "none":
            lines.append(f"Rejections by gate: {gate_str}")
        if warnings:
            lines.append("---")
            for w in warnings:
                lines.append(f"WARN: {w}")

        return "\n".join(lines)
