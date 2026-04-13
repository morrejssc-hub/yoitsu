# Yoitsu Architecture

Date: 2026-04-02
Status: Consolidated from ADRs, code, and design discussion

## System Identity

Yoitsu is a self-evolving LLM agent system. It decomposes goals into tasks,
executes them via containerized agent jobs, evaluates results, and allows
agents to modify the logic governing their own execution.

## Dual Source of Truth

The system has two authoritative persistence layers:

1. **Pasloe event stream** -- records what happened (task lifecycle, job
   outcomes, observations, spawn requests, LLM/tool calls).
2. **Artifact store** (ADR-0013) -- records what was produced (directory
   trees, files, reports, checkpoints).

Everything else is derived or ephemeral:

- Workspace directories (private copies for each job)
- Trenni in-memory state (rebuilt from event replay)
- Git branches (external compatibility receipts)
- Process-internal return values

## Four Components

### Pasloe -- Event Store

Append-only, schema-agnostic event log with two-stage delivery:

- **Ingest**: producers receive `accepted` (durability boundary)
- **Committed**: consumers read only committed events
- **Domain tables**: indexed projections for jobs, tasks, LLM, tools
- **Webhooks**: async fan-out to consumers

Pasloe does not interpret task semantics. It stores and delivers events.

### Trenni -- Scheduler and Control Plane

Deterministic, non-evolvable control plane:

- **Task state machine**: pending -> running -> evaluating -> terminal
- **Spawn expansion**: agent.job.spawn_request -> child tasks + jobs + join
- **Condition evaluation**: TaskIs, All, Any, Not condition trees
- **Job launch**: queue drain, container lifecycle via PodmanBackend
- **Replay/checkpoint**: state reconstruction from committed events
- **Team isolation** (ADR-0011): per-team runtime profiles, scheduling
  constraints, evo layer resolution
- **Artifact store ownership** (ADR-0013): hosts the store directory,
  configures container access

Trenni has no dependency on evo. It treats spawn payloads as opaque blobs.
Its decision logic is hardcoded and not subject to evolution. Task
decomposition decisions belong to the planner role (an LLM judgment in
Palimpsest), not to Trenni.

### Palimpsest -- Job Executor

Single-job, four-stage pipeline executor. Runs inside Podman containers.

```
preparation -> context -> interaction -> publication
```

Each job is a single attempt: short-lived, disposable, allowed to fail
honestly. The four stages are causally sequential (each depends on the
prior stage's output). This ordering is a dependency chain, not a design
choice.

**Preparation** (via preparation_fn):
- Materializes input artifacts / clones git repo into private workspace
- Installs dependencies, fetches context, stages files
- Establishes short-lived resources (e.g. RCON bridge for Factorio)

**Context** (via context_fn):
- Builds AgentContext: system prompt, goal, available tools
- Loads context providers (eval_context, join_context, job_trace, etc.)
- Queries Pasloe for relevant events

**Interaction** (LLM loop):
- LLM calls + tool execution until idle detection or budget exhaustion
- Emits agent.llm.* and agent.tool.* events
- Produces candidate summary on idle exit

**Publication** (via publication_fn):
- Stores workspace output as artifact (canonical output)
- Optionally pushes to git remote (compatibility receipt)
- Returns artifact bindings + optional git_ref
- Failure = job failure (never silent)

### yoitsu-contracts -- Shared Types

Cross-repo boundary definitions:

- Event schemas (BaseEvent, all *Data models)
- Configuration types (JobConfig, TriggerData, SpawnTaskData, etc.)
- Condition serialization (TaskIs, All, Any, Not)
- Role metadata (RoleMetadataReader)
- Observation event types (budget_variance, tool_retry, etc.)
- Artifact types (ArtifactRef, ArtifactBinding, ArtifactBackend protocol)

## Artifact Store (ADR-0013)

Content-addressed, immutable object store. Two object kinds in first
version:

- **blob**: immutable byte sequence
- **tree**: directory snapshot (canonical tar with deterministic
  normalization)

Key properties:

- ArtifactRef is pure physical identifier (no semantics)
- ArtifactBinding pairs a ref with a relation string in event payloads
- Content addressing: identical content -> identical ref
- Copy-in/copy-out execution contract: jobs work on private copies,
  never mutate the store directly
- Trenni owns the store instance; job containers access through a
  mediated mechanism (cannot overwrite existing artifacts)
- First backend: LocalFSBackend (shared volume on single host)

git_ref is retained as a compatibility field but is not the canonical
output. The canonical output is artifact bindings in the completion event.

## Evolvable Layer (evo/)

The unit of system evolution. Agents modify evo/ during self-optimization
without touching runtime code.

```
evo/
  roles/           -- global roles (planner, implementer, evaluator, etc.)
  tools/           -- global tools
  prompts/         -- global prompt templates
  contexts/        -- global context providers
  teams/
    <team>/
      roles/       -- team-specific (shadows global by name)
      tools/
      prompts/
      contexts/
```

Two-layer resolution (ADR-0011): team-specific artifacts shadow global
artifacts of the same name. A role at `evo/teams/factorio/roles/worker.py`
is visible only to the factorio team.

Evolvable points:
- Role functions (return JobSpec)
- Preparation functions (workspace setup)
- Publication functions (output delivery)
- Context providers (prompt assembly)
- Tools (agent capabilities)
- Prompts (system/user prompt templates)

Not evolvable: Trenni's state machine, Pasloe's event pipeline, Palimpsest's
four-stage skeleton, condition evaluation logic.

## Task and Job Lifecycle

### Task (logical work unit, managed by Trenni)

```
pending -> running -> evaluating -> completed
                                 -> failed
                                 -> partial
                                 -> cancelled
                                 -> eval_failed
```

### Job (execution unit, one Palimpsest run)

Terminal events: agent.job.completed, agent.job.failed, agent.job.cancelled

### Two-Layer Verdict

- **Structural** (always present): derived from job terminal states
- **Semantic** (optional): produced by eval job (pass/fail/unknown)

### Spawn as Sole Orchestration Primitive

Agent calls spawn(tasks=[...]) -> Trenni expands into child tasks + jobs +
optional join job. No pre-defined DAGs. The planner decides decomposition.

### Typical Flow

```
trigger -> Trenni creates root task (pending)
  -> launch planner job
    -> planner explores, calls spawn(tasks=[...])
  -> Trenni expands children + jobs + join
  -> launch worker jobs (condition-gated)
    -> worker does work, publishes artifacts
  -> worker completed -> evaluating -> launch eval job
    -> evaluator judges quality
  -> eval completed -> task terminal
  -> all children terminal -> launch join job
    -> join reviews children, may create PR
  -> root task completed
```

## Budget Model (ADR-0004)

Budget is a prediction, not enforcement:

- Planner estimates cost per child task
- Runtime does not enforce cost-based termination
- System backstops: max_iterations_hard, job_timeout, tool_timeout
- budget_variance observation drives self-optimization feedback
- Partial signal: budget_exhausted + publication succeeded -> task.partial

## Self-Optimization (ADR-0010)

Closed-loop self-improvement via normal task pipeline:

1. Structured observation events (budget_variance, tool_retry, etc.)
2. Review task triggered by accumulation threshold
3. Review produces improvement proposals
4. Proposals become normal optimization tasks (modify evo/)
5. Budget prediction accuracy as proxy metric

No special optimization mode, no privileged access. Optimization tasks
compete for resources like any other task.

## Team Isolation (ADR-0011)

Team = runtime environment + evolutionary scope:

- Runtime profile: container image, pod, networks, env vars
- Scheduling: max_concurrent_jobs per team
- Evo scope: evo/teams/<team>/ for specialization

Team membership by directory location, not decorator. Teams declared in
Trenni config. The scheduler sees jobs with conditions, not teams.

## Event Naming Convention

```
<source>.<model>.<state>
```

- source: agent, supervisor, trigger
- model: job, task, llm, tool
- state: started, completed, request, exec, etc.

## Deployment

Quadlet (systemd-integrated Podman):
- pasloe.container + postgres.container on pasloe.network
- trenni.container
- yoitsu-dev.pod
- Job containers launched by Trenni via PodmanBackend
