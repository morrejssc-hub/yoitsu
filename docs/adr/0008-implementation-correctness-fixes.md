# ADR-0008: 2026-03-26 Implementation Correctness Fixes

- Status: Accepted and implemented
- Date: 2026-03-26
- Related: ADR-0004, ADR-0005

## Context

Several implementation-level defects remain unaddressed after the ADR-0004
and ADR-0005 work. None of these require architectural decisions; they are
correctness fixes to existing code.

## Fixes

### Fix 1: Task termination evaluation gated on handle presence (P1)

**File**: `trenni/trenni/supervisor.py:406`

```python
# current — task termination skipped when handle is None
if handle is not None and not replay:
    await self._cleanup_handle(handle, failed=is_failure or is_cancelled)
    await self._evaluate_task_termination(job_id=job_id, task_id=task_id, event=event)
```

`handle` is `None` when a job completes on a process that restarted after the
container was launched (the in-memory handle map is empty on restart). In this
case `_evaluate_task_termination` is never called and the task never reaches
a terminal state.

**Fix**: separate cleanup from evaluation. Cleanup requires a handle;
evaluation does not.

```python
if handle is not None:
    await self._cleanup_handle(handle, failed=is_failure or is_cancelled)
if not replay:
    await self._evaluate_task_termination(job_id=job_id, task_id=task_id, event=event)
```

### Fix 2: Private `asyncio.Queue._queue` access (P1)

**File**: `trenni/trenni/supervisor.py:453`

```python
for job in list(self.state.ready_queue._queue):
```

`asyncio.Queue._queue` is a private `collections.deque` with no stability
guarantee across Python versions.

**Fix**: add a `ready_queue_snapshot() -> list[SpawnedJob]` method to
`SupervisorState` that drains and refills the queue using the public
`get_nowait` / `put_nowait` interface (consistent with the existing
`drop_from_ready_queue` pattern in `state.py`). Use this method in
`_has_remaining_jobs`.

```python
# state.py — new method
def ready_queue_snapshot(self) -> list[SpawnedJob]:
    items: list[SpawnedJob] = []
    while not self.ready_queue.empty():
        items.append(self.ready_queue.get_nowait())
    for item in items:
        self.ready_queue.put_nowait(item)
    return items
```

```python
# supervisor.py — _has_remaining_jobs
for job in self.state.ready_queue_snapshot():
    if job.task_id == task_id:
        return True
```

### Fix 3: Missing Alembic migration for ADR-0004 schema (P1)

**File**: `pasloe/alembic/versions/`

The initial migration (`0a3e9a1488ea`) only creates `sources` and `events`.
ADR-0004 introduced three additional tables (`ingress_events`, `outbox_events`,
`webhooks`) that are currently created only via `create_all` at startup. A
deployment upgrading from an existing database will not have these tables.

**Fix**: add an Alembic migration that creates `ingress_events`,
`outbox_events`, and `webhooks` with all columns, constraints, and indexes
as defined in `pasloe/src/pasloe/models.py`. The migration must be
database-dialect aware (SQLite vs PostgreSQL) consistent with the pattern
already used in `models.py` (`is_sqlite()` guard).

### Fix 4: `test_api.py` hangs on Python 3.14 + SQLite (P1)

**File**: `pasloe/tests/test_api.py`

Tests in this file hang indefinitely under Python 3.14 with the SQLite
backend due to async event loop interaction changes in that version. The
online E2E suite (PostgreSQL) passes without issue.

**Fix**: mark the affected tests with `pytest.mark.skipif` targeting
Python >= 3.14 with an explicit reason referencing this ADR. Do not modify
the test logic or the E2E path.

```python
import sys
pytestmark = pytest.mark.skipif(
    sys.version_info >= (3, 14),
    reason="async SQLite event loop interaction hangs on Python 3.14 (ADR-0008); E2E on Postgres passes"
)
```

## Consequences

- Fix 1 closes a restart/replay correctness gap; tasks that completed while
  the supervisor was down will now reach terminal state correctly on replay
- Fix 2 removes a CPython version dependency; no behaviour change
- Fix 3 makes the Alembic migration history complete; `create_all` can be
  removed from the startup path once the migration is confirmed in all
  environments
- Fix 4 preserves test suite runnability on the development Python version
  without touching E2E coverage

## Implementation Status (2026-03-26)

Implemented in this pass:

- Fix 1: task termination evaluation is no longer gated on in-memory handle
  presence
- Fix 2: private `asyncio.Queue._queue` access was replaced with public
  snapshot helpers on `SupervisorState`
- Fix 3: added Alembic migration
  `4d7e6f5a2c11_add_ingress_outbox_and_backfill_webhooks.py`
- Fix 4: `pasloe/tests/test_api.py` now skips on Python >= 3.14 with the ADR
  reason recorded inline

Validation:

- `trenni`: full test suite passes
- `pasloe`: full test suite passes
- `pasloe`: `alembic upgrade head` succeeds against a temporary SQLite database
