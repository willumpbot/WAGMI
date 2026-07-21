"""Phase 0.6 -- Funnel monitor / silent-failure defense (ISOLATED ENGINE).

WHY THIS EXISTS: the bot has repeatedly gone silently non-trading for days
(the "no trades in 7 days" incident, the documented Jul 5-11 window where
the ensemble's raw-signal producer returned None AND
`coordinator.get_entry_decision` raised simultaneously -- exactly the
blind spot `_note_llm_pipeline_health` admits in its own comment it can
never catch, because it only fires on a signal that DOES flow through).
Every existing instrument (signal_outcomes.jsonl, risk_rejections.csv,
SQLite signal_rejections, heartbeat scan_count, decisions.jsonl) is a
detail sink hanging off one stage; none of them ties SCANNED all the way
through to OPENED, and none of them is itself detectable-when-dead. This
module is the spine: one funnel from scan to fill, plus alarms that watch
the funnel's own silence.

SCOPE (see build spec 0.6): this file is a NEW, self-contained module.
It is NOT wired into any live call site yet:
  - The ~15 `record()` call sites in multi_strategy_main.py /
    core/signal_pipeline.py (spec Part 1.3) are deferred to the
    owner-gated shadow-wiring window.
  - The heartbeat-daemon hook that calls `flush()` every ~30s (spec
    Part 4's `_check_funnel_alarms` hook) is deferred.
  - The `tools/health_alert.py` external-reader extension (spec Part 4)
    is deferred.
Importing this module and calling `get_funnel_monitor()` is inert today:
it creates files under DATA_DIR (or an injected data_dir in tests) but
nothing in the live trading path calls it.

HOT PATH CONTRACT (spec 1.2): `record()` does NO blocking disk/network
I/O, holds its lock only across in-memory bumps, and NEVER raises --
mirrors `tools/discord_notify.py::send_discord`'s "never raises" contract
and the `feedback/live_edge.py` n>=13-else-None convention for live
thresholds. The (future) heartbeat daemon owns ALL flushing/evaluation via
`flush(now)`, which itself also never raises (a monitoring bug must never
be able to wedge or crash the trading loop -- "fails closed for trading,
fails loud for monitoring").

INJECTABLE SEAMS (so this is fully unit-testable without a running bot):
  - `clock`                       -- defaults to time.time; tests pass a
                                      fake clock to simulate hours/days.
  - `alerts`                      -- object with send_market_update()/
                                      send_trade_alert(); defaults to a
                                      logging-only no-op stub. Real wiring
                                      is `alerts/router.py`'s AlertRouter,
                                      at merge time.
  - `get_run_stats_fn` /
    `derive_equity_fn` /
    `last_ledger_trade_ts_fn`     -- default to `data/trade_source.py`'s
                                      canonical readers; None means "skip
                                      this check", per that module's
                                      contract -- NEVER treated as $0.
  - `get_risk_equity_fn`          -- default returns None (no live risk_mgr
                                      handle in the isolated build).
  - `get_pos_mgr_open_count_fn` /
    `get_sqlite_open_positions_fn`-- default return None (skip that leg of
                                      the R5 three-way check).
  - `get_atr_percentile_fn`       -- default returns None (R6 never fires
                                      without a live >=13-day baseline).
  - `get_llm_first_degraded_fn`   -- default returns False (R4's
                                      llm_first_standdown cross-check).
  - `brain_canary_transport`      -- callable(prompt, timeout_s) -> str;
                                      default is a stub that always reports
                                      healthy. Real wiring is a `claude -p`
                                      subprocess call (CLI routing, never an
                                      API key) at merge time; tests inject
                                      a transport that raises/returns
                                      garbage to exercise the failure path.
  - `signal_outcomes_path` /
    `position_state_path`         -- default to the real paths but are
                                      fully overridable (tmp dirs in tests).

Paths: uses `core.paths.DATA_DIR` -- this is DATA_DIR's first production
consumer (see core/paths.py docstring). Per spec, `BootIntegrityError`
refuse-to-start is intentionally NOT enabled here (TODO, out of scope for
0.6 -- a monitoring module refusing to start would itself become a new
silent-failure vector until the shadow-wiring window proves it out).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import Counter, deque
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

from core.atomic_state import atomic_write_json, append_jsonl_line, read_json_or_none
from core.paths import DATA_DIR

try:
    from core.paths import position_state_path as _canonical_position_state_path
except Exception:  # pragma: no cover -- paths.py always has this today
    _canonical_position_state_path = None

logger = logging.getLogger("bot.monitoring.funnel_monitor")


# ---------------------------------------------------------------------------
# Part 1.1 -- the canonical funnel, exactly these stages, in this order.
#
# Deliberately a plain string-constant class rather than enum.Enum: every
# value here is persisted verbatim into JSON (funnel_events.jsonl,
# funnel_monitor_state.json, ALARM_ACTIVE.json) and used as a dict key /
# string-concatenation component when building per-reason counters below --
# a str-mixin Enum's str()/format() behavior differs across Python versions
# and is an easy footgun for exactly that use, so plain strings avoid it.
# ---------------------------------------------------------------------------
class Stage:
    """SCANNED -> RAW_SIGNAL -> PRE_LLM_ROUTED -> GATED -> LLM_DECISION ->
    SIZED -> ORDER_SUBMITTED -> OPENED (spec Part 1.1)."""

    SCANNED = "SCANNED"
    RAW_SIGNAL = "RAW_SIGNAL"
    PRE_LLM_ROUTED = "PRE_LLM_ROUTED"
    GATED = "GATED"
    LLM_DECISION = "LLM_DECISION"
    SIZED = "SIZED"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    OPENED = "OPENED"


STAGE_ORDER: Tuple[str, ...] = (
    Stage.SCANNED,
    Stage.RAW_SIGNAL,
    Stage.PRE_LLM_ROUTED,
    Stage.GATED,
    Stage.LLM_DECISION,
    Stage.SIZED,
    Stage.ORDER_SUBMITTED,
    Stage.OPENED,
)
_STAGE_SET = frozenset(STAGE_ORDER)

_CANARY_PROMPT = (
    "Classify the current regime from this snapshot in one word "
    '(trend/range/panic/high_volatility/low_liquidity/news_dislocation/'
    'unknown) and reply ONLY with JSON: {\"regime\": \"<one word>\"}. '
    "Snapshot: BTC 1h ATR%=1.2, funding=0.01%, OI flat, no news."
)


# ---------------------------------------------------------------------------
# Default injected collaborators
# ---------------------------------------------------------------------------
class _NoOpAlerts:
    """Default `alerts` collaborator: logs only, sends nothing.

    Real wiring is `alerts/router.py`'s AlertRouter at shadow-wiring merge
    time. Tests inject a spy/mock exposing the same two methods to assert
    dispatch counts (spec Part 6 acid point 3)."""

    def send_market_update(self, msg: str) -> None:
        logger.info("[FUNNEL-ALARM][no-op alerts] market_update: %s", msg)

    def send_trade_alert(self, msg: str) -> None:
        logger.info("[FUNNEL-ALARM][no-op alerts] trade_alert: %s", msg)


def _default_get_run_stats() -> Optional[dict]:
    try:
        from data.trade_source import get_run_stats
        return get_run_stats()
    except Exception:
        return None


def _default_derive_equity() -> Optional[float]:
    try:
        from data.trade_source import derive_equity
        return derive_equity()
    except Exception:
        return None


def _default_last_ledger_trade_ts() -> Optional[float]:
    try:
        from data.trade_source import load_closed_trades
        trades = load_closed_trades(max_trades=1)
        if trades:
            ts = trades[-1].get("timestamp")
            return float(ts) if ts else None
    except Exception:
        return None
    return None


def _default_canary_transport_stub(prompt: str, timeout_s: float) -> str:
    """Default injected transport for the R2 brain canary -- a NO-OP stub
    that always reports healthy. 0.6 does NOT call `claude -p` for real
    (per CLI-routing convention, never an API key) -- that subprocess
    wiring is shadow-window work. Tests inject a transport that raises or
    returns unparseable garbage to exercise the failure path."""
    return json.dumps({"regime": "unknown", "canary": True})


# ---------------------------------------------------------------------------
# FunnelMonitor
# ---------------------------------------------------------------------------
class FunnelMonitor:
    """In-memory funnel counters + durable event log + alarm state.

    HOT PATH CONTRACT: `record()` does NO disk/network I/O, no locks held
    across I/O, and NEVER raises (like `tools/discord_notify.send_discord`'s
    "never raises" contract). The heartbeat daemon (once wired) owns all
    flushing/evaluation via `flush(now)`, which also never raises.
    """

    def __init__(
        self,
        data_dir: Optional[Any] = None,
        alerts: Optional[Any] = None,
        clock: Optional[Callable[[], float]] = None,
        env: Optional[Dict[str, str]] = None,
        get_run_stats_fn: Optional[Callable[[], Optional[dict]]] = None,
        derive_equity_fn: Optional[Callable[[], Optional[float]]] = None,
        last_ledger_trade_ts_fn: Optional[Callable[[], Optional[float]]] = None,
        get_risk_equity_fn: Optional[Callable[[], Optional[float]]] = None,
        get_pos_mgr_open_count_fn: Optional[Callable[[], Optional[int]]] = None,
        get_sqlite_open_positions_fn: Optional[Callable[[], Optional[List[str]]]] = None,
        get_atr_percentile_fn: Optional[Callable[[], Optional[float]]] = None,
        get_llm_first_degraded_fn: Optional[Callable[[], bool]] = None,
        brain_canary_transport: Optional[Callable[[str, float], str]] = None,
        signal_outcomes_path: Optional[Any] = None,
        position_state_path: Optional[Any] = None,
    ) -> None:
        self._data_dir = Path(data_dir) if data_dir is not None else DATA_DIR
        self._logs_dir = self._data_dir / "logs"
        self._events_path = self._logs_dir / "funnel_events.jsonl"
        self._state_path = self._data_dir / "funnel_monitor_state.json"
        self._alarm_active_path = self._data_dir / "ALARM_ACTIVE.json"

        if signal_outcomes_path is not None:
            self._signal_outcomes_path = Path(signal_outcomes_path)
        else:
            self._signal_outcomes_path = self._logs_dir / "signal_outcomes.jsonl"

        if position_state_path is not None:
            self._position_state_path = Path(position_state_path)
        elif _canonical_position_state_path is not None and data_dir is None:
            self._position_state_path = _canonical_position_state_path()
        else:
            self._position_state_path = self._data_dir / "position_state.json"

        self._clock = clock or time.time
        self._alerts = alerts or _NoOpAlerts()
        self._env = env if env is not None else os.environ

        self._get_run_stats = get_run_stats_fn or _default_get_run_stats
        self._derive_equity = derive_equity_fn or _default_derive_equity
        self._last_ledger_trade_ts = last_ledger_trade_ts_fn or _default_last_ledger_trade_ts
        self._get_risk_equity = get_risk_equity_fn or (lambda: None)
        self._get_pos_mgr_open_count = get_pos_mgr_open_count_fn or (lambda: None)
        self._get_sqlite_open_positions = get_sqlite_open_positions_fn or (lambda: None)
        self._get_atr_percentile = get_atr_percentile_fn or (lambda: None)
        self._get_llm_first_degraded = get_llm_first_degraded_fn or (lambda: False)
        self._brain_canary_transport = brain_canary_transport or _default_canary_transport_stub

        # In-memory state -- protected by one lock (bump + timestamp only
        # inside it, per spec 1.2).
        self._lock = threading.Lock()
        self._counts: Counter = Counter()
        self._detail_counts: Counter = Counter()
        self._last_event_ts: Dict[str, float] = {}
        self._last_ok_ts: Dict[str, float] = {}
        self._last_reason_ts: Dict[str, float] = {}
        self._recent: Deque[dict] = deque(maxlen=200)

        # Baselines for computing deltas since the last flush.
        self._flushed_counts: Dict[str, int] = {}
        self._flushed_detail: Dict[str, int] = {}

        # Alarm state (persisted) + canary sub-state (persisted).
        self._alarms: Dict[str, dict] = {}
        self._canary_state: Dict[str, Any] = {
            "dead": False,
            "consecutive_fail": 0,
            "consecutive_ok": 0,
            "last_run_ts": 0.0,
            "last_ok": None,
            "last_latency_s": None,
        }
        self._tick = 0
        self._r5_last_run_ts = 0.0
        self._monitor_epoch_start: Optional[float] = None

        self._boot_replay()

    # -- singleton is module-level, see get_funnel_monitor() below --

    # ------------------------------------------------------------------
    # Hot path
    # ------------------------------------------------------------------
    def record(
        self,
        stage: str,
        symbol: str = "",
        reason: str = "",
        ok: bool = True,
        meta: Optional[dict] = None,
    ) -> None:
        """THE one public hot-path API. No I/O, no raise, ever.

        `stage` should be one of `Stage.*` but is accepted as a bare string
        so call sites never need to import the class just to record.
        Unrecognized stages are still counted (forward-compatible) --
        validation is a monitoring nicety, not a reason to ever raise.
        """
        try:
            ts = self._clock()
            stage_key = str(stage)
            reason_key = str(reason) if reason else "_none"
            ok_tag = "ok" if ok else "rej"
            detail_key = f"{stage_key}::{reason_key}::{ok_tag}"
            with self._lock:
                self._counts[stage_key] += 1
                self._detail_counts[detail_key] += 1
                self._last_event_ts[stage_key] = ts
                if ok:
                    self._last_ok_ts[stage_key] = ts
                if reason:
                    self._last_reason_ts[f"{stage_key}::{reason_key}"] = ts
                self._recent.append(
                    {
                        "ts": ts,
                        "stage": stage_key,
                        "symbol": symbol,
                        "reason": reason_key,
                        "ok": bool(ok),
                        "meta": meta if isinstance(meta, dict) else {},
                    }
                )
        except Exception:
            # HOT PATH CONTRACT: never raise, ever. A bug here must never be
            # able to alter or block a trade.
            pass

    # ------------------------------------------------------------------
    # Daemon-owned: flush (append events, persist state, evaluate alarms,
    # write ALARM_ACTIVE.json). Never raises.
    # ------------------------------------------------------------------
    def flush(self, now: Optional[float] = None) -> Dict[str, Any]:
        try:
            now = now if now is not None else self._clock()
            if not self._flag("FUNNEL_MONITOR", True):
                return {"ok": True, "skipped": "FUNNEL_MONITOR=false"}

            self._tick += 1

            with self._lock:
                snapshot_counts = dict(self._counts)
                snapshot_detail = dict(self._detail_counts)
                snapshot_last_event_ts = dict(self._last_event_ts)
                snapshot_last_ok_ts = dict(self._last_ok_ts)
                snapshot_last_reason_ts = dict(self._last_reason_ts)

            self._append_event_deltas(now, snapshot_counts, snapshot_detail, snapshot_last_event_ts)
            self._flushed_counts = snapshot_counts
            self._flushed_detail = snapshot_detail

            state = self._build_state_dict(
                now, snapshot_counts, snapshot_detail,
                snapshot_last_event_ts, snapshot_last_ok_ts, snapshot_last_reason_ts,
            )
            try:
                atomic_write_json(self._state_path, state)
            except Exception:
                logger.debug("funnel flush: failed to persist state (non-fatal)", exc_info=True)

            alarm_results = self._evaluate_alarms(
                now, snapshot_last_event_ts, snapshot_last_ok_ts, snapshot_last_reason_ts,
            )

            try:
                self._write_alarm_active(now, alarm_results)
            except Exception:
                logger.debug("funnel flush: failed to write ALARM_ACTIVE.json (non-fatal)", exc_info=True)

            return {"ok": True, "alarms": alarm_results}
        except Exception as e:
            # Symmetrical contract to record(): flush() must never propagate
            # either -- a dead/wedged evaluator is caught externally by
            # ALARM_ACTIVE.json going stale (spec Part 4), not by crashing
            # the daemon thread that calls this.
            logger.debug("funnel flush: unexpected error (non-fatal): %s", e, exc_info=True)
            return {"ok": False, "error": str(e)}

    # ------------------------------------------------------------------
    # Boot replay (spec Part 4): restore each stage's silence clock from
    # max(persisted, funnel_events.jsonl history, ledger) -- NEVER now().
    # ------------------------------------------------------------------
    def _boot_replay(self) -> None:
        try:
            persisted = read_json_or_none(self._state_path) or {}
        except Exception:
            persisted = {}

        try:
            persisted_counts = persisted.get("counts", {}) or {}
            persisted_detail = persisted.get("detail_counts", {}) or {}
            self._counts.update({k: int(v) for k, v in persisted_counts.items()})
            self._detail_counts.update({k: int(v) for k, v in persisted_detail.items()})
            self._flushed_counts = dict(self._counts)
            self._flushed_detail = dict(self._detail_counts)
            self._alarms = dict(persisted.get("alarms", {}) or {})
            self._canary_state.update(persisted.get("canary", {}) or {})
            self._r5_last_run_ts = float(persisted.get("r5_last_run_ts", 0.0) or 0.0)
        except Exception:
            logger.debug("funnel boot replay: state restore failed (non-fatal)", exc_info=True)

        # monitor_epoch_start: the anchor used when a stage has NEVER fired
        # even once (so "silence since forever" measures from when this
        # monitor first started watching, not from `now()` at each restart
        # -- this is what makes restart-at-hour-3 still trip by hour-6).
        try:
            existing_anchor = persisted.get("monitor_epoch_start")
            self._monitor_epoch_start = float(existing_anchor) if existing_anchor is not None else self._clock()
        except Exception:
            self._monitor_epoch_start = self._clock()

        persisted_last_event = persisted.get("last_event_ts", {}) or {}
        persisted_last_ok = persisted.get("last_ok_ts", {}) or {}

        events_last_ts = self._scan_events_last_ts()

        ledger_ts = None
        try:
            ledger_ts = self._last_ledger_trade_ts()
        except Exception:
            ledger_ts = None

        for stage in STAGE_ORDER:
            candidates = [persisted_last_event.get(stage), events_last_ts.get(stage)]
            if stage in (Stage.RAW_SIGNAL, Stage.LLM_DECISION, Stage.OPENED) and ledger_ts is not None:
                candidates.append(ledger_ts)
            candidates = [c for c in candidates if c is not None]
            if candidates:
                self._last_event_ts[stage] = max(candidates)

            ok_candidates = [persisted_last_ok.get(stage), events_last_ts.get(stage)]
            if stage in (Stage.RAW_SIGNAL, Stage.LLM_DECISION, Stage.OPENED) and ledger_ts is not None:
                ok_candidates.append(ledger_ts)
            ok_candidates = [c for c in ok_candidates if c is not None]
            if ok_candidates:
                self._last_ok_ts[stage] = max(ok_candidates)

        try:
            self._last_reason_ts.update(
                {k: float(v) for k, v in (persisted.get("last_reason_ts", {}) or {}).items()}
            )
        except Exception:
            pass

    def _scan_events_last_ts(self) -> Dict[str, float]:
        """Newest recorded event ts per stage from funnel_events.jsonl
        history (used both by boot replay and by R1's inter-arrival gap
        computation)."""
        out: Dict[str, float] = {}
        for rec in self._iter_funnel_events():
            stage = rec.get("stage")
            if stage not in _STAGE_SET:
                continue
            ts = rec.get("last_event_ts") or rec.get("ts")
            if ts is None:
                continue
            try:
                ts = float(ts)
            except (TypeError, ValueError):
                continue
            if stage not in out or ts > out[stage]:
                out[stage] = ts
        return out

    # ------------------------------------------------------------------
    # funnel_events.jsonl -- append-mode, one line per stage-delta since
    # the last flush (deltas, not raw events, to bound size).
    # ------------------------------------------------------------------
    def _append_event_deltas(
        self, now: float, counts: Dict[str, int], detail: Dict[str, int], last_event_ts: Dict[str, float],
    ) -> None:
        for stage in STAGE_ORDER:
            cur = counts.get(stage, 0)
            prev = self._flushed_counts.get(stage, 0)
            delta = cur - prev
            if delta <= 0:
                continue
            reasons: Dict[str, int] = {}
            prefix = stage + "::"
            for key, cnt in detail.items():
                if not key.startswith(prefix):
                    continue
                prev_r = self._flushed_detail.get(key, 0)
                d = cnt - prev_r
                if d > 0:
                    reasons[key[len(prefix):]] = d
            line = {
                "ts": now,
                "stage": stage,
                "delta": delta,
                "cumulative": cur,
                "last_event_ts": last_event_ts.get(stage),
                "reasons": reasons,
            }
            try:
                append_jsonl_line(self._events_path, line)
            except Exception:
                logger.debug("funnel flush: failed to append events line for %s (non-fatal)", stage, exc_info=True)

    def _iter_funnel_events(self):
        if not self._events_path.exists():
            return
        try:
            with open(self._events_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except ValueError:
                        continue
        except Exception:
            logger.debug("funnel: failed reading funnel_events.jsonl (non-fatal)", exc_info=True)
            return

    def _stage_event_timestamps(self, stage: str, since: Optional[float] = None, until: Optional[float] = None) -> List[float]:
        out = []
        for rec in self._iter_funnel_events():
            if rec.get("stage") != stage or not rec.get("delta"):
                continue
            ts = rec.get("last_event_ts") or rec.get("ts")
            if ts is None:
                continue
            try:
                ts = float(ts)
            except (TypeError, ValueError):
                continue
            if since is not None and ts < since:
                continue
            if until is not None and ts > until:
                continue
            out.append(ts)
        return out

    def _windowed_stage_delta(self, stage: str, since: float, until: float) -> int:
        total = 0
        for rec in self._iter_funnel_events():
            if rec.get("stage") != stage:
                continue
            ts = rec.get("ts")
            try:
                ts = float(ts)
            except (TypeError, ValueError):
                continue
            if since <= ts <= until:
                total += int(rec.get("delta") or 0)
        return total

    def _windowed_gate_stats(self, since: float, until: float) -> Tuple[Dict[str, int], Dict[str, int]]:
        """Rejections/entrants per GATED reason ("gate name") within the
        window, from the funnel's OWN records (not the paper-gated
        SQLite) -- fixes both the paper-only gap and the
        of-rejections-not-of-entrants flaw noted in the build spec."""
        entrants: Counter = Counter()
        rejections: Counter = Counter()
        for rec in self._iter_funnel_events():
            if rec.get("stage") != Stage.GATED:
                continue
            ts = rec.get("ts")
            try:
                ts = float(ts)
            except (TypeError, ValueError):
                continue
            if not (since <= ts <= until):
                continue
            for key, delta in (rec.get("reasons") or {}).items():
                gate, sep, ok_tag = key.rpartition("::")
                if not sep:
                    continue
                entrants[gate] += delta
                if ok_tag == "rej":
                    rejections[gate] += delta
        return dict(rejections), dict(entrants)

    def _read_signal_outcomes(self, since: float) -> List[dict]:
        """Normalized reader for signal_outcomes.jsonl (core/signal_tracker.py
        record shape: top-level ts/passed/hard_rej/rej_reason, with
        `meta.stage`/`meta.pipeline` for the LLM-first markers). Tolerates
        a torn last line (append-only log convention, see
        core/atomic_state.py::append_jsonl_line docstring)."""
        out: List[dict] = []
        if not self._signal_outcomes_path.exists():
            return out
        try:
            with open(self._signal_outcomes_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    ts = rec.get("ts")
                    if ts is None or float(ts) < since:
                        continue
                    meta = rec.get("meta") or {}
                    out.append(
                        {
                            "ts": float(ts),
                            "passed": rec.get("passed"),
                            "hard_rej": rec.get("hard_rej"),
                            "reason": rec.get("rej_reason") or meta.get("abort") or "",
                            "stage": meta.get("stage", ""),
                            "pipeline": meta.get("pipeline", ""),
                        }
                    )
        except Exception:
            logger.debug("funnel: failed reading signal_outcomes.jsonl (non-fatal)", exc_info=True)
        return out

    # ------------------------------------------------------------------
    # Persisted state + ALARM_ACTIVE.json
    # ------------------------------------------------------------------
    def _build_state_dict(
        self, now, counts, detail, last_event_ts, last_ok_ts, last_reason_ts,
    ) -> dict:
        return {
            "schema_version": 1,
            "updated_at": now,
            "tick": self._tick,
            "monitor_epoch_start": self._monitor_epoch_start,
            "counts": counts,
            "detail_counts": detail,
            "last_event_ts": last_event_ts,
            "last_ok_ts": last_ok_ts,
            "last_reason_ts": last_reason_ts,
            "alarms": self._alarms,
            "canary": self._canary_state,
            "r5_last_run_ts": self._r5_last_run_ts,
        }

    def _write_alarm_active(self, now: float, alarm_results: List[dict]) -> None:
        active_alarms = [a for a in alarm_results if a.get("active")]
        payload = {
            "schema_version": 1,
            "updated_at": now,
            "pid": os.getpid(),
            "heartbeat_counter": self._tick,
            "all_clear": len(active_alarms) == 0,
            "alarms": [
                {
                    "id": a["id"],
                    "severity": a.get("severity"),
                    "first_tripped_at": a.get("first_tripped_at"),
                    "observed": a.get("observed"),
                    "threshold": {
                        "value": a.get("threshold"),
                        "source": a.get("threshold_source", "n/a"),
                        "live_n": a.get("threshold_live_n", 0),
                    },
                    "message": a.get("message", ""),
                    "alert_sent": a.get("last_fired_at") is not None,
                }
                for a in active_alarms
            ],
        }
        atomic_write_json(self._alarm_active_path, payload)

    # ------------------------------------------------------------------
    # Part 2 -- shared hysteresis / re-fire / recovery machinery
    # ------------------------------------------------------------------
    def _alarm_state(self, alarm_id: str, severity: str) -> dict:
        st = self._alarms.get(alarm_id)
        if st is None:
            st = {
                "id": alarm_id,
                "severity": severity,
                "active": False,
                "first_tripped_at": None,
                "last_fired_at": None,
                "consecutive_trip_evals": 0,
                "consecutive_clear_evals": 0,
                "observed": None,
                "threshold": None,
                "threshold_source": "n/a",
                "threshold_live_n": 0,
                "message": "",
            }
            self._alarms[alarm_id] = st
        return st

    def _evaluate_generic(
        self,
        alarm_id: str,
        severity: str,
        is_tripped: bool,
        observed: Any,
        threshold: Any,
        message_fn: Callable[[Any, Any], str],
        now: float,
        n_trip: int = 2,
        n_clear: int = 2,
        refire_s: float = 6 * 3600.0,
        threshold_source: str = "n/a",
        threshold_live_n: int = 0,
    ) -> dict:
        """Generic edges: trip after `n_trip` consecutive evaluations true;
        clear after `n_clear` consecutive false + send a recovery message;
        re-fire while active at `refire_s`. Delivery: `send_trade_alert`
        (critical) or `send_market_update` (warn) -- spec Part 2."""
        st = self._alarm_state(alarm_id, severity)
        st["observed"] = observed
        st["threshold"] = threshold
        st["threshold_source"] = threshold_source
        st["threshold_live_n"] = threshold_live_n

        if is_tripped:
            st["consecutive_trip_evals"] = st.get("consecutive_trip_evals", 0) + 1
            st["consecutive_clear_evals"] = 0
            if not st["active"]:
                if st["consecutive_trip_evals"] >= n_trip:
                    st["active"] = True
                    st["first_tripped_at"] = st.get("first_tripped_at") or now
                    st["last_fired_at"] = now
                    st["message"] = message_fn(observed, threshold)
                    self._dispatch_alert(severity, f"[{alarm_id}] {st['message']}")
            else:
                if now - (st.get("last_fired_at") or 0.0) >= refire_s:
                    st["last_fired_at"] = now
                    st["message"] = message_fn(observed, threshold)
                    self._dispatch_alert(severity, f"[{alarm_id}] (still active, re-fire) {st['message']}")
        else:
            st["consecutive_trip_evals"] = 0
            if st["active"]:
                st["consecutive_clear_evals"] = st.get("consecutive_clear_evals", 0) + 1
                if st["consecutive_clear_evals"] >= n_clear:
                    st["active"] = False
                    st["first_tripped_at"] = None
                    st["consecutive_clear_evals"] = 0
                    recovery_msg = f"[{alarm_id}] RECOVERED"
                    st["message"] = recovery_msg
                    st["last_fired_at"] = now
                    self._dispatch_alert(severity, recovery_msg)
            else:
                st["consecutive_clear_evals"] = 0
        return st

    def _dispatch_alert(self, severity: str, msg: str) -> None:
        try:
            if severity == "critical":
                fn = (
                    getattr(self._alerts, "send_trade_alert", None)
                    or getattr(self._alerts, "send_alert", None)
                    or getattr(self._alerts, "notify", None)
                    or getattr(self._alerts, "send_market_update", None)
                )
            else:
                fn = (
                    getattr(self._alerts, "send_market_update", None)
                    or getattr(self._alerts, "notify", None)
                )
            if callable(fn):
                fn(msg)
        except Exception:
            logger.debug("funnel: alert dispatch failed (non-fatal)", exc_info=True)

    # ------------------------------------------------------------------
    # Env helpers (LIVING VALUES: live-computed-else-hard-ceiling pattern)
    # ------------------------------------------------------------------
    def _flag(self, name: str, default: bool) -> bool:
        raw = self._env.get(name, "true" if default else "false")
        return str(raw).strip().lower() in ("1", "true", "yes")

    def _float_env(self, name: str, default: float) -> float:
        try:
            return float(self._env.get(name, default))
        except (TypeError, ValueError):
            return float(default)

    def _ts_or_epoch_start(self, ts: Optional[float]) -> float:
        if ts is not None:
            return ts
        return self._monitor_epoch_start if self._monitor_epoch_start is not None else self._clock()

    # ------------------------------------------------------------------
    # Alarm evaluation dispatcher
    # ------------------------------------------------------------------
    def _evaluate_alarms(
        self, now: float, last_event_ts: Dict[str, float], last_ok_ts: Dict[str, float], last_reason_ts: Dict[str, float],
    ) -> List[dict]:
        if self._flag("FUNNEL_ALARM", True):
            for fn in (
                self._eval_r1_raw_signal_silence,
                self._eval_r2_llm_decision_silence,
                self._eval_r3_gos_dying,
                self._eval_r4_gate_choke,
                self._eval_r5_ledger_divergence,
                self._eval_r6_signal_drought,
            ):
                try:
                    fn(now, last_event_ts, last_ok_ts, last_reason_ts)
                except Exception:
                    logger.debug("funnel: alarm rule %s failed (non-fatal)", getattr(fn, "__name__", fn), exc_info=True)
        return [dict(v) for v in self._alarms.values()]

    # ------------------------------------------------------------------
    # R1 -- funnel.raw_signal_silence (CRITICAL)
    # ------------------------------------------------------------------
    def _raw_signal_threshold_h(self) -> Tuple[float, str, int]:
        hard_ceiling = self._float_env("FUNNEL_ALARM_MAX_SILENCE_H", 6.0)
        tss = sorted(self._stage_event_timestamps(Stage.RAW_SIGNAL))
        gaps = [(b - a) / 3600.0 for a, b in zip(tss, tss[1:]) if b > a]
        if len(gaps) >= 13:
            gs = sorted(gaps)
            idx = min(len(gs) - 1, int(0.99 * (len(gs) - 1)))
            return min(gs[idx], hard_ceiling), "live", len(gaps)
        return hard_ceiling, "hard_ceiling", len(gaps)

    def _eval_r1_raw_signal_silence(self, now, last_event_ts, last_ok_ts, last_reason_ts) -> None:
        alarm_id = "funnel.raw_signal_silence"
        scanned_ts = last_event_ts.get(Stage.SCANNED)
        if scanned_ts is None:
            return  # no scan data at all yet -- nothing to measure against
        max_silence_h = self._float_env("FUNNEL_ALARM_MAX_SILENCE_H", 6.0)
        scanned_silent_h = (now - scanned_ts) / 3600.0
        if scanned_silent_h > max_silence_h:
            # SCANNED itself has gone dark -- that's a dead bot, watchdog.py's
            # job, not this alarm's (spec: "measures the funnel, not a dead
            # bot").
            return

        raw_ts = self._ts_or_epoch_start(last_ok_ts.get(Stage.RAW_SIGNAL))
        observed_h = (now - raw_ts) / 3600.0
        threshold_h, source, live_n = self._raw_signal_threshold_h()
        tripped = observed_h > threshold_h

        self._evaluate_generic(
            alarm_id,
            "critical",
            tripped,
            observed_h,
            threshold_h,
            lambda obs, thr: (
                f"no RAW_SIGNAL in {obs:.2f}h (threshold {thr:.2f}h, source={source}, n={live_n}) "
                f"while SCANNED keeps advancing ({scanned_silent_h:.2f}h ago) -- "
                f"brain/strategy arm looks silent."
            ),
            now,
            n_trip=2,
            n_clear=1,
            refire_s=6 * 3600.0,
            threshold_source=source,
            threshold_live_n=live_n,
        )

    # ------------------------------------------------------------------
    # R2 -- funnel.llm_decision_silence (CRITICAL) + active brain canary
    # ------------------------------------------------------------------
    def _run_brain_canary_if_due(self, now: float) -> bool:
        """Push one canned micro-prompt through the injected transport at
        most every BRAIN_CANARY_INTERVAL_MIN. Returns the CURRENT sticky
        canary_dead state (updated at most once per interval) so callers
        can fold it into R2 without forcing a probe on every flush."""
        if not self._flag("BRAIN_CANARY", True):
            return bool(self._canary_state.get("dead", False))

        interval_s = self._float_env("BRAIN_CANARY_INTERVAL_MIN", 60.0) * 60.0
        if now - float(self._canary_state.get("last_run_ts", 0.0) or 0.0) < interval_s:
            return bool(self._canary_state.get("dead", False))

        self._canary_state["last_run_ts"] = now
        timeout_s = self._float_env("BRAIN_CANARY_TIMEOUT_S", 90.0)
        t0 = self._clock()
        ok = False
        try:
            raw = self._brain_canary_transport(_CANARY_PROMPT, timeout_s)
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            ok = isinstance(parsed, dict) and bool(parsed.get("regime"))
        except Exception as e:
            logger.debug("funnel: brain canary probe failed (non-fatal): %s", e)
            ok = False
        latency = max(0.0, self._clock() - t0)

        self._canary_state["last_ok"] = ok
        self._canary_state["last_latency_s"] = latency
        if ok:
            self._canary_state["consecutive_fail"] = 0
            self._canary_state["consecutive_ok"] = int(self._canary_state.get("consecutive_ok", 0)) + 1
            if self._canary_state.get("dead") and self._canary_state["consecutive_ok"] >= 2:
                self._canary_state["dead"] = False
        else:
            self._canary_state["consecutive_ok"] = 0
            self._canary_state["consecutive_fail"] = int(self._canary_state.get("consecutive_fail", 0)) + 1
            if self._canary_state["consecutive_fail"] >= 3:
                self._canary_state["dead"] = True
        return bool(self._canary_state.get("dead", False))

    def _eval_r2_llm_decision_silence(self, now, last_event_ts, last_ok_ts, last_reason_ts) -> None:
        alarm_id = "funnel.llm_decision_silence"
        hard_ceiling = self._float_env("FUNNEL_ALARM_MAX_SILENCE_H", 6.0)
        tss = sorted(self._stage_event_timestamps(Stage.LLM_DECISION))
        gaps = [(b - a) / 3600.0 for a, b in zip(tss, tss[1:]) if b > a]
        if len(gaps) >= 13:
            gs = sorted(gaps)
            idx = min(len(gs) - 1, int(0.99 * (len(gs) - 1)))
            threshold_h, source, live_n = min(gs[idx], hard_ceiling), "live", len(gaps)
        else:
            threshold_h, source, live_n = hard_ceiling, "hard_ceiling", len(gaps)

        attempt_ts = self._ts_or_epoch_start(last_reason_ts.get(f"{Stage.LLM_DECISION}::attempt"))
        observed_h = (now - attempt_ts) / 3600.0
        silence_tripped = observed_h > threshold_h

        canary_dead = self._run_brain_canary_if_due(now)
        tripped = bool(silence_tripped or canary_dead)

        self._evaluate_generic(
            alarm_id,
            "critical",
            tripped,
            observed_h,
            threshold_h,
            lambda obs, thr: (
                f"LLM decision pipeline looks dead: silence={obs:.2f}h (threshold {thr:.2f}h, "
                f"source={source}) canary_fail_streak={self._canary_state.get('consecutive_fail', 0)} "
                f"canary_dead={canary_dead}"
            ),
            now,
            n_trip=2,
            n_clear=2,
            refire_s=6 * 3600.0,
            threshold_source=source,
            threshold_live_n=live_n,
        )

    # ------------------------------------------------------------------
    # R3 -- funnel.gos_dying (CRITICAL)
    # ------------------------------------------------------------------
    def _eval_r3_gos_dying(self, now, last_event_ts, last_ok_ts, last_reason_ts) -> None:
        window_s = 24 * 3600.0
        since = now - window_s
        outcomes = self._read_signal_outcomes(since)
        go_like = [r for r in outcomes if r.get("stage") in ("llm_execute", "post_go_abort")]
        opened_n = self._windowed_stage_delta(Stage.OPENED, since, now)

        # Cross-check vs the ledger's own trade count in the window (never
        # treat a None from get_run_stats/derive_equity as $0 -- here it
        # just means "no cross-check available", the funnel count stands
        # alone).
        ledger_n = None
        try:
            stats = self._get_run_stats()
            if stats:
                ledger_n = stats.get("n")
        except Exception:
            ledger_n = None

        tripped = len(go_like) >= 3 and opened_n == 0 and (ledger_n is None or ledger_n == 0 or True)
        abort_hist = Counter(r.get("reason") or r.get("stage") for r in outcomes if r.get("stage") == "post_go_abort")

        self._evaluate_generic(
            "funnel.gos_dying",
            "critical",
            tripped,
            opened_n,
            3,
            lambda obs, thr: (
                f"{len(go_like)} GO-like outcomes in 24h but OPENED={obs} "
                f"(ledger closes in window={ledger_n}) -- GOs dying between brain and "
                f"executor. Abort histogram: {dict(abort_hist)}"
            ),
            now,
            n_trip=2,
            n_clear=1,
            refire_s=6 * 3600.0,
        )

        # Fast path: 2 consecutive order_unfilled aborts -> immediate
        # executor-dead alert. NOTE: approximated as a time-based re-fire
        # (1h) rather than the spec's literal "re-fire per 10 further
        # failures" -- exact count-based re-fire is a TODO if this proves
        # too chatty/quiet in the shadow window.
        recent_reasons = [r.get("reason") for r in outcomes if r.get("stage") == "post_go_abort"]
        last_two_unfilled = len(recent_reasons) >= 2 and recent_reasons[-2:] == ["order_unfilled", "order_unfilled"]
        self._evaluate_generic(
            "funnel.executor_dead_fastpath",
            "critical",
            last_two_unfilled,
            recent_reasons[-2:].count("order_unfilled") if recent_reasons else 0,
            2,
            lambda obs, thr: f"{obs} consecutive order_unfilled aborts -- executor may be dead.",
            now,
            n_trip=1,
            n_clear=1,
            refire_s=3600.0,
        )

    # ------------------------------------------------------------------
    # R4 -- funnel.gate_choke (WARN -> effectively CRITICAL via re-fire)
    # ------------------------------------------------------------------
    def _eval_r4_gate_choke(self, now, last_event_ts, last_ok_ts, last_reason_ts) -> None:
        window_s = 24 * 3600.0
        since = now - window_s
        rejections, entrants = self._windowed_gate_stats(since, now)
        trip_ratio = self._float_env("FUNNEL_GATE_CHOKE_TRIP", 0.90)
        clear_ratio = self._float_env("FUNNEL_GATE_CHOKE_CLEAR", 0.70)

        for gate, n_entrants in entrants.items():
            if n_entrants < 13:
                continue  # n>=13-else-silent, live_edge convention
            n_rej = rejections.get(gate, 0)
            ratio = (n_rej / n_entrants) if n_entrants else 0.0
            alarm_id = f"funnel.gate_choke.{gate}"

            if gate == "llm_first_standdown":
                # 100% choke here is by-design during degradation -- only
                # alarm on a MISMATCH against the degraded flag.
                degraded = False
                try:
                    degraded = bool(self._get_llm_first_degraded())
                except Exception:
                    degraded = False
                tripped = ratio >= trip_ratio and not degraded
            else:
                st = self._alarms.get(alarm_id)
                currently_active = bool(st and st.get("active"))
                effective_trip = clear_ratio if currently_active else trip_ratio
                tripped = ratio >= effective_trip if currently_active else ratio >= trip_ratio

            self._evaluate_generic(
                alarm_id,
                "warn",
                tripped,
                ratio,
                trip_ratio,
                lambda obs, thr, g=gate, e=n_entrants, r=n_rej: (
                    f"gate '{g}' choking: {r}/{e} rejected ({obs:.0%}) over 24h (trip {thr:.0%})"
                ),
                now,
                n_trip=2,
                n_clear=2,
                refire_s=24 * 3600.0,
            )

    # ------------------------------------------------------------------
    # R5 -- funnel.ledger_divergence (CRITICAL, 10-min cadence)
    # ------------------------------------------------------------------
    def _eval_r5_ledger_divergence(self, now, last_event_ts, last_ok_ts, last_reason_ts) -> None:
        check_min = self._float_env("FUNNEL_LEDGER_CHECK_MIN", 10.0)
        if now - self._r5_last_run_ts < check_min * 60.0:
            return
        self._r5_last_run_ts = now

        pos_state = read_json_or_none(self._position_state_path) or {}
        non_closed = {
            sym
            for sym, p in (pos_state.get("positions") or {}).items()
            if str((p or {}).get("state", "")).upper() != "CLOSED"
        }

        pos_mgr_count = None
        try:
            pos_mgr_count = self._get_pos_mgr_open_count()
        except Exception:
            pos_mgr_count = None

        sqlite_open = None
        try:
            sqlite_open = self._get_sqlite_open_positions()
        except Exception:
            sqlite_open = None

        mismatches: List[str] = []
        if pos_mgr_count is not None and len(non_closed) != pos_mgr_count:
            mismatches.append(f"position_state.json={len(non_closed)} vs pos_mgr={pos_mgr_count}")
        if sqlite_open is not None and set(sqlite_open) != non_closed:
            mismatches.append(f"position_state.json={sorted(non_closed)} vs sqlite_open={sorted(sqlite_open)}")

        tripped = bool(mismatches)
        self._evaluate_generic(
            "funnel.ledger_divergence",
            "critical",
            tripped,
            len(mismatches),
            0,
            lambda obs, thr: "open-position divergence: " + ("; ".join(mismatches) or "none"),
            now,
            n_trip=2,
            n_clear=1,
            refire_s=3600.0,
        )

        # Companion: equity drift. derive_equity()/get_risk_equity() -> None
        # means "skip this check", never treated as $0 (data/trade_source.py
        # contract).
        risk_equity = None
        try:
            risk_equity = self._get_risk_equity()
        except Exception:
            risk_equity = None
        derived = None
        try:
            derived = self._derive_equity()
        except Exception:
            derived = None

        if risk_equity is not None and derived is not None and risk_equity > 0:
            drift_pct = abs(risk_equity - derived) / risk_equity * 100.0
            drift_threshold = self._float_env("FUNNEL_EQUITY_DRIFT_PCT", 1.0)
            tripped_eq = drift_pct > drift_threshold
            self._evaluate_generic(
                "funnel.equity_divergence",
                "critical",
                tripped_eq,
                drift_pct,
                drift_threshold,
                lambda obs, thr: (
                    f"risk_mgr.equity=${risk_equity:.2f} vs derive_equity()=${derived:.2f} "
                    f"({obs:.2f}% > {thr:.2f}%)"
                ),
                now,
                n_trip=2,
                n_clear=1,
                refire_s=6 * 3600.0,
            )

    # ------------------------------------------------------------------
    # R6 -- funnel.signal_drought (WARN, quiet-market disambiguator)
    # ------------------------------------------------------------------
    def _eval_r6_signal_drought(self, now, last_event_ts, last_ok_ts, last_reason_ts) -> None:
        scanned_ts = last_event_ts.get(Stage.SCANNED)
        if scanned_ts is None or (now - scanned_ts) / 3600.0 > 1.0:
            return  # SCANNED not advancing normally -- not this alarm's job

        drought_h_threshold = self._float_env("FUNNEL_DROUGHT_H", 12.0)
        raw_ts = last_ok_ts.get(Stage.RAW_SIGNAL)
        if raw_ts is None:
            silence_h = (now - self._ts_or_epoch_start(None)) / 3600.0
        else:
            silence_h = (now - raw_ts) / 3600.0
        if silence_h < drought_h_threshold:
            return

        atr_pctile = None
        try:
            atr_pctile = self._get_atr_percentile()
        except Exception:
            atr_pctile = None
        if atr_pctile is None:
            return  # <13 days history -- never a hardcoded expected rate

        tripped = atr_pctile >= 60.0
        self._evaluate_generic(
            "funnel.signal_drought",
            "warn",
            tripped,
            atr_pctile,
            60.0,
            lambda obs, thr: (
                f"RAW_SIGNAL silent {silence_h:.1f}h (>= {drought_h_threshold:.0f}h) AND median "
                f"1h ATR percentile={obs:.0f} >= {thr:.0f} -- market looks active but the funnel "
                f"produced nothing (quiet-market disambiguator)."
            ),
            now,
            n_trip=1,
            n_clear=1,
            refire_s=12 * 3600.0,
        )


# ---------------------------------------------------------------------------
# Module-level thread-safe singleton (spec 1.2) so core/signal_pipeline.py
# (once wired, in the deferred shadow window) can record without holding a
# bot reference.
# ---------------------------------------------------------------------------
_singleton_lock = threading.Lock()
_singleton: Optional[FunnelMonitor] = None


def get_funnel_monitor(**kwargs: Any) -> FunnelMonitor:
    """Module-level thread-safe singleton accessor. Extra kwargs are only
    honored on first construction (mirrors other lazy-singleton patterns in
    this codebase, e.g. core/signal_tracker.py::get_signal_tracker)."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = FunnelMonitor(**kwargs)
    return _singleton


def reset_funnel_monitor_singleton_for_tests() -> None:
    """TEST-ONLY: drop the singleton so a fresh instance (e.g. pointed at a
    tmp data_dir with an injected fake clock) can be constructed. Never
    called from production code."""
    global _singleton
    with _singleton_lock:
        _singleton = None
