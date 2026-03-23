# Podman Job Runtime Intent

Date: 2026-03-23
Status: Intent only

## Context

Current `palimpsest` execution in `trenni` uses the `subprocess` backend as a temporary compatibility path. This is not the intended long-term isolation boundary.

An earlier version of the system executed `palimpsest` via Kubernetes Jobs in k3s. That model remains the preferred mental model:

- one isolated runtime per job
- clean environment by default
- no long-lived mutable worker state
- scheduler owns submission, observation, cancellation, and cleanup

## Direction

Adopt a new `podman` isolation backend for `trenni`, using the Podman REST API rather than shelling out to `podman run`.

The target runtime model is:

- one container per job
- container performs `clone / edit / commit / push` internally
- git is treated as a first-class runtime dependency
- host does not mount or persist the job workspace by default
- job completion normally removes the container
- debugging may later add an opt-in retain-on-failure policy

## Non-Goals For The First Pass

- no pre-created Quadlet slot pool
- no long-lived reusable worker containers
- no Incus-based runtime
- no dependency on Docker
- no shell-string based container launch path as the main implementation

## Architecture Notes

Keep the existing layered direction in `trenni`, but move toward structured runtime consumption:

1. Supervisor layer decides scheduling, dependency handling, cancellation, timeout, and state transitions.
2. Runtime spec building layer resolves config incrementally into a concrete immutable job runtime spec.
3. Backend layer consumes that spec and talks to the runtime.

Common backend/runtime defaults should be loaded once at startup from config, rather than recomputed ad hoc for each job.

Likely startup-loaded defaults include:

- Podman socket/base URL
- runtime image
- pull policy
- network mode
- user namespace policy
- default labels
- environment allowlist
- git credential injection policy
- cleanup policy
- timeout and stop-grace settings

Per-job data should only add job-specific fields such as:

- `job_id`
- `source_event_id`
- task payload
- repo / branch / evo SHA
- role
- LLM / workspace / publication overrides

## Expected Result Shape

The backend should eventually consume a structured job runtime spec, not raw command assembly logic.

The `podman` backend is expected to own:

- create
- start
- wait
- inspect
- fetch logs
- stop
- remove

`trenni` remains responsible for mapping runtime outcomes into domain events.

## Follow-Up

Detailed design, config shape, and implementation plan are captured in:

- `docs/superpowers/specs/2026-03-23-podman-job-runtime-design.md`
