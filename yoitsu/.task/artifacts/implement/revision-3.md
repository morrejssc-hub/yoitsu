All tests pass. Summary of fixes:

**Issue 1 (Medium): `to_trigger_data()` incomplete filtering for canonical fields**
- Fixed: Added `role` and `team` to forbidden keys in:
  - `TriggerData.model_post_init()` in `events.py` - validates at model level
  - `to_trigger_data()` in `review_proposal.py` - filters at conversion level
- Added test: `test_spawn_task_data_params_cannot_contain_role_or_team`
- Added test: `test_to_trigger_data_filters_role_and_team_from_params`

**Issue 2 (Medium): unsupported observation metrics fail open**
- Fixed: Made `ObservationThresholdEvent.metric_type` a `Literal["budget_variance", "preparation_failure", "tool_retry"]` type - validates at source
- Fixed: Added `else` clause in `observation_context()` to show explicit warning for unknown metric types
- Added tests: `test_observation_threshold_event_valid_metric_types`, `test_observation_threshold_event_rejects_unknown_metric_type`, `test_unknown_metric_type_shows_warning`

**Issue 3 (Process): untracked files**
- Fixed: `git add src/yoitsu_contracts/review_proposal.py tests/test_review_proposal.py`
- Status: Files now tracked (`A` in git status)

**Tests: 144 passed total**
- yoitsu-contracts: 116 passed
- palimpsest: 28 passed