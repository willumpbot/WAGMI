"""Tests for core/paths.py — canonical __file__-anchored paths + boot
integrity assertion.

Every test here is fully sandboxed: no test reads, writes, or creates
anything under a REAL data/ directory. Real BOT_ROOT/DATA_DIR resolution is
checked only via the module's own constants (never by touching files under
them); all integrity-check and orphan-detection tests operate exclusively
inside pytest's tmp_path fixture.
"""

import importlib
import os
import sys
from pathlib import Path

import pytest

_BOT_ROOT = Path(__file__).resolve().parent.parent
if str(_BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOT_ROOT))

import core.paths as paths_module  # noqa: E402


@pytest.fixture(autouse=True)
def _restore_cwd():
    """Every test may chdir; always restore the original cwd afterward so
    this test file never leaves the process pointed somewhere unexpected
    for subsequent tests / the pytest runner itself."""
    original = os.getcwd()
    yield
    os.chdir(original)


# ---------------------------------------------------------------------------
# BOT_ROOT / DATA_DIR resolve correctly regardless of cwd.
# ---------------------------------------------------------------------------

def test_bot_root_is_the_bot_directory():
    assert paths_module.BOT_ROOT.name == "bot"
    assert paths_module.BOT_ROOT == _BOT_ROOT


def test_data_dir_is_bot_root_slash_data():
    assert paths_module.DATA_DIR == paths_module.BOT_ROOT / "data"


def test_paths_stable_across_cwd_change(tmp_path, monkeypatch):
    """The whole point of __file__-anchoring: changing cwd must NOT change
    where BOT_ROOT/DATA_DIR point. Reload the module from a temp cwd and
    confirm the anchors are identical to the un-chdir'd case."""
    monkeypatch.chdir(tmp_path)
    reloaded = importlib.reload(paths_module)
    try:
        assert reloaded.BOT_ROOT == _BOT_ROOT
        assert reloaded.DATA_DIR == _BOT_ROOT / "data"
        # Accessors must also stay anchored to the real bot/, not tmp_path.
        assert reloaded.trade_ledger_path() == _BOT_ROOT / "data" / "trade_ledger.csv"
        assert str(tmp_path) not in str(reloaded.trade_ledger_path())
    finally:
        importlib.reload(paths_module)  # leave module state clean for later tests


def test_accessors_return_paths_under_data_dir():
    accessors = [
        paths_module.trade_ledger_path,
        paths_module.position_state_path,
        paths_module.risk_equity_state_path,
        paths_module.circuit_breaker_state_path,
        paths_module.heartbeat_path,
        paths_module.epoch_start_path,
    ]
    for accessor in accessors:
        p = accessor()
        assert isinstance(p, Path)
        assert p.parent == paths_module.DATA_DIR
        assert p.is_absolute()


def test_accessor_filenames_match_known_brain_files():
    assert paths_module.trade_ledger_path().name == "trade_ledger.csv"
    assert paths_module.position_state_path().name == "position_state.json"
    assert paths_module.risk_equity_state_path().name == "risk_equity_state.json"
    assert paths_module.circuit_breaker_state_path().name == "circuit_breaker_state.json"
    assert paths_module.heartbeat_path().name == "heartbeat.json"
    assert paths_module.epoch_start_path().name == "epoch_start.json"


# ---------------------------------------------------------------------------
# assert_boot_integrity() — must RAISE rather than silently proceed, and
# must NEVER touch real data/. Every case here monkeypatches DATA_DIR /
# trade_ledger_path onto a tmp_path structure.
# ---------------------------------------------------------------------------

def test_assert_boot_integrity_raises_when_data_dir_missing(tmp_path, monkeypatch):
    fake_data_dir = tmp_path / "does_not_exist"
    monkeypatch.setattr(paths_module, "DATA_DIR", fake_data_dir)
    with pytest.raises(paths_module.BootIntegrityError, match="DATA_DIR"):
        paths_module.assert_boot_integrity()


def test_assert_boot_integrity_raises_when_ledger_missing(tmp_path, monkeypatch):
    fake_data_dir = tmp_path / "data"
    fake_data_dir.mkdir()
    monkeypatch.setattr(paths_module, "DATA_DIR", fake_data_dir)
    monkeypatch.setattr(
        paths_module, "_REQUIRED_NONEMPTY", (lambda: fake_data_dir / "trade_ledger.csv",)
    )
    with pytest.raises(paths_module.BootIntegrityError, match="missing"):
        paths_module.assert_boot_integrity()


def test_assert_boot_integrity_raises_when_ledger_empty(tmp_path, monkeypatch):
    fake_data_dir = tmp_path / "data"
    fake_data_dir.mkdir()
    ledger = fake_data_dir / "trade_ledger.csv"
    ledger.write_text("")  # 0 bytes
    monkeypatch.setattr(paths_module, "DATA_DIR", fake_data_dir)
    monkeypatch.setattr(paths_module, "_REQUIRED_NONEMPTY", (lambda: ledger,))
    with pytest.raises(paths_module.BootIntegrityError, match="empty"):
        paths_module.assert_boot_integrity()


def test_assert_boot_integrity_never_autocreates(tmp_path, monkeypatch):
    """The core safety property: a missing ledger must abort loudly, and
    the function must not have created the ledger (or anything else) as a
    side effect of checking."""
    fake_data_dir = tmp_path / "data"
    fake_data_dir.mkdir()
    ledger = fake_data_dir / "trade_ledger.csv"
    monkeypatch.setattr(paths_module, "DATA_DIR", fake_data_dir)
    monkeypatch.setattr(paths_module, "_REQUIRED_NONEMPTY", (lambda: ledger,))
    with pytest.raises(paths_module.BootIntegrityError):
        paths_module.assert_boot_integrity()
    assert not ledger.exists(), "assert_boot_integrity must never auto-create the ledger"
    assert list(fake_data_dir.iterdir()) == [], "no side-effect files should be created"


def test_assert_boot_integrity_passes_and_normalizes_cwd(tmp_path, monkeypatch):
    """Happy path: valid data dir + non-empty ledger -> no raise, and cwd is
    normalized to (a stand-in for) BOT_ROOT."""
    fake_bot_root = tmp_path / "bot"
    fake_data_dir = fake_bot_root / "data"
    fake_data_dir.mkdir(parents=True)
    ledger = fake_data_dir / "trade_ledger.csv"
    ledger.write_text("timestamp,symbol,net_pnl\n1,BTC,1.0\n")

    monkeypatch.setattr(paths_module, "BOT_ROOT", fake_bot_root)
    monkeypatch.setattr(paths_module, "DATA_DIR", fake_data_dir)
    monkeypatch.setattr(paths_module, "_REQUIRED_NONEMPTY", (lambda: ledger,))

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    os.chdir(elsewhere)

    paths_module.assert_boot_integrity()  # must not raise

    assert Path(os.getcwd()).resolve() == fake_bot_root.resolve()


# ---------------------------------------------------------------------------
# detect_orphan_dirs() — read-only detection, never deletes.
# ---------------------------------------------------------------------------

def test_detect_orphan_dirs_finds_planted_orphan(tmp_path, monkeypatch):
    fake_bot_root = tmp_path / "bot"
    fake_bot_root.mkdir()
    orphan = tmp_path / "paper_trades"  # sibling of bot/, the exact incident shape
    orphan.mkdir()
    (orphan / "some_state.json").write_text("{}")

    monkeypatch.setattr(paths_module, "BOT_ROOT", fake_bot_root)

    found = paths_module.detect_orphan_dirs()
    assert orphan in found


def test_detect_orphan_dirs_empty_when_no_siblings(tmp_path, monkeypatch):
    fake_bot_root = tmp_path / "clean" / "bot"
    fake_bot_root.mkdir(parents=True)

    monkeypatch.setattr(paths_module, "BOT_ROOT", fake_bot_root)

    found = paths_module.detect_orphan_dirs()
    assert found == []


def test_detect_orphan_dirs_never_deletes(tmp_path, monkeypatch):
    fake_bot_root = tmp_path / "bot"
    fake_bot_root.mkdir()
    orphan = tmp_path / "data"
    orphan.mkdir()
    marker = orphan / "marker.txt"
    marker.write_text("still here")

    monkeypatch.setattr(paths_module, "BOT_ROOT", fake_bot_root)

    paths_module.detect_orphan_dirs()

    assert marker.exists()
    assert marker.read_text() == "still here"


def test_detect_orphan_dirs_readonly_on_real_bot_root():
    """Sanity check against the REAL BOT_ROOT (read-only os.path.is_dir
    checks only, no writes) -- confirms the function is safe to call
    unmocked without touching anything."""
    result = paths_module.detect_orphan_dirs()
    assert isinstance(result, list)
    assert all(isinstance(p, Path) for p in result)
