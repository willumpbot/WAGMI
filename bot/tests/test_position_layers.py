"""Tests for multi-layer position architecture (scalp/swing/regime)."""
import pytest
from execution.position_layers import (
    PositionLayerManager,
    PositionLayer,
    LAYER_CONFIGS,
    LayerAssignment,
)


class TestLayerClassification:
    """Test signal-to-layer classification."""

    def test_scalp_for_tight_stop_dip_buy(self):
        """Tight stop + dip buy = scalp layer."""
        mgr = PositionLayerManager()
        result = mgr.classify_signal(
            symbol="HYPE", side="BUY", confidence=85.0,
            num_agree=3, regime="consolidation",
            stop_width_pct=0.015, entry_price=40.0,
            is_dip_buy=True,
        )
        assert result is not None
        assert result.layer == PositionLayer.SCALP

    def test_swing_for_moderate_signal(self):
        """Moderate signal without dip = swing (scalp too wide)."""
        mgr = PositionLayerManager()
        result = mgr.classify_signal(
            symbol="BTC", side="BUY", confidence=80.0,
            num_agree=2, regime="trend",
            stop_width_pct=0.04, entry_price=70000.0,
            is_dip_buy=False,
        )
        assert result is not None
        assert result.layer == PositionLayer.SWING

    def test_regime_for_high_conviction_trend(self):
        """High conviction + 3 agree + trending = regime layer."""
        mgr = PositionLayerManager(max_total_leverage=50)
        # Fill scalp and swing with moderate leverage
        mgr.open_position("BTC", "LONG", PositionLayer.SCALP, 70000, 0.1, 10, 69000, 72000)
        mgr.open_position("SOL", "SHORT", PositionLayer.SCALP, 130, 10, 10, 135, 120)
        mgr.open_position("BTC", "LONG", PositionLayer.SWING, 70000, 0.5, 5, 67000, 75000)
        mgr.open_position("SOL", "SHORT", PositionLayer.SWING, 130, 50, 5, 140, 115)
        result = mgr.classify_signal(
            symbol="HYPE", side="BUY", confidence=85.0,
            num_agree=3, regime="trending_bull",
            stop_width_pct=0.08, entry_price=40.0,
        )
        # Should get regime since scalp/swing are full
        assert result is not None
        assert result.layer == PositionLayer.REGIME

    def test_no_layer_for_low_confidence(self):
        """Low confidence signal doesn't qualify for any layer."""
        mgr = PositionLayerManager()
        result = mgr.classify_signal(
            symbol="HYPE", side="BUY", confidence=55.0,
            num_agree=1, regime="unknown",
            stop_width_pct=0.025, entry_price=40.0,
        )
        assert result is None

    def test_no_layer_when_full(self):
        """When all layers are full, returns None."""
        mgr = PositionLayerManager(max_total_leverage=100)
        # Fill all scalp slots
        mgr.open_position("BTC", "LONG", PositionLayer.SCALP, 70000, 0.1, 15, 69000, 72000)
        mgr.open_position("SOL", "LONG", PositionLayer.SCALP, 130, 10, 15, 128, 135)
        # Fill all swing slots
        mgr.open_position("BTC", "LONG", PositionLayer.SWING, 70000, 0.5, 8, 67000, 75000)
        mgr.open_position("SOL", "LONG", PositionLayer.SWING, 130, 50, 8, 125, 140)
        # Fill regime slot
        mgr.open_position("BTC", "LONG", PositionLayer.REGIME, 70000, 1.0, 3, 63000, 80000)

        # All layers full
        result = mgr.classify_signal(
            symbol="HYPE", side="BUY", confidence=90.0,
            num_agree=3, regime="trending_bull",
            stop_width_pct=0.015, entry_price=40.0,
            is_dip_buy=True,
        )
        assert result is None

    def test_regime_requires_trend(self):
        """Regime layer needs trending regime, not consolidation."""
        mgr = PositionLayerManager(max_total_leverage=50)
        # Fill scalp/swing
        for i in range(4):
            mgr.open_position(f"SYM{i}", "LONG", PositionLayer.SCALP if i < 2 else PositionLayer.SWING,
                              100, 1, 5, 95, 110)
        result = mgr.classify_signal(
            symbol="HYPE", side="BUY", confidence=85.0,
            num_agree=3, regime="consolidation",
            stop_width_pct=0.08, entry_price=40.0,
        )
        # Regime requires trending regime
        assert result is None

    def test_same_symbol_different_layers(self):
        """Can have same symbol in different layers."""
        mgr = PositionLayerManager()
        mgr.open_position("HYPE", "LONG", PositionLayer.SCALP, 40, 10, 20, 39, 42)

        # Should still be able to classify into swing
        result = mgr.classify_signal(
            symbol="HYPE", side="BUY", confidence=80.0,
            num_agree=2, regime="trend",
            stop_width_pct=0.04, entry_price=40.0,
        )
        assert result is not None
        assert result.layer == PositionLayer.SWING


class TestPositionManagement:
    """Test position open/close/tracking."""

    def test_open_and_close(self):
        mgr = PositionLayerManager()
        pos = mgr.open_position("HYPE", "LONG", PositionLayer.SCALP, 40.0, 10.0, 20.0, 39.0, 42.0)
        assert pos.symbol == "HYPE"
        assert mgr.has_position("HYPE", PositionLayer.SCALP)

        closed = mgr.close_position("HYPE", PositionLayer.SCALP)
        assert closed is not None
        assert not mgr.has_position("HYPE", PositionLayer.SCALP)

    def test_total_leverage(self):
        mgr = PositionLayerManager()
        mgr.open_position("HYPE", "LONG", PositionLayer.SCALP, 40, 10, 20, 39, 42)
        mgr.open_position("BTC", "LONG", PositionLayer.SWING, 70000, 0.5, 8, 67000, 75000)
        assert mgr.get_total_leverage() == 28.0

    def test_layer_count(self):
        mgr = PositionLayerManager()
        mgr.open_position("HYPE", "LONG", PositionLayer.SCALP, 40, 10, 20, 39, 42)
        mgr.open_position("BTC", "LONG", PositionLayer.SCALP, 70000, 0.1, 15, 69000, 72000)
        assert mgr.get_layer_count(PositionLayer.SCALP) == 2
        assert mgr.get_layer_count(PositionLayer.SWING) == 0

    def test_summary(self):
        mgr = PositionLayerManager()
        mgr.open_position("HYPE", "LONG", PositionLayer.SCALP, 40, 10, 20, 39, 42)
        summary = mgr.get_summary()
        assert summary["total_positions"] == 1
        assert summary["scalp"] == 1
        assert summary["swing"] == 0


class TestLayerConfigs:
    """Test layer configuration sanity."""

    def test_scalp_config(self):
        cfg = LAYER_CONFIGS[PositionLayer.SCALP]
        assert cfg.max_leverage == 25.0
        assert cfg.max_hold_hours == 4.0
        assert cfg.tp_multiplier == 1.5

    def test_swing_config(self):
        cfg = LAYER_CONFIGS[PositionLayer.SWING]
        assert cfg.max_leverage == 10.0
        assert cfg.max_hold_hours == 24.0

    def test_regime_config(self):
        cfg = LAYER_CONFIGS[PositionLayer.REGIME]
        assert cfg.max_leverage == 3.0
        assert cfg.max_hold_hours == 168.0  # 7 days
        assert cfg.min_agree == 3

    def test_leverage_decreases_across_layers(self):
        """Scalp > Swing > Regime leverage."""
        assert LAYER_CONFIGS[PositionLayer.SCALP].max_leverage > \
               LAYER_CONFIGS[PositionLayer.SWING].max_leverage > \
               LAYER_CONFIGS[PositionLayer.REGIME].max_leverage

    def test_hold_time_increases_across_layers(self):
        """Scalp < Swing < Regime hold time."""
        assert LAYER_CONFIGS[PositionLayer.SCALP].max_hold_hours < \
               LAYER_CONFIGS[PositionLayer.SWING].max_hold_hours < \
               LAYER_CONFIGS[PositionLayer.REGIME].max_hold_hours


class TestTimeStops:
    """Test time stop checking."""

    def test_no_time_stop_for_fresh_positions(self):
        import time as _time
        mgr = PositionLayerManager()
        mgr.open_position("HYPE", "LONG", PositionLayer.SCALP, 40, 10, 20, 39, 42)
        to_close = mgr.check_time_stops()
        assert len(to_close) == 0

    def test_time_stop_triggers_for_expired(self):
        import time as _time
        mgr = PositionLayerManager()
        pos = mgr.open_position("HYPE", "LONG", PositionLayer.SCALP, 40, 10, 20, 39, 42)
        # Backdate opening time to 5 hours ago (exceeds 4h scalp limit)
        pos.opened_at = _time.time() - 5 * 3600
        to_close = mgr.check_time_stops()
        assert len(to_close) == 1
        assert to_close[0].symbol == "HYPE"
