# Yoitsu Architecture

Updated: 2026-03-24

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

`Job` is the execution unit. It runs one Palimpsest pipeline. It only ends in:

- `success`
- `failure`

`Task` is the logical work unit representing a goal. Its lifecycle is purely event-driven and strictly managed by Trenni. It has no intermediate explicit states; it is implicitly active until it reaches a terminal event:

- `task.completed`
- `task.failed`
- `task.cancelled`

Trenni manages task lifecycle transitions purely via structral state evaluation. Palimpsest emits `job.completed` or `job.failed` to reflect execution results, while Trenni derives whether the parent task is done.

## Spawn Is The Only Orchestration Primitive

The runtime never executes child work inline. It only emits `job.spawn.request`.

Trenni expands one spawn request into:

- child tasks
- child jobs
- one join job tied to the parent task

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

Pasloe stays schema-agnostic. It stores and delivers opaque event payloads.

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
- Environment injection happens in the isolation layer, not ad hoc in the runtime.
- Replay must be able to reconstruct pending, ready, and running work from Pasloe events plus container inspection.

## Roadmap Notes

The old document described several future-state features that are still not shipped. Their current status is:

- `Dual Gate Validation`: planned for later self-evolution phases, not implemented now.
- `Supervisor detects changed_files violations`: not implemented; boundaries are enforced by convention.
- metric-based soft gate comparison: not implemented.
- self-evolution rollback loops: not implemented.

Those items belong to Phase 4 and Phase 5 work, not to the current runtime/scheduler baseline.
