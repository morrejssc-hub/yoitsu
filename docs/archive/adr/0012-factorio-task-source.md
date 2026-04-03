# ADR-0012: Factorio as a Stateful Task Source

- Status: Proposed
- Date: 2026-04-01
- Related: ADR-0003, ADR-0007

## Context

ADR-0003 (D7-D11) established team as a first-class isolation boundary
with per-team runtime profiles, two-layer evo structure, and team-scoped
evolution. This ADR defines the first concrete team beyond `default`:
**Factorio**.

Factorio is a long-running headless game process reachable over RCON. It
is useful as a task source because it provides:

- A persistent world with clear state transitions
- A rich action surface that is mechanically verifiable
- A natural fit for planner / worker / evaluator decomposition

It is not a git-native workload. The live world, the script repository,
and the publication boundary must be defined explicitly.

## Decisions

### D1. Factorio is a Yoitsu team

Factorio is integrated as a team named `factorio` in Trenni's
configuration. Per ADR-0003 D7, this means it gets its own runtime
profile, its own evo scope, and its own launch conditions.

Trenni config:

```yaml
teams:
  factorio:
    runtime:
      image: "localhost/yoitsu-factorio-job:dev"
      pod_name: null
      extra_networks: ["factorio-net"]
      env_allowlist:
        - "RCON_HOST"
        - "RCON_PORT"
        - "RCON_PASSWORD"
        - "ANTHROPIC_API_KEY"
    scheduling:
      max_concurrent_jobs: 1
```

### D2. Factorio roles and tools live in `evo/teams/factorio/`

Per ADR-0003 D8, factorio-specific artifacts are physically isolated:

```
evo/teams/factorio/
  roles/
    planner.py          # factorio planner
    worker.py           # factorio worker
    evaluator.py        # factorio evaluator
  tools/
    factorio_tools.py   # call_script tool
  prompts/
    planner.md
    worker.md
    evaluator.md
```

These roles are visible only to the `factorio` team. They shadow any
global roles of the same name. Global tools (like `bash`, `spawn`) remain
available to the factorio team via the layered resolution in ADR-0003 D8.

Role definitions use `@role(...)` without `teams=` — team membership is
determined by directory location:

```python
# evo/teams/factorio/roles/worker.py
@role(
    name="worker",
    description="Executes Factorio automation tasks via Lua scripts",
    role_type="worker",
    min_cost=0.10,
    recommended_cost=0.50,
    max_cost=2.0,
)
def factorio_worker(**params) -> JobSpec:
    return JobSpec(
        preparation_fn=factorio_preparation(),
        context_fn=factorio_worker_context(),
        publication_fn=factorio_publication(),
        tools=["bash", "spawn", "call_script"],
    )
```

### D3. Workspace is the `factorio-agent` repository

The worker workspace is a git checkout of the `factorio-agent` repository.

That workspace is the source of truth for:

- Lua scripts under `mod/scripts/`
- runtime API documentation
- any code changes that should persist beyond a single job

The agent reads and writes scripts through normal file tools in the
workspace. Publication of persistent changes still uses git.

### D4. Live-world execution uses `call_script`

Factorio exposes a single source-specific tool: `call_script`.

`call_script` is a statically registered tool in
`evo/teams/factorio/tools/factorio_tools.py`. It accesses the RCON bridge
through `runtime_context` injection per ADR-0003 D9:

```python
@tool
def call_script(name: str, args: dict, runtime_context: RuntimeContext) -> ToolResult:
    bridge = runtime_context.resources.get("rcon_bridge")
    if not bridge:
        return ToolResult(success=False, output="RCON bridge not available")
    result = bridge.execute(name, args)
    return result
```

`call_script` bridges the workspace and the live world:

1. Resolves `name` against the job workspace's `mod/scripts/`
2. If the script is missing from the live server or the workspace version
   is newer, synchronizes that script into the live runtime
3. Executes the script with the provided arguments over RCON

Why a single tool rather than per-action tools:

- The evolvable surface is the Lua script set, not Python wrappers
- Script composition should stay in repo code
- `call_script` is the correct abstraction boundary for Factorio-specific
  behavior

### D5. RCON bridge is a RuntimeContext resource

The factorio worker's `preparation_fn` creates the RCON bridge and
registers it as a resource:

```python
def factorio_preparation():
    def prepare(*, runtime_context: RuntimeContext, **params):
        host = os.environ.get("RCON_HOST", "factorio-server")
        port = int(os.environ.get("RCON_PORT", "27015"))
        password = os.environ.get("RCON_PASSWORD", "")

        bridge = RconBridge(host, port, password)
        runtime_context.resources["rcon_bridge"] = bridge
        runtime_context.register_cleanup(bridge.close)

        return WorkspaceConfig(
            repo=params.get("repo", ""),
            init_branch=params.get("init_branch", "main"),
        )
    return prepare
```

The bridge tracks world mutation state internally:

- `bridge.world_mutated: bool` — updated after each `call_script`
  execution based on script type and result
- Publication and scheduler decisions depend on this flag

### D6. Server deployment is independent from the Yoitsu pod

The Factorio server runs as a Quadlet-managed Podman container with its
own network and persistent save volume:

```text
                ┌─── Pod: yoitsu-dev ───┐
                │ postgres  pasloe      │
                │ trenni                 │
                └───────────────────────┘

yoitsu-factorio-job ──RCON──▶ factorio-server
                              (factorio-net)
```

- `factorio-server` runs on `factorio-net`
- Factorio job containers join `factorio-net` via the team's
  `extra_networks` config (ADR-0003 D11)
- Factorio jobs do not join the `yoitsu-dev` pod (`pod_name: null`)
- Saves persist in `factorio-saves` volume

The server may mount a stable host checkout of the mod for baseline
assets, but that mount is **not** the synchronization path for per-job
workspace edits. Per-job script visibility comes from `call_script`
synchronization.

### D7. Publication is git + world checkpoint

Factorio publication has two outputs:

1. **Git publication** for any workspace changes (scripts, docs)
2. **Game save checkpoint** for live-world changes

The publication function uses `runtime_context` to access the bridge:

```python
def factorio_publication():
    def publish(*, runtime_context: RuntimeContext, result: dict, **params):
        # Git publication (standard)
        git_ref = git_publication()(result=result, **params)

        # World checkpoint (factorio-specific)
        bridge = runtime_context.resources.get("rcon_bridge")
        if bridge and bridge.world_mutated:
            save_result = bridge.save_world()
            if not save_result.success:
                raise PublicationError("World save failed after mutation")

        return git_ref
    return publish
```

Save policy:

- Planner and evaluator jobs do not mutate the world and skip the save
- Worker jobs that mutated the world must save successfully; failure to
  save prevents reporting the job as clean success
- Whether the world was mutated is tracked by the bridge, not assumed
  from the role type

### D8. Concurrency is a team launch condition

Per ADR-0003 D10, `max_concurrent_jobs: 1` in the factorio team config
translates to a launch condition on every factorio job:

```
running_count(team="factorio") < 1
```

This means:

- At most one factorio job runs at a time (across all roles)
- Additional factorio jobs wait in the queue until the running job
  completes
- Default team jobs are unaffected by factorio concurrency
- The scheduler does not know about "factorio" — it only evaluates the
  condition

Initial policy: the concurrency limit applies to **all factorio jobs**,
including planner and evaluator. This serializes the entire factorio
pipeline.

Rationale: the world is shared mutable state. Even "read-only" operations
during a worker mutation could observe inconsistent intermediate state.
Serializing all factorio jobs is the simplest correct approach.

Role-specific safety (e.g. restricting which scripts a planner may call)
is enforced within `call_script` — the tool can validate script permissions
based on role type or script classification. Scheduling does not
differentiate roles.

## Implementation Components

### evo/teams/factorio/

| Path | Content |
|---|---|
| `roles/planner.py` | Planner role: context-only, no world mutation |
| `roles/worker.py` | Worker role: preparation creates RCON bridge, tools include call_script |
| `roles/evaluator.py` | Evaluator role: inspects world state, no mutation |
| `tools/factorio_tools.py` | `call_script` tool with `runtime_context` injection |
| `prompts/planner.md` | Factorio planner system prompt |
| `prompts/worker.md` | Factorio worker system prompt |
| `prompts/evaluator.md` | Factorio evaluator system prompt |

### factorio-agent repository

| Path | Content |
|---|---|
| `factorio_bridge/` | RCON bridge client and on-demand script synchronization |

### deploy/

| Path | Content |
|---|---|
| `quadlet/factorio-server.container` | Factorio server Quadlet service |
| `quadlet/factorio-saves.volume` | Persistent save volume |
| `quadlet/factorio-net.network` | Dedicated network |
| `podman/factorio-job.Containerfile` | Team-specific job image (includes RCON client, Lua tooling) |

## Verification

1. Quadlet starts `factorio-server` and factorio job containers can reach
   it on `factorio-net`.
2. `call_script("ping", ...)` succeeds from a factorio job container.
3. A script edited in the job workspace can be executed in the same job
   through on-demand synchronization.
4. `RoleManager.resolve("worker")` for team `factorio` returns the
   factorio worker `JobSpec`, not the global worker.
5. Two factorio jobs cannot run concurrently — the second waits in queue.
6. A worker job that mutates world state but fails to save is surfaced as
   publication failure, not clean success.
7. Factorio evolution (modified tools/prompts) lands in
   `evo/teams/factorio/`, not in global `evo/`.

## Dependencies on ADR-0003 (Team Isolation)

ADR-0012 requires the following from ADR-0003:

| ADR-0003 Decision | Required for |
|---|---|
| D8: Two-layer evo | Factorio roles/tools/prompts live in `evo/teams/factorio/` |
| D10: Team config in Trenni | Factorio runtime profile and `max_concurrent_jobs` |
| D10: Per-team launch conditions | Concurrency enforcement |
| D9: RuntimeContext | RCON bridge lifecycle + tool injection |
| D8: Team-derived paths | Role/tool resolution finds factorio artifacts |
| D11: Container runtime per team | Factorio image, no pod, factorio-net |

Implementation sequence:

```
ADR-0003 Phase 1: RuntimeContext lifecycle + runtime_context injection
    ↓
ADR-0003 Phase 2: Two-layer evo resolution + team config in Trenni
    ↓
ADR-0003 Phase 3: Per-team runtime spec + launch conditions
    ↓
ADR-0012: Factorio roles + call_script + RCON bridge + Quadlet deployment
```

## Issues and Suggestions

### 1. Track world mutation explicitly

The bridge should record whether a job executed mutating operations.
Publication and save decisions should depend on `bridge.world_mutated`
rather than role name alone. The classification of which scripts are
mutating may be convention-based (e.g. scripts under `mod/scripts/actions/`
are mutating, scripts under `mod/scripts/queries/` are not) or
result-based (the script returns a mutation flag).

### 2. Keep baseline mod assets and job synchronization separate

Do not depend on a shared host mount to make job-edited scripts visible
to the live server. The architecture requires per-job synchronization
via `call_script`. The server's host mount provides baseline assets
only.

### 3. RCON connection failure is preparation failure

If the RCON bridge cannot be established during `preparation_fn`, the job
fails at preparation. Per ADR-0003 D4, preparation failure is job
failure — Trenni does not retry. Retry logic for transient RCON
connectivity issues (server restart, network flap) is the
preparation function's responsibility, implemented with standard retry
patterns inside the preparation function.

### 4. Factorio job image contents

The `factorio-job.Containerfile` must include:

- RCON client library (Python)
- Lua interpreter (for local script validation before sync)
- All Palimpsest runtime dependencies
- `factorio-agent` repository access (git clone at preparation time)

The image does not include the Factorio game server itself — that runs
as a separate Quadlet service.
