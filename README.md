# Yoitsu

Self-evolving agent system. An autonomous agent completes external tasks while discovering and improving its own capabilities by modifying an evolvable repository.

See [docs/architecture.md](docs/architecture.md) for system design principles and [docs/adr/](docs/adr/) for architecture decision records.

## Components

| Component | Path | Role |
|-----------|------|------|
| [palimpsest](https://github.com/morrejssc-hub/palimpsest) | `palimpsest/` | Agent Runtime — single-job execution engine |
| [trenni](https://github.com/morrejssc-hub/trenni) | `trenni/` | Supervisor — event-driven orchestration and job dispatch |
| [pasloe](https://github.com/morrejssc-hub/pasloe) | `pasloe/` | Event Store — append-only event log with webhook delivery |

Each component is a separate git repository. Use `scripts/setup.sh` to clone or update all of them.

## Quick Start

### Prerequisites
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- OpenAI-compatible API key (OpenAI, Kimi, etc.)

### Setup

```bash
# 1. Clone components
./scripts/setup.sh

# 2. Install dependencies
uv sync

# 3. Set environment variables
export PASLOE_API_KEY=yoitsu-test-key-2026
export OPENAI_API_KEY=<your-api-key>
```

### Start the Stack

```bash
# Start pasloe (event store) + trenni (supervisor)
uv run yoitsu up

# Output: {"ok": true, "pasloe_pid": 12345, "trenni_pid": 12346}
```

### Submit Tasks

Create a task file (see `examples/tasks.yaml`):

```yaml
tasks:
  - task: "Add unit tests for the user authentication module"
    role: "default"
    repo_url: "https://github.com/your-org/your-repo.git"

  - task: "Fix the memory leak in the cache invalidation logic"
    role: "default"
    repo_url: "https://github.com/your-org/your-repo.git"
```

Submit tasks:

```bash
uv run yoitsu submit examples/tasks.yaml
# Output: {"submitted": 2, "failed": 0, "errors": []}
```

### Monitor

```bash
# Check system status
uv run yoitsu status

# Output:
# {
#   "pasloe": {"alive": true, "total_events": 150, "by_type": {...}},
#   "trenni": {"alive": true, "state": "running", "queue_size": 2, ...}
# }

# View logs
uv run yoitsu logs --service pasloe --lines 50
uv run yoitsu logs --service trenni --lines 50

# Long-running report with Pasloe/Trenni + Podman job visibility
python3 scripts/monitor.py --hours 5

# Pause/resume job dispatch
uv run yoitsu pause   # Stop dispatching new jobs
uv run yoitsu resume  # Resume dispatching
```

### Quadlet Deployment

```bash
# Build the Palimpsest job image
./scripts/build-job-image.sh

# Install/update Quadlet units and start the stack
./scripts/deploy-quadlet.sh

# Inspect user-systemd + Podman state
./scripts/quadlet-status.sh
```

### Stop

```bash
uv run yoitsu down
# Output: {"ok": true, "stopped": ["pasloe", "trenni"]}
```

## Configuration

### Trenni Configuration

`config/trenni.yaml` configures the Supervisor:

```yaml
# Event store connection
pasloe_url: "http://localhost:8000"
pasloe_api_key_env: "PASLOE_API_KEY"
source_id: "trenni-supervisor"

# Podman job runtime
runtime:
  kind: "podman"
  podman:
    socket_uri: "unix:///run/podman/podman.sock"
    pod_name: "yoitsu-dev"
    image: "localhost/yoitsu-palimpsest-job:dev"
    pull_policy: "never"
    git_token_env: "GITHUB_TOKEN"
    env_allowlist:
      - "OPENAI_API_KEY"

# Concurrency
max_workers: 4          # Keep low until evo repo is stable
poll_interval: 2.0      # Event polling interval (seconds)

# Default LLM settings (per-job override supported)
default_llm:
  model: "kimi-k2.5"
  api_base: "https://coding.dashscope.aliyuncs.com/v1"
  api_key_env: "OPENAI_API_KEY"
  max_iterations: 30
  temperature: 0.2
```

### Task File Format

Tasks are submitted via YAML files:

```yaml
tasks:
  - task: "Description of what to do"
    role: "default"                              # Role from evo repo
    repo_url: "https://github.com/org/repo.git"  # Target repository

  - task: "Another task"
    role: "default"
    repo_url: "https://github.com/org/repo.git"
```

## CLI Reference

All commands output JSON and use exit code 0 (success) or 1 (failure).

### `yoitsu up`

Start pasloe + trenni, wait for readiness (10s timeout).

```bash
uv run yoitsu up [--config PATH]

# Options:
#   --config  Path to trenni config (default: config/trenni.yaml)

# Output: {"ok": true, "pasloe_pid": 12345, "trenni_pid": 12346}
# Errors: {"ok": false, "error": "..."}
```

Idempotent: if already running, returns success immediately.

### `yoitsu down`

Stop trenni + pasloe gracefully (POST /control/stop → 30s wait → SIGTERM → SIGKILL).

```bash
uv run yoitsu down

# Output: {"ok": true, "stopped": ["pasloe", "trenni"]}
```

Idempotent: if not running, returns success.

### `yoitsu status`

Query system status. Always exits 0.

```bash
uv run yoitsu status

# Output:
# {
#   "pasloe": {
#     "alive": true,
#     "total_events": 150,
#     "by_type": {"task.submit": 50, "job.completed": 30, ...}
#   },
#   "trenni": {
#     "alive": true,
#     "running": true,
#     "paused": false,
#     "running_jobs": 1,
#     "max_workers": 4,
#     "pending_jobs": 2,
#     "ready_queue_size": 0,
#     "runtime_kind": "podman"
#   }
# }
```

### `yoitsu submit`

Submit tasks from YAML file to pasloe.

```bash
uv run yoitsu submit TASKS_FILE

# Output: {"submitted": 5, "failed": 0, "errors": []}
# Errors: {"ok": false, "error": "File not found: ..."}
```

### `yoitsu pause` / `yoitsu resume`

Control trenni job dispatch.

```bash
uv run yoitsu pause   # Stop dispatching new jobs (running jobs continue)
uv run yoitsu resume  # Resume dispatching

# Output: {"ok": true}
# Errors: {"ok": false, "error": "trenni returned 409: already paused"}
```

### `yoitsu logs`

Print last N lines from service logs (plain text, not JSON).

```bash
uv run yoitsu logs --service SERVICE [--lines N]

# Options:
#   --service  pasloe or trenni (required)
#   --lines    Number of lines (default: 50)

# Output: (plain text log lines)
```
