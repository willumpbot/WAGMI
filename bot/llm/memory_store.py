"""
Persistent memory store for the LLM meta-brain.

Stores structured notes that persist across bot restarts.
The LLM reads a summary of recent notes and can append new ones.

Design:
  - File-backed JSON (simple, no DB overhead)
  - Auto-prunes to last 50 notes (prevents unbounded growth)
  - Robust to first run, corrupted files
  - Thread-safe writes

Schema:
  {
    "last_updated": unix_timestamp,
    "notes": ["note1", "note2", ...]
  }
"""

import json
import logging
import os
import threading
from typing import Optional

logger = logging.getLogger("bot.llm.memory")

_MEMORY_DIR = os.path.join("data", "llm")
_MEMORY_PATH = os.path.join(_MEMORY_DIR, "llm_memory.json")
_MAX_NOTES = 50
_SUMMARY_NOTES = 10  # How many recent notes to include in summary
_MAX_NOTE_LENGTH = 150  # Truncate individual notes

_lock = threading.Lock()
_memory = {"last_updated": 0, "notes": []}
_loaded = False


def _ensure_dir():
    os.makedirs(_MEMORY_DIR, exist_ok=True)


def load_memory() -> dict:
    """Load memory from disk. Safe on first run."""
    global _memory, _loaded

    if _loaded:
        return _memory

    _ensure_dir()
    try:
        if os.path.exists(_MEMORY_PATH):
            with open(_MEMORY_PATH, "r") as f:
                raw = json.load(f)
            if isinstance(raw, dict) and "notes" in raw:
                _memory = raw
                logger.info(f"[LLM-MEM] Loaded {len(_memory['notes'])} memory notes")
            else:
                logger.warning("[LLM-MEM] Invalid memory format, starting fresh")
                _memory = {"last_updated": 0, "notes": []}
        else:
            logger.info("[LLM-MEM] No memory file found, starting fresh")
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"[LLM-MEM] Failed to load memory: {e}")
        # Backup corrupt file
        if os.path.exists(_MEMORY_PATH):
            try:
                os.rename(_MEMORY_PATH, _MEMORY_PATH + ".corrupt")
            except OSError:
                pass
        _memory = {"last_updated": 0, "notes": []}

    _loaded = True
    return _memory


def get_memory_summary() -> Optional[str]:
    """Return a compact summary of recent memory notes for the LLM.

    Returns None if no notes exist (saves tokens).
    """
    mem = load_memory()
    notes = mem.get("notes", [])
    if not notes:
        return None

    recent = notes[-_SUMMARY_NOTES:]
    return " | ".join(recent)


def apply_memory_update(update: Optional[str]):
    """Append a memory note from the LLM's decision.

    Called after every LLM decision (even if gated/rejected).
    Null updates are silently ignored.
    """
    if not update or not update.strip():
        return

    with _lock:
        mem = load_memory()

        # Truncate note
        note = update.strip()[:_MAX_NOTE_LENGTH]

        # Deduplicate: skip if last note is identical
        if mem["notes"] and mem["notes"][-1] == note:
            return

        mem["notes"].append(note)

        # Prune to max
        if len(mem["notes"]) > _MAX_NOTES:
            mem["notes"] = mem["notes"][-_MAX_NOTES:]

        mem["last_updated"] = int(__import__("time").time())

        # Write to disk
        _ensure_dir()
        try:
            with open(_MEMORY_PATH, "w") as f:
                json.dump(mem, f, indent=2)
            logger.info(f"[LLM-MEM] Stored: {note}")
        except IOError as e:
            logger.warning(f"[LLM-MEM] Failed to write memory: {e}")


def get_memory_stats() -> dict:
    """Return memory stats for monitoring."""
    mem = load_memory()
    return {
        "total_notes": len(mem.get("notes", [])),
        "last_updated": mem.get("last_updated", 0),
    }


def clear_memory():
    """Reset memory. Use sparingly."""
    global _memory
    with _lock:
        _memory = {"last_updated": 0, "notes": []}
        _ensure_dir()
        try:
            with open(_MEMORY_PATH, "w") as f:
                json.dump(_memory, f, indent=2)
            logger.info("[LLM-MEM] Memory cleared")
        except IOError as e:
            logger.warning(f"[LLM-MEM] Failed to clear memory: {e}")
