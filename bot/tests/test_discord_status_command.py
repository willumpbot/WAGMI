"""Tests for the `status` command added to tools/copilot/discord_call_listener.py.

The listener shells out based on network input, so its security model is strict:
owner-only, single channel, whitelist parse, fixed argv, shell=False. `status`
is the one verb that carries NO user input — these tests pin that property so a
later edit cannot quietly turn it into an argument-taking command.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "copilot"))

import discord_call_listener as dcl  # noqa: E402


@pytest.mark.parametrize("text", ["status", "Status", "STATUS", "  status  ", "\tstatus\n"])
def test_bare_status_is_recognized(text):
    outcome, payload = dcl.parse_call_command(text)
    assert outcome == dcl.STATUS
    assert payload is None


@pytest.mark.parametrize("text", [
    "status now", "statuses", "status --leverage 3", "status; rm -rf /",
    "status BTC", "please status", "", "   ",
])
def test_anything_other_than_a_bare_status_is_not_status(text):
    outcome, _ = dcl.parse_call_command(text)
    assert outcome != dcl.STATUS


def test_status_does_not_shadow_the_call_grammar():
    outcome, payload = dcl.parse_call_command("call BTC long reclaimed vwap")
    assert outcome == dcl.RUN
    assert payload[0] == "BTC" and payload[1] == "long"


def test_status_argv_is_constant_and_shell_free(monkeypatch):
    """No element of the argv may come from a message, and shell must be off."""
    seen = {}

    class _Proc:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def _fake_run(argv, **kw):
        seen["argv"] = argv
        seen["kw"] = kw
        return _Proc()

    monkeypatch.setattr(dcl.subprocess, "run", _fake_run)
    dcl.execute_status()

    assert seen["argv"] == [sys.executable, dcl.DIGEST_REL, "--no-send"]
    assert seen["kw"]["shell"] is False
    assert seen["kw"]["timeout"] == 60
    assert seen["kw"]["cwd"] == dcl.BOT_DIR


def test_status_never_raises_on_launch_failure(monkeypatch):
    def _boom(*a, **kw):
        raise OSError("no python here")
    monkeypatch.setattr(dcl.subprocess, "run", _boom)
    out = dcl.execute_status()
    assert "could not be launched" in out


def test_status_never_raises_on_timeout(monkeypatch):
    def _timeout(*a, **kw):
        raise dcl.subprocess.TimeoutExpired(cmd="x", timeout=60)
    monkeypatch.setattr(dcl.subprocess, "run", _timeout)
    out = dcl.execute_status()
    assert "timed out" in out


def test_status_reply_fits_discord_limit(monkeypatch):
    class _Proc:
        returncode = 0
        stdout = "x" * 50_000
        stderr = ""
    monkeypatch.setattr(dcl.subprocess, "run", lambda *a, **kw: _Proc())
    out = dcl.execute_status()
    assert len(out) <= dcl.DISCORD_MSG_LIMIT


def test_status_reports_a_failing_exit_without_a_traceback(monkeypatch):
    class _Proc:
        returncode = 3
        stdout = ""
        stderr = "Traceback (most recent call last):\n  secret internals\n"
    monkeypatch.setattr(dcl.subprocess, "run", lambda *a, **kw: _Proc())
    out = dcl.execute_status()
    assert "status failed (exit 3)" in out
    assert "Traceback" not in out


def test_authorization_is_unchanged_and_still_requires_both():
    assert dcl.authorize(1, 2, 1, 2) is True
    assert dcl.authorize(9, 2, 1, 2) is False      # wrong user
    assert dcl.authorize(1, 9, 1, 2) is False      # wrong channel
