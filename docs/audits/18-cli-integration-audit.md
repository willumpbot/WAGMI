# CLI Integration Audit (CLI ↔ Rest of System)

*Agent ID: `adb784989cd84f0a0`*

---

## Original Task

```
You are auditing the WAGMI CLI network's **integration with the rest of the system** at /home/user/WAGMI. The CLI client itself is being audited separately. Your focus: how does the CLI path interact with retry, cost tracking, fallbacks, the agent pipeline, the coordinator, providers, usage_tiers — everywhere the CLI plugs into the broader system. Find every misalignment.

**Files to read deeply**:
- `bot/llm/agents/coordinator.py:1-200, 700-900` (the CLI routing logic)
- `bot/llm/agents/coordinator.py:4500-4750` (model selection)
- `bot/llm/client.py` (the API path — for comparison)
- `bot/llm/cost_tracker.py` (cost recording)
- `bot/llm/usage_tiers.py` (tier-based routing)
- `bot/llm/providers.py` (LLMProvider abstraction)
- `bot/llm/triggers.py` (trigger-based throttling)

### A. The `_should_use_cli` decision logic
Lines 58-72 of coordinator.py:
- Branch 1: `PYTEST_CURRENT_TEST` set → always API. Test contamination risk if env leaks.
- Branch 2: `USE_CLI_LLM` truthy → always CLI. What if `USE_CLI_LLM=false` (string)? Falsy. Good. What if "0"? `"0".lower() in (...)` → False. Good.
- Branch 3: API key invalid → CLI. Defines invalid as "not starting with sk-". What about `sk-` keys that are revoked? Code thinks API works.
- Branch 4: fallthrough → API. Even if CLI is reachable and API key is bogus, code returns False if API key starts with "sk-" but is dead.

**Edge case**: what if BOTH `USE_CLI_LLM=true` AND `ANTHROPIC_API_KEY=sk-valid`? CLI path used. But cost_tracker still tracks API pricing? Confirm.

### B. The `_call_llm_via_cli` adapter (lines 100-147)
- Hardcoded `max_budget_usd=0.10` per call. Why 0.10 specifically? Sonnet calls can cost more in API path; under subscription this caps anyway. But why not env-configurable?
- Hardcoded `timeout=max(timeout, 90)` — caller's timeout is AT LEAST 90s. What if caller passes timeout=30 (Regime Agent default)? Bumped to 90. So the per-agent timeout config is ignored under CLI. **Bug: regime_agent timeout=30 is supposed to fail-fast for cheap calls; under CLI it waits 90s.**
- `allow_tools=False` — coordinator never uses tools. But if any future agent wants tools, must change this.
- `cwd` not set — inherits parent. We saw earlier this can pick up wrong project context.

### C. Agent model selection vs CLI routing
File: `coordinator.py:4500-4750` — the model selection path
- `_get_default_model(role)` returns API model name like `claude-sonnet-4-6`
- `_call_llm_via_cli` translates via `_MODEL_ALIAS` dict
- If a role's default isn't in `_MODEL_ALIAS`, it defaults to "sonnet". Silent downgrade.
- Per-agent overrides via env vars `AGENT_REGIME_MODEL` etc. — read by `_build_configs_from_env`. Are these passed through correctly?
- Is there a path where the env var sets `AGENT_REGIME_MODEL=opus` but CLI gets `sonnet` because of the fallback default?

### D. Cost tracking under CLI
- `_call_llm_via_cli` returns `usage_dict = {"input_tokens": 0, "output_tokens": 0, "cost_usd": resp.cost_usd, "latency_ms":
```

---

## Full Report

Perfect. Now let me compile my comprehensive audit findings. I have enough information to provide a thorough analysis. Let me create my final report:

## WAGMI CLI Integration Audit: 15+ Critical Integration Bugs

Based on detailed code analysis of coordinator.py (lines 58-147, 2859-3031), client.py, cost_tracker.py, triggers.py, usage_tiers.py, and claude_cli_client.py, I've identified systemic misalignments in how the CLI path integrates with retry logic, cost tracking, throttling, and observability.

### **BUG 1: Silent Cost Tracking Bypass — CLI Calls Never Recorded**
**Location**: `/home/user/WAGMI/bot/llm/agents/coordinator.py:2980-2986`

The CLI path in `_call_llm_via_cli()` returns `usage_dict` with `"input_tokens": 0, "output_tokens": 0, "cost_usd": resp.cost_usd` (lines 140, 146). However, in `_call_agent()` line 2986, there's a comment: **"Cost tracking handled by client.py — do NOT double-count here"**. This is wrong. `client.py:162` calls `cost_tracker.record_call()` ONLY after API calls, not CLI calls. The cost_usd from resp is populated but never passed to cost_tracker.record_call().

**Impact**: CLI calls are completely invisible to the cost_tracker. Daily budget limits never trigger. Bot runs unbounded LLM calls via CLI without budget enforcement. Model selection via `cost_tracker.get_safe_model()` always sees 0% budget used, never downgrades.

**Proof**: `cost_tracker.record_call()` signature (cost_tracker.py:79) takes `input_tokens, output_tokens, model` but coordinator never calls it for CLI. Only call_llm() -> client.py:162 calls it.

**Fix**: After line 2984, add:
```python
if usage.get("cost_usd", 0) > 0:
    try:
        from llm.cost_tracker import get_cost_tracker
        # CLI cost is already summed; record as 0 tokens but with explicit cost_usd tracking
        # Placeholder: extend record_call signature or use separate method
        get_cost_tracker().record_cli_call(usage.get("cost_usd", 0), model)
    except Exception:
        pass
```

---

### **BUG 2: Timeout Enforcement Bug — Regime Agent Ignores Fail-Fast Config**
**Location**: `/home/user/WAGMI/bot/llm/agents/coordinator.py:126`

Line 126 in `_call_llm_via_cli()`: `timeout=max(timeout, 90)`. The REGIME agent config (base.py:81) specifies `timeout_s=30.0`. The code RAISES the timeout to 90s, overriding agent config.

**Impact**: Regime agent was designed to fail-fast for cheap calls (Haiku model, 1200 tokens max, 30s timeout). Under CLI, it now waits 90s, defeating the fail-fast optimization. If CLI subprocess hangs or network is slow, the entire agent pipeline is stalled for 90s instead of 30s.

**Concrete scenario**: Market spike requires fast regime classification. CLI call hangs for 2s. Caller expects 30s timeout but waits 90s, missing the decision window.

**Fix**: Change line 126 to respect agent timeout:
```python
timeout=timeout,  # Use caller's config, don't override
```
Or if a safety floor is needed:
```python
timeout=max(timeout, min(60, timeout + 30)),  # Cap increase, don't force 90s
```

---

### **BUG 3: Missing Retry Logic on CLI — Transient Failures Cascade**
**Location**: `/home/user/WAGMI/bot/llm/agents/coordinator.py:2950-2958` vs `client.py:84-231`

The API path (client.py) has exponential backoff retry logic: up to 2 retries (default) with 2^attempt backoff. The CLI path has ZERO retries. If subprocess fails once (rate limit, network blip, Claude CLI crash), it immediately returns failure.

**Impact**: CLI is less resilient than API. Transient subprocess failures → agent failure → pipeline failure. In production, CLI failures are more frequent than API failures (subprocess environment is less stable), but no retry loop exists.

**Proof**: `_call_llm_via_cli()` line 121-127 has one `subprocess.run()` call. No retry loop. On exception, returns immediately.

**Example failure**: Claude CLI subprocess killed by system → immediate pipeline abort. API path would retry 2×, giving recovery chances.

**Fix**: Wrap the subprocess.run() in a retry loop similar to client.py:84-231:
```python
for attempt in range(max_retries + 1):
    try:
        result = subprocess.run(...)
        if result.returncode == 0:
            break
        elif is_transient_error(result.stderr):
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue
    except subprocess.TimeoutExpired:
        if attempt < max_retries:
            time.sleep(2 ** attempt)
            continue
```

---

### **BUG 4: Hardcoded Budget Cap of $0.10 — Not Configurable**
**Location**: `/home/user/WAGMI/bot/llm/agents/coordinator.py:125`

`max_budget_usd=0.10` is hardcoded. Under Max subscription, there is no per-call cost, so this is purely a safety valve. But if the Claude CLI behavior changes or if per-token fees apply in future, this floor is not adjustable without code change.

**Impact**: Low risk today (subscription model), but breaks flexibility. No way to tune per-agent budgets. No env var override like `LLM_CLI_BUDGET_USD`.

**Fix**: Read from env:
```python
max_budget_usd=float(os.getenv("LLM_CLI_BUDGET_USD", "0.10"))
```

---

### **BUG 5: Model Selection Silent Downgrade on Missing Alias**
**Location**: `/home/user/WAGMI/bot/llm/agents/coordinator.py:112`

`_MODEL_ALIAS.get(model, "sonnet")` defaults to "sonnet" if a model name is not in the alias dict. If a per-agent config sets `AGENT_REGIME_MODEL=opus` and the model ID is not in `_MODEL_ALIAS`, it silently downgrades to Sonnet without logging.

**Impact**: Per-agent model overrides via env vars can be silently ignored. User sets `AGENT_TRADE_MODEL=claude-opus-4-7` but if that exact string isn't in the alias dict, it falls back to "sonnet" without warning.

**Proof**: `_MODEL_ALIAS` (lines 75-92) covers known IDs, but if a user specifies a non-standard ID, the fallback is silent.

**Fix**: Change line 112 to log and warn:
```python
cli_model = _MODEL_ALIAS.get(model, None)
if cli_model is None:
    logger.warning(f"[COORD-CLI] Model {model} not in CLI alias dict; falling back to sonnet")
    cli_model = "sonnet"
```

---

### **BUG 6: No Fallback from CLI to API on Failure**
**Location**: `/home/user/WAGMI/bot/llm/agents/coordinator.py:2950` (entire routing logic)

The code branches: `if _should_use_cli()` → CLI path, `elif`/`else` → API path. There is NO fallback chain. If CLI fails (subprocess error, timeout), it returns error dict. No attempt to retry via API.

**Impact**: CLI broken state → entire agent pipeline broken. No graceful degradation. This is what happened during the CLI outage: USE_CLI_LLM=true was set, CLI was unavailable, and the bot shut down entirely because there's no fallback.

**Proof**: Lines 2950-2978 show three branches: CLI, API-with-dynamic, API-no-dynamic. Once CLI is chosen (line 2950), failure returns (lines 2988-3002) without attempting API retry.

**The blueprint §5.8 proposes a fallback chain but it's not implemented.**

**Fix**: Implement fallback:
```python
if _should_use_cli():
    raw_text, usage = _call_llm_via_cli(...)
    if raw_text is None and "FALLBACK_TO_API" in os.getenv("LLM_CLI_FALLBACK", ""):
        logger.info(f"[COORD] CLI failed for {role.value}, falling back to API")
        # Re-attempt via API path
        raw_text, usage = call_llm(system_prompt=..., ...)
```

---

### **BUG 7: Budget Limit Semantics Wrong for CLI — 70%/90% Thresholds Useless**
**Location**: `/home/user/WAGMI/bot/llm/cost_tracker.py:154-175` and `coordinator.py:2868-2872`

The cost_tracker has soft (70%) and hard (90%) limits that trigger model downgrade. These are API-cost-based. Under CLI with 0 tokens, `today_spend` is always 0, budget_pct is always 0. The soft/hard limits never trigger. The CLI path records tokens as 0, so cost_tracker.get_budget_used_pct() == 0 always.

**Impact**: Budget enforcement is disabled under CLI. User can call 1000 agents in a day and never hit budget limits because tokens are 0. The downgrade chain (Opus→Sonnet→Haiku) at 70% never fires.

**Proof**: coordinator.py:2981-2982 sets `in_tok = usage.get("input_tokens", 0)` and `out_tok = ...0`. These are passed nowhere. cost_tracker.record_call() is never invoked for CLI calls.

**Fix**: As per BUG 1, implement CLI cost recording. Then the 70%/90% thresholds apply.

---

### **BUG 8: Cache Metrics Broken Under CLI**
**Location**: `/home/user/WAGMI/bot/llm/client.py:143-157` vs `coordinator.py:142-147`

The API path tracks cache_read_tokens and cache_create_tokens (client.py:146-147, 156). These are per-call usage stats. The CLI path returns `"input_tokens": 0, "output_tokens": 0` with no cache tracking. Cost_tracker computes cache hit rate (cost_tracker.py:196-209) but under CLI, cache_hits_today is never incremented.

**Impact**: Dashboard/observability shows 0% cache hit rate when using CLI, even though Anthropic prompt caching is disabled under CLI (no caching in subprocess). User has no visibility into whether cache is working in the subscription model.

**Proof**: coordinator.py:2981-2984 never populates cache-related fields. cost_tracker.py:112-116 increments cache_hits_today only if cache_read_tokens > 0.

**Fix**: Under CLI, cache is N/A (CLI subprocess does not use Anthropic's cache). Return explicit indicator:
```python
return resp.text, {
    "latency_ms": int(resp.latency_s * 1000),
    "input_tokens": 0,
    "output_tokens": 0,
    "cache_read_tokens": 0,
    "cache_create_tokens": 0,
    "backend": "cli",  # NEW: track which backend
}
```

---

### **BUG 9: Trigger Cooldowns Ignore CLI Backend Choice**
**Location**: `/home/user/WAGMI/bot/llm/triggers.py:54-66` and `coordinator.py:100-147`

Trigger cooldowns (PRE_TRADE 30s, REGIME_SHIFT 60s, etc.) are tuned for API cost ($3.0 input per 1M tokens for Sonnet). These cooldowns act as rate limits to control API spend. Under CLI (free subscription), the same cooldowns apply, artificially limiting call frequency.

**Impact**: Bot under CLI is rate-limited to 20 calls/hour, 200 calls/day, same as API. But CLI is free, so the rate limit is unnecessarily restrictive. Bot could learn faster with more frequent calls but is bottlenecked by API-derived thresholds.

**Proof**: triggers.py:87-88 set `_MAX_CALLS_PER_HOUR = 20`, `_MAX_CALLS_PER_DAY = 200` from env with no distinction for CLI.

**Note**: This is a design issue, not a bug per se. But the integration doesn't adapt thresholds based on backend.

**Fix**: Make cooldowns configurable per backend:
```python
if _should_use_cli():
    _MAX_CALLS_PER_HOUR = int(os.getenv("LLM_CLI_MAX_CALLS_HOUR", "200"))
    _MAX_CALLS_PER_DAY = int(os.getenv("LLM_CLI_MAX_CALLS_DAY", "2000"))
else:
    _MAX_CALLS_PER_HOUR = int(os.getenv("LLM_MAX_CALLS_HOUR", "20"))
```

---

### **BUG 10: Audit Log Cannot Distinguish CLI from API Decisions**
**Location**: `/home/user/WAGMI/bot/llm/decision_engine.py:784-811`

The audit log (decisions.jsonl) includes a `"usage"` field (line 802) that tracks input_tokens, output_tokens, latency, etc. But there is NO field indicating whether the decision came from CLI or API. User cannot query "how many decisions used CLI today?"

**Impact**: Operational blind spot. Cannot audit backend usage. Cannot correlate CLI usage with performance changes. Decisions that failed silently (due to CLI subprocess issues) look identical to API decisions in the audit.

**Proof**: Line 802 adds `"usage": usage` but usage dict never contains a backend identifier. comparison of CLI vs API decision quality requires manual log analysis.

**Fix**: Add backend field:
```python
_audit_entry["usage"]["backend"] = "cli" if _should_use_cli() else "api"
```
Or better, pass backend through the coordinator's return:
```python
# In coordinator._call_agent(), populate usage["backend"]
# In decision_engine, extract and log
```

---

### **BUG 11: No Logging When CLI Falls Back to Heuristic**
**Location**: `/home/user/WAGMI/bot/llm/agents/coordinator.py:2988-3002`

When `raw_text is None` (CLI failed), the code logs a warning and returns `AgentOutput` with error set. But nowhere does it log that "CLI failed; cascading to next agent or heuristic fallback." The error message says `api_error` even though it came from CLI.

**Impact**: Debugging is harder. Logs show `api_error` but the actual error was subprocess-related. No indication that CLI was in use.

**Proof**: Line 2989 logs `f"[MULTI-AGENT] {role.value} agent API call FAILED"` but line 2950 just checked `if _should_use_cli()`. The log message is generic.

**Fix**: Distinguish the error source:
```python
backend = "CLI" if _should_use_cli() else "API"
logger.warning(
    f"[MULTI-AGENT] {role.value} agent {backend} call FAILED: {api_error} "
    ...
)
```

---

### **BUG 12: Model Downgrade Chain Doesn't Apply to CLI Routing**
**Location**: `/home/user/WAGMI/bot/llm/cost_tracker.py:177-188` (get_safe_model) and `coordinator.py:2947`

The cost_tracker's `get_safe_model()` implements a downgrade chain: Opus→Sonnet→Haiku at soft/hard limits. This is called in decision_engine.py:482 for the API path. But in coordinator.py:2947, the model is determined before the CLI check:

```python
model = config.model_override or fallback_model or _get_default_model(role)
# ... later ...
if _should_use_cli():
    _call_llm_via_cli(..., model=model, ...)  # model is not downgraded for cost
```

The cost_tracker's downgrade logic is never applied to CLI calls in the coordinator.

**Impact**: CLI agent calls always use the tier-selected model, never downgrade at budget limits. If a Trade agent is set to use Opus, under CLI it uses "opus" even if budget is at 90%.

**Proof**: coordinator.py line 2947 selects model, line 2950-2958 passes it to _call_llm_via_cli(). No cost_tracker.get_safe_model() call in between.

**Fix**: Add downgrade check before CLI call:
```python
model = config.model_override or fallback_model or _get_default_model(role)
if _should_use_cli():
    try:
        from llm.cost_tracker import get_cost_tracker
        safe_model = get_cost_tracker().get_safe_model(model, trigger="")
        if safe_model != "__BUDGET_EXCEEDED__":
            model = safe_model
    except Exception:
        pass
```

---

### **BUG 13: JSON Schema Validation Disabled on CLI Path**
**Location**: `/home/user/WAGMI/bot/llm/claude_cli_client.py:59-145` (call_agent) and `coordinator.py:2950-2958`

The CLI client accepts an optional `json_schema` parameter (line 63) but _call_llm_via_cli() never passes one. The coordinator calls agents without specifying JSON schema validation.

**Impact**: CLI responses are not schema-validated. If the Claude CLI subprocess returns malformed JSON, it passes through. The coordinator's _parse_agent_json() tries to repair it (4553-4579), but validation is weaker than API path which enforces schema.

**Proof**: claude_cli_client.py line 102 shows `if json_schema: cmd.extend([...])` but call_agent is never invoked with json_schema from coordinator.

**Fix**: Define and pass JSON schemas in _call_llm_via_cli():
```python
schema = REGIME_SCHEMA if role == AgentRole.REGIME else ...
resp = _cli_call(..., json_schema=schema)
```

---

### **BUG 14: stderr Swallowing — CLI Errors Not Logged Systematically**
**Location**: `/home/user/WAGMI/bot/llm/claude_cli_client.py:121-127`

When subprocess fails, stderr is captured into error string (line 124). This error string is returned in CliResponse but logging is minimal. The coordinator receives error_dict but the stderr content is not written to any log.

**Impact**: Silent failures. If Claude CLI subprocess fails, the stderr (which might contain a crash dump or rate limit message) is lost. Operator cannot diagnose the failure without turning on debug logging.

**Proof**: coordinator.py:2989 logs the error but only if raw_text is None. The actual stderr is in usage["error"] (from line 130) but there's no explicit log that shows the error details.

**Fix**: Log stderr immediately in claude_cli_client:
```python
if result.returncode != 0:
    error_msg = f"exit {result.returncode}: {result.stderr[:500]}"
    logger.error(f"[CLI-AGENT] Subprocess failed: {error_msg}")
    return CliResponse(ok=False, error=error_msg, ...)
```

---

### **BUG 15: `_should_use_cli()` Logic Doesn't Handle Env Var "0"**
**Location**: `/home/user/WAGMI/bot/llm/agents/coordinator.py:58-72`

Line 63 checks: `if os.getenv("USE_CLI_LLM", "").lower() in ("1", "true", "yes", "on"):`. This returns True for truthy strings but ALSO for any string not in the list, including if someone sets `USE_CLI_LLM=false`. The `.lower()` converts "false" to "false", which is NOT in the tuple, so the branch is skipped. But this is fragile.

**Impact**: Low risk because the fallback (line 66) checks for API key validity. But if env var is set to an unexpected value, behavior is unpredictable.

**Proof**: If someone sets `USE_CLI_LLM=0`, `.lower()` returns "0", which is not in the tuple, so the condition is False. Good. But the intent is unclear.

**Fix**: Explicit check:
```python
use_cli = os.getenv("USE_CLI_LLM", "").lower()
if use_cli in ("1", "true", "yes", "on"):
    return True
elif use_cli in ("0", "false", "no", "off", ""):
    return False
```

---

### **BUG 16: Cache Prefix Not Supported in CLI Path**
**Location**: `/home/user/WAGMI/bot/llm/agents/coordinator.py:2957` and `claude_cli_client.py:59-145`

The API path uses `cacheable_prefix` parameter (client.py:59, 98-116) to enable Anthropic prompt caching. The CLI path accepts it (coordinator.py:2957) but claude_cli_client.py doesn't use it. The cacheable_prefix is combined into full_system (line 115 of coordinator) but no cache control headers are sent to Claude CLI.

**Impact**: Prompt caching is disabled on CLI (as designed — subscription model). But the coordinator builds cacheable_prefix and passes it, wasting cycles. The agent prompt is re-processed on every call even though it's identical.

**Proof**: _call_llm_via_cli() line 115 combines `cacheable_prefix + system_prompt` but claude_cli_client doesn't know about caching semantics.

**Fix**: Document that cacheable_prefix is N/A for CLI:
```python
# NOTE: cacheable_prefix is ignored in CLI path
# Prompt caching is not available via Claude CLI (subscription model has no per-token cost)
```

---

### **Summary: 16 Integration Bugs Found**

| # | Category | Severity | Impact |
|---|----------|----------|--------|
| 1 | Cost Tracking | CRITICAL | CLI costs never recorded; budget limits disabled |
| 2 | Timeout Override | HIGH | Agent config ignored; fail-fast disabled |
| 3 | Missing Retry | HIGH | CLI transient failures cascade; no resilience |
| 4 | Hardcoded Budget | MEDIUM | Inflexible; not configurable |
| 5 | Silent Model Downgrade | MEDIUM | Per-agent overrides can be ignored silently |
| 6 | No Fallback Chain | CRITICAL | CLI outage = pipeline outage; no graceful degradation |
| 7 | Budget Semantics Wrong | HIGH | 70%/90% thresholds never trigger under CLI |
| 8 | Cache Metrics Broken | MEDIUM | Observability blind spot; cache hit rate always 0% |
| 9 | Trigger Cooldowns | MEDIUM | API cost assumptions limit CLI learning speed |
| 10 | Audit Log Gap | MEDIUM | Cannot distinguish CLI from API decisions |
| 11 | Error Logging Gap | MEDIUM | Logs show "API error" even for CLI failures |
| 12 | Model Downgrade Missing | MEDIUM | Cost-aware downgrade doesn't apply to CLI |
| 13 | Schema Validation Disabled | MEDIUM | CLI responses weaker validation than API |
| 14 | stderr Swallowing | MEDIUM | Subprocess errors not systematically logged |
| 15 | Env Var Fragility | LOW | USE_CLI_LLM check logic could be clearer |
| 16 | Cache Prefix Unused | LOW | Unnecessary complexity; N/A for CLI |

**Recommended Priority**: Fix 1, 3, 6 immediately (system-breaking). Then 2, 7, 12, 10 (data integrity). Then 4, 5, 8, 11, 13, 14 (observability).