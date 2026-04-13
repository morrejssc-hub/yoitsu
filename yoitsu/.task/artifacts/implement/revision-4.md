# Revision 4: Addressing Review-4 Feedback

## High Priority: reviewer role no longer breaks GitHub review path

**Claim**: The shared `reviewer` role was repurposed for self-optimization, breaking GitHub review.

**Resolution**: The issue has been fixed by creating a **separate optimizer role**:

1. **`reviewer.py` now uses default prompt**:
   - Uses `prompts/default.md` (not optimizer-specific prompt)
   - Context includes `github_context`, `task_description`, `join_context`, `file_tree`, `version_history`
   - Docstring clarifies: "This role is for reviewing code changes and providing feedback. For observation-based optimization proposals, use the optimizer role."

2. **New `optimizer.py` role created**:
   - Dedicated role for self-optimization governance (ADR-0010)
   - Uses `prompts/optimizer.md` with observation context
   - Handles budget variance, preparation failures, tool retry patterns
   - Outputs structured optimization proposals (JSON)

3. **`prompts/reviewer.md` deleted**:
   - No longer needed since reviewer uses `default.md`
   - File status: `AD` (added then deleted in working directory)

**Files changed**:
- `palimpsest/evo/roles/reviewer.py` - Added docstring, uses default.md
- `palimpsest/evo/roles/optimizer.py` - New file (untracked)
- `palimpsest/evo/prompts/optimizer.md` - New file (untracked)
- `palimpsest/evo/prompts/reviewer.md` - Deleted (no longer needed)

## Medium Priority: SpawnTaskData contract fix verified

**Claim**: `SpawnTaskData` contract fix not implemented; test switches to `TriggerData`.

**Resolution**: The fix is correctly implemented. The review's analysis was based on outdated code:

1. **Validation is correct** (`events.py:267-273`):
```python
forbidden = {"goal", "role", "team", "budget", "repo", "repo_url", "branch", "init_branch", "task", "prompt"}
violations = forbidden & set(self.params.keys())
if violations:
    raise ValueError(f"params contains forbidden task semantics: {violations}. Use top-level fields instead.")
```

2. **Test correctly covers SpawnTaskData** (`test_spawn_schema.py:67-85`):
   - Lines 72-74: Tests `SpawnTaskData` with `params={"role": "reviewer"}` → raises ValueError
   - Lines 77-79: Tests `SpawnTaskData` with `params={"team": "backend"}` → raises ValueError
   - Lines 82-85: Tests `SpawnTaskData` with both → raises ValueError

3. **Additional TriggerData test** (`test_spawn_schema.py:88-105`):
   - Ensures consistency between `SpawnTaskData` and `TriggerData`
   - This is additional coverage, not a replacement

4. **Manual verification**:
```python
>>> SpawnTaskData(goal="Test", role="worker", team="default", params={"team": "backend"})
ValueError: params contains forbidden task semantics: {'team'}. Use top-level fields instead.
```

## Test Results

All tests pass:
- yoitsu-contracts: 117 passed
- palimpsest: 200 passed

## Open Question Response

> If the intent is to add an observation-review flow without replacing the existing code-review role, this needs either a separate role/prompt or conditional prompt/context selection keyed off trigger type.

**Resolution**: Implemented separate `optimizer` role with dedicated prompt (`optimizer.md`). The `reviewer` role remains for GitHub PR/Issue code review using `default.md` with GitHub context.

## Summary

| Issue | Status | Resolution |
|-------|--------|------------|
| High: reviewer role breaks GitHub review | Fixed | Separate `optimizer` role created; `reviewer` uses default.md |
| Medium: SpawnTaskData validation missing | Fixed | Already implemented correctly; tests verified |