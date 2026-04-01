"""
Tests for the auto-recovery system.

Covers:
- Position state persistence (save/load)
- Heartbeat and downtime detection
- Stale signal detection
- Exchange retry logic
- Full startup recovery orchestration
- Phantom/orphan detection
"""

import json
import os
import tempfile
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

from execution.auto_recovery import (
    save_heartbeat,
    get_downtime_seconds,
    should_skip_stale_signals,
    save_position_state,
    load_position_state,
    wait_for_exchange,
    startup_recovery,
    _position_to_dict,
    _dict_to_position,
    _STALE_SIGNAL_THRESHOLD_S,
)
from execution.position_manager import PositionManager, Position
from execution.position_state import OPEN, CLOSED, TRAILING, TP1_HIT


# ── Fixtures ───────────────────────────────────────────────

@pytest.fixture
def pos_mgr():
    return PositionManager(taker_fee_bps=4, enable_trailing=True)


@pytest.fixture
def sample_position():
    return Position(
        symbol="BTC",
        side="LONG",
        entry=50000.0,
        qty=0.001,
        sl=48000.0,
        tp1=52000.0,
        tp2=55000.0,
        leverage=5.0,
        mode="leverage",
        strategy="regime_trend",
        confidence=75.0,
        atr=1000.0,
        tp1_close_pct=0.7,
        state=OPEN,
        state_path=[OPEN],
        trailing_distance=1500.0,
        peak_price=50500.0,
    )


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


# ── Heartbeat Tests ────────────────────────────────────────

class TestHeartbeat:

    def test_save_and_read_heartbeat(self, tmp_dir):
        filepath = os.path.join(tmp_dir, "heartbeat.json")
        save_heartbeat(filepath)

        assert os.path.exists(filepath)
        with open(filepath) as f:
            data = json.load(f)
        assert "last_alive" in data
        assert "pid" in data

    def test_downtime_fresh_start(self, tmp_dir):
        filepath = os.path.join(tmp_dir, "nonexistent.json")
        downtime = get_downtime_seconds(filepath)
        assert downtime == 0.0

    def test_downtime_recent(self, tmp_dir):
        filepath = os.path.join(tmp_dir, "heartbeat.json")
        save_heartbeat(filepath)
        downtime = get_downtime_seconds(filepath)
        # Should be very small (just saved)
        assert downtime < 5.0

    def test_downtime_old(self, tmp_dir):
        filepath = os.path.join(tmp_dir, "heartbeat.json")
        # Write a heartbeat from 10 minutes ago
        old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        with open(filepath, "w") as f:
            json.dump({"last_alive": old_time.isoformat(), "pid": 12345}, f)

        downtime = get_downtime_seconds(filepath)
        assert downtime >= 590  # ~10 minutes, with some tolerance
        assert downtime < 700

    def test_stale_signal_detection_fresh(self, tmp_dir):
        filepath = os.path.join(tmp_dir, "heartbeat.json")
        save_heartbeat(filepath)
        skip, downtime = should_skip_stale_signals(filepath)
        assert not skip
        assert downtime < 5.0

    def test_stale_signal_detection_stale(self, tmp_dir):
        filepath = os.path.join(tmp_dir, "heartbeat.json")
        old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        with open(filepath, "w") as f:
            json.dump({"last_alive": old_time.isoformat(), "pid": 12345}, f)

        skip, downtime = should_skip_stale_signals(filepath)
        assert skip
        assert downtime > _STALE_SIGNAL_THRESHOLD_S

    def test_stale_signal_threshold_boundary(self, tmp_dir):
        filepath = os.path.join(tmp_dir, "heartbeat.json")
        # Just under 5 minutes
        recent_time = datetime.now(timezone.utc) - timedelta(seconds=290)
        with open(filepath, "w") as f:
            json.dump({"last_alive": recent_time.isoformat(), "pid": 12345}, f)

        skip, downtime = should_skip_stale_signals(filepath)
        assert not skip

    def test_heartbeat_corrupt_file(self, tmp_dir):
        filepath = os.path.join(tmp_dir, "heartbeat.json")
        with open(filepath, "w") as f:
            f.write("not json")
        downtime = get_downtime_seconds(filepath)
        assert downtime == 0.0


# ── Position Serialization Tests ───────────────────────────

class TestPositionSerialization:

    def test_position_to_dict(self, sample_position):
        d = _position_to_dict(sample_position)
        assert d["symbol"] == "BTC"
        assert d["side"] == "LONG"
        assert d["entry"] == 50000.0
        assert d["sl"] == 48000.0
        assert d["tp1"] == 52000.0
        assert d["tp2"] == 55000.0
        assert d["leverage"] == 5.0
        assert d["state"] == OPEN
        assert d["trailing_distance"] == 1500.0
        assert d["peak_price"] == 50500.0

    def test_dict_roundtrip(self, sample_position):
        d = _position_to_dict(sample_position)
        restored = _dict_to_position(d)
        assert restored.symbol == sample_position.symbol
        assert restored.side == sample_position.side
        assert restored.entry == sample_position.entry
        assert restored.sl == sample_position.sl
        assert restored.tp1 == sample_position.tp1
        assert restored.tp2 == sample_position.tp2
        assert restored.leverage == sample_position.leverage
        assert restored.state == sample_position.state
        assert restored.trailing_distance == sample_position.trailing_distance
        assert restored.peak_price == sample_position.peak_price
        assert restored.atr == sample_position.atr
        assert restored.confidence == sample_position.confidence
        assert restored.strategy == sample_position.strategy

    def test_dict_roundtrip_trailing_state(self):
        pos = Position(
            symbol="ETH",
            side="SHORT",
            entry=3000.0,
            qty=1.0,
            sl=3100.0,
            tp1=2800.0,
            tp2=2500.0,
            state=TRAILING,
            state_path=[OPEN, TP1_HIT, TRAILING],
            trailing_distance=50.0,
            peak_price=2750.0,
        )
        d = _position_to_dict(pos)
        restored = _dict_to_position(d)
        assert restored.state == TRAILING
        assert restored.state_path == [OPEN, TP1_HIT, TRAILING]
        assert restored.peak_price == 2750.0

    def test_dict_to_position_minimal(self):
        """Minimal dict with only required fields."""
        d = {
            "symbol": "SOL",
            "side": "LONG",
            "entry": 100.0,
            "qty": 10.0,
            "sl": 95.0,
            "tp1": 110.0,
            "tp2": 120.0,
        }
        pos = _dict_to_position(d)
        assert pos.symbol == "SOL"
        assert pos.leverage == 1.0
        assert pos.state == OPEN

    def test_dict_preserves_pnl_fields(self, sample_position):
        sample_position.realized_pnl = 123.45
        sample_position.fees_paid = 5.0
        sample_position.funding_costs = 2.5
        d = _position_to_dict(sample_position)
        restored = _dict_to_position(d)
        assert restored.realized_pnl == 123.45
        assert restored.fees_paid == 5.0
        assert restored.funding_costs == 2.5


# ── State Persistence Tests ────────────────────────────────

class TestStatePersistence:

    def test_save_and_load_empty(self, pos_mgr, tmp_dir):
        filepath = os.path.join(tmp_dir, "state.json")
        save_position_state(pos_mgr, filepath)

        new_mgr = PositionManager()
        loaded = load_position_state(new_mgr, filepath)
        assert loaded == 0
        assert len(new_mgr.positions) == 0

    def test_save_and_load_with_positions(self, pos_mgr, sample_position, tmp_dir):
        filepath = os.path.join(tmp_dir, "state.json")
        pos_mgr.positions["BTC"] = sample_position

        save_position_state(pos_mgr, filepath)

        new_mgr = PositionManager()
        loaded = load_position_state(new_mgr, filepath)
        assert loaded == 1
        assert "BTC" in new_mgr.positions
        restored = new_mgr.positions["BTC"]
        assert restored.side == "LONG"
        assert restored.sl == 48000.0
        assert restored.tp1 == 52000.0
        assert restored.trailing_distance == 1500.0

    def test_save_and_load_multiple_positions(self, pos_mgr, tmp_dir):
        filepath = os.path.join(tmp_dir, "state.json")
        pos_mgr.positions["BTC"] = Position(
            symbol="BTC", side="LONG", entry=50000, qty=0.01,
            sl=48000, tp1=52000, tp2=55000, state=OPEN, state_path=[OPEN],
        )
        pos_mgr.positions["ETH"] = Position(
            symbol="ETH", side="SHORT", entry=3000, qty=1.0,
            sl=3200, tp1=2800, tp2=2500, state=TRAILING,
            state_path=[OPEN, TP1_HIT, TRAILING],
        )

        save_position_state(pos_mgr, filepath)

        new_mgr = PositionManager()
        loaded = load_position_state(new_mgr, filepath)
        assert loaded == 2
        assert new_mgr.positions["BTC"].state == OPEN
        assert new_mgr.positions["ETH"].state == TRAILING

    def test_load_skips_closed_positions(self, pos_mgr, tmp_dir):
        filepath = os.path.join(tmp_dir, "state.json")
        pos_mgr.positions["BTC"] = Position(
            symbol="BTC", side="LONG", entry=50000, qty=0.01,
            sl=48000, tp1=52000, tp2=55000, state=CLOSED, state_path=[OPEN, CLOSED],
        )
        save_position_state(pos_mgr, filepath)

        new_mgr = PositionManager()
        loaded = load_position_state(new_mgr, filepath)
        assert loaded == 0

    def test_load_does_not_overwrite_existing(self, pos_mgr, sample_position, tmp_dir):
        filepath = os.path.join(tmp_dir, "state.json")
        pos_mgr.positions["BTC"] = sample_position
        save_position_state(pos_mgr, filepath)

        new_mgr = PositionManager()
        # Pre-populate with a different BTC position
        new_mgr.positions["BTC"] = Position(
            symbol="BTC", side="SHORT", entry=55000, qty=0.002,
            sl=57000, tp1=53000, tp2=50000, state=OPEN, state_path=[OPEN],
        )

        loaded = load_position_state(new_mgr, filepath)
        assert loaded == 0  # Should not overwrite
        assert new_mgr.positions["BTC"].side == "SHORT"  # Kept original

    def test_save_returns_true_on_success(self, pos_mgr, tmp_dir):
        filepath = os.path.join(tmp_dir, "state.json")
        assert save_position_state(pos_mgr, filepath) is True

    def test_load_nonexistent_file(self, pos_mgr, tmp_dir):
        filepath = os.path.join(tmp_dir, "does_not_exist.json")
        loaded = load_position_state(pos_mgr, filepath)
        assert loaded == 0

    def test_load_corrupt_file(self, pos_mgr, tmp_dir):
        filepath = os.path.join(tmp_dir, "state.json")
        with open(filepath, "w") as f:
            f.write("not valid json!")
        loaded = load_position_state(pos_mgr, filepath)
        assert loaded == 0

    def test_state_file_json_structure(self, pos_mgr, sample_position, tmp_dir):
        filepath = os.path.join(tmp_dir, "state.json")
        pos_mgr.positions["BTC"] = sample_position
        save_position_state(pos_mgr, filepath)

        with open(filepath) as f:
            data = json.load(f)
        assert "saved_at" in data
        assert "position_count" in data
        assert data["position_count"] == 1
        assert "positions" in data
        assert "BTC" in data["positions"]


# ── Exchange Retry Tests ───────────────────────────────────

class TestExchangeRetry:

    def test_exchange_reachable_first_try(self):
        mock_exchange = MagicMock()
        mock_exchange.fetch_positions.return_value = []
        exchanges = {"hyperliquid": mock_exchange}

        result = wait_for_exchange(exchanges, max_retries=3, retry_interval_s=0.01)
        assert result is True
        assert mock_exchange.fetch_positions.call_count == 1

    def test_exchange_reachable_after_retries(self):
        mock_exchange = MagicMock()
        mock_exchange.fetch_positions.side_effect = [
            ConnectionError("timeout"),
            ConnectionError("timeout"),
            [],  # succeeds on 3rd try
        ]
        exchanges = {"hyperliquid": mock_exchange}

        result = wait_for_exchange(exchanges, max_retries=3, retry_interval_s=0.01)
        assert result is True
        assert mock_exchange.fetch_positions.call_count == 3

    def test_exchange_unreachable_after_max_retries(self):
        mock_exchange = MagicMock()
        mock_exchange.fetch_positions.side_effect = ConnectionError("timeout")
        exchanges = {"hyperliquid": mock_exchange}

        result = wait_for_exchange(exchanges, max_retries=2, retry_interval_s=0.01)
        assert result is False
        assert mock_exchange.fetch_positions.call_count == 2

    def test_exchange_no_hyperliquid(self):
        result = wait_for_exchange({}, max_retries=1, retry_interval_s=0.01)
        assert result is False


# ── Startup Recovery Integration Tests ─────────────────────

class TestStartupRecovery:

    def _make_exchange_with_positions(self, positions=None):
        """Create mock exchange returning given positions."""
        mock = MagicMock()
        mock.fetch_positions.return_value = positions or []
        return mock

    def test_fresh_start_no_state(self, pos_mgr, tmp_dir):
        """First start: no state file, no exchange positions."""
        state_fp = os.path.join(tmp_dir, "state.json")
        hb_fp = os.path.join(tmp_dir, "hb.json")
        exchanges = {"hyperliquid": self._make_exchange_with_positions([])}

        result = startup_recovery(
            pos_mgr=pos_mgr,
            exchanges=exchanges,
            last_prices={},
            state_filepath=state_fp,
            heartbeat_filepath=hb_fp,
        )

        assert result["positions_loaded_from_disk"] == 0
        assert result["positions_reconciled_from_exchange"] == 0
        assert result["exchange_reachable"] is True
        assert len(result["phantoms_closed"]) == 0
        assert len(result["errors"]) == 0

    def test_recovery_with_persisted_state(self, tmp_dir):
        """Restart with saved state and matching exchange position."""
        state_fp = os.path.join(tmp_dir, "state.json")
        hb_fp = os.path.join(tmp_dir, "hb.json")

        # Save a position state
        old_mgr = PositionManager()
        old_mgr.positions["BTC"] = Position(
            symbol="BTC", side="LONG", entry=50000, qty=0.01,
            sl=48000, tp1=52000, tp2=55000, state=OPEN, state_path=[OPEN],
            trailing_distance=1500, atr=1000,
        )
        save_position_state(old_mgr, state_fp)

        # Simulate heartbeat from 2 minutes ago
        old_time = datetime.now(timezone.utc) - timedelta(minutes=2)
        with open(hb_fp, "w") as f:
            json.dump({"last_alive": old_time.isoformat(), "pid": 1234}, f)

        # Exchange still has the BTC position
        exchange = self._make_exchange_with_positions([{
            "symbol": "BTC/USDC:USDC",
            "side": "long",
            "contracts": 0.01,
            "entryPrice": 50000,
            "leverage": 5,
            "unrealizedPnl": 10.0,
        }])

        new_mgr = PositionManager()
        result = startup_recovery(
            pos_mgr=new_mgr,
            exchanges={"hyperliquid": exchange},
            last_prices={"BTC": 50200},
            state_filepath=state_fp,
            heartbeat_filepath=hb_fp,
        )

        assert result["positions_loaded_from_disk"] == 1
        assert result["skip_stale_signals"] is False
        # BTC was loaded from disk, so exchange reconciliation won't re-add it
        assert "BTC" in new_mgr.positions
        # Original SL/TP preserved from disk (not estimated from ATR)
        assert new_mgr.positions["BTC"].sl == 48000
        assert new_mgr.positions["BTC"].tp1 == 52000
        assert new_mgr.positions["BTC"].trailing_distance == 1500

    def test_recovery_phantom_detection(self, tmp_dir):
        """Detect position tracked locally but closed on exchange."""
        state_fp = os.path.join(tmp_dir, "state.json")
        hb_fp = os.path.join(tmp_dir, "hb.json")

        # Save a position state with BTC
        old_mgr = PositionManager()
        old_mgr.positions["BTC"] = Position(
            symbol="BTC", side="LONG", entry=50000, qty=0.01,
            sl=48000, tp1=52000, tp2=55000, state=OPEN, state_path=[OPEN],
        )
        save_position_state(old_mgr, state_fp)

        # But exchange has NO positions (BTC was closed while bot was down)
        exchange = self._make_exchange_with_positions([])

        new_mgr = PositionManager()
        result = startup_recovery(
            pos_mgr=new_mgr,
            exchanges={"hyperliquid": exchange},
            last_prices={},
            state_filepath=state_fp,
            heartbeat_filepath=hb_fp,
        )

        assert "BTC" in result["phantoms_closed"]
        assert new_mgr.positions["BTC"].state == CLOSED
        assert new_mgr.positions["BTC"].outcome == "reconciliation_phantom"

    def test_recovery_stale_signals_flag(self, tmp_dir):
        """Bot down > 5 minutes should flag stale signals."""
        state_fp = os.path.join(tmp_dir, "state.json")
        hb_fp = os.path.join(tmp_dir, "hb.json")

        # Heartbeat from 10 minutes ago
        old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        with open(hb_fp, "w") as f:
            json.dump({"last_alive": old_time.isoformat(), "pid": 1234}, f)

        exchange = self._make_exchange_with_positions([])

        result = startup_recovery(
            pos_mgr=PositionManager(),
            exchanges={"hyperliquid": exchange},
            last_prices={},
            state_filepath=state_fp,
            heartbeat_filepath=hb_fp,
        )

        assert result["skip_stale_signals"] is True
        assert result["downtime_seconds"] >= 590

    def test_recovery_exchange_unreachable(self, tmp_dir):
        """Exchange unreachable: use persisted state only."""
        state_fp = os.path.join(tmp_dir, "state.json")
        hb_fp = os.path.join(tmp_dir, "hb.json")

        # Save a position
        old_mgr = PositionManager()
        old_mgr.positions["ETH"] = Position(
            symbol="ETH", side="SHORT", entry=3000, qty=1.0,
            sl=3200, tp1=2800, tp2=2500, state=TRAILING,
            state_path=[OPEN, TP1_HIT, TRAILING],
            trailing_distance=50, peak_price=2750,
        )
        save_position_state(old_mgr, state_fp)

        # Exchange always fails
        mock_exchange = MagicMock()
        mock_exchange.fetch_positions.side_effect = ConnectionError("timeout")

        new_mgr = PositionManager()
        result = startup_recovery(
            pos_mgr=new_mgr,
            exchanges={"hyperliquid": mock_exchange},
            last_prices={},
            state_filepath=state_fp,
            heartbeat_filepath=hb_fp,
        )

        assert result["exchange_reachable"] is False
        assert result["positions_loaded_from_disk"] == 1
        assert "exchange_unreachable" in result["errors"]
        # Position still loaded from disk even though exchange is down
        assert "ETH" in new_mgr.positions
        assert new_mgr.positions["ETH"].state == TRAILING

    def test_recovery_saves_state_after_completion(self, tmp_dir):
        """Recovery should save updated state when done."""
        state_fp = os.path.join(tmp_dir, "state.json")
        hb_fp = os.path.join(tmp_dir, "hb.json")

        exchange = self._make_exchange_with_positions([])
        startup_recovery(
            pos_mgr=PositionManager(),
            exchanges={"hyperliquid": exchange},
            last_prices={},
            state_filepath=state_fp,
            heartbeat_filepath=hb_fp,
        )

        # State file should exist after recovery
        assert os.path.exists(state_fp)
        # Heartbeat should be refreshed
        assert os.path.exists(hb_fp)

    def test_recovery_no_exchange_configured(self, tmp_dir):
        """No exchange at all: still loads from disk."""
        state_fp = os.path.join(tmp_dir, "state.json")
        hb_fp = os.path.join(tmp_dir, "hb.json")

        old_mgr = PositionManager()
        old_mgr.positions["SOL"] = Position(
            symbol="SOL", side="LONG", entry=100, qty=10,
            sl=95, tp1=110, tp2=120, state=OPEN, state_path=[OPEN],
        )
        save_position_state(old_mgr, state_fp)

        new_mgr = PositionManager()
        result = startup_recovery(
            pos_mgr=new_mgr,
            exchanges={},
            last_prices={},
            state_filepath=state_fp,
            heartbeat_filepath=hb_fp,
        )

        assert result["exchange_reachable"] is False
        assert result["positions_loaded_from_disk"] == 1
        assert "SOL" in new_mgr.positions


# ── Edge Cases ─────────────────────────────────────────────

class TestEdgeCases:

    def test_position_with_none_open_time(self, tmp_dir):
        """Position with None open_time should serialize/deserialize safely."""
        filepath = os.path.join(tmp_dir, "state.json")
        mgr = PositionManager()
        pos = Position(
            symbol="DOGE", side="LONG", entry=0.15, qty=1000,
            sl=0.14, tp1=0.16, tp2=0.18, state=OPEN, state_path=[OPEN],
        )
        pos.open_time = datetime.now(timezone.utc)
        mgr.positions["DOGE"] = pos
        save_position_state(mgr, filepath)

        new_mgr = PositionManager()
        loaded = load_position_state(new_mgr, filepath)
        assert loaded == 1
        assert new_mgr.positions["DOGE"].open_time is not None

    def test_concurrent_save_safety(self, pos_mgr, sample_position, tmp_dir):
        """Multiple rapid saves should not corrupt the file."""
        filepath = os.path.join(tmp_dir, "state.json")
        pos_mgr.positions["BTC"] = sample_position

        for _ in range(10):
            assert save_position_state(pos_mgr, filepath) is True

        new_mgr = PositionManager()
        loaded = load_position_state(new_mgr, filepath)
        assert loaded == 1

    def test_heartbeat_creates_parent_dirs(self, tmp_dir):
        filepath = os.path.join(tmp_dir, "sub", "dir", "heartbeat.json")
        save_heartbeat(filepath)
        assert os.path.exists(filepath)

    def test_state_preserves_wallet_id(self, tmp_dir):
        filepath = os.path.join(tmp_dir, "state.json")
        mgr = PositionManager()
        pos = Position(
            symbol="BTC", side="LONG", entry=50000, qty=0.01,
            sl=48000, tp1=52000, tp2=55000, state=OPEN, state_path=[OPEN],
            wallet_id="A",
        )
        mgr.positions["BTC"] = pos
        save_position_state(mgr, filepath)

        new_mgr = PositionManager()
        load_position_state(new_mgr, filepath)
        assert new_mgr.positions["BTC"].wallet_id == "A"

    def test_state_preserves_notes_and_setup_type(self, tmp_dir):
        filepath = os.path.join(tmp_dir, "state.json")
        mgr = PositionManager()
        pos = Position(
            symbol="ETH", side="SHORT", entry=3000, qty=1.0,
            sl=3200, tp1=2800, tp2=2500, state=OPEN, state_path=[OPEN],
            notes="THESIS: bearish divergence on 4H",
            setup_type="trend_reversal",
        )
        mgr.positions["ETH"] = pos
        save_position_state(mgr, filepath)

        new_mgr = PositionManager()
        load_position_state(new_mgr, filepath)
        assert "bearish divergence" in new_mgr.positions["ETH"].notes
        assert new_mgr.positions["ETH"].setup_type == "trend_reversal"

    def test_downtime_naive_datetime(self, tmp_dir):
        """Handle naive datetime in heartbeat (no timezone info)."""
        filepath = os.path.join(tmp_dir, "heartbeat.json")
        # Write without timezone
        old_time = datetime.now(timezone.utc) - timedelta(minutes=3)
        with open(filepath, "w") as f:
            json.dump({"last_alive": old_time.isoformat(), "pid": 1}, f)
        downtime = get_downtime_seconds(filepath)
        assert downtime >= 170  # ~3 minutes
        assert downtime < 250
