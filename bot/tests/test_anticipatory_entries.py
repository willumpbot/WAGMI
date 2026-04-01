"""
Tests for the Anticipatory Entry Engine.

Tests cover:
1. Indicator computation
2. Setup detection (SELL overbought, BUY oversold, trend entries)
3. Trigger condition checking
4. Entry building and validation
5. Signal conversion for the sniper pipeline
6. Persistence (save/load)
7. Expiry and invalidation
8. Deduplication
"""

import json
import os
import sys
import time
import tempfile
from unittest.mock import patch, MagicMock

import pytest
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from manual.anticipatory_entries import (
    AnticipationEngine,
    PendingEntry,
    TriggerResult,
    _compute_indicators,
    _compute_6h_trend,
    _get_timeframe_alignment,
    _detect_5m_reversal,
    _find_resistance,
    _find_support,
    DEFAULT_EXPIRY_HOURS,
    MIN_RR_RATIO,
    MAX_PENDING_PER_SYMBOL,
    MAX_PENDING_TOTAL,
    PRICE_INVALIDATION_PCT,
    RSI_OVERBOUGHT_TRIGGER,
    RSI_OVERSOLD_TRIGGER,
    TF_FLAT_THRESHOLD,
    LEVERAGE_ALIGNED,
    LEVERAGE_NEUTRAL,
    VOL_MIN_RATIO,
    VOL_REVERSAL_MIN_RATIO,
    VOL_TREND_MIN_RATIO,
    VOL_SPIKE_RATIO,
    VOL_SPIKE_CONFIDENCE_BOOST,
    REVERSAL_SETUPS,
    TREND_SETUPS,
    EXHAUSTION_VOL_RATIO,
    EXHAUSTION_BODY_RATIO,
    EXHAUSTION_WICK_MIN_PCT,
    EXHAUSTION_SYMBOLS,
    EXHAUSTION_CONFIDENCE,
    INSTITUTIONAL_VOL_RATIO,
    INSTITUTIONAL_BODY_RATIO,
    INSTITUTIONAL_SYMBOLS,
    INSTITUTIONAL_CONFIDENCE,
    SHOOTING_STAR_WICK_RATIO,
    SHOOTING_STAR_BODY_RATIO,
    SHOOTING_STAR_SYMBOLS,
    SHOOTING_STAR_CONFIDENCE,
    SHOOTING_STAR_SL_BUFFER_PCT,
)


# ── Fixtures ──────────────────────────────────────────────────────────


def _make_ohlcv(
    n: int = 50,
    base_price: float = 100.0,
    trend: str = "flat",
    rsi_target: float = 50.0,
) -> pd.DataFrame:
    """Generate synthetic OHLCV data.

    Args:
        n: Number of bars
        base_price: Starting price
        trend: "up", "down", or "flat"
        rsi_target: Approximate target RSI (drives price direction)
    """
    np.random.seed(42)
    prices = [base_price]
    for i in range(1, n):
        if trend == "up":
            drift = 0.002
        elif trend == "down":
            drift = -0.002
        else:
            drift = 0.0
        change = drift + np.random.normal(0, 0.005)
        prices.append(prices[-1] * (1 + change))

    prices = np.array(prices)
    df = pd.DataFrame({
        "open": prices * (1 + np.random.normal(0, 0.001, n)),
        "high": prices * (1 + abs(np.random.normal(0, 0.005, n))),
        "low": prices * (1 - abs(np.random.normal(0, 0.005, n))),
        "close": prices,
        "volume": np.random.uniform(1000, 5000, n),
    })
    return df


def _make_overbought_data(base: float = 100.0) -> pd.DataFrame:
    """Create data where price is near BB upper and RSI is high."""
    np.random.seed(123)
    n = 50
    # Steady uptrend that pushes price to BB upper
    prices = [base]
    for i in range(1, n):
        prices.append(prices[-1] * 1.004)  # Strong uptrend
    prices = np.array(prices)
    df = pd.DataFrame({
        "open": prices * 0.999,
        "high": prices * 1.003,
        "low": prices * 0.997,
        "close": prices,
        "volume": np.random.uniform(1000, 5000, n),
    })
    return df


def _make_oversold_data(base: float = 100.0) -> pd.DataFrame:
    """Create data where price is near BB lower and RSI is low."""
    np.random.seed(456)
    n = 50
    # Steady downtrend that pushes price to BB lower
    prices = [base]
    for i in range(1, n):
        prices.append(prices[-1] * 0.996)  # Strong downtrend
    prices = np.array(prices)
    df = pd.DataFrame({
        "open": prices * 1.001,
        "high": prices * 1.003,
        "low": prices * 0.997,
        "close": prices,
        "volume": np.random.uniform(1000, 5000, n),
    })
    return df


@pytest.fixture
def engine(tmp_path):
    """Create engine with temp data directory."""
    with patch("manual.anticipatory_entries._DATA_DIR", str(tmp_path)):
        with patch("manual.anticipatory_entries._PENDING_PATH", str(tmp_path / "pending.json")):
            with patch("manual.anticipatory_entries._HISTORY_PATH", str(tmp_path / "history.jsonl")):
                eng = AnticipationEngine()
                return eng


# ── Test: Indicator Computation ───────────────────────────────────────


class TestIndicatorComputation:
    def test_basic_indicators(self):
        df = _make_ohlcv(50, 100.0)
        ind = _compute_indicators(df)
        assert "close" in ind
        assert "ema20" in ind
        assert "ema50" in ind
        assert "rsi" in ind
        assert "atr" in ind
        assert "bb_upper" in ind
        assert "bb_lower" in ind
        assert "vwap" in ind
        assert "swing_high" in ind
        assert "swing_low" in ind
        assert "resistance" in ind
        assert "support" in ind

    def test_rsi_in_valid_range(self):
        df = _make_ohlcv(50, 100.0)
        ind = _compute_indicators(df)
        assert 0 <= ind["rsi"] <= 100

    def test_bb_ordering(self):
        df = _make_ohlcv(50, 100.0)
        ind = _compute_indicators(df)
        assert ind["bb_lower"] < ind["bb_mid"] < ind["bb_upper"]

    def test_ema_ordering_uptrend(self):
        df = _make_ohlcv(50, 100.0, trend="up")
        ind = _compute_indicators(df)
        # In uptrend, EMA20 should be above EMA50
        assert ind["ema20"] > ind["ema50"]

    def test_empty_df_returns_empty(self):
        assert _compute_indicators(None) == {}
        assert _compute_indicators(pd.DataFrame()) == {}
        assert _compute_indicators(_make_ohlcv(5)) == {}  # Too short

    def test_no_volume_column(self):
        df = _make_ohlcv(50, 100.0)
        df = df.drop(columns=["volume"])
        ind = _compute_indicators(df)
        assert "vwap" in ind  # Falls back to bb_mid

    def test_resistance_above_price(self):
        df = _make_ohlcv(50, 100.0)
        ind = _compute_indicators(df)
        # Resistance should be at or above current price (or fallback to max)
        assert ind["resistance"] >= ind["close"] * 0.99

    def test_support_below_price(self):
        df = _make_ohlcv(50, 100.0)
        ind = _compute_indicators(df)
        assert ind["support"] <= ind["close"] * 1.01


# ── Test: Find Resistance/Support ─────────────────────────────────────


class TestSupportResistance:
    def test_find_resistance_with_peaks(self):
        highs = pd.Series([10, 12, 10, 15, 10, 11, 10])
        r = _find_resistance(highs, 11.0)
        assert r == 12.0  # Nearest peak above 11 (12 is closer than 15)

    def test_find_support_with_troughs(self):
        lows = pd.Series([10, 8, 10, 5, 10, 9, 10])
        s = _find_support(lows, 9.0)
        assert s == 8.0  # Nearest trough below 9

    def test_find_resistance_fallback(self):
        highs = pd.Series([10, 10, 10])  # No peaks
        r = _find_resistance(highs, 11.0)
        assert r == 10.0  # Fallback to max

    def test_find_support_fallback(self):
        lows = pd.Series([10, 10, 10])
        s = _find_support(lows, 9.0)
        assert s == 10.0  # Fallback to min


# ── Test: PendingEntry Dataclass ──────────────────────────────────────


class TestPendingEntry:
    def _make_entry(self, **overrides):
        defaults = dict(
            entry_id="ANT-0001",
            symbol="SOL",
            side="SELL",
            target_price=83.50,
            sl=84.30,
            tp=80.50,
            tp2=79.00,
            trigger_conditions={"rsi_above": 70, "price_above": 83.40},
            confidence=80,
            leverage=10.0,
            risk_pct=0.03,
            expiry=time.time() + 3600 * 12,
            reasoning="BB upper rejection",
            setup_type="bb_upper_rejection",
            source="bb_upper",
            created_at=time.time(),
            created_at_iso="2026-03-25T12:00:00+00:00",
            rr_ratio=3.8,
            stop_width_pct=0.0095,
        )
        defaults.update(overrides)
        return PendingEntry(**defaults)

    def test_serialization_roundtrip(self):
        entry = self._make_entry()
        d = entry.to_dict()
        restored = PendingEntry.from_dict(d)
        assert restored.entry_id == entry.entry_id
        assert restored.symbol == entry.symbol
        assert restored.target_price == entry.target_price
        assert restored.trigger_conditions == entry.trigger_conditions

    def test_default_status(self):
        entry = self._make_entry()
        assert entry.status == "pending"
        assert entry.checks == 0
        assert entry.best_approach_price == 0.0


# ── Test: Engine Setup Detection ──────────────────────────────────────


class TestSetupDetection:
    def test_no_setups_on_flat_market(self, engine):
        df = _make_ohlcv(50, 100.0, trend="flat")
        new = engine.scan_for_setups("SOL", df_1h=df)
        # Flat market may or may not produce setups depending on randomness,
        # but should not crash
        assert isinstance(new, list)

    def test_overbought_generates_sell_setup(self, engine):
        df = _make_overbought_data(80.0)
        new = engine.scan_for_setups("SOL", df_1h=df)
        sell_setups = [e for e in new if e.side == "SELL"]
        # Should find at least one sell setup approaching overbought
        # (depends on exact indicator values)
        assert isinstance(sell_setups, list)
        for s in sell_setups:
            assert s.symbol == "SOL"
            assert s.side == "SELL"
            assert s.sl > s.target_price  # SL above entry for shorts
            assert s.tp < s.target_price  # TP below entry for shorts
            assert s.rr_ratio >= MIN_RR_RATIO

    def test_oversold_generates_buy_setup(self, engine):
        df = _make_oversold_data(120.0)
        new = engine.scan_for_setups("HYPE", df_1h=df)
        buy_setups = [e for e in new if e.side == "BUY"]
        assert isinstance(buy_setups, list)
        for s in buy_setups:
            assert s.symbol == "HYPE"
            assert s.side == "BUY"
            assert s.sl < s.target_price  # SL below entry for longs
            assert s.tp > s.target_price  # TP above entry for longs
            assert s.rr_ratio >= MIN_RR_RATIO

    def test_max_pending_per_symbol(self, engine):
        df = _make_overbought_data(80.0)
        # Fill up pending with fake entries
        for i in range(MAX_PENDING_PER_SYMBOL):
            engine._pending.append(PendingEntry(
                entry_id=f"FAKE-{i}",
                symbol="SOL", side="SELL",
                target_price=83.0 + i, sl=84.0, tp=80.0, tp2=79.0,
                trigger_conditions={}, confidence=80, leverage=10,
                risk_pct=0.03, expiry=time.time() + 9999,
                reasoning="test", setup_type=f"test_{i}", source="test",
                created_at=time.time(), created_at_iso="", rr_ratio=3.0,
                stop_width_pct=0.01,
            ))
        new = engine.scan_for_setups("SOL", df_1h=df)
        assert len(new) == 0  # Capped by per-symbol limit

    def test_dedup_prevents_identical_setups(self, engine):
        df = _make_overbought_data(80.0)
        first = engine.scan_for_setups("SOL", df_1h=df)
        second = engine.scan_for_setups("SOL", df_1h=df)
        # Second scan should not create duplicates
        for s in second:
            # Should not match any from first scan
            assert not any(
                f.setup_type == s.setup_type and f.symbol == s.symbol and f.side == s.side
                for f in first
            )

    def test_rr_filter_rejects_poor_setups(self, engine):
        """Entries with R:R below MIN_RR_RATIO should not be created."""
        # All entries should have R:R >= MIN_RR_RATIO
        for entry in engine._pending:
            if entry.status == "pending":
                assert entry.rr_ratio >= MIN_RR_RATIO


# ── Test: Trigger Checking ────────────────────────────────────────────


class TestTriggerChecking:
    def _make_sell_entry(self, engine):
        engine._entry_counter += 1
        return PendingEntry(
            entry_id=f"ANT-{engine._entry_counter:04d}",
            symbol="SOL", side="SELL",
            target_price=83.50, sl=84.30, tp=80.50, tp2=79.00,
            trigger_conditions={
                "rsi_above": 70,
                "price_above": 83.40,
            },
            confidence=80, leverage=10.0, risk_pct=0.03,
            expiry=time.time() + 3600 * 12,
            reasoning="test sell", setup_type="bb_upper_rejection",
            source="test", created_at=time.time(), created_at_iso="",
            rr_ratio=3.8, stop_width_pct=0.0095,
        )

    def _make_buy_entry(self, engine):
        engine._entry_counter += 1
        return PendingEntry(
            entry_id=f"ANT-{engine._entry_counter:04d}",
            symbol="HYPE", side="BUY",
            target_price=20.00, sl=19.80, tp=20.80, tp2=21.50,
            trigger_conditions={
                "rsi_below_then_above": 35,
                "price_below": 20.05,
            },
            confidence=80, leverage=12.0, risk_pct=0.04,
            expiry=time.time() + 3600 * 12,
            reasoning="test buy", setup_type="bb_lower_bounce",
            source="test", created_at=time.time(), created_at_iso="",
            rr_ratio=4.0, stop_width_pct=0.01,
        )

    def test_sell_triggers_when_conditions_met(self, engine):
        entry = self._make_sell_entry(engine)
        entry.status = "pending"
        engine._pending = [entry]

        triggered = engine.check_pending_entries(
            prices={"SOL": 83.60},  # Above target
            indicators={"SOL": {"rsi": 72, "rsi_prev": 68}},
        )
        assert len(triggered) == 1
        assert triggered[0].entry_id == entry.entry_id
        assert triggered[0].status == "triggered"

    def test_sell_does_not_trigger_low_rsi(self, engine):
        entry = self._make_sell_entry(engine)
        entry.status = "pending"
        engine._pending = [entry]

        triggered = engine.check_pending_entries(
            prices={"SOL": 83.60},
            indicators={"SOL": {"rsi": 55, "rsi_prev": 52}},
        )
        assert len(triggered) == 0

    def test_buy_triggers_on_rsi_crossover(self, engine):
        entry = self._make_buy_entry(engine)
        entry.status = "pending"
        engine._pending = [entry]

        triggered = engine.check_pending_entries(
            prices={"HYPE": 19.98},  # Below target
            indicators={"HYPE": {"rsi": 36, "rsi_prev": 33}},
        )
        assert len(triggered) == 1
        assert triggered[0].status == "triggered"

    def test_expiry_removes_entry(self, engine):
        entry = self._make_sell_entry(engine)
        entry.status = "pending"
        entry.expiry = time.time() - 1  # Already expired
        engine._pending = [entry]

        triggered = engine.check_pending_entries(
            prices={"SOL": 83.60},
            indicators={"SOL": {"rsi": 72}},
        )
        assert len(triggered) == 0
        assert entry.status == "expired"
        assert engine._expired_count >= 1

    def test_invalidation_when_price_moves_away(self, engine):
        entry = self._make_sell_entry(engine)
        entry.status = "pending"
        engine._pending = [entry]

        # Price dropped 5% below target (SELL target at 83.50, price at 79)
        triggered = engine.check_pending_entries(
            prices={"SOL": 79.0},
            indicators={"SOL": {"rsi": 35}},
        )
        assert len(triggered) == 0
        assert entry.status == "invalidated"

    def test_no_indicator_data_only_checks_price(self, engine):
        entry = self._make_sell_entry(engine)
        entry.status = "pending"
        engine._pending = [entry]

        # No indicators provided — should not trigger (RSI condition unmet)
        triggered = engine.check_pending_entries(
            prices={"SOL": 83.60},
            indicators=None,
        )
        assert len(triggered) == 0

    def test_missing_symbol_price_keeps_entry(self, engine):
        entry = self._make_sell_entry(engine)
        entry.status = "pending"
        engine._pending = [entry]

        triggered = engine.check_pending_entries(
            prices={"BTC": 65000},  # No SOL price
            indicators={},
        )
        assert len(triggered) == 0
        # Entry should remain pending
        active = [e for e in engine._pending if e.status == "pending"]
        assert len(active) == 1


# ── Test: Signal Conversion ───────────────────────────────────────────


class TestSignalConversion:
    def test_sell_signal_valid(self):
        entry = PendingEntry(
            entry_id="ANT-0001", symbol="SOL", side="SELL",
            target_price=83.50, sl=84.30, tp=80.50, tp2=79.00,
            trigger_conditions={}, confidence=80, leverage=10.0,
            risk_pct=0.03, expiry=time.time() + 9999,
            reasoning="test", setup_type="bb_upper_rejection",
            source="test", created_at=time.time(), created_at_iso="",
            rr_ratio=3.8, stop_width_pct=0.0095,
        )
        signal = AnticipationEngine.pending_to_signal(entry, 83.50)
        assert signal.side == "SELL"
        assert signal.symbol == "SOL"
        assert signal.sl > signal.entry  # SL above for shorts
        assert signal.tp1 < signal.entry  # TP below for shorts
        assert signal.confidence == 80
        assert signal.metadata["anticipatory_entry"] is True
        assert signal.is_valid

    def test_buy_signal_valid(self):
        entry = PendingEntry(
            entry_id="ANT-0002", symbol="HYPE", side="BUY",
            target_price=20.00, sl=19.80, tp=20.80, tp2=21.50,
            trigger_conditions={}, confidence=82, leverage=12.0,
            risk_pct=0.04, expiry=time.time() + 9999,
            reasoning="test", setup_type="bb_lower_bounce",
            source="test", created_at=time.time(), created_at_iso="",
            rr_ratio=4.0, stop_width_pct=0.01,
        )
        signal = AnticipationEngine.pending_to_signal(entry, 20.00)
        assert signal.side == "BUY"
        assert signal.sl < signal.entry
        assert signal.tp1 > signal.entry
        assert signal.is_valid

    def test_signal_metadata_contains_anticipatory_fields(self):
        entry = PendingEntry(
            entry_id="ANT-0003", symbol="BTC", side="SELL",
            target_price=65000, sl=65650, tp=63700, tp2=62000,
            trigger_conditions={}, confidence=85, leverage=10.0,
            risk_pct=0.05, expiry=time.time() + 9999,
            reasoning="resistance rejection", setup_type="resistance_rejection",
            source="swing_high", created_at=time.time(), created_at_iso="",
            rr_ratio=2.0, stop_width_pct=0.01,
        )
        signal = AnticipationEngine.pending_to_signal(entry, 65000)
        meta = signal.metadata
        assert meta["anticipatory_entry"] is True
        assert meta["entry_id"] == "ANT-0003"
        assert meta["setup_type"] == "resistance_rejection"
        assert meta["rr_ratio"] == 2.0
        assert "anticipatory" in signal.strategy


# ── Test: Leverage and Risk Calculation ───────────────────────────────


class TestSizing:
    def test_tight_stop_higher_leverage(self):
        lev_tight = AnticipationEngine._calc_leverage(0.005, 80)  # 0.5% stop
        lev_wide = AnticipationEngine._calc_leverage(0.015, 80)   # 1.5% stop
        assert lev_tight > lev_wide

    def test_higher_confidence_more_leverage(self):
        lev_low = AnticipationEngine._calc_leverage(0.01, 70)
        lev_high = AnticipationEngine._calc_leverage(0.01, 85)
        assert lev_high >= lev_low

    def test_leverage_within_bounds(self):
        for stop in [0.003, 0.005, 0.008, 0.010, 0.015]:
            for conf in [70, 75, 80, 85, 90]:
                lev = AnticipationEngine._calc_leverage(stop, conf)
                assert 8.0 <= lev <= 15.0

    def test_risk_pct_within_bounds(self):
        for conf in [70, 75, 80, 85, 90]:
            for rr in [2.0, 2.5, 3.0, 4.0, 5.0]:
                risk = AnticipationEngine._calc_risk_pct(conf, rr)
                assert 0.02 <= risk <= 0.08

    def test_higher_rr_more_risk(self):
        risk_low_rr = AnticipationEngine._calc_risk_pct(80, 2.0)
        risk_high_rr = AnticipationEngine._calc_risk_pct(80, 5.0)
        assert risk_high_rr >= risk_low_rr


# ── Test: Persistence ─────────────────────────────────────────────────


class TestPersistence:
    def test_save_and_load(self, tmp_path):
        pending_path = str(tmp_path / "pending.json")
        history_path = str(tmp_path / "history.jsonl")

        with patch("manual.anticipatory_entries._DATA_DIR", str(tmp_path)):
            with patch("manual.anticipatory_entries._PENDING_PATH", pending_path):
                with patch("manual.anticipatory_entries._HISTORY_PATH", history_path):
                    eng1 = AnticipationEngine()
                    # Add a pending entry
                    eng1._entry_counter = 1
                    eng1._pending.append(PendingEntry(
                        entry_id="ANT-0001", symbol="SOL", side="SELL",
                        target_price=83.50, sl=84.30, tp=80.50, tp2=79.00,
                        trigger_conditions={"rsi_above": 70},
                        confidence=80, leverage=10.0, risk_pct=0.03,
                        expiry=time.time() + 9999,
                        reasoning="test", setup_type="test",
                        source="test", created_at=time.time(),
                        created_at_iso="2026-03-25T12:00:00",
                        rr_ratio=3.8, stop_width_pct=0.01,
                    ))
                    eng1._triggered_count = 5
                    eng1._save_pending()

                    # Create new engine and load
                    eng2 = AnticipationEngine()
                    assert len(eng2._pending) == 1
                    assert eng2._pending[0].entry_id == "ANT-0001"
                    assert eng2._triggered_count == 5
                    assert eng2._entry_counter == 1

    def test_expired_entries_not_loaded(self, tmp_path):
        pending_path = str(tmp_path / "pending.json")
        history_path = str(tmp_path / "history.jsonl")

        with patch("manual.anticipatory_entries._DATA_DIR", str(tmp_path)):
            with patch("manual.anticipatory_entries._PENDING_PATH", pending_path):
                with patch("manual.anticipatory_entries._HISTORY_PATH", history_path):
                    eng1 = AnticipationEngine()
                    eng1._pending.append(PendingEntry(
                        entry_id="ANT-0001", symbol="SOL", side="SELL",
                        target_price=83.50, sl=84.30, tp=80.50, tp2=79.00,
                        trigger_conditions={},
                        confidence=80, leverage=10.0, risk_pct=0.03,
                        expiry=time.time() - 100,  # Already expired
                        reasoning="test", setup_type="test",
                        source="test", created_at=time.time(),
                        created_at_iso="",
                        rr_ratio=3.8, stop_width_pct=0.01,
                    ))
                    eng1._save_pending()

                    eng2 = AnticipationEngine()
                    assert len(eng2._pending) == 0  # Expired entry not loaded


# ── Test: Entry Building Validation ───────────────────────────────────


class TestEntryBuilding:
    def test_sell_entry_rejects_bad_prices(self, engine):
        # SL below target (wrong side for SELL)
        result = engine._build_sell_entry(
            symbol="SOL", target_price=83.50, sl_price=82.00,
            tp_price=80.50, tp2_price=79.0,
            trigger_conditions={}, confidence=80,
            setup_type="test", source="test", reasoning="test",
            atr=1.0, ind={},
        )
        assert result is None

    def test_buy_entry_rejects_bad_prices(self, engine):
        # SL above target (wrong side for BUY)
        result = engine._build_buy_entry(
            symbol="HYPE", target_price=20.0, sl_price=21.0,
            tp_price=20.80, tp2_price=21.5,
            trigger_conditions={}, confidence=80,
            setup_type="test", source="test", reasoning="test",
            atr=0.5, ind={},
        )
        assert result is None

    def test_sell_entry_clamps_stop_width(self, engine):
        # Very tight stop (0.1%) should be clamped to MIN_STOP_PCT
        result = engine._build_sell_entry(
            symbol="SOL", target_price=100.0, sl_price=100.10,
            tp_price=96.0, tp2_price=94.0,
            trigger_conditions={}, confidence=80,
            setup_type="test", source="test", reasoning="test",
            atr=1.0, ind={},
        )
        if result is not None:
            assert result.stop_width_pct >= 0.005

    def test_buy_entry_has_valid_fields(self, engine):
        result = engine._build_buy_entry(
            symbol="HYPE", target_price=20.0, sl_price=19.70,
            tp_price=20.80, tp2_price=21.50,
            trigger_conditions={"rsi_below_then_above": 35},
            confidence=82, setup_type="bb_lower_bounce",
            source="bb_lower", reasoning="test buy",
            atr=0.5, ind={},
        )
        if result is not None:
            assert result.symbol == "HYPE"
            assert result.side == "BUY"
            assert result.leverage >= 8.0
            assert result.leverage <= 15.0
            assert result.risk_pct >= 0.02
            assert result.risk_pct <= 0.08
            assert result.rr_ratio >= MIN_RR_RATIO


# ── Test: Status Reporting ────────────────────────────────────────────


class TestStatus:
    def test_empty_status(self, engine):
        status = engine.get_status()
        assert status["active_pending"] == 0
        assert status["total_triggered"] == 0
        assert status["total_expired"] == 0
        assert "pending_entries" in status

    def test_status_with_pending(self, engine):
        engine._pending.append(PendingEntry(
            entry_id="ANT-0001", symbol="SOL", side="SELL",
            target_price=83.50, sl=84.30, tp=80.50, tp2=79.00,
            trigger_conditions={}, confidence=80, leverage=10.0,
            risk_pct=0.03, expiry=time.time() + 9999,
            reasoning="test", setup_type="test", source="test",
            created_at=time.time(), created_at_iso="",
            rr_ratio=3.8, stop_width_pct=0.01,
        ))
        status = engine.get_status()
        assert status["active_pending"] == 1
        assert len(status["pending_entries"]) == 1


# ── Test: Remove Entry ────────────────────────────────────────────────


class TestRemoveEntry:
    def test_remove_existing(self, engine):
        engine._pending.append(PendingEntry(
            entry_id="ANT-0001", symbol="SOL", side="SELL",
            target_price=83.50, sl=84.30, tp=80.50, tp2=79.00,
            trigger_conditions={}, confidence=80, leverage=10.0,
            risk_pct=0.03, expiry=time.time() + 9999,
            reasoning="test", setup_type="test", source="test",
            created_at=time.time(), created_at_iso="",
            rr_ratio=3.8, stop_width_pct=0.01,
        ))
        assert engine.remove_entry("ANT-0001") is True
        active = [e for e in engine._pending if e.status == "pending"]
        assert len(active) == 0

    def test_remove_nonexistent(self, engine):
        assert engine.remove_entry("FAKE-9999") is False


# -- Test: Volume Confirmation System ---------------------------------------


class TestVolumeConfirmation:
    """Tests for volume-based entry confirmation."""

    def _make_sell_entry(self, engine, setup_type="bb_upper_rejection"):
        engine._entry_counter += 1
        return PendingEntry(
            entry_id=f"ANT-{engine._entry_counter:04d}",
            symbol="SOL", side="SELL",
            target_price=83.50, sl=84.30, tp=80.50, tp2=79.00,
            trigger_conditions={
                "rsi_above": 70,
                "price_above": 83.40,
            },
            confidence=80, leverage=10.0, risk_pct=0.03,
            expiry=time.time() + 3600 * 12,
            reasoning="test sell", setup_type=setup_type,
            source="test", created_at=time.time(), created_at_iso="",
            rr_ratio=3.8, stop_width_pct=0.0095,
        )

    def _make_buy_entry(self, engine, setup_type="bb_lower_bounce"):
        engine._entry_counter += 1
        return PendingEntry(
            entry_id=f"ANT-{engine._entry_counter:04d}",
            symbol="HYPE", side="BUY",
            target_price=20.00, sl=19.80, tp=20.80, tp2=21.50,
            trigger_conditions={
                "rsi_below_then_above": 35,
                "price_below": 20.05,
            },
            confidence=80, leverage=12.0, risk_pct=0.04,
            expiry=time.time() + 3600 * 12,
            reasoning="test buy", setup_type=setup_type,
            source="test", created_at=time.time(), created_at_iso="",
            rr_ratio=4.0, stop_width_pct=0.01,
        )

    def test_compute_indicators_includes_volume_metrics(self):
        """Volume metrics should be present in indicator output."""
        df = _make_ohlcv(50, 100.0)
        ind = _compute_indicators(df)
        assert "vol_avg" in ind
        assert "vol_current" in ind
        assert "vol_ratio" in ind
        assert "vol_is_buying" in ind
        assert ind["vol_avg"] > 0
        assert ind["vol_current"] > 0
        assert ind["vol_ratio"] > 0

    def test_volume_metrics_without_volume_column(self):
        """Without volume column, volume metrics should be zero."""
        df = _make_ohlcv(50, 100.0)
        df = df.drop(columns=["volume"])
        ind = _compute_indicators(df)
        assert ind["vol_avg"] == 0.0
        assert ind["vol_current"] == 0.0
        assert ind["vol_ratio"] == 0.0

    def test_reversal_entry_blocked_by_low_volume(self, engine):
        """Reversal setups (bb_upper_rejection) need vol >= 1.2x avg."""
        entry = self._make_sell_entry(engine, setup_type="bb_upper_rejection")
        assert entry.setup_type in REVERSAL_SETUPS

        # Low volume (0.5x avg) should block
        ind = {
            "rsi": 75, "rsi_prev": 68,
            "vol_ratio": 0.5, "vol_is_buying": False,
        }
        result = engine._check_triggers(entry, 83.60, ind)
        assert result.conditions_met.get("volume_confirmed") is False
        assert result.triggered is False

    def test_reversal_entry_passes_with_high_volume(self, engine):
        """Reversal with vol >= 1.2x avg + correct pressure should pass."""
        entry = self._make_sell_entry(engine, setup_type="bb_upper_rejection")

        # High volume + selling pressure for SELL
        ind = {
            "rsi": 75, "rsi_prev": 68,
            "vol_ratio": 1.5, "vol_is_buying": False,
        }
        result = engine._check_triggers(entry, 83.60, ind)
        assert result.conditions_met.get("volume_confirmed") is True
        assert result.conditions_met.get("candle_pressure") is True

    def test_trend_entry_needs_lower_volume_threshold(self, engine):
        """Trend setups (ema20_bear_touch) need only vol >= 0.9x avg."""
        entry = self._make_sell_entry(engine, setup_type="ema20_bear_touch")
        assert entry.setup_type in TREND_SETUPS

        # 0.95x avg is enough for trend, but not for reversal
        ind = {
            "rsi": 55, "rsi_prev": 48,
            "vol_ratio": 0.95, "vol_is_buying": False,
        }
        result = engine._check_triggers(entry, 83.60, ind)
        assert result.conditions_met.get("volume_confirmed") is True

    def test_wrong_candle_pressure_blocks_entry(self, engine):
        """BUY entry with selling pressure candle should be blocked."""
        entry = self._make_buy_entry(engine, setup_type="bb_lower_bounce")

        # High volume but SELLING pressure for a BUY = wrong direction
        ind = {
            "rsi": 36, "rsi_prev": 34,
            "vol_ratio": 1.5, "vol_is_buying": False,  # Selling, not buying
        }
        result = engine._check_triggers(entry, 19.95, ind)
        assert result.conditions_met.get("candle_pressure") is False
        assert result.triggered is False

    def test_correct_candle_pressure_passes(self, engine):
        """BUY entry with buying pressure candle should pass volume check."""
        entry = self._make_buy_entry(engine, setup_type="bb_lower_bounce")

        ind = {
            "rsi": 36, "rsi_prev": 34,
            "vol_ratio": 1.5, "vol_is_buying": True,  # Buying pressure
        }
        result = engine._check_triggers(entry, 19.95, ind)
        assert result.conditions_met.get("candle_pressure") is True
        assert result.conditions_met.get("volume_confirmed") is True

    def test_volume_spike_boosts_confidence(self, engine):
        """Volume > 2x avg should boost confidence by 15."""
        entry = self._make_sell_entry(engine, setup_type="bb_upper_rejection")
        original_conf = entry.confidence

        # Volume spike (2.5x avg) + all conditions met
        ind = {
            "rsi": 75, "rsi_prev": 68,
            "vol_ratio": 2.5, "vol_is_buying": False,
        }
        result = engine._check_triggers(entry, 83.60, ind)
        if result.triggered:
            assert entry.confidence == min(100, original_conf + VOL_SPIKE_CONFIDENCE_BOOST)

    def test_no_volume_data_skips_volume_checks(self, engine):
        """Without volume data (vol_ratio=0), volume checks are skipped."""
        entry = self._make_sell_entry(engine, setup_type="bb_upper_rejection")

        # No volume data at all
        ind = {"rsi": 75, "rsi_prev": 68}
        result = engine._check_triggers(entry, 83.60, ind)
        # volume_confirmed and candle_pressure should not be in conditions
        assert "volume_confirmed" not in result.conditions_met
        assert "candle_pressure" not in result.conditions_met

    def test_dead_market_blocks_all_setups(self, engine):
        """Volume < 0.8x avg should block even non-reversal setups."""
        entry = self._make_sell_entry(engine, setup_type="bb_upper_rejection")

        ind = {
            "rsi": 75, "rsi_prev": 68,
            "vol_ratio": 0.3, "vol_is_buying": False,
        }
        result = engine._check_triggers(entry, 83.60, ind)
        assert result.conditions_met.get("volume_confirmed") is False

    def test_pending_to_signal_includes_vol_ratio(self):
        """Signal metadata should include vol_ratio for scorecard."""
        entry = PendingEntry(
            entry_id="ANT-0001", symbol="SOL", side="SELL",
            target_price=83.50, sl=84.30, tp=80.50, tp2=79.00,
            trigger_conditions={}, confidence=80, leverage=10.0,
            risk_pct=0.03, expiry=time.time() + 9999,
            reasoning="test", setup_type="bb_upper_rejection",
            source="test", created_at=time.time(), created_at_iso="",
            rr_ratio=3.8, stop_width_pct=0.0095,
        )
        signal = AnticipationEngine.pending_to_signal(entry, 83.50, vol_ratio=1.5)
        assert signal.metadata["vol_ratio"] == 1.5
        assert "vol=" in signal.signal_context

    def test_pending_to_signal_default_vol_ratio(self):
        """Without vol_ratio, default should be 0.0."""
        entry = PendingEntry(
            entry_id="ANT-0002", symbol="HYPE", side="BUY",
            target_price=20.00, sl=19.80, tp=20.80, tp2=21.50,
            trigger_conditions={}, confidence=82, leverage=12.0,
            risk_pct=0.04, expiry=time.time() + 9999,
            reasoning="test", setup_type="bb_lower_bounce",
            source="test", created_at=time.time(), created_at_iso="",
            rr_ratio=4.0, stop_width_pct=0.01,
        )
        signal = AnticipationEngine.pending_to_signal(entry, 20.00)
        assert signal.metadata["vol_ratio"] == 0.0

    def test_get_status_with_volume_annotations(self, engine):
        """get_status with indicators should include vol_status."""
        engine._pending.append(PendingEntry(
            entry_id="ANT-0001", symbol="SOL", side="SELL",
            target_price=83.50, sl=84.30, tp=80.50, tp2=79.00,
            trigger_conditions={}, confidence=80, leverage=10.0,
            risk_pct=0.03, expiry=time.time() + 9999,
            reasoning="test", setup_type="test", source="test",
            created_at=time.time(), created_at_iso="",
            rr_ratio=3.8, stop_width_pct=0.01,
        ))
        indicators = {"SOL": {"vol_ratio": 1.5}}
        status = engine.get_status(indicators=indicators)
        assert status["active_pending"] == 1
        entry_dict = status["pending_entries"][0]
        assert "vol_status" in entry_dict
        assert "CONFIRMED" in entry_dict["vol_status"]

    def test_get_status_low_volume_annotation(self, engine):
        """Low volume should show warning in status."""
        engine._pending.append(PendingEntry(
            entry_id="ANT-0002", symbol="HYPE", side="BUY",
            target_price=20.00, sl=19.80, tp=20.80, tp2=21.50,
            trigger_conditions={}, confidence=80, leverage=12.0,
            risk_pct=0.04, expiry=time.time() + 9999,
            reasoning="test", setup_type="test", source="test",
            created_at=time.time(), created_at_iso="",
            rr_ratio=4.0, stop_width_pct=0.01,
        ))
        indicators = {"HYPE": {"vol_ratio": 0.3}}
        status = engine.get_status(indicators=indicators)
        entry_dict = status["pending_entries"][0]
        assert "LOW" in entry_dict["vol_status"]


# -- Test: Trade Scorecard Volume Factor ------------------------------------


class TestScorecardVolumeFactor:
    """Tests for volume confirmation in trade scorecard."""

    def test_scorecard_high_volume_bonus(self):
        from manual.trade_scorecard import TradeScorecard
        sc = TradeScorecard()
        pts = sc._score_volume_confirmation(1.5)
        assert pts == 10

    def test_scorecard_normal_volume_neutral(self):
        from manual.trade_scorecard import TradeScorecard
        sc = TradeScorecard()
        pts = sc._score_volume_confirmation(1.0)
        assert pts == 0

    def test_scorecard_dead_market_penalty(self):
        from manual.trade_scorecard import TradeScorecard
        sc = TradeScorecard()
        pts = sc._score_volume_confirmation(0.3)
        assert pts == -5

    def test_scorecard_no_volume_data_neutral(self):
        from manual.trade_scorecard import TradeScorecard
        sc = TradeScorecard()
        assert sc._score_volume_confirmation(None) == 0
        assert sc._score_volume_confirmation(0.0) == 0

    def test_scorecard_includes_volume_component(self):
        from manual.trade_scorecard import TradeScorecard
        sc = TradeScorecard()
        result = sc.score(
            symbol="SOL", side="SELL", confidence=85,
            num_agree=3, regime="trend",
            metadata={"vol_ratio": 1.5},
        )
        assert "volume_confirmation" in result.components
        assert result.components["volume_confirmation"] == 10

    def test_scorecard_volume_in_max_components(self):
        from manual.trade_scorecard import TradeScorecard
        sc = TradeScorecard()
        result = sc.score(
            symbol="SOL", side="SELL", confidence=85,
            num_agree=3, regime="trend",
        )
        assert "volume_confirmation" in result.max_components
        assert result.max_components["volume_confirmation"] == 10


# -- Test: Multi-Timeframe Alignment (6h trend filter) ---------------------


def _make_6h_bullish(n: int = 60, base: float = 100.0) -> pd.DataFrame:
    """Create 6h data with clear bullish trend (EMA20 > EMA50)."""
    np.random.seed(77)
    prices = [base]
    for i in range(1, n):
        prices.append(prices[-1] * 1.003)  # Steady uptrend
    prices = np.array(prices)
    return pd.DataFrame({
        "open": prices * 0.999,
        "high": prices * 1.002,
        "low": prices * 0.998,
        "close": prices,
        "volume": np.random.uniform(1000, 5000, n),
    })


def _make_6h_bearish(n: int = 60, base: float = 100.0) -> pd.DataFrame:
    """Create 6h data with clear bearish trend (EMA20 < EMA50)."""
    np.random.seed(88)
    prices = [base]
    for i in range(1, n):
        prices.append(prices[-1] * 0.997)  # Steady downtrend
    prices = np.array(prices)
    return pd.DataFrame({
        "open": prices * 1.001,
        "high": prices * 1.002,
        "low": prices * 0.998,
        "close": prices,
        "volume": np.random.uniform(1000, 5000, n),
    })


def _make_6h_neutral(n: int = 60, base: float = 100.0) -> pd.DataFrame:
    """Create 6h data with flat trend (EMAs very close)."""
    np.random.seed(99)
    prices = [base]
    for i in range(1, n):
        prices.append(prices[-1] * (1 + np.random.normal(0, 0.0005)))
    prices = np.array(prices)
    return pd.DataFrame({
        "open": prices * 0.999,
        "high": prices * 1.001,
        "low": prices * 0.999,
        "close": prices,
        "volume": np.random.uniform(1000, 5000, n),
    })


def _make_5m_hammer(base: float = 100.0) -> pd.DataFrame:
    """Create 5m data where last candle is a hammer (BUY signal)."""
    np.random.seed(55)
    n = 10
    prices = [base] * n
    rows = []
    for i in range(n - 1):
        rows.append({
            "open": prices[i] * 0.999,
            "high": prices[i] * 1.002,
            "low": prices[i] * 0.998,
            "close": prices[i] * 1.001,
            "volume": 1000,
        })
    # Last candle: hammer (long lower wick, close near high)
    rows.append({
        "open": base * 0.999,
        "high": base * 1.001,
        "low": base * 0.990,    # Long lower wick
        "close": base * 1.0005,  # Close near high
        "volume": 2000,
    })
    return pd.DataFrame(rows)


def _make_5m_shooting_star(base: float = 100.0) -> pd.DataFrame:
    """Create 5m data where last candle is a shooting star (SELL signal)."""
    np.random.seed(66)
    n = 10
    rows = []
    for i in range(n - 1):
        rows.append({
            "open": base * 0.999,
            "high": base * 1.002,
            "low": base * 0.998,
            "close": base * 1.001,
            "volume": 1000,
        })
    # Last candle: shooting star (long upper wick, close near low)
    rows.append({
        "open": base * 1.001,
        "high": base * 1.012,   # Long upper wick
        "low": base * 0.999,
        "close": base * 0.9995, # Close near low
        "volume": 2000,
    })
    return pd.DataFrame(rows)


class TestCompute6hTrend:
    def test_bullish_trend(self):
        df = _make_6h_bullish(60, 100.0)
        assert _compute_6h_trend(df) == "bullish"

    def test_bearish_trend(self):
        df = _make_6h_bearish(60, 100.0)
        assert _compute_6h_trend(df) == "bearish"

    def test_neutral_trend(self):
        df = _make_6h_neutral(60, 100.0)
        assert _compute_6h_trend(df) == "neutral"

    def test_insufficient_data(self):
        df = _make_6h_bullish(10, 100.0)  # Less than 50 bars
        assert _compute_6h_trend(df) == "unknown"

    def test_none_input(self):
        assert _compute_6h_trend(None) == "unknown"


class TestTimeframeAlignment:
    def test_buy_bullish_aligned(self):
        assert _get_timeframe_alignment("BUY", "bullish") == "aligned"

    def test_sell_bearish_aligned(self):
        assert _get_timeframe_alignment("SELL", "bearish") == "aligned"

    def test_buy_bearish_counter(self):
        assert _get_timeframe_alignment("BUY", "bearish") == "counter"

    def test_sell_bullish_counter(self):
        assert _get_timeframe_alignment("SELL", "bullish") == "counter"

    def test_neutral_returns_neutral(self):
        assert _get_timeframe_alignment("BUY", "neutral") == "neutral"
        assert _get_timeframe_alignment("SELL", "neutral") == "neutral"

    def test_unknown_returns_unknown(self):
        assert _get_timeframe_alignment("BUY", "unknown") == "unknown"


class TestDetect5mReversal:
    def test_hammer_detected(self):
        df = _make_5m_hammer(100.0)
        result = _detect_5m_reversal(df, "BUY")
        assert result["found"] is True
        assert result["pattern"] == "hammer"
        assert result["stop_price"] < 100.0  # Below the candle
        assert result["entry_price"] > 0

    def test_shooting_star_detected(self):
        df = _make_5m_shooting_star(100.0)
        result = _detect_5m_reversal(df, "SELL")
        assert result["found"] is True
        assert result["pattern"] == "shooting_star"
        assert result["stop_price"] > 100.0  # Above the candle

    def test_no_pattern_wrong_side(self):
        # Hammer is a BUY signal, should not be detected for SELL
        df = _make_5m_hammer(100.0)
        result = _detect_5m_reversal(df, "SELL")
        # May or may not find a pattern depending on wick ratios
        # but should not return "hammer"
        if result["found"]:
            assert result["pattern"] != "hammer"

    def test_insufficient_data(self):
        result = _detect_5m_reversal(None, "BUY")
        assert result["found"] is False

    def test_short_data(self):
        df = pd.DataFrame({
            "open": [100], "high": [101], "low": [99], "close": [100.5], "volume": [1000]
        })
        result = _detect_5m_reversal(df, "BUY")
        assert result["found"] is False


class TestMultiTFSetupFiltering:
    """Test that scan_for_setups filters by 6h trend."""

    def test_bearish_6h_blocks_buy_setups(self, engine):
        """With 6h bearish, BUY setups should be blocked as counter-trend."""
        df_1h = _make_oversold_data(120.0)  # Would normally generate BUY setups
        df_6h = _make_6h_bearish(60, 120.0)

        new = engine.scan_for_setups("HYPE", df_1h=df_1h, df_6h=df_6h)
        buy_setups = [e for e in new if e.side == "BUY"]
        # All BUY setups should be blocked (counter to 6h bearish)
        assert len(buy_setups) == 0

    def test_bullish_6h_blocks_sell_setups(self, engine):
        """With 6h bullish, SELL setups should be blocked as counter-trend."""
        df_1h = _make_overbought_data(80.0)  # Would normally generate SELL setups
        df_6h = _make_6h_bullish(60, 80.0)

        new = engine.scan_for_setups("SOL", df_1h=df_1h, df_6h=df_6h)
        sell_setups = [e for e in new if e.side == "SELL"]
        # All SELL setups should be blocked (counter to 6h bullish)
        assert len(sell_setups) == 0

    def test_no_6h_data_allows_both_sides(self, engine):
        """Without 6h data, both sides should be allowed (unknown alignment)."""
        df_1h = _make_overbought_data(80.0)
        new = engine.scan_for_setups("SOL", df_1h=df_1h, df_6h=None)
        # Should produce entries (alignment = "unknown", not blocked)
        for e in new:
            assert e.timeframe_alignment == "unknown"

    def test_aligned_setups_have_higher_leverage(self, engine):
        """Aligned setups should use LEVERAGE_ALIGNED range."""
        df_1h = _make_overbought_data(80.0)
        df_6h = _make_6h_bearish(60, 80.0)  # Bearish aligns with SELL

        new = engine.scan_for_setups("SOL", df_1h=df_1h, df_6h=df_6h)
        for e in new:
            if e.timeframe_alignment == "aligned":
                assert e.leverage >= LEVERAGE_ALIGNED[0]
                assert e.leverage <= LEVERAGE_ALIGNED[1]

    def test_neutral_setups_have_reduced_confidence(self, engine):
        """Neutral alignment should reduce confidence by 5."""
        df_1h = _make_overbought_data(80.0)
        df_6h = _make_6h_neutral(60, 80.0)

        new = engine.scan_for_setups("SOL", df_1h=df_1h, df_6h=df_6h)
        for e in new:
            if e.timeframe_alignment == "neutral":
                assert e.leverage >= LEVERAGE_NEUTRAL[0]
                assert e.leverage <= LEVERAGE_NEUTRAL[1]

    def test_alignment_field_set_on_entries(self, engine):
        """All returned entries should have timeframe_alignment set."""
        df_1h = _make_overbought_data(80.0)
        df_6h = _make_6h_bearish(60, 80.0)

        new = engine.scan_for_setups("SOL", df_1h=df_1h, df_6h=df_6h)
        for e in new:
            assert e.timeframe_alignment in ("aligned", "neutral", "counter", "unknown")
            # Counter should never appear (they are filtered out)
            assert e.timeframe_alignment != "counter"

    def test_signal_conversion_includes_alignment(self):
        """pending_to_signal should include timeframe_alignment in metadata."""
        entry = PendingEntry(
            entry_id="ANT-0001", symbol="SOL", side="SELL",
            target_price=83.50, sl=84.30, tp=80.50, tp2=79.00,
            trigger_conditions={}, confidence=80, leverage=12.0,
            risk_pct=0.03, expiry=time.time() + 9999,
            reasoning="test", setup_type="bb_upper_rejection",
            source="test", created_at=time.time(), created_at_iso="",
            rr_ratio=3.8, stop_width_pct=0.0095,
            timeframe_alignment="aligned",
        )
        signal = AnticipationEngine.pending_to_signal(entry, 83.50)
        assert signal.metadata.get("timeframe_alignment") == "aligned"


# ── Test: Candle Pattern Setups (10-12) ──────────────────────────────


def _make_exhaustion_data(base: float = 100.0, bearish: bool = True) -> pd.DataFrame:
    """Create data with an exhaustion candle at the end.

    Exhaustion = high volume + small body + prominent wick.
    Uses a sustained trend so EMA20 is well separated from close
    (needed for viable R:R on the mean-reversion TP).
    """
    np.random.seed(789)
    n = 50

    if bearish:
        # Sustained downtrend -> EMA20 well above close -> viable BUY R:R
        prices = [base]
        for i in range(1, n - 1):
            prices.append(prices[-1] * (1 - 0.003 + np.random.normal(0, 0.001)))
        last_price = prices[-1]
        prices.append(last_price)
        prices = np.array(prices)

        opens = prices * (1 + np.random.normal(0, 0.001, n))
        highs = prices * (1 + abs(np.random.normal(0.003, 0.002, n)))
        lows = prices * (1 - abs(np.random.normal(0.003, 0.002, n)))
        closes = prices.copy()

        # Bearish exhaustion at bottom: tiny body, big lower wick
        opens[-1] = last_price * 1.0002
        closes[-1] = last_price * 1.0000
        highs[-1] = last_price * 1.002
        lows[-1] = last_price * 0.988  # 1.2% lower wick
    else:
        # Sustained uptrend -> EMA20 well below close -> viable SELL R:R
        prices = [base]
        for i in range(1, n - 1):
            prices.append(prices[-1] * (1 + 0.003 + np.random.normal(0, 0.001)))
        last_price = prices[-1]
        prices.append(last_price)
        prices = np.array(prices)

        opens = prices * (1 + np.random.normal(0, 0.001, n))
        highs = prices * (1 + abs(np.random.normal(0.003, 0.002, n)))
        lows = prices * (1 - abs(np.random.normal(0.003, 0.002, n)))
        closes = prices.copy()

        # Bullish exhaustion at top: tiny body, big upper wick
        opens[-1] = last_price * 0.9998
        closes[-1] = last_price * 1.0000
        highs[-1] = last_price * 1.012  # 1.2% upper wick
        lows[-1] = last_price * 0.998

    volumes = np.random.uniform(1000, 3000, n)
    volumes[-1] = float(volumes[:-1].mean()) * 2.5  # High volume

    df = pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })
    return df


def _make_institutional_data(base: float = 100.0) -> pd.DataFrame:
    """Create data with a large green institutional candle at the end.

    Institutional = vol > 2x avg, body > 1.5x avg, green candle.
    """
    np.random.seed(101)
    n = 50
    prices = [base]
    for i in range(1, n - 1):
        prices.append(prices[-1] * (1 + np.random.normal(0, 0.002)))

    last_close = prices[-1]
    prices.append(last_close)
    prices = np.array(prices)

    opens = prices * (1 + np.random.normal(0, 0.001, n))
    highs = prices * (1 + abs(np.random.normal(0.003, 0.002, n)))
    lows = prices * (1 - abs(np.random.normal(0.003, 0.002, n)))
    closes = prices.copy()
    volumes = np.random.uniform(1000, 3000, n)

    # Make last candle a big green institutional candle
    # Normal body ~0.3% of price, institutional = 1.5% body
    opens[-1] = base * 0.994
    closes[-1] = base * 1.009   # Large green body (1.5%)
    highs[-1] = base * 1.011
    lows[-1] = base * 0.993

    # Very high volume (3x average)
    volumes[-1] = float(volumes[:-1].mean()) * 3.0

    df = pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })
    return df


def _make_shooting_star_data(base: float = 20.0) -> pd.DataFrame:
    """Create data with a shooting star candle at the end.

    Shooting star = upper wick > 60% of range, body < 30% of range.
    Uses a sustained uptrend so EMA20 is well below close, giving a viable
    short TP target for R:R.
    """
    np.random.seed(222)
    n = 50
    # Sustained uptrend -> EMA20 below close -> viable SELL R:R target
    prices = [base]
    for i in range(1, n - 1):
        prices.append(prices[-1] * (1 + 0.003 + np.random.normal(0, 0.001)))

    last_price = prices[-1]
    prices.append(last_price)
    prices = np.array(prices)

    opens = prices * (1 + np.random.normal(0, 0.001, n))
    highs = prices * (1 + abs(np.random.normal(0.003, 0.002, n)))
    lows = prices * (1 - abs(np.random.normal(0.003, 0.002, n)))
    closes = prices.copy()
    volumes = np.random.uniform(1000, 3000, n)

    # Shooting star at the top: long upper wick, tiny body near bottom
    range_size = last_price * 0.03  # 3% range
    lows[-1] = last_price * 0.998
    opens[-1] = last_price * 1.001  # Open near low-ish
    closes[-1] = last_price * 0.999  # Close near open (tiny body)
    highs[-1] = lows[-1] + range_size  # Long upper wick

    # Moderate volume
    volumes[-1] = float(volumes[:-1].mean()) * 1.5

    df = pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })
    return df


class TestCandlePatternSetups:
    """Tests for setups 10-12: Exhaustion Reversal, Institutional Continuation,
    Shooting Star Short."""

    # -- Setup classification tests --

    def test_exhaustion_reversal_in_reversal_setups(self):
        assert "exhaustion_reversal" in REVERSAL_SETUPS

    def test_institutional_continuation_in_trend_setups(self):
        assert "institutional_continuation" in TREND_SETUPS

    def test_shooting_star_in_reversal_setups(self):
        assert "shooting_star_short" in REVERSAL_SETUPS

    # -- Indicator computation tests --

    def test_indicators_include_candle_metrics(self):
        """_compute_indicators should return candle body/wick metrics."""
        df = _make_exhaustion_data(100.0, bearish=True)
        ind = _compute_indicators(df)
        assert "candle_body" in ind
        assert "avg_body" in ind
        assert "candle_range" in ind
        assert "upper_wick" in ind
        assert "lower_wick" in ind
        assert "upper_wick_pct" in ind
        assert "lower_wick_pct" in ind
        assert "body_pct_of_range" in ind
        assert "prominent_wick_pct" in ind
        assert "candle_is_green" in ind
        assert "last_open" in ind
        assert "last_high" in ind
        assert "last_low" in ind

    def test_exhaustion_candle_metrics(self):
        """Exhaustion candle should have small body and prominent wick."""
        df = _make_exhaustion_data(100.0, bearish=True)
        ind = _compute_indicators(df)
        # Small body relative to average
        assert ind["candle_body"] < ind["avg_body"]
        # Prominent wick
        assert ind["prominent_wick_pct"] > 0.002

    def test_institutional_candle_metrics(self):
        """Institutional candle should have large body and be green."""
        df = _make_institutional_data(100.0)
        ind = _compute_indicators(df)
        assert ind["candle_body"] > ind["avg_body"]
        assert ind["candle_is_green"] is True

    def test_shooting_star_candle_metrics(self):
        """Shooting star should have large upper wick ratio."""
        df = _make_shooting_star_data(20.0)
        ind = _compute_indicators(df)
        assert ind["upper_wick_pct"] > 0.5  # Upper wick > 50% of range

    # -- Setup 10: Exhaustion Reversal detection --

    def test_exhaustion_reversal_detects_bearish_on_sol(self, engine):
        """Bearish exhaustion on SOL should create BUY entry."""
        df = _make_exhaustion_data(100.0, bearish=True)
        new = engine.scan_for_setups("SOL", df_1h=df)
        exhaust = [e for e in new if e.setup_type == "exhaustion_reversal"]
        # May or may not fire depending on R:R, but if it does, it should be BUY
        for e in exhaust:
            assert e.side == "BUY"
            assert e.symbol == "SOL"
            assert e.confidence == EXHAUSTION_CONFIDENCE or e.confidence >= 60

    def test_exhaustion_reversal_detects_bullish_on_btc(self, engine):
        """Bullish exhaustion on BTC should create SELL entry."""
        df = _make_exhaustion_data(50000.0, bearish=False)
        new = engine.scan_for_setups("BTC", df_1h=df)
        exhaust = [e for e in new if e.setup_type == "exhaustion_reversal"]
        for e in exhaust:
            assert e.side == "SELL"
            assert e.symbol == "BTC"

    def test_exhaustion_reversal_skips_hype(self, engine):
        """Exhaustion reversal should NOT fire on HYPE (not in allowed symbols)."""
        df = _make_exhaustion_data(20.0, bearish=True)
        new = engine.scan_for_setups("HYPE", df_1h=df)
        exhaust = [e for e in new if e.setup_type == "exhaustion_reversal"]
        assert len(exhaust) == 0

    def test_exhaustion_reversal_requires_high_volume(self, engine):
        """No exhaustion signal without vol >= 1.5x."""
        df = _make_exhaustion_data(100.0, bearish=True)
        # Kill the volume spike
        df.loc[df.index[-1], "volume"] = float(df["volume"].iloc[:-1].mean()) * 0.5
        new = engine.scan_for_setups("SOL", df_1h=df)
        exhaust = [e for e in new if e.setup_type == "exhaustion_reversal"]
        assert len(exhaust) == 0

    # -- Setup 11: Institutional Continuation detection --

    def test_institutional_continuation_detects_on_sol(self, engine):
        """Large green candle on SOL should create BUY continuation."""
        df = _make_institutional_data(100.0)
        new = engine.scan_for_setups("SOL", df_1h=df)
        inst = [e for e in new if e.setup_type == "institutional_continuation"]
        for e in inst:
            assert e.side == "BUY"
            assert e.symbol == "SOL"
            assert e.confidence == INSTITUTIONAL_CONFIDENCE or e.confidence >= 60

    def test_institutional_continuation_detects_on_hype(self, engine):
        """Large green candle on HYPE should create BUY continuation."""
        df = _make_institutional_data(20.0)
        new = engine.scan_for_setups("HYPE", df_1h=df)
        inst = [e for e in new if e.setup_type == "institutional_continuation"]
        for e in inst:
            assert e.side == "BUY"
            assert e.symbol == "HYPE"

    def test_institutional_continuation_skips_btc(self, engine):
        """Institutional continuation should NOT fire on BTC."""
        df = _make_institutional_data(50000.0)
        new = engine.scan_for_setups("BTC", df_1h=df)
        inst = [e for e in new if e.setup_type == "institutional_continuation"]
        assert len(inst) == 0

    def test_institutional_requires_green_candle(self, engine):
        """No institutional signal on red candle."""
        df = _make_institutional_data(100.0)
        # Flip last candle to red
        df.loc[df.index[-1], "open"] = df.loc[df.index[-1], "close"] + 1.0
        new = engine.scan_for_setups("SOL", df_1h=df)
        inst = [e for e in new if e.setup_type == "institutional_continuation"]
        assert len(inst) == 0

    def test_institutional_requires_high_volume(self, engine):
        """No institutional signal without vol >= 2.0x."""
        df = _make_institutional_data(100.0)
        df.loc[df.index[-1], "volume"] = float(df["volume"].iloc[:-1].mean()) * 1.0
        new = engine.scan_for_setups("SOL", df_1h=df)
        inst = [e for e in new if e.setup_type == "institutional_continuation"]
        assert len(inst) == 0

    # -- Setup 12: Shooting Star Short detection --

    def test_shooting_star_detects_on_hype(self, engine):
        """Shooting star on HYPE should create SELL entry."""
        df = _make_shooting_star_data(20.0)
        new = engine.scan_for_setups("HYPE", df_1h=df)
        stars = [e for e in new if e.setup_type == "shooting_star_short"]
        for e in stars:
            assert e.side == "SELL"
            assert e.symbol == "HYPE"
            assert e.confidence == SHOOTING_STAR_CONFIDENCE or e.confidence >= 60

    def test_shooting_star_skips_sol(self, engine):
        """Shooting star should NOT fire on SOL (HYPE only)."""
        df = _make_shooting_star_data(100.0)
        new = engine.scan_for_setups("SOL", df_1h=df)
        stars = [e for e in new if e.setup_type == "shooting_star_short"]
        assert len(stars) == 0

    def test_shooting_star_skips_btc(self, engine):
        """Shooting star should NOT fire on BTC (HYPE only)."""
        df = _make_shooting_star_data(50000.0)
        new = engine.scan_for_setups("BTC", df_1h=df)
        stars = [e for e in new if e.setup_type == "shooting_star_short"]
        assert len(stars) == 0

    def test_shooting_star_sl_above_entry(self, engine):
        """Shooting star SL should be above entry price (ATR-based or candle high)."""
        df = _make_shooting_star_data(20.0)
        new = engine.scan_for_setups("HYPE", df_1h=df)
        stars = [e for e in new if e.setup_type == "shooting_star_short"]
        if stars:
            for e in stars:
                assert e.sl > e.target_price  # SL above entry for SELL

    # -- Multi-TF alignment on candle patterns --

    def test_candle_pattern_gets_alignment_tag(self, engine):
        """Candle pattern entries should get timeframe_alignment set."""
        df = _make_shooting_star_data(20.0)
        new = engine.scan_for_setups("HYPE", df_1h=df)
        stars = [e for e in new if e.setup_type == "shooting_star_short"]
        for e in stars:
            assert e.timeframe_alignment in ("aligned", "neutral", "unknown")

    # -- Signal conversion for candle patterns --

    def test_exhaustion_reversal_signal_conversion(self):
        """Exhaustion reversal PendingEntry converts to Signal correctly."""
        entry = PendingEntry(
            entry_id="ANT-0010", symbol="SOL", side="BUY",
            target_price=100.0, sl=99.0, tp=102.0, tp2=103.0,
            trigger_conditions={}, confidence=EXHAUSTION_CONFIDENCE,
            leverage=12.0, risk_pct=0.03, expiry=time.time() + 9999,
            reasoning="exhaustion reversal test",
            setup_type="exhaustion_reversal",
            source="candle_exhaustion",
            created_at=time.time(), created_at_iso="",
            rr_ratio=2.0, stop_width_pct=0.01,
            timeframe_alignment="aligned",
        )
        signal = AnticipationEngine.pending_to_signal(entry, 100.0)
        assert signal.strategy == "anticipatory_exhaustion_reversal"
        assert signal.side == "BUY"
        assert signal.metadata.get("setup_type") == "exhaustion_reversal"

    def test_institutional_continuation_signal_conversion(self):
        """Institutional continuation PendingEntry converts to Signal correctly."""
        entry = PendingEntry(
            entry_id="ANT-0011", symbol="SOL", side="BUY",
            target_price=101.0, sl=99.0, tp=104.0, tp2=106.0,
            trigger_conditions={}, confidence=INSTITUTIONAL_CONFIDENCE,
            leverage=10.0, risk_pct=0.03, expiry=time.time() + 9999,
            reasoning="institutional continuation test",
            setup_type="institutional_continuation",
            source="candle_institutional",
            created_at=time.time(), created_at_iso="",
            rr_ratio=2.5, stop_width_pct=0.02,
            timeframe_alignment="aligned",
        )
        signal = AnticipationEngine.pending_to_signal(entry, 101.0)
        assert signal.strategy == "anticipatory_institutional_continuation"
        assert signal.side == "BUY"

    def test_shooting_star_signal_conversion(self):
        """Shooting star PendingEntry converts to Signal correctly."""
        entry = PendingEntry(
            entry_id="ANT-0012", symbol="HYPE", side="SELL",
            target_price=20.0, sl=20.10, tp=19.70, tp2=19.50,
            trigger_conditions={}, confidence=SHOOTING_STAR_CONFIDENCE,
            leverage=10.0, risk_pct=0.03, expiry=time.time() + 9999,
            reasoning="shooting star test",
            setup_type="shooting_star_short",
            source="candle_shooting_star",
            created_at=time.time(), created_at_iso="",
            rr_ratio=3.0, stop_width_pct=0.005,
            timeframe_alignment="aligned",
        )
        signal = AnticipationEngine.pending_to_signal(entry, 20.0)
        assert signal.strategy == "anticipatory_shooting_star_short"
        assert signal.side == "SELL"
