# Prompt: Safe Refactoring Checklist

When refactoring any part of the trading bot:

## Before Starting
- [ ] Read the FULL file(s) you're modifying (don't guess at structure)
- [ ] Identify all callers of the code you're changing (grep for function/class names)
- [ ] Check if the code is tested (grep test files for references)
- [ ] Understand the data flow: what comes in, what goes out, who consumes it

## During Refactoring
- [ ] Maintain all existing public interfaces (function signatures, return types)
- [ ] If changing interfaces, update ALL callers
- [ ] Don't break the Signal dataclass contract (strategies depend on it)
- [ ] Don't break the LLMDecision contract (coordinator and decision_engine depend on it)
- [ ] Don't remove safety checks (risk gates, circuit breakers, validation)
- [ ] Deep copy mutable objects before passing between modules
- [ ] Keep error handling — don't let exceptions propagate to the main loop

## After Refactoring
- [ ] Run full test suite: `cd bot && pytest tests/`
- [ ] If touching execution code: verify paper trading still works
- [ ] If touching LLM code: verify multi-agent pipeline still works
- [ ] If touching strategies: verify ensemble voting still works
- [ ] Check for regressions in decision logging
- [ ] Update documentation if interfaces changed
