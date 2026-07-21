"""Phase 0.6 acid test -- monitoring/funnel_monitor.py (ISOLATED ENGINE).

Simulates the documented Jul 5-11 blind spot: the ensemble's raw-signal
producer returns None AND `coordinator.get_entry_decision` raises,
simultaneously, for hours -- the exact state in which
`_note_llm_pipeline_health` (multi_strategy_main.py:8024-8027) never runs,
per its own comment, because it only fires on a signal that DOES flow
through. Before this monitor, nothing would have alerted in that state.

This test drives FunnelMonitor's public record()/flush() API directly.
The ~15 call sites into multi_strategy_main.py / core/signal_pipeline.py
(build spec Part 1.3) and the heartbeat-daemon hook (Part 4) are deferred
to the owner-gated shadow-wiring window -- this suite proves the isolated
engine itself would catch the blind spot once wired, using synthetic
ticks that stand in for the real scan loop.

Covers all 8 Part-6 acid points where in-scope; points 5/6 (the
`tools/health_alert.py` external-reader extension) are explicitly OUT OF
SCOPE for 0.6 (deferred to Part 4's external-reader work) -- those two are
adapted here into a scoped check that ALARM_ACTIVE.json itself carries
everything such an external reader would need (existence + staleness +
schema), without invoking health_alert.py.
"""
import json
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitoring.funnel_monitor import (  # noqa: E402
    FunnelMonitor,
    Stage,
    get_funnel_monitor,
    reset_funnel_monitor_singleton_for_tests,
)


# ---------------------------------------------------------------------------
# Fixtures / test doubles
# ---------------------------------------------------------------------------
class FakeClock:
    """Injected clock -- lets the test simulate days of wall time instantly."""

    def __init__(self, start: float = 1_800_000_000.0):
        self.t = float(start)

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class SpyAlerts:
    """Injected `alerts` collaborator -- records every dispatch instead of
    sending anything (mocked AlertRouter per spec Part 6 point 3)."""

    def __init__(self):
        self.market_updates = []
        self.trade_alerts = []

    def send_market_update(self, msg):
        self.market_updates.append(msg)

    def send_trade_alert(self, msg):
        self.trade_alerts.append(msg)

    @property
    def all_sent(self):
        return self.market_updates + self.trade_alerts


@pytest.fixture
def tmp_data_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    (d / "logs").mkdir()
    return d


def _make_monitor(tmp_data_dir, clock, alerts=None, **kwargs):
    kwargs.setdefault("get_run_stats_fn", lambda: None)
    kwargs.setdefault("derive_equity_fn", lambda: None)
    kwargs.setdefault("last_ledger_trade_ts_fn", lambda: None)
    return FunnelMonitor(
        data_dir=tmp_data_dir,
        clock=clock,
        alerts=alerts if alerts is not None else SpyAlerts(),
        env={},
        **kwargs,
    )


def _drive_silence(mon, clock, hours, step_s=300.0, flush_every=1):
    """Advance `hours` of simulated time: SCANNED alive every tick, an
    LLM_DECISION 'attempt' + 'pipeline_error' every tick (coordinator
    raises), and NEVER a RAW_SIGNAL -- the Jul 5-11 blind spot. Flushes
    (the daemon's job) every `flush_every` ticks."""
    n_steps = int((hours * 3600.0) / step_s)
    for i in range(n_steps):
        mon.record(Stage.SCANNED, symbol="ETH")
        mon.record(Stage.LLM_DECISION, reason="attempt")
        mon.record(Stage.LLM_DECISION, reason="pipeline_error", ok=False)
        clock.advance(step_s)
        if (i + 1) % flush_every == 0:
            mon.flush(clock())
    return mon.flush(clock())


# ---------------------------------------------------------------------------
# Acid point 1: raw_signal_silence trips within 6h using ONLY advancing
# SCANNED + wall clock (signal-independent -- no RAW_SIGNAL ever recorded).
# ---------------------------------------------------------------------------
def test_acid_1_raw_signal_silence_trips_signal_independently(tmp_data_dir):
    clock = FakeClock()
    alerts = SpyAlerts()
    mon = _make_monitor(tmp_data_dir, clock, alerts)

    result = _drive_silence(mon, clock, hours=6.3)

    alarms = {a["id"]: a for a in result["alarms"]}
    r1 = alarms["funnel.raw_signal_silence"]
    assert r1["active"] is True
    assert r1["observed"] >= 6.0
    assert r1["threshold_source"] == "hard_ceiling"  # <13 gaps ever recorded
    assert len(alerts.all_sent) == 1


# ---------------------------------------------------------------------------
# Acid point 2: ALARM_ACTIVE.json is atomically replaced -- a concurrent
# reader in a tight loop must NEVER observe a torn/unparseable file.
# ---------------------------------------------------------------------------
def test_acid_2_alarm_active_parses_mid_write(tmp_data_dir):
    clock = FakeClock()
    mon = _make_monitor(tmp_data_dir, clock, SpyAlerts())
    stop = threading.Event()
    read_errors = []
    saw_file = threading.Event()

    def writer():
        while not stop.is_set():
            mon.record(Stage.SCANNED)
            clock.advance(1.0)
            mon.flush(clock())

    def reader():
        # The contract under test is the ATOMIC guarantee: a reader must
        # NEVER observe a partial/truncated/torn JSON file (os.replace is
        # atomic). On Windows, os.replace can also transiently deny a
        # concurrent open() with PermissionError while the swap is in
        # flight -- that is a file-lock artifact, NOT a torn read, so it is
        # retried (a real external reader would do the same), while any
        # JSONDecodeError or missing-key would be a genuine torn-read
        # failure and is recorded.
        path = tmp_data_dir / "ALARM_ACTIVE.json"
        reads = 0
        while reads < 300:
            if path.exists():
                saw_file.set()
                got = False
                for _ in range(50):  # retry only transient OS lock races
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        assert "schema_version" in data
                        assert "alarms" in data
                        got = True
                        break
                    except (PermissionError, FileNotFoundError):
                        time.sleep(0.001)
                        continue
                    except Exception as e:
                        read_errors.append(repr(e))
                        got = True
                        break
                if got:
                    reads += 1
            time.sleep(0.001)

    wt = threading.Thread(target=writer, daemon=True)
    rt = threading.Thread(target=reader, daemon=True)
    wt.start()
    rt.start()
    rt.join(timeout=15)
    stop.set()
    wt.join(timeout=5)

    assert saw_file.is_set(), "ALARM_ACTIVE.json was never created"
    assert read_errors == [], f"torn/unparseable reads observed: {read_errors[:5]}"


# ---------------------------------------------------------------------------
# Acid point 3: exactly ONE alert per episode (hysteresis), then a re-fire
# after +6h fake time while still active.
# ---------------------------------------------------------------------------
def test_acid_3_one_alert_per_episode_then_refire(tmp_data_dir):
    clock = FakeClock()
    alerts = SpyAlerts()
    mon = _make_monitor(tmp_data_dir, clock, alerts)

    _drive_silence(mon, clock, hours=6.3)
    assert len(alerts.all_sent) == 1, "expected exactly one alert for the initial trip"

    # Still silent, but not yet +6h since the fire -- no re-fire yet.
    _drive_silence(mon, clock, hours=2.0)
    assert len(alerts.all_sent) == 1, "must not re-fire before the 6h re-fire interval"

    # Cross +6h since the last fire -- exactly one re-fire.
    _drive_silence(mon, clock, hours=4.5)
    assert len(alerts.all_sent) == 2, "expected exactly one re-fire after +6h"


# ---------------------------------------------------------------------------
# Acid point 4: simulated restart at hour 3 (new FunnelMonitor instance,
# same tmp dir) -- the replayed silence clock still trips by hour 6, i.e.
# NOT reset to now() by the restart.
# ---------------------------------------------------------------------------
def test_acid_4_restart_no_amnesia(tmp_data_dir):
    clock = FakeClock()
    mon1 = _make_monitor(tmp_data_dir, clock, SpyAlerts())

    result_at_3h = _drive_silence(mon1, clock, hours=3.0)
    alarms_at_3h = {a["id"]: a for a in result_at_3h["alarms"]}
    assert alarms_at_3h["funnel.raw_signal_silence"]["active"] is False, "must not trip before 6h"

    # "Restart": brand new instance, same on-disk state, clock keeps ticking
    # (representing that real wall time passed during the outage).
    mon2 = _make_monitor(tmp_data_dir, clock, SpyAlerts())

    result = _drive_silence(mon2, clock, hours=3.3)
    alarms = {a["id"]: a for a in result["alarms"]}
    r1 = alarms["funnel.raw_signal_silence"]
    assert r1["active"] is True, "restart must not reset the silence clock to now()"
    assert r1["observed"] >= 6.0


def test_acid_4b_restart_preserves_never_happened_anchor(tmp_data_dir):
    """Even when RAW_SIGNAL has NEVER once fired (last_ok_ts is None), the
    fallback anchor (monitor_epoch_start) must itself survive a restart --
    otherwise a restarted instance would silently reset its own "never
    happened" clock to its own boot time and never trip."""
    clock = FakeClock()
    mon1 = _make_monitor(tmp_data_dir, clock, SpyAlerts())
    mon1.flush(clock())
    state_path = tmp_data_dir / "funnel_monitor_state.json"
    state1 = json.loads(state_path.read_text())
    epoch_start_1 = state1["monitor_epoch_start"]

    clock.advance(3600.0)
    mon2 = _make_monitor(tmp_data_dir, clock, SpyAlerts())
    mon2.flush(clock())
    state2 = json.loads(state_path.read_text())
    assert state2["monitor_epoch_start"] == epoch_start_1


# ---------------------------------------------------------------------------
# Acid points 5/6 (SCOPED to the isolated engine): the external reader
# (tools/health_alert.py extension) is deferred, but the ALARM_ACTIVE.json
# file this build produces must carry everything such a reader needs:
# it must exist, parse, and its mtime/updated_at must go stale exactly
# when flush() stops being called (proving "the file itself is the
# evaluator's liveness signal", spec Part 4).
# ---------------------------------------------------------------------------
def test_acid_5_6_alarm_active_is_a_valid_external_liveness_signal(tmp_data_dir):
    clock = FakeClock()
    mon = _make_monitor(tmp_data_dir, clock, SpyAlerts())

    _drive_silence(mon, clock, hours=6.3)
    path = tmp_data_dir / "ALARM_ACTIVE.json"
    assert path.exists()
    payload = json.loads(path.read_text())
    assert payload["schema_version"] == 1
    assert payload["all_clear"] is False
    ids = {a["id"] for a in payload["alarms"]}
    assert "funnel.raw_signal_silence" in ids
    r1 = next(a for a in payload["alarms"] if a["id"] == "funnel.raw_signal_silence")
    assert r1["alert_sent"] is True
    assert r1["threshold"]["source"] in ("live", "hard_ceiling")

    # "Freeze the daemon" (stop calling flush) -- the file's updated_at
    # stops advancing even while the fake clock (standing in for a fresh
    # heartbeat.json) keeps ticking. An external reader comparing
    # updated_at age vs. a fresh heartbeat is exactly how Part 4's deferred
    # health_alert.py extension would detect "alarm evaluator dead".
    frozen_updated_at = payload["updated_at"]
    clock.advance(3600.0)  # 1h with no flush() call at all
    payload_after = json.loads(path.read_text())
    assert payload_after["updated_at"] == frozen_updated_at, (
        "ALARM_ACTIVE.json must not advance on its own -- only flush() writes it"
    )


# ---------------------------------------------------------------------------
# Acid point 7: record()/flush() exceptions never propagate.
# ---------------------------------------------------------------------------
def test_acid_7_record_never_raises_even_with_broken_internals(tmp_data_dir):
    clock = FakeClock()
    mon = _make_monitor(tmp_data_dir, clock, SpyAlerts())

    class ExplodingLock:
        def __enter__(self):
            raise RuntimeError("lock exploded")

        def __exit__(self, *a):
            return False

    mon._lock = ExplodingLock()
    # Must not raise.
    mon.record(Stage.SCANNED)
    mon.record(Stage.RAW_SIGNAL, symbol="ETH", reason="x", ok=True, meta={"a": 1})
    mon.record(None)  # even a garbage stage type must not raise
    mon.record(123)


def test_acid_7b_flush_never_raises_even_with_broken_persistence(tmp_data_dir, monkeypatch):
    clock = FakeClock()
    mon = _make_monitor(tmp_data_dir, clock, SpyAlerts())
    mon.record(Stage.SCANNED)

    import monitoring.funnel_monitor as fm

    def _boom(*a, **k):
        raise RuntimeError("disk exploded")

    monkeypatch.setattr(fm, "atomic_write_json", _boom)
    result = mon.flush(clock())  # must not raise
    assert result["ok"] is False or result.get("ok") is True  # never propagates either way


def test_acid_7c_flush_never_raises_when_alarm_rule_itself_is_broken(tmp_data_dir):
    clock = FakeClock()
    mon = _make_monitor(tmp_data_dir, clock, SpyAlerts())
    mon.record(Stage.SCANNED)

    def _explode(*a, **k):
        raise RuntimeError("alarm rule exploded")

    mon._eval_r1_raw_signal_silence = _explode
    result = mon.flush(clock())  # must not raise -- other rules still run
    assert result["ok"] is True
    assert any(a["id"] == "funnel.gos_dying" for a in result["alarms"])


# ---------------------------------------------------------------------------
# Acid point 8 (SCOPED): dup-blocked / unfilled-order paths (Part 3's
# eventual post_go_abort records) must be consumable by R3 as "GO-like but
# not opened", and a run with ONLY llm_execute (passed=True, i.e. an actual
# fill, per the Part-3 fix) must NOT trip gos_dying. The actual multi_
# strategy_main.py call-site wiring (Part 1.3/3) is deferred; this proves
# the engine's consumption logic is ready for it using synthetic
# signal_outcomes.jsonl fixtures shaped exactly like
# core/signal_tracker.py::record_signal's on-disk record.
# ---------------------------------------------------------------------------
def _write_signal_outcome(path, ts, stage, passed, hard_rej=False, reason=""):
    rec = {
        "ts": ts,
        "sym": "ETH",
        "side": "BUY",
        "conf": 80.0,
        "strat": "llm_first",
        "passed": passed,
        "hard_rej": hard_rej,
        "rej_reason": reason,
        "meta": {"pipeline": "llm_first", "stage": stage},
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def test_acid_8_post_go_abort_without_fill_trips_gos_dying(tmp_data_dir):
    clock = FakeClock()
    outcomes_path = tmp_data_dir / "logs" / "signal_outcomes.jsonl"
    mon = _make_monitor(tmp_data_dir, clock, SpyAlerts(), signal_outcomes_path=outcomes_path)

    now0 = clock()
    # Three GOs that all die post-brain-approval (dup block / unfilled /
    # portfolio cap) -- exactly the Part-3 "post_go_abort" shape, and
    # crucially NO llm_execute (no fill) anywhere.
    _write_signal_outcome(outcomes_path, now0 + 60, "post_go_abort", passed=False, hard_rej=True, reason="dup_block")
    _write_signal_outcome(outcomes_path, now0 + 120, "post_go_abort", passed=False, hard_rej=True, reason="order_unfilled")
    _write_signal_outcome(outcomes_path, now0 + 180, "post_go_abort", passed=False, hard_rej=True, reason="portfolio_cap")

    clock.advance(300.0)
    mon.record(Stage.SCANNED)
    result = mon.flush(clock())
    alarms = {a["id"]: a for a in result["alarms"]}
    # 3 GO-like outcomes, zero OPENED funnel events -> gos_dying condition
    # observed after 2 consecutive evals (n_trip=2).
    result2 = mon.flush(clock())
    alarms2 = {a["id"]: a for a in result2["alarms"]}
    assert alarms2["funnel.gos_dying"]["active"] is True


def test_acid_8b_fill_with_matching_llm_execute_does_not_trip_gos_dying(tmp_data_dir):
    clock = FakeClock()
    outcomes_path = tmp_data_dir / "logs" / "signal_outcomes.jsonl"
    mon = _make_monitor(tmp_data_dir, clock, SpyAlerts(), signal_outcomes_path=outcomes_path)

    now0 = clock()
    _write_signal_outcome(outcomes_path, now0 + 60, "llm_execute", passed=True)
    mon.record(Stage.SCANNED)
    mon.record(Stage.OPENED, symbol="ETH")
    mon.flush(clock())
    clock.advance(60.0)
    result = mon.flush(clock())
    alarms = {a["id"]: a for a in result["alarms"]}
    assert alarms["funnel.gos_dying"]["active"] is False


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
def test_singleton_returns_same_instance_and_resets_for_tests():
    reset_funnel_monitor_singleton_for_tests()
    try:
        m1 = get_funnel_monitor(data_dir=None, clock=lambda: 1.0)
        m2 = get_funnel_monitor(data_dir=None, clock=lambda: 2.0)
        assert m1 is m2
    finally:
        reset_funnel_monitor_singleton_for_tests()


# ---------------------------------------------------------------------------
# Focused per-alarm unit tests (R1-R6), synthetic-data driven.
# ---------------------------------------------------------------------------
def test_r1_live_threshold_from_history_clamped_to_hard_ceiling(tmp_data_dir):
    """>=13 historical RAW_SIGNAL inter-arrival gaps of e.g. 8h each should
    still clamp the alarm threshold to FUNNEL_ALARM_MAX_SILENCE_H=6, per
    the "clamp to hard ceiling either way" rule -- a live p99 gap must
    never let the alarm sleep LONGER than the ceiling."""
    clock = FakeClock()
    mon = _make_monitor(tmp_data_dir, clock, SpyAlerts())

    # Seed 14 fake RAW_SIGNAL events, 8h apart, directly into
    # funnel_events.jsonl (the history R1 reads).
    events_path = tmp_data_dir / "logs" / "funnel_events.jsonl"
    t = clock() - 14 * 8 * 3600.0
    with open(events_path, "a", encoding="utf-8") as f:
        for i in range(14):
            t += 8 * 3600.0
            f.write(json.dumps({"ts": t, "stage": "RAW_SIGNAL", "delta": 1, "cumulative": i + 1, "last_event_ts": t, "reasons": {}}) + "\n")

    threshold_h, source, n = mon._raw_signal_threshold_h()
    assert source == "live"
    assert n >= 13
    assert threshold_h <= 6.0 + 1e-9


def test_r1_hard_ceiling_when_fewer_than_13_gaps(tmp_data_dir):
    clock = FakeClock()
    mon = _make_monitor(tmp_data_dir, clock, SpyAlerts())
    threshold_h, source, n = mon._raw_signal_threshold_h()
    assert source == "hard_ceiling"
    assert n == 0
    assert threshold_h == 6.0


def test_r2_canary_trips_after_3_consecutive_failures_and_clears_after_2_oks(tmp_data_dir):
    clock = FakeClock()

    def failing_transport(prompt, timeout_s):
        raise RuntimeError("claude -p timed out")

    mon = _make_monitor(tmp_data_dir, clock, SpyAlerts(), brain_canary_transport=failing_transport)
    mon.record(Stage.LLM_DECISION, reason="attempt")

    interval = 3600.0  # BRAIN_CANARY_INTERVAL_MIN default 60 -> 3600s
    for _ in range(3):
        clock.advance(interval)
        mon.record(Stage.LLM_DECISION, reason="attempt")
        mon.flush(clock())
    assert mon._canary_state["consecutive_fail"] >= 3
    assert mon._canary_state["dead"] is True

    # Now fix the transport and let it recover for 2 consecutive probes.
    mon._brain_canary_transport = lambda prompt, timeout_s: json.dumps({"regime": "trend"})
    for _ in range(2):
        clock.advance(interval)
        mon.record(Stage.LLM_DECISION, reason="attempt")
        mon.flush(clock())
    assert mon._canary_state["dead"] is False


def test_r3_gos_dying_requires_at_least_3_go_like_in_24h(tmp_data_dir):
    clock = FakeClock()
    outcomes_path = tmp_data_dir / "logs" / "signal_outcomes.jsonl"
    mon = _make_monitor(tmp_data_dir, clock, SpyAlerts(), signal_outcomes_path=outcomes_path)
    now0 = clock()
    _write_signal_outcome(outcomes_path, now0 + 10, "post_go_abort", passed=False, reason="dup_block")
    _write_signal_outcome(outcomes_path, now0 + 20, "post_go_abort", passed=False, reason="dup_block")
    mon.record(Stage.SCANNED)
    mon.flush(clock())
    result = mon.flush(clock())
    alarms = {a["id"]: a for a in result["alarms"]}
    assert alarms["funnel.gos_dying"]["active"] is False  # only 2, needs >=3


def test_r4_gate_choke_trips_at_90pct_with_n_gte_13_and_clears_at_70pct(tmp_data_dir):
    clock = FakeClock()
    mon = _make_monitor(tmp_data_dir, clock, SpyAlerts())

    def _feed_gate(n_entrants, n_rej, gate="safety_chain"):
        mon._detail_counts[f"{Stage.GATED}::{gate}::ok"] += (n_entrants - n_rej)
        mon._detail_counts[f"{Stage.GATED}::{gate}::rej"] += n_rej
        mon._counts[Stage.GATED] += n_entrants
        mon._last_event_ts[Stage.GATED] = clock()

    # 20 entrants, 19 rejected = 95% >= 90% trip ratio, n=20 >= 13.
    _feed_gate(20, 19)
    mon.flush(clock())
    clock.advance(3600.0)
    result = mon.flush(clock())
    alarms = {a["id"]: a for a in result["alarms"]}
    assert alarms["funnel.gate_choke.safety_chain"]["active"] is True


def test_r4_gate_choke_silent_below_n13(tmp_data_dir):
    clock = FakeClock()
    mon = _make_monitor(tmp_data_dir, clock, SpyAlerts())
    mon._detail_counts[f"{Stage.GATED}::tiny_gate::ok"] += 1
    mon._detail_counts[f"{Stage.GATED}::tiny_gate::rej"] += 9
    mon._counts[Stage.GATED] += 10
    mon._last_event_ts[Stage.GATED] = clock()
    mon.flush(clock())
    clock.advance(3600.0)
    result = mon.flush(clock())
    ids = {a["id"] for a in result["alarms"]}
    assert "funnel.gate_choke.tiny_gate" not in ids  # n=10 < 13 -> silent


def test_r5_ledger_divergence_position_state_vs_pos_mgr_mismatch(tmp_data_dir):
    clock = FakeClock()
    pos_state_path = tmp_data_dir / "position_state.json"
    pos_state_path.write_text(json.dumps({
        "saved_at": clock(), "position_count": 1,
        "positions": {"ETH": {"symbol": "ETH", "state": "OPEN"}},
    }))
    mon = _make_monitor(
        tmp_data_dir, clock, SpyAlerts(),
        position_state_path=pos_state_path,
        get_pos_mgr_open_count_fn=lambda: 0,  # mismatch: file says 1 open, pos_mgr says 0
    )
    mon.flush(clock())
    clock.advance(700.0)  # > FUNNEL_LEDGER_CHECK_MIN default 10 min
    result = mon.flush(clock())
    alarms = {a["id"]: a for a in result["alarms"]}
    assert alarms["funnel.ledger_divergence"]["active"] is True


def test_r5_equity_divergence_skips_when_derive_equity_is_none(tmp_data_dir):
    """derive_equity() returning None must be treated as 'skip', never $0
    (data/trade_source.py contract) -- no equity_divergence alarm should
    even be created."""
    clock = FakeClock()
    mon = _make_monitor(
        tmp_data_dir, clock, SpyAlerts(),
        get_risk_equity_fn=lambda: 5000.0,
        derive_equity_fn=lambda: None,
    )
    mon.flush(clock())
    clock.advance(700.0)
    result = mon.flush(clock())
    ids = {a["id"] for a in result["alarms"]}
    assert "funnel.equity_divergence" not in ids


def test_r5_equity_divergence_trips_on_drift_over_threshold(tmp_data_dir):
    clock = FakeClock()
    mon = _make_monitor(
        tmp_data_dir, clock, SpyAlerts(),
        get_risk_equity_fn=lambda: 5000.0,
        derive_equity_fn=lambda: 4900.0,  # 2% drift > default 1% threshold
    )
    mon.flush(clock())
    clock.advance(700.0)
    result = mon.flush(clock())
    alarms = {a["id"]: a for a in result["alarms"]}
    assert alarms["funnel.equity_divergence"]["active"] is True


def test_r6_signal_drought_stays_silent_without_live_atr_baseline(tmp_data_dir):
    """No injected ATR-percentile source (None, the default) -> R6 must
    NEVER fire, even with a long drought -- 'n>=13 days else None -> no
    alarm', never a hardcoded expected rate."""
    clock = FakeClock()
    mon = _make_monitor(tmp_data_dir, clock, SpyAlerts())
    _drive_silence(mon, clock, hours=13.0)
    result = mon.flush(clock())
    ids = {a["id"] for a in result["alarms"]}
    assert "funnel.signal_drought" not in ids


def test_r6_signal_drought_fires_when_atr_baseline_says_active_market(tmp_data_dir):
    clock = FakeClock()
    mon = _make_monitor(tmp_data_dir, clock, SpyAlerts(), get_atr_percentile_fn=lambda: 75.0)
    _drive_silence(mon, clock, hours=13.0)
    result = mon.flush(clock())
    alarms = {a["id"]: a for a in result["alarms"]}
    assert alarms["funnel.signal_drought"]["active"] is True


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
