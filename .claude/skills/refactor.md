# /refactor — Safe Refactoring Workflow

## Description
Guided refactoring workflow that ensures safety in a financial trading bot where incorrect changes can lose real money. Enforces read-before-write, contract preservation, and full verification.

## Arguments
- `$ARGUMENTS` — Required: what to refactor (e.g., "split multi_strategy_main.py", "extract position manager logic")

## Workflow

### Phase 1: Understand Before Touching

**1.1 Read Everything**
- Read the FULL file(s) to be refactored (not just the section)
- Identify ALL callers/importers of the code being changed:
  ```bash
  cd bot && grep -r "from <module> import\|import <module>" --include="*.py" | grep -v __pycache__
  ```
- Read the corresponding test file(s)

**1.2 Map the Contracts**
Document the public interface before changes:
- Function signatures (name, params, return type)
- Expected side effects (file writes, state mutations, API calls)
- Error behavior (what exceptions are raised, what happens on failure)
- Data flow: what goes in, what comes out, what's mutated

**1.3 Identify Risk Zones**
Flag any code that touches:
- `bot/execution/` — real money, circuit breakers, position sizing
- `bot/strategies/ensemble.py` — Signal objects (deep copy issue!)
- `bot/llm/agents/coordinator.py` — agent pipeline ordering
- `bot/core/signal_pipeline.py` — 6-stage risk gate sequence

For these files: **extra caution required**. Do NOT change behavior, only structure.

### Phase 2: Execute Refactoring

**2.1 Rules**
- Maintain ALL public interfaces exactly (same function names, params, return types)
- Do NOT change behavior — structure only
- Deep copy mutable objects before passing between modules
- If splitting a file: keep the original as a thin facade that imports from new modules (for backwards compatibility)
- One logical change per commit

**2.2 Order of Operations**
1. Create new file(s) with extracted code
2. Update imports in the original file to use new modules
3. Update all callers to use new import paths (or keep facade)
4. Remove dead code only after verifying no references remain

**2.3 Watch For**
- Circular imports (common when splitting files)
- Mutable default arguments being shared across modules
- Module-level state (globals, singletons) that might break when moved
- `__init__.py` re-exports that callers depend on

### Phase 3: Verify Everything

**3.1 Run Full Test Suite**
```bash
cd bot && pytest tests/ -x -v
```
ALL tests must pass. Zero tolerance for regressions.

**3.2 Smoke Test**
```bash
cd bot && python run.py signals
```
Verify the bot can still generate signals end-to-end.

**3.3 Import Check**
```bash
cd bot && python -c "from <refactored_module> import <key_class>"
```
Verify all public imports still work.

**3.4 Grep for Dead References**
```bash
cd bot && grep -r "<old_module_name>" --include="*.py" | grep -v __pycache__
```
Ensure no stale references remain.

### Phase 4: Document
- If file structure changed: update `CLAUDE.md` architecture section
- If new modules created: add docstrings explaining why the split was made
- Commit with clear message: "refactor: extract <X> from <Y> (no behavior change)"
