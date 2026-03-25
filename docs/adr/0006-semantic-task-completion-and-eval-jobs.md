# ADR-0006: 2026-03-26 Semantic Task Completion, Eval Jobs, And Task ID Hierarchy

- Status: Accepted and implemented (phase 1)
- Date: 2026-03-26
- Related: ADR-0002, ADR-0005

## Context

ADR-0002 identified the structural/semantic completion gap: trenni marks a task
`completed` when all its jobs reach a terminal state, but structural completion
(scheduler state) does not imply semantic completion (business quality). A job
calling `task_complete` signals runtime exit, not goal achievement.

Two concrete failure modes:

- An agent exhausts max iterations and the runtime exits without the goal being
  met. The task is marked `completed`.
- A join job assembles child outputs but makes no quality judgement. The parent
  task receives a `task.completed` event regardless of whether deliverables meet
  the original criteria.

Placing semantic evaluation inside the producing agent creates self-reporting
bias and couples quality assessment to execution. The Dual Gate requirement from
ADR-0002 remains unimplemented.

A second problem: task IDs under the current scheme (`{parent}/{index}`) collide
when the same parent job spawns children more than once, because the index
counter resets per spawn event.

## Decision

### 1. Two-Layer Verdict

Every terminal task carries a result with two independent layers:

**Structural verdict** (computed by trenni, always present):
- Derived from job terminal states: counts of `success`, `failed`, `cancelled`,
  `unknown`
- Includes execution trace: ordered list of job IDs, roles, and outcomes
- Deterministic, computed without LLM involvement
- Available even when no eval job runs or when eval job itself fails

**Semantic verdict** (produced by eval job, optional):
- Qualitative judgement against original goal and deliverables
- Structured as `{verdict: pass|fail|unknown, summary: str, criteria_results: list}`
- `verdict` field extracted separately for fast programmatic checks
- Falls back to `unknown` when eval job fails or is not configured

The combined result propagated upward is always `{structural, semantic, trace}`.
Semantic takes precedence for quality decisions; structural is always the
ground truth for what actually ran.

### 2. Eval Job Mechanism

After all productive jobs for a task reach structural completion, trenni
optionally spawns one eval job per task:

- The eval job shares the same `task_id` as the task it evaluates
- It receives the original goal, deliverables spec, verification criteria, and
  child job summaries (including git refs) as context
- It calls `task_complete` and terminates; no rework loop
- If rework is needed, a new task is created externally (clean audit trail,
  no in-flight state mutation)

`eval_spec` is optional on each task. A default evaluator role is provided by
the system when `eval_spec.role` is omitted. For flat tasks (no spawn, single
job), the semantic verdict defaults to `unknown`; the structural verdict
reflects the single job outcome.

`eval_spec` is supplied by the planning job (first job in a task) via
`SpawnRequestData`, not at trigger time. Triggers initiate tasks at a
high-level goal; `eval_spec` is only known after planning decomposes the goal
into concrete deliverables and verification criteria.

An `eval_spawned: bool` flag on `TaskRecord` prevents a second eval job from
being triggered when the eval job itself completes.

### 3. `task.evaluating` Intermediate State

Task lifecycle gains an explicit intermediate state:

```
pending → running → evaluating → completed
                               → failed
                               → cancelled
                               → eval_failed
```

- `evaluating`: structural completion reached, eval job spawned, awaiting
  semantic verdict
- `eval_failed`: eval job itself failed or timed out; task is terminal with
  structural verdict only, semantic verdict is `unknown`

Parent join conditions (`TaskIsCondition`) monitor the final terminal state,
not structural completion. This means the join naturally waits for semantic
evaluation to finish without any change to condition logic.

### 4. Hierarchical Verdict Rollup

Eval results propagate up the task hierarchy:

- Each child task's terminal event carries its full result (`structural +
  semantic + trace`)
- When trenni constructs the eval job for a parent task, it injects all child
  task results into the eval job's context at the context-building stage
- The parent evaluator synthesizes child verdicts; it does not re-run child
  work
- The root task's eval is the final authoritative outcome of the original
  trigger goal

This rollup is driven by the context stage reading task results from the event
store, not by trenni aggregating state internally.

### 5. Task ID Hierarchy

Task IDs use a prefix-nested scheme compatible with SQL `LIKE` and
`startswith` queries:

**Root task ID**: first 16 hex chars of the trigger event UUID v7 (dashes
removed). UUID v7 encodes a millisecond timestamp in its high bits, so root
task IDs are time-sortable by construction. Example: `018f4e3ab2c17d3e`.

**Child task ID**: `{parent_task_id}/{hash}` where `hash` is the first 4 chars
of `base32(sha256(f"{parent_task_id}:{spawn_event_id}:{child_index}"))`.
4 base32 chars = ~1M possible values; at typical fan-outs (<20 children per
parent) collision probability is negligible. No per-task counter state is
required; IDs are fully deterministic from their inputs and can be
reconstructed during replay.

Examples:
```
018f4e3ab2c17d3e              # root
018f4e3ab2c17d3e/3afw         # child
018f4e3ab2c17d3e/3afw/b2er    # grandchild
018f4e3ab2c17d3e/7c1p         # sibling
```

Depth is visible by counting `/` separators. Subtree queries:
`WHERE task_id LIKE '018f4e3ab2c17d3e/%'`.

This also fixes the spawn ID collision in `trenni/trenni/spawn_handler.py`:
child job IDs are derived from the same hash, so multiple spawns from the same
parent produce distinct IDs without a monotonic counter.

## Consequences

### Positive

- Structural verdict is always available; no task can complete with a total
  information blackout
- Semantic evaluation is decoupled from execution; evaluator role is
  independently testable and replaceable
- `task.evaluating` makes the quality gate visible in observability tooling
- Hierarchical rollup gives root-level eval full context without re-running
  work
- Task ID prefix scheme enables efficient subtree queries and makes nesting
  depth readable at a glance
- Spawn ID collision (Issue 3) is eliminated as a side effect of the ID redesign

### Tradeoffs

- Task lifecycle gains more states; state machine complexity increases slightly
- Eval job adds latency to task terminal; time-sensitive workflows must account
  for eval duration
- `eval_failed` as a distinct terminal requires handling in all consumers of
  task terminal events

### Non-Goals

- In-process rework loops (retry is a new task, not a state transition)
- Synchronous eval (eval job runs asynchronously like any other job)
- Multi-dimensional job budget (iterations, cost, tokens) — separate work

## Implementation Scope

Changes required across all packages:

**yoitsu_contracts**
- `SpawnRequestData`: add optional `eval_spec: EvalSpec | None` per child task
- `TaskCreatedData`: carry `eval_spec`
- `TaskCompletedData`, `TaskFailedData`: carry `TaskResult` (structural +
  semantic + trace)
- New event type: `task.evaluating` with `TaskEvaluatingData`
- New terminal event type: `task.eval_failed`
- New model: `EvalSpec`, `StructuralVerdict`, `SemanticVerdict`, `TaskResult`

**trenni**
- `spawn_handler.py`: new task/job ID generation using UUID v7 prefix and
  hash-based child IDs
- `state.py`: `TaskRecord` gains `eval_spec`, `eval_spawned`, `result` fields
- `supervisor.py` / `_evaluate_task_termination`: compute structural verdict,
  check `eval_spec`, spawn eval job, emit `task.evaluating`; on eval job
  completion emit final terminal with merged result
- New `eval_failed` handling path

**palimpsest**
- `task_complete` result propagation (Issue 2 prerequisite): `status` field
  flows from tool call into result dict and into job terminal event
- Context stage: inject child task results when building eval job context

**pasloe**
- No schema changes required; task results are carried in event `data` JSON

## Implementation Status (2026-03-26)

Implemented in this pass:

- contracts: `EvalSpec`, `TaskResult`, `task.evaluating`, `task.eval_failed`,
  `JobCompletedData.status`, and `SpawnTaskData.eval_spec`
- trenni: hash-based child task/job IDs, root task ID UUIDv7-prefix scheme,
  structural verdict + trace, eval job spawn/settlement flow, and replay support
  for evaluating/eval_failed lifecycle
- palimpsest: `task_complete.status` propagation to interaction result and
  `job.completed`, plus eval-spec passthrough in `spawn` tool
- context rollup: eval context and child terminal task results are injected via
  context loader at runtime

Still open:

- stronger evaluator-specific default role/prompt tuning (currently defaults to
  `default` role when `eval_spec.role` is omitted)
