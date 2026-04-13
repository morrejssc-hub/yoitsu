# Autonomous Review Loop Output Closure Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让 optimizer 角色的 ReviewProposal 输出在运行时主链中被消费，自动生成后续优化任务，完成自治优化闭环。

**Architecture:** 在 `_handle_job_done` 中检测 optimizer role 的完成，解析 summary 字段中的 ReviewProposal JSON，转换为 TriggerData 并送入 `_process_trigger()`。消费点唯一（job 完成后），解析失败不污染正常任务流。

**Tech Stack:** Python, Pydantic, asyncio, yoitsu-contracts (ReviewProposal, TriggerData), trenni (supervisor)

---

## Task 1: 在 supervisor.py 中添加 optimizer 输出处理方法

**Files:**
- Modify: `trenni/trenni/supervisor.py:617` (_handle_job_done 后添加调用)
- Modify: `trenni/trenni/supervisor.py:1680+` (添加 _handle_optimizer_output 方法)

**Step 1: 在 _handle_job_done 中添加 optimizer 输出处理调用**

在 `_emit_budget_variance` 调用后添加 optimizer 输出处理：

```python
# 在 _handle_job_done 中，_emit_budget_variance 调用后添加：
# ADR-0010: Handle optimizer output - parse ReviewProposal and spawn optimization task
if not replay and not is_failure and not is_cancelled:
    await self._handle_optimizer_output(job_id, job_record, event)
```

**Step 2: 添加 _handle_optimizer_output 方法**

在 `_emit_budget_variance` 方法后添加新方法：

```python
async def _handle_optimizer_output(
    self,
    job_id: str,
    job: SpawnedJob | None,
    event: Event,
) -> None:
    """Handle optimizer role output - parse ReviewProposal and spawn optimization task.

    Per ADR-0010: The optimizer role outputs structured proposals that can be
    converted into optimization tasks. This method:
    1. Detects if the completed job was an optimizer role
    2. Parses the summary field as ReviewProposal JSON
    3. Converts the proposal to a TriggerData
    4. Spawns the optimization task via _process_trigger

    Parsing failures are logged but do not interrupt normal flow.
    """
    from yoitsu_contracts.review_proposal import ReviewProposal
    from yoitsu_contracts.external_events import review_proposal_to_trigger

    # Only process optimizer role
    if job is None or job.role != "optimizer":
        return

    # Extract summary (contains the ReviewProposal JSON)
    summary = event.data.get("summary", "")
    if not summary:
        logger.warning("Optimizer job %s completed without summary", job_id)
        return

    # Parse ReviewProposal from summary
    proposal = ReviewProposal.from_json_str(summary)
    if proposal is None:
        logger.warning(
            "Optimizer job %s summary could not be parsed as ReviewProposal",
            job_id,
        )
        return

    # Convert proposal to trigger data
    trigger_data = review_proposal_to_trigger(proposal)

    # Create synthetic event for _process_trigger
    synthetic_event = SimpleNamespace(
        id=f"{job_id}-proposal",
        source_id=self.config.source_id,
        type="trigger.review_proposal",
        data=trigger_data,
        ts=datetime.now(timezone.utc),
    )

    # Validate as TriggerData
    try:
        data = TriggerData.model_validate(trigger_data)
    except Exception as e:
        logger.warning(
            "Optimizer proposal from job %s failed TriggerData validation: %s",
            job_id,
            e,
        )
        return

    # Process the trigger to spawn optimization task
    logger.info(
        "Spawning optimization task from optimizer job %s: goal=%s",
        job_id,
        data.goal[:50] if data.goal else "",
    )
    await self._process_trigger(synthetic_event, data, replay=False)
```

**Step 3: 验证语法正确**

Run: `python3 -c "from trenni.supervisor import Supervisor"`
Expected: No import errors

---

## Task 2: 添加 optimizer 输出处理的单元测试

**Files:**
- Create: `trenni/tests/test_optimizer_output.py`

**Step 1: 写测试文件**

```python
"""Tests for optimizer output handling and ReviewProposal closure (ADR-0010)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace
from datetime import datetime, timezone

from yoitsu_contracts.review_proposal import (
    ReviewProposal,
    ProblemClassification,
    ExecutableProposal,
    TaskTemplate,
    ProblemCategory,
    SeverityLevel,
    ActionType,
)
from yoitsu_contracts.events import TriggerData
from yoitsu_contracts.external_events import review_proposal_to_trigger
from trenni.state import SupervisorState, SpawnedJob


class TestOptimizerOutputHandling:
    """Test _handle_optimizer_output method."""

    @pytest.mark.asyncio
    async def test_optimizer_output_parsed_and_spawned(self):
        """Optimizer job output is parsed and spawns optimization task."""
        from trenni.supervisor import Supervisor
        from trenni.config import TrenniConfig

        # Create supervisor with mocked client
        config = TrenniConfig()
        supervisor = Supervisor(config)
        supervisor.client = AsyncMock()

        # Create optimizer job
        job_id = "optimizer-001"
        job = SpawnedJob(
            job_id=job_id,
            source_event_id="evt-threshold",
            goal="Analyze budget variance",
            role="optimizer",
            repo="",
            init_branch="main",
            evo_sha="abc123",
            budget=0.5,
            task_id="task-opt",
            team="default",
        )
        supervisor.state.jobs_by_id[job_id] = job

        # Create proposal JSON
        proposal = ReviewProposal(
            problem_classification=ProblemClassification(
                category=ProblemCategory.BUDGET_ACCURACY,
                severity=SeverityLevel.HIGH,
                summary="Budget variance exceeds threshold",
            ),
            executable_proposal=ExecutableProposal(
                action_type=ActionType.ADJUST_BUDGET,
                description="Increase planner budget by 20%",
                estimated_impact="Reduce variance by 15%",
            ),
            task_template=TaskTemplate(
                goal="Adjust planner budget estimation",
                role="implementer",
                budget=0.3,
            ),
        )
        summary = proposal.model_dump_json()

        # Create completion event
        event = SimpleNamespace(
            id="evt-complete",
            type="agent.job.completed",
            data={"summary": summary, "cost": 0.45},
            ts=datetime.now(timezone.utc),
        )

        # Handle optimizer output
        await supervisor._handle_optimizer_output(job_id, job, event)

        # Verify task was spawned (client.emit called for task.created)
        # At minimum, supervisor.task.created should be emitted
        assert supervisor.client.emit.called

    @pytest.mark.asyncio
    async def test_non_optimizer_job_not_processed(self):
        """Non-optimizer jobs are not processed for proposal output."""
        from trenni.supervisor import Supervisor
        from trenni.config import TrenniConfig

        config = TrenniConfig()
        supervisor = Supervisor(config)
        supervisor.client = AsyncMock()

        # Create planner job (not optimizer)
        job_id = "planner-001"
        job = SpawnedJob(
            job_id=job_id,
            source_event_id="evt-001",
            goal="Plan something",
            role="planner",
            repo="https://github.com/org/repo",
            init_branch="main",
            evo_sha="abc123",
            budget=0.5,
            task_id="task-001",
            team="default",
        )
        supervisor.state.jobs_by_id[job_id] = job

        # Create completion event with JSON-like summary
        event = SimpleNamespace(
            id="evt-complete",
            type="agent.job.completed",
            data={"summary": '{"some": "json"}', "cost": 0.3},
            ts=datetime.now(timezone.utc),
        )

        # Handle optimizer output
        await supervisor._handle_optimizer_output(job_id, job, event)

        # Should not process - no emit calls for task spawning
        # Only planner job, not optimizer
        assert not supervisor.client.emit.called

    @pytest.mark.asyncio
    async def test_invalid_proposal_json_logged_not_crashed(self):
        """Invalid proposal JSON is logged but doesn't crash."""
        from trenni.supervisor import Supervisor
        from trenni.config import TrenniConfig

        config = TrenniConfig()
        supervisor = Supervisor(config)
        supervisor.client = AsyncMock()

        # Create optimizer job
        job_id = "optimizer-002"
        job = SpawnedJob(
            job_id=job_id,
            source_event_id="evt-threshold",
            goal="Analyze budget variance",
            role="optimizer",
            repo="",
            init_branch="main",
            evo_sha="abc123",
            budget=0.5,
            task_id="task-opt",
            team="default",
        )
        supervisor.state.jobs_by_id[job_id] = job

        # Create completion event with invalid JSON
        event = SimpleNamespace(
            id="evt-complete",
            type="agent.job.completed",
            data={"summary": "not valid json at all", "cost": 0.45},
            ts=datetime.now(timezone.utc),
        )

        # Handle optimizer output - should not crash
        await supervisor._handle_optimizer_output(job_id, job, event)

        # Should not spawn any task
        assert not supervisor.client.emit.called

    @pytest.mark.asyncio
    async def test_missing_summary_logged_not_crashed(self):
        """Missing summary is logged but doesn't crash."""
        from trenni.supervisor import Supervisor
        from trenni.config import TrenniConfig

        config = TrenniConfig()
        supervisor = Supervisor(config)
        supervisor.client = AsyncMock()

        # Create optimizer job
        job_id = "optimizer-003"
        job = SpawnedJob(
            job_id=job_id,
            source_event_id="evt-threshold",
            goal="Analyze budget variance",
            role="optimizer",
            repo="",
            init_branch="main",
            evo_sha="abc123",
            budget=0.5,
            task_id="task-opt",
            team="default",
        )
        supervisor.state.jobs_by_id[job_id] = job

        # Create completion event without summary
        event = SimpleNamespace(
            id="evt-complete",
            type="agent.job.completed",
            data={"cost": 0.45},  # No summary
            ts=datetime.now(timezone.utc),
        )

        # Handle optimizer output - should not crash
        await supervisor._handle_optimizer_output(job_id, job, event)

        # Should not spawn any task
        assert not supervisor.client.emit.called

    @pytest.mark.asyncio
    async def test_proposal_in_markdown_code_block_parsed(self):
        """Proposal embedded in markdown code block is parsed."""
        from trenni.supervisor import Supervisor
        from trenni.config import TrenniConfig

        config = TrenniConfig()
        supervisor = Supervisor(config)
        supervisor.client = AsyncMock()

        # Create optimizer job
        job_id = "optimizer-004"
        job = SpawnedJob(
            job_id=job_id,
            source_event_id="evt-threshold",
            goal="Analyze budget variance",
            role="optimizer",
            repo="",
            init_branch="main",
            evo_sha="abc123",
            budget=0.5,
            task_id="task-opt",
            team="default",
        )
        supervisor.state.jobs_by_id[job_id] = job

        # Create proposal in markdown code block (realistic optimizer output)
        summary = """Based on my analysis, the planner role shows budget variance...

Here is my proposal:

```json
{
    "problem_classification": {
        "category": "budget_accuracy",
        "severity": "high",
        "summary": "Planner budget underestimation"
    },
    "executable_proposal": {
        "action_type": "adjust_budget",
        "description": "Increase planner budget by 20%",
        "estimated_impact": "Reduce variance by 15%"
    },
    "task_template": {
        "goal": "Adjust planner budget defaults",
        "role": "implementer",
        "budget": 0.3
    }
}
```
"""

        event = SimpleNamespace(
            id="evt-complete",
            type="agent.job.completed",
            data={"summary": summary, "cost": 0.45},
            ts=datetime.now(timezone.utc),
        )

        # Handle optimizer output
        await supervisor._handle_optimizer_output(job_id, job, event)

        # Should spawn task
        assert supervisor.client.emit.called


class TestReviewProposalTriggerConversion:
    """Test review_proposal_to_trigger produces valid TriggerData."""

    def test_full_proposal_converts_to_valid_trigger(self):
        """Full proposal with task_template converts to valid TriggerData."""
        proposal = ReviewProposal(
            problem_classification=ProblemClassification(
                category=ProblemCategory.BUDGET_ACCURACY,
                severity=SeverityLevel.HIGH,
                summary="Budget variance issue",
            ),
            evidence_events=[
                EvidenceEvent(
                    event_type="observation.budget_variance",
                    task_id="task-123",
                    job_id="job-456",
                    role="planner",
                    key_metric="variance_ratio=0.35",
                ),
            ],
            executable_proposal=ExecutableProposal(
                action_type=ActionType.ADJUST_BUDGET,
                description="Increase planner budget",
                estimated_impact="Reduce variance",
            ),
            task_template=TaskTemplate(
                goal="Fix planner budget estimation",
                role="implementer",
                budget=0.5,
                repo="https://github.com/org/yoitsu",
                team="backend",
            ),
        )
        trigger_data = review_proposal_to_trigger(proposal)
        data = TriggerData.model_validate(trigger_data)

        assert data.goal == "Fix planner budget estimation"
        assert data.role == "implementer"
        assert data.budget == 0.5
        assert data.repo == "https://github.com/org/yoitsu"
        assert data.team == "backend"
        assert data.params.get("source_review") is True
        assert len(data.params.get("evidence_summary", [])) == 1
```

**Step 2: 运行测试验证失败**

Run: `cd trenni && python3 -m pytest tests/test_optimizer_output.py -v`
Expected: FAIL - `_handle_optimizer_output` method not implemented yet

**Step 3: 实现代码后验证测试通过**

Run: `cd trenni && python3 -m pytest tests/test_optimizer_output.py -v`
Expected: All tests PASS

---

## Task 3: 端到端 smoke 测试

**Files:**
- Modify: `trenni/tests/test_optimizer_output.py` (添加端到端测试)

**Step 1: 添加端到端测试类**

在 `test_optimizer_output.py` 末尾添加：

```python
class TestEndToEndOptimizationLoop:
    """End-to-end smoke test for autonomous optimization loop."""

    @pytest.mark.asyncio
    async def test_threshold_to_optimizer_to_optimization_task(self):
        """Complete loop: observation_threshold -> optimizer -> proposal -> optimization task.

        This test simulates the full autonomous review loop:
        1. observation_threshold event triggers optimizer task
        2. optimizer job completes with ReviewProposal JSON
        3. proposal parsed and converted to optimization trigger
        4. optimization task spawned
        """
        from trenni.supervisor import Supervisor
        from trenni.config import TrenniConfig
        from yoitsu_contracts.external_events import (
            ObservationThresholdEvent,
            observation_threshold_to_trigger,
        )

        config = TrenniConfig()
        supervisor = Supervisor(config)
        supervisor.client = AsyncMock()

        # Step 1: Observation threshold event
        threshold_event = ObservationThresholdEvent(
            metric_type="budget_variance",
            threshold=0.3,
            current_value=0.45,
            role="planner",
            team="default",
            budget=0.5,
            window_hours=24,
        )

        threshold_trigger = observation_threshold_to_trigger(threshold_event)

        # Create synthetic threshold event
        event = SimpleNamespace(
            id="evt-threshold-001",
            source_id=config.source_id,
            type="external.event",
            data={
                "event_type": "observation_threshold",
                **threshold_event.model_dump(),
            },
            ts=datetime.now(timezone.utc),
        )

        # Process threshold trigger
        trigger_data = TriggerData.model_validate(threshold_trigger)
        await supervisor._process_trigger(event, trigger_data, replay=False)

        # Verify optimizer task was spawned
        # Find the optimizer job in state
        optimizer_jobs = [
            j for j in supervisor.state.jobs_by_id.values()
            if j.role == "optimizer"
        ]
        assert len(optimizer_jobs) >= 1, "Optimizer task should be spawned"

        optimizer_job = optimizer_jobs[0]

        # Step 2: Simulate optimizer job completion with proposal
        proposal = ReviewProposal(
            problem_classification=ProblemClassification(
                category=ProblemCategory.BUDGET_ACCURACY,
                severity=SeverityLevel.HIGH,
                summary=f"Budget variance {threshold_event.current_value} exceeds threshold {threshold_event.threshold}",
            ),
            executable_proposal=ExecutableProposal(
                action_type=ActionType.ADJUST_BUDGET,
                description="Increase planner budget by 20%",
                estimated_impact="Reduce variance to below threshold",
            ),
            task_template=TaskTemplate(
                goal="Adjust planner budget estimation parameters",
                role="implementer",
                budget=0.3,
                team="default",
            ),
        )

        completion_event = SimpleNamespace(
            id="evt-optimizer-complete",
            type="agent.job.completed",
            data={
                "summary": proposal.model_dump_json(),
                "cost": 0.45,
            },
            ts=datetime.now(timezone.utc),
        )

        # Handle optimizer output
        await supervisor._handle_optimizer_output(
            optimizer_job.job_id,
            optimizer_job,
            completion_event,
        )

        # Step 3: Verify optimization task was spawned from proposal
        # Find implementer jobs spawned after optimizer
        implementer_jobs = [
            j for j in supervisor.state.jobs_by_id.values()
            if j.role == "implementer" and j.source_event_id.endswith("-proposal")
        ]
        assert len(implementer_jobs) >= 1, "Optimization implementer task should be spawned"

        # Verify the implementer task has correct goal
        implementer_job = implementer_jobs[0]
        assert "budget" in implementer_job.goal.lower()
        assert implementer_job.team == "default"
```

**Step 2: 运行端到端测试**

Run: `cd trenni && python3 -m pytest tests/test_optimizer_output.py::TestEndToEndOptimizationLoop -v`
Expected: PASS after implementation complete

---

## Task 4: 更新 TODO.md 并运行全部测试

**Files:**
- Modify: `TODO.md`

**Step 1: 更新 TODO.md**

添加完成记录：

```markdown
### Autonomous Review Loop Output Closure (ADR-0010)
- [x] optimizer 输出在 job 完成后被消费
- [x] ReviewProposal.from_json_str() 在主链中被调用
- [x] review_proposal_to_trigger() 在主链中被调用
- [x] 解析失败不污染正常任务流
- [x] 端到端 smoke 测试通过
```

**Step 2: 运行全部测试**

Run: `cd /home/holo/yoitsu && python3 -m pytest yoitsu-contracts/tests/ trenni/tests/ palimpsest/tests/ -q`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add trenni/trenni/supervisor.py trenni/tests/test_optimizer_output.py docs/plans/2026-04-04-autonomous-review-loop-output-closure.md
git commit -m "feat(trenni): complete autonomous review loop output closure (ADR-0010)

- Add _handle_optimizer_output method to parse ReviewProposal from optimizer job output
- Convert proposal to TriggerData and spawn optimization task
- Unit tests for optimizer output handling
- End-to-end smoke test for threshold->optimizer->proposal->optimization loop
"
```

---

## Verification Summary

验收标准：
- [x] optimizer 输出有唯一消费点 (_handle_job_done)
- [x] ReviewProposal.from_json_str() 被主链实际调用
- [x] review_proposal_to_trigger() 被主链实际调用
- [x] 成功解析会生成后续优化任务
- [x] 失败解析不会污染正常任务流
- [x] 至少一条端到端 smoke 通过