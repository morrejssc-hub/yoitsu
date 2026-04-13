# 2026-03-25 Quadlet Test Run

- Date: 2026-03-25
- Scope: local rootless Podman + Quadlet deployment in `~/yoitsu`
- Goal: deploy the latest repo state into the local Quadlet stack, submit a
  focused task batch, observe execution behavior, and record runtime issues
- Final snapshot time: 2026-03-25 14:10:27 CST

## Final Status

At the final snapshot:

- `yoitsu-pod.service` was running
- `yoitsu-trenni.service` was running and healthy
- `yoitsu-pasloe.service` was running, but the container health state still
  reported `unhealthy`
- `Trenni /control/status` reported:
  - `running_jobs=0`
  - `ready_queue_size=0`
  - `pending_jobs=0`
  - 9 tasks tracked, all `completed`

Observed caveat:

- completion at the scheduler level did not always mean high-quality output
- several jobs finished with the summary `Stopped after 30 iterations`
- the run therefore counts as an operationally successful end-to-end test, but
  not as a clean signal that all task results were useful

## What Was Tested

### 1. Quadlet deployment refresh

The local Quadlet deployment was refreshed from the current repo using
`./scripts/deploy-quadlet.sh --skip-build`.

### 2. Task submission pipeline

A focused 8-task roadmap batch was prepared and submitted through Pasloe using
`trigger.external`.

A separate self-monitoring operations task was also submitted to test whether
Yoitsu could inspect its own runtime state from inside a normal job.

### 3. Runtime execution

The stack was observed across:

- `systemd --user status`
- `journalctl --user -u yoitsu-*.service`
- `podman ps --all`
- `Pasloe /events/stats`
- `Trenni /control/status`

## Timeline Summary

### Phase 1: Initial deployment and submission

Initial deployment and submission exposed two immediate issues:

- the long-lived service containers were not always refreshing to the newest
  checked-out source code
- task payloads used host-local repo paths such as `/home/holo/yoitsu/...`,
  which isolated Palimpsest job containers could not clone

### Phase 2: Source refresh fix

The Quadlet start wrappers were updated so they no longer relied only on
`git rev-parse` inside the runtime image to detect source changes.

Fallback content hashing was added so that, even without `git` in the running
  image, the container could still detect changed source trees and reinstall the
  latest checked-out code.

### Phase 3: Task submission hardening

A dedicated one-shot Quadlet submitter unit was introduced so task YAML could be
submitted from inside the Yoitsu pod, avoiding host/sandbox routing problems.

This submitter was also hardened to avoid duplicate source registration
collisions by using unique source ids per submitted event.

### Phase 4: Runtime reset and clean rerun

The runtime state was reset by:

- stopping Yoitsu services
- removing Yoitsu job containers
- removing the Yoitsu state and Pasloe data volumes
- redeploying from the current repo

This gave one clean rerun of the full task batch.

### Phase 5: HTTPS repo rerun with serialized workers

To address the clone failure path and reduce event-store write contention:

- task `repo` values were changed from host-local filesystem paths to GitHub
  HTTPS URLs
- `deploy/quadlet/trenni.dev.yaml` was temporarily changed from
  `max_workers: 4` to `max_workers: 1`

That rerun completed all queued tasks to terminal state.

## Issues Found

### 1. Service source refresh depended too heavily on git availability

Before the wrapper change, the service containers could continue running stale
code because source refresh logic assumed `git` was available inside the runtime
image.

Impact:

- deployment would appear to succeed
- the long-lived services could still execute older source snapshots

### 2. Local filesystem repos are not valid runtime clone targets

Early submitted tasks used repo values like:

- `/home/holo/yoitsu`
- `/home/holo/yoitsu/trenni`
- `/home/holo/yoitsu/palimpsest`
- `/home/holo/yoitsu/yoitsu-contracts`

Palimpsest job containers could not clone those paths, because those host paths
do not exist inside isolated job containers.

Observed failure shape:

- `git clone ... /home/holo/yoitsu/...`
- `fatal: repository '...' does not exist`

Impact:

- tasks failed immediately at workspace setup

### 3. Pasloe still shows real SQLite write-contention under load

Repeated `POST /events` calls produced:

- `500 Internal Server Error`
- `sqlite3.OperationalError: database is locked`

This was observed multiple times during the run, including after the clean reset.

Impact:

- runtime event emission could fail even when the job logic itself was fine
- task and job terminal events could be delayed or lost
- `yoitsu-pasloe` container health remained unstable

### 4. Pasloe container health remains unstable

Even after the health path hardening work and a clean rerun:

- the service process stayed up
- API requests continued to succeed
- but the Podman health state still eventually returned to `unhealthy`

Impact:

- operator status is noisy or misleading
- true runtime failures are harder to distinguish from healthcheck instability

### 5. Completion quality is uneven

Although all 9 tasks reached `completed` in the final rerun, several completions
reported only:

- `Stopped after 30 iterations`

Impact:

- queue drain success is not the same as useful output
- future test runs should distinguish scheduler completion from result quality

## Useful Outcomes

Despite the issues above, the run did produce a few meaningful outputs:

- hardening work around the Pasloe `/health` path
- hardening work around Quadlet-side health/startup wrappers
- a first cut of shared contracts for graph and structured child outputs
- an in-band self-monitoring job that produced a Yoitsu stack health report

## Architectural Discussion Captured

The discussion about decoupling execution workspace from publication sink was
captured separately in:

- [ADR-0003](../adr/0003-workspace-publication-sink-decoupling.md)

Status there is intentionally:

- `Proposed, not implemented`

## Recommendations

### Immediate

- fix Pasloe SQLite write contention before trusting longer autonomous runs
- treat `yoitsu-pasloe` health instability as an open operational bug
- keep runtime concurrency at `1` until Pasloe write stability is improved

### Near-term

- distinguish “queue drained” from “useful result produced” in monitoring
- add explicit operational/reporting task roles instead of overloading the
  generic code-editing role
- define a first-class publication strategy for hidden artifact sinks instead of
  forcing operational jobs into code-repo publication semantics

### Nice-to-have

- capture a stable per-run report artifact automatically
- expose better status summaries than raw terminal job summaries

## Suggested Monitoring Commands

Current commands that were most useful during this run:

```bash
curl -sS http://127.0.0.1:8100/control/status

PASLOE_API_KEY=$(sed -n 's/^PASLOE_API_KEY=//p' ~/.config/containers/systemd/yoitsu/trenni.env | tail -n 1)
curl -sS -H "X-API-Key: $PASLOE_API_KEY" http://127.0.0.1:8000/events/stats
curl -sS -H "X-API-Key: $PASLOE_API_KEY" "http://127.0.0.1:8000/events?type=job.completed&limit=20&order=desc" | jq -r '.[].data.summary'

journalctl --user -u yoitsu-trenni.service -f
journalctl --user -u yoitsu-pasloe.service -f

podman ps --all --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}' | rg yoitsu
```
