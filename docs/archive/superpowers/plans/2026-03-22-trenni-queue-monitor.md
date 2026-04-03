# Trenni Task Queue + Monitor/Submit Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an in-memory task queue with Pasloe-backed restart replay to Trenni, and fix the broken monitor/submit scripts so the 5-hour test can actually run.

**Architecture:** Trenni gets an `asyncio.Queue` drained by a background coroutine; on startup it replays Pasloe event history to recover unfinished tasks. monitor.py is rewritten to use cursor-based polling and job-level state tracking. submit-tasks.py gets pre-flight health checks.

**Tech Stack:** Python 3.11, asyncio, httpx, uuid-utils (UUID v7), pytest, pytest-asyncio. All deps managed with `uv`.

**Spec:** `docs/superpowers/specs/2026-03-22-trenni-queue-monitor-design.md`

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `trenni/trenni/supervisor.py` | Modify | Add `TaskItem`, queue, `_drain_queue`, `_fetch_all`, `_replay_unfinished_tasks`, dedup, UUID v7 |
| `trenni/pyproject.toml` | Already updated | `uuid-utils`, `pytest`, `pytest-asyncio` added via uv |
| `trenni/tests/__init__.py` | Create | Empty, makes tests a package |
| `trenni/tests/test_supervisor_queue.py` | Create | Tests for queue, dedup, replay classification |
| `yoitsu/monitor.py` | Modify | API fix, cursor, job state, noise filter, health check |
| `yoitsu/submit-tasks.py` | Modify | Pre-flight checks, print event ids |

All `uv` commands below must be run from the `trenni/` directory:
```bash
cd /home/holo/yoitsu/trenni
```

---

## Task 1: UUID v7 job ID

**Files:** Modify `trenni/trenni/supervisor.py`

Replace the UUID v4 `_generate_job_id` method with UUID v7 (time-ordered, sortable).

- [ ] **Step 1: Write failing test**

Create `trenni/tests/__init__.py` (empty) and `trenni/tests/test_supervisor_queue.py`:

```python
"""Tests for Trenni supervisor queue and replay logic."""
import re
import pytest


def test_generate_job_id_is_uuid_v7():
    from trenni.supervisor import Supervisor
    from trenni.config import TrenniConfig
    sup = Supervisor(TrenniConfig())
    job_id = sup._generate_job_id()
    # UUID v7: xxxxxxxx-xxxx-7xxx-xxxx-xxxxxxxxxxxx
    assert re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        job_id,
    ), f"Not a UUID v7: {job_id}"
```

- [ ] **Step 2: Run test — verify it fails**

```bash
cd /home/holo/yoitsu/trenni && uv run pytest tests/test_supervisor_queue.py::test_generate_job_id_is_uuid_v7 -v
```
Expected: FAIL (current `_generate_job_id` returns `trenni-YYYYMMDD-...` format)

- [ ] **Step 3: Update `_generate_job_id` in supervisor.py**

Replace the entire `_generate_job_id` method (lines ~326-330):

```python
def _generate_job_id(self) -> str:
    import uuid_utils
    return str(uuid_utils.uuid7())
```

- [ ] **Step 4: Run test — verify it passes**

```bash
uv run pytest tests/test_supervisor_queue.py::test_generate_job_id_is_uuid_v7 -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /home/holo/yoitsu
git add trenni/trenni/supervisor.py trenni/tests/__init__.py trenni/tests/test_supervisor_queue.py trenni/pyproject.toml trenni/uv.lock
git commit -m "feat(trenni): use UUID v7 for job IDs, add test infra"
```

---

## Task 2: TaskItem dataclass + Supervisor fields

**Files:** Modify `trenni/trenni/supervisor.py`

Add `TaskItem` and the new Supervisor state fields: `_task_queue` and `_launched_event_ids`.

- [ ] **Step 1: Write failing test**

Add to `trenni/tests/test_supervisor_queue.py`:

```python
def test_task_item_fields():
    from trenni.supervisor import TaskItem
    item = TaskItem(
        source_event_id="evt-1",
        job_id="job-1",
        task="do something",
        role="default",
        repo="/repo",
        branch="main",
        evo_sha=None,
    )
    assert item.source_event_id == "evt-1"
    assert item.evo_sha is None


def test_supervisor_has_queue_and_dedup_set():
    import asyncio
    from trenni.supervisor import Supervisor
    from trenni.config import TrenniConfig
    sup = Supervisor(TrenniConfig())
    assert isinstance(sup._task_queue, asyncio.Queue)
    assert isinstance(sup._launched_event_ids, set)
```

- [ ] **Step 2: Run test — verify it fails**

```bash
uv run pytest tests/test_supervisor_queue.py::test_task_item_fields tests/test_supervisor_queue.py::test_supervisor_has_queue_and_dedup_set -v
```
Expected: FAIL (`TaskItem` not defined, `_task_queue` not found)

- [ ] **Step 3: Add `TaskItem` and fields to supervisor.py**

At the top of `supervisor.py`, after the existing imports, add:

```python
import asyncio
from dataclasses import dataclass, field
```

(Check if `asyncio` and `dataclass` are already imported; they probably are — only add what's missing.)

After the `ForkJoin` dataclass, add:

```python
@dataclass
class TaskItem:
    """A queued task waiting to be launched."""
    source_event_id: str   # originating task.submit event id
    job_id: str            # pre-assigned at enqueue time
    task: str
    role: str
    repo: str
    branch: str
    evo_sha: str | None
```

In `Supervisor.__init__`, after `self.fork_joins: dict[str, ForkJoin] = {}`, add:

```python
# Task queue — unbounded (add maxsize= here when backpressure is needed)
self._task_queue: asyncio.Queue[TaskItem] = asyncio.Queue()
# Event IDs of task.submit events already enqueued or skipped (dedup guard)
self._launched_event_ids: set[str] = set()
```

- [ ] **Step 4: Run test — verify it passes**

```bash
uv run pytest tests/test_supervisor_queue.py::test_task_item_fields tests/test_supervisor_queue.py::test_supervisor_has_queue_and_dedup_set -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /home/holo/yoitsu
git add trenni/trenni/supervisor.py trenni/tests/test_supervisor_queue.py
git commit -m "feat(trenni): add TaskItem dataclass and queue/dedup fields to Supervisor"
```

---

## Task 3: `_handle_task_submit` — enqueue instead of launch

**Files:** Modify `trenni/trenni/supervisor.py`

Replace the direct `_launch` call with enqueue + dedup check.

- [ ] **Step 1: Write failing test**

Add to `trenni/tests/test_supervisor_queue.py`:

```python
import asyncio
import pytest


@pytest.mark.asyncio
async def test_handle_task_submit_enqueues():
    from unittest.mock import AsyncMock, patch
    from trenni.supervisor import Supervisor
    from trenni.config import TrenniConfig
    from trenni.pasloe_client import Event
    from datetime import datetime

    sup = Supervisor(TrenniConfig())
    event = Event(
        id="evt-abc",
        source_id="test",
        type="task.submit",
        ts=datetime.utcnow(),
        data={"task": "do X", "role": "default", "repo": "/r", "branch": "main"},
    )
    with patch.object(sup, "_launch", new_callable=AsyncMock) as mock_launch:
        await sup._handle_task_submit(event)
        mock_launch.assert_not_called()   # should not launch directly

    assert sup._task_queue.qsize() == 1
    item = sup._task_queue.get_nowait()
    assert item.source_event_id == "evt-abc"
    assert item.task == "do X"


@pytest.mark.asyncio
async def test_handle_task_submit_deduplicates():
    from unittest.mock import AsyncMock, patch
    from trenni.supervisor import Supervisor
    from trenni.config import TrenniConfig
    from trenni.pasloe_client import Event
    from datetime import datetime

    sup = Supervisor(TrenniConfig())
    sup._launched_event_ids.add("evt-dup")
    event = Event(
        id="evt-dup",
        source_id="test",
        type="task.submit",
        ts=datetime.utcnow(),
        data={"task": "do X", "role": "default", "repo": "/r", "branch": "main"},
    )
    await sup._handle_task_submit(event)
    assert sup._task_queue.qsize() == 0   # deduped, not enqueued
```

- [ ] **Step 2: Add `pytest-asyncio` config to `trenni/pyproject.toml`**

Add at the end of `pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 3: Run test — verify it fails**

```bash
uv run pytest tests/test_supervisor_queue.py::test_handle_task_submit_enqueues tests/test_supervisor_queue.py::test_handle_task_submit_deduplicates -v
```
Expected: FAIL

- [ ] **Step 4: Rewrite `_handle_task_submit` in supervisor.py**

Replace the entire `_handle_task_submit` method:

```python
async def _handle_task_submit(self, event: Event) -> None:
    # Dedup: skip events already enqueued or completed
    if event.id in self._launched_event_ids:
        logger.debug("Skipping already-processed task.submit %s", event.id)
        return

    data = event.data
    task = data.get("task", "")
    role = data.get("role", "default")
    repo = data.get("repo", "")
    branch = data.get("branch", "main")
    evo_sha = data.get("evo_sha")

    if not task:
        logger.warning("Ignoring task.submit with empty task (event=%s)", event.id)
        return

    job_id = self._generate_job_id()
    self._launched_event_ids.add(event.id)

    item = TaskItem(
        source_event_id=event.id,
        job_id=job_id,
        task=task,
        role=role,
        repo=repo,
        branch=branch,
        evo_sha=evo_sha,
    )
    await self._task_queue.put(item)
    logger.info("Queued task %s (job_id=%s, queue_size=%d)",
                event.id, job_id, self._task_queue.qsize())
```

- [ ] **Step 5: Run test — verify it passes**

```bash
uv run pytest tests/test_supervisor_queue.py::test_handle_task_submit_enqueues tests/test_supervisor_queue.py::test_handle_task_submit_deduplicates -v
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd /home/holo/yoitsu
git add trenni/trenni/supervisor.py trenni/pyproject.toml trenni/uv.lock
git commit -m "feat(trenni): _handle_task_submit enqueues instead of launching directly"
```

---

## Task 4: `_drain_queue` coroutine

**Files:** Modify `trenni/trenni/supervisor.py`

Background coroutine that dequeues `TaskItem`s and launches them when capacity is available.

- [ ] **Step 1: Write failing test**

Add to `trenni/tests/test_supervisor_queue.py`:

```python
@pytest.mark.asyncio
async def test_drain_queue_launches_when_capacity():
    from unittest.mock import AsyncMock, patch
    from trenni.supervisor import Supervisor, TaskItem
    from trenni.config import TrenniConfig

    sup = Supervisor(TrenniConfig(max_workers=2))
    item = TaskItem("evt-1", "job-1", "task", "default", "/repo", "main", None)
    await sup._task_queue.put(item)

    launched = []

    async def fake_launch_from_item(i):
        launched.append(i.job_id)

    sup._launch_from_item = fake_launch_from_item

    # Run _drain_queue briefly then cancel
    task = asyncio.create_task(sup._drain_queue())
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert launched == ["job-1"]


@pytest.mark.asyncio
async def test_drain_queue_waits_when_at_capacity():
    from unittest.mock import AsyncMock
    from trenni.supervisor import Supervisor, TaskItem
    from trenni.config import TrenniConfig
    from trenni.isolation import JobProcess

    sup = Supervisor(TrenniConfig(max_workers=1))

    # Fake a running job to fill capacity
    fake_proc = AsyncMock()
    fake_proc.returncode = None
    from pathlib import Path
    sup.jobs["existing-job"] = JobProcess(
        job_id="existing-job", proc=fake_proc,
        work_dir=Path("/tmp"), config_path=Path("/tmp/cfg.yaml")
    )

    item = TaskItem("evt-2", "job-2", "task", "default", "/repo", "main", None)
    await sup._task_queue.put(item)

    launched = []
    async def fake_launch_from_item(i):
        launched.append(i.job_id)
    sup._launch_from_item = fake_launch_from_item

    task = asyncio.create_task(sup._drain_queue())
    await asyncio.sleep(0.15)  # give drain loop time to run
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert launched == []   # still waiting for capacity
```

- [ ] **Step 2: Run test — verify it fails**

```bash
uv run pytest tests/test_supervisor_queue.py::test_drain_queue_launches_when_capacity tests/test_supervisor_queue.py::test_drain_queue_waits_when_at_capacity -v
```
Expected: FAIL (`_drain_queue` not defined)

- [ ] **Step 3: Add `_drain_queue` and `_launch_from_item` to supervisor.py**

Add after `_run_loop`:

```python
async def _drain_queue(self) -> None:
    """Background coroutine: dequeue TaskItems and launch when capacity allows."""
    while True:
        item = await self._task_queue.get()
        while not self._has_capacity():
            await asyncio.sleep(1.0)
        try:
            await self._launch_from_item(item)
        except Exception:
            logger.exception("Failed to launch queued job %s, dropping (recoverable on restart)", item.job_id)

async def _launch_from_item(self, item: TaskItem) -> None:
    """Launch a TaskItem as a palimpsest job."""
    await self._launch(
        job_id=item.job_id,
        task=item.task,
        role=item.role,
        repo=item.repo,
        branch=item.branch,
        evo_sha=item.evo_sha,
    )
```

- [ ] **Step 4: Run test — verify it passes**

```bash
uv run pytest tests/test_supervisor_queue.py::test_drain_queue_launches_when_capacity tests/test_supervisor_queue.py::test_drain_queue_waits_when_at_capacity -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /home/holo/yoitsu
git add trenni/trenni/supervisor.py trenni/tests/test_supervisor_queue.py
git commit -m "feat(trenni): add _drain_queue background coroutine"
```

---

## Task 5: `source_event_id` in `supervisor.job.launched`

**Files:** Modify `trenni/trenni/supervisor.py`

Update `_launch` to accept `source_event_id` and include it in the emitted event. Update `_launch_from_item` to pass it through.

- [ ] **Step 1: Write failing test**

Add to `trenni/tests/test_supervisor_queue.py`:

```python
@pytest.mark.asyncio
async def test_launch_emits_source_event_id():
    from unittest.mock import AsyncMock, patch, MagicMock
    from trenni.supervisor import Supervisor, TaskItem
    from trenni.config import TrenniConfig
    from pathlib import Path

    sup = Supervisor(TrenniConfig())

    emitted = []
    async def fake_emit(type_, data):
        emitted.append((type_, data))
        return "evt-out"
    sup.client.emit = fake_emit

    # Mock the isolation backend to avoid real subprocess
    fake_proc = AsyncMock()
    fake_proc.returncode = None
    fake_proc.pid = 9999
    fake_jp_mock = MagicMock()
    fake_jp_mock.proc = fake_proc
    with patch("trenni.supervisor.launch_job", new_callable=AsyncMock, return_value=fake_jp_mock):
        await sup._launch(
            job_id="job-xyz",
            task="test",
            role="default",
            repo="/repo",
            branch="main",
            evo_sha=None,
            source_event_id="evt-src-123",
        )

    assert emitted, "No events emitted"
    type_, data = emitted[0]
    assert type_ == "supervisor.job.launched"
    assert data["source_event_id"] == "evt-src-123"
    assert data["job_id"] == "job-xyz"
```

- [ ] **Step 2: Run test — verify it fails**

```bash
uv run pytest tests/test_supervisor_queue.py::test_launch_emits_source_event_id -v
```
Expected: FAIL

- [ ] **Step 3: Update `_launch` signature and emission**

In `_launch`, add `source_event_id: str = ""` parameter and include it in the emitted payload:

```python
async def _launch(
    self, job_id: str, task: str, role: str,
    repo: str, branch: str, evo_sha: str | None,
    source_event_id: str = "",
) -> None:
    logger.info("Launching job %s (role=%s, source=%s)", job_id, role, source_event_id or "?")

    jp = await launch_job(
        backend=self.backend,
        job_id=job_id,
        task=task,
        role=role,
        repo=repo,
        branch=branch,
        evo_sha=evo_sha,
        evo_repo_path=self.config.evo_repo_path,
        palimpsest_command=self.config.palimpsest_command,
        work_dir=Path(self.config.work_dir),
        eventstore_url=self.config.eventstore_url,
        eventstore_api_key_env=self.config.pasloe_api_key_env,
        eventstore_source=self.config.default_eventstore_source,
        llm_defaults=self.config.default_llm,
        workspace_defaults=self.config.default_workspace,
        publication_defaults=self.config.default_publication,
    )

    self.jobs[job_id] = jp

    await self.client.emit("supervisor.job.launched", {
        "job_id": job_id,
        "source_event_id": source_event_id,
        "task": task,
        "role": role,
        "evo_sha": evo_sha or "",
        "pid": jp.proc.pid,
    })
```

Update `_launch_from_item` to pass `source_event_id`:

```python
async def _launch_from_item(self, item: TaskItem) -> None:
    await self._launch(
        job_id=item.job_id,
        task=item.task,
        role=item.role,
        repo=item.repo,
        branch=item.branch,
        evo_sha=item.evo_sha,
        source_event_id=item.source_event_id,
    )
```

- [ ] **Step 4: Run test — verify it passes**

```bash
uv run pytest tests/test_supervisor_queue.py::test_launch_emits_source_event_id -v
```
Expected: PASS

- [ ] **Step 5: Run all tests so far**

```bash
uv run pytest tests/ -v
```
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
cd /home/holo/yoitsu
git add trenni/trenni/supervisor.py trenni/tests/test_supervisor_queue.py
git commit -m "feat(trenni): add source_event_id to supervisor.job.launched event"
```

---

## Task 6: `_fetch_all` helper

**Files:** Modify `trenni/trenni/supervisor.py`

Paginate Pasloe until `X-Next-Cursor` is absent, return all events of a given type.

- [ ] **Step 1: Write failing test**

Add to `trenni/tests/test_supervisor_queue.py`:

```python
@pytest.mark.asyncio
async def test_fetch_all_paginates_until_done():
    from unittest.mock import AsyncMock, patch
    from trenni.supervisor import Supervisor
    from trenni.config import TrenniConfig
    from trenni.pasloe_client import Event
    from datetime import datetime

    sup = Supervisor(TrenniConfig())

    def make_event(id_):
        return Event(id=id_, source_id="s", type="job.started",
                     ts=datetime.utcnow(), data={"job_id": id_})

    page1 = ([make_event("e1"), make_event("e2")], "cursor-page2")
    page2 = ([make_event("e3")], None)

    poll_results = [page1, page2]
    call_count = 0

    async def fake_poll(cursor=None, source=None, type_=None, limit=100):
        nonlocal call_count
        result = poll_results[call_count]
        call_count += 1
        return result

    sup.client.poll = fake_poll
    events = await sup._fetch_all("job.started")
    assert [e.id for e in events] == ["e1", "e2", "e3"]
    assert call_count == 2
```

- [ ] **Step 2: Run test — verify it fails**

```bash
uv run pytest tests/test_supervisor_queue.py::test_fetch_all_paginates_until_done -v
```
Expected: FAIL

- [ ] **Step 3: Add `_fetch_all` to supervisor.py**

Add after `_resolve_fork_join`:

```python
async def _fetch_all(
    self,
    type_: str,
    source: str | None = None,
) -> list[Event]:
    """Fetch all Pasloe events of a given type, paginating until exhausted."""
    results = []
    cursor = None
    while True:
        events, next_cursor = await self.client.poll(
            cursor=cursor,
            source=source,
            type_=type_,
            limit=100,
        )
        results.extend(events)
        if not next_cursor:
            break
        cursor = next_cursor
    return results
```

- [ ] **Step 4: Run test — verify it passes**

```bash
uv run pytest tests/test_supervisor_queue.py::test_fetch_all_paginates_until_done -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /home/holo/yoitsu
git add trenni/trenni/supervisor.py trenni/tests/test_supervisor_queue.py
git commit -m "feat(trenni): add _fetch_all pagination helper"
```

---

## Task 7: `_replay_unfinished_tasks`

**Files:** Modify `trenni/trenni/supervisor.py`

On startup, classify all historical `task.submit` events into 5 states and re-enqueue unfinished ones.

- [ ] **Step 1: Write failing tests**

Add to `trenni/tests/test_supervisor_queue.py`:

```python
@pytest.mark.asyncio
async def test_replay_enqueues_not_launched():
    """task.submit with no supervisor.job.launched → re-enqueue."""
    from unittest.mock import AsyncMock
    from trenni.supervisor import Supervisor
    from trenni.config import TrenniConfig
    from trenni.pasloe_client import Event
    from datetime import datetime

    sup = Supervisor(TrenniConfig())

    def make_event(id_, type_, data=None):
        return Event(id=id_, source_id="s", type=type_,
                     ts=datetime.utcnow(), data=data or {})

    async def fake_fetch_all(type_, source=None):
        if type_ == "task.submit":
            return [make_event("sub-1", "task.submit",
                               {"task": "do X", "role": "default", "repo": "/r", "branch": "main"})]
        return []

    sup._fetch_all = fake_fetch_all
    await sup._replay_unfinished_tasks()
    assert sup._task_queue.qsize() == 1


@pytest.mark.asyncio
async def test_replay_skips_completed():
    """task.submit with launched + started + completed → skip."""
    from trenni.supervisor import Supervisor
    from trenni.config import TrenniConfig
    from trenni.pasloe_client import Event
    from datetime import datetime

    sup = Supervisor(TrenniConfig())

    def make_event(id_, type_, data=None):
        return Event(id=id_, source_id="s", type=type_,
                     ts=datetime.utcnow(), data=data or {})

    async def fake_fetch_all(type_, source=None):
        if type_ == "task.submit":
            return [make_event("sub-1", "task.submit",
                               {"task": "do X", "role": "default", "repo": "/r", "branch": "main"})]
        if type_ == "supervisor.job.launched":
            return [make_event("launched-1", "supervisor.job.launched",
                               {"source_event_id": "sub-1", "job_id": "job-A"})]
        if type_ == "job.started":
            return [make_event("started-1", "job.started", {"job_id": "job-A"})]
        if type_ == "job.completed":
            return [make_event("done-1", "job.completed", {"job_id": "job-A"})]
        return []

    sup._fetch_all = fake_fetch_all
    await sup._replay_unfinished_tasks()
    assert sup._task_queue.qsize() == 0
    assert "sub-1" in sup._launched_event_ids


@pytest.mark.asyncio
async def test_replay_reenqueues_launched_not_started():
    """launched + no job.started + no job end + not in self.jobs → re-enqueue."""
    from trenni.supervisor import Supervisor
    from trenni.config import TrenniConfig
    from trenni.pasloe_client import Event
    from datetime import datetime

    sup = Supervisor(TrenniConfig())

    def make_event(id_, type_, data=None):
        return Event(id=id_, source_id="s", type=type_,
                     ts=datetime.utcnow(), data=data or {})

    async def fake_fetch_all(type_, source=None):
        if type_ == "task.submit":
            return [make_event("sub-1", "task.submit",
                               {"task": "do X", "role": "default", "repo": "/r", "branch": "main"})]
        if type_ == "supervisor.job.launched":
            return [make_event("launched-1", "supervisor.job.launched",
                               {"source_event_id": "sub-1", "job_id": "job-A"})]
        return []  # no job.started, no job.completed, no job.failed

    sup._fetch_all = fake_fetch_all
    await sup._replay_unfinished_tasks()
    assert sup._task_queue.qsize() == 1
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
uv run pytest tests/test_supervisor_queue.py::test_replay_enqueues_not_launched tests/test_supervisor_queue.py::test_replay_skips_completed tests/test_supervisor_queue.py::test_replay_reenqueues_launched_not_started -v
```
Expected: FAIL

- [ ] **Step 3: Add `_replay_unfinished_tasks` to supervisor.py**

Add after `_fetch_all`:

```python
async def _replay_unfinished_tasks(self) -> None:
    """On startup: replay Pasloe history to recover unfinished tasks into the queue."""
    logger.info("Replaying unfinished tasks from Pasloe...")

    # 1–4: load all relevant event sets
    launched_events = await self._fetch_all(
        "supervisor.job.launched", source=self.config.source_id
    )
    started_events = await self._fetch_all("job.started")
    completed_events = await self._fetch_all("job.completed")
    failed_events = await self._fetch_all("job.failed")
    submit_events = await self._fetch_all("task.submit")

    # Build lookup sets
    # source_event_id → job_id (only events with source_event_id set)
    launched_map: dict[str, str] = {
        e.data["source_event_id"]: e.data["job_id"]
        for e in launched_events
        if e.data.get("source_event_id")
    }
    started_job_ids: set[str] = {e.data["job_id"] for e in started_events if e.data.get("job_id")}
    finished_job_ids: set[str] = {
        e.data["job_id"] for e in (completed_events + failed_events) if e.data.get("job_id")
    }

    # 5: find globally latest event for cursor initialization
    all_events = launched_events + started_events + completed_events + failed_events + submit_events
    latest = max(all_events, key=lambda e: (e.ts, e.id), default=None)
    if latest:
        self.event_cursor = f"{latest.ts.isoformat()}|{latest.id}"
        logger.info("Replay cursor initialized to %s", self.event_cursor)

    # 6: classify each task.submit
    enqueued = skipped = orphans = 0
    for event in submit_events:
        data = event.data
        task = data.get("task", "")
        if not task:
            continue

        job_id_from_launch = launched_map.get(event.id)

        if job_id_from_launch:
            job_started = job_id_from_launch in started_job_ids
            job_finished = job_id_from_launch in finished_job_ids

            if job_started and job_finished:
                # Complete — skip
                self._launched_event_ids.add(event.id)
                skipped += 1
                continue

            if not job_started and not job_finished:
                if job_id_from_launch in self.jobs:
                    # Process alive — skip
                    self._launched_event_ids.add(event.id)
                    skipped += 1
                    continue
                # Launched but never started and not running — re-enqueue
                # (old supervisor.job.launched remains in Pasloe; that is fine)

            if job_started and not job_finished:
                if job_id_from_launch in self.jobs:
                    # Still running — skip
                    self._launched_event_ids.add(event.id)
                    skipped += 1
                    continue
                # Orphan — started but no terminal event and process gone
                logger.warning(
                    "Orphaned job %s (task.submit=%s): started but no terminal event. "
                    "TODO: emit compensating event.",
                    job_id_from_launch, event.id,
                )
                orphans += 1
                pass  # TODO: emit compensating event
                continue

        # Not launched, or launched-not-started with dead process → re-enqueue
        new_job_id = self._generate_job_id()
        self._launched_event_ids.add(event.id)
        item = TaskItem(
            source_event_id=event.id,
            job_id=new_job_id,
            task=task,
            role=data.get("role", "default"),
            repo=data.get("repo", ""),
            branch=data.get("branch", "main"),
            evo_sha=data.get("evo_sha"),
        )
        await self._task_queue.put(item)
        enqueued += 1

    logger.info(
        "Replay complete: %d enqueued, %d skipped, %d orphans",
        enqueued, skipped, orphans,
    )
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
uv run pytest tests/test_supervisor_queue.py::test_replay_enqueues_not_launched tests/test_supervisor_queue.py::test_replay_skips_completed tests/test_supervisor_queue.py::test_replay_reenqueues_launched_not_started -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /home/holo/yoitsu
git add trenni/trenni/supervisor.py trenni/tests/test_supervisor_queue.py
git commit -m "feat(trenni): add _replay_unfinished_tasks with 5-state classification"
```

---

## Task 8: Wire into `Supervisor.start()` + shutdown

**Files:** Modify `trenni/trenni/supervisor.py`

Call `_replay_unfinished_tasks()` on startup, launch `_drain_queue` as a task, cancel it on shutdown.

- [ ] **Step 1: Write failing test**

Add to `trenni/tests/test_supervisor_queue.py`:

```python
@pytest.mark.asyncio
async def test_start_calls_replay_and_drain():
    from unittest.mock import AsyncMock, patch
    from trenni.supervisor import Supervisor
    from trenni.config import TrenniConfig

    sup = Supervisor(TrenniConfig())

    replay_called = False

    async def fake_replay():
        nonlocal replay_called
        replay_called = True

    sup._replay_unfinished_tasks = fake_replay

    # Patch _run_loop to return immediately so start() doesn't loop forever
    with patch.object(sup, "_run_loop", new_callable=AsyncMock) as mock_run_loop, \
         patch.object(sup.client, "register_source", new_callable=AsyncMock), \
         patch.object(sup.client, "close", new_callable=AsyncMock), \
         patch("asyncio.create_task") as mock_create_task:

        mock_task = AsyncMock()
        mock_create_task.return_value = mock_task

        await sup.start()

    assert replay_called
    mock_run_loop.assert_called_once()
    mock_create_task.assert_called_once()
    mock_task.cancel.assert_called_once()
```

- [ ] **Step 2: Run test — verify it fails**

```bash
uv run pytest tests/test_supervisor_queue.py::test_start_calls_replay_and_drain -v
```
Expected: FAIL

- [ ] **Step 3: Update `Supervisor.start()` in supervisor.py**

Replace the `start` method:

```python
async def start(self) -> None:
    logger.info(
        "Supervisor starting (max_workers=%d, isolation=%s)",
        self.config.max_workers, self.config.isolation_backend,
    )
    self.running = True
    work_dir = Path(self.config.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    await self.client.register_source()
    logger.info("Registered source '%s' with Pasloe", self.config.source_id)

    await self._replay_unfinished_tasks()

    drain_task = asyncio.create_task(self._drain_queue())
    try:
        await self._run_loop()
    except asyncio.CancelledError:
        logger.info("Supervisor loop cancelled")
    finally:
        self.running = False
        drain_task.cancel()
        try:
            await drain_task
        except asyncio.CancelledError:
            pass
        await self.client.close()
```

- [ ] **Step 4: Run test — verify it passes**

```bash
uv run pytest tests/test_supervisor_queue.py::test_start_calls_replay_and_drain -v
```
Expected: PASS

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest tests/ -v
```
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
cd /home/holo/yoitsu
git add trenni/trenni/supervisor.py trenni/tests/test_supervisor_queue.py
git commit -m "feat(trenni): wire replay + drain_queue into start(), clean shutdown"
```

---

## Task 9: Fix `monitor.py`

**Files:** Modify `yoitsu/monitor.py`

Full rewrite: fix API parsing, add cursor (persisted in STATE_FILE), job state dict, noise filter, health checks, report filename.

- [ ] **Step 1: Rewrite `monitor.py`**

```python
#!/usr/bin/env python3
"""Monitor script for Yoitsu test runs."""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

import httpx

PASLOE_URL = "http://localhost:8000"
TRENNI_URL = "http://localhost:8100"
API_KEY = "yoitsu-test-key-2026"

STATE_FILE = Path("/home/holo/yoitsu/monitor-state.json")
REPORT_FILE = Path(f"/home/holo/yoitsu/test-report-{datetime.now().strftime('%Y-%m-%d')}.md")

IGNORED_EVENT_TYPES = {
    "agent.llm.request",
    "agent.llm.response",
    "agent.tool.exec",
    "agent.tool.result",
    "job.stage.transition",
}


class Monitor:
    def __init__(self, duration_hours: float = 5.0):
        self.start_time = datetime.now()
        self.end_time = None  # set in run()
        self.duration_hours = duration_hours

        # Load persisted cursor
        self.event_cursor: str | None = None
        if STATE_FILE.exists():
            try:
                state = json.loads(STATE_FILE.read_text())
                self.event_cursor = state.get("event_cursor")
            except Exception:
                pass

        # Job state tracking: job_id -> "launched"|"started"|"completed"|"failed"
        self.jobs: dict[str, str] = {}
        self.tasks_submitted: int = 0
        self.errors: list[str] = []

    async def run(self):
        from datetime import timedelta
        self.end_time = self.start_time + timedelta(hours=self.duration_hours)
        print(f"[Monitor] Started at {self.start_time.isoformat()}")
        print(f"[Monitor] Will run until {self.end_time.isoformat()}")

        while datetime.now() < self.end_time:
            try:
                await self._poll_events()
                await self._check_health()
                self._print_status()
                self._save_state()
            except Exception as e:
                msg = f"[{datetime.now().isoformat()}] Error: {e}"
                print(msg, file=sys.stderr)
                self.errors.append(msg)

            await asyncio.sleep(30)

        self._write_report()
        print(f"[Monitor] Done. Report: {REPORT_FILE}")

    async def _poll_events(self):
        params: dict = {"limit": "100", "order": "asc"}
        if self.event_cursor:
            params["cursor"] = self.event_cursor

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{PASLOE_URL}/events",
                params=params,
                headers={"X-API-Key": API_KEY},
                timeout=15.0,
            )
            resp.raise_for_status()
            events = resp.json()  # bare list[Event]
            next_cursor = resp.headers.get("X-Next-Cursor")

        if not events:
            return

        for event in events:
            self._process_event(event)

        # Advance cursor
        if next_cursor:
            self.event_cursor = next_cursor
        else:
            last = events[-1]
            self.event_cursor = f"{last['ts']}|{last['id']}"

    def _process_event(self, event: dict):
        etype = event.get("type", "")
        data = event.get("data", {})
        job_id = data.get("job_id", "")

        if etype == "task.submit":
            self.tasks_submitted += 1
        elif etype == "supervisor.job.launched" and job_id:
            self.jobs[job_id] = "launched"
        elif etype == "job.started" and job_id:
            self.jobs[job_id] = "started"
        elif etype == "job.completed" and job_id:
            self.jobs[job_id] = "completed"
        elif etype == "job.failed" and job_id:
            self.jobs[job_id] = "failed"

        if etype not in IGNORED_EVENT_TYPES:
            print(f"  [{etype}] {job_id or data}")

    async def _check_health(self):
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Pasloe health
            try:
                await client.get(f"{PASLOE_URL}/events/stats",
                                 headers={"X-API-Key": API_KEY})
            except Exception as e:
                print(f"[Monitor] WARNING: Pasloe unreachable: {e}", file=sys.stderr)

            # Trenni health
            try:
                resp = await client.get(f"{TRENNI_URL}/status")
                d = resp.json()
                print(f"[Monitor] Trenni: jobs={d.get('running_jobs')}/{d.get('max_workers')} "
                      f"forks={d.get('fork_joins_active')}")
            except Exception as e:
                print(f"[Monitor] WARNING: Trenni unreachable: {e}", file=sys.stderr)

    def _print_status(self):
        completed = sum(1 for s in self.jobs.values() if s == "completed")
        failed = sum(1 for s in self.jobs.values() if s == "failed")
        in_progress = sum(1 for s in self.jobs.values() if s in ("launched", "started"))
        elapsed = (datetime.now() - self.start_time).total_seconds()
        remaining = (self.end_time - datetime.now()).total_seconds()
        rate = f"{completed/(completed+failed)*100:.0f}%" if (completed + failed) > 0 else "n/a"

        print(
            f"[Monitor] {elapsed/60:.0f}min elapsed | {remaining/60:.0f}min left | "
            f"submitted={self.tasks_submitted} total={len(self.jobs)} "
            f"in_progress={in_progress} completed={completed} failed={failed} rate={rate}"
        )

    def _save_state(self):
        STATE_FILE.write_text(json.dumps({
            "start_time": self.start_time.isoformat(),
            "event_cursor": self.event_cursor,
            "tasks_submitted": self.tasks_submitted,
            "jobs": self.jobs,
        }, indent=2))

    def _write_report(self):
        completed = sum(1 for s in self.jobs.values() if s == "completed")
        failed = sum(1 for s in self.jobs.values() if s == "failed")
        duration = (datetime.now() - self.start_time).total_seconds()
        rate = f"{completed/(completed+failed)*100:.1f}%" if (completed + failed) > 0 else "n/a"

        lines = [
            f"# Yoitsu 测试报告",
            f"",
            f"## 概览",
            f"- **开始**: {self.start_time.isoformat()}",
            f"- **结束**: {datetime.now().isoformat()}",
            f"- **时长**: {duration/60:.1f} 分钟",
            f"",
            f"## 统计",
            f"- 任务提交: {self.tasks_submitted}",
            f"- Jobs 总数: {len(self.jobs)}",
            f"- 完成: {completed}",
            f"- 失败: {failed}",
            f"- 成功率: {rate}",
            f"",
            f"## 错误",
        ]
        if self.errors:
            lines += [f"- {e}" for e in self.errors]
        else:
            lines.append("无")

        REPORT_FILE.write_text("\n".join(lines))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=float, default=5.0)
    args = parser.parse_args()
    asyncio.run(Monitor(duration_hours=args.hours).run())
```

- [ ] **Step 2: Verify it runs without import errors**

```bash
cd /home/holo/yoitsu
python -c "import monitor; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
cd /home/holo/yoitsu && git add monitor.py
git commit -m "fix(monitor): cursor tracking, job state dict, noise filter, health checks"
```

---

## Task 10: Fix `submit-tasks.py`

**Files:** Modify `yoitsu/submit-tasks.py`

Add pre-flight health check (warn if Trenni down, exit if Pasloe down), print event ids.

- [ ] **Step 1: Update `submit-tasks.py`**

Replace the entire file:

```python
#!/usr/bin/env python3
"""Submit tasks for a Yoitsu test run."""

import asyncio
import sys

import httpx

PASLOE_URL = "http://localhost:8000"
TRENNI_URL = "http://localhost:8100"
API_KEY = "yoitsu-test-key-2026"
SOURCE_ID = "test-coordinator"

TASKS = [
    # Palimpsest improvements
    {
        "task": "Review and improve palimpsest error handling in runner.py. Add better exception catching, logging, and recovery mechanisms. Focus on Stage 1-4 error handling.",
        "role": "default",
        "repo": "/home/holo/yoitsu/palimpsest",
        "branch": "master",
    },
    {
        "task": "Add comprehensive type hints to palimpsest/config.py and palimpsest/events.py. Ensure all dataclasses have proper type annotations.",
        "role": "default",
        "repo": "/home/holo/yoitsu/palimpsest",
        "branch": "master",
    },
    {
        "task": "Review palimpsest tool system. Add new file operation tools: move_file, copy_file, delete_file. Follow existing patterns in evo/tools/.",
        "role": "default",
        "repo": "/home/holo/yoitsu/palimpsest",
        "branch": "master",
    },
    {
        "task": "Improve palimpsest context assembly performance. Review context.py and optimize file tree building and provider loading.",
        "role": "default",
        "repo": "/home/holo/yoitsu/palimpsest",
        "branch": "master",
    },
    {
        "task": "Add unit tests for palimpsest resolver.py and emitter.py. Create test cases following existing patterns in tests/.",
        "role": "default",
        "repo": "/home/holo/yoitsu/palimpsest",
        "branch": "master",
    },
    # Pasloe improvements
    {
        "task": "Add metrics export endpoint to Pasloe. Create /metrics endpoint that returns job counts, event rates, and webhook status in JSON format.",
        "role": "default",
        "repo": "/home/holo/yoitsu/pasloe",
        "branch": "master",
    },
    {
        "task": "Improve Pasloe WebUI. Add event filtering by type and source to the /ui dashboard.",
        "role": "default",
        "repo": "/home/holo/yoitsu/pasloe",
        "branch": "master",
    },
    {
        "task": "Add batch event query endpoint to Pasloe. Allow querying multiple event types in a single request.",
        "role": "default",
        "repo": "/home/holo/yoitsu/pasloe",
        "branch": "master",
    },
    # Trenni improvements
    {
        "task": "Review and improve Trenni fork-join logic in supervisor.py. Add better error handling for child task failures and parent resume logic.",
        "role": "default",
        "repo": "/home/holo/yoitsu/trenni",
        "branch": "master",
    },
    {
        "task": "Add dynamic capacity adjustment to Trenni. Implement logic to adjust max_workers based on system load (CPU/memory).",
        "role": "default",
        "repo": "/home/holo/yoitsu/trenni",
        "branch": "master",
    },
    {
        "task": "Improve Trenni error recovery. Add retry logic for failed job launches and better cleanup on supervisor shutdown.",
        "role": "default",
        "repo": "/home/holo/yoitsu/trenni",
        "branch": "master",
    },
    # Evo improvements
    {
        "task": "Review evo repository structure. Add documentation to roles/, contexts/, tools/, and prompts/ explaining the purpose of each file.",
        "role": "default",
        "repo": "/home/holo/yoitsu/palimpsest",
        "branch": "master",
    },
    {
        "task": "Create a new coding-focused role in evo/roles/. This role should be optimized for code review and refactoring tasks.",
        "role": "default",
        "repo": "/home/holo/yoitsu/palimpsest",
        "branch": "master",
    },
]


async def preflight():
    async with httpx.AsyncClient(timeout=5.0) as client:
        # Must have Pasloe
        try:
            resp = await client.get(
                f"{PASLOE_URL}/events?limit=1",
                headers={"X-API-Key": API_KEY},
            )
            resp.raise_for_status()
            print("[Preflight] Pasloe OK")
        except Exception as e:
            print(f"[Preflight] ERROR: Pasloe unreachable: {e}", file=sys.stderr)
            sys.exit(1)

        # Trenni is optional (tasks will replay on next start) but warn if down
        try:
            resp = await client.get(f"{TRENNI_URL}/status")
            d = resp.json()
            print(f"[Preflight] Trenni OK: jobs={d.get('running_jobs')}/{d.get('max_workers')}")
        except Exception as e:
            print(f"[Preflight] WARNING: Trenni unreachable ({e}). "
                  f"Tasks will be replayed when Trenni starts.", file=sys.stderr)


async def submit_task(client: httpx.AsyncClient, task_def: dict, index: int) -> None:
    resp = await client.post(
        f"{PASLOE_URL}/events",
        json={"source_id": SOURCE_ID, "type": "task.submit", "data": task_def},
        headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
    )
    resp.raise_for_status()
    event_id = resp.json().get("id", "?")
    print(f"[Submit] {index}/{len(TASKS)} submitted event_id={event_id}: "
          f"{task_def['task'][:60]}...")


async def main():
    await preflight()

    print(f"[Submit] Submitting {len(TASKS)} tasks...")
    async with httpx.AsyncClient(timeout=15.0) as client:
        for i, task in enumerate(TASKS, 1):
            try:
                await submit_task(client, task, i)
            except Exception as e:
                print(f"[Submit] Failed task {i}: {e}", file=sys.stderr)
            await asyncio.sleep(0.1)

    print("[Submit] Done.")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Verify it runs without import errors**

```bash
cd /home/holo/yoitsu
python -c "import submit_tasks; print('OK')" 2>/dev/null || python submit-tasks.py --help 2>/dev/null || python -c "
import ast, pathlib
ast.parse(pathlib.Path('submit-tasks.py').read_text())
print('syntax OK')
"
```
Expected: `syntax OK`

- [ ] **Step 3: Commit**

```bash
cd /home/holo/yoitsu && git add submit-tasks.py
git commit -m "fix(submit-tasks): pre-flight health checks, print event ids"
```

---

## Task 11: Final integration check

Run the full trenni test suite and confirm all tests pass.

- [ ] **Step 1: Run all tests**

```bash
cd /home/holo/yoitsu/trenni && uv run pytest tests/ -v
```
Expected: all PASS, no errors

- [ ] **Step 2: Quick smoke test of supervisor import**

```bash
uv run python -c "
from trenni.supervisor import Supervisor, TaskItem
from trenni.config import TrenniConfig
import asyncio
s = Supervisor(TrenniConfig())
print('queue:', s._task_queue)
print('dedup set:', s._launched_event_ids)
print('job_id sample:', s._generate_job_id())
print('OK')
"
```
Expected: prints `OK` with a UUID v7 job_id

- [ ] **Step 3: Final commit**

```bash
cd /home/holo/yoitsu
git status  # verify only expected files changed
git add trenni/
git commit -m "test(trenni): verify full queue + replay integration"
```
