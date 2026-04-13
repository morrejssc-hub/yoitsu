# ADR-0003: Runtime Execution Architecture

- Status: Accepted (Consolidated 2026-04-02)
- Date: 2026-03-27
- Revised: 2026-04-02
- Consolidates: original ADR-0003, ADR-0009, ADR-0011
- Related: ADR-0001, ADR-0002, ADR-0004, ADR-0013

## Context

Palimpsest is the single-job executor. It receives a spawn payload, resolves
the role function from evo/, and runs a four-stage pipeline. The pipeline
must support:

- Code-change jobs that clone a git repository, perform work, and publish
  via commit and push.
- Non-git jobs (monitoring, reporting, Factorio) that need different
  workspace setup, tools, and publication strategies.
- A self-evolving system where agents can modify the logic governing job
  execution.

This ADR consolidates three previously separate decisions:

- The four-stage pipeline and role model (original ADR-0003)
- Preparation and publication function semantics (ADR-0009)
- Team as a runtime isolation boundary (ADR-0011)

## Decisions

### 1. Four Evolvable Stages

Every job executes through four stages, each controlled by a function
defined in evo/ and therefore independently evolvable:

| Stage | Function | Returns | Purpose |
|-------|----------|---------|---------|
| Preparation | preparation_fn | PreparedEnv | Establish execution environment |
| Context | context_fn | AgentContext | Build agent prompt and context |
| Interaction | (LLM loop) | result dict | Agent work: LLM calls + tool execution |
| Publication | publication_fn | artifact bindings + git_ref \| None | Deliver results |

The stage ordering is a causal dependency chain: each stage requires the
prior stage's output. Context cannot be built without a workspace.
Interaction cannot start without context. Publication cannot happen without
interaction output. This ordering is not configurable.

Variation between task types lives in stage implementations (different
preparation_fn, different publication_fn), not in stage topology.

All stages signal failure by raising exceptions. Palimpsest has one failure
handler: any exception -> agent.job.failed. No sentinel return values.

### 2. Role Is a First-Class Runtime Citizen

A role is a function in evo/ that returns a fully-resolved JobSpec. It
composes preparation, context, tools, publication, and budget into a
coherent agent definition for a specific task type.

```python
@role(
    name="implementer",
    description="Writes code to implement a specific task",
    role_type="worker",
    min_cost=0.10,
    recommended_cost=0.80,
    max_cost=2.00,
    min_capability="reasoning_medium",
)
def implementer_role(repo, branch, goal, budget) -> JobSpec:
    return JobSpec(
        preparation_fn = git_preparation(repo, branch),
        context_fn     = coder_context(goal),
        publication_fn = git_publication(),
        tools          = git_tools() | shell_tools(),
        provider       = default_code_provider(),
        budget         = budget,
    )
```

Role functions are the unit of system evolution.

**Metadata fields** (via @role decorator):

- `name`: unique role identifier within a team
- `description`: one-line capability summary exposed to the planner
- `role_type`: worker | planner | evaluator
- `min_cost`: spawn rejected below this value
- `recommended_cost`: planner's allocation reference
- `max_cost`: per-job ceiling
- `min_capability`: capability tier required from the provider

**Validation rules** (enforced at evo load time):

- Each team must have exactly one planner role
- Each team must have at most one evaluator role
- Each team must have at least one worker role
- Role names must be unique within a team

### 3. Spawn Payload vs. Runtime Execution

**Spawn payload** (declaration, stored in Pasloe event):

```json
{
  "role": "implementer",
  "params": { "repo": "...", "goal": "...", "budget": 0.80 },
  "sha": "abc123"
}
```

Compact and serializable. The `sha` anchors the role function to a
specific version of evo, making job behavior reproducible and evolution
auditable.

**JobSpec** (resolved execution input, constructed by Palimpsest):

Palimpsest receives the spawn payload, checks out evo at the specified sha,
calls role(**params), and receives a JobSpec. Trenni treats spawn payloads
as opaque blobs with zero dependency on evo.

### 4. Preparation: Any Deterministic Setup Before the Agent Loop

The preparation function (formerly workspace function) has expanded scope:
any deterministic setup required before the agent loop.

- Git repository checkout and branch setup
- Dependency installation
- Context fetching (Pasloe queries, PR diffs, CI status)
- Artifact materialization (copy-in from artifact store, ADR-0013)
- Environment variable injection, file staging
- Resource establishment (e.g. RCON bridge for Factorio)

Each role has exactly one preparation function. No declarative pipeline, no
step configuration, no composition DSL. If a new role needs different
preparation, it gets a new function. Internal reuse via shared utilities.

Parameters flow through PreparationConfig. The config structure is the only
contract between Trenni and preparation logic.

The agent sees none of this. It receives a ready environment and produces
outputs; the surrounding lifecycle is invisible to it.

**Failure handling:** Preparation failure = job failure. Trenni does not
retry preparation. Retry logic for transient failures is the preparation
function's responsibility.

### 5. Publication: Artifact-First Result Delivery

The publication function delivers job results. Its canonical output is
artifact bindings (ADR-0013). For jobs that also push to a git remote,
git_ref is an additional compatibility receipt.

```
publication_fn returns:
  -> artifact bindings   (canonical, always)
  -> git_ref             (compatibility, optional: "branch:sha" or None)
```

publication_fn must confirm the artifact is retrievable before returning.
Publication failure is never silent — it raises an exception, which
produces agent.job.failed.

Publication strategy is role-owned:

- strategy="branch": commit + push + store artifact
- strategy="skip": no publication (planner, eval roles)

**Publication guarantee** (state matrix from ADR-0002):

| Budget exhausted | Publication succeeded | Outcome |
|------------------|-----------------------|---------|
| no  | yes | job.completed -> task.completed (via eval) |
| yes | yes | job.completed(code=budget_exhausted) -> task.partial |
| no  | no  | job.failed |
| yes | no  | job.failed |

### 6. Provider Is Separate from Role

Role functions declare a capability requirement, not a specific model:

```python
min_capability = "reasoning_medium"
```

Provider selection happens at the job level. The runtime maps capability
requirements to available providers. This allows the same role to run on
different providers without modification.

### 7. Team Is a Runtime Isolation Boundary

A team is not a collection of roles. A team is the runtime environment and
evolutionary scope for a category of tasks.

**What a team isolates:**

- **Runtime environment**: container image, pod membership, network
  reachability, environment variables
- **Evolvable artifacts**: team-specific roles, tools, prompts, context
  providers
- **Launch conditions**: max_concurrent_jobs per team

**What a team does not do:**

- Team does not participate in scheduling. The scheduler sees jobs with
  conditions.
- Team does not own roles. Roles are generic logic; team provides the
  execution environment.

Teams are declared in Trenni's configuration, not inferred from role
metadata.

### 8. Two-Layer Evo Structure

```
evo/
  roles/              # global — available to all teams
  tools/
  prompts/
  contexts/
  teams/
    <team>/
      roles/          # team-specific — shadows global by name
      tools/
      prompts/
      contexts/
```

**Resolution:** team layer checked first; if no match, global layer used.
Team-specific artifacts completely replace global artifacts of the same
name for that team.

**Team membership:** determined by directory location. A role at
`evo/teams/factorio/roles/worker.py` is visible only to the factorio team.
The `@role(teams=...)` decorator field is deprecated and ignored.

**Write scope:** only optimization tasks modify evo/. Normal tasks work
against target repositories, not evo/.

### 9. RuntimeContext: Job-Scoped Lifecycle

Palimpsest creates a RuntimeContext at job start and carries it through
the entire pipeline:

```python
@dataclass
class RuntimeContext:
    workspace_path: str = ""
    job_id: str = ""
    task_id: str = ""
    team: str = ""
    artifact_backend: ArtifactBackend | None = None
    resources: dict[str, Any] = field(default_factory=dict)
    _cleanup_fns: list[Callable] = field(default_factory=list)
```

Lifecycle:
```
runner creates RuntimeContext
  -> preparation_fn(runtime_context=ctx)
  -> ctx.workspace_path set
  -> context_fn(...)
  -> interaction loop (tools receive ctx via injection)
  -> publication_fn(runtime_context=ctx)
  -> ctx.cleanup() (LIFO)
```

Tools request injection by declaring a `runtime_context: RuntimeContext`
parameter. The gateway injects it at call time; the parameter does not
appear in the tool schema.

### 10. Team Configuration in Trenni

```yaml
teams:
  default:
    runtime:
      image: "localhost/yoitsu-palimpsest-job:dev"
      pod_name: "yoitsu-dev"
      env_allowlist: ["GITHUB_TOKEN", "OPENAI_API_KEY"]
    scheduling:
      max_concurrent_jobs: 0    # 0 = no team-level limit

  factorio:
    runtime:
      image: "localhost/yoitsu-factorio-job:dev"
      pod_name: null
      extra_networks: ["factorio-net"]
      env_allowlist: ["RCON_HOST", "RCON_PORT", "RCON_PASSWORD"]
    scheduling:
      max_concurrent_jobs: 1
```

max_concurrent_jobs is a job launch condition (like any other condition
tree), not a scheduler policy. The scheduler has no team awareness.

PASLOE_API_KEY and eventstore connection parameters are injected for all
teams regardless of env_allowlist.

### 11. Container Runtime per Team

RuntimeSpecBuilder.build() uses the team's TeamRuntimeConfig:

- `image` from team config (fallback to global default)
- `pod_name` from team config (None = no pod)
- `env_allowlist` from team config (replaces global, not merged)
- `extra_networks` from team config

PodmanBackend handles pod_name=None (omit pod field) and extra_networks
(attach in create payload).

### 12. Eval Job Workspace Setup

**Leaf eval** (evaluating a task with a repo): checks out the git output
of the work it evaluates. Workspace config: repo=same,
init_branch=work_branch, new_branch=False.

**Root eval** (evaluating a repoless parent): input comes entirely from
event context (child eval verdicts, job execution traces). Workspace is a
scratch directory (repoless degradation).

### 13. Repoless Pipeline Degradation

When repo="", the pipeline degrades gracefully:

- Preparation: creates empty temp directory as scratch space
- Context and interaction: unchanged
- Publication: skipped; git_ref returns None; artifacts may still be
  produced

No second pipeline. Planner, root eval, and meta jobs use this path.

## Consequences

### Positive

- Role functions are independently testable, versioned, and evolvable.
- Preparation and publication semantics are broad enough for non-git tasks
  without architectural changes.
- Team isolation gives different task domains independent runtime profiles
  without complicating the scheduler.
- Two-layer evo gives evolution physical isolation per team.
- RuntimeContext provides clean resource lifecycle without leaking between
  stages.

### Tradeoffs

- Palimpsest must check out and execute evo at an arbitrary sha.
- Role functions must be deterministic given the same inputs at the same sha.
- PreparationConfig parameter growth signals role scope problems (tracked
  via self-optimization, ADR-0010).
- Team directory without Trenni config entry is a startup error.

### Non-Goals

- Dynamic tool sets that change mid-loop.
- Event-driven stage selection within a job (stages are causally fixed).
- Independent attempt types (validator, publisher) without agent loops.
- Evolvable decision policy in Trenni.
- Cross-team role sharing within a single task tree.
- Multi-provider routing within a single job.
