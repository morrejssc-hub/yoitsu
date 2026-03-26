# ADR-0007: 2026-03-26 Job Budget Exhaustion And Task Partial Terminal State

- Status: Accepted and implemented (current hard budget: max_iterations)
- Date: 2026-03-26
- Related: ADR-0002, ADR-0006

## Context

Jobs are subject to multi-dimensional budget constraints: iteration count,
context window size, and cost. When a budget limit is reached the runtime
must terminate the job. Currently all runtime-terminated jobs exit through
the same `job.completed` path, and the task is marked `completed` regardless
of whether the agent finished its goal.

A separate budget warning mechanism already exists (`LoopWarning` in
`palimpsest/palimpsest/stages/interaction.py`): as a budget approaches
exhaustion, the runtime injects an informational user prompt into the agent
loop. This gives the agent an opportunity to wrap up gracefully and call
`task_complete` voluntarily. The warning is independent of the hard-cut path
— it does not force termination and does not guarantee the agent will act on
it. The agent may continue normally, wrap up early, or ignore the warning
entirely.

When the budget is actually exhausted the runtime must terminate regardless
of agent state. There is currently no way to distinguish this forced exit
from a genuine task completion at the task level.

## Decision

### Job layer: budget exhaustion is a normal exit

When any budget dimension is exhausted the runtime:

1. Commits whatever workspace state exists (WIP commit)
2. Emits `job.completed` with `code="budget_exhausted"` in the event data

From the job layer's perspective this is a clean exit. The job ran, consumed
its full budget, and committed. No new job terminal state is introduced.

The warning mechanism remains unchanged and independent: it fires near the
limit, gives the agent a chance to exit gracefully via `task_complete`, and
has no mandatory outcome. A graceful agent exit via `task_complete` produces
a normal `job.completed` with no special code.

### Task layer: `task.partial` as a new terminal state

trenni detects `job.completed` with `code="budget_exhausted"` and propagates
this to the task layer as `task.partial`.

`task.partial` is a terminal state. It is semantically distinct from
`task.failed`:

- `task.failed`: active error or inability to proceed
- `task.partial`: meaningful work was done but the goal was not reached within
  the allocated budget — progress without completion

`task.partial` participates in the structural verdict introduced in ADR-0006:
the breakdown becomes `{success, failed, partial, cancelled, unknown}`.

### No automatic follow-up

Budget exhaustion does not trigger any automatic continuation. Rework, if
needed, is always a new task with a fresh budget allocation. This preserves
the per-job budget as a hard limit. If a parent join or eval job decides that
partial child work is insufficient, it makes that judgement explicitly and the
orchestrator creates a new task — the partial result is not automatically
extended.

### Eval job on partial tasks

A `task.partial` task may still have an eval job run against it (if
`eval_spec` is present). The eval job receives the partial work as its input
and produces a semantic verdict: how much was accomplished, whether the
partial output meets minimum criteria, what remains. This verdict informs the
parent join/eval job's decision on whether to accept or reject the partial
result.

## Consequences

### Positive

- Budget constraints are hard per-job limits with clear task-level visibility
- `task.partial` gives parent jobs and eval jobs honest signal rather than a
  misleading `task.completed`
- The warning mechanism remains a clean, independent optimization layer with
  no required coupling to the partial path
- Rework decisions stay at the orchestration level, not embedded in runtime
  mechanics

### Tradeoffs

- All consumers of task terminal events must handle `task.partial` as a
  distinct case alongside `completed`, `failed`, `cancelled`, `eval_failed`
- WIP commits on budget exhaustion may produce incomplete git history; callers
  should treat `budget_exhausted` git refs accordingly

### Non-Goals

- Automatic budget reallocation or job continuation
- Per-budget-dimension distinction in the terminal event (all budget types
  collapse to `budget_exhausted`)
- Changes to the warning injection mechanism

## Implementation Scope

**palimpsest**
- `interaction.py`: detect budget exhaustion (iterations, context, cost) and
  force exit with WIP commit; emit `job.completed` with `code="budget_exhausted"`
- `runner.py`: ensure WIP commit path is reached on forced exit

**yoitsu_contracts**
- `JobCompletedData`: document `code` field; `"budget_exhausted"` is a
  reserved value
- New event type: `task.partial` with `TaskPartialData`
  (`task_id`, `reason`, structural verdict snapshot)

**trenni**
- `supervisor.py` / `_evaluate_task_termination`: detect
  `job.completed` with `code="budget_exhausted"`, emit `task.partial`
  instead of `task.completed`
- `state.py`: `TaskRecord` terminal states extended with `partial`
- Structural verdict breakdown updated to include `partial` count

## Implementation Status (2026-03-26)

Implemented in this pass:

- contracts: added `task.partial`, `JobCompletedData.code`, and structural
  verdict `partial` count
- palimpsest: max-iteration exhaustion now exits through `job.completed` with
  `status="partial"` and `code="budget_exhausted"` after normal publication
- trenni: detects `budget_exhausted`, rolls structural verdict to `partial`,
  emits `task.partial`, and preserves partial through eval result settlement

Current scope note:

- the runtime currently has one hard enforced budget dimension:
  `max_iterations`
- future hard stops for context-window or cost exhaustion should reuse the same
  `job.completed(code="budget_exhausted") -> task.partial` path
