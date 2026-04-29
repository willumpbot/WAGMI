"""
Execution Tracker: Measures real alpha on ask/receive basis for manual trading.

Records:
- Signal generated (curator recommendation)
- Manual execution (actual fill price, size)
- Trade closed (exit price)
- Analysis: signal vs execution alpha

Key metrics:
- Signal Alpha: (TP hit - Entry signal) / Entry signal
- Execution Alpha: (Actual fill - Signal entry) / Entry signal
- Exit Alpha: (Actual exit - Expected exit from signal) / Entry signal
- Total PnL: Realized P&L on position
- Total Alpha: Total P&L from signal quality + execution quality

Reports:
- Daily execution quality (slippage, timing)
- Weekly signal vs execution alpha decomposition
- Symbol and setup type consistency metrics
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict, field
from pathlib import Path
from enum import Enum

logger = logging.getLogger("bot.curator.execution_tracker")


class ExecutionStatus(str, Enum):
    """Execution status of a signal."""
    SIGNAL_GENERATED = "signal_generated"      # Curator recommended
    PENDING_EXECUTION = "pending_execution"    # Waiting for manual fill
    PARTIALLY_FILLED = "partially_filled"      # Partial fill
    FILLED = "filled"                          # Full position opened
    HOLDING = "holding"                        # Position open
    CLOSED = "closed"                          # Position exited
    MISSED = "missed"                          # Signal never executed


@dataclass
class SignalRecord:
    """Record of a signal and its execution outcome."""
    signal_id: str
    timestamp: float
    symbol: str
    side: str
    setup_type: str
    regime: str
    confidence: float

    # Signal targets
    signal_entry: float
    signal_sl: float
    signal_tp1: float
    signal_tp2: float

    # Execution data
    status: ExecutionStatus = ExecutionStatus.SIGNAL_GENERATED
    actual_entry: Optional[float] = None
    actual_entry_time: Optional[float] = None
    actual_size: Optional[float] = None
    actual_sl: Optional[float] = None
    actual_exit: Optional[float] = None
    actual_exit_time: Optional[float] = None

    # Calculated metrics
    signal_alpha_pct: float = 0.0       # Signal quality (0-100 scale)
    execution_alpha_pct: float = 0.0    # Fill quality vs signal
    exit_alpha_pct: float = 0.0         # Exit quality vs expected
    total_pnl: float = 0.0
    total_pnl_pct: float = 0.0
    comments: str = ""

    def to_dict(self) -> Dict:
        d = asdict(self)
        d['status'] = self.status.value
        return d


class ExecutionTracker:
    """Track manual trade execution and measure alpha decomposition."""

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.tracker_file = self.data_dir / "EXECUTION_TRACKER.jsonl"
        self.daily_report = self.data_dir / "DAILY_EXECUTION_REPORT.json"

    def add_signal(
        self,
        signal_id: str,
        symbol: str,
        side: str,
        setup_type: str,
        regime: str,
        confidence: float,
        entry: float,
        sl: float,
        tp1: float,
        tp2: float,
        timestamp: Optional[float] = None,
    ) -> SignalRecord:
        """Record a new signal from the curator."""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).timestamp()

        record = SignalRecord(
            signal_id=signal_id,
            timestamp=timestamp,
            symbol=symbol,
            side=side,
            setup_type=setup_type,
            regime=regime,
            confidence=confidence,
            signal_entry=entry,
            signal_sl=sl,
            signal_tp1=tp1,
            signal_tp2=tp2,
        )

        self._append_record(record)
        return record

    def log_execution(
        self,
        signal_id: str,
        actual_entry: float,
        actual_size: float,
        actual_sl: Optional[float] = None,
        comments: str = "",
    ) -> None:
        """Record manual execution of a signal."""
        record = self._load_signal(signal_id)
        if not record:
            logger.error(f"Signal {signal_id} not found")
            return

        record.status = ExecutionStatus.FILLED
        record.actual_entry = actual_entry
        record.actual_entry_time = datetime.now(timezone.utc).timestamp()
        record.actual_size = actual_size
        if actual_sl:
            record.actual_sl = actual_sl
        else:
            record.actual_sl = record.signal_sl

        # Calculate execution alpha
        execution_slippage = ((actual_entry - record.signal_entry) / record.signal_entry) * 100
        record.execution_alpha_pct = -execution_slippage  # Negative slippage = negative alpha

        record.comments = comments
        self._update_record(signal_id, record)

        logger.info(
            f"Recorded execution: {signal_id} {record.symbol} {record.side} "
            f"@ {actual_entry} (signal was {record.signal_entry}, "
            f"slippage: {execution_slippage:.2f}%)"
        )

    def log_close(
        self,
        signal_id: str,
        actual_exit: float,
        comments: str = "",
    ) -> None:
        """Record position closure and measure outcome alpha."""
        record = self._load_signal(signal_id)
        if not record:
            logger.error(f"Signal {signal_id} not found")
            return

        if not record.actual_entry:
            logger.error(f"No execution recorded for signal {signal_id}")
            return

        record.status = ExecutionStatus.CLOSED
        record.actual_exit = actual_exit
        record.actual_exit_time = datetime.now(timezone.utc).timestamp()

        # Measure exit quality: how close to TP1/TP2 did we get?
        if record.actual_exit > record.signal_entry:  # Long exit
            expected_exit = record.signal_tp1
            exit_quality = (actual_exit - record.signal_entry) / (expected_exit - record.signal_entry)
        else:  # Short exit
            expected_exit = record.signal_tp1
            exit_quality = (record.signal_entry - actual_exit) / (record.signal_entry - expected_exit)

        record.exit_alpha_pct = (exit_quality - 1.0) * 100

        # Calculate total P&L
        if record.side == "BUY":
            pnl_per_unit = actual_exit - record.actual_entry
        else:  # SELL
            pnl_per_unit = record.actual_entry - actual_exit

        record.total_pnl = pnl_per_unit * (record.actual_size or 1.0)
        record.total_pnl_pct = (pnl_per_unit / record.actual_entry) * 100

        record.comments = comments
        self._update_record(signal_id, record)

        logger.info(
            f"Closed: {signal_id} {record.symbol} "
            f"@ {actual_exit} | P&L: ${record.total_pnl:.2f} ({record.total_pnl_pct:+.2f}%)"
        )

    def _append_record(self, record: SignalRecord) -> None:
        """Append record to execution tracker JSONL."""
        try:
            with open(self.tracker_file, 'a') as f:
                json.dump(record.to_dict(), f)
                f.write('\n')
        except Exception as e:
            logger.error(f"Error appending record: {e}")

    def _load_signal(self, signal_id: str) -> Optional[SignalRecord]:
        """Load a signal record by ID."""
        if not self.tracker_file.exists():
            return None

        try:
            with open(self.tracker_file, 'r') as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        if data.get('signal_id') == signal_id:
                            # Reconstruct record
                            data['status'] = ExecutionStatus(data.get('status'))
                            return self._dict_to_record(data)
                    except (json.JSONDecodeError, ValueError):
                        continue
        except Exception as e:
            logger.error(f"Error loading signal: {e}")

        return None

    def _update_record(self, signal_id: str, updated: SignalRecord) -> None:
        """Update a record in the tracker file."""
        records = []

        # Read all records
        if self.tracker_file.exists():
            try:
                with open(self.tracker_file, 'r') as f:
                    for line in f:
                        try:
                            data = json.loads(line)
                            if data.get('signal_id') != signal_id:
                                records.append(data)
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                logger.error(f"Error reading tracker: {e}")
                return

        # Write all records + updated
        try:
            with open(self.tracker_file, 'w') as f:
                for record in records:
                    json.dump(record, f)
                    f.write('\n')

                json.dump(updated.to_dict(), f)
                f.write('\n')
        except Exception as e:
            logger.error(f"Error writing tracker: {e}")

    @staticmethod
    def _dict_to_record(data: Dict) -> SignalRecord:
        """Convert dict to SignalRecord."""
        return SignalRecord(
            signal_id=data.get('signal_id'),
            timestamp=data.get('timestamp', 0),
            symbol=data.get('symbol'),
            side=data.get('side'),
            setup_type=data.get('setup_type'),
            regime=data.get('regime'),
            confidence=data.get('confidence', 0),
            signal_entry=data.get('signal_entry', 0),
            signal_sl=data.get('signal_sl', 0),
            signal_tp1=data.get('signal_tp1', 0),
            signal_tp2=data.get('signal_tp2', 0),
            status=ExecutionStatus(data.get('status', 'signal_generated')),
            actual_entry=data.get('actual_entry'),
            actual_entry_time=data.get('actual_entry_time'),
            actual_size=data.get('actual_size'),
            actual_sl=data.get('actual_sl'),
            actual_exit=data.get('actual_exit'),
            actual_exit_time=data.get('actual_exit_time'),
            signal_alpha_pct=data.get('signal_alpha_pct', 0),
            execution_alpha_pct=data.get('execution_alpha_pct', 0),
            exit_alpha_pct=data.get('exit_alpha_pct', 0),
            total_pnl=data.get('total_pnl', 0),
            total_pnl_pct=data.get('total_pnl_pct', 0),
            comments=data.get('comments', ''),
        )

    def generate_daily_report(self, date: Optional[datetime] = None) -> Dict[str, Any]:
        """Generate daily execution quality report."""
        if date is None:
            date = datetime.now(timezone.utc)

        cutoff_start = datetime.combine(date.date(), datetime.min.time()).replace(tzinfo=timezone.utc)
        cutoff_end = cutoff_start + timedelta(days=1)
        cutoff_start_ts = cutoff_start.timestamp()
        cutoff_end_ts = cutoff_end.timestamp()

        records = []
        if self.tracker_file.exists():
            try:
                with open(self.tracker_file, 'r') as f:
                    for line in f:
                        try:
                            data = json.loads(line)
                            ts = float(data.get('timestamp', 0))
                            if cutoff_start_ts <= ts < cutoff_end_ts:
                                data['status'] = ExecutionStatus(data.get('status'))
                                records.append(self._dict_to_record(data))
                        except (json.JSONDecodeError, ValueError):
                            continue
            except Exception as e:
                logger.error(f"Error reading tracker for report: {e}")

        # Group by status
        signals_generated = [r for r in records if r.status == ExecutionStatus.SIGNAL_GENERATED]
        executed = [r for r in records if r.status in [ExecutionStatus.FILLED, ExecutionStatus.CLOSED, ExecutionStatus.HOLDING]]
        closed = [r for r in records if r.status == ExecutionStatus.CLOSED]

        # Calculate metrics
        execution_rate = len(executed) / len(records) if records else 0
        avg_execution_alpha = sum(r.execution_alpha_pct for r in executed) / len(executed) if executed else 0
        avg_total_pnl = sum(r.total_pnl for r in closed) / len(closed) if closed else 0
        total_pnl = sum(r.total_pnl for r in closed)
        avg_wr = len([r for r in closed if r.total_pnl > 0]) / len(closed) if closed else 0

        report = {
            "date": date.isoformat(),
            "total_signals": len(records),
            "signals_generated": len(signals_generated),
            "signals_executed": len(executed),
            "signals_closed": len(closed),
            "execution_rate_pct": execution_rate * 100,
            "avg_execution_alpha_pct": avg_execution_alpha,
            "avg_total_pnl": avg_total_pnl,
            "total_pnl": total_pnl,
            "win_rate_pct": avg_wr * 100,
            "execution_quality": {
                "slippage_basis_points": avg_execution_alpha * 100,  # Convert pct to bps
                "filled_signals": len(executed),
                "closed_trades": len(closed),
            },
            "by_symbol": self._group_by_symbol(closed),
            "by_setup": self._group_by_setup(closed),
        }

        return report

    def _group_by_symbol(self, records: List[SignalRecord]) -> Dict[str, Dict]:
        """Group closed trades by symbol."""
        by_symbol = {}
        for record in records:
            if record.symbol not in by_symbol:
                by_symbol[record.symbol] = []
            by_symbol[record.symbol].append(record)

        result = {}
        for symbol, trades in by_symbol.items():
            wins = len([t for t in trades if t.total_pnl > 0])
            result[symbol] = {
                "trades": len(trades),
                "wins": wins,
                "wr": (wins / len(trades) * 100) if trades else 0,
                "avg_pnl": sum(t.total_pnl for t in trades) / len(trades) if trades else 0,
                "total_pnl": sum(t.total_pnl for t in trades),
            }

        return result

    def _group_by_setup(self, records: List[SignalRecord]) -> Dict[str, Dict]:
        """Group closed trades by setup type."""
        by_setup = {}
        for record in records:
            if record.setup_type not in by_setup:
                by_setup[record.setup_type] = []
            by_setup[record.setup_type].append(record)

        result = {}
        for setup, trades in by_setup.items():
            wins = len([t for t in trades if t.total_pnl > 0])
            result[setup] = {
                "trades": len(trades),
                "wins": wins,
                "wr": (wins / len(trades) * 100) if trades else 0,
                "avg_pnl": sum(t.total_pnl for t in trades) / len(trades) if trades else 0,
                "total_pnl": sum(t.total_pnl for t in trades),
            }

        return result

    def format_daily_report(self, report: Dict[str, Any]) -> str:
        """Format daily report for Discord/Telegram."""
        lines = [
            f"[REPORT] DAILY EXECUTION REPORT — {report['date'][:10]}",
            "=" * 80,
            f"Signals Generated: {report['total_signals']}",
            f"Execution Rate: {report['execution_rate_pct']:.1f}%",
            f"Total P&L: ${report['total_pnl']:.2f} | Win Rate: {report['win_rate_pct']:.1f}%",
            f"Avg Execution Alpha: {report['avg_execution_alpha_pct']:+.2f}% (slippage)",
            "",
            "By Symbol:",
        ]

        for symbol, metrics in report["by_symbol"].items():
            lines.append(
                f"  {symbol}: {metrics['trades']} trades, {metrics['wr']:.0f}% WR, "
                f"${metrics['total_pnl']:+.2f} P&L"
            )

        lines.append("")
        lines.append("By Setup Type:")
        for setup, metrics in report["by_setup"].items():
            lines.append(
                f"  {setup}: {metrics['trades']} trades, {metrics['wr']:.0f}% WR, "
                f"${metrics['total_pnl']:+.2f} P&L"
            )

        return "\n".join(lines)
