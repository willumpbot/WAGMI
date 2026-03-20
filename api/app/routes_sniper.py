"""
Sniper Queue API routes.

Reads from the bot's SQLite database directly (same filesystem approach
used by routes_llm.py for decisions.jsonl). The sniper_queue table is
written by the bot's LLMSniperEngine when LLM_SNIPER_ENABLED=true.

Endpoints:
  GET  /v1/sniper/queue       - list pending proposals
  GET  /v1/sniper/history     - list approved/rejected history
  POST /v1/sniper/{id}/approve - approve a proposal
  POST /v1/sniper/{id}/reject  - reject a proposal
  GET  /v1/sniper/stats       - summary counts
"""

import os
import sqlite3
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger("api.sniper")

router = APIRouter(prefix="/v1/sniper", tags=["sniper"])

# Path to bot's SQLite — same approach as routes_llm.py reading decisions.jsonl
_BOT_DB_PATH = os.environ.get(
    "BOT_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", "bot", "ml_data", "bot.db"),
)


# ── DB helpers ─────────────────────────────────────────────────────────────

def _get_conn() -> Optional[sqlite3.Connection]:
    """Get a connection to the bot's SQLite. Returns None if DB not found."""
    path = os.path.abspath(_BOT_DB_PATH)
    if not os.path.exists(path):
        return None
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _rows_to_list(rows) -> List[Dict[str, Any]]:
    return [dict(r) for r in rows]


def _table_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='sniper_queue'"
    ).fetchone()
    return row is not None


# ── Schemas ────────────────────────────────────────────────────────────────

class RejectRequest(BaseModel):
    reason: Optional[str] = None


# ── Routes ────────────────────────────────────────────────────────────────

@router.get("/queue")
def get_queue(limit: int = Query(50, ge=1, le=200)):
    """List pending sniper proposals, most recent first."""
    conn = _get_conn()
    if conn is None:
        return {"proposals": [], "note": "Bot database not found — bot may not be running"}
    try:
        if not _table_exists(conn):
            return {"proposals": [], "note": "sniper_queue table not yet created — start the bot first"}
        rows = conn.execute(
            "SELECT * FROM sniper_queue WHERE status = 'pending' ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return {"proposals": _rows_to_list(rows), "count": len(rows)}
    finally:
        conn.close()


@router.get("/history")
def get_history(limit: int = Query(100, ge=1, le=500)):
    """List approved/rejected/executed proposals, most recent first."""
    conn = _get_conn()
    if conn is None:
        return {"proposals": [], "note": "Bot database not found"}
    try:
        if not _table_exists(conn):
            return {"proposals": [], "note": "sniper_queue table not yet created"}
        rows = conn.execute(
            """SELECT * FROM sniper_queue
               WHERE status IN ('approved', 'rejected', 'executed')
               ORDER BY reviewed_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return {"proposals": _rows_to_list(rows), "count": len(rows)}
    finally:
        conn.close()


@router.get("/stats")
def get_stats():
    """Summary counts for the sniper queue dashboard widget."""
    conn = _get_conn()
    if conn is None:
        return {"pending": 0, "approved": 0, "rejected": 0, "executed": 0, "total": 0,
                "note": "Bot database not found"}
    try:
        if not _table_exists(conn):
            return {"pending": 0, "approved": 0, "rejected": 0, "executed": 0, "total": 0}
        rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM sniper_queue GROUP BY status"
        ).fetchall()
        counts = {r["status"]: r["cnt"] for r in rows}
        return {
            "pending": counts.get("pending", 0),
            "approved": counts.get("approved", 0),
            "rejected": counts.get("rejected", 0),
            "executed": counts.get("executed", 0),
            "total": sum(counts.values()),
        }
    finally:
        conn.close()


@router.post("/{proposal_id}/approve")
def approve_proposal(proposal_id: str):
    """Approve a pending sniper proposal for paper execution."""
    conn = _get_conn()
    if conn is None:
        raise HTTPException(status_code=503, detail="Bot database not available")
    try:
        if not _table_exists(conn):
            raise HTTPException(status_code=503, detail="sniper_queue table not found")

        row = conn.execute(
            "SELECT * FROM sniper_queue WHERE id = ?", (proposal_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Proposal not found")
        if dict(row)["status"] != "pending":
            raise HTTPException(status_code=409, detail=f"Proposal is already {dict(row)['status']}")

        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE sniper_queue SET status = 'approved', reviewed_at = ? WHERE id = ?",
            (now, proposal_id),
        )
        conn.commit()
        logger.info(f"[SNIPER-API] Approved proposal {proposal_id}")
        return {"status": "approved", "id": proposal_id, "reviewed_at": now}
    finally:
        conn.close()


@router.post("/{proposal_id}/reject")
def reject_proposal(proposal_id: str, body: RejectRequest = RejectRequest()):
    """Reject a pending sniper proposal."""
    conn = _get_conn()
    if conn is None:
        raise HTTPException(status_code=503, detail="Bot database not available")
    try:
        if not _table_exists(conn):
            raise HTTPException(status_code=503, detail="sniper_queue table not found")

        row = conn.execute(
            "SELECT * FROM sniper_queue WHERE id = ?", (proposal_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Proposal not found")
        if dict(row)["status"] != "pending":
            raise HTTPException(status_code=409, detail=f"Proposal is already {dict(row)['status']}")

        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE sniper_queue SET status = 'rejected', reviewed_at = ? WHERE id = ?",
            (now, proposal_id),
        )
        conn.commit()
        logger.info(f"[SNIPER-API] Rejected proposal {proposal_id} (reason: {body.reason})")
        return {"status": "rejected", "id": proposal_id, "reviewed_at": now}
    finally:
        conn.close()
