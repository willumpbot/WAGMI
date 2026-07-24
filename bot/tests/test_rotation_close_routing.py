"""
Structural + config tests: rotation closes route through the booked per-event
loop (no double-book), and TELEGRAM_CLOSE is in the loop's allowlists.

_execute_rotation must NOT book the close directly anymore -- the per-event loop
(multi_strategy_main.py) does update_equity + log_trade + FULL_CLOSE fan-out +
shadow tap + cooldown/_last_close_win EXACTLY once for the injected event. So the
old direct `self.risk_mgr.update_equity(close_event.pnl - close_event.fee)` and
`log_trade(...)` inside _execute_rotation were removed (they were the double-book);
the close_event must instead be stamped _exchange_submitted and appended to
_pending_exit_events. TELEGRAM_CLOSE must be in BOTH _FULL_CLOSE (else the
learning/CloseBus fan-out is skipped) and _close_actions.

These are source/AST assertions (no full-bot bring-up needed); the loop's
once-only booking is covered by the existing e2e suite.
"""
import ast
import unittest
from pathlib import Path

BOT = Path(__file__).parent.parent
PW = BOT / "core" / "position_wiring.py"
MSM = BOT / "multi_strategy_main.py"


def _func_node(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {path}")


class TestRotationRoutesNotDoubleBooks(unittest.TestCase):
    def setUp(self):
        self.all_src = PW.read_text(encoding="utf-8")
        self.fn = _func_node(PW, "_execute_rotation")
        self.fn_src = ast.get_source_segment(self.all_src, self.fn) or ""
        self.assertTrue(self.fn_src, "could not extract _execute_rotation source")

    def test_direct_equity_booking_removed(self):
        # The exact double-book line vs the loop's unconditional update_equity.
        self.assertNotIn(
            "self.risk_mgr.update_equity(close_event.pnl - close_event.fee)",
            self.fn_src,
            "rotation still books equity directly -- double-book vs the per-event loop",
        )

    def test_no_direct_log_trade_of_the_close(self):
        # No log_trade call inside _execute_rotation (the close is now logged by
        # the loop). A log_trade here would double-write the ledger row.
        log_trade_calls = [
            n for n in ast.walk(self.fn)
            if isinstance(n, ast.Call) and (
                (isinstance(n.func, ast.Name) and n.func.id == "log_trade")
                or (isinstance(n.func, ast.Attribute) and n.func.attr == "log_trade")
            )
        ]
        self.assertEqual(
            log_trade_calls, [],
            "rotation still calls log_trade directly -- double-book vs the loop",
        )

    def test_no_bare_force_close_discarded(self):
        # force_close's return value must be captured (assigned), never a bare
        # expression statement (the discarded-return silent-drop shape).
        bare = [
            n.value.lineno for n in ast.walk(self.fn)
            if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
            and isinstance(n.value.func, ast.Attribute)
            and n.value.func.attr == "force_close"
        ]
        self.assertEqual(bare, [], f"bare force_close (discarded) at lines {bare}")

    def test_routes_via_pending_exit_events(self):
        self.assertIn("_pending_exit_events.append(close_event)", self.fn_src)

    def test_stamps_exchange_submitted(self):
        self.assertIn('close_event.metadata["_exchange_submitted"] = True', self.fn_src)

    def test_preserves_rotation_metadata(self):
        for key in ("rotation_to", "rotation_reason", "rotation_rr_improvement"):
            self.assertIn(key, self.fn_src,
                          f"rotation metadata {key!r} dropped from the routed event")


class TestTelegramCloseInLoopAllowlists(unittest.TestCase):
    def test_telegram_close_in_full_close_and_close_actions(self):
        src = MSM.read_text(encoding="utf-8")
        # Present in both _FULL_CLOSE and _close_actions tuples -> at least twice.
        self.assertGreaterEqual(
            src.count('"TELEGRAM_CLOSE"'), 2,
            "TELEGRAM_CLOSE must be in BOTH _FULL_CLOSE and _close_actions "
            "(else equity+ledger book but the learning/CloseBus fan-out is skipped)",
        )


if __name__ == "__main__":
    unittest.main()
