"""
Tests for quant data backbone (quant_data.py) and graduated rules engine (graduated_rules.py).
"""

import os
import sys
import json
import time
import tempfile
import pytest

# Ensure bot/ is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ──────────────────────────────────────────────────────────────
# Helpers: mock TradeDNA store with synthetic trades
# ──────────────────────────────────────────────────────────────

class MockTradeDNAStore:
    """Minimal TradeDNA store loaded with synthetic trades for testing."""

    def __init__(self, trades=None):
        self._trades = trades or []
        self._loaded = True

    def _ensure_loaded(self):
        pass


def _make_trades(n_wins=15, n_losses=5, regime="trend", setup_type="scalp",
                 strategies=None, btc_trend="up", volume_ratio=1.2):
    """Generate synthetic trade records."""
    strategies = strategies or ["regime_trend", "confidence_scorer"]
    trades = []
    for i in range(n_wins):
        trades.append({
            "outcome": "WIN", "pnl": 50 + i * 5, "pnl_pct": 2.0 + i * 0.2,
            "regime": regime, "entry_type": setup_type,
            "strategies_agreed": strategies, "num_agree": len(strategies),
            "btc_trend": btc_trend, "volume_ratio": volume_ratio,
            "entry_price": 40000, "sl": 39000,
        })
    for i in range(n_losses):
        trades.append({
            "outcome": "LOSS", "pnl": -(30 + i * 5), "pnl_pct": -(1.5 + i * 0.3),
            "regime": regime, "entry_type": setup_type,
            "strategies_agreed": strategies, "num_agree": len(strategies),
            "btc_trend": btc_trend, "volume_ratio": volume_ratio,
            "entry_price": 40000, "sl": 39000,
        })
    return trades


# ══════════════════════════════════════════════════════════════
# QUANT DATA PROVIDER TESTS
# ══════════════════════════════════════════════════════════════

class TestQuantDataProvider:
    """Tests for QuantDataProvider."""

    def _make_provider(self, trades):
        from llm.quant_data import QuantDataProvider
        store = MockTradeDNAStore(trades)
        return QuantDataProvider(trade_dna_store=store)

    def test_avg_win_loss_basic(self):
        trades = _make_trades(n_wins=10, n_losses=5)
        qp = self._make_provider(trades)
        result = qp.get_avg_win_loss(group_by="entry_type")
        assert "scalp" in result
        assert result["scalp"]["n_wins"] == 10
        assert result["scalp"]["n_losses"] == 5
        assert result["scalp"]["avg_win"] > 0
        assert result["scalp"]["avg_loss"] > 0
        assert result["scalp"]["avg_win_ratio"] > 0

    def test_avg_win_loss_regime_filter(self):
        trades = _make_trades(regime="trend") + _make_trades(regime="range", n_wins=3, n_losses=7)
        qp = self._make_provider(trades)
        trend = qp.get_avg_win_loss(regime_filter="trend")
        assert "scalp" in trend
        assert trend["scalp"]["n_wins"] == 15

    def test_avg_win_loss_empty(self):
        qp = self._make_provider([])
        result = qp.get_avg_win_loss()
        assert result == {}

    # ── Kelly Fraction ──

    def test_kelly_positive_edge(self):
        trades = _make_trades(n_wins=15, n_losses=5)  # 75% WR
        qp = self._make_provider(trades)
        k = qp.compute_kelly(setup_type="scalp", min_trades=10)
        assert k["sufficient_data"] is True
        assert k["kelly_fraction"] > 0
        assert k["half_kelly"] > 0
        assert k["half_kelly"] <= k["kelly_fraction"]
        assert k["win_rate"] == 0.75

    def test_kelly_negative_edge(self):
        trades = _make_trades(n_wins=3, n_losses=17)  # 15% WR
        qp = self._make_provider(trades)
        k = qp.compute_kelly(min_trades=10)
        assert k["sufficient_data"] is True
        assert k["kelly_fraction"] < 0  # Negative edge
        assert k["half_kelly"] == 0.0   # Half-kelly clamped to 0

    def test_kelly_insufficient_data(self):
        trades = _make_trades(n_wins=2, n_losses=1)
        qp = self._make_provider(trades)
        k = qp.compute_kelly(min_trades=10)
        assert k["sufficient_data"] is False
        assert k["kelly_fraction"] is None

    def test_kelly_matrix(self):
        trades = _make_trades(regime="trend", setup_type="scalp") + \
                 _make_trades(regime="range", setup_type="breakout", n_wins=8, n_losses=6)
        qp = self._make_provider(trades)
        m = qp.compute_kelly_matrix(min_trades=5)
        assert isinstance(m, dict)

    # ── Conditional Edge ──

    def test_conditional_edge_with_regime(self):
        trades = _make_trades(regime="trend", n_wins=15, n_losses=5) + \
                 _make_trades(regime="range", n_wins=3, n_losses=12)
        qp = self._make_provider(trades)
        e = qp.compute_conditional_edge(regime="trend", min_trades=5)
        assert e["sufficient_data"] is True
        assert e["conditional_wr"] > e["base_wr"]  # Trend regime has better WR
        assert e["edge_pct"] > 0

    def test_conditional_edge_with_agreement(self):
        trades = _make_trades(n_wins=15, n_losses=5)
        qp = self._make_provider(trades)
        e = qp.compute_conditional_edge(num_agree=2, min_trades=5)
        assert e["sufficient_data"] is True

    def test_conditional_edge_insufficient(self):
        trades = _make_trades(n_wins=1, n_losses=1)
        qp = self._make_provider(trades)
        e = qp.compute_conditional_edge(regime="trend", min_trades=10)
        assert e["sufficient_data"] is False

    # ── Fat-Tail Risk ──

    def test_fat_tail_risk_normal(self):
        trades = _make_trades(n_wins=15, n_losses=5)
        qp = self._make_provider(trades)
        ft = qp.compute_fat_tail_risk()
        assert ft["sufficient_data"] is True
        assert ft["fat_tail_risk"] in ("low", "medium", "high")
        assert ft["p95_adverse"] is not None
        assert ft["p95_adverse"] >= 0

    def test_fat_tail_risk_panic_regime(self):
        trades = _make_trades(n_wins=5, n_losses=10, regime="panic")
        qp = self._make_provider(trades)
        ft = qp.compute_fat_tail_risk(regime="panic")
        assert ft["sufficient_data"] is True
        assert ft["fat_tail_risk"] == "high"  # Panic always high risk

    def test_fat_tail_risk_insufficient(self):
        trades = _make_trades(n_wins=1, n_losses=1)
        qp = self._make_provider(trades)
        ft = qp.compute_fat_tail_risk()
        assert ft["sufficient_data"] is False

    # ── Convergence Matrix ──

    def test_convergence_matrix(self):
        trades = _make_trades(strategies=["regime_trend", "confidence_scorer"], n_wins=10, n_losses=3)
        qp = self._make_provider(trades)
        cm = qp.compute_convergence_matrix(min_trades=3)
        assert isinstance(cm, dict)
        # Should have at least one pair
        if cm:
            pair = list(cm.values())[0]
            assert "wr" in pair
            assert "n" in pair

    def test_convergence_matrix_empty(self):
        qp = self._make_provider([])
        cm = qp.compute_convergence_matrix()
        assert cm == {}

    # ── Bayesian Priors ──

    def test_bayesian_priors(self):
        trades = _make_trades(n_wins=15, n_losses=5, btc_trend="up", volume_ratio=2.0)
        qp = self._make_provider(trades)
        p = qp.compute_bayesian_priors()
        assert p["base"]["wr"] > 0
        assert p["base"]["n"] == 20

    def test_bayesian_priors_by_regime(self):
        trades = _make_trades(regime="trend") + _make_trades(regime="range", n_wins=5, n_losses=10)
        qp = self._make_provider(trades)
        p = qp.compute_bayesian_priors()
        assert "trend" in p["by_regime"]
        assert "range" in p["by_regime"]
        assert p["by_regime"]["trend"]["wr"] > p["by_regime"]["range"]["wr"]

    def test_bayesian_priors_empty(self):
        qp = self._make_provider([])
        p = qp.compute_bayesian_priors()
        assert p["base"]["wr"] == 0.5
        assert p["base"]["n"] == 0

    # ── Full Quant Package ──

    def test_build_quant_package(self):
        trades = _make_trades(n_wins=15, n_losses=5)
        qp = self._make_provider(trades)
        pkg = qp.build_quant_package(regime="trend", num_agree=2, setup_type="scalp")
        assert isinstance(pkg, dict)
        # With 20 trades, should have kelly, edge, tail, win_loss, priors
        assert "kelly" in pkg or "edge" in pkg or "tail" in pkg

    def test_build_quant_package_empty(self):
        qp = self._make_provider([])
        pkg = qp.build_quant_package()
        assert isinstance(pkg, dict)

    # ── Singleton ──

    def test_singleton(self):
        from llm.quant_data import get_quant_provider
        p1 = get_quant_provider()
        p2 = get_quant_provider()
        assert p1 is p2


# ══════════════════════════════════════════════════════════════
# GRADUATED RULES ENGINE TESTS
# ══════════════════════════════════════════════════════════════

class MockHypothesis:
    """Mock hypothesis for testing graduation."""

    def __init__(self, statement, confidence=0.8, evidence_ratio=0.75,
                 total_evidence=15, supporting_count=12, contradicting_count=3,
                 stage="validated"):
        self.statement = statement
        self.confidence = confidence
        self.evidence_ratio = evidence_ratio
        self.total_evidence = total_evidence
        self.supporting_count = supporting_count
        self.contradicting_count = contradicting_count
        self.stage = stage


class TestGraduatedRulesEngine:
    """Tests for GraduatedRulesEngine."""

    def _make_engine(self):
        from llm.graduated_rules import GraduatedRulesEngine
        engine = GraduatedRulesEngine()
        engine._loaded = True  # Skip file loading
        return engine

    def test_graduate_boost_hypothesis(self):
        engine = self._make_engine()
        h = MockHypothesis("BTC performs strongly in trend regime")
        rule = engine.graduate_hypothesis(h)
        assert rule is not None
        assert rule.action == "boost"
        assert rule.conditions.get("symbol") == "BTC"
        assert rule.conditions.get("regime") == "trend"
        assert rule.adjustment > 0

    def test_graduate_penalize_hypothesis(self):
        engine = self._make_engine()
        h = MockHypothesis("ETH short signals are weak in range regime")
        rule = engine.graduate_hypothesis(h)
        assert rule is not None
        assert rule.action == "penalize"
        assert rule.conditions.get("symbol") == "ETH"
        assert rule.conditions.get("side") == "SELL"
        assert rule.adjustment < 0

    def test_graduate_veto_hypothesis(self):
        engine = self._make_engine()
        h = MockHypothesis("Never buy SOL in panic regime")
        rule = engine.graduate_hypothesis(h)
        assert rule is not None
        assert rule.action == "veto"
        assert rule.conditions.get("symbol") == "SOL"
        assert rule.conditions.get("regime") == "panic"

    def test_no_duplicate_graduation(self):
        engine = self._make_engine()
        h = MockHypothesis("BTC performs strongly in trend regime")
        r1 = engine.graduate_hypothesis(h)
        r2 = engine.graduate_hypothesis(h)
        assert r1 is not None
        assert r2 is None  # Duplicate prevented

    def test_unparseable_hypothesis_returns_none(self):
        engine = self._make_engine()
        h = MockHypothesis("No conditions can possibly match this 12345")
        rule = engine.graduate_hypothesis(h)
        # Should return None because no conditions could be extracted
        assert rule is None

    # ── Signal Evaluation ──

    def test_evaluate_signal_veto(self):
        engine = self._make_engine()
        h = MockHypothesis("Never buy SOL in panic regime")
        engine.graduate_hypothesis(h)

        vetoed, conf, summary, veto_ids = engine.evaluate_signal(
            symbol="SOL", regime="panic", side="BUY", confidence=80.0
        )
        assert vetoed is True
        assert "VETO" in summary
        assert veto_ids and isinstance(veto_ids, list)

    def test_evaluate_signal_boost(self):
        engine = self._make_engine()
        h = MockHypothesis("BTC has a strong edge in trend regime", evidence_ratio=0.85)
        engine.graduate_hypothesis(h)

        vetoed, conf, summary, veto_ids = engine.evaluate_signal(
            symbol="BTC", regime="trend", side="BUY", confidence=70.0
        )
        assert vetoed is False
        assert conf > 70.0  # Boosted
        assert "BOOST" in summary
        assert veto_ids == []

    def test_evaluate_signal_penalize(self):
        engine = self._make_engine()
        h = MockHypothesis("DOGE shows poor performance in range regime")
        engine.graduate_hypothesis(h)

        vetoed, conf, summary, veto_ids = engine.evaluate_signal(
            symbol="DOGE", regime="range", side="BUY", confidence=70.0
        )
        assert vetoed is False
        assert conf < 70.0  # Penalized
        assert "PEN" in summary

    def test_evaluate_signal_no_match(self):
        engine = self._make_engine()
        h = MockHypothesis("BTC has a strong edge in trend regime")
        engine.graduate_hypothesis(h)

        vetoed, conf, summary, veto_ids = engine.evaluate_signal(
            symbol="ETH", regime="range", side="BUY", confidence=70.0
        )
        assert vetoed is False
        assert conf == 70.0  # Unchanged
        assert summary == ""

    def test_confidence_clamped(self):
        engine = self._make_engine()
        h = MockHypothesis("BTC has a strong edge in trend regime", evidence_ratio=0.85)
        engine.graduate_hypothesis(h)

        _, conf, _, _ = engine.evaluate_signal(
            symbol="BTC", regime="trend", side="BUY", confidence=95.0
        )
        assert conf <= 100.0

    # ── Outcome Recording ──

    def test_record_outcome_boost_correct(self):
        engine = self._make_engine()
        h = MockHypothesis("BTC has a strong edge in trend regime")
        engine.graduate_hypothesis(h)

        # Apply the rule
        engine.evaluate_signal(symbol="BTC", regime="trend", side="BUY", confidence=70.0)

        # Record win (boost was correct)
        engine.record_outcome(symbol="BTC", regime="trend", side="BUY", won=True)
        rule = engine._rules[0]
        assert rule.times_correct == 1

    def test_record_outcome_penalize_correct(self):
        engine = self._make_engine()
        h = MockHypothesis("DOGE shows poor performance in range")
        engine.graduate_hypothesis(h)

        engine.evaluate_signal(symbol="DOGE", regime="range", side="BUY", confidence=70.0)
        engine.record_outcome(symbol="DOGE", regime="range", side="BUY", won=False)
        rule = engine._rules[0]
        assert rule.times_correct == 1

    # ── Auto-Retirement ──

    def test_auto_retire_bad_rule(self):
        engine = self._make_engine()
        h = MockHypothesis("BTC has a strong edge in trend regime")
        engine.graduate_hypothesis(h)

        rule = engine._rules[0]
        rule.times_applied = 15
        rule.times_correct = 3  # 20% accuracy < 35% threshold

        # Record an outcome to trigger the check
        engine.record_outcome(symbol="BTC", regime="trend", side="BUY", won=False)
        assert rule.active is False  # Auto-retired

    # ── Summary & Stats ──

    def test_get_active_rules_summary(self):
        engine = self._make_engine()
        h = MockHypothesis("BTC performs strongly in trend regime")
        engine.graduate_hypothesis(h)

        summary = engine.get_active_rules_summary()
        assert "GRADUATED RULES" in summary
        assert "BOOST" in summary

    def test_get_active_rules_summary_empty(self):
        engine = self._make_engine()
        summary = engine.get_active_rules_summary()
        assert summary == ""

    def test_get_stats(self):
        engine = self._make_engine()
        h = MockHypothesis("BTC performs strongly in trend regime")
        engine.graduate_hypothesis(h)

        stats = engine.get_stats()
        assert stats["total_rules"] == 1
        assert stats["active_rules"] == 1

    # ── GraduatedRule dataclass ──

    def test_rule_accuracy_no_applications(self):
        from llm.graduated_rules import GraduatedRule
        r = GraduatedRule()
        assert r.accuracy == 0.5  # Default when no applications

    def test_rule_accuracy_with_data(self):
        from llm.graduated_rules import GraduatedRule
        r = GraduatedRule(times_applied=10, times_correct=7)
        assert r.accuracy == 0.7

    def test_rule_matches_symbol(self):
        from llm.graduated_rules import GraduatedRule
        r = GraduatedRule(active=True, conditions={"symbol": "BTC"})
        assert r.matches(symbol="BTC") is True
        assert r.matches(symbol="ETH") is False
        assert r.matches(symbol="btc") is True  # Case insensitive

    def test_rule_matches_inactive(self):
        from llm.graduated_rules import GraduatedRule
        r = GraduatedRule(active=False, conditions={"symbol": "BTC"})
        assert r.matches(symbol="BTC") is False

    # ── Singleton ──

    def test_singleton(self):
        from llm.graduated_rules import get_graduated_rules_engine
        e1 = get_graduated_rules_engine()
        e2 = get_graduated_rules_engine()
        assert e1 is e2

    # ── Persistence ──

    def test_save_and_load(self, tmp_path):
        import llm.graduated_rules as gr_mod
        old_file = gr_mod._RULES_FILE
        try:
            gr_mod._RULES_FILE = str(tmp_path / "rules.json")

            engine = gr_mod.GraduatedRulesEngine()
            engine._loaded = True
            h = MockHypothesis("BTC performs strongly in trend regime")
            engine.graduate_hypothesis(h)

            # Load in new engine
            engine2 = gr_mod.GraduatedRulesEngine()
            engine2._ensure_loaded()
            assert len(engine2._rules) == 1
            assert engine2._rules[0].action == "boost"
        finally:
            gr_mod._RULES_FILE = old_file


# ══════════════════════════════════════════════════════════════
# INTEGRATION TESTS
# ══════════════════════════════════════════════════════════════

class TestIntegration:
    """Integration tests for the quant backbone + ensemble + coordinator wiring."""

    def test_imports(self):
        from llm.quant_data import get_quant_provider, QuantDataProvider
        from llm.graduated_rules import get_graduated_rules_engine, GraduatedRulesEngine, GraduatedRule
        assert QuantDataProvider is not None
        assert GraduatedRulesEngine is not None
        assert GraduatedRule is not None

    def test_strategy_maps_complete(self):
        """All 11 strategies should be in ensemble duration and timeframe maps."""
        from strategies.ensemble import EnsembleStrategy
        duration_map = EnsembleStrategy.STRATEGY_DURATION_MAP
        timeframe_map = EnsembleStrategy.STRATEGY_TIMEFRAME
        expected = [
            "regime_trend", "monte_carlo_zones", "confidence_scorer", "multi_tier_quality",
            "bollinger_squeeze", "funding_rate", "lead_lag", "liquidation_cascade",
            "oi_delta", "probability_engine", "vmc_cipher",
        ]
        for strat in expected:
            assert strat in duration_map, f"{strat} missing from STRATEGY_DURATION_MAP"
            assert strat in timeframe_map, f"{strat} missing from STRATEGY_TIMEFRAME"

    def test_regime_fallback_coordinator(self):
        """The coordinator should have a regime fallback method."""
        from llm.agents.coordinator import AgentCoordinator
        coord = AgentCoordinator.__new__(AgentCoordinator)
        assert hasattr(coord, "_compute_regime_fallback")

        # Test with empty snapshot
        result = coord._compute_regime_fallback({})
        assert result == "consolidation"

        # Test with trending market data
        result = coord._compute_regime_fallback({
            "m": [{"pct_24h": 5.0, "vol_ratio": 2.5}]
        })
        assert result in ("trend", "high_volatility")

        # Test with panicky market
        result = coord._compute_regime_fallback({
            "m": [{"pct_24h": -7.0}, {"pct_24h": -8.0}, {"pct_24h": -6.0}]
        })
        assert result == "panic"

        # Test with ranging market
        result = coord._compute_regime_fallback({
            "m": [{"pct_24h": 0.3}, {"pct_24h": -0.2}]
        })
        assert result == "range"
