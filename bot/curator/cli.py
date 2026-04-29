#!/usr/bin/env python3
"""
Curator CLI: Signal ranking and manual execution tracking.

Commands:
  curator show-signals [--date TODAY|yesterday|7d]    — Show top daily signals for manual execution
  curator log-execution SIGNAL_ID ENTRY_PRICE SIZE    — Record manual fill
  curator log-close SIGNAL_ID EXIT_PRICE              — Record position close
  curator report [--date TODAY|yesterday|7d]          — Daily execution quality report
  curator status                                       — Show pending signals and active positions

Example:
  cd bot
  python -c "from curator.cli import main; main()" show-signals
"""

import sys
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional
import json

# Setup paths
BOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BOT_DIR))

from curator.signal_ranker import SignalRanker
from curator.execution_tracker import ExecutionTracker

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("bot.curator.cli")


class CuratorCLI:
    """Command-line interface for signal curation and execution tracking."""

    def __init__(self, data_dir: Optional[str] = None):
        if data_dir is None:
            data_dir = str(BOT_DIR / "data")

        self.data_dir = Path(data_dir)
        self.ranker = SignalRanker(str(self.data_dir))
        self.tracker = ExecutionTracker(str(self.data_dir))

    def cmd_show_signals(self, args: list) -> None:
        """Show today's top ranked signals for manual trading."""
        max_age = 24

        if args:
            if args[0] == "yesterday":
                max_age = 48  # Show signals from 24-48 hours ago
            elif args[0] == "7d":
                max_age = 168

        logger.info(f"Ranking signals from last {max_age} hours...")

        ranked = self.ranker.rank_daily_signals(max_age_hours=max_age)
        self.ranker.save_daily_signals(ranked)

        if not ranked:
            print("[WARNING] No signals found in the last", max_age, "hours.")
            return

        formatted = self.ranker.format_for_manual_trader(ranked)
        print("\n" + formatted)

        # Also save to curator output
        self.ranker.save_daily_signals(ranked)
        print(f"\n[OK] Saved {len(ranked)} ranked signals to {self.ranker.curator_output}")

    def cmd_log_execution(self, args: list) -> None:
        """Log manual execution of a signal."""
        if len(args) < 3:
            print("Usage: curator log-execution SIGNAL_ID ENTRY_PRICE SIZE [SL_PRICE] [COMMENTS]")
            print("  Example: curator log-execution sig_001 45632.50 0.01 45000 'Morning edge scalp'")
            return

        signal_id = args[0]
        try:
            entry = float(args[1])
            size = float(args[2])
        except (ValueError, IndexError):
            print("[ERROR] Invalid entry price or size")
            return

        sl = None
        comments = ""

        if len(args) > 3:
            try:
                sl = float(args[3])
            except ValueError:
                comments = args[3]

        if len(args) > 4:
            comments = args[4]

        try:
            self.tracker.log_execution(
                signal_id=signal_id,
                actual_entry=entry,
                actual_size=size,
                actual_sl=sl,
                comments=comments,
            )
            print(f"[OK] Logged execution: {signal_id} @ {entry} ({size} contracts)")
        except Exception as e:
            print(f"[ERROR] Error logging execution: {e}")

    def cmd_log_close(self, args: list) -> None:
        """Log position close."""
        if len(args) < 2:
            print("Usage: curator log-close SIGNAL_ID EXIT_PRICE [COMMENTS]")
            print("  Example: curator log-close sig_001 46200.75 'Hit TP1'")
            return

        signal_id = args[0]
        try:
            exit_price = float(args[1])
        except (ValueError, IndexError):
            print("[ERROR] Invalid exit price")
            return

        comments = " ".join(args[2:]) if len(args) > 2 else ""

        try:
            self.tracker.log_close(
                signal_id=signal_id,
                actual_exit=exit_price,
                comments=comments,
            )
            print(f"[OK] Logged close: {signal_id} @ {exit_price}")
        except Exception as e:
            print(f"[ERROR] Error logging close: {e}")

    def cmd_report(self, args: list) -> None:
        """Show daily execution quality report."""
        date = datetime.now(timezone.utc)

        if args:
            if args[0] == "yesterday":
                date = date - timedelta(days=1)
            elif args[0] == "7d":
                # Show average over last 7 days
                print("[INFO] Seven-day execution summary (coming soon)")
                return

        report = self.tracker.generate_daily_report(date)
        formatted = self.tracker.format_daily_report(report)
        print("\n" + formatted)

        # Save to file
        report_output = self.data_dir / f"EXECUTION_REPORT_{date.strftime('%Y%m%d')}.json"
        try:
            with open(report_output, 'w') as f:
                json.dump(report, f, indent=2)
            print(f"\n[OK] Saved report to {report_output}")
        except Exception as e:
            print(f"[WARNING] Could not save report: {e}")

    def cmd_status(self, args: list) -> None:
        """Show pending signals and active positions."""
        # Load tracker data
        tracker_file = self.data_dir / "EXECUTION_TRACKER.jsonl"

        if not tracker_file.exists():
            print("[INFO] No execution history found yet.")
            return

        pending = []
        active = []

        try:
            with open(tracker_file, 'r') as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        status = record.get('status', 'signal_generated')

                        if status == 'signal_generated':
                            pending.append(record)
                        elif status in ['filled', 'holding']:
                            active.append(record)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            print(f"[ERROR] Error reading tracker: {e}")
            return

        # Format output
        lines = ["[STATUS] SIGNAL & POSITION STATUS", "=" * 80]

        if pending:
            lines.append(f"\n[PENDING] Signals ({len(pending)}):")
            for sig in pending[:10]:  # Show top 10
                lines.append(
                    f"  {sig['signal_id']}: {sig['symbol']} {sig['side']} "
                    f"@ {sig['signal_entry']} ({sig['confidence']:.0f}% conf)"
                )

        if active:
            lines.append(f"\n[ACTIVE] Positions ({len(active)}):")
            for pos in active:
                pnl = "N/A"
                if pos.get('actual_entry') and pos.get('actual_exit'):
                    if pos['side'] == 'BUY':
                        pnl = f"+${(pos['actual_exit'] - pos['actual_entry']) * pos.get('actual_size', 1):.2f}"
                    else:
                        pnl = f"+${(pos['actual_entry'] - pos['actual_exit']) * pos.get('actual_size', 1):.2f}"

                lines.append(
                    f"  {pos['signal_id']}: {pos['symbol']} {pos['side']} "
                    f"@ {pos.get('actual_entry', pos['signal_entry'])} (P&L: {pnl})"
                )

        if not pending and not active:
            lines.append("\n[OK] No pending or active positions.")

        print("\n".join(lines))

    def run(self) -> None:
        """Parse command-line arguments and dispatch."""
        if len(sys.argv) < 2:
            print(__doc__)
            return

        command = sys.argv[1]
        args = sys.argv[2:] if len(sys.argv) > 2 else []

        if command == "show-signals":
            self.cmd_show_signals(args)
        elif command == "log-execution":
            self.cmd_log_execution(args)
        elif command == "log-close":
            self.cmd_log_close(args)
        elif command == "report":
            self.cmd_report(args)
        elif command == "status":
            self.cmd_status(args)
        else:
            print(f"❌ Unknown command: {command}")
            print(__doc__)


def main():
    """Entry point."""
    cli = CuratorCLI()
    cli.run()


if __name__ == "__main__":
    main()
