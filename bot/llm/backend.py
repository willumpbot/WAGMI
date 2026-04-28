"""LLMBackend ABC - Abstraction layer for LLM backends (CLI, API, Ollama, local)

This module provides a unified interface for different LLM backends, enabling:
- Fail-loud error handling (no silent fallbacks)
- Per-backend cost tracking
- Switchable backends without code changes
- Automatic fallback chains
- Latency monitoring per agent
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Literal
from datetime import datetime
import json
import time
import logging

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Unified response from any LLM backend."""
    ok: bool
    text: str
    parsed: Optional[Dict[str, Any]] = None
    cost_usd: float = 0.0
    latency_s: float = 0.0
    model: str = ""
    backend_name: str = ""
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class BackendStats:
    """Track stats per backend."""
    total_calls: int = 0
    total_failures: int = 0
    total_parse_failures: int = 0
    total_cost_usd: float = 0.0
    mean_latency_s: float = 0.0
    last_failure_time: Optional[datetime] = None
    last_failure_msg: Optional[str] = None


class LLMBackend(ABC):
    """Abstract base for all LLM backends."""

    def __init__(self, name: str, model: str = ""):
        self.name = name
        self.model = model
        self.stats = BackendStats()
        self.failures = []  # Track recent failures for fallback logic
        self.max_tracked_failures = 10

    @abstractmethod
    def call(
        self,
        prompt: str,
        system: str = "",
        json_schema: Optional[Dict] = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        timeout_s: float = 60.0,
    ) -> LLMResponse:
        """Make an LLM call. Must implement fail-loud behavior."""
        pass

    def _record_success(self, cost: float, latency: float):
        """Record successful call."""
        self.stats.total_calls += 1
        self.stats.total_cost_usd += cost
        self.stats.mean_latency_s = (
            (self.stats.mean_latency_s * (self.stats.total_calls - 1) + latency)
            / self.stats.total_calls
        )

    def _record_failure(self, error_msg: str):
        """Record failure. Raise if too many consecutive failures."""
        self.stats.total_calls += 1
        self.stats.total_failures += 1
        self.stats.last_failure_time = datetime.utcnow()
        self.stats.last_failure_msg = error_msg

        self.failures.append({
            "timestamp": datetime.utcnow(),
            "error": error_msg
        })
        if len(self.failures) > self.max_tracked_failures:
            self.failures = self.failures[-self.max_tracked_failures:]

        logger.error(
            f"[{self.name}] LLM call failed: {error_msg}",
            extra={"backend": self.name, "model": self.model}
        )

        # Log to audit trail for observability
        try:
            from llm.audit_logger import audit_backend_failure
            audit_backend_failure(
                backend_name=self.name,
                error_msg=error_msg,
                call_count=self.stats.total_failures,
            )
        except Exception:
            pass  # Don't block on audit logging failure

    def get_stats(self) -> Dict[str, Any]:
        """Return current stats."""
        failure_rate = 0.0
        if self.stats.total_calls > 0:
            failure_rate = self.stats.total_failures / self.stats.total_calls

        return {
            "name": self.name,
            "model": self.model,
            "total_calls": self.stats.total_calls,
            "total_failures": self.stats.total_failures,
            "failure_rate": failure_rate,
            "total_cost_usd": self.stats.total_cost_usd,
            "mean_latency_s": self.stats.mean_latency_s,
            "last_failure": self.stats.last_failure_msg,
        }


class CliBackend(LLMBackend):
    """Claude CLI backend (Subscription, $0/call, local).

    Routes calls through bot/llm/claude_cli_client.py for $0/call access
    to Claude via the local Max subscription. No API key required.
    """

    def __init__(self):
        super().__init__("cli", "claude-sonnet-4-6")

    def call(
        self,
        prompt: str,
        system: str = "",
        json_schema: Optional[Dict] = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        timeout_s: float = 60.0,
    ) -> LLMResponse:
        """Call via Claude CLI. Imports and uses actual CLI client."""
        from .claude_cli_client import call_agent

        start = time.time()
        try:
            response = call_agent(
                prompt,
                system,
                model=self.model,
                json_schema=json_schema,
                temperature=temperature,
                timeout=timeout_s,
            )

            latency = time.time() - start
            self._record_success(response.cost_usd, latency)

            return LLMResponse(
                ok=response.ok,
                text=response.text,
                parsed=response.parsed,
                cost_usd=response.cost_usd,
                latency_s=latency,
                model=self.model,
                backend_name="cli",
            )
        except Exception as e:
            latency = time.time() - start
            error_msg = f"{type(e).__name__}: {str(e)[:200]}"
            self._record_failure(error_msg)

            return LLMResponse(
                ok=False,
                text="",
                parsed=None,
                cost_usd=0.0,
                latency_s=latency,
                model=self.model,
                backend_name="cli",
                error=error_msg,
            )


class ApiBackend(LLMBackend):
    """Anthropic API backend (requires API key, $$$)."""

    def __init__(self, api_key: Optional[str] = None):
        super().__init__("api", "claude-sonnet-4-6")
        self.api_key = api_key

    def call(
        self,
        prompt: str,
        system: str = "",
        json_schema: Optional[Dict] = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        timeout_s: float = 60.0,
    ) -> LLMResponse:
        """Call via Anthropic API. Deferred implementation."""
        # This is a fallback for when CLI is unavailable
        # Implement actual API call when needed
        return LLMResponse(
            ok=False,
            text="API backend not yet implemented",
            error="ApiBackend stub",
            backend_name="api",
        )


class OllamaBackend(LLMBackend):
    """Ollama backend (local models, zero cost, no rate limits)."""

    def __init__(self, base_url: str = "http://localhost:11434"):
        super().__init__("ollama", "qwen2.5:32b-instruct")
        self.base_url = base_url

    def call(
        self,
        prompt: str,
        system: str = "",
        json_schema: Optional[Dict] = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        timeout_s: float = 60.0,
    ) -> LLMResponse:
        """Call via Ollama. Deferred for Week 6."""
        return LLMResponse(
            ok=False,
            text="Ollama backend deferred to Week 6",
            error="OllamaBackend stub",
            backend_name="ollama",
        )


class BackendRouter:
    """Route LLM calls through primary + fallback chain."""

    def __init__(self, primary: LLMBackend, fallbacks: Optional[list] = None):
        self.primary = primary
        self.fallbacks = fallbacks or []
        self.all_backends = [primary] + self.fallbacks

    def call(
        self,
        prompt: str,
        system: str = "",
        json_schema: Optional[Dict] = None,
        agent_name: str = "unknown",
        **kwargs
    ) -> LLMResponse:
        """Route with automatic fallback on failure."""

        for backend in self.all_backends:
            try:
                response = backend.call(
                    prompt,
                    system=system,
                    json_schema=json_schema,
                    **kwargs
                )

                if response.ok:
                    logger.info(
                        f"[ROUTER] {agent_name} via {backend.name}",
                        extra={"agent": agent_name, "backend": backend.name}
                    )
                    return response
                else:
                    logger.warning(
                        f"[ROUTER] {agent_name} failed on {backend.name}: {response.error}",
                        extra={"agent": agent_name, "backend": backend.name, "error": response.error}
                    )
                    continue
            except Exception as e:
                logger.error(
                    f"[ROUTER] {agent_name} exception on {backend.name}: {e}",
                    extra={"agent": agent_name, "backend": backend.name}
                )
                continue

        # All backends failed
        logger.critical(
            f"[ROUTER] {agent_name} exhausted all backends",
            extra={"agent": agent_name}
        )
        return LLMResponse(
            ok=False,
            text="All LLM backends failed",
            error="No backends available",
            backend_name="router",
        )

    def get_all_stats(self) -> Dict[str, Any]:
        """Get stats from all backends."""
        return {
            backend.name: backend.get_stats()
            for backend in self.all_backends
        }


# Module-level default router (will be initialized in coordinator)
_default_router: Optional[BackendRouter] = None


def get_default_router() -> BackendRouter:
    """Get or create default router."""
    global _default_router
    if _default_router is None:
        cli = CliBackend()
        api = ApiBackend()
        _default_router = BackendRouter(primary=cli, fallbacks=[api])
    return _default_router
