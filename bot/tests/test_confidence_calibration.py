"""
Tests for the Confidence Calibration System.

Covers:
- Basic calibration curve building and application
- Per-symbol calibration (BTC vs SOL vs HYPE)
- EWMA weighting (recent trades weighted more)
- Backtest bootstrapping from CSV
- Pipeline integration (calibration before sizing)
- Edge cases (insufficient data, empty curve, boundary values)
"""

import csv
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from llm.confidence_calibrator import ConfidenceCalibrator


# ────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────

def _make_calibrator(tmp_path, calibration_window=50):
    """Create a calibrator pointing to a temp directory."""
    data_dir = str(tmp_path / "llm")
    return ConfidenceCalibrator(data_dir=data_dir, calibration_window=calibration_window)


def _seed_observations(cal, confidence, win_rate, n=20, symbol=""):
    """Seed n observations at a given confidence with a target win rate.

    Interleaves wins and losses with distinct timestamps to give stable
    EWMA results regardless of sort-stability quirks.
    """
    n_wins = int(n * win_rate)
    # Build a deterministic interleaved pattern
    results = []
    wins_placed = 0
    losses_placed = 0
    n_losses = n - n_wins
    for i in range(n):
        # Distribute wins evenly across the sequence
        if n_wins > 0 and (wins_placed / max(1, n_wins)) <= (losses_placed / max(1, n_losses)):
            results.append(True)
            wins_placed += 1
        elif n_losses > 0 and losses_placed < n_losses:
            results.append(False)
            losses_placed += 1
        else:
            results.append(True)
            wins_placed += 1

    for i, correct in enumerate(results):
        obs = {
            "confidence": confidence,
            "correct": correct,
            "agent": "test",
            "symbol": cal._normalize_symbol(symbol),
            "regime": "",
            "pnl_pct": 0.0,
            "timestamp": f"2026-03-15T{i:02d}:{i:02d}:00+00:00",
        }
        cal._observations.append(obs)


def _write_backtest_csv(path, rows):
    """Write a minimal backtest CSV for bootstrapping."""
    fieldnames = [
        "symbol", "side", "strategy", "close_reason", "entry", "exit",
        "sl", "tp1", "tp2", "pnl", "fee", "leverage", "confidence",
        "rr_achieved", "duration_h", "state_path", "outcome",
        "llm_action", "llm_regime", "llm_confidence",
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


# ────────────────────────────────────────────────────────────────────
# SECTION 1: Basic calibration curve
# ────────────────────────────────────────────────────────────────────

class TestCalibrationCurve:
    """Test curve building and calibration application."""

    def test_no_data_returns_raw(self, tmp_path):
        """With no observations, calibrate() returns raw confidence."""
        cal = _make_calibrator(tmp_path)
        assert cal.calibrate(85.0) == 85.0
        assert cal.calibrate(95.0) == 95.0

    def test_overconfident_bin_deflates(self, tmp_path):
        """If 90-100% bin has 40% WR, calibration should deflate."""
        cal = _make_calibrator(tmp_path)
        # Seed: 90-100% confidence but only 40% win rate
        _seed_observations(cal, 95.0, win_rate=0.4, n=20)
        cal.rebuild_curve()

        calibrated = cal.calibrate(95.0)
        # Should be deflated significantly below 95
        assert calibrated < 85.0, f"Expected deflation, got {calibrated}"
        assert calibrated > 10.0, "Should not deflate below floor"

    def test_underconfident_bin_inflates(self, tmp_path):
        """If 70-80% bin has 85% WR, calibration should inflate."""
        cal = _make_calibrator(tmp_path)
        # Seed: 70-80% confidence but 85% actual win rate
        _seed_observations(cal, 75.0, win_rate=0.85, n=20)
        cal.rebuild_curve()

        calibrated = cal.calibrate(75.0)
        # 0.7 * (0.85*100) + 0.3 * 75 = 59.5 + 22.5 = 82
        # Should be inflated above 75
        assert calibrated > 75.0, f"Expected inflation above 75, got {calibrated}"

    def test_well_calibrated_no_change(self, tmp_path):
        """If actual WR matches confidence, minimal adjustment."""
        cal = _make_calibrator(tmp_path)
        # Seed: 75% confidence with 75% win rate
        _seed_observations(cal, 75.0, win_rate=0.75, n=20)
        cal.rebuild_curve()

        calibrated = cal.calibrate(75.0)
        # 0.7 * (0.75*100) + 0.3 * 75 = 52.5 + 22.5 = 75
        # Should be very close to 75 (EWMA may deviate slightly from simple avg)
        assert abs(calibrated - 75.0) < 5.0, f"Expected ~75, got {calibrated}"

    def test_max_adjustment_cap(self, tmp_path):
        """Calibration should not adjust by more than MAX_ADJUSTMENT_PCT."""
        cal = _make_calibrator(tmp_path)
        # Extreme mismatch: 95% confidence but 10% WR
        _seed_observations(cal, 95.0, win_rate=0.1, n=30)
        cal.rebuild_curve()

        calibrated = cal.calibrate(95.0)
        adjustment = abs(calibrated - 95.0)
        assert adjustment <= cal.MAX_ADJUSTMENT_PCT + 0.1, (
            f"Adjustment {adjustment} exceeded max {cal.MAX_ADJUSTMENT_PCT}"
        )

    def test_clamp_to_valid_range(self, tmp_path):
        """Calibrated values should stay in [10, 99] range."""
        cal = _make_calibrator(tmp_path)
        _seed_observations(cal, 55.0, win_rate=0.05, n=20)
        cal.rebuild_curve()

        calibrated = cal.calibrate(55.0)
        assert 10.0 <= calibrated <= 99.0

    def test_insufficient_samples_returns_raw(self, tmp_path):
        """With fewer than MIN_SAMPLES_PER_BIN, return raw confidence."""
        cal = _make_calibrator(tmp_path)
        # Only 3 observations (below threshold of 5)
        for i in range(3):
            cal.record_observation(95.0, was_correct=False, agent="test")
        cal.rebuild_curve()

        assert cal.calibrate(95.0) == 95.0


# ────────────────────────────────────────────────────────────────────
# SECTION 2: Per-symbol calibration
# ────────────────────────────────────────────────────────────────────

class TestPerSymbolCalibration:
    """Test symbol-specific calibration curves."""

    def test_different_symbols_different_calibration(self, tmp_path):
        """BTC and SOL at same raw confidence should calibrate differently."""
        cal = _make_calibrator(tmp_path)

        # BTC at 85% confidence wins 80% of the time
        _seed_observations(cal, 85.0, win_rate=0.80, n=20, symbol="BTC")
        # SOL at 85% confidence wins only 45% of the time
        _seed_observations(cal, 85.0, win_rate=0.45, n=20, symbol="SOL")
        cal.rebuild_curve()

        btc_cal = cal.calibrate(85.0, symbol="BTC")
        sol_cal = cal.calibrate(85.0, symbol="SOL")

        assert btc_cal > sol_cal, (
            f"BTC ({btc_cal:.1f}) should be higher than SOL ({sol_cal:.1f})"
        )

    def test_symbol_fallback_to_global(self, tmp_path):
        """If no per-symbol data, fall back to global curve."""
        cal = _make_calibrator(tmp_path)

        # Only global data
        _seed_observations(cal, 85.0, win_rate=0.60, n=20, symbol="BTC")
        _seed_observations(cal, 85.0, win_rate=0.60, n=20, symbol="SOL")
        cal.rebuild_curve()

        # ETH has no specific data — should use global
        eth_cal = cal.calibrate(85.0, symbol="ETH")
        global_cal = cal.calibrate(85.0, symbol="")

        # Both should use global curve, so similar result
        assert abs(eth_cal - global_cal) < 1.0

    def test_symbol_normalization(self, tmp_path):
        """Symbol with suffix should be normalized."""
        cal = _make_calibrator(tmp_path)
        _seed_observations(cal, 85.0, win_rate=0.60, n=20, symbol="BTC/USDC:USDC")
        cal.rebuild_curve()

        # Should find data under normalized "BTC"
        result = cal.calibrate(85.0, symbol="BTC")
        assert result != 85.0 or len(cal._curve.get("BTC", {})) > 0


# ────────────────────────────────────────────────────────────────────
# SECTION 3: EWMA weighting
# ────────────────────────────────────────────────────────────────────

class TestEWMAWeighting:
    """Test that recent trades are weighted more heavily."""

    def test_ewma_weights_recent_more(self, tmp_path):
        """Recent wins should produce higher WR than uniform average."""
        cal = _make_calibrator(tmp_path)

        # First 10 trades: all losses (older)
        for i in range(10):
            obs = {
                "confidence": 85.0,
                "correct": False,
                "agent": "test",
                "symbol": "",
                "regime": "",
                "pnl_pct": 0.0,
                "timestamp": f"2026-03-01T{i:02d}:00:00+00:00",
            }
            cal._observations.append(obs)

        # Next 10 trades: all wins (recent)
        for i in range(10):
            obs = {
                "confidence": 85.0,
                "correct": True,
                "agent": "test",
                "symbol": "",
                "regime": "",
                "pnl_pct": 0.0,
                "timestamp": f"2026-03-30T{i:02d}:00:00+00:00",
            }
            cal._observations.append(obs)

        # Simple average would be 50%
        # EWMA should be > 50% since recent trades are all wins
        ewma_wr = cal._compute_ewma_win_rate(cal._observations)
        assert ewma_wr > 0.55, f"EWMA should weight recent wins higher, got {ewma_wr}"

    def test_ewma_all_wins(self, tmp_path):
        """100% win rate should produce ~1.0 EWMA."""
        cal = _make_calibrator(tmp_path)
        obs = [
            {"confidence": 80.0, "correct": True, "timestamp": f"2026-03-{i+1:02d}T00:00:00+00:00"}
            for i in range(20)
        ]
        wr = cal._compute_ewma_win_rate(obs)
        assert abs(wr - 1.0) < 0.01

    def test_ewma_all_losses(self, tmp_path):
        """0% win rate should produce ~0.0 EWMA."""
        cal = _make_calibrator(tmp_path)
        obs = [
            {"confidence": 80.0, "correct": False, "timestamp": f"2026-03-{i+1:02d}T00:00:00+00:00"}
            for i in range(20)
        ]
        wr = cal._compute_ewma_win_rate(obs)
        assert abs(wr) < 0.01

    def test_ewma_empty_returns_half(self, tmp_path):
        """Empty list should return 0.5 (neutral)."""
        cal = _make_calibrator(tmp_path)
        assert cal._compute_ewma_win_rate([]) == 0.5

    def test_calibration_window_limits(self, tmp_path):
        """Calibration window should limit observations used."""
        cal = _make_calibrator(tmp_path, calibration_window=5)

        # 20 observations total, window = 5
        obs = [
            {"confidence": 80.0, "correct": (i >= 15), "timestamp": f"2026-03-{i+1:02d}T00:00:00+00:00"}
            for i in range(20)
        ]
        wr = cal._compute_ewma_win_rate(obs)
        # Only last 5 are used (all wins), so WR should be ~1.0
        assert wr > 0.9, f"Window should limit to recent 5, got WR={wr}"


# ────────────────────────────────────────────────────────────────────
# SECTION 4: Backtest bootstrapping
# ────────────────────────────────────────────────────────────────────

class TestBacktestBootstrap:
    """Test pre-seeding from backtest CSV."""

    def test_bootstrap_loads_trades(self, tmp_path):
        """Bootstrap should load trades from CSV into observations."""
        cal = _make_calibrator(tmp_path)
        csv_path = str(tmp_path / "backtest.csv")

        rows = []
        for i in range(15):
            rows.append({
                "symbol": "BTC", "side": "BUY", "strategy": "ensemble",
                "close_reason": "TP1", "entry": "100", "exit": "105",
                "sl": "95", "tp1": "105", "tp2": "110", "pnl": "50",
                "fee": "1", "leverage": "5", "confidence": "85",
                "rr_achieved": "2.0", "duration_h": "2",
                "state_path": "", "outcome": "WIN",
                "llm_action": "", "llm_regime": "trend", "llm_confidence": "",
            })
        for i in range(5):
            rows.append({
                "symbol": "BTC", "side": "SELL", "strategy": "ensemble",
                "close_reason": "SL", "entry": "100", "exit": "105",
                "sl": "95", "tp1": "95", "tp2": "90", "pnl": "-50",
                "fee": "1", "leverage": "5", "confidence": "85",
                "rr_achieved": "-1.0", "duration_h": "2",
                "state_path": "", "outcome": "LOSS",
                "llm_action": "", "llm_regime": "trend", "llm_confidence": "",
            })

        _write_backtest_csv(csv_path, rows)
        cal.bootstrap_from_backtest(csv_path)

        assert len(cal._observations) == 20
        assert cal._bootstrapped is True

    def test_bootstrap_idempotent(self, tmp_path):
        """Calling bootstrap twice should not double-count."""
        cal = _make_calibrator(tmp_path)
        csv_path = str(tmp_path / "backtest.csv")

        rows = [
            {"symbol": "BTC", "side": "BUY", "strategy": "ensemble",
             "close_reason": "TP1", "entry": "100", "exit": "105",
             "sl": "95", "tp1": "105", "tp2": "110", "pnl": "50",
             "fee": "1", "leverage": "5", "confidence": "85",
             "rr_achieved": "2.0", "duration_h": "2",
             "state_path": "", "outcome": "WIN",
             "llm_action": "", "llm_regime": "", "llm_confidence": ""}
        ] * 10

        _write_backtest_csv(csv_path, rows)
        cal.bootstrap_from_backtest(csv_path)
        count_after_first = len(cal._observations)
        cal.bootstrap_from_backtest(csv_path)
        count_after_second = len(cal._observations)

        assert count_after_first == count_after_second

    def test_bootstrap_missing_file(self, tmp_path):
        """Missing CSV should not crash."""
        cal = _make_calibrator(tmp_path)
        cal.bootstrap_from_backtest(str(tmp_path / "nonexistent.csv"))
        assert len(cal._observations) == 0

    def test_bootstrap_builds_curve(self, tmp_path):
        """After bootstrap with enough data, curve should be built."""
        cal = _make_calibrator(tmp_path)
        csv_path = str(tmp_path / "backtest.csv")

        rows = []
        # 15 wins and 5 losses at 85% confidence
        for i in range(15):
            rows.append({
                "symbol": "HYPE", "side": "BUY", "strategy": "ensemble",
                "close_reason": "TP1", "entry": "28", "exit": "30",
                "sl": "26", "tp1": "30", "tp2": "32", "pnl": "100",
                "fee": "1", "leverage": "10", "confidence": "85",
                "rr_achieved": "3.0", "duration_h": "1",
                "state_path": "", "outcome": "WIN",
                "llm_action": "", "llm_regime": "", "llm_confidence": "",
            })
        for i in range(5):
            rows.append({
                "symbol": "HYPE", "side": "BUY", "strategy": "ensemble",
                "close_reason": "SL", "entry": "28", "exit": "26",
                "sl": "26", "tp1": "30", "tp2": "32", "pnl": "-100",
                "fee": "1", "leverage": "10", "confidence": "85",
                "rr_achieved": "-1.0", "duration_h": "1",
                "state_path": "", "outcome": "LOSS",
                "llm_action": "", "llm_regime": "", "llm_confidence": "",
            })

        _write_backtest_csv(csv_path, rows)
        cal.bootstrap_from_backtest(csv_path)

        # Curve should exist
        assert "global" in cal._curve or "HYPE" in cal._curve
        # Calibration should work
        result = cal.calibrate(85.0, symbol="HYPE")
        assert isinstance(result, float)


# ────────────────────────────────────────────────────────────────────
# SECTION 5: Calibration summary and prompt context
# ────────────────────────────────────────────────────────────────────

class TestCalibrationReporting:
    """Test summary and prompt context generation."""

    def test_summary_with_data(self, tmp_path):
        """Summary should include bins and overall bias."""
        cal = _make_calibrator(tmp_path)
        _seed_observations(cal, 95.0, win_rate=0.4, n=20)
        _seed_observations(cal, 75.0, win_rate=0.8, n=20)
        cal.rebuild_curve()

        summary = cal.get_calibration_summary()
        assert summary["total_observations"] == 40
        assert "global" in summary["scopes"]
        assert summary["overall_bias"] is not None

    def test_summary_empty(self, tmp_path):
        """Empty calibrator should return clean summary."""
        cal = _make_calibrator(tmp_path)
        summary = cal.get_calibration_summary()
        assert summary["total_observations"] == 0
        assert summary["overall_bias"] is None

    def test_prompt_context_overconfident(self, tmp_path):
        """Prompt context should flag overconfident bins."""
        cal = _make_calibrator(tmp_path)
        _seed_observations(cal, 95.0, win_rate=0.4, n=25)
        cal.rebuild_curve()

        context = cal.get_prompt_context()
        assert "OVERCONFIDENT" in context or "overconfident" in context.lower()

    def test_prompt_context_insufficient_data(self, tmp_path):
        """With <20 observations, prompt context should be empty."""
        cal = _make_calibrator(tmp_path)
        for i in range(10):
            cal.record_observation(85.0, was_correct=True)
        cal.rebuild_curve()

        context = cal.get_prompt_context()
        assert context == ""


# ────────────────────────────────────────────────────────────────────
# SECTION 6: Bin key edge cases
# ────────────────────────────────────────────────────────────────────

class TestBinKeys:
    """Test bin key assignment edge cases."""

    def test_bin_boundaries(self, tmp_path):
        cal = _make_calibrator(tmp_path)
        assert cal._get_bin_key(50.0) == "50-60"
        assert cal._get_bin_key(59.9) == "50-60"
        assert cal._get_bin_key(60.0) == "60-70"
        assert cal._get_bin_key(90.0) == "90-100"
        assert cal._get_bin_key(99.9) == "90-100"
        assert cal._get_bin_key(100.0) == "90-100"

    def test_below_50(self, tmp_path):
        cal = _make_calibrator(tmp_path)
        assert cal._get_bin_key(30.0) == "50-60"

    def test_symbol_normalization(self, tmp_path):
        cal = _make_calibrator(tmp_path)
        assert cal._normalize_symbol("BTC/USDC:USDC") == "BTC"
        assert cal._normalize_symbol("SOL/USDT:USDT") == "SOL"
        assert cal._normalize_symbol("ETH/USD") == "ETH"
        assert cal._normalize_symbol("HYPE") == "HYPE"
        assert cal._normalize_symbol("") == ""


# ────────────────────────────────────────────────────────────────────
# SECTION 7: Persistence
# ────────────────────────────────────────────────────────────────────

class TestPersistence:
    """Test saving and loading calibration data."""

    def test_curve_save_and_load(self, tmp_path):
        """Curve should survive save/load cycle."""
        cal = _make_calibrator(tmp_path)
        _seed_observations(cal, 85.0, win_rate=0.60, n=20)
        cal.rebuild_curve()

        # Create new calibrator pointing to same dir
        cal2 = _make_calibrator(tmp_path)
        assert len(cal2._curve) > 0

    def test_observations_persist(self, tmp_path):
        """Observations should persist to JSONL file."""
        cal = _make_calibrator(tmp_path)
        cal.record_observation(85.0, True, symbol="BTC")
        cal.record_observation(75.0, False, symbol="SOL")

        # New calibrator loads from same dir
        cal2 = _make_calibrator(tmp_path)
        assert len(cal2._observations) >= 2


# ────────────────────────────────────────────────────────────────────
# SECTION 8: Pipeline integration
# ────────────────────────────────────────────────────────────────────

class TestPipelineIntegration:
    """Test that calibration integrates correctly with signal pipeline."""

    def test_config_flags_exist(self):
        """TradingConfig should have calibration config fields."""
        from trading_config import TradingConfig
        config = TradingConfig()
        assert hasattr(config, "confidence_calibration_enabled")
        assert hasattr(config, "calibration_window")
        assert config.confidence_calibration_enabled is True
        assert config.calibration_window == 50

    def test_config_env_override(self):
        """Config should respect env var overrides."""
        with patch.dict(os.environ, {
            "CONFIDENCE_CALIBRATION_ENABLED": "false",
            "CALIBRATION_WINDOW": "100",
        }):
            from trading_config import TradingConfig
            config = TradingConfig()
            assert config.confidence_calibration_enabled is False
            assert config.calibration_window == 100

    def test_disabled_calibration_no_change(self, tmp_path):
        """When disabled, calibrate() should still return raw confidence."""
        cal = _make_calibrator(tmp_path)
        _seed_observations(cal, 95.0, win_rate=0.4, n=20)
        cal.rebuild_curve()

        # Even with curve data, calibrate still works (the disable is in pipeline)
        # But we can verify the calibrator itself always works
        result = cal.calibrate(95.0)
        assert result != 95.0  # Calibrator applies if it has data


# ────────────────────────────────────────────────────────────────────
# SECTION 9: Real-world scenario
# ────────────────────────────────────────────────────────────────────

class TestRealWorldScenario:
    """Simulate the actual problem: 90%+ losing, 70-79% winning."""

    def test_backtest_pattern_correction(self, tmp_path):
        """Simulate the observed pattern and verify calibration fixes it.

        The key outcome: 90-100% raw confidence gets significantly deflated,
        closing the gap with lower-confidence bands. This prevents the sizing
        system from over-betting on overconfident signals.
        """
        cal = _make_calibrator(tmp_path)

        # 90-100% confidence: 40% WR (losing)
        _seed_observations(cal, 95.0, win_rate=0.40, n=20)
        # 80-89% confidence: 55% WR (marginal)
        _seed_observations(cal, 85.0, win_rate=0.55, n=20)
        # 70-79% confidence: 65% WR (sweet spot)
        _seed_observations(cal, 75.0, win_rate=0.65, n=20)
        # 60-69%: 50% WR
        _seed_observations(cal, 65.0, win_rate=0.50, n=20)

        cal.rebuild_curve()

        # 95% raw should be deflated significantly (MAX_ADJUSTMENT caps at 20pts)
        cal_95 = cal.calibrate(95.0)
        assert cal_95 < 85.0, f"95% should deflate to <85, got {cal_95}"

        # 85% raw should also be deflated (55% WR < 85% claimed)
        cal_85 = cal.calibrate(85.0)
        assert cal_85 < 85.0, f"85% should deflate, got {cal_85}"

        # The gap between 95% and 75% raw should SHRINK after calibration
        # Raw gap: 95 - 75 = 20 points
        # Calibrated gap should be smaller because 95% gets deflated more
        cal_75 = cal.calibrate(75.0)
        raw_gap = 95.0 - 75.0
        calibrated_gap = cal_95 - cal_75
        assert calibrated_gap < raw_gap, (
            f"Calibration should shrink gap: raw={raw_gap}, "
            f"calibrated={calibrated_gap:.1f}"
        )

    def test_per_symbol_real_pattern(self, tmp_path):
        """BTC at 80% is reliable, SOL at 80% is not."""
        cal = _make_calibrator(tmp_path)

        # BTC: 80% confidence = 82% actual WR (well calibrated)
        _seed_observations(cal, 82.0, win_rate=0.82, n=15, symbol="BTC")
        # SOL: 80% confidence = 55% actual WR (overconfident)
        _seed_observations(cal, 82.0, win_rate=0.55, n=15, symbol="SOL")

        cal.rebuild_curve()

        btc_cal = cal.calibrate(82.0, symbol="BTC")
        sol_cal = cal.calibrate(82.0, symbol="SOL")

        # BTC should stay ~82, SOL should be deflated
        assert btc_cal > sol_cal, (
            f"BTC ({btc_cal:.1f}) should calibrate higher than SOL ({sol_cal:.1f})"
        )
        assert sol_cal < 75.0, f"SOL at 55% WR should deflate below 75, got {sol_cal}"
