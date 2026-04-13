# ADR-0011: Team as First-Class Isolation Boundary

- Status: Accepted
- Date: 2026-04-01
- Implemented: 2026-04-01
- Supersedes: none
- Amends: ADR-0003 (evo_root handling), ADR-0007 (team field semantics),
  ADR-0009 (preparation function interface)
- Related: ADR-0003, ADR-0007, ADR-0009

## Context

Yoitsu supports a `team` field that flows from trigger through task and job,
but it is treated as a pass-through label. The runtime makes no decisions
based on it: every job uses the same image, the same pod, the same tool
search path, and the same scheduling constraints. The only team-aware logic
is `_resolve_team_definition`, which groups roles by their `@role(teams=[...])`
decorator — a purely logical grouping with no runtime isolation.

This model breaks when different task types require fundamentally different
execution environments. Factorio is the motivating example, but the gap is
generic: any non-git-native task source with its own runtime dependencies,
credentials, network topology, or concurrency constraints exposes the same
limitations.

The core problem is not workspace-centricity (which is a symptom). It is
that **team is not an isolation boundary**. Task-specific runtime
configuration, task-specific evolvable artifacts, and task-specific
scheduling constraints all lack a structural home.

This ADR promotes team from a metadata label to a first-class isolation
boundary in Trenni and Palimpsest.

## Decisions

### D1. Team is a task-domain isolation boundary

A team is not a collection of roles. A team is the **runtime environment
and evolutionary scope** for a category of tasks.

What a team isolates:

- **Runtime environment**: container image, pod membership, network
  reachability, environment variables
- **Evolvable artifacts**: tools, prompts, context loaders, and role
  specializations that have been optimized for this task domain
- **Launch conditions**: concurrency limits and other preconditions for
  dispatching jobs in this domain

What a team does **not** do:

- Team does not participate in scheduling. The scheduler sees jobs with
  launch conditions. It does not know which team a job belongs to.
- Team does not own roles in an organizational sense. Roles are generic
  logic; team provides the execution environment.

A team is declared in Trenni's configuration. It is not inferred from role
metadata. A role that exists in `evo/` without a corresponding team
declaration in Trenni config receives the `default` team's runtime profile.

### D2. Two-layer evo structure

The evolvable repository (`evo/`) uses a two-layer directory structure:

```
evo/
  roles/              # global roles — available to all teams
  tools/              # global tools
  prompts/            # global prompts
  contexts/           # global context loaders
  teams/
    <team>/
      roles/          # team-specific roles (shadow global by name)
      tools/          # team-specific tools (shadow global by name)
      prompts/        # team-specific prompts (shadow global by name)
      contexts/       # team-specific context loaders
```

**Visibility for a team**: a team sees its own `evo/teams/<team>/` layer
merged over the global `evo/` layer, with team-specific artifacts shadowing
global artifacts of the same name.

**Write scope**: only **optimization tasks** may modify evo artifacts.

- **Normal tasks**: workspace is the target repository (e.g. a GitHub repo).
The agent does not see evo as a workspace and cannot modify it.
- **Optimization tasks**: workspace is the evo directory itself. A team-scoped
optimization task writes to `evo/teams/<team>/`. A system-level optimization
task (e.g. improving global prompts) writes to global `evo/`.

This separation ensures evolution is deliberate and auditable, not accidental
side effects of regular work.

This gives evolution physical isolation: optimizations that accumulate within
a team's task domain stay in that team's directory. They cannot pollute other
teams or the global baseline.

**Shadowing semantics**: when resolving a role, tool, prompt, or context
loader by name, the resolver checks `evo/teams/<team>/` first. If a match
is found, it is used. Otherwise, the global `evo/` version is used. A
team-specific artifact completely replaces the global artifact of the same
name for that team; there is no merging of partial content.

### D3. `@role(teams=...)` is replaced by directory location

Role team membership was previously declared via `@role(teams=["..."])`.
That mechanism is removed.

Team membership is now determined by directory location:

- `evo/roles/<name>.py` → global role, available to all teams
- `evo/teams/<team>/roles/<name>.py` → available only to `<team>`

The `teams` field in `@role(...)` is deprecated and ignored by the metadata
reader. All other `@role` fields (`name`, `description`, `role_type`,
`min_cost`, `recommended_cost`, `max_cost`, `min_capability`) are retained.

`RoleMetadataReader` and `TeamManager` resolve a team's role catalog by
scanning both directories and merging with shadowing.

### D4. Team configuration in Trenni

Teams are declared in Trenni's configuration as a top-level concept:

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
      env_allowlist: ["RCON_HOST", "RCON_PORT", "RCON_PASSWORD", "ANTHROPIC_API_KEY"]
    scheduling:
      max_concurrent_jobs: 1

max_workers: 4    # global resource cap — across all teams
```

Data model:

```python
@dataclass
class TeamConfig:
    runtime: TeamRuntimeConfig
    scheduling: TeamSchedulingConfig

@dataclass
class TeamRuntimeConfig:
    image: str | None = None          # None = use global default
    pod_name: str | None = None       # None = no pod
    env_allowlist: list[str] = field(default_factory=list)
    extra_networks: list[str] = field(default_factory=list)

@dataclass
class TeamSchedulingConfig:
    max_concurrent_jobs: int = 0      # 0 = unlimited
```

**Startup validation**: Trenni validates at startup that every team
referenced by existing roles in `evo/teams/` has a corresponding entry in
the `teams:` configuration block. A team directory without config is a
startup error. A config entry without a team directory is allowed (the team
uses only global artifacts until it accumulates specializations).

### D5. Per-team launch conditions, not scheduling policy

`max_concurrent_jobs` is a **job launch condition**, not a scheduler policy.

When a job is enqueued for a team with `max_concurrent_jobs > 0`, the system
attaches a condition to the job:

```
running_count(team=T) < max_concurrent_jobs(T)
```

The scheduler evaluates this condition alongside existing `depends_on` and
structural conditions. The scheduler itself has no team awareness — it sees
jobs with conditions.

This preserves the current model where `max_workers` is the scheduler's
resource constraint and team concurrency is a domain constraint from the
task source.

**State tracking**: Trenni maintains `running_jobs_by_team: dict[str, int]`,
incremented at job launch and decremented at job terminal. This counter is
consulted by the condition evaluator, not by the scheduler directly.

### D6. RuntimeContext — job-scoped lifecycle context

Palimpsest provides a `RuntimeContext` object created by the runner before
`preparation_fn` and carried through preparation, tool execution,
publication, and finalization.

```python
@dataclass
class RuntimeContext:
    workspace_path: str = ""
    job_id: str = ""
    task_id: str = ""
    team: str = ""
    resources: dict[str, Any] = field(default_factory=dict)
    _cleanup_fns: list[Callable] = field(default_factory=list)

    def register_cleanup(self, fn: Callable[[], None]) -> None: ...
    def cleanup(self) -> None: ...
```

Lifecycle:

```
runner creates RuntimeContext (team from JobConfig.team)
  → preparation_fn(runtime_context=ctx)
  → setup_workspace(...)                   # ctx.workspace_path set
  → context_fn(...)
  → interaction loop                       # tools receive ctx via injection
  → publication_fn(runtime_context=ctx)
  → ctx.cleanup()                          # release resources (LIFO)
```

`RuntimeContext` stays Palimpsest-internal. It does not move into
`yoitsu-contracts`.

Tools request injection by declaring a `runtime_context: RuntimeContext`
parameter. It is added to the `injected_args` set alongside `workspace`,
`gateway`, `evo_root`, and `evo_sha`. The gateway injects it at call time.

### D7. Fixed evo path with team parameter

The `evo_root` parameter is removed from runtime components. The evolvable
directory is a fixed structural constant:

```python
EVO_DIR = Path.cwd() / "evo"
```

Resolution functions receive only the **team name** and derive paths:

```python
def resolve_role(team: str, role_name: str):
    team_path = EVO_DIR / "teams" / team / "roles" / f"{role_name}.py"
    global_path = EVO_DIR / "roles" / f"{role_name}.py"
    return load_from(team_path if team_path.exists() else global_path)
```

Team directory nonexistence is handled naturally: if `EVO_DIR / "teams" / team`
does not exist, resolution falls back to global artifacts. No special error
handling needed.

Components change:

| Component | Current | New |
|---|---|---|
| `RoleManager` | `__init__(evo_root)` | `__init__(team)` — derives paths from EVO_DIR |
| `UnifiedToolGateway` | `__init__(..., evo_root, ...)` | `__init__(..., team, ...)` — same |
| `build_context` | `evo_root=...` | `team=...` — same |
| `resolve_tool_functions` | `(evo_root, requested)` | `(team, requested)` — same |

`JobConfig.evo_sha` is retained for SHA pinning. `_materialize_evo_root`
materializes the entire evo/ tree at a pinned SHA and sets `EVO_DIR` to the
temp directory. Team resolution works identically against the materialized tree.

### D8. Container runtime per team

`RuntimeSpecBuilder.build()` uses the team's `TeamRuntimeConfig` to
assemble the `JobRuntimeSpec`:

- `image` from team config (fallback to global default)
- `pod_name` from team config (`None` = no pod)
- `env_allowlist` from team config (replaces global, not merged)
- `extra_networks` from team config

`JobRuntimeSpec` gains:

- `pod_name: str | None` (currently `str`, needs to accept `None`)
- `extra_networks: tuple[str, ...]`

`PodmanBackend` changes:

- `prepare()` omits the `pod` field from the create payload when
  `pod_name is None`
- `prepare()` attaches `extra_networks` in the create payload
- `ensure_ready()` skips pod existence check when `pod_name is None`
- `ensure_ready()` validates that all `extra_networks` exist before
  container creation

**Platform env**: `PASLOE_API_KEY` and `eventstore` connection parameters
are injected by `RuntimeSpecBuilder` for all teams. They are not subject
to `env_allowlist`. The allowlist controls only team-specific credentials.

### D9. Publication remains role-owned

No new publication abstraction is introduced here.

ADR-0009 established that each role owns exactly one `publication_fn`.
This ADR only extends what that function can see:

- `publication_fn` may receive `runtime_context`
- `publication_fn` may use resources created during preparation
- publication may target git, external systems, or both

The runtime remains agnostic about publication strategy.

## Implementation Components

### Trenni

| File | Change |
|---|---|
| `config.py` | Add `TeamConfig`, `TeamRuntimeConfig`, `TeamSchedulingConfig`; add `teams: dict[str, TeamConfig]` to `TrenniConfig`; move `PodmanRuntimeConfig` fields into team defaults |
| `runtime_types.py` | `JobRuntimeSpec.pod_name: str \| None`; add `extra_networks: tuple[str, ...]` |
| `runtime_builder.py` | Accept team name, look up `TeamConfig`, build spec from team runtime profile |
| `podman_backend.py` | Handle `pod_name=None` and `extra_networks` |
| `supervisor.py` | Maintain `running_jobs_by_team`; attach team launch condition to jobs; refactor `_resolve_team_definition` to use directory-based resolution |
| `scheduler.py` | No changes — team conditions are evaluated like any other condition |

### Palimpsest

| File | Change |
|---|---|
| `runtime/context.py` | Add `team` field to `RuntimeContext` |
| `runtime/tools.py` | Add `runtime_context` to `injected_args`; accept `team` in `UnifiedToolGateway` and `resolve_tool_functions`; scan both evo layers |
| `runtime/roles.py` | `RoleManager` and `TeamManager` resolve from both evo layers with shadowing; deprecate `teams` field in `@role` |
| `runner.py` | Create `RuntimeContext` at job start, pass through pipeline, call `cleanup()` in finally; derive team from `JobConfig.team` |
| `stages/context.py` | Accept `team` parameter, resolve prompts from both evo layers |

### yoitsu-contracts

| File | Change |
|---|---|
| `role_metadata.py` | `RoleMetadata.teams` deprecated; `RoleMetadataReader` learns layered scanning |

### evo/

| Path | Change |
|---|---|
| `evo/teams/` | Directory exists; populated per team as artifacts accumulate |

## Verification

1. A role at `evo/teams/factorio/roles/worker.py` is visible only to the
   `factorio` team. A role at `evo/roles/planner.py` is visible to all
   teams.
2. A team-specific role with the same name as a global role shadows the
   global role for that team only.
3. `team=factorio` jobs use the factorio image, pod_name=None, factorio-net
   network, and factorio-specific env vars.
4. `team=factorio` jobs with `max_concurrent_jobs=1` are blocked when
   another factorio job is running. Default team jobs are unaffected.
5. `RuntimeContext` is created, passed through preparation and publication,
   and cleaned up in LIFO order.
6. A tool declaring `runtime_context: RuntimeContext` receives it via
   injection; the parameter does not appear in the tool schema.
7. A factorio job's evo modifications land in `evo/teams/factorio/`, not
   in global `evo/`.
8. Existing Palimpsest and Trenni tests continue to pass.

## Scope Exclusions

The following are explicitly deferred to future ADRs:

- **Cross-team role sharing**: a role available to multiple specific teams
  (not all) requires a mechanism beyond directory location. Deferred.
- **Cross-team visibility**: a meta-team optimizer that queries data from
  multiple teams. The event system (Pasloe) is already global; no
  additional mechanism is needed now.
- **Per-role concurrency**: not needed. Team-level `max_concurrent_jobs`
  applies uniformly to all roles in the team. Role-specific safety
  constraints (e.g. restricting which scripts a planner may call) are
  enforced within tools, not via scheduling differentiation.
- **Team-scoped evo_sha pinning**: pinning specific teams to different evo
  versions. Currently evo_sha pins the entire tree.
- **Comparison teams**: A/B testing via parallel teams with shared baselines.

## Issues and Suggestions

### 1. Default team bootstrapping

Every Yoitsu deployment must have a `default` team. If `teams:` is absent
from config, Trenni should synthesize a `default` team using the current
`PodmanRuntimeConfig` fields as its runtime profile. This preserves backward
compatibility: existing configs without `teams:` behave identically to
before.

### 2. Team creation workflow

When a new team is added to Trenni config, the corresponding
`evo/teams/<team>/` directory may not exist. This is allowed — the team
operates with global artifacts only. Team-specific artifacts accumulate
through evolution. Trenni should not create the directory eagerly.

### 3. Global tool name conflicts across teams

If `evo/tools/review.py` defines a `review` tool and
`evo/teams/factorio/tools/review.py` also defines `review`, the shadowing
rule applies: factorio sees only its own version. But
`find_duplicate_tool_names` must understand layered resolution to avoid
false positives.

### 4. Prompt path resolution in context_spec

`context_spec("prompts/planner.md", ...)` currently resolves relative to
`evo_root`. With two-layer resolution, this becomes:
`evo/teams/<team>/prompts/planner.md` if it exists, else
`evo/prompts/planner.md`. Roles do not need to change their prompt path
references; the resolution layer handles it transparently.
