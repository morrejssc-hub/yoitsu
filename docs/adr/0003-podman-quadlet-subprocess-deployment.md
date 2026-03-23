# ADR 0003: Podman Quadlet Dev Deployment Uses Subprocess, Not Bubblewrap

**Status:** Accepted  
**Date:** 2026-03-23  
**Deciders:** holo, Codex

## Context

The current development deployment target is a rootless Podman + Quadlet stack:

- one pod
- two long-lived containers
- `pasloe` isolated in its own container
- `trenni` plus short-lived `palimpsest` job subprocesses in the second container

The immediate goal is to validate application behavior under a production-like
service manager and container boundary, not to prove a second nested sandbox.

At the same time, the codebase still supports two Trenni isolation backends:

- `subprocess`
- `bubblewrap`

When we tested the Quadlet deployment, the inner `bubblewrap` path added extra
failure modes around:

- container-visible repo paths vs host-visible repo paths
- dependency/bootstrap complexity inside the job runner container
- nested sandbox policy clarity
- debugging cost during first-pass deployment validation

## Research Notes

Official Podman Quadlet documentation says rootless Quadlet units live under
`~/.config/containers/systemd/`, supports recursive search in subdirectories,
and generates transient systemd services from `.container`, `.pod`, and related
source files during `daemon-reload`.

Official bubblewrap documentation describes it as a low-level sandbox
construction tool, not a complete security policy by itself. The effective
boundary depends on the arguments supplied by the higher-level launcher.

That combination leads to a practical conclusion for this phase:

- Podman/Quadlet already gives us an outer container boundary, supervised by
  systemd.
- Bubblewrap remains useful technology, but it should be reintroduced only when
  we have a container-native path model and a deliberate inner security policy.

## Decision

For the Quadlet development deployment:

1. Use rootless Podman + Quadlet as the outer isolation boundary.
2. Keep `palimpsest` as short-lived subprocesses launched by `trenni`.
3. Configure `trenni.dev.yaml` with `isolation_backend: "subprocess"`.
4. Do not install or depend on `bubblewrap` in the Quadlet bootstrap path.
5. Treat re-enabling `bubblewrap` as a future explicit decision, not a default.

## Consequences

### Positive

- Faster path to validating service supervision, restart behavior, event flow,
  and real task execution.
- Lower debugging overhead in the containerized deployment.
- Clearer separation between deployment validation and sandbox-policy work.

### Negative

- Per-job inner sandboxing is absent in this deployment profile.
- Security characteristics differ from the long-term target architecture.

### Follow-up Conditions For Re-enabling Bubblewrap

Only revisit `bubblewrap` in the Quadlet deployment when all of the following
are addressed:

1. Job repo paths are expressed in container-native paths.
2. The intended inner security policy is written down, not implied.
3. The interaction between rootless Podman and `bubblewrap` is tested with
   representative tasks.
4. Operator diagnostics capture stderr/stdout from failed job launches cleanly.

## References

- Podman Quadlet docs: https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html
- Podman pod docs: https://docs.podman.io/en/latest/markdown/podman-pod-create.1.html
- Bubblewrap project README: https://github.com/containers/bubblewrap
