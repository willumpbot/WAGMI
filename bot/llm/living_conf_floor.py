"""Living confidence floor for the LLM risk gate.

THE BUG (found 2026-09-12)
  risk_gating.py Rule 2 rejects every non-flat decision below a HARDCODED 0.60.
  That constant was hand-tuned in an era when the ensemble emitted 0.60-0.95.
  After the DEFABRICATE_* flags removed the fabricated confidence inflation
  (late July 2026), the ensemble's honest output tops out near 0.55 — so Rule 2
  became an absolute wall. The bot took ZERO trades from 2026-07-29 to
  2026-09-12 (45 days) while running perfectly healthy: max observed confidence
  0.62, a single decision above the floor in six weeks.

WHY A PERCENTILE, NOT A SMALLER CONSTANT
  Hand-picking 0.40 would be the same mistake with a smaller number — it dies
  the next time the scale moves. This makes the floor a LIVING VALUE
  (2026-07-14 mandate): the Pth percentile of the confidences the ensemble
  ACTUALLY emits. Selectivity is preserved in RANK terms — act on the top
  (100-P)% of the bot's own decisions — and survives any future rescaling.

WHY NOT AN EDGE SCAN
  The natural alternative is "lowest confidence whose admitted trades are net
  positive" (feedback/live_edge.get_breakeven_confidence_floor's approach).
  The ledger refuses to support it: over n=274 closed trades (2026-06-01 ->
  2026-07-29) confidence is NOT monotone with outcome —

      conf 0-60   n=156  WR=35.3%  net=+$125.88   <- the only positive band
      conf 60-70  n= 63  WR=41.3%  net= -$98.57
      conf 70-75  n= 21  WR=42.9%  net= -$23.96
      conf 75-80  n= 15  WR=20.0%  net=-$162.78   <- the worst band
      conf 80-85  n= 10  WR=20.0%  net=  +$1.26
      conf 95+    n=  5  WR=40.0%  net= -$62.68

  An edge scan over an anti-predictive feature returns noise. So this module
  makes NO claim that higher confidence is better; it only keeps the gate's
  ORIGINAL intent — "act on the ensemble's strongest calls, not its mumbles" —
  expressed in a unit that cannot silently die again.

SAFETY
  - Flag-gated: LIVING_CONF_FLOOR (default false -> legacy 0.60 untouched).
  - Clamped to [FLOOR_MIN, legacy]. It can never open below 0.30 and never sit
    stricter than the 0.60 it replaces, so enabling it moves the gate only
    within a band bounded by today's behaviour.
  - Needs n>=MIN_N real observations, else returns the legacy value
    (fail-closed: no data -> no loosening).
  - Rolling window (count- and age-bounded) so it tracks the live scale.
  - Never touches any other gate rule; circuit breaker, loss limits, position
    caps, regime rejections and strategy-weight sanity all still run.
"""
import os
import json
import time
import logging
import threading

logger = logging.getLogger("bot.llm.living_conf_floor")

_BOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STORE = os.path.join(_BOT, "data", "llm_conf_distribution.json")

MIN_N = 30              # house data-learned standard, raised for a distribution
FLOOR_MIN = 0.30        # hard lower clamp — the gate never opens below this
MAX_OBS = 500           # rolling window: most recent N observations
MAX_AGE_S = 14 * 86400  # ...and nothing older than 14 days
_FLUSH_EVERY_S = 30.0
_TTL_S = 60.0           # recompute the floor at most once a minute

_lock = threading.RLock()
_obs = None             # list[[ts, conf]] once loaded
_dirty = False
_last_flush = 0.0
_cache = {"floor": None, "at": 0.0, "n": None}


def enabled() -> bool:
    return os.getenv("LIVING_CONF_FLOOR", "false").strip().lower() in ("1", "true", "yes")


def percentile_target() -> float:
    """P for the floor. Default 90 -> act on the top 10% of the bot's calls.

    Calibrated 2026-09-12 against the live decision rate (~17 non-flat
    decisions/day): P90 -> floor ~0.41 -> ~3 admits/day before the remaining
    gate rules, landing near the owner's ~2 trades/day posture.
    """
    try:
        p = float(os.getenv("LIVING_CONF_FLOOR_PCTL", "90"))
    except (TypeError, ValueError):
        return 90.0
    return min(99.0, max(50.0, p))


def _load():
    global _obs
    if _obs is not None:
        return _obs
    try:
        with open(_STORE) as fh:
            raw = json.load(fh)
        _obs = [[float(t), float(c)] for t, c in raw.get("obs", [])]
    except (OSError, ValueError, TypeError):
        _obs = []
    return _obs


def _prune(now):
    global _obs
    _obs = [o for o in _obs if now - o[0] <= MAX_AGE_S][-MAX_OBS:]
    return _obs


def _flush(force=False):
    global _dirty, _last_flush
    now = time.time()
    if not _dirty:
        return
    if not force and now - _last_flush < _FLUSH_EVERY_S:
        return
    tmp = _STORE + ".tmp"
    try:
        with open(tmp, "w") as fh:
            json.dump({"obs": _obs, "saved_at": now}, fh)
        os.replace(tmp, _STORE)
        _dirty = False
        _last_flush = now
    except OSError as exc:
        logger.warning("[LIVING-FLOOR] could not persist distribution: %s", exc)


def record(confidence, action="") -> None:
    """Record one non-flat ensemble confidence. Cheap, never raises."""
    if action == "flat":
        return
    try:
        c = float(confidence)
    except (TypeError, ValueError):
        return
    if not 0.0 <= c <= 1.0:
        return
    global _dirty
    with _lock:
        _load()
        now = time.time()
        _obs.append([now, c])
        _prune(now)
        _dirty = True
        _cache["at"] = 0.0     # invalidate
        _flush()


def _percentile(values, p):
    """Nearest-rank percentile — no numpy dependency in the gate path."""
    if not values:
        return None
    s = sorted(values)
    idx = int(round((p / 100.0) * (len(s) - 1)))
    return s[min(max(idx, 0), len(s) - 1)]


def base_floor(legacy: float = 0.60) -> float:
    """The living floor, or `legacy` when the flag is off or evidence is thin."""
    if not enabled():
        return legacy
    with _lock:
        now = time.time()
        if _cache["floor"] is not None and now - _cache["at"] < _TTL_S:
            return _cache["floor"]
        _load()
        _prune(now)
        vals = [c for _, c in _obs]
        if len(vals) < MIN_N:
            _cache.update({"floor": legacy, "at": now, "n": len(vals)})
            return legacy
        raw = _percentile(vals, percentile_target())
        floor = min(legacy, max(FLOOR_MIN, raw))
        if _cache.get("n") != len(vals):
            logger.info(
                "[LIVING-FLOOR] floor=%.2f (P%.0f of n=%d live confidences, "
                "raw=%.2f, clamped to [%.2f, %.2f])",
                floor, percentile_target(), len(vals), raw, FLOOR_MIN, legacy,
            )
        _cache.update({"floor": floor, "at": now, "n": len(vals)})
        return floor


def scaled(legacy_threshold: float, legacy_base: float = 0.60) -> float:
    """Scale a sibling threshold (panic 0.70, loss-streak 0.68, flip 0.65) by the
    same factor the base floor moved, so their RELATIVE strictness is preserved.
    """
    if not enabled() or legacy_base <= 0:
        return legacy_threshold
    factor = base_floor(legacy_base) / legacy_base
    return min(legacy_threshold, max(FLOOR_MIN, legacy_threshold * factor))


def stats() -> dict:
    with _lock:
        _load()
        now = time.time()
        _prune(now)
        vals = [c for _, c in _obs]
        return {
            "enabled": enabled(),
            "n": len(vals),
            "pctl": percentile_target(),
            "floor": base_floor(),
            "min": min(vals) if vals else None,
            "max": max(vals) if vals else None,
        }


def flush() -> None:
    with _lock:
        _flush(force=True)
