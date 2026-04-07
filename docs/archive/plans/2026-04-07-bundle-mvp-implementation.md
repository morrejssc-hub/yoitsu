# Bundle MVP Implementation Plan

> **REQUIRED SUB-SKILL:** Use the executing-plans skill to implement this plan task-by-task.

**Goal:** Delete `team` semantics from trenni's control-plane, replacing with minimal `(bundle, role)` lookup. Flatten evo directory layout from `evo/teams/<team>/` to `evo/<bundle>/`. Remove global layer and role categorization.

**Architecture:** Breaking change with no backwards compatibility. Bundle is a directory under `evo/` that owns its own roles, tools, contexts, prompts, and lib. Trenni's only business entry point is `(bundle, role)` → load and run. No topology validation, no automatic routing.

**Tech Stack:** Python packages: trenni, palimpsest, yoitsu-contracts, evo directory

---

## Phase 1: Archive and Cleanup (Preparation)

### Task 1: Archive conflicting plans

**TDD scenario:** Trivial change — file moves only

**Files:**
- Move: `docs/plans/2026-04-06-evo-team-isolation.md` → `docs/archive/plans/`
- Move: `docs/plans/2026-04-06-multi-bundle-evo-phase2.md` → `docs/archive/plans/`

**Step 1: Create archive directory if needed**

```bash
mkdir -p docs/archive/plans
```

**Step 2: Move the files**

```bash
git mv docs/plans/2026-04-06-evo-team-isolation.md docs/archive/plans/
git mv docs/plans/2026-04-06-multi-bundle-evo-phase2.md docs/archive/plans/
```

**Step 3: Commit**

```bash
git commit -m "docs: archive superseded team/bundle plans"
```

---

## Phase 2: Flatten evo Directory Layout

### Task 2: Move factorio bundle from teams wrapper to top-level

**TDD scenario:** Trivial change — directory restructuring

**Files:**
- Move: `evo/teams/factorio/` → `evo/factorio/`
- Delete: `evo/teams/` (after move)
- Create: `evo/factorio/__init__.py` (new)

**Step 1: Create target directory and move contents**

```bash
mkdir -p evo/factorio
git mv evo/teams/factorio/* evo/factorio/
```

**Step 2: Add __init__.py for package imports**

```python
# evo/factorio/__init__.py
"""Factorio bundle — self-contained evolution subtree."""
```

**Step 3: Remove empty teams wrapper**

```bash
rm -rf evo/teams
git add evo/factorio/__init__.py
git add -A evo/teams  # records deletion
```

**Step 4: Verify layout**

```bash
ls -la evo/factorio/
# Expected: contexts/, lib/, prompts/, roles/, scripts/, tools/, __init__.py
```

**Step 5: Commit**

```bash
git commit -m "refactor(evo): flatten factorio bundle to evo/factorio/"
```

---

### Task 3: Create evolved/ directory in factorio bundle

**TDD scenario:** Trivial change — directory creation

**Files:**
- Create: `evo/factorio/evolved/`
- Create: `evo/factorio/evolved/scripts/`
- Create: `evo/factorio/evolved/.gitkeep`

**Step 1: Create evolved directory structure**

```bash
mkdir -p evo/factorio/evolved/scripts
touch evo/factorio/evolved/scripts/.gitkeep
```

**Step 2: Commit**

```bash
git add evo/factorio/evolved/
git commit -m "feat(evo): add evolved/ agent-write surface for factorio bundle"
```

---

## Phase 3: Delete Global evo Layer

### Task 4: Delete global evo layer directories

**TDD scenario:** Trivial change — file deletions

**Files:**
- Delete: `evo/roles/` (global)
- Delete: `evo/tools/` (if exists)
- Delete: `evo/contexts/` (if exists)
- Delete: `evo/prompts/` (global)

**Step 1: Remove global roles directory**

```bash
rm -rf evo/roles
git add -A evo/roles
```

**Step 2: Remove global prompts directory**

```bash
rm -rf evo/prompts
git add -A evo/prompts
```

**Step 3: Check and remove other global dirs if they exist**

```bash
ls evo/  # Should only show: factorio/, evolved/ (after Task 5)
rm -rf evo/tools evo/contexts 2>/dev/null || true
```

**Step 4: Commit**

```bash
git commit -m "refactor(evo): delete global roles/prompts layer"
```

---

## Phase 4: Update Python Imports (team → bundle semantics)

### Task 5: Update factorio role imports to use flattened path

**TDD scenario:** Modifying tested code — run existing tests first

**Files:**
- Modify: `evo/factorio/roles/worker.py` (imports)
- Modify: `evo/factorio/roles/implementer.py` (imports)

**Step 1: Read current worker.py imports**

Run: `cat evo/factorio/roles/worker.py | head -30`
Identify any `teams.factorio` imports.

**Step 2: Update imports in worker.py**

Replace:
```python
from teams.factorio.lib.rcon import ...
```

With:
```python
from factorio.lib.rcon import ...
```

**Step 3: Update imports in implementer.py**

Same pattern: `teams.factorio.` → `factorio.`

**Step 4: Verify no teams imports remain**

```bash
grep -r "teams\.factorio" evo/factorio/ || echo "No teams imports found"
```

**Step 5: Commit**

```bash
git add evo/factorio/roles/*.py
git commit -m "refactor(evo): update factorio role imports to flattened path"
```

---

### Task 6: Update context and tool imports in factorio bundle

**TDD scenario:** Modifying tested code

**Files:**
- Modify: `evo/factorio/contexts/factorio_scripts.py`
- Modify: `evo/factorio/tools/factorio_call_script.py`

**Step 1: Check imports in contexts**

```bash
grep -n "from teams\|import teams" evo/factorio/contexts/*.py
```

**Step 2: Check imports in tools**

```bash
grep -n "from teams\|import teams" evo/factorio/tools/*.py
```

**Step 3: Update imports**

Replace `teams.factorio.` with `factorio.` in all found locations.

**Step 4: Commit**

```bash
git add evo/factorio/contexts/*.py evo/factorio/tools/*.py
git commit -m "refactor(evo): update factorio context/tool imports"
```

---

## Phase 5: Rename team → bundle in yoitsu-contracts

### Task 7: Rename team → bundle in yoitsu-contracts events.py

**TDD scenario:** Modifying tested code — run tests first

**Files:**
- Modify: `yoitsu-contracts/src/yoitsu_contracts/events.py`

**Step 1: Run existing tests**

```bash
cd yoitsu-contracts && pytest tests/ -v
```

**Step 2: Rename field `team` → `bundle` in TriggerData**

Find all occurrences of `team: str` field and rename to `bundle: str`.
Update docstrings accordingly.

Key classes to update:
- `TriggerData`: `team: str = "default"` → `bundle: str = ""`
- `SpawnTaskData`: `team: str` → `bundle: str`
- `SpawnRequestData`: `team` field
- `TaskCreatedData`: `team: str` → `bundle: str`

**Step 3: Update validation logic**

Update `forbidden` sets in model_post_init to include `bundle` instead of `team`.

**Step 4: Run tests to verify**

```bash
pytest tests/ -v
```

**Step 5: Commit**

```bash
git add yoitsu-contracts/src/yoitsu_contracts/events.py
git commit -m "refactor(contracts): rename team → bundle in event payloads"
```

---

### Task 8: Rename team → bundle in yoitsu-contracts config.py

**TDD scenario:** Modifying tested code

**Files:**
- Modify: `yoitsu-contracts/src/yoitsu_contracts/config.py`

**Step 1: Update JobContextConfig**

```python
# Before
team: str = "default"  # Task semantics (inherited)

# After
bundle: str = ""  # Bundle name for artifact loading
```

**Step 2: Run tests**

```bash
pytest tests/ -v
```

**Step 3: Commit**

```bash
git add yoitsu-contracts/src/yoitsu_contracts/config.py
git commit -m "refactor(contracts): rename team → bundle in config"
```

---

### Task 9: Rename team → bundle in other yoitsu-contracts files

**TDD scenario:** Modifying tested code

**Files:**
- Modify: `yoitsu-contracts/src/yoitsu_contracts/external_events.py`
- Modify: `yoitsu-contracts/src/yoitsu_contracts/observation.py`
- Modify: `yoitsu-contracts/src/yoitsu_contracts/review_proposal.py`
- Modify: `yoitsu-contracts/src/yoitsu_contracts/role_metadata.py`

**Step 1: Grep for all team references**

```bash
grep -rn "team" yoitsu-contracts/src/yoitsu_contracts/*.py | grep -v "steam"
```

**Step 2: Update each file**

For each file:
- Rename `team: str` fields to `bundle: str`
- Update docstrings
- Remove teams field from RoleMetadata (it's deprecated per ADR-0011 D3)

**Step 3: Run tests**

```bash
pytest tests/ -v
```

**Step 4: Commit**

```bash
git add yoitsu-contracts/src/yoitsu_contracts/*.py
git commit -m "refactor(contracts): complete team → bundle rename"
```

---

## Phase 6: Update palimpsest Runtime

### Task 10: Update RoleManager to use bundle parameter

**TDD scenario:** Full TDD cycle — new API

**Files:**
- Modify: `palimpsest/palimpsest/runtime/roles.py`
- Modify: `palimpsest/tests/integration/test_adr0011_team_isolation.py` (rename/update)

**Step 1: Write failing test for bundle-based resolution**

```python
# tests/test_role_manager_bundle.py
def test_role_manager_bundle_parameter():
    """RoleManager accepts bundle parameter, not team."""
    from palimpsest.runtime.roles import RoleManager
    
    # Should look in evo/<bundle>/roles/ only
    manager = RoleManager(evo_fixture_path, bundle="factorio")
    
    # Resolve worker role
    spec = manager.resolve("worker")
    assert spec.source_role == "worker"
```

**Step 2: Run test to verify it fails**

```bash
cd palimpsest && pytest tests/test_role_manager_bundle.py -v
# Expected: FAIL (no bundle parameter)
```

**Step 3: Update RoleManager.__init__**

```python
class RoleManager(RoleMetadataReader):
    def __init__(self, evo_root: str | Path, bundle: str = "") -> None:
        super().__init__(evo_root)
        self._bundle = bundle
        self._bundle_roles_dir = self._root / bundle / "roles" if bundle else None
```

**Step 4: Update resolve() method**

Remove two-layer resolution. Now only looks in `evo/<bundle>/roles/<name>.py`.
Missing role → raise FileNotFoundError, no fallback.

```python
def resolve(self, role_name: str, **params: Any) -> JobSpec:
    if not self._bundle:
        raise ValueError("bundle parameter is required")
    func = self._load_role_function(role_name)
    # ... rest unchanged
```

**Step 5: Update _load_role_by_name()**

```python
def _load_role_by_name(self, name: str) -> tuple[Callable[..., JobSpec], RoleMetadata]:
    if not self._bundle_roles_dir:
        raise ValueError("bundle not specified")
    
    bundle_path = self._bundle_roles_dir / f"{name}.py"
    if not bundle_path.exists():
        raise FileNotFoundError(f"Role '{name}' not found in bundle '{self._bundle}'")
    return self._load_role_module(bundle_path, expected_name=name)
```

**Step 6: Run test to verify it passes**

```bash
pytest tests/test_role_manager_bundle.py -v
```

**Step 7: Delete TeamManager class entirely**

Remove `TeamManager` class from roles.py. It's no longer needed.

**Step 8: Delete TeamDefinition dataclass**

Remove `TeamDefinition` from roles.py.

**Step 9: Commit**

```bash
git add palimpsest/palimpsest/runtime/roles.py
git commit -m "refactor(palimpsest): RoleManager uses bundle, removes team layer"
```

---

### Task 11: Update RoleMetadataReader to scan bundle directories only

**TDD scenario:** Modifying tested code

**Files:**
- Modify: `yoitsu-contracts/src/yoitsu_contracts/role_metadata.py`

**Step 1: Update list_definitions() to accept bundle parameter**

The base `RoleMetadataReader` should still support scanning, but the semantics change:
- No global roles directory
- Must specify bundle to scan

**Step 2: Update _read_role_file() path resolution**

No changes needed if bundle path is passed in.

**Step 3: Run tests**

```bash
pytest tests/ -v
```

**Step 4: Commit**

```bash
git add yoitsu-contracts/src/yoitsu_contracts/role_metadata.py
git commit -m "refactor(contracts): RoleMetadataReader bundle-only scanning"
```

---

### Task 12: Update ToolLoader to use bundle parameter

**TDD scenario:** Modifying tested code

**Files:**
- Modify: `palimpsest/palimpsest/runtime/tools.py`

**Step 1: Update resolve_tool_functions()**

```python
def resolve_tool_functions(
    evo_root: str | Path,
    bundle: str,
    requested: list[str],
) -> dict[str, Callable]:
    """Scan evo/<bundle>/tools/ for requested @tool functions.
    
    No global fallback. Missing tool → warning + skip.
    """
    evo_path = Path(evo_root)
    bundle_tools_dir = evo_path / bundle / "tools"
    
    if not bundle_tools_dir.is_dir():
        logger.warning(f"No tools directory for bundle '{bundle}'")
        return {}
    
    # ... scan bundle tools only
```

**Step 2: Update UnifiedToolGateway.__init__**

Change `team` parameter to `bundle`:

```python
def __init__(
    self,
    config: ToolsConfig,
    evo_root: Path,
    bundle: str,  # renamed from team
    requested_evo_tools: list[str],
    ...
):
```

**Step 3: Update tests**

Rename test fixtures and update test imports.

**Step 4: Run tests**

```bash
pytest tests/ -v
```

**Step 5: Commit**

```bash
git add palimpsest/palimpsest/runtime/tools.py
git commit -m "refactor(palimpsest): ToolLoader uses bundle, removes team layer"
```

---

### Task 13: Update ContextLoader to use bundle parameter

**TDD scenario:** Modifying tested code

**Files:**
- Modify: `palimpsest/palimpsest/runtime/contexts.py`
- Modify: `palimpsest/palimpsest/stages/context.py`

**Step 1: Find ContextLoader implementation**

```bash
grep -rn "class.*Context\|def.*context" palimpsest/palimpsest/runtime/*.py
```

**Step 2: Update to bundle parameter**

Similar pattern to ToolLoader: only search `evo/<bundle>/contexts/`.

**Step 3: Run tests**

```bash
pytest tests/ -v
```

**Step 4: Commit**

```bash
git add palimpsest/palimpsest/runtime/contexts.py palimpsest/palimpsest/stages/context.py
git commit -m "refactor(palimpsest): ContextLoader uses bundle"
```

---

### Task 14: Update RuntimeContext to use bundle

**TDD scenario:** Modifying tested code

**Files:**
- Modify: `palimpsest/palimpsest/runtime/context.py`

**Step 1: Rename team → bundle in RuntimeContext**

```python
@dataclass
class RuntimeContext:
    workspace_path: str = ""
    job_id: str = ""
    task_id: str = ""
    bundle: str = ""  # renamed from team
    role: str = ""
    ...
```

**Step 2: Run tests**

```bash
pytest tests/ -v
```

**Step 3: Commit**

```bash
git add palimpsest/palimpsest/runtime/context.py
git commit -m "refactor(palimpsest): RuntimeContext uses bundle"
```

---

### Task 15: Update runner.py to use bundle

**TDD scenario:** Modifying tested code

**Files:**
- Modify: `palimpsest/palimpsest/runner.py`
- Modify: `palimpsest/palimpsest/config.py`

**Step 1: Update RoleManager instantiation**

```python
# Before
resolver = RoleManager(evo_path, team=config.team)

# After
resolver = RoleManager(evo_path, bundle=config.bundle)
```

**Step 2: Update RuntimeContext creation**

```python
runtime_context = RuntimeContext(
    job_id=job_id,
    task_id=task_id,
    bundle=config.bundle,  # renamed
    role=config.role,
)
```

**Step 3: Update _setup_tools() call**

```python
tools = _setup_tools(config, spec, evo_path, evo_sha, gateway, config.bundle)
```

**Step 4: Update JobConfig in config.py**

Add `bundle: str` field, remove `team: str`.

**Step 5: Run tests**

```bash
pytest tests/ -v
```

**Step 6: Commit**

```bash
git add palimpsest/palimpsest/runner.py palimpsest/palimpsest/config.py
git commit -m "refactor(palimpsest): runner uses bundle parameter"
```

---

## Phase 7: Update trenni Supervisor

### Task 16: Delete _DEFAULT_TEAM_DEFINITION and role categorization

**TDD scenario:** Modifying tested code — run tests first

**Files:**
- Modify: `trenni/trenni/supervisor.py`

**Step 1: Run existing tests**

```bash
cd trenni && pytest tests/ -v
```

**Step 2: Delete _DEFAULT_TEAM_DEFINITION**

Remove lines 60-67:
```python
_DEFAULT_TEAM_DEFINITION = SimpleNamespace(
    name="default",
    ...
)
```

**Step 3: Delete _resolve_team_definition() method**

Remove the entire method (lines ~1430-1511).

**Step 4: Delete _load_role_catalog() method**

Remove the method that builds team/global role catalog.

**Step 5: Delete _get_role_for_team() method**

Remove team-specific role lookup.

**Step 6: Commit**

```bash
git add trenni/trenni/supervisor.py
git commit -m "refactor(trenni): delete team definition and role categorization"
```

---

### Task 17: Update task submission to require bundle + role

**TDD scenario:** Full TDD cycle — new validation

**Files:**
- Modify: `trenni/trenni/supervisor.py`

**Step 1: Write test for required bundle field**

```python
# tests/test_bundle_submission.py
def test_submit_without_bundle_returns_400():
    """Task submission without bundle returns 400."""
    response = submit_task(goal="test", role="worker")  # no bundle
    assert response.status_code == 400
    assert "bundle is required" in response.json()["error"]

def test_submit_without_role_returns_400():
    """Task submission without role returns 400."""
    response = submit_task(goal="test", bundle="factorio")  # no role
    assert response.status_code == 400
    assert "role is required" in response.json()["error"]
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_bundle_submission.py -v
# Expected: FAIL
```

**Step 3: Update _handle_trigger() validation**

Around line 432-461:
```python
def _handle_trigger(self, event):
    data = TriggerData.model_validate(event.data)
    
    # Validate required fields
    bundle = str(data.bundle or "").strip()
    role = str(data.role or "").strip()
    
    if not bundle:
        return self._error_response(400, "bundle is required")
    if not role:
        return self._error_response(400, "role is required")
    
    # No planner decomposition - direct role assignment
    task_id = self._make_task_id()
    ...
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_bundle_submission.py -v
```

**Step 5: Commit**

```bash
git add trenni/trenni/supervisor.py tests/test_bundle_submission.py
git commit -m "feat(trenni): require bundle + role in task submission"
```

---

### Task 18: Update SpawnedJob and TaskRecord to use bundle

**TDD scenario:** Modifying tested code

**Files:**
- Modify: `trenni/trenni/state.py`

**Step 1: Rename team → bundle in SpawnedJob**

```python
@dataclass
class SpawnedJob:
    ...
    bundle: str = ""  # renamed from team
```

**Step 2: Rename team → bundle in TaskRecord**

```python
@dataclass
class TaskRecord:
    ...
    bundle: str = ""  # renamed from team
```

**Step 3: Update LaunchCondition.team → bundle**

```python
@dataclass
class LaunchCondition:
    bundle: str
    max_concurrent: int
    
    def satisfied(self, state) -> bool:
        return state.running_count_for_bundle(self.bundle) < self.max_concurrent
```

**Step 4: Update SupervisorState methods**

```python
def increment_bundle_running(self, bundle: str) -> None:
def decrement_bundle_running(self, bundle: str) -> None:
def running_count_for_bundle(self, bundle: str) -> int:
```

**Step 5: Run tests**

```bash
pytest tests/ -v
```

**Step 6: Commit**

```bash
git add trenni/trenni/state.py
git commit -m "refactor(trenni): SpawnedJob/TaskRecord use bundle"
```

---

### Task 19: Update spawn_handler.py to use bundle

**TDD scenario:** Modifying tested code

**Files:**
- Modify: `trenni/trenni/spawn_handler.py`

**Step 1: Rename team → bundle in expand()**

```python
bundle = child.bundle or self._inherit("bundle", parent_job, parent_defaults, "")
```

**Step 2: Update child_defs tuple**

Replace `team` with `bundle` in the tuple structure.

**Step 3: Update TaskRecord creation**

```python
TaskRecord(
    ...
    bundle=bundle,
    ...
)
```

**Step 4: Update SpawnedJob creation**

```python
SpawnedJob(
    ...
    bundle=bundle,
    ...
)
```

**Step 5: Run tests**

```bash
pytest tests/ -v
```

**Step 6: Commit**

```bash
git add trenni/trenni/spawn_handler.py
git commit -m "refactor(trenni): spawn_handler uses bundle"
```

---

### Task 20: Update Scheduler to use bundle capacity

**TDD scenario:** Modifying tested code

**Files:**
- Modify: `trenni/trenni/scheduler.py`

**Step 1: Rename teams → bundles in Scheduler.__init__**

```python
def __init__(
    self,
    state: SupervisorState,
    max_workers: int,
    bundles: Mapping[str, BundleConfig] | None = None,  # renamed
):
    self.bundles: Mapping[str, BundleConfig] = bundles or {}
```

**Step 2: Rename has_team_capacity → has_bundle_capacity**

```python
def has_bundle_capacity(self, bundle: str) -> bool:
    bundle_config = self.bundles.get(bundle)
    ...
```

**Step 3: Update capacity check in promote_next_job()**

```python
if self.has_bundle_capacity(job.bundle):
    ...
```

**Step 4: Run tests**

```bash
pytest tests/ -v
```

**Step 5: Commit**

```bash
git add trenni/trenni/scheduler.py
git commit -m "refactor(trenni): Scheduler uses bundle capacity"
```

---

### Task 21: Update TrenniConfig (teams → bundles)

**TDD scenario:** Modifying tested code

**Files:**
- Modify: `trenni/trenni/config.py`

**Step 1: Rename TeamConfig → BundleConfig**

```python
@dataclass
class BundleConfig:  # renamed from TeamConfig
    runtime: BundleRuntimeConfig = field(default_factory=BundleRuntimeConfig)
    scheduling: BundleSchedulingConfig = field(default_factory=BundleSchedulingConfig)
```

**Step 2: Rename teams → bundles in TrenniConfig**

```python
@dataclass
class TrenniConfig:
    ...
    bundles: dict[str, BundleConfig] = field(default_factory=dict)  # renamed
```

**Step 3: Update from_yaml() parsing**

```python
payload["bundles"] = {
    name: BundleConfig.from_dict(bundle_data)
    for name, bundle_data in (data.get("bundles") or {}).items()
}
```

**Step 4: Rename TeamRuntimeConfig → BundleRuntimeConfig**

Similar rename for all team-related dataclasses.

**Step 5: Run tests**

```bash
pytest tests/ -v
```

**Step 6: Commit**

```bash
git add trenni/trenni/config.py
git commit -m "refactor(trenni): config uses bundles instead of teams"
```

---

### Task 22: Update runtime_builder.py to use bundle

**TDD scenario:** Modifying tested code

**Files:**
- Modify: `trenni/trenni/runtime_builder.py`

**Step 1: Rename team → bundle in build_job_runtime()**

```python
def build_job_runtime(
    self,
    job: SpawnedJob,
    bundle: str = "",  # renamed
    ...
):
```

**Step 2: Rename _get_team_runtime → _get_bundle_runtime**

```python
def _get_bundle_runtime(self, bundle: str) -> BundleRuntimeConfig | None:
    bundle_config = self.config.bundles.get(bundle)
    ...
```

**Step 3: Update runtime config lookup**

```python
bundle_runtime = self._get_bundle_runtime(bundle)
```

**Step 4: Run tests**

```bash
pytest tests/ -v
```

**Step 5: Commit**

```bash
git add trenni/trenni/runtime_builder.py
git commit -m "refactor(trenni): runtime_builder uses bundle"
```

---

### Task 23: Update control_api.py to use bundle

**TDD scenario:** Modifying tested code

**Files:**
- Modify: `trenni/trenni/control_api.py`

**Step 1: Rename team → bundle in list_tasks()**

```python
async def list_tasks(state: str | None = None, bundle: str | None = None):
```

**Step 2: Update task response fields**

```python
"bundle": record.bundle,  # renamed
```

**Step 3: Run tests**

```bash
pytest tests/ -v
```

**Step 4: Commit**

```bash
git add trenni/trenni/control_api.py
git commit -m "refactor(trenni): control_api uses bundle"
```

---

### Task 24: Update replay.py to use bundle

**TDD scenario:** Modifying tested code

**Files:**
- Modify: `trenni/trenni/replay.py`

**Step 1: Rename team → bundle in rebuild_state()**

```python
running_jobs_with_bundles: list[tuple[str, str]] = []
...
bundle = data.get("bundle", "")
task.bundle = data.get("bundle", "")
...
running_jobs_with_bundles.append((job_id, bundle))
```

**Step 2: Rename replay_team_counts → replay_bundle_counts**

```python
supervisor.state.replay_bundle_counts(running_jobs_with_bundles)
```

**Step 3: Run tests**

```bash
pytest tests/ -v
```

**Step 4: Commit**

```bash
git add trenni/trenni/replay.py
git commit -m "refactor(trenni): replay uses bundle"
```

---

## Phase 8: Update Test Fixtures

### Task 25: Update palimpsest test fixtures

**TDD scenario:** Trivial change — fixture restructuring

**Files:**
- Move: `palimpsest/tests/fixtures/evo/teams/factorio/` → `palimpsest/tests/fixtures/evo/factorio/`
- Delete: `palimpsest/tests/fixtures/evo/roles/` (global)
- Modify: `palimpsest/tests/integration/test_adr0011_team_isolation.py` → rename to `test_bundle_isolation.py`

**Step 1: Move factorio fixtures**

```bash
cd palimpsest
mkdir -p tests/fixtures/evo/factorio
git mv tests/fixtures/evo/teams/factorio/* tests/fixtures/evo/factorio/
rm -rf tests/fixtures/evo/teams
```

**Step 2: Delete global fixtures**

```bash
rm -rf tests/fixtures/evo/roles
rm -rf tests/fixtures/evo/prompts
```

**Step 3: Rename and update integration test**

```bash
git mv tests/integration/test_adr0011_team_isolation.py tests/integration/test_bundle_isolation.py
```

Update imports and test code:
- `RoleManager(evo_path, team=...)` → `RoleManager(evo_path, bundle=...)`
- Rename test functions from `test_team_*` → `test_bundle_*`

**Step 4: Run tests**

```bash
pytest tests/ -v
```

**Step 5: Commit**

```bash
git add -A tests/fixtures/evo/
git add tests/integration/test_bundle_isolation.py
git commit -m "refactor(tests): update fixtures for bundle layout"
```

---

### Task 26: Update all test imports and references

**TDD scenario:** Modifying tested code

**Files:**
- All test files in palimpsest/tests/, trenni/tests/, yoitsu-contracts/tests/

**Step 1: Grep for team references in tests**

```bash
grep -rn "team\|TeamManager\|TeamConfig\|TeamDefinition" palimpsest/tests/ trenni/tests/ yoitsu-contracts/tests/ --include="*.py"
```

**Step 2: Update each file**

- Replace `team` → `bundle` in test parameters
- Replace `TeamManager` references → delete or use `RoleManager(bundle=...)`
- Replace `TeamConfig` → `BundleConfig`

**Step 3: Run all tests**

```bash
cd palimpsest && pytest tests/ -v
cd trenni && pytest tests/ -v
cd yoitsu-contracts && pytest tests/ -v
```

**Step 4: Commit**

```bash
git add -A palimpsest/tests/ trenni/tests/ yoitsu-contracts/tests/
git commit -m "refactor(tests): complete team → bundle rename"
```

---

## Phase 9: Update CLI and Config Files

### Task 27: Update palimpsest CLI

**TDD scenario:** Modifying tested code

**Files:**
- Modify: `palimpsest/palimpsest/cli.py`

**Step 1: Update RoleManager usage**

```python
resolver = RoleManager(evo_path, bundle=config.bundle)
```

**Step 2: Run tests**

```bash
pytest tests/ -v
```

**Step 3: Commit**

```bash
git add palimpsest/palimpsest/cli.py
git commit -m "refactor(palimpsest): CLI uses bundle"
```

---

### Task 28: Update trenni CLI

**TDD scenario:** Modifying tested code

**Files:**
- Modify: `trenni/trenni/cli.py`

**Step 1: Update config loading**

```bash
grep -n "team\|TeamConfig" trenni/trenni/cli.py
```

Replace any team references with bundle.

**Step 2: Run tests**

```bash
pytest tests/ -v
```

**Step 3: Commit**

```bash
git add trenni/trenni/cli.py
git commit -m "refactor(trenni): CLI uses bundle"
```

---

### Task 29: Update config/trenni.yaml if exists

**TDD scenario:** Trivial change — config update

**Files:**
- Modify: `config/trenni.yaml` (if exists)

**Step 1: Rename teams: section to bundles:**

```yaml
# Before
teams:
  factorio:
    runtime:
      image: ...

# After
bundles:
  factorio:
    runtime:
      image: ...
```

**Step 2: Commit**

```bash
git add config/trenni.yaml
git commit -m "refactor(config): rename teams → bundles in yaml"
```

---

## Phase 10: Update Documentation

### Task 30: Update docs and READMEs

**TDD scenario:** Trivial change — doc updates

**Files:**
- Modify: `docs/superpowers/specs/2026-04-06-bundle-mvp-design.md` (mark as implemented)
- Modify: `README.md` in yoitsu, trenni, palimpsest (if they mention teams)
- Modify: Any other docs mentioning teams

**Step 1: Update design spec status**

```markdown
**Status:** Implemented
```

**Step 2: Grep for team references in docs**

```bash
grep -rn "team\|TeamManager\|TeamDefinition" docs/ README.md --include="*.md"
```

**Step 3: Update each doc**

Replace team → bundle terminology where appropriate.

**Step 4: Commit**

```bash
git add docs/ README.md
git commit -m "docs: update team → bundle terminology"
```

---

## Phase 11: Final Verification

### Task 31: Verify no team references remain

**TDD scenario:** Verification step

**Files:**
- None (grep verification)

**Step 1: Grep for team in Python code**

```bash
grep -rn "team\|TeamManager\|TeamConfig\|TeamDefinition\|_DEFAULT_TEAM_DEFINITION" \
  yoitsu/ palimpsest/ trenni/ yoitsu-contracts/ \
  --include="*.py" | grep -v "steam\|steamboat\|# team\|team members\|@team"
```

Expected: Zero hits (except comments or unrelated matches).

**Step 2: Grep for teams/factorio path**

```bash
grep -rn "teams\.factorio\|teams/factorio" yoitsu/ palimpsest/ trenni/ --include="*.py"
```

Expected: Zero hits.

**Step 3: Verify evo directory layout**

```bash
ls -la evo/
# Expected: factorio/ only (no roles/, teams/, prompts/, tools/, contexts/)
ls -la evo/factorio/
# Expected: roles/, tools/, contexts/, prompts/, lib/, scripts/, evolved/, __init__.py
```

**Step 4: Commit verification results**

```bash
git add -A
git commit -m "verify: no team references remain in codebase"
```

---

### Task 32: Run full test suite

**TDD scenario:** Verification step

**Files:**
- None (test execution)

**Step 1: Run all tests**

```bash
cd yoitsu-contracts && pytest tests/ -v --tb=short
cd palimpsest && pytest tests/ -v --tb=short
cd trenni && pytest tests/ -v --tb=short
cd yoitsu && pytest tests/ -v --tb=short
```

**Step 2: Fix any failures**

If tests fail, debug and fix incrementally.

**Step 3: Run smoke test if available**

```bash
# Check for smoke tests
ls smoke/ scripts/
# Run any available smoke tests
```

---

## Success Criteria Verification

After completing all tasks, verify:

1. **Submitting `{bundle: factorio, role: worker, goal: "...", params: {}}` runs worker directly**
2. **Submitting a task without `role` returns 400 immediately**
3. **`supervisor.py` contains zero references to `planner_role`, `worker_roles`, `eval_role`, or `_DEFAULT_TEAM_DEFINITION`**
4. **`evo/roles/`, `evo/tools/`, `evo/contexts/`, `evo/prompts/`, and `evo/teams/` do not exist**
5. **`grep -r "teams\.factorio\|teams/factorio"` returns zero hits in code**
6. **Factorio smoke test passes under new layout**
7. **Implementer-produced Lua script lands in `evo/factorio/evolved/scripts/`**