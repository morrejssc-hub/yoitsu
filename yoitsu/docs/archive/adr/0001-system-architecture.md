# ADR-0001: System Architecture

- Status: Accepted (Revised 2026-04-02)
- Date: 2026-03-27
- Revised: 2026-04-02
- Related: ADR-0002, ADR-0003, ADR-0004, ADR-0013

Note: The normative system entry point is [docs/architecture.md](../architecture.md).
This ADR retains the individual design decisions and their rationale.

## Context

Yoitsu is a self-evolving agent system. It orchestrates LLM agents across
jobs and tasks, persists and replays events through a durable event store,
and allows the agents themselves to modify the logic that governs their
execution.

The architecture has four primary components:

- **Pasloe** — the event store and HTTP event bus
- **Trenni** — the task scheduler and supervisor
- **Palimpsest** — the agent runtime (job executor)
- **Artifact Store** — content-addressed immutable object store (ADR-0013)

A fifth component, **evo**, is a versioned directory of Python modules that
define how jobs execute. It is not a separate service — it is the evolvable
layer consumed by Palimpsest at runtime.

The system has two authoritative persistence layers: the Pasloe event
stream (records what happened) and the artifact store (records what was
produced). Everything else — workspaces, git branches, in-memory state —
is derived or ephemeral.

## Decisions

### 1. Job and Task Are Strictly Separated

`job` is the runtime execution unit. `task` is the logical work unit.

- `agent.job.completed` and `agent.job.failed` describe execution outcome only.
- `supervisor.task.*` events describe logical work state.
- A job may succeed while its task stays in progress (e.g. partial result).
- Trenni is the sole authority for task state transitions. Palimpsest
  has no task awareness.

### 2. Three Architectural Layers

**Scheduler layer (Trenni)**
- Queueing, condition evaluation, replay, and checkpoint.
- Consumes committed Pasloe events to drive state transitions.
- Emits `supervisor.*` events (task lifecycle, job enqueued/launched).

**Isolation and runtime layer (Palimpsest)**
- Receives a spawn payload, resolves the role function from evo, executes
  the job pipeline, emits `agent.*` events.
- No task-level logic. No knowledge of the task hierarchy.

**Event persistence layer (Pasloe)**
- Durable ingest and fan-out for all events.
- Producers depend only on `accepted` acknowledgement.
- Consumers read only `committed` events.

### 3. Shared Contracts in `yoitsu-contracts`

All typed event models, `JobConfig`, condition serialization, Pasloe
clients, and environment helpers are defined in `yoitsu-contracts`. Pasloe
and Trenni consume these directly.

### 4. Conditional Spawn Is the Only Orchestration Primitive

The runtime emits `agent.job.spawn_request`. Trenni expands it into child
jobs plus an optional join job. Queue admission is controlled by typed
condition trees over task state. There is no other orchestration mechanism.

### 5. Trenni Internal Structure

Trenni has explicit modules:

- `state` — task and job records, ready queue
- `scheduler` — condition evaluation and queue admission
- `spawn_handler` — spawn request processing and child ID derivation
- `replay` — state reconstruction from committed events
- `checkpoint` — durable progress markers
- `isolation` — container and process lifecycle

`supervisor.py` is the entry point and control-plane facade.

### 6. Pasloe Two-Stage Pipeline

Pasloe is a two-stage architecture:

1. **Ingest log** is the durability boundary. `POST /events` persists ingress
   rows and returns `accepted`. An optional `idempotency_key` is enforced per
   source for safe producer retries.
2. **Read models** are driven asynchronously from committed events. A
   `committer` pipeline moves ingress rows into committed `events`. Detail
   tables are written synchronously in the same commit transaction. A webhook
   worker handles fan-out.

Event visibility semantics:

- Producers depend only on `accepted`.
- Business consumers read only `committed`.
- The pipeline is: **committer + webhook** (the projection worker has been
  replaced by synchronous detail writes in the committer).

### 7. Supervisor Intake/Execution Phase Split

Trenni supervisor is split into two phases:

1. **Intake phase** (deterministic control plane): consumes committed Pasloe
   events, validates, dedupes, applies scheduler mutations, persists an
   intake-safe progress marker.
2. **Execution phase** (runtime side effects): drains the ready queue,
   launches and monitors containers, emits runtime lifecycle events.

Cursor semantics:

- Cursor advances only after the intake phase succeeds for an event batch.
- Execution failures do not roll back the intake cursor.
- Replay reconstructs pending/ready/running state using intake-derived state
  plus launch/terminal events.

Lifecycle signals distinguish: received → enqueued → launched → terminal.

### 8. Event Type Naming Convention

Event types follow a three-segment convention:

```
<source>.<model>.<state>
```

- **source**: the emitting component (`agent`, `supervisor`, `trigger`)
- **model**: the domain entity (`job`, `task`, `llm`, `tool`)
- **state**: the specific event (`started`, `completed`, `request`, `exec`)

Registered models (`job`, `task`, `llm`, `tool`) have corresponding detail
tables in Pasloe. Four-segment names are flattened with underscore
(e.g. `agent.job.runtime_issue`).

Current event type map:

| Event type                       | Model |
|----------------------------------|-------|
| `agent.llm.request`              | llm   |
| `agent.llm.response`             | llm   |
| `agent.tool.exec`                | tool  |
| `agent.tool.result`              | tool  |
| `agent.job.started`              | job   |
| `agent.job.completed`            | job   |
| `agent.job.failed`               | job   |
| `agent.job.cancelled`            | job   |
| `agent.job.runtime_issue`        | job   |
| `agent.job.stage_transition`     | job   |
| `agent.job.spawn_request`        | job   |
| `supervisor.task.created`        | task  |
| `supervisor.task.evaluating`     | task  |
| `supervisor.task.completed`      | task  |
| `supervisor.task.failed`         | task  |
| `supervisor.task.partial`        | task  |
| `supervisor.task.eval_failed`    | task  |
| `supervisor.task.cancelled`      | task  |
| `supervisor.job.launched`        | job   |
| `supervisor.job.enqueued`        | job   |
| `trigger.external.received`      | —     |

### 9. Event Domain System

Each registered domain is a single module under `pasloe/domains/` that
bundles:

- **Detail model** (SQLAlchemy table with indexed columns flattened from
  event data)
- **API routes** (FastAPI router under a domain-specific prefix)
- **Stats queries** (aggregation over the detail table)
- **`from_event` / `to_payload`** (typed extraction and normalized response)

Detail tables provide indexed access to fields inside event data — portable
to both PostgreSQL and SQLite. One row per event (no entity snapshot, no
upsert). The `events.data` JSONB column is retained as the canonical
representation and for webhook delivery.

If detail extraction fails for a registered event type, the committed event
is preserved and the detail-write failure is surfaced operationally. Event
visibility is never blocked behind a domain parsing bug.

### 10. Domain API Endpoints

Each registered domain exposes routes:

```
GET  /tasks         — query task events (task_id, state, team filters)
GET  /tasks/stats   — task event statistics and derived task metrics
GET  /jobs          — query job events (job_id, task_id, role, status)
GET  /jobs/stats    — job event statistics and derived job metrics
GET  /llm           — query LLM call events (job_id, model filters)
GET  /llm/stats     — token/cost aggregation by model and time range
GET  /tools         — query tool execution events (job_id, tool_name)
GET  /tools/stats   — tool statistics (group by tool_name, success rate)
```

The generic `GET /events` is preserved for envelope-level queries and
unregistered event types. Pasloe domain endpoints are **historical event
views**, not live entity snapshots. Trenni control endpoints are the live
operational view:

```
GET  /control/tasks              — list tasks (state, team filters)
GET  /control/tasks/{task_id}    — task detail (job_order, eval state, result)
GET  /control/jobs               — list jobs (task_id, role, queue/running)
GET  /control/jobs/{job_id}      — job detail (condition, runtime handle)
```

### 11. Unified CLI

A `yoitsu` CLI provides the operator interface:

```
yoitsu status              — system overview (trenni + pasloe + podman)
yoitsu tasks               — list tasks (queries trenni live state)
yoitsu tasks <id>          — task detail + job trace
yoitsu events              — recent events (queries pasloe)
yoitsu jobs                — job listing (queries pasloe /jobs)
yoitsu llm-stats           — LLM token/cost summary
yoitsu submit <file>       — submit trigger event from file
yoitsu submit <goal> --goal --budget <amount>  — submit raw goal (requires budget > 0)
yoitsu deploy              — wraps deploy-quadlet.sh
```

Config: `~/.config/yoitsu/config.yaml` or environment variables
(`YOITSU_PASLOE_URL`, `YOITSU_TRENNI_URL`, `PASLOE_API_KEY`).

### 12. Evo: The Evolvable Layer

The `evo/` directory contains roles, contexts, and tools that define how
jobs execute. These are Python modules consumed by Palimpsest at runtime.
They are the unit of system evolution — agents can modify evo during
self-optimization without touching runtime code.

Evo structure:

```
evo/
├── roles/       — role functions (return JobSpec)
├── contexts/    — context providers
├── tools/       — tool implementations
└── prompts/     — prompt templates
```

See ADR-0003 for the role function model, team composition, and publication
protocol.

## Consequences

### Positive

- Job and task lifecycle is understandable from events alone.
- Replay and checkpoint have stable, auditable state structures.
- Palimpsest is replaceable; any executor can consume spawn payloads.
- Adding a new event domain requires one file and one Alembic migration.
- Pasloe and Trenni share typed contracts instead of ad hoc dict parsing.

### Tradeoffs

- Intake/execution phase split adds intermediate event volume.
- Event type rename requires coordinated migration across contracts and
  producers.
- Detail tables are redundant with `events.data` for registered types.
- Pasloe domain endpoints are historical; operators must use Trenni control
  endpoints for live scheduler state.

### Non-Goals

- Global backpressure and rate shaping in Pasloe.
- Exactly-once webhook semantics across external systems.
- Schema-aware event validation inside Pasloe.
- Task persistence in Trenni (in-memory state with event replay is
  sufficient at current scale).
- Condition-based alerting (can be added later as a Trenni feature emitting
  alert events).
