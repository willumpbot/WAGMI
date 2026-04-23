"""Tests for the deep_trade_analyst module (statistics + formatting, no CLI)."""
import os
import sys
import json
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from llm.deep_trade_analyst import _compute_statistics, _format_stats_for_prompt, _check_milestone


SAMPLE_TRADES = [
    {"symbol": "BTC", "side": "SHORT", "outcome": "WIN", "pnl": 12.0,
     "regime": "trending", "num_agree": 2, "leverage": 3.0,
     "hold_time_s": 7200, "confidence": 75.0, "btc_trend": "down"},
    {"symbol": "BTC", "side": "SHORT", "outcome": "WIN", "pnl": 8.0,
     "regime": "trending", "num_agree": 2, "leverage": 3.0,
     "hold_time_s": 5400, "confidence": 72.0, "btc_trend": "down"},
    {"symbol": "BTC", "side": "SHORT", "outcome": "WIN", "pnl": 9.0,
     "regime": "trending", "num_agree": 2, "leverage": 2.0,
     "hold_time_s": 4800, "confidence": 78.0, "btc_trend": "down"},
    {"symbol": "BTC", "side": "SHORT", "outcome": "WIN", "pnl": 11.0,
     "regime": "trending", "num_agree": 2, "leverage": 3.0,
     "hold_time_s": 6600, "confidence": 76.0, "btc_trend": "down"},
    {"symbol": "BTC", "side": "SHORT", "outcome": "LOSS", "pnl": -5.0,
     "regime": "trending", "num_agree": 1, "leverage": 2.0,
     "hold_time_s": 1800, "confidence": 65.0, "btc_trend": "flat"},
    {"symbol": "SOL", "side": "LONG", "outcome": "LOSS", "pnl": -4.0,
     "regime": "ranging", "num_agree": 1, "leverage": 2.0,
     "hold_time_s": 900, "confidence": 58.0, "btc_trend": "flat"},
    {"symbol": "SOL", "side": "LONG", "outcome": "LOSS", "pnl": -3.0,
     "regime": "ranging", "num_agree": 1, "leverage": 2.0,
     "hold_time_s": 600, "confidence": 55.0, "btc_trend": "flat"},
    {"symbol": "SOL", "side": "LONG", "outcome": "LOSS", "pnl": -5.0,
     "regime": "ranging", "num_agree": 1, "leverage": 2.5,
     "hold_time_s": 1200, "confidence": 57.0, "btc_trend": "flat"},
    {"symbol": "SOL", "side": "LONG", "outcome": "LOSS", "pnl": -3.5,
     "regime": "ranging", "num_agree": 1, "leverage": 2.0,
     "hold_time_s": 750, "confidence": 56.0, "btc_trend": "flat"},
    {"symbol": "SOL", "side": "LONG", "outcome": "WIN", "pnl": 2.0,
     "regime": "ranging", "num_agree": 2, "leverage": 1.5,
     "hold_time_s": 1500, "confidence": 60.0, "btc_trend": "flat"},
]


class TestComputeStatistics:
    def test_overall_stats_computed(self):
        stats = _compute_statistics(SAMPLE_TRADES)
        overall = stats["overall"]
        assert overall["n"] == 10
        assert overall["wins"] == 5
        assert overall["wr"] == 0.5

    def test_by_regime_groups(self):
        stats = _compute_statistics(SAMPLE_TRADES)
        by_regime = stats["by_regime"]
        # trending should qualify (5 trades)
        assert "trending" in by_regime
        assert by_regime["trending"]["wr"] == 0.8  # 4/5 wins
        # ranging should qualify (5 trades)
        assert "ranging" in by_regime
        assert by_regime["ranging"]["wr"] == 0.2  # 1/5 wins

    def test_by_symbol_side_groups(self):
        stats = _compute_statistics(SAMPLE_TRADES)
        by_ss = stats["by_symbol_side"]
        assert "BTC.SHORT" in by_ss
        assert by_ss["BTC.SHORT"]["wr"] == 0.8  # 4/5
        assert "SOL.LONG" in by_ss
        assert by_ss["SOL.LONG"]["wr"] == 0.2   # 1/5

    def test_avg_pnl_computed(self):
        stats = _compute_statistics(SAMPLE_TRADES)
        btc_short = stats["by_symbol_side"]["BTC.SHORT"]
        # avg pnl = (12+8+9+11-5)/5 = 7.0
        assert btc_short["avg_pnl"] == 7.0

    def test_cells_below_min_excluded(self):
        # With only 2 trades of a type, it won't appear
        small_trades = SAMPLE_TRADES[:3]
        stats = _compute_statistics(small_trades)
        # SOL.LONG only has 1 trade here — won't appear
        by_ss = stats["by_symbol_side"]
        assert "SOL.LONG" not in by_ss


class TestFormatStats:
    def test_formats_without_crash(self):
        stats = _compute_statistics(SAMPLE_TRADES)
        text = _format_stats_for_prompt(stats)
        assert "TOTAL TRADES: 10" in text
        assert "BY REGIME" in text

    def test_plus_for_profitable_cells(self):
        stats = _compute_statistics(SAMPLE_TRADES)
        text = _format_stats_for_prompt(stats)
        # BTC.SHORT has avg_pnl > 1, should get +
        assert "+ BTC.SHORT" in text or "+ trending" in text

    def test_minus_for_losing_cells(self):
        stats = _compute_statistics(SAMPLE_TRADES)
        text = _format_stats_for_prompt(stats)
        # SOL.LONG has avg_pnl < -1, should get -
        assert "- SOL.LONG" in text or "- ranging" in text


class TestMilestoneCheck:
    def test_milestone_at_50(self, tmp_path, monkeypatch):
        monkeypatch.setattr("llm.deep_trade_analyst._STATE_PATH", str(tmp_path / "state.json"))
        # At n=50 with no prior state, should trigger
        assert _check_milestone(50) is True

    def test_milestone_at_164(self, tmp_path, monkeypatch):
        monkeypatch.setattr("llm.deep_trade_analyst._STATE_PATH", str(tmp_path / "state.json"))
        # Should trigger at milestone 150 (max applicable)
        assert _check_milestone(164) is True

    def test_no_milestone_below_50(self, tmp_path, monkeypatch):
        monkeypatch.setattr("llm.deep_trade_analyst._STATE_PATH", str(tmp_path / "state.json"))
        assert _check_milestone(30) is False

    def test_already_analyzed_milestone_skips(self, tmp_path, monkeypatch):
        state_path = str(tmp_path / "state.json")
        monkeypatch.setattr("llm.deep_trade_analyst._STATE_PATH", state_path)
        # Record that we analyzed at n=150 already
        with open(state_path, "w") as f:
            json.dump({"last_analyzed_at_n": 150}, f)
        # At n=164, milestone is 150 which was already done
        assert _check_milestone(164) is False

    def test_new_milestone_triggers_again(self, tmp_path, monkeypatch):
        state_path = str(tmp_path / "state.json")
        monkeypatch.setattr("llm.deep_trade_analyst._STATE_PATH", state_path)
        # Record analyzed at n=100, now at n=164 (milestone 150 is new)
        with open(state_path, "w") as f:
            json.dump({"last_analyzed_at_n": 100}, f)
        assert _check_milestone(164) is True
