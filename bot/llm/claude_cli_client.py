"""Claude CLI Client — run LLM agents through `claude -p` instead of the Anthropic API.

This lets WAGMI's agent suite run on the user's Claude Code subscription
(no per-token billing) and gain tool-access capabilities the Anthropic
API doesn't provide.

Key features:
- Subprocess-based: invokes `claude --print --output-format json ...`
- JSON-schema output validation (Claude CLI handles it natively)
- Model selection: haiku/sonnet/opus
- Safety budget per call (--max-budget-usd)
- Tools disabled by default (pure reasoning calls)
- Fallback: returns None on failure (caller falls back to heuristics)
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger("bot.llm.claude_cli")


@dataclass
class CliResponse:
    ok: bool
    text: str = ""
    parsed: Optional[Dict[str, Any]] = None
    latency_s: float = 0.0
    model: str = ""
    error: str = ""
    cost_usd: float = 0.0


def _claude_path() -> Optional[str]:
    """Locate the claude CLI binary."""
    path = shutil.which("claude")
    if path:
        return path
    candidates = [
        os.path.expanduser("~/AppData/Roaming/npm/claude"),
        os.path.expanduser("~/AppData/Roaming/npm/claude.cmd"),
        "/usr/local/bin/claude",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


CLAUDE_BIN = _claude_path()


def call_agent(
    user_prompt: str,
    system_prompt: str = "",
    model: str = "haiku",
    json_schema: Optional[Dict[str, Any]] = None,
    max_budget_usd: float = 0.10,
    timeout: int = 90,
    allow_tools: bool = False,
    cwd: Optional[str] = None,
) -> CliResponse:
    """Invoke Claude CLI in non-interactive mode.

    Args:
        user_prompt: the main prompt content
        system_prompt: system/role prompt (goes to --system-prompt)
        model: haiku / sonnet / opus (alias)
        json_schema: optional JSON-schema that output must match
        max_budget_usd: safety cap per call
        timeout: seconds before subprocess is killed
        allow_tools: if False, disables all tools (pure reasoning)
        cwd: working directory for the subprocess

    Returns:
        CliResponse with ok/text/parsed/latency/error fields.
    """
    if CLAUDE_BIN is None:
        return CliResponse(ok=False, error="claude CLI not found in PATH")

    cmd = [CLAUDE_BIN, "--print",
           "--output-format", "json",
           "--model", model,
           "--max-budget-usd", str(max_budget_usd),
           "--no-session-persistence",
           "--dangerously-skip-permissions"]

    if json_schema:
        cmd.extend(["--json-schema", json.dumps(json_schema)])
    if not allow_tools:
        cmd.extend(["--tools", ""])

    # Pass system prompt via --system-prompt flag (cheaper: uses only the base
    # Claude Code context, not the full project context). Falls back to a temp
    # file for very long prompts to stay within Windows 8191-char cmd limit.
    # NOTE: --system-prompt-file loads the full project context (~39K tokens at
    # $0.11/Sonnet call), blowing through the $0.10 per-call budget. Using
    # --system-prompt keeps costs under $0.03/Sonnet call.
    _CMDLINE_SAFE_LIMIT = 6500  # conservative threshold for inline system prompt
    tmp_file = None
    try:
        if system_prompt:
            if len(system_prompt) <= _CMDLINE_SAFE_LIMIT:
                cmd.extend(["--system-prompt", system_prompt])
            else:
                # Long prompt: write to temp file. Increase budget so the extra
                # project context tokens don't blow the per-call limit.
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".txt", delete=False, encoding="utf-8"
                ) as f:
                    f.write(system_prompt)
                    tmp_file = f.name
                cmd.extend(["--system-prompt-file", tmp_file])
                # Bump budget: file mode loads full project context (~39K tokens)
                for idx, arg in enumerate(cmd):
                    if arg == "--max-budget-usd" and idx + 1 < len(cmd):
                        cmd[idx + 1] = str(max(float(cmd[idx + 1]), 0.50))
                        break

        start = time.time()
        try:
            result = subprocess.run(
                cmd, input=user_prompt, capture_output=True, text=True,
                timeout=timeout, cwd=cwd, encoding="utf-8", errors="replace",
            )
            latency = time.time() - start
        except subprocess.TimeoutExpired:
            return CliResponse(ok=False, error=f"timeout after {timeout}s",
                               latency_s=time.time() - start, model=model)
        except Exception as e:
            return CliResponse(ok=False, error=f"subprocess error: {e}",
                               latency_s=time.time() - start, model=model)
    finally:
        if tmp_file:
            try:
                os.unlink(tmp_file)
            except Exception:
                pass

    if result.returncode != 0:
        # Include stdout snippet — CLI sometimes writes error details there (JSON envelope)
        _err_detail = result.stderr[:300] or result.stdout[:300]
        return CliResponse(
            ok=False,
            error=f"exit {result.returncode}: {_err_detail}",
            latency_s=latency,
            model=model,
        )

    # Parse the outer JSON envelope (claude --output-format json)
    # Envelope format: {"type": "result", "result": "text content", "total_cost_usd": ..., ...}
    raw = result.stdout.strip()
    envelope: Dict[str, Any] = {}
    try:
        envelope = json.loads(raw)
    except Exception:
        # Fallback: treat raw as the text directly
        return CliResponse(ok=True, text=raw, latency_s=latency, model=model)

    text = envelope.get("result", "") or envelope.get("text", "") or ""
    cost = float(envelope.get("total_cost_usd", 0) or 0)
    parsed = _extract_json(text)
    return CliResponse(
        ok=True, text=text, parsed=parsed,
        latency_s=latency, model=model, cost_usd=cost,
    )


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Tolerant JSON extractor: strips markdown, finds first balanced {...}."""
    if not text:
        return None
    # Try straight parse first
    s = text.strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    # Strip markdown code fences
    if s.startswith("```"):
        lines = s.split("\n")
        s = "\n".join(lines[1:])
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
        try:
            return json.loads(s.strip())
        except Exception:
            pass
    # Find first balanced {...} in text
    depth = 0
    start = -1
    for i, ch in enumerate(s):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                candidate = s[start:i + 1]
                try:
                    return json.loads(candidate)
                except Exception:
                    pass
    return None


def available() -> bool:
    """Is the Claude CLI usable right now?"""
    return CLAUDE_BIN is not None


# ------- Convenience agent wrappers (mirror the bot's current agent roles) -------

REGIME_SYSTEM = """You are the WAGMI Regime Agent. Classify the market regime.

CRITICAL: Respond with ONE JSON object on a single response. No prose before or after. No markdown code fences. Start with { and end with }. Your entire response is the JSON.

Schema:
{"regime": "trending_bull"|"trending_bear"|"range"|"high_volatility"|"low_liquidity"|"news_dislocation"|"unknown", "confidence": 0-100, "bias": "bullish"|"bearish"|"neutral", "vol_band": "low"|"medium"|"high", "narrative": "<=200 chars"}"""

REGIME_SCHEMA = {
    "type": "object",
    "properties": {
        "regime": {"type": "string", "enum": ["trending_bull", "trending_bear", "range", "high_volatility", "low_liquidity", "news_dislocation", "unknown"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 100},
        "bias": {"type": "string", "enum": ["bullish", "bearish", "neutral"]},
        "vol_band": {"type": "string", "enum": ["low", "medium", "high"]},
        "narrative": {"type": "string", "maxLength": 200},
    },
    "required": ["regime", "confidence", "bias", "vol_band", "narrative"],
}

TRADE_SYSTEM = """You are the WAGMI Trade Agent. Form a directional thesis and decide go/skip/flip.

CRITICAL: Respond with ONE JSON object, no prose, no markdown fences. Start { end }.

Schema:
{"action": "go"|"skip"|"flip", "side": "BUY"|"SELL"|"NONE", "confidence": 0-100, "thesis": "<=300 chars", "entry_low": number, "entry_high": number, "stop": number, "target": number, "confluence": ["factor",...]}"""

TRADE_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["go", "skip", "flip"]},
        "side": {"type": "string", "enum": ["BUY", "SELL", "NONE"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 100},
        "thesis": {"type": "string", "maxLength": 300},
        "entry_low": {"type": "number"},
        "entry_high": {"type": "number"},
        "stop": {"type": "number"},
        "target": {"type": "number"},
        "confluence": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["action", "side", "confidence", "thesis"],
}

CRITIC_SYSTEM = """You are the WAGMI Critic Agent. Stress-test the thesis. If veto, provide counter-thesis.

CRITICAL: Respond with ONE JSON object, no prose, no markdown fences. Start { end }.

Schema:
{"vote": "pass"|"veto"|"reduce"|"counter", "reason": "<=300 chars", "counter_thesis": "<=300 chars or empty", "risk_flags": ["flag",...]}"""

CRITIC_SCHEMA = {
    "type": "object",
    "properties": {
        "vote": {"type": "string", "enum": ["pass", "veto", "reduce", "counter"]},
        "reason": {"type": "string", "maxLength": 300},
        "counter_thesis": {"type": "string", "maxLength": 300},
        "risk_flags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["vote", "reason"],
}

RISK_SYSTEM = """You are the WAGMI Risk Agent. Given thesis + equity + exposure, size the position.

CRITICAL: Respond with ONE JSON object, no prose, no markdown fences. Start { end }.

Schema:
{"size_multiplier": 0.0-2.0, "leverage": 1-10, "max_loss_pct": 0.0-5.0, "risk_flags": ["flag",...], "reason": "<=200 chars"}"""

RISK_SCHEMA = {
    "type": "object",
    "properties": {
        "size_multiplier": {"type": "number", "minimum": 0, "maximum": 2},
        "leverage": {"type": "number", "minimum": 1, "maximum": 10},
        "max_loss_pct": {"type": "number", "minimum": 0, "maximum": 5},
        "risk_flags": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string", "maxLength": 200},
    },
    "required": ["size_multiplier", "leverage", "reason"],
}


def regime(data_summary: str, model: str = "sonnet") -> CliResponse:
    """Sonnet is default because it reliably follows the JSON-only constraint;
    Haiku tends to return markdown prose even with strict prompts."""
    return call_agent(data_summary, REGIME_SYSTEM, model=model, json_schema=REGIME_SCHEMA)


def trade(data_summary: str, regime_output: str, model: str = "sonnet") -> CliResponse:
    full = f"REGIME: {regime_output}\n\nDATA:\n{data_summary}"
    return call_agent(full, TRADE_SYSTEM, model=model, json_schema=TRADE_SCHEMA)


def critic(thesis: str, data_summary: str, model: str = "sonnet") -> CliResponse:
    full = f"THESIS: {thesis}\n\nDATA:\n{data_summary}"
    return call_agent(full, CRITIC_SYSTEM, model=model, json_schema=CRITIC_SCHEMA)


def risk(thesis: str, equity: float, positions: int, model: str = "sonnet") -> CliResponse:
    prompt = (f"Thesis: {thesis}\nEquity: ${equity:.2f}\n"
              f"Open positions: {positions}\nMax risk per trade: 8%")
    return call_agent(prompt, RISK_SYSTEM, model=model, json_schema=RISK_SCHEMA)


if __name__ == "__main__":
    # Quick smoke test
    print(f"Claude CLI available: {available()}")
    print(f"Binary: {CLAUDE_BIN}")
    if available():
        resp = call_agent(
            "BTC at $75,888. Daily trend UP, RSI 61, above EMA20 by 3.8%. What regime?",
            REGIME_SYSTEM,
            model="haiku",
        )
        print(f"OK: {resp.ok} | latency: {resp.latency_s:.2f}s | cost: ${resp.cost_usd:.4f}")
        print(f"Text:\n{resp.text[:400]}")
        print(f"Parsed: {resp.parsed}")
