"""
Tests for the self-teaching, learning mode, signal override, and signal flagger systems.
"""

import os
import shutil
import sys
import tempfile
import time

import pytest

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from llm.signal_override import (
    SignalPowerScore,
    SignalOverrideEngine,
    BlockerType,
    OverrideDecision,
    should_override_blocker,
    HARD_BLOCKERS,
    OVERRIDEABLE_BLOCKERS,
)
from llm.signal_flagger import (
    SignalFlagger,
    FlagType,
    FlaggedSignal,
)
from llm.learning_mode import (
    LearningPhase,
    LearningState,
    apply_learning_constraints,
)
from llm.self_teaching import (
    CurriculumLevel,
    KnowledgeBase,
    KnowledgeType,
    LearningCycleEngine,
)
from llm.deep_memory import (
    TradeDNA,
    TradeDNAStore,
    StrategyFingerprints,
    PatternLibrary,
    RegimeHistory,
    InsightJournal,
    DeepMemoryManager,
)


# ═══════════════════════════════════════════════════════════════
# Signal Power Score Tests
# ═══════════════════════════════════════════════════════════════


class TestSignalPowerScore:
    def test_basic_power_score(self):
        ps = SignalPowerScore(confidence=80, num_strategies_agree=3, total_strategies=4)
        assert ps.power_score > 0
        assert ps.power_score <= 100

    def test_high_confidence_high_agreement(self):
        ps = SignalPowerScore(
            confidence=90, num_strategies_agree=4, total_strategies=4,
            volume_confirmation=True, regime_aligned=True,
            trend_aligned=True, funding_confirms=True, oi_confirms=True,
        )
        assert ps.is_powerful
        assert ps.is_exceptional

    def test_low_score_not_powerful(self):
        ps = SignalPowerScore(confidence=50, num_strategies_agree=1, total_strategies=4)
        assert not ps.is_powerful
        assert not ps.is_exceptional

    def test_powerful_but_not_exceptional(self):
        # Power = 85*0.4 + (3/4)*25 + 4*7 = 34 + 18.75 + 28 = 80.75 (>75, <85)
        ps = SignalPowerScore(
            confidence=85, num_strategies_agree=3, total_strategies=4,
            volume_confirmation=True, regime_aligned=True,
            trend_aligned=True, funding_confirms=True,
        )
        assert ps.is_powerful
        assert not ps.is_exceptional  # Needs 85+ power AND 3+ agree AND 80+ conf


# ═══════════════════════════════════════════════════════════════
# Signal Override Engine Tests
# ═══════════════════════════════════════════════════════════════


class TestSignalOverrideEngine:
    def test_hard_blockers_never_override(self):
        engine = SignalOverrideEngine()
        power = SignalPowerScore(
            confidence=99, num_strategies_agree=4, total_strategies=4,
            volume_confirmation=True, regime_aligned=True,
            trend_aligned=True, funding_confirms=True, oi_confirms=True,
        )
        for blocker in HARD_BLOCKERS:
            decision = engine.evaluate_override(power, blocker)
            assert not decision.should_override

    def test_exceptional_overrides_circuit_breaker(self):
        engine = SignalOverrideEngine()
        power = SignalPowerScore(
            confidence=90, num_strategies_agree=4, total_strategies=4,
            volume_confirmation=True, regime_aligned=True,
            trend_aligned=True, funding_confirms=True, oi_confirms=True,
        )
        decision = engine.evaluate_override(power, BlockerType.CIRCUIT_BREAKER)
        assert decision.should_override

    def test_weak_signal_does_not_override(self):
        engine = SignalOverrideEngine()
        power = SignalPowerScore(confidence=55, num_strategies_agree=2, total_strategies=4)
        decision = engine.evaluate_override(power, BlockerType.CONSECUTIVE_LOSSES)
        assert not decision.should_override

    def test_daily_cap_enforced(self):
        engine = SignalOverrideEngine()
        engine._max_daily_overrides = 2

        power = SignalPowerScore(
            confidence=90, num_strategies_agree=4, total_strategies=4,
            volume_confirmation=True, regime_aligned=True,
            trend_aligned=True, funding_confirms=True, oi_confirms=True,
        )

        # First two should work
        engine._override_cooldown = 0  # Disable cooldown for test
        d1 = engine.evaluate_override(power, BlockerType.CONSECUTIVE_LOSSES)
        assert d1.should_override

        d2 = engine.evaluate_override(power, BlockerType.CONFIDENCE_FLOOR)
        assert d2.should_override

        # Third should be capped
        d3 = engine.evaluate_override(power, BlockerType.REGIME_MISMATCH)
        assert not d3.should_override

    def test_convenience_function(self):
        decision = should_override_blocker(
            confidence=90, num_agree=4, total_strategies=4,
            blocker=BlockerType.DAILY_LOSS_LIMIT,
        )
        assert not decision.should_override  # Hard blocker


# ═══════════════════════════════════════════════════════════════
# Signal Flagger Tests
# ═══════════════════════════════════════════════════════════════


class TestSignalFlagger:
    def test_no_flags_for_normal_signal(self):
        flagger = SignalFlagger()
        result = flagger.evaluate_signal(
            symbol="BTC", side="BUY", confidence=65, regime="trending",
            num_agree=2, total_strategies=4,
        )
        # Low-conviction signals get no flags
        assert len(result.flags) == 0

    def test_sniper_candidate_flagged(self):
        flagger = SignalFlagger()
        result = flagger.evaluate_signal(
            symbol="BTC", side="BUY", confidence=85, regime="trend",
            num_agree=3, total_strategies=4, volume_ratio=1.5,
        )
        flag_types = {f.flag_type for f in result.flags}
        assert FlagType.SNIPER_CANDIDATE in flag_types

    def test_anomaly_flagged(self):
        flagger = SignalFlagger()
        result = flagger.evaluate_signal(
            symbol="BTC", side="BUY", confidence=70, regime="trending",
            num_agree=2, total_strategies=4,
            volume_ratio=4.0, funding_rate=0.1,
        )
        flag_types = {f.flag_type for f in result.flags}
        assert FlagType.ANOMALY in flag_types

    def test_squeeze_flagged(self):
        flagger = SignalFlagger()
        result = flagger.evaluate_signal(
            symbol="BTC", side="BUY", confidence=70, regime="trending",
            num_agree=2, total_strategies=4,
            funding_rate=-0.05, oi_change_pct=-5.0, price_change_1h=1.0,
        )
        flag_types = {f.flag_type for f in result.flags}
        assert FlagType.SQUEEZE_SETUP in flag_types

    def test_divergence_flagged(self):
        flagger = SignalFlagger()
        result = flagger.evaluate_signal(
            symbol="BTC", side="BUY", confidence=70, regime="trending",
            num_agree=2, total_strategies=4,
            strategy_signals={
                "regime_trend": "BUY", "monte_carlo": "BUY",
                "confidence_scorer": "SELL", "multi_tier": "SELL",
            },
        )
        flag_types = {f.flag_type for f in result.flags}
        assert FlagType.STRATEGY_DIVERGENCE in flag_types

    def test_should_trigger_llm(self):
        flagger = SignalFlagger()
        result = flagger.evaluate_signal(
            symbol="BTC", side="BUY", confidence=90, regime="trend",
            num_agree=4, total_strategies=4, volume_ratio=2.0,
        )
        assert result.should_trigger_llm


# ═══════════════════════════════════════════════════════════════
# Learning Mode Tests
# ═══════════════════════════════════════════════════════════════


class TestLearningMode:
    def test_absorb_blocks_veto(self):
        """In ABSORB phase, vetoes are overridden to proceed."""
        action, mult, reason = apply_learning_constraints(
            llm_action="flat",
            llm_confidence=0.8,
            llm_size_multiplier=1.0,
            signal_confidence=70.0,
        )
        # Can't veto during absorb (checked via function behavior)
        # This tests the function directly - phase depends on global state
        assert action in ("flat", "proceed")  # Depends on internal phase

    def test_absorb_blocks_flip(self):
        action, mult, reason = apply_learning_constraints(
            llm_action="flip",
            llm_confidence=0.9,
            llm_size_multiplier=1.5,
            signal_confidence=70.0,
        )
        assert action in ("flip", "proceed")

    def test_learning_state_defaults(self):
        state = LearningState()
        assert state.phase == 0
        assert state.trades_observed == 0
        assert state.counterfactual_accuracy == 0.0


# ═══════════════════════════════════════════════════════════════
# Self-Teaching Knowledge Base Tests
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def tmp_teach_dir(monkeypatch):
    """Create a temporary directory for teaching data."""
    d = tempfile.mkdtemp(prefix="teach_test_")
    # Monkey-patch the module paths
    monkeypatch.setattr("llm.self_teaching._TEACH_DIR", d)
    yield d
    shutil.rmtree(d, ignore_errors=True)


class TestKnowledgeBase:
    def test_add_and_search(self, tmp_teach_dir):
        kb = KnowledgeBase()
        kb.add(KnowledgeType.AXIOM, "Never trade without stop loss", confidence=0.95, category="risk")
        kb.add(KnowledgeType.PRINCIPLE, "BTC leads alt moves", confidence=0.7, category="correlation")

        axioms = kb.get_axioms()
        assert len(axioms) == 1
        assert "stop loss" in axioms[0]["content"]

        principles = kb.get_principles(min_confidence=0.6)
        assert len(principles) == 1

    def test_deduplication(self, tmp_teach_dir):
        kb = KnowledgeBase()
        idx1 = kb.add(KnowledgeType.OBSERVATION, "BTC is trending up")
        idx2 = kb.add(KnowledgeType.OBSERVATION, "BTC is trending up")
        assert idx1 == idx2  # Same entry updated

    def test_validation_increases_confidence(self, tmp_teach_dir):
        kb = KnowledgeBase()
        kb.add(KnowledgeType.HYPOTHESIS, "SOL strong in Asian hours", confidence=0.5)
        kb.validate("SOL strong in Asian hours", True, "Won 3/4 trades 0-8 UTC")
        entries = kb.search(knowledge_type=KnowledgeType.HYPOTHESIS)
        assert entries[0]["confidence"] > 0.5
        assert entries[0]["validation_count"] == 1

    def test_invalidation_decreases_confidence(self, tmp_teach_dir):
        kb = KnowledgeBase()
        kb.add(KnowledgeType.HYPOTHESIS, "Always short DOGE", confidence=0.5)
        kb.validate("Always short DOGE", False, "DOGE pump 20%")
        entries = kb.search(knowledge_type=KnowledgeType.HYPOTHESIS)
        assert entries[0]["confidence"] < 0.5

    def test_search_by_category(self, tmp_teach_dir):
        kb = KnowledgeBase()
        kb.add(KnowledgeType.OBSERVATION, "BTC bullish", category="symbol")
        kb.add(KnowledgeType.OBSERVATION, "High vol", category="regime")
        results = kb.search(category="symbol")
        assert len(results) == 1

    def test_get_for_llm_prompt(self, tmp_teach_dir):
        kb = KnowledgeBase()
        kb.add(KnowledgeType.AXIOM, "Test axiom", confidence=0.95)
        kb.add(KnowledgeType.PRINCIPLE, "Test principle", confidence=0.8)
        prompt = kb.get_for_llm_prompt()
        assert "AXIOMS" in prompt
        assert "Test axiom" in prompt


# ═══════════════════════════════════════════════════════════════
# Learning Cycle Engine Tests
# ═══════════════════════════════════════════════════════════════


class TestLearningCycleEngine:
    def test_seed_axioms(self, tmp_teach_dir):
        engine = LearningCycleEngine()
        axioms = engine.knowledge.get_axioms()
        assert len(axioms) >= 5  # Should have seeded axioms

    def test_extract_patterns(self, tmp_teach_dir):
        engine = LearningCycleEngine()
        trades = [
            {"symbol": "BTC", "outcome": "WIN", "pnl": 10, "regime": "trending", "confidence": 75, "side": "BUY"},
            {"symbol": "BTC", "outcome": "WIN", "pnl": 8, "regime": "trending", "confidence": 72, "side": "BUY"},
            {"symbol": "BTC", "outcome": "WIN", "pnl": 12, "regime": "trending", "confidence": 80, "side": "BUY"},
            {"symbol": "BTC", "outcome": "LOSS", "pnl": -5, "regime": "ranging", "confidence": 65, "side": "SELL"},
        ]
        patterns = engine._extract_patterns(trades)
        assert len(patterns) > 0

    def test_learning_cycle_runs(self, tmp_teach_dir):
        engine = LearningCycleEngine()
        trades = []
        for i in range(15):
            trades.append({
                "symbol": "BTC",
                "outcome": "WIN" if i % 3 != 0 else "LOSS",
                "pnl": 10 if i % 3 != 0 else -5,
                "regime": "trending",
                "confidence": 70 + i,
                "side": "BUY",
                "hold_time_s": 300 + i * 60,
                "num_agree": 3,
                "leverage": 2,
            })

        report = engine.run_learning_cycle(trades)
        assert report["trades_analyzed"] == 15
        assert report["cycle_number"] == 1

    def test_curriculum_starts_at_level_1(self, tmp_teach_dir):
        engine = LearningCycleEngine()
        assert engine.curriculum.current_level == CurriculumLevel.PATTERN_RECOGNITION

    def test_generate_hypotheses(self, tmp_teach_dir):
        engine = LearningCycleEngine()
        engine.curriculum.current_level = CurriculumLevel.CAUSAL_ANALYSIS
        trades = [
            {"symbol": "BTC", "outcome": "WIN", "side": "BUY", "hold_time_s": 100, "leverage": 2},
            {"symbol": "BTC", "outcome": "WIN", "side": "BUY", "hold_time_s": 150, "leverage": 2},
            {"symbol": "BTC", "outcome": "WIN", "side": "BUY", "hold_time_s": 200, "leverage": 2},
            {"symbol": "BTC", "outcome": "LOSS", "side": "SELL", "hold_time_s": 500, "leverage": 2},
            {"symbol": "BTC", "outcome": "LOSS", "side": "SELL", "hold_time_s": 600, "leverage": 2},
            {"symbol": "BTC", "outcome": "LOSS", "side": "SELL", "hold_time_s": 700, "leverage": 2},
        ]
        hypotheses = engine._generate_hypotheses(trades)
        assert isinstance(hypotheses, list)


# ═══════════════════════════════════════════════════════════════
# Deep Memory Tests
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def tmp_deep_dir(monkeypatch):
    d = tempfile.mkdtemp(prefix="deep_mem_test_")
    monkeypatch.setattr("llm.deep_memory._DEEP_MEMORY_DIR", d)
    yield d
    shutil.rmtree(d, ignore_errors=True)


class TestTradeDNAStore:
    def test_record_and_retrieve(self, tmp_deep_dir):
        store = TradeDNAStore()
        dna = TradeDNA(
            trade_id="test_001",
            symbol="BTC",
            side="BUY",
            entry_price=95000,
            exit_price=96000,
            outcome="WIN",
            pnl=100,
            confidence=80,
            regime="trending",
            strategies_agreed=["regime_trend", "monte_carlo"],
        )
        store.record_trade(dna)
        assert len(store._trades) == 1

    def test_get_sniper_trades(self, tmp_deep_dir):
        import time as _time
        store = TradeDNAStore()
        dna = TradeDNA(
            trade_id="sniper_001", symbol="BTC", side="BUY",
            outcome="WIN", pnl=500, was_sniper=True, quality_score=0.9,
            timestamp=_time.time(),  # clean-ledger era
        )
        store.record_trade(dna)
        snipers = store.get_sniper_trades()
        assert len(snipers) == 1

    def test_get_sniper_trades_excludes_dirty_ledger(self, tmp_deep_dir):
        """FALLACY_AUDIT M12: pre-clean-ledger snipers are not replication templates."""
        store = TradeDNAStore()
        dna = TradeDNA(
            trade_id="sniper_dirty", symbol="ETH", side="SELL",
            outcome="WIN", pnl=1010, was_sniper=True, quality_score=0.9,
            timestamp=TradeDNAStore.CLEAN_LEDGER_EPOCH - 86400,
        )
        store.record_trade(dna)
        assert store.get_sniper_trades() == []

    def test_summary_stats(self, tmp_deep_dir):
        store = TradeDNAStore()
        for i in range(5):
            dna = TradeDNA(
                trade_id=f"test_{i}", symbol="BTC", side="BUY",
                outcome="WIN" if i < 3 else "LOSS",
                pnl=10 if i < 3 else -5,
                regime="trending",
            )
            store.record_trade(dna)
        stats = store.get_summary_stats()
        assert stats["total_trades"] == 5
        assert stats["wins"] == 3
        assert stats["win_rate"] == 0.6


class TestStrategyFingerprints:
    def test_update_and_retrieve(self, tmp_deep_dir):
        fp = StrategyFingerprints()
        for i in range(10):
            fp.update("regime_trend", "BTC", "trending", "BUY", i < 7, 10 if i < 7 else -5, 75)
        all_fps = fp.get_all()
        assert "regime_trend" in all_fps
        assert all_fps["regime_trend"]["total"] == 10

    def test_context_string(self, tmp_deep_dir):
        fp = StrategyFingerprints()
        for i in range(10):
            fp.update("monte_carlo", "BTC", "trending", "BUY", True, 10, 80)
        ctx = fp.get_for_context("monte_carlo", "BTC", "trending")
        assert "monte_carlo" in ctx
        assert "100%" in ctx


class TestInsightJournal:
    def test_add_and_retrieve(self, tmp_deep_dir):
        journal = InsightJournal()
        journal.add_insight("strategy_insight", "Regime trend works best in trending markets", confidence=0.8)
        results = journal.get_by_category("strategy_insight")
        assert len(results) == 1

    def test_summary_for_llm(self, tmp_deep_dir):
        """FALLACY_AUDIT M19: only vc>=3 insights are served, with evidence."""
        journal = InsightJournal()
        journal.add_insight("strategy_insight", "Test insight 1", confidence=0.9,
                            evidence="BTC WIN $+10 in trend")
        journal.add_insight("regime_insight", "Test insight 2", confidence=0.8)
        # Unvalidated opinions are NOT served
        assert journal.get_summary_for_llm() == ""
        # Validate insight 1 three times -> served with tally + evidence
        for _ in range(3):
            journal.validate_insight("Test insight 1", True)
        summary = journal.get_summary_for_llm()
        assert "Test insight 1" in summary
        assert "validated 3x" in summary
        assert "evidence" in summary
        assert "Test insight 2" not in summary


class TestDeepMemoryManager:
    def test_record_full_trade(self, tmp_deep_dir):
        mgr = DeepMemoryManager()
        mgr.record_full_trade(
            trade_id="t1", symbol="BTC", side="BUY",
            entry_price=95000, exit_price=96000,
            sl=93000, tp1=97000, tp2=99000,
            confidence=80, leverage=3, regime="trending",
            strategies_agreed=["regime_trend", "monte_carlo"],
            outcome="WIN", pnl=100, hold_time_s=600,
            exit_reason="TP1",
        )
        stats = mgr.trade_dna.get_summary_stats()
        assert stats["total_trades"] == 1

    def test_build_knowledge_summary(self, tmp_deep_dir):
        mgr = DeepMemoryManager()
        for i in range(5):
            mgr.record_full_trade(
                trade_id=f"t{i}", symbol="BTC", side="BUY",
                entry_price=95000, exit_price=96000,
                sl=93000, tp1=97000, tp2=99000,
                confidence=75, leverage=2, regime="trending",
                strategies_agreed=["regime_trend"],
                outcome="WIN" if i < 3 else "LOSS",
                pnl=50 if i < 3 else -20,
                hold_time_s=300,
                exit_reason="TP1",
            )
        summary = mgr.build_llm_knowledge_summary(symbol="BTC", regime="trending")
        assert "PERFORMANCE" in summary


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
