"""
Phase 0.4-A3: close_types.py registry tests + T-TAX taxonomy-drift guard.

Two test classes:

  TestCloseTypesRegistry -- consistency checks on core/close_types.py itself
  (count, kind/flag sanity, query helpers).

  TestTaxonomyDrift (T-TAX, spec04.md section (4)) -- statically greps the
  whole bot/ tree for close-reason/action string literals passed to
  force_close(), partial_close(), and _close_position(), and asserts every
  one of them is a registered name in core.close_types.CLOSE_TYPES. This is
  the drift guard: if someone adds a new close reason to the live code
  without registering it in close_types.py, this test fails in CI.
"""

import ast
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.close_types import (
    CLOSE_TYPES,
    CloseKind,
    CloseType,
    all_names,
    get,
    is_full,
    is_partial,
    live_types,
    mechanical,
)


# ---------------------------------------------------------------------------
# Registry consistency
# ---------------------------------------------------------------------------
class TestCloseTypesRegistry(unittest.TestCase):
    def test_total_count_is_27(self):
        self.assertEqual(len(CLOSE_TYPES), 27)
        self.assertEqual(len(all_names()), 27)

    def test_live_full_count_is_17(self):
        n = sum(1 for ct in CLOSE_TYPES.values()
                if ct.kind == CloseKind.FULL and ct.live and not ct.backtest_only and not ct.vestigial)
        self.assertEqual(n, 17)

    def test_live_partial_count_is_3(self):
        n = sum(1 for ct in CLOSE_TYPES.values()
                if ct.kind == CloseKind.PARTIAL and ct.live and not ct.backtest_only and not ct.vestigial)
        self.assertEqual(n, 3)

    def test_backtest_only_count_is_3(self):
        n = sum(1 for ct in CLOSE_TYPES.values() if ct.backtest_only)
        self.assertEqual(n, 3)

    def test_vestigial_count_is_4(self):
        n = sum(1 for ct in CLOSE_TYPES.values() if ct.vestigial)
        self.assertEqual(n, 4)
        self.assertEqual(
            {name for name, ct in CLOSE_TYPES.items() if ct.vestigial},
            {"EARLY_EXIT", "TIME_STOP", "EMERGENCY", "PARTIAL_CLOSE"},
        )

    def test_every_entry_key_matches_its_name_field(self):
        for key, ct in CLOSE_TYPES.items():
            self.assertEqual(key, ct.name)

    def test_backtest_only_implies_not_live(self):
        for name, ct in CLOSE_TYPES.items():
            if ct.backtest_only:
                self.assertFalse(ct.live, f"{name}: backtest_only=True but live=True")

    def test_partials_are_never_mechanical_except_documented_tp1(self):
        # TP1 is the one PM-internal partial leg the god-block special-cases
        # (spec04.md: "mechanical()... returns the set the god-block treats
        # as PM-internal SL/TP/TRAILING/TP1_FULL/TP2" -- TP1 itself is also
        # PM-internal, unlike LLM_EXIT_PARTIAL/EXIT_ENGINE_PARTIAL which are
        # helper-routed).
        for name, ct in CLOSE_TYPES.items():
            if ct.kind == CloseKind.PARTIAL and ct.mechanical:
                self.assertEqual(name, "TP1", f"unexpected mechanical partial: {name}")

    def test_mechanical_set_matches_spec(self):
        # spec04.md §(2): "mechanical() ... returns the set the god-block
        # treats as PM-internal SL/TP/TRAILING/TP1_FULL/TP2".
        self.assertEqual(
            mechanical(),
            frozenset({"SL", "TRAILING_STOP", "TP2", "TP1_FULL", "TP1"}),
        )

    def test_vestigial_types_have_no_producers_flag_consistent(self):
        # Vestigial types may still declare an exchange_order (metadata for
        # if a producer is ever added), but they must never be counted as
        # "live" reachable types.
        for name in ("EARLY_EXIT", "TIME_STOP", "EMERGENCY", "PARTIAL_CLOSE"):
            self.assertNotIn(name, live_types())

    def test_exchange_order_values_are_valid(self):
        valid = {"HELPER", "GOD_BLOCK_PM_INTERNAL", "NONE_OWNER_GATED"}
        for name, ct in CLOSE_TYPES.items():
            self.assertIn(ct.exchange_order, valid, f"{name}: bad exchange_order {ct.exchange_order!r}")

    def test_get_returns_none_for_unregistered(self):
        self.assertIsNone(get("NOT_A_REAL_CLOSE_TYPE"))

    def test_get_returns_entry_for_registered(self):
        ct = get("SL")
        self.assertIsInstance(ct, CloseType)
        self.assertEqual(ct.kind, CloseKind.FULL)

    def test_is_full_is_partial_agree_with_kind(self):
        for name, ct in CLOSE_TYPES.items():
            if ct.kind == CloseKind.FULL:
                self.assertTrue(is_full(name))
                self.assertFalse(is_partial(name))
            else:
                self.assertTrue(is_partial(name))
                self.assertFalse(is_full(name))
        self.assertFalse(is_full("NOT_A_REAL_CLOSE_TYPE"))
        self.assertFalse(is_partial("NOT_A_REAL_CLOSE_TYPE"))

    def test_leaf_module_imports_nothing_from_pm_or_main(self):
        """Static guard: close_types.py must not import position_manager or
        multi_strategy_main (leaf-module invariant, spec04.md §(2))."""
        path = Path(__file__).parent.parent / "core" / "close_types.py"
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename=str(path))
        banned_substrings = ("position_manager", "multi_strategy_main")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for bad in banned_substrings:
                        self.assertNotIn(bad, alias.name)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                for bad in banned_substrings:
                    self.assertNotIn(bad, mod)


# ---------------------------------------------------------------------------
# T-TAX: taxonomy drift guard
# ---------------------------------------------------------------------------
BOT_ROOT = Path(__file__).resolve().parent.parent

# spec04.md §(1) "Excluded": manual/pa simulator actions live in a separate
# PAPosition namespace (their own _close_position(pos, price, reason, now)
# with a 4-arg signature and lowercase reason strings like "tp_scalp") and
# are explicitly out of scope for this registry.
_EXCLUDED_DIRS = {(BOT_ROOT / "manual").resolve()}

# Which positional slot holds the reason/action for each target method, and
# how many total positional args a PositionManager-style call has when the
# reason/action is passed positionally (not via keyword). This disambiguates
# same-named methods on OTHER classes with different signatures -- notably
# manual/pa_simulator's own `_close_position(self, pos, exit_price,
# exit_reason, now)` (4 positional args) vs. PositionManager's
# `_close_position(self, pos, price, action)` (3 positional args). A call
# with a mismatched positional count is skipped rather than guessed at.
_METHOD_ARG_SPEC = {
    "force_close": {"index": 2, "count": 3, "keyword": "reason"},       # (symbol, price, reason)
    "partial_close": {"index": 3, "count": 4, "keyword": "action"},     # (symbol, pct, price, action)
    "_close_position": {"index": 2, "count": 3, "keyword": "action"},   # (pos, price, action)
}

# Literals that are test-scaffolding, not real production close reasons.
_TEST_ONLY_LITERALS = {"TEST", "TEST_FINAL"}

# This test file itself intentionally references many close-reason literals
# in docstrings/comments/asserts (not as force_close() call arguments) --
# excluded from the scan like any other tests/ file would be if it used
# non-registry literals. (In practice its own force_close-adjacent calls
# only use registry-valid names, so no exclusion is actually needed, but
# the AST walk only inspects Call nodes anyway -- docstrings never match.)


def _under_excluded_dir(path: Path) -> bool:
    resolved = path.resolve()
    return any(excluded in resolved.parents or excluded == resolved for excluded in _EXCLUDED_DIRS)


def _iter_py_files():
    for path in sorted(BOT_ROOT.rglob("*.py")):
        if _under_excluded_dir(path):
            continue
        yield path


def _method_name(call: ast.Call):
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr in _METHOD_ARG_SPEC:
        return func.attr
    if isinstance(func, ast.Name) and func.id in _METHOD_ARG_SPEC:
        return func.id
    return None


def _string_constants_from_call(call: ast.Call):
    """Yield every literal string close-reason/action argument passed to a
    force_close/partial_close/_close_position call, keyed by the method's
    known argument shape (see _METHOD_ARG_SPEC). Skipped by design (can't be
    statically resolved to a literal, or don't match this call shape):
      - variables / attribute lookups, e.g. `action.close_reason`
        (core/position_wiring.py rotation close) or the `action` local in
        `self._close_position(pos, current_price, action)`
        (execution/position_manager.py's SL/TRAILING_STOP dispatch)
      - f-strings, e.g. `f"LLM_EXIT_{urgency.upper()}"`
        (core/llm_integration.py)
      - calls whose positional-arg COUNT doesn't match the PositionManager
        shape for that method name, e.g. manual/pa_simulator's own 4-arg
        `_close_position(pos, exit_price, exit_reason, now)` (would collide
        with PositionManager's 3-arg version by name alone)
    """
    spec = _METHOD_ARG_SPEC[_method_name(call)]
    # Keyword form always wins when present, regardless of positional count
    # (covers calls like `partial_close("ETH", pct=0.5, price=110.0,
    # action="LLM_EXIT_PARTIAL")` where earlier params are also keywords).
    for kw in call.keywords:
        if kw.arg == spec["keyword"] and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            yield kw.value.value
            return
    # Positional form: only trust it when the call has exactly the expected
    # number of positional args for this method (no keywords covering the
    # reason/action slot), so we're reading the right index.
    if len(call.args) == spec["count"]:
        arg = call.args[spec["index"]]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            yield arg.value


def _scan_repo_for_close_reason_literals():
    """Returns dict: literal -> list of "relative/path.py:lineno" locations."""
    findings = {}
    for path in _iter_py_files():
        try:
            source = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue
        rel = path.relative_to(BOT_ROOT)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _method_name(node) is not None:
                for literal in _string_constants_from_call(node):
                    findings.setdefault(literal, []).append(f"{rel}:{node.lineno}")
    return findings


class TestTaxonomyDrift(unittest.TestCase):
    """T-TAX (spec04.md §(4)): grep repo for force_close()/partial_close()/
    _close_position() reason literals; assert set ⊆ CLOSE_TYPES registry."""

    @classmethod
    def setUpClass(cls):
        cls.findings = _scan_repo_for_close_reason_literals()

    def test_scan_actually_found_calls(self):
        # Sanity: if this is ever 0, the AST scanner itself is broken (wrong
        # root, method names changed, etc.) -- a silently-vacuous test is
        # worse than no test.
        self.assertGreater(
            len(self.findings), 10,
            "T-TAX scanner found suspiciously few close-reason literals -- "
            "verify _TARGET_METHODS / repo root are still correct.",
        )

    def test_every_production_close_reason_is_registered(self):
        unregistered = {
            literal: locs
            for literal, locs in self.findings.items()
            if literal not in _TEST_ONLY_LITERALS and literal not in CLOSE_TYPES
        }
        self.assertEqual(
            unregistered, {},
            "Found close-reason literal(s) passed to force_close()/"
            "partial_close()/_close_position() that are NOT registered in "
            "core/close_types.py CLOSE_TYPES:\n"
            + "\n".join(f"  {lit!r}: {locs}" for lit, locs in sorted(unregistered.items())),
        )

    # LIVE registry names that are never passed as a bare string literal to
    # force_close()/partial_close()/_close_position() -- each verified by
    # direct read, not guessed:
    #   TRAILING_STOP -- position_manager.py:1004 computes
    #     `action = "TRAILING_STOP" if pos.state == TRAILING else "SL"` then
    #     calls `self._close_position(pos, current_price, action)` -- a
    #     variable, not a literal, at the call site.
    #   TP1 -- built directly as `TradeEvent(action="TP1", ...)` inside
    #     `_partial_close_tp1()` (position_manager.py:~1641); TP1 never goes
    #     through partial_close()/force_close()/_close_position() at all.
    #   ROTATE_PROFIT / ROTATE_LOSS_AVOIDANCE -- set as literals on
    #     `RotationAction.close_reason` (execution/rotation_manager.py:405,
    #     434), then passed to force_close() as the variable
    #     `action.close_reason` (core/position_wiring.py:213) -- an
    #     attribute lookup, not a literal, at the force_close() call site.
    #   LLM_EXIT_HIGH / LLM_EXIT_CRITICAL -- only ever constructed via the
    #     f-string `f"LLM_EXIT_{urgency.upper()}"`
    #     (core/llm_integration.py:1229) -- an f-string (ast.JoinedStr), not
    #     a plain ast.Constant, so it can't be statically resolved to either
    #     literal name by this scanner.
    _KNOWN_NON_LITERAL_LIVE_TYPES = frozenset({
        "TRAILING_STOP", "TP1",
        "ROTATE_PROFIT", "ROTATE_LOSS_AVOIDANCE",
        "LLM_EXIT_HIGH", "LLM_EXIT_CRITICAL",
    })

    def test_known_production_reasons_are_all_found_by_the_scanner(self):
        # Cross-check in the other direction: every LIVE (non-vestigial,
        # non-backtest-only) registry name should actually be seen at least
        # once by the scanner AS A LITERAL, confirming the scanner isn't
        # silently missing a whole call-site pattern (e.g. multi-line
        # calls) -- except the documented set above, which are genuinely
        # never passed as literals (variables/f-strings at the call site).
        missing = sorted(
            name for name in live_types()
            if name not in self.findings and name not in self._KNOWN_NON_LITERAL_LIVE_TYPES
        )
        self.assertEqual(
            missing, [],
            f"Registered LIVE close types with no matching call site found by "
            f"the T-TAX scanner, and not in the documented non-literal "
            f"exclusion set (scanner may be missing a call pattern): {missing}",
        )


if __name__ == "__main__":
    unittest.main()
