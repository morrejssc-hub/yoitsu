# Yoitsu System Architecture

Date: 2026-04-02
Status: Normative baseline. Supersedes prior system-level descriptions.

## 1. Scope and Authority

This document is the single normative entry point for the Yoitsu system
design. It describes what the system IS in the current codebase. In-flight
ADRs are called out explicitly when they describe accepted direction that
has not yet landed in code.

Normative sources, in order of authority:

1. Current code (four repositories + evo/)
2. This document
3. In-flight ADRs in `docs/adr/` for design areas not yet folded into this
   baseline

When this document conflicts with code, code wins. Historical ADRs in
`docs/adr/archive/` and materials in `docs/archive/` are retained for
decision history, not as day-to-day entry points.

Non-normative companion documents:

- [component-map.md](component-map.md) -- file paths, directory layout,
  event type table
- [redesign-evaluation.md](redesign-evaluation.md) -- why certain
  alternative designs were rejected
- [design-principles.md](design-principles.md) -- extracted invariants and
  conventions
- [test-operations.md](test-operations.md) -- long-running test and
  operator procedures

## 2. System Identity and Current Durable State

Yoitsu is a self-evolving LLM agent system. It decomposes goals into tasks,
executes them via containerized agent jobs, evaluates results, and allows
agents to modify the logic governing their own execution.

The current code has one authoritative system-wide persistence layer:

- **Pasloe event stream** -- records what happened: task lifecycle, job
  outcomes, observations, spawn requests, LLM and tool calls.

For git-backed jobs, durable output is additionally published through git
and surfaced as `git_ref` in `agent.job.completed`. That gives the system a
usable publication path today, but it is not a general-purpose physical
artifact layer.

Everything else is derived or ephemeral:

| Category | Example | Status |
|----------|---------|--------|
| Execution substrate | Workspace directories | Private copy, disposable |
| Scheduler state | Trenni TaskRecord, ready queue | Rebuilt from event replay |
| External coordination | Git branches, PRs, git_ref | Durable for git-backed jobs only |
| Process-internal | Return values, runtime memory | Lost on restart |

Git is therefore both the current publication mechanism and the main
external collaboration protocol. ADR-0013 proposes an artifact store as a
future second persistence layer, but that subsystem is not implemented yet.

## 3. Component Boundaries

### 3.1 Pasloe -- Event Store

Append-only, schema-agnostic event log.

**Responsibilities:**
- Durable ingest with `accepted` acknowledgement
- Committed event visibility for consumers
- Domain detail tables (jobs, tasks, llm, tools) as indexed projections
- Webhook fan-out to consumers

**Does not do:** task semantics, scheduling, artifact storage, business
logic.

Reference: ADR-0001 sections 6, 9, 10.

### 3.2 Trenni -- Scheduler and Control Plane

Deterministic, non-evolvable task control plane.

**Responsibilities:**
- Task state machine (pending -> running -> evaluating -> terminal)
- Spawn expansion (spawn_request -> child tasks + jobs + join job)
- Condition evaluation (TaskIs, All, Any, Not)
- Job queue drain and container launch via PodmanBackend
- Replay and checkpoint (state reconstruction from committed events)
- Team isolation: per-team runtime profiles, scheduling constraints,
  evo layer resolution (ADR-0011)
- JobConfig assembly from Trenni defaults, spawn semantics, and team runtime
  settings

**Does not do:** execute agent logic, consume evo/ code, make semantic
task decomposition decisions. Trenni treats spawn payloads as opaque blobs.
It has no dependency on evo.

Reference: ADR-0001 sections 5, 7; ADR-0011 D1, D4, D5.

### 3.3 Palimpsest -- Job Executor

Single-job, four-stage pipeline executor. Runs inside Podman containers.
Each job is a single attempt: short-lived, disposable, allowed to fail
honestly.

**Responsibilities:**
- Resolve role function from evo/ at pinned SHA
- Execute four-stage pipeline (see section 5)
- Emit agent.* events throughout execution
- Produce `git_ref` on completion when branch publication runs; planner and
  evaluator roles normally skip publication

**Does not do:** task-level orchestration, scheduling, sibling awareness,
retry decisions.

Reference: ADR-0003 sections 1-5; ADR-0009.

### 3.4 yoitsu-contracts -- Shared Types

Cross-repository boundary definitions consumed by all components:

- Event schemas (BaseEvent, all *Data models)
- Configuration types (JobConfig, TriggerData, SpawnTaskData)
- Condition serialization (TaskIs, All, Any, Not)
- Role metadata (RoleMetadataReader)
- Observation event types (budget_variance, tool_retry, etc.)
- Preparation/publication config types shared between Trenni and Palimpsest

### 3.5 Artifact Store (ADR-0013)

Artifact contracts have landed in `yoitsu-contracts`:

- `ArtifactRef` and `ArtifactBinding` models define the physical identifier
  and semantic binding structure.
- `JobCompletedData` accepts `artifact_bindings` as an optional field with
  `[]` default.

**Backend and runtime wiring are still pending.** There is no
`ArtifactBackend` implementation, no artifact store config in Trenni, no
workspace materialization from artifact refs, and no artifact publication
in Palimpsest. Git-based publication remains the only active output
channel.

Reference: ADR-0013.

## 4. Task, Job, and Spawn Semantics

### Task (logical work unit)

Managed exclusively by Trenni. States:

```
pending -> running -> evaluating -> completed
                                 -> failed
                                 -> partial
                                 -> cancelled
                                 -> eval_failed
```

Every terminal task carries a two-layer result:

- **Structural verdict** (always present): derived from job terminal states.
  Deterministic, computed without LLM.
- **Semantic verdict** (optional): produced by eval job
  (pass / fail / unknown).

Reference: ADR-0002 sections 1, 2, 3.

### Job (execution unit)

One Palimpsest run inside one container. Terminal events:
agent.job.completed, agent.job.failed, agent.job.cancelled.

A job completing does not mean its task is complete. Palimpsest has no task
awareness.

### Spawn (sole orchestration primitive)

The agent calls spawn(tasks=[...]) during interaction. Trenni mechanically
expands this into child tasks, child jobs, and an optional join job. There
are no pre-defined DAGs or workflow definitions.

The planner role decides decomposition: which roles, what goals, what
budgets, what eval criteria. Trenni executes the mechanics.

Task IDs are hierarchical and deterministic:
```
018f4e3ab2c17d3e              # root (UUIDv7 prefix)
018f4e3ab2c17d3e/3afw         # child (base32 hash)
018f4e3ab2c17d3e/3afw/b2er    # grandchild
```

Reference: ADR-0001 section 4; ADR-0002 sections 5, 6; ADR-0007; ADR-0008.

## 5. Palimpsest Four-Stage Runtime

Every job executes through four stages. The ordering is a causal dependency
chain: each stage requires the prior stage's output. It is not configurable
because it cannot be otherwise.

| Stage | Input | Output | Evolvable via |
|-------|-------|--------|--------------|
| Preparation | Job config, repo/init_branch, role params | Private workspace, JobStartedData, RuntimeContext resources | preparation_fn in evo/ |
| Context | Workspace, job config, Pasloe events | AgentContext (prompt + tools) | context_fn in evo/ |
| Interaction | AgentContext | Tool calls, LLM responses, candidate summary | Role definition, tools in evo/ |
| Publication | Workspace, interaction result | Optional git_ref | publication_fn in evo/ |

**Preparation** clones a git repo or creates a repoless scratch workspace.
It may also establish job-scoped resources through `RuntimeContext`. The
workspace is a private copy; it is not the truth.

**Context** assembles the agent's prompt and available tools from job
config, workspace state, Pasloe queries, and evo/ providers.

**Interaction** runs the LLM loop with tool execution. Exits via idle
detection (two consecutive no-tool-call responses) or budget exhaustion.
Emits agent.llm.* and agent.tool.* events throughout.

**Publication** commits and pushes workspace output when the role uses
branch publication, and returns `git_ref` (`branch:sha`). Planner and
evaluator roles normally use `strategy="skip"`. Publication failure = job
failure, never silent.

Variation between task types lives in stage implementations (different
preparation_fn, different publication_fn), not in stage topology.

Reference: ADR-0003; ADR-0009; ADR-0002 sections 8, 9.

## 6. Current Git-Based Publication

```
publication_fn produces:
  -> git_ref             (branch publication)
  -> None                (intentional skip / repoless case)
```

Today, productive git-backed roles publish by committing the workspace and
pushing the active branch. `agent.job.completed` then carries `git_ref`,
summary, status, and code. Planner and evaluator roles usually skip
publication entirely, and repoless workspaces also return no `git_ref`.

There is no implemented artifact binding channel yet. ADR-0013 is the
planned migration path from git-only publication to a generalized physical
artifact layer.

Reference: ADR-0003 section 5; ADR-0013.

## 7. Evolvable and Non-Evolvable Boundaries

### Evolvable (lives in evo/, agents can modify)

| Artifact | What it controls |
|----------|-----------------|
| Role functions | JobSpec composition: which preparation, context, tools, publication |
| Preparation functions | Workspace setup: what to clone/materialize, what to install |
| Publication functions | Output delivery: what to store, where to push |
| Context providers | Prompt assembly: what information the agent sees |
| Tools | Agent capabilities: what actions the agent can take |
| Prompts | System/user prompt templates |

Two-layer structure (ADR-0011): global evo/ + evo/teams/<team>/ with
team-specific artifacts shadowing global by name.

### Non-evolvable (runtime skeleton, not modified by agents)

| Component | Why it is fixed |
|-----------|----------------|
| Trenni state machine | Trust boundary: deterministic control plane that works correctly even when evo/ has bugs |
| Palimpsest four-stage pipeline | Causal dependency chain: stages cannot be reordered |
| Pasloe event pipeline | Infrastructure: append-only log semantics |
| Condition evaluation | Mechanical: TaskIs, All, Any, Not |
| Spawn expansion | Mechanical: parent -> children + join |

The clean separation means: a bad evo/ change can break one job. It cannot
break the scheduler or the event store. The system
can detect the failure (via events) and continue operating.

Self-optimization (ADR-0010) modifies evo/ through normal tasks. It uses
budget prediction accuracy as its primary feedback signal. There is no
special optimization mode or privileged access.

Reference: ADR-0003 sections 3, 4; ADR-0010; ADR-0011 D2.

## 8. Companion Documents

### Normative

- **This document**: the normative system baseline.
- **In-flight ADRs** (`docs/adr/`): open design areas not yet fully absorbed
  into this baseline.

### Reference (non-normative, but maintained)

- [component-map.md](component-map.md): file paths, directory structure,
  event type table, configuration template, data flow diagram.
- [design-principles.md](design-principles.md): extracted invariants,
  conventions, and the publication guarantee matrix.
- [redesign-evaluation.md](redesign-evaluation.md): accepted vs rejected
  redesign directions and rationale.
- [test-operations.md](test-operations.md): deployment and long-running test
  procedures.

### Working List

- [TODO-open-items.md](TODO-open-items.md): unresolved implementation and
  cleanup items.

### Historical (retained for context, not authoritative)

- `docs/adr/archive/`: accepted or absorbed ADRs retained as decision
  history.
- `docs/archive/`: superseded drafts, plans, reviews, exploratory notes,
  and prior AI-generated consolidation attempts.
