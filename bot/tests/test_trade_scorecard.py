"""
Tests for the Pre-Trade Quality Scorecard.

Validates:
- Each scoring dimension independently
- Composite scoring with pass/fail thresholds
- The 3 HYPE losses would be rejected (score < 50)
- The SOL SELL winner would pass (score >= 50)
- Half-size vs full-size classification
- JSONL logging of every evaluation
- Integration with sniper filter (scorecard gate)
"""

import json
import os
import pytest
import tempfile
from dataclasses import dataclass, field
from typing import Dict, Any


# ── Minimal Signal stub ──
@dataclass
class MockSignal:
    strategy: str = "regime_trend"
    symbol: str = "HYPE"
    side: str = "BUY"
    confidence: float = 82.0
    entry: float = 40.0
    sl: float = 39.0
    tp1: float = 42.0
    tp2: float = 44.0
    atr: float = 1.5
    metadata: Dict[str, Any] = field(default_factory=dict)
    signal_context: str = "Strong trend continuation"

    @property
    def is_valid(self):
        return True


class TestConfidenceScoring:
    """Test dimension 1: Confidence (25 pts max)."""

    def test_elite_confidence(self):
        from manual.trade_scorecard import TradeScorecard
        sc = TradeScorecard()
        assert sc._score_confidence(90) == 25
        assert sc._score_confidence(85) == 25
        assert sc._score_confidence(99) == 25

    def test_high_confidence(self):
        from manual.trade_scorecard import TradeScorecard
        sc = TradeScorecard()
        assert sc._score_confidence(80) == 20
        assert sc._score_confidence(84) == 20

    def test_medium_confidence(self):
        from manual.trade_scorecard import TradeScorecard
        sc = TradeScorecard()
        assert sc._score_confidence(75) == 15
        assert sc._score_confidence(79) == 15

    def test_low_confidence(self):
        from manual.trade_scorecard import TradeScorecard
        sc = TradeScorecard()
        assert sc._score_confidence(70) == 8
        assert sc._score_confidence(74) == 8

    def test_junk_confidence(self):
        from manual.trade_scorecard import TradeScorecard
        sc = TradeScorecard()
        assert sc._score_confidence(60) == 3  # Partial credit for 60%+
        assert sc._score_confidence(50) == 0
        assert sc._score_confidence(69) == 3


class TestConsensusScoring:
    """Test dimension 2: Consensus (25 pts max)."""

    def test_triple_agree(self):
        from manual.trade_scorecard import TradeScorecard
        assert TradeScorecard._score_consensus(3) == 25
        assert TradeScorecard._score_consensus(4) == 25

    def test_double_agree(self):
        from manual.trade_scorecard import TradeScorecard
        assert TradeScorecard._score_consensus(2) == 15

    def test_solo_signal(self):
        from manual.trade_scorecard import TradeScorecard
        assert TradeScorecard._score_consensus(1) == 5  # Partial credit for solo proven setups
        assert TradeScorecard._score_consensus(0) == 0


class TestEdgeTrendScoring:
    """Test dimension 3: Edge Trend (15 pts max)."""

    def test_strengthening_edge(self):
        from manual.trade_scorecard import TradeScorecard
        assert TradeScorecard._score_edge_trend("SOL_SELL") == 15

    def test_stable_edge(self):
        from manual.trade_scorecard import TradeScorecard
        assert TradeScorecard._score_edge_trend("BTC_BUY") == 10
        assert TradeScorecard._score_edge_trend("SOL_BUY") == 10

    def test_weakening_edge(self):
        from manual.trade_scorecard import TradeScorecard
        assert TradeScorecard._score_edge_trend("HYPE_BUY") == 0
        assert TradeScorecard._score_edge_trend("BTC_SELL") == 0

    def test_unknown_setup(self):
        from manual.trade_scorecard import TradeScorecard
        # Unknown defaults to "stable" = 10
        assert TradeScorecard._score_edge_trend("DOGE_BUY") == 10


class TestRegimeScoring:
    """Test dimension 4: Regime Quality (15 pts max, can go negative)."""

    def test_aligned_bull_buy(self):
        from manual.trade_scorecard import TradeScorecard
        assert TradeScorecard._score_regime("trending_bull", "BUY") == 15

    def test_aligned_bear_sell(self):
        from manual.trade_scorecard import TradeScorecard
        assert TradeScorecard._score_regime("trending_bear", "SELL") == 15

    def test_counter_trend(self):
        from manual.trade_scorecard import TradeScorecard
        assert TradeScorecard._score_regime("trending_bull", "SELL") == 0
        assert TradeScorecard._score_regime("trending_bear", "BUY") == 0

    def test_generic_trend(self):
        from manual.trade_scorecard import TradeScorecard
        assert TradeScorecard._score_regime("trend", "BUY") == 15
        assert TradeScorecard._score_regime("trend", "SELL") == 15

    def test_neutral_regime(self):
        from manual.trade_scorecard import TradeScorecard
        assert TradeScorecard._score_regime("consolidation", "BUY") == 10
        assert TradeScorecard._score_regime("range", "SELL") == 10

    def test_dangerous_regime(self):
        from manual.trade_scorecard import TradeScorecard
        assert TradeScorecard._score_regime("panic", "BUY") == -10
        assert TradeScorecard._score_regime("high_volatility", "SELL") == -10
        assert TradeScorecard._score_regime("unknown", "BUY") == -10

    def test_unknown_regime_defaults_dangerous(self):
        from manual.trade_scorecard import TradeScorecard
        assert TradeScorecard._score_regime("unknown", "BUY") == -10


class TestVolRegimeScoring:
    """Test dimension 5: Vol Regime (10 pts max, can go negative)."""

    def test_hype_optimal_vol(self):
        from manual.trade_scorecard import TradeScorecard
        # HYPE at $20, ATR=$0.30 => atr_pct=1.5%  (in 1.40-1.69 optimal band)
        assert TradeScorecard._score_vol_regime("HYPE_BUY", 0.30, 20.0) == 10

    def test_hype_extreme_vol(self):
        from manual.trade_scorecard import TradeScorecard
        # HYPE at $20, ATR=$0.50 => atr_pct=2.5% (extreme)
        assert TradeScorecard._score_vol_regime("HYPE_BUY", 0.50, 20.0) == -5

    def test_sol_optimal_vol(self):
        from manual.trade_scorecard import TradeScorecard
        # SOL at $100, ATR=$0.90 => atr_pct=0.90% (in 0.80-0.98 optimal band)
        assert TradeScorecard._score_vol_regime("SOL_SELL", 0.90, 100.0) == 10

    def test_no_atr_data(self):
        from manual.trade_scorecard import TradeScorecard
        assert TradeScorecard._score_vol_regime("HYPE_BUY", None, 20.0) == 5

    def test_no_entry_price(self):
        from manual.trade_scorecard import TradeScorecard
        assert TradeScorecard._score_vol_regime("HYPE_BUY", 0.30, None) == 5


class TestTimeOfDayScoring:
    """Test dimension 6: Time of Day (15 pts max, granular seasonality)."""

    def test_peak_alpha_window(self):
        """18-20 UTC = +12 (peak alpha)."""
        from manual.trade_scorecard import TradeScorecard
        # weekday=1 (Tuesday) = no day bonus/penalty
        assert TradeScorecard._score_time_of_day(18, weekday=1) == 12
        assert TradeScorecard._score_time_of_day(19, weekday=1) == 12
        assert TradeScorecard._score_time_of_day(20, weekday=1) == 12

    def test_hype_sweet_spot(self):
        """09-11 UTC = +8."""
        from manual.trade_scorecard import TradeScorecard
        assert TradeScorecard._score_time_of_day(9, weekday=1) == 8
        assert TradeScorecard._score_time_of_day(10, weekday=1) == 8
        assert TradeScorecard._score_time_of_day(11, weekday=1) == 8

    def test_us_open_dip_buy(self):
        """14-15 UTC = -5 for BUY (US open bearish dip)."""
        from manual.trade_scorecard import TradeScorecard
        assert TradeScorecard._score_time_of_day(14, side="BUY", weekday=1) == -5
        assert TradeScorecard._score_time_of_day(15, side="BUY", weekday=1) == -5

    def test_us_open_dip_sell(self):
        """14-15 UTC = +5 for SELL (US open bearish = good for shorts)."""
        from manual.trade_scorecard import TradeScorecard
        assert TradeScorecard._score_time_of_day(14, side="SELL", weekday=1) == 5
        assert TradeScorecard._score_time_of_day(15, side="SELL", weekday=1) == 5

    def test_dead_zone(self):
        """04-06 UTC = -3 (low liquidity)."""
        from manual.trade_scorecard import TradeScorecard
        assert TradeScorecard._score_time_of_day(4, weekday=1) == -3
        assert TradeScorecard._score_time_of_day(5, weekday=1) == -3
        assert TradeScorecard._score_time_of_day(6, weekday=1) == -3

    def test_overnight_decent(self):
        """21-03 UTC = +5 (decent overnight)."""
        from manual.trade_scorecard import TradeScorecard
        assert TradeScorecard._score_time_of_day(22, weekday=1) == 5
        assert TradeScorecard._score_time_of_day(0, weekday=1) == 5
        assert TradeScorecard._score_time_of_day(3, weekday=1) == 5

    def test_neutral_hours(self):
        """7-8, 12-13, 16-17 UTC = 0."""
        from manual.trade_scorecard import TradeScorecard
        assert TradeScorecard._score_time_of_day(7, weekday=1) == 0
        assert TradeScorecard._score_time_of_day(12, weekday=1) == 0
        assert TradeScorecard._score_time_of_day(17, weekday=1) == 0

    def test_monday_bonus(self):
        """Monday = +3 bonus on top of hour score."""
        from manual.trade_scorecard import TradeScorecard
        assert TradeScorecard._score_time_of_day(18, weekday=0) == 15  # 12 + 3
        assert TradeScorecard._score_time_of_day(12, weekday=0) == 3   # 0 + 3

    def test_thursday_penalty(self):
        """Thursday = -3 penalty on top of hour score."""
        from manual.trade_scorecard import TradeScorecard
        assert TradeScorecard._score_time_of_day(18, weekday=3) == 9   # 12 - 3
        assert TradeScorecard._score_time_of_day(12, weekday=3) == -3  # 0 - 3


class TestCompositeScoring:
    """Test full scorecard with pass/fail thresholds."""

    def _make_scorecard(self, log_path=None):
        from manual.trade_scorecard import TradeScorecard
        if log_path is None:
            log_path = os.path.join(tempfile.mkdtemp(), "test_scorecards.jsonl")
        return TradeScorecard(log_path=log_path)

    def test_junk_hype_loss_1(self):
        """HYPE loss #1: 1-agree, 62% conf, high_volatility regime."""
        sc = self._make_scorecard()
        result = sc.score(
            symbol="HYPE", side="BUY",
            confidence=62, num_agree=1,
            regime="high_volatility",
            utc_hour=10,  # weak hours
        )
        # confidence=0, consensus=0, edge=0(weakening), regime=-10, vol=5(unknown), time=0
        # total = -5, clamped to 0
        assert result.total_score < 50
        assert not result.passed
        assert result.size_factor == 0.0

    def test_junk_hype_loss_2(self):
        """HYPE loss #2: 1-agree, 60% conf, unknown regime."""
        sc = self._make_scorecard()
        result = sc.score(
            symbol="HYPE", side="BUY",
            confidence=60, num_agree=1,
            regime="unknown",
            utc_hour=14,
        )
        assert result.total_score < 50
        assert not result.passed

    def test_junk_hype_loss_3(self):
        """HYPE loss #3: 1-agree, 61% conf, panic regime."""
        sc = self._make_scorecard()
        result = sc.score(
            symbol="HYPE", side="BUY",
            confidence=61, num_agree=1,
            regime="panic",
            utc_hour=8,
        )
        assert result.total_score < 50
        assert not result.passed

    def test_sol_sell_winner(self):
        """SOL SELL winner: 3-agree, 85% conf, trending_bear, prime hours."""
        sc = self._make_scorecard()
        result = sc.score(
            symbol="SOL", side="SELL",
            confidence=85, num_agree=3,
            regime="trending_bear",
            atr=0.90, entry_price=100.0,
            utc_hour=22,  # prime hours
        )
        # confidence=25, consensus=25, edge=15, regime=15, vol=10, time=10 = 100
        assert result.total_score >= 70
        assert result.passed
        assert result.size_factor == 1.0

    def test_decent_hype_buy(self):
        """Decent HYPE BUY: 2-agree, 82% conf, trend, prime hours."""
        sc = self._make_scorecard()
        result = sc.score(
            symbol="HYPE", side="BUY",
            confidence=82, num_agree=2,
            regime="trend",
            atr=0.30, entry_price=20.0,  # atr_pct=1.5%, optimal band
            utc_hour=20,
        )
        # confidence=20, consensus=15, edge=0, regime=15, vol=10, time=10 = 70
        assert result.total_score >= 50
        assert result.passed

    def test_half_size_zone(self):
        """Score between 50-69 should get half size."""
        sc = self._make_scorecard()
        result = sc.score(
            symbol="HYPE", side="BUY",
            confidence=82, num_agree=2,
            regime="consolidation",  # neutral = 10
            utc_hour=10,  # weak hours = 0
        )
        # confidence=20, consensus=15, edge=0, regime=10, vol=5(no atr), time=0 = 50
        assert result.total_score >= 50
        assert result.total_score < 70
        assert result.passed
        assert result.size_factor == 0.5

    def test_full_size_zone(self):
        """Score >= 70 should get full size."""
        sc = self._make_scorecard()
        result = sc.score(
            symbol="SOL", side="SELL",
            confidence=88, num_agree=3,
            regime="trend",
            utc_hour=22,
        )
        # confidence=25, consensus=25, edge=15, regime=15, vol=5, time=10 = 95
        assert result.total_score >= 70
        assert result.size_factor == 1.0

    def test_score_clamped_to_zero(self):
        """Negative scores should be clamped to 0."""
        sc = self._make_scorecard()
        result = sc.score(
            symbol="HYPE", side="BUY",
            confidence=50, num_agree=1,
            regime="panic",
            utc_hour=10,
        )
        assert result.total_score >= 0

    def test_score_clamped_to_100(self):
        """Scores above 100 should be clamped."""
        sc = self._make_scorecard()
        result = sc.score(
            symbol="SOL", side="SELL",
            confidence=95, num_agree=4,
            regime="trending_bear",
            atr=0.90, entry_price=100.0,
            utc_hour=22,
        )
        assert result.total_score <= 100


class TestScorecardLogging:
    """Test JSONL logging of evaluations."""

    def test_logs_passed_evaluation(self):
        from manual.trade_scorecard import TradeScorecard
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "scorecards.jsonl")
            sc = TradeScorecard(log_path=log_path)
            sc.score(
                symbol="SOL", side="SELL",
                confidence=85, num_agree=3,
                regime="trend", utc_hour=22,
            )
            with open(log_path) as f:
                lines = f.readlines()
            assert len(lines) == 1
            record = json.loads(lines[0])
            assert record["symbol"] == "SOL"
            assert record["passed"] is True
            assert "components" in record
            assert "timestamp" in record

    def test_logs_failed_evaluation(self):
        from manual.trade_scorecard import TradeScorecard
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "scorecards.jsonl")
            sc = TradeScorecard(log_path=log_path)
            sc.score(
                symbol="HYPE", side="BUY",
                confidence=60, num_agree=1,
                regime="unknown", utc_hour=10,
            )
            with open(log_path) as f:
                record = json.loads(f.readline())
            assert record["passed"] is False
            assert record["total_score"] < 50

    def test_multiple_evaluations_append(self):
        from manual.trade_scorecard import TradeScorecard
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "scorecards.jsonl")
            sc = TradeScorecard(log_path=log_path)
            for _ in range(5):
                sc.score("SOL", "SELL", 85, 3, "trend", utc_hour=22)
            with open(log_path) as f:
                lines = f.readlines()
            assert len(lines) == 5


class TestScorecardFormatting:
    """Test human-readable scorecard formatting."""

    def test_format_pass(self):
        from manual.trade_scorecard import TradeScorecard
        with tempfile.TemporaryDirectory() as tmpdir:
            sc = TradeScorecard(log_path=os.path.join(tmpdir, "sc.jsonl"))
            result = sc.score("SOL", "SELL", 85, 3, "trend", utc_hour=22)
            text = sc.format_scorecard(result)
            assert "PASS" in text
            assert "FULL" in text

    def test_format_reject(self):
        from manual.trade_scorecard import TradeScorecard
        with tempfile.TemporaryDirectory() as tmpdir:
            sc = TradeScorecard(log_path=os.path.join(tmpdir, "sc.jsonl"))
            result = sc.score("HYPE", "BUY", 60, 1, "unknown", utc_hour=10)
            text = sc.format_scorecard(result)
            assert "REJECT" in text
            assert "BLOCKED" in text


class TestScorecardSniperIntegration:
    """Test scorecard wired into sniper filter."""

    def _make_filter(self, **overrides):
        from manual.sniper_filter import ManualSniperFilter
        from manual.config import ManualSniperConfig
        config = ManualSniperConfig()
        for k, v in overrides.items():
            setattr(config, k, v)
        f = ManualSniperFilter(config)
        f._running_equity = overrides.get('equity', 100.0)
        return f

    def test_junk_hype_rejected_by_scorecard(self):
        """1-agree, 62% conf HYPE BUY should be rejected."""
        filt = self._make_filter(mode="standard", min_confidence=50, min_num_agree=1)
        signal = MockSignal(
            symbol="HYPE", side="BUY", confidence=62, entry=40.0,
            sl=39.0, tp1=42.0, tp2=44.0,
            metadata={"num_agree": 1, "regime": "high_volatility", "chop_score": 0.2},
        )
        result = filt.evaluate(signal)
        # Should be blocked by one of the quality gates (scorecard or quality_floor)
        assert result is None

    def test_good_sol_sell_passes(self):
        """3-agree, 85% conf SOL SELL in trending_bear should pass."""
        filt = self._make_filter(mode="standard")
        signal = MockSignal(
            symbol="SOL", side="SELL", confidence=85, entry=100.0,
            sl=102.0, tp1=96.0, tp2=93.0, atr=0.90,
            metadata={
                "num_agree": 3,
                "strategies_agree": ["regime_trend", "monte_carlo", "multi_tier"],
                "regime": "trending_bear",
                "ev_per_dollar": 0.3,
                "chop_score": 0.15,
            },
        )
        result = filt.evaluate(signal)
        assert result is not None
        assert result.symbol == "SOL"
        assert result.side == "SELL"

    def test_scorecard_instance_exists(self):
        """Sniper filter should have a _scorecard attribute."""
        filt = self._make_filter()
        assert hasattr(filt, '_scorecard')
        from manual.trade_scorecard import TradeScorecard
        assert isinstance(filt._scorecard, TradeScorecard)
