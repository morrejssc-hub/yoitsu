# Optimizer Proposal Task ID Collision Implementation Plan

> **REQUIRED SUB-SKILL:** Use the executing-plans skill to implement this plan task-by-task.

**Goal:** Fix the optimizer-output closure so a parsed `ReviewProposal` spawns a new implementer task/job instead of reusing and overwriting the optimizer task/job IDs.

**Architecture:** The collision happens because `_handle_optimizer_output()` synthesizes a trigger event ID from `job_id`, and `_process_trigger()` derives `task_id` from the first 16 hex chars of that event ID. For optimizer jobs, `job_id` begins with the parent `task_id`, so the derived proposal task ID collides with the optimizer task. The fix should preserve replay/idempotency behavior while making proposal-trigger task IDs derive from a unique source event ID that cannot collapse back to the optimizer task ID.

**Tech Stack:** Python 3.11, Trenni supervisor state machine, pytest, Pydantic trigger models, Pasloe event semantics.

---

## Context to read before coding

- `trenni/trenni/supervisor.py`
  - `_handle_optimizer_output()`
  - `_process_trigger()`
  - `_root_task_id()`
- `trenni/tests/test_optimizer_output.py`
- `yoitsu-contracts/src/yoitsu_contracts/external_events.py`
- `yoitsu-contracts/src/yoitsu_contracts/review_proposal.py`

## Root cause summary

Today `_handle_optimizer_output()` creates:

```python
synthetic_event = SimpleNamespace(
    id=f"{job_id}-proposal",
    ...
)
```

Then `_process_trigger()` does:

```python
task_id = self._root_task_id(event.id)
root_job_id = f"{task_id}-root"
```

And `_root_task_id()` keeps the first 16 hex chars. For an optimizer job like:

```text
job_id = 9a77a7b31508b8ef-root
```

`event.id = 9a77a7b31508b8ef-root-proposal` still starts with the same 16 hex chars, so the proposal trigger resolves to the original task ID:

```text
task_id = 9a77a7b31508b8ef
```

That overwrites the optimizer task and reuses `9a77a7b31508b8ef-root` for the implementer job.

The safest minimal fix is: **derive the proposal trigger event ID from the completion event ID, not from the optimizer job ID**. The completion event ID is already unique/stable for replay and does not share the optimizer task prefix.

---

### Task 1: Add a regression test for proposal-trigger task uniqueness

**TDD scenario:** Modifying tested code — run existing tests first

**Files:**
- Modify: `trenni/tests/test_optimizer_output.py`
- Test command: `cd /home/holo/yoitsu/trenni && ../.venv/bin/pytest tests/test_optimizer_output.py -q`

**Step 1: Run the existing optimizer-output tests first**

Run:
```bash
cd /home/holo/yoitsu/trenni && ../.venv/bin/pytest tests/test_optimizer_output.py -q
```

Expected: existing file is green before the change.

**Step 2: Add a failing regression test that reproduces the collision**

Add a test near `TestOptimizerOutputHandling` with this shape:

```python
@pytest.mark.asyncio
async def test_optimizer_proposal_spawns_distinct_task_and_job_ids():
    from trenni.supervisor import Supervisor
    from trenni.config import TrenniConfig

    config = TrenniConfig()
    supervisor = Supervisor(config)
    supervisor.client = AsyncMock()

    optimizer_task_id = "9a77a7b31508b8ef"
    optimizer_job_id = f"{optimizer_task_id}-root"
    job = SpawnedJob(
        job_id=optimizer_job_id,
        source_event_id="obs-agg-tool_repetition-62bb6101",
        goal="Analyze tool repetition",
        role="optimizer",
        repo="",
        init_branch="main",
        evo_sha="",
        budget=0.5,
        task_id=optimizer_task_id,
        bundle="factorio",
    )
    supervisor.state.jobs_by_id[optimizer_job_id] = job
    supervisor.state.tasks[optimizer_task_id] = MagicMock(
        task_id=optimizer_task_id,
        bundle="factorio",
        job_order=[optimizer_job_id],
        terminal=False,
        eval_spawned=False,
        state="running",
    )

    proposal = ReviewProposal(
        problem_classification=ProblemClassification(
            category=ProblemCategory.OTHER,
            severity=SeverityLevel.MEDIUM,
            summary="Repeated tool usage",
        ),
        executable_proposal=ExecutableProposal(
            action_type=ActionType.IMPROVE_TOOL,
            description="Create area scan tool",
            estimated_impact="Reduce steps",
        ),
        task_template=TaskTemplate(
            goal="在 factorio/scripts/ 下创建 area_scan_resources.lua",
            role="implementer",
            bundle="factorio",
            budget=1.5,
        ),
    )

    completion_event = SimpleNamespace(
        id="069d6591-8cf8-7fb4-8000-eea678d5e9ce",
        type="agent.job.completed",
        data={"summary": proposal.model_dump_json(), "cost": 0.0},
        ts=datetime.now(timezone.utc),
    )

    await supervisor._handle_optimizer_output(optimizer_job_id, job, completion_event)

    implementer_jobs = [
        j for j in supervisor.state.jobs_by_id.values()
        if j.role == "implementer"
    ]
    assert len(implementer_jobs) == 1
    implementer_job = implementer_jobs[0]
    assert implementer_job.task_id != optimizer_task_id
    assert implementer_job.job_id != optimizer_job_id
```

**Step 3: Run the new test to verify it fails**

Run:
```bash
cd /home/holo/yoitsu/trenni && ../.venv/bin/pytest tests/test_optimizer_output.py -q -k distinct_task_and_job_ids
```

Expected: FAIL because the implementer job/task reuse the optimizer IDs.

**Step 4: Commit the failing-test checkpoint (optional if you want strict TDD evidence)**

```bash
git add trenni/tests/test_optimizer_output.py
git commit -m "test(trenni): reproduce optimizer proposal task id collision"
```

---

### Task 2: Fix proposal synthetic event identity at the source

**TDD scenario:** Modifying tested code — failing regression test already added

**Files:**
- Modify: `trenni/trenni/supervisor.py`
- Test: `trenni/tests/test_optimizer_output.py`

**Step 1: Change `_handle_optimizer_output()` to derive proposal trigger identity from the completion event**

Replace the current synthetic event construction with a version based on `event.id`, not `job_id`.

Target block:

```python
synthetic_event = SimpleNamespace(
    id=f"{job_id}-proposal",
    source_id=self.config.source_id,
    type="trigger.review_proposal",
    data=trigger_data,
    ts=datetime.now(timezone.utc),
)
```

Recommended minimal implementation:

```python
proposal_source_event_id = f"{event.id}-proposal"
synthetic_event = SimpleNamespace(
    id=proposal_source_event_id,
    source_id=self.config.source_id,
    type="trigger.review_proposal",
    data=trigger_data,
    ts=datetime.now(timezone.utc),
)
```

Why this fix:
- `event.id` is unique per optimizer completion event
- replay stays stable because the completion event ID is stable
- `_root_task_id()` will derive a new task ID that does not match the optimizer task ID
- idempotency keys still use the synthetic event ID cleanly

**Step 2: Run the focused regression test**

Run:
```bash
cd /home/holo/yoitsu/trenni && ../.venv/bin/pytest tests/test_optimizer_output.py -q -k distinct_task_and_job_ids
```

Expected: PASS.

**Step 3: Run the full optimizer-output file**

Run:
```bash
cd /home/holo/yoitsu/trenni && ../.venv/bin/pytest tests/test_optimizer_output.py -q
```

Expected: PASS.

**Step 4: Commit**

```bash
git add trenni/trenni/supervisor.py trenni/tests/test_optimizer_output.py
git commit -m "fix(trenni): give proposal-trigger tasks distinct ids"
```

---

### Task 3: Add a coverage test for stable proposal source event wiring

**TDD scenario:** Modifying tested code — add regression coverage for event lineage

**Files:**
- Modify: `trenni/tests/test_optimizer_output.py`

**Step 1: Add a second small test that asserts the spawned implementer job keeps proposal lineage**

Suggested test:

```python
@pytest.mark.asyncio
async def test_optimizer_proposal_source_event_id_uses_completion_event_id():
    ...
    completion_event = SimpleNamespace(
        id="evt-optimizer-complete-123",
        ...
    )
    await supervisor._handle_optimizer_output(...)

    implementer_job = next(
        j for j in supervisor.state.jobs_by_id.values()
        if j.role == "implementer"
    )
    assert implementer_job.source_event_id == "evt-optimizer-complete-123-proposal"
```

This test protects against future reintroduction of `job_id`-based synthetic IDs.

**Step 2: Run only the new lineage test**

Run:
```bash
cd /home/holo/yoitsu/trenni && ../.venv/bin/pytest tests/test_optimizer_output.py -q -k source_event_id_uses_completion_event_id
```

Expected: PASS.

**Step 3: Re-run the full file**

Run:
```bash
cd /home/holo/yoitsu/trenni && ../.venv/bin/pytest tests/test_optimizer_output.py -q
```

Expected: PASS.

**Step 4: Commit**

```bash
git add trenni/tests/test_optimizer_output.py
git commit -m "test(trenni): lock proposal trigger lineage to completion event ids"
```

---

### Task 4: Verify the fix in the live Trenni container

**TDD scenario:** Trivial change — use judgment

**Files:**
- No repo code change required if Task 2 already fixed bootstrap path
- Verify live runtime under `~/.config/containers/systemd/yoitsu/bin/start-trenni.sh`

**Step 1: Run the targeted tests in repo before touching live service**

Run:
```bash
cd /home/holo/yoitsu && .venv/bin/pytest -q trenni/tests/test_optimizer_output.py -k 'distinct_task_and_job_ids or source_event_id_uses_completion_event_id'
```

Expected: PASS.

**Step 2: Restart live Trenni so the new supervisor code is installed**

Run:
```bash
systemctl --user restart yoitsu-trenni.service
sleep 5
systemctl --user is-active yoitsu-trenni.service
```

Expected: `active`.

**Step 3: Confirm live installed code contains the fix**

Run:
```bash
podman exec yoitsu-trenni sh -lc 'sed -n "1408,1448p" /var/lib/yoitsu/venvs/trenni/lib/python3.11/site-packages/trenni/supervisor.py'
```

Expected: synthetic proposal event ID uses `event.id`, not `job_id`.

**Step 4: Trigger or wait for one real factorio optimizer completion and inspect resulting IDs**

Run:
```bash
curl -s 'http://127.0.0.1:8100/control/jobs?task_id=<optimizer-task-id>' | jq
curl -s 'http://127.0.0.1:8100/control/tasks/<new-implementer-task-id>' | jq
```

Expected:
- optimizer task ID and implementer task ID are different
- optimizer job ID and implementer job ID are different
- implementer task is a separate task record, not an overwrite of the optimizer task

**Step 5: Commit any live config/bootstrap follow-up only if needed**

```bash
git add <only-if-changed>
git commit -m "chore: refresh live trenni after proposal id collision fix"
```

---

### Task 5: Resume the Factorio loop-closure smoke and update documentation

**TDD scenario:** Trivial change — use judgment

**Files:**
- Modify: `docs/runbooks/2026-04-07-factorio-optimization-loop-closure-runbook.md`
- Modify: `docs/plans/2026-04-07-factorio-optimization-loop-closure.md`

**Step 1: Re-run the real smoke after the fix**

Goal to submit again:
```text
用挖矿机挖 50 个铁矿
```

**Step 2: Record the exact chain**

Capture:
- worker task ID / job ID
- `observation.tool_repetition`
- factorio optimizer task ID / job ID
- proposal-spawned implementer task ID / job ID
- created script path in `evo/factorio/scripts/` or live mod scripts dir

**Step 3: Update the runbook with the collision root cause and fix**

Add a short section documenting:
- original bug (`job_id`-derived proposal synthetic event caused task ID reuse)
- fix (`event.id`-derived proposal synthetic event)
- evidence from the real smoke

**Step 4: Update the main closure plan status**

Mark Task 5 substeps appropriately after live verification.

**Step 5: Commit docs**

```bash
git add docs/runbooks/2026-04-07-factorio-optimization-loop-closure-runbook.md docs/plans/2026-04-07-factorio-optimization-loop-closure.md
git commit -m "docs: record optimizer proposal id collision fix"
```

---

## Verification checklist

Before claiming the bug is fixed, verify all of these:

- [ ] `trenni/tests/test_optimizer_output.py` includes a regression that failed before the fix
- [ ] proposal-trigger implementer task ID differs from optimizer task ID
- [ ] proposal-trigger implementer job ID differs from optimizer job ID
- [ ] spawned implementer `source_event_id` is derived from the optimizer completion event ID
- [ ] full optimizer-output test file passes
- [ ] live Trenni site-packages contains the updated `_handle_optimizer_output()` implementation
- [ ] one real factorio optimizer completion produces a separate implementer task instead of overwriting the optimizer task

## Notes for the implementing engineer

- Do **not** redesign the whole task-ID derivation system unless the focused fix fails. YAGNI.
- Keep replay/idempotency behavior stable; this bug is about synthetic proposal event identity, not global task ID generation.
- The existing end-to-end optimizer-output tests are close to the right location; extend them instead of creating a brand-new test module.
- If you discover that `event.id` is unavailable in some replay path, add the smallest fallback necessary and cover it with a dedicated test before changing production code.
