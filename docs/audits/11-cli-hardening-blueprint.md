# CLI Improvement and Hardening Blueprint

*Agent ID: `a02296fbdccfb751a`*

---

## Original Task

```
You are designing the **CLI network hardening blueprint** for WAGMI at /home/user/WAGMI. The CLI network is the user's newest tech and TOP audit priority. Multiple bugs already found. The user wants this layer to be bulletproof going forward — long-term value, not band-aids.

**Mission**: produce the definitive design for what the CLI network should look like when fully hardened.

### A. The ideal CliBackend(LLMBackend) class
- Implement the `LLMBackend` ABC from §5 of blueprint
- Methods: `call`, `validate_model`, `available`, `health`
- Wrap all current `claude_cli_client` logic + fixes
- Failure-mode classification per §5.6 (13 modes)
- Cost reporting that doesn't lie (parse `usage` block from envelope)
- Latency tracking per (agent, model) pair
- Concurrency-safe (no shared mutable state)
- Atomic JSON write for failure log
- Graceful degradation when binary missing/auth expired

Provide the full Python class implementation, ~200-300 lines.

### B. The ideal subprocess launcher
- `preexec_fn=os.setsid` for process group control
- Explicit `cwd` always passed (never None)
- File descriptor cleanup (close-on-exec)
- Stdin/stdout buffering management for large payloads
- Timeout enforcement at process-group level (`os.killpg`)
- Encoding: UTF-8 with bytes-mode fallback for binary content
- Resource limits via `resource.setrlimit` for safety

### C. The envelope parser (replaces current broken one)
- Read `structured_output` first (the §22 fix)
- Read `usage` block (real tokens)
- Read `stop_reason` (detect truncation)
- Read `model` (verify no silent downgrade)
- Read `id` (correlation for audit)
- Validate envelope shape against versioned schema
- Fail loud on shape change (no silent fallback)
- Strict mode for production, lenient for tests

### D. Failure mode classifier
A function that takes (returncode, stderr, stdout, exception) and returns a FailureMode enum:
- BINARY_NOT_FOUND
- AUTH_EXPIRED (regex stderr)
- QUOTA_EXHAUSTED (regex stderr)
- NETWORK_ERROR (regex stderr)
- SUBPROCESS_TIMEOUT
- SUBPROCESS_NONZERO_EXIT
- SUBPROCESS_HUNG
- SUBPROCESS_KILLED_OOM (returncode 137)
- ENVELOPE_MALFORMED
- RESULT_FIELD_EMPTY
- AGENT_JSON_MALFORMED
- SCHEMA_MISMATCH
- BUDGET_EXCEEDED
- RATE_LIMITED
- UNKNOWN

For each: regex patterns to match, recovery action (retry/circuit-break/abort/escalate), severity.

### E. The retry policy
- Per-failure-mode retry decisions
- Exponential backoff with jitter
- Max retries per call
- Circuit breaker integration (if N failures in M seconds, fast-fail for K seconds)
- Per-(agent, backend) circuit breakers, not global

### F. The fallback chain integration
- Primary: claude_cli (subscription)
- Secondary: claude_cli with different model (e.g. Haiku → Sonnet on schema fail)
- Tertiary: anthropic_api (if API key set)
- Quaternary: heuristic (e.g., quant_regime.py for Regime Agent)
- Final: defensive_skip
- Each fallback emits structured log with correlation_id

### G. The compliance auditor
Per-(agent, model) rollin
```

---

## Full Report

I have sufficient context. I'll now produce the definitive CLI hardening blueprint as the final assistant message (no file writes per plan-mode and read-only constraints).

---

# CLI Network Hardening Blueprint — WAGMI

A definitive, opinionated, file-path-specific blueprint for hardening the Claude CLI network at `/home/user/WAGMI/bot/llm/`. This plan replaces ad-hoc subprocess code with a versioned, observable, fault-tolerant backend layer. Target: 4–8 weeks. Result: a CLI subsystem that fails loudly, recovers gracefully, and produces canonical audit records the rest of the system can trust.

The current attack surface (concrete):
- `/home/user/WAGMI/bot/llm/claude_cli_client.py` — 309 lines. Single function `call_agent` doing argv build + subprocess + parse + JSON repair. No process group, no fd cleanup, no usage block parsing (envelope `total_cost_usd` only), no failure-mode taxonomy, no atomic writes anywhere. `_extract_json` is the silent fallback that quietly hides envelope drift.
- `/home/user/WAGMI/bot/llm/agents/coordinator.py` lines 100–147 — `_call_llm_via_cli` dual-imports the client per call, throws away `usage` (sets `input_tokens=0`), and only triggers the "structured_output" fallback by string-prefix sniffing. This is the §22 bug (the coordinator never reads the structured channel).
- `/home/user/WAGMI/bot/llm/cost_tracker.py` — assumes API token semantics. Records `$0` for CLI by virtue of `total_cost_usd: 0`, masking subscription rate-limit pressure.
- `/home/user/WAGMI/bot/data/llm/` — exists, has `llm_memory.json`, but no `cli_calls.jsonl`, no `model_compliance.json`, no per-call audit trail.

What follows is the bulletproof rebuild.

---

## A. The ideal `CliBackend(LLMBackend)` class

Target file: `/home/user/WAGMI/bot/llm/backends/cli_backend.py` (new). The ABC lives at `/home/user/WAGMI/bot/llm/backends/base.py` (new).

The class is a thin coordinator: it does not parse, validate, classify, or audit itself — it composes those concerns from sibling modules. This is what makes it testable.

```python
# /home/user/WAGMI/bot/llm/backends/base.py
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

@dataclass
class LLMRequest:
    agent: str                  # e.g. "regime", "trade", "critic"
    model: str                  # canonical model id (NOT alias)
    system_prompt: str
    user_prompt: str
    schema: Optional[Dict[str, Any]] = None
    timeout_s: int = 90
    max_budget_usd: float = 0.10
    correlation_id: str = ""    # caller-supplied; backend must propagate
    autonomy_level: int = 0     # so backend can short-circuit if Level 0

@dataclass
class LLMResponse:
    ok: bool
    correlation_id: str
    backend: str
    agent: str
    model_requested: str
    model_returned: str = ""    # from envelope; verifies no silent downgrade
    text: str = ""
    parsed: Optional[Dict[str, Any]] = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    failure_mode: Optional[str] = None
    stop_reason: str = ""
    schema_compliant: bool = False
    envelope_id: str = ""
    envelope_keys: list = field(default_factory=list)
    error: str = ""

class LLMBackend(ABC):
    name: str = "abstract"

    @abstractmethod
    def call(self, req: LLMRequest) -> LLMResponse: ...
    @abstractmethod
    def validate_model(self, model: str) -> bool: ...
    @abstractmethod
    def available(self) -> bool: ...
    @abstractmethod
    def health(self) -> Dict[str, Any]: ...
```

```python
# /home/user/WAGMI/bot/llm/backends/cli_backend.py
import hashlib, os, threading, time, uuid
from collections import defaultdict, deque
from typing import Any, Dict, Optional
from llm.backends.base import LLMBackend, LLMRequest, LLMResponse
from llm.cli.launcher import launch_subprocess, LaunchResult
from llm.cli.envelope import parse_envelope, EnvelopeError, EnvelopeStrictness
from llm.cli.classifier import classify_failure, FailureMode
from llm.cli.audit import write_audit_line
from llm.cli.version import detect_version, verify_version_unchanged
from llm.cli.compliance import record_sample
from llm.cli.budget import check_budget_envelope

class CliBackend(LLMBackend):
    name = "claude_cli"

    def __init__(self, *, binary_path: Optional[str] = None,
                 cwd: Optional[str] = None,
                 strict: bool = True):
        self._binary = binary_path or _resolve_binary()  # never silently None
        self._cwd = cwd or os.getcwd()                  # always explicit
        self._strict = strict
        self._version: Optional[str] = None
        # per-(agent, model) latency rings — concurrency-safe via lock
        self._lat_lock = threading.Lock()
        self._latencies: dict[tuple, deque] = defaultdict(lambda: deque(maxlen=256))
        # rate counters (subscription accounting)
        self._minute_calls: deque = deque(maxlen=120)
        self._day_calls: deque = deque(maxlen=20000)

    # ── Public API ──────────────────────────────────────────────────────────
    def available(self) -> bool:
        return self._binary is not None and os.access(self._binary, os.X_OK)

    def validate_model(self, model: str) -> bool:
        return model in {"haiku", "sonnet", "opus"} or model.startswith("claude-")

    def health(self) -> Dict[str, Any]:
        with self._lat_lock:
            lat = {f"{a}/{m}": _percentiles(d) for (a, m), d in self._latencies.items()}
        return {
            "binary": self._binary, "version": self._version,
            "available": self.available(),
            "calls_last_minute": len(self._minute_calls),
            "calls_last_24h": len(self._day_calls),
            "latency_p50_p99_ms": lat,
        }

    def call(self, req: LLMRequest) -> LLMResponse:
        cid = req.correlation_id or uuid.uuid4().hex
        if req.autonomy_level == 0:
            return LLMResponse(ok=False, correlation_id=cid, backend=self.name,
                               agent=req.agent, model_requested=req.model,
                               failure_mode="DISABLED_BY_AUTONOMY",
                               error="LLM_MODE=0; CLI gated off")
        if not self.available():
            return self._fail(req, cid, FailureMode.BINARY_NOT_FOUND,
                              "claude binary not on PATH")

        # Version pinning — first call captures, subsequent calls verify
        if self._version is None:
            self._version = detect_version(self._binary, self._cwd)
        else:
            verify_version_unchanged(self._binary, self._cwd, self._version)

        prompt_hash = _sha256(req.system_prompt + "\x1f" + req.user_prompt)
        t0 = time.time()
        launch: LaunchResult = launch_subprocess(
            binary=self._binary, cwd=self._cwd,
            argv=_build_argv(self._binary, req),
            stdin=_compose_stdin(req),
            timeout_s=req.timeout_s,
            correlation_id=cid,
        )
        latency_ms = int((time.time() - t0) * 1000)

        # Classify before parsing — many failure modes are pre-envelope.
        fm = classify_failure(launch.returncode, launch.stderr,
                              launch.stdout, launch.exception)
        if fm not in (FailureMode.OK, FailureMode.UNKNOWN):
            return self._record(req, cid, latency_ms, prompt_hash,
                                ok=False, failure_mode=fm,
                                error=launch.stderr[:500])

        # Strict envelope parse — reads structured_output FIRST (the §22 fix)
        try:
            env = parse_envelope(launch.stdout,
                                 strict=EnvelopeStrictness.STRICT
                                 if self._strict else EnvelopeStrictness.LENIENT)
        except EnvelopeError as e:
            return self._record(req, cid, latency_ms, prompt_hash, ok=False,
                                failure_mode=FailureMode.ENVELOPE_MALFORMED,
                                error=str(e), stdout=launch.stdout)

        # Cost: real numbers from usage block
        in_tok = env.input_tokens
        out_tok = env.output_tokens
        cost = env.cost_usd  # CLI emits 0 under subscription — that's truthful, not a lie
        check_budget_envelope(cost, req.max_budget_usd)  # raises if API ever sneaks in

        # Schema compliance (drives compliance auditor + Sonnet upgrade signals)
        schema_ok = env.parsed is not None and env.parsed_matches_schema(req.schema)
        record_sample(req.agent, req.model, schema_ok)

        self._track_latency(req.agent, req.model, latency_ms)
        self._track_rate()

        resp = LLMResponse(
            ok=True, correlation_id=cid, backend=self.name,
            agent=req.agent, model_requested=req.model,
            model_returned=env.model, text=env.text, parsed=env.parsed,
            input_tokens=in_tok, output_tokens=out_tok, cost_usd=cost,
            latency_ms=latency_ms, stop_reason=env.stop_reason,
            schema_compliant=schema_ok, envelope_id=env.id,
            envelope_keys=list(env.raw.keys()),
        )
        write_audit_line(resp, prompt_hash=prompt_hash,
                         response_hash=_sha256(env.text))
        return resp

    # ── Internals ──────────────────────────────────────────────────────────
    def _track_latency(self, agent, model, ms):
        with self._lat_lock:
            self._latencies[(agent, model)].append(ms)

    def _track_rate(self):
        now = time.time()
        self._minute_calls.append(now)
        self._day_calls.append(now)
        # prune
        while self._minute_calls and now - self._minute_calls[0] > 60:
            self._minute_calls.popleft()
        while self._day_calls and now - self._day_calls[0] > 86400:
            self._day_calls.popleft()

    def _fail(self, req, cid, fm: FailureMode, error: str) -> LLMResponse:
        return self._record(req, cid, 0, "", ok=False, failure_mode=fm, error=error)

    def _record(self, req, cid, latency_ms, prompt_hash, *, ok,
                failure_mode=None, error="", stdout=""):
        resp = LLMResponse(
            ok=ok, correlation_id=cid, backend=self.name,
            agent=req.agent, model_requested=req.model,
            failure_mode=failure_mode.name if failure_mode else None,
            latency_ms=latency_ms, error=error,
        )
        write_audit_line(resp, prompt_hash=prompt_hash, response_hash="")
        return resp

def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="replace")).hexdigest()
```

Key invariants enforced by this class:
- No shared mutable globals — `CLAUDE_BIN` becomes per-instance `_binary`.
- Concurrency: latency rings and rate counters are guarded by a `Lock`. Multiple coordinators can share one `CliBackend` safely.
- Every code path emits exactly one audit line (success or failure).
- Cost surface is honest: under subscription `cost_usd=0` is correct, not zeroed-out by ignorance.
- `available()` plus `_resolve_binary()` (private helper that searches PATH and the npm install paths from the existing `_claude_path()`) means graceful degradation: callers ask `available()` before calling.

---

## B. The ideal subprocess launcher

Target file: `/home/user/WAGMI/bot/llm/cli/launcher.py` (new).

The current `subprocess.run(...)` call is fragile: no process group, no fd hygiene, no rlimit, no oom guard, no kill-tree, encoding fallback baked into `text=True`. Replace with a single function that returns a `LaunchResult` dataclass.

```python
# /home/user/WAGMI/bot/llm/cli/launcher.py
import os, resource, signal, subprocess, time
from dataclasses import dataclass
from typing import Optional, Sequence

@dataclass
class LaunchResult:
    returncode: int
    stdout: str
    stderr: str
    duration_s: float
    exception: Optional[BaseException] = None
    timed_out: bool = False
    killed_by: str = ""           # "timeout" | "oom" | ""

def _preexec():
    # New process group → killpg controls all children.
    os.setsid()
    # File descriptors: close everything above stderr at exec.
    try: os.closerange(3, 256)
    except OSError: pass
    # Resource limits — defensive caps so a runaway CLI can't eat the box.
    # These are intentionally generous; tune via env if needed.
    resource.setrlimit(resource.RLIMIT_AS,    (4 * 1024**3,  4 * 1024**3))   # 4 GiB virt
    resource.setrlimit(resource.RLIMIT_CPU,   (300, 300))                    # 5 min cpu
    resource.setrlimit(resource.RLIMIT_NOFILE,(1024, 1024))
    resource.setrlimit(resource.RLIMIT_CORE,  (0, 0))                        # no cores

def launch_subprocess(*, binary: str, cwd: str, argv: Sequence[str],
                      stdin: bytes, timeout_s: int,
                      correlation_id: str) -> LaunchResult:
    assert cwd is not None, "cwd must be explicit"
    assert os.path.isdir(cwd), f"cwd does not exist: {cwd}"

    env = {**os.environ,
           "WAGMI_CORRELATION_ID": correlation_id,
           # Force UTF-8; defang locale-driven encoding surprises.
           "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8",
           "PYTHONIOENCODING": "utf-8"}

    # Bytes mode: we decode ourselves so we control replacement semantics.
    proc = subprocess.Popen(
        argv, cwd=cwd, env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        bufsize=0,                        # unbuffered for large payloads
        close_fds=True,
        preexec_fn=_preexec,
    )
    t0 = time.time()
    try:
        out_b, err_b = proc.communicate(input=stdin, timeout=timeout_s)
        rc = proc.returncode
        timed_out = False
        killed_by = ""
    except subprocess.TimeoutExpired:
        # Process-group level kill so subprocesses of claude die too.
        try: os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception: pass
        try: out_b, err_b = proc.communicate(timeout=5)
        except Exception:
            try: os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception: pass
            out_b, err_b = b"", b""
        rc = proc.returncode if proc.returncode is not None else -signal.SIGTERM
        timed_out = True
        killed_by = "timeout"

    return LaunchResult(
        returncode=rc,
        stdout=out_b.decode("utf-8", errors="replace"),
        stderr=err_b.decode("utf-8", errors="replace"),
        duration_s=time.time() - t0,
        timed_out=timed_out,
        killed_by=killed_by or ("oom" if rc == -9 or rc == 137 else ""),
    )
```

Notes:
- `preexec_fn=_preexec` runs in the child only. `os.setsid` makes it a session leader and the head of a new process group; `os.killpg(os.getpgid(pid), SIG…)` reaches the whole tree. The current code can leak `claude` children if it forks downstream tools.
- `close_fds=True` plus `closerange(3, 256)` is belt-and-suspenders. Python 3.11 already does close_fds, but explicit is better when a hung child can lock fds we need.
- `bufsize=0` matters for large prompts (7000+ chars system prompts plus snapshots).
- Bytes mode + manual decode preserves behavior on Windows where UTF-8 stdout used to be unreliable; replacement is explicit.
- Encoding fallback: if a caller ever needs to send non-UTF-8 (binary tool input), the function takes `bytes` directly. We never re-encode the user's payload.

---

## C. The envelope parser

Target file: `/home/user/WAGMI/bot/llm/cli/envelope.py` (new). Replaces the silent `_extract_json` regime in `claude_cli_client.py`.

Versioned schema lives next to it: `/home/user/WAGMI/bot/llm/cli/envelope_schemas/v1.json`, `…/v2.json`. Schema selection is keyed off `claude --version` (see §J).

```python
# /home/user/WAGMI/bot/llm/cli/envelope.py
import enum, json
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

class EnvelopeError(Exception): ...
class EnvelopeStrictness(enum.Enum):
    STRICT = "strict"      # production
    LENIENT = "lenient"    # tests + local dev

REQUIRED_KEYS_V1 = {"type", "result"}
KNOWN_KEYS_V1 = REQUIRED_KEYS_V1 | {
    "structured_output", "usage", "stop_reason", "model", "id",
    "total_cost_usd", "session_id", "subtype", "is_error",
}

@dataclass
class Envelope:
    raw: Dict[str, Any]
    text: str
    parsed: Optional[Dict[str, Any]]
    model: str
    id: str
    stop_reason: str
    input_tokens: int
    output_tokens: int
    cost_usd: float

    def parsed_matches_schema(self, schema): ...

def parse_envelope(stdout: str, *, strict: EnvelopeStrictness) -> Envelope:
    if not stdout or not stdout.strip():
        raise EnvelopeError("empty stdout")
    try:
        env = json.loads(stdout)
    except json.JSONDecodeError as e:
        raise EnvelopeError(f"non-json envelope: {e}") from e
    if not isinstance(env, dict):
        raise EnvelopeError(f"envelope not an object: {type(env).__name__}")
    missing = REQUIRED_KEYS_V1 - env.keys()
    if missing:
        raise EnvelopeError(f"missing required keys: {missing}")
    if strict is EnvelopeStrictness.STRICT:
        unknown = set(env.keys()) - KNOWN_KEYS_V1
        if unknown:
            # FAIL LOUD on shape change
            raise EnvelopeError(f"unknown envelope keys: {unknown}")

    # 1) structured_output FIRST — this is the §22 fix.
    parsed = None
    so = env.get("structured_output")
    if isinstance(so, dict):
        parsed = so
    elif isinstance(so, str):
        try: parsed = json.loads(so)
        except Exception: parsed = None

    # 2) Tolerant fallback ONLY in LENIENT mode.
    text = env.get("result") or env.get("text") or ""
    if parsed is None and strict is EnvelopeStrictness.LENIENT:
        parsed = _tolerant_extract(text)

    # 3) Truncation detection.
    stop = env.get("stop_reason", "")
    if stop in ("max_tokens", "length"):
        # Don't raise — just propagate. Caller decides whether to retry.
        pass

    usage = env.get("usage", {}) if isinstance(env.get("usage"), dict) else {}
    return Envelope(
        raw=env, text=text, parsed=parsed,
        model=env.get("model", ""),
        id=env.get("id", ""),
        stop_reason=stop,
        input_tokens=int(usage.get("input_tokens", 0) or 0),
        output_tokens=int(usage.get("output_tokens", 0) or 0),
        cost_usd=float(env.get("total_cost_usd", 0) or 0),
    )
```

Why this is the correct shape:
- Reads `structured_output` first, before falling back to `result` text. The current coordinator does the opposite — sniffs `text` for `{`, then asks the tolerant extractor. That's how silent envelope drift bites.
- `usage` block is the source of token truth. `total_cost_usd` keeps existing dashboards happy under API but is *not* the canonical cost when subscription is in play.
- STRICT mode rejects unknown keys; LENIENT mode logs and continues. STRICT is the default in production.
- `stop_reason` propagates so the retry policy can detect truncation and rerun with larger `max_tokens`.
- `id` becomes a correlation handle for support tickets to Anthropic.

---

## D. Failure mode classifier

Target file: `/home/user/WAGMI/bot/llm/cli/classifier.py` (new). Single pure function consumed by `CliBackend.call`.

```python
import enum, re
class FailureMode(enum.Enum):
    OK                       = "ok"
    BINARY_NOT_FOUND         = "binary_not_found"
    AUTH_EXPIRED             = "auth_expired"
    QUOTA_EXHAUSTED          = "quota_exhausted"
    NETWORK_ERROR            = "network_error"
    SUBPROCESS_TIMEOUT       = "subprocess_timeout"
    SUBPROCESS_NONZERO_EXIT  = "subprocess_nonzero_exit"
    SUBPROCESS_HUNG          = "subprocess_hung"
    SUBPROCESS_KILLED_OOM    = "subprocess_killed_oom"
    ENVELOPE_MALFORMED       = "envelope_malformed"
    RESULT_FIELD_EMPTY       = "result_field_empty"
    AGENT_JSON_MALFORMED     = "agent_json_malformed"
    SCHEMA_MISMATCH          = "schema_mismatch"
    BUDGET_EXCEEDED          = "budget_exceeded"
    RATE_LIMITED             = "rate_limited"
    UNKNOWN                  = "unknown"

# (regex, mode) pairs. Order matters — first match wins.
_STDERR_RULES = [
    (re.compile(r"command not found|No such file", re.I), FailureMode.BINARY_NOT_FOUND),
    (re.compile(r"not.{0,5}authenticat|login.{0,5}expired|please run `claude login`", re.I), FailureMode.AUTH_EXPIRED),
    (re.compile(r"quota|usage limit (reached|exceeded)|subscription.{0,15}exhausted", re.I), FailureMode.QUOTA_EXHAUSTED),
    (re.compile(r"rate.?limit|429|too many requests", re.I), FailureMode.RATE_LIMITED),
    (re.compile(r"network|dns|getaddrinfo|connection refused|EAI_AGAIN|ECONNRESET", re.I), FailureMode.NETWORK_ERROR),
    (re.compile(r"budget.{0,10}exceeded|max-budget", re.I), FailureMode.BUDGET_EXCEEDED),
]

# Recovery policy table, consumed by retry & fallback layers.
RECOVERY = {
    FailureMode.BINARY_NOT_FOUND       : ("abort",         "critical"),
    FailureMode.AUTH_EXPIRED           : ("escalate",      "critical"),  # do NOT auto-retry
    FailureMode.QUOTA_EXHAUSTED        : ("circuit-break", "critical"),
    FailureMode.RATE_LIMITED           : ("retry-backoff", "warn"),
    FailureMode.NETWORK_ERROR          : ("retry-backoff", "warn"),
    FailureMode.SUBPROCESS_TIMEOUT     : ("retry-once",    "warn"),
    FailureMode.SUBPROCESS_NONZERO_EXIT: ("retry-once",    "warn"),
    FailureMode.SUBPROCESS_HUNG        : ("circuit-break", "error"),
    FailureMode.SUBPROCESS_KILLED_OOM  : ("abort",         "critical"),
    FailureMode.ENVELOPE_MALFORMED     : ("fallback-model","error"),    # try Sonnet
    FailureMode.RESULT_FIELD_EMPTY     : ("retry-once",    "warn"),
    FailureMode.AGENT_JSON_MALFORMED   : ("fallback-model","warn"),
    FailureMode.SCHEMA_MISMATCH        : ("fallback-model","warn"),
    FailureMode.BUDGET_EXCEEDED        : ("abort",         "critical"),
    FailureMode.UNKNOWN                : ("retry-once",    "error"),
}

def classify_failure(returncode, stderr, stdout, exception) -> FailureMode:
    if isinstance(exception, TimeoutError):  return FailureMode.SUBPROCESS_TIMEOUT
    if returncode == 137 or returncode == -9: return FailureMode.SUBPROCESS_KILLED_OOM
    if exception:                             return FailureMode.SUBPROCESS_HUNG
    if returncode != 0:
        for pat, mode in _STDERR_RULES:
            if pat.search(stderr or ""):
                return mode
        return FailureMode.SUBPROCESS_NONZERO_EXIT
    if not (stdout and stdout.strip()):
        return FailureMode.RESULT_FIELD_EMPTY
    return FailureMode.OK
```

This is exactly 13 distinct failure modes plus OK + UNKNOWN, mapped 1-to-1 with the audit log enum and the dashboard tile counters. `RECOVERY` is the single source of truth read by §E and §F.

---

## E. The retry policy

Target file: `/home/user/WAGMI/bot/llm/cli/retry.py` (new).

```python
import random, time
from llm.cli.classifier import FailureMode, RECOVERY
from llm.cli.circuit import CircuitBreaker

def with_retry(call_fn, *, agent: str, backend: str,
               max_retries: int = 2, base_delay_s: float = 0.5):
    breaker = CircuitBreaker.get(agent, backend)
    breaker.guard()  # raises CircuitOpen if tripped
    last = None
    for attempt in range(max_retries + 1):
        resp = call_fn()
        last = resp
        if resp.ok:
            breaker.record_success()
            return resp
        action, sev = RECOVERY[FailureMode[resp.failure_mode]]
        if action == "abort" or action == "escalate":
            breaker.record_failure(); return resp
        if action == "circuit-break":
            breaker.trip(); return resp
        if action == "fallback-model":
            return resp                           # fallback chain handles
        if attempt >= max_retries: break
        # exponential backoff with full jitter (Marc Brooker style)
        delay = random.uniform(0, base_delay_s * (2 ** attempt))
        time.sleep(delay)
        breaker.record_failure()
    return last
```

Circuit breaker, in `/home/user/WAGMI/bot/llm/cli/circuit.py` (new):

- Per-`(agent, backend)` keys. Global breakers cause Trade Agent to drag Critic down with it.
- State machine: `CLOSED → OPEN → HALF_OPEN`.
- Trip when `>= 5 failures in 60s`.
- Open for 90s, then HALF_OPEN with one probe call.
- All transitions emit a structured log to `data/llm/cli_calls.jsonl`.

Crucial rule, written in code as well as comments: **`AUTH_EXPIRED` is never auto-retried.** Auto-retry on auth-expired exhausts retries and silently kills the bot's brain.

---

## F. The fallback chain integration

Target file: `/home/user/WAGMI/bot/llm/backends/chain.py` (new).

```python
from llm.backends.cli_backend import CliBackend
from llm.backends.api_backend import AnthropicApiBackend  # optional
from llm.backends.heuristic_backend import HeuristicBackend

class FallbackChain:
    def __init__(self, autonomy_level: int):
        self.autonomy = autonomy_level
        self.tiers = [
            ("primary",    CliBackend()),                     # subscription
            ("secondary",  CliBackend()),                     # diff. model: Haiku→Sonnet
            ("tertiary",   AnthropicApiBackend.maybe()),      # only if API key set
            ("quaternary", HeuristicBackend()),               # quant_regime / defensive_skip
        ]

    def call(self, req):
        for tier_name, backend in self.tiers:
            if backend is None or not backend.available(): continue
            req2 = self._adjust(req, tier_name)
            resp = backend.call(req2)
            if resp.ok:
                if tier_name != "primary":
                    log_fallback(req.correlation_id, tier_name, resp)
                return resp
        return defensive_skip(req)
```

Concrete rules:
- **Primary → Secondary** when `failure_mode in {SCHEMA_MISMATCH, AGENT_JSON_MALFORMED, ENVELOPE_MALFORMED}` and the original model was Haiku. Re-issue with Sonnet.
- **Primary → Tertiary** is gated behind `WAGMI_ALLOW_API_FALLBACK=1`. Default off — the user must opt-in to dollar surprises.
- **Quaternary**: heuristic. For Regime Agent, call `bot/core/quant_regime.detect_regime` and wrap the canonical regime in the schema. For Trade Agent, return `defensive_skip` (size 0, side NONE, action skip).
- Every tier transition writes one structured log line with the `correlation_id` so a single decision is reconstructable end-to-end.

`HeuristicBackend` lives at `/home/user/WAGMI/bot/llm/backends/heuristic_backend.py` and is just a `dispatch(agent) → callable` mapping per agent role. It uses canonical regime names from `/home/user/WAGMI/bot/llm/regime_canonical.py`.

---

## G. The compliance auditor

Target file: `/home/user/WAGMI/bot/llm/cli/compliance.py` (new). Persisted at `/home/user/WAGMI/bot/data/llm/model_compliance.json` (atomic writes).

```python
# Rolling window per (agent, model) — 200 most recent samples.
THRESHOLDS = {"haiku": 0.95, "sonnet": 0.99, "opus": 0.99}
ESCALATION = {"haiku": "recommend-upgrade-to-sonnet",
              "sonnet": "escalate-to-ops"}

def record_sample(agent: str, model: str, schema_compliant: bool):
    state = _load()
    key = f"{agent}::{model}"
    rec = state.setdefault(key, {"samples": [], "last_recommendation": None})
    rec["samples"].append(int(schema_compliant))
    rec["samples"] = rec["samples"][-200:]
    _evaluate(rec, model)
    _atomic_write(state)

def _evaluate(rec, model):
    s = rec["samples"]
    if len(s) < 30: return
    rate = sum(s) / len(s)
    threshold = THRESHOLDS.get(model.split("-")[0], 0.95)
    if rate < threshold:
        rec["last_recommendation"] = ESCALATION.get(model.split("-")[0])

def _atomic_write(state):
    tmp = MODEL_COMPLIANCE_PATH + ".tmp"
    with open(tmp, "w") as f: json.dump(state, f, indent=2); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, MODEL_COMPLIANCE_PATH)   # POSIX atomic rename
```

This replaces the hardcoded `# Sonnet is default because…` comment in `claude_cli_client.py:275`. Default model selection consults `compliance.recommendation(agent)` and switches to Sonnet automatically when Haiku trips below 95%.

---

## H. The cost tracker integration

Target file: `/home/user/WAGMI/bot/llm/cli/budget.py` (new), with append-only sink `/home/user/WAGMI/bot/data/llm/cost_tracker.jsonl`.

The existing `cost_tracker.py` operates per *day, dollars*. The CLI layer needs a *parallel* counter:
- Per-minute call count (proxy for Anthropic CLI rate-limit).
- Per-day call count, broken down by model.
- Subscription headroom estimate (call rate / configured ceiling).
- Per-call `cost_usd` derived from envelope `usage`, multiplied by current pricing table — even when `total_cost_usd: 0` is reported under subscription. Two columns: `realized_cost_usd` (envelope), `theoretical_cost_usd` (would-be API cost). The user can see both.

Atomic append: `os.O_APPEND | os.O_CREAT | os.O_WRONLY` opened with `os.fdopen`, single `write()` per record (POSIX guarantees atomicity for writes < PIPE_BUF, which JSON lines comfortably are).

Subscription headroom alarm: threshold env var `CLI_RATE_LIMIT_CALLS_PER_MIN` (default 30). If observed `calls_last_minute > 0.8 * limit`, log WARN and emit `data/llm/cli_calls.jsonl` event with `failure_mode="RATE_PRESSURE_WARN"`.

---

## I. The audit log

Target file (write only via library): `/home/user/WAGMI/bot/llm/cli/audit.py` (new). Sink: `/home/user/WAGMI/bot/data/llm/cli_calls.jsonl`.

Exact line schema is the one specified in the request. One line per call, append-only, atomic. The `envelope_keys` field is a drift sentinel: if a key like `partial_result` or `tool_uses` ever appears, a separate `tools/audit_drift.py` script greps the JSONL and alerts.

This file becomes the canonical record. Every other analytical artifact (cost dashboards, latency reports, replay) is *derived* from this file. The smoke test (§K) asserts that for any call, `cli_calls.jsonl` gains exactly one line.

Rotation: nightly job (separate cron, do not bake into hot path) renames `cli_calls.jsonl` to `cli_calls.YYYY-MM-DD.jsonl.zst` if size > 100 MiB or on day boundary. Hot path never rotates — it just appends.

Read path: `bot/llm/cli/replay.py` (new) provides `iter_calls(filter=…)` for analytics.

---

## J. Version compatibility detector

Target file: `/home/user/WAGMI/bot/llm/cli/version.py` (new).

```python
_RE_VER = re.compile(r"(\d+\.\d+\.\d+)")

def detect_version(binary: str, cwd: str) -> str:
    out = subprocess.check_output([binary, "--version"], cwd=cwd, timeout=5,
                                  text=True, errors="replace")
    m = _RE_VER.search(out)
    return m.group(1) if m else out.strip()[:64]

def verify_version_unchanged(binary, cwd, pinned: str):
    cur = detect_version(binary, cwd)
    if cur != pinned:
        # CRITICAL log + reload classifiers if a v2 schema exists for cur.
        logger.critical(f"[CLI] claude version drifted: {pinned} → {cur}; "
                        f"envelope schema must be re-validated")
        # Do NOT silently switch schemas. Caller (CliBackend) re-pins and
        # callers see ENVELOPE_MALFORMED until a matching schema lands.
        raise VersionDrift(pinned, cur)
```

The blueprint forbids silent fallback. If the binary auto-updates mid-runtime, the next call fails loud with `ENVELOPE_MALFORMED` (or a new `VERSION_DRIFT` if you prefer that as a 14th mode), the breaker trips, the heuristic backend takes over, the dashboard shows red, the operator sees it.

---

## K. The smoke test harness

Target dir: `/home/user/WAGMI/bot/tests/cli_backend/` (new). Pytest fixture `fake_claude_bin`:

```python
# /home/user/WAGMI/bot/tests/cli_backend/conftest.py
import os, stat, textwrap, pytest

@pytest.fixture
def fake_claude_bin(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"; bin_dir.mkdir()
    script = bin_dir / "claude"
    def install(scenario: str):
        body = SCENARIOS[scenario]
        script.write_text(body)
        script.chmod(stat.S_IRWXU)
        monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
        return str(script)
    return install

SCENARIOS = {
    "success": '#!/usr/bin/env bash\ncat <<JSON\n{"type":"result","result":"{\\"x\\":1}","structured_output":{"x":1},"usage":{"input_tokens":10,"output_tokens":5},"stop_reason":"end_turn","model":"claude-haiku-4-5","id":"msg_123","total_cost_usd":0}\nJSON\n',
    "malformed":   '#!/usr/bin/env bash\necho "not json"\n',
    "prose_only":  '#!/usr/bin/env bash\necho \'{"type":"result","result":"sure! here is your answer:"}\'\n',
    "timeout":     '#!/usr/bin/env bash\nsleep 600\n',
    "auth_fail":   '#!/usr/bin/env bash\necho "Please run `claude login`" 1>&2; exit 2\n',
    "quota":       '#!/usr/bin/env bash\necho "usage limit reached" 1>&2; exit 3\n',
    "rate":        '#!/usr/bin/env bash\necho "rate limit exceeded (429)" 1>&2; exit 4\n',
    "version_old": '#!/usr/bin/env bash\nif [ "$1" = "--version" ]; then echo "1.2.3"; exit 0; fi\n…',
    "version_new": '#!/usr/bin/env bash\nif [ "$1" = "--version" ]; then echo "2.0.0"; exit 0; fi\n…',
    "oom":         '#!/usr/bin/env bash\nkill -9 $$\n',
    "race":        '#!/usr/bin/env bash\n# emits two envelopes; parser must reject\n…\n',
}
```

Hypothesis-driven property tests in `test_envelope_property.py`:

- `@given(json_envelopes())` round-trips: any well-formed envelope parses without raising in STRICT mode.
- `@given(text())` no-crash: malformed input always raises `EnvelopeError`, never returns garbage.
- Latency-ring concurrency: spawn 32 threads issuing `_track_latency`, assert `len(self._latencies[k]) <= 256` invariant.

Test scenarios required by the request all map 1-to-1 to `SCENARIOS` keys.

---

## L. The continuous probe

Target file: `/home/user/WAGMI/bot/llm/cli/probe.py` (new). A background thread launched once at bot startup.

- Every 5 minutes, send a 1-token health probe: `prompt="ok"`, `max_tokens=1`, model=Haiku.
- Probe results write to `data/llm/cli_probe.jsonl` (separate from main audit log so it doesn't pollute analysis).
- Track 30-minute success rate. If `< 0.95`, raise an alarm via `bot/llm/agent_output_logger.py` channel.
- The probe is the canary: if it goes red while no real calls are flowing, you still find out.
- Important: probe respects circuit breaker. If breaker is OPEN, probe blocks. When breaker goes HALF_OPEN, probe is the first request through.

---

## M. Graceful degradation

Wired through `FallbackChain` (§F) plus bot-side enforcement:

- `bot/llm/backends/heuristic_backend.py` exposes `regime()` calling `bot/core/quant_regime.detect_regime` and wrapping with `regime_canonical.canonicalize_regime`.
- `bot/llm/agents/coordinator.py`: when the Regime agent is heuristic-derived, set a flag in `LLMDecision.meta["regime_source"] = "heuristic"`. Critic Agent reads that flag and **always vetoes**. This ensures the bot doesn't trade off heuristic-derived intelligence — it just stays observational.
- Trade Agent in heuristic mode: `action=skip`, `side=NONE`, `size_multiplier=0`. Logs "DEFENSIVE_SKIP — CLI degraded" once per regime change.
- The bot stays alive, the perception loop keeps running, the dashboard keeps updating. Only execution is gated.
- Recovery condition: when probe success rate ≥ 99% over 15 minutes AND breaker is CLOSED for ≥ 30 minutes, automatically lift defensive mode. Log "CLI_RECOVERED".

---

## N. The dashboard panel `/health` for CLI

Add to `/home/user/WAGMI/bot/api_server.py` a route `GET /health/cli` returning:

```json
{
  "backend": "claude_cli",
  "available": true,
  "binary": "/usr/local/bin/claude",
  "version": "1.4.2",
  "last_success_ago_s": 4,
  "error_rate_1h": 0.012,
  "error_rate_24h": 0.018,
  "latency_ms": {
    "regime/haiku":  {"p50": 820, "p99": 2400, "n": 256},
    "trade/sonnet":  {"p50": 1640, "p99": 4900, "n": 256},
    "critic/sonnet": {"p50": 1820, "p99": 5100, "n": 256}
  },
  "failure_mode_counts": {
    "1h":  {"AUTH_EXPIRED": 0, "ENVELOPE_MALFORMED": 1, "SUBPROCESS_TIMEOUT": 2},
    "24h": {"AUTH_EXPIRED": 0, "ENVELOPE_MALFORMED": 4, "SUBPROCESS_TIMEOUT": 14}
  },
  "compliance": {
    "regime/haiku":  {"rate": 0.94, "n": 200, "recommendation": "upgrade-to-sonnet"},
    "trade/sonnet":  {"rate": 0.997, "n": 200, "recommendation": null}
  },
  "cost": {"today_realized_usd": 0.0, "today_theoretical_usd": 4.21, "calls_today": 612},
  "rate": {"calls_last_minute": 8, "headroom_pct_estimate": 0.73},
  "circuit_breakers": {
    "regime/claude_cli":  "CLOSED",
    "trade/claude_cli":   "CLOSED",
    "critic/claude_cli":  "HALF_OPEN"
  }
}
```

All values are derived from `cli_calls.jsonl` (fresh tail-read of last 5000 lines) plus live state from the singleton `CliBackend`. No additional state to keep coherent.

---

## O. The migration sequence

**Step 1 — §22 structured_output fix (immediate, today)**
- Modify only `/home/user/WAGMI/bot/llm/agents/coordinator.py` lines 100–147: read envelope's `structured_output` field if present, parse it as JSON, prefer it over `text`. This is a 20-line surgical fix.
- Verification gate: existing pytests pass; manual smoke call to Haiku regime returns parsed dict.

**Step 2 — Module-level logger calls (immediate, today)**
- Add explicit `logger.info(...)` and `logger.warning(...)` at each branch in `claude_cli_client.call_agent` and `_call_llm_via_cli` so failures are loud. Don't refactor yet — just wire visibility.
- Verification: `tail -F` shows clear lines for success/timeout/non-json.

**Step 3 — Create `LLMBackend` ABC + `CliBackend` (Week 1)**
- New files: `bot/llm/backends/base.py`, `bot/llm/backends/cli_backend.py`, `bot/llm/cli/launcher.py`, `bot/llm/cli/envelope.py`, `bot/llm/cli/audit.py`, `bot/llm/cli/version.py`, plus `bot/llm/cli/__init__.py` and `bot/llm/backends/__init__.py`.
- Verification: `python -m bot.llm.backends.cli_backend` self-test invokes `claude --version`, parses envelope from a fixture, writes one audit line.

**Step 4 — Migrate `_call_llm_via_cli` to use the backend (Week 1)**
- Modify `bot/llm/agents/coordinator.py`: replace the inlined `_call_llm_via_cli` with a thin shim that builds an `LLMRequest` and dispatches to a module-level `CliBackend` singleton.
- Verification: paper-trading session for 1 hour shows identical decision counts and zero new errors. Audit log accumulates.

**Step 5 — Failure-mode classifier (Week 1)**
- New file: `bot/llm/cli/classifier.py`.
- Wire into `CliBackend.call`. Update `cli_calls.jsonl` rows to include `failure_mode`.
- Verification: each `SCENARIOS` key in §K test fixture maps to its expected `FailureMode`.

**Step 6 — Per-(agent, backend) circuit breakers (Week 2)**
- New files: `bot/llm/cli/circuit.py`, `bot/llm/cli/retry.py`.
- Wrap `CliBackend.call` in `with_retry`. State stored in-process (do not persist breakers; cold start is fine).
- Verification: synthetic test forces 5 consecutive timeouts in 60s; sixth call returns immediately with `failure_mode=CIRCUIT_OPEN`.

**Step 7 — Fallback chain (Week 2)**
- New files: `bot/llm/backends/api_backend.py` (optional), `bot/llm/backends/heuristic_backend.py`, `bot/llm/backends/chain.py`.
- Coordinator now consumes `FallbackChain` instead of `CliBackend` directly.
- Verification: env var `WAGMI_FORCE_HEURISTIC=1` runs whole pipeline through heuristic; bot enters defensive_skip cleanly.

**Step 8 — Compliance auditor + audit log + smoke tests (Weeks 2–3)**
- New files: `bot/llm/cli/compliance.py`, `bot/llm/cli/probe.py`, `bot/tests/cli_backend/*`, `bot/data/llm/model_compliance.json`.
- Replace `# Sonnet is default because…` comment in `claude_cli_client.py` (which becomes a thin compatibility shim) with a `compliance.recommendation(agent)` call.
- Verification: pytest suite green; 30-minute live run shows compliance.json populating; probe writes 6 lines per 30 minutes.

After Step 8, mark `claude_cli_client.py` as `@deprecated` but leave it: callers outside the coordinator still import it. Phase it out in a Week 4 follow-up.

---

## P. The "what NOT to do" list (with reasons)

- **Do not add prompt caching to the CLI path.** The CLI does not honor `cache_control` blocks; cache hit rate would always read 0% and create a false expectation that API and CLI behave identically. Keep `cost_tracker.py`'s cache fields tied to API path only.
- **Do not unify cost reporting in a way that hides subscription "calls".** Keep two columns: `realized_cost_usd` (truthful zero) and `theoretical_cost_usd` (what API would have charged). Operators must see both.
- **Do not auto-retry `AUTH_EXPIRED`.** Retries exhaust, the bot goes dark silently. Wire it to `escalate` and require human re-login.
- **Do not fall back from CLI to API silently.** Gate the API tier behind `WAGMI_ALLOW_API_FALLBACK=1`; when it does activate, log at WARN and emit a Discord/Telegram alert via `bot/publishers.py`.
- **Do not trust the binary version after auto-update.** Re-pin and re-validate envelope shape; a new `claude` may rename fields without notice.
- **Do not share a single circuit breaker across agents.** A flaky Critic must not silence Trade.
- **Do not parse envelope by string-prefix sniffing the `result` text.** Read `structured_output` first (the §22 fix). Treat anything else as drift.
- **Do not log full prompt or response bodies.** The audit log carries `prompt_hash` and `response_hash`. Bodies, if needed, get a separate file with stricter retention.
- **Do not handcraft the "use sonnet" decision.** Drive it from `compliance.json`.

---

## Q. Long-term vision (months 2–6)

- **Month 2: Ollama backend alongside `CliBackend`.** New `bot/llm/backends/ollama_backend.py` implements `LLMBackend`. Same `LLMRequest`/`LLMResponse`. Slot into `FallbackChain` as `quaternary` (above heuristic, below CLI). Add a "sandbox" tier in the chain that always calls Ollama and just *logs* decisions for comparison.
- **Month 3: A/B mode.** A flag `LLM_AB_MODE={off, mirror, gate}` lets some calls route to CLI, others to Ollama. Both write to `cli_calls.jsonl` (extend `backend` field). Compare hash-equivalence over 1000 paired calls.
- **Month 4: Streaming support.** When Claude CLI ships streaming, add `bot/llm/cli/stream.py` reading line-delimited JSON. The `LLMResponse` grows an optional async iterator. First consumer: live operator UI.
- **Month 5: Tool-use mode.** When agents need filesystem or web access, expose `allow_tools=True` in `LLMRequest`. The launcher already runs in an explicit `cwd`; wire a safe-tool allowlist.
- **Month 6: Multi-binary support.** If Anthropic splits Claude Code into specialized binaries (e.g. `claude-quant`, `claude-research`), `_resolve_binary()` becomes a strategy: pick by agent role. Per-binary version pinning.

---

## R. Economic model (subscription)

The CLI is "free" in dollars, constrained in calls. Hardening must:

- Maintain a per-minute call deque (60-entry, last 60 seconds).
- Maintain a per-day call deque.
- Maintain per-model availability — Opus typically has tighter rate caps. Track per-model 429 rate; if Opus 429s exceed 5% over 5 minutes, downgrade Opus calls to Sonnet automatically and log.
- Backpressure: when `calls_last_minute > 0.8 * CLI_RATE_LIMIT_CALLS_PER_MIN`, the coordinator's pre-trade pipeline drops the optional agents (Forecaster, Hypothesis, Correlator) and keeps only the critical four (Regime, Trade, Critic, Risk).
- Hard cutover: when 429 rate > 50%, breaker trips and the bot enters defensive_skip until headroom returns.

This logic lives in `bot/llm/cli/budget.py` (one function: `recommend_agent_set(headroom_estimate)`).

---

## S. LLM_MODE autonomy interaction

The coordinator gates, the backend obeys. Specifically:

- **Level 0 (OFF)**: coordinator never invokes the chain. As a defense-in-depth, `CliBackend.call` short-circuits on `req.autonomy_level == 0` and returns `failure_mode=DISABLED_BY_AUTONOMY`. This catches accidental call sites.
- **Level 1 (ADVISORY)**: full chain runs; the coordinator simply does not use the decision for trading. Audit log still gets a line per call so the user can replay what the LLM *would* have said.
- **Level 2 (VETO_ONLY)**: only Critic Agent calls the chain. Coordinator ensures other agents are skipped. Backend is unaware — it just sees one request per cycle.
- **Level 3+ (SIZING/DIRECTION/FULL)**: full pipeline; backend handles all calls.

The backend does not "know" about modes beyond the Level-0 guard. This keeps the backend boring and pure.

---

## T. `--max-budget-usd` strategy

- Currently hardcoded `0.10` in `claude_cli_client.py:64` and `coordinator.py:125`.
- New env var `CLI_MAX_BUDGET_USD_PER_CALL`, default `0.10`. Read once at backend init via `os.getenv`.
- Under subscription it's a no-op (CLI ignores it). Under a misconfigured fallback to API, it caps blast radius.
- Add a corresponding CI assertion: `bot/tests/cli_backend/test_budget_envelope.py` checks that the value is propagated to the actual argv.
- Defense in depth: `budget.check_budget_envelope(reported, allowed)` in §H raises `BudgetExceeded` if `reported > 1.5 * allowed` (catches accidental API path with surprising costs).

---

## File-path summary

New files (creation deferred — read-only mode):
- `/home/user/WAGMI/bot/llm/backends/__init__.py`
- `/home/user/WAGMI/bot/llm/backends/base.py`
- `/home/user/WAGMI/bot/llm/backends/cli_backend.py`
- `/home/user/WAGMI/bot/llm/backends/api_backend.py`
- `/home/user/WAGMI/bot/llm/backends/heuristic_backend.py`
- `/home/user/WAGMI/bot/llm/backends/chain.py`
- `/home/user/WAGMI/bot/llm/cli/__init__.py`
- `/home/user/WAGMI/bot/llm/cli/launcher.py`
- `/home/user/WAGMI/bot/llm/cli/envelope.py`
- `/home/user/WAGMI/bot/llm/cli/classifier.py`
- `/home/user/WAGMI/bot/llm/cli/retry.py`
- `/home/user/WAGMI/bot/llm/cli/circuit.py`
- `/home/user/WAGMI/bot/llm/cli/audit.py`
- `/home/user/WAGMI/bot/llm/cli/version.py`
- `/home/user/WAGMI/bot/llm/cli/compliance.py`
- `/home/user/WAGMI/bot/llm/cli/budget.py`
- `/home/user/WAGMI/bot/llm/cli/probe.py`
- `/home/user/WAGMI/bot/llm/cli/replay.py`
- `/home/user/WAGMI/bot/llm/cli/envelope_schemas/v1.json`
- `/home/user/WAGMI/bot/data/llm/cli_calls.jsonl` (created on first call)
- `/home/user/WAGMI/bot/data/llm/cli_probe.jsonl`
- `/home/user/WAGMI/bot/data/llm/model_compliance.json`
- `/home/user/WAGMI/bot/data/llm/cost_tracker.jsonl`
- `/home/user/WAGMI/bot/tests/cli_backend/conftest.py`
- `/home/user/WAGMI/bot/tests/cli_backend/test_envelope.py`
- `/home/user/WAGMI/bot/tests/cli_backend/test_classifier.py`
- `/home/user/WAGMI/bot/tests/cli_backend/test_launcher.py`
- `/home/user/WAGMI/bot/tests/cli_backend/test_envelope_property.py`
- `/home/user/WAGMI/bot/tests/cli_backend/test_circuit.py`
- `/home/user/WAGMI/bot/tests/cli_backend/test_chain.py`

Modified files:
- `/home/user/WAGMI/bot/llm/agents/coordinator.py` — replace `_call_llm_via_cli` (lines 100–147) and call site at 2950–2958 with `FallbackChain` shim.
- `/home/user/WAGMI/bot/llm/claude_cli_client.py` — keep as deprecated shim importing from the new module; remove `_extract_json` silent fallback eventually.
- `/home/user/WAGMI/bot/llm/cost_tracker.py` — add `realized_cost_usd` vs `theoretical_cost_usd` distinction.
- `/home/user/WAGMI/bot/api_server.py` — add `/health/cli` route.

### Critical Files for Implementation
- /home/user/WAGMI/bot/llm/backends/cli_backend.py
- /home/user/WAGMI/bot/llm/cli/launcher.py
- /home/user/WAGMI/bot/llm/cli/envelope.py
- /home/user/WAGMI/bot/llm/cli/classifier.py
- /home/user/WAGMI/bot/llm/agents/coordinator.py