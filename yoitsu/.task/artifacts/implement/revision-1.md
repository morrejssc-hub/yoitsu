Let me provide a final summary of all fixes:

## Summary of Code Review Fixes

**All 4 high/medium issues fixed + 1 open question addressed:**

### Issue 1 (High): Wired params through reviewer to observation_context
- **File**: `palimpsest/evo/roles/reviewer.py`
- Changed `reviewer_role(**params)` to extract `window_hours`, `metric_type`, `trigger_role` from params
- Passes these to `observation_context` config instead of hardcoding `window_hours: 24`

### Issue 2 (High): Fixed ReviewProposal.to_trigger_data() data loss
- **File**: `yoitsu-contracts/src/yoitsu_contracts/review_proposal.py`
- Added `team` field to `TaskTemplate` model (defaults to "default")
- Merged `task_template.params` into output params (task template params can override base params)
- Uses `task_template.team` instead of hardcoding `"default"`

### Issue 3 (Medium): Removed non-existent Pasloe endpoint calls
- **File**: `palimpsest/evo/contexts/loaders.py`
- Removed calls to `/observation/preparation_failure` and `/observation/tool_retry`
- Pasloe only implements `/observation/budget_variance` routes
- Added `role` and `metric_type` parameters to `observation_context` provider

### Issue 4 (Medium): Fixed tests to exercise real implementation
- **File**: `palimpsest/tests/test_observation_context.py`
- Rewrote to load provider via `resolve_context_functions(EVO_ROOT, ["observation_context"])`
- Mocks `httpx.Client` at global level
- Added 10 tests covering: provider loading, window_hours, role filter, metric_type, by_role breakdown

### Issue 5 (Open question): Fixed JSON parsing inconsistency
- **File**: `yoitsu-contracts/src/yoitsu_contracts/review_proposal.py`
- Updated `from_json_str()` to extract JSON from markdown code blocks (` ```json ... ``` `)
- Also handles plain code blocks and JSON embedded anywhere in text
- Added 3 tests for markdown parsing scenarios

### Additional fixes:
- **File**: `palimpsest/evo/prompts/reviewer.md`
- Added `team` field to task_template output format and example

**All tests passing:**
```
yoitsu-contracts: 18 passed
palimpsest: 10 passed  
trenni: 13 passed
```