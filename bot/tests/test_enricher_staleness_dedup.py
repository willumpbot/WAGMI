import csv
import json
import os
import sys

import pytest

# Ensure bot/ on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm.agents import prompt_enricher as pe


def _write_trades(path, rows):
    cols = ["timestamp", "symbol", "side", "pnl", "regime", "strategy",
            "primary_driver", "outcome"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


@pytest.fixture
def enricher_env(tmp_path, monkeypatch):
    # Trades: BTC/trend loses 5/6 -> a 'boost BTC in trend' rule is empirically stale,
    # a 'penalize BTC in trend' rule is correct.
    trades = []
    for i in range(6):
        trades.append({
            "symbol": "BTC", "side": "LONG",
            "pnl": "5.0" if i == 0 else "-3.0",
            "regime": "trend", "strategy": "regime_trend",
            "primary_driver": "regime_trend", "outcome": "X",
        })
    tpath = tmp_path / "trades.csv"
    _write_trades(tpath, trades)
    monkeypatch.setattr(pe, "_TRADES_CSV_PATH", str(tpath))
    return tpath


def test_recompute_accuracy_from_trades(enricher_env):
    rows = pe._load_all_trades_for_recompute(str(enricher_env))
    n, acc = pe._recompute_rule_accuracy({"symbol": "BTC", "regime": "trend"}, "boost", rows)
    assert n == 6
    assert acc == pytest.approx(1 / 6, abs=1e-6)   # only 1/6 won
    n2, acc2 = pe._recompute_rule_accuracy({"symbol": "BTC", "regime": "trend"}, "penalize", rows)
    assert n2 == 6
    assert acc2 == pytest.approx(5 / 6, abs=1e-6)  # penalize correct on the 5 losses


def test_stale_flag_and_empirical_staleness_dropped(enricher_env):
    rows = pe._load_all_trades_for_recompute(str(enricher_env))
    entries = [
        # explicit stale flag -> dropped
        {"knowledge_type": "graduated_rule", "category": "regime", "content": "[EDGE] stale one",
         "confidence": 0.9, "evidence_count": 20, "action": "boost",
         "conditions": {"symbol": "BTC", "regime": "trend"}, "stale": True},
        # empirically stale boost (live acc 1/6 < 0.40, n>=5) -> dropped
        {"knowledge_type": "graduated_rule", "category": "regime", "content": "[EDGE] BTC boost",
         "confidence": 0.9, "evidence_count": 15, "action": "boost",
         "conditions": {"symbol": "BTC", "regime": "trend"}},
        # high invalidation_count -> dropped
        {"knowledge_type": "graduated_rule", "category": "regime", "content": "[CAUTION] invalidated",
         "confidence": 0.9, "evidence_count": 9, "action": "penalize",
         "conditions": {"symbol": "ETH"}, "invalidation_count": 5},
    ]
    out = pe._dedup_and_resolve_graduated(entries, rows)
    contents = {e.get("content") for e in out}
    assert "[EDGE] stale one" not in contents
    assert "[EDGE] BTC boost" not in contents
    assert "[CAUTION] invalidated" not in contents


def test_exact_dup_merged(enricher_env):
    rows = pe._load_all_trades_for_recompute(str(enricher_env))
    dup = {"knowledge_type": "graduated_rule", "category": "regime",
           "content": "[CAUTION] BTC weak in trend", "confidence": 0.8,
           "evidence_count": 10, "action": "penalize",
           "conditions": {"symbol": "BTC", "regime": "trend"}}
    out = pe._dedup_and_resolve_graduated([dict(dup), dict(dup)], rows)
    grad = [e for e in out if e.get("action") == "penalize"]
    assert len(grad) == 1  # two identical (action,conditions) collapsed to one


def test_contradiction_resolved_by_live_evidence(enricher_env):
    # Same conditions, boost vs penalize. Live data: BTC/trend loses 5/6 ->
    # penalize has stronger live evidence -> boost must be dropped.
    rows = pe._load_all_trades_for_recompute(str(enricher_env))
    entries = [
        {"knowledge_type": "graduated_rule", "category": "regime",
         "content": "[EDGE] BTC strong in trend", "confidence": 0.9, "evidence_count": 15,
         "action": "boost", "conditions": {"symbol": "BTC", "regime": "trend"}},
        {"knowledge_type": "graduated_rule", "category": "regime",
         "content": "[CAUTION] BTC weak in trend", "confidence": 0.8, "evidence_count": 12,
         "action": "penalize", "conditions": {"symbol": "BTC", "regime": "trend"}},
    ]
    out = pe._dedup_and_resolve_graduated(entries, rows)
    actions = {e.get("action") for e in out if e.get("conditions")}
    assert actions == {"penalize"}  # contradiction resolved in favor of live-correct action


def test_no_evidence_contradiction_keeps_protective():
    # No trades at all -> no live evidence -> keep most protective (veto > boost).
    entries = [
        {"knowledge_type": "graduated_rule", "category": "symbol",
         "content": "[EDGE] SOL boost", "confidence": 0.9, "evidence_count": 15,
         "action": "boost", "conditions": {"symbol": "SOL", "regime": "trend", "side": "BUY"}},
        {"knowledge_type": "graduated_rule", "category": "symbol",
         "content": "[AVOID] SOL veto", "confidence": 0.9, "evidence_count": 15,
         "action": "veto", "conditions": {"symbol": "SOL", "regime": "trend", "side": "BUY"}},
    ]
    out = pe._dedup_and_resolve_graduated(entries, [])
    actions = {e.get("action") for e in out if e.get("conditions")}
    assert actions == {"veto"}


def test_passthrough_non_graduated_untouched():
    plain = {"category": "general", "content": "general wisdom",
             "confidence": 0.95, "evidence_count": 0, "source": "seed"}
    out = pe._dedup_and_resolve_graduated([plain], [])
    assert plain in out
