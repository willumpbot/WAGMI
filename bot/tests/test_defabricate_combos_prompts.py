"""
Tests for RIP-OUT PHASE 1 items #4 + #6:
DEFABRICATE_LOSING_COMBOS + DEFABRICATE_PROMPT_PHANTOMS.

#4 ENSEMBLE LOSING-COMBOS SEED -- strategies/ensemble.py `_LOSING_COMBOS_SEED`
(two frozensets seeded at n=0, e.g. {regime_trend, vmc_cipher} "PF 0.39,
29% WR" -- a pre-live-data guess never corroborated) is unconditionally
injected into the live combo-blocklist whenever a seed combo hasn't reached
n>=13 ledger evidence. This is a LIVE ensemble block (main pipeline, not
QuantBrain-gated): a fabricated seed of "losing combos" hard-blocks (returns
None -- zero trade) any signal group containing it as a strict subset, with
zero live evidence behind the block.

This module characterizes the flag-OFF (default) behavior as unchanged
(seed injected, seed-only matches blocked), and verifies the flag-ON
replacement: the n<13 seed fallback is no longer injected into the live
blocklist (`_get_live_losing_combos()`); a seed-only match at the call site
in `_weighted_veto()` is shadow-logged ("[DEFAB-LOSING-COMBOS] ...
acting=proceed") and the signal proceeds instead of being hard-blocked. A
combo that HAS graduated to n>=13 live-toxic ledger evidence still blocks,
flag or no flag.

#6 PROMPT PHANTOM FIELDS -- llm/agents/prompts.py bullets in TRADE_AGENT_
PROMPT / RISK_AGENT_PROMPT / CRITIC_AGENT_PROMPT reference enriched-context
fields/sections that NO generator ever emits into the multi-agent pipeline's
snapshot (verified against llm/agents/comprehensive_snapshot.py and
llm/agents/dynamic_stats.py): `signals.validated_edges` (source table
`_AGENT_SHADOW_EDGES` emptied to {} 2026-06-05 -- can NEVER be present),
`noise_floor_pct`, `min_ev_per_dollar`/`break_even_wr`, the "SIZING STATS"
block, and the "CONFLUENCE CALIBRATION (live)" section name. Telling the LLM
to "use" a field/section that never appears is hallucination bait.

This module characterizes flag-OFF (default) as the unchanged fabricated
prompt text, and verifies flag-ON: the phantom bullets are reworded to state
the operative fallback constant honestly (no phantom field/section name
left in the text) and the `validated_edges` bullets are deleted outright.

All ledger access is mocked via feedback.live_edge / strategies.ensemble's
module-level `_load_combo_stats` -- these tests never read or write real
ledger data. Prompt tests reload llm.agents.prompts with monkeypatched env
(mirrors the existing THESIS_CHECKLIST_ENABLED import-time flag pattern
already used in that module) -- no ledger/network access at all.
"""
import importlib
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

import strategies.ensemble as ensemble_mod
from feedback import live_edge
from strategies.ensemble import EnsembleStrategy


# ---------------------------------------------------------------------------
# Shared fixtures / helpers (#4)
# ---------------------------------------------------------------------------

@dataclass
class MockSignal:
    """Minimal strategies.base.Signal stub (mirrors tests/test_defabricate_sol_veto.py)."""
    strategy: str = "regime_trend"
    symbol: str = "BTC"
    side: str = "BUY"
    confidence: float = 80.0
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


def _make_ensemble(strategy_names: Optional[List[str]] = None) -> EnsembleStrategy:
    names = strategy_names or ["regime_trend", "vmc_cipher", "confidence_scorer", "probability_engine"]
    fake_strategies = [SimpleNamespace(name=n) for n in names]
    return EnsembleStrategy(strategies=fake_strategies, mode="weighted_veto", min_votes=2)


def _signals(symbol: str, side: str, strategy_names: List[str], confidence: float = 80.0) -> List[MockSignal]:
    return [MockSignal(strategy=n, symbol=symbol, side=side, confidence=confidence) for n in strategy_names]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Flags default to unset/false and never leak between tests."""
    monkeypatch.delenv("DEFABRICATE_LOSING_COMBOS", raising=False)
    monkeypatch.delenv("DEFABRICATE_PROMPT_PHANTOMS", raising=False)
    yield


# ---------------------------------------------------------------------------
# feedback/live_edge.py -- the flag reader
# ---------------------------------------------------------------------------

class TestLiveEdgeFlag:
    def test_flag_defaults_off(self):
        assert live_edge.defabricate_losing_combos_enabled() is False

    def test_flag_recognizes_truthy_values(self, monkeypatch):
        for v in ("1", "true", "True", "TRUE", "yes"):
            monkeypatch.setenv("DEFABRICATE_LOSING_COMBOS", v)
            assert live_edge.defabricate_losing_combos_enabled() is True

    def test_flag_recognizes_falsy_values(self, monkeypatch):
        for v in ("0", "false", "no", ""):
            monkeypatch.setenv("DEFABRICATE_LOSING_COMBOS", v)
            assert live_edge.defabricate_losing_combos_enabled() is False


# ---------------------------------------------------------------------------
# 1. _get_live_losing_combos() -- seed injection gating
# ---------------------------------------------------------------------------

class TestGetLiveLosingCombosFlagOff:
    """Characterization: flag OFF (default) = fabricated seed injected
    exactly as before, for any seed combo with n<13."""

    def test_seed_injected_when_stats_empty(self, monkeypatch):
        ens = _make_ensemble()
        monkeypatch.setattr(ensemble_mod, "_load_combo_stats", lambda: {})
        combos = ens._get_live_losing_combos()
        assert ens._LOSING_COMBOS_SEED <= combos

    def test_seed_injected_when_seed_has_n_lt_13(self, monkeypatch):
        ens = _make_ensemble()
        seed = frozenset({"regime_trend", "vmc_cipher"})
        monkeypatch.setattr(ensemble_mod, "_load_combo_stats", lambda: {seed: (5, 0.2, -3.0)})
        combos = ens._get_live_losing_combos()
        assert seed in combos


class TestGetLiveLosingCombosFlagOn:
    """Flag ON: fabricated seed fallback is NOT injected below n>=13; a
    seed combo that HAS graduated to n>=13 live-toxic evidence still blocks
    (via the live_toxic path, unconditional on the flag)."""

    def test_seed_not_injected_when_stats_empty(self, monkeypatch):
        monkeypatch.setenv("DEFABRICATE_LOSING_COMBOS", "true")
        ens = _make_ensemble()
        monkeypatch.setattr(ensemble_mod, "_load_combo_stats", lambda: {})
        combos = ens._get_live_losing_combos()
        assert combos == set()

    def test_seed_not_injected_when_seed_has_n_lt_13(self, monkeypatch):
        monkeypatch.setenv("DEFABRICATE_LOSING_COMBOS", "true")
        ens = _make_ensemble()
        seed = frozenset({"regime_trend", "vmc_cipher"})
        monkeypatch.setattr(ensemble_mod, "_load_combo_stats", lambda: {seed: (5, 0.2, -3.0)})
        combos = ens._get_live_losing_combos()
        assert seed not in combos
        assert combos == set()

    def test_seed_combo_that_graduated_to_live_toxic_still_blocks(self, monkeypatch):
        monkeypatch.setenv("DEFABRICATE_LOSING_COMBOS", "true")
        ens = _make_ensemble()
        seed = frozenset({"regime_trend", "vmc_cipher"})
        # n>=13 AND avg_net<0 -> toxic by the live (data-driven) rule, independent
        # of the flag and independent of the seed table.
        monkeypatch.setattr(ensemble_mod, "_load_combo_stats", lambda: {seed: (20, 0.10, -6.0)})
        combos = ens._get_live_losing_combos()
        assert seed in combos

    def test_other_seed_unaffected_by_first_seed_state(self, monkeypatch):
        """Both seed entries are gated independently."""
        monkeypatch.setenv("DEFABRICATE_LOSING_COMBOS", "true")
        ens = _make_ensemble()
        seed1 = frozenset({"regime_trend", "vmc_cipher"})
        seed2 = frozenset({"probability_engine", "regime_trend"})
        assert ens._LOSING_COMBOS_SEED == {seed1, seed2}
        monkeypatch.setattr(ensemble_mod, "_load_combo_stats", lambda: {seed1: (20, 0.05, -9.0)})
        combos = ens._get_live_losing_combos()
        assert seed1 in combos      # graduated live-toxic
        assert seed2 not in combos  # n<13, not injected (flag ON)


# ---------------------------------------------------------------------------
# 2. _weighted_veto() call site -- block vs shadow-log-and-proceed
# ---------------------------------------------------------------------------

class TestWeightedVetoFlagOff:
    """Characterization: flag OFF (default) = seed-only match hard-blocks
    (returns None) exactly as before, zero live behavior change."""

    def test_seed_only_match_blocked(self, monkeypatch, caplog):
        monkeypatch.setattr(ensemble_mod, "_load_combo_stats", lambda: {})
        ens = _make_ensemble()
        ens._merge_signals = MagicMock(side_effect=AssertionError("should not reach merge"))
        sigs = _signals("BTC", "BUY", ["regime_trend", "vmc_cipher", "confidence_scorer"])
        with caplog.at_level("INFO"):
            result = ens._weighted_veto("BTC", sigs)
        assert result is None
        assert not ens._merge_signals.called
        assert any("Blocked losing combo" in r.message for r in caplog.records)
        assert not any("DEFAB-LOSING-COMBOS" in r.message for r in caplog.records)


class TestWeightedVetoFlagOn:
    """Flag ON: seed-only match is shadow-logged and proceeds (does not
    short-circuit at the combo-block site); a combo with real n>=13
    live-toxic evidence still hard-blocks."""

    def test_seed_only_match_proceeds_and_shadow_logs(self, monkeypatch, caplog):
        monkeypatch.setenv("DEFABRICATE_LOSING_COMBOS", "true")
        monkeypatch.setattr(ensemble_mod, "_load_combo_stats", lambda: {})
        ens = _make_ensemble()
        _sentinel = MockSignal(strategy="merged", symbol="BTC", side="BUY", confidence=80.0)
        ens._merge_signals = MagicMock(return_value=_sentinel)
        sigs = _signals("BTC", "BUY", ["regime_trend", "vmc_cipher", "confidence_scorer"])
        with caplog.at_level("INFO"):
            result = ens._weighted_veto("BTC", sigs)
        assert result is _sentinel  # proceeded past the combo-block site
        assert ens._merge_signals.called
        assert not any("Blocked losing combo" in r.message for r in caplog.records)
        assert any(
            "[DEFAB-LOSING-COMBOS]" in r.message and "would_block=True" in r.message
            and "acting=proceed" in r.message and "live_n=0" in r.message
            for r in caplog.records
        )

    def test_live_toxic_combo_still_blocks(self, monkeypatch, caplog):
        monkeypatch.setenv("DEFABRICATE_LOSING_COMBOS", "true")
        seed = frozenset({"regime_trend", "vmc_cipher"})
        monkeypatch.setattr(ensemble_mod, "_load_combo_stats", lambda: {seed: (20, 0.05, -9.0)})
        ens = _make_ensemble()
        ens._merge_signals = MagicMock(side_effect=AssertionError("should not reach merge"))
        sigs = _signals("BTC", "BUY", ["regime_trend", "vmc_cipher", "confidence_scorer"])
        with caplog.at_level("INFO"):
            result = ens._weighted_veto("BTC", sigs)
        assert result is None  # n>=13 live-toxic evidence -> still blocked
        assert not ens._merge_signals.called
        assert any("Blocked losing combo" in r.message for r in caplog.records)

    def test_non_matching_group_proceeds_with_no_shadow_log(self, monkeypatch, caplog):
        """A signal group that doesn't contain either seed combo as a subset
        should proceed silently -- no block, no shadow-log noise."""
        monkeypatch.setenv("DEFABRICATE_LOSING_COMBOS", "true")
        monkeypatch.setattr(ensemble_mod, "_load_combo_stats", lambda: {})
        ens = _make_ensemble()
        _sentinel = MockSignal(strategy="merged", symbol="BTC", side="BUY", confidence=80.0)
        ens._merge_signals = MagicMock(return_value=_sentinel)
        sigs = _signals("BTC", "BUY", ["confidence_scorer", "probability_engine"])  # not a seed subset
        with caplog.at_level("INFO"):
            result = ens._weighted_veto("BTC", sigs)
        assert result is _sentinel
        assert not any("DEFAB-LOSING-COMBOS" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# #6 -- llm/agents/prompts.py phantom-field bullets
# ---------------------------------------------------------------------------

def _reload_prompts(monkeypatch, flag_value: Optional[str]):
    """Reload llm.agents.prompts with DEFABRICATE_PROMPT_PHANTOMS set (or
    unset) -- mirrors the existing THESIS_CHECKLIST_ENABLED import-time flag
    pattern already used in that module (flags are read once at import
    time, not per-call)."""
    if flag_value is None:
        monkeypatch.delenv("DEFABRICATE_PROMPT_PHANTOMS", raising=False)
    else:
        monkeypatch.setenv("DEFABRICATE_PROMPT_PHANTOMS", flag_value)
    import llm.agents.prompts as prompts_mod
    importlib.reload(prompts_mod)
    return prompts_mod


PHANTOM_TERMS = (
    "validated_edges",
    "noise_floor_pct",
    "min_ev_per_dollar",
    "break_even_wr",
    "SIZING STATS",
    "CONFLUENCE CALIBRATION",
)


class TestPromptPhantomsFlagOff:
    """Characterization: flag OFF (default) = every phantom bullet present,
    unchanged from before this rip-out."""

    def test_flag_reads_false_by_default(self, monkeypatch):
        p = _reload_prompts(monkeypatch, None)
        assert p.DEFABRICATE_PROMPT_PHANTOMS_ENABLED is False

    def test_trade_prompt_has_phantom_bullets(self, monkeypatch):
        p = _reload_prompts(monkeypatch, "false")
        assert "signals.validated_edges" in p.TRADE_AGENT_PROMPT
        assert "CONFLUENCE CALIBRATION" in p.TRADE_AGENT_PROMPT
        assert "min_ev_per_dollar" in p.TRADE_AGENT_PROMPT
        assert "break_even_wr" in p.TRADE_AGENT_PROMPT

    def test_risk_prompt_has_phantom_bullets(self, monkeypatch):
        p = _reload_prompts(monkeypatch, "false")
        assert "SIZING STATS" in p.RISK_AGENT_PROMPT
        assert "noise_floor_pct" in p.RISK_AGENT_PROMPT

    def test_critic_prompt_has_phantom_bullets(self, monkeypatch):
        p = _reload_prompts(monkeypatch, "false")
        assert "signals.validated_edges" in p.CRITIC_AGENT_PROMPT
        assert "validated_edges entries carry their own wr/n/era" in p.CRITIC_AGENT_PROMPT


class TestPromptPhantomsFlagOn:
    """Flag ON: validated_edges bullets deleted outright; other phantom
    bullets reworded to an honest operative-constant statement with no
    residual phantom field/section name."""

    def test_flag_reads_true(self, monkeypatch):
        p = _reload_prompts(monkeypatch, "true")
        assert p.DEFABRICATE_PROMPT_PHANTOMS_ENABLED is True

    def test_trade_prompt_validated_edges_bullet_gone(self, monkeypatch):
        p = _reload_prompts(monkeypatch, "true")
        assert "validated_edges" not in p.TRADE_AGENT_PROMPT

    def test_critic_prompt_validated_edges_bullets_gone(self, monkeypatch):
        p = _reload_prompts(monkeypatch, "true")
        assert "validated_edges" not in p.CRITIC_AGENT_PROMPT

    def test_trade_prompt_confluence_calibration_name_gone(self, monkeypatch):
        p = _reload_prompts(monkeypatch, "true")
        assert "CONFLUENCE CALIBRATION" not in p.TRADE_AGENT_PROMPT
        # honest operative-constant replacement text present
        assert "0.55" in p.TRADE_AGENT_PROMPT  # solo cap constant preserved
        assert "operative constant" in p.TRADE_AGENT_PROMPT

    def test_trade_prompt_ev_gate_phantom_fields_gone(self, monkeypatch):
        p = _reload_prompts(monkeypatch, "true")
        assert "min_ev_per_dollar" not in p.TRADE_AGENT_PROMPT
        assert "break_even_wr" not in p.TRADE_AGENT_PROMPT
        # operative fallback constants (0.10 / 0.48) preserved honestly
        assert "0.10" in p.TRADE_AGENT_PROMPT
        assert "0.48" in p.TRADE_AGENT_PROMPT

    def test_risk_prompt_sizing_stats_and_noise_floor_gone(self, monkeypatch):
        p = _reload_prompts(monkeypatch, "true")
        assert "SIZING STATS" not in p.RISK_AGENT_PROMPT
        assert "noise_floor_pct" not in p.RISK_AGENT_PROMPT
        assert "0.30" in p.RISK_AGENT_PROMPT  # operative noise-floor constant preserved

    def test_no_phantom_terms_survive_anywhere(self, monkeypatch):
        p = _reload_prompts(monkeypatch, "true")
        for term in PHANTOM_TERMS:
            assert term not in p.TRADE_AGENT_PROMPT, f"{term} still in TRADE_AGENT_PROMPT"
            assert term not in p.RISK_AGENT_PROMPT, f"{term} still in RISK_AGENT_PROMPT"
            assert term not in p.CRITIC_AGENT_PROMPT, f"{term} still in CRITIC_AGENT_PROMPT"

    def test_prompts_still_non_empty_valid_text(self, monkeypatch):
        p = _reload_prompts(monkeypatch, "true")
        for prompt in (p.TRADE_AGENT_PROMPT, p.RISK_AGENT_PROMPT, p.CRITIC_AGENT_PROMPT):
            assert isinstance(prompt, str)
            assert len(prompt) > 500
            assert "```json" in prompt or "JSON" in prompt  # output-format instructions intact

    def test_flag_off_after_flag_on_restores_original_text(self, monkeypatch):
        """Reload sanity: toggling the flag back OFF restores byte-identical
        fabricated text (proves the ON path doesn't mutate global state)."""
        p_off_1 = _reload_prompts(monkeypatch, "false")
        off_trade = p_off_1.TRADE_AGENT_PROMPT
        off_risk = p_off_1.RISK_AGENT_PROMPT
        off_critic = p_off_1.CRITIC_AGENT_PROMPT
        _reload_prompts(monkeypatch, "true")
        p_off_2 = _reload_prompts(monkeypatch, "false")
        assert p_off_2.TRADE_AGENT_PROMPT == off_trade
        assert p_off_2.RISK_AGENT_PROMPT == off_risk
        assert p_off_2.CRITIC_AGENT_PROMPT == off_critic
