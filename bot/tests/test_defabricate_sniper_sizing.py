"""
Tests for RIP-OUT PHASE 1 items #2 + #3: DEFABRICATE_SNIPER_SIZING.

A verification swarm found two fabricated tables driving the manual sniper
(LIVE — MANUAL_SNIPER defaults ON):

  #2 SIZING PRIORS — execution/sizing_optimizer.py `_DEFAULT_PRIORS` (e.g.
     HYPE_BUY prior (0.52, 1.34)) + the `dip_mult` 1.15x leverage boost in
     `dynamic_leverage()`. The "real data will override these quickly" comment
     is false: `record_trade_outcome` (manual/sniper_filter.py) has ZERO
     production callers, so `SizingOptimizer._setup_stats` never accumulates
     real trades and the fabricated priors run on EVERY non-conviction sniper
     call forever. Audited live HYPE_BUY WR is ~22-23%, not 52%.

  #3 ELITE SETUP LABELS — manual/sniper_filter.py `positive_ev_setups` (the
     "proven +EV" grade table) + the `_detect_dip_buy` tier boost it gates +
     manual/signal_scorer.py's dip-buy score bonus. These label the ledger's
     worst slice as "elite/proven +EV 88.5% WR" to the human.

This module characterizes the flag-OFF (default) behavior as unchanged from
the pre-existing fabricated tables, and verifies the flag-ON living-values
replacement: query feedback/live_edge for live (symbol, side) ledger evidence
(n>=13) — sizing uses live win-rate/payoff (falling back to the single
documented neutral prior below n=13, never a fabricated per-setup value),
and labels are only "proven" (A/B) if the ledger itself says so (else
"unproven") — always shadow-logging the counterfactual
("[DEFAB-SNIPER-SIZE]" / "[DEFAB-SNIPER-LABEL]").

All ledger access is mocked via feedback.live_edge — these tests never read
or write real ledger data.
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from feedback import live_edge
from execution.sizing_optimizer import SizingOptimizer, _DEFAULT_PRIORS, _DEFAULT_PRIOR
from manual import signal_scorer
from manual.config import ManualSniperConfig
from manual.sniper_filter import ManualSniperFilter, _FABRICATED_POSITIVE_EV_SETUPS
from manual.trade_scorecard import ScorecardResult


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

@dataclass
class MockSignal:
    """Minimal strategies.base.Signal stub (mirrors tests/test_manual_sniper.py)."""
    strategy: str = "regime_trend"
    symbol: str = "HYPE"
    side: str = "BUY"
    confidence: float = 82.0
    entry: float = 30.0
    sl: float = 29.0
    tp1: float = 32.0
    tp2: float = 34.0
    atr: float = 0.3
    metadata: Dict[str, Any] = field(default_factory=dict)
    signal_context: str = ""

    @property
    def is_valid(self):
        return True


def _hype_buy_dip_signal() -> MockSignal:
    """A HYPE_BUY signal in a dip-buy consolidation regime — the fabricated
    "elite" path (grade A, 88.5% WR dip bonus, tier-boost eligible)."""
    return MockSignal(metadata={
        "rsi": 50.0,
        "num_agree": 3,
        "strategies_agree": ["regime_trend", "monte_carlo_zones", "confidence_scorer"],
        "regime": "consolidation",
        "win_prob": 0.6,
        "chop_score": 0.15,
    })


def _make_sniper_filter() -> ManualSniperFilter:
    """A sniper filter configured so a qualifying HYPE_BUY signal makes it
    all the way through the pipeline. Mirrors the fixture pattern in
    tests/test_defabricate_sol_veto.py."""
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
    monkeypatch.delenv("DEFABRICATE_SNIPER_SIZING", raising=False)
    yield


# ---------------------------------------------------------------------------
# feedback/live_edge.py -- the shared flag + living-values helpers
# ---------------------------------------------------------------------------

class TestLiveEdgeHelpers:
    def test_flag_defaults_off(self):
        assert live_edge.defabricate_sniper_sizing_enabled() is False

    def test_flag_recognizes_truthy_values(self, monkeypatch):
        for v in ("1", "true", "True", "TRUE", "yes"):
            monkeypatch.setenv("DEFABRICATE_SNIPER_SIZING", v)
            assert live_edge.defabricate_sniper_sizing_enabled() is True

    def test_flag_recognizes_falsy_values(self, monkeypatch):
        for v in ("0", "false", "no", ""):
            monkeypatch.setenv("DEFABRICATE_SNIPER_SIZING", v)
            assert live_edge.defabricate_sniper_sizing_enabled() is False

    def test_split_setup_key(self):
        assert live_edge.split_setup_key("HYPE_BUY") == ("HYPE", "BUY")
        assert live_edge.split_setup_key("SOL_SELL") == ("SOL", "SELL")
        assert live_edge.split_setup_key("garbage") == (None, None)
        assert live_edge.split_setup_key("") == (None, None)

    def test_get_side_wr_payoff_delegates_to_get_side_stats(self, monkeypatch):
        monkeypatch.setattr(live_edge, "get_side_stats",
                             lambda s, sd: {"n": 20, "avg_pnl": -3.0, "win_rate": 0.22, "payoff_ratio": 0.9})
        stats = live_edge.get_side_wr_payoff("HYPE", "BUY")
        assert stats == {"n": 20, "avg_pnl": -3.0, "win_rate": 0.22, "payoff_ratio": 0.9}

    def test_living_setup_grade_insufficient_evidence(self, monkeypatch):
        monkeypatch.setattr(live_edge, "get_side_stats", lambda s, sd: None)
        g = live_edge.living_setup_grade("HYPE", "BUY")
        assert g["grade"] == "unproven"
        assert g["reason"] == "insufficient_evidence"
        assert g["n"] == 0

    def test_living_setup_grade_strong_positive(self, monkeypatch):
        monkeypatch.setattr(live_edge, "get_side_stats",
                             lambda s, sd: {"n": 30, "avg_pnl": 5.0, "win_rate": 0.60, "payoff_ratio": 1.5})
        g = live_edge.living_setup_grade("ETH", "SELL")
        assert g["grade"] == "A"
        assert g["reason"] == "live_positive_ev_strong"

    def test_living_setup_grade_marginal_positive(self, monkeypatch):
        monkeypatch.setattr(live_edge, "get_side_stats",
                             lambda s, sd: {"n": 30, "avg_pnl": 2.0, "win_rate": 0.30, "payoff_ratio": 3.0})
        g = live_edge.living_setup_grade("ETH", "SELL")
        assert g["grade"] == "B"
        assert g["reason"] == "live_positive_ev_marginal"

    def test_living_setup_grade_negative_ev_the_hype_buy_case(self, monkeypatch):
        # Audited HYPE_BUY: ~22-23% WR, negative avg PnL -- the OPPOSITE of
        # the fabricated 52% WR / "elite grade A" claim.
        monkeypatch.setattr(live_edge, "get_side_stats",
                             lambda s, sd: {"n": 40, "avg_pnl": -4.5, "win_rate": 0.225, "payoff_ratio": 0.85})
        g = live_edge.living_setup_grade("HYPE", "BUY")
        assert g["grade"] == "F"
        assert g["reason"] == "live_negative_ev"
        assert g["win_rate"] < 0.30


# ---------------------------------------------------------------------------
# 1. execution/sizing_optimizer.py -- #2 sizing priors
# ---------------------------------------------------------------------------

class TestSizingFlagOff:
    """Characterization: flag OFF (default) = fabricated _DEFAULT_PRIORS /
    dip_mult fire exactly as before deploy. Zero live behavior change."""

    def test_kelly_fraction_uses_fabricated_prior(self):
        opt = SizingOptimizer()
        full_kelly, wr, payoff = opt.kelly_fraction("HYPE_BUY")
        fab_wr, fab_payoff = _DEFAULT_PRIORS["HYPE_BUY"]
        assert wr == fab_wr == 0.52
        assert payoff == fab_payoff == 1.34

    def test_dip_mult_boost_applies(self):
        opt = SizingOptimizer()
        lev_with_dip = opt.dynamic_leverage(
            win_rate=0.52, payoff=1.34, confidence=80, num_agree=3,
            regime="trend", is_dip_buy=True, tier_max_leverage=25.0,
        )
        lev_without_dip = opt.dynamic_leverage(
            win_rate=0.52, payoff=1.34, confidence=80, num_agree=3,
            regime="trend", is_dip_buy=False, tier_max_leverage=25.0,
        )
        assert lev_with_dip > lev_without_dip  # fabricated 1.15x boost still applies

    def test_no_defab_shadow_log_when_flag_off(self, caplog):
        opt = SizingOptimizer()
        with caplog.at_level(logging.INFO, logger="bot.execution.sizing_optimizer"):
            opt.kelly_fraction("HYPE_BUY")
            opt.dynamic_leverage(win_rate=0.5, payoff=1.5, confidence=80, num_agree=3,
                                  regime="trend", is_dip_buy=True, tier_max_leverage=25.0)
        assert "DEFAB-SNIPER-SIZE" not in caplog.text


class TestSizingFlagOn:
    """Flag ON: living per-(symbol,side) win-rate/payoff from feedback/live_edge,
    always shadow-logged."""

    def test_hype_buy_sized_down_from_live_22pct_wr(self, monkeypatch, caplog):
        monkeypatch.setenv("DEFABRICATE_SNIPER_SIZING", "true")
        monkeypatch.setattr(
            live_edge, "get_side_wr_payoff",
            lambda symbol, side: {"n": 40, "avg_pnl": -4.5, "win_rate": 0.225, "payoff_ratio": 0.85}
            if (symbol, side) == ("HYPE", "BUY") else None,
        )
        opt = SizingOptimizer()
        with caplog.at_level(logging.INFO, logger="bot.execution.sizing_optimizer"):
            full_kelly, wr, payoff = opt.kelly_fraction("HYPE_BUY")

        fab_wr, fab_payoff = _DEFAULT_PRIORS["HYPE_BUY"]
        assert wr == 0.225
        assert wr < fab_wr  # opposite of fabricated 52% claim
        # Fabricated prior yields a strictly positive Kelly fraction...
        opt2 = SizingOptimizer()
        fab_full_kelly, _, _ = opt2.kelly_fraction("SOL_SELL")  # any fabricated-path setup as reference
        assert fab_full_kelly >= 0.0
        # ...while the audited-toxic live prior yields ZERO (sized DOWN, not up).
        assert full_kelly == 0.0
        assert "[DEFAB-SNIPER-SIZE]" in caplog.text
        assert "setup=HYPE_BUY" in caplog.text
        assert "source=live" in caplog.text

    def test_insufficient_evidence_falls_back_to_neutral_not_fabricated(self, monkeypatch, caplog):
        monkeypatch.setenv("DEFABRICATE_SNIPER_SIZING", "true")
        monkeypatch.setattr(live_edge, "get_side_wr_payoff", lambda symbol, side: None)
        opt = SizingOptimizer()
        with caplog.at_level(logging.INFO, logger="bot.execution.sizing_optimizer"):
            full_kelly, wr, payoff = opt.kelly_fraction("HYPE_BUY")
        assert (wr, payoff) == _DEFAULT_PRIOR
        assert wr != _DEFAULT_PRIORS["HYPE_BUY"][0]  # NOT the fabricated per-setup prior
        assert "source=neutral_insufficient_evidence" in caplog.text

    def test_dip_mult_boost_removed(self, monkeypatch, caplog):
        monkeypatch.setenv("DEFABRICATE_SNIPER_SIZING", "true")
        opt = SizingOptimizer()
        with caplog.at_level(logging.INFO, logger="bot.execution.sizing_optimizer"):
            lev_with_dip = opt.dynamic_leverage(
                win_rate=0.52, payoff=1.34, confidence=80, num_agree=3,
                regime="trend", is_dip_buy=True, tier_max_leverage=25.0,
            )
            lev_without_dip = opt.dynamic_leverage(
                win_rate=0.52, payoff=1.34, confidence=80, num_agree=3,
                regime="trend", is_dip_buy=False, tier_max_leverage=25.0,
            )
        assert lev_with_dip == lev_without_dip  # fabricated boost neutralized
        assert "[DEFAB-SNIPER-SIZE]" in caplog.text
        assert "dip_mult fabricated=1.15 live=1.0" in caplog.text

    def test_risk_caps_and_floors_unchanged(self, monkeypatch):
        """Even with extreme mocked live stats, sizing must stay within the
        SAME hard caps/floors as flag-off -- de-fabrication must never change
        risk bounds."""
        monkeypatch.setenv("DEFABRICATE_SNIPER_SIZING", "true")
        monkeypatch.setattr(
            live_edge, "get_side_wr_payoff",
            lambda symbol, side: {"n": 100, "avg_pnl": 50.0, "win_rate": 0.95, "payoff_ratio": 5.0},
        )
        opt = SizingOptimizer()
        sizing = opt.get_optimal_size(
            setup="HYPE_BUY", equity=1000.0, confidence=90, num_agree=3,
            regime="trending_bull", is_dip_buy=True, stop_width_pct=0.02,
        )
        assert opt.min_risk_pct <= sizing.risk_pct <= opt.max_risk_pct
        assert sizing.leverage <= opt._leverage_cap
        assert sizing.kelly_full <= opt._kelly_cap
        assert sizing.risk_amount <= 1000.0 * opt.max_single_loss_pct + 1e-6


# ---------------------------------------------------------------------------
# 2. manual/sniper_filter.py -- #3 elite labels (positive_ev_setups)
# ---------------------------------------------------------------------------

class TestSniperLabelFlagOff:
    """Characterization: flag OFF (default) = fabricated positive_ev_setups
    table + dip-buy tier boost fire exactly as before deploy."""

    def test_fabricated_table_unchanged(self):
        assert _FABRICATED_POSITIVE_EV_SETUPS["HYPE_BUY"]["grade"] == "A"
        assert _FABRICATED_POSITIVE_EV_SETUPS["HYPE_BUY"]["max_chop"] == 0.55

    def test_hype_buy_dip_gets_tier_boost_and_passes(self):
        filt = _make_sniper_filter()
        sig = _hype_buy_dip_signal()
        result = filt.evaluate(sig)
        assert result is not None
        assert result.tier in ("PREMIUM", "SNIPER")  # boosted from STANDARD by dip-buy
        assert result.is_dip_buy is True

    def test_no_defab_label_shadow_log_when_flag_off(self, caplog):
        filt = _make_sniper_filter()
        sig = _hype_buy_dip_signal()
        with caplog.at_level(logging.INFO, logger="bot.manual.sniper"):
            filt.evaluate(sig)
        assert "DEFAB-SNIPER-LABEL" not in caplog.text


class TestSniperLabelFlagOn:
    """Flag ON: living_setup_grade() from feedback/live_edge decides "proven",
    always shadow-logged."""

    def test_living_positive_ev_setups_drops_unproven_hype_buy(self, monkeypatch, caplog):
        monkeypatch.setenv("DEFABRICATE_SNIPER_SIZING", "true")
        monkeypatch.setattr(
            live_edge, "living_setup_grade",
            lambda symbol, side: {"grade": "F", "n": 40, "win_rate": 0.225,
                                   "avg_pnl": -4.5, "reason": "live_negative_ev"},
        )
        filt = _make_sniper_filter()
        with caplog.at_level(logging.INFO, logger="bot.manual.sniper"):
            result = filt._living_positive_ev_setups("HYPE_BUY")
        assert result == {}  # NOT labeled elite -- opposite of fabricated grade A
        assert "[DEFAB-SNIPER-LABEL]" in caplog.text
        assert "fabricated_grade=A" in caplog.text
        assert "live_grade=F" in caplog.text

    def test_living_positive_ev_setups_keeps_a_grade_when_ledger_agrees(self, monkeypatch, caplog):
        monkeypatch.setenv("DEFABRICATE_SNIPER_SIZING", "true")
        monkeypatch.setattr(
            live_edge, "living_setup_grade",
            lambda symbol, side: {"grade": "A", "n": 30, "win_rate": 0.60,
                                   "avg_pnl": 8.0, "reason": "live_positive_ev_strong"},
        )
        filt = _make_sniper_filter()
        result = filt._living_positive_ev_setups("ETH_BUY")
        assert "ETH_BUY" in result
        assert result["ETH_BUY"]["grade"] == "A"
        assert result["ETH_BUY"]["max_chop"] == _FABRICATED_POSITIVE_EV_SETUPS["ETH_BUY"]["max_chop"]

    def test_living_positive_ev_setups_new_setup_gets_neutral_max_chop(self, monkeypatch):
        """A setup with NO fabricated entry at all still earns living A/B
        status if the ledger proves it, using the codebase's existing
        neutral max_chop default (0.5) rather than inventing a new one."""
        monkeypatch.setenv("DEFABRICATE_SNIPER_SIZING", "true")
        monkeypatch.setattr(
            live_edge, "living_setup_grade",
            lambda symbol, side: {"grade": "B", "n": 15, "win_rate": 0.40,
                                   "avg_pnl": 1.5, "reason": "live_positive_ev_marginal"},
        )
        filt = _make_sniper_filter()
        result = filt._living_positive_ev_setups("DOGE_SELL")
        assert result["DOGE_SELL"]["max_chop"] == 0.5

    def test_hype_buy_dip_no_longer_boosted_when_ledger_disagrees(self, monkeypatch, caplog):
        monkeypatch.setenv("DEFABRICATE_SNIPER_SIZING", "true")
        monkeypatch.setattr(
            live_edge, "living_setup_grade",
            lambda symbol, side: {"grade": "F", "n": 40, "win_rate": 0.225,
                                   "avg_pnl": -4.5, "reason": "live_negative_ev"}
            if symbol == "HYPE" else {"grade": "unproven", "n": 0, "win_rate": None,
                                       "avg_pnl": None, "reason": "insufficient_evidence"},
        )
        filt = _make_sniper_filter()
        sig = _hype_buy_dip_signal()
        with caplog.at_level(logging.INFO, logger="bot.manual.sniper"):
            result = filt.evaluate(sig)
        # setup is no longer "proven" -> falls to the discovery/confidence path
        # (still may pass on confidence/agree merits, but MUST NOT get the
        # free proven-setup tier boost or the fabricated grade).
        if result is not None:
            assert result.tier not in ("SNIPER",) or result.quality_score < 100
        assert "[DEFAB-SNIPER-LABEL]" in caplog.text
        assert "live_grade=F" in caplog.text

    def test_insufficient_evidence_labels_unproven(self, monkeypatch, caplog):
        monkeypatch.setenv("DEFABRICATE_SNIPER_SIZING", "true")
        monkeypatch.setattr(
            live_edge, "living_setup_grade",
            lambda symbol, side: {"grade": "unproven", "n": 4, "win_rate": None,
                                   "avg_pnl": None, "reason": "insufficient_evidence"},
        )
        filt = _make_sniper_filter()
        with caplog.at_level(logging.INFO, logger="bot.manual.sniper"):
            result = filt._living_positive_ev_setups("HYPE_BUY")
        assert result == {}
        assert "live_grade=unproven" in caplog.text
        assert "reason=insufficient_evidence" in caplog.text


# ---------------------------------------------------------------------------
# 3. manual/signal_scorer.py -- dip-buy score bonus (line ~88)
# ---------------------------------------------------------------------------

_SCORE_KWARGS = dict(
    symbol="HYPE", side="BUY", confidence=80.0, num_agree=3,
    chop=0.2, ev_per_dollar=0.3, regime="consolidation", is_dip_buy=True,
)


class TestSignalScorerFlagOff:
    def test_dip_bonus_awarded_unconditionally(self):
        result = signal_scorer.score_signal(**_SCORE_KWARGS)
        assert result["factors"].get("dip_buy") == 15

    def test_no_defab_shadow_log(self, caplog):
        with caplog.at_level(logging.INFO, logger="bot.manual.signal_scorer"):
            signal_scorer.score_signal(**_SCORE_KWARGS)
        assert "DEFAB-SNIPER-LABEL" not in caplog.text


class TestSignalScorerFlagOn:
    def test_dip_bonus_withheld_for_unproven_setup(self, monkeypatch, caplog):
        monkeypatch.setenv("DEFABRICATE_SNIPER_SIZING", "true")
        monkeypatch.setattr(
            live_edge, "living_setup_grade",
            lambda symbol, side: {"grade": "F", "n": 40, "win_rate": 0.225,
                                   "avg_pnl": -4.5, "reason": "live_negative_ev"},
        )
        with caplog.at_level(logging.INFO, logger="bot.manual.signal_scorer"):
            result = signal_scorer.score_signal(**_SCORE_KWARGS)
        assert "dip_buy" not in result["factors"]
        assert "[DEFAB-SNIPER-LABEL]" in caplog.text
        assert "live_pts=0" in caplog.text

    def test_dip_bonus_awarded_when_ledger_agrees(self, monkeypatch, caplog):
        monkeypatch.setenv("DEFABRICATE_SNIPER_SIZING", "true")
        monkeypatch.setattr(
            live_edge, "living_setup_grade",
            lambda symbol, side: {"grade": "A", "n": 30, "win_rate": 0.60,
                                   "avg_pnl": 8.0, "reason": "live_positive_ev_strong"},
        )
        with caplog.at_level(logging.INFO, logger="bot.manual.signal_scorer"):
            result = signal_scorer.score_signal(**_SCORE_KWARGS)
        assert result["factors"].get("dip_buy") == 15
        assert "[DEFAB-SNIPER-LABEL]" in caplog.text
        assert "live_pts=15" in caplog.text
