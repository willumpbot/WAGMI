"""
Phase 0.4-A2: regression tests for the LLM_EXIT_HIGH/CRITICAL NameError.

WHY THIS EXISTS: core/llm_integration.py's `_run_exit_agent_checks` gives the
Exit Intelligence Agent "teeth" — when it reports urgency high/critical and
action full_close/close, it force-closes the position. The force-close block
used a BARE `_last_prices` name (every other reference in the file is
`self._last_prices`), which raised `NameError: name '_last_prices' is not
defined` on every single invocation. Because that block sits inside its own
`try/except Exception` (so the surrounding per-position loop never crashes),
the bug was silent: the Exit Agent's urgent-close path has been fully DEAD in
production — it always logs the "FORCE-CLOSED by LLM" intent but the
NameError swallows the actual `force_close()` call before it happens.

THIS IS A LIVE BUG. This test file lives ONLY in the isolated worktree
(claude/measurement-integrity, C:\\Users\\vince\\WAGMI_measurework). The fix
(core/llm_integration.py ~:1227, `_last_prices` -> `self._last_prices`) has
NOT been applied to the live bot tree (C:\\Users\\vince\\WAGMI) as part of
this change — see the Phase 0.4-A report for the owner's separate hotfix
decision.

Two layers of protection:
  1. A static AST guard: no bare `_last_prices` Name node may exist anywhere
     in core/llm_integration.py. This is the narrowest possible check and
     would have caught the exact original bug (and prevents reintroduction
     anywhere else in the file, not just the one fixed line).
  2. A behavioral test: force the urgent-exit branch with a mocked
     coordinator + mocked position manager, and assert `force_close()` is
     actually invoked. Before the fix, the NameError was silently caught by
     the inner `except Exception`, so `force_close()` was NEVER called even
     though the urgency/action gate matched -- the pre-fix version of this
     test fails on the `assert_called_once_with` (not on an uncaught
     NameError, since the bug was self-swallowing).
"""

import ast
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

_LLM_INTEGRATION_PATH = os.path.join(
    os.path.dirname(__file__), "..", "core", "llm_integration.py"
)


class TestNoBareLastPricesReference(unittest.TestCase):
    """Static guard: every `_last_prices` use must be `self._last_prices`."""

    def test_no_bare_last_prices_name_node(self):
        with open(_LLM_INTEGRATION_PATH, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename=_LLM_INTEGRATION_PATH)

        bare_refs = []
        for node in ast.walk(tree):
            # A bare `_last_prices` reference parses as ast.Name(id='_last_prices').
            # `self._last_prices` parses as ast.Attribute(attr='_last_prices',
            # value=ast.Name(id='self')) -- the Name node there is 'self', not
            # '_last_prices' -- so this walk only matches the buggy pattern.
            if isinstance(node, ast.Name) and node.id == "_last_prices":
                bare_refs.append(node.lineno)

        self.assertEqual(
            bare_refs, [],
            f"Found bare `_last_prices` reference(s) at line(s) {bare_refs} in "
            f"core/llm_integration.py -- must be `self._last_prices` (NameError "
            f"regression; see the LLM_EXIT_HIGH/CRITICAL dead-path bug).",
        )


class TestUrgentExitForceClosesWithoutNameError(unittest.TestCase):
    """Behavioral: urgency=critical + action=full_close must reach force_close()."""

    def _build_self(self, last_price=101.0):
        from core.llm_integration import LLMIntegrationMixin

        class _FakeBot(LLMIntegrationMixin):
            """Minimal stand-in for MultiStrategyBot exposing only what
            _run_exit_agent_checks touches via `self.*`."""

        obj = _FakeBot()

        fake_pos = MagicMock()
        fake_pos.state = "OPEN"
        fake_pos.side = "LONG"
        fake_pos.entry = 100.0
        fake_pos.sl = 95.0
        fake_pos.tp1 = 110.0
        fake_pos.tp2 = 120.0
        fake_pos.qty = 1.0
        fake_pos.leverage = 1.0
        fake_pos.confidence = 80
        fake_pos.open_time = datetime.now(timezone.utc)

        obj.pos_mgr = MagicMock()
        obj.pos_mgr.positions = {"BTC": fake_pos}
        obj.pos_mgr.force_close = MagicMock()
        obj._last_prices = {"BTC": last_price}
        obj._tick_regime_cache = {}
        return obj

    def test_critical_full_close_invokes_force_close(self):
        obj = self._build_self(last_price=101.0)

        mock_coordinator = MagicMock()
        mock_coordinator.get_exit_intelligence.return_value = {
            "action": "full_close",
            "urgency": "critical",
            "reason": "thesis broken",
        }

        with patch("llm.autonomy.get_llm_mode", return_value=object()), \
             patch("llm.autonomy.should_call_llm", return_value=True), \
             patch("llm.agents.coordinator.get_coordinator", return_value=mock_coordinator), \
             patch("llm.agents.coordinator.is_multi_agent_enabled", return_value=True):
            # Must not raise -- and, more importantly, must actually reach
            # force_close() rather than silently swallowing a NameError.
            obj._run_exit_agent_checks(trace_id="test-trace")

        obj.pos_mgr.force_close.assert_called_once_with("BTC", 101.0, "LLM_EXIT_CRITICAL")

    def test_high_close_invokes_force_close(self):
        obj = self._build_self(last_price=250.5)

        mock_coordinator = MagicMock()
        mock_coordinator.get_exit_intelligence.return_value = {
            "action": "close",
            "urgency": "high",
            "reason": "regime flip",
        }

        with patch("llm.autonomy.get_llm_mode", return_value=object()), \
             patch("llm.autonomy.should_call_llm", return_value=True), \
             patch("llm.agents.coordinator.get_coordinator", return_value=mock_coordinator), \
             patch("llm.agents.coordinator.is_multi_agent_enabled", return_value=True):
            obj._run_exit_agent_checks(trace_id="test-trace")

        obj.pos_mgr.force_close.assert_called_once_with("BTC", 250.5, "LLM_EXIT_HIGH")

    def test_hold_action_does_not_force_close(self):
        """Sanity check: the mock harness itself doesn't force-close on a
        non-urgent verdict (guards against a test that trivially passes)."""
        obj = self._build_self(last_price=101.0)

        mock_coordinator = MagicMock()
        mock_coordinator.get_exit_intelligence.return_value = {
            "action": "hold",
            "urgency": "low",
            "reason": "thesis intact",
        }

        with patch("llm.autonomy.get_llm_mode", return_value=object()), \
             patch("llm.autonomy.should_call_llm", return_value=True), \
             patch("llm.agents.coordinator.get_coordinator", return_value=mock_coordinator), \
             patch("llm.agents.coordinator.is_multi_agent_enabled", return_value=True):
            obj._run_exit_agent_checks(trace_id="test-trace")

        obj.pos_mgr.force_close.assert_not_called()


if __name__ == "__main__":
    unittest.main()
