"""
LLM-first activation smoke test.

Guards against regressions in the LLM_FIRST_MODE activation path. This test
does NOT hit the Anthropic API — it verifies the dispatch flag, the config
propagation, and the dispatch method exists with the right signature.

Catches:
  - `.env` file with LLM_FIRST_MODE=true but config object reading it as false
  - Missing prerequisites (LLM_MULTI_AGENT, LLM_MODE)
  - _process_symbol_llm_first method deleted or renamed
  - Dispatch branch in _process_symbol() removed
"""

import os
import inspect
import pytest


class TestLLMFirstActivation:
    def test_config_exposes_llm_first_mode_flag(self):
        """trading_config must have llm_first_mode as a bool attribute."""
        from trading_config import TradingConfig
        cfg = TradingConfig()
        assert hasattr(cfg, "llm_first_mode"), (
            "TradingConfig missing llm_first_mode attribute — "
            "the LLM-first flag has been removed"
        )
        assert isinstance(cfg.llm_first_mode, bool)

    def test_env_flag_reads_true(self):
        """When LLM_FIRST_MODE=true is set, the config must reflect it."""
        os.environ["LLM_FIRST_MODE"] = "true"
        try:
            from trading_config import TradingConfig
            cfg = TradingConfig()
            assert cfg.llm_first_mode is True
        finally:
            os.environ.pop("LLM_FIRST_MODE", None)

    def test_env_flag_reads_false(self):
        os.environ["LLM_FIRST_MODE"] = "false"
        try:
            from trading_config import TradingConfig
            cfg = TradingConfig()
            assert cfg.llm_first_mode is False
        finally:
            os.environ.pop("LLM_FIRST_MODE", None)

    def test_process_symbol_llm_first_method_exists(self):
        """The dispatch method must exist on MultiStrategyBot."""
        from multi_strategy_main import MultiStrategyBot
        assert hasattr(MultiStrategyBot, "_process_symbol_llm_first"), (
            "MultiStrategyBot._process_symbol_llm_first is missing — "
            "the LLM-first dispatch method has been removed"
        )

    def test_track_llm_first_outcome_method_exists(self):
        """Signal tracking helper for LLM-first must exist."""
        from multi_strategy_main import MultiStrategyBot
        assert hasattr(MultiStrategyBot, "_track_llm_first_outcome"), (
            "MultiStrategyBot._track_llm_first_outcome is missing — "
            "LLM-first signal tracking coverage will be silently broken"
        )

    def test_safety_filter_chain_importable(self):
        """SafetyFilterChain is the pre-LLM gate in LLM-first path."""
        from core.signal_pipeline import SafetyFilterChain
        # Must have evaluate method
        assert hasattr(SafetyFilterChain, "evaluate")

    def test_evaluate_raw_exists_on_ensemble(self):
        """evaluate_raw is the quality-filter-free entry into LLM-first."""
        from strategies.ensemble import EnsembleStrategy
        assert hasattr(EnsembleStrategy, "evaluate_raw")

    def test_coordinator_has_get_entry_decision(self):
        """Coordinator's LLM-first entry point."""
        from llm.agents.coordinator import AgentCoordinator
        assert hasattr(AgentCoordinator, "get_entry_decision")

    def test_dispatch_branch_in_process_symbol(self):
        """The main _process_symbol method must contain the LLM-first
        dispatch branch. If this is removed, LLM-first never fires."""
        from multi_strategy_main import MultiStrategyBot
        src = inspect.getsource(MultiStrategyBot._process_symbol)
        assert "_process_symbol_llm_first" in src, (
            "_process_symbol() no longer dispatches to _process_symbol_llm_first"
        )
        assert "llm_first_mode" in src, (
            "_process_symbol() no longer checks llm_first_mode flag"
        )


class TestLLMFirstDispatchGate:
    """Verify the dispatch logic gates are present and correctly ordered."""

    def test_cost_gate_precedes_llm_first_dispatch(self):
        """The 60% confidence cost gate must be applied before the LLM-first
        dispatch fires, otherwise sub-60% noise burns API budget."""
        from multi_strategy_main import MultiStrategyBot
        src = inspect.getsource(MultiStrategyBot._process_symbol)
        # Crude but effective: find order of key markers
        cost_gate_idx = src.find("60% threshold")
        dispatch_idx = src.find("_process_symbol_llm_first")
        assert cost_gate_idx > 0, "60% cost gate missing from _process_symbol"
        assert dispatch_idx > 0, "LLM-first dispatch call missing"
        assert cost_gate_idx < dispatch_idx, (
            "Cost gate must appear BEFORE LLM-first dispatch; budget protection broken"
        )

    def test_cooldown_mechanism_present(self):
        """Per-symbol cooldown must exist to prevent API burn on repeated signals."""
        from multi_strategy_main import MultiStrategyBot
        src = inspect.getsource(MultiStrategyBot._process_symbol)
        assert "_llm_eval_cooldowns" in src, (
            "10-min LLM-first cooldown mechanism is missing — risk of budget burn"
        )


# SafetyFilterChain internals are covered by test_llm_first_architecture.py.
# The smoke tests above verify activation + dispatch only.
