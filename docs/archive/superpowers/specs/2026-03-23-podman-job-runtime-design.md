# Design Spec: Trenni Podman Job Runtime For Quadlet Deployment

**Date:** 2026-03-23
**Status:** Proposed

---

## 1. Background

The current Quadlet deployment is operational, but the job runtime boundary is
still wrong for the target architecture:

- Quadlet manages the long-lived `pasloe` and `trenni` services
- `trenni` launches `palimpsest` jobs as local subprocesses
- the `trenni` container must also install and host the `palimpsest` runtime
- job workspace preparation is host-path oriented (`work_dir`, `evo_repo_path`,
  config file write, cwd symlink)

That deployment was the right compatibility step, but it should not be the
steady state. The deployment target remains Quadlet, but the inner runtime must
move from `subprocess` to one Podman-managed container per job.

This spec replaces the "Quadlet outside, subprocess inside" model with:

- Quadlet for long-lived service management
- Podman REST API for short-lived job container management
- one container per job
- no host-mounted job workspace by default
- no `subprocess` compatibility backend in deployed Trenni

## 2. Decision Summary

### 2.1 Recommendation

Use Podman as both:

1. the long-lived deployment substrate through Quadlet, and
2. the per-job runtime substrate through the Podman REST API.

Do not model ephemeral jobs as additional Quadlet units. Quadlet is the correct
tool for stable service topology; the Podman API is the correct tool for
transient job lifecycle.

### 2.2 Hard Decisions

- `subprocess` is removed from deployed Trenni runtime selection
- `trenni` talks to a mounted rootless Podman API socket, not `podman run`
- each job becomes a sibling container in the same rootless Podman namespace
- each job joins the existing Quadlet pod `yoitsu-dev` for networking
- the job runtime image contains `palimpsest`, `evo`, `git`, and its entrypoint
- `trenni` no longer needs the `palimpsest` source tree mounted into its
  container
- host-path job workspace setup is removed from the runtime path

### 2.3 Non-Goals

- no pre-created worker pool
- no long-lived reusable job containers
- no Docker dependency
- no shell-string launch path
- no retain-on-failure by default
- no attempt to preserve backward compatibility for `pid`-based runtime events

## 3. Target Topology

```text
Pasloe Quadlet service  ----+
                            |
Trenni Quadlet service  ----+---- rootless Podman namespace
                            |
                            +---- job container (job A)
                            +---- job container (job B)
                            +---- job container (job C)
```

Networking model:

- Quadlet continues to create the long-lived pod `yoitsu-dev`
- `pasloe` and `trenni` remain long-lived containers in that pod
- each job container is created dynamically by `trenni`
- each job container joins pod `yoitsu-dev`
- jobs keep using the pod-local eventstore URL (`http://127.0.0.1:8000`)

Control model:

- `trenni` owns submission, launch, observation, cancellation, and cleanup
- Podman owns container lifecycle primitives
- `palimpsest` remains responsible for job logic and domain event emission

## 4. Runtime Model

### 4.1 Startup

On startup, `trenni` must:

1. load immutable runtime defaults from config once
2. create a Podman API client bound to the mounted Unix socket
3. fail fast if the socket is unreachable
4. fail fast if pod `yoitsu-dev` does not exist
5. fail fast if the runtime image is unavailable under the configured pull
   policy
6. replay unfinished jobs from Pasloe and reconcile them against Podman

If the Podman control plane is unavailable, `trenni` must refuse to start. This
deployment no longer has a subprocess fallback.

### 4.2 Launch

For each queued job, `trenni` performs:

1. build immutable `JobRuntimeSpec`
2. create a container through the Podman REST API
3. start the container
4. store a `JobHandle` keyed by `job_id`
5. emit `supervisor.job.launched` including the Podman container identity

Jobs are created as named containers, not auto-remove containers. Cleanup is
supervisor-driven so logs and exit status remain inspectable after abnormal
termination.

If create succeeds but start fails, `trenni` must remove the partially created
container and must not emit `supervisor.job.launched`.

### 4.3 Execution

The job container performs all mutable repository work internally:

- clone
- branch checkout
- file edits
- commit
- push

`trenni` does not create a host workspace for the job. The writable workspace
exists only inside the container filesystem.

### 4.4 Completion

Normal path:

1. `palimpsest` emits `job.started`
2. `palimpsest` emits `job.completed` or `job.failed`
3. `trenni` observes the terminal event
4. `trenni` removes the container unless retain-on-failure is enabled

Abnormal path:

1. Podman reports container exit without a terminal Pasloe event
2. `trenni` records the first observed exit timestamp
3. at checkpoint timeout, `trenni` fetches logs, emits compensating
   `job.failed`, and removes the container

### 4.5 Restart And Replay

`trenni` restart must not duplicate or lose in-flight work.

Replay uses Pasloe history plus Podman inspection:

1. read `task.submit`
2. read `supervisor.job.launched`
3. read `job.started`
4. read `job.completed` and `job.failed`
5. for unfinished launched jobs, inspect recorded `container_id`

Classification:

| State | Pasloe history | Podman inspect | Action |
|------|----------------|----------------|--------|
| complete | started + terminal | any | mark complete |
| queued only | submit with no launch | n/a | enqueue |
| launching | launch only | running or created | reattach `JobHandle` |
| launched, not started | launch only | missing or exited | enqueue new job id |
| running | launch + started, no terminal | running | reattach `JobHandle` |
| lost | launch + started, no terminal | exited or missing | schedule compensating failure |

The replay key is the original `source_event_id`. The runtime identity is the
recorded `container_id`, not an in-memory process handle.

## 5. Structured Runtime Types

The current `isolation.py` API mixes:

- job config assembly
- env allowlisting
- git credential injection
- host workspace creation
- backend launch

That coupling must be removed.

Introduce three explicit layers:

1. `Supervisor`
2. `RuntimeSpecBuilder`
3. `PodmanBackend`

### 5.1 `RuntimeDefaults`

Loaded once at startup from config:

```python
@dataclass(frozen=True)
class RuntimeDefaults:
    kind: Literal["podman"]
    socket_uri: str
    pod_name: str
    image: str
    pull_policy: Literal["always", "missing", "newer", "never"]
    stop_grace_seconds: int
    cleanup_timeout_seconds: int
    retain_on_failure: bool
    labels: Mapping[str, str]
    env_allowlist: tuple[str, ...]
    git_token_env: str
```

### 5.2 `JobRuntimeSpec`

Built per job and never mutated after creation:

```python
@dataclass(frozen=True)
class JobRuntimeSpec:
    job_id: str
    source_event_id: str
    container_name: str
    image: str
    pod_name: str
    labels: Mapping[str, str]
    env: Mapping[str, str]
    command: tuple[str, ...]
    config_payload_b64: str
```

### 5.3 `JobHandle`

Stored by the supervisor while a job is active:

```python
@dataclass
class JobHandle:
    job_id: str
    container_id: str
    container_name: str
    exit_code: int | None = None
    exited_at: float | None = None
```

`JobProcess.proc` disappears from the supervisor data model.

## 6. Podman Backend Contract

`PodmanBackend` owns container lifecycle operations:

- `create(spec) -> JobHandle`
- `start(handle) -> None`
- `inspect(handle) -> ContainerState`
- `wait(handle) -> ContainerExit`
- `logs(handle) -> RuntimeLogs`
- `stop(handle, timeout_s) -> None`
- `remove(handle, force=False) -> None`

Implementation notes:

- use `httpx.AsyncClient` over a Unix domain socket
- use the Libpod API, not CLI subprocesses
- store Podman `Id` as the durable runtime identity
- treat `404` on inspect/remove as a first-class state, not an exception leak

## 7. Container Payload Design

### 7.1 Runtime Image

Add a dedicated job runtime image that already contains:

- Python runtime
- `palimpsest`
- bundled `evo`
- `git`
- CA certificates
- a tiny entrypoint that decodes config and execs `palimpsest`

The job image must not depend on the `trenni` container's filesystem.

### 7.2 Config Injection

Do not write a host-side config file and bind mount it into the job container.

Instead:

1. `RuntimeSpecBuilder` renders the Palimpsest job config as YAML or JSON
2. encode it as base64
3. pass it as `PALIMPSEST_JOB_CONFIG_B64`
4. the image entrypoint writes it to a container-local temp path
5. exec `palimpsest run <temp-config-path>`

This keeps the runtime stateless from the host perspective.

### 7.3 Credential Injection

The backend allowlists only explicit env vars:

- Pasloe API key env
- LLM API key env
- git token env

Git auth remains environment-based, but the policy moves out of
`default_workspace` and into runtime defaults.

### 7.4 Labels

Every job container must include labels:

- `io.yoitsu.managed-by=trenni`
- `io.yoitsu.job-id=<job_id>`
- `io.yoitsu.source-event-id=<source_event_id>`
- `io.yoitsu.stack=yoitsu`
- `io.yoitsu.runtime=podman`
- `io.yoitsu.evo-sha=<evo_sha or empty>`

These labels support inspection, audit, and operational cleanup.

## 8. Config Shape

Replace the current deployment-oriented isolation fields:

- `palimpsest_command`
- `evo_repo_path`
- `work_dir`
- `isolation_backend`
- `isolation_unshare_net`

with an explicit runtime block:

```yaml
runtime:
  kind: "podman"
  podman:
    socket_uri: "unix:///run/podman/podman.sock"
    pod_name: "yoitsu-dev"
    image: "localhost/yoitsu-palimpsest-job:dev"
    pull_policy: "never"
    stop_grace_seconds: 10
    cleanup_timeout_seconds: 120
    retain_on_failure: false
    git_token_env: "GITHUB_TOKEN"
    env_allowlist:
      - "OPENAI_API_KEY"
    labels:
      io.yoitsu.managed-by: "trenni"
      io.yoitsu.stack: "yoitsu"
```

Other existing blocks remain:

- `default_eventstore_source`
- `default_llm`
- `default_workspace`
- `default_publication`

But `default_workspace` now contains only workspace semantics for Palimpsest.
It no longer carries host-runtime concerns like `git_token_env`.

## 9. Event Shape Changes

`supervisor.job.launched` must stop pretending the runtime is a local process.

Before:

```json
{
  "job_id": "uuid",
  "source_event_id": "evt-123",
  "pid": 12345
}
```

After:

```json
{
  "job_id": "uuid",
  "source_event_id": "evt-123",
  "runtime_kind": "podman",
  "container_id": "abc123...",
  "container_name": "yoitsu-job-uuid"
}
```

`pid` is removed. Any tooling that still expects a process id must migrate to
container identity.

## 10. Quadlet Deployment Changes

### 10.1 `yoitsu-trenni.container`

Change the service container so it:

- keeps the `trenni` source mount
- drops the `palimpsest` source mount
- mounts the rootless Podman socket at a stable in-container path
- depends on `podman.socket`
- exports `PODMAN_HOST=unix:///run/podman/podman.sock`

The service container remains long-lived under Quadlet. It does not become
privileged, but it does become the trusted control plane for the user's rootless
Podman namespace.

If the host uses SELinux, the socket mount must be configured in a way that
still allows the container to connect to the Podman API. Do not assume the
existing `:Z` bind-mount pattern is correct for the socket path.

### 10.2 `start-trenni.sh`

Simplify the bootstrap script:

- install or sync only `trenni`
- stop bootstrapping `palimpsest` venv into the supervisor container
- stop installing `git` only for the supervisor's sake

### 10.3 Job Image Build

Add a build path for `yoitsu-palimpsest-job`.

The first pass may build the image locally for development, but the deployed
runtime contract is an image reference, not a source tree bind mount.

## 11. Supervisor Changes

### 11.1 Replace `isolation.py`

Replace the current module with a runtime-focused structure:

- `runtime_types.py`
- `runtime_builder.py`
- `podman_backend.py`

The new backend API should not expose `asyncio.subprocess.Process`.

### 11.2 Launch Path

`Supervisor._launch()` becomes:

1. build `JobRuntimeSpec`
2. `handle = await backend.create(spec)`
3. `await backend.start(handle)`
4. `self.jobs[job_id] = handle`
5. emit `supervisor.job.launched`

### 11.3 Exit Detection

`_mark_exited_processes()` becomes runtime inspection:

- inspect each tracked container
- if state is exited and `exited_at` is empty, set `exited_at`
- cache `exit_code`

### 11.4 Cleanup

On `job.completed` or `job.failed`:

1. remove the in-memory handle
2. remove the container unless retention is enabled
3. keep event mapping history in Pasloe

### 11.5 Shutdown

On supervisor stop:

- stop tracked containers with configured grace period
- remove them when stop succeeds
- if stop fails and force is requested, force-remove

This keeps scheduler ownership consistent during controlled shutdown. Replay
reattachment is still required for unclean supervisor loss, container crashes,
or service restarts that bypass graceful shutdown.

## 12. Palimpsest Changes

`palimpsest` should not need architecture changes, but the runtime package must
gain a container entrypoint.

Minimum addition:

- a small wrapper script that decodes `PALIMPSEST_JOB_CONFIG_B64`
- writes config to a temp path
- execs `palimpsest run`

Optional but recommended:

- emit runtime metadata such as image revision or bundled `evo` sha in
  `job.started`

## 13. File Impact

| File | Change |
|------|--------|
| `trenni/trenni/config.py` | replace isolation fields with `runtime` config dataclasses |
| `trenni/trenni/supervisor.py` | track `JobHandle`, emit container identity, inspect runtime state, cleanup containers |
| `trenni/trenni/isolation.py` | remove or replace with runtime modules |
| `trenni/tests/test_isolation.py` | replace with runtime builder/backend tests |
| `trenni/tests/test_supervisor_queue.py` | update replay and launch expectations for container ids |
| `deploy/quadlet/yoitsu-trenni.container` | mount Podman socket, drop `palimpsest` source mount, add `podman.socket` dependency |
| `deploy/quadlet/bin/start-trenni.sh` | stop installing/syncing `palimpsest` into supervisor container |
| `deploy/quadlet/trenni.dev.yaml` | switch to runtime block |
| `deploy/quadlet/README.md` | describe sibling job containers instead of subprocess jobs |
| `palimpsest/...` | add container entrypoint packaging |

## 14. Test Plan

### 14.1 Unit

- runtime config parsing
- `RuntimeSpecBuilder` output
- env allowlist behavior
- Podman request construction
- replay classification using mocked inspect states
- compensating failure on runtime exit without terminal event

### 14.2 Integration

- create/start/inspect/remove against a live rootless Podman socket
- launch job container into pod `yoitsu-dev`
- verify job container reaches Pasloe at `127.0.0.1:8000`
- verify cleanup after terminal event

### 14.3 Quadlet End-To-End

- `systemctl --user start podman.socket yoitsu-pod.service yoitsu-pasloe.service yoitsu-trenni.service`
- submit a real task against a remote test repo
- verify branch push succeeds
- verify `supervisor.job.launched` records `container_id`
- verify no `palimpsest` subprocess exists inside `yoitsu-trenni`
- restart `yoitsu-trenni` while a job is running and verify replay reattaches or
  compensates correctly

## 15. Migration Plan

Implement in this order:

1. add runtime config dataclasses and Podman backend
2. switch supervisor state from process handles to container handles
3. change launched-event payload to container identity
4. add runtime image and entrypoint
5. update Quadlet deployment to mount Podman socket and drop `palimpsest` mount
6. remove `subprocess` code, config, tests, and docs

Do not add a long-term dual runtime matrix. The goal is replacement, not
permanent coexistence.

## 16. Acceptance Criteria

This design is complete when all of the following are true:

- Quadlet deployment starts without `subprocess` runtime support
- `trenni` launches each job through the Podman REST API
- each job runs in its own container in pod `yoitsu-dev`
- no host job workspace is required
- `supervisor.job.launched` contains container identity, not `pid`
- restart/replay handles in-flight containers correctly
- terminal jobs are cleaned up by policy
