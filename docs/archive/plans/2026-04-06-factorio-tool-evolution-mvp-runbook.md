# Factorio Tool Evolution MVP - Runbook

**Date**: 2026-04-06  
**Status**: ✅ Verified Working

---

## 1. Overview

This runbook documents the actual implementation and verification of the Factorio Tool Evolution MVP. The MVP enables autonomous evolution of Factorio Lua scripts through:

```
Observation (tool_repetition) → Optimizer proposal → Implementer writes scripts → Worker uses scripts
```

---

## 2. Infrastructure Setup

### 2.1 Yoitsu Stack (Quadlet)

Deployed via systemd user units in `/home/holo/.config/containers/systemd/yoitsu/`:

| Service | Image | Purpose | Endpoint |
|---------|-------|---------|----------|
| `yoitsu-postgres` | postgres:16 | Event store database | localhost:5432 |
| `yoitsu-pasloe` | yoitsu-python-base:dev | Event gateway API | http://localhost:8000 |
| `yoitsu-trenni` | yoitsu-python-base:dev | Job supervisor | http://localhost:8100 |

**Start command:**
```bash
systemctl --user start yoitsu-dev-infra.service
systemctl --user start yoitsu-trenni.service
```

### 2.2 Factorio Headless Server

```bash
/home/holo/factorio/bin/x64/factorio \
  --start-server /home/holo/factorio/saves/test.zip \
  --server-settings /home/holo/factorio/config/server-settings.json \
  --rcon-port 27015 \
  --rcon-password changeme
```

| Config | Value |
|--------|-------|
| RCON Host | localhost (or `host.containers.internal` from container) |
| RCON Port | 27015 |
| RCON Password | changeme |
| Save File | `/home/holo/factorio/saves/test.zip` |
| Server Settings | `/home/holo/factorio/config/server-settings.json` |

### 2.3 LLM Configuration

Using DashScope (Alibaba Cloud) coding API:

```yaml
# trenni.dev.yaml
default_llm:
  model: "qwen3-max-2026-01-23"
  api_base: "https://coding.dashscope.aliyuncs.com/v1"
  api_key_env: "OPENAI_API_KEY"
```

---

## 3. Code Changes Summary

### 3.1 Trenni (Job Supervisor)

**File: `trenni/runtime_types.py`**
- Added `volume_mounts: tuple[tuple[str, str], ...]` to `JobRuntimeSpec` for mounting evo directory

**File: `trenni/podman_backend.py`**
- Added volume mount support in `prepare()` method
- Added SELinux `Z` option for container access to host volumes

**File: `trenni/runtime_builder.py`**
- Added `evo_root_host` volume mount injection for job containers

**File: `trenni/config.py`**
- Added `evo_root_host: str = ""` configuration field

**File: `trenni/supervisor.py`**
- Modified `_allocated_job_budget()` to use role's `min_cost` when budget=0

**File: `trenni.dev.yaml`**
- Added `evo_root_host: /home/holo/yoitsu/evo`
- Added `FACTORIO_RCON_*` to env_allowlist
- Added `teams.factorio` configuration

### 3.2 Palimpsest (Job Runner)

**File: `palimpsest/runner.py`**
- Added `sys.path.insert(0, evo_path_str)` to make team-specific modules importable

**File: `palimpsest/runtime/roles.py`**
- Added `team` parameter to `RoleManager.__init__()`
- Added two-layer resolution: `evo/teams/<team>/roles/` → `evo/roles/`

**File: `palimpsest/runtime/contexts.py`**
- Added team-specific context provider loading

**File: `palimpsest/stages/context.py`**
- Pass `team=job_config.team` to context resolver

### 3.3 Yoitsu-Contracts

**File: `yoitsu_contracts/observation.py`**
- Added `ObservationToolRepetitionEvent` and `ObservationContextLateLookupEvent`

### 3.4 Yoitsu (Evo Directory)

**Created files:**

```
/home/holo/yoitsu/evo/
├── roles/
│   ├── planner.py          # Global planner role
│   ├── worker.py           # Placeholder (team-specific overrides)
│   ├── evaluator.py        # Global evaluator role
│   └── optimizer.py        # Optimizer role for evolution
├── prompts/
│   └── optimizer.md        # Optimizer instructions
└── teams/
    └── factorio/
        ├── roles/
        │   ├── worker.py       # RCON-connected worker
        │   └── implementer.py  # Lua script writer
        ├── tools/
        │   └── factorio_call_script.py  # RCON dispatcher tool
        ├── contexts/
        │   └── factorio_scripts.py      # Script catalog provider
        ├── prompts/
        │   ├── worker.md
        │   ├── implementer.md
        │   └── optimizer-addendum.md
        ├── lib/
        │   ├── rcon.py         # RCON client
        │   └── bridge.py       # Factorio bridge
        └── scripts/
            ├── ping.lua
            ├── actions/
            ├── atomic/
            └── ...
```

### 3.5 Key Code Snippets

**Worker Role** (`evo/teams/factorio/roles/worker.py`):
```python
@role(
    name="worker",
    description="Factorio in-game worker with RCON",
    role_type="worker",
    min_cost=0.1,
)
def worker(**params) -> JobSpec:
    return JobSpec(
        preparation_fn=factorio_worker_preparation,  # RCON connection
        context_fn=context_spec(
            system="teams/factorio/prompts/worker.md",
            sections=[{"type": "factorio_scripts"}],
        ),
        publication_fn=factorio_worker_publication,  # No git commits
        tools=["factorio_call_script"],
    )
```

**factorio_call_script Tool** (`evo/teams/factorio/tools/factorio_call_script.py`):
```python
def factorio_call_script(name: str, args: str = "", runtime_context=None) -> ToolResult:
    rcon = runtime_context.resources["rcon"]
    command = f"/agent {name} {args}".strip()
    raw = rcon.send_command(command)
    return ToolResult(success=True, output=raw)
```

---

## 4. Configuration Files

### 4.1 Trenni Environment (`trenni.env`)

```bash
PASLOE_API_KEY=change-me
OPENAI_API_KEY=<your-api-key>
GITHUB_TOKEN=<your-github-token>
FACTORIO_RCON_HOST=host.containers.internal
FACTORIO_RCON_PORT=27015
FACTORIO_RCON_PASSWORD=changeme
FACTORIO_AGENT_REPO=https://github.com/guan-spicy-wolf/factorio-agent.git
```

### 4.2 Trenni Config (`trenni.dev.yaml`)

```yaml
pasloe_url: "http://127.0.0.1:8000"
evo_root: "/workspace/evo"
evo_root_host: "/home/holo/yoitsu/evo"

default_llm:
  model: "qwen3-max-2026-01-23"
  api_base: "https://coding.dashscope.aliyuncs.com/v1"

runtime:
  podman:
    env_allowlist:
      - "OPENAI_API_KEY"
      - "FACTORIO_RCON_HOST"
      - "FACTORIO_RCON_PORT"
      - "FACTORIO_RCON_PASSWORD"

teams:
  default:
    roles: [planner, worker]
    planner_role: planner
    worker_roles: [worker]
  factorio:
    roles: [worker, implementer]
    planner_role: planner
    worker_roles: [worker]
```

---

## 5. Verified Execution Flow

### 5.1 Test Command

```bash
cat > /tmp/factorio-test.yaml << 'EOF'
tasks:
  - goal: "Call the ping script via factorio_call_script and report response"
    role: worker
    team: factorio
    budget: 0.3
EOF

uv run yoitsu submit /tmp/factorio-test.yaml
```

### 5.2 Event Flow (Verified)

```
trigger.external.received
  ↓
supervisor.task.created (task_id: 069d420823227a3b)
  ↓
supervisor.job.enqueued (role: worker, team: factorio)
  ↓
supervisor.job.launched
  ↓
agent.job.started
  ↓
agent.job.stage_transition (init → workspace → context → interaction)
  ↓
agent.llm.request (iteration 1, tools_count: 1)
  ↓
agent.tool.exec (factorio_call_script, args: {'name': 'ping'})
  ↓
agent.tool.result (success: True, output_preview: {"tick":0,"mod":"factorio-agent","status":"ok"})
  ↓
agent.llm.request (iteration 2)
  ↓
agent.llm.response (finish_reason: stop)
  ↓
agent.job.completed
  ↓
supervisor.task.completed
```

### 5.3 RCON Command Verification

Direct RCON test from host:
```python
from teams.factorio.lib.rcon import RCONClient
client = RCONClient(host='localhost', port=27015, password='changeme')
client.connect()
print(client.send_command('/agent ping'))  # {"tick":0,"mod":"factorio-agent","status":"ok"}
client.close()
```

**RCON Test Results:**

| Command | Result |
|---------|--------|
| `agent ping` (no slash) | Empty (Factorio ignores non-commands) |
| `/agent ping` (with slash) | `{"tick":0,"mod":"factorio-agent","status":"ok"}` |
| `/help` | Non-empty (built-in command works) |

---

## 6. Repositories & Commits

| Repo | Commit | Changes |
|------|--------|---------|
| `yoitsu` | `ce3eefc` | Task 8 optimizer role |
| `palimpsest` | `3f955bb` | Tasks 0-8 implementation (sys.path, team roles) |
| `yoitsu-contracts` | `a2fbc43` | Observation contracts |
| `trenni` | `2c28c0e` | Volume mounts, budget fallback |
| `factorio-agent` | `d7867cb` | Worker/implementer roles, tools, scripts |

---

## 7. File Locations

### 7.1 Save Files & Maps

| Type | Location |
|------|----------|
| Factorio Save | `/home/holo/factorio/saves/test.zip` |
| Factorio Config | `/home/holo/factorio/config/server-settings.json` |
| Factorio Mods | `/home/holo/factorio/mods/` |
| Factorio Logs | `/home/holo/factorio/factorio-current.log` |

### 7.2 Evo Directory Structure

```
/home/holo/yoitsu/evo/
├── roles/                    # Global roles
│   ├── planner.py
│   ├── evaluator.py
│   └── optimizer.py
├── prompts/
│   └── optimizer.md
└── teams/
    └── factorio/
        ├── roles/
        │   ├── worker.py
        │   └── implementer.py
        ├── tools/
        │   └── factorio_call_script.py
        ├── contexts/
        │   └── factorio_scripts.py
        ├── lib/
        │   ├── rcon.py
        │   └── bridge.py
        └── scripts/         # Lua scripts (copied from factorio-agent)
            ├── ping.lua
            ├── actions/
            │   ├── place.lua
            │   ├── mine.lua
            │   └── ...
            └── atomic/
```

### 7.3 Container Images

| Image | Dockerfile | Purpose |
|-------|------------|---------|
| `localhost/yoitsu-python-base:dev` | `deploy/podman/yoitsu-python-base.Containerfile` | Base image with trenni, pasloe, contracts |
| `localhost/yoitsu-palimpsest-job:dev` | `deploy/podman/palimpsest-job.Containerfile` | Job execution container |

Build commands:
```bash
./scripts/build-python-base.sh
./scripts/build-job-image.sh
```

---

## 8. Troubleshooting

### 8.1 Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| `No module named 'teams'` | evo not in sys.path | Verify `sys.path.insert(0, evo_path)` in runner.py |
| `'function' object has no attribute '__tool_schema__'` | Tool missing schema | Add `__tool_schema__` dict to tool function |
| `Role definition not found` | Role file missing or syntax error | Check evo/teams/factorio/roles/*.py |
| RCON returns empty | Wrong command format | Use `/agent <name>` with leading slash |
| Budget 0.0 below min_cost | Planner not assigning budget | Fixed: uses role's min_cost as fallback |

### 8.2 Useful Commands

```bash
# Check trenni status
uv run yoitsu status

# View recent events
uv run yoitsu events --limit 50

# Check specific event type
curl -s "http://localhost:8000/events?type=agent.tool.exec&limit=10&order=desc" -H "X-API-Key: change-me"

# View container logs
podman logs yoitsu-job-<job-id>

# Restart trenni
systemctl --user restart yoitsu-trenni.service

# Clean up job containers
podman rm -f $(podman ps -aq --filter "name=yoitsu-job-")
```

---

## 9. Next Steps

1. **Implement optimizer workflow**: Connect `tool_repetition` observation → optimizer spawn
2. **Test implementer role**: Verify Lua script creation with git push
3. **Add more scripts**: Expand `teams/factorio/scripts/` with useful actions
4. **Production hardening**: 
   - Secure RCON password
   - Use real API keys
   - Add monitoring/alerting

---

## 10. References

- MVP Plan: `docs/plans/2026-04-06-factorio-tool-evolution-mvp.md`
- ADR-0011: Team-specific roles and contexts
- ADR-0007: Budget propagation
- Factorio RCON Protocol: https://wiki.factorio.com/Console#RCON