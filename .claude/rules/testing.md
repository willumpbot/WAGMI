# Testing Rules

## Test Structure
Tests live in `bot/tests/` with 20 test files covering:
- Phase-based tests (test_phase2.py through test_phase_l.py)
- E2E pipeline tests (test_e2e_phases.py)
- Safety tests (test_execution_safety.py, test_ops_guard.py)
- Feedback loop tests (test_feedback_loop.py, test_feedback_closers.py)
- Ensemble weight tests (test_ensemble_weights.py)
- Self-teaching tests (test_self_teaching.py)
- Serialization tests (test_serializers.py)
- Stability tests (test_stability_fixes.py)
- Stress tests (test_stress.py)
- PnL math tests (test_pnl_math.py)

## Running Tests
```bash
cd bot && pytest tests/                    # All tests
cd bot && pytest tests/ -k "agent"         # Agent-related tests
cd bot && pytest tests/ -k "safety"        # Safety tests
cd bot && pytest tests/ -x                 # Stop on first failure
cd bot && pytest tests/ -v                 # Verbose output
```

## Rules
- NEVER skip tests to make a PR pass
- After modifying ANY execution/risk code, run the full suite
- After modifying agent prompts, run agent-specific tests
- New features MUST include tests (at minimum, smoke tests)
- Mock external dependencies (exchange APIs, LLM calls) in tests
- Use `bot/llm/test_harness.py` for deterministic LLM testing
- Test both happy path AND error paths (API failure, parse failure, circuit breaker)
