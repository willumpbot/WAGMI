"""
Sniper Optimizer — Continuous improvement for the manual sniper system.

Monitors signal quality, leverage efficiency, timing patterns, and
suggests parameter adjustments over time. Advisory-only: NEVER auto-applies
changes to ManualSniperConfig.

Usage:
    from manual.optimizer import SniperOptimizer
    opt = SniperOptimizer()
    report = opt.generate_weekly_report()
    suggestions = opt.suggest_parameter_changes()
"""

import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("bot.manual.optimizer")

_DATA_DIR = os.path.join("data", "manual")
_SIGNALS_PATH = os.path.join(_DATA_DIR, "sniper_signals.jsonl")
_SIM_TRADES_PATH = os.path.join(_DATA_DIR, "sim_trades.jsonl")
_JOURNAL_PATH = os.path.join(_DATA_DIR, "trade_journal.jsonl")
_REPORTS_DIR = os.path.join(_DATA_DIR, "weekly_reports")


def _load_jsonl(path: str) -> List[Dict[str, Any]]:
    """Load records from a JSONL file, skipping malformed lines."""
    records = []
    if not os.path.exists(path):
        return records
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except Exception as e:
        logger.warning(f"Failed to load {path}: {e}")
    return records


def _parse_ts(ts_str: str) -> Optional[datetime]:
    """Parse an ISO timestamp string, returning None on failure."""
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return None


class SniperOptimizer:
    """
    Continuous optimization engine for the manual sniper system.

    All methods are read-only and advisory. No method modifies config
    or trading parameters automatically.
    """

    def __init__(self):
        self._signals: Optional[List[Dict]] = None
        self._trades: Optional[List[Dict]] = None

    def _get_signals(self) -> List[Dict[str, Any]]:
        if self._signals is None:
            self._signals = _load_jsonl(_SIGNALS_PATH)
        return self._signals

    def _get_trades(self) -> List[Dict[str, Any]]:
        """Load trades from sim_trades or trade_journal (prefer journal)."""
        if self._trades is None:
            trades = _load_jsonl(_JOURNAL_PATH)
            if not trades:
                trades = _load_jsonl(_SIM_TRADES_PATH)
            self._trades = trades
        return self._trades

    def _get_closed_trades(self) -> List[Dict[str, Any]]:
        """Return only closed trades with PnL data."""
        return [
            t for t in self._get_trades()
            if t.get("status", "").upper() == "CLOSED" and t.get("pnl") is not None
        ]

    # ── 1. Signal Quality Analysis ─────────────────────────────────

    def analyze_signal_quality(self) -> Dict[str, Any]:
        """
        Analyze sniper signal generation quality.

        Returns metrics on volume, tier distribution, symbol concentration,
        signal-to-noise ratio, and dedup/cooldown effectiveness.
        """
        signals = self._get_signals()
        if not signals:
            return {
                "status": "cold_start",
                "total_signals": 0,
                "message": "No signals yet. Generate signals first.",
                "recommendations": [],
            }

        total = len(signals)

        # ── Signals per day ──
        daily_counts: Dict[str, int] = defaultdict(int)
        for sig in signals:
            ts = _parse_ts(sig.get("timestamp", ""))
            if ts:
                daily_counts[ts.strftime("%Y-%m-%d")] += 1

        days_active = len(daily_counts) if daily_counts else 1
        avg_per_day = total / days_active
        max_per_day = max(daily_counts.values()) if daily_counts else 0
        min_per_day = min(daily_counts.values()) if daily_counts else 0

        # ── Tier distribution ──
        tier_dist: Dict[str, int] = defaultdict(int)
        for sig in signals:
            tier_dist[sig.get("tier", "UNKNOWN")] += 1
        tier_pcts = {t: round(c / total * 100, 1) for t, c in tier_dist.items()}

        # ── Symbol distribution ──
        symbol_dist: Dict[str, int] = defaultdict(int)
        for sig in signals:
            symbol_dist[sig.get("symbol", "UNKNOWN")] += 1
        symbol_pcts = {s: round(c / total * 100, 1) for s, c in symbol_dist.items()}

        # ── Confidence distribution ──
        confidences = [sig.get("confidence", 0) for sig in signals]
        avg_conf = sum(confidences) / len(confidences) if confidences else 0
        high_conf = sum(1 for c in confidences if c >= 85)
        med_conf = sum(1 for c in confidences if 78 <= c < 85)
        low_conf = sum(1 for c in confidences if c < 78)

        # ── Signal-to-noise ratio ──
        # Ratio of SNIPER+PREMIUM to total; higher = better filtering
        quality_signals = tier_dist.get("SNIPER", 0) + tier_dist.get("PREMIUM", 0)
        snr = quality_signals / total if total > 0 else 0

        # ── Dedup effectiveness (consecutive same symbol+side within cooldown) ──
        potential_dupes = 0
        sorted_sigs = sorted(signals, key=lambda s: s.get("timestamp", ""))
        for i in range(1, len(sorted_sigs)):
            prev = sorted_sigs[i - 1]
            curr = sorted_sigs[i]
            if (prev.get("symbol") == curr.get("symbol") and
                    prev.get("side") == curr.get("side")):
                t1 = _parse_ts(prev.get("timestamp", ""))
                t2 = _parse_ts(curr.get("timestamp", ""))
                if t1 and t2 and (t2 - t1).total_seconds() < 600:
                    potential_dupes += 1

        # ── Recommendations ──
        recs = []
        if avg_per_day > 8:
            recs.append({
                "param": "min_confidence",
                "action": "increase",
                "reason": f"Averaging {avg_per_day:.1f} signals/day — too noisy. Raise min_confidence.",
                "confidence_pct": 80,
            })
        elif avg_per_day < 1 and days_active > 3:
            recs.append({
                "param": "min_confidence",
                "action": "decrease",
                "reason": f"Only {avg_per_day:.1f} signals/day over {days_active} days. Lower min_confidence to capture more.",
                "confidence_pct": 60,
            })

        if snr < 0.3 and total > 10:
            recs.append({
                "param": "min_num_agree",
                "action": "increase",
                "reason": f"Only {snr:.0%} of signals are PREMIUM/SNIPER. Raise min_agree to filter noise.",
                "confidence_pct": 70,
            })

        if potential_dupes > total * 0.15 and total > 10:
            recs.append({
                "param": "dedup_window_s",
                "action": "increase",
                "reason": f"{potential_dupes} potential dupes ({potential_dupes/total:.0%}). Increase dedup window.",
                "confidence_pct": 75,
            })

        return {
            "status": "ok",
            "total_signals": total,
            "days_active": days_active,
            "avg_per_day": round(avg_per_day, 1),
            "max_per_day": max_per_day,
            "min_per_day": min_per_day,
            "tier_distribution": dict(tier_dist),
            "tier_pcts": tier_pcts,
            "symbol_distribution": dict(symbol_dist),
            "symbol_pcts": symbol_pcts,
            "confidence": {
                "avg": round(avg_conf, 1),
                "high_85plus": high_conf,
                "med_78_85": med_conf,
                "low_sub78": low_conf,
            },
            "signal_to_noise": round(snr, 3),
            "potential_dupes": potential_dupes,
            "recommendations": recs,
        }

    # ── 2. Leverage Efficiency Analysis ─────────────────────────────

    def analyze_leverage_efficiency(self) -> Dict[str, Any]:
        """
        Analyze which leverage bands produce the best risk-adjusted returns.

        Groups trades by leverage and stop_width_pct buckets, then computes
        win rate, average PnL, and Sharpe-like ratio per bucket.
        """
        closed = self._get_closed_trades()
        if not closed:
            return {
                "status": "no_trades",
                "message": "No closed trades yet. Need trade data for leverage analysis.",
                "leverage_bands": {},
                "optimal_curve": {},
                "recommendations": [],
            }

        # ── Group by leverage band ──
        lev_bands = {
            "1-10x": (1, 10),
            "10-15x": (10, 15),
            "15-20x": (15, 20),
            "20-25x": (20, 25),
        }
        band_stats: Dict[str, Dict] = {}

        for band_name, (lo, hi) in lev_bands.items():
            band_trades = [
                t for t in closed
                if lo <= t.get("leverage", 0) < hi or (hi == 25 and t.get("leverage", 0) == 25)
            ]
            if not band_trades:
                band_stats[band_name] = {"count": 0, "win_rate": 0, "avg_pnl": 0, "total_pnl": 0}
                continue

            wins = sum(1 for t in band_trades if t.get("pnl", 0) > 0)
            pnls = [t.get("pnl", 0) for t in band_trades]
            total_pnl = sum(pnls)
            avg_pnl = total_pnl / len(pnls)

            # Risk-adjusted: avg_pnl / std_dev (pseudo-Sharpe)
            if len(pnls) > 1:
                mean = avg_pnl
                variance = sum((p - mean) ** 2 for p in pnls) / (len(pnls) - 1)
                std = variance ** 0.5
                sharpe = avg_pnl / std if std > 0 else 0
            else:
                sharpe = 0

            band_stats[band_name] = {
                "count": len(band_trades),
                "win_rate": round(wins / len(band_trades), 3),
                "avg_pnl": round(avg_pnl, 2),
                "total_pnl": round(total_pnl, 2),
                "sharpe": round(sharpe, 3),
            }

        # ── Optimal leverage by stop width bucket ──
        # Group by stop_width_pct ranges
        sw_buckets = {
            "tight_0.5-1%": (0.5, 1.0),
            "normal_1-2%": (1.0, 2.0),
            "wide_2-3%": (2.0, 3.0),
            "very_wide_3%+": (3.0, 100.0),
        }
        optimal_curve: Dict[str, Dict] = {}

        for bucket_name, (lo, hi) in sw_buckets.items():
            bucket_trades = []
            for t in closed:
                entry = t.get("entry_price", t.get("entry", 0))
                sl = t.get("sl", 0)
                if entry > 0 and sl > 0:
                    sw_pct = abs(entry - sl) / entry * 100
                    if lo <= sw_pct < hi:
                        bucket_trades.append(t)

            if not bucket_trades:
                optimal_curve[bucket_name] = {"count": 0, "best_leverage": None}
                continue

            # Find best leverage in this bucket
            by_lev: Dict[float, List[float]] = defaultdict(list)
            for t in bucket_trades:
                lev = t.get("leverage", 1)
                by_lev[lev].append(t.get("pnl", 0))

            best_lev = None
            best_avg = float("-inf")
            for lev, pnls in by_lev.items():
                avg = sum(pnls) / len(pnls) if pnls else 0
                if avg > best_avg and len(pnls) >= 2:
                    best_avg = avg
                    best_lev = lev

            optimal_curve[bucket_name] = {
                "count": len(bucket_trades),
                "best_leverage": best_lev,
                "best_avg_pnl": round(best_avg, 2) if best_lev else None,
            }

        # ── Recommendations ──
        recs = []
        # Find the band with best Sharpe
        best_band = None
        best_sharpe = 0
        worst_band = None
        worst_sharpe = float("inf")
        for band_name, stats in band_stats.items():
            if stats["count"] >= 3:
                if stats["sharpe"] > best_sharpe:
                    best_sharpe = stats["sharpe"]
                    best_band = band_name
                if stats["sharpe"] < worst_sharpe:
                    worst_sharpe = stats["sharpe"]
                    worst_band = band_name

        if best_band and worst_band and best_band != worst_band:
            recs.append({
                "action": f"Favor {best_band} leverage (Sharpe={best_sharpe:.2f}), "
                          f"reduce {worst_band} exposure (Sharpe={worst_sharpe:.2f})",
                "confidence_pct": min(90, 40 + band_stats[best_band]["count"] * 5),
            })

        return {
            "status": "ok",
            "total_closed": len(closed),
            "leverage_bands": band_stats,
            "optimal_curve": optimal_curve,
            "recommendations": recs,
        }

    # ── 3. Timing Analysis ──────────────────────────────────────────

    def analyze_timing(self) -> Dict[str, Any]:
        """
        Analyze when signals are generated and when winners/losers cluster.

        Provides hour-of-day distributions and recommends optimal check-in times.
        """
        signals = self._get_signals()
        closed = self._get_closed_trades()

        if not signals:
            return {
                "status": "cold_start",
                "message": "No signals yet.",
                "hour_distribution": {},
                "recommendations": [],
            }

        # ── Signal hour distribution ──
        hour_counts: Dict[int, int] = defaultdict(int)
        for sig in signals:
            ts = _parse_ts(sig.get("timestamp", ""))
            if ts:
                hour_counts[ts.hour] += 1

        # ── Winner/loser hour distribution (from trades) ──
        win_hours: Dict[int, int] = defaultdict(int)
        loss_hours: Dict[int, int] = defaultdict(int)

        for t in closed:
            ts = _parse_ts(t.get("entry_time", t.get("timestamp", "")))
            if not ts:
                continue
            if t.get("pnl", 0) > 0:
                win_hours[ts.hour] += 1
            else:
                loss_hours[ts.hour] += 1

        # ── Day-of-week distribution ──
        dow_counts: Dict[str, int] = defaultdict(int)
        dow_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        for sig in signals:
            ts = _parse_ts(sig.get("timestamp", ""))
            if ts:
                dow_counts[dow_names[ts.weekday()]] += 1

        # ── Identify hot/cold hours ──
        if hour_counts:
            total_signals = sum(hour_counts.values())
            avg_per_hour = total_signals / 24
            hot_hours = sorted(
                [h for h, c in hour_counts.items() if c > avg_per_hour * 1.5],
                key=lambda h: hour_counts[h], reverse=True
            )
            cold_hours = [h for h in range(24) if hour_counts.get(h, 0) == 0]
        else:
            hot_hours = []
            cold_hours = list(range(24))

        # ── Win rate by hour ──
        hourly_wr: Dict[int, float] = {}
        for h in range(24):
            w = win_hours.get(h, 0)
            l = loss_hours.get(h, 0)
            if w + l >= 2:
                hourly_wr[h] = round(w / (w + l), 3)

        # Best hours for winning
        best_hours = sorted(hourly_wr.keys(), key=lambda h: hourly_wr[h], reverse=True)[:5]
        worst_hours = sorted(hourly_wr.keys(), key=lambda h: hourly_wr[h])[:3]

        # ── Recommendations ──
        recs = []
        if hot_hours:
            recs.append({
                "action": f"Peak signal hours (UTC): {', '.join(f'{h:02d}:00' for h in hot_hours[:5])}",
                "type": "check_in",
                "confidence_pct": 70,
            })
        if best_hours and hourly_wr:
            recs.append({
                "action": f"Best win-rate hours (UTC): {', '.join(f'{h:02d}:00 ({hourly_wr[h]:.0%})' for h in best_hours[:3])}",
                "type": "priority",
                "confidence_pct": min(85, 40 + len(closed) * 2),
            })
        if worst_hours and hourly_wr:
            bad = [h for h in worst_hours if hourly_wr.get(h, 1) < 0.4]
            if bad:
                recs.append({
                    "action": f"Avoid hours (UTC): {', '.join(f'{h:02d}:00 ({hourly_wr[h]:.0%})' for h in bad)}",
                    "type": "avoid",
                    "confidence_pct": min(75, 30 + len(closed) * 2),
                })

        return {
            "status": "ok",
            "total_signals": len(signals),
            "total_closed_trades": len(closed),
            "hour_distribution": dict(hour_counts),
            "day_of_week": dict(dow_counts),
            "hot_hours": hot_hours,
            "cold_hours": cold_hours[:8],
            "hourly_win_rate": hourly_wr,
            "best_win_hours": best_hours,
            "worst_win_hours": worst_hours,
            "recommendations": recs,
        }

    # ── 4. Weekly Report Generation ─────────────────────────────────

    def generate_weekly_report(self) -> str:
        """
        Generate a comprehensive weekly optimization report.

        Combines signal quality, leverage efficiency, and timing analyses
        into a single markdown report. Saves to data/manual/weekly_reports/.
        Returns the report as a string.
        """
        quality = self.analyze_signal_quality()
        leverage = self.analyze_leverage_efficiency()
        timing = self.analyze_timing()
        suggestions = self.suggest_parameter_changes()

        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y_%m_%d")
        week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")

        lines = [
            f"# Sniper Optimizer Report — {now.strftime('%Y-%m-%d %H:%M UTC')}",
            f"Week of {week_start}",
            "",
            "---",
            "",
            "## Signal Quality",
            "",
        ]

        if quality["status"] == "cold_start":
            lines.append("No signals generated yet. Waiting for data.")
        else:
            lines.extend([
                f"- **Total signals**: {quality['total_signals']}",
                f"- **Days active**: {quality['days_active']}",
                f"- **Avg signals/day**: {quality['avg_per_day']}",
                f"- **Signal-to-noise ratio**: {quality['signal_to_noise']:.1%}",
                f"- **Avg confidence**: {quality['confidence']['avg']:.1f}",
                f"- **Potential dupes**: {quality['potential_dupes']}",
                "",
                "### Tier Distribution",
            ])
            for tier, count in quality.get("tier_distribution", {}).items():
                pct = quality["tier_pcts"].get(tier, 0)
                lines.append(f"- {tier}: {count} ({pct}%)")

            lines.extend(["", "### Symbol Distribution"])
            for sym, count in quality.get("symbol_distribution", {}).items():
                pct = quality["symbol_pcts"].get(sym, 0)
                lines.append(f"- {sym}: {count} ({pct}%)")

        lines.extend(["", "---", "", "## Leverage Efficiency", ""])

        if leverage["status"] == "no_trades":
            lines.append("No closed trades yet. Need trade data for leverage analysis.")
        else:
            lines.extend([
                f"- **Total closed trades**: {leverage['total_closed']}",
                "",
                "### Performance by Leverage Band",
                "",
                "| Band | Trades | Win Rate | Avg PnL | Total PnL | Sharpe |",
                "|------|--------|----------|---------|-----------|--------|",
            ])
            for band, stats in leverage["leverage_bands"].items():
                if stats["count"] > 0:
                    lines.append(
                        f"| {band} | {stats['count']} | {stats['win_rate']:.0%} | "
                        f"${stats['avg_pnl']:+.2f} | ${stats['total_pnl']:+.2f} | "
                        f"{stats['sharpe']:.2f} |"
                    )

            lines.extend(["", "### Optimal Leverage by Stop Width"])
            for bucket, data in leverage["optimal_curve"].items():
                if data["count"] > 0 and data["best_leverage"]:
                    lines.append(
                        f"- {bucket}: best at {data['best_leverage']}x "
                        f"(avg PnL ${data['best_avg_pnl']:+.2f}, n={data['count']})"
                    )

        lines.extend(["", "---", "", "## Timing Analysis", ""])

        if timing["status"] == "cold_start":
            lines.append("No signals yet.")
        else:
            lines.extend([
                f"- **Total signals analyzed**: {timing['total_signals']}",
                f"- **Closed trades with timing**: {timing['total_closed_trades']}",
                "",
            ])

            if timing["hot_hours"]:
                hours_str = ", ".join(f"{h:02d}:00" for h in timing["hot_hours"][:6])
                lines.append(f"**Peak signal hours (UTC)**: {hours_str}")

            if timing["hourly_win_rate"]:
                lines.extend(["", "### Win Rate by Hour (UTC)", ""])
                for h in sorted(timing["hourly_win_rate"].keys()):
                    wr = timing["hourly_win_rate"][h]
                    bar = "+" * int(wr * 10)
                    lines.append(f"- {h:02d}:00 — {wr:.0%} {bar}")

            if timing.get("day_of_week"):
                lines.extend(["", "### Signals by Day of Week"])
                for day, count in timing["day_of_week"].items():
                    lines.append(f"- {day}: {count}")

        # ── Parameter suggestions ──
        lines.extend(["", "---", "", "## Parameter Recommendations", ""])

        if not suggestions:
            lines.append("No parameter changes suggested (need more data).")
        else:
            for param, info in suggestions.items():
                lines.extend([
                    f"### `{param}`: {info['current']} -> {info['suggested']}",
                    f"- Reason: {info['reason']}",
                    f"- Confidence: {info['confidence_pct']}%",
                    f"- Data backing: {info.get('data_points', 'N/A')} data points",
                    "",
                ])

        # ── Collect all recommendations ──
        all_recs = (
            quality.get("recommendations", []) +
            leverage.get("recommendations", []) +
            timing.get("recommendations", [])
        )
        if all_recs:
            lines.extend(["---", "", "## All Observations", ""])
            for i, rec in enumerate(all_recs, 1):
                conf = rec.get("confidence_pct", "?")
                lines.append(f"{i}. [{conf}%] {rec.get('reason', rec.get('action', ''))}")

        lines.extend(["", "---", f"_Generated {now.isoformat()}_", ""])

        report = "\n".join(lines)

        # Save to file
        try:
            os.makedirs(_REPORTS_DIR, exist_ok=True)
            report_path = os.path.join(_REPORTS_DIR, f"report_{date_str}.md")
            with open(report_path, "w") as f:
                f.write(report)
            logger.info(f"Weekly report saved to {report_path}")
        except Exception as e:
            logger.warning(f"Failed to save weekly report: {e}")

        return report

    # ── 5. Parameter Change Suggestions ─────────────────────────────

    def suggest_parameter_changes(self) -> Dict[str, Dict[str, Any]]:
        """
        Based on accumulated data, suggest changes to ManualSniperConfig.

        Returns dict of parameter -> {current, suggested, reason, confidence_pct, data_points}.
        NEVER auto-applies changes.
        """
        from manual.config import ManualSniperConfig
        config = ManualSniperConfig()

        signals = self._get_signals()
        closed = self._get_closed_trades()

        suggestions: Dict[str, Dict[str, Any]] = {}

        if not signals:
            return suggestions

        total_signals = len(signals)

        # ── min_confidence adjustment ──
        confidences = [s.get("confidence", 0) for s in signals]
        avg_conf = sum(confidences) / len(confidences) if confidences else 0

        if closed:
            # Compare win rates at different confidence thresholds
            high_conf_trades = [
                t for t in closed
                if t.get("confidence", 0) >= 85
            ]
            med_conf_trades = [
                t for t in closed
                if 78 <= t.get("confidence", 0) < 85
            ]

            high_wr = (
                sum(1 for t in high_conf_trades if t.get("pnl", 0) > 0) / len(high_conf_trades)
                if high_conf_trades else 0
            )
            med_wr = (
                sum(1 for t in med_conf_trades if t.get("pnl", 0) > 0) / len(med_conf_trades)
                if med_conf_trades else 0
            )

            # If medium-confidence trades are significantly worse, raise threshold
            if len(med_conf_trades) >= 5 and med_wr < 0.4 and high_wr > med_wr + 0.15:
                suggestions["min_confidence"] = {
                    "current": config.min_confidence,
                    "suggested": 85.0,
                    "reason": f"Medium-conf trades ({med_wr:.0%} WR) much worse than high-conf ({high_wr:.0%} WR). Tighten filter.",
                    "confidence_pct": min(85, 40 + len(med_conf_trades) * 3),
                    "data_points": len(med_conf_trades) + len(high_conf_trades),
                }
            # If medium-confidence trades are solid, could lower threshold
            elif len(med_conf_trades) >= 5 and med_wr > 0.6:
                suggestions["min_confidence"] = {
                    "current": config.min_confidence,
                    "suggested": max(75.0, config.min_confidence - 3),
                    "reason": f"Medium-conf trades have {med_wr:.0%} WR — solid. Can capture more signals.",
                    "confidence_pct": min(70, 30 + len(med_conf_trades) * 2),
                    "data_points": len(med_conf_trades),
                }

        # ── risk_pct_sniper adjustment ──
        if closed:
            sniper_trades = [t for t in closed if t.get("tier", "").upper() == "SNIPER"]
            if len(sniper_trades) >= 5:
                sniper_wr = (
                    sum(1 for t in sniper_trades if t.get("pnl", 0) > 0) / len(sniper_trades)
                )
                avg_sniper_pnl = sum(t.get("pnl", 0) for t in sniper_trades) / len(sniper_trades)

                if sniper_wr > 0.75 and avg_sniper_pnl > 0:
                    # Winning a lot, could size up
                    new_risk = min(0.15, config.risk_pct_sniper + 0.02)
                    if new_risk != config.risk_pct_sniper:
                        suggestions["risk_pct_sniper"] = {
                            "current": config.risk_pct_sniper,
                            "suggested": new_risk,
                            "reason": f"SNIPER trades at {sniper_wr:.0%} WR, avg PnL ${avg_sniper_pnl:+.2f}. Edge supports larger sizing.",
                            "confidence_pct": min(80, 35 + len(sniper_trades) * 3),
                            "data_points": len(sniper_trades),
                        }
                elif sniper_wr < 0.5 and len(sniper_trades) >= 8:
                    # Losing, reduce size
                    new_risk = max(0.05, config.risk_pct_sniper - 0.02)
                    if new_risk != config.risk_pct_sniper:
                        suggestions["risk_pct_sniper"] = {
                            "current": config.risk_pct_sniper,
                            "suggested": new_risk,
                            "reason": f"SNIPER trades only {sniper_wr:.0%} WR. Reduce risk until edge recovers.",
                            "confidence_pct": min(85, 40 + len(sniper_trades) * 3),
                            "data_points": len(sniper_trades),
                        }

        # ── Leverage adjustment ──
        if closed:
            lev_pnls: Dict[str, List[float]] = defaultdict(list)
            for t in closed:
                lev = t.get("leverage", 0)
                if lev >= 20:
                    lev_pnls["high_20plus"].append(t.get("pnl", 0))
                elif lev >= 10:
                    lev_pnls["med_10_20"].append(t.get("pnl", 0))
                else:
                    lev_pnls["low_sub10"].append(t.get("pnl", 0))

            high_pnls = lev_pnls.get("high_20plus", [])
            med_pnls = lev_pnls.get("med_10_20", [])

            if len(high_pnls) >= 5 and len(med_pnls) >= 5:
                high_avg = sum(high_pnls) / len(high_pnls)
                med_avg = sum(med_pnls) / len(med_pnls)

                if high_avg < 0 and med_avg > high_avg:
                    suggestions["max_leverage"] = {
                        "current": config.max_leverage,
                        "suggested": 20.0,
                        "reason": f"20x+ trades avg ${high_avg:+.2f} vs 10-20x avg ${med_avg:+.2f}. Cap leverage lower.",
                        "confidence_pct": min(80, 35 + len(high_pnls) * 2),
                        "data_points": len(high_pnls) + len(med_pnls),
                    }

        # ── Signal volume (max_daily_signals) ──
        daily_counts: Dict[str, int] = defaultdict(int)
        for sig in signals:
            ts = _parse_ts(sig.get("timestamp", ""))
            if ts:
                daily_counts[ts.strftime("%Y-%m-%d")] += 1

        if daily_counts:
            avg_daily = sum(daily_counts.values()) / len(daily_counts)
            if avg_daily > config.max_daily_signals * 1.5:
                suggestions["max_daily_signals"] = {
                    "current": config.max_daily_signals,
                    "suggested": max(3, config.max_daily_signals - 1),
                    "reason": f"Averaging {avg_daily:.1f} signals/day vs limit {config.max_daily_signals}. Signals may be too loose.",
                    "confidence_pct": 60,
                    "data_points": len(daily_counts),
                }

        return suggestions

    # ── Telegram-friendly summary ──────────────────────────────────

    def format_telegram_summary(self) -> str:
        """Format a concise optimization summary for Telegram (max ~20 lines)."""
        quality = self.analyze_signal_quality()
        leverage = self.analyze_leverage_efficiency()
        timing = self.analyze_timing()
        suggestions = self.suggest_parameter_changes()

        lines = [
            "=== SNIPER OPTIMIZER ===",
            "",
        ]

        # Signal quality score
        if quality["status"] == "cold_start":
            lines.append("Signals: No data yet")
        else:
            snr = quality["signal_to_noise"]
            grade = "A" if snr > 0.7 else "B" if snr > 0.5 else "C" if snr > 0.3 else "D"
            lines.append(
                f"Signal Quality: {grade} (SNR {snr:.0%}, "
                f"{quality['avg_per_day']:.1f}/day, "
                f"{quality['total_signals']} total)"
            )

        # Leverage efficiency
        if leverage["status"] != "no_trades":
            best_band = None
            best_sharpe = 0
            for band, stats in leverage["leverage_bands"].items():
                if stats["count"] >= 2 and stats["sharpe"] > best_sharpe:
                    best_sharpe = stats["sharpe"]
                    best_band = band
            if best_band:
                bs = leverage["leverage_bands"][best_band]
                lines.append(
                    f"Best Leverage: {best_band} "
                    f"(WR {bs['win_rate']:.0%}, Sharpe {bs['sharpe']:.2f})"
                )
        else:
            lines.append("Leverage: No trade data yet")

        # Timing
        if timing["status"] != "cold_start" and timing.get("hot_hours"):
            top3 = timing["hot_hours"][:3]
            lines.append(f"Peak Hours (UTC): {', '.join(f'{h:02d}:00' for h in top3)}")

        # Top 3 suggestions
        if suggestions:
            lines.extend(["", "Recommendations:"])
            for i, (param, info) in enumerate(
                sorted(suggestions.items(), key=lambda x: x[1]["confidence_pct"], reverse=True)[:3],
                1
            ):
                lines.append(
                    f"{i}. {param}: {info['current']} -> {info['suggested']} "
                    f"[{info['confidence_pct']}%]"
                )
                lines.append(f"   {info['reason'][:80]}")
        else:
            lines.append("\nNo changes suggested (need more data)")

        return "\n".join(lines)
