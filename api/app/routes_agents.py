"""
Agent Intelligence API: endpoints for per-agent data, brains, debate outcomes.

Exposes the multi-agent system's internal state to the frontend:
- Per-agent performance (accuracy, calibration, decisions)
- Agent brain state (beliefs, lessons learned)
- Debate outcomes (consensus, disagreements, corroboration)
- Pipeline telemetry (latency, tokens, costs per agent)
"""

import json
import os
from pathlib import Path
from fastapi import APIRouter, Query
from typing import Optional

router = APIRouter(prefix="/v1/agents", tags=["agents"])

# Paths to bot data files
_BOT_DATA = os.environ.get(
    "BOT_DATA_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", "bot", "data"),
)
_BRAINS_DIR = os.path.join(_BOT_DATA, "llm", "brains")
_DECISIONS_PATH = os.path.join(_BOT_DATA, "llm", "decisions.jsonl")
_LEDGER_PATH = os.path.join(_BOT_DATA, "llm", "decision_ledger.jsonl")

# All known agent roles
AGENT_ROLES = ["regime", "trade", "risk", "critic", "learning", "exit", "scout", "quant", "overseer"]


def _read_brain_file(agent: str) -> dict:
    """Read an agent's brain file if it exists."""
    brain_path = os.path.join(_BRAINS_DIR, f"{agent}_brain.json")
    if not os.path.exists(brain_path):
        return {}
    try:
        with open(brain_path, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _tail_jsonl(path: str, n: int = 50) -> list:
    """Read last N lines from a JSONL file."""
    if not os.path.exists(path):
        return []
    try:
        lines = []
        with open(path, "r") as f:
            for line in f:
                if line.strip():
                    lines.append(line)
        # Take last N
        recent = lines[-n:]
        result = []
        for line in recent:
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return list(reversed(result))  # newest first
    except Exception:
        return []


@router.get("/overview")
def get_agents_overview():
    """High-level overview of all agents: status, performance, last activity."""
    agents = []
    for role in AGENT_ROLES:
        brain = _read_brain_file(role)
        perf = brain.get("performance", {})
        agents.append({
            "role": role,
            "has_brain": bool(brain),
            "total_decisions": perf.get("total_decisions", 0),
            "correct_decisions": perf.get("correct_decisions", 0),
            "accuracy": (
                round(perf["correct_decisions"] / perf["total_decisions"], 3)
                if perf.get("total_decisions", 0) > 0 else None
            ),
            "belief_count": len(brain.get("beliefs", [])),
            "last_updated": brain.get("last_updated"),
        })
    return {"agents": agents, "total_agents": len(AGENT_ROLES)}


@router.get("/{agent_role}/brain")
def get_agent_brain(agent_role: str):
    """Full brain state for a specific agent."""
    if agent_role not in AGENT_ROLES:
        return {"error": f"Unknown agent role: {agent_role}", "valid_roles": AGENT_ROLES}

    brain = _read_brain_file(agent_role)
    if not brain:
        return {
            "agent": agent_role,
            "has_brain": False,
            "message": "No brain data yet. Enable multi-agent mode and run trades to populate.",
        }
    return {"agent": agent_role, "has_brain": True, "brain": brain}


@router.get("/{agent_role}/beliefs")
def get_agent_beliefs(
    agent_role: str,
    regime: Optional[str] = Query(default=None),
    min_confidence: float = Query(default=0.0, ge=0.0, le=1.0),
    limit: int = Query(default=20, ge=1, le=100),
):
    """Get an agent's beliefs, optionally filtered by regime and confidence."""
    brain = _read_brain_file(agent_role)
    beliefs = brain.get("beliefs", [])

    if regime:
        beliefs = [b for b in beliefs if b.get("regime_context") == regime]
    if min_confidence > 0:
        beliefs = [b for b in beliefs if b.get("confidence", 0) >= min_confidence]

    # Sort by confidence descending
    beliefs.sort(key=lambda b: b.get("confidence", 0), reverse=True)

    return {
        "agent": agent_role,
        "beliefs": beliefs[:limit],
        "total": len(beliefs),
        "filters": {"regime": regime, "min_confidence": min_confidence},
    }


@router.get("/{agent_role}/calibration")
def get_agent_calibration(agent_role: str, bins: int = Query(default=10, ge=5, le=20)):
    """Get calibration curve for an agent (predicted vs actual accuracy)."""
    brain = _read_brain_file(agent_role)
    perf = brain.get("performance", {})
    cal_history = perf.get("calibration_history", [])

    if not cal_history:
        return {
            "agent": agent_role,
            "has_data": False,
            "message": "No calibration data yet. Need 5+ decisions with outcomes.",
        }

    # Build calibration curve
    bin_size = 1.0 / bins
    curve = {}
    for i in range(bins):
        lower = i * bin_size
        upper = (i + 1) * bin_size
        bucket_label = f"{lower:.1f}-{upper:.1f}"
        in_bucket = [h for h in cal_history if lower <= h[0] < upper]
        if in_bucket:
            actual_acc = sum(1 for h in in_bucket if h[1]) / len(in_bucket)
            curve[bucket_label] = {
                "predicted_avg": round(sum(h[0] for h in in_bucket) / len(in_bucket), 3),
                "actual_accuracy": round(actual_acc, 3),
                "count": len(in_bucket),
            }

    # Overall calibration error
    if cal_history:
        errors = [abs(h[0] - (1.0 if h[1] else 0.0)) for h in cal_history]
        cal_error = round(sum(errors) / len(errors), 4)
    else:
        cal_error = None

    return {
        "agent": agent_role,
        "has_data": True,
        "calibration_error": cal_error,
        "curve": curve,
        "total_decisions": len(cal_history),
    }


@router.get("/{agent_role}/performance")
def get_agent_performance(agent_role: str):
    """Detailed performance metrics for an agent."""
    brain = _read_brain_file(agent_role)
    perf = brain.get("performance", {})

    if not perf:
        return {"agent": agent_role, "has_data": False}

    # Regime breakdown
    by_regime = perf.get("decisions_by_regime", {})
    regime_stats = {}
    for regime, (correct, total) in by_regime.items() if isinstance(by_regime, dict) else []:
        if isinstance(correct, (int, float)) and isinstance(total, (int, float)) and total > 0:
            regime_stats[regime] = {
                "correct": correct,
                "total": total,
                "accuracy": round(correct / total, 3),
            }

    return {
        "agent": agent_role,
        "has_data": True,
        "total_decisions": perf.get("total_decisions", 0),
        "correct_decisions": perf.get("correct_decisions", 0),
        "overall_accuracy": (
            round(perf["correct_decisions"] / perf["total_decisions"], 3)
            if perf.get("total_decisions", 0) > 0 else None
        ),
        "by_regime": regime_stats,
        "avg_response_time_ms": perf.get("avg_response_time_ms"),
        "recent_decisions": perf.get("last_n_decisions", [])[-10:],
    }


@router.get("/debate/latest")
def get_latest_debate():
    """Get the most recent debate outcome (if debate mechanism is active)."""
    debate_path = os.path.join(_BOT_DATA, "llm", "debate_history.jsonl")
    debates = _tail_jsonl(debate_path, 1)
    if not debates:
        return {"has_data": False, "message": "No debate history yet."}
    return {"has_data": True, "debate": debates[0]}


@router.get("/debate/history")
def get_debate_history(limit: int = Query(default=20, ge=1, le=100)):
    """Get recent debate outcomes."""
    debate_path = os.path.join(_BOT_DATA, "llm", "debate_history.jsonl")
    debates = _tail_jsonl(debate_path, limit)
    return {"items": debates, "total": len(debates)}


@router.get("/pipeline/telemetry")
def get_pipeline_telemetry(limit: int = Query(default=20, ge=1, le=100)):
    """Get per-agent pipeline telemetry (tokens, latency, costs)."""
    telemetry_path = os.path.join(_BOT_DATA, "llm", "pipeline_telemetry.jsonl")
    entries = _tail_jsonl(telemetry_path, limit)
    if not entries:
        return {"has_data": False, "message": "No pipeline telemetry yet."}

    # Aggregate stats
    total_tokens = sum(e.get("total_tokens", 0) for e in entries)
    total_cost = sum(e.get("estimated_cost", 0) for e in entries)
    avg_latency = (
        round(sum(e.get("total_latency_ms", 0) for e in entries) / len(entries))
        if entries else 0
    )

    return {
        "has_data": True,
        "recent": entries,
        "aggregate": {
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 4),
            "avg_latency_ms": avg_latency,
            "pipeline_count": len(entries),
        },
    }


@router.get("/team/calibration")
def get_team_calibration():
    """Cross-team calibration report: how well-calibrated is each agent?"""
    results = {}
    for role in AGENT_ROLES:
        brain = _read_brain_file(role)
        perf = brain.get("performance", {})
        cal_history = perf.get("calibration_history", [])
        if cal_history:
            errors = [abs(h[0] - (1.0 if h[1] else 0.0)) for h in cal_history]
            results[role] = {
                "calibration_error": round(sum(errors) / len(errors), 4),
                "decisions": len(cal_history),
                "overall_accuracy": (
                    round(sum(1 for h in cal_history if h[1]) / len(cal_history), 3)
                    if cal_history else None
                ),
            }
    return {
        "has_data": bool(results),
        "agents": results,
        "best_calibrated": min(results, key=lambda k: results[k]["calibration_error"]) if results else None,
    }
