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
    max_budget_usd: float = 1.00,  # 2026-05-30: was 0.10. Sonnet/Opus calls cost $0.10-0.30 each; sub pays anyway.
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

    # Build cmd — keep it short. Windows has an 8191-char argv limit; agent system
    # prompts can be 7000+ chars, so we embed the system prompt in stdin instead
    # of passing it via --append-system-prompt.
    cmd = [CLAUDE_BIN, "--print",
           "--output-format", "json",
           "--model", model,
           "--max-budget-usd", str(max_budget_usd),
           "--no-session-persistence"]

    # Embed system prompt in stdin (avoids Windows 8191-char cmd-line limit)
    if system_prompt:
        combined_input = f"<system>\n{system_prompt}\n</system>\n\n{user_prompt}"
    else:
        combined_input = user_prompt

    if json_schema:
        cmd.extend(["--json-schema", json.dumps(json_schema)])
    if not allow_tools:
        cmd.extend(["--tools", ""])

    # 2026-06-02 laptop-claude fix (cherry-picked): On Windows, claude.cmd spawns
    # Node.js as a grandchild. subprocess.run() timeout killing cmd.exe leaves Node
    # holding the pipe handles open -- communicate() then blocks forever (6h+ observed,
    # which explains the multi-hour quota windows we kept hitting). Fix: Popen +
    # CREATE_NEW_PROCESS_GROUP + taskkill /F /T on timeout to kill the whole tree.
    # Adapted to keep desktop's combined_input (system_prompt embedded in stdin)
    # approach rather than laptop's --system-prompt-file.
    _win = os.name == "nt"
    _popen_kwargs: dict = dict(
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        encoding="utf-8",
        errors="replace",
    )
    if _win:
        _popen_kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | 0x08000000  # CREATE_NO_WINDOW
        )

    start = time.time()
    proc = None
    try:
        proc = subprocess.Popen(cmd, **_popen_kwargs)
        stdout_data, stderr_data = proc.communicate(input=combined_input, timeout=timeout)
        latency = time.time() - start

        class _Result:
            def __init__(self, rc, out, err):
                self.returncode, self.stdout, self.stderr = rc, out, err

        result = _Result(proc.returncode, stdout_data, stderr_data)
    except subprocess.TimeoutExpired:
        if proc is not None:
            if _win:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                )
            else:
                proc.kill()
            try:
                proc.communicate(timeout=5)
            except Exception:
                pass
        return CliResponse(ok=False, error=f"timeout after {timeout}s",
                           latency_s=time.time() - start, model=model)
    except Exception as e:
        if proc is not None:
            try:
                proc.kill()
                proc.communicate(timeout=3)
            except Exception:
                pass
        return CliResponse(ok=False, error=f"subprocess error: {e}",
                           latency_s=time.time() - start, model=model)

    if result.returncode != 0:
        return CliResponse(
            ok=False,
            error=f"exit {result.returncode}: {result.stderr[:500]}",
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
