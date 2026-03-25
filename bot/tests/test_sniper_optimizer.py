"""
Tests for the Sniper Optimizer module.

Covers cold-start (empty data), signal quality analysis,
leverage efficiency calculations, timing analysis, and report generation.
"""

import json
import os
import tempfile
import shutil
from datetime import datetime, timezone, timedelta
from unittest import mock

import pytest


def _make_signal(
    symbol="HYPE",
    side="BUY",
    tier="SNIPER",
    confidence=88.0,
    num_agree=3,
    leverage=20.0,
    entry=40.0,
    sl=39.0,
    timestamp=None,
    **kwargs,
):
    """Create a test sniper signal dict."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat()
    sig = {
        "symbol": symbol,
        "side": side,
        "tier": tier,
        "confidence": confidence,
        "num_agree": num_agree,
        "leverage": leverage,
        "entry": entry,
        "sl": sl,
        "tp_scalp": entry * 1.04,
        "tp_swing": entry * 1.08,
        "risk_pct": 0.10,
        "risk_amount": 10.0,
        "position_size_usd": 200.0,
        "qty": 5.0,
        "pnl_scalp": 8.0,
        "pnl_swing": 16.0,
        "loss_amount": 10.0,
        "rr_scalp": 1.5,
        "rr_swing": 3.0,
        "strategies": ["a", "b", "c"][:num_agree],
        "regime": "trend",
        "ev_per_dollar": 0.15,
        "signal_context": "Test signal",
        "timestamp": timestamp,
        "hold_target_hours": "2-8h (swing)",
    }
    sig.update(kwargs)
    return sig


def _make_trade(
    symbol="HYPE",
    side="BUY",
    entry_price=40.0,
    exit_price=41.5,
    leverage=20.0,
    pnl=15.0,
    status="CLOSED",
    tier="SNIPER",
    confidence=88.0,
    sl=39.0,
    entry_time=None,
    exit_time=None,
    **kwargs,
):
    """Create a test trade dict."""
    if entry_time is None:
        entry_time = datetime.now(timezone.utc).isoformat()
    if exit_time is None:
        exit_time = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    trade = {
        "trade_id": f"test_{hash(f'{symbol}{entry_time}')}",
        "symbol": symbol,
        "side": side,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "leverage": leverage,
        "qty": 5.0,
        "margin_used": entry_price * 5.0 / leverage,
        "pnl": pnl,
        "pnl_pct": pnl / (entry_price * 5.0 / leverage) * 100 if leverage else 0,
        "status": status,
        "tier": tier,
        "confidence": confidence,
        "sl": sl,
        "entry_time": entry_time,
        "exit_time": exit_time,
        "exit_reason": "TP" if pnl > 0 else "SL",
        "hold_time_hours": 2.0,
        "notes": "",
    }
    trade.update(kwargs)
    return trade


def _write_jsonl(path, records):
    """Write records to a JSONL file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


@pytest.fixture
def tmp_data_dir(monkeypatch):
    """Create a temp directory and patch the optimizer paths."""
    tmpdir = tempfile.mkdtemp()
    manual_dir = os.path.join(tmpdir, "data", "manual")
    os.makedirs(manual_dir, exist_ok=True)

    import manual.optimizer as opt_mod
    monkeypatch.setattr(opt_mod, "_DATA_DIR", manual_dir)
    monkeypatch.setattr(opt_mod, "_SIGNALS_PATH", os.path.join(manual_dir, "sniper_signals.jsonl"))
    monkeypatch.setattr(opt_mod, "_SIM_TRADES_PATH", os.path.join(manual_dir, "sim_trades.jsonl"))
    monkeypatch.setattr(opt_mod, "_JOURNAL_PATH", os.path.join(manual_dir, "trade_journal.jsonl"))
    monkeypatch.setattr(opt_mod, "_REPORTS_DIR", os.path.join(manual_dir, "weekly_reports"))

    yield manual_dir

    shutil.rmtree(tmpdir, ignore_errors=True)


# ── Cold Start Tests ──────────────────────────────────────────────


class TestColdStart:
    """Test optimizer behavior with empty/missing data."""

    def test_signal_quality_no_data(self, tmp_data_dir):
        from manual.optimizer import SniperOptimizer
        opt = SniperOptimizer()
        result = opt.analyze_signal_quality()
        assert result["status"] == "cold_start"
        assert result["total_signals"] == 0
        assert result["recommendations"] == []

    def test_leverage_efficiency_no_trades(self, tmp_data_dir):
        from manual.optimizer import SniperOptimizer
        opt = SniperOptimizer()
        result = opt.analyze_leverage_efficiency()
        assert result["status"] == "no_trades"
        assert result["leverage_bands"] == {}

    def test_timing_no_data(self, tmp_data_dir):
        from manual.optimizer import SniperOptimizer
        opt = SniperOptimizer()
        result = opt.analyze_timing()
        assert result["status"] == "cold_start"

    def test_suggest_no_data(self, tmp_data_dir):
        from manual.optimizer import SniperOptimizer
        opt = SniperOptimizer()
        result = opt.suggest_parameter_changes()
        assert result == {}

    def test_weekly_report_cold_start(self, tmp_data_dir):
        from manual.optimizer import SniperOptimizer
        opt = SniperOptimizer()
        report = opt.generate_weekly_report()
        assert "Sniper Optimizer Report" in report
        assert "No signals" in report or "cold_start" in report or "Waiting" in report

    def test_telegram_summary_cold_start(self, tmp_data_dir):
        from manual.optimizer import SniperOptimizer
        opt = SniperOptimizer()
        summary = opt.format_telegram_summary()
        assert "SNIPER OPTIMIZER" in summary
        assert "No data yet" in summary


# ── Signal Quality Tests ──────────────────────────────────────────


class TestSignalQuality:
    """Test signal quality analysis with mock data."""

    def test_basic_signal_analysis(self, tmp_data_dir):
        from manual.optimizer import SniperOptimizer

        now = datetime.now(timezone.utc)
        signals = [
            _make_signal(tier="SNIPER", confidence=90, timestamp=(now - timedelta(hours=i)).isoformat())
            for i in range(10)
        ] + [
            _make_signal(tier="PREMIUM", confidence=82, timestamp=(now - timedelta(hours=i+10)).isoformat())
            for i in range(5)
        ] + [
            _make_signal(tier="STANDARD", confidence=78, timestamp=(now - timedelta(hours=i+20)).isoformat())
            for i in range(5)
        ]
        _write_jsonl(os.path.join(tmp_data_dir, "sniper_signals.jsonl"), signals)

        opt = SniperOptimizer()
        result = opt.analyze_signal_quality()

        assert result["status"] == "ok"
        assert result["total_signals"] == 20
        assert result["tier_distribution"]["SNIPER"] == 10
        assert result["tier_distribution"]["PREMIUM"] == 5
        assert result["tier_distribution"]["STANDARD"] == 5
        assert result["signal_to_noise"] == 0.75  # (10+5)/20
        assert result["confidence"]["avg"] > 80

    def test_symbol_distribution(self, tmp_data_dir):
        from manual.optimizer import SniperOptimizer

        signals = [
            _make_signal(symbol="HYPE"),
            _make_signal(symbol="HYPE"),
            _make_signal(symbol="BTC"),
            _make_signal(symbol="SOL"),
        ]
        _write_jsonl(os.path.join(tmp_data_dir, "sniper_signals.jsonl"), signals)

        opt = SniperOptimizer()
        result = opt.analyze_signal_quality()
        assert result["symbol_distribution"]["HYPE"] == 2
        assert result["symbol_distribution"]["BTC"] == 1
        assert result["symbol_distribution"]["SOL"] == 1

    def test_dedup_detection(self, tmp_data_dir):
        from manual.optimizer import SniperOptimizer

        now = datetime.now(timezone.utc)
        # Two signals for same symbol+side within 5 minutes = potential dupe
        signals = [
            _make_signal(symbol="HYPE", side="BUY", timestamp=now.isoformat()),
            _make_signal(symbol="HYPE", side="BUY", timestamp=(now + timedelta(minutes=3)).isoformat()),
            _make_signal(symbol="BTC", side="BUY", timestamp=(now + timedelta(minutes=10)).isoformat()),
        ]
        _write_jsonl(os.path.join(tmp_data_dir, "sniper_signals.jsonl"), signals)

        opt = SniperOptimizer()
        result = opt.analyze_signal_quality()
        assert result["potential_dupes"] >= 1

    def test_noisy_signals_recommendation(self, tmp_data_dir):
        """Too many signals per day should recommend raising min_confidence."""
        from manual.optimizer import SniperOptimizer

        now = datetime.now(timezone.utc)
        # 15 signals in one day
        signals = [
            _make_signal(
                tier="STANDARD",
                confidence=79,
                timestamp=(now - timedelta(minutes=i * 30)).isoformat()
            )
            for i in range(15)
        ]
        _write_jsonl(os.path.join(tmp_data_dir, "sniper_signals.jsonl"), signals)

        opt = SniperOptimizer()
        result = opt.analyze_signal_quality()
        rec_params = [r["param"] for r in result["recommendations"]]
        assert "min_confidence" in rec_params or "min_num_agree" in rec_params


# ── Leverage Efficiency Tests ─────────────────────────────────────


class TestLeverageEfficiency:
    """Test leverage efficiency analysis."""

    def test_leverage_bands(self, tmp_data_dir):
        from manual.optimizer import SniperOptimizer

        trades = [
            _make_trade(leverage=8, pnl=5.0),
            _make_trade(leverage=8, pnl=3.0),
            _make_trade(leverage=12, pnl=10.0),
            _make_trade(leverage=12, pnl=-5.0),
            _make_trade(leverage=12, pnl=8.0),
            _make_trade(leverage=22, pnl=20.0),
            _make_trade(leverage=22, pnl=-15.0),
            _make_trade(leverage=22, pnl=25.0),
        ]
        _write_jsonl(os.path.join(tmp_data_dir, "trade_journal.jsonl"), trades)

        opt = SniperOptimizer()
        result = opt.analyze_leverage_efficiency()

        assert result["status"] == "ok"
        assert result["total_closed"] == 8
        assert result["leverage_bands"]["1-10x"]["count"] == 2
        assert result["leverage_bands"]["10-15x"]["count"] == 3
        assert result["leverage_bands"]["20-25x"]["count"] == 3

    def test_leverage_win_rates(self, tmp_data_dir):
        from manual.optimizer import SniperOptimizer

        trades = [
            _make_trade(leverage=12, pnl=10.0),
            _make_trade(leverage=12, pnl=8.0),
            _make_trade(leverage=12, pnl=-2.0),
        ]
        _write_jsonl(os.path.join(tmp_data_dir, "trade_journal.jsonl"), trades)

        opt = SniperOptimizer()
        result = opt.analyze_leverage_efficiency()
        band = result["leverage_bands"]["10-15x"]
        assert band["count"] == 3
        assert abs(band["win_rate"] - 0.667) < 0.01

    def test_sim_trades_fallback(self, tmp_data_dir):
        """If no trade_journal, should fall back to sim_trades."""
        from manual.optimizer import SniperOptimizer

        trades = [
            _make_trade(leverage=15, pnl=12.0),
            _make_trade(leverage=15, pnl=-4.0),
        ]
        _write_jsonl(os.path.join(tmp_data_dir, "sim_trades.jsonl"), trades)

        opt = SniperOptimizer()
        result = opt.analyze_leverage_efficiency()
        assert result["total_closed"] == 2


# ── Timing Analysis Tests ─────────────────────────────────────────


class TestTimingAnalysis:
    """Test timing analysis."""

    def test_hour_distribution(self, tmp_data_dir):
        from manual.optimizer import SniperOptimizer

        now = datetime.now(timezone.utc).replace(hour=14, minute=0)
        signals = [
            _make_signal(timestamp=now.isoformat()),
            _make_signal(timestamp=now.replace(hour=14, minute=30).isoformat()),
            _make_signal(timestamp=now.replace(hour=8).isoformat()),
            _make_signal(timestamp=now.replace(hour=20).isoformat()),
        ]
        _write_jsonl(os.path.join(tmp_data_dir, "sniper_signals.jsonl"), signals)

        opt = SniperOptimizer()
        result = opt.analyze_timing()

        assert result["status"] == "ok"
        assert result["hour_distribution"][14] == 2
        assert result["hour_distribution"][8] == 1
        assert result["hour_distribution"][20] == 1

    def test_win_loss_hours(self, tmp_data_dir):
        from manual.optimizer import SniperOptimizer

        now = datetime.now(timezone.utc)
        signals = [_make_signal() for _ in range(2)]
        _write_jsonl(os.path.join(tmp_data_dir, "sniper_signals.jsonl"), signals)

        trades = [
            _make_trade(pnl=10.0, entry_time=now.replace(hour=10).isoformat()),
            _make_trade(pnl=8.0, entry_time=now.replace(hour=10).isoformat()),
            _make_trade(pnl=-5.0, entry_time=now.replace(hour=3).isoformat()),
            _make_trade(pnl=-3.0, entry_time=now.replace(hour=3).isoformat()),
        ]
        _write_jsonl(os.path.join(tmp_data_dir, "trade_journal.jsonl"), trades)

        opt = SniperOptimizer()
        result = opt.analyze_timing()
        assert result["hourly_win_rate"].get(10, 0) == 1.0
        assert result["hourly_win_rate"].get(3, 1) == 0.0


# ── Report Generation Tests ──────────────────────────────────────


class TestReportGeneration:
    """Test weekly report generation."""

    def test_report_with_data(self, tmp_data_dir):
        from manual.optimizer import SniperOptimizer

        now = datetime.now(timezone.utc)
        signals = [
            _make_signal(
                tier="SNIPER", confidence=90,
                timestamp=(now - timedelta(hours=i)).isoformat()
            )
            for i in range(10)
        ]
        trades = [
            _make_trade(leverage=20, pnl=15.0),
            _make_trade(leverage=20, pnl=10.0),
            _make_trade(leverage=15, pnl=-5.0),
        ]
        _write_jsonl(os.path.join(tmp_data_dir, "sniper_signals.jsonl"), signals)
        _write_jsonl(os.path.join(tmp_data_dir, "trade_journal.jsonl"), trades)

        opt = SniperOptimizer()
        report = opt.generate_weekly_report()

        assert "Sniper Optimizer Report" in report
        assert "Signal Quality" in report
        assert "Leverage Efficiency" in report
        assert "Timing Analysis" in report
        assert "Parameter Recommendations" in report

        # Check file was saved
        reports_dir = os.path.join(tmp_data_dir, "weekly_reports")
        assert os.path.exists(reports_dir)
        files = os.listdir(reports_dir)
        assert len(files) == 1
        assert files[0].startswith("report_")
        assert files[0].endswith(".md")

    def test_report_markdown_format(self, tmp_data_dir):
        from manual.optimizer import SniperOptimizer

        signals = [_make_signal() for _ in range(5)]
        _write_jsonl(os.path.join(tmp_data_dir, "sniper_signals.jsonl"), signals)

        opt = SniperOptimizer()
        report = opt.generate_weekly_report()

        # Should be valid markdown with headers
        assert report.startswith("#")
        assert "##" in report


# ── Parameter Suggestions Tests ───────────────────────────────────


class TestParameterSuggestions:
    """Test parameter change suggestions."""

    def test_no_suggestions_insufficient_data(self, tmp_data_dir):
        from manual.optimizer import SniperOptimizer

        signals = [_make_signal()]
        _write_jsonl(os.path.join(tmp_data_dir, "sniper_signals.jsonl"), signals)

        opt = SniperOptimizer()
        result = opt.suggest_parameter_changes()
        # With just 1 signal and no trades, shouldn't suggest much
        assert isinstance(result, dict)

    def test_suggestions_structure(self, tmp_data_dir):
        from manual.optimizer import SniperOptimizer

        now = datetime.now(timezone.utc)
        signals = [_make_signal(confidence=82, tier="PREMIUM") for _ in range(20)]
        trades = [
            _make_trade(confidence=82, tier="PREMIUM", pnl=-5.0)
            for _ in range(8)
        ] + [
            _make_trade(confidence=90, tier="SNIPER", pnl=15.0)
            for _ in range(8)
        ]
        _write_jsonl(os.path.join(tmp_data_dir, "sniper_signals.jsonl"), signals)
        _write_jsonl(os.path.join(tmp_data_dir, "trade_journal.jsonl"), trades)

        opt = SniperOptimizer()
        result = opt.suggest_parameter_changes()

        # Each suggestion should have required fields
        for param, info in result.items():
            assert "current" in info
            assert "suggested" in info
            assert "reason" in info
            assert "confidence_pct" in info
            assert isinstance(info["confidence_pct"], (int, float))
            assert info["confidence_pct"] <= 100

    def test_telegram_summary_format(self, tmp_data_dir):
        from manual.optimizer import SniperOptimizer

        signals = [_make_signal() for _ in range(5)]
        _write_jsonl(os.path.join(tmp_data_dir, "sniper_signals.jsonl"), signals)

        opt = SniperOptimizer()
        summary = opt.format_telegram_summary()

        assert "SNIPER OPTIMIZER" in summary
        lines = summary.strip().split("\n")
        # Should be concise
        assert len(lines) <= 25
