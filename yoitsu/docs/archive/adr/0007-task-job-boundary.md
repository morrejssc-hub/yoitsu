# ADR-0007: Task Semantics and Spawn Contract

- Status: Accepted (Consolidated 2026-04-02)
- Date: 2026-03-29
- Revised: 2026-04-02
- Consolidates: original ADR-0007, ADR-0008
- Implemented: 2026-03-29 (ADR-0007), 2026-03-31 (ADR-0008)
- Supersedes: ADR-0002 Decision 6 (spawn payload schema)
- Amends: ADR-0003 Decision 5 (role metadata mechanism)
- Related: ADR-0001, ADR-0002, ADR-0003, ADR-0004

## Context

ADR-0001 established that task and job are strictly separated, with Trenni
as the sole authority for task state. This ADR enforces that principle at
the information level by defining:

1. What information belongs to which layer (task semantics vs execution
   config vs runtime identity).
2. What the spawn payload may and may not contain.
3. How tasks enter the system (spawn requests and external triggers).
4. How Trenni assembles job configurations from these inputs.

This consolidates two previously separate decisions: the task/job
information boundary (original ADR-0007) and task creation and ingestion
(ADR-0008).

## Decisions

### 1. Three Categories of Information

Every field in the system belongs to exactly one category:

**Task semantics** -- what is being attempted and how to verify it.
Owned by the trigger event and the spawn payload. Lives in Trenni's
TaskRecord. Passed to Palimpsest as read-only inputs.

| Field | Location |
|-------|----------|
| task_id | TaskRecord, JobConfig (reference) |
| goal | TaskRecord.goal, JobConfig.task (single copy) |
| repo, init_branch | Spawn payload -> TaskRecord.spec -> JobConfig.workspace |
| budget | Spawn payload -> JobConfig.llm.max_total_cost (single write) |
| eval_spec | TaskRecord.eval_spec |
| team | Trigger -> TaskRecord.team; inherited, not overridable |

**Execution config** -- how the job runs. Owned by the role definition
in evo/. Derived by Trenni at job-config assembly time. Not settable at
spawn time or runtime.

| Field | Source |
|-------|--------|
| llm.model, llm.max_iterations, llm.* | Role metadata + TrenniConfig.default_llm |
| workspace.new_branch, workspace.depth | preparation_fn in role |
| tools | JobSpec.tools |
| publication.strategy, publication.branch_prefix | publication_fn in role |

**Runtime identity** -- mechanical fields assigned by Trenni at job
creation.

| Field | Source |
|-------|--------|
| job_id | Hash-derived from parent + spawn event + index |
| evo_sha | Inherited from parent job or spawn payload sha field |
| eventstore.* | Trenni config |
| container_name, image, labels | RuntimeSpecBuilder |

### 2. Spawn Payload Boundary

The spawn payload is a task-semantics document. It describes what sub-tasks
need to happen. It does not describe how those sub-tasks execute.

Canonical payload shape:

```json
{
  "goal":      "...",
  "role":      "implementer",
  "repo":      "https://github.com/org/repo",
  "budget":    0.80,
  "sha":       "abc123",
  "eval_spec": { "deliverables": [...], "criteria": [...] }
}
```

All fields are top-level. The `params: dict` field in the previous schema
is restricted to role-internal behavior flags only (e.g. mode="join").

**Not permitted in spawn payload:** any execution config field -- model
selection, workspace behavior, publication strategy.

**team** is not part of the spawn payload. It is set once at trigger time
and inherited by all descendant tasks. The planner cannot override it.

### 3. Spawn Requests May Omit Role; Trenni Defaults to Planner

If `role` is absent from the spawn payload, Trenni assigns `planner` as
the first job's role. The planner receives only the goal, reads whatever
context it needs, then spawns concrete sub-tasks with explicit roles.

This means agents can spawn sub-tasks by stating what needs to be done,
without specifying how. Fully specified spawn requests (with role) continue
to work as before.

### 4. goal Is a First-Class Field

`goal` is a task-semantics field. It must not travel through role_params.

- JobConfig.task is the single authoritative copy.
- context_fn receives goal as an explicit argument, not via **params.
- role_params contains only role-internal behavior flags (e.g. mode="join").
- Join job: synthetic goal written to JobConfig.task. Original parent goal
  lives in JobContextConfig.join.parent_summary.

### 5. budget Has a Single Channel

- Trenni writes budget to exactly one place: JobConfig.llm.max_total_cost.
- budget is not written into role_params.
- When budget is absent from spawn, system default is used.

### 6. Execution Config Is Derived from Role Definition

When Trenni assembles a JobConfig, execution config comes from two sources
only:

1. **Role definition** (evo/roles/*.py) via RoleMetadataReader.
2. **TrenniConfig.default_llm** for system-level LLM defaults.

Changing execution config requires an evo/ commit. There is no runtime
override mechanism. This makes evo/ the authoritative record of how the
system behaves.

### 7. Task:Job = 1:1 at Leaf Level

Each leaf task has exactly one execution job. Multi-attempt behavior is
handled via the join mechanism: when a child task is partial or failed, the
join job decides whether to spawn follow-up tasks. This is preferable to
mechanical retry because the join agent reasons about what was accomplished.

The task layer carries value even in 1:1 binding: it is the unit of eval,
the unit of budget allocation, and the unit of evolutionary comparison.

### 8. External Event -> Task Translation Lives in Trenni

Pasloe remains domain-agnostic. Trenni gains a trigger evaluator that
processes new events from its existing Pasloe poll loop.

Triggers are declarative rules in Trenni config:

```yaml
triggers:
  - name: "ci_failure"
    match:
      type: "github.ci.completed"
      data.conclusion: "failure"
    spawn:
      goal: "investigate and fix CI failure: {{data.summary}}"

  - name: "optimization_review"
    match:
      type: "observation.*"
      accumulate: 20
    spawn:
      goal: "review recent observation signals and propose improvements"
```

When a trigger matches, Trenni creates a normal task. No special code path.
Trigger evaluation runs as an additional step in the existing poll loop:

1. Poll new events from Pasloe (existing)
2. Route task/job events to supervisor state machine (existing)
3. Evaluate remaining events against trigger rules (new)
4. Matched triggers create tasks through normal task creation path

### 9. Trenni-Palimpsest Collaboration Model

Push-based and Pasloe-mediated:

```
Trenni -> [JobConfig via env var] -> Palimpsest container
Palimpsest -> [agent.job.* events] -> Pasloe -> Trenni
```

Trenni serializes JobConfig to base64 YAML in PALIMPSEST_JOB_CONFIG_B64.
Palimpsest emits events to Pasloe. Palimpsest has no direct channel back
to Trenni.

Task context (join, eval) is pre-computed by Trenni and embedded in
JobConfig.context before the container starts.

### 10. Role Metadata: Shared Reader, Single Mechanism

RoleMetadataReader (in yoitsu-contracts): reads @role decorator metadata
via AST scanning. Does not execute modules. Importable by both Trenni and
Palimpsest.

RoleManager (in palimpsest.runtime.roles): extends RoleMetadataReader with
resolve(), which loads and executes role modules to produce JobSpec.

@role decorator arguments must be constant expressions. Non-literal
expressions raise ValueError at scan time.

Catalog invalidation: before each spawn expansion, Trenni reads current evo
HEAD sha. If it differs from the cached sha, the cache is cleared. This
ensures self-evolution takes effect before the next spawn.

## Consequences

### Positive

- goal has one authoritative location; event records and LLM context
  cannot diverge silently.
- Execution config cannot be manipulated through spawn payloads.
- budget has one write location; validation is unambiguous.
- Role definition is the sole source of execution config; changes are
  auditable via evo/ commits.
- Agents can spawn sub-tasks without knowing role details; planner handles
  decomposition.
- External event ingestion requires no Pasloe changes; Trenni handles
  translation.
- Single role metadata mechanism eliminates AST/importlib divergence.

### Tradeoffs

- RoleMetadataReader must stay free of execution logic.
- Removing override fields from SpawnedJob is a structural change; existing
  event payloads with these fields will have them ignored on replay.
- @role decorator restricted to constant expressions.
- Trigger rules are evaluated in the poll loop, adding latency proportional
  to rule count.

### Non-Goals

- Dynamic role selection based on runtime load.
- Pull-based task context (Palimpsest querying Pasloe at startup).
- Cross-job budget pooling at the task level.
- Automatic job retry for partial tasks.
- Sophisticated trigger batching (time windows, cooldown, adaptive
  thresholds) -- deferred to Phase 5.
- Source-level event deduplication -- deferred to Phase 2 external event
  integration.
