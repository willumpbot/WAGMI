"""Backend integration for multi-agent system.

Provides a clean interface for routing agent calls through the LLMBackend
abstraction layer (CliBackend, ApiBackend, OllamaBackend) while preserving
existing prompt enrichment, token counting, and error handling logic.

This enables:
- Switchable backends without code changes
- Automatic fallback chains
- Per-backend cost and latency tracking
- Unified fail-loud error handling
"""

import json
import logging
import time
from typing import Tuple, Dict, Any, Optional

from llm.backend import get_default_router, LLMResponse

logger = logging.getLogger(__name__)


def call_agent_via_backend(
    system_prompt: str,
    snapshot_json: str,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 2048,
    timeout_s: float = 60.0,
    agent_name: str = "unknown",
) -> Tuple[Optional[str], Dict[str, Any]]:
    """Call agent through LLMBackend abstraction.

    Args:
        system_prompt: Complete system prompt (static + dynamic + agent base)
        snapshot_json: JSON snapshot of market/portfolio context
        model: Model name (haiku/sonnet/opus or full model ID)
        max_tokens: Max output tokens
        timeout_s: Call timeout in seconds
        agent_name: Agent name for logging (regime/trade/risk/critic/etc)

    Returns:
        Tuple[raw_text, usage_dict]:
        - raw_text: LLM response (None on failure)
        - usage_dict: {input_tokens, output_tokens, error, latency_ms, ...}
    """
    start = time.monotonic()
    router = get_default_router()

    try:
        # Call through backend abstraction
        response = router.call(
            prompt=snapshot_json,
            system=system_prompt,
            model=model,
            max_tokens=max_tokens,
            timeout_s=timeout_s,
            agent_name=agent_name,
        )

        latency_ms = int((time.monotonic() - start) * 1000)

        # Check success
        if not response.ok:
            error_msg = response.error or "Unknown backend error"
            logger.warning(
                f"[BACKEND] {agent_name} call failed: {error_msg} "
                f"({response.backend_name}, latency={latency_ms}ms)"
            )
            return None, {
                "error": error_msg,
                "latency_ms": latency_ms,
                "backend": response.backend_name,
                "input_tokens": 0,
                "output_tokens": 0,
            }

        # Success: return text + stats
        return response.text, {
            "input_tokens": 0,  # TODO: track from backend
            "output_tokens": 0,  # TODO: track from backend
            "latency_ms": latency_ms,
            "backend": response.backend_name,
            "cost_usd": response.cost_usd,
            "model_used": response.model,
        }

    except Exception as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        error_msg = f"{type(e).__name__}: {str(e)[:200]}"
        logger.error(
            f"[BACKEND] {agent_name} call exception: {error_msg}",
            exc_info=True,
        )
        return None, {
            "error": error_msg,
            "latency_ms": latency_ms,
            "backend": "unknown",
            "input_tokens": 0,
            "output_tokens": 0,
        }
