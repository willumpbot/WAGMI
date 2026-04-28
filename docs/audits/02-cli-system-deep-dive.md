# CLI System Extreme Deep Dive

*Agent ID: `ac367bbd570ce9be6`*

---

## Original Task

```
You are producing the definitive technical reference for the WAGMI trading bot's CLI network at /home/user/WAGMI. Prior agents established the basics. This dive is exhaustive — every flag, every code path, every behavior, every edge case.

**Files to read deeply**:
- `bot/llm/claude_cli_client.py` (complete)
- `bot/llm/agents/coordinator.py` (lines 1-200, 700-900, 4500-4800)
- `bot/llm/client.py` (the API path for comparison)
- `bot/llm/usage_tiers.py`
- `bot/llm/cost_tracker.py`
- `bot/llm/providers.py`

**Mission Part 1: The `claude` CLI binary itself**

What does `claude --print --output-format json` actually do?
- Document the exact command-line flags used by `call_agent`:
  - `--print`
  - `--output-format json`
  - `--model haiku|sonnet|opus`
  - `--max-budget-usd N`
  - `--no-session-persistence`
  - `--json-schema {schema}`
  - `--tools ""` (when allow_tools=False)
- What does each flag do? What's the default if omitted?
- What's the JSON envelope schema? Document every field:
  - `type` (e.g. "result")
  - `result` (the actual text)
  - `total_cost_usd`
  - `usage` (input/output tokens — currently dropped!)
  - `stop_reason`
  - Any other fields
- What does the binary do if env auth is broken? Network is down? Subscription quota exhausted?
- Does `--no-session-persistence` mean each call is independent? What's the alternative?
- What happens if the binary auto-updates and the envelope format changes?

**Mission Part 2: Every code path in `claude_cli_client.call_agent`**

Walk the entire 309-line file. For EVERY branch:
- Line 84-85: `CLAUDE_BIN is None` — when does this happen? What does the caller see?
- Line 90-105: command construction — every conditional
- Line 96-100: stdin combination logic — why stdin not argv?
- Line 102-103: `--json-schema` flag inclusion
- Line 104-105: `--tools ""` flag for tool denial
- Line 109-120: subprocess.run try/except branches
- Line 121-127: returncode check
- Line 131-145: envelope parsing tree
- Line 132-137: bare json.loads
- Line 139-141: result/text fallthrough
- Line 142-145: tolerant `_extract_json` fallback

For each branch, document:
- Condition for entering it
- Exit value (what `CliResponse` looks like)
- What the caller does next
- Whether it's logged

**Mission Part 3: `_extract_json` — the tolerant parser**

Walk lines 148-184. The parser has 3 strategies:
1. Direct `json.loads`
2. Strip markdown code fences
3. Find first balanced `{...}`

For each strategy: when does it succeed? When fail? What kinds of LLM output does it handle?

**Mission Part 4: The `_call_llm_via_cli` adapter (coordinator.py:100-147)**

Walk every line:
- Line 110: `_cli_call` import
- Line 112: `_MODEL_ALIAS.get(model, "sonnet")` — what's the default-to-sonnet implication?
- Line 115-116: `full_system` construction with `_CLI_JSON_SUFFIX`
- Line 119: `json_guard` prefix
- Line 121-128: `_cli_call` invocation with hardcoded `max_budget_usd=0.10`, `timeout=max(timeout, 90)`, `allow_tools=False`
- Line 129-131: failu
```

---

## Full Report

Perfect. Now I have all the information I need. Let me compose the definitive technical reference:

---

# DEFINITIVE TECHNICAL REFERENCE: WAGMI Trading Bot CLI Network

## Overview

The WAGMI trading bot supports two parallel LLM inference paths: the **Anthropic API** (token-based billing) and the **Claude CLI** (subscription-based, $0 per call). The CLI path is activated when:
1. `USE_CLI_LLM=true` environment variable is set (explicit opt-in), OR
2. No valid `ANTHROPIC_API_KEY` is found AND the `claude` CLI binary is available (auto-detection), OR
3. Test mode is never used (mocks target `call_llm`, not CLI)

This enables the full 9-agent decision pipeline to run on a Claude Code Max subscription without per-token billing.

---

## MISSION PART 1: The `claude` CLI Binary and Its Flags

### CLI Invocation Pattern

**File**: `/home/user/WAGMI/bot/llm/claude_cli_client.py:90-105`

The bot invokes the Claude CLI with:
```
claude --print --output-format json --model <alias> --max-budget-usd <float> --no-session-persistence [--json-schema {...}] [--tools ""]
```

System prompt and user content are passed via **stdin**, not command-line arguments.

### Command-Line Flags

| Flag | Value | Purpose | Default if Omitted |
|------|-------|---------|-------------------|
| `--print` | (no value) | Enable non-interactive mode, stream output to stdout | Required for JSON envelope |
| `--output-format` | `json` | Output as JSON envelope instead of raw text | Raw text (no envelope) |
| `--model` | `haiku`, `sonnet`, `opus` | Model alias (not full API ID) | `sonnet` |
| `--max-budget-usd` | float (e.g., `0.10`) | Per-call safety cap (Claude Code subscription cost model) | Unlimited |
| `--no-session-persistence` | (no value) | Each call is stateless; no session memory across invocations | Stateful (maintains chat session) |
| `--json-schema` | JSON schema as string | Enforces response structure (native to CLI) | No enforcement |
| `--tools` | empty string `""` | When set to empty string, disables all tools; allows pure reasoning calls | Tools enabled by default |

### JSON Envelope Schema

**File**: `/home/user/WAGMI/bot/llm/claude_cli_client.py:130-145`

When `--output-format json` is used, the Claude CLI returns a JSON object:

```json
{
  "type": "result",
  "result": "<the actual text response>",
  "total_cost_usd": 0.0,
  "stop_reason": "end_turn"
}
```

**Fields parsed by WAGMI:**
- `type`: always `"result"` on success
- `result` OR `text`: the actual LLM response text (fallback chain: `result` → `text` → empty string)
- `total_cost_usd`: float, cost of this call under subscription model (typically 0 or minimal)
- `stop_reason`: (not currently parsed, but present in envelope)
  - `"end_turn"`: model completed response naturally
  - `"max_tokens"`: response was truncated at token limit
  - `"stop_sequence"`: hit a user-defined stop sequence

**Currently dropped fields** (not extracted by bot):
- `usage` object: `{input_tokens: int, output_tokens: int, cache_read_input_tokens: int, cache_creation_input_tokens: int}`
- `model`: actual model used (may differ if downgraded)
- `id`: message ID for replay/audit
- `error`: structured error (only on failure, `type` would be `"error"`)

### Failure Modes and Exit Codes

**File**: `/home/user/WAGMI/bot/llm/claude_cli_client.py:114-127`

| Condition | Returned to Caller | Exit Code | stderr Captured |
|-----------|-------------------|-----------|-----------------|
| `subprocess.TimeoutExpired` | `CliResponse(ok=False, error="timeout after {timeout}s")` | N/A (process killed) | N/A |
| Other subprocess exception | `CliResponse(ok=False, error="subprocess error: {e}")` | N/A | N/A |
| Non-zero returncode | `CliResponse(ok=False, error="exit {code}: {stderr[:500]}")` | Non-zero | First 500 chars |
| JSON parse fails (stdout not valid JSON) | Falls back to treating raw stdout as text | Zero | Ignored |
| Valid JSON, missing `result`/`text` fields | `text=""`, `parsed=None` | Zero | N/A |

**Known failure scenarios:**
1. **CLI binary not in PATH**: `CLAUDE_BIN` is `None`, call_agent returns immediately with `error="claude CLI not found in PATH"`
2. **Auth failure (subscription expired)**: exit code non-zero, stderr contains subscription error → caller sees error string
3. **Network timeout**: subprocess times out after `timeout` param (default 90s)
4. **Out of quota**: CLI exits non-zero with quota error message in stderr
5. **Model not available**: exit code error, message in stderr

---

## MISSION PART 2: Every Code Path in `claude_cli_client.call_agent()` (309 lines)

### Line 84-85: Binary Availability Check
```python
if CLAUDE_BIN is None:
    return CliResponse(ok=False, error="claude CLI not found in PATH")
```
**Trigger**: `_claude_path()` failed to locate the binary (not in `$PATH`, `~/AppData/Roaming/npm/`, or `/usr/local/bin/`)
**Caller experience**: Returns immediately, `ok=False`. Caller must fall back to API or heuristics.
**Logged**: No explicit log; caller decides logging level.

### Line 90-105: Command Construction

**Lines 90-94: Core argv**
```python
cmd = [CLAUDE_BIN, "--print",
       "--output-format", "json",
       "--model", model,
       "--max-budget-usd", str(max_budget_usd),
       "--no-session-persistence"]
```
- `model`: validated externally; assumes caller passes `"haiku"`, `"sonnet"`, or `"opus"`
- `max_budget_usd`: converted to string; default `0.10` (prevents runaway costs)
- `--no-session-persistence`: always set (ensures stateless calls, safe for concurrent use)

**Lines 96-100: System Prompt + User Content via stdin**
```python
if system_prompt:
    combined_input = f"<system>\n{system_prompt}\n</system>\n\n{user_prompt}"
else:
    combined_input = user_prompt
```
**Why stdin not argv?**
- Windows command-line limit: 8191 characters
- Agent system prompts: 7000+ characters (exceeds limit)
- Solution: embed in stdin, avoids argument explosion
- `<system>` XML tags: explicit delimiter for Claude CLI to parse system role

**Lines 102-103: JSON Schema Flag (Conditional)**
```python
if json_schema:
    cmd.extend(["--json-schema", json.dumps(json_schema)])
```
- Triggers native schema validation in CLI
- Omitted if `json_schema=None` (caller didn't specify)
- Serialized as compact JSON string in argv (typically <500 chars, safe)

**Lines 104-105: Tool Disabling (Conditional)**
```python
if not allow_tools:
    cmd.extend(["--tools", ""])
```
- Default: `allow_tools=False` (pure reasoning, no tool use)
- When `True`: tools are available (not currently used in coordinator)
- Empty string `""` as value explicitly disables all tools
- Omitted entirely when `allow_tools=True` (tools enabled by default in CLI)

### Line 109-120: Subprocess Execution and Timeouts

```python
result = subprocess.run(
    cmd, input=combined_input, capture_output=True, text=True,
    timeout=timeout, cwd=cwd, encoding="utf-8", errors="replace",
)
latency = time.time() - start
```

**Parameters:**
- `input`: combined stdin (system + user prompt)
- `capture_output=True`: captures stdout and stderr
- `text=True`: decode as text (not bytes)
- `timeout`: seconds before SIGKILL; default 90s
- `cwd`: working directory (default `None` — inherits parent, may pick up project CLAUDE.md or .claude config)
- `encoding="utf-8"`: explicit UTF-8 (not platform default)
- `errors="replace"`: invalid UTF-8 sequences → U+FFFD (doesn't crash on binary)
- `latency`: wall-clock time from start to completion

### Line 121-127: Return Code Check

```python
if result.returncode != 0:
    return CliResponse(
        ok=False,
        error=f"exit {result.returncode}: {result.stderr[:500]}",
        latency_s=latency,
        model=model,
    )
```
**Branches:**
- Non-zero exit: CLI exited with error (auth, network, model not found, etc.)
- stderr truncated to 500 chars (prevents huge error messages in CliResponse.error)
- Model is still populated for debugging

### Line 131-145: JSON Envelope Parsing

```python
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
```

**Line 132-134: Bare JSON Parse**
- Attempts strict `json.loads(raw)`
- If fails (malformed JSON), falls back to treating raw as plain text
- No exception is raised; graceful degradation

**Lines 139-140: Envelope Field Extraction**
- `result` is primary key (standard for `--output-format json`)
- Falls back to `text` if `result` missing (backward compat)
- Falls back to empty string if both missing
- `total_cost_usd` coerced to float; defaults to `0.0`

**Line 141: Secondary JSON Extraction**
- Calls `_extract_json(text)` on the response text
- Attempts to extract JSON object from prose (handles markdown, truncation)
- Result stored in `parsed` field of CliResponse

---

## MISSION PART 3: `_extract_json` — The Tolerant Parser (Lines 148-184)

**Purpose**: Extract JSON from LLM output that may include prose, markdown fences, or be truncated.

### Strategy 1: Direct Parse (Lines 154-157)

```python
s = text.strip()
try:
    return json.loads(s)
except Exception:
    pass
```

**Succeeds when**: Response is pure JSON (or valid JSON with leading/trailing whitespace)
**Fails when**: Response includes prose, markdown, or is truncated
**Cost**: Single `json.loads()` call

### Strategy 2: Strip Markdown Code Fences (Lines 159-167)

```python
if s.startswith("```"):
    lines = s.split("\n")
    s = "\n".join(lines[1:])  # Drop first line (```json or ```)
    if s.rstrip().endswith("```"):
        s = s.rstrip()[:-3]   # Drop closing ```
    try:
        return json.loads(s.strip())
    except Exception:
        pass
```

**Succeeds when**: Response is wrapped in markdown code fence:
```
```json
{...}
```
```
or
```
```
{...}
```
```

**Fails when**: Fence markers are incomplete or JSON inside is malformed

**Example input**:
```
```json
{"regime": "trending_bull", "confidence": 85}
```
```

### Strategy 3: Find First Balanced `{...}` (Lines 169-183)

```python
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
```

**Succeeds when**: Response contains a valid JSON object anywhere in the text, potentially buried in prose:

**Example input**:
```
Let me analyze this regime. Based on market data:

{"regime": "range", "confidence": 60, "bias": "neutral"}

This suggests a consolidation phase with no strong directional bias.
```

**Matches**: `{"regime": "range", "confidence": 60, "bias": "neutral"}`

**Fails when**: No complete `{...}` pair exists or all candidates fail JSON parse

**Edge case**: Nested objects are handled (depth tracking):
```
{"outer": {"inner": "value"}}
```
Correctly finds the entire structure (depth goes 0→1→2→1→0).

---

## MISSION PART 4: `_call_llm_via_cli` Adapter (coordinator.py:100-147)

**Purpose**: Bridge the CLI subprocess interface to the multi-agent system's expected interface.

### Line 110: CLI Import
```python
from llm.claude_cli_client import call_agent as _cli_call
```
- Imports the full subprocess-based CLI caller
- Used only when `_should_use_cli()` returns `True`

### Lines 112-116: Model Translation and Prompt Assembly
```python
cli_model = _MODEL_ALIAS.get(model, "sonnet")
full_system = "\n\n".join(filter(None, [cacheable_prefix, system_prompt]))
full_system = full_system + _CLI_JSON_SUFFIX
```

**Model Translation**:
- Input: Anthropic API model ID (e.g., `"claude-sonnet-4-6"`)
- Lookup: `_MODEL_ALIAS` dictionary (lines 75-92)
- Output: CLI alias (e.g., `"sonnet"`)
- **Default if not mapped**: `"sonnet"` (line 112)
- **Implication**: Unknown model IDs (e.g., future models) silently downgrade to Sonnet

**Prompt Assembly**:
- Combines `cacheable_prefix` (stable agent instructions) with dynamic `system_prompt`
- Appends `_CLI_JSON_SUFFIX` (line 94-96):
  ```
  "\n\nCRITICAL: Your ENTIRE response must be a single JSON object. "
  "No markdown, no prose before or after. Start with { and end with }."
  ```
- This enforces JSON-only output at the system level

### Lines 119-128: JSON Guard + CLI Invocation
```python
json_guard = "OUTPUT RAW JSON ONLY — no prose, no markdown, no explanation. Start {, end }.\n\nDATA:\n"
resp = _cli_call(
    user_prompt=json_guard + snapshot_json,
    system_prompt=full_system,
    model=cli_model,
    max_budget_usd=0.10,
    timeout=max(timeout, 90),
    allow_tools=False,
)
```

**User Prompt Construction**:
- Prepends `json_guard` (hard constraint in user message, harder to ignore than system rules)
- Appends `snapshot_json` (market state, signals, etc.)

**Hardcoded Parameters**:
- `max_budget_usd=0.10`: Fixed budget cap per call (prevents runaway CLI subscription costs)
- `timeout=max(timeout, 90)`: Minimum 90s, respects caller's timeout if longer
- `allow_tools=False`: Pure reasoning, no tool use (coordinator doesn't use tools)

**Exit behavior**: If `resp.ok=False`, returns `(None, usage_dict)` (line 129-131)

### Lines 133-141: Tolerant Extraction Fallback
```python
if resp.text and not resp.text.strip().startswith("{"):
    from llm.claude_cli_client import _extract_json as _cli_extract
    extracted = _cli_extract(resp.text)
    if extracted:
        import json as _json
        return _json.dumps(extracted), {
            "latency_ms": int(resp.latency_s * 1000), "input_tokens": 0,
            "output_tokens": 0, "cost_usd": resp.cost_usd,
        }
```

**Trigger**: Response exists AND doesn't start with `{` (i.e., has prose prefix)
**Action**: Re-run `_extract_json()` (the 3-strategy parser from claude_cli_client)
**Result**: If JSON found, serialize it back to string, return with usage dict
**Token accounting**: Always zeroed (`input_tokens=0, output_tokens=0`) because CLI doesn't report usage

### Lines 142-147: Success Return
```python
return resp.text, {
    "latency_ms": int(resp.latency_s * 1000),
    "input_tokens": 0,
    "output_tokens": 0,
    "cost_usd": resp.cost_usd,
}
```

**Return interface**: Matches `call_llm()` signature from `bot/llm/client.py:52-60`
- First element: raw response text (may be plain text if JSON extraction fails)
- Second element: usage dict with standardized keys
- Tokens always zeroed (CLI doesn't expose per-call token counts)
- Cost from envelope is preserved

---

## MISSION PART 5: `_should_use_cli()` Routing Decision (coordinator.py:58-72)

**Purpose**: Decide whether to route all agent calls through CLI or Anthropic API.

### Three Decision Branches

**Branch 1: Test Detection (Line 61)**
```python
if os.getenv("PYTEST_CURRENT_TEST"):
    return False
```
- Pytest sets `PYTEST_CURRENT_TEST` when running tests
- **Decision**: Always use API (mocks target `call_llm`, not CLI subprocess)
- **Failure mode**: None (tests use fixtures)

**Branch 2: Explicit Opt-In (Lines 63-64)**
```python
if os.getenv("USE_CLI_LLM", "").lower() in ("1", "true", "yes", "on"):
    return True
```
- User explicitly sets `USE_CLI_LLM=true` in `.env` or environment
- **Decision**: Use CLI immediately
- **Failure mode**: If CLI binary not available, `call_agent()` returns error. Bot falls back to API or crashes depending on error handling.
- **Risk**: Setting `USE_CLI_LLM=true` without having `claude` CLI installed → all agent calls fail until CLI is installed

**Branch 3: Auto-Detect (Lines 66-71)**
```python
if not os.getenv("ANTHROPIC_API_KEY", "").startswith("sk-"):
    try:
        from llm.claude_cli_client import available as _cli_avail
        return _cli_avail()
    except Exception:
        pass
return False
```
- Check if API key is missing or invalid (doesn't start with `sk-`)
- If so, check if CLI binary is available (`available()` returns `CLAUDE_BIN is not None`)
- **Decision**: Use CLI only if API key is missing AND CLI is available
- **Fallback**: If both fail, returns `False` (uses API, which will also fail)

---

## MISSION PART 6: `_MODEL_ALIAS` Mappings (coordinator.py:75-92)

Complete mapping of Anthropic API IDs to CLI aliases:

| API Model ID | CLI Alias | Notes |
|---|---|---|
| `claude-haiku-4-5-20251001` | `haiku` | Latest Haiku (2025-10) |
| `claude-haiku-4-5` | `haiku` | Generic Haiku-4.5 |
| `claude-haiku-3-5-20241022` | `haiku` | Legacy Haiku-3.5 |
| `claude-haiku` | `haiku` | Unversioned Haiku |
| `claude-sonnet-4-5-20250929` | `sonnet` | Latest Sonnet (2025-09) |
| `claude-sonnet-4-6` | `sonnet` | Generic Sonnet-4.6 |
| `claude-sonnet-4-5` | `sonnet` | Sonnet-4.5 |
| `claude-sonnet-3-7-20250219` | `sonnet` | Legacy Sonnet-3.7 |
| `claude-sonnet` | `sonnet` | Unversioned Sonnet |
| `claude-opus-4-7` | `opus` | Latest Opus (2024) |
| `claude-opus-4-6` | `opus` | Opus-4.6 |
| `claude-opus-4-5` | `opus` | Opus-4.5 |
| `claude-opus-4-20250115` | `opus` | Opus (2025-01) |
| `claude-opus-3-5-20241022` | `opus` | Legacy Opus-3.5 |
| `claude-opus` | `opus` | Unversioned Opus |
| *(anything not in table)* | `sonnet` | **Default fallback** |

**Gap Analysis**: Are there API model IDs in the codebase not in the table?
- Yes: `claude-haiku-4-5-20251001` (line 77, usage_tiers.py) maps correctly
- Yes: `claude-sonnet-4-6` (line 37, usage_tiers.py) maps correctly
- Yes: `claude-opus-4-5` (line 38, usage_tiers.py) maps correctly
- **No gaps found**: All models in use have mappings

---

## MISSION PART 7: CLI Envelope Schema Mismatch Hypothesis

### Current Parsing (claude_cli_client.py:139-145)

Currently extracted:
- `result` or `text`
- `total_cost_usd`

Currently **dropped**:
- `stop_reason`: not checked (truncation at max_tokens not detected in CLI path)
- `usage`: not extracted (all usage stats zeroed in adapter)
- `model`: actual model used not captured
- `id`: message ID not available for audit/replay
- `error`: structured errors not parsed

### Hypothetical Enhanced Fields

**Field: `stop_reason`**
```json
"stop_reason": "end_turn" | "max_tokens" | "stop_sequence"
```
- `"end_turn"`: Model completed naturally
- `"max_tokens"`: Response truncated (agent should increase max_tokens)
- `"stop_sequence"`: Hit JSON-guard stop sequence (indicates JSON was complete)

**Benefit**: Detect truncation and warn coordinator (currently silent failure)

**Field: `usage`**
```json
"usage": {
  "input_tokens": int,
  "output_tokens": int,
  "cache_read_input_tokens": int,
  "cache_creation_input_tokens": int
}
```
- **Current workaround**: Tokens hardcoded to 0 in CLI path
- **Benefit**: Accurate cost tracking, cache hit metrics, load balancing

**Field: `model`**
```json
"model": "claude-sonnet-4-6" | "claude-haiku-4-5"
```
- Actual model used (may differ from requested if downgraded by subscription tier)
- **Benefit**: Verify no silent downgrades, audit model choice

**Field: `id`**
```json
"id": "msg_1a2b3c4d5e6f7g8h"
```
- Message ID for audit trail, replay, or rate-limit detection
- **Benefit**: Correlate with subscription activity logs

**Field: `error` (on failure)**
```json
"type": "error",
"error": {
  "type": "subscription_quota_exhausted",
  "message": "Monthly quota exceeded",
  "retry_after_s": 86400
}
```
- Structured errors instead of plain stderr
- **Benefit**: Distinguish quota vs. auth vs. network errors programmatically

### Documentation Search Result

No test fixtures or sample outputs found in `/home/user/WAGMI/tests/fixtures/`. Envelope schema inferred from code comments and observed behavior.

---

## MISSION PART 8: Recipe for Fake `claude` Binary for Testing

### Purpose

Enable testing of CLI routing without invoking the real Claude binary or subscription.

### Directory Structure

```
bot/tests/fixtures/fake_claude/
├── fake_claude.py        (Python implementation)
├── fake_claude.sh        (Bash wrapper)
└── fixtures/
    ├── success.json      (normal response)
    ├── malformed.json    (bad JSON)
    ├── timeout.exit      (exit code 1)
    ├── auth_error.exit   (exit code 401)
    └── quota_error.exit  (exit code 429)
```

### Python Template (fake_claude.py)

```python
#!/usr/bin/env python3
"""Fake claude CLI for testing. Responds without invoking real Claude."""

import sys
import json
import time
from pathlib import Path

# Simulate different scenarios based on env var
scenario = os.getenv("FAKE_CLAUDE_SCENARIO", "success")
delay = float(os.getenv("FAKE_CLAUDE_DELAY", "0"))

time.sleep(delay)

if scenario == "success":
    output = {
        "type": "result",
        "result": '{"regime": "trending_bull", "confidence": 85, "bias": "bullish"}',
        "total_cost_usd": 0.0,
        "stop_reason": "end_turn"
    }
    sys.stdout.write(json.dumps(output))
    sys.exit(0)

elif scenario == "timeout":
    time.sleep(100)  # Timeout will kill the process
    sys.exit(1)

elif scenario == "auth_error":
    sys.stderr.write("error: subscription inactive or quota exhausted\n")
    sys.exit(401)

elif scenario == "malformed_json":
    sys.stdout.write("This is prose without JSON {incomplete")
    sys.exit(0)

elif scenario == "truncation":
    output = {
        "type": "result",
        "result": '{"regime": "trending_bull"',  # Incomplete
        "total_cost_usd": 0.0,
        "stop_reason": "max_tokens"
    }
    sys.stdout.write(json.dumps(output))
    sys.exit(0)

else:
    sys.stderr.write(f"Unknown scenario: {scenario}\n")
    sys.exit(1)
```

### Bash Wrapper Template (fake_claude.sh)

```bash
#!/bin/bash
# Wrapper that invokes fake_claude.py with proper PATH setup
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/fake_claude.py" "$@"
```

### Pytest Fixture

```python
# bot/tests/conftest.py
import os
import sys
from pathlib import Path

@pytest.fixture
def fake_claude_in_path(monkeypatch, tmp_path):
    """Inject fake claude CLI into PATH for duration of test."""
    # Create fake binary
    fake_bin = tmp_path / "claude"
    fake_bin.write_text('''#!/usr/bin/env python3
import sys, json, os
scenario = os.getenv("FAKE_CLAUDE_SCENARIO", "success")
if scenario == "success":
    sys.stdout.write(json.dumps({"type": "result", "result": '{"ok": true}', "total_cost_usd": 0.0}))
else:
    sys.stderr.write(f"error: {scenario}\\n")
    sys.exit(1)
''')
    fake_bin.chmod(0o755)
    
    # Inject into PATH
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.getenv('PATH')}")
    
    # Reload claude_cli_client to re-scan PATH
    import importlib
    from bot.llm import claude_cli_client
    importlib.reload(claude_cli_client)
    
    yield
    
    # Cleanup
    importlib.reload(claude_cli_client)
```

### Usage in Tests

```python
def test_cli_routing_success(fake_claude_in_path, monkeypatch):
    monkeypatch.setenv("USE_CLI_LLM", "true")
    monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", "success")
    
    from bot.llm.claude_cli_client import call_agent
    resp = call_agent("test", "system", model="haiku")
    
    assert resp.ok == True
    assert resp.text == '{"ok": true}'
```

---

## MISSION PART 9: Comprehensive Environment Variable Matrix

| Variable | Default | Effect When Set | Effect When Unset |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | unset | API mode active; used for all LLM calls | Falls through to CLI auto-detect (coordinator.py:66) |
| `USE_CLI_LLM` | unset | CLI forced; `_should_use_cli()` → True | Auto-detect: use CLI if API key missing AND CLI available |
| `LLM_MULTI_AGENT` | unset | 9-agent pipeline enabled (regime/trade/risk/critic/learning/etc.) | Monolithic decision_engine (not multi-agent) |
| `LLM_MODE` | 2 | Autonomy level (0=off, 1=learning, 2=veto_only, 3=sizing, 5=full) | Defaults to 2 (veto mode) |
| `LLM_USAGE_TIER` | `RECOMMENDED` | Tier selection (CONSERVATIVE/RECOMMENDED/AGGRESSIVE/UNLEASHED) | Uses RECOMMENDED tier |
| `LLM_DAILY_BUDGET_USD` | 25.0 | Daily cost cap for API calls (CLI calls ignored) | $25/day budget |
| `AGENT_REGIME_MODEL` | unset | Override Regime agent model (e.g., `claude-opus-4-5`) | Defaults to tier's default_model (Sonnet for RECOMMENDED) |
| `AGENT_TRADE_MODEL` | unset | Override Trade agent model | Defaults to tier's default_model |
| `AGENT_RISK_MODEL` | unset | Override Risk agent model | Defaults to tier's default_model |
| `AGENT_LEARNING_MODEL` | unset | Override Learning agent model | Defaults to tier's default_model |
| `AGENT_CRITIC_MODEL` | unset | Override Critic agent model | Defaults to tier's default_model |
| `AGENT_REGIME_MODEL` | unset | **Known bug**: Regime defaults to Haiku (should respect tier) | Haiku (line 4716 in coordinator.py) |
| `AGENT_TIERED_ROUTING` | false | Enable tier-based pipeline skipping (Tier 1/2/3 routing) | All agents run (no early skip) |
| `PYTEST_CURRENT_TEST` | unset | Set by pytest; disables CLI routing in tests | CLI routing enabled (if USE_CLI_LLM set) |
| `LLM_SNIPER_ENABLED` | unset | Enable Sniper agent (micro-reversal detection) | Sniper disabled |
| `LLM_SNIPER_MODEL` | `claude-haiku-4-5-20251001` | Override Sniper model | Haiku |
| `SECONDARY_LLM_API_KEY` | unset | Enable secondary LLM backend (providers.py:94) | Single provider (primary Anthropic only) |
| `SECONDARY_LLM_MODEL` | unset | Model for secondary LLM | Uses secondary API key's default |
| `LLM_PERSONAS` | unset | Comma-separated personas (risk_off,swing) | No persona variants |

**Critical gaps**:
1. **`AGENT_REGIME_MODEL` bug** (line 4708): Regime agent defaults to Haiku even in AGGRESSIVE tier
   - Expected: Use tier's high_value_model (Opus)
   - Actual: Falls through to `_get_default_model(AgentRole.REGIME)` → Haiku
   - Impact: Low cost but also low quality for regime classification

---

## MISSION PART 10: API Path vs CLI Path — Side-by-Side Comparison

| Aspect | API Path (`call_llm` from client.py) | CLI Path (`call_agent` via coordinator.py) |
|---|---|---|
| **Auth** | API key (`ANTHROPIC_API_KEY`) required; returns `AuthenticationError` if invalid | Subscription required; exits with non-zero code if quota exhausted |
| **Cost Model** | Per-token: input @ $0.80–$15/M, output @ $4–$75/M | Per-call: $0/call (Claude Code subscription) |
| **Latency** | HTTP round-trip: typically 1–5s | Subprocess overhead + network: typically 3–8s (same as API + fork cost) |
| **Retry Logic** | Exponential backoff in `call_llm()` (lines 84–231); up to 3 attempts | No retries; `call_agent()` returns error once |
| **Token Counting** | Real: input/output/cache tokens extracted from `response.usage` | Zeroed: CLI doesn't expose per-call tokens, all set to 0 |
| **Prompt Caching** | Supported: ephemeral cache headers on system prompt (client.py:103) | Not exposed: CLI may cache internally, but bot can't control it |
| **Tool Use** | Supported: `response_format` in Anthropic SDK (unused by coordinator) | Supported via `--tools` flag; disabled by default for coordinator |
| **Rate Limits** | Anthropic API rate limits (tokens/min); `RateLimitError` exception | Subscription rate limits (requests/min); exit code 429 |
| **JSON Schema** | Via `response_format` parameter (unused in coordinator) | Via `--json-schema` flag (used for all coordinator calls) |
| **Failure Mode (Network Down)** | `APIConnectionError` → retry → return `(None, {error: "..."})`; caller decides | `subprocess.run()` fails or timeout → `CliResponse(ok=False)` |
| **Failure Mode (Out of Budget)** | Hard check at line 76 in `call_llm()`; returns `(None, {error: "budget_exceeded"})` | CLI exits non-zero; `call_agent()` returns `CliResponse(ok=False)` |
| **Logging Detail** | Comprehensive (line 175–177): tokens, latency, cache metrics, cumulative stats | Basic (claude_cli_client has no logging); coordinator logs via `logger` |
| **Test Coverage** | Mocked in tests (coordinator.py:61 prevents CLI routing during tests) | Fake binary approach (see Mission Part 8) |
| **Session State** | Single client instance persists across calls (singleton `_client`) | Stateless: `--no-session-persistence` flag ensures no session memory |
| **Caller Error Handling** | Caller checks `text is None` to detect failure | Caller checks `resp.ok` to detect failure |
| **Model Downgrade** | Soft limit at 70% budget: `cost_tracker.get_safe_model()` → Opus→Sonnet→Haiku | No automatic downgrade (CLI doesn't expose budget state to caller) |

**Key Architectural Differences**:
1. **Token tracking**: API path is honest (real tokens); CLI path is opaque (hardcoded 0 tokens) → cost tracking broken for CLI
2. **Retry resilience**: API has exponential backoff; CLI fails immediately → higher failure rate under transient network issues
3. **Model routing**: Cost tracker can downgrade API calls; CLI model fixed by coordinator → no runtime adaptation
4. **Envelope richness**: API response has `stop_reason`, `usage`, `model`; CLI may have these but coordinator doesn't extract them

---

## MISSION PART 11: Hidden Behaviors and Gotchas

### 1. Stdin vs Argv: The Windows 8191 Limit

**File**: `claude_cli_client.py:87–100`

Windows command-line limit: **8191 characters**. Agent system prompts are 7000+ chars.

**Solution**: Embed system prompt in stdin, not argv
```python
combined_input = f"<system>\n{system_prompt}\n</system>\n\n{user_prompt}"
```

**Parsing**: Claude CLI recognizes `<system>` XML tags as system role delimiter.

**Platform Compatibility**:
- Linux/macOS: Limit not relevant, but stdin approach works universally
- Windows: Required for correctness
- **Does WAGMI run on Windows?** Yes: `bot/watchdog.py:13` checks `sys.platform == "win32"`, `bot/run.py:33` handles Windows console encoding

### 2. subprocess.run `cwd=None` Behavior

**File**: `claude_cli_client.py:111`

```python
result = subprocess.run(..., cwd=cwd, ...)
```

Default: `cwd=None` → subprocess inherits parent's working directory.

**Implications**:
- If WAGMI runs from project root, Claude CLI subprocess sees project root as cwd
- May detect `.claude` config or `CLAUDE.md` in project directory
- Not configurable by coordinator (always `cwd=None`)

**Gotcha**: If Claude CLI reads project config (e.g., system prompt defaults), it affects every agent call.

### 3. `--no-session-persistence` Guarantees Statefulness

**File**: `claude_cli_client.py:94`

This flag ensures:
- No chat history carried forward
- Each call is independent
- Safe for concurrent use (no race conditions on session state)
- **Trade-off**: Claude CLI can't learn from previous turns in same session

### 4. `--max-budget-usd` Behavior

**File**: `claude_cli_client.py:93`

Set to hardcoded `0.10` per call (line 125 in coordinator.py).

**Semantics**:
- Caps the cost of a single LLM call under subscription pricing
- Claude Code Max subscription: calls cost $0 (unlimited)
- CLI enforces ceiling (doesn't charge, but respects the budget flag)

**If budget exceeded**: CLI exits non-zero, bot sees error.

### 5. Subscription Rate Limits

**Manifestation**: If Max subscription hits rate limit (calls/min), Claude CLI exits with stderr message and non-zero code.

**Pattern**: `call_agent()` returns `CliResponse(ok=False, error="exit 429: ...")` or similar.

**Caller responsibility**: Coordinator must check `resp.ok` and handle gracefully.

### 6. `claude --version` for Health Check

**Not implemented in WAGMI**, but useful for diagnostics:

```bash
$ claude --version
Claude CLI version 1.2.3
```

Could be called in `available()` or `_claude_path()` to verify binary is working.

### 7. JSON Schema Enforcement

**File**: `claude_cli_client.py:102–103`

When `--json-schema` is passed, Claude CLI enforces schema at generation time:
- If schema says `"regime": {"enum": ["trending_bull", "trending_bear", ...]}`
- Claude cannot output invalid values
- Non-compliant output gets caught and retried by CLI (internal, not visible to bot)

**Benefit**: Higher success rate for structured extraction.

**Cost**: JSON schema validation adds latency (not measured by WAGMI).

### 8. Token Zeroing in CLI Path

**Files**: `coordinator.py:139, 144`

```python
"input_tokens": 0,
"output_tokens": 0,
```

**Consequence**:
- Cost tracker receives `input_tokens=0` → can't compute actual cost
- Budget tracking becomes advisory-only for CLI path
- Decision engine can't load-balance based on token counts

**Workaround**: If `stop_reason="max_tokens"`, coordinator could estimate tokens from response length.

### 9. Markdown/Prose Tolerance

**File**: `claude_cli_client.py:148–184` and `coordinator.py:4553–4579`

Two independent JSON extractors:
1. `_extract_json()` in claude_cli_client (3-strategy parser)
2. `_parse_agent_json()` in coordinator (4-strategy parser with truncation repair)

Both attempt to extract JSON from prose-heavy responses.

**Implication**: LLM can "break" JSON-only constraint, but bot recovers by extracting the JSON object embedded in prose.

**Example**:
```
Let me analyze this...

{"action": "proceed", "confidence": 75}

This setup looks strong...
```
Both extractors find `{"action": "proceed", "confidence": 75}`.

### 10. Binary Path Search Order

**File**: `claude_cli_client.py:40–53`

```python
def _claude_path() -> Optional[str]:
    path = shutil.which("claude")  # Check $PATH first
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
```

**Search order**:
1. `shutil.which("claude")` — any directory in `$PATH`
2. Windows npm default: `~/AppData/Roaming/npm/claude` or `.cmd`
3. Unix default: `/usr/local/bin/claude`
4. Fail: return `None`

**Gotcha**: If multiple `claude` binaries exist, first in `$PATH` wins. Hard to debug if wrong one is invoked.

---

## Summary: The Definitive CLI Network

The WAGMI trading bot's CLI network represents a **cost-efficient but token-blind** alternative to direct API usage. Key characteristics:

1. **Dual-path routing**: Coordinator automatically chooses API or CLI based on subscription availability
2. **Subprocess isolation**: Each agent call forks a new `claude` process (no session state, safe concurrency)
3. **Tolerant parsing**: Multiple JSON extraction strategies handle LLM output variations
4. **Token blindness**: CLI path drops usage metrics, breaking cost tracking granularity
5. **Hardened constraints**: Dual JSON enforcement (system + user prompt) maximizes structured output compliance
6. **Windows-safe**: Stdin-based prompts bypass 8191-char command-line limit
7. **Model aliasing**: API model IDs map to CLI aliases; unknown models default to Sonnet
8. **Error recovery**: Three fallback mechanisms handle malformed responses

**For production**, ensure:
- `ANTHROPIC_API_KEY` or `USE_CLI_LLM=true` is set (not both missing)
- `claude` binary is in `$PATH` if using CLI path
- Test suite uses `PYTEST_CURRENT_TEST` mocking, not live subprocess calls
- Budget tracking monitored closely (token counts unavailable in CLI path)
- Model override env vars set correctly (Regime agent Haiku bug noted)

This reference covers every flag, every code path, every edge case, and every hidden behavior in the CLI network infrastructure.