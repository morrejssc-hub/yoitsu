## Summary of Fixes

All 4 issues from the review feedback are now fixed:

### Issue 1 (High) - observation_context routes based on metric_type
**File**: `palimpsest/evo/contexts/loaders.py`
- Changed: `observation_context` now routes based on `metric_type`
- `metric_type=None` or `"budget_variance"` → queries budget_variance endpoints
- `metric_type="preparation_failure"` or `"tool_retry"` → shows message that endpoint not yet implemented (Pasloe only has budget_variance routes)

### Issue 2 (Medium) - from_json_str finds last valid JSON
**File**: `yoitsu-contracts/src/yoitsu_contracts/review_proposal.py`
- Changed: Now uses 3 strategies in order:
  1. Find ALL code blocks → try from LAST one first
  2. Parse entire string as raw JSON
  3. Find balanced JSON objects using brace counting → try from END
- This handles realistic model output with earlier JSON snippets

### Issue 3 (Medium) - forbidden keys filtered from params
**File**: `yoitsu-contracts/src/yoitsu_contracts/review_proposal.py`
- Changed: `to_trigger_data()` now filters `task_template.params` to remove forbidden keys
- Filters: `goal`, `budget`, `repo`, `repo_url`, `branch`, `init_branch`, `task`, `prompt`
- Prevents `TriggerData` validation errors when model outputs `params={"repo": ...}`

### Issue 4 (Assumption) - reviewer.md tracked
**File**: `palimpsest/evo/prompts/reviewer.md`
- Changed: Added file to git staging (`git add prompts/reviewer.md`)
- Status: `A  prompts/reviewer.md` (staged as new file)

### Tests Added
- `test_from_json_str_multiple_code_blocks_uses_last`
- `test_from_json_str_earlier_inline_json_ignored`
- `test_to_trigger_data_filters_forbidden_keys`
- `test_metric_type_budget_variance_queries_budget_variance`
- `test_metric_type_preparation_failure_no_endpoint`
- `test_metric_type_tool_retry_no_endpoint`
- `test_metric_type_none_defaults_to_budget_variance`

### All Tests Passing
```
yoitsu-contracts: 21 passed
palimpsest: 14 passed
trenni: 8 passed
```