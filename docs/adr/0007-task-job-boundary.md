# ADR-0007: Task/Job Information Boundary

- Status: Accepted
- Date: 2026-03-29
- Implemented: 2026-03-29
- Supersedes: ADR-0002 Decision 6 (spawn payload schema)
- Amends: ADR-0003 Decision 5 (role metadata mechanism)
- Related: ADR-0001, ADR-0002, ADR-0003

## Context

ADR-0001 established the principle that task and job are strictly separated,
with Trenni as the sole authority for task state. The principle is sound but
has not been enforced at the information level. Analysis of the current
implementation revealed several concrete violations:

1. **`goal` flows through three channels simultaneously.** `JobConfig.task`,
   `role_params["goal"]`, and `EvalContextConfig.goal` all carry the same
   text. `context_fn` reads from `role_params["goal"]`, not from
   `JobConfig.task`. If these diverge (e.g. the planner reformulates a goal
   in the spawn payload), the event record and the LLM context describe
   different goals with no observable signal.

2. **`budget` is written into two channels at spawn time.** `spawn_handler`
   sets both `role_params["budget"]` and `llm_overrides["max_total_cost"]`
   from the same spawn value. `_allocated_job_budget` reads from both with
   `role_params` taking precedence. The two channels can drift.

3. **Spawn payload leaks execution config.** `SpawnedJob` carries
   `llm_overrides`, `workspace_overrides`, and `publication_overrides` that
   are inherited by child jobs. This allows a planner agent's runtime behavior
   to determine the execution config of all its descendants — bypassing role
   definition as the authoritative source.

4. **Role catalog is cached permanently.** `_role_catalog_cache` is populated
   once at supervisor startup and never invalidated. In a self-evolving system
   where `evo/` changes are expected during operation, new and modified roles
   are invisible until the supervisor process restarts.

5. **Two independent mechanisms read role metadata.** Trenni uses AST
   `literal_eval` to extract role decorator keywords; Palimpsest uses
   `importlib` to execute the module. Computed decorator arguments (any
   non-literal expression) are parsed correctly by `importlib` but silently
   fail or error under AST parsing. The two mechanisms can disagree without
   any observable discrepancy.

This ADR defines the authoritative information model, makes the task/job
boundary explicit in terms of data ownership, and specifies the corrections
required to bring the implementation into alignment.

## Decisions

### 1. Three Categories of Information

Every field in the system belongs to exactly one category:

**Task semantics** — what is being attempted and how to verify it.
Owned by the trigger event and the spawn payload. Lives in Trenni's
`TaskRecord`. Passed to Palimpsest as read-only inputs.

| Field | Where |
|-------|-------|
| `task_id` | `TaskRecord`, `JobConfig` (reference, not ownership) |
| `goal` | `TaskRecord.goal`, `JobConfig.task` (single copy) |
| `repo`, `init_branch` | Spawn payload → `TaskRecord.spec` → `JobConfig.workspace` |
| `budget` | Spawn payload → `JobConfig.llm.max_total_cost` (single write) |
| `eval_spec` | `TaskRecord.eval_spec` |
| `team` | Trigger → `TaskRecord.team`; inherited by all descendant tasks. Not overridable in spawn payload. |

**Execution config** — how the job runs. Owned by the role definition
(`evo/roles/*.py`). Derived by Trenni from the role at job-config assembly
time. Not settable at spawn time or runtime.

| Field | Source |
|-------|--------|
| `llm.model`, `llm.max_iterations`, `llm.*` | Role metadata + `TrenniConfig.default_llm` |
| `workspace.new_branch`, `workspace.depth` | `workspace_fn` in role |
| `tools` | `JobSpec.tools` |
| `publication.strategy`, `publication.branch_prefix` | `publication_fn` in role |

**Runtime identity** — mechanical fields assigned by Trenni at job creation.

| Field | Source |
|-------|--------|
| `job_id` | Trenni (hash-derived from parent + spawn event + index) |
| `evo_sha` | Inherited from parent job or spawn payload `sha` field |
| `eventstore.*` | Trenni config |
| `container_name`, `image`, labels | `RuntimeSpecBuilder` |

### 2. Spawn Payload Boundary

The spawn payload is a task-semantics document. It describes what sub-tasks
need to happen. It does not describe how those sub-tasks execute.

This decision supersedes the spawn payload schema in ADR-0002 Decision 6.
The canonical payload shape is:

```json
{
  "goal":      "...",
  "role":      "implementer",
  "repo":      "https://github.com/org/repo",  // optional; omit for repoless jobs
  "budget":    0.80,
  "sha":       "abc123",
  "eval_spec": { "deliverables": [...], "criteria": [...] }
}
```

All fields are top-level. The `params: dict` field in the previous schema
is removed. Fields that were previously tunneled through `params`
(`goal`, `budget`, `repo`) are now first-class fields with defined semantics.

`team` is not part of the spawn payload. It is set once at trigger time and
inherited by all descendant tasks. Trenni fills it from the parent
`TaskRecord` during spawn expansion; the planner cannot override it.

**Not permitted in spawn payload:** any field from the execution config
category — model selection, workspace behavior, publication strategy.
`SpawnedJob`, `SpawnDefaults`, and `SpawnTaskData` must not carry
`llm_overrides`, `workspace_overrides`, or `publication_overrides`.

`role` in the spawn payload is a task-semantics field: it is the planner's
decision about which role type should accomplish this sub-goal. It is not
execution config — it is the key that Trenni uses to derive execution config
from the role definition.

`role` is optional. When omitted, Trenni selects the first entry from the
team's `worker_roles` list. Declaration order in `@role(teams=[...])` is the
implicit priority order. This default policy is intentionally simple;
`TeamDefinition` may gain a `role_selector` field in a future ADR to support
more sophisticated routing without changing the spawn payload contract.

### 3. Execution Config Is Derived from Role Definition

When Trenni assembles a `JobConfig` for a new job, execution config fields
are populated from two authoritative sources only:

1. **Role definition** (`evo/roles/<role>.py`) — via the shared role metadata
   reader (see Decision 9). This provides workspace behavior, tool list,
   publication strategy, and any role-specific LLM constraints.
2. **`TrenniConfig.default_llm`** — provides system-level LLM defaults
   (model, retry policy, token limits). Role metadata (`min_cost`,
   `min_capability`) can constrain these defaults but cannot be overridden
   from spawn payloads or runtime.

Changing execution config requires an `evo/` commit. There is no runtime
mechanism to override it. This is not a limitation — it is the guarantee that
makes `evo/` the authoritative record of how the system behaves.

### 4. `goal` Is a First-Class Field

`goal` is a task-semantics field. It must not travel through `role_params`.

- `JobConfig.task` is the single authoritative copy of the goal text.
- Palimpsest reads the goal from `JobConfig.task` directly.
- `context_fn` receives `goal` as an explicit argument, not via `**params`.
- `role_params` contains only role-internal behavior parameters — flags
  that control how the role executes, not what it is working on. For
  example, `mode="join"` switches the planner between initial decomposition
  and join-phase assessment; this is a role execution mode, not task content.
  No task-level content belongs in `role_params`.

**Join job:** The join job's synthetic goal (a formatted instruction to review
completed children) is written to `JobConfig.task`, not to `role_params`.
`role_params` for the join job carries only `mode="join"`. The original
parent goal, previously passed as `role_params["parent_goal"]`, is moved to
`JobContextConfig.join.parent_summary`, which already exists for this
purpose.

### 5. `budget` Has a Single Channel

`budget` is a task-semantics field that maps to one execution constraint.

- Trenni writes `budget` to exactly one place: `JobConfig.llm.max_total_cost`.
- `budget` is not written into `role_params`.
- `_allocated_job_budget` reads from `JobConfig.llm.max_total_cost` only.
- When `budget` is absent from the spawn payload, `JobConfig.llm.max_total_cost`
  inherits from `TrenniConfig.default_llm.max_total_cost`. This is an
  execution config default, not a task-semantics value; the spawn payload
  omitting `budget` means "use system default", not "unconstrained".

### 6. Task:Job = 1:1 at Leaf Level Is Intentional

Each leaf task (a task created by a spawn) has exactly one execution job.
This is a deliberate design property, not a limitation.

Multi-attempt behavior is handled via the join mechanism: when a child task
is partial or failed, the join job receives the full outcome context and
decides whether to spawn targeted follow-up tasks. This is preferable to
mechanical job retry because the join agent can reason about what was
accomplished, what is missing, and what role (if any different) should
address the gap.

The task layer carries independent value even in a 1:1 binding: it is the
unit of eval, the unit of budget allocation, and the unit of evolutionary
comparison across team versions.

### 7. Trenni's Dual Responsibility

Trenni is responsible for two distinct operations that must not be conflated:

**Task state management** — owns the task lifecycle state machine
(`pending → running → evaluating → terminal`), tracks task hierarchy,
computes structural verdicts, spawns eval jobs, maintains `TaskRecord`.
This operation has no dependency on role definitions.

**Job config assembly** — translates a `(TaskRecord, role_name)` pair into
a fully-specified `JobConfig` by combining task semantics (category 1) with
execution config derived from the role definition (category 2) and runtime
identity fields (category 3).

These two operations happen at different points in the event loop. Task state
management happens whenever a task event is received. Job config assembly
happens immediately before a container is launched.

### 8. Trenni–Palimpsest Collaboration Model

The collaboration is push-based and Pasloe-mediated:

```
Trenni → [JobConfig via env var] → Palimpsest container
Palimpsest container → [agent.job.* events] → Pasloe → Trenni
```

**Trenni → Palimpsest:** Trenni serializes `JobConfig` to base64 YAML and
passes it as `PALIMPSEST_JOB_CONFIG_B64` in the container environment. This
is a complete, self-contained specification of the job. Palimpsest requires
no network call to start.

**Palimpsest → Trenni:** Palimpsest emits events to Pasloe. Trenni consumes
Pasloe events to update task state and trigger subsequent actions (spawn eval,
advance join conditions, etc.). Palimpsest has no direct channel back to
Trenni; it has no Trenni client.

**Task context (join, eval)** is pre-computed by Trenni and embedded in
`JobConfig.context` before the container starts. Palimpsest does not query
Pasloe for task history at startup. This push model keeps Palimpsest
stateless and reduces startup dependencies.

**Observability events:** `SupervisorJobLaunchedData` and
`SupervisorJobEnqueuedData` carry `llm`, `workspace`, and `publication` dict
fields. After this change these fields contain the fully-resolved config
(derived from role + defaults), not override deltas. This makes the launched
event a complete record of what the job actually ran with, improving
observability without schema changes.

Palimpsest has no task awareness beyond what is in its `JobConfig`. It does
not know whether it is the first or fifth job under a task. It does not know
the task's current state.

### 9. Role Metadata: Shared Reader, Single Mechanism

This decision amends ADR-0003 Decision 5. ADR-0003 stated that Trenni has
zero dependency on evo. That constraint remains true for role *execution* —
Trenni never calls a role function. It is amended for role *metadata*: Trenni
and Palimpsest must use the same code to read role metadata.

The implementation splits the current `RoleManager` responsibility into two
layers:

**`RoleMetadataReader`** (extracted to `yoitsu-contracts`): reads `@role`
decorator metadata from `evo/roles/*.py` using AST scanning. Does not execute
modules. Produces `RoleMetadata` instances. Importable by both Trenni and
Palimpsest without triggering role module execution or palimpsest pipeline
imports.

**`RoleManager`** (remains in `palimpsest.runtime.roles`): extends
`RoleMetadataReader` with `resolve()`, which loads and executes a role module
via `importlib` to produce a `JobSpec`. Used only inside Palimpsest containers.

Trenni replaces its current hand-written AST catalog with `RoleMetadataReader`
from `yoitsu-contracts`. This is the only new import Trenni gains; it does
not import `RoleManager`, `JobSpec`, or any palimpsest pipeline stage.

**Constraint:** `@role` decorator arguments must be constant expressions
(string and numeric literals). `RoleMetadataReader` calls `ast.literal_eval`
on each decorator keyword; a non-literal expression (e.g. `min_cost=BASE *
1.5`) raises a `ValueError` at scan time — when the reader loads the file,
not at job execution time. This must be documented in the `@role` decorator's
docstring. The failure is loud and immediate, not a silent metadata gap.

**Catalog invalidation:** Before each spawn expansion, Trenni reads the
current HEAD sha from the evo root (`git rev-parse HEAD`). If this differs
from the sha used to populate the cache, the cache is cleared before
proceeding. This ensures budget validation and role resolution during spawn
always reflect the current `evo/` state. The git read happens once per spawn
event; spawn frequency is low enough that this is not a performance concern.

## Consequences

### Positive

- `goal` has one authoritative location; event records and LLM context
  cannot diverge silently.
- Execution config cannot be manipulated through spawn payloads; a planner
  agent cannot alter its descendants' model or workspace behavior.
- `budget` has one write location; validation is unambiguous.
- Role definition is the sole source of execution config; changing behavior
  requires an `evo/` commit, making changes auditable and reversible.
- Role catalog reflects the current `evo/` state; self-evolution takes effect
  before the next spawn expansion, without supervisor restart.
- Single role metadata mechanism eliminates the AST/importlib divergence.
- Launched events carry fully-resolved config; job behavior is fully
  observable from the event record without reconstructing defaults.
- Join job follows the same `goal` rules as all other jobs; no special cases.

### Tradeoffs

- `RoleMetadataReader` must be extracted to `yoitsu-contracts` and kept free
  of execution logic. Future role metadata fields that require runtime
  evaluation cannot be read by Trenni; they must remain Palimpsest-only.
- Removing `llm_overrides`, `workspace_overrides`, `publication_overrides`
  from `SpawnedJob` and `SpawnDefaults` is a structural change to the state
  model. Existing event payloads that carry these fields will have them
  ignored on replay.
- Planners that currently pass model hints through `role_params` must have
  those hints removed from their prompts. The effective model is determined
  by the role definition.
- `@role` decorator arguments are restricted to constant expressions. This
  is a minor authoring constraint but prevents a class of silent metadata
  divergence.

### Non-Goals

- Dynamic role selection based on runtime load or capability matching.
- Pull-based task context (Palimpsest querying Pasloe at startup).
- Cross-job budget pooling at the task level.
- Automatic job retry for partial tasks (handled by join → spawn).
- Role metadata that requires runtime evaluation (deferred to a future ADR
  if needed).
