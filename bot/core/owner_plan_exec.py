"""Owner-plan execution: the bot paper-trades the OWNER's saved plans and manages the exit itself.

The owner saves trade plans from the terminal (tools/hivemind/plans.py -> data/hivemind/owner_plans.jsonl).
With OWNER_PLAN_EXEC=true the bot also opens each plan as a PAPER position in its own PositionManager,
tagged strategy="owner_plan", and lets its normal exit machinery (TP1 partial, trailing, exit agent,
time stops, MFE exits) manage it. plans.py grades the plan as written; this module records what the
bot's management made of the same plan, so the two can be compared side by side.
How much of that machinery may act is set per plan by `exit_mode` (see owner_exit_mode() below):
default profits_only = partial profits only, the owner's stop is never moved and never closed early.

HARD RULE: owner trades never feed the bot's learning or stats. Every close/partial of a tagged position
is diverted (multi_strategy_main close loop -> record_owner_close -> `continue`) into
data/hivemind/owner_fills.jsonl instead of equity / circuit breaker / trades.csv / trade ledger / DB /
weights / Kelly / IC / deep memory / learning. Guards elsewhere key off the TAG (strategy=="owner_plan"),
not the flag, so a tagged position recovered after the flag was switched off is still excluded.

Files (all under data/hivemind/):
  owner_plans.jsonl          read-only here (written by plans.py)
  owner_orders_state.json    this module's state: per-plan status (idempotent across restarts)
  owner_fills.jsonl          append-only: one row per open, partial leg and final close
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bot.core.owner_plan_exec")

OWNER_STRATEGY = "owner_plan"

try:
    from core.paths import DATA_DIR as _DATA_DIR
except Exception:  # pragma: no cover - import-path fallback
    _DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Module-level so tests can point it at a temp dir.
HM_DIR: Path = Path(os.getenv("OWNER_PLAN_DIR") or (_DATA_DIR / "hivemind"))

_LOCK = threading.RLock()

# Statuses after which a plan is never looked at again by drain().
TERMINAL = {"open", "closed", "filled", "blocked", "rejected", "stale", "expired", "cancelled"}


def enabled() -> bool:
    return os.getenv("OWNER_PLAN_EXEC", "false").strip().lower() in ("1", "true", "yes", "on")


def is_owner_position(pos: Any) -> bool:
    return pos is not None and getattr(pos, "strategy", "") == OWNER_STRATEGY


def is_owner_event(event: Any) -> bool:
    return event is not None and getattr(event, "strategy", "") == OWNER_STRATEGY


# ── per-plan EXIT MODE ──────────────────────────────────────────────────────
# What the bot's exit machinery may do to an owner position (stored as `exit_mode` on the plan row,
# copied into pos.entry_reasons["exit_mode"] at open):
#   profits_only (default) — bot may bank PARTIAL profits (TP1 leg / AI partials, total <= 50% of the
#                            original qty) but never moves the owner's stop (no breakeven, profit-lock,
#                            ratchet, trailing, AI tighten, hold-limit tighten) and never fully closes
#                            early (no AI close, MFE/funding/hold-limit close). Only the owner's stop,
#                            the owner's target, or the partial legs end it.
#   hands_off              — as profits_only, and no bot partials either: pure stop/target. Exception: with
#                            OWNER_RUNNER_STYLE on, the owner's OWN exit_style=runner rule (half at +1R, 1-ATR
#                            trail, plan time limit) applies here too - it is his declared rule, not bot judgment.
#                            Same for OWNER_LADDER_STYLE on + exit_style=ladder (quarters at +0.5/+0.75/+1R, trail).
#                            Every owner_fills.jsonl row says which rule closed it ("managed_by").
#   bot_manages            — the bot's normal exit machinery, no restrictions (pre-2026-10-12 behaviour).
# Bot-opened positions always resolve to bot_manages, so every guard is inert for them.
# Kill-switches (no code change needed):
#   OWNER_PLAN_EXIT_MODE_DEFAULT  mode for plans/positions with no (or an invalid) exit_mode. Default profits_only.
#   OWNER_PLAN_EXIT_MODE_FORCE    if set to a valid mode, overrides EVERY owner position's mode
#                                 (e.g. =bot_manages reverts all owner positions to the old behaviour).
EXIT_PROFITS_ONLY = "profits_only"
EXIT_HANDS_OFF = "hands_off"
EXIT_BOT_MANAGES = "bot_manages"
EXIT_MODES = (EXIT_PROFITS_ONLY, EXIT_HANDS_OFF, EXIT_BOT_MANAGES)
RESTRICTED_EXIT_MODES = (EXIT_PROFITS_ONLY, EXIT_HANDS_OFF)
OWNER_PARTIAL_CAP_FRAC = 0.5  # profits_only: total partial-closed qty <= 50% of ORIGINAL qty


def normalize_exit_mode(value: Any) -> Optional[str]:
    v = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return v if v in EXIT_MODES else None


def default_exit_mode() -> str:
    return normalize_exit_mode(os.getenv("OWNER_PLAN_EXIT_MODE_DEFAULT", EXIT_PROFITS_ONLY)) or EXIT_PROFITS_ONLY


def owner_exit_mode(pos: Any) -> str:
    """profits_only / hands_off / bot_manages for this position. bot_manages for every non-owner position."""
    if not is_owner_position(pos):
        return EXIT_BOT_MANAGES
    forced = normalize_exit_mode(os.getenv("OWNER_PLAN_EXIT_MODE_FORCE", ""))
    if forced:
        return forced
    er = getattr(pos, "entry_reasons", None) or {}
    mode = normalize_exit_mode(er.get("exit_mode")) if isinstance(er, dict) else None
    return mode or default_exit_mode()


def owner_exit_restricted(pos: Any) -> bool:
    """True when the bot may NOT move this position's stop or fully close it early."""
    return owner_exit_mode(pos) in RESTRICTED_EXIT_MODES


def owner_partial_allowance(pos: Any) -> float:
    """Qty the bot may still partially close on this position under its exit mode.

    bot_manages / non-owner: the whole current qty (no cap). hands_off: 0. profits_only:
    max(0, 50% x original_qty - qty already partial-closed).
    """
    qty = float(getattr(pos, "qty", 0) or 0)
    mode = owner_exit_mode(pos)
    if mode == EXIT_BOT_MANAGES:
        return qty
    if mode == EXIT_HANDS_OFF:
        return 0.0
    if runner_live(pos) or ladder_live(pos):
        # exit_style=runner with OWNER_RUNNER_STYLE on: the owner's +1R half IS the 50% partial
        # (taken deterministically by position_manager._owner_runner_step), so the bot's own
        # partials (TP1 leg / AI partials) get nothing - no double count against the 50% cap.
        # exit_style=ladder with OWNER_LADDER_STYLE on: same - the owner's three quarters are the only partials.
        return 0.0
    orig = float(getattr(pos, "original_qty", 0) or 0) or qty
    already = max(0.0, orig - qty)
    # round off float dust (0.5 - 0.4 = 0.0999..) so a later round-DOWN of the qty doesn't lose a tick
    return round(max(0.0, min(qty, OWNER_PARTIAL_CAP_FRAC * orig - already)), 10)


# ── per-plan EXIT STYLE (tools/hivemind/exit_style.py is the one engine every grader uses) ───────
# Stored as `exit_style` on the plan row, copied into pos.entry_reasons["exit_style"] at open, with the
# 14-day daily ATR known at the fill in entry_reasons["atr_at_fill"].
#   runner (default) — HALF of the original qty at +1R (1R = |entry - owner's stop|); the other half then
#                      trails 1 x atr_at_fill behind the best price since +1R (only ever moves the
#                      profitable way); the plan's own time limit closes what is left. The plan target
#                      closes NOTHING in this style (exit_style.play ignores it). Before +1R: the owner's stop.
#   ladder           — a QUARTER of the original qty at +0.5R, +0.75R and +1R (1R from the ACTUAL fill, as runner);
#                      after the third quarter the last 25% trails 1 x atr_at_fill behind the best price since,
#                      starting from the owner's stop, only ever the profitable way; the plan's time limit closes
#                      what is left; the target closes nothing. Before the first quarter: the owner's stop.
#   full             — stop / target / time limit (the pre-2026-10-15 behaviour).
# Applied only to owner positions in a restricted exit mode (profits_only / hands_off): those are the
# modes where the bot's own TP1 / trailing machinery is switched off. bot_manages keeps the bot's machinery.
# OWNER_RUNNER_STYLE=false (default): behaviour is byte-identical to before; position_manager only logs
# "[OWNER-RUNNER-SHADOW] would ..." lines (and owner_exit_decisions.jsonl rows) when the style would act.
# OWNER_LADDER_STYLE=false (default): a ladder position runs the 'full' machinery (stop / target / time, exactly as
# a full-style position) and position_manager only logs "[OWNER-LADDER-SHADOW] would ..." rows. Independent of
# OWNER_RUNNER_STYLE: each flag only ever acts on its own style.
EXIT_STYLES = ("runner", "full", "ladder")
DEFAULT_EXIT_STYLE = "runner"
TRAIL_EXIT_STYLES = ("runner", "ladder")   # need a trail width + a target beyond +1R (else they run 'full')
# ladder steps: (k, R multiple, fraction of the ORIGINAL qty); the last 25% trails after step 3
LADDER_STEPS = ((1, 0.5, 0.25), (2, 0.75, 0.25), (3, 1.0, 0.25))
LADDER_ACTIONS = {k: f"OWNER_LADDER_Q{k}" for k, _, _ in LADDER_STEPS}
LADDER_TRAIL_ACTION = "OWNER_LADDER_TRAIL"


def normalize_exit_style(value: Any) -> str:
    """Mirrors tools/hivemind/exit_style.norm: 'full' / 'ladder' as given, anything else is 'runner'."""
    v = str(value or "").strip().lower()
    return v if v in EXIT_STYLES else DEFAULT_EXIT_STYLE


def runner_style_enabled() -> bool:
    return os.getenv("OWNER_RUNNER_STYLE", "false").strip().lower() in ("1", "true", "yes", "on")


def ladder_style_enabled() -> bool:
    return os.getenv("OWNER_LADDER_STYLE", "false").strip().lower() in ("1", "true", "yes", "on")


def owner_exit_style(pos: Any) -> Optional[str]:
    """runner / ladder / full for an owner position, None for every bot position."""
    if not is_owner_position(pos):
        return None
    er = getattr(pos, "entry_reasons", None) or {}
    return normalize_exit_style(er.get("exit_style") if isinstance(er, dict) else None)


def runner_applies(pos: Any) -> bool:
    """True when the owner's runner rule governs this position's exit (flag aside)."""
    return owner_exit_style(pos) == "runner" and owner_exit_mode(pos) in RESTRICTED_EXIT_MODES


def runner_live(pos: Any) -> bool:
    """True when the runner rule is ACTUALLY applied (OWNER_RUNNER_STYLE on).

    The first time a runner position is seen with the flag on it is checked once (ensure_runner_ready):
    no usable atr_at_fill -> point-in-time backfill, else degrade to exit_style=full; target at/inside +1R
    -> full (OWNER_RUNNER_TARGET_GUARD). A runner without a trail never ignores its target. While a failed
    backfill is waiting for its retry the position is NOT live (the full stop/target machinery manages it).
    """
    if not (runner_style_enabled() and runner_applies(pos)):
        return False
    ensure_runner_ready(pos)
    er = getattr(pos, "entry_reasons", None)
    return runner_applies(pos) and isinstance(er, dict) and bool(er.get("runner_checked"))


def ladder_applies(pos: Any) -> bool:
    """True when the owner's ladder (quarters) rule governs this position's exit (flag aside)."""
    return owner_exit_style(pos) == "ladder" and owner_exit_mode(pos) in RESTRICTED_EXIT_MODES


def ladder_live(pos: Any) -> bool:
    """True when the ladder rule is ACTUALLY applied (OWNER_LADDER_STYLE on). Same once-per-position readiness
    check as the runner (ensure_runner_ready): no usable atr_at_fill -> point-in-time backfill (retried), else
    exit_style=full; target at/inside +1R of the fill -> full (OWNER_RUNNER_TARGET_GUARD). Not live while a failed
    backfill waits for its retry (the full stop/target machinery manages it meanwhile)."""
    if not (ladder_style_enabled() and ladder_applies(pos)):
        return False
    ensure_runner_ready(pos)
    er = getattr(pos, "entry_reasons", None)
    return ladder_applies(pos) and isinstance(er, dict) and bool(er.get("runner_checked"))


def _env_num(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


def runner_target_guard_enabled() -> bool:
    """OWNER_RUNNER_TARGET_GUARD (default true): a plan whose target sits at or inside +1R (measured from the
    actual fill) runs exit_style=full - in runner style a touch of such a target would bank nothing."""
    return os.getenv("OWNER_RUNNER_TARGET_GUARD", "true").strip().lower() in ("1", "true", "yes", "on")


def _valid_atr(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def runner_style_check(side: str, fill: float, stop: float, target: Any, atr: Any,
                       style: str = "runner") -> Optional[str]:
    """Why a runner (or ladder) plan must run as 'full' instead (None = the style is fine). Geometry from the ACTUAL
    fill. Same two rules for both: a trail width must exist, and the target must sit beyond +1R."""
    if _valid_atr(atr) is None:
        return f"no atr_at_fill (14d daily ATR at the fill unavailable): a {style} needs a trail width"
    try:
        risk = abs(float(fill) - float(stop))
        reward = abs(float(target) - float(fill)) if target not in (None, "") else None
    except (TypeError, ValueError):
        risk, reward = 0.0, None
    if runner_target_guard_enabled() and reward is not None and risk > 0 and reward <= risk:
        return (f"target {float(target):g} is at or inside +1R from the fill {float(fill):g} (reward {reward:g} <= "
                f"risk {risk:g}): " + ("runner would bank nothing at the target" if style == "runner" else
                                        f"{style} ignores the target and only completes at +1R")
                + " (OWNER_RUNNER_TARGET_GUARD)")
    return None


def _log_style_decision(pos: Any, action: str, details: str) -> None:
    try:
        er = getattr(pos, "entry_reasons", None) or {}
        row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "symbol": getattr(pos, "symbol", ""),
               "exit_action": action, "applied": True, "source": "owner_runner_check",
               "exit_mode": owner_exit_mode(pos), "exit_style": owner_exit_style(pos), "details": details,
               "owner_plan_id": er.get("owner_plan_id") if isinstance(er, dict) else None,
               "position_side": getattr(pos, "side", ""), "position_id": getattr(pos, "position_id", "")}
        p = Path(HM_DIR) / "owner_exit_decisions.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
    except Exception:
        logger.debug("[OWNER-PLAN] runner check log failed", exc_info=True)


def ensure_runner_ready(pos: Any) -> None:
    """Once per position, with OWNER_RUNNER_STYLE (runner) / OWNER_LADDER_STYLE (ladder) on: make sure the style
    can actually run (both need a trail width and a target beyond +1R; the stamp key is 'runner_checked' for both).

    Positions opened before the runner build carry no atr_at_fill / exit_style. Backfill atr_at_fill point-in-time
    from the fill timestamp (exit_style.atr_at on completed daily bars, same as the graders); if that fails, or the
    target sits at/inside +1R of the fill, store exit_style=full (stop / target / time limit) with the reason.
    Never raises.
    """
    try:
        er = getattr(pos, "entry_reasons", None)
        style = owner_exit_style(pos)
        if not isinstance(er, dict) or er.get("runner_checked") or style not in TRAIL_EXIT_STYLES:
            return
        tag = f"[OWNER-{style.upper()}]"
        sym = getattr(pos, "symbol", "")
        atr = _valid_atr(er.get("atr_at_fill"))
        if atr is None:
            now = time.time()
            if now < float(er.get("atr_backfill_next") or 0):
                return   # waiting for the next retry (the position runs on the full machinery meanwhile)
            ot = getattr(pos, "open_time", None)
            ts = ot.timestamp() if hasattr(ot, "timestamp") else now
            v, src = atr_at_fill(None, sym, ts)
            atr = _valid_atr(v)
            if atr is not None:
                er["atr_at_fill"] = atr
                er["atr_at_fill_source"] = f"backfill_{src}"
                er["atr_backfilled_at"] = now
                logger.info(f"{tag} {sym} atr_at_fill backfilled point-in-time = {atr:g} ({src})")
            else:
                # one transient HL blip must not permanently degrade a runner: retry a few times, spaced
                n = int(er.get("atr_backfill_attempts") or 0) + 1
                er["atr_backfill_attempts"] = n
                tries = int(_env_num("OWNER_RUNNER_ATR_RETRIES", 3))
                if n < tries:
                    er["atr_backfill_next"] = now + _env_num("OWNER_RUNNER_ATR_RETRY_S", 60.0)
                    logger.warning(f"{tag} {sym} plan {er.get('owner_plan_id')}: atr_at_fill backfill "
                                   f"failed ({src}), attempt {n}/{tries} - retrying; full machinery until then")
                    return
        fill = float(getattr(pos, "entry", 0) or 0)
        stop = float(getattr(pos, "original_sl", 0) or getattr(pos, "sl", 0) or 0)
        target = er.get("plan_target") if er.get("plan_target") not in (None, "") else getattr(pos, "tp2", None)
        why = runner_style_check(getattr(pos, "side", ""), fill, stop, target, atr, style=style)
        er["runner_checked"] = time.time()
        if why:
            er["exit_style"] = "full"
            er["exit_style_reason"] = why
            logger.warning(f"{tag} {sym} plan {er.get('owner_plan_id')}: runs exit_style=full - {why}")
            _log_style_decision(pos, "style_full", why)
        else:
            er["exit_style"] = style
    except Exception:
        logger.warning("[OWNER-RUNNER] ensure_runner_ready failed", exc_info=True)


def managed_by(action: str) -> str:
    """Which rule produced an owner fill row (owner_fills.jsonl 'managed_by')."""
    a = str(action or "").upper()
    return {"OWNER_RUNNER_HALF": "runner_half", "OWNER_RUNNER_TRAIL": "runner_trail", "SL": "stop",
            "TP2": "target", "TP1": "tp1_leg", "OWNER_PLAN_MAX_HOLD": "time",
            "OWNER_LADDER_Q1": "ladder_q1", "OWNER_LADDER_Q2": "ladder_q2", "OWNER_LADDER_Q3": "ladder_q3",
            "OWNER_LADDER_TRAIL": "ladder_trail"}.get(a, f"bot:{a.lower()}" if a else "")


def recorded_ladder_steps(plan_id: str, position_id: str = "") -> Dict[int, Dict[str, Any]]:
    """{step k: the OWNER_LADDER_Q<k> partial row already in owner_fills.jsonl} for this plan/position (same plan /
    position matching as recorded_runner_half). Empty when none / unreadable."""
    out: Dict[int, Dict[str, Any]] = {}
    if not plan_id:
        return out
    try:
        with open(fills_path(), encoding="utf-8") as fh:
            for line in fh:
                if "OWNER_LADDER_Q" not in line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                reason = str(r.get("reason") or "")
                k = {v: k for k, v in LADDER_ACTIONS.items()}.get(reason)
                if (k and r.get("kind") == "partial" and str(r.get("plan_id") or "") == str(plan_id)
                        and (not position_id or not r.get("position_id") or r.get("position_id") == position_id)):
                    out.setdefault(k, r)   # the FIRST row per step is the real one (a step can only fire once)
    except OSError:
        return {}
    return out


def recorded_runner_half(plan_id: str, position_id: str = "") -> Optional[Dict[str, Any]]:
    """The OWNER_RUNNER_HALF partial row already in owner_fills.jsonl for this plan/position, or None."""
    if not plan_id:
        return None
    hit = None
    try:
        with open(fills_path(), encoding="utf-8") as fh:
            for line in fh:
                if "OWNER_RUNNER_HALF" not in line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if (r.get("kind") == "partial" and r.get("reason") == "OWNER_RUNNER_HALF"
                        and str(r.get("plan_id") or "") == str(plan_id)
                        and (not position_id or not r.get("position_id") or r.get("position_id") == position_id)):
                    hit = r
    except OSError:
        return None
    return hit


def log_owner_runner_shadow(pos: Any, action: str, details: str, key: Optional[str] = None) -> None:
    """[OWNER-RUNNER-SHADOW] line + owner_exit_decisions.jsonl row, at most once per (position, key). Never raises."""
    _log_style_shadow(pos, action, details, key, "runner")


def log_owner_ladder_shadow(pos: Any, action: str, details: str, key: Optional[str] = None) -> None:
    """[OWNER-LADDER-SHADOW] line + owner_exit_decisions.jsonl row (source owner_ladder_shadow), at most once per
    (position, key). Never raises."""
    _log_style_shadow(pos, action, details, key, "ladder")


def _log_style_shadow(pos: Any, action: str, details: str, key: Optional[str], style: str) -> None:
    try:
        attr = f"_owner_{style}_shadow_logged"
        seen = getattr(pos, attr, None)
        if seen is None:
            seen = set()
            try:
                setattr(pos, attr, seen)
            except Exception:
                pass
        k = key or action
        if k in seen:
            return
        seen.add(k)
        er = getattr(pos, "entry_reasons", None) or {}
        row = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "symbol": getattr(pos, "symbol", ""),
            "exit_action": action, "applied": False, "source": f"owner_{style}_shadow",
            "exit_mode": owner_exit_mode(pos), "exit_style": owner_exit_style(pos),
            "details": f"[OWNER-{style.upper()}-SHADOW] {details} (OWNER_{style.upper()}_STYLE off, not applied)",
            "owner_plan_id": er.get("owner_plan_id") if isinstance(er, dict) else None,
            "position_side": getattr(pos, "side", ""), "position_sl": getattr(pos, "sl", None),
            "position_id": getattr(pos, "position_id", ""),
        }
        p = Path(HM_DIR) / "owner_exit_decisions.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
        logger.info(f"[OWNER-{style.upper()}-SHADOW] {row['symbol']} {details}")
    except Exception:
        logger.debug("[OWNER-PLAN] %s shadow log failed", style, exc_info=True)


def log_owner_exit_block(pos: Any, source: str, action: str, reason: str, once: bool = False) -> None:
    """Record a blocked bot exit action on an owner position (data/hivemind/owner_exit_decisions.jsonl).

    once=True: write at most one row per (position, source, action) — for paths evaluated every tick.
    Never raises.
    """
    try:
        if once:
            seen = getattr(pos, "_owner_exit_blocks_logged", None)
            if seen is None:
                seen = set()
                try:
                    setattr(pos, "_owner_exit_blocks_logged", seen)
                except Exception:
                    pass
            key = f"{source}:{action}"
            if key in seen:
                return
            seen.add(key)
        mode = owner_exit_mode(pos)
        er = getattr(pos, "entry_reasons", None) or {}
        row = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "symbol": getattr(pos, "symbol", ""),
            "exit_action": action, "applied": False, "source": source, "exit_mode": mode,
            "details": f"blocked by owner exit_mode={mode}: {reason}",
            "owner_plan_id": er.get("owner_plan_id") if isinstance(er, dict) else None,
            "position_side": getattr(pos, "side", ""), "position_sl": getattr(pos, "sl", None),
            "position_id": getattr(pos, "position_id", ""),
        }
        p = Path(HM_DIR) / "owner_exit_decisions.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
        logger.info(f"[OWNER-PLAN] {row['symbol']} {source} {action} blocked (exit_mode={mode}): {reason}")
    except Exception:
        logger.debug("[OWNER-PLAN] exit-block log failed", exc_info=True)


def plans_path() -> Path:
    return Path(HM_DIR) / "owner_plans.jsonl"


def state_path() -> Path:
    return Path(HM_DIR) / "owner_orders_state.json"


def fills_path() -> Path:
    return Path(HM_DIR) / "owner_fills.jsonl"


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# ── persistence ─────────────────────────────────────────────────────────────

def read_plan_rows() -> List[Dict[str, Any]]:
    try:
        text = plans_path().read_text(encoding="utf-8")
    except OSError:
        return []
    rows = []
    for line in text.splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def load_state() -> Dict[str, Any]:
    try:
        st = json.loads(state_path().read_text(encoding="utf-8"))
        if isinstance(st, dict) and isinstance(st.get("plans"), dict):
            return st
    except (OSError, ValueError):
        pass
    return {"plans": {}}


def save_state(st: Dict[str, Any]) -> None:
    p = state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    st["updated"] = time.time()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, p)


def _append_fill(row: Dict[str, Any]) -> None:
    p = fills_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, default=str) + "\n")


# ── geometry ────────────────────────────────────────────────────────────────

def plan_levels(side: str, entry: float, stop: float, target: float) -> Optional[Dict[str, float]]:
    """tp2 = target, tp1 = entry +/- 1R capped at the midpoint to target. None if geometry is invalid."""
    sg = 1 if side == "LONG" else -1
    if entry <= 0 or sg * (entry - stop) <= 0 or sg * (target - entry) <= 0:
        return None
    r = abs(entry - stop)
    mid = (entry + target) / 2.0
    tp1 = min(entry + r, mid) if sg > 0 else max(entry - r, mid)
    return {"sl": stop, "tp1": tp1, "tp2": target, "r": r}


def _side_of(price: float, entry: float) -> int:
    return 0 if price == entry else (1 if price > entry else -1)


# ── the drain (called once per tick from _tick_once) ────────────────────────

def drain(bot, trace_id: str = "", now: Optional[float] = None) -> Dict[str, Any]:
    """Process new owner plans: queue limits, open fills, mark rejects. Returns the state dict.

    `bot` is the MultiStrategyBot (needs pos_mgr, order_executor, _last_prices; optional ops_guard,
    telegram_bot, degradation, _tick_regime_cache, fetcher, _executing_lock/_executing_symbols).
    """
    now = time.time() if now is None else now
    with _LOCK:
        st = load_state()
        plans = st["plans"]
        rows = read_plan_rows()
        cancelled = {str(r.get("id")) for r in rows if r.get("kind") == "cancel"}
        changed = False

        try:
            from trading_config import DEFAULT_SYMBOLS
            managed = set(DEFAULT_SYMBOLS.keys())
        except Exception:
            managed = {"BTC", "ETH", "SOL", "HYPE", "XRP", "NEAR"}

        # Entry halts are transient: plans stay pending and are re-evaluated next tick.
        halted = ""
        try:
            if getattr(getattr(bot, "ops_guard", None), "is_killed", False):
                halted = "kill switch"
            elif getattr(getattr(bot, "telegram_bot", None), "is_paused", False):
                halted = "paused"
            elif getattr(bot, "degradation", None) is not None and bot.degradation.should_halt_entries():
                halted = "exchange degraded"
        except Exception:
            pass

        prices = dict(getattr(bot, "_last_prices", {}) or {})
        market_max_age = _f("OWNER_PLAN_MARKET_MAX_AGE_S", 1800.0)
        market_drift = _f("OWNER_PLAN_MARKET_MAX_DRIFT", 0.005)

        for pl in (r for r in rows if r.get("kind") == "plan"):
            pid = str(pl.get("id") or "")
            if not pid:
                continue
            rec = plans.get(pid)
            if rec and rec.get("status") in TERMINAL:
                continue
            if pl.get("ts") and float(pl.get("ts") or 0) < _f("OWNER_PLAN_MIN_TS", 0.0):
                # Plans saved before the feature was switched on are never executed retroactively.
                continue

            def mark(status, reason, **extra):
                nonlocal changed
                r = dict(plans.get(pid) or {}, status=status, reason=reason, coin=pl.get("coin"),
                         side=pl.get("side"), updated=now, **extra)
                r.setdefault("first_seen", now)
                plans[pid] = r
                changed = True
                logger.info(f"[{trace_id}][OWNER-PLAN] {pid} {pl.get('coin')} {pl.get('side')}: {status} — {reason}")

            if pid in cancelled:
                mark("cancelled", "cancelled by owner before fill")
                continue

            coin = str(pl.get("coin") or "").upper()
            side = str(pl.get("side") or "").upper()
            etype = pl.get("entry_type") or "limit"
            try:
                ts = float(pl.get("ts") or 0)
                entry = float(pl["entry"])
                stop = float(pl["stop"])
                target = float(pl["target"])
                price_at_plan = float(pl.get("price_at_plan") or entry)
                window_h = float(pl.get("entry_window_h") or 24)
            except (KeyError, TypeError, ValueError):
                mark("rejected", "plan has non-numeric levels")
                continue

            if coin not in managed:
                mark("rejected", f"bot only manages {'/'.join(sorted(managed))}; {coin or '?'} is not one")
                continue
            if side not in ("LONG", "SHORT") or plan_levels(side, entry, stop, target) is None:
                mark("rejected", "invalid side / stop / target geometry")
                continue
            if getattr(getattr(bot, "order_executor", None), "mode", "paper") != "paper":
                mark("rejected", "owner-plan execution is paper-only; executor is not in paper mode")
                continue

            price = prices.get(coin)
            fill_reason = ""
            if etype == "market":
                if now - ts > market_max_age:
                    mark("stale", f"market plan was {(now - ts) / 60:.0f} min old when the bot saw it")
                    continue
                if not price:
                    if not rec:
                        mark("queued", "waiting for a live price")
                    continue
                drift = abs(price - price_at_plan) / price_at_plan if price_at_plan > 0 else 1.0
                if drift > market_drift:
                    mark("stale", f"price moved {drift:.2%} from the plan's {price_at_plan:g} (max {market_drift:.1%})")
                    continue
                fill_reason = "market plan opened at current price"
            else:
                if now > ts + window_h * 3600:
                    mark("expired", f"entry {entry:g} not reached within {window_h:g}h")
                    continue
                if not price:
                    if not rec:
                        mark("queued", f"limit {entry:g} waiting for a live price")
                    continue
                ref_side = (rec or {}).get("last_side")
                if ref_side is None:
                    ref_side = _side_of(price_at_plan, entry)
                cur_side = _side_of(price, entry)
                crossed = cur_side == 0 or (ref_side != 0 and cur_side != ref_side) or ref_side == 0
                if not crossed:
                    if not rec or rec.get("status") != "queued" or rec.get("last_side") != cur_side:
                        mark("queued", f"limit {entry:g} waiting (last {price:g})", last_side=cur_side)
                    continue
                fill_reason = f"limit {entry:g} crossed (last {price:g})"

            # ---- ready to fill ----
            if halted:
                if not rec or rec.get("reason") != f"waiting: {halted}":
                    mark("queued", f"waiting: {halted}")
                continue
            pm = bot.pos_mgr
            existing = pm.positions.get(coin)
            if existing is not None and getattr(existing, "state", "CLOSED") != "CLOSED":
                if is_owner_position(existing):
                    mark("blocked", f"another owner plan is already open in {coin}")
                else:
                    mark("blocked", f"bot already in {coin}")
                continue
            # Loss cooldown in PositionManager is transient: wait it out instead of burning the plan.
            try:
                _lc = pm._last_close_time.get(coin)
                if _lc is not None and not pm._last_close_won.get(coin, True):
                    from datetime import datetime, timezone
                    if (datetime.now(timezone.utc) - _lc).total_seconds() / 60.0 < pm._reentry_cooldown_minutes:
                        if not rec or rec.get("reason") != "waiting: bot loss cooldown":
                            mark("queued", "waiting: bot loss cooldown")
                        continue
            except Exception:
                pass

            res = _open(bot, pl, coin, side, price, stop, target, trace_id)
            if res.get("ok"):
                mark("open", fill_reason, fill_price=res["entry"], qty=res["qty"], tp1=res["tp1"],
                     tp2=res["tp2"], sl=res["sl"], risk_usd=res["risk_usd"], position_id=res["position_id"],
                     exit_mode=res.get("exit_mode"), exit_style=res.get("exit_style"),
                     atr_at_fill=res.get("atr_at_fill"), exit_style_reason=res.get("exit_style_reason"),
                     filled_at=now, fills=[])
                try:
                    _append_fill({"kind": "open", "plan_id": pid, "coin": coin, "side": side, "entry": res["entry"],
                                  "qty": res["qty"], "sl": res["sl"], "tp1": res["tp1"], "tp2": res["tp2"],
                                  "risk_usd": res["risk_usd"], "position_id": res["position_id"], "ts": now,
                                  "pnl_lev": res.get("pnl_lev", 1.0), "exit_mode": res.get("exit_mode"),
                                  "exit_style": res.get("exit_style"), "atr_at_fill": res.get("atr_at_fill"),
                                  "exit_style_reason": res.get("exit_style_reason"),
                                  "reason": fill_reason})
                except Exception:
                    logger.debug("[OWNER-PLAN] open row write failed", exc_info=True)
            else:
                mark("rejected", res.get("reason", "open failed"))

        if changed:
            try:
                save_state(st)
            except Exception:
                logger.warning("[OWNER-PLAN] state save failed", exc_info=True)
        return st


def _atr_1h(bot, coin: str) -> float:
    try:
        from trading_config import DEFAULT_SYMBOLS
        cfg = DEFAULT_SYMBOLS.get(coin)
        data = bot.fetcher.fetch_multi_timeframe(coin, cfg.coingecko_id if cfg else "", ["1h"])
        df = data.get("1h")
        if df is None or len(df) < 15:
            return 0.0
        import pandas as pd
        prev_c = df["close"].shift(1)
        tr = pd.concat([df["high"] - df["low"], (df["high"] - prev_c).abs(), (df["low"] - prev_c).abs()],
                       axis=1).max(axis=1)
        v = float(tr.rolling(14, min_periods=14).mean().iloc[-1])
        return v if v > 0 else 0.0
    except Exception:
        return 0.0


class _HLOneShot:
    """Minimal Hyperliquid candle client for exit_style.atr_at: ONE request, short timeout, no retry/sleep
    (tools/hivemind/hl.py retries with sleeps for ~15s, too long to block the bot's tick)."""

    def __init__(self, timeout: float = 5.0):
        self.timeout = timeout

    def candles(self, coin, interval, start_ms, end_ms=None, ttl=60):
        import urllib.request
        end_ms = int(end_ms or time.time() * 1000)
        body = json.dumps({"type": "candleSnapshot", "req": {"coin": coin, "interval": interval,
                                                             "startTime": int(start_ms), "endTime": end_ms}}).encode()
        req = urllib.request.Request("https://api.hyperliquid.xyz/info", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read())


_EXIT_STYLE_MOD = None


def _exit_style_module():
    """tools/hivemind/exit_style.py (not a package) - loaded by path so the bot uses the SAME ATR formula."""
    global _EXIT_STYLE_MOD
    if _EXIT_STYLE_MOD is None:
        import importlib.util
        p = Path(__file__).resolve().parent.parent / "tools" / "hivemind" / "exit_style.py"
        spec = importlib.util.spec_from_file_location("_owner_exit_style", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _EXIT_STYLE_MOD = mod
    return _EXIT_STYLE_MOD


def _atr_from_daily_df(df, ts: float, n: int = 14) -> Optional[float]:
    """Same formula as exit_style.atr_at on the bot's own daily candles: completed bars only (bar open + 1d <= ts)."""
    import pandas as pd
    if df is None or len(df) == 0 or not {"high", "low", "close"} <= set(df.columns):
        return None
    if "time" in df.columns:
        t = pd.to_datetime(df["time"], utc=True)
        df = df[(t + pd.Timedelta(days=1)) <= pd.Timestamp(ts, unit="s", tz="UTC")]
    else:
        return None  # no bar times -> cannot prove point-in-time; refuse rather than guess
    if len(df) < n + 1:
        return None
    h, l, c = (df[k].astype(float).tolist() for k in ("high", "low", "close"))
    trs = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(h))]
    v = sum(trs[-n:]) / n
    return v if v > 0 else None


def atr_at_fill(bot, coin: str, ts: float):
    """14-day daily ATR as known at the fill (completed daily bars only). Returns (atr or None, source).

    1st: Hyperliquid daily candles through exit_style.atr_at (identical to the graders / trade_case files).
    2nd: the bot's own fetcher daily candles, same formula. Never raises.
    Network is skipped under pytest unless a test monkeypatches this function.
    """
    if not os.getenv("PYTEST_CURRENT_TEST"):
        try:
            v = _exit_style_module().atr_at(_HLOneShot(), coin, ts)
            if v and v > 0:
                return float(v), "hl_1d"
        except Exception:
            logger.debug("[OWNER-PLAN] HL daily ATR failed", exc_info=True)
    try:
        from trading_config import DEFAULT_SYMBOLS
        cfg = DEFAULT_SYMBOLS.get(coin)
        data = bot.fetcher.fetch_multi_timeframe(coin, cfg.coingecko_id if cfg else "", ["1d"])
        v = _atr_from_daily_df(data.get("1d"), ts)
        if v:
            return float(v), "bot_1d"
    except Exception:
        logger.debug("[OWNER-PLAN] bot daily ATR failed", exc_info=True)
    return None, "unavailable"


def _open(bot, pl: Dict[str, Any], coin: str, side: str, price: float, stop: float, target: float,
          trace_id: str) -> Dict[str, Any]:
    pm = bot.pos_mgr
    lv = plan_levels(side, price, stop, target)
    if lv is None:
        return {"ok": False, "reason": f"price {price:g} is already past the stop or target"}
    if lv["r"] / price < 0.001:
        return {"ok": False, "reason": "stop is closer than 0.1% to the fill price"}
    risk_usd = float(pl.get("risk_usd") or 0) or _f("OWNER_PLAN_DEFAULT_RISK_USD", 10.0)
    leverage = max(1.0, float(pl.get("leverage") or 1))
    try:
        pnl_lev = pm._pnl_lev(leverage)
    except Exception:
        pnl_lev = 1.0
    qty = risk_usd / (lv["r"] * (pnl_lev or 1.0))
    order_side = "BUY" if side == "LONG" else "SELL"

    lock = getattr(bot, "_executing_lock", None)
    execs = getattr(bot, "_executing_symbols", None)
    if lock is not None and execs is not None:
        with lock:
            if coin in execs:
                return {"ok": False, "reason": f"bot was mid-execution in {coin}"}
            execs.add(coin)
    try:
        order = bot.order_executor.open_position(symbol=coin, side=order_side, qty=qty, price=price,
                                                 leverage=int(leverage), order_type="market")
        if not getattr(order, "filled", False):
            return {"ok": False, "reason": f"paper order refused: {getattr(order, 'error', '')}"[:200]}
        fill = order.fill_price if getattr(order, "fill_price", 0) > 0 else price
        qty = order.fill_qty if getattr(order, "fill_qty", 0) > 0 else qty
        lv = plan_levels(side, fill, stop, target) or lv
        try:
            from execution.trade_profile import TradeProfile
            prof = TradeProfile(entry_type="MEDIUM", entry_reasons=[OWNER_STRATEGY], primary_driver=OWNER_STRATEGY,
                                confidence=50.0, regime=(getattr(bot, "_tick_regime_cache", {}) or {}).get(coin, "unknown"),
                                volatility_band="medium", timeframe_bias="medium")
        except Exception:
            prof = None
        regime = (getattr(bot, "_tick_regime_cache", {}) or {}).get(coin, "unknown")
        exit_mode = normalize_exit_mode(pl.get("exit_mode")) or default_exit_mode()
        exit_style = normalize_exit_style(pl.get("exit_style"))
        # 14-day daily ATR known AT THE FILL (the runner's trail width). Stored whatever the flag, so the
        # shadow log and the trade case files see the same number the live rule would use.
        _atr_d, _atr_src = atr_at_fill(bot, coin, time.time())
        # A runner / ladder needs a trail width and a target beyond +1R of the FILL; otherwise run this plan as
        # 'full' (stop / target / time limit), loudly, with the reason on the fill row.
        _style_reason = None
        if exit_style in TRAIL_EXIT_STYLES:
            _style_reason = runner_style_check(side, fill, stop, target, _atr_d, style=exit_style)
            if _style_reason:
                if _valid_atr(_atr_d) is None:
                    logger.warning(f"[OWNER-PLAN] {coin} plan {pl.get('id')}: daily ATR fetch failed at open "
                                   f"({_atr_src}) - plan degraded to exit_style=full")
                else:
                    logger.warning(f"[OWNER-PLAN] {coin} plan {pl.get('id')}: exit_style=full - {_style_reason}")
                exit_style = "full"
        pos = pm.open_position(
            symbol=coin, side=side, entry=fill, qty=qty, sl=lv["sl"], tp1=lv["tp1"], tp2=lv["tp2"],
            atr=_atr_1h(bot, coin), leverage=leverage, mode="leverage" if leverage > 1 else "spot",
            strategy=OWNER_STRATEGY, confidence=50.0,
            entry_reasons={"owner_plan_id": pl.get("id"), "owner_trade": True, "llm_action": "owner",
                           "primary_driver": OWNER_STRATEGY, "regime": regime, "setup": pl.get("setup"),
                           "plan_entry": pl.get("entry"), "plan_stop": stop, "plan_target": target,
                           "exit_mode": exit_mode, "plan_max_hold_h": pl.get("max_hold_h"),
                           "exit_style": exit_style, "atr_at_fill": _atr_d, "atr_at_fill_source": _atr_src,
                           "exit_style_reason": _style_reason, "runner_checked": time.time()},
            trade_profile=prof,
            notes=f"THESIS: owner plan {side} {coin} tgt {target:g} inval {stop:g} | setup=owner_plan",
            setup_type=OWNER_STRATEGY,
        )
        if pos is None:
            return {"ok": False, "reason": "position manager refused (duplicate / cooldown / stop too tight)"}
        return {"ok": True, "entry": pos.entry, "qty": pos.qty, "sl": pos.sl, "tp1": pos.tp1, "tp2": pos.tp2,
                "risk_usd": round(abs(pos.entry - pos.sl) * pos.qty * (pnl_lev or 1.0), 4),
                "position_id": pos.position_id, "pnl_lev": pnl_lev or 1.0, "exit_mode": exit_mode,
                "exit_style": exit_style, "atr_at_fill": _atr_d, "exit_style_reason": _style_reason}
    finally:
        if lock is not None and execs is not None:
            with lock:
                execs.discard(coin)


# ── close-side diversion (called from the multi_strategy_main close loop) ───

def record_owner_close(event, pos, pos_mgr=None) -> Dict[str, Any]:
    """Write one owner_fills.jsonl row for a tagged TP1 / partial / final close and update state.

    Never touches equity, ledgers or learning — the caller `continue`s past all of that.
    """
    md = getattr(event, "metadata", None) or {}
    er = (getattr(pos, "entry_reasons", None) or md.get("entry_reasons") or {}) if pos is not None else (md.get("entry_reasons") or {})
    pid = str(er.get("owner_plan_id") or "")
    final = bool(getattr(event, "is_position_close", False))
    entry = float(getattr(pos, "entry", 0) or md.get("entry") or 0)
    orig_sl = float(getattr(pos, "original_sl", 0) or md.get("sl") or 0)
    orig_qty = float(getattr(pos, "original_qty", 0) or 0) or float(getattr(event, "qty", 0) or 0)
    lev = float(getattr(event, "leverage", 1) or 1)
    try:
        pnl_lev = pos_mgr._pnl_lev(lev) if pos_mgr is not None else 1.0
    except Exception:
        pnl_lev = 1.0
    risk_usd = abs(entry - orig_sl) * orig_qty * (pnl_lev or 1.0)
    funding = float(md.get("funding_costs", 0) or 0) if final else float(md.get("funding_share", 0) or 0)
    leg_net = float(getattr(event, "pnl", 0) or 0) - float(getattr(event, "fee", 0) or 0) - funding
    total = float(getattr(pos, "realized_pnl", 0) or 0) if pos is not None else leg_net
    opened = getattr(pos, "open_time", None)
    row = {
        "kind": "final" if final else "partial", "plan_id": pid, "coin": getattr(event, "symbol", ""),
        "side": getattr(event, "side", ""), "entry": entry, "exit": float(getattr(event, "price", 0) or 0),
        "qty": float(getattr(event, "qty", 0) or 0), "pnl": round(leg_net, 6),
        "r": round(leg_net / risk_usd, 4) if risk_usd > 0 else None, "reason": getattr(event, "action", ""),
        "position_id": getattr(event, "position_id", "") or getattr(pos, "position_id", ""),
        "opened_at": opened.isoformat() if hasattr(opened, "isoformat") else opened, "ts": time.time(),
        "fee": round(float(getattr(event, "fee", 0) or 0), 8), "funding": round(funding, 8),
        "managed_by": managed_by(getattr(event, "action", "")),
        "exit_style": normalize_exit_style(er.get("exit_style")) if isinstance(er, dict) else None,
        "exit_mode": er.get("exit_mode") if isinstance(er, dict) else None,
    }
    if final:
        row["total_pnl"] = round(total, 6)
        row["total_r"] = round(total / risk_usd, 4) if risk_usd > 0 else None
        row["outcome"] = getattr(pos, "outcome", "")
        row["state_path"] = getattr(pos, "state_path_str", "")
    with _LOCK:
        try:
            _append_fill(row)
        except Exception:
            logger.warning("[OWNER-PLAN] fill row write failed", exc_info=True)
        if pid:
            try:
                st = load_state()
                rec = st["plans"].get(pid) or {"first_seen": time.time()}
                rec.setdefault("fills", []).append({k: row[k] for k in ("kind", "exit", "qty", "pnl", "r", "reason", "ts")})
                rec["pnl_usd"] = round(total, 4)
                rec["r"] = round(total / risk_usd, 3) if risk_usd > 0 else None
                if final:
                    rec["status"] = "closed"
                    rec["reason"] = f"closed by bot: {row['reason']}"
                    rec["closed_at"] = row["ts"]
                rec["updated"] = row["ts"]
                st["plans"][pid] = rec
                save_state(st)
            except Exception:
                logger.warning("[OWNER-PLAN] state update on close failed", exc_info=True)
    if final:
        try:
            from core.position_journal import journal_booked
            journal_booked(row["position_id"], symbol=row["coin"])
        except Exception:
            pass
    logger.info(f"[OWNER-PLAN] {row['kind']} {row['coin']} {row['reason']} leg={leg_net:+.2f} "
                f"total={total:+.2f} ({row.get('total_r', row['r'])}R) — excluded from bot books")
    return row
