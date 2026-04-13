# ADR-0002: Task and Job Lifecycle

- Status: Accepted
- Date: 2026-03-27
- Related: ADR-0001, ADR-0003, ADR-0004

## Context

Tasks represent logical work objectives. Jobs are runtime execution units.
The distinction must be clean and consistent throughout the system:

- Trenni is the sole authority for task state. Palimpsest has no task
  awareness.
- A job completing does not automatically mean its task is complete.
- Structural completion (all jobs finished) does not imply semantic
  completion (goal actually met).

## Decisions

### 1. Task Lifecycle States

```
pending → running → evaluating → completed
                              → failed
                              → partial
                              → cancelled
                              → eval_failed
```

- **pending**: task created, no jobs launched yet.
- **running**: at least one job is active.
- **evaluating**: all productive jobs have reached structural completion; an
  eval job has been spawned to assess quality.
- **completed**: eval job confirmed the goal was met.
- **failed**: active error or inability to proceed.
- **partial**: meaningful work was done but the goal was not reached within
  the allocated budget (see ADR-0004).
- **cancelled**: task cancelled before completion.
- **eval_failed**: eval job itself failed or timed out; task is terminal with
  structural verdict only, semantic verdict is `unknown`.

Parent join conditions monitor the final terminal state, not structural
completion. The join naturally waits for semantic evaluation without any
change to condition logic.

### 2. Two-Layer Verdict

Every terminal task carries a result with two independent layers:

**Structural verdict** (computed by Trenni, always present):
- Derived from job terminal states: counts of `success`, `failed`,
  `partial`, `cancelled`, `unknown`.
- Includes execution trace: ordered list of job IDs, roles, and outcomes.
- Deterministic, computed without LLM involvement.
- Available even when no eval job runs or when the eval job itself fails.

**Semantic verdict** (produced by eval job, optional):
- Qualitative judgment against the original goal and deliverables.
- Structured as `{verdict: pass|fail|unknown, summary: str, criteria_results: list}`.
- Falls back to `unknown` when no eval job is configured or the eval job
  fails.

The combined result is always `{structural, semantic, trace}`. Semantic
takes precedence for quality decisions; structural is always the ground
truth for what actually ran.

### 3. Eval Job Mechanism

After all productive jobs for a task reach structural completion, Trenni
optionally spawns one eval job:

- The eval job shares the same `task_id` as the task it evaluates.
- It receives the original goal, deliverables spec, verification criteria,
  and child job summaries (including git refs) as context.
- It exits via idle detection (no tool calls); no rework loop.
- If rework is needed, a new task is created externally. In-process rework
  is not supported.

`eval_spec` is optional on each task. When omitted, a system default
evaluator role is used. For flat tasks (no spawn, single job), the semantic
verdict defaults to `unknown`.

`eval_spec` is supplied by the planning job via `SpawnRequestData`, not at
trigger time. Triggers initiate tasks at a high-level goal; `eval_spec` is
known only after planning decomposes the goal into concrete deliverables and
verification criteria.

An `eval_spawned: bool` flag on `TaskRecord` prevents a second eval job
from being triggered when the eval job itself completes.

### 4. Hierarchical Verdict Rollup

Eval results propagate up the task hierarchy:

- Each child task's terminal event carries its full result
  (`structural + semantic + trace`).
- When Trenni constructs the eval job for a parent task, it injects all
  child task results into the eval job's context at the context-building
  stage.
- The parent evaluator synthesizes child verdicts; it does not re-run child
  work.
- The root task's eval is the final authoritative outcome of the original
  trigger goal.

This rollup is driven by the context stage reading task results from the
event store, not by Trenni aggregating state internally.

### 5. Task ID Hierarchy

Task IDs use a prefix-nested scheme compatible with SQL `LIKE` and
`startswith` queries.

**Root task ID**: first 16 hex chars of the trigger event UUID v7 (dashes
removed). UUID v7 encodes a millisecond timestamp in its high bits, so root
task IDs are time-sortable by construction.

Example: `018f4e3ab2c17d3e`

**Child task ID**: `{parent_task_id}/{hash}` where `hash` is the first 4
chars of `base32(sha256(f"{parent_task_id}:{spawn_event_id}:{child_index}"))`.
4 base32 chars provides ~1M possible values; at typical fan-outs (fewer than
20 children per parent) collision probability is negligible. No per-task
counter state is required; IDs are fully deterministic from inputs and can
be reconstructed during replay.

Examples:

```
018f4e3ab2c17d3e              # root
018f4e3ab2c17d3e/3afw         # child
018f4e3ab2c17d3e/3afw/b2er    # grandchild
018f4e3ab2c17d3e/7c1p         # sibling
```

Depth is visible by counting `/` separators. Subtree queries:
`WHERE task_id LIKE '018f4e3ab2c17d3e/%'`

Child job IDs are derived from the same hash scheme, eliminating spawn ID
collisions that arise from per-task monotonic counters resetting across
multiple spawn events.

### 6. Spawn Mechanism

The runtime emits `agent.job.spawn_request`. Trenni processes the spawn
request and creates child tasks and jobs. The spawn payload is:

```json
{
  "role":   "implementer",
  "params": { "repo": "...", "goal": "...", "budget": 0.80 },
  "sha":    "abc123"
}
```

The `sha` anchors the role function to a specific version of evo, making
job behavior reproducible. Trenni treats spawn payloads as opaque blobs —
it has no dependency on evo.

Inherited params (repo, evo sha, team) are resolved by Trenni during spawn
expansion. When the planner does not specify them explicitly, Trenni fills
them from the parent job context before creating child jobs.

Spawn validation: if the allocated budget is below the role's `min_cost`,
the spawn is rejected with an explicit error before any job is created.

### 7. Budget Exhaustion → task.partial Signal Path

When a job exits due to budget exhaustion and publication succeeds:

1. Palimpsest emits `agent.job.completed` with `code="budget_exhausted"`.
2. Trenni detects this code and emits `supervisor.task.partial` instead of
   `supervisor.task.completed`.

The `task.partial` state means: meaningful work was done but the goal was
not reached within the allocated budget. It is distinct from `task.failed`
(active error). A `task.partial` task may still have an eval job run against
it to assess how much was accomplished and whether the partial output meets
minimum criteria.

If publication fails (for any reason, including budget exhaustion), the
runtime emits `agent.job.failed` instead. `task.partial` is only valid when
a durable, retrievable artifact exists. There is no `job.partial` state.

Full state matrix:

| Budget exhausted | Publication succeeded | Outcome |
|------------------|-----------------------|---------|
| no  | yes | `agent.job.completed` → `task.completed` (via eval) |
| yes | yes | `agent.job.completed(code="budget_exhausted")` → `task.partial` |
| no  | no  | `agent.job.failed` |
| yes | no  | `agent.job.failed` |

### 8. Idle Detection as the Primary Job Exit Path

The `task_complete` tool has been removed. Jobs exit through one of two
paths:

**Idle exit** (primary):
1. LLM returns a response with no tool calls: capture it as the **candidate
   summary** and inject a single confirmation prompt.
2. Second consecutive no-tool-call response (or first after confirmation):
   exit with the candidate summary from step 1, `status="complete"`.
3. If the agent resumes tool calls after the confirmation prompt, reset idle
   state; the candidate summary is discarded.

The exit summary is always the agent's natural conclusion, not its response
to a system prompt.

**Budget exit**: `budget_exhausted()` returns a non-null reason before an
LLM call; exit with candidate summary (if any) or descriptive fallback,
`status="partial"`, `code="budget_exhausted"`.

All exits produce `agent.job.completed`. No tool can force the loop to exit.
`ToolResult.terminal` has been removed.

### 9. Interaction Loop Structure

```
while True:
    if llm.budget_exhausted():
        → exit: candidate_summary, status="partial", code="budget_exhausted"

    check LoopWarning triggers against llm.budget_remaining()

    response = llm.call(...)

    if no tool calls:
        if first idle:
            save candidate_summary, inject confirmation prompt, continue
        else:
            → exit: candidate_summary, status="complete"
    else:
        reset idle state
        execute tool calls
```

### 10. Unified Budget Tracking

`UnifiedLLMGateway` is the single source of truth for all budget dimensions.
It accumulates per-call metrics and exposes:

- `budget_exhausted() -> str | None` — returns the exhaustion reason
  (`"cost"`, `"max_iterations_hard"`, `"input_tokens"`, `"output_tokens"`)
  or `None`.
- `budget_remaining() -> dict` — remaining quantities per dimension, used
  by `LoopWarning` triggers.

See ADR-0004 for the full budget model, including the penalty/hard-cut
distinction and cost as the primary accumulator.

## Consequences

### Positive

- Structural verdict is always available; no task can complete with a total
  information blackout.
- Semantic evaluation is decoupled from execution; the evaluator role is
  independently testable and replaceable.
- `task.evaluating` makes the quality gate visible in observability tooling.
- Hierarchical rollup gives root-level eval full context without re-running
  work.
- Task ID prefix scheme enables efficient subtree queries; nesting depth is
  readable at a glance.
- Idle detection eliminates the task/job semantic confusion from
  `task_complete` and the unreliable agent self-reporting path.
- Summary selection is deterministic: always the agent's first idle response.

### Tradeoffs

- Task lifecycle has more states; all consumers of task terminal events must
  handle `task.partial` and `eval_failed` as distinct cases.
- Eval job adds latency to task terminal; time-sensitive workflows must
  account for eval duration.
- The confirmation prompt adds one extra LLM call per job exit.
- Agents cannot explicitly signal "I'm done" — they must stop calling tools.
  In practice this is how LLMs naturally behave when finished.

### Non-Goals

- In-process rework loops (retry is a new task, not a state transition).
- Synchronous eval (eval job runs asynchronously like any other job).
- Automatic budget reallocation or job continuation on exhaustion.
- Per-budget-dimension distinction in the partial signal (all budget types
  collapse to `code="budget_exhausted"`; the triggering dimension is
  recorded in `JobCompletedData.budget_dim` for observability).
- Dynamic budget reallocation mid-job.
- Cross-job budget pooling at the task level.
