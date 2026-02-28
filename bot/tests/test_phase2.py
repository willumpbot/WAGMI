"""
Phase 2+3 test suite.

Tests:
1. test_state_machine_transitions - valid/invalid state transitions
2. test_one_position_per_symbol - enforced single position per symbol
3. test_precision_rounding - per-symbol price/qty precision
4. test_risk_filters - circuit breaker + position limits
5. test_tp1_never_net_negative - TP1 partial close is always profitable
6. test_ml_stats_export - ML stats JSONL output
7. test_ml_conf_history_logging - per-symbol confidence CSV
8. test_backtest_equity_curve - equity curve from backtest engine
9. test_replay_mode_consistency - replay produces same signals for same data
"""

import csv
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# Allow imports from bot/ root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from execution.position_state import (
    IDLE, OPEN, TP1_HIT, TRAILING, CLOSED,
    is_valid_transition, transition,
)
from execution.position_manager import PositionManager, Position
from execution.precision import round_price, round_qty, format_price, _precision_cache
from execution.risk import RiskManager, CircuitBreaker
from data.ml_log import log_ml_stats, log_ml_confidence
from data.learning import record_trade_outcome, get_performance, _recent_outcomes
from multi_strategy_main import get_tp1_close_pct


# ─── Fixtures ───────────────────────────────────────────


@pytest.fixture(autouse=True)
def tmpdir_data(tmp_path, monkeypatch):
    """Redirect all data/* and ml_data/* writes to a temp dir."""
    data_dir = str(tmp_path / "data")
    os.makedirs(data_dir, exist_ok=True)
    # Patch data paths for all modules
    monkeypatch.setattr("execution.position_state._LOG_DIR", os.path.join(data_dir, "logs"))
    monkeypatch.setattr("execution.position_state._LOG_FILE", os.path.join(data_dir, "logs", "state_transitions.csv"))
    monkeypatch.setattr("data.ml_log._ML_DIR", os.path.join(data_dir, "ml"))
    monkeypatch.setattr("data.ml_log._STATS_FILE", os.path.join(data_dir, "ml", "ml_stats.jsonl"))
    monkeypatch.setattr("data.ml_log._CONF_FILE", os.path.join(data_dir, "ml", "ml_conf_history.csv"))
    monkeypatch.setattr("data.learning._OUTCOMES_DIR", os.path.join(data_dir, "analysis"))
    monkeypatch.setattr("data.learning._OUTCOMES_FILE", os.path.join(data_dir, "analysis", "trade_outcomes.csv"))
    monkeypatch.setattr("data.learning._PERF_FILE", os.path.join(data_dir, "analysis", "performance.json"))
    monkeypatch.setattr("data.risk_log._LOG_DIR", os.path.join(data_dir, "logs"))
    monkeypatch.setattr("data.risk_log._LOG_FILE", os.path.join(data_dir, "logs", "risk_rejections.csv"))
    # Clear rolling window between tests
    _recent_outcomes.clear()
    yield tmp_path


# ─── 1. State Machine Transitions ───────────────────────


class TestStateMachineTransitions:
    def test_valid_transitions(self):
        """All valid state transitions should be accepted."""
        assert is_valid_transition(IDLE, OPEN) is True
        assert is_valid_transition(OPEN, TP1_HIT) is True
        assert is_valid_transition(OPEN, CLOSED) is True
        assert is_valid_transition(TP1_HIT, TRAILING) is True
        assert is_valid_transition(TP1_HIT, CLOSED) is True
        assert is_valid_transition(TRAILING, CLOSED) is True

    def test_invalid_transitions(self):
        """Invalid state transitions should be rejected."""
        assert is_valid_transition(IDLE, TP1_HIT) is False
        assert is_valid_transition(IDLE, TRAILING) is False
        assert is_valid_transition(IDLE, CLOSED) is False
        assert is_valid_transition(OPEN, TRAILING) is False  # must go through TP1_HIT
        assert is_valid_transition(CLOSED, OPEN) is False  # terminal state
        assert is_valid_transition(CLOSED, IDLE) is False
        assert is_valid_transition(TRAILING, OPEN) is False

    def test_transition_function_valid(self):
        """transition() should return target state when valid."""
        result = transition("BTC", IDLE, OPEN, "test open")
        assert result == OPEN

    def test_transition_function_invalid(self):
        """transition() should return current state when invalid."""
        result = transition("BTC", IDLE, TRAILING, "bad transition")
        assert result == IDLE  # stays in IDLE

    def test_closed_is_terminal(self):
        """No transitions out of CLOSED."""
        for target in [IDLE, OPEN, TP1_HIT, TRAILING]:
            assert is_valid_transition(CLOSED, target) is False

    def test_full_happy_path(self):
        """IDLE -> OPEN -> TP1_HIT -> TRAILING -> CLOSED."""
        state = IDLE
        state = transition("BTC", state, OPEN, "open")
        assert state == OPEN
        state = transition("BTC", state, TP1_HIT, "tp1")
        assert state == TP1_HIT
        state = transition("BTC", state, TRAILING, "trail")
        assert state == TRAILING
        state = transition("BTC", state, CLOSED, "tp2")
        assert state == CLOSED


# ─── 2. One Position Per Symbol ─────────────────────────


class TestOnePositionPerSymbol:
    def test_rejects_duplicate_position(self):
        """Cannot open a second position for the same symbol."""
        pm = PositionManager()
        pos1 = pm.open_position(
            symbol="BTC", side="LONG", entry=100.0, qty=1.0,
            sl=95.0, tp1=110.0, tp2=120.0, atr=2.0,
            leverage=2.0, tp1_close_pct=0.7,
        )
        assert pos1 is not None

        pos2 = pm.open_position(
            symbol="BTC", side="SHORT", entry=100.0, qty=1.0,
            sl=105.0, tp1=90.0, tp2=80.0, atr=2.0,
            leverage=2.0, tp1_close_pct=0.7,
        )
        assert pos2 is None  # rejected

    def test_allows_after_close(self):
        """Can open new position after previous one is closed."""
        pm = PositionManager()
        pm.open_position(
            symbol="BTC", side="LONG", entry=100.0, qty=1.0,
            sl=95.0, tp1=110.0, tp2=120.0, atr=2.0,
            leverage=2.0, tp1_close_pct=0.7,
        )
        # Force close
        pm.force_close("BTC", 96.0, "TEST")

        # Now should be able to open again
        pos2 = pm.open_position(
            symbol="BTC", side="SHORT", entry=100.0, qty=1.0,
            sl=105.0, tp1=90.0, tp2=80.0, atr=2.0,
            leverage=2.0, tp1_close_pct=0.7,
        )
        assert pos2 is not None

    def test_different_symbols_allowed(self):
        """Can have positions in different symbols simultaneously."""
        pm = PositionManager()
        pos1 = pm.open_position(
            symbol="BTC", side="LONG", entry=100.0, qty=1.0,
            sl=95.0, tp1=110.0, tp2=120.0, atr=2.0,
            leverage=2.0, tp1_close_pct=0.7,
        )
        pos2 = pm.open_position(
            symbol="SOL", side="LONG", entry=50.0, qty=10.0,
            sl=47.0, tp1=55.0, tp2=60.0, atr=1.0,
            leverage=2.0, tp1_close_pct=0.7,
        )
        assert pos1 is not None
        assert pos2 is not None
        assert pm.get_open_count() == 2


# ─── 3. Precision Rounding ──────────────────────────────


class TestPrecisionRounding:
    def test_btc_price_precision(self):
        """BTC prices should round to 1 decimal place."""
        assert round_price("BTC", 98765.4321) == 98765.4

    def test_sol_price_precision(self):
        """SOL prices should round to 3 decimal places."""
        assert round_price("SOL", 123.4567) == 123.457

    def test_hype_price_precision(self):
        """HYPE (microcap) prices should round to 4 decimal places."""
        assert round_price("HYPE", 0.12345678) == 0.1235

    def test_qty_rounds_down(self):
        """Quantity always rounds DOWN for safety."""
        assert round_qty("BTC", 1.56789) == 1.56789  # 5 decimals per config
        assert round_qty("SOL", 99.999) == 99.99      # 2 decimals, round down

    def test_format_price(self):
        """format_price should produce correct string representation."""
        assert format_price("BTC", 98765.0) == "98765.0"
        assert format_price("SOL", 123.4) == "123.400"  # 3 decimal places per config

    def test_unknown_symbol_uses_default(self):
        """Unknown symbols should use default precision (2 price, 4 qty)."""
        assert round_price("UNKNOWN_TOKEN", 1.23456) == 1.23
        assert round_qty("UNKNOWN_TOKEN", 100.123456) == 100.1234


# ─── 4. Risk Filters ────────────────────────────────────


class TestRiskFilters:
    def test_circuit_breaker_consecutive_losses(self):
        """Circuit breaker trips after max consecutive losses."""
        cb = CircuitBreaker(max_consecutive_losses=3)
        cb.peak_equity = 10000
        cb.record_trade(-100, 9900)
        cb.record_trade(-100, 9800)
        assert cb.is_trading_allowed() is True
        cb.record_trade(-100, 9700)
        assert cb.is_trading_allowed() is False  # tripped

    def test_circuit_breaker_daily_loss(self):
        """Circuit breaker trips when daily loss exceeds limit."""
        cb = CircuitBreaker(daily_loss_limit_pct=0.05)
        cb.peak_equity = 10000
        cb.record_trade(-550, 9450)  # 5.5% loss
        assert cb.is_trading_allowed() is False

    def test_max_open_positions(self):
        """RiskManager rejects new positions when at max."""
        rm = RiskManager(max_open_positions=2)
        assert rm.can_open_position(0) is True
        assert rm.can_open_position(1) is True
        assert rm.can_open_position(2) is False

    def test_qty_calculation(self):
        """Position size should risk exactly risk_per_trade * equity."""
        rm = RiskManager(starting_equity=10000, risk_per_trade=0.015)
        qty = rm.calculate_qty(entry=100.0, stop_loss=95.0, leverage=2.0)
        # risk_usd = 10000 * 0.015 = 150
        # qty = 150 / (5.0 * 2.0) = 15.0
        assert qty == pytest.approx(15.0)

    def test_zero_stop_width_returns_zero(self):
        """Entry == SL should return 0 qty."""
        rm = RiskManager()
        qty = rm.calculate_qty(entry=100.0, stop_loss=100.0)
        assert qty == 0.0

    def test_win_resets_consecutive_losses(self):
        """A winning trade resets the consecutive loss counter."""
        cb = CircuitBreaker(max_consecutive_losses=5)
        cb.peak_equity = 10000
        cb.record_trade(-100, 9900)
        cb.record_trade(-100, 9800)
        assert cb.consecutive_losses == 2
        cb.record_trade(200, 10000)
        assert cb.consecutive_losses == 0


# ─── 5. TP1 Never Net Negative ──────────────────────────


class TestTp1NeverNetNegative:
    """TP1 partial close should always lock in profit, never net negative."""

    def _make_long_position(self, pm, entry, sl, tp1, tp2, confidence=75.0):
        tp1_pct = get_tp1_close_pct(confidence)
        pm.open_position(
            symbol="BTC", side="LONG", entry=entry, qty=1.0,
            sl=sl, tp1=tp1, tp2=tp2, atr=abs(entry - sl),
            leverage=2.0, tp1_close_pct=tp1_pct,
        )

    def test_tp1_partial_profit_is_positive(self):
        """The partial close at TP1 should produce positive PnL."""
        pm = PositionManager()
        self._make_long_position(pm, entry=100.0, sl=95.0, tp1=107.5, tp2=115.0)
        # Walk price to TP1
        events = pm.update_price("BTC", 107.5)
        tp1_events = [e for e in events if e.action == "TP1"]
        assert len(tp1_events) == 1
        assert tp1_events[0].pnl > 0, f"TP1 PnL should be positive, got {tp1_events[0].pnl}"

    def test_tp1_low_confidence_closes_all(self):
        """At <70% confidence, TP1 closes 100% of position."""
        pm = PositionManager()
        tp1_pct = get_tp1_close_pct(65.0)
        assert tp1_pct == 1.00
        pm.open_position(
            symbol="BTC", side="LONG", entry=100.0, qty=1.0,
            sl=95.0, tp1=107.5, tp2=115.0, atr=5.0,
            leverage=2.0, tp1_close_pct=tp1_pct,
        )
        events = pm.update_price("BTC", 107.5)
        # Should have TP1 event (partial close at 100%)
        tp1_events = [e for e in events if e.action == "TP1"]
        assert len(tp1_events) == 1
        # After 100% close at TP1, remaining qty should be ~0
        pos = pm.positions["BTC"]
        assert pos.qty == pytest.approx(0.0, abs=0.01)

    def test_tp1_high_confidence_closes_less(self):
        """At >92% confidence, TP1 closes only 30%."""
        tp1_pct = get_tp1_close_pct(95.0)
        assert tp1_pct == 0.30

    def test_breakeven_sl_after_tp1(self):
        """After TP1, SL should be moved to breakeven + buffer."""
        pm = PositionManager()
        self._make_long_position(pm, entry=100.0, sl=95.0, tp1=107.5, tp2=115.0)
        pm.update_price("BTC", 107.5)
        pos = pm.positions["BTC"]
        # SL should be at entry + buffer (0.2%)
        expected_sl = 100.0 + 100.0 * 0.002
        assert pos.sl >= expected_sl - 0.1, f"SL should be above breakeven, got {pos.sl}"

    def test_tp1_then_sl_still_profitable(self):
        """If TP1 hits then SL hits at breakeven, total trade should be ~breakeven or small profit."""
        pm = PositionManager()
        self._make_long_position(pm, entry=100.0, sl=95.0, tp1=107.5, tp2=115.0, confidence=80.0)
        # Hit TP1
        events_tp1 = pm.update_price("BTC", 107.5)
        tp1_pnl = sum(e.pnl for e in events_tp1 if e.action == "TP1")
        assert tp1_pnl > 0

        # Now SL at breakeven — walk price back down to SL
        pos = pm.positions["BTC"]
        events_sl = pm.update_price("BTC", pos.sl - 0.1)  # just below SL
        sl_events = [e for e in events_sl if e.action in ("TRAILING_STOP", "SL")]
        if sl_events:
            total_pnl = tp1_pnl + sl_events[0].pnl - sum(e.fee for e in events_tp1) - sl_events[0].fee
            # Total should be near breakeven (TP1 profit offsets small SL loss on remainder)
            # The key property: NOT a big loss
            assert total_pnl > -20, f"TP1->SL total should be near breakeven, got {total_pnl:.2f}"


# ─── 6. ML Stats Export ─────────────────────────────────


class TestMlStatsExport:
    def test_writes_jsonl(self, tmpdir_data):
        """log_ml_stats should write valid JSONL."""
        stats_file = os.path.join(str(tmpdir_data), "data", "ml", "ml_stats.jsonl")
        log_ml_stats(
            ml_samples_total=100,
            ml_conf_trade=0.85,
            ml_conf_snapshot=0.72,
            ml_conf_fast=0.78,
            equity=10500.0,
            open_positions=2,
        )
        assert os.path.exists(stats_file)
        with open(stats_file) as f:
            lines = f.readlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["ml_samples_total"] == 100
        assert data["equity"] == 10500.0
        assert data["open_positions"] == 2

    def test_appends_multiple(self, tmpdir_data):
        """Multiple calls append separate JSONL entries."""
        stats_file = os.path.join(str(tmpdir_data), "data", "ml", "ml_stats.jsonl")
        for i in range(5):
            log_ml_stats(i * 10, 0.5 + i * 0.1, 0.5, 0.5, 10000 + i * 100, i)
        with open(stats_file) as f:
            lines = f.readlines()
        assert len(lines) == 5
        # Each line should be valid JSON
        for line in lines:
            data = json.loads(line)
            assert "timestamp" in data


# ─── 7. ML Confidence History Logging ───────────────────


class TestMlConfHistoryLogging:
    def test_writes_csv(self, tmpdir_data):
        """log_ml_confidence should write a CSV with correct headers."""
        conf_file = os.path.join(str(tmpdir_data), "data", "ml", "ml_conf_history.csv")
        log_ml_confidence("BTC", 0.82, 0.75, 0.79)
        assert os.path.exists(conf_file)
        with open(conf_file) as f:
            reader = csv.reader(f)
            header = next(reader)
            assert header == ["timestamp", "symbol", "conf_trade", "conf_snapshot", "conf_fast"]
            row = next(reader)
            assert row[1] == "BTC"
            assert float(row[2]) == pytest.approx(0.82, abs=0.001)

    def test_multiple_symbols(self, tmpdir_data):
        """Logging multiple symbols produces multiple rows."""
        conf_file = os.path.join(str(tmpdir_data), "data", "ml", "ml_conf_history.csv")
        log_ml_confidence("BTC", 0.80, 0.70, 0.75)
        log_ml_confidence("SOL", 0.60, 0.55, 0.58)
        log_ml_confidence("HYPE", 0.90, 0.85, 0.88)
        with open(conf_file) as f:
            reader = csv.reader(f)
            next(reader)  # skip header
            rows = list(reader)
        assert len(rows) == 3
        symbols = [r[1] for r in rows]
        assert symbols == ["BTC", "SOL", "HYPE"]


# ─── 8. Backtest Equity Curve ────────────────────────────


class TestBacktestEquityCurve:
    def test_equity_curve_tracked(self):
        """PositionManager tracks equity changes through trade lifecycle."""
        pm = PositionManager(taker_fee_bps=5)
        rm = RiskManager(starting_equity=10000, risk_per_trade=0.015)

        # Open -> TP1 -> TP2 path
        pm.open_position(
            symbol="BTC", side="LONG", entry=100.0, qty=10.0,
            sl=95.0, tp1=107.5, tp2=115.0, atr=5.0,
            leverage=2.0, tp1_close_pct=0.7,
        )
        equity_points = [rm.equity]

        # Hit TP1
        events = pm.update_price("BTC", 107.5)
        for e in events:
            rm.update_equity(e.pnl - e.fee)
        equity_points.append(rm.equity)

        # Hit TP2
        events = pm.update_price("BTC", 115.0)
        for e in events:
            rm.update_equity(e.pnl - e.fee)
        equity_points.append(rm.equity)

        # Equity should increase through the lifecycle
        assert equity_points[-1] > equity_points[0], \
            f"Equity should increase: {equity_points}"

    def test_sl_reduces_equity(self):
        """A stop loss should reduce equity."""
        pm = PositionManager(taker_fee_bps=5)
        rm = RiskManager(starting_equity=10000)

        pm.open_position(
            symbol="SOL", side="LONG", entry=100.0, qty=10.0,
            sl=95.0, tp1=110.0, tp2=120.0, atr=5.0,
            leverage=2.0, tp1_close_pct=0.7,
        )
        initial_equity = rm.equity

        # Hit SL
        events = pm.update_price("SOL", 94.9)
        for e in events:
            rm.update_equity(e.pnl - e.fee)

        assert rm.equity < initial_equity


# ─── 9. Replay Mode Consistency ─────────────────────────


class TestReplayModeConsistency:
    def test_position_lifecycle_deterministic(self):
        """Same price sequence should produce same trade outcomes."""
        results = []
        for _ in range(2):
            pm = PositionManager(taker_fee_bps=5)
            pm.open_position(
                symbol="BTC", side="LONG", entry=100.0, qty=1.0,
                sl=95.0, tp1=107.5, tp2=115.0, atr=5.0,
                leverage=2.0, tp1_close_pct=0.7,
            )
            all_events = []
            # Simulate a price path
            prices = [101, 103, 105, 107, 107.5, 108, 110, 112, 115]
            for p in prices:
                events = pm.update_price("BTC", float(p))
                all_events.extend(events)
            results.append([(e.action, round(e.pnl, 2)) for e in all_events])

        assert results[0] == results[1], "Same price sequence should produce identical events"

    def test_short_position_lifecycle(self):
        """SHORT positions should mirror LONG behavior."""
        pm = PositionManager(taker_fee_bps=5)
        pm.open_position(
            symbol="BTC", side="SHORT", entry=100.0, qty=1.0,
            sl=105.0, tp1=92.5, tp2=85.0, atr=5.0,
            leverage=2.0, tp1_close_pct=0.7,
        )
        # Walk price down to TP1
        events = pm.update_price("BTC", 92.5)
        tp1_events = [e for e in events if e.action == "TP1"]
        assert len(tp1_events) == 1
        assert tp1_events[0].pnl > 0, "SHORT TP1 should be profitable"

    def test_learning_hooks_record(self, tmpdir_data):
        """record_trade_outcome should write to CSV and update performance."""
        record_trade_outcome(
            symbol="BTC", side="LONG", outcome="CLEAN_WIN",
            pnl=150.0, entry=100.0, sl=95.0, tp1=107.5, tp2=115.0,
            tp1_hit=True, sl_after_tp1=False,
            state_path="IDLE->OPEN->TP1_HIT->TRAILING->CLOSED",
            leverage=2.0, confidence=80.0, strategy="regime_trend",
        )
        perf = get_performance()
        assert perf["total_trades"] == 1
        assert perf["total_pnl"] == 150.0

        outcomes_file = os.path.join(str(tmpdir_data), "data", "analysis", "trade_outcomes.csv")
        assert os.path.exists(outcomes_file)
        with open(outcomes_file) as f:
            reader = csv.reader(f)
            next(reader)  # header
            row = next(reader)
            assert row[2] == "LONG"
            assert row[3] == "CLEAN_WIN"
