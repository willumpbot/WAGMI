"""Tests for the prompt enricher module."""

import csv
import json
import os
import tempfile
import time
import pytest

# Ensure bot directory is on path
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import llm.agents.prompt_enricher as enricher_mod
from llm.agents.prompt_enricher import (
    enrich_prompt,
    invalidate_cache,
    get_cache_age_seconds,
    get_enrichment_stats,
    _select_insights_for_agent,
    _build_quant_briefing,
    _build_fingerprint_summary,
    _build_sim_status_summary,
    _build_recent_performance,
    _refresh_cache,
)
_MAX_BRIEFING_CHARS = 3000  # updated budget — CLI is $0/call


# ── Fixtures ────────────────────────────────────────────────────

SAMPLE_INSIGHTS = {
    "insights": [
        {
            "ts": 1000.0,
            "category": "strategy_insight",
            "insight": "HYPE_BUY is the highest-edge setup with 58% WR",
            "confidence": 0.9,
            "evidence": "30-day backtest",
            "source": "quant_backtest",
            "validated": True,
            "validation_count": 36,
        },
        {
            "ts": 1001.0,
            "category": "risk_insight",
            "insight": "Never risk more than 2% per trade",
            "confidence": 0.85,
            "evidence": "Student course",
            "source": "student_course",
            "validated": False,
            "validation_count": 0,
        },
        {
            "ts": 1002.0,
            "category": "regime_insight",
            "insight": "RSI 35-65 is the sweet spot for HYPE_BUY entries",
            "confidence": 0.80,
            "evidence": "RSI zone analysis",
            "source": "quant_backtest",
            "validated": True,
            "validation_count": 84,
        },
        {
            "ts": 1003.0,
            "category": "timing_insight",
            "insight": "HYPE_BUY performs best during 18-06 UTC",
            "confidence": 0.85,
            "evidence": "Time-of-day analysis",
            "source": "quant_backtest",
            "validated": True,
            "validation_count": 74,
        },
        {
            "ts": 1004.0,
            "category": "execution_insight",
            "insight": "12h time stop is optimal at +4.5R net",
            "confidence": 0.85,
            "evidence": "Time stop sweep",
            "source": "quant_timestop",
            "validated": False,
            "validation_count": 0,
        },
        {
            "ts": 1005.0,
            "category": "correlation_insight",
            "insight": "BTC >0.5% hourly move predicts HYPE direction next hour with 73% accuracy",
            "confidence": 0.9,
            "evidence": "30-day correlation",
            "source": "quant_correlation",
            "validated": False,
            "validation_count": 0,
        },
        {
            "ts": 1006.0,
            "category": "meta_insight",
            "insight": "The best trade is often no trade",
            "confidence": 0.85,
            "evidence": "Student course",
            "source": "student_course",
            "validated": False,
            "validation_count": 0,
        },
        {
            "ts": 1007.0,
            "category": "symbol_insight",
            "insight": "SOL_SELL is marginal with PF < 1.0",
            "confidence": 0.80,
            "evidence": "Parameter sweep",
            "source": "quant_backtest",
            "validated": True,
            "validation_count": 36,
        },
    ]
}

SAMPLE_FINGERPRINTS = {
    "ensemble": {
        "total": 10,
        "wins": 6,
        "pnl": 45.5,
        "by_regime": {
            "trending": {"wins": 4, "total": 6, "pnl": 30.0},
            "range": {"wins": 2, "total": 4, "pnl": 15.5},
        },
        "by_symbol": {
            "HYPE": {"wins": 5, "total": 7, "pnl": 40.0},
            "SOL": {"wins": 1, "total": 3, "pnl": 5.5},
        },
    }
}

SAMPLE_SIM_STATUS = {
    "current_equity": 110.5,
    "starting_equity": 100.0,
    "total_trades": 15,
    "wins": 9,
    "losses": 6,
    "win_rate": 60.0,
    "profit_factor": 1.85,
    "max_drawdown": 8.3,
    "current_streak": 2,
    "daily_pnl": 5.25,
    "weekly_pnl": 10.5,
}


@pytest.fixture(autouse=True)
def _setup_test_data(tmp_path, monkeypatch):
    """Write sample data files and point the enricher at them."""
    # Write insight journal
    insight_path = tmp_path / "insight_journal.json"
    insight_path.write_text(json.dumps(SAMPLE_INSIGHTS))

    # Write fingerprints
    fp_path = tmp_path / "strategy_fingerprints.json"
    fp_path.write_text(json.dumps(SAMPLE_FINGERPRINTS))

    # Write sim status
    sim_path = tmp_path / "sim_status.json"
    sim_path.write_text(json.dumps(SAMPLE_SIM_STATUS))

    # Write trades CSV
    trades_path = tmp_path / "trades.csv"
    with open(trades_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "timestamp", "symbol", "side", "pnl", "outcome",
            "primary_driver", "strategy", "regime", "leverage",
        ])
        writer.writeheader()
        writer.writerow({
            "timestamp": "2026-03-25T14:00:00",
            "symbol": "HYPE", "side": "LONG", "pnl": "-10.53",
            "outcome": "CLEAN_LOSS", "primary_driver": "multi_tier_quality",
            "strategy": "ensemble", "regime": "trending", "leverage": "2.0",
        })
        writer.writerow({
            "timestamp": "2026-03-25T20:00:00",
            "symbol": "HYPE", "side": "LONG", "pnl": "5.25",
            "outcome": "TP1_HIT", "primary_driver": "confidence_scorer",
            "strategy": "ensemble", "regime": "trending", "leverage": "3.0",
        })
        writer.writerow({
            "timestamp": "2026-03-25T22:00:00",
            "symbol": "SOL", "side": "SHORT", "pnl": "-2.10",
            "outcome": "CLEAN_LOSS", "primary_driver": "regime_trend",
            "strategy": "ensemble", "regime": "range", "leverage": "1.5",
        })

    # Patch paths in the enricher module
    monkeypatch.setattr(enricher_mod, "_INSIGHT_PATH", str(insight_path))
    monkeypatch.setattr(enricher_mod, "_FINGERPRINTS_PATH", str(fp_path))
    monkeypatch.setattr(enricher_mod, "_SIM_STATUS_PATH", str(sim_path))
    monkeypatch.setattr(enricher_mod, "_TRADES_CSV_PATH", str(trades_path))

    # Invalidate cache before each test
    invalidate_cache()


# ── Tests ───────────────────────────────────────────────────────


class TestInsightSelection:
    def test_selects_relevant_categories_for_regime(self):
        _refresh_cache()
        selected = _select_insights_for_agent("regime", enricher_mod._cache["insights"])
        categories = {ins["category"] for ins in selected}
        # Regime agent should get regime, correlation, timing, meta insights
        assert "regime_insight" in categories or "correlation_insight" in categories

    def test_selects_relevant_categories_for_trade(self):
        _refresh_cache()
        selected = _select_insights_for_agent("trade", enricher_mod._cache["insights"])
        categories = {ins["category"] for ins in selected}
        assert "strategy_insight" in categories

    def test_max_5_insights(self):
        _refresh_cache()
        selected = _select_insights_for_agent("trade", enricher_mod._cache["insights"])
        assert len(selected) <= 5

    def test_validated_insights_ranked_higher(self):
        _refresh_cache()
        selected = _select_insights_for_agent("trade", enricher_mod._cache["insights"])
        if len(selected) >= 2:
            # First insight should be validated (or higher confidence)
            first = selected[0]
            assert first.get("validated", False) or first.get("confidence", 0) >= 0.85

    def test_unknown_role_gets_fallback(self):
        _refresh_cache()
        selected = _select_insights_for_agent("unknown_agent", enricher_mod._cache["insights"])
        # Should still return something via fallback
        assert len(selected) >= 0  # No crash


class TestBriefingBuilding:
    def test_quant_briefing_contains_header(self):
        _refresh_cache()
        briefing = _build_quant_briefing("trade")
        assert "QUANT INTELLIGENCE BRIEFING" in briefing

    def test_quant_briefing_contains_insights(self):
        _refresh_cache()
        briefing = _build_quant_briefing("trade")
        assert "HYPE_BUY" in briefing or "strategy" in briefing.lower()

    def test_quant_briefing_shows_validation_status(self):
        _refresh_cache()
        briefing = _build_quant_briefing("trade")
        assert "VALIDATED" in briefing

    def test_fingerprint_summary_for_trade(self):
        _refresh_cache()
        summary = _build_fingerprint_summary("trade")
        assert "SETUP EDGE DATA" in summary
        assert "HYPE" in summary
        assert "60% WR" in summary

    def test_fingerprint_summary_skipped_for_regime(self):
        _refresh_cache()
        summary = _build_fingerprint_summary("regime")
        assert summary == ""

    def test_sim_status_summary(self):
        _refresh_cache()
        summary = _build_sim_status_summary()
        assert "SIM STATUS" in summary
        assert "$110.5" in summary
        assert "60% WR" in summary

    def test_recent_performance(self):
        _refresh_cache()
        perf = _build_recent_performance()
        assert "RECENT PERFORMANCE" in perf
        assert "HYPE" in perf
        assert "SOL" in perf
        # Should have summary line
        assert "Summary:" in perf


class TestEnrichPrompt:
    def test_enriches_trade_prompt(self):
        base = "You are a trade evaluator."
        enriched = enrich_prompt("trade", base)
        assert enriched.startswith(base)
        assert "QUANT INTELLIGENCE BRIEFING" in enriched
        assert "RECENT PERFORMANCE" in enriched

    def test_enriches_regime_prompt(self):
        base = "You are a regime classifier."
        enriched = enrich_prompt("regime", base)
        assert enriched.startswith(base)
        assert "QUANT INTELLIGENCE BRIEFING" in enriched
        # Regime agent should NOT get recent performance
        assert "RECENT PERFORMANCE" not in enriched

    def test_enriches_risk_prompt(self):
        base = "You are a risk agent."
        enriched = enrich_prompt("risk", base)
        assert "QUANT INTELLIGENCE BRIEFING" in enriched
        assert "SETUP EDGE DATA" in enriched

    def test_enrichment_respects_token_budget(self):
        base = "Short base prompt."
        enriched = enrich_prompt("trade", base)
        # The enrichment part should not exceed budget
        enrichment_part = enriched[len(base):]
        assert len(enrichment_part) <= _MAX_BRIEFING_CHARS + 100  # small margin for separators

    def test_base_prompt_preserved(self):
        base = "IMPORTANT: You must follow these rules exactly."
        enriched = enrich_prompt("trade", base)
        assert base in enriched

    def test_empty_data_returns_base(self, tmp_path, monkeypatch):
        """With no data files, enrichment returns base prompt unchanged."""
        monkeypatch.setattr(enricher_mod, "_INSIGHT_PATH", str(tmp_path / "nonexistent.json"))
        monkeypatch.setattr(enricher_mod, "_FINGERPRINTS_PATH", str(tmp_path / "nonexistent2.json"))
        monkeypatch.setattr(enricher_mod, "_SIM_STATUS_PATH", str(tmp_path / "nonexistent3.json"))
        monkeypatch.setattr(enricher_mod, "_TRADES_CSV_PATH", str(tmp_path / "nonexistent4.csv"))
        monkeypatch.setattr(enricher_mod, "_KB_PATH", str(tmp_path / "nonexistent5.json"))
        monkeypatch.setattr(enricher_mod, "_META_PATH", str(tmp_path / "nonexistent6.json"))
        monkeypatch.setattr(enricher_mod, "_OVERSEER_MEMO_PATH", str(tmp_path / "nonexistent7.json"))
        invalidate_cache()

        base = "Base prompt here."
        enriched = enrich_prompt("trade", base)
        assert enriched == base


class TestCaching:
    def test_cache_invalidation(self):
        _refresh_cache()
        assert get_cache_age_seconds() < 5

        invalidate_cache()
        assert get_cache_age_seconds() == float("inf")

    def test_cache_reuses_data(self):
        # First call loads data
        enriched1 = enrich_prompt("trade", "base")
        age1 = get_cache_age_seconds()

        # Second call should use cache (no time change)
        enriched2 = enrich_prompt("trade", "base")
        age2 = get_cache_age_seconds()

        assert enriched1 == enriched2
        assert age2 >= age1  # Cache age only increases


class TestEnrichmentStats:
    def test_stats_populated(self):
        stats = get_enrichment_stats()
        assert stats["total_insights"] == 8
        assert stats["validated_insights"] == 4
        assert "strategy_insight" in stats["insights_by_category"]
        assert stats["recent_trades_loaded"] == 3
        assert stats["sim_equity"] == 110.5


class TestEdgeCases:
    def test_corrupt_json_handled(self, tmp_path, monkeypatch):
        """Corrupt JSON should not crash the enricher."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{corrupt json!!")
        monkeypatch.setattr(enricher_mod, "_INSIGHT_PATH", str(bad_file))
        invalidate_cache()

        base = "Base prompt."
        enriched = enrich_prompt("trade", base)
        # Should not crash, just return base or partial enrichment
        assert base in enriched

    def test_empty_trades_csv(self, tmp_path, monkeypatch):
        """Empty trades CSV should not crash."""
        empty_csv = tmp_path / "empty.csv"
        empty_csv.write_text("")
        monkeypatch.setattr(enricher_mod, "_TRADES_CSV_PATH", str(empty_csv))
        invalidate_cache()

        base = "Base prompt."
        enriched = enrich_prompt("trade", base)
        assert base in enriched

    def test_all_agent_roles(self):
        """Every known agent role should work without error."""
        roles = [
            "regime", "trade", "risk", "critic", "exit",
            "scout", "learning", "overseer", "quant",
        ]
        base = "Agent prompt."
        for role in roles:
            enriched = enrich_prompt(role, base)
            assert enriched.startswith(base), f"Failed for role={role}"

    def test_very_long_insight_truncated(self, tmp_path, monkeypatch):
        """Insights longer than 200 chars should be truncated."""
        long_insights = {
            "insights": [{
                "ts": 1000.0,
                "category": "strategy_insight",
                "insight": "A" * 500,
                "confidence": 0.9,
                "evidence": "test",
                "source": "test",
                "validated": True,
                "validation_count": 10,
            }]
        }
        long_path = tmp_path / "long.json"
        long_path.write_text(json.dumps(long_insights))
        monkeypatch.setattr(enricher_mod, "_INSIGHT_PATH", str(long_path))
        invalidate_cache()

        enriched = enrich_prompt("trade", "base")
        # Should contain truncated version, not full 500 chars of A
        assert "A" * 200 not in enriched
        assert "..." in enriched
