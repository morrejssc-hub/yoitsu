# ADR-0005: CLI Task Observability

- Status: Accepted
- Date: 2026-03-27
- Related: ADR-0001, ADR-0002

## Context

The CLI already has two live-observability tools:

- `yoitsu watch` — continuous event stream with aggregate counters (job
  started/completed/failed totals). Not task-scoped.
- `yoitsu tui` — Textual dashboard showing active jobs and tasks tables.
  Requires services to be reachable.

Both tools answer "is anything happening?" but neither answers:

- What is the state of this specific task chain right now?
- Which jobs ran, in what roles, with what eval verdicts?
- What branches were produced?
- Has this task finished, and did it succeed?

During the first planner → spawn → implementer × N → eval smoke run, every
one of those questions required ad-hoc `curl | python3` against Pasloe's raw
event API. The gaps are:

1. No way to reconstruct a human-readable chain view for a specific task.
2. No blocking "wait for terminal state" primitive with a meaningful exit
   code.
3. `yoitsu events` is a snapshot dump; following new events requires repeated
   manual invocations. `yoitsu watch` follows events but is not task-scoped.
4. `yoitsu status` reports `alive=false` for services started outside of
   `yoitsu up` (e.g. quadlet), because aliveness is checked via a PID file
   written only by `yoitsu up`, not via HTTP.

## Decisions

### 1. `yoitsu tasks chain <task_id>` — Human-readable chain view

A new command that reconstructs the full task chain from Pasloe events and
overlays live state from Trenni where available.

**Data sources:**

Pasloe's `/events` API does not support `task_id` filtering. The chain is
reconstructed from two event queries:

1. `GET /events?source=trenni-supervisor&limit=1000` — fetches all supervisor
   lifecycle events (task created/terminal, job enqueued/launched). Filter
   client-side to the root task_id and its descendants (see §4).
2. `GET /control/tasks/{task_id}` from Trenni — provides live state for tasks still
   in-memory. Optional; degraded gracefully if Trenni is unreachable.

**Output format** (human-readable text, one line per task, indented by
depth):

```
069c633f53417da0          pending      planner    -
  069c633f53417da0/fv7o   completed ✓  implementer  palimpsest/job/…:f0e1f05d
  069c633f53417da0/g6gw   completed ✓  implementer  palimpsest/job/…:9809a3ea
```

Columns: task_id (shortened to 16 chars), terminal state + verdict icon,
role of the primary job, git_ref from eval result if available.

**Verdict icons:**

| Condition                                   | Icon |
|---------------------------------------------|------|
| `supervisor.task.completed` + verdict=pass  | ✓    |
| `supervisor.task.completed` + verdict≠pass  | ~    |
| `supervisor.task.completed` + no eval       | ✓    |
| `supervisor.task.partial`                   | ~    |
| `supervisor.task.failed`                    | ✗    |
| `supervisor.task.cancelled`                 | –    |
| Not yet terminal                            | …    |

**Reconstruction algorithm:**

1. Fetch supervisor events (see above) and filter to the subtree (§4).
2. For each task_id in the subtree, determine:
   - Primary job role from the first `supervisor.job.launched` event for
     that task.
   - Terminal state from the latest `supervisor.task.*` terminal event.
   - Eval verdict and git_ref from the `result` field in the terminal event
     (`supervisor.task.evaluating` or `supervisor.task.completed`), if
     present.
3. Print in depth-first order (root first, children sorted by task_id).

---

### 2. `yoitsu tasks wait <task_id>` — Block until terminal state

A new command that polls until the specified task reaches a terminal state,
then exits with a meaningful exit code.

**Options:**

| Flag              | Default | Meaning                                 |
|-------------------|---------|-----------------------------------------|
| `--timeout SECS`  | 600     | Abort with exit code 2 after N seconds  |
| `--interval SECS` | 5       | Poll interval                           |
| `--quiet`         | false   | Suppress progress output                |

**Exit codes:**

| Code | Condition                                          |
|------|----------------------------------------------------|
| 0    | `supervisor.task.completed`                        |
| 1    | `supervisor.task.failed`, `.partial`, `.cancelled` |
| 2    | Timeout elapsed before terminal state              |

**Progress output** (unless `--quiet`): on each poll, print one line showing
elapsed time and the current state of each task in the chain using the same
format as `tasks chain`. On terminal, print the final chain view and exit.

**Data source:** same as `tasks chain` — Pasloe supervisor events filtered
client-side (see §4). Trenni is consulted but not required.

---

### 3. `yoitsu events tail [--task <task_id>]` — Streaming event follow

A new command that continuously polls Pasloe for new events using cursor
pagination and prints each new event as it arrives. This extends `yoitsu
watch` with explicit task-scoping and structured per-event output.

**Options:**

| Flag              | Default | Meaning                                        |
|-------------------|---------|------------------------------------------------|
| `--task TASK_ID`  | —       | Show historical events for this task first,    |
|                   |         | then follow new events (see below)             |
| `--source SOURCE` | —       | Filter by source_id                            |
| `--type TYPE`     | —       | Filter by event type                           |
| `--interval SECS` | 2       | Poll interval                                  |

**Output format** (one line per event):

```
15:42:01 [trenni-supervisor] supervisor.job.launched  job=069c…-root  task=069c…  role=planner
15:42:03 [palimpsest-agent] agent.job.started         job=069c…-root  task=069c…
```

Runs until interrupted (Ctrl-C).

**Cursor management:** Pasloe returns the next cursor as the `X-Next-Cursor`
response header, carrying a composite `<ts>|<event_id>` value (as used in
the existing `yoitsu watch` implementation). On start without `--task`, begin
from the current tail (fetch with `order=desc&limit=1` to get the latest
cursor, then switch to `order=asc&cursor=<that>`). With `--task`, first fetch
all historical supervisor events for the subtree (client-side filter, §4),
print them, then follow from the current tail.

---

### 4. Descendant task ID enumeration (shared algorithm)

`tasks chain` and `tasks wait` both need the set of task IDs in a subtree.
Task IDs use `/` as a depth separator: `abc123` is parent, `abc123/fv7o` is
child, `abc123/fv7o/x9zz` is grandchild.

**Stopgap algorithm (current):**

1. Fetch `GET /events?source=trenni-supervisor&type=supervisor.task.created
   &limit=1000`.
2. From the results, collect all `task_id` values where `task_id ==
   root_task_id` or `task_id.startswith(root_task_id + "/")`.
3. Use this set as the subtree.

This is a full scan of all task-creation events on every call. It is
acceptable at current scale (tens of tasks) but will degrade as the event
log grows. It is explicitly a stopgap. A proper solution requires either:
- A `/events?task_prefix=<id>` filter added to Pasloe (API change), or
- A dedicated `/tasks/<id>/subtree` endpoint in Trenni.

That API change is deferred. The stopgap must be replaced before the full
scan becomes operator-visible in normal use.

---

### 5. `yoitsu status` alive detection fix

`yoitsu status` reports `alive=false` for services not started via
`yoitsu up` (e.g. quadlet/systemd). The root cause is that aliveness is
gated on `proc.is_alive(pid)` which reads from `.pids.json` — a file only
written by `yoitsu up`. When no PID file exists the PID is `None` and
`is_alive` unconditionally returns `False`.

**Fix:** when no PID is recorded for a service, fall back to an HTTP
reachability check:

- Pasloe: `GET /health` (unauthenticated, already used by the quadlet
  health-check script).
- Trenni: `GET /control/status` (Trenni does not expose `/health`; this is
  its liveness endpoint per `trenni/trenni/control_api.py`).

If the HTTP check succeeds, report `alive=true`. The PID check remains for
services started via `yoitsu up`; HTTP fallback is only used when the PID
file is absent or stale.

## Non-decisions

- **Push/SSE from Trenni or Pasloe**: Not in scope. All observability is
  pull-based (polling against Pasloe). A future ADR may add server-sent
  events.
- **Persisting wait state across restarts**: `tasks wait` holds no durable
  state. If the process is killed, the caller must re-run it.
- **JSON output mode for chain/wait**: `yoitsu tasks <task_id>` already
  provides the raw JSON. The new commands target human operators, not
  pipelines.
