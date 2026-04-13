# ADR-0011: Team as First-Class Isolation Boundary - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement team as a first-class isolation boundary with per-team runtime profiles, two-layer evo structure, and team-scoped launch conditions.

**Architecture:** Three-part change: (1) Trenni gains TeamConfig and team-aware scheduling, (2) Palimpsest gains RuntimeContext.team and two-layer evo resolution, (3) yoitsu-contracts deprecates @role(teams=). Components receive `team` parameter instead of `evo_root`, using fixed EVO_DIR constant.

**Tech Stack:** Python, Pydantic, dataclasses, async event handling, git

---

## Phase 1: yoitsu-contracts (Team Metadata Changes)

### Task 1: Deprecate `teams` field in RoleMetadata

**Files:**
- Modify: `yoitsu-contracts/src/yoitsu_contracts/role_metadata.py`
- Test: `yoitsu-contracts/tests/test_role_metadata.py`

**Step 1: Write the failing test**

```python
# Add to yoitsu-contracts/tests/test_role_metadata.py

def test_role_metadata_teams_field_deprecated():
    """RoleMetadata.teams field is deprecated and ignored."""
    from yoitsu_contracts.role_metadata import RoleMetadata
    
    # teams field still exists for backward compat but is not used
    meta = RoleMetadata(
        name="test",
        description="test role",
        teams=["deprecated"],  # Should be ignored
    )
    assert meta.teams == ["deprecated"]  # Field exists but deprecated
```

**Step 2: Run test to verify current behavior**

Run: `cd /home/holo/yoitsu/yoitsu-contracts && pytest tests/test_role_metadata.py -v`
Expected: PASS (teams field already exists)

**Step 3: Add deprecation note in RoleMetadata**

```python
# Modify yoitsu-contracts/src/yoitsu_contracts/role_metadata.py

@dataclass
class RoleMetadata:
    name: str
    description: str
    teams: list[str] = field(default_factory=lambda: ["default"])  # DEPRECATED: directory location determines team membership
    role_type: str = "worker"
    min_cost: float = 0.0
    recommended_cost: float = 0.0
    max_cost: float = 10.0
    min_capability: str = ""
```

**Step 4: Update RoleMetadataReader to ignore teams in decorator**

```python
# In RoleMetadataReader._extract_metadata, add comment:
# NOTE: 'teams' field is extracted for backward compat but ignored.
# Team membership is determined by directory location.
```

**Step 5: Commit**

```bash
cd /home/holo/yoitsu/yoitsu-contracts
git add src/yoitsu_contracts/role_metadata.py
git commit -m "feat(contracts): deprecate RoleMetadata.teams field (ADR-0011 D3)"
```

---

## Phase 2: Trenni (Team Configuration)

### Task 2: Add TeamConfig dataclasses to Trenni

**Files:**
- Modify: `trenni/trenni/config.py`
- Test: `trenni/tests/test_config.py`

**Step 1: Write the failing test**

```python
# Add to trenni/tests/test_config.py

def test_team_config_parsing():
    """TeamConfig parses from YAML with runtime and scheduling sections."""
    from trenni.config import TeamConfig, TeamRuntimeConfig, TeamSchedulingConfig
    
    runtime = TeamRuntimeConfig(
        image="localhost/test:dev",
        pod_name=None,
        extra_networks=["test-net"],
    )
    scheduling = TeamSchedulingConfig(max_concurrent_jobs=2)
    
    team = TeamConfig(runtime=runtime, scheduling=scheduling)
    assert team.runtime.image == "localhost/test:dev"
    assert team.runtime.pod_name is None
    assert team.scheduling.max_concurrent_jobs == 2

def test_trenni_config_has_teams():
    """TrenniConfig includes teams dict."""
    from trenni.config import TrenniConfig, TeamConfig
    
    config = TrenniConfig()
    assert hasattr(config, 'teams')
    assert isinstance(config.teams, dict)
```

**Step 2: Run test to verify it fails**

Run: `cd /home/holo/yoitsu/trenni && pytest tests/test_config.py::test_team_config_parsing -v`
Expected: FAIL with "cannot import name 'TeamConfig'"

**Step 3: Write implementation**

```python
# Add to trenni/trenni/config.py

@dataclass
class TeamRuntimeConfig:
    image: str | None = None
    pod_name: str | None = None
    env_allowlist: list[str] = field(default_factory=list)
    extra_networks: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict | None) -> "TeamRuntimeConfig":
        payload = data or {}
        return cls(
            image=payload.get("image"),
            pod_name=payload.get("pod_name"),
            env_allowlist=list(payload.get("env_allowlist", [])),
            extra_networks=list(payload.get("extra_networks", [])),
        )


@dataclass
class TeamSchedulingConfig:
    max_concurrent_jobs: int = 0  # 0 = unlimited

    @classmethod
    def from_dict(cls, data: dict | None) -> "TeamSchedulingConfig":
        payload = data or {}
        return cls(max_concurrent_jobs=int(payload.get("max_concurrent_jobs", 0)))


@dataclass
class TeamConfig:
    runtime: TeamRuntimeConfig = field(default_factory=TeamRuntimeConfig)
    scheduling: TeamSchedulingConfig = field(default_factory=TeamSchedulingConfig)

    @classmethod
    def from_dict(cls, data: dict | None) -> "TeamConfig":
        payload = data or {}
        return cls(
            runtime=TeamRuntimeConfig.from_dict(payload.get("runtime")),
            scheduling=TeamSchedulingConfig.from_dict(payload.get("scheduling")),
        )
```

**Step 4: Add teams to TrenniConfig**

```python
# Modify TrenniConfig in trenni/trenni/config.py

@dataclass
class TrenniConfig:
    # ... existing fields ...
    teams: dict[str, TeamConfig] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "TrenniConfig":
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        
        # ... existing parsing ...
        
        # Parse teams
        teams_data = data.get("teams", {})
        teams = {name: TeamConfig.from_dict(cfg) for name, cfg in teams_data.items()}
        
        payload["teams"] = teams
        return cls(**payload)
```

**Step 5: Run test to verify it passes**

Run: `cd /home/holo/yoitsu/trenni && pytest tests/test_config.py -v`
Expected: PASS

**Step 6: Commit**

```bash
cd /home/holo/yoitsu/trenni
git add trenni/config.py tests/test_config.py
git commit -m "feat(trenni): add TeamConfig, TeamRuntimeConfig, TeamSchedulingConfig (ADR-0011 D4)"
```

### Task 3: Update JobRuntimeSpec for team runtime

**Files:**
- Modify: `trenni/trenni/runtime_types.py`
- Test: `trenni/tests/test_runtime_types.py`

**Step 1: Write the failing test**

```python
# Add to trenni/tests/test_runtime_types.py

def test_job_runtime_spec_pod_name_can_be_none():
    """JobRuntimeSpec.pod_name accepts None (no pod)."""
    from trenni.runtime_types import JobRuntimeSpec
    
    spec = JobRuntimeSpec(
        job_id="test",
        source_event_id="evt",
        container_name="test-container",
        image="test:dev",
        pod_name=None,  # None = no pod
        labels={},
        env={},
        command=("test",),
        config_payload_b64="",
        extra_networks=("factorio-net",),
    )
    assert spec.pod_name is None
    assert spec.extra_networks == ("factorio-net",)
```

**Step 2: Run test to verify it fails**

Run: `cd /home/holo/yoitsu/trenni && pytest tests/test_runtime_types.py -v`
Expected: FAIL with "JobRuntimeSpec has no attribute 'extra_networks'"

**Step 3: Write implementation**

```python
# Modify trenni/trenni/runtime_types.py

@dataclass(frozen=True)
class JobRuntimeSpec:
    job_id: str
    source_event_id: str
    container_name: str
    image: str
    pod_name: str | None  # Changed: None = no pod
    labels: Mapping[str, str]
    env: Mapping[str, str]
    command: tuple[str, ...]
    config_payload_b64: str
    extra_networks: tuple[str, ...] = ()  # NEW: additional networks
```

**Step 4: Run test to verify it passes**

Run: `cd /home/holo/yoitsu/trenni && pytest tests/test_runtime_types.py -v`
Expected: PASS

**Step 5: Commit**

```bash
cd /home/holo/yoitsu/trenni
git add trenni/runtime_types.py tests/test_runtime_types.py
git commit -m "feat(trenni): JobRuntimeSpec.pod_name accepts None, add extra_networks (ADR-0011 D8)"
```

### Task 4: RuntimeSpecBuilder uses team config

**Files:**
- Modify: `trenni/trenni/runtime_builder.py`
- Test: `trenni/tests/test_runtime_builder.py`

**Step 1: Write the failing test**

```python
# Add to trenni/tests/test_runtime_builder.py

def test_runtime_spec_builder_uses_team_config():
    """RuntimeSpecBuilder selects runtime profile from team config."""
    from trenni.config import TrenniConfig, TeamConfig, TeamRuntimeConfig
    from trenni.runtime_builder import RuntimeSpecBuilder, build_runtime_defaults
    
    config = TrenniConfig()
    config.teams["factorio"] = TeamConfig(
        runtime=TeamRuntimeConfig(
            image="localhost/factorio-job:dev",
            pod_name=None,
            extra_networks=["factorio-net"],
        )
    )
    
    defaults = build_runtime_defaults(config)
    builder = RuntimeSpecBuilder(config, defaults)
    
    spec = builder.build(
        job_id="test-job",
        task_id="test-task",
        source_event_id="evt",
        task="test goal",
        role="worker",
        team="factorio",
        repo="",
        init_branch="main",
        evo_sha=None,
    )
    
    assert spec.image == "localhost/factorio-job:dev"
    assert spec.pod_name is None
    assert spec.extra_networks == ("factorio-net",)
```

**Step 2: Run test to verify it fails**

Run: `cd /home/holo/yoitsu/trenni && pytest tests/test_runtime_builder.py::test_runtime_spec_builder_uses_team_config -v`
Expected: FAIL (team config lookup not implemented)

**Step 3: Write implementation**

```python
# Modify trenni/trenni/runtime_builder.py

class RuntimeSpecBuilder:
    def __init__(self, config: TrenniConfig, defaults: RuntimeDefaults) -> None:
        self.config = config
        self.defaults = defaults

    def _get_team_runtime(self, team: str) -> TeamRuntimeConfig:
        """Get team runtime config, fallback to defaults."""
        team_config = self.config.teams.get(team)
        if team_config:
            return team_config.runtime
        # Return empty config (use defaults)
        return TeamRuntimeConfig()

    def build(
        self,
        *,
        job_id: str,
        task_id: str | None = None,
        source_event_id: str,
        task: str,
        role: str,
        role_params: dict | None = None,
        team: str = "default",
        repo: str,
        init_branch: str,
        evo_sha: str | None,
        budget: float | None = None,
        job_context: JobContextConfig | None = None,
    ) -> JobRuntimeSpec:
        # Get team runtime config
        team_runtime = self._get_team_runtime(team)
        
        # Derive runtime settings from team config + defaults
        image = team_runtime.image or self.defaults.image
        pod_name = team_runtime.pod_name if team_runtime.pod_name is not None else self.defaults.pod_name
        extra_networks = tuple(team_runtime.extra_networks)
        
        # Merge env allowlist: team-specific replaces global
        env_allowlist = tuple(team_runtime.env_allowlist) if team_runtime.env_allowlist else self.defaults.env_allowlist
        
        # ... rest of existing build logic ...
        
        return JobRuntimeSpec(
            job_id=job_id,
            source_event_id=source_event_id,
            container_name=f"yoitsu-job-{job_id.replace('/', '-')}",
            image=image,
            pod_name=pod_name,
            labels=labels,
            env=env,
            command=("palimpsest", "container-entrypoint"),
            config_payload_b64=payload_b64,
            extra_networks=extra_networks,
        )
```

**Step 4: Run test to verify it passes**

Run: `cd /home/holo/yoitsu/trenni && pytest tests/test_runtime_builder.py -v`
Expected: PASS

**Step 5: Commit**

```bash
cd /home/holo/yoitsu/trenni
git add trenni/runtime_builder.py tests/test_runtime_builder.py
git commit -m "feat(trenni): RuntimeSpecBuilder uses team runtime config (ADR-0011 D8)"
```

### Task 5: PodmanBackend handles pod_name=None and extra_networks

**Files:**
- Modify: `trenni/trenni/podman_backend.py`
- Test: `trenni/tests/test_podman_backend.py`

**Step 1: Write the failing test**

```python
# Add to trenni/tests/test_podman_backend.py

import pytest
from trenni.runtime_types import JobRuntimeSpec

def test_podman_backend_prepare_without_pod():
    """PodmanBackend.prepare() omits pod field when pod_name is None."""
    # This test uses mock transport
    pass  # Integration test, verify behavior in prepare()

def test_podman_backend_prepare_with_extra_networks():
    """PodmanBackend.prepare() includes extra_networks in payload."""
    pass  # Integration test
```

**Step 2: Write implementation**

```python
# Modify trenni/trenni/podman_backend.py

async def ensure_ready(self, spec: JobRuntimeSpec) -> None:
    """Validate runtime environment before container creation."""
    # Check pod only if pod_name is not None
    if spec.pod_name is not None:
        await self._ensure_pod_exists(spec.pod_name)
    
    await self._ensure_image_available(spec.image, self.defaults.pull_policy)
    
    # Validate extra networks exist
    for network in spec.extra_networks:
        await self._ensure_network_exists(network)

async def prepare(self, spec: JobRuntimeSpec) -> JobHandle:
    payload = {
        "name": spec.container_name,
        "image": spec.image,
        "env": dict(spec.env),
        "labels": dict(spec.labels),
        "command": list(spec.command),
    }
    
    # Only include pod if pod_name is not None
    if spec.pod_name is not None:
        payload["pod"] = spec.pod_name
    
    # Include extra networks
    if spec.extra_networks:
        payload["networks"] = list(spec.extra_networks)
    
    response = await self._request("POST", "/libpod/containers/create", json=payload)
    data = response.json()
    return JobHandle(
        job_id=spec.job_id,
        container_id=data["Id"],
        container_name=spec.container_name,
    )

async def _ensure_network_exists(self, network_name: str) -> None:
    """Validate that a Podman network exists."""
    response = await self._request(
        "GET",
        f"/libpod/networks/{quote(network_name, safe='')}/exists",
        expected={204, 404},
    )
    if response.status_code == 404:
        raise RuntimeError(f"Podman network {network_name!r} does not exist")
```

**Step 3: Run existing tests to verify no regression**

Run: `cd /home/holo/yoitsu/trenni && pytest tests/ -v`
Expected: All tests pass

**Step 4: Commit**

```bash
cd /home/holo/yoitsu/trenni
git add trenni/podman_backend.py
git commit -m "feat(trenni): PodmanBackend handles pod_name=None and extra_networks (ADR-0011 D8)"
```

### Task 6: Add running_jobs_by_team tracking and launch conditions

**Files:**
- Modify: `trenni/trenni/state.py`
- Modify: `trenni/trenni/supervisor.py`
- Test: `trenni/tests/test_state.py`

**Step 1: Write the failing test**

```python
# Add to trenni/tests/test_state.py

def test_supervisor_state_tracks_running_jobs_by_team():
    """SupervisorState maintains running_jobs_by_team counter."""
    from trenni.state import SupervisorState
    
    state = SupervisorState()
    assert hasattr(state, 'running_jobs_by_team')
    assert state.running_jobs_by_team == {}
    
    state.increment_team_running("factorio")
    assert state.running_jobs_by_team["factorio"] == 1
    
    state.increment_team_running("factorio")
    assert state.running_jobs_by_team["factorio"] == 2
    
    state.decrement_team_running("factorio")
    assert state.running_jobs_by_team["factorio"] == 1
    
    state.decrement_team_running("factorio")
    assert state.running_jobs_by_team.get("factorio", 0) == 0

def test_team_launch_condition():
    """Team launch condition checks running count against max_concurrent."""
    from trenni.state import SupervisorState, TeamLaunchCondition
    
    state = SupervisorState()
    state.teams_config = {"factorio": {"scheduling": {"max_concurrent_jobs": 1}}}
    
    condition = TeamLaunchCondition(team="factorio", max_concurrent=1)
    
    # No jobs running -> condition satisfied
    assert condition.is_satisfied(state)
    
    # One job running -> condition not satisfied
    state.increment_team_running("factorio")
    assert not condition.is_satisfied(state)
```

**Step 2: Run test to verify it fails**

Run: `cd /home/holo/yoitsu/trenni && pytest tests/test_state.py -v`
Expected: FAIL with missing attributes

**Step 3: Write implementation**

```python
# Modify trenni/trenni/state.py

@dataclass
class SupervisorState:
    # ... existing fields ...
    running_jobs_by_team: dict[str, int] = field(default_factory=dict)
    teams_config: dict[str, Any] = field(default_factory=dict)
    
    def increment_team_running(self, team: str) -> None:
        self.running_jobs_by_team[team] = self.running_jobs_by_team.get(team, 0) + 1
    
    def decrement_team_running(self, team: str) -> None:
        current = self.running_jobs_by_team.get(team, 0)
        if current > 0:
            self.running_jobs_by_team[team] = current - 1
    
    def running_count_for_team(self, team: str) -> int:
        return self.running_jobs_by_team.get(team, 0)


@dataclass
class TeamLaunchCondition:
    team: str
    max_concurrent: int
    
    def is_satisfied(self, state: SupervisorState) -> bool:
        if self.max_concurrent <= 0:
            return True  # No limit
        return state.running_count_for_team(self.team) < self.max_concurrent
```

**Step 4: Run test to verify it passes**

Run: `cd /home/holo/yoitsu/trenni && pytest tests/test_state.py -v`
Expected: PASS

**Step 5: Integrate into supervisor**

```python
# Modify trenni/trenni/supervisor.py
# In job launch logic:
# 1. Get team from job config
# 2. Get max_concurrent from teams_config
# 3. Check TeamLaunchCondition
# 4. Increment running_jobs_by_team on launch
# 5. Decrement on terminal
```

**Step 6: Commit**

```bash
cd /home/holo/yoitsu/trenni
git add trenni/state.py trenni/supervisor.py tests/test_state.py
git commit -m "feat(trenni): add running_jobs_by_team tracking and launch conditions (ADR-0011 D5)"
```

---

## Phase 3: Palimpsest (RuntimeContext and Two-Layer Evo)

### Task 7: Add team field to RuntimeContext

**Files:**
- Modify: `palimpsest/palimpsest/runtime/context.py`
- Test: `palimpsest/tests/test_runtime_context.py`

**Step 1: Write the failing test**

```python
# Add to palimpsest/tests/test_runtime_context.py

def test_runtime_context_has_team_field():
    """RuntimeContext includes team field."""
    from palimpsest.runtime.context import RuntimeContext
    
    ctx = RuntimeContext(
        workspace_path="/tmp/test",
        job_id="job-123",
        task_id="task-123",
        team="factorio",
    )
    assert ctx.team == "factorio"

def test_runtime_context_cleanup_on_error():
    """RuntimeContext.cleanup() is called even on exceptions."""
    from palimpsest.runtime.context import RuntimeContext
    
    ctx = RuntimeContext()
    cleanup_called = []
    
    def cleanup_fn():
        cleanup_called.append(True)
    
    ctx.register_cleanup(cleanup_fn)
    
    try:
        raise ValueError("test error")
    finally:
        ctx.cleanup()
    
    assert cleanup_called == [True]
```

**Step 2: Run test to verify it fails**

Run: `cd /home/holo/yoitsu/palimpsest && pytest tests/test_runtime_context.py -v`
Expected: FAIL with "RuntimeContext has no attribute 'team'"

**Step 3: Write implementation**

```python
# Modify palimpsest/palimpsest/runtime/context.py

@dataclass
class RuntimeContext:
    workspace_path: str = ""
    job_id: str = ""
    task_id: str = ""
    team: str = "default"  # NEW: team name for evo resolution
    resources: dict[str, Any] = field(default_factory=dict)
    _cleanup_fns: list[Callable] = field(default_factory=list, repr=False)
```

**Step 4: Export RuntimeContext**

```python
# Modify palimpsest/palimpsest/runtime/__init__.py

from palimpsest.runtime.context import RuntimeContext

__all__ = [
    # ... existing exports ...
    "RuntimeContext",
]
```

**Step 5: Run test to verify it passes**

Run: `cd /home/holo/yoitsu/palimpsest && pytest tests/test_runtime_context.py -v`
Expected: PASS

**Step 6: Commit**

```bash
cd /home/holo/yoitsu/palimpsest
git add palimpsest/runtime/context.py palimpsest/runtime/__init__.py tests/test_runtime_context.py
git commit -m "feat(palimpsest): add team field to RuntimeContext (ADR-0011 D6)"
```

### Task 8: Add runtime_context injection to UnifiedToolGateway

**Files:**
- Modify: `palimpsest/palimpsest/runtime/tools.py`
- Test: `palimpsest/tests/test_tool_injection.py`

**Step 1: Write the failing test**

```python
# Add to palimpsest/tests/test_tool_injection.py

def test_tool_receives_runtime_context():
    """Tool declaring runtime_context parameter receives it via injection."""
    from palimpsest.runtime.tools import tool, UnifiedToolGateway
    from palimpsest.runtime.context import RuntimeContext
    from palimpsest.config import ToolsConfig
    from palimpsest.runtime.event_gateway import EventGateway
    
    @tool
    def test_tool_with_context(value: int, runtime_context: RuntimeContext) -> str:
        return f"team={runtime_context.team}, value={value}"
    
    # Gateway setup
    config = ToolsConfig()
    gateway = UnifiedToolGateway(config, Path("/tmp/evo"), [], mock_gateway)
    
    # Execute with runtime_context injection
    ctx = RuntimeContext(team="factorio")
    result = gateway.execute("test_tool_with_context", "call-1", {"value": 42}, "/tmp/ws", runtime_context=ctx)
    
    assert "team=factorio" in result.output
    assert "value=42" in result.output
```

**Step 2: Run test to verify it fails**

Run: `cd /home/holo/yoitsu/palimpsest && pytest tests/test_tool_injection.py -v`
Expected: FAIL

**Step 3: Write implementation**

```python
# Modify palimpsest/palimpsest/runtime/tools.py

# Add runtime_context to injected_args
INJECTED_ARGS = {"workspace", "gateway", "evo_root", "evo_sha", "runtime_context"}

# Modify UnifiedToolGateway.execute
def execute(
    self,
    name: str,
    call_id: str,
    args: dict,
    workspace: str,
    runtime_context: RuntimeContext | None = None,  # NEW parameter
) -> ToolResult:
    func = self._functions.get(name)
    if not func:
        return ToolResult(success=False, output=f"Unknown tool: {name}")
    
    # ... existing event emission ...
    
    try:
        sig = inspect.signature(func)
        kwargs = dict(args)
        if "workspace" in sig.parameters:
            kwargs["workspace"] = workspace
        if "gateway" in sig.parameters and getattr(func, "__module__", "").startswith("palimpsest.runtime"):
            kwargs["gateway"] = self._gateway
        if "runtime_context" in sig.parameters and runtime_context is not None:
            kwargs["runtime_context"] = runtime_context
        
        result = func(**kwargs)
        # ... rest of existing logic ...
```

**Step 4: Run test to verify it passes**

Run: `cd /home/holo/yoitsu/palimpsest && pytest tests/test_tool_injection.py -v`
Expected: PASS

**Step 5: Commit**

```bash
cd /home/holo/yoitsu/palimpsest
git add palimpsest/runtime/tools.py tests/test_tool_injection.py
git commit -m "feat(palimpsest): add runtime_context injection to UnifiedToolGateway (ADR-0011 D6)"
```

### Task 9: RoleManager uses team parameter and two-layer resolution

**Files:**
- Modify: `palimpsest/palimpsest/runtime/roles.py`
- Test: `palimpsest/tests/test_role_resolution.py`

**Step 1: Write the failing test**

```python
# Add to palimpsest/tests/test_role_resolution.py

def test_role_manager_with_team():
    """RoleManager accepts team parameter for two-layer resolution."""
    from palimpsest.runtime.roles import RoleManager
    from pathlib import Path
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        evo_root = Path(tmpdir)
        
        # Create global role
        global_roles = evo_root / "roles"
        global_roles.mkdir()
        (global_roles / "worker.py").write_text('''
from palimpsest.runtime.roles import role, JobSpec

@role(name="worker", description="global worker")
def worker_role(**params):
    return JobSpec(...)
''')
        
        # Create team-specific role
        team_roles = evo_root / "teams" / "factorio" / "roles"
        team_roles.mkdir(parents=True)
        (team_roles / "worker.py").write_text('''
from palimpsest.runtime.roles import role, JobSpec

@role(name="worker", description="factorio worker")
def worker_role(**params):
    return JobSpec(...)
''')
        
        # Global manager sees global role
        global_manager = RoleManager(evo_root, team="default")
        global_meta = global_manager.get_definition("worker")
        assert global_meta.description == "global worker"
        
        # Team manager sees team-specific role
        factorio_manager = RoleManager(evo_root, team="factorio")
        factorio_meta = factorio_manager.get_definition("worker")
        assert factorio_meta.description == "factorio worker"
```

**Step 2: Run test to verify it fails**

Run: `cd /home/holo/yoitsu/palimpsest && pytest tests/test_role_resolution.py -v`
Expected: FAIL

**Step 3: Write implementation**

```python
# Modify palimpsest/palimpsest/runtime/roles.py

EVO_DIR = Path.cwd() / "evo"  # Fixed constant

class RoleManager(RoleMetadataReader):
    def __init__(self, evo_root: str | Path, team: str = "default") -> None:
        self._evo_root = Path(evo_root)
        self._team = team
        self._team_roles_dir = self._evo_root / "teams" / team / "roles"
        self._global_roles_dir = self._evo_root / "roles"
    
    def list_definitions(self) -> list[RoleMetadata]:
        """Scan both team and global roles, with team shadowing global."""
        definitions = {}
        
        # Scan global first
        for meta in self._scan_directory(self._global_roles_dir):
            definitions[meta.name] = meta
        
        # Scan team (shadows global)
        if self._team_roles_dir.exists():
            for meta in self._scan_directory(self._team_roles_dir):
                definitions[meta.name] = meta
        
        return list(definitions.values())
    
    def get_definition(self, name: str) -> RoleMetadata | None:
        """Get role metadata, preferring team-specific over global."""
        # Try team-specific first
        if self._team_roles_dir.exists():
            team_path = self._team_roles_dir / f"{name}.py"
            if team_path.exists():
                return self._extract_metadata(team_path)
        
        # Fallback to global
        global_path = self._global_roles_dir / f"{name}.py"
        if global_path.exists():
            return self._extract_metadata(global_path)
        
        return None
    
    def resolve(self, role_name: str, **params: Any) -> JobSpec:
        """Resolve role, preferring team-specific over global."""
        # Try team-specific first
        if self._team_roles_dir.exists():
            team_path = self._team_roles_dir / f"{role_name}.py"
            if team_path.exists():
                return self._load_and_execute(team_path, params)
        
        # Fallback to global
        global_path = self._global_roles_dir / f"{role_name}.py"
        if global_path.exists():
            return self._load_and_execute(global_path, params)
        
        raise FileNotFoundError(f"Role {role_name} not found for team {self._team}")
```

**Step 4: Run test to verify it passes**

Run: `cd /home/holo/yoitsu/palimpsest && pytest tests/test_role_resolution.py -v`
Expected: PASS

**Step 5: Commit**

```bash
cd /home/holo/yoitsu/palimpsest
git add palimpsest/runtime/roles.py tests/test_role_resolution.py
git commit -m "feat(palimpsest): RoleManager two-layer resolution with team parameter (ADR-0011 D2, D7)"
```

### Task 10: Runner creates and passes RuntimeContext

**Files:**
- Modify: `palimpsest/palimpsest/runner.py`
- Test: `palimpsest/tests/test_runner_context.py`

**Step 1: Write the failing test**

```python
# Add to palimpsest/tests/test_runner_context.py

def test_runner_creates_runtime_context():
    """Runner creates RuntimeContext with team from JobConfig."""
    # Integration test: verify runner behavior
    pass
```

**Step 2: Write implementation**

```python
# Modify palimpsest/palimpsest/runner.py

from palimpsest.runtime.context import RuntimeContext

def _run_job_from_spec(
    config: JobConfig, spec: JobSpec, evo_path: Path, *, resolved_evo_sha: str | None = None
) -> None:
    job_id = config.job_id
    # ... existing setup ...
    
    # Create RuntimeContext
    runtime_context = RuntimeContext(
        job_id=job_id,
        task_id=config.task_id or job_id,
        team=config.team,  # From JobConfig
    )
    
    workspace: str | None = None
    try:
        # Pass runtime_context to preparation_fn
        if "runtime_context" in inspect.signature(spec.preparation_fn).parameters:
            workspace_cfg = spec.preparation_fn(
                goal=config.task,
                repo=config.workspace.repo,
                runtime_context=runtime_context,
                **role_params,
            )
        else:
            workspace_cfg = spec.preparation_fn(
                goal=config.task,
                repo=config.workspace.repo,
                **role_params,
            )
        
        workspace = setup_workspace(...)
        runtime_context.workspace_path = workspace
        
        # ... context and interaction ...
        
        # Pass runtime_context to tools
        tools = _setup_tools(config, spec, evo_path, team=config.team, gateway=gateway)
        
        # Interaction loop with runtime_context
        result, git_ref = _stage_interaction_and_publication(
            ...,
            runtime_context=runtime_context,
        )
        
        # ... completion ...
    
    finally:
        if runtime_context:
            runtime_context.cleanup()
        if workspace:
            finalize_workspace_after_job(workspace, gateway=gateway)
```

**Step 3: Run tests to verify**

Run: `cd /home/holo/yoitsu/palimpsest && pytest tests/ -v`
Expected: All tests pass

**Step 4: Commit**

```bash
cd /home/holo/yoitsu/palimpsest
git add palimpsest/runner.py tests/test_runner_context.py
git commit -m "feat(palimpsest): runner creates and passes RuntimeContext (ADR-0011 D6)"
```

---

## Phase 4: Integration Tests

### Task 11: Verify two-layer evo with real structure

**Files:**
- Create test structure in `palimpsest/tests/fixtures/evo-test/`

**Step 1: Create test fixture structure**

```bash
mkdir -p palimpsest/tests/fixtures/evo-test/teams/factorio/roles
mkdir -p palimpsest/tests/fixtures/evo-test/teams/factorio/tools
```

**Step 2: Write integration test**

```python
# Add to palimpsest/tests/test_evo_two_layer.py

def test_two_layer_evo_integration():
    """Full two-layer evo resolution works with real directory structure."""
    from palimpsest.runtime.roles import RoleManager
    from pathlib import Path
    
    evo_root = Path("tests/fixtures/evo-test")
    
    # Test team-specific role shadows global
    manager = RoleManager(evo_root, team="factorio")
    # ... assertions ...
```

**Step 3: Run integration tests**

Run: `cd /home/holo/yoitsu && pytest yoitsu-contracts/tests/ palimpsest/tests/ trenni/tests/ -v`
Expected: All 185+ tests pass

**Step 4: Commit**

```bash
cd /home/holo/yoitsu
git add palimpsest/tests/fixtures/ palimpsest/tests/test_evo_two_layer.py
git commit -m "test: add two-layer evo integration tests (ADR-0011)"
```

### Task 12: Final verification and cleanup

**Step 1: Run all tests**

Run: `cd /home/holo/yoitsu && pytest yoitsu-contracts/tests/ palimpsest/tests/ trenni/tests/ -v`

**Step 2: Update TODO.md**

Mark ADR-0011 as implemented.

**Step 3: Final commit**

```bash
cd /home/holo/yoitsu
git add TODO.md docs/adr/0011-external-task-sources.md
git commit -m "docs: mark ADR-0011 as implemented"
```

---

## Summary

### Implementation Sequence

```
Phase 1: yoitsu-contracts (Task 1)
    ↓
Phase 2: Trenni (Tasks 2-6)
    ↓
Phase 3: Palimpsest (Tasks 7-10)
    ↓
Phase 4: Integration (Tasks 11-12)
```

### Key Changes

- `RoleMetadata.teams` deprecated
- `TeamConfig`, `TeamRuntimeConfig`, `TeamSchedulingConfig` in Trenni
- `JobRuntimeSpec.pod_name: str | None` and `extra_networks`
- `RuntimeSpecBuilder` uses team config
- `PodmanBackend` handles no-pod and extra networks
- `running_jobs_by_team` tracking
- `RuntimeContext.team` field
- `runtime_context` injection in tools
- Two-layer evo resolution with team shadowing