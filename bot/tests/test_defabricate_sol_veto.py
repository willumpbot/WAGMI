"""
Tests for RIP-OUT PHASE 1: DEFABRICATE_SOL_VETO.

A verification swarm found fabricated SOL_BUY RSI<20 hard vetoes (justified
by a frozen "0% up at 6h" backtest stat that was never corroborated against
live trade outcomes) blocking live signals in three places:

  1. manual/sniper_filter.py ManualSniperFilter.evaluate()   -- LIVE sniper path
  2. llm/quant_brain.py QuantBrain._run_critic() veto        -- dormant (QB off live)
     llm/quant_brain.py QuantBrain.generate_signals() Setup3 -- dormant (QB off live)
  3. core/position_wiring.py PositionWiringMixin._on_solo_signal_for_sniper()
     -- no independent veto logic; just a hard-return on QuantBrain's action.
     Its shadow-log is exercised directly at that call site for traceability.

This module characterizes the flag-OFF (default) behavior as byte-identical
to the pre-existing fabricated veto, and verifies the flag-ON living-values
replacement: query feedback/live_edge for live (symbol, side) ledger evidence
(n>=13), veto only if genuinely toxic (avg net PnL < 0), otherwise let the
signal proceed -- always shadow-logging the counterfactual (old fabricated
decision vs new living decision) tagged "[DEFAB-SOL-VETO]".

All ledger access is mocked via feedback.live_edge -- these tests never read
or write real ledger data.
"""
import logging
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from feedback import live_edge
from manual.config import ManualSniperConfig
from manual.sniper_filter import ManualSniperFilter
from manual.trade_scorecard import ScorecardResult


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

@dataclass
class MockSignal:
    """Minimal strategies.base.Signal stub (mirrors tests/test_manual_sniper.py)."""
    strategy: str = "regime_trend"
    symbol: str = "SOL"
    side: str = "BUY"
    confidence: float = 72.0
    entry: float = 100.0
    sl: float = 97.0
    tp1: float = 106.0
    tp2: float = 112.0
    atr: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    signal_context: str = ""

    @property
    def is_valid(self):
        return True


def _sol_buy_signal(rsi_val: float = 15.0) -> MockSignal:
    """A SOL_BUY signal in the 70-75% confidence discovery band, RSI<20."""
    return MockSignal(metadata={
        "rsi": rsi_val,
        "num_agree": 2,
        "strategies_agree": ["regime_trend", "monte_carlo_zones"],
        "regime": "trend",
        "win_prob": 0.6,
        "chop_score": 0.2,
    })


def _make_sniper_filter() -> ManualSniperFilter:
    """A sniper filter configured so a qualifying SOL_BUY signal makes it all
    the way through the pipeline (i.e. `evaluate()` returning None can ONLY
    be attributed to the RSI death-trap gate under test, not some unrelated
    gate). The real TradeScorecard has a time-of-day component that would
    make pass/fail flaky across CI runs, so it's mocked to a deterministic
    pass -- we're characterizing the RSI-gate/veto logic, not the scorecard.
    """
    config = ManualSniperConfig()
    config.mode = "standard"          # sidesteps the aggressive-mode STANDARD-tier skip
    config.min_confidence = 60.0
    config.min_num_agree = 1
    config.min_rr = 1.0
    config.expanded_setups = False
    config.micro_sniper_enabled = False
    config.compound_sizing = False
    config.equity = 1000.0
    f = ManualSniperFilter(config)
    f._running_equity = 1000.0
    f._reflection_engine = None
    f._sizing_optimizer = None
    f._scorecard.score = MagicMock(return_value=ScorecardResult(
        total_score=100, passed=True, size_factor=1.0,
        components={}, max_components={}, reason="mocked pass",
    ))
    return f


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Flag defaults to unset/false and never leaks between tests."""
    monkeypatch.delenv("DEFABRICATE_SOL_VETO", raising=False)
    yield


# ---------------------------------------------------------------------------
# feedback/live_edge.py -- the shared flag + living-values gate helpers
# ---------------------------------------------------------------------------

class TestLiveEdgeHelpers:
    def test_flag_defaults_off(self):
        assert live_edge.defabricate_sol_veto_enabled() is False

    def test_flag_recognizes_truthy_values(self, monkeypatch):
        for v in ("1", "true", "True", "TRUE", "yes"):
            monkeypatch.setenv("DEFABRICATE_SOL_VETO", v)
            assert live_edge.defabricate_sol_veto_enabled() is True

    def test_flag_recognizes_falsy_values(self, monkeypatch):
        for v in ("0", "false", "no", ""):
            monkeypatch.setenv("DEFABRICATE_SOL_VETO", v)
            assert live_edge.defabricate_sol_veto_enabled() is False

    def test_living_veto_decision_insufficient_evidence(self, monkeypatch):
        monkeypatch.setattr(live_edge, "get_side_stats", lambda s, sd: None)
        d = live_edge.living_veto_decision("SOL", "BUY")
        assert d == {"veto": False, "n": 0, "avg_pnl": None, "reason": "insufficient_evidence"}

    def test_living_veto_decision_toxic_confirmed(self, monkeypatch):
        monkeypatch.setattr(live_edge, "get_side_stats",
                             lambda s, sd: {"n": 20, "avg_pnl": -8.5})
        d = live_edge.living_veto_decision("SOL", "BUY")
        assert d["veto"] is True
        assert d["reason"] == "toxic_confirmed"
        assert d["n"] == 20

    def test_living_veto_decision_neutral_or_positive(self, monkeypatch):
        monkeypatch.setattr(live_edge, "get_side_stats",
                             lambda s, sd: {"n": 20, "avg_pnl": 3.2})
        d = live_edge.living_veto_decision("SOL", "BUY")
        assert d["veto"] is False
        assert d["reason"] == "neutral_or_positive"


# ---------------------------------------------------------------------------
# 1. manual/sniper_filter.py -- the LIVE sniper path
# ---------------------------------------------------------------------------

class TestSniperFilterFlagOff:
    """Characterization: flag OFF (default) = fabricated veto fires exactly
    as before deploy. Zero live behavior change."""

    def test_fabricated_veto_still_fires(self):
        filt = _make_sniper_filter()
        sig = _sol_buy_signal(rsi_val=15.0)
        result = filt.evaluate(sig)
        assert result is None
        assert filt.get_rejection_stats().get("sol_rsi_death_trap_15") == 1

    def test_no_defab_shadow_log_when_flag_off(self):
        filt = _make_sniper_filter()
        sig = _sol_buy_signal(rsi_val=15.0)
        filt.evaluate(sig)
        assert not any("DEFAB-SOL-VETO" in r for r in filt.get_rejection_stats())


class TestSniperFilterFlagOn:
    """Flag ON: living-values gate from feedback/live_edge, always shadow-logged."""

    def test_toxic_confirmed_n_ge_13_still_vetoes(self, monkeypatch):
        monkeypatch.setenv("DEFABRICATE_SOL_VETO", "true")
        monkeypatch.setattr(
            live_edge, "living_veto_decision",
            lambda symbol, side: {"veto": True, "n": 20, "avg_pnl": -8.5, "reason": "toxic_confirmed"},
        )
        filt = _make_sniper_filter()
        sig = _sol_buy_signal(rsi_val=15.0)
        result = filt.evaluate(sig)
        assert result is None  # living data confirms toxicity -> veto still applies
        reasons = filt.get_rejection_stats()
        assert any(
            "[DEFAB-SOL-VETO]" in r and "living_veto=True" in r and "n=20" in r
            for r in reasons
        )

    def test_insufficient_evidence_n_lt_13_does_not_veto(self, monkeypatch):
        monkeypatch.setenv("DEFABRICATE_SOL_VETO", "true")
        monkeypatch.setattr(
            live_edge, "living_veto_decision",
            lambda symbol, side: {"veto": False, "n": 4, "avg_pnl": None, "reason": "insufficient_evidence"},
        )
        filt = _make_sniper_filter()
        sig = _sol_buy_signal(rsi_val=15.0)
        result = filt.evaluate(sig)
        assert result is not None  # NOT vetoed -- signal proceeds (epsilon-preserving)
        assert result.symbol == "SOL"
        assert result.side == "BUY"
        reasons = filt.get_rejection_stats()
        assert any(
            "[DEFAB-SOL-VETO]" in r and "old_would_veto=True" in r and "living_veto=False" in r
            for r in reasons
        )

    def test_neutral_or_positive_edge_does_not_veto(self, monkeypatch):
        monkeypatch.setenv("DEFABRICATE_SOL_VETO", "true")
        monkeypatch.setattr(
            live_edge, "living_veto_decision",
            lambda symbol, side: {"veto": False, "n": 30, "avg_pnl": 4.1, "reason": "neutral_or_positive"},
        )
        filt = _make_sniper_filter()
        sig = _sol_buy_signal(rsi_val=15.0)
        result = filt.evaluate(sig)
        assert result is not None
        reasons = filt.get_rejection_stats()
        assert any(
            "[DEFAB-SOL-VETO]" in r and "reason=neutral_or_positive" in r and "living_veto=False" in r
            for r in reasons
        )


# ---------------------------------------------------------------------------
# 2. llm/quant_brain.py -- dormant copies (QuantBrain is off live), kept
#    consistent with the live sniper copy.
# ---------------------------------------------------------------------------

def _qb_pieces(rsi_val: float):
    from llm.quant_brain import RegimeClassification, SizingRecommendation, TradeThesis
    sig = _sol_buy_signal(rsi_val=rsi_val)
    merged = {"rsi": rsi_val}
    regime = RegimeClassification(
        regime="trend", sub_regime="trend", confidence=0.7,
        bias="neutral", factors=[], risk_multiplier=1.0,
    )
    thesis = TradeThesis(
        action="strong_entry", setup_key="SOL_BUY", edge_source="test",
        win_prob=0.6, confluence_score=5, reasoning="test",
    )
    sizing = SizingRecommendation(
        tier="PREMIUM", risk_multiplier=1.0, max_leverage=10.0, rationale="test",
    )
    return sig, merged, regime, thesis, sizing


class TestQuantBrainCriticFlagOff:
    def test_fabricated_veto_still_fires(self):
        from llm.quant_brain import QuantBrain
        brain = QuantBrain()
        sig, merged, regime, thesis, sizing = _qb_pieces(15.0)
        critic = brain._run_critic(sig, merged, regime, thesis, sizing)
        assert critic.verdict == "veto"
        assert any("death trap" in r for r in critic.veto_reasons)
        assert critic.confidence_adj == 0.0


class TestQuantBrainCriticFlagOn:
    def test_toxic_confirmed_still_vetoes(self, monkeypatch):
        monkeypatch.setenv("DEFABRICATE_SOL_VETO", "true")
        monkeypatch.setattr(
            live_edge, "living_veto_decision",
            lambda symbol, side: {"veto": True, "n": 15, "avg_pnl": -6.0, "reason": "toxic_confirmed"},
        )
        from llm.quant_brain import QuantBrain
        brain = QuantBrain()
        sig, merged, regime, thesis, sizing = _qb_pieces(15.0)
        critic = brain._run_critic(sig, merged, regime, thesis, sizing)
        assert critic.verdict == "veto"
        assert any("[DEFAB-SOL-VETO]" in r and "living_veto=True" in r for r in critic.veto_reasons)

    def test_insufficient_evidence_does_not_veto(self, monkeypatch):
        monkeypatch.setenv("DEFABRICATE_SOL_VETO", "true")
        monkeypatch.setattr(
            live_edge, "living_veto_decision",
            lambda symbol, side: {"veto": False, "n": 6, "avg_pnl": None, "reason": "insufficient_evidence"},
        )
        from llm.quant_brain import QuantBrain
        brain = QuantBrain()
        sig, merged, regime, thesis, sizing = _qb_pieces(15.0)
        critic = brain._run_critic(sig, merged, regime, thesis, sizing)
        assert critic.verdict != "veto"
        assert not any("death trap" in r for r in critic.veto_reasons)
        assert any("[DEFAB-SOL-VETO]" in w and "living_veto=False" in w for w in critic.warnings)

    def test_neutral_or_positive_does_not_veto(self, monkeypatch):
        monkeypatch.setenv("DEFABRICATE_SOL_VETO", "true")
        monkeypatch.setattr(
            live_edge, "living_veto_decision",
            lambda symbol, side: {"veto": False, "n": 25, "avg_pnl": 2.5, "reason": "neutral_or_positive"},
        )
        from llm.quant_brain import QuantBrain
        brain = QuantBrain()
        sig, merged, regime, thesis, sizing = _qb_pieces(15.0)
        critic = brain._run_critic(sig, merged, regime, thesis, sizing)
        assert critic.verdict != "veto"
        assert any("[DEFAB-SOL-VETO]" in w and "reason=neutral_or_positive" in w for w in critic.warnings)


class TestQuantBrainSetup3FlagOff:
    def test_blanket_sol_exclusion_unchanged(self):
        from llm.quant_brain import QuantBrain
        brain = QuantBrain()
        assert brain._sol_oversold_setup_blocked(15.0) is True


class TestQuantBrainSetup3FlagOn:
    def test_blocks_when_living_data_confirms_toxic(self, monkeypatch):
        monkeypatch.setenv("DEFABRICATE_SOL_VETO", "true")
        monkeypatch.setattr(
            live_edge, "living_veto_decision",
            lambda symbol, side: {"veto": True, "n": 20, "avg_pnl": -8.0, "reason": "toxic_confirmed"},
        )
        from llm.quant_brain import QuantBrain
        brain = QuantBrain()
        assert brain._sol_oversold_setup_blocked(15.0) is True

    def test_allows_when_insufficient_evidence(self, monkeypatch):
        monkeypatch.setenv("DEFABRICATE_SOL_VETO", "true")
        monkeypatch.setattr(
            live_edge, "living_veto_decision",
            lambda symbol, side: {"veto": False, "n": 5, "avg_pnl": None, "reason": "insufficient_evidence"},
        )
        from llm.quant_brain import QuantBrain
        brain = QuantBrain()
        assert brain._sol_oversold_setup_blocked(15.0) is False


# ---------------------------------------------------------------------------
# 3. core/position_wiring.py -- observability at the QB call site (no
#    independent veto logic; the hard-return already respects the flag
#    transparently because QuantBrain's own decision is flag-gated upstream).
# ---------------------------------------------------------------------------

class TestPositionWiringObservability:
    def test_shadow_log_fires_when_qb_veto_is_defab_tagged(self, caplog):
        from core.position_wiring import PositionWiringMixin
        fake_decision = SimpleNamespace(
            action="veto",
            critic_verdict=SimpleNamespace(veto_reasons=[
                "[DEFAB-SOL-VETO] rsi=15 old_would_veto=True n=20 "
                "avg_pnl=-8.0 reason=toxic_confirmed living_veto=True"
            ]),
        )
        fake_self = SimpleNamespace(
            _manual_sniper=object(),
            _quant_brain=SimpleNamespace(evaluate_signal=lambda signal: fake_decision),
        )
        sig = _sol_buy_signal(rsi_val=15.0)
        with caplog.at_level(logging.INFO, logger="bot.main"):
            PositionWiringMixin._on_solo_signal_for_sniper(fake_self, sig)
        assert "[DEFAB-SOL-VETO][position_wiring]" in caplog.text

    def test_no_shadow_log_for_unrelated_qb_veto(self, caplog):
        from core.position_wiring import PositionWiringMixin
        fake_decision = SimpleNamespace(
            action="veto",
            critic_verdict=SimpleNamespace(veto_reasons=["some unrelated veto reason"]),
        )
        fake_self = SimpleNamespace(
            _manual_sniper=object(),
            _quant_brain=SimpleNamespace(evaluate_signal=lambda signal: fake_decision),
        )
        sig = _sol_buy_signal(rsi_val=50.0)
        with caplog.at_level(logging.INFO, logger="bot.main"):
            PositionWiringMixin._on_solo_signal_for_sniper(fake_self, sig)
        assert "[DEFAB-SOL-VETO]" not in caplog.text
