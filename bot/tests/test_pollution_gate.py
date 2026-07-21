"""Tests for core/provenance.py -- the write-time pollution filter.

Guards against a repeat of the 253-fabricated-POPCAT-row incident (a
backtest run appended simulated trade outcomes into the live
trade_outcomes.csv) and the stray "TEST" key written into the live
momentum_state.json. See core/provenance.py's module docstring for full
incident context.

Every test here uses tmp_path / monkeypatch and MUST NOT touch any real
data file under bot/data/.
"""
from __future__ import annotations

import json
import os

import pytest

from core import provenance
from core.provenance import (
    PollutionError,
    QuarantineError,
    Source,
    gate_live_write,
    is_real_event,
    quarantine,
    resolve_source,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def sandbox_data_dir(tmp_path, monkeypatch):
    """Point core.paths.DATA_DIR at an isolated tmp directory so gate tests
    can simulate a "live" path without ever touching the real bot/data/."""
    fake_data_dir = tmp_path / "data"
    fake_data_dir.mkdir()
    monkeypatch.setattr("core.paths.DATA_DIR", fake_data_dir)
    return fake_data_dir


# ---------------------------------------------------------------------------
# gate_live_write
# ---------------------------------------------------------------------------
class TestGateLiveWrite:
    @pytest.mark.parametrize("source", [Source.BACKTEST, Source.TEST, Source.SIM, "backtest", "test", "sim"])
    def test_raises_for_simulated_source_targeting_live_file(self, sandbox_data_dir, source):
        live_target = sandbox_data_dir / "analysis" / "trade_outcomes.csv"
        with pytest.raises(PollutionError):
            gate_live_write(live_target, source=source)

    @pytest.mark.parametrize("source", [Source.LIVE, Source.PAPER, "live", "paper"])
    def test_noop_for_real_source(self, sandbox_data_dir, source):
        live_target = sandbox_data_dir / "analysis" / "trade_outcomes.csv"
        # Should not raise.
        gate_live_write(live_target, source=source)

    def test_noop_for_simulated_source_targeting_non_live_path(self, sandbox_data_dir, tmp_path):
        # A path entirely outside DATA_DIR (e.g. a scratch tmp file) is not
        # this gate's concern regardless of source.
        outside_target = tmp_path / "somewhere_else" / "scratch.csv"
        gate_live_write(outside_target, source=Source.BACKTEST)

    def test_noop_for_simulated_source_targeting_backtest_runs_sink(self, sandbox_data_dir):
        # A run-scoped backtest sink lives under DATA_DIR but is explicitly
        # exempted -- this is how backtest engine redirection stays legal.
        run_scoped = sandbox_data_dir / "backtest_runs" / "run123" / "trade_outcomes.csv"
        gate_live_write(run_scoped, source=Source.BACKTEST)

    def test_noop_for_simulated_source_targeting_quarantine_sink(self, sandbox_data_dir):
        quarantine_target = sandbox_data_dir / "quarantine" / "trade_outcomes.jsonl"
        gate_live_write(quarantine_target, source=Source.TEST)

    def test_pytest_context_autodetects_as_test_and_blocks(self, sandbox_data_dir):
        # PYTEST_CURRENT_TEST is set by the test runner itself right now --
        # no source= passed, so resolution must fall through to TEST.
        assert os.environ.get("PYTEST_CURRENT_TEST")
        live_target = sandbox_data_dir / "trade_ledger.csv"
        with pytest.raises(PollutionError):
            gate_live_write(live_target)

    def test_env_wagmi_source_paper_is_noop(self, sandbox_data_dir, monkeypatch):
        monkeypatch.setenv("WAGMI_SOURCE", "paper")
        live_target = sandbox_data_dir / "trade_ledger.csv"
        gate_live_write(live_target)  # no raise

    def test_env_wagmi_source_backtest_blocks(self, sandbox_data_dir, monkeypatch):
        monkeypatch.setenv("WAGMI_SOURCE", "backtest")
        live_target = sandbox_data_dir / "trade_ledger.csv"
        with pytest.raises(PollutionError):
            gate_live_write(live_target)


# ---------------------------------------------------------------------------
# resolve_source
# ---------------------------------------------------------------------------
class TestResolveSource:
    def test_explicit_source_wins(self, monkeypatch):
        monkeypatch.setenv("WAGMI_SOURCE", "paper")
        assert resolve_source(Source.BACKTEST) == Source.BACKTEST

    def test_environment_paper_resolves_real(self, monkeypatch):
        monkeypatch.delenv("WAGMI_SOURCE", raising=False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setenv("ENVIRONMENT", "paper")
        assert resolve_source() == Source.PAPER

    def test_environment_production_resolves_live(self, monkeypatch):
        monkeypatch.delenv("WAGMI_SOURCE", raising=False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setenv("ENVIRONMENT", "production")
        assert resolve_source() == Source.LIVE

    def test_ambiguous_defaults_to_paper_not_a_raise(self, monkeypatch):
        # No source, no env, no pytest marker -- must default to a REAL
        # source (PAPER), never to a simulated one. This is the "conservative
        # about NOT blocking real writes" requirement.
        monkeypatch.delenv("WAGMI_SOURCE", raising=False)
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        assert resolve_source() == Source.PAPER


# ---------------------------------------------------------------------------
# is_real_event
# ---------------------------------------------------------------------------
class TestIsRealEvent:
    def _valid_record(self):
        return {"symbol": "BTC", "side": "BUY", "pnl": 12.34, "outcome": "WIN"}

    def test_accepts_well_formed_record(self):
        assert is_real_event(self._valid_record()) is True

    def test_rejects_record_with_test_key(self):
        record = self._valid_record()
        record["TEST"] = True
        assert is_real_event(record) is False

    def test_rejects_missing_required_field(self):
        record = self._valid_record()
        del record["pnl"]
        assert is_real_event(record) is False

    def test_rejects_test_symbol(self):
        record = self._valid_record()
        record["symbol"] = "TESTUSD"
        assert is_real_event(record) is False

    def test_rejects_sim_flag_true(self):
        record = self._valid_record()
        record["is_backtest"] = True
        assert is_real_event(record) is False

    def test_rejects_non_numeric_pnl(self):
        record = self._valid_record()
        record["pnl"] = "not-a-number"
        assert is_real_event(record) is False

    def test_rejects_non_dict(self):
        assert is_real_event(["not", "a", "dict"]) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# quarantine
# ---------------------------------------------------------------------------
class TestQuarantine:
    def test_writes_record_to_quarantine_sink(self, sandbox_data_dir):
        record = {"symbol": "TESTUSD", "side": "BUY", "pnl": 1.0}
        live_target = sandbox_data_dir / "analysis" / "trade_outcomes.csv"

        sink_path = quarantine(record, reason="test symbol marker", target_path=live_target)

        assert sink_path.exists()
        assert sink_path.parent == sandbox_data_dir / "quarantine"
        lines = sink_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["reason"] == "test symbol marker"
        assert entry["record"] == record
        assert "timestamp" in entry

    def test_does_not_write_live_target(self, sandbox_data_dir):
        record = {"symbol": "TESTUSD", "side": "BUY", "pnl": 1.0}
        live_target = sandbox_data_dir / "analysis" / "trade_outcomes.csv"

        quarantine(record, reason="malformed", target_path=live_target)

        assert not live_target.exists()

    def test_appends_multiple_records(self, sandbox_data_dir):
        live_target = sandbox_data_dir / "trade_ledger.csv"
        quarantine({"symbol": "A"}, reason="r1", target_path=live_target)
        sink_path = quarantine({"symbol": "B"}, reason="r2", target_path=live_target)
        lines = sink_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2

    def test_quarantine_failure_raises_not_swallows(self, sandbox_data_dir, monkeypatch):
        # Simulate a sink that cannot be created (permission-style failure)
        # by monkeypatching Path.mkdir to blow up -- quarantine() must raise
        # QuarantineError, never silently return/drop the record.
        import pathlib

        def _boom(self, *a, **kw):
            raise OSError("simulated disk failure")

        monkeypatch.setattr(pathlib.Path, "mkdir", _boom)
        live_target = sandbox_data_dir / "trade_ledger.csv"
        with pytest.raises(QuarantineError):
            quarantine({"symbol": "A"}, reason="r", target_path=live_target)
