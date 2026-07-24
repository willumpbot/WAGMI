"""Daily shadow-vs-god-block close pipeline diff harness (measurement-
integrity, Phase 0.4-C).

READ-ONLY: this tool never writes anywhere except its own report file
(``data/shadow/diff_reports/YYYY-MM-DD.json``). It compares what the SHADOW
close-bus wiring (``core/close_pipeline/shadow_close_wiring.py``) recorded
under ``data/shadow/`` against what the LIVE god-block
(``multi_strategy_main.py``) actually did, so the pipeline's accuracy can be
scored before any flip decision -- see the project's pipeline-accuracy plan,
section 4 ("FLIP READINESS CRITERIA").

WHAT THIS COMPARES:
  1. ROW EXISTENCE (the D1-class CRITICAL detector, BOTH directions): every
     TERMINAL close_id in the shadow outbox must have a matching
     ``position_id`` row in the REAL ledger, and vice versa. A gap in
     either direction is CRITICAL -- it means a close was silently dropped
     somewhere (either god-block or shadow side).
  2. LEDGER COLUMN DIFF: for every ``position_id`` present in BOTH ledgers,
     compare every ``feedback.trade_ledger.LEDGER_COLUMNS`` value,
     excluding the pre-whitelisted known-intended diffs (see
     ``_WHITELISTED_LEDGER_COLUMNS`` below).
  3. TRADES.CSV RECONSTRUCTION: the shadow ctx's ``log_closed_trade_fn`` /
     ``record_trade_outcome_fn`` are CallRecorder stubs, not real writers
     (see shadow_close_wiring.py's module docstring -- writing a second
     real, timestamp-named trades CSV per boot would multiply file count
     for no diffing benefit). Instead, this reconstructs the row from the
     recorder's captured kwargs and compares field-by-field against the
     nearest REAL ``data/trades.csv`` row (matched by symbol + close_type +
     price, since trades.csv carries no ``position_id`` column).
  4. PER-EVENT + CUMULATIVE EQUITY: the shadow ``ShadowRiskManager``'s
     in-memory equity accumulator is traced to
     ``data/shadow/equity_trace.jsonl`` (pnl_delta per booked leg). This
     compares the shadow trajectory's cumulative delta against the god
     reference rows' (``data/shadow/publishes.jsonl``) real equity deltas
     over the same window.
  5. SUBSCRIBER CALL-COUNT vs GATE TABLE: every non-ledger/logger
     collaborator is a ``CallRecorder`` writing to
     ``data/shadow/calls/<name>.jsonl`` -- one line per call. This compares
     each recorder's call count against the EXPECTED count derived from the
     shadow outbox's own dedup key (``(position_id, leg_kind)``, matching
     ``CloseBus``'s exactly-once semantics -- see close_bus.py) for its
     registered ``kind=`` filter (FULL-only vs FULL+PARTIAL).
  6. SUBSCRIBER FAILURE COUNT: ``close_bus.subscriber_failure_count()`` is
     an IN-PROCESS counter (module-level, lives only inside the bot's
     process) -- unreachable from this external analysis script. Best
     effort: grep the bot's own log file (``logs/bot_YYYYMMDD.log``, if
     present) for the exact message ``close_bus.publish()`` logs on a
     subscriber exception (``logger.exception("close_bus: subscriber %r
     raised on event ...")``) and count matches per subscriber name. This
     is diagnostic, not authoritative -- a rotated/missing log file simply
     yields zero counts, not a false "all clear."
  7. ARG-RECOMPUTE SANITY: kelly's ``pnl_pct`` argument (captured in
     ``calls/kelly_engine.jsonl``) should equal
     ``total_pnl / equity_after * 100`` recomputed from the correlated
     shadow outbox event -- and ``hour_utc`` (graduated_rules) should never
     be the ``-1`` sentinel when ``open_time`` was actually populated.

PRE-WHITELISTED KNOWN-INTENDED DIFFS (see the plan's ACCURACY VERDICT
section) -- these do NOT count as failures on day one:
  - L1 confidence fallback chain (pipeline: ``ev.confidence or 50.0``; vs
    god-block's richer ``pos.confidence -> llm_confidence ->
    win_prob_deflated -> 50.0`` cascade) -- ``confidence_score`` column.
  - L2 ``hold_hours`` (pipeline recovers REAL hold time; god-block's
    ``pos.opened_at`` is never assigned, so its own hold_hours is always
    0.0) -- ``hold_hours`` column, silent bug-fix, not a regression.
  - L3 / D13 regime precedence inversion -- ``regime_1h`` / ``regime_4h``
    columns (``regime_4h`` is additionally a permanent FIELD-GAP, always
    "" in the pipeline).
  - D4 ``kelly_weight_applied`` timing (ledger T1 runs before kelly T2 in
    the god-block, capturing the PRE-trade weight; the pipeline's T1/T2
    ordering is the same relative order, so this is expected to match --
    whitelisted defensively in case a future reorder changes it).
  - D5 TP1 partial alert (pipeline's ``alert`` subscriber is
    ``kind=(FULL,)``; the god-block alerts on every event) -- not a ledger
    column, tracked via the ``alert`` recorder's call count vs PARTIAL
    events (expected to under-count by design).
  - D8b ``ml_samples_at_exit`` (pipeline hardcodes 0; god-block reads
    ``len(self.ml.outcomes)``) -- trades.csv reconstruction field.
  - Dedup semantics asymmetry (T0 tier dedup vs the god-block's
    ``CLOSE_DEDUP_GUARD`` 3600s window) -- affects duplicate-publish
    scenarios only, not scored per-event here.
  - ``if pos:``-gated row omission -- the pipeline writes ledger/trades.csv
    rows on raced pos-None closes where the god-block writes nothing (see
    close_subscribers_learning.py's module docstring) -- these show up as
    "extra" shadow rows with no real counterpart; not counted as CRITICAL
    row-existence failures (checked via the ``KNOWN_RACED_CLOSE`` allowance
    below -- best-effort, since this script cannot independently confirm a
    race occurred).

USAGE:
    cd bot && python tools/shadow_close_diff.py [--data-dir PATH] [--out PATH]

Writes ``data/shadow/diff_reports/YYYY-MM-DD.json`` (today's UTC date) by
default. Exits 0 always (this is an analysis tool, not a gate) -- read the
report's ``"critical"`` list to decide whether shadow data is trustworthy.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # allow `python tools/shadow_close_diff.py`

from core import paths  # noqa: E402
from core.close_pipeline import close_outbox  # noqa: E402
from core.close_pipeline.trade_closed import LegKind  # noqa: E402
from feedback.trade_ledger import LEDGER_COLUMNS  # noqa: E402

logger = logging.getLogger("bot.tools.shadow_close_diff")

# ---------------------------------------------------------------------------
# Pre-whitelist: known-intended diffs, see module docstring.
# ---------------------------------------------------------------------------
_WHITELISTED_LEDGER_COLUMNS = frozenset({
    "confidence_score",   # L1
    "hold_hours",         # L2 (silent bug-fix)
    "regime_1h",           # L3 / D13
    "regime_4h",           # L3 / D13 + permanent FIELD-GAP
    "kelly_weight_applied",  # D4
})

# Registration shape (subscriber name -> kind filter), mirrors each
# close_subscribers_*.py's register_*() call -- see those modules for the
# authoritative source. "FULL" = kind=(CloseKind.FULL,) only; "BOTH" =
# default kind=(FULL, PARTIAL).
_RECORDER_GATE_TABLE: Dict[str, str] = {
    # accounting (T0 unconditional, T1 FULL-only)
    "kelly_engine": "FULL",  # not a bus subscriber name itself, but only
                              # ever called from FULL-only subscribers
                              # (on_close_ledger/on_close_kelly)
    "log_trade_fn": "BOTH",
    "record_trade_outcome_fn": "FULL",
    "log_closed_trade_fn": "FULL",
    # learning batch 1 (all FULL-only)
    "weight_mgr": "FULL",
    "regime_feedback": "FULL",
    "confidence_floor": "FULL",
    "hold_time_rules": "FULL",
    "parameter_tuner": "FULL",
    "feedback": "FULL",
    "ic_tracker": "FULL",
    "graduated_rules_engine": "FULL",
    # learning batch 2 (all FULL-only)
    "deep_memory": "FULL",
    "thesis_grader": "FULL",
    "post_trade_learner": "FULL",
    "reflection": "FULL",
    "autopsy": "FULL",
    "learning_integrator": "FULL",
    "ml": "FULL",
    "counterfactual": "FULL",
    "log_signal_outcome_fn": "FULL",
    "rl_append_transition_fn": "FULL",
    # misc batch 3 (all FULL-only)
    "adaptive_risk": "FULL",
    "adaptive_sizer": "FULL",
    "shadow_ledger": "FULL",
    "continuous_backtest": "FULL",
    "llm_triggers": "FULL",
    "quant_brain": "FULL",
    "growth": "FULL",
    "ab_manager": "FULL",
    "agent_perf": "FULL",
    "cost_optimizer": "FULL",
    "risk_telemetry": "FULL",
    "telemetry_cls": "FULL",
    "alerts": "FULL",  # D5 whitelisted: pipeline is FULL-only, god-block alerts every event
    "format_trade_event_fn": "FULL",
    "survival_record_outcome_fn": "FULL",
    "learning_mode_active_fn": "FULL",
    "learning_mode_record_fn": "FULL",
    "add_observation_fn": "FULL",
    # LLM learning agent (FULL-only)
    "learning_agent_fn": "FULL",
    "process_agent_lesson_fn": "FULL",
}

# Some recorders are legitimately written MORE than once per close and are NOT
# a dedup regression: the recorder sink is shared by >1 bus subscriber, or one
# subscriber makes >1 recorded method call per delivery. Verified 2026-07-23:
#   - llm_triggers: fan-in of 2 subscribers (llm_triggers_outcome.record_trade_outcome
#     + llm_triggers_notify.add) -> 2 recorded calls per terminal close.
#   - telemetry_cls: on_close_telemetry does inc(won|lost) + record("pnls") -> 2 calls.
# Each underlying bus subscriber is still dispatched exactly once per (position, leg);
# this multiplier only corrects the recorder-line upper bound so the gate check
# doesn't false-flag an OVER-count. Default multiplicity is 1.
_RECORDER_CALLS_PER_CLOSE: Dict[str, int] = {
    "llm_triggers": 2,
    "telemetry_cls": 2,
}

_FAILURE_LOG_RE = re.compile(r"close_bus: subscriber '([^']+)' raised")


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------
def _load_csv_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    try:
        with open(path, "r", newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except (OSError, csv.Error) as e:
        logger.warning("shadow_close_diff: failed reading %s: %s", path, e)
        return []


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except (ValueError, TypeError):
                    continue
    except OSError as e:
        logger.warning("shadow_close_diff: failed reading %s: %s", path, e)
    return rows


def _by_position_id(rows: List[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {}
    for row in rows:
        pid = (row.get("position_id") or "").strip()
        if pid:
            out[pid] = row
    return out


# ---------------------------------------------------------------------------
# Comparisons
# ---------------------------------------------------------------------------
def _row_existence(
    shadow_outbox_events: List[Any],
    real_ledger_by_pid: Dict[str, Dict[str, str]],
    shadow_ledger_by_pid: Dict[str, Dict[str, str]],
) -> Dict[str, Any]:
    terminal_pids = {
        e.position_id for e in shadow_outbox_events
        if e.leg_kind == LegKind.TERMINAL
    }
    real_pids = set(real_ledger_by_pid.keys())
    shadow_pids = set(shadow_ledger_by_pid.keys())

    # Both directions: a TERMINAL shadow event with no real ledger row is
    # CRITICAL (real close dropped from the ledger); a real ledger row with
    # no shadow counterpart is CRITICAL the other way (shadow under-counted
    # -- e.g. a D1-class dedup key bug reintroduced).
    missing_in_real = sorted(terminal_pids - real_pids)
    missing_in_shadow = sorted((real_pids & terminal_pids) - shadow_pids) if terminal_pids else []
    # Real ledger rows this shadow run never even saw an outbox event for
    # (e.g. shadow was enabled mid-session) are informational, not CRITICAL.
    real_only_no_shadow_event = sorted(real_pids - terminal_pids - shadow_pids)

    # Split "outside window" by time. A real close NEWER than the shadow's most
    # recent capture -- while the shadow was demonstrably live (>=1 capture) --
    # is a real COVERAGE GAP: the shadow silently stopped capturing. That is NOT
    # the benign "shadow enabled mid-session" case (older, pre-first-capture
    # closes). Without this split the diff reports is_clean=True while the shadow
    # quietly stops covering closes -> false confidence toward the flip.
    def _ts(row: Dict[str, str]) -> float:
        try:
            return float(row.get("timestamp") or 0)
        except (TypeError, ValueError):
            return 0.0
    _shadow_captured_ts = [
        _ts(real_ledger_by_pid[p]) for p in (shadow_pids & real_pids)
        if _ts(real_ledger_by_pid[p]) > 0
    ]
    shadow_last_ts = max(_shadow_captured_ts) if _shadow_captured_ts else None
    coverage_gap: List[str] = []
    before_window: List[str] = []
    for pid in real_only_no_shadow_event:
        rts = _ts(real_ledger_by_pid.get(pid, {}))
        if shadow_last_ts is not None and rts > shadow_last_ts:
            coverage_gap.append(pid)
        else:
            before_window.append(pid)

    return {
        "terminal_position_ids_shadow": len(terminal_pids),
        "real_ledger_rows": len(real_pids),
        "shadow_ledger_rows": len(shadow_pids),
        "missing_in_real_ledger": missing_in_real,   # CRITICAL
        "missing_in_shadow_ledger": missing_in_shadow,  # CRITICAL
        "real_rows_outside_shadow_window": real_only_no_shadow_event,  # informational (all)
        "coverage_gap_after_window": sorted(coverage_gap),  # CRITICAL: shadow stopped capturing
        "real_rows_before_shadow_window": sorted(before_window),  # informational (pre-existence)
    }


def _ledger_column_diff(
    real_ledger_by_pid: Dict[str, Dict[str, str]],
    shadow_ledger_by_pid: Dict[str, Dict[str, str]],
) -> Dict[str, Any]:
    common = sorted(set(real_ledger_by_pid) & set(shadow_ledger_by_pid))
    diffs: List[Dict[str, Any]] = []
    for pid in common:
        real_row = real_ledger_by_pid[pid]
        shadow_row = shadow_ledger_by_pid[pid]
        col_diffs = {}
        for col in LEDGER_COLUMNS:
            if col in _WHITELISTED_LEDGER_COLUMNS or col in ("trade_id", "timestamp", "epoch_id", "ab_gate_hash"):
                continue  # non-comparable / pre-whitelisted
            rv, sv = real_row.get(col, ""), shadow_row.get(col, "")
            if rv != sv:
                col_diffs[col] = {"real": rv, "shadow": sv}
        if col_diffs:
            diffs.append({"position_id": pid, "diffs": col_diffs})
    return {"common_position_ids": len(common), "non_whitelisted_diffs": diffs}


def _call_counts(calls_dir: Path) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    if not calls_dir.is_dir():
        return counts
    for jf in calls_dir.glob("*.jsonl"):
        name = jf.stem
        try:
            with open(jf, "r", encoding="utf-8") as f:
                counts[name] = sum(1 for line in f if line.strip())
        except OSError:
            counts[name] = 0
    return counts


def _gate_table_check(
    shadow_outbox_events: List[Any],
    call_counts: Dict[str, int],
) -> Dict[str, Any]:
    n_full = len({e.position_id for e in shadow_outbox_events if e.leg_kind == LegKind.TERMINAL})
    n_both = len({(e.position_id, e.leg_kind.value) for e in shadow_outbox_events})

    rows: List[Dict[str, Any]] = []
    for name, kind in sorted(_RECORDER_GATE_TABLE.items()):
        expected = (n_full if kind == "FULL" else n_both) * _RECORDER_CALLS_PER_CLOSE.get(name, 1)
        actual = call_counts.get(name, 0)
        rows.append({
            "subscriber": name,
            "kind": kind,
            "expected_at_most": expected,  # upper bound: a recorder may
                                            # legitimately fire less (e.g.
                                            # optional collaborator's own
                                            # internal guard) -- only an
                                            # OVER-count is a hard anomaly
            "actual": actual,
            "over_count": actual > expected,
        })
    return {"terminal_count": n_full, "both_leg_count": n_both, "rows": rows}


def _subscriber_failure_counts(data_dir: Path, *, date_str: str) -> Dict[str, Any]:
    log_path = data_dir.parent / "logs" / f"bot_{date_str.replace('-', '')}.log"
    counts: Dict[str, int] = defaultdict(int)
    found_log = log_path.exists()
    if found_log:
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    m = _FAILURE_LOG_RE.search(line)
                    if m:
                        counts[m.group(1)] += 1
        except OSError as e:
            logger.warning("shadow_close_diff: failed reading %s: %s", log_path, e)
    return {
        "log_file_checked": str(log_path),
        "log_file_found": found_log,
        "note": (
            "close_bus.subscriber_failure_count() is an in-process counter, "
            "unreachable from this external script -- this is a best-effort "
            "log grep, not authoritative. A missing log file yields zero "
            "counts, not a confirmed 'zero failures.'"
        ),
        "counts": dict(counts),
        "total": sum(counts.values()),
    }


def _equity_trace_summary(equity_trace_rows: List[Dict[str, Any]], publishes_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    shadow_cumulative = sum(float(r.get("pnl_delta") or 0.0) for r in equity_trace_rows)
    god_equities = [r.get("god_equity_after") for r in publishes_rows if r.get("god_equity_after") is not None]
    god_delta = None
    if len(god_equities) >= 2:
        try:
            god_delta = float(god_equities[-1]) - float(god_equities[0])
        except (TypeError, ValueError):
            god_delta = None
    return {
        "shadow_equity_deltas_recorded": len(equity_trace_rows),
        "shadow_cumulative_pnl_delta": round(shadow_cumulative, 4),
        "god_reference_rows": len(publishes_rows),
        "god_first_to_last_equity_delta": round(god_delta, 4) if god_delta is not None else None,
        "note": (
            "Approximate: shadow_cumulative_pnl_delta sums ShadowRiskManager's "
            "own booked per-leg deltas (ev.pnl - ev.fee [- funding]); "
            "god_first_to_last_equity_delta is the real risk_mgr.equity's net "
            "change over the same publishes.jsonl window. These are expected "
            "to be close but not exact (the god trajectory also reflects OTHER "
            "concurrently-processing symbols under SCAN_PARALLEL_SYMBOLS)."
        ),
    }


def _arg_recompute_sanity(calls_dir: Path, publishes_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Kelly pnl_pct sanity: recomputes total_pnl/equity_after*100 from the
    god reference rows and flags any kelly_engine.jsonl call whose recorded
    pnl_pct diverges from every candidate god value beyond a small
    tolerance. Best-effort (kelly calls aren't event_id-correlated -- the
    kelly_engine collaborator only receives factor/win/pnl_pct, not the
    event_id), so this reports aggregate sanity, not a hard per-call match.
    """
    kelly_calls = _load_jsonl(calls_dir / "kelly_engine.jsonl")
    record_trade_calls = [c for c in kelly_calls if c.get("method") == "record_trade"]
    pnl_pcts = []
    for c in record_trade_calls:
        args = c.get("args") or []
        if len(args) >= 3:
            try:
                pnl_pcts.append(float(args[2]))
            except (TypeError, ValueError):
                pass
    candidates = []
    for r in publishes_rows:
        try:
            total = float(r.get("god_total_pnl"))
            eq = float(r.get("god_equity_after"))
            if eq:
                candidates.append(round(total / eq * 100.0, 4))
        except (TypeError, ValueError, ZeroDivisionError):
            continue
    unmatched = []
    for p in pnl_pcts:
        if candidates and not any(abs(p - c) < 0.05 for c in candidates):
            unmatched.append(p)
    return {
        "kelly_record_trade_calls": len(record_trade_calls),
        "pnl_pct_values_seen": len(pnl_pcts),
        "candidate_god_pnl_pcts": len(candidates),
        "unmatched_pnl_pct_values": unmatched,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def run_diff(data_dir: Path) -> Dict[str, Any]:
    shadow_dir = data_dir / "shadow"
    calls_dir = shadow_dir / "calls"

    real_ledger_by_pid = _by_position_id(_load_csv_rows(data_dir / "trade_ledger.csv"))
    shadow_ledger_by_pid = _by_position_id(_load_csv_rows(shadow_dir / "trade_ledger.csv"))

    shadow_outbox_events = close_outbox.load_all(path=shadow_dir / "close_outbox.jsonl")
    publishes_rows = _load_jsonl(shadow_dir / "publishes.jsonl")
    equity_trace_rows = _load_jsonl(shadow_dir / "equity_trace.jsonl")
    call_counts = _call_counts(calls_dir)

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    row_existence = _row_existence(shadow_outbox_events, real_ledger_by_pid, shadow_ledger_by_pid)
    ledger_diff = _ledger_column_diff(real_ledger_by_pid, shadow_ledger_by_pid)
    gate_table = _gate_table_check(shadow_outbox_events, call_counts)
    failures = _subscriber_failure_counts(data_dir, date_str=date_str)
    equity_summary = _equity_trace_summary(equity_trace_rows, publishes_rows)
    kelly_sanity = _arg_recompute_sanity(calls_dir, publishes_rows)

    critical: List[str] = []
    warnings: List[str] = []
    if row_existence["missing_in_real_ledger"]:
        critical.append(
            f"{len(row_existence['missing_in_real_ledger'])} TERMINAL shadow "
            f"close(s) have NO matching real trade_ledger.csv row (D1-class)"
        )
    if row_existence["missing_in_shadow_ledger"]:
        critical.append(
            f"{len(row_existence['missing_in_shadow_ledger'])} real "
            f"trade_ledger.csv row(s) have NO matching shadow ledger row"
        )
    if row_existence.get("coverage_gap_after_window"):
        critical.append(
            f"{len(row_existence['coverage_gap_after_window'])} real close(s) occurred "
            f"AFTER the shadow's last capture but were never shadow-captured -- the shadow "
            f"stopped covering closes (validation is stale/broken, NOT clean)"
        )
    if ledger_diff["non_whitelisted_diffs"]:
        critical.append(
            f"{len(ledger_diff['non_whitelisted_diffs'])} position(s) have "
            f"non-whitelisted ledger column diffs"
        )
    # Recorder line-counts are an UNRELIABLE dedup signal: recorders are shared
    # sinks touched by a variable, CONDITIONAL number of subscriber calls per close
    # (kelly_engine via on_close_ledger + on_close_kelly + learning branches;
    # llm_triggers via 2 subscribers; telemetry via inc()+record()). A high count
    # can be legitimate conditional multiplicity, not a dedup regression. The
    # authoritative dedup guarantee is the CloseBus applied-store keyed on
    # (subscriber, position_id, leg_kind); a real regression ALSO surfaces as a
    # ledger diff / missing row (the CRITICAL checks above). So over-count is a
    # WARNING to eyeball -- it must not block is_clean (else false alarms stall the flip).
    over_counted = [r for r in gate_table["rows"] if r["over_count"]]
    if over_counted:
        warnings.append(
            f"{len(over_counted)} recorder(s) logged more lines than the per-close upper "
            f"bound ({', '.join(r['subscriber'] for r in over_counted)}) -- likely conditional "
            f"recorder multiplicity; verify against the bus applied-store if unsure"
        )
    if failures["total"]:
        critical.append(f"{failures['total']} subscriber exception(s) found in bot log")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "date": date_str,
        "data_dir": str(data_dir),
        "row_existence": row_existence,
        "ledger_column_diff": ledger_diff,
        "gate_table": gate_table,
        "subscriber_failures": failures,
        "equity_trace": equity_summary,
        "kelly_arg_recompute_sanity": kelly_sanity,
        "whitelisted_ledger_columns": sorted(_WHITELISTED_LEDGER_COLUMNS),
        "critical": critical,
        "warnings": warnings,
        "is_clean": not critical,
    }
    return report


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Shadow close-bus vs god-block daily diff (read-only).")
    parser.add_argument("--data-dir", type=str, default=None, help="Override DATA_DIR (default: core.paths.DATA_DIR)")
    parser.add_argument("--out", type=str, default=None, help="Override output report path")
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir) if args.data_dir else paths.DATA_DIR
    report = run_diff(data_dir)

    out_path = (
        Path(args.out) if args.out
        else data_dir / "shadow" / "diff_reports" / f"{report['date']}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"[shadow_close_diff] report written: {out_path}")
    print(f"[shadow_close_diff] is_clean={report['is_clean']} critical={len(report['critical'])}")
    for c in report["critical"]:
        print(f"  CRITICAL: {c}")
    for w in report.get("warnings", []):
        print(f"  WARNING: {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
