"""
Daily Automated Report — 6 Key Metrics.

Generates a daily health-check report covering win rates by agreement
level and regime, walk-forward ratio, session drawdown, IC per factor,
and Kelly weights.  Designed to be run on a schedule or on-demand.

Usage:
    from feedback.trade_ledger import TradeLedger
    from feedback.daily_report import DailyReporter
    ledger = TradeLedger("data")
    reporter = DailyReporter(trade_ledger=ledger)
    report = reporter.generate_report()
    print(reporter.format_report(report))
    alerts = reporter.check_alerts(report)
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bot.feedback.daily_report")

# ── Alert thresholds ──────────────────────────────────────────────
AGREEMENT_WR_ALERT = 40.0       # Alert if any agreement-level WR < 40%
REGIME_WR_ALERT = 35.0          # Alert if any regime WR < 35%
WALK_FORWARD_ALERT = 0.4        # Alert if walk-forward ratio < 0.4
SESSION_DD_ALERT = 15.0         # Alert if session drawdown > 15%
IC_ALERT = 0.02                 # Alert if any factor IC < 0.02
KELLY_ALERT = 0.05              # Alert if any Kelly weight < 0.05


class DailyReporter:
    """Computes 6 key daily metrics from the trade ledger and optional
    dependency modules (IC tracker, Kelly engine).

    Args:
        trade_ledger: A ``TradeLedger`` instance for trade data.
        ic_tracker: Optional object with a ``get_report() -> dict``
            method.  If ``None``, IC metrics are reported as placeholders.
        kelly_engine: Optional object with a ``get_all_weights() -> dict``
            method.  If ``None``, Kelly metrics are reported as placeholders.
    """

    def __init__(
        self,
        trade_ledger,
        ic_tracker=None,
        kelly_engine=None,
    ):
        self._ledger = trade_ledger
        self._ic_tracker = ic_tracker
        self._kelly_engine = kelly_engine

    # ── Report generation ─────────────────────────────────────────

    def generate_report(self) -> Dict[str, Any]:
        """Compute all 6 daily metrics and return a structured dict.

        Returns:
            Dict with keys ``generated_at``, ``metrics`` (dict of 6
            metric blocks), ``alerts`` (list of alert strings), and
            ``recommendations`` (list of actionable strings).
        """
        report: Dict[str, Any] = {
            "generated_at": datetime.now(timezone.utc).strftime(
                "%Y-%m-%d %H:%M UTC"
            ),
            "metrics": {},
            "alerts": [],
            "recommendations": [],
        }

        # 1. 7d rolling WR by agreement level
        report["metrics"]["agreement_wr"] = self._metric_agreement_wr()

        # 2. 7d rolling WR by regime
        report["metrics"]["regime_wr"] = self._metric_regime_wr()

        # 3. Walk-forward ratio (placeholder until E1 is built)
        report["metrics"]["walk_forward"] = self._metric_walk_forward()

        # 4. Session drawdown
        report["metrics"]["session_drawdown"] = self._metric_session_drawdown()

        # 5. IC per factor
        report["metrics"]["ic_per_factor"] = self._metric_ic_per_factor()

        # 6. Kelly weights per factor
        report["metrics"]["kelly_weights"] = self._metric_kelly_weights()

        # Compute alerts and recommendations
        report["alerts"] = self.check_alerts(report)
        report["recommendations"] = self._build_recommendations(report)

        logger.info(
            f"[DAILY] Report generated — {len(report['alerts'])} alerts"
        )
        return report

    # ── Individual metrics ────────────────────────────────────────

    def _metric_agreement_wr(self) -> Dict[str, Any]:
        """Metric 1: 7-day rolling win rate by strategy agreement level."""
        breakdown = self._ledger.get_agreement_breakdown(lookback_days=7)
        return {
            "label": "7d Rolling WR by Agreement Level",
            "data": breakdown,
            "alert_threshold": AGREEMENT_WR_ALERT,
        }

    def _metric_regime_wr(self) -> Dict[str, Any]:
        """Metric 2: 7-day rolling win rate by market regime."""
        breakdown = self._ledger.get_regime_breakdown(lookback_days=7)
        return {
            "label": "7d Rolling WR by Regime",
            "data": breakdown,
            "alert_threshold": REGIME_WR_ALERT,
        }

    def _metric_walk_forward(self) -> Dict[str, Any]:
        """Metric 3: Walk-forward ratio for the last window."""
        try:
            from validation.walk_forward import run_rolling_walk_forward, avg_wf_ratio
            trades = self._ledger.get_trades(lookback_days=60)
            if len(trades) >= 10:
                # Convert trades to format walk-forward expects
                results = []
                for t in trades:
                    results.append({
                        "pnl": self._parse_float(t.get("net_pnl", "0")),
                        "timestamp": self._parse_float(t.get("timestamp", "0")),
                    })
                wf_results = run_rolling_walk_forward(results)
                ratio = avg_wf_ratio(wf_results) if wf_results else None
                return {
                    "label": "Walk-Forward Ratio (last window)",
                    "ratio": ratio,
                    "status": "computed",
                    "windows": len(wf_results) if wf_results else 0,
                    "alert_threshold": WALK_FORWARD_ALERT,
                }
        except Exception as e:
            logger.warning(f"[DAILY] Walk-forward computation error: {e}")

        return {
            "label": "Walk-Forward Ratio (last window)",
            "ratio": None,
            "status": "insufficient data or module unavailable",
            "alert_threshold": WALK_FORWARD_ALERT,
        }

    def _metric_session_drawdown(self) -> Dict[str, Any]:
        """Metric 4: Current session drawdown percentage.

        Computed from the most recent trade's ``session_dd_pct`` field.
        Falls back to computing from running equity if available.
        """
        trades = self._ledger.get_trades(lookback_days=1)
        dd_pct = 0.0
        if trades:
            latest = trades[0]  # newest first
            dd_str = latest.get("session_dd_pct", "0")
            dd_pct = self._parse_float(dd_str)

            # Fallback: estimate from running equity series
            if dd_pct == 0.0:
                equities = [
                    self._parse_float(t.get("running_equity", "0"))
                    for t in self._ledger.get_trades(lookback_days=7)
                    if self._parse_float(t.get("running_equity", "0")) > 0
                ]
                if len(equities) >= 2:
                    peak = max(equities)
                    current = equities[0]  # newest
                    if peak > 0:
                        dd_pct = round((peak - current) / peak * 100, 2)

        return {
            "label": "Session Drawdown",
            "dd_pct": dd_pct,
            "alert_threshold": SESSION_DD_ALERT,
        }

    def _metric_ic_per_factor(self) -> Dict[str, Any]:
        """Metric 5: Information Coefficient per factor.

        Delegates to the ``ic_tracker`` if provided.  Otherwise returns
        an empty data dict with a note that the tracker is unavailable.
        """
        data: Dict[str, float] = {}
        status = "available"
        if self._ic_tracker is not None:
            try:
                raw = self._ic_tracker.get_report()
                data = {f: info.get("ic", 0.0) for f, info in raw.items() if info.get("ic") is not None}
            except Exception as e:
                logger.warning(f"[DAILY] IC tracker error: {e}")
                status = f"error: {e}"
        else:
            status = "ic_tracker not provided"

        return {
            "label": "IC per Factor",
            "data": data,
            "status": status,
            "alert_threshold": IC_ALERT,
        }

    def _metric_kelly_weights(self) -> Dict[str, Any]:
        """Metric 6: Kelly-optimal weights per factor.

        Delegates to the ``kelly_engine`` if provided.  Otherwise
        returns an empty data dict with a note.
        """
        data: Dict[str, float] = {}
        status = "available"
        if self._kelly_engine is not None:
            try:
                data = self._kelly_engine.get_all_weights()
            except Exception as e:
                logger.warning(f"[DAILY] Kelly engine error: {e}")
                status = f"error: {e}"
        else:
            status = "kelly_engine not provided"

        return {
            "label": "Kelly Weights per Factor",
            "data": data,
            "status": status,
            "alert_threshold": KELLY_ALERT,
        }

    # ── Alerts ────────────────────────────────────────────────────

    def check_alerts(self, report: Dict[str, Any]) -> List[str]:
        """Check all 6 metrics against alert thresholds.

        Args:
            report: The dict returned by ``generate_report()``.

        Returns:
            List of human-readable alert strings.
        """
        alerts: List[str] = []
        metrics = report.get("metrics", {})

        # 1. Agreement WR alerts
        agreement = metrics.get("agreement_wr", {})
        for level, data in agreement.get("data", {}).items():
            wr = data.get("win_rate", 0)
            n = data.get("trades", 0)
            if n >= 3 and wr < AGREEMENT_WR_ALERT:
                alerts.append(
                    f"[AGREEMENT WR] Level {level}: {wr:.1f}% WR "
                    f"({n} trades) — below {AGREEMENT_WR_ALERT}% threshold"
                )

        # 2. Regime WR alerts
        regime = metrics.get("regime_wr", {})
        for reg_name, data in regime.get("data", {}).items():
            wr = data.get("win_rate", 0)
            n = data.get("trades", 0)
            if n >= 3 and wr < REGIME_WR_ALERT:
                alerts.append(
                    f"[REGIME WR] {reg_name}: {wr:.1f}% WR "
                    f"({n} trades) — below {REGIME_WR_ALERT}% threshold"
                )

        # 3. Walk-forward ratio
        wf = metrics.get("walk_forward", {})
        ratio = wf.get("ratio")
        if ratio is not None and ratio < WALK_FORWARD_ALERT:
            alerts.append(
                f"[WALK-FORWARD] Ratio {ratio:.2f} — "
                f"below {WALK_FORWARD_ALERT} threshold"
            )

        # 4. Session drawdown
        dd = metrics.get("session_drawdown", {})
        dd_pct = dd.get("dd_pct", 0)
        if dd_pct > SESSION_DD_ALERT:
            alerts.append(
                f"[DRAWDOWN] Session DD {dd_pct:.1f}% — "
                f"exceeds {SESSION_DD_ALERT}% threshold"
            )

        # 5. IC per factor
        ic = metrics.get("ic_per_factor", {})
        for factor, ic_val in ic.get("data", {}).items():
            if isinstance(ic_val, (int, float)) and ic_val < IC_ALERT:
                alerts.append(
                    f"[IC] Factor '{factor}': IC={ic_val:.4f} — "
                    f"below {IC_ALERT} threshold"
                )

        # 6. Kelly weights
        kelly = metrics.get("kelly_weights", {})
        for factor, weight in kelly.get("data", {}).items():
            if isinstance(weight, (int, float)) and weight < KELLY_ALERT:
                alerts.append(
                    f"[KELLY] Factor '{factor}': weight={weight:.4f} — "
                    f"below {KELLY_ALERT} threshold"
                )

        return alerts

    # ── Recommendations ───────────────────────────────────────────

    def _build_recommendations(
        self, report: Dict[str, Any]
    ) -> List[str]:
        """Generate actionable recommendations from the report metrics."""
        recs: List[str] = []
        metrics = report.get("metrics", {})

        # Agreement WR: suggest tightening if low-agreement trades lose
        agreement = metrics.get("agreement_wr", {}).get("data", {})
        for level, data in agreement.items():
            n = data.get("trades", 0)
            wr = data.get("win_rate", 0)
            if n >= 5 and wr < 40:
                recs.append(
                    f"Raise MIN_VOTES or increase confidence floor for "
                    f"agreement-level-{level} trades (WR={wr:.0f}%)."
                )
            elif n >= 5 and wr >= 60:
                recs.append(
                    f"Agreement-level-{level} is strong ({wr:.0f}% WR) — "
                    f"consider increasing position size for high-agreement setups."
                )

        # Regime: avoid losing regimes
        regime = metrics.get("regime_wr", {}).get("data", {})
        for reg_name, data in regime.items():
            n = data.get("trades", 0)
            wr = data.get("win_rate", 0)
            if n >= 5 and wr < 35:
                recs.append(
                    f"Consider skipping trades in '{reg_name}' regime "
                    f"(WR={wr:.0f}% over {n} trades)."
                )

        # Drawdown
        dd_pct = metrics.get("session_drawdown", {}).get("dd_pct", 0)
        if dd_pct > 10:
            recs.append(
                f"Session DD is elevated at {dd_pct:.1f}%. "
                f"Consider reducing position sizes or pausing new entries."
            )

        # IC: low IC factors
        ic_data = metrics.get("ic_per_factor", {}).get("data", {})
        weak_factors = [
            f for f, v in ic_data.items()
            if isinstance(v, (int, float)) and v < IC_ALERT
        ]
        if weak_factors:
            recs.append(
                f"Low-IC factors ({', '.join(weak_factors)}) — "
                f"consider reducing their ensemble weight."
            )

        # Kelly: negative or near-zero weight
        kelly_data = metrics.get("kelly_weights", {}).get("data", {})
        bad_kelly = [
            f for f, w in kelly_data.items()
            if isinstance(w, (int, float)) and w < KELLY_ALERT
        ]
        if bad_kelly:
            recs.append(
                f"Kelly suggests minimal allocation to: {', '.join(bad_kelly)}. "
                f"Review if these factors still have edge."
            )

        if not recs:
            recs.append("All metrics within normal ranges. No action needed.")

        return recs

    # ── Formatting ────────────────────────────────────────────────

    def format_report(self, report: Dict[str, Any]) -> str:
        """Format the report dict as a human-readable text block.

        Args:
            report: The dict returned by ``generate_report()``.

        Returns:
            Multi-line formatted string.
        """
        lines: List[str] = []
        sep = "=" * 70

        lines.append(sep)
        lines.append("  DAILY AUTOMATED REPORT — 6 KEY METRICS")
        lines.append(f"  Generated: {report.get('generated_at', 'N/A')}")
        lines.append(sep)

        metrics = report.get("metrics", {})

        # ── 1. Agreement WR ───────────────────────────────────────
        lines.append("")
        lines.append("  1. 7d ROLLING WR BY AGREEMENT LEVEL")
        lines.append("  " + "-" * 55)
        agreement = metrics.get("agreement_wr", {}).get("data", {})
        if agreement:
            lines.append(
                f"  {'Level':<12} {'Trades':>7} {'Wins':>6} "
                f"{'WR%':>7} {'PnL':>10}"
            )
            lines.append("  " + "-" * 55)
            for level in sorted(agreement.keys()):
                d = agreement[level]
                lines.append(
                    f"  {level:<12} {d['trades']:>7} {d['wins']:>6} "
                    f"{d['win_rate']:>6.1f}% ${d['total_pnl']:>+9.2f}"
                )
        else:
            lines.append("  No trades in last 7 days.")

        # ── 2. Regime WR ──────────────────────────────────────────
        lines.append("")
        lines.append("  2. 7d ROLLING WR BY REGIME")
        lines.append("  " + "-" * 55)
        regime = metrics.get("regime_wr", {}).get("data", {})
        if regime:
            lines.append(
                f"  {'Regime':<20} {'Trades':>7} {'Wins':>6} "
                f"{'WR%':>7} {'PnL':>10}"
            )
            lines.append("  " + "-" * 55)
            for reg_name in sorted(regime.keys()):
                d = regime[reg_name]
                lines.append(
                    f"  {reg_name:<20} {d['trades']:>7} {d['wins']:>6} "
                    f"{d['win_rate']:>6.1f}% ${d['total_pnl']:>+9.2f}"
                )
        else:
            lines.append("  No trades in last 7 days.")

        # ── 3. Walk-forward ───────────────────────────────────────
        lines.append("")
        lines.append("  3. WALK-FORWARD RATIO")
        lines.append("  " + "-" * 55)
        wf = metrics.get("walk_forward", {})
        ratio = wf.get("ratio")
        if ratio is not None:
            lines.append(f"  Ratio: {ratio:.3f}")
        else:
            lines.append(f"  Status: {wf.get('status', 'N/A')}")

        # ── 4. Session drawdown ───────────────────────────────────
        lines.append("")
        lines.append("  4. SESSION DRAWDOWN")
        lines.append("  " + "-" * 55)
        dd = metrics.get("session_drawdown", {})
        dd_pct = dd.get("dd_pct", 0)
        marker = "!!!" if dd_pct > SESSION_DD_ALERT else ""
        lines.append(f"  Current DD: {dd_pct:.2f}% {marker}")

        # ── 5. IC per factor ──────────────────────────────────────
        lines.append("")
        lines.append("  5. IC PER FACTOR")
        lines.append("  " + "-" * 55)
        ic = metrics.get("ic_per_factor", {})
        ic_data = ic.get("data", {})
        if ic_data:
            for factor, val in sorted(ic_data.items()):
                flag = " <-- LOW" if isinstance(val, (int, float)) and val < IC_ALERT else ""
                lines.append(f"  {factor:<25} IC={val:.4f}{flag}")
        else:
            lines.append(f"  Status: {ic.get('status', 'N/A')}")

        # ── 6. Kelly weights ──────────────────────────────────────
        lines.append("")
        lines.append("  6. KELLY WEIGHTS PER FACTOR")
        lines.append("  " + "-" * 55)
        kelly = metrics.get("kelly_weights", {})
        kelly_data = kelly.get("data", {})
        if kelly_data:
            for factor, weight in sorted(kelly_data.items()):
                flag = " <-- LOW" if isinstance(weight, (int, float)) and weight < KELLY_ALERT else ""
                lines.append(f"  {factor:<25} weight={weight:.4f}{flag}")
        else:
            lines.append(f"  Status: {kelly.get('status', 'N/A')}")

        # ── Alerts ────────────────────────────────────────────────
        alerts = report.get("alerts", [])
        lines.append("")
        lines.append(sep)
        if alerts:
            lines.append(f"  ALERTS ({len(alerts)})")
            lines.append(sep)
            for i, alert in enumerate(alerts, 1):
                lines.append(f"  {i}. {alert}")
        else:
            lines.append("  NO ALERTS — all metrics within thresholds")
            lines.append(sep)

        # ── Recommendations ───────────────────────────────────────
        recs = report.get("recommendations", [])
        if recs:
            lines.append("")
            lines.append("  RECOMMENDATIONS")
            lines.append("  " + "-" * 55)
            for i, rec in enumerate(recs, 1):
                lines.append(f"  {i}. {rec}")

        lines.append("")
        lines.append(sep)
        return "\n".join(lines)

    # ── Utilities ─────────────────────────────────────────────────

    @staticmethod
    def _parse_float(val: str) -> float:
        """Safely parse a float from string."""
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0
