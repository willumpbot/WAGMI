"""SIDE / SELECTIVITY gate decision log -- LOGGING ONLY (laptop M22, 2026-10-16).

WHY: the laptop's M22 ("would a LIVING side gate unblock what the FROZEN gate
blocks?") is unanswerable on history: the side gate's block/size decision was
never recorded per entry (only free-text [ENTRY-GATE] log lines since
2026-07-27). This writes ONE immutable JSONL row per LLM-first entry evaluation
with the at-decision facts, so the frozen-vs-living comparison can be made
prospectively (M22 re-opens at n_block_flips >= ~15).

File: bot/data/logs/side_gate_decisions.jsonl (append-only).

Row (schema v1):
  ts, ts_utc, trace_id, pipeline_id, symbol, side, llm_action, llm_confidence,
  stage           last stage reached: llm_decision | gate | post_gate | execution
  selectivity     entry_selectivity.gate_snapshot(): mode + per-leg state,
                  inputs, would_fire and verdict (off/exempt/pass/block/shadow_block)
  gate            the live gate's own return: mode, block, reasons
  probe           BLOCKED_GO_PROBE: enabled, rate, roll, breaker, fire, size_mult
  side_mult       live_edge.side_mult_snapshot() + raw/cap/applied mult, qty pre/post
  outcome         blocked | probe_opened | opened | llm_skip | not_opened | error
  position_id     when a position opened
  exploration     True when the entry went in as an exploration/probe entry

CONTRACT: no function here raises, and nothing here is read by any trading
decision, size, gate or exit. Kill switch: SIDE_GATE_LOG=false.
Tests: SIDE_GATE_LOG_PATH overrides the path; under pytest the DEFAULT live
path is never written (mirrors core/structured_logging's PYTEST guard; the
live-write guard in tests/conftest.py would refuse it anyway).
"""
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

logger = logging.getLogger("bot.core.side_gate_log")

_BOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PATH = os.path.join(_BOT, "data", "logs", "side_gate_decisions.jsonl")
SCHEMA = 1

_tls = threading.local()       # one pending record per symbol-scan thread
_write_lock = threading.Lock()


def enabled() -> bool:
    return os.getenv("SIDE_GATE_LOG", "true").strip().lower() not in ("0", "false", "no", "off")


def _path():
    p = os.getenv("SIDE_GATE_LOG_PATH", "").strip()
    if p:
        return p, False
    return DEFAULT_PATH, True


def _append(row: dict) -> bool:
    path, is_default = _path()
    if is_default and os.getenv("PYTEST_CURRENT_TEST"):
        return False
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    line = json.dumps(row, default=str, separators=(",", ":"))
    with _write_lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    return True


# ── scope: one record per _process_symbol_llm_first call (thread-local) ──────

def start_scope():
    """Called by the dispatcher right before _process_symbol_llm_first."""
    try:
        _tls.rec = None
    except Exception:
        pass


def end_scope(error=None):
    """Called in the dispatcher's finally: writes the pending record if no
    terminal point wrote it (LLM skip, downstream cap/OpsGuard/slippage/order
    reject, or an exception). Never raises."""
    try:
        rec = getattr(_tls, "rec", None)
        _tls.rec = None
        if rec is None or rec.get("_written"):
            return
        if error is not None:
            rec["outcome"] = "error"
            rec["error"] = repr(error)[:200]
        elif rec.get("outcome") is None:
            if rec.get("action_at_gate", rec.get("llm_action")) != "go":
                rec["outcome"] = "llm_skip"
            else:
                rec["outcome"] = "not_opened"
                rec["abort_stage"] = rec.get("stage")
        finish(rec, rec["outcome"])
    except Exception as e:
        logger.debug(f"side_gate_log end_scope failed: {e!r}")


def new_record(trace_id, symbol, side, entry_decision):
    """Start the record for one evaluation (right after the LLM decision)."""
    try:
        if not enabled():
            return None
        now = time.time()
        rec = {
            "schema": SCHEMA,
            "ts": round(now, 3),
            "ts_utc": datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "trace_id": trace_id or "",
            "pipeline_id": getattr(entry_decision, "pipeline_id", "") or "",
            "symbol": symbol,
            "side": side,
            "llm_action": getattr(entry_decision, "action", None),
            "llm_confidence": getattr(entry_decision, "confidence", None),
            "stage": "llm_decision",
            "selectivity": None, "gate": None, "probe": None, "side_mult": None,
            "outcome": None, "position_id": None, "exploration": False,
        }
        _tls.rec = rec
        return rec
    except Exception as e:
        logger.debug(f"side_gate_log new_record failed: {e!r}")
        return None


def set_stage(rec, stage):
    try:
        if rec is not None:
            rec["stage"] = stage
    except Exception:
        pass


def note_gate(rec, *, action, mode, block, reasons, num_agree, ev_per_dollar,
              loss_streak, is_exploration, side, regime, sym_d24h):
    """Record the selectivity gate's live return + the per-leg snapshot."""
    try:
        if rec is None:
            return
        rec["stage"] = "gate"
        rec["action_at_gate"] = action
        rec["exploration"] = bool(is_exploration)
        rec["gate"] = {"mode": mode, "block": bool(block), "reasons": list(reasons or [])}
        try:
            from core import entry_selectivity as _es
            rec["selectivity"] = _es.gate_snapshot(
                num_agree=num_agree, ev_per_dollar=ev_per_dollar,
                loss_streak=loss_streak, is_exploration=is_exploration,
                side=side, regime=regime, sym_d24h=sym_d24h)
        except Exception as e:
            rec["selectivity"] = {"error": repr(e)[:200]}
    except Exception as e:
        logger.debug(f"side_gate_log note_gate failed: {e!r}")


def note_probe(rec, *, enabled_, rate, roll, breaker, fire, size_mult=None):
    try:
        if rec is None:
            return
        rec["probe"] = {"enabled": bool(enabled_), "rate": rate, "roll": roll,
                        "breaker": bool(breaker), "fire": bool(fire), "size_mult": size_mult}
        if fire:
            rec["exploration"] = True
    except Exception:
        pass


def note_side_mult(rec, *, symbol, side, raw, cap, applied, qty_pre, qty_post):
    try:
        if rec is None:
            return
        try:
            from feedback.live_edge import side_mult_snapshot as _sms
            snap = _sms(symbol, side)
        except Exception as e:
            snap = {"error": repr(e)[:200]}
        rec["side_mult"] = {"raw": raw, "cap": cap, "applied": applied,
                            "qty_pre": qty_pre, "qty_post": qty_post, "evidence": snap}
    except Exception:
        pass


def finish(rec, outcome, position_id=None):
    """Write the record once with its final outcome. Never raises."""
    try:
        if rec is None or rec.get("_written"):
            return
        rec["outcome"] = outcome
        if position_id:
            rec["position_id"] = position_id
        rec["_written"] = True
        row = {k: v for k, v in rec.items() if k != "_written"}
        _append(row)
    except Exception as e:
        logger.debug(f"side_gate_log write failed: {e!r}")
