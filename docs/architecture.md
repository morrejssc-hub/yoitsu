# Yoitsu Architecture

Updated: 2026-03-26

## Core Model

Yoitsu has two durable sources of truth:

- Git repositories
- the Pasloe event stream

Everything else is derived state and can be rebuilt.

The runtime split is:

- `palimpsest`: execute one job
- `trenni`: schedule, checkpoint, replay, and isolate jobs
- `pasloe`: store and deliver events
- `yoitsu-contracts`: keep the cross-repo contracts typed and shared

## Job And Task Are Different

`Job` is the execution unit. It runs one Palimpsest pipeline. It terminates via
job lifecycle events:

- `job.completed`
- `job.failed`
- `job.cancelled`

`Task` is the logical work unit representing a goal. Its lifecycle is event-driven
and strictly managed by Trenni. Current states are:

- intermediate:
  - `pending`
  - `running`
  - `evaluating`
- terminal:
- `task.completed`
- `task.failed`
- `task.partial`
- `task.cancelled`
- `task.eval_failed`

Trenni manages task lifecycle transitions through two layers:

- structural verdict derived from job terminal states and trace
- optional semantic verdict produced by one eval job per task

Palimpsest emits job outcomes. Trenni derives the final task state from those
job outcomes plus optional eval output.

## Spawn Is The Only Orchestration Primitive

The runtime never executes child work inline. It only emits `job.spawn.request`.

Trenni expands one spawn request into:

- child tasks
- child jobs
- one join job tied to the parent task

Task IDs are hierarchical and deterministic:

- root task IDs are the first 16 hex chars of the trigger event UUIDv7
- child task IDs are `{parent_task_id}/{hash}`

Each queued job carries a condition tree. Trenni currently evaluates:

- `TaskIs(task_id, state)`
- `All([...])`
- `Any([...])`
- `Not(condition)`

Examples:

- cancel pending siblings if another child fails
- launch a join job only after all child tasks become terminal
- resume the parent task as a normal job with join context

## Three Layers

| Layer | Owner | Responsibility | Does Not Care About |
|---|---|---|---|
| Scheduler | Trenni | task progress, condition evaluation, queue drain, replay, checkpoint | how the runtime is launched |
| Isolation Backend | Trenni | env injection, container lifecycle, logs, cleanup | task semantics |
| Runtime | Palimpsest | workspace, context, LLM loop, tools, event emission | queueing and orchestration policy |

`PodmanBackend` is the current isolation backend. The interface is intentionally narrower than the scheduler:

- `prepare`
- `start`
- `inspect`
- `stop`
- `remove`
- `logs`

## Shared Contracts

`yoitsu-contracts` exists so Palimpsest and Trenni stop drifting on:

- event schemas
- `JobConfig`
- condition serialization
- Pasloe client behavior
- environment helpers such as Git auth injection

Pasloe stays schema-agnostic at the payload level, but now uses a two-stage
delivery model:

- producers receive `accepted`
- consumers only read `committed`

## Runtime Context

Palimpsest still treats the evo repo as the freely changeable surface:

- prompts
- context providers
- tools
- roles

The runtime itself is the stable skeleton. It transparently captures events and injects ambient ids. Permission boundaries between the runtime and evo remain enforced by convention, not by a hard supervisor file scanner.

## Invariants

- Every launched job reaches a terminal result or is reaped into one.
- The runtime never owns orchestration state for sibling jobs.
- Spawn expansion is deterministic from the event payload plus parent defaults.
- Replay queue reconstruction uses `supervisor.job.enqueued` as the intake boundary.
- Environment injection happens in the isolation layer, not ad hoc in the runtime.
- Replay must be able to reconstruct pending, ready, and running work from Pasloe events plus container inspection.

## Roadmap Notes

The old document described several future-state features that are still not shipped. Their current status is:

- `Dual Gate Validation`: partially implemented through structural verdicts plus
  optional eval jobs. Later phases may add stronger automated acceptance policy.
- `Supervisor detects changed_files violations`: not implemented; boundaries are enforced by convention.
- metric-based soft gate comparison: not implemented.
- self-evolution rollback loops: not implemented.

Those items belong to Phase 4 and Phase 5 work, not to the current runtime/scheduler baseline.
