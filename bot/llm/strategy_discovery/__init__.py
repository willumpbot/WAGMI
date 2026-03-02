# Strategy Discovery - LLM-driven autonomous strategy research
#
# This package implements the strategy discovery pipeline:
#   1. Corpus: Structured knowledge base of market observations
#   2. Research Agent: LLM-driven pattern analysis for strategy proposals
#   3. Proposals: Lifecycle management for strategy ideas (DRAFT -> SANDBOX -> APPROVED -> ACTIVE)
#   4. Sandbox: Safe backtest-style evaluation before live deployment

from .proposals import StrategyProposal, ProposalStatus
from .corpus import add_observation, load_observations, get_corpus_summary, trim_corpus
from .research_agent import (
    run_research_cycle,
    build_research_prompt,
    parse_research_output,
    create_proposals_from_research,
    save_proposal,
    load_proposal,
    list_proposals,
    format_proposals_telegram,
)
from .sandbox import (
    evaluate_proposal,
    promote_to_approval,
    approve_proposal,
    reject_proposal,
)

__all__ = [
    "StrategyProposal",
    "ProposalStatus",
    "add_observation",
    "load_observations",
    "get_corpus_summary",
    "trim_corpus",
    "run_research_cycle",
    "build_research_prompt",
    "parse_research_output",
    "create_proposals_from_research",
    "save_proposal",
    "load_proposal",
    "list_proposals",
    "format_proposals_telegram",
    "evaluate_proposal",
    "promote_to_approval",
    "approve_proposal",
    "reject_proposal",
]
