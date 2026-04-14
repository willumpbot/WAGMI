"""
Claude API client for the LLM meta-brain.

Wraps the Anthropic Python SDK with:
  - Retry logic (exponential backoff)
  - Token usage tracking
  - Timeout handling
  - Graceful degradation (returns None on failure, never crashes the bot)

Required env: ANTHROPIC_API_KEY
"""

import logging
import os
import time
from typing import Optional, Tuple

logger = logging.getLogger("bot.llm.client")

# Track cumulative token usage for cost monitoring
_total_input_tokens = 0
_total_output_tokens = 0
_total_calls = 0
_total_failures = 0


def _get_client():
    """Lazy-init the Anthropic client."""
    try:
        import anthropic
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            logger.warning("ANTHROPIC_API_KEY not set, LLM calls will fail")
            return None
        return anthropic.Anthropic(api_key=api_key, max_retries=0)
    except ImportError:
        logger.warning("anthropic package not installed (pip install anthropic)")
        return None


# Singleton client
_client = None


def get_client():
    global _client
    if _client is None:
        _client = _get_client()
    return _client


def call_llm(
    system_prompt: str,
    snapshot_json: str,
    model: str = "claude-sonnet-4-5-20250929",
    max_tokens: int = 4096,
    max_retries: int = 2,
    timeout: float = 30.0,
) -> Tuple[Optional[str], dict]:
    """Send a snapshot to Claude and get back raw text.

    Returns:
        (response_text, usage_stats) where response_text is None on failure.
        usage_stats always contains: {"input_tokens": int, "output_tokens": int, "latency_ms": int}
    """
    global _total_input_tokens, _total_output_tokens, _total_calls, _total_failures

    client = get_client()
    if client is None:
        return None, {"input_tokens": 0, "output_tokens": 0, "latency_ms": 0, "error": "no_client"}

    # Hard budget check — block call if daily budget exceeded
    try:
        from llm.cost_tracker import get_cost_tracker
        if get_cost_tracker().get_budget_used_pct() >= 1.0:
            logger.warning("[LLM] BUDGET EXCEEDED — blocking API call")
            return None, {"input_tokens": 0, "output_tokens": 0, "latency_ms": 0, "error": "budget_exceeded"}
    except Exception:
        pass

    usage = {"input_tokens": 0, "output_tokens": 0, "latency_ms": 0}

    for attempt in range(max_retries + 1):
        try:
            start = time.monotonic()
            _total_calls += 1

            # Use Anthropic prompt caching for system prompts.
            # System prompts are reused across calls — caching saves ~90% on
            # input tokens after the first call with the same prompt.
            system_content = [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ]

            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_content,
                messages=[{"role": "user", "content": snapshot_json}],
                timeout=timeout,
            )

            elapsed_ms = int((time.monotonic() - start) * 1000)

            # Extract text
            text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text += block.text

            # Detect truncation (stop_reason == "max_tokens" means output was cut off)
            stop_reason = getattr(response, "stop_reason", None)
            if stop_reason == "max_tokens":
                logger.warning(
                    f"[LLM] Response truncated at {max_tokens} tokens — "
                    f"JSON likely incomplete. Consider increasing max_tokens."
                )

            # Track usage (including cache hits)
            in_tok = getattr(response.usage, "input_tokens", 0)
            out_tok = getattr(response.usage, "output_tokens", 0)
            cache_read = getattr(response.usage, "cache_read_input_tokens", 0)
            cache_create = getattr(response.usage, "cache_creation_input_tokens", 0)
            _total_input_tokens += in_tok
            _total_output_tokens += out_tok

            usage = {
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "latency_ms": elapsed_ms,
                "cache_read_tokens": cache_read,
                "cache_create_tokens": cache_create,
            }

            # Track cost for EVERY call — prevents undercounting
            try:
                from llm.cost_tracker import get_cost_tracker
                get_cost_tracker().record_call(in_tok, out_tok, model)
            except Exception:
                pass

            logger.info(
                f"[LLM] Call OK: {in_tok} in / {out_tok} out / {elapsed_ms}ms "
                f"(cumulative: {_total_input_tokens} in / {_total_output_tokens} out / {_total_calls} calls)"
            )

            return text.strip(), usage

        except Exception as e:
            _total_failures += 1
            wait = 2 ** attempt

            # Classify error type for better diagnostics
            err_type = type(e).__name__
            err_msg = str(e)
            error_category = "unknown"
            try:
                import anthropic
                if isinstance(e, anthropic.AuthenticationError):
                    error_category = "auth"
                    logger.error(
                        f"[LLM] AUTHENTICATION FAILED: Check ANTHROPIC_API_KEY is valid. {err_msg}"
                    )
                elif isinstance(e, anthropic.RateLimitError):
                    error_category = "rate_limit"
                    wait = max(wait, 10)  # Back off more on rate limits
                    logger.warning(
                        f"[LLM] Rate limited (attempt {attempt + 1}/{max_retries + 1}), "
                        f"backing off {wait}s"
                    )
                elif isinstance(e, anthropic.APITimeoutError):
                    error_category = "timeout"
                    logger.warning(
                        f"[LLM] Timeout after {timeout}s (attempt {attempt + 1}/{max_retries + 1})"
                    )
                elif isinstance(e, anthropic.NotFoundError):
                    error_category = "model_access"
                    logger.error(
                        f"[LLM] Model not found or no access: {model}. {err_msg}"
                    )
                elif isinstance(e, anthropic.APIStatusError):
                    error_category = f"api_status_{getattr(e, 'status_code', 'unknown')}"
                    logger.warning(
                        f"[LLM] API error {getattr(e, 'status_code', '?')} "
                        f"(attempt {attempt + 1}/{max_retries + 1}): {err_msg}"
                    )
                else:
                    logger.warning(
                        f"[LLM] Call failed ({err_type}, attempt {attempt + 1}/{max_retries + 1}): {err_msg}"
                    )
            except ImportError:
                logger.warning(
                    f"[LLM] Call failed ({err_type}, attempt {attempt + 1}/{max_retries + 1}): {err_msg}"
                )

            if attempt < max_retries:
                time.sleep(wait)

    usage["error"] = f"max_retries_exceeded:{error_category}"
    logger.warning(
        f"[LLM] All {max_retries + 1} attempts failed (last error: {error_category})"
    )
    return None, usage


def get_usage_stats() -> dict:
    """Return cumulative usage stats for monitoring."""
    return {
        "total_input_tokens": _total_input_tokens,
        "total_output_tokens": _total_output_tokens,
        "total_calls": _total_calls,
        "total_failures": _total_failures,
        "estimated_cost_usd": round(
            _total_input_tokens * 0.80 / 1_000_000
            + _total_output_tokens * 4.0 / 1_000_000,
            4,
        ),  # Uses Haiku pricing since most calls are Haiku
    }
