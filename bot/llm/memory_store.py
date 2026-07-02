"""
Persistent memory store for the LLM meta-brain.

Stores structured notes that persist across bot restarts.
The LLM reads a summary of recent notes and can append new ones.

Design:
  - File-backed JSON (simple, no DB overhead)
  - Auto-prunes to last 50 notes (prevents unbounded growth)
  - Drops stale notes (>48h)
  - Drops near-duplicate notes
  - Per-symbol pattern tracking
  - Robust to first run, corrupted files
  - Thread-safe writes

Schema:
  {
    "last_updated": unix_timestamp,
    "notes": [
      {
        "text": "SOL breakout longs failing in high_vol regime",
        "ts": 1700000000,
        "symbol": "SOL",
        "regime": "high_volatility"
      },
      ...
    ]
  }
"""

import json
import logging
import os
import threading
import time
from typing import Optional, List, Dict, Any

logger = logging.getLogger("bot.llm.memory")

_MEMORY_DIR = os.path.join("data", "llm")
_MEMORY_PATH = os.path.join(_MEMORY_DIR, "llm_memory.json")
_MAX_NOTES = 100            # Doubled for aggressive learning (was 50)
_SUMMARY_NOTES = 15         # More context for LLM (was 10)
_MAX_NOTE_LENGTH = 200      # Longer notes for richer context (was 150)
_STALE_SECONDS = 168 * 3600 # 7 days retention for learning persistence (was 48h)
_DEDUP_SIMILARITY = 0.8     # Drop notes > 80% similar to recent ones

_lock = threading.Lock()
_memory = {"last_updated": 0, "notes": []}
_loaded = False


def _ensure_dir():
    os.makedirs(_MEMORY_DIR, exist_ok=True)


def load_memory() -> dict:
    """Load memory from disk. Safe on first run.

    Migrates old format (plain string notes) to new format (structured dicts).
    """
    global _memory, _loaded

    if _loaded:
        return _memory

    _ensure_dir()
    try:
        if os.path.exists(_MEMORY_PATH):
            with open(_MEMORY_PATH, "r") as f:
                raw = json.load(f)
            if isinstance(raw, dict) and "notes" in raw:
                # Migrate old format: list of strings -> list of dicts
                migrated = []
                for note in raw.get("notes", []):
                    if isinstance(note, str):
                        migrated.append({
                            "text": note,
                            "ts": raw.get("last_updated", time.time()),
                            "symbol": "",
                            "regime": "",
                        })
                    elif isinstance(note, dict) and "text" in note:
                        migrated.append(note)
                raw["notes"] = migrated
                _memory = raw
                logger.info(f"[LLM-MEM] Loaded {len(_memory['notes'])} memory notes")
            else:
                logger.warning("[LLM-MEM] Invalid memory format, starting fresh")
                _memory = {"last_updated": 0, "notes": []}
        else:
            logger.info("[LLM-MEM] No memory file found, starting fresh")
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"[LLM-MEM] Failed to load memory: {e}")
        if os.path.exists(_MEMORY_PATH):
            try:
                os.rename(_MEMORY_PATH, _MEMORY_PATH + ".corrupt")
            except OSError:
                pass
        _memory = {"last_updated": 0, "notes": []}

    _loaded = True
    return _memory


def _prune_stale(notes: List[Dict]) -> List[Dict]:
    """Remove notes older than 48 hours."""
    cutoff = time.time() - _STALE_SECONDS
    before = len(notes)
    notes = [n for n in notes if n.get("ts", 0) > cutoff]
    removed = before - len(notes)
    if removed > 0:
        logger.info(f"[LLM-MEM] Pruned {removed} stale notes (>48h)")
    return notes


def _dedup(notes: List[Dict]) -> List[Dict]:
    """Remove near-duplicate notes (keep most recent)."""
    if not notes:
        return notes

    seen_texts = set()
    unique = []
    for note in reversed(notes):
        text = note.get("text", "").strip().lower()
        # Exact dedup
        if text in seen_texts:
            continue
        # Prefix dedup (if first 60 chars match, it's a near-dup)
        prefix = text[:60]
        if prefix in seen_texts:
            continue
        seen_texts.add(text)
        seen_texts.add(prefix)
        unique.append(note)

    unique.reverse()
    removed = len(notes) - len(unique)
    if removed > 0:
        logger.info(f"[LLM-MEM] Deduped {removed} near-duplicate notes")
    return unique


def _cap_size(notes: List[Dict]) -> List[Dict]:
    """Keep only last N notes."""
    if len(notes) > _MAX_NOTES:
        notes = notes[-_MAX_NOTES:]
    return notes


def prune_memory():
    """Full pruning pipeline: stale -> dedup -> cap."""
    with _lock:
        mem = load_memory()
        notes = mem.get("notes", [])
        notes = _prune_stale(notes)
        notes = _dedup(notes)
        notes = _cap_size(notes)
        mem["notes"] = notes
        _save(mem)


def get_memory_summary() -> Optional[str]:
    """Return a compact summary of recent memory notes for the LLM.

    Format optimized for token efficiency:
    - Most recent notes first (LLM sees freshest info)
    - Symbol tags for context
    - Pipe-separated for compact packing
    - Returns None if no notes exist (saves tokens)
    """
    mem = load_memory()
    notes = mem.get("notes", [])
    if not notes:
        return None

    # Prune before summarizing
    notes = _prune_stale(notes)

    recent = notes[-_SUMMARY_NOTES:]
    parts = []
    for n in reversed(recent):
        text = n.get("text", "") if isinstance(n, dict) else str(n)
        symbol = n.get("symbol", "") if isinstance(n, dict) else ""
        # Render provenance (FALLACY_AUDIT D15): these are n=1 self-opinions;
        # the date tells the reader which era the note is from.
        _date = ""
        if isinstance(n, dict) and n.get("ts"):
            try:
                _date = time.strftime("%m-%d", time.gmtime(float(n["ts"])))
            except (ValueError, TypeError, OSError):
                _date = ""
        tag_bits = [b for b in (symbol, _date, "n=1 opinion") if b]
        parts.append(f"[{' '.join(tag_bits)}] {text}")

    return " | ".join(parts)


def get_symbol_patterns(symbol: str) -> List[str]:
    """Get recent memory notes specific to a symbol.

    Useful for pre-trade veto checks: what has the LLM learned about this symbol?
    """
    mem = load_memory()
    notes = mem.get("notes", [])
    patterns = []
    for n in reversed(notes):
        if isinstance(n, dict) and n.get("symbol", "").upper() == symbol.upper():
            patterns.append(n.get("text", ""))
        if len(patterns) >= 5:
            break
    return patterns


def _is_quality_note(text: str) -> bool:
    """Filter out low-quality memory notes that would pollute the knowledge base.

    Quality notes should contain specific, actionable insights about market
    conditions, strategy behavior, or trading patterns. Generic observations
    like "BTC went up" or "lost money" are noise.

    Structured lessons from post-trade learner always pass (they contain
    specific symbol, regime, action, and outcome data).
    """
    text_lower = text.lower().strip()

    # Too short to be useful
    if len(text_lower) < 20:
        return False

    # Structured lessons from post-trade learner are always quality
    # (they contain symbol + regime + actionable insight with em-dash markers)
    _STRUCTURED_MARKERS = [
        "—replicate", "—be cautious", "—exit earlier", "—reduce confidence",
        "—entry timing", "—setup works", "—consider", "—flip side",
        "win +$", "loss despite", "sl in ", "gated by",
    ]
    if any(marker in text_lower for marker in _STRUCTURED_MARKERS):
        return True

    # Generic/obvious statements that don't teach anything
    # Note: "lost money" and "made money" removed — these ARE useful when paired
    # with specific context (e.g., "we lost money shorting SOL in trends").
    # Only reject truly vague forms: "lost some money", "made some money".
    _NOISE_PATTERNS = [
        "went up", "went down", "price increased", "price decreased",
        "lost some money", "made some money",
        "market is uncertain", "regime is unknown", "no clear direction",
        "will monitor", "need more data", "waiting for",
        "nothing notable", "no significant", "flat market",
    ]
    for pattern in _NOISE_PATTERNS:
        if pattern in text_lower:
            return False

    # Notes with specific data (symbols + percentages/dollars) are always valuable
    import re
    has_specific_data = bool(re.search(r'\d+%|\$\d+|\d+\.\d+', text))
    has_symbol = any(sym in text.upper() for sym in ["BTC", "ETH", "SOL", "DOGE", "HYPE", "PEPE", "FARTCOIN", "WIF"])
    if has_specific_data and has_symbol:
        return True

    # Should mention at least one of: symbol, condition, or outcome pattern
    # Notes with commas or semicolons likely have structure (condition + result)
    has_structure = any(c in text for c in [",", ";", "—", "→", "because", "when", "if"])

    # Accept if it has structure OR mentions a specific symbol
    return has_structure or has_symbol


# Provenance tag for notes written going forward (THE_STANDARD 2b/3b —
# FALLACY_AUDIT D15: notes reached Trade + Critic prompts with no ledger
# version, no n, no source trade).
_LEDGER_VERSION = "v2_post_fee_fix_2026-06"


def _sanitize_symbol(symbol: str, text: str) -> str:
    """Validate a caller-supplied symbol; fall back to extracting from text.

    FALLACY_AUDIT D15 bug: decision_engine passed trigger_context.split()[0]
    as the symbol, writing garbage like '[PRE-CLOSE' / '[POSITION' into the
    symbol field (which then failed every symbol-keyed recall).
    """
    s = (symbol or "").strip().upper()
    if s and s.isalnum():
        return s
    return _extract_symbol(text)


def apply_memory_update(
    update: Optional[str],
    symbol: str = "",
    regime: str = "",
    source_trade_id: str = "",
):
    """Append a memory note from the LLM's decision.

    Called only for allowed (non-gated) decisions.
    Null updates and low-quality notes are silently ignored.

    Args:
        update: The memory note text (from LLM output)
        symbol: Symbol context (optional)
        regime: Regime context (optional)
        source_trade_id: Trade this note was learned from, if any (provenance)
    """
    if not update or not update.strip():
        return

    # Quality gate: reject noise
    if not _is_quality_note(update):
        logger.debug(f"[LLM-MEM] Rejected low-quality note: {update[:80]}")
        return

    with _lock:
        mem = load_memory()

        # Truncate note
        text = update.strip()[:_MAX_NOTE_LENGTH]

        # Deduplicate: skip if last note is identical
        notes = mem.get("notes", [])
        if notes:
            last_text = notes[-1].get("text", "") if isinstance(notes[-1], dict) else str(notes[-1])
            if last_text == text:
                return

        # Validate/extract symbol (rejects '[PRE-CLOSE'-style garbage)
        symbol = _sanitize_symbol(symbol, text)

        note_entry = {
            "text": text,
            "ts": time.time(),
            "symbol": symbol,
            "regime": regime,
            # Write-time provenance (FALLACY_AUDIT D15 / THE_STANDARD 3b):
            # every note is a single LLM self-opinion (n=1) until validated.
            "n": 1,
            "ledger_version": _LEDGER_VERSION,
            "source_trade_id": source_trade_id,
        }

        notes.append(note_entry)

        # Full prune pipeline
        notes = _prune_stale(notes)
        notes = _dedup(notes)
        notes = _cap_size(notes)

        mem["notes"] = notes
        mem["last_updated"] = int(time.time())

        _save(mem)
        logger.info(f"[LLM-MEM] Stored: {text}")


def _extract_symbol(text: str) -> str:
    """Try to extract a symbol name from note text.

    Looks for known symbols in the text.
    """
    from trading_config import DEFAULT_SYMBOLS

    text_upper = text.upper()
    for sym in DEFAULT_SYMBOLS:
        if sym in text_upper:
            return sym
    return ""


def _save(mem: dict):
    """Write memory to disk."""
    _ensure_dir()
    try:
        with open(_MEMORY_PATH, "w") as f:
            json.dump(mem, f, indent=2)
    except IOError as e:
        logger.warning(f"[LLM-MEM] Failed to write memory: {e}")


def get_memory_stats() -> dict:
    """Return memory stats for monitoring."""
    mem = load_memory()
    notes = mem.get("notes", [])
    now = time.time()

    # Count by symbol
    symbol_counts: Dict[str, int] = {}
    for n in notes:
        sym = n.get("symbol", "") if isinstance(n, dict) else ""
        if sym:
            symbol_counts[sym] = symbol_counts.get(sym, 0) + 1

    return {
        "total_notes": len(notes),
        "last_updated": mem.get("last_updated", 0),
        "oldest_note_age_h": round((now - min((n.get("ts", now) for n in notes), default=now)) / 3600, 1) if notes else 0,
        "newest_note_age_s": round(now - max((n.get("ts", 0) for n in notes), default=0)) if notes else 0,
        "symbol_counts": symbol_counts,
    }


def clear_memory():
    """Reset memory. Use sparingly."""
    global _memory
    with _lock:
        _memory = {"last_updated": 0, "notes": []}
        _save(_memory)
        logger.info("[LLM-MEM] Memory cleared")
