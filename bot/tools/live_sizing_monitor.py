#!/usr/bin/env python3
"""
Live Sizing Monitor — Autonomous data collection companion for the bot.

Monitors every signal generated, tracks sizing decisions, rejections, and
compares actual sizing vs full Kelly sizing. Outputs periodic reports.

Usage:
    cd bot && python tools/live_sizing_monitor.py [--interval 60] [--output data/monitoring]
"""

import argparse
import csv
import json
import logging
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add bot to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# trade_events.jsonl is ~93-95% fabricated PnL mass unless filtered (pytest
# fixtures, backtest-in-process runs, dormant symbol trials) — see
# core.structured_logging.is_fake_trade_event for the full explanation.
try:
    from core.structured_logging import is_fake_trade_event
except Exception:
    def is_fake_trade_event(evt):  # fail open rather than crash the monitor
        return False

try:
    from core.close_taxonomy import CLOSE_EVENT_TYPES
except Exception:
    # Fail open to the pre-fix (undercounting) behavior rather than crash.
    CLOSE_EVENT_TYPES = frozenset({"TRADE_CLOSED"})

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sizing_monitor")


class SizingMonitor:
    """Monitors bot data files and produces sizing analysis reports."""

    def __init__(self, data_dir: str = "data", output_dir: str = "data/monitoring"):
        self.data_dir = Path(data_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Track file positions for incremental reading
        self._file_positions = {}
        self._session_start = datetime.now(timezone.utc)

        # Accumulators
        self.signals_generated = 0
        self.signals_passed = 0
        self.signals_rejected = 0
        self.rejection_reasons = defaultdict(int)
        self.sizing_decisions = []
        self.trades_opened = 0
        self.trades_closed = 0
        self.pnl_total = 0.0

        # Per-symbol tracking
        self.symbol_signals = defaultdict(int)
        self.symbol_rejections = defaultdict(int)
        self.symbol_passes = defaultdict(int)

        # Sizing analysis
        self.sizing_events = []  # {symbol, side, conf, lev, risk_mult, risk_usd, position_usd}

    def read_new_lines(self, filepath: Path) -> list:
        """Read new lines since last check."""
        path_str = str(filepath)
        if not filepath.exists():
            return []

        current_size = filepath.stat().st_size
        last_pos = self._file_positions.get(path_str, 0)

        if current_size <= last_pos:
            return []

        lines = []
        try:
            with open(filepath, "r") as f:
                f.seek(last_pos)
                for line in f:
                    line = line.strip()
                    if line:
                        lines.append(line)
                self._file_positions[path_str] = f.tell()
        except Exception as e:
            logger.debug(f"Error reading {filepath}: {e}")

        return lines

    def process_trade_events(self):
        """Read new trade events."""
        lines = self.read_new_lines(self.data_dir / "trade_events.jsonl")
        for line in lines:
            try:
                event = json.loads(line)
                if is_fake_trade_event(event):
                    continue
                evt_type = event.get("event", "")
                symbol = event.get("symbol", "?")

                if evt_type == "SIGNAL_GENERATED":
                    self.signals_generated += 1
                    self.symbol_signals[symbol] += 1

                elif evt_type == "SIGNAL_PASSED":
                    self.signals_passed += 1
                    self.symbol_passes[symbol] += 1

                elif evt_type == "SIGNAL_REJECTED":
                    self.signals_rejected += 1
                    reason = event.get("reason", "unknown")
                    self.rejection_reasons[reason] += 1
                    self.symbol_rejections[symbol] += 1

                elif evt_type == "TRADE_OPENED":
                    self.trades_opened += 1

                elif evt_type in CLOSE_EVENT_TYPES:
                    self.trades_closed += 1
                    pnl = event.get("pnl", 0)
                    self.pnl_total += pnl

            except json.JSONDecodeError:
                continue

    def process_signal_outcomes(self):
        """Read new signal outcomes for sizing analysis."""
        lines = self.read_new_lines(self.data_dir / "logs" / "signal_outcomes.jsonl")
        for line in lines:
            try:
                outcome = json.loads(line)
                meta = outcome.get("meta", {})
                self.sizing_events.append({
                    "symbol": outcome.get("sym", "?"),
                    "side": outcome.get("side", "?"),
                    "confidence": outcome.get("conf", 0),
                    "passed": outcome.get("passed", False),
                    "n_agree": outcome.get("n_agree", 0),
                    "regime": outcome.get("regime", "unknown"),
                    "leverage": meta.get("leverage", 0),
                    "risk_mult": meta.get("risk_multiplier", 0) if isinstance(meta, dict) else 0,
                    "ev_per_dollar": meta.get("ev_per_dollar", 0),
                    "fee_drag_pct": meta.get("fee_drag_pct", 0),
                    "chop": meta.get("chop_score_smoothed", 0),
                })
            except (json.JSONDecodeError, KeyError):
                continue

    def process_risk_rejections(self):
        """Read new risk rejections."""
        lines = self.read_new_lines(self.data_dir / "logs" / "risk_rejections.csv")
        for line in lines:
            if line.startswith("timestamp") or line.startswith("2026"):
                parts = line.split(",", 3)
                if len(parts) >= 3:
                    symbol = parts[1]
                    reason = parts[2] if len(parts) > 2 else "unknown"
                    self.signals_rejected += 1
                    self.symbol_rejections[symbol] += 1
                    # Extract short reason
                    if "Duplicate" in reason:
                        self.rejection_reasons["duplicate_position"] += 1
                    elif "circuit_breaker" in reason.lower():
                        self.rejection_reasons["circuit_breaker"] += 1
                    else:
                        self.rejection_reasons[reason[:50]] += 1

    def process_sniper_rejections(self):
        """Read new sniper rejections."""
        lines = self.read_new_lines(self.data_dir / "manual" / "sniper_rejections.jsonl")
        for line in lines:
            try:
                rej = json.loads(line)
                reason = rej.get("reason", "unknown")
                symbol = rej.get("symbol", "?")
                self.rejection_reasons[f"sniper:{reason}"] += 1
                self.symbol_rejections[symbol] += 1
            except json.JSONDecodeError:
                continue

    def get_position_state(self) -> dict:
        """Read current position state."""
        try:
            with open(self.data_dir / "position_state.json") as f:
                return json.load(f)
        except Exception:
            return {"positions": {}, "position_count": 0}

    def get_heartbeat(self) -> dict:
        """Check bot heartbeat."""
        try:
            with open(self.data_dir / "heartbeat.json") as f:
                hb = json.load(f)
            last = datetime.fromisoformat(hb["last_alive"])
            age = (datetime.now(timezone.utc) - last).total_seconds()
            return {"alive": age < 300, "age_s": age, "pid": hb.get("pid")}
        except Exception:
            return {"alive": False, "age_s": 999999}

    def generate_report(self) -> str:
        """Generate current monitoring report."""
        hb = self.get_heartbeat()
        pos = self.get_position_state()
        runtime = (datetime.now(timezone.utc) - self._session_start).total_seconds()
        runtime_h = runtime / 3600

        lines = []
        lines.append("=" * 60)
        lines.append(f"  SIZING MONITOR REPORT — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        lines.append("=" * 60)
        lines.append(f"Bot: {'ALIVE' if hb['alive'] else 'DEAD'} (heartbeat {hb['age_s']:.0f}s ago)")
        lines.append(f"Monitoring for: {runtime_h:.1f}h")
        lines.append(f"Open positions: {pos['position_count']}")
        lines.append("")

        # Position details
        for sym, p in pos.get("positions", {}).items():
            lines.append(f"  {sym} {p['side']} @ {p['entry']} | lev={p['leverage']:.1f}x | "
                        f"qty={p['qty']} | state={p['state']}")

        lines.append("")
        lines.append("-" * 60)
        lines.append("SIGNAL FLOW")
        lines.append("-" * 60)
        lines.append(f"Signals generated:  {self.signals_generated}")
        lines.append(f"Signals passed:     {self.signals_passed}")
        lines.append(f"Signals rejected:   {self.signals_rejected}")
        pass_rate = (self.signals_passed / max(self.signals_generated, 1)) * 100
        lines.append(f"Pass rate:          {pass_rate:.1f}%")
        lines.append(f"Signals/hour:       {self.signals_generated / max(runtime_h, 0.01):.1f}")
        lines.append("")

        # Per symbol
        lines.append("Per symbol:")
        for sym in sorted(set(list(self.symbol_signals.keys()) + list(self.symbol_rejections.keys()))):
            gen = self.symbol_signals[sym]
            rej = self.symbol_rejections[sym]
            pas = self.symbol_passes[sym]
            lines.append(f"  {sym}: {gen} generated, {pas} passed, {rej} rejected")

        lines.append("")
        lines.append("-" * 60)
        lines.append("TOP REJECTION REASONS")
        lines.append("-" * 60)
        sorted_reasons = sorted(self.rejection_reasons.items(), key=lambda x: -x[1])[:15]
        for reason, count in sorted_reasons:
            lines.append(f"  {count:5d}x  {reason}")

        lines.append("")
        lines.append("-" * 60)
        lines.append("SIZING ANALYSIS")
        lines.append("-" * 60)
        if self.sizing_events:
            passed = [e for e in self.sizing_events if e["passed"]]
            if passed:
                avg_lev = sum(e["leverage"] for e in passed) / len(passed)
                avg_rm = sum(e["risk_mult"] for e in passed) / len(passed)
                avg_conf = sum(e["confidence"] for e in passed) / len(passed)
                lines.append(f"Passed signals: {len(passed)}")
                lines.append(f"  Avg leverage:       {avg_lev:.1f}x")
                lines.append(f"  Avg risk_mult:      {avg_rm:.3f}")
                lines.append(f"  Avg confidence:     {avg_conf:.1f}%")

            failed = [e for e in self.sizing_events if not e["passed"]]
            if failed:
                avg_conf_f = sum(e["confidence"] for e in failed) / len(failed)
                lines.append(f"Failed signals: {len(failed)}")
                lines.append(f"  Avg confidence:     {avg_conf_f:.1f}%")

        lines.append("")
        lines.append("-" * 60)
        lines.append("TRADES")
        lines.append("-" * 60)
        lines.append(f"Opened: {self.trades_opened}")
        lines.append(f"Closed: {self.trades_closed}")
        lines.append(f"Net PnL: ${self.pnl_total:+.2f}")

        report = "\n".join(lines)
        return report

    def save_report(self, report: str):
        """Save report to monitoring directory."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filepath = self.output_dir / f"report_{ts}.txt"
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(report)

        # Also save as latest
        with open(self.output_dir / "latest_report.txt", "w", encoding="utf-8") as f:
            f.write(report)

    def save_state(self):
        """Save accumulated state for continuity across restarts."""
        state = {
            "session_start": self._session_start.isoformat(),
            "signals_generated": self.signals_generated,
            "signals_passed": self.signals_passed,
            "signals_rejected": self.signals_rejected,
            "rejection_reasons": dict(self.rejection_reasons),
            "trades_opened": self.trades_opened,
            "trades_closed": self.trades_closed,
            "pnl_total": self.pnl_total,
            "symbol_signals": dict(self.symbol_signals),
            "symbol_rejections": dict(self.symbol_rejections),
            "file_positions": self._file_positions,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(self.output_dir / "monitor_state.json", "w") as f:
            json.dump(state, f, indent=2)

    def run(self, interval_s: int = 60, report_interval_s: int = 300):
        """Main monitoring loop."""
        logger.info(f"Starting sizing monitor (check every {interval_s}s, report every {report_interval_s}s)")
        last_report = 0

        try:
            while True:
                self.process_trade_events()
                self.process_signal_outcomes()
                self.process_risk_rejections()
                self.process_sniper_rejections()

                now = time.time()
                if now - last_report >= report_interval_s:
                    report = self.generate_report()
                    self.save_report(report)
                    self.save_state()
                    logger.info(f"Report saved. Signals: {self.signals_generated}, "
                              f"Rejections: {self.signals_rejected}, "
                              f"Trades: {self.trades_opened}/{self.trades_closed}")
                    last_report = now

                time.sleep(interval_s)

        except KeyboardInterrupt:
            logger.info("Monitor stopped. Saving final state...")
            report = self.generate_report()
            self.save_report(report)
            self.save_state()
            print(report)


def one_shot_report(data_dir: str = "data"):
    """Generate a one-shot report from existing data."""
    monitor = SizingMonitor(data_dir=data_dir)

    # Read ALL existing data (not incremental)
    monitor._file_positions = {}  # Reset to read from start

    monitor.process_trade_events()
    monitor.process_signal_outcomes()
    monitor.process_risk_rejections()
    monitor.process_sniper_rejections()

    report = monitor.generate_report()
    monitor.save_report(report)
    print(report)
    return monitor


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Live sizing monitor")
    parser.add_argument("--interval", type=int, default=60, help="Check interval (seconds)")
    parser.add_argument("--report-interval", type=int, default=300, help="Report interval (seconds)")
    parser.add_argument("--one-shot", action="store_true", help="Generate one report and exit")
    parser.add_argument("--data-dir", default="data", help="Bot data directory")
    args = parser.parse_args()

    if args.one_shot:
        one_shot_report(args.data_dir)
    else:
        monitor = SizingMonitor(data_dir=args.data_dir)
        monitor.run(interval_s=args.interval, report_interval_s=args.report_interval)
