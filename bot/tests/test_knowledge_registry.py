"""HIVEMIND Phase 0: knowledge registry (bot/knowledge/) + discrepancy checks (tools/knowledge/check.py).

Two kinds of test:
  * fixture tests - each check D1-D11 on a tiny synthetic registry/code/data tree in tmp_path, with a positive case
    (must flag) and a negative case (must not), so a check that always or never fires fails here;
  * acceptance tests - the committed registry against the REAL repo code and the live bot/data (read-only), which must
    flag the brief's day-1 instances. They skip when no live data dir is reachable.
Everything written goes to tmp_path (tests/conftest.py live-write guard).
"""
import csv
import json
import os
import re
import sys
import time
from pathlib import Path

import pytest

BOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BOT / "tools" / "knowledge"))

import check  # noqa: E402
import common  # noqa: E402
import render_map  # noqa: E402
import seed_from_map  # noqa: E402

MAP = BOT / "data" / "laptop_mining" / "KNOWLEDGE_MAP.md"
RULES = BOT / "data" / "laptop_mining" / "SERVER_AUDIT_RULES_2026-10-13.md"


def _live_data_dir():
    """The live bot/data (read-only): $WAGMI_KNOWLEDGE_DATA_DIR, this checkout's data/, or - from a git worktree under
    <main>/.claude/worktrees/<name>/bot - the main checkout's bot/data."""
    cands = [os.environ.get("WAGMI_KNOWLEDGE_DATA_DIR"), BOT / "data"]
    if len(BOT.parents) > 3:
        cands.append(BOT.parents[3] / "bot" / "data")
    for c in cands:
        if c and (Path(c) / "trade_ledger.csv").exists():
            return Path(c)
    return None


def _live_env(data_dir):
    p = data_dir.parent / ".env"
    return p if p.exists() else None


# ---------------------------------------------------------------------------------------------------------------
# Seeding + rendering
# ---------------------------------------------------------------------------------------------------------------
@pytest.fixture
def seeded(tmp_path):
    counts = seed_from_map.seed(MAP, RULES, tmp_path / "nodata", tmp_path / "knowledge")
    return tmp_path / "knowledge", counts


def test_seed_counts(seeded):
    root, counts = seeded
    assert counts["rules"] == 17
    assert counts["claims"] >= 50
    assert counts["definitions"] == 10
    assert len(list((root / "claims").glob("*.json"))) == counts["claims"]
    assert len(list((root / "rules").glob("*.json"))) == 17


def test_status_mapping():
    m = seed_from_map.map_status
    assert m("REFUTED (backwards)")[:2] == ("REFUTED", "backwards")
    assert m("PROVEN, definition-sensitive")[:2] == ("PROVEN", "definition-sensitive")
    assert m("UNDERPOWERED / negative")[0] == "UNDERPOWERED"
    assert m("OPEN (10-16)")[0] == "HYPOTHESIS"
    assert m("KEEP")[0] == "SUPPORTED"
    assert m("RETRACTED")[0] == "RETRACTED"
    assert m("Strong in-sample REVERSAL; forward prereg sealed")[0] == "PREREG_SEALED"
    assert m("NO FINDING")[0] == "UNDERPOWERED"
    st, _, mapped = m("something new")
    assert st == "HYPOTHESIS" and not mapped


def test_seeded_claims_shape(seeded):
    root, _ = seeded
    claims = common.load_cards("claims", root)
    for c in claims.values():
        assert c["status"] in common.STATUSES
        assert c["wording_tier"] == common.tier_for(c["status"])
        assert c["verified_by"] == "none"
        # laptop red-team item 2: the placebo is a number (or not yet known), never a boolean
        assert "placebo_could_fail" not in c["evidence"]
        assert c["evidence"]["no_edge_median"] is None or isinstance(c["evidence"]["no_edge_median"], (int, float))
    assert claims["long_side_drain"]["status"] == "STALE"            # era window closed -> may not bind
    assert claims["funding_hot_stop_hits"]["status"] == "PROVEN"      # as the map seeds it; the live card is SUPPORTED
    assert claims["ic_gate_keep"]["status"] == "SUPPORTED"
    assert claims["momentum_small_fade"]["needs_source"] is True       # the map's warning sign
    assert claims["volume_surge_size"]["needs_source"] is True
    assert claims["llm_agent_predicts_price"]["evidence"]["source"] == "[mem:mining_findings_10-07]"
    assert "rule:r03_long_block" in claims["long_side_drain"]["consumers"]


def test_render_reproduces_map(seeded):
    """The cards hold the map: section 3 rendered from them equals the original rows, in order."""
    root, _ = seeded
    md = MAP.read_text(encoding="utf-8")
    orig = {k: v for k, v in seed_from_map.parse_tables(md, "3. Knowledge ledger").items() if v}
    rend = {k: v for k, v in seed_from_map.parse_tables(render_map.render(root), "3. Knowledge ledger").items() if v}
    assert set(orig) == set(rend)
    strip = lambda r: {k: v for k, v in r.items() if k != "_raw"}  # noqa: E731
    for sec in orig:
        assert [strip(r) for r in rend[sec]] == [strip(r) for r in orig[sec]], sec


def test_rule_cards(seeded):
    root, _ = seeded
    rules = common.load_cards("rules", root)
    assert rules["r07_risk_cap_0_5pct"]["claim_id"] == "owner_policy"
    assert "MAX_RISK_PCT_CEILING" in rules["r07_risk_cap_0_5pct"]["flags"]
    assert rules["r03_long_block"]["claim_id"] == "long_side_drain"
    assert "LONG_REGIME_VETO" in rules["r03_long_block"]["flags"]
    for r in rules.values():
        assert r["unit"] and "description" in r and r["source"].startswith("SERVER_AUDIT_RULES")


def test_definition_hashes(seeded):
    root, _ = seeded
    defs = common.load_cards("definitions", root)
    exp = defs["exp_move"]
    assert len(exp["implementations"]) == 3
    for im in exp["implementations"]:
        assert re.fullmatch(r"[0-9a-f]{64}", im["impl_hash"]), im["label"]
        assert common.impl_hash(im, BOT) == im["impl_hash"]
    for name in ("funding_hot", "smallcap_breakout", "R", "notional"):
        assert all(im.get("impl_hash") for im in defs[name]["implementations"]), name


def test_function_hash_changes_with_code(tmp_path):
    (tmp_path / "m.py").write_text("def f(x):\n    return x + 1\n", encoding="utf-8")
    spec = {"path": "m.py", "function": "f"}
    h1 = common.impl_hash(spec, tmp_path)
    (tmp_path / "m.py").write_text("def f(x):\n    return x + 2\n", encoding="utf-8")
    assert h1 and common.impl_hash(spec, tmp_path) != h1


# ---------------------------------------------------------------------------------------------------------------
# Fixture tree for the check unit tests
# ---------------------------------------------------------------------------------------------------------------
def _claim(cid, status, **kw):
    return {"id": cid, "status": status, "wording_tier": common.tier_for(status), "evidence": {}, **kw}


def _w(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj) if not isinstance(obj, str) else obj, encoding="utf-8")


def _ctx(tmp, now=None):
    return check.Ctx(tmp / "k", tmp / "code", tmp / "data", tmp / ".env", now)


@pytest.fixture
def tree(tmp_path):
    k, code, data = tmp_path / "k", tmp_path / "code", tmp_path / "data"
    for c in [_claim("c_supported", "SUPPORTED"), _claim("c_proven", "PROVEN", live_bot_terms=["hot_flag"]),
              _claim("c_refuted", "REFUTED"), _claim("c_stale", "STALE"),
              _claim("c_metric", "PROVEN", metric="stop_hit_rate")]:
        _w(k / "claims" / f"{c['id']}.json", c)
    _w(k / "bindings.json", {"displays": [], "prompts": [], "graders": []})
    _w(k / "threads.json", {"threads": []})
    (k / "rules").mkdir(parents=True)
    (k / "definitions").mkdir(parents=True)
    _w(code / "tools/hivemind/milestones.json", [])
    _w(code / "tools/hivemind/scanner.py", "FLAGS = {}\n")
    _w(code / "tools/hivemind/scan_grader.py", "SIGN = {'ma50_pullback': 1}\n")
    _w(code / "core/x.py", "y = 1\n")
    data.mkdir()
    _w(tmp_path / ".env", "FOO=1\n")
    return tmp_path


def _ids(findings, check_name=None):
    return {f["id"] for f in findings if check_name is None or f["check"] == check_name}


def test_d1_flags_overclaim_and_not_negation(tree):
    _w(tree / "code/tools/hivemind/milestones.json", [
        {"title": "Filter is right", "kind": "proven", "what": "x"},
        {"title": "Thing refuted", "kind": "refuted", "what": "x"},
        {"title": "Unbound proven", "kind": "proven", "what": "x"}])
    _w(tree / "k/bindings.json", {"displays": [
        {"id": "m1", "surface": "tools/hivemind/milestones.json", "locator": {"title": "Filter is right"},
         "claim_id": "c_supported", "polarity": "claim"},
        {"id": "m2", "surface": "tools/hivemind/milestones.json", "locator": {"title": "Thing refuted"},
         "claim_id": "c_refuted", "polarity": "negation"}], "prompts": [], "graders": []})
    f, _ = check.check_d1_display_vs_grade(_ctx(tree))
    high = {x["id"] for x in f if x["severity"] == "high"}
    assert "m1" in high and "m2" not in high
    assert any(x["id"].startswith("milestone_unbound_") for x in f)


def test_d1_prompt_and_chip(tree):
    _w(tree / "code/tools/hivemind/chief.py", "PROMPT = 'moves ~5% vs ~3% when many dissent'\n")
    _w(tree / "code/tools/hivemind/scanner.py",
       "FLAGS = {'hot': ('Hot', 'tested', 'Tested a lot.'), 'cold': ('Cold', 'context', 'This is not proven.')}\n")
    _w(tree / "k/bindings.json", {"displays": [
        {"id": "chip_hot", "surface": "scanner", "locator": {"flag": "hot"}, "claim_id": "c_stale"}],
        "prompts": [{"id": "p1", "surface": "tools/hivemind/chief.py", "pattern": r"~5% vs ~3%",
                     "claim_id": "c_supported", "asserted_tier": "proven"}], "graders": []})
    f, _ = check.check_d1_display_vs_grade(_ctx(tree))
    assert {"p1", "chip_hot"} <= _ids(f)
    assert "scanner_text_cold" not in _ids(f)          # "not proven" is a negation, not a claim


def _ledger(path, rows):
    cols = ["trade_id", "timestamp", "symbol", "side", "fees", "net_pnl"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow(r)


def _rule(tree, rid, **kw):
    _w(tree / "k/rules" / f"{rid}.json", {"id": rid, "unit": "R", **kw})


def test_d2_frozen_gate(tree):
    t0 = 1784800000  # 2026-07-23
    _ledger(tree / "data/trade_ledger.csv", [
        ["a", t0, "ETH", "LONG", 5.0, -10], ["b", t0 + 60 * 86400, "ETH", "LONG", 0.1, -0.2],
        ["c", t0 + 80 * 86400, "SOL", "LONG", 0.2, 0.3], ["d", t0 + 80 * 86400, "TESTX", "LONG", 0.1, 0]])
    _w(tree / ".env", "LEARNING_INPUT_FLOOR=true\n")
    spec = {"kind": "ledger", "file": "trade_ledger.csv", "side": "LONG", "fee_floor": 0.5,
            "fee_floor_env": "LEARNING_INPUT_FLOOR"}
    _rule(tree, "gate", claim_id="c_stale", evidence_source=spec)
    f, _ = check.check_d2_stale_gate(_ctx(tree))
    hit = [x for x in f if x["id"] == "gate"]
    assert hit and hit[0]["evidence_through"] == "2026-07-23" and hit[0]["n_ignored_newer"] == 2
    # with the fee floor off every row counts -> not frozen
    _w(tree / ".env", "LEARNING_INPUT_FLOOR=false\n")
    f, _ = check.check_d2_stale_gate(_ctx(tree))
    assert "gate" not in _ids(f)


def test_d3_definition_drift(tree):
    _w(tree / "k/definitions/q.json", {"id": "q", "kind": "quantity", "implementations": [
        {"label": "a", "path": "a.py", "impl_hash": "1"}, {"label": "b", "path": "b.py", "impl_hash": "2"}]})
    _w(tree / "k/definitions/one.json", {"id": "one", "kind": "quantity", "implementations": [
        {"label": "a", "path": "a.py", "impl_hash": "1"}, {"label": "txt", "role": "display", "impl_hash": "9"}]})
    f, _ = check.check_d3_definition_drift(_ctx(tree))
    assert "q" in _ids(f) and "one" not in _ids(f)


def test_d4_code_changed_since_card(tree):
    _w(tree / "code/m.py", "def f():\n    return 1\n")
    spec = {"label": "f", "path": "m.py", "function": "f"}
    h = common.impl_hash(spec, tree / "code")
    _w(tree / "k/definitions/d.json", {"id": "d", "kind": "quantity", "implementations": [{**spec, "impl_hash": h}]})
    assert not check.check_d4_impl_vs_tested(_ctx(tree))[0]
    _w(tree / "code/m.py", "def f():\n    return 2\n")
    assert "d:f" in _ids(check.check_d4_impl_vs_tested(_ctx(tree))[0])


def test_d5_grader_metric(tree):
    _w(tree / "k/bindings.json", {"displays": [], "prompts": [], "graders": [
        {"id": "g1", "grader": "tools/hivemind/scan_grader.py", "flag": "hot", "claim_id": "c_metric"}]})
    f, _ = check.check_d5_grader_vs_claim(_ctx(tree))
    assert "g1" in _ids(f)
    _w(tree / "k/claims/c_metric.json", _claim("c_metric", "PROVEN",
                                               metric="abs_excess_return_vs_universe_median"))
    assert "g1" not in _ids(check.check_d5_grader_vs_claim(_ctx(tree))[0])


def test_d6_orphans_and_prompt_only(tree):
    _rule(tree, "dead", claim_id="c_stale")
    _rule(tree, "orphan", claim_id=None)
    _rule(tree, "exempt", claim_id=None, exempt_reason="sim")
    _rule(tree, "cap", claim_id="owner_policy", flags=["CAP"], enforcement_check={
        "prompt_markers": [{"path": "llm/prompts.py", "pattern": r"sizing_constraint\.max_risk_pct"}],
        "code_paths": ["llm/coord.py"], "clamp_pattern": r"(?<![\w.])risk_pct\b[^\n]*_ceiling_cap"})
    _w(tree / "code/llm/prompts.py", "P = 'risk_pct MUST NOT exceed sizing_constraint.max_risk_pct'\n")
    _w(tree / "code/llm/coord.py", "_ceiling_cap = 0.005\nmsg = f'risk_pct {_ceiling_cap}'\n")
    f, _ = check.check_d6_orphans(_ctx(tree))
    ids = _ids(f)
    assert {"claim_c_proven", "rule_dead", "rule_orphan", "rule_cap_prompt_only"} <= ids
    assert "rule_exempt" not in ids
    # a real clamp in code clears the prompt-only finding; a live consumer clears the orphan claim
    _w(tree / "code/llm/coord.py", "_ceiling_cap = 0.005\nrisk_pct = min(risk_pct, _ceiling_cap)\n")
    _w(tree / "code/core/x.py", "if 'hot_flag' in flags:\n    size *= 0.9\n")
    ids = _ids(check.check_d6_orphans(_ctx(tree))[0])
    assert "rule_cap_prompt_only" not in ids and "claim_c_proven" not in ids


def test_d7_card_vs_env(tree):
    _w(tree / "data/hivemind/decisions.json", [
        {"id": "saver", "ready": False, "note": "Saying yes = set COOLDOWN_S=3600 in .env",
         "live": "Built (COOLDOWN_S, default off)."},
        {"id": "stops", "ready": False, "note": "Switched OFF (ADAPTIVE=false)."}])
    _w(tree / ".env", "COOLDOWN_S=3600\nADAPTIVE=false   # comment\n")
    ids = _ids(check.check_d7_config_vs_card(_ctx(tree))[0])
    assert "saver:COOLDOWN_S" in ids and "saver:COOLDOWN_S:default" in ids
    assert not any(i.startswith("stops") for i in ids)
    _w(tree / ".env", "COOLDOWN_S=0\nADAPTIVE=true\n")
    ids = _ids(check.check_d7_config_vs_card(_ctx(tree))[0])
    assert "stops:ADAPTIVE" in ids and "saver:COOLDOWN_S" not in ids


def test_d8_count_disagreement(tree):
    _w(tree / "k/threads.json", {"threads": [
        {"id": "ideas", "thread": "IDEAS", "disagreements": [
            {"field": "n", "a": {"source": "laptop", "value": 4}, "b": {"source": "server", "value": 1}}]},
        {"id": "ok", "thread": "OK", "disagreements": [
            {"field": "n", "a": {"source": "laptop", "value": 2}, "b": {"source": "server", "value": 2}}]}]})
    ids = _ids(check.check_d8_count_disagreement(_ctx(tree))[0])
    assert "ideas:n" in ids and "ok:n" not in ids


def _stream_def(tree, name, path, invariants=(), expected=(), map_keys=()):
    _w(tree / "k/definitions" / f"{name}.json", {
        "id": name, "kind": "stream", "stream": {"path": path, "archive": name, "max_age_days": 2,
                                                 "map_keys": list(map_keys)},
        "expected_fields": list(expected), "invariants": list(invariants)})


def _jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_d9_stale_stream(tree):
    now = time.time()
    _jsonl(tree / "data/old.jsonl", [{"ts": now - 5 * 86400, "x": 1}])
    _jsonl(tree / "data/new.jsonl", [{"ts_utc": "2099-01-01T00:00:00+00:00", "x": 1}])
    _stream_def(tree, "s_old", "old.jsonl")
    _stream_def(tree, "s_new", "new.jsonl")
    _stream_def(tree, "s_gone", "gone.jsonl")
    ids = _ids(check.check_d9_substrate_death(_ctx(tree, now))[0])
    assert {"s_old", "s_gone"} <= ids and "s_new" not in ids


def test_d10_payload_thinning(tree):
    _jsonl(tree / "data/d.jsonl", [{"ts": 1, "a": 1, "b": {"c": 2}, "lsr": 1.5}] * 3 + [{"ts": 2, "a": 1}] * 20)
    _stream_def(tree, "d", "d.jsonl", expected=["ts", "a", "b.c"])
    f, _ = check.check_d10_payload_completeness(_ctx(tree))
    by = {x["id"]: x for x in f}
    assert by["d"]["missing"] == ["b.c"]
    assert by["d_history"]["dropped"] == ["lsr"]


def test_d11_whale_invariant(tree):
    inv = [{"expr": "all(abs(v[0]) <= v[1] for v in g('coins').values())", "why": "abs(net) <= gross"}]
    _jsonl(tree / "data/w.jsonl", [{"ts": 1, "coins": {"BTC": [100, 200, 1, 1], "ETH": [-50, 50, 0, 2]}}])
    _stream_def(tree, "w", "w.jsonl", invariants=inv, map_keys=["coins"])
    assert not check.check_d11_semantic_invariants(_ctx(tree))[0]
    # swapped column names (gross written where net belongs) -> the invariant catches it
    _jsonl(tree / "data/w.jsonl", [{"ts": 1, "coins": {"BTC": [200, 100, 1, 1]}}])
    assert any(x["check"] == "D11" for x in check.check_d11_semantic_invariants(_ctx(tree))[0])


def test_run_survives_a_crashing_check(tree, monkeypatch):
    def boom(ctx):
        raise RuntimeError("x")
    monkeypatch.setattr(check, "CHECKS", [("D1", boom)] + check.CHECKS[1:])
    rep = check.run(_ctx(tree), tree / "out" / "d.json")
    assert any(f["id"] == "check_crashed" for f in rep["discrepancies"])
    assert json.loads((tree / "out" / "d.json").read_text(encoding="utf-8"))["summary"]["D1"]["high"] == 1


# ---------------------------------------------------------------------------------------------------------------
# Acceptance: the committed registry vs the real code and live data must flag the brief's day-1 instances
# ---------------------------------------------------------------------------------------------------------------
LIVE = _live_data_dir()
needs_live = pytest.mark.skipif(LIVE is None, reason="no live bot/data with trade_ledger.csv reachable")


@pytest.fixture(scope="module")
def real_report(tmp_path_factory):
    out = tmp_path_factory.mktemp("knowledge") / "discrepancies.json"
    ctx = check.Ctx(common.KNOWLEDGE, BOT, LIVE, _live_env(LIVE))
    return check.run(ctx, out)


@needs_live
def test_acceptance_d1_fixed_instances_stay_fixed(real_report):
    # The day-1 D1 instances (IC-gate milestone said "proven", chief prompt stated a hypothesis as fact) were found by
    # this checker and fixed on 2026-10-13; they must not come back. (That D1 CAN fail is proven by the fixture tests.)
    d1 = {f["id"] for f in real_report["discrepancies"] if f["check"] == "D1" and f["severity"] == "high"}
    assert not d1 & {"milestone_the_bot_s_hidden_filter_is_right", "milestone_the_bot_s_hidden_filter_looks_right",
                     "chief_prompt_dissent_move"}


@needs_live
def test_acceptance_d2_long_gate_frozen(real_report):
    hit = [f for f in real_report["discrepancies"] if f["check"] == "D2" and f["id"] == "r03_long_block"]
    assert hit, "D2 must flag the long gate's frozen evidence"
    assert hit[0]["evidence_through"] == "2026-07-23" and hit[0]["n_ignored_newer"] > 0


@needs_live
def test_acceptance_d3_exp_move_multiple_impls(real_report):
    assert any(f["check"] == "D3" and f["id"] == "exp_move" for f in real_report["discrepancies"])


@needs_live
def test_acceptance_d6_funding_hot_and_risk_cap(real_report):
    ids = {f["id"] for f in real_report["discrepancies"] if f["check"] == "D6"}
    # both funding_hot claims were downgraded to SUPPORTED on 2026-10-13 (laptop 122f5f1c, 2bc463da) -> no longer
    # PROVEN-but-unused orphans; the prompt-only risk cap still is one.
    assert "claim_funding_hot_stop_hits" not in ids
    assert "rule_r07_risk_cap_0_5pct_prompt_only" in ids


@needs_live
def test_acceptance_d9_runs_on_real_streams(real_report):
    """On today's data every stream is fresh, so D9 must run (not be skipped or crash) without false alarms ..."""
    s = real_report["summary"]["D9"]
    assert not any(f["id"] == "check_crashed" for f in real_report["discrepancies"])
    assert not any(f["check"] == "D9" and "missing" in f["what"] for f in real_report["discrepancies"]), s


@needs_live
def test_acceptance_d9_flags_real_streams_two_days_on():
    """... and the same real streams, read as if 'now' were 3 days later, are all flagged as stopped."""
    ctx = check.Ctx(common.KNOWLEDGE, BOT, LIVE, _live_env(LIVE), now=time.time() + 3 * 86400)
    ids = {f["id"] for f in check.check_d9_substrate_death(ctx)[0]}
    assert {"stream_liq_events", "stream_market_depth", "stream_whales", "stream_voices"} <= ids


@needs_live
def test_acceptance_real_streams_hold_invariants(real_report):
    # Live data may legitimately break an invariant on a few rows (2026-10-13: market_depth 2/183 non-cumulative bands,
    # reported to the laptop) - D11 must REPORT that, and a stream breaking it on more than 5% of rows is a real defect.
    for f in [f for f in real_report["discrepancies"] if f["check"] == "D11"]:
        m = __import__("re").search(r"(\d+)/(\d+) recent rows", f["what"])
        assert m and int(m.group(1)) <= 0.05 * int(m.group(2)), f["what"]
