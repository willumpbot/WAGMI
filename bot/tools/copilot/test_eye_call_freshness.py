#!/usr/bin/env python
"""Lightweight regression test for the micro-cap snapshot STALENESS disclosure
in eye.py / owner_call.py (build_spot_eye / build_spot_owner_call).

The wash/liquidity/flow snapshots are written FORWARD by a separate collector.
If it stalls, `_latest_row_for_mint` still returns its last (possibly hours/days
old) row. Presenting that stale organic/price/liquidity/"RIGHT NOW" flow as if
current is a real harm on a fast meme. These tests assert the two decision-
support briefs DISCLOSE the snapshot age (prominent caveat when stale, quiet
"current" note when fresh) and that the owner-call ledger row records freshness.

Run: python tools/copilot/test_eye_call_freshness.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import eye  # noqa: E402
import owner_call  # noqa: E402


def _write_snapshots(dir_: str, mint: str, age_hours: float) -> None:
    ts = (datetime.now(timezone.utc) - timedelta(hours=age_hours)).isoformat()
    for name, extra in (
        ("wash.jsonl", {"organic_score": 72, "holder_count": 5000}),
        ("liq.jsonl", {"liquidity_usd": 300000, "price_usd": 0.005, "volume_h24": 90000}),
        ("flow.jsonl", {"holder_growth_1h": 0.004, "txns_buy_sell_ratio_24h": 0.6,
                        "vol_accel_1h_vs_24h": 1.4, "liq_change_1h": 0.03, "price_usd": 0.005}),
    ):
        row = {"mint": mint, "symbol": "TESTCOIN", "ts_utc": ts, **extra}
        with open(os.path.join(dir_, name), "w", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")


def _point_modules(dir_: str, mint: str) -> None:
    w = os.path.join(dir_, "wash.jsonl")
    l = os.path.join(dir_, "liq.jsonl")
    fl = os.path.join(dir_, "flow.jsonl")
    for mod in (owner_call, eye):
        mod.WASH_PATH = w
        mod.LIQ_SNAP_PATH = l
        mod.FLOW_PATH = fl
    mm = owner_call.MintMatch(mint=mint, liquidity_usd=300000, organic_score=72,
                              ohlcv_day_path=None, ambiguous=False, n_candidates=1)
    owner_call.resolve_mint = lambda _s: mm
    eye.resolve_mint = lambda _s: mm


def _run_case(age_hours: float):
    mint = "M" * 43
    with tempfile.TemporaryDirectory() as d:
        _write_snapshots(d, mint, age_hours)
        _point_modules(d, mint)
        eye_lines = eye.build_spot_eye("TESTCOIN", 5000.0).lines
        oc = owner_call.OwnerCall(symbol="TESTCOIN", side="LONG", reason="x",
                                  instrument_type="DEX_SPOT")
        owner_call.build_spot_owner_call(oc, datetime.now(timezone.utc))
        return eye_lines, oc.brief_lines, oc.row


def test_stale_discloses() -> None:
    eye_lines, call_lines, row = _run_case(age_hours=72.0)  # 3 days old
    eye_txt = "\n".join(eye_lines)
    call_txt = "\n".join(call_lines)
    assert "STALE DATA" in eye_txt, "eye must show STALE banner on old snapshot"
    assert "STALE DATA" in call_txt, "call must show STALE banner on old snapshot"
    assert "FLOW AS OF A STALE SNAPSHOT" in eye_txt, "eye FLOW header must drop 'RIGHT NOW' when stale"
    assert "RIGHT NOW" not in eye_txt, "eye must NOT claim 'RIGHT NOW' on stale data"
    assert row.get("snapshot_stale") is True
    assert row.get("snapshot_age_hours") is not None and row["snapshot_age_hours"] > 2.0
    assert row.get("snapshot_ts_utc")


def test_fresh_marks_current() -> None:
    eye_lines, call_lines, row = _run_case(age_hours=0.2)  # 12 min old
    eye_txt = "\n".join(eye_lines)
    call_txt = "\n".join(call_lines)
    assert "STALE DATA" not in eye_txt
    assert "STALE DATA" not in call_txt
    assert "(current)" in eye_txt and "(current)" in call_txt
    assert "FLOW RIGHT NOW" in eye_txt
    assert row.get("snapshot_stale") is False


def test_no_timestamp_is_honest() -> None:
    # snapshot rows with no ts_utc -> age unknown, must not silently look current
    mint = "N" * 43
    with tempfile.TemporaryDirectory() as d:
        for name, extra in (("wash.jsonl", {"organic_score": 50}),
                            ("liq.jsonl", {"liquidity_usd": 100000, "price_usd": 0.01}),
                            ("flow.jsonl", {"txns_buy_sell_ratio_24h": 0.5})):
            with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                f.write(json.dumps({"mint": mint, "symbol": "NOTS", **extra}) + "\n")
        _point_modules(d, mint)
        eye_txt = "\n".join(eye.build_spot_eye("NOTS", 5000.0).lines)
        assert "age UNKNOWN" in eye_txt or "NO timestamp" in eye_txt


if __name__ == "__main__":
    test_stale_discloses()
    test_fresh_marks_current()
    test_no_timestamp_is_honest()
    print("OK - eye/call staleness-disclosure tests pass")
