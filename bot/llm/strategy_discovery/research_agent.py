"""
Research Agent: LLM-driven pattern analysis for strategy discovery.

Analyzes the corpus of observations and trade outcomes to:
1. Identify recurring profitable patterns
2. Detect regime-specific edge opportunities
3. Generate strategy proposals
4. Score existing strategies against recent data
"""

import json
import logging
import os
import time
import uuid
from typing import Dict, List, Any, Optional

from .corpus import get_corpus_summary, PATTERN_TEMPLATES, add_observation
from .proposals import StrategyProposal, ProposalStatus

logger = logging.getLogger("bot.llm.strategy_discovery.research_agent")

_PROPOSALS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "strategy_proposals"
)


def _ensure_proposals_dir():
    os.makedirs(_PROPOSALS_DIR, exist_ok=True)


def save_proposal(proposal: StrategyProposal) -> str:
    """Save a proposal to disk. Returns the file path."""
    _ensure_proposals_dir()
    path = os.path.join(_PROPOSALS_DIR, f"{proposal.proposal_id}.json")
    with open(path, "w") as f:
        json.dump(proposal.to_dict(), f, indent=2)
    return path


def load_proposal(proposal_id: str) -> Optional[StrategyProposal]:
    """Load a proposal by ID."""
    path = os.path.join(_PROPOSALS_DIR, f"{proposal_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return StrategyProposal.from_dict(json.load(f))


def list_proposals(status_filter: Optional[str] = None) -> List[StrategyProposal]:
    """List all proposals, optionally filtered by status."""
    _ensure_proposals_dir()
    proposals = []
    for fname in os.listdir(_PROPOSALS_DIR):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(_PROPOSALS_DIR, fname)
        try:
            with open(path, "r") as f:
                p = StrategyProposal.from_dict(json.load(f))
            if status_filter and p.status.value != status_filter:
                continue
            proposals.append(p)
        except Exception:
            continue
    return sorted(proposals, key=lambda p: p.created_ts, reverse=True)


def build_research_prompt(corpus_summary: Dict[str, Any]) -> str:
    """Build the prompt for the LLM research agent.

    The research agent analyzes the corpus and proposes new strategies
    or modifications to existing ones.
    """
    patterns_desc = "\n".join(
        f"  - {name}: {p['description']} (regimes: {', '.join(p['best_regimes'])})"
        for name, p in PATTERN_TEMPLATES.items()
    )

    recent_obs = corpus_summary.get("recent_observations", [])
    obs_text = "\n".join(
        f"  [{o['category']}] {o['symbol']} ({o['regime']}): {o['observation']}"
        for o in recent_obs[-20:]
    ) if recent_obs else "  (no recent observations)"

    regime_dist = corpus_summary.get("by_regime", {})
    regime_text = ", ".join(f"{k}: {v}" for k, v in regime_dist.items()) if regime_dist else "no data"

    return f"""You are the STRATEGY RESEARCH AGENT for the WAGMI trading bot.

KNOWN STRATEGY PATTERNS:
{patterns_desc}

RECENT MARKET OBSERVATIONS ({corpus_summary.get('total_observations', 0)} total):
{obs_text}

REGIME DISTRIBUTION: {regime_text}

YOUR TASK:
Analyze the observations and identify opportunities to improve trading performance.
Consider:
1. Are there recurring patterns not captured by existing strategies?
2. Are certain regimes consistently profitable/unprofitable?
3. Are there symbol-specific edges we're missing?
4. Can we combine existing patterns in new ways?

OUTPUT FORMAT (JSON):
{{
  "insights": ["insight1", "insight2"],
  "proposed_strategies": [
    {{
      "name": "strategy_name",
      "description": "what it does",
      "rationale": "why it should work based on observations",
      "entry_conditions": ["condition1", "condition2"],
      "exit_conditions": ["condition1", "condition2"],
      "best_regimes": ["trend", "range"],
      "avoid_regimes": ["panic"],
      "expected_rr": 2.0,
      "expected_win_rate": 0.55,
      "target_symbols": []
    }}
  ],
  "strategy_adjustments": [
    {{
      "pattern_name": "existing_pattern",
      "adjustment": "what to change",
      "reason": "why"
    }}
  ]
}}

Only propose strategies with clear rationale grounded in the observations.
Never propose strategies with leverage > 10x or position size > 2% of equity."""


def parse_research_output(raw_output: str) -> Dict[str, Any]:
    """Parse the LLM research agent's output into structured proposals."""
    try:
        # Try to find JSON block
        start = raw_output.find("{")
        end = raw_output.rfind("}") + 1
        if start == -1 or end == 0:
            return {"error": "No JSON found in output"}
        parsed = json.loads(raw_output[start:end])
        return parsed
    except json.JSONDecodeError as e:
        return {"error": f"JSON parse error: {e}"}


def create_proposals_from_research(
    research_output: Dict[str, Any],
) -> List[StrategyProposal]:
    """Convert research agent output into StrategyProposal objects."""
    proposals = []
    for raw in research_output.get("proposed_strategies", []):
        proposal = StrategyProposal(
            proposal_id=f"prop_{uuid.uuid4().hex[:8]}",
            name=raw.get("name", "unnamed"),
            description=raw.get("description", ""),
            rationale=raw.get("rationale", ""),
            entry_conditions=raw.get("entry_conditions", []),
            exit_conditions=raw.get("exit_conditions", []),
            best_regimes=raw.get("best_regimes", []),
            avoid_regimes=raw.get("avoid_regimes", []),
            expected_rr=float(raw.get("expected_rr", 1.5)),
            expected_win_rate=float(raw.get("expected_win_rate", 0.5)),
            target_symbols=raw.get("target_symbols", []),
            status=ProposalStatus.DRAFT,
            created_ts=time.time(),
        )
        if proposal.is_safe():
            proposals.append(proposal)
            save_proposal(proposal)
            logger.info(f"[RESEARCH] Created proposal: {proposal.name} ({proposal.proposal_id})")
        else:
            logger.warning(f"[RESEARCH] Unsafe proposal rejected: {proposal.name}")

    # Log insights as observations
    for insight in research_output.get("insights", []):
        add_observation(
            category="insight",
            symbol="ALL",
            regime="unknown",
            observation=insight,
        )

    return proposals


def run_research_cycle(
    max_proposals: int = 3,
    notify_fn=None,
) -> List[StrategyProposal]:
    """Run a single research cycle: analyze corpus, generate proposals.

    This is the main entry point called from the bot's learning cycle.
    Uses deep memory + corpus data to generate strategy proposals.

    Args:
        max_proposals: Maximum number of proposals to generate
        notify_fn: Optional callback to send notifications (e.g., Telegram)

    Returns:
        List of generated StrategyProposal objects
    """
    try:
        # Step 1: Build corpus summary
        corpus_summary = get_corpus_summary(max_observations=50)
        total_obs = corpus_summary.get("total_observations", 0)
        if total_obs < 5:
            logger.info("[RESEARCH] Not enough observations for research cycle")
            return []

        # Step 2: Enrich with deep memory knowledge
        enriched_summary = dict(corpus_summary)
        try:
            from llm.deep_memory import get_deep_memory
            dm = get_deep_memory()
            knowledge = dm.build_llm_knowledge_summary()
            if knowledge:
                enriched_summary["deep_memory_knowledge"] = knowledge
            # Add strategy effectiveness data
            effectiveness = dm.trade_dna.get_strategy_effectiveness()
            if effectiveness:
                enriched_summary["strategy_effectiveness"] = {
                    k: {"win_rate": v.get("win_rate", 0), "total": v["total"]}
                    for k, v in effectiveness.items()
                    if v["total"] >= 3
                }
        except Exception as e:
            logger.debug(f"[RESEARCH] Deep memory enrichment failed: {e}")

        # Step 3: Build research prompt
        prompt = build_research_prompt(enriched_summary)

        # Step 4: Call LLM (use low-cost model for research)
        try:
            from llm.client import call_llm
            raw_text, usage = call_llm(
                system_prompt=prompt,
                snapshot_json="{}",
                model="claude-haiku-4-5-20251001",
                max_tokens=2000,
            )
        except Exception as e:
            logger.warning(f"[RESEARCH] LLM call failed: {e}")
            return []

        if not raw_text:
            return []

        # Step 5: Parse output
        research_output = parse_research_output(raw_text)
        if "error" in research_output:
            logger.warning(f"[RESEARCH] Parse error: {research_output['error']}")
            return []

        # Step 6: Create proposals
        proposals = create_proposals_from_research(research_output)
        proposals = proposals[:max_proposals]

        # Step 7: Notify operator
        if proposals and notify_fn:
            try:
                msg = format_proposals_telegram(proposals)
                notify_fn(msg)
            except Exception:
                pass

        logger.info(
            f"[RESEARCH] Cycle complete: {len(proposals)} proposals from "
            f"{total_obs} observations"
        )
        return proposals

    except Exception as e:
        logger.error(f"[RESEARCH] Research cycle failed: {e}")
        return []


def format_proposals_telegram(proposals: List[StrategyProposal]) -> str:
    """Format proposals for Telegram display."""
    if not proposals:
        return "No proposals found."
    lines = ["STRATEGY PROPOSALS:"]
    for p in proposals[:10]:
        status_icon = {
            "draft": "📝", "sandbox_pending": "⏳", "sandbox_passed": "✅",
            "sandbox_failed": "❌", "awaiting_approval": "🔔",
            "approved": "👍", "rejected": "👎", "active": "🟢",
        }.get(p.status.value, "❓")
        lines.append(
            f"\n{status_icon} {p.name} [{p.proposal_id}]"
            f"\n  {p.description[:100]}"
            f"\n  Regimes: {', '.join(p.best_regimes)}"
            f"\n  RR: {p.expected_rr:.1f} | WR: {p.expected_win_rate:.0%}"
            f"\n  Status: {p.status.value}"
        )
    return "\n".join(lines)
