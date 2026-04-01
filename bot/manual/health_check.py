"""
Manual Sniper System Health Check.

Quick diagnostic for the babysit terminal or manual inspection.
Checks: data freshness, file integrity, sim state, error rates.

Usage:
    cd bot && python -m manual.health_check          # Full check
    cd bot && python -m manual.health_check --quick   # Quick check
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

logger = logging.getLogger("bot.manual.health_check")

_DATA_DIR = os.path.join("data", "manual")
_SIGNALS_PATH = os.path.join(_DATA_DIR, "sniper_signals.jsonl")
_SIM_TRADES_PATH = os.path.join(_DATA_DIR, "sim_trades.jsonl")
_SIM_STATUS_PATH = os.path.join(_DATA_DIR, "sim_status.json")
_JOURNAL_PATH = os.path.join(_DATA_DIR, "trade_journal.jsonl")
_EQUITY_PATH = os.path.join(_DATA_DIR, "equity_state.json")


class HealthStatus:
    """Aggregated health check result."""

    def __init__(self):
        self.checks: List[Dict[str, Any]] = []
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def add_check(self, name: str, status: str, detail: str = ""):
        """Add a check result. status: OK, WARN, ERROR, CRITICAL."""
        self.checks.append({"name": name, "status": status, "detail": detail})
        if status == "ERROR" or status == "CRITICAL":
            self.errors.append(f"{name}: {detail}")
        elif status == "WARN":
            self.warnings.append(f"{name}: {detail}")

    @property
    def overall(self) -> str:
        if any(c["status"] == "CRITICAL" for c in self.checks):
            return "CRITICAL"
        if any(c["status"] == "ERROR" for c in self.checks):
            return "ERROR"
        if any(c["status"] == "WARN" for c in self.checks):
            return "WARN"
        return "OK"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall": self.overall,
            "checks": self.checks,
            "errors": self.errors,
            "warnings": self.warnings,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def format(self) -> str:
        """Format as human-readable report."""
        status_icons = {"OK": "[OK]", "WARN": "[!!]", "ERROR": "[XX]", "CRITICAL": "[!!]"}
        lines = [
            "=" * 40,
            f"  SNIPER HEALTH CHECK — {self.overall}",
            "=" * 40,
            "",
        ]
        for check in self.checks:
            icon = status_icons.get(check["status"], "[??]")
            lines.append(f"  {icon} {check['name']}: {check['detail']}")

        if self.errors:
            lines.extend(["", "  ERRORS:"])
            for err in self.errors:
                lines.append(f"    - {err}")
        if self.warnings:
            lines.extend(["", "  WARNINGS:"])
            for warn in self.warnings:
                lines.append(f"    - {warn}")

        lines.append("")
        lines.append("=" * 40)
        return "\n".join(lines)

    def format_telegram(self) -> str:
        """Compact format for Telegram (max ~10 lines)."""
        icon = {"OK": "OK", "WARN": "WARN", "ERROR": "ERR", "CRITICAL": "CRIT"}
        lines = [f"HEALTH: {self.overall}"]
        for check in self.checks:
            if check["status"] != "OK":
                lines.append(f"  {icon.get(check['status'], '?')} {check['name']}: {check['detail']}")
        if not self.errors and not self.warnings:
            lines.append("  All checks passed")
        return "\n".join(lines)


def _file_age_minutes(path: str) -> Optional[float]:
    """Get age of a file in minutes. None if file doesn't exist."""
    if not os.path.exists(path):
        return None
    try:
        mtime = os.path.getmtime(path)
        return (time.time() - mtime) / 60.0
    except OSError:
        return None


def _count_jsonl_lines(path: str) -> int:
    """Count valid JSONL lines in a file."""
    if not os.path.exists(path):
        return 0
    count = 0
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        json.loads(line)
                        count += 1
                    except json.JSONDecodeError:
                        pass
    except Exception:
        pass
    return count


def _last_jsonl_entry(path: str) -> Optional[Dict]:
    """Get the last valid entry from a JSONL file."""
    if not os.path.exists(path):
        return None
    last = None
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        last = json.loads(line)
                    except json.JSONDecodeError:
                        pass
    except Exception:
        pass
    return last


def run_health_check(quick: bool = False) -> HealthStatus:
    """
    Run health checks on the manual sniper system.

    Args:
        quick: If True, skip slow checks.

    Returns:
        HealthStatus with all check results.
    """
    health = HealthStatus()

    # ── 1. Data directory exists ──
    if os.path.exists(_DATA_DIR):
        health.add_check("data_dir", "OK", f"{_DATA_DIR} exists")
    else:
        health.add_check("data_dir", "CRITICAL", f"{_DATA_DIR} missing — no data directory")
        return health

    # ── 2. Signal log ──
    signal_count = _count_jsonl_lines(_SIGNALS_PATH)
    signal_age = _file_age_minutes(_SIGNALS_PATH)
    if signal_count == 0:
        health.add_check("signal_log", "WARN", "No signals logged yet")
    elif signal_age is not None and signal_age > 120:
        health.add_check("signal_log", "WARN",
                         f"{signal_count} signals, last update {signal_age:.0f}m ago (stale >2h)")
    else:
        age_str = f"{signal_age:.0f}m ago" if signal_age else "unknown age"
        health.add_check("signal_log", "OK", f"{signal_count} signals, last update {age_str}")

    # ── 2b. Rejection log ──
    rejection_path = os.path.join(_DATA_DIR, "sniper_rejections.jsonl")
    rejection_count = _count_jsonl_lines(rejection_path)
    if rejection_count > 0 and signal_count > 0:
        ratio = rejection_count / (rejection_count + signal_count)
        if ratio > 0.98:
            health.add_check("rejections", "WARN",
                             f"{rejection_count} rejections vs {signal_count} signals ({ratio:.0%} reject rate — filter may be too strict)")
        else:
            health.add_check("rejections", "OK",
                             f"{rejection_count} rejections, {signal_count} signals ({ratio:.0%} reject rate)")
    elif rejection_count > 0:
        health.add_check("rejections", "OK", f"{rejection_count} rejections logged")

    # ── 3. Sim status ──
    if os.path.exists(_SIM_STATUS_PATH):
        try:
            with open(_SIM_STATUS_PATH) as f:
                sim = json.load(f)
            equity = sim.get("current_equity", 0)
            trades = sim.get("total_trades", 0)
            wr = sim.get("win_rate", 0)
            open_pos = len(sim.get("open_positions", []))

            if equity <= 0:
                health.add_check("sim_equity", "ERROR", f"Equity ${equity:.2f} — blown up")
            elif equity < 50:
                health.add_check("sim_equity", "WARN", f"Equity ${equity:.2f} — low")
            else:
                health.add_check("sim_equity", "OK", f"${equity:.2f} ({trades} trades, {wr:.0f}% WR)")

            health.add_check("sim_positions", "OK" if open_pos <= 3 else "WARN",
                             f"{open_pos} open positions")
        except (json.JSONDecodeError, Exception) as e:
            health.add_check("sim_status", "ERROR", f"Corrupted: {e}")
    else:
        health.add_check("sim_status", "WARN", "No sim status file")

    # ── 4. Trade journal ──
    journal_count = _count_jsonl_lines(_JOURNAL_PATH)
    if journal_count > 0:
        last_trade = _last_jsonl_entry(_JOURNAL_PATH)
        status = last_trade.get("status", "?") if last_trade else "?"
        health.add_check("journal", "OK", f"{journal_count} entries, last: {status}")
    else:
        health.add_check("journal", "OK", "No manual trades logged yet (expected pre-live)")

    # ── 5. Equity state ──
    if os.path.exists(_EQUITY_PATH):
        try:
            with open(_EQUITY_PATH) as f:
                eq = json.load(f)
            current = eq.get("current_equity", 0)
            health.add_check("equity_state", "OK", f"${current:.2f}")
        except Exception as e:
            health.add_check("equity_state", "ERROR", f"Corrupted: {e}")
    else:
        health.add_check("equity_state", "OK", "Not created yet (pre-live)")

    # ── 6. File integrity ──
    for name, path in [
        ("signals", _SIGNALS_PATH),
        ("sim_trades", _SIM_TRADES_PATH),
        ("journal", _JOURNAL_PATH),
    ]:
        if os.path.exists(path):
            try:
                size = os.path.getsize(path)
                if size == 0:
                    health.add_check(f"file_{name}", "WARN", "Empty file")
                else:
                    health.add_check(f"file_{name}", "OK", f"{size:,} bytes")
            except OSError as e:
                health.add_check(f"file_{name}", "ERROR", f"Cannot read: {e}")

    # ── 7. Config sanity ──
    if not quick:
        try:
            from manual.config import ManualSniperConfig
            config = ManualSniperConfig()
            issues = []
            if config.max_leverage > 50:
                issues.append(f"max_leverage={config.max_leverage} (dangerous)")
            if config.risk_pct_sniper > 0.20:
                issues.append(f"risk_pct_sniper={config.risk_pct_sniper} (>20% per trade)")
            if config.equity <= 0:
                issues.append(f"equity={config.equity} (invalid)")

            if issues:
                health.add_check("config", "WARN", "; ".join(issues))
            else:
                health.add_check("config", "OK",
                                 f"mode={config.mode}, equity=${config.equity:.0f}, "
                                 f"max_lev={config.max_leverage}x")
        except Exception as e:
            health.add_check("config", "ERROR", f"Config load failed: {e}")

    # ── 8. Disk space ──
    try:
        import shutil
        usage = shutil.disk_usage(os.path.dirname(os.path.abspath(_DATA_DIR)))
        free_gb = usage.free / (1024 ** 3)
        if free_gb < 1:
            health.add_check("disk", "WARN", f"Only {free_gb:.1f}GB free")
        else:
            health.add_check("disk", "OK", f"{free_gb:.1f}GB free")
    except Exception:
        health.add_check("disk", "OK", "Could not check")

    return health


def get_rejection_summary() -> Dict[str, Any]:
    """Analyze rejection patterns from sniper_rejections.jsonl."""
    rejection_path = os.path.join(_DATA_DIR, "sniper_rejections.jsonl")
    if not os.path.exists(rejection_path):
        return {"total": 0, "by_reason": {}, "by_symbol": {}}

    from collections import Counter, defaultdict
    reasons = Counter()
    by_symbol = defaultdict(int)

    try:
        with open(rejection_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    reason = d.get("reason", "unknown")
                    # Normalize variable reasons
                    for prefix in ("low_confidence_", "chop_too_high_", "low_rr_",
                                   "setup_high_conf_", "setup_low_conf_", "weak_regime_",
                                   "low_consensus_", "near_high_", "already_dipped_"):
                        if reason.startswith(prefix):
                            reason = prefix.rstrip("_")
                            break
                    reasons[reason] += 1
                    by_symbol[d.get("symbol", "?")] += 1
                except (json.JSONDecodeError, TypeError):
                    continue
    except Exception:
        pass

    return {
        "total": sum(reasons.values()),
        "by_reason": dict(reasons.most_common(10)),
        "by_symbol": dict(Counter(by_symbol).most_common(10)),
    }


def main():
    """CLI entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Sniper System Health Check")
    parser.add_argument("--quick", action="store_true", help="Quick check only")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--rejections", action="store_true", help="Show rejection analysis")
    args = parser.parse_args()

    # Ensure bot/ is on path
    bot_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if bot_dir not in sys.path:
        sys.path.insert(0, bot_dir)

    if args.rejections:
        summary = get_rejection_summary()
        print(f"\nRejection Analysis ({summary['total']} total)")
        print("-" * 40)
        if summary["by_reason"]:
            print("By reason:")
            for reason, count in summary["by_reason"].items():
                print(f"  {count:4d}  {reason}")
        if summary["by_symbol"]:
            print("\nBy symbol:")
            for sym, count in summary["by_symbol"].items():
                print(f"  {sym}: {count}")
        return

    health = run_health_check(quick=args.quick)

    if args.json:
        print(json.dumps(health.to_dict(), indent=2))
    else:
        print(health.format())

    # Exit code: 0=OK, 1=WARN, 2=ERROR/CRITICAL
    if health.overall in ("ERROR", "CRITICAL"):
        sys.exit(2)
    elif health.overall == "WARN":
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
