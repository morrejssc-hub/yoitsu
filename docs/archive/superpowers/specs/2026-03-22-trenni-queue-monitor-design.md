# Design Spec: Trenni Task Queue + Monitor/Submit Fixes

**Date:** 2026-03-22
**Status:** Approved

---

## 1. Background

The 5-hour test on 2026-03-22 completed zero tasks. Root causes:

1. **monitor.py** — `data.get("events", [])` never matched (Pasloe returns a bare list, not `{"events": [...]}`)；no cursor tracking caused duplicate event counting
2. **Trenni supervisor** — no task queue; tasks beyond `max_workers` were silently dropped with `# TODO: queue for later`
3. **Restart gap** — `event_cursor` is in-memory only; on restart the supervisor has no way to distinguish already-launched tasks from new ones

---

## 2. Scope

Three components changed:

| Component | Change |
|-----------|--------|
| `trenni/trenni/supervisor.py` | Add in-memory task queue + startup replay with deduplication |
| `yoitsu/monitor.py` | Fix API parsing, cursor tracking, job-level state, noise filtering |
| `yoitsu/submit-tasks.py` | Add pre-flight health check, sequential submission |

---

## 3. Trenni — Task Queue

### 3.1 Queue Design

- `asyncio.Queue` instance on `Supervisor`, unbounded (no max size for now — add `maxsize` limit here when needed)
- `_handle_task_submit` enqueues a `TaskItem` dataclass instead of calling `_launch` directly
- A dedicated `_drain_queue` coroutine is started as `asyncio.create_task` in `start()`, before the poll loop. It is cancelled and awaited in the `finally` block of `start()` (same cleanup block that closes the client), so it exits cleanly on supervisor shutdown.

`_drain_queue` loop:
1. `item = await queue.get()` — yields until a task is available
2. `while not self._has_capacity(): await asyncio.sleep(1.0)` — yields to event loop while waiting for capacity
3. `await self._launch_from_item(item)` — launch; on exception, log and continue (task is not re-enqueued; it will be recovered on next restart via replay)

> Note on `self.jobs` lifetime: `_handle_job_done` calls `self.jobs.pop(job_id, None)` immediately when a terminal event (`job.completed` / `job.failed`) arrives. `_reap_processes` only logs process exits; it does not modify `self.jobs`. Therefore, `_has_capacity()` returns True after the terminal event is received, which is the correct trigger for draining the next queued task.

```python
@dataclass
class TaskItem:
    source_event_id: str   # originating task.submit event id
    job_id: str            # pre-assigned by supervisor at enqueue time
    task: str
    role: str
    repo: str
    branch: str
    evo_sha: str | None
```

`job_id` is pre-assigned at enqueue time (not at launch time), so the mapping is stable across the async gap between enqueue and actual launch.

### 3.2 supervisor.job.launched — New Field

Add `source_event_id` to the emitted `supervisor.job.launched` event payload:

```json
{
  "job_id": "trenni-...",
  "source_event_id": "<task.submit event id>",
  "task": "...",
  "role": "default",
  "evo_sha": "",
  "pid": 12345
}
```

This field is the join key used during replay. (`supervisor.job.launched` already exists in the current supervisor; this spec adds one field to its payload.)

### 3.3 Startup Replay

On `Supervisor.start()`, before starting `_drain_queue` and the poll loop, call `_replay_unfinished_tasks()`. Add `self._launched_event_ids: set[str] = set()` to `Supervisor.__init__`.

**Full historical scan:** All queries paginate Pasloe until `X-Next-Cursor` is absent. A helper `_fetch_all(type_, source=None)` handles pagination, collecting all pages into a list.

**Source filtering per query:**

| Query | `source` filter |
|-------|-----------------|
| `supervisor.job.launched` | `self.config.source_id` (only this supervisor's launches) |
| `job.started` | none (palimpsest-agent source, but safe to query globally since job_ids are unique) |
| `job.completed` | none |
| `job.failed` | none |
| `task.submit` | none (tasks can be submitted from any source) |

**Cursor after replay:** Track the globally latest event seen across all five query sets, comparing by `(ts, id)`. After replay, synthesize `self.event_cursor = f"{last.ts.isoformat()}|{last.id}"` using that event. If no events exist at all, leave `self.event_cursor = None`.

Steps:

1. `_fetch_all("supervisor.job.launched", source=self.config.source_id)` → mapping `source_event_id → job_id`
2. `_fetch_all("job.started")` → set of `job_id`
3. `_fetch_all("job.completed")` + `_fetch_all("job.failed")` → union into set of finished `job_id` (two separate calls)
4. `_fetch_all("task.submit")` → full task list
5. Find globally latest event by `(ts, id)` across all results
6. For each `task.submit` event, classify:

| State | Condition | Action |
|-------|-----------|--------|
| **Complete** | launched + `job.started` + job end | Add `source_event_id` to `_launched_event_ids`; skip |
| **Not launched** | no `supervisor.job.launched` for this event | Assign new `job_id`; enqueue |
| **Launched, not started** | launched + no `job.started` + no job end + `job_id` NOT in `self.jobs` | Assign new `job_id`; enqueue. Old `supervisor.job.launched` record stays in Pasloe (append-only store). On next restart, same `source_event_id` maps to old `job_id` which still has no `job.started` — same classification, correct. |
| **Launched, not started (process alive)** | launched + no `job.started` + no job end + `job_id` IS in `self.jobs` | Already running; add to `_launched_event_ids`; skip |
| **Orphan** | launched + `job.started` + no job end + `job_id` NOT in `self.jobs` | `pass` (TODO: emit compensating event). Known gap: orphaned processes are not tracked after restart and do not consume a `max_workers` slot until a job end event arrives. |

> Note: `self.jobs` on a fresh cold start is empty, so the "process alive" check never matches — this is correct.

7. Set `self.event_cursor` to synthesized cursor from step 5.

### 3.4 Normal Operation Deduplication

After replay, the poll loop cursor starts from the last replayed event, so new events are processed. `_handle_task_submit` also checks `_launched_event_ids` as a safety guard:

```python
if event.id in self._launched_event_ids:
    return  # already processed
self._launched_event_ids.add(event.id)
# ... enqueue
```

The event id is added to `_launched_event_ids` at enqueue time, before `_launch` is called. If `_launch` later fails, the id stays in `_launched_event_ids` (the task will be recovered on next restart via replay).

---

## 4. monitor.py — Fixes and Improvements

monitor.py uses raw `httpx` GET requests, not `PasloeClient` from the trenni package.

### 4.1 API Parsing Fix

```python
# Before (broken):
events = data.get("events", [])

# After:
events = resp.json()  # Pasloe /events returns list[Event] directly
```

### 4.2 Cursor-Based Tracking

- Store `self.event_cursor: str | None` between poll cycles
- On startup: load `event_cursor` from `STATE_FILE` if it exists; otherwise `None` (processes all history, which correctly populates initial counts)
- Pass `cursor` and `order=asc` as query params on each GET `/events`
- After each poll: if `X-Next-Cursor` header is present, use it; otherwise if events were returned, synthesize `f"{events[-1]['ts']}|{events[-1]['id']}"` to avoid re-reading the same batch
- Save cursor in `STATE_FILE` each cycle so monitor restarts resume from last position

### 4.3 Job-Level State Tracking

Track per-job state using a dict keyed by `job_id`:

```python
self.jobs: dict[str, str] = {}  # job_id -> "launched" | "started" | "completed" | "failed"
```

Event → state update:
- `supervisor.job.launched` → `jobs[job_id] = "launched"`
- `job.started` → `jobs[job_id] = "started"`
- `job.completed` → `jobs[job_id] = "completed"`
- `job.failed` → `jobs[job_id] = "failed"`

Stats exposed (mix of gauges and cumulative counters — clearly labelled in output):

| Stat | Definition | Type |
|------|-----------|------|
| `tasks_submitted` | count of `task.submit` events seen | cumulative counter |
| `jobs_total` | `len(jobs)` | cumulative counter (all jobs ever seen) |
| `jobs_in_progress` | count of jobs in `"launched"` or `"started"` state | gauge |
| `jobs_completed` | count of jobs in `"completed"` state | gauge (equals cumulative here since completed is terminal) |
| `jobs_failed` | count of jobs in `"failed"` state | gauge (equals cumulative here since failed is terminal) |

### 4.4 Noise Filtering

```python
IGNORED_EVENT_TYPES = {
    "agent.llm.request",
    "agent.llm.response",
    "agent.tool.exec",
    "agent.tool.result",
    "job.stage.transition",
}
```

Events with these types are still counted for `tasks_submitted` if applicable, but not printed to stdout.

### 4.5 Service Health Check

Each poll cycle checks:
- Pasloe: `GET /events/stats` (returns JSON dict with event count stats)
- Trenni: `GET http://localhost:8100/status`

Logs a warning if either is unreachable; does not abort the monitor loop.

### 4.6 Other Fixes

- Division-by-zero guard: success rate only printed when `completed + failed > 0`
- Report filename: `f"test-report-{datetime.now().strftime('%Y-%m-%d')}.md"`

---

## 5. submit-tasks.py — Small Fixes

- Pre-flight: check both Pasloe (`GET /events?limit=1`) and Trenni (`GET http://localhost:8100/status`) are reachable; print a clear warning if Trenni is down (submission still proceeds — tasks will be replayed on next Trenni startup — but the warning surfaces misconfiguration before a long test run)
- Sequential submission with `asyncio.sleep(0.1)` between tasks
- Print the event id returned by Pasloe for each submitted task

No batching or capacity-aware throttling — the Trenni queue handles backlog.

---

## 6. What Is NOT Changed

- No persistent queue (in-memory only; Pasloe event stream is the durable source of truth for recovery)
- No queue size limit (deferred; add `maxsize` to `asyncio.Queue` when needed)
- Orphan job compensating logic — `pass` placeholder only
- Trenni fork-join logic — unchanged
- Pasloe API — unchanged
- `_reap_processes` behavior — unchanged

---

## 7. Files Changed

| File | Change |
|------|--------|
| `trenni/trenni/supervisor.py` | `TaskItem` dataclass, `_launched_event_ids` in `__init__`, queue field, `_drain_queue` task (with shutdown cancel), `_replay_unfinished_tasks`, `_fetch_all` helper, `source_event_id` in launched event, dedup check in `_handle_task_submit` |
| `yoitsu/monitor.py` | API fix, cursor save/load from STATE_FILE, job state dict, mixed stats table, noise filter, health check, report filename fix |
| `yoitsu/submit-tasks.py` | Pre-flight health check (Pasloe + Trenni with warning), sequential with delay |
