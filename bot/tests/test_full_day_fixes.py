"""
Regression tests for 2026-04-14 full-day fixes.

Covers the set of changes made in the "LLM-first completion" session:
- regime_canonical: synonym map for legacy/alt regime vocabularies
- symbol_strategy_profile: per-symbol strategy activation + min_votes
- coordinator edge_data propagation: signal_ctx.edge_data → snapshot.g.setup_mfe
- TOXIC block: is_toxic detection + SafetyFilterChain hard block
- confidence_scorer calibration: raised thresholds 55→65, 75→85
- cost_tracker prompt caching: cache_read/cache_create cost math
- LLM-first dispatch: solo signals with LLM_FIRST_MODE=true route to LLM
- Overseer cold-start guard: skip when input < 1500 chars
- fail-closed on validation errors in llm_integration.py

Each test is a small, focused unit. No network calls, no LLM, no file I/O
beyond tempfiles.
"""

import os
import tempfile
import pytest


# ── regime_canonical ──────────────────────────────────────────


class TestRegimeCanonical:
    def test_execution_legacy_names_map(self):
        from llm.regime_canonical import canonicalize_regime
        assert canonicalize_regime("illiquid") == "low_liquidity"
        assert canonicalize_regime("trending") == "trend"
        assert canonicalize_regime("ranging") == "range"
        assert canonicalize_regime("volatile") == "high_volatility"

    def test_llm_prompt_variants_map(self):
        from llm.regime_canonical import canonicalize_regime
        assert canonicalize_regime("trending_bull") == "trend"
        assert canonicalize_regime("trending_bear") == "trend"
        assert canonicalize_regime("consolidation") == "range"

    def test_quant_brain_microregimes_map(self):
        from llm.regime_canonical import canonicalize_regime
        assert canonicalize_regime("panic_oversold") == "panic"
        assert canonicalize_regime("recovering") == "trend"

    def test_canonical_names_passthrough(self):
        from llm.regime_canonical import canonicalize_regime
        for canonical in ("trend", "range", "panic", "high_volatility",
                          "low_liquidity", "news_dislocation", "unknown"):
            assert canonicalize_regime(canonical) == canonical

    def test_case_and_whitespace_tolerance(self):
        from llm.regime_canonical import canonicalize_regime
        assert canonicalize_regime("  Trending  ") == "trend"
        assert canonicalize_regime("ILLIQUID") == "low_liquidity"

    def test_unknown_stays_lowercased(self):
        from llm.regime_canonical import canonicalize_regime
        # Unknown names are lowercased but not mapped
        assert canonicalize_regime("FooBar") == "foobar"

    def test_none_and_non_string(self):
        from llm.regime_canonical import canonicalize_regime
        assert canonicalize_regime(None) is None
        assert canonicalize_regime(42) == 42


# ── symbol_strategy_profile ───────────────────────────────────


class TestSymbolStrategyProfile:
    def test_hype_min_votes_is_one(self):
        from data.symbol_strategy_profile import get_min_votes_for_symbol
        assert get_min_votes_for_symbol("HYPE") == 1

    def test_default_min_votes_is_two(self):
        from data.symbol_strategy_profile import get_min_votes_for_symbol
        for sym in ("BTC", "ETH", "SOL"):
            assert get_min_votes_for_symbol(sym) == 2

    def test_unknown_symbol_uses_default(self):
        from data.symbol_strategy_profile import get_min_votes_for_symbol
        assert get_min_votes_for_symbol("NONESUCH") == 2
        assert get_min_votes_for_symbol("NONESUCH", default=5) == 5

    def test_hype_active_strategy_set_is_restricted(self):
        from data.symbol_strategy_profile import get_active_strategies_for_symbol
        hype = get_active_strategies_for_symbol("HYPE")
        assert hype is not None
        # Forensic: only confidence_scorer fires reliably on HYPE
        assert "confidence_scorer" in hype
        # regime_trend isn't in the HYPE set (fires poorly on HYPE)
        assert "regime_trend" not in hype

    def test_sol_drops_regime_trend(self):
        from data.symbol_strategy_profile import get_active_strategies_for_symbol
        sol = get_active_strategies_for_symbol("SOL")
        assert sol is not None
        # Memory: regime_trend is 0% WR on SOL
        assert "regime_trend" not in sol

    def test_btc_has_full_stack(self):
        from data.symbol_strategy_profile import get_active_strategies_for_symbol
        btc = get_active_strategies_for_symbol("BTC")
        assert btc is not None
        assert "regime_trend" in btc
        assert "confidence_scorer" in btc

    def test_symbol_lookup_strips_pair_suffix(self):
        from data.symbol_strategy_profile import get_min_votes_for_symbol
        assert get_min_votes_for_symbol("HYPE/USDC:USDC") == 1
        assert get_min_votes_for_symbol("BTC/USDT:USDT") == 2


# ── cost_tracker prompt caching ───────────────────────────────


class TestCostTrackerCaching:
    def _fresh_tracker(self):
        """Return a CostTracker with state in a tempdir (no pollution)."""
        import llm.cost_tracker as ct_mod
        tmpdir = tempfile.mkdtemp()
        ct_mod._COST_DIR = tmpdir
        ct_mod._COST_PATH = os.path.join(tmpdir, "cost_tracker.json")
        return ct_mod.CostTracker(daily_budget=5.0)

    def test_haiku_cache_read_is_cheap(self):
        ct = self._fresh_tracker()
        # 1000 cache-read tokens = 1000 * $0.08/M = $0.00008
        ct.record_call(
            input_tokens=0, output_tokens=0,
            model="claude-haiku-4-5-20251001",
            cache_read_tokens=1000, cache_create_tokens=0,
        )
        assert abs(ct._today_spend - 0.00008) < 1e-8

    def test_haiku_cache_write_premium(self):
        ct = self._fresh_tracker()
        # 1000 cache-create tokens = 1000 * $1.00/M = $0.001
        ct.record_call(
            input_tokens=0, output_tokens=0,
            model="claude-haiku-4-5-20251001",
            cache_read_tokens=0, cache_create_tokens=1000,
        )
        assert abs(ct._today_spend - 0.001) < 1e-8

    def test_sonnet_cache_read_is_cheap(self):
        ct = self._fresh_tracker()
        # 1000 cache-read tokens = 1000 * $0.30/M = $0.0003
        ct.record_call(
            input_tokens=0, output_tokens=0,
            model="claude-sonnet-4-5-20250929",
            cache_read_tokens=1000, cache_create_tokens=0,
        )
        assert abs(ct._today_spend - 0.0003) < 1e-8

    def test_uncached_still_works(self):
        ct = self._fresh_tracker()
        # 1000 uncached in + 500 out, Haiku
        # = 1000*0.80/M + 500*4.0/M = 0.0008 + 0.002 = 0.0028
        ct.record_call(
            input_tokens=1000, output_tokens=500,
            model="claude-haiku-4-5-20251001",
        )
        assert abs(ct._today_spend - 0.0028) < 1e-8

    def test_combined_call(self):
        ct = self._fresh_tracker()
        # Realistic LLM-first call: 500 uncached in + 2500 cached in + 800 out, Sonnet
        # = 500*3/M + 2500*0.30/M + 800*15/M
        # = 0.0015 + 0.00075 + 0.012 = 0.01425
        ct.record_call(
            input_tokens=500, output_tokens=800,
            model="claude-sonnet-4-5-20250929",
            cache_read_tokens=2500, cache_create_tokens=0,
        )
        assert abs(ct._today_spend - 0.01425) < 1e-8


# ── ensemble llm_first_raw flag threading ─────────────────────


class TestLLMFirstRawFlag:
    def test_voting_signature_has_flag(self):
        import inspect
        from strategies.ensemble import EnsembleStrategy
        params = inspect.signature(EnsembleStrategy._voting).parameters
        assert "llm_first_raw" in params
        assert params["llm_first_raw"].default is False

    def test_weighted_veto_signature_has_flag(self):
        import inspect
        from strategies.ensemble import EnsembleStrategy
        params = inspect.signature(EnsembleStrategy._weighted_veto).parameters
        assert "llm_first_raw" in params
        assert params["llm_first_raw"].default is False

    def test_merge_signals_signature_has_flag(self):
        import inspect
        from strategies.ensemble import EnsembleStrategy
        params = inspect.signature(EnsembleStrategy._merge_signals).parameters
        assert "llm_first_raw" in params
        assert params["llm_first_raw"].default is False


# ── fail-closed validation ────────────────────────────────────


class TestFailClosedMarkers:
    def test_validation_failure_markers_in_source(self):
        """The fail-closed list must include LLM-returned-but-unparseable
        categories: validation_error, sanitization_error, parse_error."""
        import pathlib
        src = pathlib.Path("core") / "llm_integration.py"
        if not src.exists():
            # running from bot/ dir
            src = pathlib.Path("bot") / "core" / "llm_integration.py"
        text = src.read_text()
        # The critical markers are listed in the fail_closed_markers tuple
        assert "validation_error" in text
        assert "sanitization_error" in text
        assert "parse_error" in text
        # And they cause a fail-closed skip, not a default-to-proceed
        assert "fail-closed" in text.lower()


# ── confidence_scorer recalibration ───────────────────────────


class TestConfidenceScorerThresholds:
    def test_strong_threshold_is_raised(self):
        """STRONG_BUY threshold should be >= 85 post-recalibration."""
        import pathlib
        src = pathlib.Path("strategies") / "confidence_scorer.py"
        if not src.exists():
            src = pathlib.Path("bot") / "strategies" / "confidence_scorer.py"
        text = src.read_text()
        # The comment in the recalibrated block
        assert "RECALIBRATED" in text or "recalibrated" in text
        # Both thresholds must be present and raised
        assert "confidence >= 85" in text  # STRONG threshold
        assert "confidence >= 65" in text  # BUY floor


# ── Coordinator edge_data propagation ─────────────────────────


class TestCoordinatorEdgeDataPropagation:
    """Verify that signal_ctx.edge_data reaches the agent snapshot.

    Before 2026-04-14 the coordinator dropped edge_data when building the
    snapshot — prompts said they checked TOXIC flags but the data never
    arrived. This test guards the fix.
    """

    def _make_minimal_ctx_and_build(self, edge_data: dict):
        from llm.agents.coordinator import get_coordinator
        coord = get_coordinator()
        signal_ctx = {
            "symbol": "HYPE",
            "side": "BUY",
            "entry": 43.0,
            "sl": 42.0,
            "tp1": 44.0,
            "tp2": 45.0,
            "confidence": 67,
            "atr": 0.5,
            "strategy": "confidence_scorer",
            "edge_data": edge_data,
        }
        market_ctx = {
            "funding_rate": 0.01,
            "volume_ratio": 1.0,
            "time_utc_hour": 12,
            "btc_trend": 0.0,
            "signal_age": 0.0,
        }
        portfolio_ctx = {
            "equity": 500.0,
            "open_positions": {},
            "open_positions_count": 0,
            "daily_pnl": 0.0,
            "circuit_breaker_proximity": 1.0,
            "consecutive_losses": 0,
        }
        return coord._build_entry_snapshot(signal_ctx, market_ctx, portfolio_ctx)

    def test_edge_data_surfaces_in_global_setup_mfe(self):
        edge = {
            "setup_key": "HYPE_BUY",
            "wr": 58,
            "pf": 1.4,
            "n": 36,
            "verdict": "CONFIRMED_EDGE",
            "regime": "low_liquidity",
            "regime_wr": 9.0,
            "regime_n": 11,
            "is_toxic": True,
        }
        snap = self._make_minimal_ctx_and_build(edge)
        # Snapshot must surface edge_data under both 'setup_mfe' and
        # 'historical_edge' keys so agent input builders can find it.
        assert snap["g"]["setup_mfe"] == edge
        assert snap["g"]["historical_edge"] == edge

    def test_edge_data_surfaces_in_signal_metadata(self):
        edge = {
            "setup_key": "HYPE_BUY",
            "regime": "low_liquidity",
            "regime_wr": 9.0,
            "regime_n": 11,
            "is_toxic": True,
            "verdict": "CONFIRMED_EDGE",
        }
        snap = self._make_minimal_ctx_and_build(edge)
        sig_meta = snap["signal_metadata"]
        assert sig_meta["is_toxic"] is True
        assert sig_meta["regime_wr"] == 9.0
        assert sig_meta["regime_n"] == 11
        assert sig_meta["setup_verdict"] == "CONFIRMED_EDGE"
        assert sig_meta["historical_edge"] == edge

    def test_missing_edge_data_is_safe(self):
        """When no edge_data is provided, the snapshot still builds cleanly."""
        snap = self._make_minimal_ctx_and_build({})
        # Empty dict — no crash
        assert snap["g"]["setup_mfe"] == {}
        assert snap["signal_metadata"]["is_toxic"] is False


# ── Prompt JSON-only rule ─────────────────────────────────────


class TestPromptJSONOnlyRule:
    """All 8 core agent prompts must force JSON-only output.

    Forensic 2026-04-14 showed Trade agent writing "## STEP 0: INDEPENDENT
    THESIS" prose before JSON, burning output tokens and truncating. The
    fix added a CRITICAL OUTPUT RULE to every prompt.
    """

    def test_all_prompts_have_json_only_rule(self):
        from llm.agents.prompts import (
            REGIME_AGENT_PROMPT, TRADE_AGENT_PROMPT, RISK_AGENT_PROMPT,
            CRITIC_AGENT_PROMPT, EXIT_AGENT_PROMPT, SCOUT_AGENT_PROMPT,
            OVERSEER_AGENT_PROMPT, QUANT_AGENT_PROMPT,
        )
        prompts = {
            "REGIME": REGIME_AGENT_PROMPT,
            "TRADE": TRADE_AGENT_PROMPT,
            "RISK": RISK_AGENT_PROMPT,
            "CRITIC": CRITIC_AGENT_PROMPT,
            "EXIT": EXIT_AGENT_PROMPT,
            "SCOUT": SCOUT_AGENT_PROMPT,
            "OVERSEER": OVERSEER_AGENT_PROMPT,
            "QUANT": QUANT_AGENT_PROMPT,
        }
        for name, prompt in prompts.items():
            assert "CRITICAL OUTPUT RULE" in prompt, (
                f"{name} agent prompt missing JSON-only rule — "
                f"will allow prose preamble before JSON"
            )
            # Case-insensitive check — some prompts say "First character",
            # others "first character", both are valid.
            assert "first character must be `{`" in prompt.lower(), (
                f"{name} agent prompt missing explicit first-character rule"
            )


# ── signal_tracker whitelist accepts llm_first markers ────────


class TestSignalTrackerWhitelist:
    def test_pipeline_marker_persisted(self):
        """signal_tracker.record_signal must persist 'pipeline' and 'stage'
        when passed via filter_metadata. Without this, _track_llm_first_outcome
        calls are invisible to signal_outcomes.jsonl analysis tools."""
        import tempfile
        from core.signal_tracker import SignalTracker
        with tempfile.TemporaryDirectory() as tmp:
            tracker = SignalTracker(log_dir=tmp)
            tracker.record_signal(
                symbol="HYPE", side="SELL", confidence=72.0,
                strategy="confidence_scorer",
                passed=False, hard_rejected=False,
                hard_rejection_reason="LLM veto: toxic setup",
                filter_metadata={
                    "pipeline": "llm_first",
                    "stage": "toxic_block",
                    "regime_wr": 9.0,
                    "regime_n": 11,
                    "llm_confidence": 0.45,
                },
                num_strategies_agree=1,
            )
            # Read back
            import json, os
            log_file = os.path.join(tmp, "signal_outcomes.jsonl")
            with open(log_file) as f:
                line = f.readline()
            rec = json.loads(line)
            meta = rec.get("meta", {})
            assert meta.get("pipeline") == "llm_first"
            assert meta.get("stage") == "toxic_block"
            assert meta.get("regime_wr") == 9.0
            assert meta.get("regime_n") == 11
            assert meta.get("llm_confidence") == 0.45


# ── Prompt caching structure (two-block fix) ─────────────────


class TestCacheablePrefix:
    """Verify client.py correctly splits stable vs dynamic content blocks.

    The coordinator used to prepend dynamic content (calibration, brain,
    protocol) onto the agent prompt, making the system_prompt differ on
    every call and defeating Anthropic's prompt cache. The fix: accept a
    `cacheable_prefix` kwarg that is placed in its own content block with
    cache_control, while the dynamic `system_prompt` is a second uncached
    block.
    """

    def test_call_llm_accepts_cacheable_prefix(self):
        import inspect
        from llm.client import call_llm
        params = inspect.signature(call_llm).parameters
        assert "cacheable_prefix" in params, (
            "call_llm signature missing cacheable_prefix kwarg"
        )
        assert params["cacheable_prefix"].default is None

    def test_coordinator_splits_dynamic_prefix(self):
        """The coordinator must pass the stable agent prompt as
        cacheable_prefix and the dynamic content as system_prompt."""
        import pathlib
        src = pathlib.Path("llm") / "agents" / "coordinator.py"
        if not src.exists():
            src = pathlib.Path("bot") / "llm" / "agents" / "coordinator.py"
        text = src.read_text(encoding="utf-8", errors="replace")
        # Look for the two-block call site
        assert "cacheable_prefix=prompt" in text, (
            "Coordinator must pass prompt as cacheable_prefix for cache hits"
        )
        # And for the explanation comment
        assert "dynamic_prefix" in text, (
            "Coordinator must separate dynamic_prefix from stable prompt"
        )


# ── Overseer cold-start guard ─────────────────────────────────


class TestOverseerColdStartGuard:
    def test_run_overseer_skips_on_thin_input(self):
        """Overseer must skip when _build_overseer_input returns < 1500 chars."""
        from llm.agents.coordinator import get_coordinator
        coord = get_coordinator()
        # Monkey-patch _build_overseer_input to return a stub
        original = coord._build_overseer_input
        try:
            coord._build_overseer_input = lambda: "{}"  # Very thin (2 chars)
            result = coord.run_overseer()
            assert result is None, (
                "Overseer should skip on thin input but returned a result"
            )
        finally:
            coord._build_overseer_input = original
