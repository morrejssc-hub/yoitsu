# Planner -> Spawn -> Eval Smoke Test Gap

Updated: 2026-03-27

## Goal

Run one real end-to-end smoke test that proves the new execution model works
in production-like flow:

1. root task routes to planner
2. planner emits spawned child tasks
3. child task executes with real workspace params
4. eval job is triggered from child completion
5. task settles through semantic result, not only structural completion

## Current State

The codebase now has:

- decorator-based role metadata
- function-based `JobSpec`
- `role_params` threaded through runtime and scheduler
- planner-style spawn payload support
- scheduler-level unit coverage for `planner -> spawn -> eval`

What is still missing is a **real smoke run** that enters this path from the
actual trigger entrypoint.

## Remaining Gaps

### 1. Root trigger still starts `default`, not planner

Current smoke submissions still result in root jobs with:

- `role=default`
- `team=default`

This means the live system is still entering the old direct-execution path
instead of the planner path.

Needed:

- trigger submission must include `team`
- root routing must launch the team's planner role

### 2. Planner output is not yet constrained by a smoke-specific task

The runtime supports planner-style spawn payloads:

- `goal`
- `role`
- `budget`
- `params`
- `eval_spec`

But the real planner prompt has not yet been validated in a smoke run to
consistently produce that shape.

Needed:

- one very small, controlled planner task
- predictable spawned output

### 3. Child role params must be sufficient to build the workspace

For a real spawned child job to work, planner output must include enough
inputs for the child role:

- `repo`
- `branch` / `init_branch`
- `goal`
- `budget`

Without these, child jobs can fall back to incomplete or repoless execution.

### 4. Eval must be triggered in the real run, not only in unit tests

The scheduler unit tests already prove this path:

- child terminal state
- `supervisor.task.evaluating`
- eval job launch
- semantic settlement

But the production-like smoke run still needs to show this sequence with real
events and real containers.

Needed smoke evidence:

- child `supervisor.task.created`
- child `supervisor.job.enqueued` / `supervisor.job.launched`
- `supervisor.task.evaluating`
- eval job terminal event
- final child task terminal event after semantic settlement

### 5. Current smoke tasks are too large

The current roadmap-style tasks are too big for architecture validation.
They mostly exercise budget exhaustion, not planner/eval correctness.

Needed:

- one tiny smoke task
- one or two spawned children at most
- one small file change
- one simple evaluator check

## Recommended Smoke Shape

Use a minimal task like:

- root goal: "Plan and implement one tiny change in a test repository"

Expected planner output:

- one `implementer` child
- optional one `reviewer` child
- `budget`
- `params.repo`
- `params.branch`
- `eval_spec.deliverables`
- `eval_spec.criteria`

Expected success condition:

- planner job runs
- at least one child job runs
- eval job runs
- final child task reaches semantic terminal state

## Practical Next Steps

1. Make root trigger route to planner for team-based work
2. Create a tiny dedicated smoke task for planner/eval validation
3. Re-run deploy smoke and watch for:
   - planner root job
   - spawned child jobs
   - `supervisor.task.evaluating`
   - eval settlement
