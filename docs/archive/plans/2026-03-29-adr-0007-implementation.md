# ADR-0007 Task/Job Information Boundary Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the information boundary defined in ADR-0007: goal/budget as task semantics with single channel, execution config derived only from role definition, spawn payload simplified to first-class fields.

**Architecture:** Three-layer change: (1) yoitsu-contracts defines new data structures and RoleMetadataReader, (2) Trenni uses new spawn schema and single-channel budget/goal, (3) Palimpsest receives goal as explicit argument and role_params only for role-internal flags.

**Tech Stack:** Python, Pydantic, dataclasses, AST scanning for role metadata

---

## Task 1: RoleMetadataReader in yoitsu-contracts

**Files:**
- Create: `yoitsu-contracts/src/yoitsu_contracts/role_metadata.py`
- Modify: `yoitsu-contracts/src/yoitsu_contracts/__init__.py`
- Test: `yoitsu-contracts/tests/test_role_metadata.py`

**Step 1: Write the failing test**

```python
# yoitsu-contracts/tests/test_role_metadata.py
import tempfile
from pathlib import Path
from yoitsu_contracts.role_metadata import RoleMetadataReader, RoleMetadata

def test_read_role_metadata():
    """RoleMetadataReader extracts @role decorator info without executing module."""
    with tempfile.TemporaryDirectory() as tmpdir:
        roles_dir = Path(tmpdir) / "roles"
        roles_dir.mkdir()
        role_file = roles_dir / "worker.py"
        role_file.write_text('''
from palimpsest.runtime import role

@role(
    name="worker",
    description="Does work",
    teams=["default"],
    role_type="worker",
    min_cost=0.10,
    recommended_cost=0.50,
    min_capability="reasoning_low",
)
def worker_role(**params):
    pass
''')
        reader = RoleMetadataReader(roles_dir.parent)
        definitions = reader.list_definitions()
        assert len(definitions) == 1
        meta = definitions[0]
        assert meta.name == "worker"
        assert meta.min_cost == 0.10

def test_non_literal_decorator_raises():
    """Computed decorator expressions raise ValueError at scan time."""
    with tempfile.TemporaryDirectory() as tmpdir:
        roles_dir = Path(tmpdir) / "roles"
        roles_dir.mkdir()
        role_file = roles_dir / "bad.py"
        role_file.write_text('''
BASE = 0.10
from palimpsest.runtime import role

@role(name="bad", description="bad", min_cost=BASE * 1.5)
def bad_role(**params):
    pass
''')
        reader = RoleMetadataReader(roles_dir.parent)
        try:
            reader.list_definitions()
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "literal" in str(e).lower() or "min_cost" in str(e)
```

**Step 2: Run test to verify it fails**

Run: `cd /home/holo/yoitsu/yoitsu-contracts && pytest tests/test_role_metadata.py -v`
Expected: FAIL with "module 'yoitsu_contracts' has no attribute 'role_metadata'"

**Step 3: Write minimal implementation**

```python
# yoitsu-contracts/src/yoitsu_contracts/role_metadata.py
"""RoleMetadataReader — AST-based role metadata extraction without module execution."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import ast


@dataclass
class RoleMetadata:
    name: str
    description: str
    teams: list[str] = field(default_factory=lambda: ["default"])
    role_type: str = "worker"
    min_cost: float = 0.0
    recommended_cost: float = 0.0
    min_capability: str = ""


class RoleMetadataReader:
    """Reads @role decorator metadata from evo/roles/*.py using AST scanning.
    
    Does not execute modules. Produces RoleMetadata instances.
    Importable by both Trenni and Palimpsest without triggering role module execution.
    
    Constraint: @role decorator arguments must be constant expressions (string/numeric literals).
    Non-literal expressions raise ValueError at scan time.
    """
    
    def __init__(self, evo_root: Path | str) -> None:
        self._root = Path(evo_root)
        self._cache: list[RoleMetadata] | None = None
    
    def list_definitions(self) -> list[RoleMetadata]:
        if self._cache is not None:
            return list(self._cache)
        
        roles_dir = self._root / "roles"
        if not roles_dir.exists():
            return []
        
        result: list[RoleMetadata] = []
        for py_path in sorted(roles_dir.glob("*.py")):
            if py_path.name.startswith("_"):
                continue
            meta = self._read_role_file(py_path)
            if meta:
                result.append(meta)
        
        self._cache = result
        return result
    
    def get_definition(self, name: str) -> RoleMetadata | None:
        for meta in self.list_definitions():
            if meta.name == name:
                return meta
        return None
    
    def invalidate_cache(self) -> None:
        self._cache = None
    
    def _read_role_file(self, py_path: Path) -> RoleMetadata | None:
        source = py_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Call):
                        if self._is_role_decorator(decorator):
                            return self._extract_metadata(decorator, py_path)
        return None
    
    def _is_role_decorator(self, decorator: ast.Call) -> bool:
        """Check if decorator call is @role(...)."""
        if isinstance(decorator.func, ast.Name):
            return decorator.func.id == "role"
        return False
    
    def _extract_metadata(self, decorator: ast.Call, py_path: Path) -> RoleMetadata:
        """Extract RoleMetadata from @role(...) decorator keywords."""
        kwargs: dict[str, Any] = {}
        
        for keyword in decorator.keywords:
            try:
                value = ast.literal_eval(keyword.value)
            except ValueError as e:
                raise ValueError(
                    f"Role decorator argument '{keyword.arg}' in {py_path} "
                    f"must be a literal expression. Got non-literal: {ast.unparse(keyword.value)}. "
                    f"Error: {e}"
                ) from e
            kwargs[keyword.arg] = value
        
        return RoleMetadata(
            name=str(kwargs.get("name", "")),
            description=str(kwargs.get("description", "")),
            teams=list(kwargs.get("teams", ["default"])),
            role_type=str(kwargs.get("role_type", "worker")),
            min_cost=float(kwargs.get("min_cost", 0.0)),
            recommended_cost=float(kwargs.get("recommended_cost", 0.0)),
            min_capability=str(kwargs.get("min_capability", "")),
        )
```

**Step 4: Update __init__.py**

```python
# yoitsu-contracts/src/yoitsu_contracts/__init__.py
from .role_metadata import RoleMetadata, RoleMetadataReader

__all__ = [
    "RoleMetadata",
    "RoleMetadataReader",
]
```

**Step 5: Run test to verify it passes**

Run: `cd /home/holo/yoitsu/yoitsu-contracts && pytest tests/test_role_metadata.py -v`
Expected: PASS

**Step 6: Commit**

```bash
cd /home/holo/yoitsu/yoitsu-contracts && git add src/yoitsu_contracts/role_metadata.py src/yoitsu_contracts/__init__.py tests/test_role_metadata.py && git commit -m "feat: add RoleMetadataReader for AST-based role metadata extraction"
```

---

## Task 2: Update SpawnTaskData schema (remove params, add first-class fields)

**Files:**
- Modify: `yoitsu-contracts/src/yoitsu_contracts/events.py`
- Test: `yoitsu-contracts/tests/test_spawn_schema.py`

**Step 1: Write the failing test**

```python
# yoitsu-contracts/tests/test_spawn_schema.py
from yoitsu_contracts.events import SpawnTaskData

def test_spawn_task_data_has_first_class_fields():
    """goal, budget, repo are first-class fields, not in params."""
    task = SpawnTaskData(
        goal="Implement OAuth",
        role="implementer",
        budget=0.80,
        repo="https://github.com/org/repo",
        eval_spec=None,
    )
    assert task.goal == "Implement OAuth"
    assert task.budget == 0.80
    assert task.repo == "https://github.com/org/repo"
    assert task.params == {}  # params still exists but empty/optional

def test_spawn_task_data_repo_optional():
    """repo is optional for repoless jobs."""
    task = SpawnTaskData(
        goal="Evaluate results",
        role="evaluator",
    )
    assert task.repo == ""
```

**Step 2: Run test to verify it fails**

Run: `cd /home/holo/yoitsu/yoitsu-contracts && pytest tests/test_spawn_schema.py -v`
Expected: FAIL with "SpawnTaskData has no field 'repo'"

**Step 3: Modify events.py SpawnTaskData**

Find the existing `SpawnTaskData` class and replace:

```python
# OLD (in events.py):
class SpawnTaskData(BaseModel):
    prompt: str = ""
    goal: str = ""
    role: str = ""
    budget: float = 0.0
    sha: str | None = None
    params: dict = Field(default_factory=dict)
    eval_spec: EvalSpec | None = None

# NEW:
class SpawnTaskData(BaseModel):
    goal: str = ""
    role: str = ""
    budget: float = 0.0
    repo: str = ""  # optional; omit for repoless jobs
    sha: str | None = None
    params: dict = Field(default_factory=dict)  # retained for role-internal params only
    eval_spec: EvalSpec | None = None

    # Legacy field for backward compatibility during migration
    prompt: str = ""  # deprecated; use goal instead
```

**Step 4: Run test to verify it passes**

Run: `cd /home/holo/yoitsu/yoitsu-contracts && pytest tests/test_spawn_schema.py -v`
Expected: PASS

**Step 5: Commit**

```bash
cd /home/holo/yoitsu/yoitsu-contracts && git add src/yoitsu_contracts/events.py tests/test_spawn_schema.py && git commit -m "feat: SpawnTaskData now has goal/budget/repo as first-class fields"
```

---

## Task 3: Remove overrides from SpawnedJob and SpawnDefaults

**Files:**
- Modify: `trenni/trenni/state.py`
- Test: `trenni/tests/test_state_structures.py`

**Step 1: Write the failing test**

```python
# trenni/tests/test_state_structures.py
from trenni.state import SpawnedJob, SpawnDefaults

def test_spawned_job_no_execution_overrides():
    """SpawnedJob must not carry execution config overrides."""
    job = SpawnedJob(
        job_id="test-123",
        source_event_id="evt-1",
        task="Do something",
        role="implementer",
        repo="https://github.com/org/repo",
        init_branch="main",
        evo_sha="abc123",
        task_id="task-1",
        team="default",
    )
    # These fields should not exist
    assert not hasattr(job, "llm_overrides") or job.llm_overrides == {}
    assert not hasattr(job, "workspace_overrides") or job.workspace_overrides == {}
    assert not hasattr(job, "publication_overrides") or job.publication_overrides == {}

def test_spawn_defaults_no_execution_overrides():
    """SpawnDefaults must not carry execution config overrides."""
    defaults = SpawnDefaults(
        repo="https://github.com/org/repo",
        init_branch="main",
        role="implementer",
        evo_sha="abc123",
        team="default",
    )
    assert not hasattr(defaults, "llm_overrides") or defaults.llm_overrides == {}
```

**Step 2: Run test to verify it fails**

Run: `cd /home/holo/yoitsu/trenni && pytest tests/test_state_structures.py -v`
Expected: FAIL (fields still exist with dict default)

**Step 3: Modify state.py**

Replace SpawnedJob dataclass:

```python
# OLD SpawnedJob:
@dataclass
class SpawnedJob:
    job_id: str
    source_event_id: str
    task: str
    role: str
    repo: str
    init_branch: str
    evo_sha: str | None
    role_params: dict[str, Any] = field(default_factory=dict)
    llm_overrides: dict[str, Any] = field(default_factory=dict)
    workspace_overrides: dict[str, Any] = field(default_factory=dict)
    publication_overrides: dict[str, Any] = field(default_factory=dict)
    ...

# NEW SpawnedJob:
@dataclass
class SpawnedJob:
    job_id: str
    source_event_id: str
    task: str
    role: str
    repo: str
    init_branch: str
    evo_sha: str | None
    role_params: dict[str, Any] = field(default_factory=dict)  # only role-internal flags
    depends_on: frozenset[str] = field(default_factory=frozenset)
    task_id: str = ""
    condition: Condition | None = None
    job_context: JobContextConfig = field(default_factory=JobContextConfig)
    parent_job_id: str = ""
    team: str = "default"
    # REMOVED: llm_overrides, workspace_overrides, publication_overrides
```

Replace SpawnDefaults dataclass similarly.

**Step 4: Run test to verify it passes**

Run: `cd /home/holo/yoitsu/trenni && pytest tests/test_state_structures.py -v`
Expected: PASS

**Step 5: Commit**

```bash
cd /home/holo/yoitsu/trenni && git add trenni/state.py tests/test_state_structures.py && git commit -m "refactor: remove execution config overrides from SpawnedJob/SpawnDefaults"
```

---

## Task 4: Update spawn_handler.py for new schema

**Files:**
- Modify: `trenni/trenni/spawn_handler.py`

**Step 1: Write test for new spawn behavior**

```python
# trenni/tests/test_spawn_handler.py (add to existing or new file)
from trenni.spawn_handler import SpawnHandler
from trenni.state import SupervisorState
from yoitsu_contracts.events import SpawnRequestData, SpawnTaskData

def test_spawn_handler_goal_not_in_role_params():
    """goal must not be written to role_params."""
    state = SupervisorState()
    handler = SpawnHandler(state)
    
    payload = SpawnRequestData(
        job_id="parent-1",
        tasks=[
            SpawnTaskData(goal="Implement X", role="worker", budget=0.50),
        ],
    )
    event = type("Event", (), {"id": "evt-1", "data": payload.model_dump()})()
    
    plan = handler.expand(event)
    assert len(plan.jobs) == 2  # child + join
    child_job = plan.jobs[0]
    assert child_job.task == "Implement X"
    assert "goal" not in child_job.role_params  # goal is NOT in role_params
```

**Step 2: Modify spawn_handler.py**

Key changes:
- Remove `role_params.setdefault("goal", prompt)`
- Remove `role_params.setdefault("budget", ...)`
- Remove llm/workspace/publication overrides construction and inheritance
- budget goes directly to nowhere (handled by runtime_builder from SpawnedJob.task)

The critical section to modify:

```python
# OLD:
for index, child in enumerate(payload.tasks):
    prompt = (child.goal or child.prompt).strip()
    ...
    role_params = dict(child.params or {})
    role_params.setdefault("goal", prompt)
    if child.budget:
        role_params.setdefault("budget", float(child.budget))
    ...
    llm = dict(self._inherit("llm_overrides", parent_job, parent_defaults, {}))
    if child.budget:
        llm["max_total_cost"] = float(child.budget)

# NEW:
for index, child in enumerate(payload.tasks):
    goal = (child.goal or child.prompt).strip()
    ...
    role_params = dict(child.params or {})  # only role-internal flags
    # goal and budget NOT written to role_params
    ...
    # llm/workspace/publication overrides REMOVED entirely
```

**Step 3: Update join job creation**

```python
# OLD:
join_role_params = dict(parent_job.role_params)
join_role_params["goal"] = join_task
join_role_params["parent_goal"] = parent_job.task
join_role_params["mode"] = "join"

# NEW:
join_role_params = {"mode": "join"}  # only role-internal flag
# parent_goal goes to JobContextConfig.join.parent_summary (already done)
```

**Step 4: Run tests**

Run: `cd /home/holo/yoitsu/trenni && pytest tests/test_spawn_handler.py tests/test_supervisor_queue.py -v`
Expected: Some failures to fix incrementally

**Step 5: Fix any test failures**

Iterate on spawn_handler changes until tests pass.

**Step 6: Commit**

```bash
cd /home/holo/yoitsu/trenni && git add trenni/spawn_handler.py tests/ && git commit -m "refactor: spawn_handler uses new schema, goal/budget not in role_params"
```

---

## Task 5: Update runtime_builder.py for single-channel budget

**Files:**
- Modify: `trenni/trenni/runtime_builder.py`

**Step 1: Modify RuntimeSpecBuilder.build()**

Remove override parameters:

```python
# OLD signature:
def build(
    self,
    *,
    job_id: str,
    ...
    llm_overrides: dict | None = None,
    workspace_overrides: dict | None = None,
    publication_overrides: dict | None = None,
    ...

# NEW signature:
def build(
    self,
    *,
    job_id: str,
    task_id: str | None = None,
    source_event_id: str,
    task: str,
    role: str,
    role_params: dict | None = None,  # only role-internal flags
    team: str = "default",
    repo: str,
    init_branch: str,
    evo_sha: str | None,
    budget: float | None = None,  # NEW: explicit budget from spawn
    job_context: JobContextConfig | None = None,
) -> JobRuntimeSpec:
```

Update the body:

```python
# Budget handling:
llm_config = dict(self.config.default_llm)
if budget is not None and budget > 0:
    llm_config["max_total_cost"] = budget
# else: use default from TrenniConfig.default_llm

# Workspace handling:
merged_workspace = {
    **self.config.default_workspace,
    "repo": repo,
    "init_branch": init_branch,
}
# No workspace_overrides

# Publication handling:
publication_config = dict(self.config.default_publication)
# No publication_overrides
```

**Step 2: Update callers**

Update supervisor.py or scheduler.py to pass budget from SpawnedJob.

**Step 3: Commit**

```bash
cd /home/holo/yoitsu/trenni && git add trenni/runtime_builder.py && git commit -m "refactor: runtime_builder single-channel budget, no execution overrides"
```

---

## Task 6: Add role catalog cache invalidation in Trenni

**Files:**
- Modify: `trenni/trenni/supervisor.py` or create new file for catalog management
- Modify: `trenni/trenni/spawn_handler.py`

**Step 1: Add git SHA check before spawn expansion**

```python
# In spawn_handler.py or supervisor.py:
import subprocess

class RoleCatalog:
    def __init__(self, evo_root: Path, reader: RoleMetadataReader):
        self._evo_root = evo_root
        self._reader = reader
        self._cached_sha: str | None = None
    
    def refresh_if_needed(self) -> list[RoleMetadata]:
        current_sha = self._read_head_sha()
        if current_sha != self._cached_sha:
            self._reader.invalidate_cache()
            self._cached_sha = current_sha
        return self._reader.list_definitions()
    
    def _read_head_sha(self) -> str:
        try:
            result = subprocess.run(
                ["git", "-C", str(self._evo_root), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()
        except Exception:
            return ""
```

**Step 2: Use before spawn expansion**

Call `catalog.refresh_if_needed()` before processing spawn events.

**Step 3: Commit**

```bash
cd /home/holo/yoitsu/trenni && git add trenni/role_catalog.py trenni/spawn_handler.py && git commit -m "feat: role catalog cache invalidation on evo SHA change"
```

---

## Task 7: Update Palimpsest RoleManager to extend RoleMetadataReader

**Files:**
- Modify: `palimpsest/palimpsest/runtime/roles.py`

**Step 1: Import RoleMetadataReader from contracts**

```python
from yoitsu_contracts import RoleMetadataReader, RoleMetadata
```

**Step 2: Make RoleManager extend RoleMetadataReader**

```python
# OLD:
class RoleManager:
    def __init__(self, evo_root: str | Path):
        self._root = Path(evo_root)

# NEW:
class RoleManager(RoleMetadataReader):
    """Extends RoleMetadataReader with resolve() for full JobSpec execution."""
    
    def __init__(self, evo_root: str | Path) -> None:
        super().__init__(evo_root)
    
    def resolve(self, role_name: str, **params: Any) -> JobSpec:
        """Load and execute role module to produce JobSpec."""
        func = self._load_role_function(role_name)
        ...
```

Move `list_definitions()` and `get_definition()` to inherit from RoleMetadataReader. Keep only `resolve()` and `_load_role_module()` in RoleManager.

**Step 3: Remove duplicate RoleMetadata dataclass**

RoleMetadata is now in yoitsu_contracts. Import it instead of defining locally.

**Step 4: Update tests**

Run: `cd /home/holo/yoitsu/palimpsest && pytest tests/test_roles.py -v`

**Step 5: Commit**

```bash
cd /home/holo/yoitsu/palimpsest && git add palimpsest/runtime/roles.py tests/test_roles.py && git commit -m "refactor: RoleManager extends RoleMetadataReader from yoitsu-contracts"
```

---

## Task 8: Update Palimpsest runner.py for explicit goal parameter

**Files:**
- Modify: `palimpsest/palimpsest/runner.py`

**Step 1: Remove goal from role_params fallback**

```python
# OLD:
role_params = dict(config.role_params or {})
role_params.setdefault("goal", config.task)
role_params.setdefault("repo", config.workspace.repo)

# NEW:
role_params = dict(config.role_params or {})
# goal is config.task, passed explicitly
# repo is config.workspace.repo, passed via workspace_cfg
```

**Step 2: Pass goal explicitly to context_fn**

```python
# OLD:
context_spec = spec.context_fn(
    workspace=workspace,
    job_id=job_id,
    task=config.task,
    job_config=config,
    evo_root=str(evo_path),
    **role_params,
)

# NEW:
context_spec = spec.context_fn(
    workspace=workspace,
    job_id=job_id,
    goal=config.task,  # explicit goal parameter
    job_config=config,
    evo_root=str(evo_path),
    **role_params,  # only role-internal flags
)
```

**Step 3: Update publication_fn call**

```python
# goal is already passed as explicit parameter, ensure it's not in role_params
git_ref = spec.publication_fn(
    result=result,
    workspace_path=workspace,
    job_id=job_id,
    task_id=config.task_id or job_id,
    goal=config.task,  # explicit
    ...
)
```

**Step 4: Run tests**

Run: `cd /home/holo/yoitsu/palimpsest && pytest tests/test_runner_runtime_events.py -v`

**Step 5: Commit**

```bash
cd /home/holo/yoitsu/palimpsest && git add palimpsest/runner.py && git commit -m "refactor: runner passes goal explicitly, not via role_params"
```

---

## Task 9: Update evo roles context_fn signatures

**Files:**
- Modify: `palimpsest/evo/roles/implementer.py`
- Modify: `palimpsest/evo/roles/planner.py`
- Modify: `palimpsest/evo/roles/default.py`
- Modify: `palimpsest/evo/roles/evaluator.py`
- Modify: `palimpsest/evo/roles/reviewer.py`

**Step 1: Update context_spec helper**

```python
# In roles.py (palimpsest/runtime/roles.py):
def context_spec(
    system: str,
    sections: list[dict[str, Any]],
) -> Callable[..., dict]:
    def fn(*, goal: str = "", task: str = "", **params: Any) -> dict:
        # goal is explicit parameter; task is alias for compatibility
        effective_goal = goal or task
        return {
            "system": system,
            "sections": list(sections),
            "task": effective_goal,
        }
    return fn
```

**Step 2: Verify roles work**

The `**params` signature already handles this. Roles using `context_spec(...)` will work unchanged since `goal` and `task` are passed.

**Step 3: Commit**

```bash
cd /home/holo/yoitsu/palimpsest && git add evo/roles/*.py && git commit -m "refactor: context_spec accepts explicit goal parameter"
```

---

## Task 10: Update JobConfig schema documentation

**Files:**
- Modify: `yoitsu-contracts/src/yoitsu_contracts/config.py`

**Step 1: Add docstrings clarifying field categories**

```python
class JobConfig(BaseModel):
    """Complete job configuration passed from Trenni to Palimpsest.
    
    Field categories per ADR-0007:
    - Task semantics (from spawn payload): task, task_id, team
    - Execution config (derived from role): role, llm.*, workspace.*, publication.*
    - Runtime identity (assigned by Trenni): job_id, evo_sha, eventstore
    - Role-internal behavior: role_params (only flags like mode="join")
    """
    
    job_id: str = ""  # Runtime identity
    task_id: str = ""  # Task semantics (reference)
    task: str = ""  # Task semantics — authoritative goal text
    evo_sha: str = ""  # Runtime identity
    role: str = "default"  # Task semantics — role selection key
    role_params: dict = Field(default_factory=dict)  # Role-internal flags only
    team: str = "default"  # Task semantics (inherited)
    ...
```

**Step 2: Commit**

```bash
cd /home/holo/yoitsu/yoitsu-contracts && git add src/yoitsu_contracts/config.py && git commit -m "docs: JobConfig field category documentation per ADR-0007"
```

---

## Task 11: Full test suite verification

**Files:**
- Run all tests across all packages

**Step 1: Run yoitsu-contracts tests**

```bash
cd /home/holo/yoitsu/yoitsu-contracts && pytest tests/ -v
```

**Step 2: Run Trenni tests**

```bash
cd /home/holo/yoitsu/trenni && pytest tests/ -v
```

**Step 3: Run Palimpsest tests**

```bash
cd /home/holo/yoitsu/palimpsest && pytest tests/ -v
```

**Step 4: Fix any remaining failures**

Address any integration issues.

**Step 5: Commit any fixes**

---

## Task 12: Update ADR-0007 status

**Files:**
- Modify: `docs/adr/0007-task-job-boundary.md`

**Step 1: Change status from Proposed to Accepted**

```markdown
- Status: Accepted
```

**Step 2: Commit**

```bash
cd /home/holo/yoitsu && git add docs/adr/0007-task-job-boundary.md && git commit -m "docs: ADR-0007 status changed to Accepted after implementation"
```

---

## Summary

| Task | Component | Key Change |
|------|-----------|------------|
| 1 | yoitsu-contracts | RoleMetadataReader (AST-based) |
| 2 | yoitsu-contracts | SpawnTaskData first-class fields |
| 3 | trenni | Remove SpawnedJob overrides |
| 4 | trenni | spawn_handler new schema |
| 5 | trenni | runtime_builder single-channel budget |
| 6 | trenni | Role catalog cache invalidation |
| 7 | palimpsest | RoleManager extends RoleMetadataReader |
| 8 | palimpsest | runner explicit goal parameter |
| 9 | palimpsest | context_fn signature update |
| 10 | yoitsu-contracts | JobConfig documentation |
| 11 | all | Test suite verification |
| 12 | docs | ADR status Accepted |