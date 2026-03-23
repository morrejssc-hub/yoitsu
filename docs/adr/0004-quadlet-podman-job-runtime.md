# ADR 0004: Quadlet Deployment Uses Podman Containers For Jobs

**Status:** Accepted  
**Date:** 2026-03-23  
**Supersedes:** ADR 0003

## Context

The earlier Quadlet deployment decision intentionally kept:

- Podman/Quadlet as the outer service boundary
- `subprocess` as the inner job runtime

That was the right compatibility checkpoint, but it is no longer the shipped
runtime model.

The current implementation now supports:

- rootless Podman socket mounted into the `trenni` service container
- one short-lived Podman container per `palimpsest` job
- `trenni` owning create/start/inspect/logs/stop/remove through the Podman API
- `supervisor.job.launched` carrying container identity rather than `pid`

## Decision

For the current Quadlet deployment:

1. Keep Quadlet for the long-lived `pasloe` and `trenni` services.
2. Use the Podman REST API for per-job runtime management.
3. Run each job in its own container in pod `yoitsu-dev`.
4. Remove `subprocess` as the deployed job runtime path.
5. Treat `palimpsest` as a job image, not as a source tree mounted into the
   `trenni` container.

## Consequences

### Positive

- Deployment and runtime isolation now use the same substrate.
- Job lifecycle is addressable through container identity.
- The `trenni` service container no longer needs to host the `palimpsest`
  runtime directly.

### Negative

- Deployment now depends on a reachable rootless Podman API socket.
- Operators must build or supply the job image before launch.

## References

- `docs/superpowers/specs/2026-03-23-podman-job-runtime-design.md`
- `deploy/podman/palimpsest-job.Containerfile`
