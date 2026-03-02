"""
Multi-Agent LLM System for trading decisions.

Instead of one monolithic LLM call, specialised agents each focus on a
narrow domain (regime analysis, trade evaluation, risk assessment,
post-trade learning, self-critique). The coordinator orchestrates them
and merges their outputs into a single LLMDecision.

Enable via LLM_MULTI_AGENT=true in .env.
"""
